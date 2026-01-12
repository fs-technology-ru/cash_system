"""
Domain layer - Business logic and domain models.

Contains:
- Device wrappers with unified interface
- Domain services
- Business logic
"""

from .device_manager import (
    DeviceManager,
    DeviceRegistry,
)
from .payment_state_machine import (
    PaymentStateMachine,
    PaymentPhase,
)
from .device_adapters import (
    BillAcceptorAdapter,
    BillDispenserAdapter,
    CoinAcceptorAdapter,
    CoinDispenserAdapter,
)


__all__ = [
    # Device Management
    "DeviceManager",
    "DeviceRegistry",
    # Payment State
    "PaymentStateMachine",
    "PaymentPhase",
    # Device Adapters
    "BillAcceptorAdapter",
    "BillDispenserAdapter",
    "CoinAcceptorAdapter",
    "CoinDispenserAdapter",
]
