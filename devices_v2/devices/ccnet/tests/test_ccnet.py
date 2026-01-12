"""
Unit tests for CCNET protocol implementation.

Tests CRC calculation, packet building, and state machine behavior.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from ccnet.constants import (
    Command,
    DeviceState,
    EventType,
    SYNC_BYTE,
    DEFAULT_DEVICE_ADDRESS,
    CRC_POLYNOMIAL,
    get_state_name,
    get_bill_amount,
    BILL_DENOMINATIONS,
)
from ccnet.crc import (
    calculate_crc16,
    verify_crc16,
    append_crc,
)
from ccnet.transport import CCNETPacket
from ccnet.state_machine import (
    BillValidatorStateMachine,
    StateContext,
    ValidatorPhase,
)


class TestCRC:
    """Tests for CRC16 CCITT calculation."""
    
    def test_crc16_poll_command(self):
        """Test CRC for POLL command packet."""
        # POLL command: SYNC(0x02) + ADR(0x03) + LNG(0x06) + CMD(0x33)
        data = bytes([0x02, 0x03, 0x06, 0x33])
        crc = calculate_crc16(data)
        
        # CRC should be 2 bytes in little-endian
        assert len(crc) == 2
        
        # Complete packet with CRC should verify
        complete = data + crc
        assert verify_crc16(complete)
    
    def test_crc16_reset_command(self):
        """Test CRC for RESET command packet."""
        # RESET command: SYNC(0x02) + ADR(0x03) + LNG(0x06) + CMD(0x30)
        data = bytes([0x02, 0x03, 0x06, 0x30])
        crc = calculate_crc16(data)
        
        complete = data + crc
        assert verify_crc16(complete)
    
    def test_crc16_verify_valid(self):
        """Test CRC verification of valid packet."""
        # Known valid packet (POLL with CRC)
        data = bytes([0x02, 0x03, 0x06, 0x33])
        crc = calculate_crc16(data)
        complete = data + crc
        
        assert verify_crc16(complete) is True
    
    def test_crc16_verify_invalid(self):
        """Test CRC verification rejects invalid packet."""
        # Corrupted packet
        packet = bytes([0x02, 0x03, 0x06, 0x33, 0x00, 0x00])
        assert verify_crc16(packet) is False
    
    def test_crc16_verify_too_short(self):
        """Test CRC verification rejects too short packet."""
        packet = bytes([0x02, 0x03, 0x06])
        assert verify_crc16(packet) is False
    
    def test_append_crc(self):
        """Test append_crc function."""
        data = bytes([0x02, 0x03, 0x06, 0x33])
        result = append_crc(data)
        
        assert len(result) == 6
        assert verify_crc16(result)
    
    def test_crc_polynomial(self):
        """Test that polynomial constant is correct."""
        assert CRC_POLYNOMIAL == 0x08408


class TestCCNETPacket:
    """Tests for CCNETPacket class."""
    
    def test_packet_creation(self):
        """Test basic packet creation."""
        packet = CCNETPacket(
            address=0x03,
            command=Command.POLL,
            data=b'',
        )
        
        assert packet.address == 0x03
        assert packet.command == Command.POLL
        assert packet.data == b''
        assert packet.length == 6
    
    def test_packet_with_data(self):
        """Test packet with data bytes."""
        packet = CCNETPacket(
            address=0x03,
            command=Command.ENABLE_BILL_TYPES,
            data=bytes([0xFF, 0xFF, 0xFF, 0x00, 0x00, 0x00]),
        )
        
        assert packet.length == 12
    
    def test_packet_to_bytes(self):
        """Test packet serialization."""
        packet = CCNETPacket(
            address=0x03,
            command=Command.POLL,
        )
        
        data = packet.to_bytes()
        
        assert len(data) == 6
        assert data[0] == SYNC_BYTE
        assert data[1] == 0x03
        assert data[2] == 6
        assert data[3] == Command.POLL
        # Last 2 bytes are CRC
        assert verify_crc16(data)
    
    def test_packet_from_bytes_valid(self):
        """Test packet parsing from valid bytes."""
        # Create a valid packet
        original = CCNETPacket(address=0x03, command=Command.ACK)
        raw = original.to_bytes()
        
        # Parse it back
        parsed = CCNETPacket.from_bytes(raw)
        
        assert parsed is not None
        assert parsed.address == 0x03
        assert parsed.command == Command.ACK
    
    def test_packet_from_bytes_invalid_sync(self):
        """Test packet parsing rejects invalid sync byte."""
        data = bytes([0x00, 0x03, 0x06, 0x33, 0xDA, 0x81])
        packet = CCNETPacket.from_bytes(data)
        assert packet is None
    
    def test_packet_from_bytes_too_short(self):
        """Test packet parsing rejects too short data."""
        data = bytes([0x02, 0x03, 0x06])
        packet = CCNETPacket.from_bytes(data)
        assert packet is None


class TestConstants:
    """Tests for constants and helper functions."""
    
    def test_device_states(self):
        """Test device state enum values."""
        assert DeviceState.IDLING == 0x14
        assert DeviceState.ACCEPTING == 0x15
        assert DeviceState.ESCROW_POSITION == 0x80
        assert DeviceState.BILL_STACKED == 0x81
    
    def test_commands(self):
        """Test command enum values."""
        assert Command.ACK == 0x00
        assert Command.POLL == 0x33
        assert Command.RESET == 0x30
        assert Command.STACK == 0x35
        assert Command.NAK == 0xFF
    
    def test_get_state_name(self):
        """Test state name lookup."""
        assert get_state_name(DeviceState.IDLING) == "IDLING"
        assert get_state_name(DeviceState.ESCROW_POSITION) == "ESCROW_POSITION"
        assert "UNKNOWN" in get_state_name(0x99)
    
    def test_get_bill_amount(self):
        """Test bill amount lookup."""
        assert get_bill_amount(0x06) == 100000  # 1000 RUB
        assert get_bill_amount(0x07) == 500000  # 5000 RUB
        assert get_bill_amount(0x99) == 0  # Unknown
    
    def test_default_address(self):
        """Test default device address."""
        assert DEFAULT_DEVICE_ADDRESS == 0x03


class TestStateMachine:
    """Tests for BillValidatorStateMachine."""
    
    @pytest.fixture
    def state_machine(self):
        """Create a fresh state machine."""
        return BillValidatorStateMachine()
    
    def test_initial_state(self, state_machine):
        """Test initial state machine state."""
        assert state_machine.current_state is None
        assert state_machine.previous_state is None
        assert len(state_machine.state_history) == 0
    
    @pytest.mark.asyncio
    async def test_process_state_idling(self, state_machine):
        """Test processing IDLING state."""
        await state_machine.process_state(DeviceState.IDLING)
        
        assert state_machine.current_state == DeviceState.IDLING
        assert len(state_machine.state_history) == 1
    
    @pytest.mark.asyncio
    async def test_state_transition(self, state_machine):
        """Test state transition tracking."""
        await state_machine.process_state(DeviceState.IDLING)
        await state_machine.process_state(DeviceState.ACCEPTING)
        
        assert state_machine.current_state == DeviceState.ACCEPTING
        assert state_machine.previous_state == DeviceState.IDLING
    
    @pytest.mark.asyncio
    async def test_escrow_callback(self, state_machine):
        """Test ESCROW event callback."""
        callback = AsyncMock()
        state_machine.add_callback(EventType.BILL_ESCROW, callback)
        
        # Process escrow state with bill code
        await state_machine.process_state(
            DeviceState.ESCROW_POSITION,
            bytes([0x06]),  # Bill code for 1000 RUB
        )
        
        callback.assert_called_once()
        call_args = callback.call_args
        assert call_args[0][0] == EventType.BILL_ESCROW
    
    @pytest.mark.asyncio
    async def test_bill_stacked_callback(self, state_machine):
        """Test BILL_STACKED event callback."""
        callback = AsyncMock()
        state_machine.add_callback(EventType.BILL_STACKED, callback)
        
        # First go to escrow
        await state_machine.process_state(
            DeviceState.ESCROW_POSITION,
            bytes([0x06]),
        )
        
        # Then bill is stacked
        await state_machine.process_state(
            DeviceState.BILL_STACKED,
            bytes([0x06]),
        )
        
        callback.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_state_history_limit(self, state_machine):
        """Test state history is limited."""
        for i in range(20):
            await state_machine.process_state(0x10 + (i % 10))
        
        assert len(state_machine.state_history) == BillValidatorStateMachine.HISTORY_SIZE
    
    def test_current_phase_initializing(self, state_machine):
        """Test current phase for initializing state."""
        assert state_machine.current_phase == ValidatorPhase.INITIALIZING
    
    @pytest.mark.asyncio
    async def test_current_phase_idle(self, state_machine):
        """Test current phase for idle state."""
        await state_machine.process_state(DeviceState.IDLING)
        assert state_machine.current_phase == ValidatorPhase.IDLE
    
    @pytest.mark.asyncio
    async def test_current_phase_escrow(self, state_machine):
        """Test current phase for escrow state."""
        await state_machine.process_state(DeviceState.ESCROW_POSITION)
        assert state_machine.current_phase == ValidatorPhase.ESCROW
    
    def test_reset(self, state_machine):
        """Test state machine reset."""
        state_machine._current_state = DeviceState.IDLING
        state_machine._state_history.append(DeviceState.IDLING)
        
        state_machine.reset()
        
        assert state_machine.current_state is None
        assert len(state_machine.state_history) == 0
    
    def test_remove_callback(self, state_machine):
        """Test callback removal."""
        callback = AsyncMock()
        state_machine.add_callback(EventType.BILL_STACKED, callback)
        state_machine.remove_callback(EventType.BILL_STACKED, callback)
        
        assert callback not in state_machine._callbacks.get(EventType.BILL_STACKED, [])


class TestEventType:
    """Tests for EventType constants."""
    
    def test_event_types(self):
        """Test event type constants."""
        assert EventType.CONNECTED == "CONNECTED"
        assert EventType.BILL_STACKED == "BILL_STACKED"
        assert EventType.BILL_ESCROW == "BILL_ESCROW"
        assert EventType.ERROR == "ERROR"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
