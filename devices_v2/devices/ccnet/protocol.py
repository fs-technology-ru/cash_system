"""
CCNET Protocol Layer.

Handles CCNET command/response logic, ACK/NAK handling, and response parsing.
Based on CCNET Protocol Description.

This layer sits between the Transport Layer and the Application Layer,
providing protocol-specific functionality.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from .constants import (
    Command,
    DeviceState,
    DEFAULT_DEVICE_ADDRESS,
    POLL_INTERVAL_MS,
    get_state_name,
)
from .transport import CCNETTransport, CCNETPacket


logger = logging.getLogger(__name__)


@dataclass
class PollResponse:
    """
    Parsed response to POLL command.
    
    Attributes:
        state: Device state code.
        data: Additional data bytes (e.g., bill code).
        is_ack: True if response is ACK.
        is_nak: True if response is NAK.
    """
    state: int
    data: bytes = b''
    is_ack: bool = False
    is_nak: bool = False
    
    @property
    def state_name(self) -> str:
        """Get human-readable state name."""
        return get_state_name(self.state)
    
    @property
    def bill_code(self) -> Optional[int]:
        """Get bill code from data (if present)."""
        if len(self.data) > 0:
            return self.data[0]
        return None


class CCNETProtocol:
    """
    Protocol layer for CCNET communication.
    
    Provides high-level command methods with proper ACK/NAK handling.
    
    Attributes:
        transport: Underlying transport layer.
    """
    
    def __init__(self, transport: CCNETTransport) -> None:
        """
        Initialize protocol layer.
        
        Args:
            transport: Transport layer instance.
        """
        self._transport = transport
    
    @property
    def transport(self) -> CCNETTransport:
        """Get transport layer."""
        return self._transport
    
    async def send_ack(self) -> None:
        """Send ACK (acknowledgement) to device."""
        await self._transport.send_command(Command.ACK)
    
    async def send_nak(self) -> None:
        """Send NAK (negative acknowledgement) to device."""
        await self._transport.send_command(Command.NAK)
    
    async def reset(self) -> bool:
        """
        Send RESET command to device.
        
        Returns:
            True if device acknowledged reset.
        """
        logger.info("Sending RESET command")
        await self._transport.send_command(Command.RESET)
        
        # Wait for response
        response = await self._transport.receive_packet()
        if response:
            logger.debug(f"RESET response: 0x{response.command:02X}")
            return True
        
        logger.warning("No response to RESET")
        return False
    
    async def poll(self) -> Optional[PollResponse]:
        """
        Send POLL command and parse response.
        
        Returns:
            Parsed poll response or None on error.
        """
        await self._transport.send_command(Command.POLL)
        
        response = await self._transport.receive_packet()
        if not response:
            return None
        
        # Parse response
        state = response.command  # State code is in command byte
        data = response.data
        
        return PollResponse(
            state=state,
            data=data,
            is_ack=(state == Command.ACK),
            is_nak=(state == Command.NAK),
        )
    
    async def enable_bill_types(
        self,
        bill_mask: int = 0xFFFFFF,
        security_mask: int = 0,
    ) -> bool:
        """
        Send ENABLE BILL TYPES command.
        
        Enables acceptance of specified bill types.
        
        Args:
            bill_mask: 3-byte mask of enabled bill types (default all).
            security_mask: 3-byte security mask (default none).
            
        Returns:
            True if command acknowledged.
        """
        # Build data: 3 bytes bill mask + 3 bytes security mask
        data = bytes([
            (bill_mask >> 0) & 0xFF,
            (bill_mask >> 8) & 0xFF,
            (bill_mask >> 16) & 0xFF,
            (security_mask >> 0) & 0xFF,
            (security_mask >> 8) & 0xFF,
            (security_mask >> 16) & 0xFF,
        ])
        
        logger.info(f"Enabling bill types: mask=0x{bill_mask:06X}")
        await self._transport.send_command(Command.ENABLE_BILL_TYPES, data)
        
        response = await self._transport.receive_packet()
        if response:
            return True
        
        return False
    
    async def disable_bill_types(self) -> bool:
        """
        Disable all bill types.
        
        Returns:
            True if command acknowledged.
        """
        return await self.enable_bill_types(bill_mask=0, security_mask=0)
    
    async def stack(self) -> bool:
        """
        Send STACK command to accept bill in escrow.
        
        Returns:
            True if command acknowledged.
        """
        logger.info("Sending STACK command")
        await self._transport.send_command(Command.STACK)
        
        response = await self._transport.receive_packet()
        if response:
            return True
        
        return False
    
    async def return_bill(self) -> bool:
        """
        Send RETURN command to reject bill in escrow.
        
        Returns:
            True if command acknowledged.
        """
        logger.info("Sending RETURN command")
        await self._transport.send_command(Command.RETURN)
        
        response = await self._transport.receive_packet()
        if response:
            return True
        
        return False
    
    async def hold(self) -> bool:
        """
        Send HOLD command to keep bill in escrow.
        
        Use this to extend escrow timeout.
        
        Returns:
            True if command acknowledged.
        """
        await self._transport.send_command(Command.HOLD)
        
        response = await self._transport.receive_packet()
        if response:
            return True
        
        return False
    
    async def get_status(self) -> Optional[bytes]:
        """
        Send GET STATUS command.
        
        Returns:
            Status bytes or None on error.
        """
        await self._transport.send_command(Command.GET_STATUS)
        
        response = await self._transport.receive_packet()
        if response:
            return response.data
        
        return None
    
    async def get_identification(self) -> Optional[bytes]:
        """
        Send IDENTIFICATION command.
        
        Returns:
            Identification data (part number, serial, asset number).
        """
        await self._transport.send_command(Command.IDENTIFICATION)
        
        response = await self._transport.receive_packet()
        if response:
            return response.data
        
        return None
    
    async def get_bill_table(self) -> Optional[bytes]:
        """
        Send GET BILL TABLE command.
        
        Returns:
            Bill table data describing supported denominations.
        """
        await self._transport.send_command(Command.GET_BILL_TABLE)
        
        response = await self._transport.receive_packet()
        if response:
            return response.data
        
        return None
    
    async def close(self) -> None:
        """Close the protocol and transport."""
        await self._transport.close()
