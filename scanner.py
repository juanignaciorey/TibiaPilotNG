"""
Standalone scanner — runs only the Scanner page without starting the bot.
Usage:  py -3.11 scanner.py
"""
import customtkinter
from src.ui.pages.scannerPage import ScannerPage

customtkinter.set_appearance_mode("dark")


class _FakeContext:
    """Minimal context stub so ScannerPage doesn't need the full bot context."""
    def __init__(self):
        self.context = {
            'memory_profile': {'game': None, 'attached_pid': None},
            'input_driver': 'pyautogui',
        }


class _StandaloneApp(customtkinter.CTk):
    def __init__(self):
        super().__init__()
        self.withdraw()   # hide the root window — scanner is the only window
        self._ctx = _FakeContext()
        self._page = ScannerPage(self._ctx)
        self._page.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        import os
        os._exit(0)


if __name__ == '__main__':
    app = _StandaloneApp()
    app.mainloop()
