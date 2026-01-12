"""
API Facade - Unified interface for the payment system.

Provides a clean API that preserves backward compatibility
while using the new architecture internally.
"""

import asyncio
from typing import Any, Optional

from redis.asyncio import Redis

from application.payment_service import PaymentService
from application.device_service import DeviceService
from event_system import EventPublisher, EventConsumer, EventType
from loggers import logger


class PaymentSystemFacade:
    """
    Facade for the payment system API.

    Provides a unified interface that maintains backward compatibility
    with the original PaymentSystemAPI while using the new layered architecture.
    """

    # Device name constants (for backward compatibility)
    COIN_DISPENSER_NAME = "coin_dispenser"
    COIN_ACCEPTOR_NAME = "coin_acceptor"
    BILL_ACCEPTOR_NAME = "bill_acceptor"
    BILL_DISPENSER_NAME = "bill_dispenser"

    def __init__(self, redis: Redis) -> None:
        """
        Initialize the payment system facade.

        Args:
            redis: Redis client instance.
        """
        self._redis = redis

        # Event system
        self._event_queue: asyncio.Queue = asyncio.Queue()
        self._event_publisher = EventPublisher(self._event_queue)
        self._event_consumer = EventConsumer(self._event_queue)

        # Services
        self._device_service = DeviceService(redis, self._event_publisher)
        self._payment_service = PaymentService(
            redis,
            self._device_service.device_manager,
            self._event_publisher,
        )

        # State (for backward compatibility)
        self._is_initialized = False

    # =========================================================================
    # Device Initialization
    # =========================================================================

    async def init_devices(self) -> dict[str, Any]:
        """
        Initialize all payment devices.

        Returns:
            Dictionary indicating initialization success.
        """
        result = await self._device_service.initialize_devices()

        if result["success"]:
            # Register event handlers
            self._register_event_handlers()
            asyncio.create_task(self._event_consumer.start_consuming())
            self._is_initialized = True

        return result

    def _register_event_handlers(self) -> None:
        """Register handlers for device events."""
        self._event_consumer.register_handler(
            EventType.BILL_ACCEPTED,
            self._payment_service.handle_bill_accepted,
        )
        self._event_consumer.register_handler(
            EventType.COIN_CREDIT,
            self._payment_service.handle_coin_accepted,
        )

    async def shutdown(self) -> None:
        """Shut down all devices and clean up resources."""
        try:
            await self._device_service.shutdown()
            await self._event_consumer.stop_consuming()
            logger.info("Payment system shut down successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

    # =========================================================================
    # Payment Operations
    # =========================================================================

    async def start_accepting_payment(self, amount: int) -> dict[str, Any]:
        """
        Start accepting payment for the specified amount.

        Args:
            amount: Target payment amount in kopecks.

        Returns:
            Dictionary indicating success and active devices.
        """
        return await self._payment_service.start_payment(amount)

    async def stop_accepting_payment(self) -> dict[str, Any]:
        """
        Stop the current payment.

        Returns:
            Dictionary with success status and collected amount.
        """
        return await self._payment_service.stop_payment()

    async def dispense_change(self, amount: int) -> dict[str, Any]:
        """
        Dispense change.

        Args:
            amount: Amount to dispense in kopecks.

        Returns:
            Dictionary indicating success.
        """
        return await self._payment_service.dispense_change(amount)

    async def test_dispense_change(
        self,
        is_bill: bool = False,
        is_coin: bool = False,
    ) -> dict[str, Any]:
        """Test change dispensing."""
        return await self._payment_service.test_dispense_change(is_bill, is_coin)

    # =========================================================================
    # Bill Acceptor Operations
    # =========================================================================

    async def bill_acceptor_status(self) -> dict[str, Any]:
        """Get bill acceptor status."""
        return await self._device_service.get_bill_acceptor_status()

    async def bill_acceptor_set_max_bill_count(self, value: int) -> dict[str, Any]:
        """Set maximum bill count for acceptor."""
        return await self._device_service.set_max_bill_count(value)

    async def bill_acceptor_reset_bill_count(self) -> dict[str, Any]:
        """Reset bill count (cash collection)."""
        return await self._device_service.reset_bill_count()

    # =========================================================================
    # Bill Dispenser Operations
    # =========================================================================

    async def bill_dispenser_status(self) -> dict[str, Any]:
        """Get bill dispenser status."""
        return await self._device_service.get_bill_dispenser_status()

    async def set_bill_dispenser_lvl(
        self,
        upper_lvl: int,
        lower_lvl: int,
    ) -> dict[str, Any]:
        """Set bill dispenser box denominations."""
        return await self._device_service.set_bill_dispenser_denominations(upper_lvl, lower_lvl)

    async def set_bill_dispenser_count(
        self,
        upper_count: int,
        lower_count: int,
    ) -> dict[str, Any]:
        """Add bills to dispenser counts."""
        return await self._device_service.add_bills_to_dispenser(upper_count, lower_count)

    async def bill_dispenser_reset_bill_count(self) -> dict[str, Any]:
        """Reset bill dispenser counts."""
        return await self._device_service.reset_bill_dispenser_count()

    # =========================================================================
    # Coin System Operations
    # =========================================================================

    async def coin_system_status(self) -> dict[str, Any]:
        """Get coin hopper status."""
        return await self._device_service.get_coin_system_status()

    async def coin_system_add_coin_count(
        self,
        value: int,
        denomination: int,
    ) -> dict[str, Any]:
        """Add coins to the hopper."""
        return await self._device_service.add_coins(value, denomination)

    async def coin_system_cash_collection(self) -> dict[str, Any]:
        """Perform cash collection from hopper."""
        return await self._device_service.cash_collection()

    # =========================================================================
    # Properties (for backward compatibility)
    # =========================================================================

    @property
    def is_payment_in_progress(self) -> bool:
        """Check if a payment is in progress."""
        return self._payment_service.is_payment_in_progress

    @property
    def active_devices(self) -> set[str]:
        """Get names of active devices."""
        return self._device_service.device_manager.active_device_names

    @property
    def collected_amount(self) -> int:
        """Get current collected amount."""
        return self._payment_service.collected_amount

    @property
    def target_amount(self) -> int:
        """Get current target amount."""
        return self._payment_service.target_amount
