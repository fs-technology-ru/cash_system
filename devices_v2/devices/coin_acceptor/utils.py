import os
import struct
import random
import json
from typing import Dict, List, Union, Optional, Any, Tuple
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from loggers import logger

# Constants
STX = 0x7f
STEX = 0x7e
CRC_SSP_SEED = 0xffff
CRC_SSP_POLY = 0x8005

# Load static data
with open('static/status_desc.json', 'r') as f:
    status_desc = json.load(f)

with open('static/unit_type.json', 'r') as f:
    unit_type = json.load(f)

with open('static/reject_note.json', 'r') as f:
    reject_note = json.load(f)

with open('static/commands.json', 'r') as f:
    command_list = json.load(f)


def abs_big_int(n: int) -> int:
    """Returns the absolute value of an integer."""
    return abs(n)


def encrypt(key: bytes, data: bytes) -> bytes:
    """
    Encrypts data using AES encryption with ECB mode.

    Args:
        key: The encryption key
        data: The data to encrypt

    Returns:
        Encrypted data
    """
    if not isinstance(key, bytes):
        raise TypeError("Key must be bytes")
    if not isinstance(data, bytes):
        raise TypeError("Data must be bytes")

    # Create cipher using ECB mode - NO padding should be done here
    # The data should ALREADY be a multiple of 16 bytes
    cipher = AES.new(key, AES.MODE_ECB)

    # Verify data length is multiple of 16 bytes
    if len(data) % 16 != 0:
        raise ValueError(f"Data length ({len(data)}) must be a multiple of 16 bytes in ECB mode")

    # Encrypt the data without padding
    return cipher.encrypt(data)




def decrypt(key: bytes, data: bytes) -> bytes:
    """
    Decrypts data using AES decryption with ECB mode without padding.

    Args:
        key: The decryption key
        data: The data to decrypt

    Returns:
        Decrypted data
    """
    if not isinstance(key, bytes):
        raise TypeError("Key must be bytes")
    if not isinstance(data, bytes):
        raise TypeError("Data must be bytes")

    # Create cipher using ECB mode with NO padding
    cipher = AES.new(key, AES.MODE_ECB)

    # Decrypt without unpadding - crucial fix!
    return cipher.decrypt(data)


def read_bytes_from_buffer(buffer: bytes, start_index: int, length: int) -> bytes:
    """
    Reads bytes from a buffer starting from the specified index with given length.

    Args:
        buffer: The buffer to read from
        start_index: The starting index
        length: Number of bytes to read

    Returns:
        The extracted bytes
    """
    if not isinstance(buffer, bytes):
        raise TypeError("Buffer must be bytes")
    if start_index < 0 or start_index >= len(buffer):
        raise IndexError("Invalid start index")
    if length < 0 or start_index + length > len(buffer):
        raise IndexError("Invalid length or exceeds buffer size")

    return buffer[start_index:start_index + length]


def random_int(min_val: int, max_val: int) -> int:
    """
    Generates a random integer between min and max values.

    Args:
        min_val: Minimum value (inclusive)
        max_val: Maximum value (exclusive)

    Returns:
        Random integer
    """
    return random.randint(min_val, max_val - 1)


def crc16(source: bytes) -> bytes:
    """
    Calculate CRC16 checksum for the given source data.

    Args:
        source: Source data as bytes

    Returns:
        CRC16 checksum as bytes (2 bytes, little-endian)
    """
    crc = CRC_SSP_SEED
    for byte in source:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ CRC_SSP_POLY
            else:
                crc <<= 1
        crc &= 0xffff  # Keep CRC within 16-bit range

    return struct.pack('<H', crc)


def uint64_le(number: int) -> bytes:
    """
    Converts an unsigned 64-bit integer to little-endian bytes.

    Args:
        number: The integer to convert

    Returns:
        Bytes representation
    """
    if not isinstance(number, int) or number < 0 or number > 18446744073709551615:
        raise ValueError("Input must be an unsigned 64-bit integer")

    return struct.pack('<Q', number)


def uint32_le(number: int) -> bytes:
    """
    Converts an unsigned 32-bit integer to little-endian bytes.

    Args:
        number: The integer to convert

    Returns:
        Bytes representation
    """
    if not isinstance(number, int) or number < 0 or number > 4294967295:
        raise ValueError("Input must be an unsigned 32-bit integer")

    return struct.pack('<I', number)


def uint16_le(number: int) -> bytes:
    """
    Converts an unsigned 16-bit integer to little-endian bytes.

    Args:
        number: The integer to convert

    Returns:
        Bytes representation
    """
    if not isinstance(number, int) or number < 0 or number > 65535:
        raise ValueError("Input must be an unsigned 16-bit integer")

    return struct.pack('<H', number)

def args_to_byte(command: str, args: Dict = None, protocol_version: int = None) -> bytes:
    """
    Converts command arguments to byte representation.

    Args:
        command: Command name
        args: Command arguments
        protocol_version: Protocol version

    Returns:
        Byte representation of arguments
    """
    if args is None:
        return b''

    if command == 'SET_GENERATOR' or command == 'SET_MODULUS' or command == 'REQUEST_KEY_EXCHANGE':
        return uint64_le(args['key'])

    elif command == 'SET_DENOMINATION_ROUTE':
        route_buffer = bytes([0 if args['route'] == 'payout' else 1])
        value_buffer32 = uint32_le(args['value'])

        if protocol_version >= 6:
            country_code_buffer = args['country_code'].encode('ascii')
            return route_buffer + value_buffer32 + country_code_buffer

        value_hopper_buffer = uint16_le(args['value']) if args.get('isHopper', False) else value_buffer32
        return route_buffer + value_hopper_buffer

    elif command == 'SET_CHANNEL_INHIBITS':
        channels = args['channels']
        value = sum(bit << idx for idx, bit in enumerate(channels))
        return uint16_le(value)

    elif command == 'SET_COIN_MECH_GLOBAL_INHIBIT':
        return bytes([1 if args['enable'] else 0])

    elif command == 'SET_HOPPER_OPTIONS':
        value = 0
        if args.get('payMode'):
            value += 1
        if args.get('levelCheck'):
            value += 2
        if args.get('motorSpeed'):
            value += 4
        if args.get('cashBoxPayActive'):
            value += 8
        return uint16_le(value)

    elif command == 'GET_DENOMINATION_ROUTE':
        value_buffer32 = uint32_le(args['value'])

        if protocol_version >= 6:
            country_code_buffer = args['country_code'].encode('ascii')
            return value_buffer32 + country_code_buffer

        return uint16_le(args['value']) if args.get('isHopper', False) else value_buffer32

    elif command == 'SET_DENOMINATION_LEVEL':
        value_buffer = uint16_le(args['value'])

        if protocol_version >= 6:
            country_code_buffer = args['country_code'].encode('ascii')
            denomination_buffer32 = uint32_le(args['denomination'])
            return value_buffer + denomination_buffer32 + country_code_buffer

        denomination_buffer = uint16_le(args['denomination'])
        return value_buffer + denomination_buffer

    elif command == 'SET_REFILL_MODE':
        if args['mode'] == 'on':
            return bytes([0x05, 0x81, 0x10, 0x11, 0x01])
        elif args['mode'] == 'off':
            return bytes([0x05, 0x81, 0x10, 0x11, 0x00])
        elif args['mode'] == 'get':
            return bytes([0x05, 0x81, 0x10, 0x01])
        return b''

    elif command == 'HOST_PROTOCOL_VERSION':
        return bytes([args['version']])

    elif command == 'SET_BAR_CODE_CONFIGURATION':
        enable_values = {'none': 0, 'top': 1, 'bottom': 2, 'both': 3}
        enable = enable_values.get(args.get('enable', 'none'), 0)
        number = min(max(args.get('numChar', 6), 6), 24)
        return bytes([enable, 0x01, number])

    elif command == 'SET_BAR_CODE_INHIBIT_STATUS':
        byte = 0xff
        if not args.get('currencyRead', True):
            byte &= 0xfe
        if not args.get('barCode', True):
            byte &= 0xfd
        return bytes([byte])

    elif command == 'PAYOUT_AMOUNT':
        amount_buffer = uint32_le(args['amount'])

        if protocol_version >= 6:
            country_code_buffer = args['country_code'].encode('ascii')
            test_buffer = bytes([0x19 if args.get('test', False) else 0x58])
            return amount_buffer + country_code_buffer + test_buffer

        return amount_buffer

    elif command == 'GET_DENOMINATION_LEVEL':
        amount_buffer = uint32_le(args['amount'])

        if protocol_version >= 6:
            country_code_buffer = args['country_code'].encode('ascii')
            return amount_buffer + country_code_buffer

        return amount_buffer

    elif command == 'FLOAT_AMOUNT':
        min_buffer = uint16_le(args['min_possible_payout'])
        amount_buffer = uint32_le(args['amount'])

        if protocol_version >= 6:
            country_code_buffer = args['country_code'].encode('ascii')
            test_buffer = bytes([0x19 if args.get('test', False) else 0x58])
            return min_buffer + amount_buffer + country_code_buffer + test_buffer

        return min_buffer + amount_buffer

    elif command == 'SET_COIN_MECH_INHIBITS':
        inhibit_buffer = bytes([0x00 if args.get('inhibited', False) else 0x01])
        amount_buffer = uint16_le(args['amount'])

        if protocol_version >= 6:
            country_code_buffer = args['country_code'].encode('ascii')
            return inhibit_buffer + amount_buffer + country_code_buffer

        return inhibit_buffer + amount_buffer

    elif command == 'FLOAT_BY_DENOMINATION' or command == 'PAYOUT_BY_DENOMINATION':
        value_list = args['value']
        buffers = [bytes([len(value_list)])]

        for item in value_list:
            count_buffer = uint16_le(item['number'])
            denom_buffer = uint32_le(item['denomination'])
            country_buffer = item['country_code'].encode('ascii')
            buffers.extend([count_buffer, denom_buffer, country_buffer])

        test_buffer = bytes([0x19 if args.get('test', False) else 0x58])
        buffers.append(test_buffer)

        return b''.join(buffers)

    elif command == 'SET_VALUE_REPORTING_TYPE':
        return bytes([0x01 if args.get('reportBy') == 'channel' else 0x00])

    elif command == 'SET_BAUD_RATE':
        baud_values = {9600: 0, 38400: 1, 115200: 2}
        baudrate = baud_values.get(args.get('baudrate', 9600), 0)
        reset_value = 0 if args.get('reset_to_default_on_reset', False) else 1
        return bytes([baudrate, reset_value])

    elif command == 'CONFIGURE_BEZEL':
        rgb_buffer = bytes.fromhex(args['RGB'])
        volatile_buffer = bytes([0 if args.get('volatile', False) else 1])
        return rgb_buffer + volatile_buffer

    elif command == 'ENABLE_PAYOUT_DEVICE':
        byte = 0
        if args.get('GIVE_VALUE_ON_STORED', False) or args.get('REQUIRE_FULL_STARTUP', False):
            byte += 1
        if args.get('NO_HOLD_NOTE_ON_PAYOUT', False) or args.get('OPTIMISE_FOR_PAYIN_SPEED', False):
            byte += 2
        return bytes([byte])

    elif command == 'SET_FIXED_ENCRYPTION_KEY':
        key_bytes = bytes.fromhex(args['fixedKey'])
        # Python equivalent of swap64 is to reverse the byte order
        return key_bytes[::-1]

    elif command == 'COIN_MECH_OPTIONS':
        return bytes([1 if args.get('ccTalk', False) else 0])

    # Default case for commands without arguments
    return b''



def stuff_buffer(input_buffer: bytes) -> bytes:
    """Stuff bytes without using loops."""
    if not input_buffer:
        return b''

    def stuff_recursive(buffer, index=0, result=bytearray()):
        if index >= len(buffer):
            return bytes(result)

        byte = buffer[index]
        result.append(byte)

        # If STX byte found, add duplicate
        if byte == STX:
            result.append(STX)

        return stuff_recursive(buffer, index+1, result)

    return stuff_recursive(input_buffer)


def extract_packet_data(buffer: bytes, encrypt_key: Optional[bytes], count: int) -> bytes:
    """
    Extracts data from a packet buffer.

    Args:
        buffer: Packet buffer
        encrypt_key: Encryption key (if any)
        count: Current count value

    Returns:
        Extracted data

    Raises:
        ValueError: If packet format is invalid or CRC check fails
    """
    if buffer[0] != STX:
        raise ValueError("Unknown response")

    buffer = buffer[1:]
    data_length = buffer[1]
    packet_data = buffer[2:2 + data_length]
    crc_data = buffer[:2 + data_length]
    received_crc = buffer[2 + data_length:4 + data_length]
    calculated_crc = crc16(crc_data)

    if received_crc != calculated_crc:
        raise ValueError("Wrong CRC16")

    extracted_data = packet_data

    if encrypt_key is not None and packet_data[0] == STEX:
        decrypted_data = decrypt(encrypt_key, bytes(packet_data[1:]))
        logger.debug(f"Decrypted: {decrypted_data.hex()}")

        e_length = decrypted_data[0]
        e_count = int.from_bytes(decrypted_data[1:5], byteorder='little')
        extracted_data = decrypted_data[5:5 + e_length]

        if e_count != count + 1:
            raise ValueError("Encrypted counter mismatch")

    return extracted_data


def generate_keys() -> Dict:
    """
    Generates cryptographic keys for a secure communication protocol.

    Returns:
        Dictionary containing generated keys
    """
    # Generate prime numbers for generator and modulus
    from sympy import randprime

    generator = randprime(2**15, 2**16)
    modulus = randprime(2**15, 2**16)

    # Swap if generator < modulus
    if generator < modulus:
        generator, modulus = modulus, generator

    # Generate random number for host
    host_random = random.randint(1, 2147483647)

    # Calculate host intermediate key
    host_inter = pow(generator, host_random, modulus)

    return {
        'generator': generator,
        'modulus': modulus,
        'hostRandom': host_random,
        'hostInter': host_inter
    }


def create_ssp_host_encryption_key(slave_inter_key_buffer, keys):
    """
    Creates a Secure Session Protocol (SSP) host encryption key.

    Args:
        slave_inter_key_buffer: Buffer containing slave inter key
        keys: Dictionary containing fixedKey, hostRandom, and modulus

    Returns:
        Dictionary containing slaveInterKey, key, and encryptKey
    """
    try:
        # Extract components from keys dictionary
        fixed_key = keys['fixedKey']
        host_random = keys['hostRandom']
        modulus = keys['modulus']

        # Convert buffer to integer properly - crucial fix
        if isinstance(slave_inter_key_buffer, list):
            # Handle case where it's a list of integers
            slave_inter_key_buffer = bytes(slave_inter_key_buffer)

        # Ensure we have at least 8 bytes for a 64-bit integer
        if len(slave_inter_key_buffer) < 8:
            # Pad with zeros if needed
            slave_inter_key_buffer = slave_inter_key_buffer.ljust(8, b'\x00')

        # Read as 64-bit little endian integer
        slave_inter_key = int.from_bytes(slave_inter_key_buffer, byteorder='little')

        # Calculate key using modular exponentiation
        key = pow(slave_inter_key, host_random, modulus)

        # Prepare fixed key (equivalent to swap64 in JS)
        fixed_key_bytes = bytes.fromhex(fixed_key)[::-1]

        # Combine for final encryption key
        encrypt_key = fixed_key_bytes + struct.pack('<Q', key)

        return {
            'slaveInterKey': slave_inter_key,
            'key': key,
            'encryptKey': encrypt_key
        }
    except Exception as e:
        raise Exception(f"Key exchange error: {str(e)}")



def get_packet(command_code: int, arg_bytes: bytes, sequence_byte: int,
               encrypt_key: Optional[bytes] = None, e_count: int = 0) -> bytes:
    """Constructs a packet for SSP communication."""

    if encrypt_key is not None:
        # Prepare encryption counter
        e_count_bytes = uint32_le(e_count)

        # Calculate padding to make data multiple of 16 bytes
        # Critical fix: 7 = 1 (length byte) + 4 (counter) + 2 (CRC)
        padding_length = (16 - ((len(arg_bytes) + 1 + 7) % 16)) % 16
        padding_bytes = os.urandom(padding_length)

        # Prepare data for encryption with length, counter, command, args, padding
        plain_data = bytes([len(arg_bytes) + 1]) + e_count_bytes + bytes([command_code]) + arg_bytes + padding_bytes

        # Calculate CRC
        crc = crc16(plain_data)

        # Ensure the data to encrypt is exactly a multiple of 16 bytes
        to_encrypt = plain_data + crc
        assert len(to_encrypt) % 16 == 0, "Data not properly aligned to 16 bytes"

        # Encrypt the data
        encrypted_data = encrypt(encrypt_key, to_encrypt)

        # Final data with STEX marker
        data_to_send = bytes([STEX]) + encrypted_data
    else:
        # Non-encrypted data
        data_to_send = bytes([command_code]) + arg_bytes

    # Create packet with sequence
    packet = bytes([sequence_byte, len(data_to_send)]) + data_to_send
    packet_with_crc = packet + crc16(packet)

    # Return stuffed packet
    return bytes([STX]) + stuff_buffer(packet_with_crc)




def parse_data(data, current_command, protocol_version, device_unit_type):
    """
    Parse response data from SSP device based on the command.
    Args:
        data: Response data as bytes or list of bytes
        current_command: Current command string
        protocol_version: Protocol version number
        device_unit_type: Device unit type string
    Returns:
        Parsed data dictionary
    """
    # Ensure data is in bytes
    if isinstance(data, list):
        data = bytes(data)

    # Initialize result structure
    result = {
        'success': data[0] == 0xf0,
        'status': status_desc.get(str(data[0]), {}).get('name', 'UNDEFINED'),
        'command': current_command,
        'info': {},
    }

    if result['success']:
        # Skip status byte for response data
        data = data[1:]

        # Handle command-specific parsing
        if current_command == 'REQUEST_KEY_EXCHANGE':
            result['info']['key'] = list(data) if isinstance(data, bytes) else data

        elif current_command == 'GET_SERIAL_NUMBER':
            result['info']['serial_number'] = int.from_bytes(data[0:4], byteorder='big')

        elif current_command == 'SETUP_REQUEST':
            # Common for all device types
            unit_type_code = data[0]
            result['info']['unit_type'] = unit_type.get(str(unit_type_code), 'UNKNOWN')
            result['info']['firmware_version'] = f"{int(data[1:5].decode()) / 100:.2f}"
            result['info']['country_code'] = data[5:8].decode()

            # Check if it's a Smart Hopper
            is_smart_hopper = (unit_type_code == 3)
            if is_smart_hopper:
                # Smart Hopper specific
                result['info']['protocol_version'] = data[8]
                result['info']['number_of_coin_values'] = data[9]
                coin_values = []
                for i in range(result['info']['number_of_coin_values']):
                    coin_values.append(int.from_bytes(data[10+i*2:12+i*2], byteorder='little'))
                result['info']['coin_values'] = coin_values

                if result['info']['protocol_version'] >= 6:
                    country_codes = []
                    offset = 10 + result['info']['number_of_coin_values'] * 2
                    for i in range(result['info']['number_of_coin_values']):
                        country_codes.append(data[offset+i*3:offset+i*3+3].decode())
                    result['info']['country_codes_for_values'] = country_codes
            else:
                # Other devices (note validators)
                n = data[11]
                value_multiplier = int.from_bytes(data[8:11], byteorder='big')

                # Parse channel values
                channel_values = []
                for i in range(n):
                    channel_values.append(data[12+i] * value_multiplier)

                # Parse channel security info
                channel_security = []
                for i in range(n):
                    channel_security.append(data[12+n+i])

                # Basic info
                result['info'].update({
                    'channel_security': channel_security,
                    'channel_value': channel_values,
                    'number_of_channels': n,
                    'protocol_version': data[15+n*2],
                    'real_value_multiplier': int.from_bytes(data[12+n*2:15+n*2], byteorder='big'),
                    'value_multiplier': value_multiplier,
                })

                # Extended info for protocol version 6+
                if result['info']['protocol_version'] >= 6:
                    # Extract country codes
                    country_codes = []
                    offset = 16 + n * 2
                    for i in range(n):
                        country_codes.append(data[offset+i*3:offset+i*3+3].decode())

                    # Extract expanded values
                    expanded_values = []
                    offset = 16 + n * 5
                    for i in range(n):
                        expanded_values.append(int.from_bytes(data[offset+i*4:offset+i*4+4], byteorder='little'))

                    result['info'].update({
                        'expanded_channel_country_code': country_codes,
                        'expanded_channel_value': expanded_values,
                    })

        elif current_command == 'UNIT_DATA':
            unit_type_code = data[0]
            result['info'].update({
                'unit_type': unit_type.get(str(unit_type_code), 'UNKNOWN'),
                'firmware_version': f"{int(data[1:5].decode()) / 100:.2f}",
                'country_code': data[5:8].decode(),
                'value_multiplier': int.from_bytes(data[8:11], byteorder='big'),
                'protocol_version': data[11],
            })

        elif current_command == 'CHANNEL_VALUE_REQUEST':
            count = data[0]
            if protocol_version >= 6:
                # Extract channels
                channels = list(data[1:count+1])

                # Extract country codes
                country_codes = []
                for i in range(count):
                    country_codes.append(data[count+1+i*3:count+1+i*3+3].decode())

                # Extract values
                values = []
                for i in range(count):
                    values.append(int.from_bytes(data[count+1+count*3+i*4:count+1+count*3+i*4+4], byteorder='little'))

                result['info'].update({
                    'channel': channels,
                    'country_code': country_codes,
                    'value': values,
                })
            else:
                result['info']['channel'] = list(data[1:count+1])

        elif current_command == 'CHANNEL_SECURITY_DATA':
            levels = {
                0: 'not_implemented',
                1: 'low',
                2: 'std',
                3: 'high',
                4: 'inhibited',
            }
            result['info']['channel'] = {}
            for i in range(1, data[0] + 1):
                result['info']['channel'][i] = levels.get(data[i], 'unknown')

        elif current_command == 'CHANNEL_RE_TEACH_DATA':
            result['info']['source'] = list(data)

        elif current_command == 'LAST_REJECT_CODE':
            code = data[0]
            result['info'].update({
                'code': code,
                'name': reject_note.get(str(code), {}).get('name', 'UNKNOWN'),
                'description': reject_note.get(str(code), {}).get('description', 'Unknown reject reason'),
            })

        elif current_command in ['GET_FIRMWARE_VERSION', 'GET_DATASET_VERSION']:
            result['info']['version'] = data.decode()

        elif current_command == 'GET_ALL_LEVELS':
            result['info']['counter'] = {}
            for i in range(data[0]):
                denom_data = data[i*9+1:i*9+10]
                result['info']['counter'][i+1] = {
                    'denomination_level': int.from_bytes(denom_data[0:2], byteorder='little'),
                    'value': int.from_bytes(denom_data[2:6], byteorder='little'),
                    'country_code': denom_data[6:9].decode(),
                }

        elif current_command == 'GET_BAR_CODE_READER_CONFIGURATION':
            status_hardware = {
                0: 'none',
                1: 'Top reader fitted',
                2: 'Bottom reader fitted',
                3: 'both fitted'
            }
            status_enabled = {
                0: 'none',
                1: 'top',
                2: 'bottom',
                3: 'both'
            }
            status_format = {
                1: 'Interleaved 2 of 5'
            }
            result['info'] = {
                'bar_code_hardware_status': status_hardware.get(data[0], 'unknown'),
                'readers_enabled': status_enabled.get(data[1], 'unknown'),
                'bar_code_format': status_format.get(data[2], 'unknown'),
                'number_of_characters': data[3],
            }

        elif current_command == 'GET_BAR_CODE_INHIBIT_STATUS':
            # Convert byte to bit string and check specific bits
            bits = format(data[0], '08b')
            result['info'].update({
                'currency_read_enable': bits[7] == '0',
                'bar_code_enable': bits[6] == '0',
            })

        elif current_command == 'GET_BAR_CODE_DATA':
            status_map = {
                0: 'no_valid_data',
                1: 'ticket_in_escrow',
                2: 'ticket_stacked',
                3: 'ticket_rejected'
            }
            result['info'].update({
                'status': status_map.get(data[0], 'unknown'),
                'data': data[2:2+data[1]].decode(),
            })

        elif current_command == 'GET_DENOMINATION_LEVEL':
            result['info']['level'] = int.from_bytes(data, byteorder='little')

        elif current_command == 'GET_DENOMINATION_ROUTE':
            routes = {
                0: {'code': 0, 'value': 'Recycled and used for payouts'},
                1: {'code': 1, 'value': 'Detected denomination is routed to system cashbox'},
            }
            result['info'] = routes.get(data[0], {'code': data[0], 'value': 'Unknown route'})

        elif current_command == 'GET_MINIMUM_PAYOUT':
            result['info']['value'] = int.from_bytes(data, byteorder='little')

        elif current_command == 'GET_NOTE_POSITIONS':
            count = data[0]
            data = data[1:]
            result['info']['slot'] = {}
            if len(data) == count:
                # Simple mode
                for i in range(count):
                    result['info']['slot'][i+1] = {'channel': data[i]}
            else:
                # Extended mode
                for i in range(count):
                    result['info']['slot'][i+1] = {
                        'value': int.from_bytes(data[i*4:i*4+4], byteorder='little')
                    }

        elif current_command == 'GET_BUILD_REVISION':
            count = len(data) // 3
            result['info']['device'] = {}
            for i in range(count):
                result['info']['device'][i] = {
                    'unitType': unit_type.get(str(data[i*3]), 'UNKNOWN'),
                    'revision': int.from_bytes(data[i*3+1:i*3+3], byteorder='little'),
                }

        elif current_command == 'GET_COUNTERS':
            result['info'].update({
                'stacked': int.from_bytes(data[1:5], byteorder='little'),
                'stored': int.from_bytes(data[5:9], byteorder='little'),
                'dispensed': int.from_bytes(data[9:13], byteorder='little'),
                'transferred_from_store_to_stacker': int.from_bytes(data[13:17], byteorder='little'),
                'rejected': int.from_bytes(data[17:21], byteorder='little'),
            })

        elif current_command == 'GET_HOPPER_OPTIONS':
            value = int.from_bytes(data[0:2], byteorder='little')
            result['info'].update({
                'payMode': (value & 0x01) != 0,
                'levelCheck': (value & 0x02) != 0,
                'motorSpeed': (value & 0x04) != 0,
                'cashBoxPayAcive': (value & 0x08) != 0,
            })

        elif current_command in ['POLL', 'POLL_WITH_ACK']:
            result['info'] = []
            k = 0
            while k < len(data):
                code = data[k]
                status_info = status_desc.get(str(code), None)
                if not status_info:
                    k += 1
                    continue

                info = {
                    'code': code,
                    'name': status_info.get('name', 'UNKNOWN'),
                    'description': status_info.get('description', 'Unknown status'),
                }

                # Process based on event type
                if info['name'] in [
                    'SLAVE_RESET', 'NOTE_REJECTING', 'NOTE_REJECTED', 'NOTE_STACKING',
                    'NOTE_STACKED', 'SAFE_NOTE_JAM', 'UNSAFE_NOTE_JAM', 'DISABLED',
                    'STACKER_FULL', 'CASHBOX_REMOVED', 'CASHBOX_REPLACED',
                    'BAR_CODE_TICKET_VALIDATED', 'BAR_CODE_TICKET_ACKNOWLEDGE',
                    'NOTE_PATH_OPEN', 'CHANNEL_DISABLE', 'INITIALISING',
                    'COIN_MECH_JAMMED', 'COIN_MECH_RETURN_PRESSED', 'EMPTYING',
                    'EMPTIED', 'COIN_MECH_ERROR', 'NOTE_STORED_IN_PAYOUT',
                    'PAYOUT_OUT_OF_SERVICE', 'JAM_RECOVERY', 'NOTE_FLOAT_REMOVED',
                    'NOTE_FLOAT_ATTACHED', 'DEVICE_FULL'
                ]:
                    # Simple status events with no additional data
                    k += 1

                elif info['name'] in [
                    'READ_NOTE', 'CREDIT_NOTE', 'NOTE_CLEARED_FROM_FRONT',
                    'NOTE_CLEARED_TO_CASHBOX'
                ]:
                    # Events with channel number
                    info['channel'] = data[k+1]
                    k += 2

                elif info['name'] == 'FRAUD_ATTEMPT':
                    smart_device = device_unit_type in [unit_type.get('3'), unit_type.get('6')]
                    if protocol_version >= 6 and smart_device:
                        # Complex value structure for smart devices
                        length = data[k+1]
                        info['value'] = []
                        for i in range(length):
                            info['value'].append({
                                'value': int.from_bytes(data[k+2+i*7:k+6+i*7], byteorder='little'),
                                'country_code': data[k+6+i*7:k+9+i*7].decode(),
                            })
                        k += 2 + length * 7
                    elif smart_device:
                        # Simple value structure for smart devices
                        info['value'] = int.from_bytes(data[k+1:k+5], byteorder='little')
                        k += 5
                    else:
                        # Channel only for non-smart devices
                        info['channel'] = data[k+1]
                        k += 2

                elif info['name'] in [
                    'DISPENSING', 'DISPENSED', 'JAMMED', 'HALTED', 'FLOATING',
                    'FLOATED', 'TIME_OUT', 'CASHBOX_PAID', 'COIN_CREDIT',
                    'SMART_EMPTYING', 'SMART_EMPTIED'
                ]:
                    # Value-reporting events
                    if protocol_version >= 6:
                        length = data[k+1]
                        info['value'] = []
                        for i in range(length):
                            info['value'].append({
                                'value': int.from_bytes(data[k+2+i*7:k+6+i*7], byteorder='little'),
                                'country_code': data[k+6+i*7:k+9+i*7].decode(),
                            })
                        k += 2 + length * 7
                    else:
                        info['value'] = int.from_bytes(data[k+1:k+5], byteorder='little')
                        k += 5

                elif info['name'] in ['INCOMPLETE_PAYOUT', 'INCOMPLETE_FLOAT']:
                    # Payout status events with actual/requested values
                    if protocol_version >= 6:
                        length = data[k+1]
                        info['value'] = []
                        for i in range(length):
                            info['value'].append({
                                'actual': int.from_bytes(data[k+2+i*11:k+6+i*11], byteorder='little'),
                                'requested': int.from_bytes(data[k+6+i*11:k+10+i*11], byteorder='little'),
                                'country_code': data[k+10+i*11:k+13+i*11].decode(),
                            })
                        k += 2 + length * 11
                    else:
                        info.update({
                            'actual': int.from_bytes(data[k+1:k+5], byteorder='little'),
                            'requested': int.from_bytes(data[k+5:k+9], byteorder='little'),
                        })
                        k += 9

                elif info['name'] == 'ERROR_DURING_PAYOUT':
                    errors = {
                        0x00: 'Note not being correctly detected as it is routed',
                        0x01: 'Note jammed in transport',
                    }
                    if protocol_version >= 7:
                        length = data[k+1]
                        info['value'] = []
                        for i in range(length):
                            info['value'].append({
                                'value': int.from_bytes(data[k+2+i*7:k+6+i*7], byteorder='little'),
                                'country_code': data[k+6+i*7:k+9+i*7].decode(),
                            })
                        info['error'] = errors.get(data[k+2+length*7], 'Unknown error')
                        k += 3 + length * 7
                    else:
                        info['error'] = errors.get(data[k+1], 'Unknown error')
                        k += 2

                elif info['name'] in ['NOTE_TRANSFERED_TO_STACKER', 'NOTE_DISPENSED_AT_POWER-UP']:
                    if protocol_version >= 6:
                        info['value'] = {
                            'value': int.from_bytes(data[k+1:k+5], byteorder='little'),
                            'country_code': data[k+5:k+8].decode(),
                        }
                        k += 8
                    else:
                        k += 1

                elif info['name'] in [
                    'NOTE_HELD_IN_BEZEL', 'NOTE_PAID_INTO_STACKER_AT_POWER-UP',
                    'NOTE_PAID_INTO_STORE_AT_POWER-UP'
                ]:
                    if protocol_version >= 8:
                        info['value'] = {
                            'value': int.from_bytes(data[k+1:k+5], byteorder='little'),
                            'country_code': data[k+5:k+8].decode(),
                        }
                        k += 8
                    else:
                        k += 1

                # Add processed event to info list
                result['info'].append(info)

        elif current_command == 'CASHBOX_PAYOUT_OPERATION_DATA':
            result['info'] = {'data': []}
            for i in range(data[0]):
                denom_data = data[i*9+1:i*9+10]
                result['info']['data'].append({
                    'quantity': int.from_bytes(denom_data[0:2], byteorder='little'),
                    'value': int.from_bytes(denom_data[2:6], byteorder='little'),
                    'country_code': denom_data[6:9].decode(),
                })

        elif current_command == 'SET_REFILL_MODE' and len(data) == 1:
            result['info'] = {
                'enabled': data[0] == 0x01,
            }

        # Handle error conditions with specific command details
        elif result['status'] == 'COMMAND_CANNOT_BE_PROCESSED':
            if current_command == 'ENABLE_PAYOUT_DEVICE' and len(data) > 1:
                result['info']['errorCode'] = data[1]
                error_messages = {
                    1: 'No device connected',
                    2: 'Invalid currency detected',
                    3: 'Device busy',
                    4: 'Empty only (Note float only)',
                    5: 'Device error',
                }
                result['info']['error'] = error_messages.get(data[1], 'Unknown error')

            elif current_command in ['PAYOUT_BY_DENOMINATION', 'FLOAT_AMOUNT', 'PAYOUT_AMOUNT'] and len(data) > 1:
                result['info']['errorCode'] = data[1]
                error_messages = {
                    0: 'Not enough value in device',
                    1: 'Cannot pay exact amount',
                    3: 'Device busy',
                    4: 'Device disabled',
                }
                result['info']['error'] = error_messages.get(data[1], 'Unknown error')

            elif current_command in ['SET_VALUE_REPORTING_TYPE', 'GET_DENOMINATION_ROUTE', 'SET_DENOMINATION_ROUTE'] and len(data) > 1:
                result['info']['errorCode'] = data[1]
                error_messages = {
                    1: 'No payout connected',
                    2: 'Invalid currency detected',
                    3: 'Payout device error',
                }
                result['info']['error'] = error_messages.get(data[1], 'Unknown error')

            elif current_command == 'FLOAT_BY_DENOMINATION' and len(data) > 1:
                result['info']['errorCode'] = data[1]
                error_messages = {
                    0: 'Not enough value in device',
                    1: 'Cannot pay exact amount',
                    3: 'Device busy',
                    4: 'Device disabled',
                }
                result['info']['error'] = error_messages.get(data[1], 'Unknown error')

            elif current_command in ['STACK_NOTE', 'PAYOUT_NOTE'] and len(data) > 1:
                result['info']['errorCode'] = data[1]
                error_messages = {
                    1: 'Note float unit not connected',
                    2: 'Note float empty',
                    3: 'Note float busy',
                    4: 'Note float disabled',
                }
                result['info']['error'] = error_messages.get(data[1], 'Unknown error')

            elif current_command == 'GET_NOTE_POSITIONS' and len(data) > 1:
                result['info']['errorCode'] = data[1]
                if data[1] == 2:
                    result['info']['error'] = 'Invalid currency'

    return result

