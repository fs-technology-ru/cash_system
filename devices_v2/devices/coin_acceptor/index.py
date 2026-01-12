"""
SSP (Secure Serial Protocol) Driver for coin hoppers/acceptors.

This module provides communication with ITL devices using the
Encrypted SSP protocol for coin dispensing and acceptance.
"""

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Final, Optional

import serial

from devices.coin_acceptor.utils import (
    args_to_byte,
    crc16,
    extract_packet_data,
    generate_keys,
    get_packet,
    parse_data,
    create_ssp_host_encryption_key,
)
from devices.coin_acceptor.parser import SSPParser
from event_system import EventPublisher, EventType
from configs import PORT_OPTIONS
from loggers import logger


# =============================================================================
# Load command definitions
# =============================================================================

STATIC_PATH = Path(__file__).parent.parent.parent / "static" / "commands.json"
with open(STATIC_PATH, "r") as f:
    command_list = json.load(f)


# =============================================================================
# Constants
# =============================================================================

DEFAULT_CONFIG: Final[dict[str, Any]] = {
    "encryptAllCommand": True,
    "id": 0x10,
    "commandRetries": 20,
    "pollingInterval": 300,
    "timeout": 5000,
    "fixedKey": "0123456701234567",
}


# =============================================================================
# SSP Driver
# =============================================================================

class SSP:
    """
    SSP (Secure Serial Protocol) driver for ITL devices.

    Supports encrypted communication with coin hoppers and acceptors.

    Attributes:
        port: Serial port instance.
        event_publisher: Publisher for device events.
    """

    def __init__(self, event_publisher: EventPublisher) -> None:
        """
        Initialize SSP driver.

        Args:
            event_publisher: Publisher for device events.
        """
        # Configuration
        self.config = DEFAULT_CONFIG.copy()
        self.event_publisher = event_publisher

        # Encryption keys
        self.keys: dict[str, Any] = {
            "encryptKey": None,
            "fixedKey": self.config["fixedKey"],
            "generator": None,
            "hostInter": None,
            "hostRandom": None,
            "key": None,
            "modulus": None,
            "slaveInterKey": None,
        }

        # Device state
        self.state = {
            "enabled": False,
            "polling": False,
            "processing": False,
        }

        # Counters and sequence
        self.e_count: int = 0
        self.command_send_attempts: int = 0
        self.sequence: int = 0x80
        self.protocol_version: Optional[int] = None
        self.unit_type: Optional[int] = None

        # Serial port and parser
        self.port: Optional[serial.Serial] = None
        self._parser = SSPParser()

        # Command handlers
        self._command_handlers: dict[str, Callable] = {
            "REQUEST_KEY_EXCHANGE": self._handle_key_exchange,
            "SETUP_REQUEST": self._handle_setup_request,
            "UNIT_DATA": self._handle_unit_data,
            "HOST_PROTOCOL_VERSION": self._handle_host_protocol,
        }

        # Threading
        self._poll_stop_event = threading.Event()
        self._data_available = threading.Event()
        self._data_buffer: list[bytes] = []
        self._reader_stop_event = threading.Event()
        self._reader_timer: Optional[threading.Timer] = None
        self._poll_task: Optional[asyncio.Task] = None

    def open(self, port: str, options: Optional[dict] = None) -> None:
        """
        Open serial connection.

        Args:
            port: Serial port path.
            options: Optional port configuration overrides.
        """
        port_options = PORT_OPTIONS.copy()
        if options:
            port_options.update(options)

        self.port = serial.Serial(port=port, **port_options)
        self._reader_stop_event.clear()
        self._schedule_read()

        # Publish open event
        asyncio.run_coroutine_threadsafe(
            self.event_publisher.publish(EventType.OPEN),
            asyncio.get_event_loop(),
        )

    def _schedule_read(self) -> None:
        """Schedule next read operation."""
        if self._reader_stop_event.is_set():
            return

        try:
            self._read_once()
        finally:
            self._reader_timer = threading.Timer(0.01, self._schedule_read)
            self._reader_timer.daemon = True
            self._reader_timer.start()

    def _read_once(self) -> None:
        """Perform single read operation."""
        try:
            if self.port and self.port.is_open and self.port.in_waiting > 0:
                data = self.port.read(self.port.in_waiting)
                packets = self._parser.parse(data)
                for packet in packets:
                    self._process_packet(packet)
        except Exception as e:
            logger.error(f"SSP reader error: {e}")

    def _process_packet(self, packet: bytes) -> None:
        """Process received packet."""
        self._data_buffer.append(packet)
        self._data_available.set()

    async def close(self) -> None:
        """Close connection with cleanup."""
        try:
            if self.state["polling"]:
                await self.poll(False)

            if self.state["enabled"]:
                try:
                    await self.disable()
                except Exception:
                    pass

            if self._reader_timer:
                self._reader_stop_event.set()
                self._reader_timer.cancel()

            if self.port and self.port.is_open:
                self.port.close()

            await self.event_publisher.publish(EventType.CLOSE)

        except Exception as e:
            logger.error(f"SSP close error: {e}")

    def get_sequence(self) -> int:
        """Get current sequence byte."""
        return self.config["id"] | self.sequence

    async def init_encryption(self) -> dict[str, Any]:
        """
        Initialize encryption key exchange.

        Returns:
            Result of key exchange operation.
        """
        # Generate new keys
        new_keys = generate_keys()
        self.keys.update(new_keys)
        self.keys["encryptKey"] = None
        self.e_count = 0

        # Key exchange command sequence
        commands = [
            {"command": "SET_GENERATOR", "args": {"key": self.keys["generator"]}},
            {"command": "SET_MODULUS", "args": {"key": self.keys["modulus"]}},
            {"command": "REQUEST_KEY_EXCHANGE", "args": {"key": self.keys["hostInter"]}},
        ]

        result = None
        for cmd in commands:
            result = await self.command(cmd["command"], cmd["args"])
            if not result or not result["success"]:
                raise Exception(f"Key exchange failed: {result}")

        return result

    def parse_packet_data(self, buffer: bytes, command: str) -> dict[str, Any]:
        """
        Parse packet data and invoke handlers.

        Args:
            buffer: Packet data bytes.
            command: Command name.

        Returns:
            Parsed data dictionary.
        """
        parsed_data = parse_data(buffer, command, self.protocol_version, self.unit_type)

        if parsed_data["success"] and command in self._command_handlers:
            self._command_handlers[command](parsed_data, buffer)

        return parsed_data

    def _handle_key_exchange(
        self,
        parsed_data: dict[str, Any],
        buffer: bytes,
    ) -> None:
        """Handle REQUEST_KEY_EXCHANGE response."""
        try:
            keys = create_ssp_host_encryption_key(
                bytes(parsed_data["info"]["key"]),
                self.keys,
            )
            self.keys.update(keys)
        except Exception as e:
            raise Exception(f"Key exchange error: {e}")

    def _handle_setup_request(
        self,
        parsed_data: dict[str, Any],
        buffer: bytes,
    ) -> None:
        """Handle SETUP_REQUEST response."""
        self.protocol_version = parsed_data["info"]["protocol_version"]
        self.unit_type = parsed_data["info"]["unit_type"]

    def _handle_unit_data(
        self,
        parsed_data: dict[str, Any],
        buffer: bytes,
    ) -> None:
        """Handle UNIT_DATA response."""
        self.unit_type = parsed_data["info"]["unit_type"]

    def _handle_host_protocol(
        self,
        parsed_data: dict[str, Any],
        buffer: bytes,
    ) -> None:
        """Handle HOST_PROTOCOL_VERSION response."""
        self.protocol_version = None

    async def enable(self) -> dict[str, Any]:
        """
        Enable the device for accepting cash.

        Returns:
            Command result.
        """
        result = await self.command("ENABLE")

        if result["status"] == "OK":
            self.state["enabled"] = True
            if not self.state["polling"]:
                await self.poll(True)

        return result

    async def disable(self) -> dict[str, Any]:
        """
        Disable the device.

        Returns:
            Command result.
        """
        if self.state["polling"]:
            await self.poll(False)

        result = await self.command("DISABLE")

        if result["status"] == "OK":
            self.state["enabled"] = False

        return result

    async def command(
        self,
        command: str,
        args: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """
        Send a command to the device.

        Args:
            command: Command name (e.g., 'POLL', 'ENABLE').
            args: Optional command arguments.

        Returns:
            Command result dictionary.
        """
        command = command.upper()

        # Validate command
        if command not in command_list:
            raise ValueError(f"Unknown command: {command}")

        # Check encryption requirements
        if command_list[command]["encrypted"] and self.keys["encryptKey"] is None:
            raise ValueError(f"Command requires encryption: {command}")

        # Check processing state
        if self.state["processing"]:
            raise ValueError("Already processing another command")

        # Handle SYNC command
        if command == "SYNC":
            self.sequence = 0x80

        # Reset command attempts
        self.command_send_attempts = 0

        # Determine encryption
        is_encrypted = (
            self.keys["encryptKey"] is not None
            and (command_list[command]["encrypted"] or self.config["encryptAllCommand"])
        )

        # Prepare command packet
        arg_bytes = args_to_byte(command, args, self.protocol_version)
        sequence = self.get_sequence()
        encryption_key = self.keys["encryptKey"] if is_encrypted else None

        buffer = get_packet(
            command_list[command]["code"],
            arg_bytes,
            sequence,
            encryption_key,
            self.e_count,
        )

        buffer_plain = buffer
        if is_encrypted:
            buffer_plain = get_packet(
                command_list[command]["code"],
                arg_bytes,
                sequence,
                None,
                self.e_count,
            )

        # Send command
        result = await self._send_to_device(command, buffer, buffer_plain)

        # Update sequence
        self.sequence = 0x00 if self.sequence == 0x80 else 0x80

        if not result["success"]:
            raise Exception(f"Command failed: {result}")

        await asyncio.sleep(0.3)
        return result

    async def _send_to_device(
        self,
        command: str,
        tx_buffer: bytes,
        tx_buffer_plain: bytes,
    ) -> dict[str, Any]:
        """
        Send data to device with retry logic.

        Args:
            command: Command name.
            tx_buffer: Encrypted packet.
            tx_buffer_plain: Plain packet for debugging.

        Returns:
            Response dictionary.
        """
        retries = self.config["commandRetries"]

        for attempt in range(retries):
            self.state["processing"] = True

            debug_data = {
                "command": command,
                "tx": {
                    "createdAt": time.time(),
                    "encrypted": tx_buffer,
                    "plain": tx_buffer_plain,
                },
                "rx": {
                    "createdAt": None,
                    "encrypted": None,
                    "plain": None,
                },
            }

            try:
                # Clear buffers
                self._data_available.clear()
                self._data_buffer.clear()

                # Send command
                self.port.write(tx_buffer)
                self.command_send_attempts += 1

                # Wait for response
                if not self._data_available.wait(timeout=self.config["timeout"]):
                    raise TimeoutError("Command timeout")

                # Get response
                rx_buffer = self._data_buffer.pop(0)
                debug_data["rx"]["createdAt"] = time.time()
                debug_data["rx"]["encrypted"] = rx_buffer

                # Extract packet data
                data = extract_packet_data(
                    rx_buffer,
                    self.keys["encryptKey"],
                    self.e_count,
                )

                # Construct plain response for debugging
                debug_data["rx"]["plain"] = (
                    bytes([rx_buffer[0], rx_buffer[1], len(data)])
                    + data
                    + crc16([rx_buffer[1], len(data)] + list(data))
                )

                # Validate sequence
                if tx_buffer[1] != rx_buffer[1]:
                    raise ValueError("Sequence flag mismatch")

                # Increment counter if encrypted
                if self.keys["encryptKey"] and rx_buffer[3] == 0x7E:
                    self.e_count += 1

                return self.parse_packet_data(data, command)

            except Exception as e:
                debug_data["rx"]["createdAt"] = time.time()
                logger.error(f"SSP command error: {e}")
                if attempt >= retries - 1:
                    return {
                        "success": False,
                        "error": f"Command failed after {retries} retries",
                        "reason": str(e),
                    }
            finally:
                self.state["processing"] = False
                await self.event_publisher.publish("debug", data=debug_data)

        return {
            "success": False,
            "error": "Maximum retries exceeded",
        }

    async def poll(self, status: Optional[bool] = None) -> Optional[dict[str, Any]]:
        """
        Poll device for events.

        Args:
            status: True to start polling, False to stop, None for single poll.

        Returns:
            Poll result for single poll, None otherwise.
        """
        # Wait for processing completion
        if self.state["processing"]:
            await self._wait_for_processing_completion()

        if status is True:
            if self.state["polling"]:
                return None

            self.state["polling"] = True
            self._poll_stop_event.clear()
            self._poll_task = asyncio.create_task(self._poll_loop())
            return None

        elif status is False:
            if not self.state["polling"]:
                return None

            self.state["polling"] = False
            self._poll_stop_event.set()

            if self._poll_task and not self._poll_task.done():
                self._poll_task.cancel()

            return None

        else:
            # Single poll
            return await self.command("POLL")

    async def _wait_for_processing_completion(self) -> None:
        """Wait for current command to complete."""
        timeout = 2.0
        start = time.time()

        while self.state["processing"]:
            if time.time() - start > timeout:
                raise TimeoutError("Timeout waiting for command completion")
            await asyncio.sleep(0.01)

    async def _poll_loop(self) -> None:
        """Continuous polling loop."""
        while not self._poll_stop_event.is_set() and self.state["polling"]:
            try:
                start_time = time.time()
                await self.command("POLL")

                # Calculate sleep time
                execution_time = (time.time() - start_time) * 1000
                sleep_time = max(0, self.config["pollingInterval"] - execution_time) / 1000

                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"SSP poll error: {e}")
                self.state["polling"] = False
                break
