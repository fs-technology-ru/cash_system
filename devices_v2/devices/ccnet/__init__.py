"""
CCNET Protocol Driver Package.

Async driver for CashCode NET (CCNET) compatible bill validators,
including Creator C100-B20.

Example:
    import asyncio
    from ccnet import CashCodeDriver, EventType

    async def on_bill_stacked(event_type: str, context):
        print(f"Bill accepted: {context.bill_amount / 100} RUB")

    async def main():
        driver = CashCodeDriver(port='/dev/ttyUSB0')
        driver.add_callback(EventType.BILL_STACKED, on_bill_stacked)
        
        await driver.connect()
        await driver.enable_validator()
        
        await asyncio.Future()  # Run forever

    asyncio.run(main())
"""

from .constants import (
    Command,
    DeviceState,
    EventType,
    RejectionReason,
    BILL_DENOMINATIONS,
    DEFAULT_DEVICE_ADDRESS,
    POLL_INTERVAL_MS,
    get_state_name,
    get_bill_amount,
)
from .crc import (
    calculate_crc16,
    verify_crc16,
    append_crc,
)
from .transport import (
    CCNETPacket,
    CCNETTransport,
)
from .protocol import (
    CCNETProtocol,
    PollResponse,
)
from .state_machine import (
    BillValidatorStateMachine,
    StateContext,
    ValidatorPhase,
)
from .driver import (
    CashCodeDriver,
)


__all__ = [
    # Main driver
    'CashCodeDriver',
    
    # Constants and enums
    'Command',
    'DeviceState',
    'EventType',
    'RejectionReason',
    'ValidatorPhase',
    'BILL_DENOMINATIONS',
    'DEFAULT_DEVICE_ADDRESS',
    'POLL_INTERVAL_MS',
    
    # Utility functions
    'get_state_name',
    'get_bill_amount',
    'calculate_crc16',
    'verify_crc16',
    'append_crc',
    
    # Protocol components
    'CCNETPacket',
    'CCNETTransport',
    'CCNETProtocol',
    'PollResponse',
    
    # State machine
    'BillValidatorStateMachine',
    'StateContext',
]

__version__ = '2.0.0'
