#!/usr/bin/env python3
"""
LCDM-2000 Bill Dispenser Driver.

A Python implementation of the LCDM-2000 device control protocol.
This module provides communication with dual-cassette bill dispensers
using serial protocol.
"""

import select
from typing import Final, Optional

import serial


# =============================================================================
# Protocol Constants
# =============================================================================

class LcdmCommands:
    """LCDM-2000 protocol commands."""

    NAK: Final[int] = 0xFF
    ACK: Final[int] = 0x06
    PURGE: Final[int] = 0x44
    STATUS: Final[int] = 0x46
    UPPER_DISPENSE: Final[int] = 0x45
    LOWER_DISPENSE: Final[int] = 0x55
    UPPER_AND_LOWER_DISPENSE: Final[int] = 0x56
    UPPER_TEST_DISPENSE: Final[int] = 0x76
    LOWER_TEST_DISPENSE: Final[int] = 0x77


# Exception codes
EXCEPTION_BAD_RESPONSE_CODE: Final[int] = 0
EXCEPTION_BAD_CRC_CODE: Final[int] = 1
EXCEPTION_BAD_SOH_CODE: Final[int] = 2
EXCEPTION_BAD_ID_CODE: Final[int] = 3
EXCEPTION_BAD_STX_CODE: Final[int] = 4
EXCEPTION_BAD_ACK_RESPONSE_CODE: Final[int] = 5
EXCEPTION_BAD_COUNT: Final[int] = 6


# =============================================================================
# Exceptions
# =============================================================================

class LcdmException(Exception):
    """
    Exception for LCDM device errors.

    Attributes:
        error_msg: Human-readable error message.
        code: Numeric error code.
    """

    def __init__(self, msg: str, code: int = 0) -> None:
        super().__init__(f"{msg}: {code}")
        self.error_msg = msg
        self.code = code


# =============================================================================
# TTY Serial Handler
# =============================================================================

class TTY:
    """
    Serial port handler for LCDM communication.

    Provides low-level read/write operations with timeout handling.
    """

    def __init__(self) -> None:
        """Initialize TTY handler."""
        self._serial: Optional[serial.Serial] = None

    def IsOK(self) -> bool:
        """Check if serial port is open and ready."""
        return self._serial is not None and self._serial.is_open

    def Connect(self, port: str, baudrate: int = 9600) -> None:
        """
        Connect to serial port.

        Args:
            port: Serial port path.
            baudrate: Baud rate (default 9600).
        """
        self.Disconnect()
        try:
            self._serial = serial.Serial(port=port, baudrate=baudrate, timeout=1)
        except Exception as e:
            raise LcdmException(str(e))

    def Disconnect(self) -> None:
        """Disconnect from serial port."""
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None

    def Write(self, data: bytes) -> int:
        """
        Write data to serial port.

        Args:
            data: Bytes to write.

        Returns:
            Number of bytes written.
        """
        if not self.IsOK():
            raise LcdmException("Error. Port not open")
        try:
            return self._serial.write(data)
        except Exception as e:
            raise LcdmException(str(e))

    def Read(self, size: int = 200) -> bytes:
        """
        Read data from serial port with timeout.

        Args:
            size: Maximum bytes to read.

        Returns:
            Bytes read from port.

        Note:
            Uses select.select() for polling which is Unix-compatible.
            On Windows, pyserial's timeout-based reading is used as fallback.
        """
        if not self.IsOK():
            raise LcdmException("Error. Port not open")

        data = bytearray()
        attempt = size * 2
        timeout_sec = 2

        while attempt:
            # Note: select.select() works on Unix; Windows uses pyserial timeout
            r, _, _ = select.select([self._serial], [], [], timeout_sec)
            if r:
                try:
                    chunk = self._serial.read(size - len(data))
                    data.extend(chunk)
                    if len(data) >= size:
                        break
                except Exception as e:
                    raise LcdmException(str(e))
            attempt -= 1

        return bytes(data)

# =============================================================================
# LCDM-2000 Dispenser
# =============================================================================

class Clcdm2000:
    """
    LCDM-2000 Bill Dispenser Driver.

    Controls a dual-cassette bill dispenser using serial protocol.
    Supports dispensing from upper and lower cassettes independently
    or simultaneously.

    Attributes:
        CheckSensor1-4: Bill check sensor states.
        DivertSensor1-2: Divert path sensor states.
        EjectSensor: Bill eject sensor state.
        ExitSensor: Bill exit sensor state.
        SolenoidSensor: Solenoid sensor state.
        UpperNearEnd: Upper cassette near-empty flag.
        LowerNearEnd: Lower cassette near-empty flag.
        CashBoxUpper: Upper cassette presence flag.
        CashBoxLower: Lower cassette presence flag.
        RejectTray: Reject tray sensor state.
    """

    # Protocol constants
    EOT: Final[int] = 0x04
    ID: Final[int] = 0x50
    STX: Final[int] = 0x02
    ETX: Final[int] = 0x03
    SOH: Final[int] = 0x01
    ACK: Final[int] = 0x06
    NCK: Final[int] = 0x15

    # Error code mapping
    ERROR_CODES: Final[dict[int, tuple[str, bool]]] = {
        0x30: ("Good", False),
        0x31: ("Normal stop", False),
        0x32: ("Pickup error", True),
        0x33: ("JAM at CHK1,2 Sensor", True),
        0x34: ("Overflow bill", True),
        0x35: ("JAM at EXIT Sensor or EJT Sensor", True),
        0x36: ("JAM at DIV Sensor", True),
        0x37: ("Undefined command", True),
        0x38: ("Upper Bill-End", True),
        0x3A: ("Counting Error (between CHK3,4 Sensor and DIV Sensor)", True),
        0x3B: ("Note request error", True),
        0x3C: ("Counting Error (between DIV Sensor and EJT Sensor)", True),
        0x3D: ("Counting Error (between EJT Sensor and EXIT Sensor)", True),
        0x3F: ("Reject Tray is not recognized", True),
        0x40: ("Lower Bill-End", True),
        0x41: ("Motor Stop", True),
        0x42: ("JAM at Div Sensor", True),
        0x43: ("Timeout (From DIV Sensor to EJT Sensor)", True),
        0x44: ("Over Reject", True),
        0x45: ("Upper Cassette is not recognized", True),
        0x46: ("Lower Cassette is not recognized", True),
        0x47: ("Dispensing timeout", True),
        0x48: ("JAM at EJT Sensor", True),
        0x49: ("Diverter solenoid or SOL Sensor error", True),
        0x4A: ("SOL Sensor error", True),
        0x4C: ("JAM at CHK3,4 Sensor", True),
        0x4E: ("Purge error (Jam at Div Sensor)", True),
    }

    def __init__(self) -> None:
        """Initialize the LCDM-2000 driver."""
        self.errorCode: int = 0
        self.errorMessage: str = ""

        # Sensor states
        self.CheckSensor1: bool = False
        self.CheckSensor2: bool = False
        self.CheckSensor3: bool = False
        self.CheckSensor4: bool = False
        self.DivertSensor1: bool = False
        self.DivertSensor2: bool = False
        self.EjectSensor: bool = False
        self.ExitSensor: bool = False
        self.SolenoidSensor: bool = False
        self.UpperNearEnd: bool = False
        self.LowerNearEnd: bool = False
        self.CashBoxUpper: bool = False
        self.CashBoxLower: bool = False
        self.RejectTray: bool = False

        self._tty = TTY()

    def GetCRC(self, bufData: bytes) -> int:
        """
        Calculate CRC for packet.

        Args:
            bufData: Packet data bytes.

        Returns:
            CRC byte.
        """
        crc = bufData[0]
        for b in bufData[1:]:
            crc ^= b
        return crc

    def testCRC(self, bufData: bytes) -> bool:
        """
        Verify CRC in response packet.

        Args:
            bufData: Response packet bytes.

        Returns:
            True if CRC is valid.
        """
        if len(bufData) < 2:
            return False
        crc = bufData[0]
        for b in bufData[1:-1]:
            crc ^= b
        return crc == bufData[-1]

    def checkErrors(self, test: int) -> bool:
        """
        Check error code in device response.

        Args:
            test: Error byte from response.

        Returns:
            True if error requires exception, False if OK.
        """
        self.errorCode = test

        if test in self.ERROR_CODES:
            self.errorMessage, is_error = self.ERROR_CODES[test]
            return is_error
        else:
            self.errorMessage = "Unknown error"
            return True

    def connect(self, com_port: str, baudrate: int = 9600) -> None:
        """
        Connect to dispenser device.

        Args:
            com_port: Serial port path.
            baudrate: Baud rate (default 9600).
        """
        self._tty.Connect(com_port, baudrate)
        self.status()

    def disconnect(self) -> None:
        """Disconnect from device."""
        self._tty.Disconnect()

    def compileCommand(self, cmd: int, data: bytes = b"") -> bytes:
        """
        Compile command packet.

        Args:
            cmd: Command byte.
            data: Optional command data.

        Returns:
            Complete packet bytes with CRC.
        """
        packet = bytearray()
        packet.append(self.EOT)
        packet.append(self.ID)
        packet.append(self.STX)
        packet.append(cmd)
        packet.extend(data)
        packet.append(self.ETX)
        crc = self.GetCRC(packet)
        packet.append(crc)
        return bytes(packet)

    def sendCommand(self, cmd: int, data: bytes = b"") -> int:
        """
        Send command to device.

        Args:
            cmd: Command byte.
            data: Optional command data.

        Returns:
            Number of bytes written.
        """
        packet = self.compileCommand(cmd, data)
        return self._tty.Write(packet)

    def getACK(self) -> int:
        """
        Receive ACK/NAK response.

        Returns:
            Response byte.
        """
        raw = self._tty.Read(1)
        if len(raw) != 1:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)
        return raw[0]

    def sendACK(self) -> None:
        """Send ACK to device."""
        self._tty.Write(bytes([LcdmCommands.ACK]))

    def sendNAK(self) -> None:
        """Send NAK to device."""
        self._tty.Write(bytes([LcdmCommands.NAK]))

    def getResponse(self, recv_bytes: int, attempts: int = 3) -> bytes:
        """
        Receive device response with retry.

        Args:
            recv_bytes: Expected response length.
            attempts: Maximum retry attempts.

        Returns:
            Response bytes.
        """
        if attempts <= 0:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        raw = self._tty.Read(recv_bytes)
        if len(raw) < 4:
            self.sendNAK()
            return self.getResponse(recv_bytes, attempts - 1)

        # Validate packet structure and CRC
        if (not self.testCRC(raw)
                or raw[0] != self.SOH
                or raw[1] != self.ID
                or raw[2] != self.STX):
            self.sendNAK()
            return self.getResponse(recv_bytes, attempts - 1)

        self.sendACK()
        return raw

    def go(self, cmd: int, data: bytes = b"", recv_bytes: int = 7) -> bytes:
        """
        Send command and receive response.

        Args:
            cmd: Command byte.
            data: Optional command data.
            recv_bytes: Expected response length.

        Returns:
            Response bytes.
        """
        attempts_count = 2
        success = False

        for _ in range(attempts_count):
            self.sendCommand(cmd, data)
            try:
                ack = self.getACK()
                if ack == LcdmCommands.ACK:
                    success = True
                    break
                if ack == LcdmCommands.NAK:
                    continue
            except Exception:
                raise

        if not success:
            raise LcdmException("Bad ACK response", EXCEPTION_BAD_ACK_RESPONSE_CODE)

        return self.getResponse(recv_bytes)

    def purge(self) -> None:
        """
        Clear any bills in the transport path.

        Sends PURGE command to clear stuck bills.
        """
        len_response = 7
        num_error_byte = 4

        response = self.go(LcdmCommands.PURGE, b"", len_response)
        if len(response) != len_response:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[num_error_byte]):
            raise LcdmException(self.errorMessage, self.errorCode)

    def status(self) -> None:
        """
        Query device status and update sensor states.

        Updates all sensor state attributes.
        """
        len_response = 10
        num_error_byte = 5

        response = self.go(LcdmCommands.STATUS, b"", len_response)
        if len(response) != len_response:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[num_error_byte]):
            raise LcdmException(self.errorMessage, self.errorCode)

        # Parse sensor bit flags
        r6 = response[6]
        r7 = response[7]

        self.CheckSensor1 = bool(r6 & 0b00000001)
        self.CheckSensor2 = bool(r6 & 0b00000010)
        self.DivertSensor1 = bool(r6 & 0b00000100)
        self.DivertSensor2 = bool(r6 & 0b00001000)
        self.EjectSensor = bool(r6 & 0b00010000)
        self.ExitSensor = bool(r6 & 0b00100000)
        self.UpperNearEnd = bool(r6 & 0b01000000)

        self.CheckSensor3 = bool(r7 & 0b00001000)
        self.CheckSensor4 = bool(r7 & 0b00010000)
        self.SolenoidSensor = bool(r7 & 0b00000001)
        self.CashBoxUpper = bool(r7 & 0b00000010)
        self.CashBoxLower = bool(r7 & 0b00000100)
        self.LowerNearEnd = bool(r7 & 0b00100000)
        self.RejectTray = bool(r7 & 0b01000000)

    def testStatus(self) -> None:
        """
        Verify device is ready for dispensing.

        Checks sensors and attempts purge if needed.
        """
        for i in range(2):
            self.status()

            # Check for cassette or solenoid errors
            if self.CashBoxUpper or self.CashBoxLower:
                raise LcdmException("Cashbox not installed")

            if self.SolenoidSensor:
                raise LcdmException("Solenoid error")

            # Check for sensor blockage
            if (self.CheckSensor1 or self.CheckSensor2
                    or self.CheckSensor3 or self.CheckSensor4
                    or self.DivertSensor1 or self.DivertSensor2
                    or self.EjectSensor or self.ExitSensor
                    or self.RejectTray):
                if i == 1:
                    raise LcdmException("Error sensor")
                # Attempt purge
                self.purge()
                continue
            break

    def printStatus(self) -> None:
        """Print current sensor states for debugging."""
        print(f"CheckSensor1:   {self.CheckSensor1}")
        print(f"CheckSensor2:   {self.CheckSensor2}")
        print(f"CheckSensor3:   {self.CheckSensor3}")
        print(f"CheckSensor4:   {self.CheckSensor4}")
        print(f"DivertSensor1:  {self.DivertSensor1}")
        print(f"DivertSensor2:  {self.DivertSensor2}")
        print(f"EjectSensor:    {self.EjectSensor}")
        print(f"ExitSensor:     {self.ExitSensor}")
        print(f"SolenoidSensor: {self.SolenoidSensor}")
        print(f"UpperNearEnd:   {self.UpperNearEnd}")
        print(f"LowerNearEnd:   {self.LowerNearEnd}")
        print(f"CashBoxUpper:   {self.CashBoxUpper}")
        print(f"CashBoxLower:   {self.CashBoxLower}")
        print(f"RejectTray:     {self.RejectTray}")

    def upperDispense(self, count: int) -> None:
        """
        Dispense bills from upper cassette.

        Args:
            count: Number of bills to dispense (1-60).
        """
        self.testStatus()

        if count < 1 or count > 60:
            raise LcdmException("Bad count for upperDispense", EXCEPTION_BAD_COUNT)

        data = f"{count:02d}".encode("ascii")
        len_response = 14
        num_error_byte = 8

        response = self.go(LcdmCommands.UPPER_DISPENSE, data, len_response)
        if len(response) != len_response:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[num_error_byte]):
            raise LcdmException(self.errorMessage, self.errorCode)

    def lowerDispense(self, count: int) -> None:
        """
        Dispense bills from lower cassette.

        Args:
            count: Number of bills to dispense (1-60).
        """
        self.testStatus()

        if count < 1 or count > 60:
            raise LcdmException("Bad count for lowerDispense", EXCEPTION_BAD_COUNT)

        data = f"{count:02d}".encode("ascii")
        len_response = 14
        num_error_byte = 8

        response = self.go(LcdmCommands.LOWER_DISPENSE, data, len_response)
        if len(response) != len_response:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[num_error_byte]):
            raise LcdmException(self.errorMessage, self.errorCode)

    def upperLowerDispense(
        self,
        count_upper: int,
        count_lower: int,
    ) -> list[int]:
        """
        Dispense bills from both cassettes simultaneously.

        Args:
            count_upper: Number of bills from upper cassette (0-60).
            count_lower: Number of bills from lower cassette (0-60).

        Returns:
            List of 6 values:
            [upper_exit, lower_exit, upper_rejected, lower_rejected,
             upper_check, lower_check]
        """
        self.testStatus()

        if count_upper < 0 or count_upper > 60:
            raise LcdmException(
                "Bad count_upper for upperLowerDispense",
                EXCEPTION_BAD_COUNT,
            )
        if count_lower < 0 or count_lower > 60:
            raise LcdmException(
                "Bad count_lower for upperLowerDispense",
                EXCEPTION_BAD_COUNT,
            )

        data = f"{count_upper:02d}{count_lower:02d}".encode("ascii")
        len_response = 21
        num_error_byte = 12

        response = self.go(LcdmCommands.UPPER_AND_LOWER_DISPENSE, data, len_response)
        if len(response) != len_response:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[num_error_byte]):
            raise LcdmException(self.errorMessage, self.errorCode)

        # Parse response values
        positions = [
            (6, 7),    # upper exit
            (10, 11),  # lower exit
            (15, 16),  # upper rejected
            (17, 18),  # lower rejected
            (4, 5),    # upper check
            (8, 9),    # lower check
        ]

        result = []
        for p1, p2 in positions:
            val = (response[p1] - 0x30) * 10 + (response[p2] - 0x30)
            result.append(val)

        return result