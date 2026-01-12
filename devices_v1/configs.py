SYSTEM_USER="fsadmin"

REDIS_HOST = "localhost"
REDIS_PORT = 6379

LOKI_URL='http://localhost:3100/loki/api/v1/push'

# Websocket configuration
WS_URL = "ws://localhost:8005/ws"

# Device ports
COIN_ACCEPTOR_PORT = "/dev/smart_hopper"
# Coin mappings
COIN_VALUE_MAP = {
    1375731712: 1,  # 1 ruble
    1375731713: 5,  # 5 rubles
    1375731715: 10  # 10 rubles
}
# SSP configuration
SSP_CONFIG = {
    'id': 0x10,
    'timeout': 5000,
    'encryptAllCommand': True,
    'fixedKey': '0123456701234567'
}
PORT_OPTIONS = {
    'baudrate': 9600,
    'bytesize': 8,
    'stopbits': 2,
    'parity': 'N',
    'timeout': 3.0
}


class BillAcceptorConfig:
    BILL_ACCEPTOR_PORT: str = "/dev/ttyS0"

    BILL_CODES_V2: dict[bytes, int] = {
        b'\x07': 500000,
        b'\x0d': 200000,
        b'\x06': 100000,
        b'\x05': 50000, # ?
        b'\x0c': 20000,
        b'\x04': 10000,
        b'\x02': 1000,

    }
    BILL_CODES_V1: dict[bytes, int] = {
        b'\x06': 100000,
        b'\x05': 50000,
        b'\x04': 20000,
        b'\x03': 10000,
        b'\x02': 5000,
    }

    # Device command constants
    CMD_RESET_DEVICE: bytes = bytes([0x02, 0x03, 0x06, 0x30, 0x41, 0xB3])
    # CMD_ACCEPT_ALL_BILLS: bytes = bytes([0x02, 0x03, 0x0C, 0x34, 0x00, 0x30, 0xFC, 0x00, 0x00, 0x00, 0xD9, 0x38])
    CMD_ACCEPT_ALL_BILLS: bytes = bytes([0x02, 0x03, 0x0C, 0x34, 0x00, 0x30, 0xFC, 0x00, 0x00, 0x00])
    CMD_PULL_DEVICE: bytes = b'\x02\x03\x06\x33\xDA\x81'
    CMD_ACKNOWLEDGE_BILL: bytes = bytes([0x02, 0x03, 0x06, 0x00, 0xC2, 0x82])
    CMD_PULL: bytes = bytes([0x02, 0x03, 0x06, 0x33])
    CMD_DISABLE: bytes = bytes([0x02, 0x03, 0x0C, 0x34, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    CMD_STACK: bytes = bytes([0x02, 0x03, 0x06, 0x35])

    # Protocol constants
    BILL_ACCEPTED_CODE: int = 0x81
    CRC_POLYNOMIAL: int = 0x08408

    # CCNET Protocol States Dictionary
    STATES: dict[int, str] = {
        0x10: "POWER UP",
        0x11: "POWER UP WITH BILL IN VALIDATOR",
        0x12: "POWER UP WITH BILL IN STACKER",
        0x13: "INITIALIZE",
        0x14: "IDLING",
        0x15: "ACCEPTING",
        0x17: "STACKING",
        0x18: "RETURNING",
        0x19: "UNIT DISABLED",
        0x1A: "HOLDING",
        0x1B: "DEVICE BUSY",
        0x1C: "REJECTING",
        0x41: "DROP CASSETTE FULL",
        0x42: "DROP CASSETTE OUT OF POSITION",
        0x43: "VALIDATOR JAMMED",
        0x44: "DROP CASSETTE JAMMED",
        0x45: "CHEATED",
        0x46: "PAUSE",
        0x47: "GENERIC FAILURE",
        0x80: "ESCROW POSITION",
        0x81: "BILL STACKED",
        0x82: "BILL RETURNED",
    }

BILL_DISPENSER_PORT = '/dev/ttyS1'
MIN_BOX_COUNT = 50

bill_acceptor_config = BillAcceptorConfig()
