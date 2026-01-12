"""
Payment System API for cash handling devices.

This module provides the main API for interacting with cash payment devices
including bill acceptors, coin acceptors, bill dispensers, and coin hoppers.
All device state is persisted in Redis for coordination across processes.
"""

import asyncio
from typing import Any, Optional

from redis.asyncio import Redis

from devices.cctalk_coin_acceptor import CcTalkAcceptor
from devices.coin_acceptor.index import SSP
from devices.bill_acceptor import bill_acceptor_v1, bill_acceptor_v3
from devices.bill_dispenser.bill_dispenser import Clcdm2000, LcdmException
from event_system import EventPublisher, EventConsumer, EventType
from configs import (
    PORT_OPTIONS,
    BILL_DISPENSER_PORT,
    bill_acceptor_config,
    COIN_ACCEPTOR_PORT,
    MIN_BOX_COUNT,
)
from loggers import logger
from redis_error_handler import redis_error_handler
from send_to_ws import send_to_ws


class PaymentSystemAPI:
    """
    API for interacting with cash payment devices.

    This class manages the lifecycle and operations of all cash handling
    devices, including initialization, payment processing, and change dispensing.

    Attributes:
        redis: Redis client for state persistence.
        active_devices: Set of currently active device names.
        is_payment_in_progress: Flag indicating if a payment is being processed.
    """

    # Device name constants
    COIN_DISPENSER_NAME: str = "coin_dispenser"
    COIN_ACCEPTOR_NAME: str = "coin_acceptor"
    BILL_ACCEPTOR_NAME: str = "bill_acceptor"
    BILL_DISPENSER_NAME: str = "bill_dispenser"

    def __init__(self, redis: Redis) -> None:
        """
        Initialize the payment system API.

        Args:
            redis: Redis client instance for state management.
        """
        # Event system
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.event_publisher = EventPublisher(self.event_queue)
        self.event_consumer = EventConsumer(self.event_queue)

        # Redis connection
        self.redis = redis

        # Device instances
        self.hopper = SSP(self.event_publisher)
        self.cctalk_acceptor = CcTalkAcceptor(self.event_publisher)
        self.bill_acceptor: Optional[Any] = None
        self.bill_dispenser = Clcdm2000()

        # Payment tracking
        self.target_amount: int = 0
        self.collected_amount: int = 0
        self.active_devices: set[str] = set()
        self.is_payment_in_progress: bool = False

        # Bill dispenser configurations
        self.upper_box_value: Optional[int] = None
        self.lower_box_value: Optional[int] = None
        self.upper_box_count: Optional[int] = None
        self.lower_box_count: Optional[int] = None


    async def bill_acceptor_status(self) -> dict[str, Any]:
        """
        Get the current status of the bill acceptor.

        Returns:
            Dictionary containing success status and bill count information.
        """
        try:
            max_bill_count = await self.redis.get("max_bill_count")
            bill_count = await self.redis.get("bill_count")
            return {
                "success": True,
                "message": "Bill acceptor status retrieved successfully",
                "data": {
                    "max_bill_count": int(max_bill_count) if max_bill_count else 0,
                    "bill_count": int(bill_count) if bill_count else 0,
                },
            }
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis connection issue: {e}")
            return {
                "success": False,
                "message": f"Redis connection issue: {e}",
            }

    async def bill_dispenser_status(self) -> dict[str, Any]:
        """
        Get the current status of the bill dispenser.

        Returns:
            Dictionary containing success status and dispenser configuration.
        """
        try:
            upper_box_value = await self.redis.get("bill_dispenser:upper_lvl")
            lower_box_value = await self.redis.get("bill_dispenser:lower_lvl")
            upper_box_count = await self.redis.get("bill_dispenser:upper_count")
            lower_box_count = await self.redis.get("bill_dispenser:lower_count")
            return {
                "success": True,
                "message": "Bill dispenser status retrieved successfully",
                "data": {
                    "upper_box_value": int(upper_box_value) * 100,
                    "lower_box_value": int(lower_box_value) * 100,
                    "upper_box_count": int(upper_box_count),
                    "lower_box_count": int(lower_box_count),
                },
            }
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis connection issue: {e}")
            return {
                "success": False,
                "message": f"Redis connection issue: {e}",
            }

    @redis_error_handler("Maximum bill count set successfully")
    async def bill_acceptor_set_max_bill_count(self, value: int) -> None:
        """
        Set the maximum bill count for the acceptor.

        Args:
            value: Maximum number of bills the acceptor can hold.
        """
        await self.redis.set("max_bill_count", value)
        await self.init_bill_acceptor()

    @redis_error_handler("Bill count reset successfully")
    async def bill_acceptor_reset_bill_count(self) -> None:
        """Reset the bill count to zero (cash collection)."""
        await self.redis.set("bill_count", 0)

    @redis_error_handler("Bill dispenser denominations set successfully")
    async def set_bill_dispenser_lvl(self, upper_lvl: int, lower_lvl: int) -> None:
        """
        Set the denomination values for the bill dispenser boxes.

        Args:
            upper_lvl: Denomination value for the upper box.
            lower_lvl: Denomination value for the lower box.
        """
        await self.redis.set("bill_dispenser:upper_lvl", upper_lvl)
        await self.redis.set("bill_dispenser:lower_lvl", lower_lvl)

    @redis_error_handler("Bill dispenser count updated successfully")
    async def set_bill_dispenser_count(self, upper_count: int, lower_count: int) -> None:
        """
        Add bills to the dispenser count.

        Args:
            upper_count: Number of bills to add to the upper box.
            lower_count: Number of bills to add to the lower box.
        """
        old_upper_count = int(await self.redis.get("bill_dispenser:upper_count") or 0)
        old_lower_count = int(await self.redis.get("bill_dispenser:lower_count") or 0)
        await self.redis.set("bill_dispenser:upper_count", upper_count + old_upper_count)
        await self.redis.set("bill_dispenser:lower_count", lower_count + old_lower_count)

    @redis_error_handler("Bill dispenser count reset successfully")
    async def bill_dispenser_reset_bill_count(self) -> None:
        """Reset the bill dispenser counts to zero."""
        await self.redis.set("bill_dispenser:upper_count", 0)
        await self.redis.set("bill_dispenser:lower_count", 0)


    async def stop_accepting_payment(self) -> dict[str, Any]:
        """
        Stop the current payment and return collected amount.

        Returns:
            Dictionary with success status and collected amount.
        """
        if not self.is_payment_in_progress:
            logger.warning("No payment in progress")
            return {
                "success": False,
                "message": "No payment in progress",
            }

        logger.info("Stopping payment...")

        # Stop devices
        if self.COIN_ACCEPTOR_NAME in self.active_devices:
            try:
                await self.cctalk_acceptor.disable()
            except Exception as e:
                logger.error(f"Error disabling cctalk_acceptor: {e}")

        if self.BILL_ACCEPTOR_NAME in self.active_devices and self.bill_acceptor:
            try:
                await self.bill_acceptor.stop_accepting()
                await asyncio.sleep(0.5)
                await self.bill_acceptor.reset_device()
            except Exception as e:
                logger.error(f"Error stopping bill acceptor: {e}")

        # Store collected amount before reset
        collected = self.collected_amount

        # Reset state
        self.is_payment_in_progress = False
        self.target_amount = 0
        self.collected_amount = 0

        # Reset Redis
        await self.redis.set("collected_amount", 0)
        await self.redis.set("target_amount", 0)

        logger.info(f"Payment stopped. Collected: {collected / 100} RUB")
        return {
            "success": True,
            "message": f"Payment stopped. Collected: {collected / 100} RUB",
            "collected_amount": collected,
        }

    @redis_error_handler("Change dispensing test successful")
    async def test_dispense_change(self, is_bill: bool, is_coin: bool) -> None:
        """
        Test change dispensing functionality.

        Args:
            is_bill: Whether to test bill dispensing.
            is_coin: Whether to test coin dispensing.
        """
        try:
            if is_coin:
                await self.hopper.enable()
                await self.hopper.command("PAYOUT_AMOUNT", {
                    "amount": 100,
                    "country_code": "RUB",
                    "test": False,
                })
            if is_bill:
                self.upper_box_value = int(await self.redis.get("bill_dispenser:upper_lvl"))
                self.lower_box_value = int(await self.redis.get("bill_dispenser:lower_lvl"))
                await self.dispense_change(self.upper_box_value + self.lower_box_value)
        except Exception as e:
            return {
                "success": False,
                "message": f"Error dispensing change: {e}",
            }


    async def coin_system_add_coin_count(self, value: int, denomination: int) -> dict[str, Any]:
        """
        Add coins of a specific denomination to the hopper.

        Args:
            value: Number of coins to add.
            denomination: Coin denomination in kopecks.

        Returns:
            Dictionary indicating success.
        """
        try:
            logger.info("Opening SSP hopper to add coins...")
            self.hopper.open(COIN_ACCEPTOR_PORT, PORT_OPTIONS)
            await self.hopper.command("SYNC")
            await self.hopper.command("SET_DENOMINATION_LEVEL", {
                "value": value,
                "denomination": denomination,
                "country_code": "RUB",
            })
            logger.info("Coins added successfully")
            return {
                "success": True,
                "message": "Coins added successfully",
            }
        except Exception as e:
            logger.error(f"Error adding coins: {e}")
            return {
                "success": False,
                "message": f"Error adding coins: {e}",
            }
        finally:
            logger.info("Closing SSP hopper after adding coins.")
            if self.hopper.port and self.hopper.port.is_open:
                await self.hopper.disable()
                await self.hopper.close()
                await asyncio.sleep(0.1)

    async def coin_system_status(self) -> dict[str, Any]:
        """
        Get the current status of the coin hopper.

        Returns:
            Dictionary with hopper status and coin levels.
        """
        try:
            logger.info("Checking hopper status...")
            self.hopper.open(COIN_ACCEPTOR_PORT, PORT_OPTIONS)
            await self.hopper.command("SYNC")
            status = await self.hopper.command("GET_ALL_LEVELS")
            return {
                "success": True,
                "data": status,
                "message": "Hopper status retrieved successfully",
            }
        except Exception as e:
            logger.error(f"Error getting hopper status: {e}")
            return {
                "success": False,
                "message": f"Error getting hopper status: {e}",
            }
        finally:
            logger.info("Closing SSP hopper after status check.")
            if self.hopper.port and self.hopper.port.is_open:
                await self.hopper.close()
                await asyncio.sleep(0.1)

    async def coin_system_cash_collection(self) -> dict[str, Any]:
        """
        Perform cash collection from the hopper.

        Returns:
            Dictionary indicating success.
        """
        try:
            logger.info("Starting hopper cash collection...")
            self.hopper.open(COIN_ACCEPTOR_PORT, PORT_OPTIONS)
            await self.hopper.enable()
            await self.hopper.command("SYNC")
            await self.hopper.command("EMPTY_ALL")
            return {
                "success": True,
                "message": "Cash collection started successfully",
            }
        except Exception as e:
            logger.error(f"Error during cash collection: {e}")
            return {
                "success": False,
                "message": f"Error during cash collection: {e}",
            }
        finally:
            logger.info("Closing SSP hopper after cash collection.")
            if self.hopper.port and self.hopper.port.is_open:
                await self.hopper.disable()
                await self.hopper.close()
                await asyncio.sleep(0.1)


    async def init_devices(self) -> dict[str, Any]:
        """
        Initialize all payment devices.

        Returns:
            Dictionary indicating initialization success.
        """
        is_hopper = await self.init_ssp_hopper()
        if is_hopper:
            self.active_devices.add(self.COIN_DISPENSER_NAME)

        is_coin = await self.init_cctalk_coin_acceptor()
        if is_coin:
            self.active_devices.add(self.COIN_ACCEPTOR_NAME)

        await self.init_bill_acceptor()
        await self.init_bill_dispenser()

        self.register_event_handlers()
        asyncio.create_task(self.event_consumer.start_consuming())

        available_devices = await self.redis.smembers("available_devices_cash")

        if available_devices.issubset(self.active_devices):
            logger.info("Payment system initialized successfully")
            return {
                "success": True,
                "message": "Payment system initialized successfully",
            }
        else:
            missing = available_devices - self.active_devices
            logger.error(f"Failed to initialize devices: {missing}")
            return {
                "success": False,
                "message": f"Failed to initialize devices: {missing}",
            }

    async def init_ssp_hopper(self) -> bool:
        """
        Initialize the SSP hopper for coin dispensing.

        Returns:
            True if initialization successful.
        """
        try:
            self.hopper.open(COIN_ACCEPTOR_PORT, PORT_OPTIONS)

            await self.hopper.command("SYNC")
            await self.hopper.command("HOST_PROTOCOL_VERSION", {"version": 6})
            await self.hopper.init_encryption()
            await self.hopper.command("SETUP_REQUEST")

            # Disable coin acceptance (hopper is for dispensing only)
            await self.hopper.disable()

            logger.info("SSP hopper initialized successfully (dispense only)")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize SSP hopper: {e}")
            return False
        finally:
            if self.hopper.port and self.hopper.port.is_open:
                await self.hopper.close()

    async def init_cctalk_coin_acceptor(self) -> bool:
        """
        Initialize the ccTalk coin acceptor.

        Returns:
            True if initialization successful.
        """
        try:
            self.cctalk_acceptor.port = "/dev/ttyUSB0"
            if await self.cctalk_acceptor.initialize():
                logger.info("ccTalk coin acceptor initialized successfully")
                return True
            else:
                raise Exception("initialize() returned False")
        except Exception as e:
            logger.error(f"Failed to initialize ccTalk coin acceptor: {e}")
            return False

    async def init_bill_acceptor(self) -> None:
        """Initialize the bill acceptor based on firmware version."""
        bill_acceptor_firmware = await self.redis.get("bill_acceptor_firmware")

        if bill_acceptor_firmware == "v1":
            self.bill_acceptor = bill_acceptor_v1.BillAcceptor(
                bill_acceptor_config.BILL_ACCEPTOR_PORT,
                self.event_publisher,
                self.redis,
            )
        elif bill_acceptor_firmware in ("v2", "v3"):
            self.bill_acceptor = bill_acceptor_v3.BillAcceptor(
                bill_acceptor_config.BILL_ACCEPTOR_PORT,
                self.event_publisher,
                self.redis,
            )

        if self.bill_acceptor is None:
            logger.warning("No bill acceptor firmware version configured")
            return

        try:
            if not await self.bill_acceptor.initialize():
                raise Exception("initialize() returned False")
            await self.bill_acceptor.reset_device()
            logger.info("Bill acceptor initialized successfully")
            self.active_devices.add(self.BILL_ACCEPTOR_NAME)
        except Exception as e:
            logger.error(f"Failed to initialize bill acceptor: {e}")

    async def init_bill_dispenser(self) -> None:
        """Initialize the bill dispenser."""
        try:
            self.bill_dispenser.connect(BILL_DISPENSER_PORT, 9600)
            self.bill_dispenser.purge()
            logger.info("Bill dispenser initialized successfully")
            self.active_devices.add(self.BILL_DISPENSER_NAME)
        except LcdmException as e:
            logger.error(f"Failed to initialize bill dispenser: {e}")


    def register_event_handlers(self) -> None:
        """Register handlers for device events."""
        self.event_consumer.register_handler(
            EventType.BILL_ACCEPTED,
            self.handle_bill_accepted,
        )
        self.event_consumer.register_handler(
            EventType.COIN_CREDIT,
            self.on_coin_credit,
        )

    async def handle_bill_accepted(self, event: dict[str, Any]) -> None:
        """
        Handle bill acceptance event.

        Args:
            event: Event dictionary with bill value.
        """
        bill_value = event["value"]
        self.collected_amount += bill_value
        await self.redis.set("collected_amount", self.collected_amount)

        logger.info(
            f"Bill accepted: {bill_value / 100} RUB. "
            f"Total: {self.collected_amount / 100} RUB"
        )

        await send_to_ws(
            event="acceptedBill",
            data={"bill_value": bill_value, "collected_amount": self.collected_amount},
        )

        if self.target_amount != 0 and self.collected_amount >= self.target_amount:
            await self.complete_payment()

    async def on_coin_credit(self, event: dict[str, Any]) -> None:
        """
        Handle coin credit event from ccTalk device.

        Args:
            event: Event dictionary with coin value.
        """
        try:
            amount = event.get("value")
            if amount is None:
                logger.error(f"Coin event missing value: {event}")
                return

            # Update hopper inventory
            await self.coin_system_add_coin_count(value=1, denomination=amount)

            self.collected_amount += amount
            await self.redis.set("collected_amount", self.collected_amount)

            logger.info(
                f"Coin accepted: {amount / 100} RUB. "
                f"Total: {self.collected_amount / 100} RUB"
            )

            await send_to_ws(
                event="acceptedCoin",
                data={"coin_value": amount, "collected_amount": self.collected_amount},
            )

            if self.target_amount > 0 and self.collected_amount >= self.target_amount:
                await self.complete_payment()

        except Exception as e:
            logger.error(f"Error handling coin credit: {e}")


    async def start_accepting_payment(self, amount: int) -> dict[str, Any]:
        """
        Start accepting payment for the specified amount.

        Args:
            amount: Target payment amount in kopecks.

        Returns:
            Dictionary indicating success and active devices.
        """
        if amount <= 0:
            logger.error(f"Invalid payment amount: {amount}")
            return {
                "success": False,
                "message": "Invalid payment amount",
            }

        upper_box_count = int(await self.redis.get("bill_dispenser:upper_count") or 0)
        lower_box_count = int(await self.redis.get("bill_dispenser:lower_count") or 0)
        bill_count = int(await self.redis.get("bill_count") or 0)
        max_bill_count = int(await self.redis.get("max_bill_count") or 0)
        is_test_mode = await self.redis.get("cash_system_is_test_mode")

        if self.is_payment_in_progress:
            logger.error("Payment already in progress")
            return {
                "success": False,
                "message": "Payment already in progress",
            }

        if is_test_mode:
            logger.info("Test mode - skipping validation")
        elif upper_box_count < MIN_BOX_COUNT or lower_box_count < MIN_BOX_COUNT:
            logger.error(
                f"Insufficient bills in dispenser. "
                f"Upper: {upper_box_count}, Lower: {lower_box_count}"
            )
            return {
                "success": False,
                "message": "Insufficient bills in dispenser",
            }
        elif bill_count >= max_bill_count:
            logger.error("Bill acceptor is full")
            return {
                "success": False,
                "message": "Bill acceptor is full",
            }

        logger.info(f"Starting payment acceptance for {amount / 100} RUB")

        # Set payment state before starting devices
        self.target_amount = amount
        self.collected_amount = 0
        self.is_payment_in_progress = True

        await self.redis.set("target_amount", amount)
        await self.redis.set("collected_amount", 0)

        devices_started: list[str] = []
        errors: list[str] = []

        # Start devices with error handling
        if self.COIN_ACCEPTOR_NAME in self.active_devices:
            try:
                await self.cctalk_acceptor.enable()
                devices_started.append(self.COIN_ACCEPTOR_NAME)
                logger.info("Coin acceptor enabled")
            except Exception as e:
                logger.error(f"Failed to enable coin acceptor: {e}")
                errors.append(f"{self.COIN_ACCEPTOR_NAME}: {e}")

        if self.BILL_ACCEPTOR_NAME in self.active_devices and self.bill_acceptor:
            try:
                # Ensure device is not active
                if self.bill_acceptor._active:
                    logger.warning("Bill acceptor was active, stopping first")
                    await self.bill_acceptor.stop_accepting()
                    await asyncio.sleep(0.5)

                await self.bill_acceptor.start_accepting()
                devices_started.append(self.BILL_ACCEPTOR_NAME)
                logger.info("Bill acceptor enabled")
            except Exception as e:
                logger.error(f"Failed to enable bill acceptor: {e}")
                errors.append(f"{self.BILL_ACCEPTOR_NAME}: {e}")

        if devices_started:
            message = f"Accepting payment of {amount / 100} RUB. Active: {', '.join(devices_started)}"
            if errors:
                message += f". Errors: {'; '.join(errors)}"
            return {
                "success": True,
                "message": message,
                "active_devices": devices_started,
            }
        else:
            self.is_payment_in_progress = False
            self.target_amount = 0
            self.collected_amount = 0
            logger.error("Failed to start any payment device")
            return {
                "success": False,
                "message": f"Failed to start devices. Errors: {'; '.join(errors)}",
            }

    async def complete_payment(self) -> None:
        """Complete the payment and dispense change if needed."""
        logger.info("=== COMPLETING PAYMENT ===")

        # Store values before reset
        collected = self.collected_amount
        target = self.target_amount
        change = max(0, collected - target)

        # Reset payment state first
        self.is_payment_in_progress = False

        # Stop devices
        if self.BILL_ACCEPTOR_NAME in self.active_devices and self.bill_acceptor:
            try:
                await self.bill_acceptor.stop_accepting()
                logger.info("Bill acceptor stopped")
            except Exception as e:
                logger.error(f"Error stopping bill acceptor: {e}")

        if self.COIN_ACCEPTOR_NAME in self.active_devices:
            try:
                await self.cctalk_acceptor.disable()
                logger.info("Coin acceptor disabled")
            except Exception as e:
                logger.error(f"Error disabling coin acceptor: {e}")

        # Reset counters
        self.target_amount = 0
        self.collected_amount = 0
        await self.redis.set("collected_amount", 0)
        await self.redis.set("target_amount", 0)

        logger.info(f"Payment completed: {collected / 100} RUB, change: {change / 100} RUB")

        await send_to_ws(
            event="successPayment",
            data={"collected_amount": collected, "change": change},
        )

        # Dispense change if needed
        if change > 0:
            try:
                await self.dispense_change(change)
            except Exception as e:
                logger.error(f"Error dispensing change: {e}")

    async def dispense_change(self, amount: int) -> dict[str, Any]:
        """
        Dispense change using bills and coins.

        Args:
            amount: Amount to dispense in kopecks.

        Returns:
            Dictionary indicating success and amount dispensed.
        """
        dispensed_amount = 0

        self.upper_box_value = int(await self.redis.get("bill_dispenser:upper_lvl") or 0)
        self.lower_box_value = int(await self.redis.get("bill_dispenser:lower_lvl") or 0)

        # Try dispensing bills first
        if self.BILL_DISPENSER_NAME in self.active_devices and amount >= self.lower_box_value:
            await asyncio.sleep(0.5)
            try:
                # Determine which denomination is higher
                higher_box_value = max(self.upper_box_value, self.lower_box_value)
                lower_box_value = min(self.upper_box_value, self.lower_box_value)

                # Use higher denomination first, then lower
                higher_bills = int(amount // higher_box_value)
                lower_bills = int((amount % higher_box_value) // lower_box_value)

                if higher_bills > 0 or lower_bills > 0:
                    # Determine correct order for dispenser
                    if self.upper_box_value > self.lower_box_value:
                        result = self.bill_dispenser.upperLowerDispense(higher_bills, lower_bills)
                    else:
                        result = self.bill_dispenser.upperLowerDispense(lower_bills, higher_bills)

                    upper_exit, lower_exit = result[0], result[1]

                    dispensed_amount = (
                        upper_exit * self.upper_box_value +
                        lower_exit * self.lower_box_value
                    )
                    amount -= dispensed_amount

                    # Update Redis counts
                    upper_count = int(await self.redis.get("bill_dispenser:upper_count") or 0)
                    lower_count = int(await self.redis.get("bill_dispenser:lower_count") or 0)
                    await self.redis.set("bill_dispenser:upper_count", upper_count - upper_exit)
                    await self.redis.set("bill_dispenser:lower_count", lower_count - lower_exit)

            except Exception as e:
                logger.error(f"Error dispensing bills: {e}")
                return {
                    "success": False,
                    "message": f"Error dispensing bills: {e}",
                }

        # Pause between devices
        await asyncio.sleep(1.0)

        # Dispense remaining as coins
        if self.COIN_DISPENSER_NAME in self.active_devices and amount > 0:
            try:
                self.hopper.open(COIN_ACCEPTOR_PORT, PORT_OPTIONS)
                await self.hopper.enable()
                await self.hopper.command("SYNC")

                big_coin_priority = await self.redis.get("settings:big_coin_priority")

                if not big_coin_priority:
                    # Simple payout
                    coins_to_dispense = int(amount)
                    result = await self.hopper.command("PAYOUT_AMOUNT", {
                        "amount": coins_to_dispense,
                        "country_code": "RUB",
                        "test": False,
                    })
                    if result.get("success"):
                        dispensed_amount += amount
                        amount = 0
                    else:
                        logger.error(f"Coin payout failed: {result.get('error', 'Unknown error')}")
                else:
                    # Denomination-based payout
                    all_levels = await self.hopper.command("GET_ALL_LEVELS")
                    if not all_levels.get("success"):
                        raise Exception("Could not get coin levels from hopper")

                    coin_data_dict = all_levels.get("info", {}).get("counter", {})

                    # Sort coins by value descending
                    available_coins = sorted(
                        [c for c in coin_data_dict.values() if c.get("denomination_level", 0) > 0],
                        key=lambda x: x.get("value", 0),
                        reverse=True,
                    )

                    payout_list = []
                    remaining_amount = int(amount)

                    for coin in available_coins:
                        coin_value = coin["value"]
                        coin_count = coin["denomination_level"]

                        if remaining_amount >= coin_value:
                            num_to_dispense = min(remaining_amount // coin_value, coin_count)
                            if num_to_dispense > 0:
                                payout_list.append({
                                    "number": num_to_dispense,
                                    "denomination": coin_value,
                                    "country_code": "RUB",
                                })
                                remaining_amount -= num_to_dispense * coin_value

                    if payout_list:
                        result = await self.hopper.command("PAYOUT_BY_DENOMINATION", {
                            "value": payout_list,
                            "test": False,
                        })

                        if result.get("success"):
                            dispensed_in_coins = amount - remaining_amount
                            dispensed_amount += dispensed_in_coins
                            amount -= dispensed_in_coins
                        else:
                            logger.error(f"Denomination payout failed: {result.get('error')}")
                    else:
                        logger.warning("No coins available for requested amount")

            except Exception as e:
                logger.error(f"Error dispensing coins: {e}")
            finally:
                await self.hopper.disable()
                if self.hopper.port and self.hopper.port.is_open:
                    await self.hopper.close()

        if amount > 0:
            logger.info(f"Remaining undispensed change: {amount / 100} RUB")

        if dispensed_amount > 0:
            logger.info(f"Change dispensed: {dispensed_amount / 100} RUB")
            return {
                "success": True,
                "message": "Change dispensed successfully",
            }
        else:
            logger.info("No change dispensed")
            return {
                "success": False,
                "message": "No change dispensed",
            }

    async def shutdown(self) -> None:
        """Shut down all devices and clean up resources."""
        try:
            if self.COIN_ACCEPTOR_NAME in self.active_devices:
                await self.cctalk_acceptor.disable()

            if self.COIN_DISPENSER_NAME in self.active_devices:
                await self.hopper.disable()
                await self.hopper.close()

            if self.BILL_ACCEPTOR_NAME in self.active_devices and self.bill_acceptor:
                await self.bill_acceptor.stop_accepting()

            # Stop event consumer
            await self.event_consumer.stop_consuming()

            logger.info("Payment system shut down successfully")
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")
