import time
import threading
from typing import Dict, Optional
import serial
import asyncio
import json

from devices.coin_acceptor.utils import (
    args_to_byte, crc16, extract_packet_data, generate_keys,
    get_packet, parse_data, create_ssp_host_encryption_key
)
from devices.coin_acceptor.parser import SSPParser
from event_system import EventType
from configs import PORT_OPTIONS
from loggers import logger


# Load command list
with open('static/commands.json', 'r') as f:
    command_list = json.load(f)


class SSP:
    def __init__(self, event_publisher):
        # Initialize configuration
        self.config = {
            'encryptAllCommand': True,
            'id': 0x10,
            'commandRetries': 20,
            'pollingInterval': 300,
            'timeout': 5000,
            'fixedKey': '0123456701234567'
        }

        self.event_publisher = event_publisher

        # Initialize keys
        self.keys = {
            'encryptKey': None,
            'fixedKey': self.config['fixedKey'],
            'generator': None,
            'hostInter': None,
            'hostRandom': None,
            'key': None,
            'modulus': None,
            'slaveInterKey': None,
        }

        # Initialize state
        self.state = {
            'enabled': False,
            'polling': False,
            'processing': False,
        }

        # Initialize counters and sequence
        self.e_count = 0
        self.command_send_attempts = 0
        self.sequence = 0x80
        self.protocol_version = None
        self.unit_type = None

        # Serial port and parser
        self.port = None
        self.parser = SSPParser()

        # Initialize event handler mapping
        self.command_handlers = {
            'REQUEST_KEY_EXCHANGE': self._handle_key_exchange,
            'SETUP_REQUEST': self._handle_setup_request,
            'UNIT_DATA': self._handle_unit_data,
            'HOST_PROTOCOL_VERSION': self._handle_host_protocol,
        }

        # Threading
        self.poll_stop_event = threading.Event()
        self.data_available = threading.Event()
        self.data_buffer = []
        self.reader_stop_event = threading.Event()

        # Timers
        self.reader_timer = None
        self.poll_task = None

    def open(self, port: str, options: Dict = None) -> None:
        """Open a serial connection using timer-based reading."""
        port_options = PORT_OPTIONS.copy()
        if options:
            port_options.update(options)

        self.port = serial.Serial(port=port, **port_options)
        self.reader_stop_event.clear()
        self._schedule_read()

        # Direct event publisher call
        asyncio.run_coroutine_threadsafe(
            self.event_publisher.publish(EventType.OPEN),
            asyncio.get_event_loop()
        )

    def _schedule_read(self) -> None:
        """Schedule a single read operation."""
        if self.reader_stop_event.is_set():
            return

        try:
            self._read_once()
        finally:
            # Schedule next read
            self.reader_timer = threading.Timer(0.01, self._schedule_read)
            self.reader_timer.daemon = True
            self.reader_timer.start()

    def _read_once(self) -> None:
        """Perform a single read operation."""
        try:
            if self.port and self.port.is_open and self.port.in_waiting > 0:
                data = self.port.read(self.port.in_waiting)
                packets = self.parser.parse(data)

                # Process each packet
                list(map(lambda packet: self._process_packet(packet), packets))
        except Exception as e:
            logger.error(f"Error in reader: {e}")
            # Direct event publisher call
            # asyncio.run_coroutine_threadsafe(
            #     self.event_publisher.publish(EventType.ERROR, message=str(e)),
            #     asyncio.get_event_loop()
            # )

    def _process_packet(self, packet: bytes) -> None:
        """Process a single packet."""
        self.data_buffer.append(packet)
        self.data_available.set()

    async def close(self) -> None:
        """Close connection with proper cleanup."""
        try:
            if self.state['polling']:
                await self.poll(False)

            if self.state['enabled']:
                try:
                    await self.disable()
                except Exception as e:
                    pass
                    # Direct event publisher call
                    # await self.event_publisher.publish(EventType.ERROR, message=f"Error disabling device: {e}")

            if self.reader_timer:
                self.reader_stop_event.set()
                self.reader_timer.cancel()

            if self.port and self.port.is_open:
                self.port.close()

            # Direct event publisher call
            await self.event_publisher.publish(EventType.CLOSE)
        except Exception as e:
            pass
            # Direct event publisher call
            # await self.event_publisher.publish(EventType.ERROR, message=f"Error during close: {e}")

    def get_sequence(self) -> int:
        """Get the current sequence byte."""
        return self.config['id'] | self.sequence

    async def init_encryption(self) -> Dict:
        """Exchange encryption keys without loops."""
        # Generate new keys
        new_keys = generate_keys()

        # Reset counter and keys
        self.keys.update(new_keys)
        self.keys['encryptKey'] = None
        self.e_count = 0

        # Define key exchange commands
        commands = [
            {'command': 'SET_GENERATOR', 'args': {'key': self.keys['generator']}},
            {'command': 'SET_MODULUS', 'args': {'key': self.keys['modulus']}},
            {'command': 'REQUEST_KEY_EXCHANGE', 'args': {'key': self.keys['hostInter']}},
        ]

        # Use recursion instead of loop
        async def execute_commands(remaining, last_result=None):
            if not remaining:
                return last_result

            cmd = remaining[0]
            result = await self.command(cmd['command'], cmd['args'])

            if not result or not result['success']:
                raise Exception(f"Key exchange failed: {result}")

            return await execute_commands(remaining[1:], result)

        return await execute_commands(commands)

    def parse_packet_data(self, buffer: bytes, command: str) -> Dict:
        """Parse packet data with functional approach."""
        parsed_data = parse_data(buffer, command, self.protocol_version, self.unit_type)

        if parsed_data['success'] and command in self.command_handlers:
            self.command_handlers[command](parsed_data, buffer)

        return parsed_data

    def _handle_key_exchange(self, parsed_data, buffer):
        """Handle key exchange command."""
        try:
            keys = create_ssp_host_encryption_key(
                bytes(parsed_data['info']['key']),
                self.keys
            )

            self.keys.update(keys)
        except Exception as e:
            raise Exception(f"Key exchange error: {e}")

    def _handle_setup_request(self, parsed_data, buffer):
        """Handle setup request command."""
        self.protocol_version = parsed_data['info']['protocol_version']
        self.unit_type = parsed_data['info']['unit_type']

    def _handle_unit_data(self, parsed_data, buffer):
        """Handle unit data command."""
        self.unit_type = parsed_data['info']['unit_type']

    def _handle_host_protocol(self, parsed_data, buffer):
        """Handle host protocol command."""
        self.protocol_version = None

    async def enable(self) -> Dict:
        """Enable the device for accepting cash."""
        result = await self.command('ENABLE')

        if result['status'] == 'OK':
            self.state['enabled'] = True

            if not self.state['polling']:
                await self.poll(True)

        return result

    async def disable(self) -> Dict:
        """Disable the device for accepting cash."""
        if self.state['polling']:
            await self.poll(False)

        result = await self.command('DISABLE')

        if result['status'] == 'OK':
            self.state['enabled'] = False

        return result

    async def command(self, command: str, args: Dict = None) -> Dict:
        """Send a command to the device."""
        command = command.upper()

        # Validate command
        if command not in command_list:
            raise ValueError(f"Unknown command: {command}")

        # Check encryption requirements
        if command_list[command]['encrypted'] and self.keys['encryptKey'] is None:
            raise ValueError(f"Command requires encryption: {command}")

        # Check if already processing
        if self.state['processing']:
            raise ValueError("Already processing another command")

        # Handle SYNC command specially
        if command == 'SYNC':
            self.sequence = 0x80

        # Reset command attempts
        self.command_send_attempts = 0

        # Determine if encryption should be used
        is_encrypted = (self.keys['encryptKey'] is not None and
                        (command_list[command]['encrypted'] or self.config['encryptAllCommand']))

        # Prepare command data
        arg_bytes = args_to_byte(command, args, self.protocol_version)
        sequence = self.get_sequence()
        encryption_key = self.keys['encryptKey'] if is_encrypted else None

        # Generate packet
        buffer = get_packet(command_list[command]['code'], arg_bytes, sequence,
                           encryption_key, self.e_count)

        # Generate plain packet for debugging
        buffer_plain = buffer
        if is_encrypted:
            buffer_plain = get_packet(command_list[command]['code'], arg_bytes,
                                    sequence, None, self.e_count)

        # Send to device
        result = await self._send_to_device(command, buffer, buffer_plain)

        # Update sequence after response received
        self.sequence = 0x00 if self.sequence == 0x80 else 0x80

        # Check for success
        if not result['success']:
            raise Exception(f"Command failed: {result}")

        await asyncio.sleep(0.3)
        return result

    async def _send_to_device(self, command: str, tx_buffer: bytes, tx_buffer_plain: bytes) -> Dict:
        """Send data recursively instead of using a retry loop."""
        async def attempt_send(attempts_left):
            if attempts_left <= 0:
                return {
                    'success': False,
                    'error': f"Command failed after {self.config['commandRetries']} retries",
                    'reason': "Maximum retry attempts exceeded"
                }

            # Set processing state
            self.state['processing'] = True

            # Debug data
            debug_data = {
                'command': command,
                'tx': {
                    'createdAt': time.time(),
                    'encrypted': tx_buffer,
                    'plain': tx_buffer_plain,
                },
                'rx': {
                    'createdAt': None,
                    'encrypted': None,
                    'plain': None,
                }
            }

            try:
                # Clear previous data
                self.data_available.clear()
                self.data_buffer.clear()

                # Send command to device
                self.port.write(tx_buffer)
                self.command_send_attempts += 1

                # Wait for response with timeout
                if not self.data_available.wait(timeout=self.config['timeout']):
                    raise TimeoutError("Command timeout")

                # Get response data
                rx_buffer = self.data_buffer.pop(0)
                debug_data['rx']['createdAt'] = time.time()
                debug_data['rx']['encrypted'] = rx_buffer

                # Extract packet data
                data = extract_packet_data(rx_buffer, self.keys['encryptKey'], self.e_count)

                # Construct plain response for debugging
                debug_data['rx']['plain'] = bytes([rx_buffer[0], rx_buffer[1], len(data)]) + data + crc16([rx_buffer[1], len(data)] + list(data))

                # Check if sequence flag matches
                if tx_buffer[1] != rx_buffer[1]:
                    raise ValueError("Sequence flag mismatch")

                # Increment counter if encrypted command
                if self.keys['encryptKey'] and rx_buffer[3] == 0x7e:
                    self.e_count += 1

                # Parse and return data
                return self.parse_packet_data(data, command)
            except Exception as e:
                debug_data['rx']['createdAt'] = time.time()
                logger.error(f"Command error: {e}")

                # Retry recursively
                return await attempt_send(attempts_left - 1)
            finally:
                # Reset processing state
                self.state['processing'] = False
                # Direct event publisher call
                await self.event_publisher.publish('debug', data=debug_data)

        # Start recursive retry sequence
        return await attempt_send(self.config['commandRetries'])

    async def poll(self, status: Optional[bool] = None) -> Dict:
        """Poll the device for events using event-based approach."""
        # Handle wait for processing completion
        if self.state['processing']:
            await self._wait_for_processing_completion()

        # Start polling
        if status is True:
            if self.state['polling']:
                return  # Already polling

            self.state['polling'] = True
            self.poll_stop_event.clear()

            # Start polling with task
            self.poll_task = asyncio.create_task(self._poll_once_and_schedule())
            return

        # Stop polling
        elif status is False:
            if not self.state['polling']:
                return

            self.state['polling'] = False
            self.poll_stop_event.set()

            # Cancel task if running
            if self.poll_task and not self.poll_task.done():
                self.poll_task.cancel()

            return

        # Single poll
        else:
            try:
                result = await self.command('POLL')

                # Process events with functional approach
                # if result.get('info'):
                #     await self.event_publisher.publish(
                #         EventType.COIN_CREDIT,
                #         info=result.get('info')[0],
                #     )
                return result
            except Exception as e:
                # Direct event publisher call
                # await self.event_publisher.publish(EventType.ERROR, message=str(e))
                raise

    async def _wait_for_processing_completion(self):
        """Wait for processing to complete without loops."""
        future = asyncio.Future()

        async def check_processing():
            if not self.state['processing']:
                future.set_result(None)
            else:
                await asyncio.sleep(0.01)
                asyncio.create_task(check_processing())

        asyncio.create_task(check_processing())

        try:
            await asyncio.wait_for(future, timeout=2.0)
        except asyncio.TimeoutError:
            raise TimeoutError("Timeout waiting for command completion")

    async def _poll_once_and_schedule(self):
        """Execute one poll and schedule the next recursively."""
        if self.poll_stop_event.is_set() or not self.state['polling']:
            return

        try:
            start_time = time.time()
            result = await self.command('POLL')
            # ttt('RESULT', result.get('info'))

            # Process results with functional approach
            # if result.get('info'):
            #     await self.event_publisher.publish(
            #         EventType.COIN_CREDIT,
            #         info=result.get('info')[0],
            #     )

            # Calculate sleep time
            execution_time = (time.time() - start_time) * 1000
            sleep_time = max(0, self.config['pollingInterval'] - execution_time) / 1000

            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

            # Schedule next poll recursively if still polling
            if not self.poll_stop_event.is_set() and self.state['polling']:
                asyncio.create_task(self._poll_once_and_schedule())
        except Exception as e:
            self.state['polling'] = False
            # Direct event publisher call
            # await self.event_publisher.publish(EventType.ERROR, message=str(e))
