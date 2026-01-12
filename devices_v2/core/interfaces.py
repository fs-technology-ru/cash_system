"""
Interfaces (Protocols) for the cash system.

Defines contracts for devices, repositories, and services using
Python's Protocol for structural subtyping (duck typing with type hints).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional, Protocol, TypeVar, runtime_checkable


# =============================================================================
# Enums
# =============================================================================


class DeviceType(Enum):
    """Types of payment devices in the system."""

    BILL_ACCEPTOR = auto()
    BILL_DISPENSER = auto()
    COIN_ACCEPTOR = auto()
    COIN_DISPENSER = auto()


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class DeviceStateData:
    """Data class for device state information."""

    device_type: DeviceType
    device_name: str
    is_connected: bool = False
    is_enabled: bool = False
    is_busy: bool = False
    error_message: Optional[str] = None
    extra_data: dict[str, Any] = field(default_factory=dict)


# =============================================================================
# Device Interfaces
# =============================================================================


class Device(ABC):
    """
    Abstract base class for all payment devices.

    Provides common interface for device lifecycle management.
    """

    @property
    @abstractmethod
    def device_type(self) -> DeviceType:
        """Get the device type."""
        ...

    @property
    @abstractmethod
    def device_name(self) -> str:
        """Get the device name."""
        ...

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Check if device is connected."""
        ...

    @abstractmethod
    async def connect(self) -> bool:
        """
        Connect to the device.

        Returns:
            True if connection successful.
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the device."""
        ...

    @abstractmethod
    async def get_status(self) -> DeviceStateData:
        """
        Get current device status.

        Returns:
            Device state data.
        """
        ...


@runtime_checkable
class AcceptorDevice(Protocol):
    """Protocol for devices that accept cash (bills/coins)."""

    async def enable_accepting(self) -> None:
        """Enable cash acceptance."""
        ...

    async def disable_accepting(self) -> None:
        """Disable cash acceptance."""
        ...

    @property
    def is_accepting(self) -> bool:
        """Check if device is accepting cash."""
        ...


@runtime_checkable
class DispenserDevice(Protocol):
    """Protocol for devices that dispense cash (bills/coins)."""

    async def dispense(self, amount: int) -> int:
        """
        Dispense the specified amount.

        Args:
            amount: Amount to dispense in kopecks.

        Returns:
            Actual amount dispensed.
        """
        ...

    async def get_available_amount(self) -> int:
        """
        Get total available amount for dispensing.

        Returns:
            Available amount in kopecks.
        """
        ...


class PaymentDevice(Device):
    """Base class for payment devices with event callback support."""

    @abstractmethod
    def set_event_callback(self, callback: Any) -> None:
        """
        Set callback for device events.

        Args:
            callback: Async callback function for events.
        """
        ...


# =============================================================================
# Repository Interfaces
# =============================================================================


T = TypeVar("T")


@runtime_checkable
class StateRepository(Protocol):
    """Protocol for state persistence repositories."""

    async def get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        ...

    async def set(self, key: str, value: Any) -> None:
        """Set a key-value pair."""
        ...

    async def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer value by key."""
        ...

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment a value by the specified amount."""
        ...

    async def get_set_members(self, key: str) -> set[str]:
        """Get all members of a set."""
        ...

    async def add_to_set(self, key: str, *values: str) -> None:
        """Add values to a set."""
        ...


# =============================================================================
# Event Handler Interface
# =============================================================================


@runtime_checkable
class EventHandler(Protocol):
    """Protocol for event handlers."""

    async def handle(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Handle an event.

        Args:
            event_type: Type of event.
            data: Event data.
        """
        ...


# =============================================================================
# Service Interfaces
# =============================================================================


@runtime_checkable
class PaymentService(Protocol):
    """Protocol for payment services."""

    async def start_payment(self, amount: int) -> dict[str, Any]:
        """Start accepting payment for the specified amount."""
        ...

    async def stop_payment(self) -> dict[str, Any]:
        """Stop the current payment."""
        ...

    async def dispense_change(self, amount: int) -> dict[str, Any]:
        """Dispense change for the specified amount."""
        ...

    @property
    def is_payment_in_progress(self) -> bool:
        """Check if a payment is in progress."""
        ...
