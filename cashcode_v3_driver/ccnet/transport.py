"""
CCNET Transport Layer.

Handles low-level packet construction, CRC validation, and serial I/O.
Based on CCNET Protocol Description page 9.

Packet Structure:
    SYNC (0x02) | ADR | LNG | CMD | DATA | CRC (2 bytes)
    
Where:
    - SYNC: Start of packet marker (always 0x02)
    - ADR: Device address (0x03 for Bill Validator)
    - LNG: Total packet length including SYNC, ADR, LNG, CMD, DATA, CRC
    - CMD: Command byte
    - DATA: Optional data bytes
    - CRC: CRC16 checksum (2 bytes, little-endian)
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from .constants import (
    SYNC_BYTE,
    DEFAULT_DEVICE_ADDRESS,
    RESPONSE_TIMEOUT_S,
    MAX_PACKET_LENGTH,
    MIN_PACKET_LENGTH,
    FLUSH_BUFFER_SIZE,
    FLUSH_TIMEOUT_S,
)
from .crc import calculate_crc16, verify_crc16


logger = logging.getLogger(__name__)


@dataclass
class CCNETPacket:
    """
    Represents a CCNET protocol packet.
    
    Attributes:
        address: Device address (default 0x03 for Bill Validator).
        command: Command byte.
        data: Optional data bytes.
    """
    address: int
    command: int
    data: bytes = b''
    
    @property
    def length(self) -> int:
        """Calculate total packet length."""
        # SYNC(1) + ADR(1) + LNG(1) + CMD(1) + DATA(n) + CRC(2)
        return 6 + len(self.data)
    
    def to_bytes(self) -> bytes:
        """
        Serialize packet to bytes with CRC.
        
        Returns:
            Complete packet bytes ready to send.
        """
        # Build packet without CRC
        packet = bytes([
            SYNC_BYTE,
            self.address,
            self.length,
            self.command,
        ]) + self.data
        
        # Append CRC
        crc = calculate_crc16(packet)
        return packet + crc
    
    @classmethod
    def from_bytes(cls, data: bytes) -> Optional['CCNETPacket']:
        """
        Parse packet from received bytes.
        
        Args:
            data: Raw bytes received from device.
            
        Returns:
            Parsed packet or None if invalid.
        """
        if len(data) < 6:  # Minimum packet size
            logger.warning(f"Packet too short: {len(data)} bytes")
            return None
        
        if data[0] != SYNC_BYTE:
            logger.warning(f"Invalid SYNC byte: 0x{data[0]:02X}")
            return None
        
        if not verify_crc16(data):
            logger.warning("CRC verification failed")
            return None
        
        address = data[1]
        length = data[2]
        command = data[3]
        
        # Extract data (between CMD and CRC)
        packet_data = data[4:-2] if length > 6 else b''
        
        return cls(
            address=address,
            command=command,
            data=packet_data,
        )


class CCNETTransport:
    """
    Transport layer for CCNET protocol.
    
    Handles async serial I/O, packet framing, and CRC validation.
    
    Attributes:
        reader: Async serial reader.
        writer: Async serial writer.
        address: Device address.
    """
    
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        address: int = DEFAULT_DEVICE_ADDRESS,
    ) -> None:
        """
        Initialize transport layer.
        
        Args:
            reader: Async stream reader for serial port.
            writer: Async stream writer for serial port.
            address: Device address (default 0x03).
        """
        self._reader = reader
        self._writer = writer
        self._address = address
        self._lock = asyncio.Lock()
    
    @property
    def address(self) -> int:
        """Get device address."""
        return self._address
    
    async def send_packet(self, packet: CCNETPacket) -> None:
        """
        Send a packet to the device.
        
        Args:
            packet: Packet to send.
        """
        data = packet.to_bytes()
        hex_str = ' '.join(f'{b:02X}' for b in data)
        logger.debug(f"TX: {hex_str}")
        
        async with self._lock:
            self._writer.write(data)
            await self._writer.drain()
    
    async def send_command(
        self,
        command: int,
        data: bytes = b'',
    ) -> None:
        """
        Send a command to the device.
        
        Args:
            command: Command byte.
            data: Optional command data.
        """
        packet = CCNETPacket(
            address=self._address,
            command=command,
            data=data,
        )
        await self.send_packet(packet)
    
    async def receive_packet(
        self,
        timeout: float = RESPONSE_TIMEOUT_S,
    ) -> Optional[CCNETPacket]:
        """
        Receive a packet from the device.
        
        Handles sync byte detection and packet framing.
        
        Args:
            timeout: Receive timeout in seconds.
            
        Returns:
            Received packet or None if timeout/error.
        """
        try:
            # Find SYNC byte
            sync_found = False
            max_attempts = 10
            
            for _ in range(max_attempts):
                byte_data = await asyncio.wait_for(
                    self._reader.read(1),
                    timeout=timeout,
                )
                
                if len(byte_data) == 0:
                    logger.warning("No data received (EOF)")
                    return None
                
                if byte_data[0] == SYNC_BYTE:
                    sync_found = True
                    break
                else:
                    logger.debug(f"Skipping byte: 0x{byte_data[0]:02X}")
            
            if not sync_found:
                logger.warning("SYNC byte not found")
                return None
            
            # Read ADDRESS and LENGTH
            addr_len = await asyncio.wait_for(
                self._reader.read(2),
                timeout=timeout,
            )
            
            if len(addr_len) < 2:
                logger.warning("Failed to read ADDRESS and LENGTH")
                return None
            
            address = addr_len[0]
            total_length = addr_len[1]
            
            # Validate address
            if address != self._address:
                logger.warning(
                    f"Address mismatch: expected 0x{self._address:02X}, "
                    f"got 0x{address:02X}"
                )
                # Continue anyway, some devices may use different address in response
            
            # Validate length
            if total_length < MIN_PACKET_LENGTH or total_length > MAX_PACKET_LENGTH:
                logger.warning(f"Invalid packet length: {total_length}")
                await self._flush_buffer()
                return None
            
            # Build header
            header = bytes([SYNC_BYTE, address, total_length])
            
            # Read remaining bytes (CMD + DATA + CRC)
            remaining_length = total_length - 3
            remaining = await asyncio.wait_for(
                self._reader.read(remaining_length),
                timeout=timeout,
            )
            
            if len(remaining) < remaining_length:
                logger.warning(
                    f"Incomplete packet: expected {remaining_length}, "
                    f"got {len(remaining)}"
                )
                return None
            
            # Combine and parse
            complete_data = header + remaining
            hex_str = ' '.join(f'{b:02X}' for b in complete_data)
            logger.debug(f"RX: {hex_str}")
            
            return CCNETPacket.from_bytes(complete_data)
            
        except asyncio.TimeoutError:
            logger.debug("Receive timeout")
            return None
        except Exception as e:
            logger.error(f"Receive error: {e}")
            return None
    
    async def _flush_buffer(self) -> None:
        """Flush receive buffer to clear garbage data."""
        try:
            junk = await asyncio.wait_for(
                self._reader.read(FLUSH_BUFFER_SIZE),
                timeout=FLUSH_TIMEOUT_S,
            )
            if junk:
                logger.debug(f"Flushed {len(junk)} bytes: {junk.hex(' ')}")
        except asyncio.TimeoutError:
            pass
    
    async def close(self) -> None:
        """Close the transport."""
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception as e:
            logger.debug(f"Close error (ignored): {e}")
