"""
Bill Acceptor V3 - Integration with Redis and EventPublisher.

This module wraps the CCNET driver (CashCodeDriver) with Redis and EventPublisher
integration for use in the devices_v2 system.

Features:
- Uses the improved CCNET protocol driver with proper SET_SECURITY and ACK handling
- Integrates with the devices_v2 event system (EventPublisher)
- Tracks bill count in Redis
- Checks for bill acceptor capacity (max_bill_count)

Usage:
    from redis.asyncio import Redis
    from event_system import EventPublisher
    from devices.bill_acceptor.bill_acceptor_v3 import BillAcceptor

    redis = Redis()
    publisher = EventPublisher(event_queue)
    
    acceptor = BillAcceptor(port='/dev/ttyS0', publisher=publisher, redis=redis)
    await acceptor.initialize()
    await acceptor.start_accepting()
"""

import asyncio
import logging
from typing import Optional

from redis.asyncio import Redis

from event_system import EventPublisher, EventType
from devices.ccnet import (
    CashCodeDriver,
    StateContext,
    EventType as CCNETEventType,
    get_bill_amount,
)

logger = logging.getLogger(__name__)


class BillAcceptor:
    """
    Bill Acceptor interface for devices_v2 system.
    
    Wraps CashCodeDriver with Redis and EventPublisher integration.
    
    Attributes:
        port: Serial port path (e.g., '/dev/ttyS0').
        publisher: EventPublisher for event queue.
        redis: Redis client for bill count tracking.
    """
    
    def __init__(
        self,
        port: str,
        publisher: EventPublisher,
        redis: Redis,
        auto_stack: bool = True,
    ) -> None:
        """
        Initialize bill acceptor.
        
        Args:
            port: Serial port path.
            publisher: EventPublisher for the event queue.
            redis: Redis client.
            auto_stack: Automatically accept bills in escrow (default True).
        """
        self.port = port
        self.publisher = publisher
        self.redis = redis
        
        # Create the underlying CCNET driver
        self._driver = CashCodeDriver(
            port=port,
            baudrate=9600,
            auto_stack=auto_stack,
        )
        
        # State tracking
        self._active = False
        self._accepting_enabled = False
        self.max_bill_count: Optional[int] = None
        self.transaction_counter = 0
        
        # Register internal callbacks for BILL_STACKED events
        self._driver.add_callback(CCNETEventType.BILL_STACKED, self._on_bill_stacked)
    
    async def initialize(self) -> bool:
        """
        Initialize the bill acceptor.
        
        Checks capacity and connects to the device.
        
        Returns:
            True if initialization successful.
        """
        # Check bill acceptor capacity
        if not await self._check_bill_acceptor_capacity():
            return False
        
        # Connect to the device
        try:
            result = await self._driver.connect()
            if result:
                logger.info("Bill acceptor initialized successfully")
                return True
            else:
                logger.error("Failed to connect to bill acceptor")
                return False
        except Exception as e:
            logger.error(f"Error initializing bill acceptor: {e}")
            return False
    
    async def start_accepting(self) -> None:
        """Start accepting bills."""
        if self._active:
            await self.stop_accepting()
        
        self._active = True
        self._accepting_enabled = True
        
        # Enable the validator (starts polling loop)
        await self._driver.enable_validator()
        
        logger.info("Bill acceptor started accepting")
    
    async def stop_accepting(self) -> None:
        """Stop accepting bills."""
        if not self._active:
            return
        
        self._accepting_enabled = False
        self._active = False
        
        # Stop the driver
        await self._driver.stop()
        
        logger.info("Bill acceptor stopped accepting")
    
    async def reset_device(self) -> bool:
        """
        Reset the bill acceptor device.
        
        Returns:
            True if reset successful.
        """
        try:
            return await self._driver.reset()
        except Exception as e:
            logger.error(f"Error resetting bill acceptor: {e}")
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from the bill acceptor."""
        await self._driver.disconnect()
        self._active = False
        self._accepting_enabled = False
        logger.info("Bill acceptor disconnected")
    
    async def _check_bill_acceptor_capacity(self) -> bool:
        """
        Check if bill acceptor is at capacity.
        
        Returns:
            True if capacity is available.
        """
        count = int(await self.redis.get("bill_count") or 0)
        self.max_bill_count = int(await self.redis.get("max_bill_count") or 0)
        if self.max_bill_count > 0 and count >= self.max_bill_count:
            logger.error("Bill acceptor is full (capacity reached)")
            return False
        return True
    
    async def _on_bill_stacked(
        self,
        event_type: str,
        context: StateContext,
    ) -> None:
        """
        Handle BILL_STACKED event from CCNET driver.
        
        Publishes BILL_ACCEPTED event and increments Redis bill_count.
        
        Args:
            event_type: Event type string.
            context: State context with bill information.
        """
        if not self._accepting_enabled:
            logger.warning("Bill stacked but accepting is disabled")
            return
        
        amount = context.bill_amount
        bill_code = context.bill_code
        
        if amount <= 0:
            logger.warning(f"Bill stacked with unknown amount: bill_code={bill_code}")
            return
        
        logger.info(f"Bill accepted: {amount / 100:.2f} RUB (code=0x{bill_code:02X})")
        
        # Publish event to the event system
        await self.publisher.publish(EventType.BILL_ACCEPTED, value=amount)
        
        # Increment bill count in Redis
        await self.redis.incr("bill_count")
        
        # Update transaction counter
        self.transaction_counter += 1
        logger.info(f"Transaction #{self.transaction_counter}: {amount / 100:.2f} RUB accepted")
    
    @property
    def is_connected(self) -> bool:
        """Check if driver is connected."""
        return self._driver.is_connected
    
    @property
    def is_accepting(self) -> bool:
        """Check if bill acceptance is enabled."""
        return self._accepting_enabled and self._driver.is_accepting
    
    @property
    def current_state_name(self) -> str:
        """Get current device state name."""
        return self._driver.current_state_name
    
    async def __aenter__(self) -> 'BillAcceptor':
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
