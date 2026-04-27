"""
Scanner Page — process browser, input driver switcher, pointer learner, coordinate wizard.
"""
import sys
import ctypes
import threading
import time
import customtkinter
import tkinter as tk
import tkinter.ttk as ttk
from tkinter import simpledialog, messagebox
from typing import List, Optional, Dict

from src.utils.memory import memory_reader, list_processes
from src.utils.pointer_scanner import pointer_scanner, ScanType
from src.utils.input_manager import input_manager, InputDriver
from ..utils import genRanStr

MAX_CANDIDATES_SHOWN = 30
MIN_PROC_MB = 1          # hide processes smaller than this
_NEEDS_VALUE = {ScanType.EXACT, ScanType.INCREASED_BY, ScanType.DECREASED_BY}
_HINTS = {
    ScanType.EXACT:        "Enter the value you see on screen (HP, Mana, level…)",
    ScanType.UNKNOWN:      "Value not visible on screen. Snapshots all writable memory.",
    ScanType.CHANGED:      "Keeps addresses whose value changed since last scan.",
    ScanType.UNCHANGED:    "Keeps addresses whose value did NOT change.",
    ScanType.INCREASED:    "Keeps addresses whose value went UP (any amount).",
    ScanType.DECREASED:    "Keeps addresses whose value went DOWN (any amount).",
    ScanType.INCREASED_BY: "Kept addresses that increased by exactly N (1 tile right → N=1).",
    ScanType.DECREASED_BY: "Kept addresses that decreased by exactly N.",
}
_WIZARD_STEPS = [
    ("player_x", "Move RIGHT  →  1 tile",        ScanType.INCREASED_BY, 1),
    ("player_y", "Move DOWN   ↓  1 tile",         ScanType.INCREASED_BY, 1),
    ("player_z", "Go DOWN one floor (hole/rope)", ScanType.INCREASED_BY, 1),
]
_SKIP_NAMES = {
    'python', 'python3', 'pythonw', 'py', 'explorer', 'svchost', 'system',
    'csrss', 'winlogon', 'services', 'lsass', 'dwm', 'taskhostw', 'conhost',
    'wininit', 'smss', 'fontdrvhost', 'spoolsv', 'searchhost', 'idle',
    'registry', 'memcompression', 'securityhealthservice',
}

# exe_path → PIL Image | False  (background-thread-safe)
_icon_cache: Dict[str, object] = {}
# exe_path → ImageTk.PhotoImage  (main-thread only, created lazily)
_photo_cache: Dict[str, object] = {}


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _extract_exe_icon_pil(path: str, size: int = 16):
    """Return a PIL Image from an exe icon, or None. Safe to call from any thread."""
    try:
        import win32gui, win32ui
        from PIL import Image
        large, small = win32gui.ExtractIconEx(path, 0)
        if not large and not small:
            return None
        hicon = (large or small)[0]
        for lst in (large, small):
            for h in lst[1:]:
                try:
                    win32gui.DestroyIcon(h)
                except Exception:
                    pass
        hdc_screen = win32gui.GetDC(0)
        hdc = win32ui.CreateDCFromHandle(hdc_screen)
        hdc_mem = hdc.CreateCompatibleDC()
        hbmp = win32ui.CreateBitmap()
        hbmp.CreateCompatibleBitmap(hdc, 32, 32)
        hdc_mem.SelectObject(hbmp)
        hdc_mem.FillSolidRect((0, 0, 32, 32), 0x1E1E1E)
        hdc_mem.DrawIcon((0, 0), hicon)
        bmpinfo = hbmp.GetInfo()
        bmpstr = hbmp.GetBitmapBits(True)
        img = Image.frombuffer(
            'RGB', (bmpinfo['bmWidth'], bmpinfo['bmHeight']),
            bmpstr, 'raw', 'BGRX', 0, 1,
        ).resize((size, size))
        win32gui.DestroyIcon(hicon)
        win32gui.DeleteObject(hbmp.GetHandle())
        hdc_mem.DeleteDC()
        hdc.DeleteDC()
        win32gui.ReleaseDC(0, hdc_screen)
        return img
    except Exception:
        return None


def _get_photo(exe: str) -> object:
    """Convert cached PIL image to PhotoImage (must be called from main thread)."""
    if exe in _photo_cache:
        return _photo_cache[exe]
    pil = _icon_cache.get(exe)
    if pil and pil is not False:
        try:
            from PIL import ImageTk
            photo = ImageTk.PhotoImage(pil)
            _photo_cache[exe] = photo
            return photo
        except Exception:
            pass
    return None


def _load_icons_bg(procs: list, done_cb):
    """Load PIL images in background; done_cb fires in main thread to create PhotoImages."""
    def _run():
        for p in procs:
            exe = p.get('exe')
            if exe and exe not in _icon_cache:
                pil = _extract_exe_icon_pil(exe, size=16)
                _icon_cache[exe] = pil if pil else False
        done_cb()
    threading.Thread(target=_run, daemon=True).start()


def _find_game_windows(pid: int):
    """Return list of (hwnd, rect) for visible windows owned by pid (width > 100)."""
    try:
        import win32gui, win32process
        results = []
        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                _, wpid = win32process.GetWindowThreadProcessId(hwnd)
                if wpid == pid:
                    r = win32gui.GetWindowRect(hwnd)
                    if r[2] - r[0] > 100:
                        results.append((hwnd, r))
        win32gui.EnumWindows(cb, None)
        return results
    except Exception:
        return []


def _get_game_window_rect(pid: int):
    wins = _find_game_windows(pid)
    if wins:
        r = wins[0][1]
        return r[0], r[1], r[2] - r[0], r[3] - r[1]
    return None


def _get_game_hwnd(pid: int):
    wins = _find_game_windows(pid)
    return wins[0][0] if wins else None


def _apply_dark_treeview_style():
    style = ttk.Style()
    try:
        style.theme_use('clam')
    except Exception:
        pass
    style.configure("Scanner.Treeview",
        background="#1c1c1c",
        foreground="#dddddd",
        fieldbackground="#1c1c1c",
        borderwidth=0,
        rowheight=22,
        font=('Segoe UI', 10),
    )
    style.configure("Scanner.Treeview.Heading",
        background="#111111",
        foreground="#888888",
        borderwidth=1,
        relief='flat',
        font=('Segoe UI', 9, 'bold'),
    )
    style.map("Scanner.Treeview",
        background=[('selected', '#7a0020')],
        foreground=[('selected', '#ffffff')],
    )


class ScannerPage(customtkinter.CTkToplevel):
    def __init__(self, context):
        super().__init__()
        self.context = context
        self.title(genRanStr())
        self.resizable(False, False)

        _apply_dark_treeview_style()

        self._processes: list = []
        self._filtered_pids: list = []   # iids currently in tree
        self._selected_proc: Optional[dict] = None
        self._attach_status  = tk.StringVar(value="Not attached")
        self._driver_status  = tk.StringVar(value=f"Active: {input_manager.driver_name}")
        self._current_game   = tk.StringVar()
        self._scan_status    = tk.StringVar(value="No scan active")
        self._hint_text      = tk.StringVar(value=_HINTS[ScanType.UNKNOWN])
        self._kfilter = ""   # keyboard-typed filter string

        self._wiz_step           = 0
        self._wiz_status         = tk.StringVar(value="")
        self._wiz_instruction    = tk.StringVar(value="")
        self._pending_autodetect = False

        self._build_ui()
        self._refresh_game_dropdown()
        self._start_live_refresh()
        self.after(30, self._refresh_processes_bg)   # instant open, load async
        # Global key capture — filter while no text-input is focused
        self.bind('<KeyPress>', self._on_window_key)

    # ── Top-level layout ──────────────────────────────────────────────────────

    def _build_ui(self):
        self._build_process_frame()
        self._build_driver_frame()
        tabs = customtkinter.CTkTabview(self, width=720)
        tabs.grid(row=2, column=0, columnspan=2, padx=10, pady=(4, 10), sticky='nsew')
        tabs.add("Coordinate Wizard")
        tabs.add("Manual Scanner")
        tabs.add("Saved Pointers")
        self._build_wizard_tab(tabs.tab("Coordinate Wizard"))
        self._build_manual_tab(tabs.tab("Manual Scanner"))
        self._build_saved_tab(tabs.tab("Saved Pointers"))

    # ── Process browser ───────────────────────────────────────────────────────

    def _build_process_frame(self):
        f = customtkinter.CTkFrame(self)
        f.grid(row=0, column=0, columnspan=2, padx=10, pady=(10, 4), sticky='ew')
        f.columnconfigure(0, weight=1)

        # Header
        hdr = customtkinter.CTkFrame(f, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky='ew', padx=8, pady=(8, 2))
        hdr.columnconfigure(0, weight=1)
        customtkinter.CTkLabel(hdr, text="Target Process:", font=("", 12, "bold")).grid(
            row=0, column=0, sticky='w')
        customtkinter.CTkButton(
            hdr, text="Refresh", width=75, corner_radius=20, height=26,
            fg_color="transparent", border_color="#C20034", border_width=2, hover_color="#C20034",
            command=self._refresh_processes_bg,
        ).grid(row=0, column=1, padx=4)
        customtkinter.CTkButton(
            hdr, text="Auto-detect", width=95, corner_radius=20, height=26,
            fg_color="transparent", border_color="#C20034", border_width=2, hover_color="#C20034",
            command=self._autodetect_process,
        ).grid(row=0, column=2, padx=4)

        # ── Browse frame (hidden while attached) ──────────────────────────────
        self._browse_frame = tk.Frame(f, bg="#1a1a1a")
        self._browse_frame.grid(row=1, column=0, sticky='ew', padx=8, pady=2)
        self._browse_frame.columnconfigure(0, weight=1)

        # Treeview + scrollbar
        tree_frame = tk.Frame(self._browse_frame, bg="#1c1c1c")
        tree_frame.grid(row=0, column=0, sticky='ew')
        tree_frame.columnconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=('pid', 'mem'),
            show='tree headings',
            height=8,
            style="Scanner.Treeview",
            selectmode='browse',
        )
        self._tree.heading('#0',  text='Process',  anchor='w')
        self._tree.heading('pid', text='PID',      anchor='center')
        self._tree.heading('mem', text='MB',       anchor='e')
        self._tree.column('#0',  width=280, stretch=False, anchor='w')
        self._tree.column('pid', width=75,  stretch=False, anchor='center')
        self._tree.column('mem', width=65,  stretch=False, anchor='e')

        vsb = ttk.Scrollbar(tree_frame, orient='vertical', command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky='nsew')
        vsb.grid(row=0, column=1, sticky='ns')

        self._tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self._tree.bind('<Double-Button-1>', lambda _: self._toggle_attach())

        # Keyboard filter indicator
        self._kfilter_label = customtkinter.CTkLabel(
            self._browse_frame, text="", text_color="#C20034", font=("", 10), anchor='w')
        self._kfilter_label.grid(row=1, column=0, padx=4, pady=(2, 0), sticky='w')

        # ── Attached info ─────────────────────────────────────────────────────
        self._attached_info = customtkinter.CTkLabel(
            f, text="", font=("", 12), text_color="#44cc44", anchor='w')
        # hidden until attached

        # Status bar
        bar = customtkinter.CTkFrame(f, fg_color="transparent")
        bar.grid(row=3, column=0, sticky='ew', padx=8, pady=(2, 8))
        self._selected_label = customtkinter.CTkLabel(
            bar, text="No process selected", text_color="#888888", anchor='w', width=280)
        self._selected_label.grid(row=0, column=0, sticky='w')
        self._attach_btn = customtkinter.CTkButton(
            bar, text="Attach", width=80, corner_radius=20,
            fg_color="#C20034", hover_color="#870125",
            command=self._toggle_attach,
        )
        self._attach_btn.grid(row=0, column=1, padx=6)
        if not _is_admin():
            customtkinter.CTkButton(
                bar, text="Run as Admin ↑", width=120, corner_radius=20,
                fg_color="transparent", border_color="#870125",
                border_width=2, hover_color="#870125",
                command=self._restart_as_admin,
            ).grid(row=0, column=2, padx=4)
        customtkinter.CTkLabel(
            bar, textvariable=self._attach_status, text_color="#aaaaaa"
        ).grid(row=0, column=3, padx=10)

    # ── Keyboard filter (Cheat Engine style) ──────────────────────────────────

    def _on_window_key(self, event):
        """Capture typing anywhere in the window to filter the process list.
        Ignored when a text-entry widget has keyboard focus."""
        focused = self.focus_get()
        if focused:
            cls = focused.winfo_class()
            if cls in ('Entry', 'TEntry', 'Text'):
                return   # let the focused input handle it

        ch = event.char
        if ch and ch.isprintable():
            self._kfilter += ch.lower()
        elif event.keysym == 'BackSpace':
            self._kfilter = self._kfilter[:-1]
        elif event.keysym == 'Escape':
            self._kfilter = ""
        elif event.keysym == 'Return':
            self._toggle_attach()
            return
        else:
            return

        self._kfilter_label.configure(
            text=f"  filter: {self._kfilter}" if self._kfilter else "")
        self._repopulate_tree()

    # ── Process loading ───────────────────────────────────────────────────────

    def _refresh_processes_bg(self):
        # Only show loading placeholder when the browse frame is visible
        if not memory_reader.attached:
            self._tree.delete(*self._tree.get_children())
            self._tree.insert('', 'end', iid='__loading__',
                              text='  Loading processes…', values=('', ''))
        threading.Thread(target=self._load_procs_thread, daemon=True).start()

    def _load_procs_thread(self):
        try:
            procs = list_processes()
            try:
                import psutil
                for p in procs:
                    try:
                        p['exe'] = psutil.Process(p['pid']).exe()
                    except Exception:
                        p['exe'] = None
            except ImportError:
                pass
        except Exception:
            procs = []
        try:
            self.after(0, lambda: self._procs_loaded(procs))
        except Exception:
            pass

    def _procs_loaded(self, procs):
        self._processes = procs
        if not memory_reader.attached:
            self._attach_status.set("Not attached")
        self._repopulate_tree()
        # Load icons in background then refresh tree items (main thread converts to PhotoImage)
        uncached = [p for p in procs if p.get('exe') and p['exe'] not in _icon_cache]
        if uncached:
            _load_icons_bg(uncached, done_cb=lambda: self.after(0, self._update_tree_icons))
        if self._pending_autodetect:
            self._autodetect_process()

    def _repopulate_tree(self):
        """Rebuild the tree from self._processes applying current kfilter and MIN_PROC_MB."""
        term = self._kfilter
        pid_map = {p['pid']: p for p in self._processes}

        self._tree.delete(*self._tree.get_children())
        count = 0
        for p in self._processes:
            if p['memory_mb'] < MIN_PROC_MB:
                continue
            if term and term not in p['name'].lower() and term not in str(p['pid']):
                continue
            iid = str(p['pid'])
            img = _get_photo(p.get('exe') or '') or ''
            self._tree.insert('', 'end', iid=iid,
                              image=img,
                              text=f"  {p['name']}",
                              values=(p['pid'], f"{p['memory_mb']}"))
            count += 1

        # Re-select previously selected proc if still visible
        if self._selected_proc:
            sel_iid = str(self._selected_proc['pid'])
            if self._tree.exists(sel_iid):
                self._tree.selection_set(sel_iid)
                self._tree.see(sel_iid)

    def _update_tree_icons(self):
        """Convert freshly loaded PIL images to PhotoImages and update tree items.
        Must run in main thread (PhotoImage creation requires it)."""
        for p in self._processes:
            exe = p.get('exe')
            if not exe:
                continue
            photo = _get_photo(exe)   # creates PhotoImage from PIL cache (main thread)
            if photo:
                iid = str(p['pid'])
                if self._tree.exists(iid):
                    try:
                        self._tree.item(iid, image=photo)
                    except Exception:
                        pass

    def _on_tree_select(self, _=None):
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid == '__loading__':
            return
        pid = int(iid)
        proc = next((p for p in self._processes if p['pid'] == pid), None)
        if proc:
            self._selected_proc = proc
            self._selected_label.configure(
                text=f"{proc['name']}  PID {proc['pid']}  {proc['memory_mb']} MB")

    def _autodetect_process(self):
        if not self._processes:
            # Processes not loaded yet — load them, then auto-detect
            self._pending_autodetect = True
            self._refresh_processes_bg()
            return
        self._pending_autodetect = False
        best = None
        for p in self._processes:
            if p['name'].lower().replace('.exe', '') in _SKIP_NAMES:
                continue
            if p['memory_mb'] < MIN_PROC_MB:
                continue
            if best is None or p['memory_mb'] > best['memory_mb']:
                best = p
        if best:
            self._selected_proc = best
            self._selected_label.configure(
                text=f"{best['name']}  PID {best['pid']}  {best['memory_mb']} MB")
            self._kfilter = ""
            self._kfilter_label.configure(text="")
            self._repopulate_tree()

    def _toggle_attach(self):
        if memory_reader.attached:
            memory_reader.detach()
            self.context.context['memory_profile']['attached_pid'] = None
            self._attach_status.set("Detached")
            self._attach_btn.configure(text="Attach")
            self._attached_info.grid_remove()
            self._browse_frame.grid()
            return

        if self._selected_proc is None:
            messagebox.showwarning("No process", "Select a process first.", parent=self)
            return
        proc = self._selected_proc
        ok = memory_reader.attach(proc['pid'], proc['name'])
        if ok:
            self.context.context['memory_profile']['attached_pid'] = proc['pid']
            self._attach_status.set("Attached")
            self._attach_btn.configure(text="Detach")
            self._attached_info.configure(
                text=f"  ● Attached:  {proc['name']}   PID {proc['pid']}   {proc['memory_mb']} MB")
            self._browse_frame.grid_remove()
            self._attached_info.grid(row=1, column=0, padx=8, pady=6, sticky='w')
        else:
            if not _is_admin():
                if messagebox.askyesno(
                    "Admin required",
                    "Reading game memory requires Administrator privileges.\n\n"
                    "Restart as Administrator now?",
                    parent=self,
                ):
                    self._restart_as_admin()
            else:
                self._attach_status.set("Failed — process may be system-protected")

    def _restart_as_admin(self):
        try:
            ctypes.windll.shell32.ShellExecuteW(
                None, "runas", sys.executable,
                " ".join(f'"{a}"' for a in sys.argv),
                None, 1,
            )
            self.after(500, lambda: self.winfo_toplevel().destroy())
        except Exception as e:
            messagebox.showerror("Error", f"Could not elevate: {e}", parent=self)

    # ── Input driver frame ────────────────────────────────────────────────────

    def _build_driver_frame(self):
        f = customtkinter.CTkFrame(self)
        f.grid(row=1, column=0, columnspan=2, padx=10, pady=4, sticky='ew')

        customtkinter.CTkLabel(f, text="Input Driver:", font=("", 12, "bold")).grid(
            row=0, column=0, columnspan=8, padx=12, pady=(8, 4), sticky='w')

        self._driver_var = tk.StringVar(value=input_manager.driver_name)
        self._port_var   = tk.StringVar(value="COM3")

        rows = [
            ("PyAutoGUI", "pyautogui", False),
            ("SendInput", "sendinput", False),
            ("Arduino",   "arduino",   True),
        ]
        for grid_row, (label, val, has_port) in enumerate(rows, start=1):
            rb = customtkinter.CTkRadioButton(
                f, text=label, variable=self._driver_var, value=val,
                fg_color="#C20034", hover_color="#870125",
                command=self._on_driver_change,
            )
            rb.grid(row=grid_row, column=0, padx=(12, 6), pady=3, sticky='w')

            col = 1
            if has_port:
                customtkinter.CTkLabel(f, text="Port:").grid(
                    row=grid_row, column=col, padx=(8, 2))
                col += 1
                customtkinter.CTkEntry(f, textvariable=self._port_var, width=65).grid(
                    row=grid_row, column=col, padx=(0, 6))
                col += 1

            customtkinter.CTkButton(
                f, text="Test mouse + keyboard", width=165, height=26, corner_radius=20,
                fg_color="transparent", border_color="#C20034", border_width=2,
                hover_color="#C20034",
                command=lambda v=val: self._test_driver(v),
            ).grid(row=grid_row, column=col, padx=4, sticky='w')

        customtkinter.CTkLabel(
            f, textvariable=self._driver_status, text_color="#aaaaaa", font=("", 11),
        ).grid(row=4, column=0, columnspan=8, padx=12, pady=(2, 8), sticky='w')

    def _on_driver_change(self):
        driver = InputDriver(self._driver_var.get())
        ok = input_manager.set_driver(driver, port=self._port_var.get())
        self._driver_var.set(input_manager.driver_name)
        self.context.context['input_driver'] = input_manager.driver_name
        self._driver_status.set(
            f"Active: {input_manager.driver_name}" if ok else
            f"Fallback: {input_manager.driver_name} ({InputDriver(self._driver_var.get()).value} unavailable)")

    def _test_driver(self, driver_name: str):
        try:
            ok = input_manager.set_driver(InputDriver(driver_name), port=self._port_var.get())
            self._driver_var.set(input_manager.driver_name)
            self.context.context['input_driver'] = input_manager.driver_name
            if not ok:
                self._driver_status.set(f"{driver_name}: not available")
                return
        except Exception as e:
            self._driver_status.set(f"Error: {e}")
            return

        rect      = _get_game_window_rect(self._selected_proc['pid']) if self._selected_proc else None
        game_hwnd = _get_game_hwnd(self._selected_proc['pid']) if self._selected_proc else None

        def _do():
            # Focus the game window so arrow keys land on it
            if game_hwnd:
                try:
                    import win32gui
                    win32gui.SetForegroundWindow(game_hwnd)
                    time.sleep(0.15)
                except Exception:
                    pass

            if rect:
                x, y, w, h = rect
                cx, cy = x + w // 2, y + h // 2
                input_manager.move_to(cx, cy)
                time.sleep(0.1)

            # Arrow key cross: up → right → down → left (character walks a small loop)
            for direction in ('up', 'right', 'down', 'left'):
                input_manager.key_down(direction)
                time.sleep(0.18)
                input_manager.key_up(direction)
                time.sleep(0.12)

            self.after(0, lambda: self._driver_status.set(
                f"{driver_name}: ↑→↓← sent  (active: {input_manager.driver_name})"))

        self._driver_status.set(f"Testing {driver_name}… (focuses game window)")
        threading.Thread(target=_do, daemon=True).start()

    # ── Coordinate Wizard tab ─────────────────────────────────────────────────

    def _build_wizard_tab(self, parent):
        parent.columnconfigure(0, weight=1)

        top = customtkinter.CTkFrame(parent)
        top.grid(row=0, column=0, padx=8, pady=(8, 4), sticky='ew')
        top.columnconfigure(1, weight=1)
        customtkinter.CTkLabel(top, text="Save to profile:").grid(row=0, column=0, padx=8)
        self._wiz_game_combo = customtkinter.CTkComboBox(
            top, variable=self._current_game, state='readonly', width=200,
            command=lambda _: None)
        self._wiz_game_combo.grid(row=0, column=1, padx=6)
        customtkinter.CTkButton(
            top, text="New Profile", width=100, corner_radius=20,
            fg_color="transparent", border_color="#C20034", border_width=2, hover_color="#C20034",
            command=self._new_profile,
        ).grid(row=0, column=2, padx=6)

        panel = customtkinter.CTkFrame(parent)
        panel.grid(row=1, column=0, padx=8, pady=4, sticky='ew')
        panel.columnconfigure(0, weight=1)

        customtkinter.CTkLabel(
            panel,
            text="Learns player_x / player_y / player_z automatically — just walk in-game.",
            font=("", 12), justify='left', wraplength=640,
        ).grid(row=0, column=0, columnspan=3, padx=12, pady=(10, 6), sticky='w')

        self._wiz_step_label = customtkinter.CTkLabel(
            panel, text="", font=("", 13, "bold"), text_color="#C20034")
        self._wiz_step_label.grid(row=1, column=0, columnspan=3, padx=12, pady=(4, 0), sticky='w')

        self._wiz_instr_label = customtkinter.CTkLabel(
            panel, textvariable=self._wiz_instruction,
            font=("", 11), text_color="#cccccc", wraplength=620, justify='left')
        self._wiz_instr_label.grid(row=2, column=0, columnspan=3, padx=12, pady=4, sticky='w')

        btn_row = customtkinter.CTkFrame(panel, fg_color="transparent")
        btn_row.grid(row=3, column=0, columnspan=3, padx=8, pady=6, sticky='w')

        self._wiz_snapshot_btn = customtkinter.CTkButton(
            btn_row, text="1. Snapshot Memory", width=160, corner_radius=20,
            fg_color="#C20034", hover_color="#870125",
            command=self._wiz_do_snapshot)
        self._wiz_snapshot_btn.grid(row=0, column=0, padx=6)

        self._wiz_moved_btn = customtkinter.CTkButton(
            btn_row, text="2. I Moved →", width=140, corner_radius=20,
            fg_color="transparent", border_color="#C20034", border_width=2, hover_color="#C20034",
            state='disabled', command=self._wiz_filter)
        self._wiz_moved_btn.grid(row=0, column=1, padx=6)

        self._wiz_again_btn = customtkinter.CTkButton(
            btn_row, text="3. Move Again →", width=140, corner_radius=20,
            fg_color="transparent", border_color="#555", border_width=2, hover_color="#555",
            state='disabled', command=self._wiz_filter)
        self._wiz_again_btn.grid(row=0, column=2, padx=6)

        customtkinter.CTkButton(
            btn_row, text="Skip", width=70, corner_radius=20,
            fg_color="transparent", border_color="#555", border_width=2, hover_color="#555",
            command=self._wiz_skip,
        ).grid(row=0, column=3, padx=6)

        customtkinter.CTkButton(
            btn_row, text="Restart", width=80, corner_radius=20,
            fg_color="transparent", border_color="#870125", border_width=2, hover_color="#870125",
            command=self._wiz_restart,
        ).grid(row=0, column=4, padx=6)

        customtkinter.CTkLabel(
            panel, textvariable=self._wiz_status, text_color="#aaaaaa", font=("", 11),
        ).grid(row=4, column=0, columnspan=3, padx=12, pady=(2, 4), sticky='w')

        self._wiz_cand_frame = customtkinter.CTkScrollableFrame(panel, height=90)
        self._wiz_cand_frame.grid(row=5, column=0, columnspan=3, padx=8, pady=(0, 8), sticky='ew')

        self._update_wizard_instruction()

    def _update_wizard_instruction(self):
        if self._wiz_step >= len(_WIZARD_STEPS):
            self._wiz_step_label.configure(text="✓ All done!")
            self._wiz_instruction.set(
                "All coordinates saved. Go to Saved Pointers → Use This Profile.")
            return
        name, direction, _, _ = _WIZARD_STEPS[self._wiz_step]
        self._wiz_step_label.configure(
            text=f"Step {self._wiz_step + 1} of {len(_WIZARD_STEPS)} — {name}")
        self._wiz_instruction.set(
            f"① Click 'Snapshot Memory'  (stay still in-game)\n"
            f"② Go to the game and {direction}\n"
            f"③ Come back and click 'I Moved'\n"
            f"   If many candidates remain → move again → 'Move Again'\n"
            f"   When few remain, click the correct address to save it"
        )
        self._wiz_moved_btn.configure(text=f"2. I Moved  ({direction.split()[1]})")

    def _wiz_do_snapshot(self):
        if not memory_reader.attached:
            messagebox.showwarning("Not attached", "Attach to a process first.", parent=self)
            return
        self._wiz_status.set("Snapshotting memory…")
        self._wiz_snapshot_btn.configure(state='disabled')
        self._wiz_moved_btn.configure(state='disabled')
        self._wiz_again_btn.configure(state='disabled')

        def _progress(done, total):
            self.after(0, lambda: self._wiz_status.set(f"Snapshotting… {done}/{total} MB"))

        def _run():
            count = pointer_scanner.first_scan(ScanType.UNKNOWN, progress_cb=_progress)
            self.after(0, lambda: self._wiz_snapshot_done(count))

        threading.Thread(target=_run, daemon=True).start()

    def _wiz_snapshot_done(self, count: int):
        self._wiz_snapshot_btn.configure(state='normal')
        self._wiz_moved_btn.configure(state='normal')
        step = _WIZARD_STEPS[self._wiz_step]
        if count == 0:
            self._wiz_status.set(
                "⚠ 0 addresses found. Make sure you are attached and the process is running.")
        else:
            self._wiz_status.set(
                f"Snapshot: {count:,} addresses. Now {step[1]}.")

    def _wiz_filter(self):
        if pointer_scanner.candidate_count() == 0:
            messagebox.showwarning("No snapshot", "Click 'Snapshot Memory' first.", parent=self)
            return
        _, _, scan_type, amount = _WIZARD_STEPS[self._wiz_step]
        self._wiz_status.set("Filtering…")

        def _run():
            count = pointer_scanner.next_scan(scan_type, amount)
            self.after(0, lambda: self._wiz_filter_done(count))

        threading.Thread(target=_run, daemon=True).start()

    def _wiz_filter_done(self, count: int):
        self._wiz_again_btn.configure(state='normal')
        name      = _WIZARD_STEPS[self._wiz_step][0]
        direction = _WIZARD_STEPS[self._wiz_step][1]
        if count == 0:
            self._wiz_status.set("0 candidates — restart this step.")
            pointer_scanner.reset_scan()
            self._wiz_again_btn.configure(state='disabled')
            self._wiz_moved_btn.configure(state='disabled')
        elif count <= 10:
            self._wiz_status.set(f"{count} candidates for '{name}' — click the correct address.")
            self._render_wiz_candidates(name)
        else:
            self._wiz_status.set(f"{count:,} remaining — {direction} then 'Move Again'.")
            self._render_wiz_candidates(name)

    def _render_wiz_candidates(self, var_name: str):
        for w in self._wiz_cand_frame.winfo_children():
            w.destroy()
        for idx, addr in enumerate(pointer_scanner.candidates[:MAX_CANDIDATES_SHOWN]):
            live = memory_reader.read_uint32(addr)
            customtkinter.CTkButton(
                self._wiz_cand_frame,
                text=f"{hex(addr)}  =  {live}", width=200, height=26, corner_radius=8,
                fg_color="transparent", border_color="#C20034",
                border_width=1, hover_color="#C20034",
                command=lambda a=addr, n=var_name: self._wiz_save(n, a),
            ).grid(row=idx // 3, column=idx % 3, padx=4, pady=2)

    def _wiz_save(self, var_name: str, address: int):
        game = self._current_game.get().strip()
        if not game:
            messagebox.showwarning("No profile", "Create or select a game profile first.", parent=self)
            return
        pointer_scanner.save_pointer(game, var_name, address)
        pointer_scanner.reset_scan()
        for w in self._wiz_cand_frame.winfo_children():
            w.destroy()
        self._wiz_step += 1
        self._wiz_moved_btn.configure(state='disabled')
        self._wiz_again_btn.configure(state='disabled')
        self._update_wizard_instruction()
        msg = (f"✓ {var_name} saved! Now snapshot for {_WIZARD_STEPS[self._wiz_step][0]}."
               if self._wiz_step < len(_WIZARD_STEPS) else "✓ All coordinates saved!")
        self._wiz_status.set(msg)
        self._refresh_saved_table()

    def _wiz_skip(self):
        pointer_scanner.reset_scan()
        for w in self._wiz_cand_frame.winfo_children():
            w.destroy()
        self._wiz_step = min(self._wiz_step + 1, len(_WIZARD_STEPS))
        self._wiz_moved_btn.configure(state='disabled')
        self._wiz_again_btn.configure(state='disabled')
        self._update_wizard_instruction()
        self._wiz_status.set("Step skipped.")

    def _wiz_restart(self):
        self._wiz_step = 0
        pointer_scanner.reset_scan()
        for w in self._wiz_cand_frame.winfo_children():
            w.destroy()
        self._wiz_moved_btn.configure(state='disabled')
        self._wiz_again_btn.configure(state='disabled')
        self._update_wizard_instruction()
        self._wiz_status.set("Wizard restarted.")

    # ── Manual Scanner tab ────────────────────────────────────────────────────

    def _build_manual_tab(self, parent):
        parent.columnconfigure(3, weight=1)
        customtkinter.CTkLabel(
            parent,
            text="Exact Value: for visible numbers (HP, Mana…).  "
                 "Unknown + change filters: for hidden values.",
            font=("", 11), text_color="#aaaaaa", justify='left',
        ).grid(row=0, column=0, columnspan=6, padx=10, pady=(8, 4), sticky='w')

        customtkinter.CTkLabel(parent, text="Name:").grid(row=1, column=0, padx=10, sticky='w')
        self._learn_name = tk.StringVar()
        customtkinter.CTkEntry(parent, textvariable=self._learn_name, width=120).grid(
            row=1, column=1, padx=4)
        customtkinter.CTkLabel(parent, text="Type:").grid(row=1, column=2, padx=(12, 4), sticky='w')
        self._scan_type_var = tk.StringVar(value=ScanType.UNKNOWN.value)
        customtkinter.CTkComboBox(
            parent, values=[s.value for s in ScanType],
            variable=self._scan_type_var, state='readonly', width=190,
            command=self._on_scan_type_change,
        ).grid(row=1, column=3, padx=4)
        customtkinter.CTkLabel(parent, text="Value:").grid(row=1, column=4, padx=(12, 4), sticky='w')
        self._learn_val = tk.StringVar()
        self._val_entry = customtkinter.CTkEntry(parent, textvariable=self._learn_val, width=80)
        self._val_entry.grid(row=1, column=5, padx=4)

        customtkinter.CTkLabel(parent, text="Profile:").grid(row=2, column=0, padx=10, pady=4, sticky='w')
        self._man_game_combo = customtkinter.CTkComboBox(
            parent, variable=self._current_game, state='readonly', width=180,
            command=lambda _: None)
        self._man_game_combo.grid(row=2, column=1, columnspan=2, padx=4, pady=4)

        customtkinter.CTkLabel(
            parent, textvariable=self._hint_text,
            text_color="#666666", font=("", 11), wraplength=580, justify='left',
        ).grid(row=3, column=0, columnspan=6, padx=10, pady=(2, 6), sticky='w')

        self._first_btn = customtkinter.CTkButton(
            parent, text="First Scan", width=110, corner_radius=20,
            fg_color="#C20034", hover_color="#870125", command=self._do_first_scan)
        self._first_btn.grid(row=4, column=0, padx=10, pady=6)
        customtkinter.CTkButton(
            parent, text="Next Scan", width=110, corner_radius=20,
            fg_color="transparent", border_color="#C20034", border_width=2, hover_color="#C20034",
            command=self._do_next_scan,
        ).grid(row=4, column=1, padx=4)
        customtkinter.CTkButton(
            parent, text="Reset", width=70, corner_radius=20,
            fg_color="transparent", border_color="#555", border_width=2, hover_color="#555",
            command=self._reset_scan,
        ).grid(row=4, column=2, padx=4)
        customtkinter.CTkLabel(
            parent, textvariable=self._scan_status, text_color="#aaaaaa"
        ).grid(row=4, column=3, columnspan=3, padx=10, sticky='w')

        customtkinter.CTkLabel(
            parent, text=f"Candidates (click to save, first {MAX_CANDIDATES_SHOWN}):",
            font=("", 11, "bold"),
        ).grid(row=5, column=0, columnspan=6, padx=10, pady=(6, 2), sticky='w')
        self._cand_frame = customtkinter.CTkScrollableFrame(parent, height=130)
        self._cand_frame.grid(row=6, column=0, columnspan=6, padx=8, pady=(0, 8), sticky='ew')

        self._on_scan_type_change()

    def _on_scan_type_change(self, _=None):
        st = self._get_scan_type()
        self._hint_text.set(_HINTS.get(st, ""))
        self._val_entry.configure(state='normal' if st in _NEEDS_VALUE else 'disabled')

    def _get_scan_type(self) -> ScanType:
        for st in ScanType:
            if st.value == self._scan_type_var.get():
                return st
        return ScanType.UNKNOWN

    def _do_first_scan(self):
        if not memory_reader.attached:
            messagebox.showwarning("Not attached", "Attach to a process first.", parent=self)
            return
        st = self._get_scan_type()
        value = 0
        if st in _NEEDS_VALUE:
            try:
                value = int(self._learn_val.get())
            except ValueError:
                messagebox.showwarning("Invalid", "Enter a valid integer.", parent=self)
                return
        self._scan_status.set("Scanning…")
        self._first_btn.configure(state='disabled')

        def _progress(done, total):
            self.after(0, lambda: self._scan_status.set(f"Scanning… {done}/{total} MB"))

        def _run():
            count = pointer_scanner.first_scan(
                st, value, _progress if st == ScanType.UNKNOWN else None)
            self.after(0, lambda: self._scan_done(count))

        threading.Thread(target=_run, daemon=True).start()

    def _do_next_scan(self):
        if pointer_scanner.candidate_count() == 0:
            messagebox.showwarning("No scan", "Run First Scan first.", parent=self)
            return
        st = self._get_scan_type()
        if st == ScanType.UNKNOWN:
            messagebox.showwarning("Invalid", "Choose a filter type for Next Scan.", parent=self)
            return
        value = 0
        if st in _NEEDS_VALUE:
            try:
                value = int(self._learn_val.get())
            except ValueError:
                messagebox.showwarning("Invalid", "Enter a valid integer.", parent=self)
                return
        self._scan_status.set("Filtering…")

        def _run():
            count = pointer_scanner.next_scan(st, value)
            self.after(0, lambda: self._scan_done(count))

        threading.Thread(target=_run, daemon=True).start()

    def _scan_done(self, count: int):
        self._first_btn.configure(state='normal')
        self._scan_status.set(f"{count:,} candidates remaining")
        self._render_candidates()

    def _reset_scan(self):
        pointer_scanner.reset_scan()
        self._scan_status.set("Reset")
        for w in self._cand_frame.winfo_children():
            w.destroy()

    def _render_candidates(self):
        for w in self._cand_frame.winfo_children():
            w.destroy()
        for idx, addr in enumerate(pointer_scanner.candidates[:MAX_CANDIDATES_SHOWN]):
            live = memory_reader.read_uint32(addr)
            customtkinter.CTkButton(
                self._cand_frame,
                text=f"{hex(addr)}  =  {live}", width=220, height=28, corner_radius=8,
                fg_color="transparent", border_color="#C20034",
                border_width=1, hover_color="#C20034",
                command=lambda a=addr: self._save_manual_candidate(a),
            ).grid(row=idx // 3, column=idx % 3, padx=4, pady=2)

    def _save_manual_candidate(self, address: int):
        name = self._learn_name.get().strip()
        game = self._current_game.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Enter a pointer name.", parent=self)
            return
        if not game:
            messagebox.showwarning("Profile required", "Select a game profile.", parent=self)
            return
        pointer_scanner.save_pointer(game, name, address)
        self._scan_status.set(f"Saved '{name}' → {hex(address)}")
        pointer_scanner.reset_scan()
        self._learn_name.set("")
        for w in self._cand_frame.winfo_children():
            w.destroy()
        self._refresh_saved_table()

    # ── Saved Pointers tab ────────────────────────────────────────────────────

    def _build_saved_tab(self, parent):
        parent.columnconfigure(1, weight=1)

        top = customtkinter.CTkFrame(parent)
        top.grid(row=0, column=0, columnspan=5, padx=8, pady=(8, 4), sticky='ew')
        customtkinter.CTkLabel(top, text="Profile:").grid(row=0, column=0, padx=8)
        self._saved_game_combo = customtkinter.CTkComboBox(
            top, variable=self._current_game, state='readonly', width=200,
            command=self._on_profile_change)
        self._saved_game_combo.grid(row=0, column=1, padx=6)
        customtkinter.CTkButton(
            top, text="New", width=70, corner_radius=20,
            fg_color="transparent", border_color="#C20034", border_width=2, hover_color="#C20034",
            command=self._new_profile,
        ).grid(row=0, column=2, padx=4)
        customtkinter.CTkButton(
            top, text="Delete Profile", width=110, corner_radius=20,
            fg_color="transparent", border_color="#870125", border_width=2, hover_color="#870125",
            command=self._delete_profile,
        ).grid(row=0, column=3, padx=4)
        customtkinter.CTkButton(
            top, text="Use This Profile", width=130, corner_radius=20,
            fg_color="#C20034", hover_color="#870125",
            command=self._use_profile,
        ).grid(row=0, column=4, padx=8)

        hdr = customtkinter.CTkFrame(parent, fg_color="transparent")
        hdr.grid(row=1, column=0, columnspan=5, padx=8, sticky='ew')
        for col, (txt, w) in enumerate([("Name", 140), ("Address", 120), ("Live Value", 100), ("", 70)]):
            customtkinter.CTkLabel(hdr, text=txt, width=w, anchor='w',
                                   font=("", 11, "bold")).grid(row=0, column=col, padx=4)

        self._saved_frame = customtkinter.CTkScrollableFrame(parent, height=180)
        self._saved_frame.grid(row=2, column=0, columnspan=5, padx=8, pady=4, sticky='ew')

        customtkinter.CTkButton(
            parent, text="Refresh Values", width=120, corner_radius=20,
            fg_color="transparent", border_color="#C20034", border_width=2, hover_color="#C20034",
            command=self._refresh_saved_table,
        ).grid(row=3, column=0, padx=8, pady=6, sticky='w')

    def _refresh_game_dropdown(self):
        games = pointer_scanner.list_games()
        for combo in (self._wiz_game_combo, self._man_game_combo, self._saved_game_combo):
            combo.configure(values=games)
        active = (self.context.context.get('memory_profile') or {}).get('game', '')
        val = active if (active and active in games) else (games[0] if games else '')
        self._current_game.set(val)
        self._refresh_saved_table()

    def _on_profile_change(self, _=None):
        self._refresh_saved_table()

    def _new_profile(self):
        name = simpledialog.askstring("New Profile", "Game profile name:", parent=self)
        if name:
            pointer_scanner.profiles.setdefault(name, {})
            pointer_scanner._save()
            self._refresh_game_dropdown()
            self._current_game.set(name)

    def _delete_profile(self):
        game = self._current_game.get()
        if game and messagebox.askyesno(
            "Delete", f"Delete '{game}' and all its pointers?", parent=self
        ):
            pointer_scanner.delete_game(game)
            self._refresh_game_dropdown()

    def _use_profile(self):
        game = self._current_game.get()
        if game:
            self.context.context['memory_profile']['game'] = game
            messagebox.showinfo("Profile", f"Active profile: '{game}'", parent=self)

    def _refresh_saved_table(self):
        for w in self._saved_frame.winfo_children():
            w.destroy()
        game = self._current_game.get()
        if not game:
            return
        for row, (name, addr) in enumerate(pointer_scanner.get_pointers(game).items()):
            live = memory_reader.read_uint32(addr) if memory_reader.attached else "—"
            customtkinter.CTkLabel(self._saved_frame, text=name, width=140, anchor='w').grid(
                row=row, column=0, padx=4, pady=2)
            customtkinter.CTkLabel(self._saved_frame, text=hex(addr), width=120, anchor='w').grid(
                row=row, column=1, padx=4, pady=2)
            customtkinter.CTkLabel(self._saved_frame, text=str(live), width=100, anchor='w').grid(
                row=row, column=2, padx=4, pady=2)
            customtkinter.CTkButton(
                self._saved_frame, text="Del", width=60, height=24, corner_radius=8,
                fg_color="transparent", border_color="#870125", border_width=1,
                hover_color="#870125",
                command=lambda n=name: self._delete_pointer(n),
            ).grid(row=row, column=3, padx=4, pady=2)

    def _delete_pointer(self, name: str):
        game = self._current_game.get()
        if game:
            pointer_scanner.delete_pointer(game, name)
            self._refresh_saved_table()

    # ── Live auto-refresh ─────────────────────────────────────────────────────

    def _start_live_refresh(self):
        self._refresh_saved_table()
        self.after(2000, self._start_live_refresh)
