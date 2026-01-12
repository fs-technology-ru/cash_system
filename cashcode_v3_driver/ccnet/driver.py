"""
CCNET Bill Validator Driver (Application Layer).

High-level async driver for Creator C100 and compatible bill validators
using CCNET (CashCode NET) protocol.

This is the main entry point for application code.

Example:
    import asyncio
    from ccnet.driver import CashCodeDriver

    async def on_bill_stacked(event_type: str, context):
        print(f"Bill accepted: {context.bill_amount / 100} RUB")

    async def main():
        driver = CashCodeDriver(port='/dev/ttyUSB0', baudrate=9600)
        driver.add_callback("BILL_STACKED", on_bill_stacked)
        
        await driver.connect()
        await driver.enable_validator()
        
        # Keep running
        await asyncio.Future()

    asyncio.run(main())
"""

import asyncio
import logging
from typing import Callable, Awaitable, Optional, Any

import serial_asyncio

from .constants import (
    Command,
    DeviceState,
    EventType,
    DEFAULT_DEVICE_ADDRESS,
    POLL_INTERVAL_MS,
    get_state_name,
    get_bill_amount,
)
from .transport import CCNETTransport
from .protocol import CCNETProtocol, PollResponse
from .state_machine import BillValidatorStateMachine, StateContext


logger = logging.getLogger(__name__)


# Type alias for event callbacks
EventCallback = Callable[[str, StateContext], Awaitable[None]]


class CashCodeDriver:
    """
    Async driver for CCNET-compatible bill validators.
    
    Features:
    - Asynchronous I/O using pyserial-asyncio
    - Event-driven architecture with callbacks
    - Automatic polling loop
    - State machine for bill processing
    
    Attributes:
        port: Serial port path.
        baudrate: Serial baudrate (default 9600).
        address: Device address (default 0x03 for Bill Validator).
    """
    
    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        address: int = DEFAULT_DEVICE_ADDRESS,
        auto_stack: bool = True,
    ) -> None:
        """
        Initialize the driver.
        
        Args:
            port: Serial port path (e.g., '/dev/ttyUSB0').
            baudrate: Serial port baudrate (default 9600).
            address: CCNET device address (default 0x03).
            auto_stack: Automatically stack bills in escrow (default True).
        """
        self._port = port
        self._baudrate = baudrate
        self._address = address
        self._auto_stack = auto_stack
        
        # Components (initialized on connect)
        self._transport: Optional[CCNETTransport] = None
        self._protocol: Optional[CCNETProtocol] = None
        self._state_machine = BillValidatorStateMachine()
        
        # State tracking
        self._connected = False
        self._accepting_enabled = False
        self._poll_task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        
        # Callbacks
        self._callbacks: dict[str, list[EventCallback]] = {}
    
    @property
    def port(self) -> str:
        """Get serial port path."""
        return self._port
    
    @property
    def baudrate(self) -> int:
        """Get serial baudrate."""
        return self._baudrate
    
    @property
    def address(self) -> int:
        """Get device address."""
        return self._address
    
    @property
    def is_connected(self) -> bool:
        """Check if driver is connected."""
        return self._connected
    
    @property
    def is_accepting(self) -> bool:
        """Check if bill acceptance is enabled."""
        return self._accepting_enabled
    
    @property
    def current_state(self) -> Optional[int]:
        """Get current device state."""
        return self._state_machine.current_state
    
    @property
    def current_state_name(self) -> str:
        """Get current device state name."""
        state = self._state_machine.current_state
        return get_state_name(state) if state else "UNKNOWN"
    
    def add_callback(
        self,
        event_type: str,
        callback: EventCallback,
    ) -> None:
        """
        Register a callback for an event type.
        
        Event types (from EventType):
        - CONNECTED: Driver connected to device
        - DISCONNECTED: Driver disconnected
        - BILL_ESCROW: Bill in escrow, waiting for decision
        - BILL_STACKED: Bill accepted and stored
        - BILL_RETURNED: Bill returned to customer
        - BILL_REJECTED: Bill rejected
        - STATE_CHANGED: Device state changed
        - ERROR: Error occurred
        - CASSETTE_FULL: Cash cassette is full
        - CASSETTE_REMOVED: Cash cassette removed
        
        Args:
            event_type: Event type string.
            callback: Async callback function(event_type, context).
        """
        if event_type not in self._callbacks:
            self._callbacks[event_type] = []
        self._callbacks[event_type].append(callback)
        
        # Also register with state machine for state-related events
        self._state_machine.add_callback(event_type, callback)
    
    def remove_callback(
        self,
        event_type: str,
        callback: EventCallback,
    ) -> None:
        """
        Remove a callback.
        
        Args:
            event_type: Event type.
            callback: Callback to remove.
        """
        if event_type in self._callbacks:
            try:
                self._callbacks[event_type].remove(callback)
            except ValueError:
                pass
        
        self._state_machine.remove_callback(event_type, callback)
    
    async def _emit_event(
        self,
        event_type: str,
        context: Optional[StateContext] = None,
    ) -> None:
        """
        Emit an event to all registered callbacks.
        
        Args:
            event_type: Event type.
            context: Optional state context.
        """
        if context is None:
            context = StateContext(
                previous_state=None,
                current_state=self._state_machine.current_state or 0,
            )
        
        callbacks = self._callbacks.get(event_type, [])
        for callback in callbacks:
            try:
                await callback(event_type, context)
            except Exception as e:
                logger.error(f"Callback error for {event_type}: {e}")
    
    async def connect(self) -> bool:
        """
        Connect to the bill validator.
        
        Opens serial port, sends RESET, and waits for device to initialize.
        
        Returns:
            True if connection successful.
        """
        if self._connected:
            logger.warning("Already connected")
            return True
        
        try:
            logger.info(f"Connecting to {self._port} at {self._baudrate} baud")
            
            # Open serial connection
            reader, writer = await serial_asyncio.open_serial_connection(
                url=self._port,
                baudrate=self._baudrate,
            )
            
            # Initialize layers
            self._transport = CCNETTransport(reader, writer, self._address)
            self._protocol = CCNETProtocol(self._transport)
            
            # Test connection with POLL
            response = await self._protocol.poll()
            if not response:
                logger.error("No response from device during initialization")
                await self._cleanup()
                return False
            
            logger.info(f"Device connected, initial state: {response.state_name}")
            
            # Send RESET and wait for device to be ready
            logger.info("Sending RESET command...")
            await self._protocol.reset()
            
            # Wait for device to complete initialization
            logger.info("Waiting for device initialization...")
            max_init_polls = 50  # Max polls (~10 seconds)
            initialized = False
            
            for _ in range(max_init_polls):
                response = await self._protocol.poll()
                if response:
                    logger.debug(f"Init poll: {response.state_name} (0x{response.state:02X})")
                    
                    # Device is ready when in IDLING or UNIT_DISABLED state
                    if response.state in (DeviceState.IDLING, DeviceState.UNIT_DISABLED):
                        initialized = True
                        logger.info(f"Device ready, state: {response.state_name}")
                        break
                
                await asyncio.sleep(0.2)
            
            if not initialized:
                logger.warning("Device did not reach ready state, continuing anyway...")
            
            self._connected = True
            self._stop_event.clear()
            
            await self._emit_event(EventType.CONNECTED)
            
            return True
            
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            await self._cleanup()
            return False
    
    async def disconnect(self) -> None:
        """Disconnect from the bill validator."""
        if not self._connected:
            return
        
        logger.info("Disconnecting...")
        
        # Stop polling
        await self.stop()
        
        # Cleanup
        await self._cleanup()
        
        self._connected = False
        await self._emit_event(EventType.DISCONNECTED)
    
    async def _cleanup(self) -> None:
        """Clean up resources."""
        if self._protocol:
            try:
                await self._protocol.close()
            except Exception as e:
                logger.debug(f"Close error: {e}")
        
        self._transport = None
        self._protocol = None
        self._state_machine.reset()
    
    async def reset(self) -> bool:
        """
        Reset the bill validator.
        
        Returns:
            True if reset successful.
        """
        if not self._protocol:
            logger.error("Not connected")
            return False
        
        logger.info("Resetting device...")
        
        # Stop polling if running
        was_accepting = self._accepting_enabled
        if was_accepting:
            await self.stop()
        
        # Send reset command
        result = await self._protocol.reset()
        
        if result:
            self._state_machine.reset()
            logger.info("Device reset complete")
        
        return result
    
    async def enable_validator(self) -> bool:
        """
        Enable bill acceptance and start polling loop.
        
        Follows the initialization sequence from PDF page 53:
        1. Send SET SECURITY (32H)
        2. Send ENABLE BILL TYPES (34H)
        
        Note: RESET is done in connect(), so we skip it here.
        
        Returns:
            True if enabled successfully.
        """
        if not self._protocol:
            logger.error("Not connected")
            return False
        
        if self._accepting_enabled:
            logger.warning("Already accepting")
            return True
        
        logger.info("Enabling bill acceptance...")
        
        # Send SET SECURITY command (PDF page 18)
        logger.info("Sending SET SECURITY command...")
        security_result = await self._protocol.set_security()
        if not security_result:
            logger.error("Failed to set security")
            return False
        
        # Send ENABLE BILL TYPES command (PDF page 20)
        logger.info("Sending ENABLE BILL TYPES command...")
        enable_result = await self._protocol.enable_bill_types()
        if not enable_result:
            logger.error("Failed to enable bill types")
            return False
        
        self._accepting_enabled = True
        
        # Start polling loop
        self._stop_event.clear()
        self._poll_task = asyncio.create_task(self._poll_loop())
        
        logger.info("Bill acceptance enabled successfully")
        return True
    
    async def _re_enable_bill_types(self) -> bool:
        """
        Re-enable bill types after device goes to UNIT_DISABLED.
        
        This is called automatically when the device transitions to
        UNIT_DISABLED during the polling loop (e.g., after a bill rejection).
        
        Returns:
            True if re-enabled successfully.
        """
        if not self._protocol:
            return False
        
        logger.info("Re-enabling bill types after UNIT_DISABLED...")
        
        # Send SET SECURITY command
        security_result = await self._protocol.set_security()
        if not security_result:
            logger.error("Failed to re-set security")
            return False
        
        # Send ENABLE BILL TYPES command
        enable_result = await self._protocol.enable_bill_types()
        if not enable_result:
            logger.error("Failed to re-enable bill types")
            return False
        
        logger.info("Bill types re-enabled successfully")
        return True
    
    async def disable_validator(self) -> bool:
        """
        Disable bill acceptance.
        
        Returns:
            True if disabled successfully.
        """
        if not self._protocol:
            logger.error("Not connected")
            return False
        
        logger.info("Disabling bill acceptance...")
        
        # Send disable command
        result = await self._protocol.disable_bill_types()
        
        self._accepting_enabled = False
        
        logger.info("Bill acceptance disabled")
        return True
    
    async def start(self) -> None:
        """
        Start the polling loop.
        
        Equivalent to enable_validator().
        """
        await self.enable_validator()
    
    async def stop(self) -> None:
        """
        Stop the polling loop and disable acceptance.
        """
        logger.info("Stopping...")
        
        self._stop_event.set()
        self._accepting_enabled = False
        
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None
        
        # Disable bill types
        if self._protocol:
            await self._protocol.disable_bill_types()
        
        logger.info("Stopped")
    
    async def stack_bill(self) -> bool:
        """
        Stack the bill currently in escrow.
        
        Returns:
            True if command sent successfully.
        """
        if not self._protocol:
            logger.error("Not connected")
            return False
        
        return await self._protocol.stack()
    
    async def return_bill(self) -> bool:
        """
        Return the bill currently in escrow.
        
        Returns:
            True if command sent successfully.
        """
        if not self._protocol:
            logger.error("Not connected")
            return False
        
        return await self._protocol.return_bill()
    
    async def _poll_loop(self) -> None:
        """
        Main polling loop.
        
        Continuously polls the device and processes responses.
        """
        logger.info("Poll loop started")
        poll_interval = POLL_INTERVAL_MS / 1000.0
        
        try:
            while not self._stop_event.is_set():
                try:
                    # Poll device
                    response = await self._protocol.poll()
                    
                    if response:
                        await self._handle_poll_response(response)
                    
                    # Wait for next poll
                    await asyncio.sleep(poll_interval)
                    
                except asyncio.CancelledError:
                    logger.debug("Poll loop cancelled")
                    break
                except Exception as e:
                    logger.error(f"Poll error: {e}")
                    await asyncio.sleep(1.0)  # Back off on error
                    
        finally:
            logger.info("Poll loop stopped")
    
    async def _handle_poll_response(self, response: PollResponse) -> None:
        """
        Handle a poll response.
        
        Updates state machine, handles escrow auto-stacking, and
        automatically re-enables bill types when device goes to UNIT_DISABLED.
        
        Args:
            response: Poll response from device.
        """
        previous_state = self._state_machine.current_state
        
        # Update state machine
        await self._state_machine.process_state(response.state, response.data)
        
        # Auto-stack if enabled and bill is in escrow
        if (
            self._auto_stack
            and self._accepting_enabled
            and response.state == DeviceState.ESCROW_POSITION
            and previous_state != DeviceState.ESCROW_POSITION
        ):
            logger.debug("Auto-stacking bill")
            await self._protocol.stack()
        
        # Auto re-enable if device goes to UNIT_DISABLED while we should be accepting
        if (
            self._accepting_enabled
            and response.state == DeviceState.UNIT_DISABLED
            and previous_state not in (None, DeviceState.UNIT_DISABLED)
        ):
            logger.info("Device went to UNIT_DISABLED, re-enabling bill types...")
            await self._re_enable_bill_types()
    
    async def get_status(self) -> Optional[bytes]:
        """
        Get device status.
        
        Returns:
            Status bytes or None.
        """
        if not self._protocol:
            return None
        return await self._protocol.get_status()
    
    async def get_identification(self) -> Optional[str]:
        """
        Get device identification string.
        
        Returns:
            Identification string or None.
        """
        if not self._protocol:
            return None
        
        data = await self._protocol.get_identification()
        if data:
            try:
                return data.decode('ascii', errors='ignore').strip()
            except Exception:
                return data.hex(' ')
        return None
    
    async def __aenter__(self) -> 'CashCodeDriver':
        """Async context manager entry."""
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.disconnect()
