"""
Device Manager - Central registry and lifecycle management for devices.

Provides unified access to all payment devices and manages their lifecycle.
"""

from __future__ import annotations

from typing import Any, Optional

from core.interfaces import Device, DeviceType
from core.exceptions import DeviceNotFoundError
from loggers import logger


# =============================================================================
# Device Registry
# =============================================================================


class DeviceRegistry:
    """
    Registry for payment devices.

    Maintains a collection of devices by type and name for easy access.
    """

    def __init__(self) -> None:
        """Initialize the registry."""
        self._devices: dict[str, Device] = {}
        self._by_type: dict[DeviceType, list[Device]] = {}

    def register(self, device: Device) -> None:
        """
        Register a device.

        Args:
            device: Device to register.
        """
        name = device.device_name
        device_type = device.device_type

        self._devices[name] = device

        if device_type not in self._by_type:
            self._by_type[device_type] = []
        self._by_type[device_type].append(device)

        logger.debug(f"Registered device: {name} ({device_type.name})")

    def unregister(self, name: str) -> Optional[Device]:
        """
        Unregister a device by name.

        Args:
            name: Device name.

        Returns:
            The unregistered device, or None if not found.
        """
        device = self._devices.pop(name, None)
        if device:
            device_type = device.device_type
            if device_type in self._by_type:
                self._by_type[device_type] = [
                    d for d in self._by_type[device_type]
                    if d.device_name != name
                ]
        return device

    def get(self, name: str) -> Optional[Device]:
        """
        Get a device by name.

        Args:
            name: Device name.

        Returns:
            Device or None if not found.
        """
        return self._devices.get(name)

    def get_by_type(self, device_type: DeviceType) -> list[Device]:
        """
        Get all devices of a specific type.

        Args:
            device_type: Type of device.

        Returns:
            List of devices.
        """
        return self._by_type.get(device_type, [])

    def get_all(self) -> list[Device]:
        """Get all registered devices."""
        return list(self._devices.values())

    def get_connected(self) -> list[Device]:
        """Get all connected devices."""
        return [d for d in self._devices.values() if d.is_connected]

    def get_names(self) -> set[str]:
        """Get set of all device names."""
        return set(self._devices.keys())

    def __contains__(self, name: str) -> bool:
        """Check if a device is registered."""
        return name in self._devices

    def __len__(self) -> int:
        """Get number of registered devices."""
        return len(self._devices)


# =============================================================================
# Device Manager
# =============================================================================


class DeviceManager:
    """
    Manager for payment device lifecycle.

    Handles initialization, connection, and shutdown of all devices.
    Provides unified access through the device registry.
    """

    # Device name constants
    BILL_ACCEPTOR = "bill_acceptor"
    BILL_DISPENSER = "bill_dispenser"
    COIN_ACCEPTOR = "coin_acceptor"
    COIN_DISPENSER = "coin_dispenser"

    def __init__(self) -> None:
        """Initialize the device manager."""
        self.registry = DeviceRegistry()
        self._initialized = False
        self._active_acceptors: set[str] = set()
        self._active_dispensers: set[str] = set()

    def register_device(self, device: Device) -> None:
        """Register a device with the manager."""
        self.registry.register(device)

    async def initialize_all(self) -> dict[str, bool]:
        """
        Initialize all registered devices.

        Returns:
            Dictionary of device name to success status.
        """
        results: dict[str, bool] = {}

        for device in self.registry.get_all():
            name = device.device_name
            try:
                success = await device.connect()
                results[name] = success
                logger.info(f"Device {name}: {'connected' if success else 'failed'}")
            except Exception as e:
                results[name] = False
                logger.error(f"Device {name} initialization error: {e}")

        self._initialized = True
        return results

    async def shutdown_all(self) -> None:
        """Disconnect all devices."""
        for device in self.registry.get_all():
            try:
                await device.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting {device.device_name}: {e}")

        self._active_acceptors.clear()
        self._active_dispensers.clear()
        self._initialized = False

    def get_device(self, name: str) -> Device:
        """
        Get a device by name.

        Args:
            name: Device name.

        Returns:
            Device instance.

        Raises:
            DeviceNotFoundError: If device not found.
        """
        device = self.registry.get(name)
        if device is None:
            raise DeviceNotFoundError(f"Device not found: {name}", device_name=name)
        return device

    def get_bill_acceptor(self) -> Any:
        """Get the bill acceptor device."""
        return self.registry.get(self.BILL_ACCEPTOR)

    def get_bill_dispenser(self) -> Any:
        """Get the bill dispenser device."""
        return self.registry.get(self.BILL_DISPENSER)

    def get_coin_acceptor(self) -> Any:
        """Get the coin acceptor device."""
        return self.registry.get(self.COIN_ACCEPTOR)

    def get_coin_dispenser(self) -> Any:
        """Get the coin dispenser device."""
        return self.registry.get(self.COIN_DISPENSER)

    def get_connected_device_names(self) -> set[str]:
        """Get names of all connected devices."""
        return {d.device_name for d in self.registry.get_connected()}

    def get_acceptor_devices(self) -> list[Any]:
        """Get all acceptor devices (bill and coin)."""
        devices = []
        for name in [self.BILL_ACCEPTOR, self.COIN_ACCEPTOR]:
            device = self.registry.get(name)
            if device and device.is_connected:
                devices.append(device)
        return devices

    def get_dispenser_devices(self) -> list[Any]:
        """Get all dispenser devices (bill and coin)."""
        devices = []
        for name in [self.BILL_DISPENSER, self.COIN_DISPENSER]:
            device = self.registry.get(name)
            if device and device.is_connected:
                devices.append(device)
        return devices

    async def enable_acceptors(self) -> list[str]:
        """
        Enable all acceptor devices.

        Returns:
            List of enabled device names.
        """
        enabled = []
        errors = []

        for device in self.get_acceptor_devices():
            try:
                if hasattr(device, "enable_accepting"):
                    await device.enable_accepting()
                    enabled.append(device.device_name)
                    self._active_acceptors.add(device.device_name)
            except Exception as e:
                errors.append(f"{device.device_name}: {e}")
                logger.error(f"Error enabling {device.device_name}: {e}")

        return enabled

    async def disable_acceptors(self) -> None:
        """Disable all acceptor devices."""
        for device in self.get_acceptor_devices():
            try:
                if hasattr(device, "disable_accepting"):
                    await device.disable_accepting()
            except Exception as e:
                logger.error(f"Error disabling {device.device_name}: {e}")

        self._active_acceptors.clear()

    @property
    def active_device_names(self) -> set[str]:
        """Get names of currently active devices."""
        return self._active_acceptors | self._active_dispensers

    @property
    def is_initialized(self) -> bool:
        """Check if manager has been initialized."""
        return self._initialized
