from .input_manager import input_manager


def getAsciiFromKey(key: str) -> int:
    """Kept for backwards compatibility with code that uses this directly."""
    from .input_manager import _ascii
    if key == '?':
        return 63
    return _ascii(key)


def hotkey(*args):
    input_manager.hotkey(*args)


def keyDown(key: str):
    input_manager.key_down(key)


def keyUp(key: str):
    input_manager.key_up(key)


def press(*args):
    input_manager.press(*args)


def write(phrase: str):
    input_manager.write(phrase)
