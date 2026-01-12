"""
Device Service - Application service for device management.

Provides high-level operations for device initialization, status, and control.
"""

from typing import Any, Optional

from redis.asyncio import Redis

from core.interfaces import DeviceType
from core.exceptions import DeviceError
from domain.device_manager import DeviceManager
from domain.device_adapters import (
    BillAcceptorAdapter,
    BillDispenserAdapter,
    CoinAcceptorAdapter,
    CoinDispenserAdapter,
)
from infrastructure.redis_repository import (
    BillAcceptorRepository,
    BillDispenserRepository,
    CoinSystemRepository,
    PaymentStateRepository,
)
from infrastructure.settings import get_settings
from event_system import EventPublisher
from loggers import logger


class DeviceService:
    """
    Application service for device management.

    Handles device initialization, status queries, and configuration.
    """

    def __init__(
        self,
        redis: Redis,
        event_publisher: EventPublisher,
    ) -> None:
        """
        Initialize the device service.

        Args:
            redis: Redis client for state persistence.
            event_publisher: Publisher for device events.
        """
        self._redis = redis
        self._event_publisher = event_publisher
        self._settings = get_settings()

        # Repositories
        self._bill_acceptor_repo = BillAcceptorRepository(redis)
        self._bill_dispenser_repo = BillDispenserRepository(redis)
        self._coin_system_repo = CoinSystemRepository(redis)
        self._payment_repo = PaymentStateRepository(redis)

        # Device manager
        self.device_manager = DeviceManager()

        # Device adapters (initialized lazily)
        self._bill_acceptor: Optional[BillAcceptorAdapter] = None
        self._bill_dispenser: Optional[BillDispenserAdapter] = None
        self._coin_acceptor: Optional[CoinAcceptorAdapter] = None
        self._coin_dispenser: Optional[CoinDispenserAdapter] = None

    async def initialize_devices(self) -> dict[str, Any]:
        """
        Initialize all payment devices.

        Creates device adapters and connects to hardware.

        Returns:
            Dictionary with success status and device info.
        """
        logger.info("Initializing payment devices...")

        # Create device adapters and register with manager
        await self._create_device_adapters()

        # Initialize all registered devices
        results = await self.device_manager.initialize_all()

        # Check against expected devices
        available = await self._payment_repo.get_available_devices()
        connected = self.device_manager.get_connected_device_names()

        if available.issubset(connected):
            logger.info("All expected devices initialized successfully")
            return {
                "success": True,
                "message": "Payment devices initialized successfully",
                "devices": list(connected),
            }
        else:
            missing = available - connected
            logger.error(f"Failed to initialize devices: {missing}")
            return {
                "success": False,
                "message": f"Failed to initialize devices: {missing}",
                "devices": list(connected),
                "missing": list(missing),
            }

    async def _create_device_adapters(self) -> None:
        """Create and register device adapters."""

        # Bill Acceptor
        try:
            bill_acceptor_driver = await self._create_bill_acceptor_driver()
            if bill_acceptor_driver:
                self._bill_acceptor = BillAcceptorAdapter(
                    driver=bill_acceptor_driver,
                    repository=self._bill_acceptor_repo,
                )
                self.device_manager.register_device(self._bill_acceptor)
        except Exception as e:
            logger.error(f"Error creating bill acceptor adapter: {e}")

        # Bill Dispenser
        try:
            from devices.bill_dispenser.bill_dispenser import Clcdm2000
            dispenser_driver = Clcdm2000()
            self._bill_dispenser = BillDispenserAdapter(
                driver=dispenser_driver,
                repository=self._bill_dispenser_repo,
            )
            self.device_manager.register_device(self._bill_dispenser)
        except Exception as e:
            logger.error(f"Error creating bill dispenser adapter: {e}")

        # Coin Acceptor (ccTalk)
        try:
            from devices.cctalk_coin_acceptor import CcTalkAcceptor
            cctalk_driver = CcTalkAcceptor(self._event_publisher)
            self._coin_acceptor = CoinAcceptorAdapter(driver=cctalk_driver)
            self.device_manager.register_device(self._coin_acceptor)
        except Exception as e:
            logger.error(f"Error creating coin acceptor adapter: {e}")

        # Coin Dispenser (SSP Hopper)
        try:
            from devices.coin_acceptor.index import SSP
            ssp_driver = SSP(self._event_publisher)
            self._coin_dispenser = CoinDispenserAdapter(
                driver=ssp_driver,
                repository=self._coin_system_repo,
            )
            self.device_manager.register_device(self._coin_dispenser)
        except Exception as e:
            logger.error(f"Error creating coin dispenser adapter: {e}")

    async def _create_bill_acceptor_driver(self) -> Optional[Any]:
        """Create the appropriate bill acceptor driver based on firmware version."""
        firmware = await self._bill_acceptor_repo.get_firmware_version()

        if firmware == "v1":
            from devices.bill_acceptor import bill_acceptor_v1
            return bill_acceptor_v1.BillAcceptor(
                self._settings.ports.bill_acceptor,
                self._event_publisher,
                self._redis,
            )
        elif firmware in ("v2", "v3"):
            from devices.bill_acceptor import bill_acceptor_v3
            return bill_acceptor_v3.BillAcceptor(
                self._settings.ports.bill_acceptor,
                self._event_publisher,
                self._redis,
            )
        else:
            logger.warning(f"Unknown bill acceptor firmware: {firmware}")
            return None

    async def shutdown(self) -> None:
        """Shutdown all devices."""
        await self.device_manager.shutdown_all()

    # =========================================================================
    # Bill Acceptor Operations
    # =========================================================================

    async def get_bill_acceptor_status(self) -> dict[str, Any]:
        """Get bill acceptor status."""
        try:
            state = await self._bill_acceptor_repo.get_state()
            return {
                "success": True,
                "message": "Bill acceptor status retrieved successfully",
                "data": {
                    "max_bill_count": state.max_bill_count,
                    "bill_count": state.bill_count,
                    "is_full": state.is_full,
                },
            }
        except Exception as e:
            logger.error(f"Error getting bill acceptor status: {e}")
            return {"success": False, "message": str(e)}

    async def set_max_bill_count(self, count: int) -> dict[str, Any]:
        """Set maximum bill count for acceptor."""
        try:
            await self._bill_acceptor_repo.set_max_bill_count(count)
            return {"success": True, "message": "Maximum bill count set successfully"}
        except Exception as e:
            logger.error(f"Error setting max bill count: {e}")
            return {"success": False, "message": str(e)}

    async def reset_bill_count(self) -> dict[str, Any]:
        """Reset bill count to zero (cash collection)."""
        try:
            await self._bill_acceptor_repo.reset_bill_count()
            return {"success": True, "message": "Bill count reset successfully"}
        except Exception as e:
            logger.error(f"Error resetting bill count: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Bill Dispenser Operations
    # =========================================================================

    async def get_bill_dispenser_status(self) -> dict[str, Any]:
        """Get bill dispenser status."""
        try:
            state = await self._bill_dispenser_repo.get_state()
            return {
                "success": True,
                "message": "Bill dispenser status retrieved successfully",
                "data": {
                    "upper_box_value": state.upper_box_value * 100,
                    "lower_box_value": state.lower_box_value * 100,
                    "upper_box_count": state.upper_box_count,
                    "lower_box_count": state.lower_box_count,
                },
            }
        except Exception as e:
            logger.error(f"Error getting bill dispenser status: {e}")
            return {"success": False, "message": str(e)}

    async def set_bill_dispenser_denominations(
        self,
        upper_lvl: int,
        lower_lvl: int,
    ) -> dict[str, Any]:
        """Set bill dispenser box denominations."""
        try:
            await self._bill_dispenser_repo.set_denominations(upper_lvl, lower_lvl)
            return {"success": True, "message": "Bill dispenser denominations set successfully"}
        except Exception as e:
            logger.error(f"Error setting dispenser denominations: {e}")
            return {"success": False, "message": str(e)}

    async def add_bills_to_dispenser(
        self,
        upper_count: int,
        lower_count: int,
    ) -> dict[str, Any]:
        """Add bills to dispenser counts."""
        try:
            await self._bill_dispenser_repo.add_bills(upper_count, lower_count)
            return {"success": True, "message": "Bill dispenser count updated successfully"}
        except Exception as e:
            logger.error(f"Error adding bills to dispenser: {e}")
            return {"success": False, "message": str(e)}

    async def reset_bill_dispenser_count(self) -> dict[str, Any]:
        """Reset bill dispenser counts to zero."""
        try:
            await self._bill_dispenser_repo.reset_counts()
            return {"success": True, "message": "Bill dispenser count reset successfully"}
        except Exception as e:
            logger.error(f"Error resetting dispenser count: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Coin System Operations
    # =========================================================================

    async def get_coin_system_status(self) -> dict[str, Any]:
        """Get coin hopper status."""
        try:
            if self._coin_dispenser:
                levels = await self._coin_dispenser.get_coin_levels()
                return {
                    "success": True,
                    "data": levels,
                    "message": "Hopper status retrieved successfully",
                }
            return {"success": False, "message": "Coin dispenser not available"}
        except Exception as e:
            logger.error(f"Error getting coin status: {e}")
            return {"success": False, "message": str(e)}

    async def add_coins(self, value: int, denomination: int) -> dict[str, Any]:
        """Add coins to the hopper."""
        try:
            if self._coin_dispenser:
                await self._coin_dispenser.add_coins(value, denomination)
                return {"success": True, "message": "Coins added successfully"}
            return {"success": False, "message": "Coin dispenser not available"}
        except Exception as e:
            logger.error(f"Error adding coins: {e}")
            return {"success": False, "message": str(e)}

    async def cash_collection(self) -> dict[str, Any]:
        """Perform cash collection from hopper."""
        try:
            if self._coin_dispenser:
                success = await self._coin_dispenser.empty_all()
                if success:
                    return {"success": True, "message": "Cash collection started successfully"}
            return {"success": False, "message": "Cash collection failed"}
        except Exception as e:
            logger.error(f"Error during cash collection: {e}")
            return {"success": False, "message": str(e)}
