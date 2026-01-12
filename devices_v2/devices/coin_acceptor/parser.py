from typing import Optional, List, Dict, Tuple, Any
from loggers import logger

# Constants
SSP_STX = 0x7f

class SSPParser:
    def __init__(self):
        """Initialize the parser."""
        self.reset()

    def reset(self):
        """Reset parser state."""
        self.state = {
            'counter': 0,
            'check_stuff': 0,
            'packet_length': 0,
            'buffer': bytearray()
        }

    def parse(self, chunk: bytes) -> List[bytes]:
        """Parse a chunk of data using recursion instead of loops."""
        if not chunk:
            return []

        def process_byte(byte: int, state: Dict, packets: List[bytes]) -> Tuple[Dict, List[bytes]]:
            """Process a single byte and return updated state and packets."""
            new_state = state.copy()
            new_packets = packets.copy()

            if byte == SSP_STX and state['counter'] == 0:
                # Packet start
                new_state['buffer'] = bytearray([byte])
                new_state['counter'] = 1
            elif byte == SSP_STX and state['counter'] == 1:
                # Reset if started from stuffed byte
                new_state = {
                    'counter': 0,
                    'check_stuff': 0,
                    'packet_length': 0,
                    'buffer': bytearray()
                }
            else:
                # Handle packet content
                if state['check_stuff'] == 1:
                    if byte != SSP_STX:
                        new_state['buffer'] = bytearray([SSP_STX, byte])
                        new_state['counter'] = 2
                    else:
                        new_state['buffer'].append(byte)
                        new_state['counter'] += 1
                    new_state['check_stuff'] = 0
                else:
                    if byte == SSP_STX:
                        new_state['check_stuff'] = 1
                    else:
                        new_state['buffer'].append(byte)
                        new_state['counter'] += 1

            # Get packet length
            if new_state['counter'] == 3:
                new_state['packet_length'] = new_state['buffer'][2] + 5

            # Check if packet is complete
            if new_state['packet_length'] > 0 and len(new_state['buffer']) == new_state['packet_length']:
                new_packets.append(bytes(new_state['buffer']))
                new_state = {
                    'counter': 0,
                    'check_stuff': 0,
                    'packet_length': 0,
                    'buffer': bytearray()
                }

            return new_state, new_packets

        # Process the chunk with recursion instead of loops
        def process_chunk(remaining: bytes, state: Dict, packets: List[bytes]) -> List[bytes]:
            if not remaining:
                # Update parser state before returning
                self.state = state
                return packets

            byte = remaining[0]
            new_state, new_packets = process_byte(byte, state, packets)

            return process_chunk(remaining[1:], new_state, new_packets)

        return process_chunk(chunk, self.state, [])