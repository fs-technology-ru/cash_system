"""
Redis Repository implementations.

Provides type-safe, domain-specific access to Redis state storage.
Each repository encapsulates Redis keys and operations for its domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from redis.asyncio import Redis

from core.exceptions import RedisConnectionError, RepositoryError
from loggers import logger


# =============================================================================
# Base Repository
# =============================================================================


class RedisStateRepository:
    """
    Base repository for Redis state operations.

    Provides common Redis operations with error handling.
    """

    def __init__(self, redis: Redis) -> None:
        """
        Initialize the repository.

        Args:
            redis: Redis client instance.
        """
        self._redis = redis

    async def get(self, key: str) -> Optional[str]:
        """Get a string value by key."""
        try:
            return await self._redis.get(key)
        except ConnectionError as e:
            raise RedisConnectionError(f"Redis connection error: {e}")

    async def set(self, key: str, value: Any) -> None:
        """Set a key-value pair."""
        try:
            await self._redis.set(key, value)
        except ConnectionError as e:
            raise RedisConnectionError(f"Redis connection error: {e}")

    async def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer value by key."""
        value = await self.get(key)
        return int(value) if value else default

    async def increment(self, key: str, amount: int = 1) -> int:
        """Increment a value by the specified amount."""
        try:
            return await self._redis.incrby(key, amount)
        except ConnectionError as e:
            raise RedisConnectionError(f"Redis connection error: {e}")

    async def get_set_members(self, key: str) -> set[str]:
        """Get all members of a set."""
        try:
            return await self._redis.smembers(key)
        except ConnectionError as e:
            raise RedisConnectionError(f"Redis connection error: {e}")

    async def add_to_set(self, key: str, *values: str) -> None:
        """Add values to a set."""
        try:
            await self._redis.sadd(key, *values)
        except ConnectionError as e:
            raise RedisConnectionError(f"Redis connection error: {e}")


# =============================================================================
# Bill Acceptor Repository
# =============================================================================


@dataclass
class BillAcceptorState:
    """State data for bill acceptor."""

    bill_count: int = 0
    max_bill_count: int = 0
    firmware_version: Optional[str] = None

    @property
    def is_full(self) -> bool:
        """Check if acceptor is at capacity."""
        return self.max_bill_count > 0 and self.bill_count >= self.max_bill_count

    @property
    def remaining_capacity(self) -> int:
        """Get remaining bill capacity. Returns max int if unlimited."""
        if self.max_bill_count <= 0:
            return 2**31 - 1  # Max 32-bit int (effectively unlimited)
        return max(0, self.max_bill_count - self.bill_count)


class BillAcceptorRepository(RedisStateRepository):
    """
    Repository for bill acceptor state.

    Keys:
    - bill_count: Current number of bills in stacker
    - max_bill_count: Maximum capacity
    - bill_acceptor_firmware: Firmware version (v1, v2, v3)
    """

    KEY_BILL_COUNT = "bill_count"
    KEY_MAX_BILL_COUNT = "max_bill_count"
    KEY_FIRMWARE = "bill_acceptor_firmware"

    async def get_state(self) -> BillAcceptorState:
        """Get current bill acceptor state."""
        bill_count = await self.get_int(self.KEY_BILL_COUNT)
        max_count = await self.get_int(self.KEY_MAX_BILL_COUNT)
        firmware = await self.get(self.KEY_FIRMWARE)
        return BillAcceptorState(
            bill_count=bill_count,
            max_bill_count=max_count,
            firmware_version=firmware,
        )

    async def get_bill_count(self) -> int:
        """Get current bill count."""
        return await self.get_int(self.KEY_BILL_COUNT)

    async def set_bill_count(self, count: int) -> None:
        """Set bill count."""
        await self.set(self.KEY_BILL_COUNT, count)

    async def increment_bill_count(self) -> int:
        """Increment bill count by 1."""
        return await self.increment(self.KEY_BILL_COUNT)

    async def reset_bill_count(self) -> None:
        """Reset bill count to zero (cash collection)."""
        await self.set(self.KEY_BILL_COUNT, 0)

    async def get_max_bill_count(self) -> int:
        """Get maximum bill count."""
        return await self.get_int(self.KEY_MAX_BILL_COUNT)

    async def set_max_bill_count(self, count: int) -> None:
        """Set maximum bill count."""
        await self.set(self.KEY_MAX_BILL_COUNT, count)

    async def get_firmware_version(self) -> Optional[str]:
        """Get firmware version."""
        return await self.get(self.KEY_FIRMWARE)

    async def is_full(self) -> bool:
        """Check if acceptor is at capacity."""
        state = await self.get_state()
        return state.is_full


# =============================================================================
# Bill Dispenser Repository
# =============================================================================


@dataclass
class BillDispenserState:
    """State data for bill dispenser."""

    upper_box_value: int = 0  # Denomination in kopecks
    lower_box_value: int = 0  # Denomination in kopecks
    upper_box_count: int = 0  # Number of bills
    lower_box_count: int = 0  # Number of bills

    @property
    def total_available(self) -> int:
        """Get total available amount in kopecks."""
        return (
            self.upper_box_value * self.upper_box_count +
            self.lower_box_value * self.lower_box_count
        )


class BillDispenserRepository(RedisStateRepository):
    """
    Repository for bill dispenser state.

    Keys:
    - bill_dispenser:upper_lvl: Upper box denomination
    - bill_dispenser:lower_lvl: Lower box denomination
    - bill_dispenser:upper_count: Upper box bill count
    - bill_dispenser:lower_count: Lower box bill count
    """

    KEY_UPPER_LVL = "bill_dispenser:upper_lvl"
    KEY_LOWER_LVL = "bill_dispenser:lower_lvl"
    KEY_UPPER_COUNT = "bill_dispenser:upper_count"
    KEY_LOWER_COUNT = "bill_dispenser:lower_count"

    async def get_state(self) -> BillDispenserState:
        """Get current dispenser state."""
        return BillDispenserState(
            upper_box_value=await self.get_int(self.KEY_UPPER_LVL),
            lower_box_value=await self.get_int(self.KEY_LOWER_LVL),
            upper_box_count=await self.get_int(self.KEY_UPPER_COUNT),
            lower_box_count=await self.get_int(self.KEY_LOWER_COUNT),
        )

    async def set_denominations(self, upper_lvl: int, lower_lvl: int) -> None:
        """Set box denomination values."""
        await self.set(self.KEY_UPPER_LVL, upper_lvl)
        await self.set(self.KEY_LOWER_LVL, lower_lvl)

    async def get_counts(self) -> tuple[int, int]:
        """Get bill counts (upper, lower)."""
        upper = await self.get_int(self.KEY_UPPER_COUNT)
        lower = await self.get_int(self.KEY_LOWER_COUNT)
        return upper, lower

    async def add_bills(self, upper_count: int, lower_count: int) -> None:
        """Add bills to the dispenser counts."""
        current_upper = await self.get_int(self.KEY_UPPER_COUNT)
        current_lower = await self.get_int(self.KEY_LOWER_COUNT)
        await self.set(self.KEY_UPPER_COUNT, current_upper + upper_count)
        await self.set(self.KEY_LOWER_COUNT, current_lower + lower_count)

    async def subtract_bills(self, upper_count: int, lower_count: int) -> None:
        """Subtract bills from the dispenser counts."""
        current_upper = await self.get_int(self.KEY_UPPER_COUNT)
        current_lower = await self.get_int(self.KEY_LOWER_COUNT)
        await self.set(self.KEY_UPPER_COUNT, max(0, current_upper - upper_count))
        await self.set(self.KEY_LOWER_COUNT, max(0, current_lower - lower_count))

    async def reset_counts(self) -> None:
        """Reset bill counts to zero."""
        await self.set(self.KEY_UPPER_COUNT, 0)
        await self.set(self.KEY_LOWER_COUNT, 0)


# =============================================================================
# Coin System Repository
# =============================================================================


class CoinSystemRepository(RedisStateRepository):
    """
    Repository for coin hopper/acceptor settings.

    Keys:
    - settings:big_coin_priority: Use larger coins first when dispensing
    """

    KEY_BIG_COIN_PRIORITY = "settings:big_coin_priority"

    async def get_big_coin_priority(self) -> bool:
        """Check if big coin priority is enabled."""
        value = await self.get(self.KEY_BIG_COIN_PRIORITY)
        return bool(value)

    async def set_big_coin_priority(self, enabled: bool) -> None:
        """Set big coin priority setting."""
        await self.set(self.KEY_BIG_COIN_PRIORITY, "1" if enabled else "")


# =============================================================================
# Payment State Repository
# =============================================================================


@dataclass
class PaymentState:
    """Current payment state data."""

    target_amount: int = 0
    collected_amount: int = 0
    is_test_mode: bool = False

    @property
    def is_complete(self) -> bool:
        """Check if target amount has been reached."""
        return self.target_amount > 0 and self.collected_amount >= self.target_amount

    @property
    def remaining_amount(self) -> int:
        """Get remaining amount to collect."""
        return max(0, self.target_amount - self.collected_amount)

    @property
    def change_due(self) -> int:
        """Get change due (overpayment)."""
        return max(0, self.collected_amount - self.target_amount)


class PaymentStateRepository(RedisStateRepository):
    """
    Repository for payment transaction state.

    Keys:
    - target_amount: Target payment amount
    - collected_amount: Amount collected so far
    - cash_system_is_test_mode: Test mode flag
    - available_devices_cash: Set of available device names
    """

    KEY_TARGET = "target_amount"
    KEY_COLLECTED = "collected_amount"
    KEY_TEST_MODE = "cash_system_is_test_mode"
    KEY_AVAILABLE_DEVICES = "available_devices_cash"

    async def get_state(self) -> PaymentState:
        """Get current payment state."""
        target = await self.get_int(self.KEY_TARGET)
        collected = await self.get_int(self.KEY_COLLECTED)
        test_mode = await self.get(self.KEY_TEST_MODE)
        return PaymentState(
            target_amount=target,
            collected_amount=collected,
            is_test_mode=bool(test_mode),
        )

    async def set_target_amount(self, amount: int) -> None:
        """Set target payment amount."""
        await self.set(self.KEY_TARGET, amount)

    async def set_collected_amount(self, amount: int) -> None:
        """Set collected amount."""
        await self.set(self.KEY_COLLECTED, amount)

    async def add_collected_amount(self, amount: int) -> int:
        """Add to collected amount and return new total."""
        return await self.increment(self.KEY_COLLECTED, amount)

    async def reset(self) -> None:
        """Reset payment state."""
        await self.set(self.KEY_TARGET, 0)
        await self.set(self.KEY_COLLECTED, 0)

    async def get_available_devices(self) -> set[str]:
        """Get set of available device names."""
        return await self.get_set_members(self.KEY_AVAILABLE_DEVICES)

    async def set_available_devices(self, devices: set[str]) -> None:
        """Set available devices."""
        # Clear existing and add new
        try:
            await self._redis.delete(self.KEY_AVAILABLE_DEVICES)
            if devices:
                await self._redis.sadd(self.KEY_AVAILABLE_DEVICES, *devices)
        except ConnectionError as e:
            raise RedisConnectionError(f"Redis connection error: {e}")

    async def is_test_mode(self) -> bool:
        """Check if test mode is enabled."""
        value = await self.get(self.KEY_TEST_MODE)
        return bool(value)
