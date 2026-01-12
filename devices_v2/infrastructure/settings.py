"""
Application settings using Pydantic.

Provides type-safe, validated configuration with environment variable support.
"""

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Final


# =============================================================================
# Configuration Classes
# =============================================================================


@dataclass(frozen=True)
class RedisSettings:
    """Redis connection settings."""

    host: str = "localhost"
    port: int = 6379
    decode_responses: bool = True


@dataclass(frozen=True)
class SerialPortSettings:
    """Serial port configuration."""

    baudrate: int = 9600
    bytesize: int = 8
    stopbits: int = 2
    parity: str = "N"
    timeout: float = 3.0


@dataclass(frozen=True)
class DevicePortSettings:
    """Device serial port paths."""

    coin_acceptor: str = "/dev/smart_hopper"
    bill_dispenser: str = "/dev/ttyS1"
    bill_acceptor: str = "/dev/ttyS0"
    cctalk_acceptor: str = "/dev/ttyUSB0"


@dataclass(frozen=True)
class ServiceSettings:
    """External service URLs."""

    loki_url: str = "http://localhost:3100/loki/api/v1/push"
    websocket_url: str = "ws://localhost:8005/ws"


@dataclass(frozen=True)
class PaymentSettings:
    """Payment system settings."""

    min_dispenser_box_count: int = 50
    command_channel: str = "payment_system_cash_commands"

    @property
    def response_channel(self) -> str:
        """Get response channel name."""
        return f"{self.command_channel}_response"


@dataclass(frozen=True)
class SSPSettings:
    """SSP (Secure Serial Protocol) device settings."""

    device_id: int = 0x10
    timeout: int = 5000
    encrypt_all_commands: bool = True
    fixed_key: str = "0123456701234567"
    polling_interval_ms: int = 300
    command_retries: int = 20


# =============================================================================
# Main Settings
# =============================================================================


@dataclass
class Settings:
    """
    Main application settings.

    Aggregates all configuration sections.
    """

    system_user: str = "fsadmin"
    redis: RedisSettings = field(default_factory=RedisSettings)
    serial: SerialPortSettings = field(default_factory=SerialPortSettings)
    ports: DevicePortSettings = field(default_factory=DevicePortSettings)
    services: ServiceSettings = field(default_factory=ServiceSettings)
    payment: PaymentSettings = field(default_factory=PaymentSettings)
    ssp: SSPSettings = field(default_factory=SSPSettings)


# =============================================================================
# Settings Singleton
# =============================================================================


_settings: Settings | None = None


def get_settings() -> Settings:
    """
    Get application settings singleton.

    Returns:
        Settings instance.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# =============================================================================
# Default Values (for backward compatibility)
# =============================================================================


DEFAULT_SETTINGS: Final[dict] = {
    "max_bill_count": {"key": "max_bill_count", "default": 1450},
    "bill_count": {"key": "bill_count", "default": 0},
    "upper_count": {"key": "bill_dispenser:upper_count", "default": 0},
    "lower_count": {"key": "bill_dispenser:lower_count", "default": 0},
    "upper_lvl": {"key": "bill_dispenser:upper_lvl", "default": 10000},
    "lower_lvl": {"key": "bill_dispenser:lower_lvl", "default": 5000},
}

AVAILABLE_DEVICES: Final[set[str]] = {
    "bill_acceptor",
    "bill_dispenser",
    "coin_dispenser",
    "coin_acceptor",
}
