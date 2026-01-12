"""
Payment State Machine - Manages payment transaction lifecycle.

Implements the State pattern for clean payment flow management.
"""

from __future__ import annotations

import asyncio
from enum import Enum, auto
from typing import Any, Callable, Optional
from dataclasses import dataclass, field

from core.value_objects import PaymentResult
from core.exceptions import PaymentError, PaymentInProgressError, InvalidAmountError
from loggers import logger


# =============================================================================
# Payment Phases
# =============================================================================


class PaymentPhase(Enum):
    """Phases of a payment transaction."""

    IDLE = auto()           # No payment in progress
    VALIDATING = auto()     # Validating payment request
    ACCEPTING = auto()      # Accepting cash from customer
    COMPLETING = auto()     # Payment target reached, completing
    DISPENSING = auto()     # Dispensing change
    COMPLETED = auto()      # Payment completed successfully
    CANCELLED = auto()      # Payment was cancelled
    FAILED = auto()         # Payment failed


# =============================================================================
# Payment Context
# =============================================================================


@dataclass
class PaymentContext:
    """
    Context for a payment transaction.

    Holds all state for the current payment.
    """

    target_amount: int = 0
    collected_amount: int = 0
    change_amount: int = 0
    phase: PaymentPhase = PaymentPhase.IDLE
    active_devices: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        """Check if target amount has been reached."""
        return self.target_amount > 0 and self.collected_amount >= self.target_amount

    @property
    def remaining_amount(self) -> int:
        """Get remaining amount to collect."""
        return max(0, self.target_amount - self.collected_amount)

    @property
    def overpayment(self) -> int:
        """Get overpayment amount (change due)."""
        return max(0, self.collected_amount - self.target_amount)

    def add_payment(self, amount: int) -> None:
        """Add a payment to the collected amount."""
        self.collected_amount += amount
        if self.is_complete:
            self.change_amount = self.overpayment

    def reset(self) -> None:
        """Reset the payment context."""
        self.target_amount = 0
        self.collected_amount = 0
        self.change_amount = 0
        self.phase = PaymentPhase.IDLE
        self.active_devices = []
        self.errors = []


# =============================================================================
# Payment State Machine
# =============================================================================


class PaymentStateMachine:
    """
    State machine for payment transaction management.

    Manages the lifecycle of a payment from initiation to completion,
    including accepting cash, tracking progress, and triggering change dispensing.
    """

    def __init__(self) -> None:
        """Initialize the state machine."""
        self._context = PaymentContext()
        self._lock = asyncio.Lock()
        self._on_complete_callback: Optional[Callable] = None
        self._on_payment_callback: Optional[Callable] = None

    @property
    def context(self) -> PaymentContext:
        """Get the current payment context."""
        return self._context

    @property
    def phase(self) -> PaymentPhase:
        """Get the current payment phase."""
        return self._context.phase

    @property
    def is_active(self) -> bool:
        """Check if a payment is currently active."""
        return self._context.phase in (
            PaymentPhase.VALIDATING,
            PaymentPhase.ACCEPTING,
            PaymentPhase.COMPLETING,
            PaymentPhase.DISPENSING,
        )

    @property
    def is_accepting(self) -> bool:
        """Check if currently accepting payments."""
        return self._context.phase == PaymentPhase.ACCEPTING

    def set_on_complete(self, callback: Callable) -> None:
        """Set callback for payment completion."""
        self._on_complete_callback = callback

    def set_on_payment(self, callback: Callable) -> None:
        """Set callback for payment received."""
        self._on_payment_callback = callback

    async def start(self, amount: int, active_devices: list[str]) -> PaymentResult:
        """
        Start a new payment.

        Args:
            amount: Target payment amount in kopecks.
            active_devices: List of active device names.

        Returns:
            PaymentResult indicating success or failure.

        Raises:
            PaymentInProgressError: If a payment is already in progress.
            InvalidAmountError: If amount is invalid.
        """
        async with self._lock:
            if self.is_active:
                raise PaymentInProgressError("Payment already in progress")

            if amount <= 0:
                raise InvalidAmountError(f"Invalid payment amount: {amount}")

            logger.info(f"Starting payment for {amount / 100:.2f} RUB")

            self._context.reset()
            self._context.target_amount = amount
            self._context.active_devices = active_devices
            self._context.phase = PaymentPhase.ACCEPTING

            return PaymentResult.started(amount, active_devices)

    async def add_payment(self, amount: int, source: str) -> None:
        """
        Record a payment received.

        Args:
            amount: Amount received in kopecks.
            source: Source device name.
        """
        if not self.is_accepting:
            logger.warning(f"Payment received but not accepting: {amount} from {source}")
            return

        async with self._lock:
            self._context.add_payment(amount)

            logger.info(
                f"Payment received: {amount / 100:.2f} RUB from {source}. "
                f"Total: {self._context.collected_amount / 100:.2f} RUB"
            )

            # Notify callback
            if self._on_payment_callback:
                try:
                    await self._on_payment_callback(amount, source, self._context)
                except Exception as e:
                    logger.error(f"Payment callback error: {e}")

            # Check completion
            if self._context.is_complete:
                await self._transition_to_completing()

    async def _transition_to_completing(self) -> None:
        """Transition to completing phase."""
        self._context.phase = PaymentPhase.COMPLETING

        logger.info(
            f"Payment target reached. "
            f"Collected: {self._context.collected_amount / 100:.2f} RUB, "
            f"Change: {self._context.change_amount / 100:.2f} RUB"
        )

        # Trigger completion callback
        if self._on_complete_callback:
            try:
                await self._on_complete_callback(self._context)
            except Exception as e:
                logger.error(f"Completion callback error: {e}")

    async def stop(self) -> PaymentResult:
        """
        Stop the current payment.

        Returns:
            PaymentResult with collected amount.
        """
        async with self._lock:
            if not self.is_active:
                logger.warning("No payment in progress to stop")
                return PaymentResult.failed("No payment in progress")

            collected = self._context.collected_amount
            self._context.phase = PaymentPhase.CANCELLED

            logger.info(f"Payment stopped. Collected: {collected / 100:.2f} RUB")

            result = PaymentResult.stopped(collected)
            self._context.reset()
            return result

    async def complete(self) -> PaymentResult:
        """
        Mark payment as completed.

        Returns:
            PaymentResult indicating completion.
        """
        async with self._lock:
            if self._context.phase not in (PaymentPhase.COMPLETING, PaymentPhase.DISPENSING):
                return PaymentResult.failed("Not in completing phase")

            result = PaymentResult.completed(
                self._context.collected_amount,
                self._context.target_amount,
            )

            self._context.phase = PaymentPhase.COMPLETED
            logger.info(f"Payment completed: {result.message}")

            # Reset for next payment
            self._context.reset()

            return result

    async def set_dispensing(self) -> None:
        """Mark payment as dispensing change."""
        async with self._lock:
            if self._context.phase == PaymentPhase.COMPLETING:
                self._context.phase = PaymentPhase.DISPENSING

    async def fail(self, reason: str) -> PaymentResult:
        """
        Mark payment as failed.

        Args:
            reason: Failure reason.

        Returns:
            PaymentResult indicating failure.
        """
        async with self._lock:
            self._context.phase = PaymentPhase.FAILED
            self._context.errors.append(reason)

            result = PaymentResult.failed(reason)
            self._context.reset()

            return result
