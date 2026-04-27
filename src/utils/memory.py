"""
Process memory reader using Windows API via ctypes.
No extra dependencies beyond the stdlib — works on any Windows Python install.
"""
import ctypes
import ctypes.wintypes as wintypes
import struct
from typing import Optional, List, Dict, Any, Callable

_kernel32 = ctypes.windll.kernel32

PROCESS_VM_READ          = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400
MEM_COMMIT               = 0x1000
PAGE_GUARD               = 0x100   # modifier — triggers exception on access

# Base protection bits (mask with 0xFF to strip modifiers like PAGE_GUARD)
_READABLE_BASE  = {0x02, 0x04, 0x08, 0x20, 0x40, 0x80}
_WRITABLE_BASE  = {0x04, 0x08, 0x40, 0x80}  # RW, WC, ERW, EWC


class _MBI(ctypes.Structure):
    """MEMORY_BASIC_INFORMATION — layout matches both 32-bit and 64-bit Windows."""
    _fields_ = [
        ("BaseAddress",       ctypes.c_void_p),
        ("AllocationBase",    ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize",        ctypes.c_size_t),  # ctypes pads 4 bytes before this on 64-bit
        ("State",             wintypes.DWORD),
        ("Protect",           wintypes.DWORD),
        ("Type",              wintypes.DWORD),
    ]


def _max_user_address() -> int:
    """Return the highest user-mode address for the current OS (handles 32/64-bit)."""
    class SYSTEM_INFO(ctypes.Structure):
        _fields_ = [
            ("wProcessorArchitecture",      wintypes.WORD),
            ("wReserved",                   wintypes.WORD),
            ("dwPageSize",                  wintypes.DWORD),
            ("lpMinimumApplicationAddress", ctypes.c_void_p),
            ("lpMaximumApplicationAddress", ctypes.c_void_p),
            ("dwActiveProcessorMask",       ctypes.POINTER(wintypes.DWORD)),
            ("dwNumberOfProcessors",        wintypes.DWORD),
            ("dwProcessorType",             wintypes.DWORD),
            ("dwAllocationGranularity",     wintypes.DWORD),
            ("wProcessorLevel",             wintypes.WORD),
            ("wProcessorRevision",          wintypes.WORD),
        ]
    si = SYSTEM_INFO()
    _kernel32.GetSystemInfo(ctypes.byref(si))
    return si.lpMaximumApplicationAddress or 0x7FFFFFFF


_MAX_ADDR = _max_user_address()


def _is_writable(protect: int) -> bool:
    return (protect & 0xFF) in _WRITABLE_BASE and not (protect & PAGE_GUARD)


def _is_readable(protect: int) -> bool:
    return (protect & 0xFF) in _READABLE_BASE and not (protect & PAGE_GUARD)


class MemoryReader:
    def __init__(self):
        self.handle: Optional[int] = None
        self.pid: Optional[int] = None
        self.name: str = ""

    @property
    def attached(self) -> bool:
        return self.handle is not None

    def attach(self, pid: int, name: str = "") -> bool:
        self.detach()
        h = _kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False
        self.handle = h
        self.pid = pid
        self.name = name
        return True

    def detach(self):
        if self.handle:
            _kernel32.CloseHandle(self.handle)
        self.handle = None
        self.pid = None
        self.name = ""

    def read(self, address: int, size: int) -> Optional[bytes]:
        if not self.handle:
            return None
        buf = ctypes.create_string_buffer(size)
        read = ctypes.c_size_t(0)
        ok = _kernel32.ReadProcessMemory(
            self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(read)
        )
        return buf.raw if ok and read.value == size else None

    def read_uint32(self, address: int) -> Optional[int]:
        b = self.read(address, 4)
        return struct.unpack('<I', b)[0] if b else None

    def read_int32(self, address: int) -> Optional[int]:
        b = self.read(address, 4)
        return struct.unpack('<i', b)[0] if b else None

    def read_uint8(self, address: int) -> Optional[int]:
        b = self.read(address, 1)
        return b[0] if b else None

    def read_uint16(self, address: int) -> Optional[int]:
        b = self.read(address, 2)
        return struct.unpack('<H', b)[0] if b else None

    # ── Full memory scan (exact value) ────────────────────────────────────────

    def scan_uint32(self, value: int, candidates: Optional[List[int]] = None) -> List[int]:
        target = struct.pack('<I', value & 0xFFFFFFFF)
        if candidates is not None:
            return [a for a in candidates if self.read(a, 4) == target]
        return self._full_scan(target, writable_only=False)

    def _full_scan(self, target: bytes, writable_only: bool = False) -> List[int]:
        results = []
        addr = 0
        mbi = _MBI()
        mbi_size = ctypes.sizeof(mbi)
        while addr < _MAX_ADDR:
            ret = _kernel32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), mbi_size
            )
            if ret == 0:
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize or 0x1000
            check = _is_writable(mbi.Protect) if writable_only else _is_readable(mbi.Protect)
            if mbi.State == MEM_COMMIT and check:
                try:
                    chunk = self.read(base, size)
                    if chunk:
                        offset = 0
                        while True:
                            idx = chunk.find(target, offset)
                            if idx == -1:
                                break
                            if idx % 4 == 0:
                                results.append(base + idx)
                            offset = idx + 4
                except Exception:
                    pass
            addr = base + size
        return results

    # ── Snapshot scan (for unknown / change-based types) ──────────────────────

    def snapshot_writable(self, progress_cb: Optional[Callable[[int, int], None]] = None) -> Dict[int, int]:
        """
        Snapshot all uint32 values in writable committed regions.
        Returns {address: value}. progress_cb(done_mb, total_mb) called periodically.
        """
        snapshot: Dict[int, int] = {}
        addr = 0
        mbi = _MBI()
        mbi_size = ctypes.sizeof(mbi)
        regions = []

        while addr < _MAX_ADDR:
            ret = _kernel32.VirtualQueryEx(
                self.handle, ctypes.c_void_p(addr), ctypes.byref(mbi), mbi_size
            )
            if ret == 0:
                break
            base = mbi.BaseAddress or 0
            size = mbi.RegionSize or 0x1000
            if mbi.State == MEM_COMMIT and _is_writable(mbi.Protect):
                regions.append((base, size))
            addr = base + size

        total_mb = max(1, sum(r[1] for r in regions) // (1024 * 1024))
        done_bytes = 0

        for base, size in regions:
            try:
                chunk = self.read(base, size)
                if chunk:
                    for i in range(0, len(chunk) - 3, 4):
                        snapshot[base + i] = struct.unpack_from('<I', chunk, i)[0]
            except Exception:
                pass
            done_bytes += size
            if progress_cb:
                progress_cb(done_bytes // (1024 * 1024), total_mb)

        return snapshot

    def read_snapshot_addresses(self, addresses: List[int]) -> Dict[int, Optional[int]]:
        return {addr: self.read_uint32(addr) for addr in addresses}


def list_processes() -> List[Dict[str, Any]]:
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                info = p.info
                mem = info['memory_info']
                mem_mb = mem.rss // (1024 * 1024) if mem else 0
                procs.append({'pid': info['pid'], 'name': info['name'], 'memory_mb': mem_mb})
            except Exception:
                pass
        return sorted(procs, key=lambda x: x['name'].lower())
    except ImportError:
        return _list_processes_win32()


def _list_processes_win32() -> List[Dict[str, Any]]:
    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize",              wintypes.DWORD),
            ("cntUsage",            wintypes.DWORD),
            ("th32ProcessID",       wintypes.DWORD),
            ("th32DefaultHeapID",   ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID",        wintypes.DWORD),
            ("cntThreads",          wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase",      ctypes.c_long),
            ("dwFlags",             wintypes.DWORD),
            ("szExeFile",           ctypes.c_char * 260),
        ]

    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    procs = []
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    if _kernel32.Process32First(snap, ctypes.byref(entry)):
        while True:
            procs.append({
                'pid': entry.th32ProcessID,
                'name': entry.szExeFile.decode('utf-8', errors='replace'),
                'memory_mb': 0,
            })
            if not _kernel32.Process32Next(snap, ctypes.byref(entry)):
                break
    _kernel32.CloseHandle(snap)
    return sorted(procs, key=lambda x: x['name'].lower())


# Global singleton
memory_reader = MemoryReader()
