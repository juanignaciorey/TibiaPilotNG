import ctypes
import struct
import pyautogui
from enum import Enum
from typing import Optional, Tuple

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0

# ── Windows SendInput structures ─────────────────────────────────────────────

PUL = ctypes.POINTER(ctypes.c_ulong)


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long), ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong), ("dwExtraInfo", PUL),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
        ("dwExtraInfo", PUL),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("union", _INPUT_UNION)]


_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1
_MOUSEEVENTF_MOVE = 0x0001
_MOUSEEVENTF_ABSOLUTE = 0x8000
_MOUSEEVENTF_LEFTDOWN = 0x0002
_MOUSEEVENTF_LEFTUP = 0x0004
_MOUSEEVENTF_RIGHTDOWN = 0x0008
_MOUSEEVENTF_RIGHTUP = 0x0010
_MOUSEEVENTF_WHEEL = 0x0800
_KEYEVENTF_KEYUP = 0x0002

_SM_CXSCREEN = 0
_SM_CYSCREEN = 1

# Virtual key codes
_VK_MAP = {
    'esc': 0x1B, 'enter': 0x0D, 'space': 0x20, 'backspace': 0x08,
    'ctrl': 0x11, 'alt': 0x12, 'shift': 0x10,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73,
    'f5': 0x74, 'f6': 0x75, 'f7': 0x76, 'f8': 0x77,
    'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
}

# Legacy Arduino ASCII codes (kept for Arduino driver compatibility)
_ASCII_MAP = {
    'esc': 177, 'enter': 176, 'space': 32,
    'ctrl': 128, 'alt': 130, 'shift': 129,
    'up': 218, 'down': 217, 'left': 216, 'right': 215,
    'backspace': 178,
    'f1': 194, 'f2': 195, 'f3': 196, 'f4': 197,
    'f5': 198, 'f6': 199, 'f7': 200, 'f8': 201,
    'f9': 202, 'f10': 203, 'f11': 204, 'f12': 205,
}


def _vk(key: str) -> int:
    k = key.lower()
    if k in _VK_MAP:
        return _VK_MAP[k]
    if len(k) == 1:
        return ctypes.windll.user32.VkKeyScanA(ord(k)) & 0xFF
    return 0


def _ascii(key: str) -> int:
    k = key.lower()
    if k in _ASCII_MAP:
        return _ASCII_MAP[k]
    if len(k) == 1 and k.isalpha():
        return ord(k)
    return 0


# ── Driver enum ──────────────────────────────────────────────────────────────

class InputDriver(Enum):
    PYAUTOGUI = "pyautogui"
    ARDUINO = "arduino"
    SENDINPUT = "sendinput"


# ── SendInput implementation ─────────────────────────────────────────────────

class _SendInputDriver:
    def __init__(self):
        self._sw = ctypes.windll.user32.GetSystemMetrics(_SM_CXSCREEN)
        self._sh = ctypes.windll.user32.GetSystemMetrics(_SM_CYSCREEN)

    def _send(self, *inputs):
        arr = (_INPUT * len(inputs))(*inputs)
        ctypes.windll.user32.SendInput(len(inputs), arr, ctypes.sizeof(_INPUT))

    def _mouse(self, flags: int, dx: int = 0, dy: int = 0, data: int = 0) -> _INPUT:
        mi = _MOUSEINPUT(dx, dy, data, flags, 0, None)
        return _INPUT(_INPUT_MOUSE, _INPUT_UNION(mi=mi))

    def _key(self, vk: int, flags: int = 0) -> _INPUT:
        ki = _KEYBDINPUT(vk, 0, flags, 0, None)
        return _INPUT(_INPUT_KEYBOARD, _INPUT_UNION(ki=ki))

    def move_to(self, x: int, y: int):
        abs_x = int(x * 65535 / self._sw)
        abs_y = int(y * 65535 / self._sh)
        self._send(self._mouse(_MOUSEEVENTF_MOVE | _MOUSEEVENTF_ABSOLUTE, abs_x, abs_y))

    def left_click(self):
        self._send(self._mouse(_MOUSEEVENTF_LEFTDOWN), self._mouse(_MOUSEEVENTF_LEFTUP))

    def right_click(self):
        self._send(self._mouse(_MOUSEEVENTF_RIGHTDOWN), self._mouse(_MOUSEEVENTF_RIGHTUP))

    def scroll(self, clicks: int):
        self._send(self._mouse(_MOUSEEVENTF_WHEEL, data=clicks * 120))

    def key_down(self, vk: int):
        self._send(self._key(vk))

    def key_up(self, vk: int):
        self._send(self._key(vk, _KEYEVENTF_KEYUP))

    def drag(self, x1: int, y1: int, x2: int, y2: int):
        self.move_to(x1, y1)
        self._send(self._mouse(_MOUSEEVENTF_LEFTDOWN))
        self.move_to(x2, y2)
        self._send(self._mouse(_MOUSEEVENTF_LEFTUP))


# ── Main InputManager ────────────────────────────────────────────────────────

class InputManager:
    def __init__(self):
        self._driver = InputDriver.PYAUTOGUI
        self._arduino_serial = None
        self._si = _SendInputDriver()

    @property
    def driver(self) -> InputDriver:
        return self._driver

    @property
    def driver_name(self) -> str:
        return self._driver.value

    def set_driver(self, driver: InputDriver, port: str = 'COM3', baudrate: int = 115200) -> bool:
        if driver == InputDriver.ARDUINO:
            if not self._connect_arduino(port, baudrate):
                return False
        self._driver = driver
        return True

    def _connect_arduino(self, port: str, baudrate: int) -> bool:
        try:
            import serial
            self._arduino_serial = serial.Serial(port, baudrate, timeout=1)
            return True
        except Exception as e:
            print(f"[InputManager] Arduino unavailable on {port}: {e}")
            return False

    def test_arduino(self, port: str = 'COM3') -> bool:
        try:
            import serial
            s = serial.Serial(port, 115200, timeout=2)
            s.close()
            return True
        except Exception:
            return False

    def _arduino(self, command: str):
        import base64, time
        line = base64.b64encode(command.encode()).decode() + '\n'
        self._arduino_serial.write(line.encode())
        time.sleep(0.01)

    # ── Mouse ─────────────────────────────────────────────────────────────────

    def move_to(self, x: int, y: int):
        if self._driver == InputDriver.ARDUINO:
            self._arduino(f"moveTo,{int(x)},{int(y)}")
        elif self._driver == InputDriver.SENDINPUT:
            self._si.move_to(int(x), int(y))
        else:
            pyautogui.moveTo(int(x), int(y))

    def left_click(self, x: int = None, y: int = None):
        if x is not None:
            self.move_to(x, y)
        if self._driver == InputDriver.ARDUINO:
            self._arduino("leftClick")
        elif self._driver == InputDriver.SENDINPUT:
            self._si.left_click()
        else:
            pyautogui.click()

    def right_click(self, x: int = None, y: int = None):
        if x is not None:
            self.move_to(x, y)
        if self._driver == InputDriver.ARDUINO:
            self._arduino("rightClick")
        elif self._driver == InputDriver.SENDINPUT:
            self._si.right_click()
        else:
            pyautogui.rightClick()

    def scroll(self, clicks: int):
        if self._driver == InputDriver.ARDUINO:
            cx, cy = pyautogui.position()
            self._arduino(f"scroll,{cx},{cy},{clicks}")
        elif self._driver == InputDriver.SENDINPUT:
            self._si.scroll(clicks)
        else:
            pyautogui.scroll(clicks)

    def drag(self, x1: int, y1: int, x2: int, y2: int):
        if self._driver == InputDriver.ARDUINO:
            self._arduino(f"moveTo,{int(x1)},{int(y1)}")
            self._arduino("dragStart")
            self._arduino(f"moveTo,{int(x2)},{int(y2)}")
            self._arduino("dragEnd")
        elif self._driver == InputDriver.SENDINPUT:
            self._si.drag(int(x1), int(y1), int(x2), int(y2))
        else:
            pyautogui.moveTo(int(x1), int(y1))
            pyautogui.dragTo(int(x2), int(y2), button='left')

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def key_down(self, key: str):
        if self._driver == InputDriver.ARDUINO:
            code = _ascii(key)
            if code:
                self._arduino(f"keyDown,{code}")
        elif self._driver == InputDriver.SENDINPUT:
            vk = _vk(key)
            if vk:
                self._si.key_down(vk)
        else:
            pyautogui.keyDown(key)

    def key_up(self, key: str):
        if self._driver == InputDriver.ARDUINO:
            code = _ascii(key)
            if code:
                self._arduino(f"keyUp,{code}")
        elif self._driver == InputDriver.SENDINPUT:
            vk = _vk(key)
            if vk:
                self._si.key_up(vk)
        else:
            pyautogui.keyUp(key)

    def press(self, *keys: str):
        for key in keys:
            if self._driver == InputDriver.ARDUINO:
                code = _ascii(key)
                if code:
                    self._arduino(f"press,{code}")
            elif self._driver == InputDriver.SENDINPUT:
                vk = _vk(key)
                if vk:
                    self._si.key_down(vk)
                    self._si.key_up(vk)
            else:
                pyautogui.press(key)

    def hotkey(self, *keys: str):
        for key in keys:
            self.key_down(key)
        for key in reversed(keys):
            self.key_up(key)

    def write(self, text: str):
        if self._driver == InputDriver.ARDUINO:
            self._arduino(f"write,{text}")
        else:
            pyautogui.write(text)


# Global singleton used by mouse.py and keyboard.py
input_manager = InputManager()
