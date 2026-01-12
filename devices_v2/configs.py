"""
Configuration module for the cash system.

This module provides centralized configuration for all devices and services,
including Redis, WebSocket, serial ports, and device-specific settings.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Final


# =============================================================================
# System Configuration
# =============================================================================

SYSTEM_USER: Final[str] = "fsadmin"


# =============================================================================
# Redis Configuration
# =============================================================================

REDIS_HOST: Final[str] = "localhost"
REDIS_PORT: Final[int] = 6379


# =============================================================================
# External Services Configuration
# =============================================================================

LOKI_URL: Final[str] = "http://localhost:3100/loki/api/v1/push"
WS_URL: Final[str] = "ws://localhost:8005/ws"


# =============================================================================
# Serial Port Configuration
# =============================================================================

COIN_ACCEPTOR_PORT: Final[str] = "/dev/smart_hopper"
BILL_DISPENSER_PORT: Final[str] = "/dev/ttyS1"


@dataclass(frozen=True)
class SerialPortOptions:
    """Configuration for serial port connections."""

    baudrate: int = 9600
    bytesize: int = 8
    stopbits: int = 2
    parity: str = "N"
    timeout: float = 3.0


PORT_OPTIONS: Final[dict[str, int | str | float]] = {
    "baudrate": 9600,
    "bytesize": 8,
    "stopbits": 2,
    "parity": "N",
    "timeout": 3.0,
}


# =============================================================================
# Coin Acceptor / Hopper Configuration
# =============================================================================

COIN_VALUE_MAP: Final[dict[int, int]] = {
    1375731712: 1,   # 1 ruble
    1375731713: 5,   # 5 rubles
    1375731715: 10,  # 10 rubles
}


@dataclass(frozen=True)
class SSPConfiguration:
    """Configuration for SSP (Secure Serial Protocol) devices."""

    device_id: int = 0x10
    timeout: int = 5000
    encrypt_all_commands: bool = True
    fixed_key: str = "0123456701234567"


SSP_CONFIG: Final[dict[str, int | bool | str]] = {
    "id": 0x10,
    "timeout": 5000,
    "encryptAllCommand": True,
    "fixedKey": "0123456701234567",
}


# =============================================================================
# Bill Dispenser Configuration
# =============================================================================

MIN_BOX_COUNT: Final[int] = 50


# =============================================================================
# CCNET Protocol States
# =============================================================================

class CCNETState(IntEnum):
    """CCNET protocol state codes."""

    POWER_UP = 0x10
    POWER_UP_WITH_BILL_IN_VALIDATOR = 0x11
    POWER_UP_WITH_BILL_IN_STACKER = 0x12
    INITIALIZE = 0x13
    IDLING = 0x14
    ACCEPTING = 0x15
    STACKING = 0x17
    RETURNING = 0x18
    UNIT_DISABLED = 0x19
    HOLDING = 0x1A
    DEVICE_BUSY = 0x1B
    REJECTING = 0x1C
    DROP_CASSETTE_FULL = 0x41
    DROP_CASSETTE_OUT_OF_POSITION = 0x42
    VALIDATOR_JAMMED = 0x43
    DROP_CASSETTE_JAMMED = 0x44
    CHEATED = 0x45
    PAUSE = 0x46
    GENERIC_FAILURE = 0x47
    ESCROW_POSITION = 0x80
    BILL_STACKED = 0x81
    BILL_RETURNED = 0x82


# =============================================================================
# Bill Acceptor Configuration
# =============================================================================

@dataclass
class BillAcceptorConfig:
    """Configuration for bill acceptor devices."""

    BILL_ACCEPTOR_PORT: str = "/dev/ttyS0"

    # Bill denomination mappings (byte code -> value in kopecks)
    BILL_CODES_V2: dict[bytes, int] = field(default_factory=lambda: {
        b"\x07": 500000,   # 5000 RUB
        b"\x0d": 200000,   # 2000 RUB
        b"\x06": 100000,   # 1000 RUB
        b"\x05": 50000,    # 500 RUB
        b"\x0c": 20000,    # 200 RUB
        b"\x04": 10000,    # 100 RUB
        b"\x02": 1000,     # 10 RUB
    })

    BILL_CODES_V1: dict[bytes, int] = field(default_factory=lambda: {
        b"\x06": 100000,   # 1000 RUB
        b"\x05": 50000,    # 500 RUB
        b"\x04": 20000,    # 200 RUB
        b"\x03": 10000,    # 100 RUB
        b"\x02": 5000,     # 50 RUB
    })

    # CCNET Protocol Commands
    CMD_RESET_DEVICE: bytes = field(
        default_factory=lambda: bytes([0x02, 0x03, 0x06, 0x30, 0x41, 0xB3])
    )
    CMD_ACCEPT_ALL_BILLS: bytes = field(
        default_factory=lambda: bytes([0x02, 0x03, 0x0C, 0x34, 0x00, 0x30, 0xFC, 0x00, 0x00, 0x00])
    )
    CMD_PULL_DEVICE: bytes = field(
        default_factory=lambda: b"\x02\x03\x06\x33\xDA\x81"
    )
    CMD_ACKNOWLEDGE_BILL: bytes = field(
        default_factory=lambda: bytes([0x02, 0x03, 0x06, 0x00, 0xC2, 0x82])
    )
    CMD_PULL: bytes = field(
        default_factory=lambda: bytes([0x02, 0x03, 0x06, 0x33])
    )
    CMD_DISABLE: bytes = field(
        default_factory=lambda: bytes([0x02, 0x03, 0x0C, 0x34, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    )
    CMD_STACK: bytes = field(
        default_factory=lambda: bytes([0x02, 0x03, 0x06, 0x35])
    )

    # Protocol constants
    BILL_ACCEPTED_CODE: int = 0x81
    CRC_POLYNOMIAL: int = 0x08408

    # CCNET Protocol States (for backward compatibility)
    STATES: dict[int, str] = field(default_factory=lambda: {
        state.value: state.name.replace("_", " ")
        for state in CCNETState
    })


# Global configuration instance
bill_acceptor_config = BillAcceptorConfig()
