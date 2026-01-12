"""
Custom exceptions for the cash system.

Provides a hierarchy of typed exceptions for better error handling
and more informative error messages.
"""

from typing import Any, Optional


class CashSystemError(Exception):
    """Base exception for all cash system errors."""

    def __init__(
        self,
        message: str,
        code: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
    ) -> None:
        """
        Initialize the exception.

        Args:
            message: Human-readable error message.
            code: Optional error code for programmatic handling.
            details: Optional additional error details.
        """
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        """Convert exception to dictionary for API responses."""
        return {
            "error": self.code,
            "message": self.message,
            "details": self.details,
        }


# =============================================================================
# Device Errors
# =============================================================================


class DeviceError(CashSystemError):
    """Base exception for device-related errors."""

    def __init__(
        self,
        message: str,
        device_name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.device_name = device_name
        if device_name:
            self.details["device"] = device_name


class DeviceConnectionError(DeviceError):
    """Error connecting to a device."""

    pass


class DeviceTimeoutError(DeviceError):
    """Device operation timed out."""

    pass


class DeviceNotFoundError(DeviceError):
    """Device not found or not configured."""

    pass


class DeviceOperationError(DeviceError):
    """Error during device operation."""

    pass


# =============================================================================
# Payment Errors
# =============================================================================


class PaymentError(CashSystemError):
    """Base exception for payment-related errors."""

    pass


class PaymentInProgressError(PaymentError):
    """A payment is already in progress."""

    pass


class InsufficientFundsError(PaymentError):
    """Insufficient funds in dispenser."""

    def __init__(
        self,
        message: str,
        required: int = 0,
        available: int = 0,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, **kwargs)
        self.details["required"] = required
        self.details["available"] = available


class InvalidAmountError(PaymentError):
    """Invalid payment amount."""

    pass


class PaymentCancelledError(PaymentError):
    """Payment was cancelled."""

    pass


# =============================================================================
# Repository Errors
# =============================================================================


class RepositoryError(CashSystemError):
    """Base exception for repository errors."""

    pass


class RedisConnectionError(RepositoryError):
    """Error connecting to Redis."""

    pass


class DataNotFoundError(RepositoryError):
    """Requested data not found."""

    pass
