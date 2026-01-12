"""
CCNET Protocol Constants and Enumerations.

Based on CCNET Protocol Description documentation.
All commands and states are defined as IntEnum for type safety.
"""

from enum import IntEnum
from typing import Final


# Protocol constants
SYNC_BYTE: Final[int] = 0x02
DEFAULT_DEVICE_ADDRESS: Final[int] = 0x03  # Bill Validator default address (page 12)
CRC_POLYNOMIAL: Final[int] = 0x08408  # CCITT polynomial (page 10)
MAX_PACKET_LENGTH: Final[int] = 250  # Maximum packet length
MIN_PACKET_LENGTH: Final[int] = 6  # Minimum packet length (SYNC+ADR+LNG+CMD+CRC)

# Timing constants (page 15)
POLL_INTERVAL_MS: Final[int] = 200  # Poll every 200ms
ACK_TIMEOUT_MS: Final[int] = 10  # ACK must be sent within 10ms
RESPONSE_TIMEOUT_S: Final[float] = 1.0  # Response timeout in seconds

# Buffer constants
FLUSH_BUFFER_SIZE: Final[int] = 100  # Bytes to read when flushing buffer
FLUSH_TIMEOUT_S: Final[float] = 0.1  # Timeout for buffer flush


class Command(IntEnum):
    """
    CCNET Protocol Commands (page 11).
    
    Commands sent from controller to peripheral device.
    """
    ACK = 0x00          # Acknowledgement
    RESET = 0x30        # Reset device
    GET_STATUS = 0x31   # Get status
    SET_SECURITY = 0x32 # Set security
    POLL = 0x33         # Poll device
    ENABLE_BILL_TYPES = 0x34  # Enable bill types
    STACK = 0x35        # Stack bill (accept)
    RETURN = 0x36       # Return bill
    IDENTIFICATION = 0x37     # Get identification
    HOLD = 0x38         # Hold bill in escrow
    SET_BARCODE_PARAMS = 0x39 # Set barcode parameters
    EXTRACT_BARCODE = 0x3A    # Extract barcode data
    GET_BILL_TABLE = 0x41     # Get bill table
    DOWNLOAD = 0x50     # Download firmware
    GET_CRC32 = 0x51    # Get CRC32 of firmware
    GET_DATASET_VERSION = 0x62  # Get dataset version
    NAK = 0xFF          # Negative acknowledgement


class DeviceState(IntEnum):
    """
    CCNET Bill Validator States (page 19, 38).
    
    States returned in response to POLL command.
    """
    # Power-up states
    POWER_UP = 0x10
    POWER_UP_WITH_BILL_IN_VALIDATOR = 0x11
    POWER_UP_WITH_BILL_IN_STACKER = 0x12
    
    # Initialization and idle states
    INITIALIZE = 0x13
    IDLING = 0x14
    ACCEPTING = 0x15
    
    # Operation states
    STACKING = 0x17
    RETURNING = 0x18
    UNIT_DISABLED = 0x19
    HOLDING = 0x1A
    DEVICE_BUSY = 0x1B
    REJECTING = 0x1C
    
    # Error states
    DROP_CASSETTE_FULL = 0x41
    DROP_CASSETTE_OUT_OF_POSITION = 0x42
    VALIDATOR_JAMMED = 0x43
    DROP_CASSETTE_JAMMED = 0x44
    CHEATED = 0x45
    PAUSE = 0x46
    GENERIC_FAILURE = 0x47
    
    # Bill position states (with data byte for bill code)
    ESCROW_POSITION = 0x80
    BILL_STACKED = 0x81
    BILL_RETURNED = 0x82


class RejectionReason(IntEnum):
    """
    Bill Rejection Reasons.
    
    Extended data for REJECTING state.
    """
    INSERTION = 0x60
    MAGNETIC = 0x61
    REMAINING_BILLS_IN_TRANSPORT = 0x62
    MULTIPLYING = 0x63
    CONVEYING = 0x64
    IDENTIFICATION1 = 0x65
    VERIFICATION = 0x66
    OPTIC = 0x67
    INHIBIT = 0x68
    CAPACITY = 0x69
    OPERATION = 0x6A
    LENGTH = 0x6C


class EventType(str):
    """
    Events emitted by the driver.
    
    Used for callback-based event system.
    """
    CONNECTED = "CONNECTED"
    DISCONNECTED = "DISCONNECTED"
    BILL_ESCROW = "BILL_ESCROW"
    BILL_STACKED = "BILL_STACKED"
    BILL_RETURNED = "BILL_RETURNED"
    BILL_REJECTED = "BILL_REJECTED"
    STATE_CHANGED = "STATE_CHANGED"
    ERROR = "ERROR"
    CASSETTE_FULL = "CASSETTE_FULL"
    CASSETTE_REMOVED = "CASSETTE_REMOVED"


# Bill denomination mapping for Creator C100-B20 (Russian Rubles in kopecks)
BILL_DENOMINATIONS: dict[int, int] = {
    0x02: 1000,       # 10 RUB
    0x03: 5000,       # 50 RUB (not always present)
    0x04: 10000,      # 100 RUB
    0x05: 50000,      # 500 RUB
    0x06: 100000,     # 1000 RUB
    0x07: 500000,     # 5000 RUB
    0x0c: 20000,      # 200 RUB
    0x0d: 200000,     # 2000 RUB
}


# State name mapping for logging
STATE_NAMES: dict[int, str] = {
    state.value: state.name for state in DeviceState
}


def get_state_name(state_code: int | None) -> str:
    """Get human-readable state name from state code."""
    if state_code is None:
        return "UNKNOWN"
    return STATE_NAMES.get(state_code, f"UNKNOWN(0x{state_code:02X})")


def get_bill_amount(bill_code: int | None) -> int:
    """Get bill amount in kopecks from bill code."""
    if bill_code is None:
        return 0
    return BILL_DENOMINATIONS.get(bill_code, 0)
