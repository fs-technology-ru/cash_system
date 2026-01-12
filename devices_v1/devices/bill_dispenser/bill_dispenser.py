#!/usr/bin/env python3
"""
A Python translation of the C++ lcdm2000 device control library.
Requires pyserial for serial communication.
"""

import os
import fcntl
import termios
import errno
import time
import sys
import struct
import select

import serial
import serial.tools.list_ports

class LcdmCommands:
    """
    Enum-like class for device commands (equivalent to enum class in C++).
    """
    NAK = 0xFF
    ACK = 0x06
    PURGE = 0x44
    STATUS = 0x46
    UPPER_DISPENSE = 0x45
    LOWER_DISPENSE = 0x55
    UPPER_AND_LOWER_DISPENSE = 0x56
    UPPER_TEST_DISPENSE = 0x76
    LOWER_TEST_DISPENSE = 0x77

# Exceptions from original code
EXCEPTION_BAD_RESPONSE_CODE = 0
EXCEPTION_BAD_CRC_CODE = 1
EXCEPTION_BAD_SOH_CODE = 2
EXCEPTION_BAD_ID_CODE = 3
EXCEPTION_BAD_STX_CODE = 4
EXCEPTION_BAD_ACK_RESPONSE_CODE = 5
EXCEPTION_BAD_COUNT = 6

class LcdmException(Exception):
    """
    Mimics the C++ Exception class with code and message.
    """
    def __init__(self, msg: str, code: int = 0):
        super().__init__(f"{msg}: {code}")
        self.error_msg = msg
        self.code = code

class TTY:
    """
    TTY class to handle serial port operations.
    Equivalent to Clcdm2000::TTY in C++.
    """

    def __init__(self):
        self.ser = None

    def IsOK(self) -> bool:
        return self.ser is not None and self.ser.is_open

    def Connect(self, port: str, baudrate: int = 9600):
        self.Disconnect()
        try:
            self.ser = serial.Serial(port=port, baudrate=baudrate, timeout=1)
        except Exception as e:
            raise LcdmException(str(e))

    def Disconnect(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except:
                pass
        self.ser = None

    def Write(self, data: bytes) -> int:
        if not self.IsOK():
            raise LcdmException("Error. Port not open")
        try:
            return self.ser.write(data)
        except Exception as e:
            raise LcdmException(str(e))

    def Read(self, size: int = 200) -> bytes:
        """
        Read 'size' bytes with a poll-like approach.
        Adjusted for Python usage.
        """
        if not self.IsOK():
            raise LcdmException("Error. Port not open")

        data = bytearray()
        attempt = size << 1  # same as: size * 2
        timeout_sec = 2

        while attempt:
            # We use 'select' to emulate poll for readability
            # We can also rely on pyserial's timeout, but let's match the original logic.
            r, _, _ = select.select([self.ser], [], [], timeout_sec)
            if r:
                try:
                    chunk = self.ser.read(size - len(data))
                    data.extend(chunk)
                    if len(data) >= size:
                        break
                except Exception as e:
                    raise LcdmException(str(e))
            attempt -= 1

        return bytes(data)

class Clcdm2000:
    """
    Main class: translates from the original C++ version.
    """

    def __init__(self):
        # Bytes from C++ version
        self.EOT = 0x04
        self.ID = 0x50
        self.STX = 0x02
        self.ETX = 0x03
        self.SOH = 0x01
        self.ACK = 0x06
        self.NCK = 0x15  # Original code used 0x15 for "NCK"

        self.errorCode = 0
        self.errorMessage = ""

        # Public booleans from the code
        self.CheckSensor1 = False
        self.CheckSensor2 = False
        self.CheckSensor3 = False
        self.CheckSensor4 = False
        self.DivertSensor1 = False
        self.DivertSensor2 = False
        self.EjectSensor = False
        self.ExitSensor = False
        self.SolenoidSensor = False
        self.UpperNearEnd = False
        self.LowerNearEnd = False
        self.CashBoxUpper = False
        self.CashBoxLower = False
        self.RejectTray = False

        self.tty = TTY()

    def GetCRC(self, bufData: bytes) -> int:
        """
        Calc CRC packet, same as GetCRC in C++.
        """
        crc = bufData[0]
        for b in bufData[1:]:
            crc ^= b
        return crc

    def testCRC(self, bufData: bytes) -> bool:
        """
        Test CRC in response packet, equivalent to testCRC in C++.
        """
        if len(bufData) < 2:
            return False
        crc = bufData[0]
        for b in bufData[1:-1]:
            crc ^= b
        return (crc == bufData[-1])

    def checkErrors(self, test: int) -> bool:
        """
        Check error code in device response, sets self.errorMessage if error.
        Returns True if it's an error requiring an exception, else False (meaning 'ok' or 'normal stop').
        """
        self.errorCode = test
        # Keep track if error = True means there's a problem
        error = True
        mapping = {
            0x30: ("Good", False),
            0x31: ("Normal stop", False),
            0x32: ("Pickup error", True),
            0x33: ("JAM at CHK1,2 Sensor", True),
            0x34: ("Overflow bill", True),
            0x35: ("JAM at EXIT Sensor or EJT Sensor", True),
            0x36: ("JAM at DIV Sensor", True),
            0x37: ("Undefined command", True),
            0x38: ("Upper Bill- End", True),
            0x3A: ("Counting Error(between CHK3,4 Sensor and DIV Sensor)", True),
            0x3B: ("Note request error", True),
            0x3C: ("Counting Error(between DIV Sensor and EJT Sensor)", True),
            0x3D: ("Counting Error(between EJT Sensor and EXIT Sensor)", True),
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
            0x4E: ("Purge error(Jam at Div Sensor)", True)
        }
        if test in mapping:
            self.errorMessage, error = mapping[test]
        else:
            self.errorMessage = "Unknown error"
            error = True
        return error

    def connect(self, com_port: str, baudrate: int = 9600):
        """
        Open port with device, using TTY.
        """
        self.tty.Connect(com_port, baudrate)
        self.status()

    def disconnect(self):
        """
        Close com port.
        """
        self.tty.Disconnect()

    def compileCommand(self, cmd: int, data: bytes = b"") -> bytes:
        """
        Compile packet to send to device, equivalent to compileCommand in C++.
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
        Send command (via TTY), returns number of bytes written.
        """
        packet = self.compileCommand(cmd, data)
        return self.tty.Write(packet)

    def getACK(self) -> int:
        """
        Receive single byte (ACK or NAK or anything).
        """
        raw = self.tty.Read(1)
        if len(raw) != 1:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)
        return raw[0]

    def sendACK(self):
        """
        Send ACK to device.
        """
        self.tty.Write(bytes([LcdmCommands.ACK]))

    def sendNAK(self):
        """
        Send NAK to device.
        """
        self.tty.Write(bytes([LcdmCommands.NAK]))

    def getResponse(self, recv_bytes: int, attempts: int = 3) -> bytes:
        """
        Receive device response. If error, tries up to 'attempts'.
        """
        if attempts <= 0:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        raw = self.tty.Read(recv_bytes)
        if len(raw) < 4:
            # send NAK & retry
            self.sendNAK()
            return self.getResponse(recv_bytes, attempts - 1)

        # Check CRC
        if (not self.testCRC(raw)
            or raw[0] != self.SOH
            or raw[1] != self.ID
            or raw[2] != self.STX):
            # send NAK & retry
            self.sendNAK()
            return self.getResponse(recv_bytes, attempts - 1)

        # If all is well
        self.sendACK()
        return raw

    def go(self, cmd: int, data: bytes = b"", recv_bytes: int = 7) -> bytes:
        """
        Send command 'cmd' with 'data', receive ACK, then receive device response.
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
            except Exception as e:
                raise e

        if not success:
            raise LcdmException("Bad ACK response", EXCEPTION_BAD_ACK_RESPONSE_CODE)

        response = self.getResponse(recv_bytes)
        return response

    def purge(self):
        """
        Send PURGE command.
        """
        lenResponse = 7
        numErrorByte = 4

        response = self.go(LcdmCommands.PURGE, b"", lenResponse)
        if len(response) != lenResponse:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[numErrorByte]):
            raise LcdmException(self.errorMessage, self.errorCode)

    def status(self):
        """
        Send STATUS command and parse device sensors.
        """
        lenResponse = 10
        numErrorByte = 5

        response = self.go(LcdmCommands.STATUS, b"", lenResponse)
        if len(response) != lenResponse:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[numErrorByte]):
            raise LcdmException(self.errorMessage, self.errorCode)

        # parse bits
        # response[6], response[7] store bit flags
        r6 = response[6]
        r7 = response[7]

        self.CheckSensor1 = bool(r6 & 0b00000001)
        self.CheckSensor2 = bool(r6 & 0b00000010)
        self.DivertSensor1 = bool(r6 & 0b00000100)
        self.DivertSensor2 = bool(r6 & 0b00001000)
        self.EjectSensor   = bool(r6 & 0b00010000)
        self.ExitSensor    = bool(r6 & 0b00100000)
        self.UpperNearEnd  = bool(r6 & 0b01000000)

        self.CheckSensor3  = bool(r7 & 0b00001000)
        self.CheckSensor4  = bool(r7 & 0b00010000)
        self.SolenoidSensor = bool(r7 & 0b00000001)
        self.CashBoxUpper   = bool(r7 & 0b00000010)
        self.CashBoxLower   = bool(r7 & 0b00000100)
        self.LowerNearEnd   = bool(r7 & 0b00100000)
        self.RejectTray     = bool(r7 & 0b01000000)

    def testStatus(self):
        """
        Called before every major command to ensure sensors are clear or do purge if needed.
        """
        for i in range(2):
            self.status()
            # Check for cassette or solenoid errors first
            if self.CashBoxUpper or self.CashBoxLower:
                raise LcdmException("Cashbox not installed")

            if self.SolenoidSensor:
                raise LcdmException("Solenoid error")

            # If any sensor is triggered -> run purge once, else raise error if second time
            if (self.CheckSensor1 or self.CheckSensor2 or self.CheckSensor3 or self.CheckSensor4
                    or self.DivertSensor1 or self.DivertSensor2
                    or self.EjectSensor or self.ExitSensor
                    or self.RejectTray):
                if i == 1:
                    raise LcdmException("Error sensor")
                # Attempt purge
                self.purge()
                continue
            break

    def printStatus(self):
        """
        Debug helper: prints sensor states.
        """
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

    def upperDispense(self, count: int):
        """
        Send UPPER_DISPENSE command with 'count'.
        """
        self.testStatus()

        if count < 1 or count > 60:
            raise LcdmException("Bad count for upperDispense", EXCEPTION_BAD_COUNT)

        data_str = f"{count:02d}"
        data = data_str.encode("ascii")

        lenResponse = 14
        numErrorByte = 8

        response = self.go(LcdmCommands.UPPER_DISPENSE, data, lenResponse)
        if len(response) != lenResponse:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[numErrorByte]):
            raise LcdmException(self.errorMessage, self.errorCode)

    def lowerDispense(self, count: int):
        """
        Send LOWER_DISPENSE command with 'count'.
        """
        self.testStatus()

        if count < 1 or count > 60:
            raise LcdmException("Bad count for lowerDispense", EXCEPTION_BAD_COUNT)

        data_str = f"{count:02d}"
        data = data_str.encode("ascii")

        lenResponse = 14
        numErrorByte = 8

        response = self.go(LcdmCommands.LOWER_DISPENSE, data, lenResponse)
        if len(response) != lenResponse:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[numErrorByte]):
            raise LcdmException(self.errorMessage, self.errorCode)

    def upperLowerDispense(self, count_upper: int, count_lower: int):
        """
        Combined dispense command from upper and lower cassettes.

        Returns a list of 6 values:
        [ upper_exit_count, lower_exit_count,
          upper_rejected_count, lower_rejected_count,
          upper_check_count, lower_check_count ]
        """
        self.testStatus()

        if count_upper < 0 or count_upper > 60:
            raise LcdmException("Bad _count_upper for upperLowerDispense", EXCEPTION_BAD_COUNT)
        if count_lower < 0 or count_lower > 60:
            raise LcdmException("Bad _count_lower for upperLowerDispense", EXCEPTION_BAD_COUNT)

        data_str = f"{count_upper:02d}{count_lower:02d}"
        data = data_str.encode("ascii")

        lenResponse = 21
        numErrorByte = 12

        response = self.go(LcdmCommands.UPPER_AND_LOWER_DISPENSE, data, lenResponse)
        if len(response) != lenResponse:
            raise LcdmException("Bad response", EXCEPTION_BAD_RESPONSE_CODE)

        if self.checkErrors(response[numErrorByte]):
            raise LcdmException(self.errorMessage, self.errorCode)

        result = []

        positions = [
            (6, 7),   # upper exit
            (10, 11), # lower exit
            (15, 16), # upper rejected
            (17, 18), # lower rejected
            (4, 5),   # upper check
            (8, 9)    # lower check
        ]

        for (p1, p2) in positions:
            val = (response[p1] - 0x30) * 10 + (response[p2] - 0x30)
            result.append(val)

        return result