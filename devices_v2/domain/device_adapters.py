"""
Device Adapters - Unified interface for different device types.

Wraps hardware-specific device drivers with a common interface
for use in the payment system.
"""

import asyncio
from typing import Any, Callable, Optional

from core.interfaces import DeviceType, DeviceStateData, Device
from core.exceptions import DeviceError, DeviceConnectionError
from loggers import logger


# =============================================================================
# Base Device Adapter
# =============================================================================


class BaseDeviceAdapter(Device):
    """
    Base class for device adapters.

    Provides common functionality for all device adapters.
    """

    def __init__(self, device_type: DeviceType, device_name: str) -> None:
        """
        Initialize the adapter.

        Args:
            device_type: Type of device.
            device_name: Human-readable device name.
        """
        self._device_type = device_type
        self._device_name = device_name
        self._connected = False
        self._event_callback: Optional[Callable] = None

    @property
    def device_type(self) -> DeviceType:
        """Get the device type."""
        return self._device_type

    @property
    def device_name(self) -> str:
        """Get the device name."""
        return self._device_name

    @property
    def is_connected(self) -> bool:
        """Check if device is connected."""
        return self._connected

    def set_event_callback(self, callback: Callable) -> None:
        """Set callback for device events."""
        self._event_callback = callback

    async def _emit_event(self, event_type: str, **data: Any) -> None:
        """Emit an event to the callback."""
        if self._event_callback:
            try:
                await self._event_callback(event_type, data)
            except Exception as e:
                logger.error(f"Event callback error: {e}")


# =============================================================================
# Bill Acceptor Adapter
# =============================================================================


class BillAcceptorAdapter(BaseDeviceAdapter):
    """
    Adapter for bill acceptor devices.

    Wraps the CCNET bill acceptor driver with a unified interface.
    """

    def __init__(
        self,
        driver: Any,
        repository: Any,
    ) -> None:
        """
        Initialize the bill acceptor adapter.

        Args:
            driver: The underlying bill acceptor driver.
            repository: Bill acceptor repository for state.
        """
        super().__init__(DeviceType.BILL_ACCEPTOR, "bill_acceptor")
        self._driver = driver
        self._repository = repository
        self._accepting = False

    @property
    def is_accepting(self) -> bool:
        """Check if device is accepting bills."""
        return self._accepting

    async def connect(self) -> bool:
        """Connect to the bill acceptor."""
        try:
            if self._driver is None:
                return False

            result = await self._driver.initialize()
            if result:
                self._connected = True
                logger.info("Bill acceptor connected")
            return result
        except Exception as e:
            logger.error(f"Bill acceptor connection error: {e}")
            raise DeviceConnectionError(
                f"Failed to connect to bill acceptor: {e}",
                device_name=self._device_name,
            )

    async def disconnect(self) -> None:
        """Disconnect from the bill acceptor."""
        if self._driver and self._connected:
            try:
                await self._driver.disconnect()
            except Exception as e:
                logger.error(f"Bill acceptor disconnect error: {e}")
            finally:
                self._connected = False
                self._accepting = False

    async def enable_accepting(self) -> None:
        """Enable bill acceptance."""
        if not self._driver:
            raise DeviceError("Bill acceptor not initialized", self._device_name)

        if self._accepting:
            await self.disable_accepting()
            await asyncio.sleep(0.5)

        await self._driver.start_accepting()
        self._accepting = True
        logger.info("Bill acceptor enabled")

    async def disable_accepting(self) -> None:
        """Disable bill acceptance."""
        if self._driver and self._accepting:
            try:
                await self._driver.stop_accepting()
            except Exception as e:
                logger.error(f"Error disabling bill acceptor: {e}")
            finally:
                self._accepting = False
                logger.info("Bill acceptor disabled")

    async def reset(self) -> bool:
        """Reset the bill acceptor."""
        if self._driver:
            return await self._driver.reset_device()
        return False

    async def get_status(self) -> DeviceStateData:
        """Get device status."""
        state = await self._repository.get_state()
        return DeviceStateData(
            device_type=self._device_type,
            device_name=self._device_name,
            is_connected=self._connected,
            is_enabled=self._accepting,
            extra_data={
                "bill_count": state.bill_count,
                "max_bill_count": state.max_bill_count,
                "is_full": state.is_full,
            },
        )


# =============================================================================
# Bill Dispenser Adapter
# =============================================================================


class BillDispenserAdapter(BaseDeviceAdapter):
    """
    Adapter for bill dispenser devices.

    Wraps the LCDM-2000 dispenser driver with a unified interface.
    """

    def __init__(
        self,
        driver: Any,
        repository: Any,
    ) -> None:
        """
        Initialize the bill dispenser adapter.

        Args:
            driver: The underlying dispenser driver.
            repository: Bill dispenser repository for state.
        """
        super().__init__(DeviceType.BILL_DISPENSER, "bill_dispenser")
        self._driver = driver
        self._repository = repository

    async def connect(self) -> bool:
        """Connect to the bill dispenser."""
        try:
            from infrastructure.settings import get_settings
            settings = get_settings()

            self._driver.connect(settings.ports.bill_dispenser, 9600)
            self._driver.purge()
            self._connected = True
            logger.info("Bill dispenser connected")
            return True
        except Exception as e:
            logger.error(f"Bill dispenser connection error: {e}")
            raise DeviceConnectionError(
                f"Failed to connect to bill dispenser: {e}",
                device_name=self._device_name,
            )

    async def disconnect(self) -> None:
        """Disconnect from the bill dispenser."""
        if self._driver and self._connected:
            try:
                self._driver.disconnect()
            except Exception:
                pass
            finally:
                self._connected = False

    async def dispense(self, amount: int) -> int:
        """
        Dispense bills for the specified amount.

        Args:
            amount: Amount to dispense in kopecks.

        Returns:
            Actual amount dispensed in kopecks.
        """
        if not self._connected:
            raise DeviceError("Bill dispenser not connected", self._device_name)

        state = await self._repository.get_state()

        # Calculate optimal bill combination
        upper_val = state.upper_box_value
        lower_val = state.lower_box_value

        if upper_val <= 0 and lower_val <= 0:
            return 0

        # Determine which box has higher denomination
        higher_val = max(upper_val, lower_val)
        lower_val_actual = min(upper_val, lower_val)

        # Calculate bills to dispense
        higher_bills = amount // higher_val if higher_val > 0 else 0
        remaining = amount % higher_val if higher_val > 0 else amount
        lower_bills = remaining // lower_val_actual if lower_val_actual > 0 else 0

        # Map back to upper/lower based on which is higher
        if upper_val >= lower_val:
            upper_to_dispense = higher_bills
            lower_to_dispense = lower_bills
        else:
            upper_to_dispense = lower_bills
            lower_to_dispense = higher_bills

        # Limit to available counts
        upper_to_dispense = min(upper_to_dispense, state.upper_box_count)
        lower_to_dispense = min(lower_to_dispense, state.lower_box_count)

        if upper_to_dispense == 0 and lower_to_dispense == 0:
            return 0

        try:
            result = self._driver.upperLowerDispense(
                int(upper_to_dispense),
                int(lower_to_dispense),
            )
            upper_exit, lower_exit = result[0], result[1]

            # Update repository
            await self._repository.subtract_bills(upper_exit, lower_exit)

            dispensed = upper_exit * state.upper_box_value + lower_exit * state.lower_box_value
            logger.info(f"Dispensed {dispensed / 100:.2f} RUB in bills")
            return dispensed

        except Exception as e:
            logger.error(f"Bill dispense error: {e}")
            raise DeviceError(f"Dispense failed: {e}", self._device_name)

    async def get_available_amount(self) -> int:
        """Get total available amount for dispensing."""
        state = await self._repository.get_state()
        return state.total_available

    async def get_status(self) -> DeviceStateData:
        """Get device status."""
        state = await self._repository.get_state()
        return DeviceStateData(
            device_type=self._device_type,
            device_name=self._device_name,
            is_connected=self._connected,
            extra_data={
                "upper_box_value": state.upper_box_value * 100,
                "lower_box_value": state.lower_box_value * 100,
                "upper_box_count": state.upper_box_count,
                "lower_box_count": state.lower_box_count,
                "total_available": state.total_available,
            },
        )


# =============================================================================
# Coin Acceptor Adapter (ccTalk)
# =============================================================================


class CoinAcceptorAdapter(BaseDeviceAdapter):
    """
    Adapter for ccTalk coin acceptor devices.

    Wraps the ccTalk driver with a unified interface.
    """

    def __init__(self, driver: Any) -> None:
        """
        Initialize the coin acceptor adapter.

        Args:
            driver: The underlying ccTalk driver.
        """
        super().__init__(DeviceType.COIN_ACCEPTOR, "coin_acceptor")
        self._driver = driver
        self._accepting = False

    @property
    def is_accepting(self) -> bool:
        """Check if device is accepting coins."""
        return self._accepting

    async def connect(self) -> bool:
        """Connect to the coin acceptor."""
        try:
            self._driver.port = "/dev/ttyUSB0"
            result = await self._driver.initialize()
            if result:
                self._connected = True
                logger.info("Coin acceptor connected")
            return result
        except Exception as e:
            logger.error(f"Coin acceptor connection error: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the coin acceptor."""
        if self._accepting:
            await self.disable_accepting()
        self._connected = False

    async def enable_accepting(self) -> None:
        """Enable coin acceptance."""
        if self._accepting:
            return
        await self._driver.enable()
        self._accepting = True
        logger.info("Coin acceptor enabled")

    async def disable_accepting(self) -> None:
        """Disable coin acceptance."""
        if not self._accepting:
            return
        try:
            await self._driver.disable()
        except Exception as e:
            logger.error(f"Error disabling coin acceptor: {e}")
        finally:
            self._accepting = False
            logger.info("Coin acceptor disabled")

    async def get_status(self) -> DeviceStateData:
        """Get device status."""
        return DeviceStateData(
            device_type=self._device_type,
            device_name=self._device_name,
            is_connected=self._connected,
            is_enabled=self._accepting,
        )


# =============================================================================
# Coin Dispenser Adapter (SSP Hopper)
# =============================================================================


class CoinDispenserAdapter(BaseDeviceAdapter):
    """
    Adapter for SSP coin hopper/dispenser devices.

    Wraps the SSP driver with a unified interface.
    """

    def __init__(
        self,
        driver: Any,
        repository: Any,
    ) -> None:
        """
        Initialize the coin dispenser adapter.

        Args:
            driver: The underlying SSP driver.
            repository: Coin system repository.
        """
        super().__init__(DeviceType.COIN_DISPENSER, "coin_dispenser")
        self._driver = driver
        self._repository = repository

    async def connect(self) -> bool:
        """Connect and initialize the SSP hopper."""
        try:
            from infrastructure.settings import get_settings
            settings = get_settings()

            self._driver.open(
                settings.ports.coin_acceptor,
                {
                    "baudrate": settings.serial.baudrate,
                    "bytesize": settings.serial.bytesize,
                    "stopbits": settings.serial.stopbits,
                    "parity": settings.serial.parity,
                    "timeout": settings.serial.timeout,
                },
            )

            await self._driver.command("SYNC")
            await self._driver.command("HOST_PROTOCOL_VERSION", {"version": 6})
            await self._driver.init_encryption()
            await self._driver.command("SETUP_REQUEST")
            await self._driver.disable()

            self._connected = True
            logger.info("Coin dispenser (SSP) connected")

            # Close port after init (will reopen for operations)
            if self._driver.port and self._driver.port.is_open:
                await self._driver.close()

            return True

        except Exception as e:
            logger.error(f"Coin dispenser connection error: {e}")
            return False

    async def disconnect(self) -> None:
        """Disconnect from the hopper."""
        if self._driver:
            try:
                await self._driver.disable()
                await self._driver.close()
            except Exception:
                pass
            finally:
                self._connected = False

    async def dispense(self, amount: int) -> int:
        """
        Dispense coins for the specified amount.

        Args:
            amount: Amount to dispense in kopecks.

        Returns:
            Actual amount dispensed in kopecks.
        """
        if amount <= 0:
            return 0

        try:
            from infrastructure.settings import get_settings
            settings = get_settings()

            self._driver.open(
                settings.ports.coin_acceptor,
                {
                    "baudrate": settings.serial.baudrate,
                    "bytesize": settings.serial.bytesize,
                    "stopbits": settings.serial.stopbits,
                    "parity": settings.serial.parity,
                    "timeout": settings.serial.timeout,
                },
            )
            await self._driver.enable()
            await self._driver.command("SYNC")

            big_coin_priority = await self._repository.get_big_coin_priority()

            if not big_coin_priority:
                # Simple payout
                result = await self._driver.command("PAYOUT_AMOUNT", {
                    "amount": int(amount),
                    "country_code": "RUB",
                    "test": False,
                })
                dispensed = amount if result.get("success") else 0
            else:
                # Denomination-based payout
                dispensed = await self._dispense_by_denomination(amount)

            return dispensed

        except Exception as e:
            logger.error(f"Coin dispense error: {e}")
            return 0
        finally:
            await self._driver.disable()
            if self._driver.port and self._driver.port.is_open:
                await self._driver.close()

    async def _dispense_by_denomination(self, amount: int) -> int:
        """Dispense using specific denominations."""
        all_levels = await self._driver.command("GET_ALL_LEVELS")
        if not all_levels.get("success"):
            return 0

        coin_data = all_levels.get("info", {}).get("counter", {})
        available_coins = sorted(
            [c for c in coin_data.values() if c.get("denomination_level", 0) > 0],
            key=lambda x: x.get("value", 0),
            reverse=True,
        )

        payout_list = []
        remaining = int(amount)

        for coin in available_coins:
            coin_value = coin["value"]
            coin_count = coin["denomination_level"]

            if remaining >= coin_value:
                num = min(remaining // coin_value, coin_count)
                if num > 0:
                    payout_list.append({
                        "number": num,
                        "denomination": coin_value,
                        "country_code": "RUB",
                    })
                    remaining -= num * coin_value

        if payout_list:
            result = await self._driver.command("PAYOUT_BY_DENOMINATION", {
                "value": payout_list,
                "test": False,
            })
            if result.get("success"):
                return amount - remaining

        return 0

    async def add_coins(self, value: int, denomination: int) -> None:
        """Add coins to the hopper inventory."""
        from infrastructure.settings import get_settings
        settings = get_settings()

        try:
            self._driver.open(
                settings.ports.coin_acceptor,
                {
                    "baudrate": settings.serial.baudrate,
                    "bytesize": settings.serial.bytesize,
                    "stopbits": settings.serial.stopbits,
                    "parity": settings.serial.parity,
                    "timeout": settings.serial.timeout,
                },
            )
            await self._driver.command("SYNC")
            await self._driver.command("SET_DENOMINATION_LEVEL", {
                "value": value,
                "denomination": denomination,
                "country_code": "RUB",
            })
        finally:
            if self._driver.port and self._driver.port.is_open:
                await self._driver.disable()
                await self._driver.close()
                await asyncio.sleep(0.1)

    async def get_coin_levels(self) -> dict[str, Any]:
        """Get current coin levels from hopper."""
        from infrastructure.settings import get_settings
        settings = get_settings()

        try:
            self._driver.open(
                settings.ports.coin_acceptor,
                {
                    "baudrate": settings.serial.baudrate,
                    "bytesize": settings.serial.bytesize,
                    "stopbits": settings.serial.stopbits,
                    "parity": settings.serial.parity,
                    "timeout": settings.serial.timeout,
                },
            )
            await self._driver.command("SYNC")
            return await self._driver.command("GET_ALL_LEVELS")
        finally:
            if self._driver.port and self._driver.port.is_open:
                await self._driver.close()
                await asyncio.sleep(0.1)

    async def empty_all(self) -> bool:
        """Empty all coins (cash collection)."""
        from infrastructure.settings import get_settings
        settings = get_settings()

        try:
            self._driver.open(
                settings.ports.coin_acceptor,
                {
                    "baudrate": settings.serial.baudrate,
                    "bytesize": settings.serial.bytesize,
                    "stopbits": settings.serial.stopbits,
                    "parity": settings.serial.parity,
                    "timeout": settings.serial.timeout,
                },
            )
            await self._driver.enable()
            await self._driver.command("SYNC")
            await self._driver.command("EMPTY_ALL")
            return True
        except Exception as e:
            logger.error(f"Empty all error: {e}")
            return False
        finally:
            if self._driver.port and self._driver.port.is_open:
                await self._driver.disable()
                await self._driver.close()
                await asyncio.sleep(0.1)

    async def get_status(self) -> DeviceStateData:
        """Get device status."""
        return DeviceStateData(
            device_type=self._device_type,
            device_name=self._device_name,
            is_connected=self._connected,
        )
