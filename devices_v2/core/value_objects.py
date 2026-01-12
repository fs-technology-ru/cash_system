"""
Value Objects for the cash system.

Immutable objects that represent values in the domain.
Value objects are compared by value, not by identity.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Optional


# =============================================================================
# Enums
# =============================================================================


class PaymentStatus(Enum):
    """Status of a payment transaction."""

    IDLE = auto()
    PENDING = auto()
    ACCEPTING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


class DeviceHealthStatus(Enum):
    """Health status of a device."""

    HEALTHY = auto()
    DEGRADED = auto()
    UNHEALTHY = auto()
    UNKNOWN = auto()


# =============================================================================
# Money Value Object
# =============================================================================


@dataclass(frozen=True)
class Money:
    """
    Immutable value object representing monetary amounts.

    Internally stores amounts in kopecks (smallest unit) to avoid
    floating-point precision issues.

    Attributes:
        kopecks: Amount in kopecks.
    """

    kopecks: int = 0

    def __post_init__(self) -> None:
        """Validate the amount."""
        if self.kopecks < 0:
            raise ValueError("Amount cannot be negative")

    @classmethod
    def from_rubles(cls, rubles: float) -> "Money":
        """
        Create Money from rubles.

        Args:
            rubles: Amount in rubles.

        Returns:
            Money instance.
        """
        return cls(kopecks=int(rubles * 100))

    @property
    def rubles(self) -> float:
        """Get amount in rubles."""
        return self.kopecks / 100

    def __add__(self, other: "Money") -> "Money":
        """Add two Money objects."""
        if not isinstance(other, Money):
            return NotImplemented
        return Money(kopecks=self.kopecks + other.kopecks)

    def __sub__(self, other: "Money") -> "Money":
        """Subtract two Money objects."""
        if not isinstance(other, Money):
            return NotImplemented
        return Money(kopecks=max(0, self.kopecks - other.kopecks))

    def __str__(self) -> str:
        """String representation in rubles."""
        return f"{self.rubles:.2f} RUB"

    def __repr__(self) -> str:
        """Detailed representation."""
        return f"Money(kopecks={self.kopecks})"


# =============================================================================
# Device Status Value Object
# =============================================================================


@dataclass(frozen=True)
class DeviceStatus:
    """
    Immutable status of a device at a point in time.

    Attributes:
        is_connected: Whether device is connected.
        is_enabled: Whether device is enabled/active.
        is_busy: Whether device is busy with an operation.
        health: Overall health status.
        error_message: Current error message if any.
        extra: Additional device-specific data.
    """

    is_connected: bool = False
    is_enabled: bool = False
    is_busy: bool = False
    health: DeviceHealthStatus = DeviceHealthStatus.UNKNOWN
    error_message: Optional[str] = None
    extra: tuple[tuple[str, Any], ...] = field(default_factory=tuple)

    @classmethod
    def healthy(cls, is_enabled: bool = False) -> "DeviceStatus":
        """Create a healthy device status."""
        return cls(
            is_connected=True,
            is_enabled=is_enabled,
            health=DeviceHealthStatus.HEALTHY,
        )

    @classmethod
    def disconnected(cls) -> "DeviceStatus":
        """Create a disconnected device status."""
        return cls(
            is_connected=False,
            health=DeviceHealthStatus.UNHEALTHY,
        )

    @classmethod
    def with_error(cls, error: str) -> "DeviceStatus":
        """Create a status with error."""
        return cls(
            is_connected=True,
            health=DeviceHealthStatus.UNHEALTHY,
            error_message=error,
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "is_connected": self.is_connected,
            "is_enabled": self.is_enabled,
            "is_busy": self.is_busy,
            "health": self.health.name.lower(),
        }
        if self.error_message:
            result["error"] = self.error_message
        if self.extra:
            result.update(dict(self.extra))
        return result


# =============================================================================
# Payment Result Value Objects
# =============================================================================


@dataclass(frozen=True)
class PaymentResult:
    """
    Result of a payment operation.

    Attributes:
        success: Whether the operation succeeded.
        collected_amount: Amount collected in kopecks.
        target_amount: Target amount in kopecks.
        change_due: Change to be dispensed in kopecks.
        message: Human-readable message.
        active_devices: List of active devices.
    """

    success: bool
    collected_amount: int = 0
    target_amount: int = 0
    change_due: int = 0
    message: str = ""
    active_devices: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def started(
        cls,
        target_amount: int,
        active_devices: list[str],
    ) -> "PaymentResult":
        """Create a result for a started payment."""
        return cls(
            success=True,
            target_amount=target_amount,
            active_devices=tuple(active_devices),
            message=f"Payment started for {target_amount / 100:.2f} RUB",
        )

    @classmethod
    def stopped(cls, collected_amount: int) -> "PaymentResult":
        """Create a result for a stopped payment."""
        return cls(
            success=True,
            collected_amount=collected_amount,
            message=f"Payment stopped. Collected: {collected_amount / 100:.2f} RUB",
        )

    @classmethod
    def completed(
        cls,
        collected_amount: int,
        target_amount: int,
    ) -> "PaymentResult":
        """Create a result for a completed payment."""
        change = max(0, collected_amount - target_amount)
        return cls(
            success=True,
            collected_amount=collected_amount,
            target_amount=target_amount,
            change_due=change,
            message=f"Payment completed. Collected: {collected_amount / 100:.2f} RUB",
        )

    @classmethod
    def failed(cls, message: str) -> "PaymentResult":
        """Create a failed result."""
        return cls(success=False, message=message)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API response."""
        result = {
            "success": self.success,
            "message": self.message,
        }
        if self.collected_amount:
            result["collected_amount"] = self.collected_amount
        if self.target_amount:
            result["target_amount"] = self.target_amount
        if self.change_due:
            result["change"] = self.change_due
        if self.active_devices:
            result["active_devices"] = list(self.active_devices)
        return result


@dataclass(frozen=True)
class DispensingResult:
    """
    Result of a change dispensing operation.

    Attributes:
        success: Whether dispensing succeeded.
        requested_amount: Amount requested to dispense.
        dispensed_amount: Actual amount dispensed.
        remaining_amount: Amount that could not be dispensed.
        bills_dispensed: Number of bills dispensed (upper, lower).
        coins_dispensed: Amount dispensed in coins.
        message: Human-readable message.
    """

    success: bool
    requested_amount: int = 0
    dispensed_amount: int = 0
    remaining_amount: int = 0
    bills_dispensed: tuple[int, int] = (0, 0)
    coins_dispensed: int = 0
    message: str = ""

    @classmethod
    def full_dispense(
        cls,
        amount: int,
        bills: tuple[int, int] = (0, 0),
        coins: int = 0,
    ) -> "DispensingResult":
        """Create a successful full dispense result."""
        return cls(
            success=True,
            requested_amount=amount,
            dispensed_amount=amount,
            bills_dispensed=bills,
            coins_dispensed=coins,
            message=f"Dispensed {amount / 100:.2f} RUB",
        )

    @classmethod
    def partial_dispense(
        cls,
        requested: int,
        dispensed: int,
        bills: tuple[int, int] = (0, 0),
        coins: int = 0,
    ) -> "DispensingResult":
        """Create a partial dispense result."""
        return cls(
            success=True,
            requested_amount=requested,
            dispensed_amount=dispensed,
            remaining_amount=requested - dispensed,
            bills_dispensed=bills,
            coins_dispensed=coins,
            message=f"Partially dispensed {dispensed / 100:.2f} of {requested / 100:.2f} RUB",
        )

    @classmethod
    def failed(cls, message: str) -> "DispensingResult":
        """Create a failed result."""
        return cls(success=False, message=message)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "requested_amount": self.requested_amount,
            "dispensed_amount": self.dispensed_amount,
            "remaining_amount": self.remaining_amount,
            "message": self.message,
        }
