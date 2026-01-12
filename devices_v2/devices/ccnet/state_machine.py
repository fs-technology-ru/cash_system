"""
CCNET State Machine for Bill Validator.

Implements a finite state machine for handling Bill Validator states
based on CCNET Protocol Description page 19 and 38.

The state machine tracks device state transitions and emits events
for significant state changes.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable, Optional, Awaitable, Any

from .constants import (
    DeviceState,
    EventType,
    get_state_name,
    get_bill_amount,
)


logger = logging.getLogger(__name__)


class ValidatorPhase(Enum):
    """
    High-level validator phases.
    
    Groups related DeviceStates into logical phases.
    """
    INITIALIZING = auto()  # Power-up states
    IDLE = auto()          # Ready to accept bills
    PROCESSING = auto()    # Bill being processed (accepting, stacking)
    ESCROW = auto()        # Bill in escrow position
    COMPLETED = auto()     # Bill stacked or returned
    ERROR = auto()         # Error states
    DISABLED = auto()      # Unit disabled


@dataclass
class StateContext:
    """
    Context information for a state transition.
    
    Attributes:
        previous_state: Previous device state.
        current_state: Current device state.
        bill_code: Bill code (if applicable).
        bill_amount: Bill amount in kopecks (if applicable).
        raw_data: Raw response data.
    """
    previous_state: Optional[int]
    current_state: int
    bill_code: Optional[int] = None
    bill_amount: int = 0
    raw_data: bytes = b''


# Type alias for event callbacks
EventCallback = Callable[[str, StateContext], Awaitable[None]]


class BillValidatorStateMachine:
    """
    State machine for Bill Validator.
    
    Tracks state transitions and emits events for:
    - Bill escrow (bill waiting for STACK/RETURN decision)
    - Bill stacked (bill accepted and stored)
    - Bill returned (bill rejected/returned)
    - Error states (cassette full, jammed, etc.)
    
    Attributes:
        current_state: Current device state code.
        previous_state: Previous device state code.
        state_history: List of recent states (for debugging).
    """
    
    # Maximum states to keep in history
    HISTORY_SIZE = 10
    
    # States that indicate bill processing
    PROCESSING_STATES = {
        DeviceState.ACCEPTING,
        DeviceState.STACKING,
        DeviceState.HOLDING,
    }
    
    # Error states
    ERROR_STATES = {
        DeviceState.DROP_CASSETTE_FULL,
        DeviceState.DROP_CASSETTE_OUT_OF_POSITION,
        DeviceState.VALIDATOR_JAMMED,
        DeviceState.DROP_CASSETTE_JAMMED,
        DeviceState.CHEATED,
        DeviceState.PAUSE,
        DeviceState.GENERIC_FAILURE,
    }
    
    def __init__(self) -> None:
        """Initialize state machine."""
        self._current_state: Optional[int] = None
        self._previous_state: Optional[int] = None
        self._state_history: list[int] = []
        self._callbacks: dict[str, list[EventCallback]] = {}
        self._pending_bill_code: Optional[int] = None
        self._escrow_processed: bool = False
    
    @property
    def current_state(self) -> Optional[int]:
        """Get current device state."""
        return self._current_state
    
    @property
    def previous_state(self) -> Optional[int]:
        """Get previous device state."""
        return self._previous_state
    
    @property
    def state_history(self) -> list[int]:
        """Get state history."""
        return self._state_history.copy()
    
    @property
    def current_phase(self) -> ValidatorPhase:
        """Get current high-level phase."""
        if self._current_state is None:
            return ValidatorPhase.INITIALIZING
        
        state = self._current_state
        
        if state in {
            DeviceState.POWER_UP,
            DeviceState.POWER_UP_WITH_BILL_IN_VALIDATOR,
            DeviceState.POWER_UP_WITH_BILL_IN_STACKER,
            DeviceState.INITIALIZE,
        }:
            return ValidatorPhase.INITIALIZING
        
        if state == DeviceState.IDLING:
            return ValidatorPhase.IDLE
        
        if state in self.PROCESSING_STATES:
            return ValidatorPhase.PROCESSING
        
        if state == DeviceState.ESCROW_POSITION:
            return ValidatorPhase.ESCROW
        
        if state in {DeviceState.BILL_STACKED, DeviceState.BILL_RETURNED}:
            return ValidatorPhase.COMPLETED
        
        if state in self.ERROR_STATES:
            return ValidatorPhase.ERROR
        
        if state == DeviceState.UNIT_DISABLED:
            return ValidatorPhase.DISABLED
        
        return ValidatorPhase.IDLE  # Default
    
    def add_callback(
        self,
        event_type: str,
        callback: EventCallback,
    ) -> None:
        """
        Register a callback for an event type.
        
        Args:
            event_type: Event type (from EventType).
            callback: Async callback function.
        """
        if event_type not in self._callbacks:
            self._callbacks[event_type] = []
        self._callbacks[event_type].append(callback)
    
    def remove_callback(
        self,
        event_type: str,
        callback: EventCallback,
    ) -> None:
        """
        Remove a callback for an event type.
        
        Args:
            event_type: Event type.
            callback: Callback to remove.
        """
        if event_type in self._callbacks:
            try:
                self._callbacks[event_type].remove(callback)
            except ValueError:
                pass
    
    async def _emit_event(
        self,
        event_type: str,
        context: StateContext,
    ) -> None:
        """
        Emit an event to all registered callbacks.
        
        Args:
            event_type: Event type.
            context: State context.
        """
        callbacks = self._callbacks.get(event_type, [])
        for callback in callbacks:
            try:
                await callback(event_type, context)
            except Exception as e:
                logger.error(f"Callback error for {event_type}: {e}")
    
    async def process_state(
        self,
        state_code: int,
        data: bytes = b'',
    ) -> None:
        """
        Process a new state from POLL response.
        
        Updates internal state and emits events for significant transitions.
        
        Args:
            state_code: State code from response.
            data: Additional data bytes (e.g., bill code).
        """
        # Update state tracking
        self._previous_state = self._current_state
        self._current_state = state_code
        
        # Update history
        self._state_history.append(state_code)
        if len(self._state_history) > self.HISTORY_SIZE:
            self._state_history.pop(0)
        
        # Log state change
        state_name = get_state_name(state_code)
        if self._previous_state != state_code:
            prev_name = get_state_name(self._previous_state) if self._previous_state else "None"
            logger.debug(f"State transition: {prev_name} -> {state_name}")
        
        # Build context
        bill_code = data[0] if data and len(data) > 0 else None
        bill_amount = get_bill_amount(bill_code) if bill_code else 0
        
        context = StateContext(
            previous_state=self._previous_state,
            current_state=state_code,
            bill_code=bill_code,
            bill_amount=bill_amount,
            raw_data=data,
        )
        
        # Always emit STATE_CHANGED for debugging
        if self._previous_state != state_code:
            await self._emit_event(EventType.STATE_CHANGED, context)
        
        # Handle specific state transitions
        await self._handle_state_transition(context)
    
    async def _handle_state_transition(
        self,
        context: StateContext,
    ) -> None:
        """
        Handle specific state transitions and emit appropriate events.
        
        Args:
            context: State transition context.
        """
        current = context.current_state
        previous = context.previous_state
        
        # Handle ESCROW - bill waiting for decision
        if current == DeviceState.ESCROW_POSITION:
            if previous != DeviceState.ESCROW_POSITION:
                # New bill in escrow
                self._pending_bill_code = context.bill_code
                self._escrow_processed = False
                bill_code_str = f"0x{context.bill_code:02X}" if context.bill_code is not None else "unknown"
                logger.info(
                    f"Bill in escrow: code={bill_code_str}, "
                    f"amount={context.bill_amount / 100:.2f} RUB"
                )
                await self._emit_event(EventType.BILL_ESCROW, context)
        
        # Handle BILL_STACKED - bill accepted
        elif current == DeviceState.BILL_STACKED:
            if previous != DeviceState.BILL_STACKED and not self._escrow_processed:
                self._escrow_processed = True
                # Use pending bill code if current data is empty
                if context.bill_code is None and self._pending_bill_code is not None:
                    context.bill_code = self._pending_bill_code
                    context.bill_amount = get_bill_amount(self._pending_bill_code)
                
                bill_code_str = f"0x{context.bill_code:02X}" if context.bill_code is not None else "unknown"
                logger.info(
                    f"Bill stacked: code={bill_code_str}, "
                    f"amount={context.bill_amount / 100:.2f} RUB"
                )
                await self._emit_event(EventType.BILL_STACKED, context)
                self._pending_bill_code = None
        
        # Handle BILL_RETURNED
        elif current == DeviceState.BILL_RETURNED:
            if previous != DeviceState.BILL_RETURNED:
                logger.info("Bill returned")
                await self._emit_event(EventType.BILL_RETURNED, context)
                self._pending_bill_code = None
                self._escrow_processed = False
        
        # Handle REJECTING
        elif current == DeviceState.REJECTING:
            if previous != DeviceState.REJECTING:
                logger.info(f"Bill rejected")
                await self._emit_event(EventType.BILL_REJECTED, context)
                self._pending_bill_code = None
                self._escrow_processed = False
        
        # Handle IDLING - reset escrow tracking
        elif current == DeviceState.IDLING:
            if previous in {
                DeviceState.BILL_STACKED,
                DeviceState.BILL_RETURNED,
                DeviceState.REJECTING,
            }:
                # Reset after completing a bill cycle
                self._pending_bill_code = None
                self._escrow_processed = False
        
        # Handle error states
        elif current in self.ERROR_STATES:
            if previous != current:
                logger.error(f"Error state: {get_state_name(current)}")
                await self._emit_event(EventType.ERROR, context)
                
                if current == DeviceState.DROP_CASSETTE_FULL:
                    await self._emit_event(EventType.CASSETTE_FULL, context)
                elif current == DeviceState.DROP_CASSETTE_OUT_OF_POSITION:
                    await self._emit_event(EventType.CASSETTE_REMOVED, context)
    
    def reset(self) -> None:
        """Reset state machine to initial state."""
        self._current_state = None
        self._previous_state = None
        self._state_history.clear()
        self._pending_bill_code = None
        self._escrow_processed = False
