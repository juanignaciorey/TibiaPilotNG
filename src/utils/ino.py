"""
Legacy Arduino serial interface.
Kept for backwards compatibility — new code should use input_manager.py instead.
Connection is lazy: only opens the port on first use or explicit connect().
"""
import base64
from time import sleep

_serial = None
_port = 'COM3'
_baudrate = 115200


def connect(port: str = 'COM3', baudrate: int = 115200) -> bool:
    global _serial, _port, _baudrate
    _port = port
    _baudrate = baudrate
    try:
        import serial
        _serial = serial.Serial(port, baudrate, timeout=1)
        return True
    except Exception as e:
        print(f"[ino] Arduino not available on {port}: {e}")
        _serial = None
        return False


def is_connected() -> bool:
    return _serial is not None and _serial.is_open


def sendCommandArduino(command: str):
    global _serial
    if _serial is None:
        connect(_port, _baudrate)
    if _serial is None:
        return
    try:
        line = base64.b64encode(command.encode('utf-8')).decode('utf-8') + '\n'
        _serial.write(line.encode())
        sleep(0.01)
    except Exception as e:
        print(f"[ino] Send error: {e}")
        _serial = None
