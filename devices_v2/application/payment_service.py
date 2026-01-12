"""
Payment Service - Application service for payment operations.

Handles the payment flow including accepting cash, tracking progress,
and dispensing change.
"""

import asyncio
from typing import Any, Optional

from redis.asyncio import Redis

from core.value_objects import PaymentResult, DispensingResult
from core.exceptions import (
    PaymentError,
    PaymentInProgressError,
    InsufficientFundsError,
)
from domain.payment_state_machine import PaymentStateMachine, PaymentContext
from domain.device_manager import DeviceManager
from infrastructure.redis_repository import (
    BillAcceptorRepository,
    BillDispenserRepository,
    PaymentStateRepository,
)
from infrastructure.settings import get_settings
from event_system import EventPublisher, EventType
from send_to_ws import send_to_ws
from loggers import logger


class PaymentService:
    """
    Application service for payment operations.

    Coordinates between devices, state machine, and repositories
    to process payments.
    """

    def __init__(
        self,
        redis: Redis,
        device_manager: DeviceManager,
        event_publisher: EventPublisher,
    ) -> None:
        """
        Initialize the payment service.

        Args:
            redis: Redis client for state persistence.
            device_manager: Manager for payment devices.
            event_publisher: Publisher for events.
        """
        self._redis = redis
        self._device_manager = device_manager
        self._event_publisher = event_publisher
        self._settings = get_settings()

        # Repositories
        self._bill_acceptor_repo = BillAcceptorRepository(redis)
        self._bill_dispenser_repo = BillDispenserRepository(redis)
        self._payment_repo = PaymentStateRepository(redis)

        # State machine
        self._state_machine = PaymentStateMachine()
        self._state_machine.set_on_complete(self._on_payment_complete)
        self._state_machine.set_on_payment(self._on_payment_received)

    @property
    def is_payment_in_progress(self) -> bool:
        """Check if a payment is in progress."""
        return self._state_machine.is_active

    @property
    def collected_amount(self) -> int:
        """Get current collected amount."""
        return self._state_machine.context.collected_amount

    @property
    def target_amount(self) -> int:
        """Get current target amount."""
        return self._state_machine.context.target_amount

    async def start_payment(self, amount: int) -> dict[str, Any]:
        """
        Start accepting payment for the specified amount.

        Args:
            amount: Target payment amount in kopecks.

        Returns:
            Dictionary with success status and active devices.
        """
        if amount <= 0:
            logger.error(f"Invalid payment amount: {amount}")
            return {"success": False, "message": "Invalid payment amount"}

        # Validate system readiness
        validation = await self._validate_payment_start()
        if not validation["valid"]:
            return {"success": False, "message": validation["message"]}

        logger.info(f"Starting payment for {amount / 100:.2f} RUB")

        # Enable acceptor devices
        enabled_devices = await self._device_manager.enable_acceptors()

        if not enabled_devices:
            logger.error("Failed to start any payment device")
            return {
                "success": False,
                "message": "Failed to start payment devices",
            }

        # Start payment in state machine
        try:
            result = await self._state_machine.start(amount, enabled_devices)
        except PaymentInProgressError:
            return {"success": False, "message": "Payment already in progress"}

        # Persist state to Redis
        await self._payment_repo.set_target_amount(amount)
        await self._payment_repo.set_collected_amount(0)

        message = f"Accepting payment of {amount / 100:.2f} RUB. Active: {', '.join(enabled_devices)}"
        return {
            "success": True,
            "message": message,
            "active_devices": enabled_devices,
        }

    async def _validate_payment_start(self) -> dict[str, Any]:
        """Validate that the system is ready to start a payment."""
        # Check if already in progress
        if self.is_payment_in_progress:
            return {"valid": False, "message": "Payment already in progress"}

        # Check test mode
        is_test = await self._payment_repo.is_test_mode()
        if is_test:
            logger.info("Test mode - skipping validations")
            return {"valid": True, "message": "OK"}

        # Check bill dispenser has enough bills
        dispenser_state = await self._bill_dispenser_repo.get_state()
        min_count = self._settings.payment.min_dispenser_box_count

        if (dispenser_state.upper_box_count < min_count or
                dispenser_state.lower_box_count < min_count):
            return {
                "valid": False,
                "message": f"Insufficient bills in dispenser. Upper: {dispenser_state.upper_box_count}, Lower: {dispenser_state.lower_box_count}",
            }

        # Check bill acceptor capacity
        acceptor_state = await self._bill_acceptor_repo.get_state()
        if acceptor_state.is_full:
            return {"valid": False, "message": "Bill acceptor is full"}

        return {"valid": True, "message": "OK"}

    async def stop_payment(self) -> dict[str, Any]:
        """
        Stop the current payment.

        Returns:
            Dictionary with success status and collected amount.
        """
        if not self.is_payment_in_progress:
            logger.warning("No payment in progress")
            return {"success": False, "message": "No payment in progress"}

        logger.info("Stopping payment...")

        # Disable acceptors
        await self._device_manager.disable_acceptors()

        # Stop state machine
        result = await self._state_machine.stop()

        # Reset Redis state
        await self._payment_repo.reset()

        return result.to_dict()

    async def handle_bill_accepted(self, event: dict[str, Any]) -> None:
        """
        Handle bill acceptance event.

        Args:
            event: Event dictionary with bill value.
        """
        value = event.get("value", 0)
        if value <= 0:
            return

        # Update state machine
        await self._state_machine.add_payment(value, "bill_acceptor")

        # Persist to Redis
        collected = self._state_machine.context.collected_amount
        await self._payment_repo.set_collected_amount(collected)

        # Send WebSocket notification
        await send_to_ws(
            event="acceptedBill",
            data={"bill_value": value, "collected_amount": collected},
        )

    async def handle_coin_accepted(self, event: dict[str, Any]) -> None:
        """
        Handle coin acceptance event.

        Args:
            event: Event dictionary with coin value.
        """
        value = event.get("value", 0)
        if value <= 0:
            return

        # Add coin to hopper inventory
        coin_dispenser = self._device_manager.get_coin_dispenser()
        if coin_dispenser:
            try:
                await coin_dispenser.add_coins(value=1, denomination=value)
            except Exception as e:
                logger.error(f"Error adding coin to inventory: {e}")

        # Update state machine
        await self._state_machine.add_payment(value, "coin_acceptor")

        # Persist to Redis
        collected = self._state_machine.context.collected_amount
        await self._payment_repo.set_collected_amount(collected)

        # Send WebSocket notification
        await send_to_ws(
            event="acceptedCoin",
            data={"coin_value": value, "collected_amount": collected},
        )

    async def _on_payment_received(
        self,
        amount: int,
        source: str,
        context: PaymentContext,
    ) -> None:
        """Callback when payment is received."""
        logger.info(
            f"Payment received: {amount / 100:.2f} RUB from {source}. "
            f"Total: {context.collected_amount / 100:.2f} RUB"
        )

    async def _on_payment_complete(self, context: PaymentContext) -> None:
        """Callback when payment target is reached."""
        logger.info("=== COMPLETING PAYMENT ===")

        # Disable acceptors first
        await self._device_manager.disable_acceptors()

        # Calculate values
        collected = context.collected_amount
        target = context.target_amount
        change = context.change_amount

        # Reset Redis state
        await self._payment_repo.reset()

        logger.info(f"Payment completed: {collected / 100:.2f} RUB, change: {change / 100:.2f} RUB")

        # Send WebSocket notification
        await send_to_ws(
            event="successPayment",
            data={"collected_amount": collected, "change": change},
        )

        # Dispense change if needed
        if change > 0:
            await self.dispense_change(change)

        # Complete the state machine
        await self._state_machine.complete()

    async def dispense_change(self, amount: int) -> dict[str, Any]:
        """
        Dispense change using bills and coins.

        Args:
            amount: Amount to dispense in kopecks.

        Returns:
            Dictionary with success status and dispensed amount.
        """
        logger.info(f"Dispensing change: {amount / 100:.2f} RUB")

        dispensed_total = 0
        remaining = amount

        # Try dispensing bills first
        bill_dispenser = self._device_manager.get_bill_dispenser()
        if bill_dispenser and bill_dispenser.is_connected:
            dispenser_state = await self._bill_dispenser_repo.get_state()
            min_denomination = min(dispenser_state.upper_box_value, dispenser_state.lower_box_value)

            if remaining >= min_denomination:
                await asyncio.sleep(0.5)  # Brief pause before dispensing
                try:
                    dispensed_bills = await bill_dispenser.dispense(remaining)
                    dispensed_total += dispensed_bills
                    remaining -= dispensed_bills
                except Exception as e:
                    logger.error(f"Error dispensing bills: {e}")

        # Dispense remaining as coins
        if remaining > 0:
            await asyncio.sleep(1.0)  # Pause between devices
            coin_dispenser = self._device_manager.get_coin_dispenser()
            if coin_dispenser and coin_dispenser.is_connected:
                try:
                    dispensed_coins = await coin_dispenser.dispense(remaining)
                    dispensed_total += dispensed_coins
                    remaining -= dispensed_coins
                except Exception as e:
                    logger.error(f"Error dispensing coins: {e}")

        if remaining > 0:
            logger.warning(f"Unable to dispense full amount. Remaining: {remaining / 100:.2f} RUB")

        if dispensed_total > 0:
            logger.info(f"Change dispensed: {dispensed_total / 100:.2f} RUB")
            return {
                "success": True,
                "message": f"Change dispensed: {dispensed_total / 100:.2f} RUB",
                "dispensed_amount": dispensed_total,
                "remaining_amount": remaining,
            }
        else:
            return {
                "success": False,
                "message": "No change dispensed",
                "remaining_amount": remaining,
            }

    async def test_dispense_change(
        self,
        is_bill: bool = False,
        is_coin: bool = False,
    ) -> dict[str, Any]:
        """
        Test change dispensing functionality.

        Args:
            is_bill: Whether to test bill dispensing.
            is_coin: Whether to test coin dispensing.

        Returns:
            Dictionary with success status.
        """
        try:
            if is_coin:
                coin_dispenser = self._device_manager.get_coin_dispenser()
                if coin_dispenser:
                    await coin_dispenser.dispense(100)  # Dispense 1 ruble

            if is_bill:
                dispenser_state = await self._bill_dispenser_repo.get_state()
                test_amount = dispenser_state.upper_box_value + dispenser_state.lower_box_value
                if test_amount > 0:
                    await self.dispense_change(test_amount)

            return {"success": True, "message": "Change dispensing test successful"}
        except Exception as e:
            logger.error(f"Test dispense error: {e}")
            return {"success": False, "message": f"Error dispensing change: {e}"}
