"""
Core module - Foundation layer with no external dependencies.

Contains:
- Exceptions
- Interfaces (Protocols)
- Value Objects
- Base types
"""

from .exceptions import (
    CashSystemError,
    DeviceError,
    DeviceConnectionError,
    DeviceTimeoutError,
    DeviceNotFoundError,
    PaymentError,
    PaymentInProgressError,
    InsufficientFundsError,
    RepositoryError,
    RedisConnectionError,
)
from .interfaces import (
    Device,
    DeviceType,
    PaymentDevice,
    DispenserDevice,
    AcceptorDevice,
    StateRepository,
    DeviceStateData,
)
from .value_objects import (
    Money,
    DeviceStatus,
    PaymentStatus,
    PaymentResult,
    DispensingResult,
)


__all__ = [
    # Exceptions
    "CashSystemError",
    "DeviceError",
    "DeviceConnectionError",
    "DeviceTimeoutError",
    "DeviceNotFoundError",
    "PaymentError",
    "PaymentInProgressError",
    "InsufficientFundsError",
    "RepositoryError",
    "RedisConnectionError",
    # Interfaces
    "Device",
    "DeviceType",
    "PaymentDevice",
    "DispenserDevice",
    "AcceptorDevice",
    "StateRepository",
    "DeviceStateData",
    # Value Objects
    "Money",
    "DeviceStatus",
    "PaymentStatus",
    "PaymentResult",
    "DispensingResult",
]
