"""
ccTalk Coin Acceptor Driver.

This module provides an asynchronous driver for coin acceptors
using the ccTalk protocol.
"""

import asyncio
from typing import Any, Final, Optional

import serial_asyncio

from configs import COIN_ACCEPTOR_PORT
from event_system import EventPublisher, EventType
from loggers import logger


# =============================================================================
# ccTalk Protocol Constants
# =============================================================================

# Coin slot to value mapping (value in kopecks)
CCTALK_COIN_VALUES: Final[dict[int, int]] = {
    10: 100,    # 1 ruble
    12: 200,    # 2 rubles
    14: 500,    # 5 rubles
    16: 1000,   # 10 rubles
}

DEVICE_ADDRESS: Final[int] = 2
HOST_ADDRESS: Final[int] = 1

# ccTalk Commands
CMD_RESET: Final[int] = 1
CMD_SIMPLE_POLL: Final[int] = 254
CMD_READ_BUFFERED_CREDIT: Final[int] = 229
CMD_MODIFY_INHIBIT_STATUS: Final[int] = 231

# Polling configuration
POLL_INTERVAL_S: Final[float] = 0.2
SERIAL_BAUDRATE: Final[int] = 9600
SERIAL_TIMEOUT: Final[float] = 0.2


class CcTalkAcceptor:
    """
    Asynchronous driver for ccTalk coin acceptors.

    This driver handles initialization, enabling/disabling coin acceptance,
    and polling for credit events from the coin acceptor.

    Attributes:
        port: Serial port path.
        event_publisher: Publisher for coin credit events.
    """

    def __init__(self, event_publisher: EventPublisher) -> None:
        """
        Initialize the ccTalk acceptor driver.

        Args:
            event_publisher: Publisher for device events.
        """
        self.event_publisher = event_publisher
        self.port: str = COIN_ACCEPTOR_PORT
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._is_polling: bool = False
        self._polling_task: Optional[asyncio.Task] = None
        self._last_event_counter: int = 0

    async def initialize(self) -> bool:
        """
        Initialize the ccTalk device.

        Opens the serial port, resets the device, and initializes
        the event counter.

        Returns:
            True if initialization successful.
        """
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self.port,
                baudrate=SERIAL_BAUDRATE,
                timeout=SERIAL_TIMEOUT,
            )
            logger.info(f"ccTalk coin acceptor: port {self.port} opened")

            # Reset device
            await self._send_command(CMD_RESET)
            await asyncio.sleep(0.5)
            logger.info("ccTalk coin acceptor: device reset")

            # Verify communication
            response = await self._send_command(CMD_SIMPLE_POLL)
            if response is None:
                logger.error("ccTalk coin acceptor: no response after reset")
                return False
            logger.info("ccTalk coin acceptor: device responding")

            # Initialize event counter
            initial_events = await self._send_command(CMD_READ_BUFFERED_CREDIT)
            if not initial_events:
                logger.error("ccTalk coin acceptor: failed to get initial event counter")
                return False
            self._last_event_counter = initial_events[0]
            logger.info(f"ccTalk coin acceptor: event counter initialized to {self._last_event_counter}")

            return True

        except Exception as e:
            logger.error(f"ccTalk coin acceptor initialization error: {e}")
            return False

    async def enable(self) -> None:
        """
        Enable coin acceptance and start polling.

        Enables all coin channels and starts the event polling loop.
        """
        if self._is_polling:
            logger.warning("ccTalk coin acceptor: polling already running")
            return

        try:
            # Enable all coin channels
            await self._send_command(CMD_MODIFY_INHIBIT_STATUS, [255, 255])
            logger.info("ccTalk coin acceptor: coin acceptance enabled")

            self._is_polling = True
            self._polling_task = asyncio.create_task(self._poll_events())
            logger.info("ccTalk coin acceptor: event polling started")

        except Exception as e:
            logger.error(f"Error enabling ccTalk coin acceptor: {e}")

    async def disable(self) -> None:
        """
        Disable coin acceptance and stop polling.

        Disables all coin channels and cancels the polling task.
        """
        if not self._is_polling:
            return

        try:
            # Disable all coin channels
            await self._send_command(CMD_MODIFY_INHIBIT_STATUS, [0, 0])
            logger.info("ccTalk coin acceptor: coin acceptance disabled")

            self._is_polling = False
            if self._polling_task:
                self._polling_task.cancel()
                try:
                    await self._polling_task
                except asyncio.CancelledError:
                    pass
            logger.info("ccTalk coin acceptor: event polling stopped")

        except Exception as e:
            logger.error(f"Error disabling ccTalk coin acceptor: {e}")

    async def _poll_events(self) -> None:
        """
        Continuous event polling loop.

        Polls the device for credit events and publishes them
        to the event queue.
        """
        while self._is_polling:
            try:
                events = await self._send_command(CMD_READ_BUFFERED_CREDIT)

                if events and len(events) > 0:
                    await self._process_events(events)

                await asyncio.sleep(POLL_INTERVAL_S)

            except asyncio.CancelledError:
                logger.info("ccTalk coin acceptor: polling task cancelled")
                break
            except Exception as e:
                logger.error(f"ccTalk polling error: {e}")
                await asyncio.sleep(1.0)  # Back off on error

    async def _process_events(self, events: list[int]) -> None:
        """
        Process buffered credit events.

        Args:
            events: Event buffer from the device.
        """
        current_event_counter = events[0]

        if current_event_counter == self._last_event_counter:
            return

        # Calculate number of new events
        num_events_by_counter = (current_event_counter - self._last_event_counter + 256) % 256
        num_events_in_buffer = (len(events) - 1) // 2
        events_to_process = min(num_events_by_counter, num_events_in_buffer)

        for i in range(events_to_process):
            event_index = 1 + (i * 2)
            if event_index + 1 >= len(events):
                continue

            coin_slot = events[event_index]
            status_code = events[event_index + 1]

            # Skip status-only events
            if coin_slot == 0:
                if status_code > 0:
                    logger.warning(f"ccTalk coin acceptor: status event (code: {status_code})")
                continue

            # Process coin credit
            if coin_slot in CCTALK_COIN_VALUES:
                coin_value = CCTALK_COIN_VALUES[coin_slot]
                logger.info(
                    f"ccTalk coin acceptor: coin from slot {coin_slot}, "
                    f"value {coin_value / 100} RUB"
                )

                await self.event_publisher.publish(
                    EventType.COIN_CREDIT,
                    value=coin_value,
                )

                # Re-enable coin acceptance to acknowledge event
                await self._send_command(CMD_MODIFY_INHIBIT_STATUS, [255, 255])
            else:
                logger.warning(f"ccTalk coin acceptor: unknown slot {coin_slot}")

        self._last_event_counter = current_event_counter

    def _calculate_checksum(self, data: list[int]) -> int:
        """
        Calculate ccTalk checksum.

        Args:
            data: Message data bytes.

        Returns:
            Checksum byte.
        """
        return (256 - (sum(data) % 256)) % 256

    async def _send_command(
        self,
        header: int,
        data: Optional[list[int]] = None,
    ) -> Optional[list[int]]:
        """
        Send a command and receive response.

        Args:
            header: Command header byte.
            data: Optional command data bytes.

        Returns:
            Response data bytes or None on error.
        """
        if data is None:
            data = []

        if self._writer is None or self._reader is None:
            logger.error("ccTalk: serial port not open")
            return None

        payload = [DEVICE_ADDRESS, len(data), HOST_ADDRESS, header] + data
        checksum = self._calculate_checksum(payload)
        message = bytes(payload + [checksum])

        self._writer.write(message)
        await self._writer.drain()

        await asyncio.sleep(0.1)  # Wait for device response

        response = await self._reader.read(255)
        return self._parse_response(response)

    def _parse_response(self, response: bytes) -> Optional[list[int]]:
        """
        Parse device response.

        Args:
            response: Raw response bytes.

        Returns:
            Parsed data bytes or None if invalid.
        """
        if not response:
            return None

        response_bytes = list(response)

        if len(response_bytes) < 5:
            return None

        payload = response_bytes[:-1]
        checksum = response_bytes[-1]

        if self._calculate_checksum(payload) != checksum:
            logger.warning(f"ccTalk: checksum mismatch: {response_bytes}")
            return None

        if response_bytes[0] != HOST_ADDRESS or response_bytes[2] != DEVICE_ADDRESS:
            logger.warning(f"ccTalk: response from wrong device: {response_bytes}")
            return None

        return response_bytes[4:-1]
