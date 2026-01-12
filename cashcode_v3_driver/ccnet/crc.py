"""
CRC16 CCITT Calculation for CCNET Protocol.

Implementation based on CCNET Protocol Description page 10.
Uses polynomial 0x08408 (reversed CCITT polynomial).
"""

from .constants import CRC_POLYNOMIAL


def calculate_crc16(data: bytes) -> bytes:
    """
    Calculate CRC16 checksum for CCNET packet.
    
    Uses CCITT algorithm with polynomial 0x08408 (bit-reversed 0x1021).
    The CRC is returned as 2 bytes in little-endian format.
    
    Args:
        data: Bytes to calculate CRC for (excluding CRC bytes).
        
    Returns:
        2-byte CRC in little-endian format.
        
    Example:
        >>> data = bytes([0x02, 0x03, 0x06, 0x33])
        >>> crc = calculate_crc16(data)
        >>> len(crc)
        2
    """
    crc: int = 0
    
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ CRC_POLYNOMIAL
            else:
                crc = crc >> 1
    
    return crc.to_bytes(2, byteorder='little')


def verify_crc16(data: bytes) -> bool:
    """
    Verify CRC16 checksum of a complete CCNET packet.
    
    The packet must include the CRC bytes at the end.
    When CRC is calculated over the entire packet (including CRC bytes),
    the result should be 0 for a valid packet.
    
    Args:
        data: Complete packet including CRC bytes.
        
    Returns:
        True if CRC is valid, False otherwise.
        
    Example:
        >>> packet = bytes([0x02, 0x03, 0x06, 0x33, 0xDA, 0x81])
        >>> verify_crc16(packet)
        True
    """
    if len(data) < 5:  # Minimum packet: SYNC + ADR + LNG + CMD + CRC(2)
        return False
    
    # Calculate CRC over entire packet including received CRC
    # Result should be 0 for valid packet
    crc: int = 0
    
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ CRC_POLYNOMIAL
            else:
                crc = crc >> 1
    
    return crc == 0


def append_crc(data: bytes) -> bytes:
    """
    Append CRC16 checksum to data.
    
    Args:
        data: Packet data without CRC.
        
    Returns:
        Packet data with CRC appended.
    """
    return data + calculate_crc16(data)
