"""
Pointer learning — mirrors Cheat Engine's value scanner.

Scan types:
  EXACT          → value == X              (HP/Mana: enter what you see on screen)
  UNKNOWN        → any value               (Coordinates: you don't know the initial value)
  CHANGED        → current != previous     (value changed since last scan)
  UNCHANGED      → current == previous     (value did NOT change)
  INCREASED      → current > previous      (moved right → X increased)
  DECREASED      → current < previous      (moved left  → X decreased)
  INCREASED_BY   → current == previous + N (moved 1 tile right → X increased by exactly 1)
  DECREASED_BY   → current == previous - N (moved 1 tile left  → X decreased by exactly 1)

Workflow for coordinates (not visible on screen):
  1. first_scan(UNKNOWN)                  → snapshots all writable memory
  2. Move character right 1 tile
  3. next_scan(INCREASED_BY, amount=1)    → keeps only addresses that went up by exactly 1
  4. Repeat steps 2-3 until < 10 candidates
  5. save_pointer(game, "player_x", address)

Workflow for visible values (HP, Mana):
  1. first_scan(EXACT, value=850)         → finds all addresses holding 850
  2. Take some damage, HP becomes 710
  3. next_scan(EXACT, value=710)          → keeps only addresses now holding 710
  4. save_pointer(game, "player_hp", address)
"""
import json
import os
from enum import Enum
from typing import Dict, List, Optional, Any, Callable

from .memory import memory_reader

PROFILES_FILE = "game_profiles.json"


class ScanType(Enum):
    EXACT = "Exact Value"
    UNKNOWN = "Unknown Initial Value"
    CHANGED = "Changed Value"
    UNCHANGED = "Unchanged Value"
    INCREASED = "Increased Value"
    DECREASED = "Decreased Value"
    INCREASED_BY = "Increased by..."
    DECREASED_BY = "Decreased by..."


class PointerScanner:
    def __init__(self):
        self.candidates: List[int] = []
        # Snapshot stores {address: value_at_last_scan} for change-based filtering
        self._snapshot: Dict[int, int] = {}
        self.profiles: Dict[str, Dict[str, int]] = {}
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self):
        if os.path.exists(PROFILES_FILE):
            try:
                with open(PROFILES_FILE, 'r') as f:
                    self.profiles = json.load(f)
            except Exception:
                self.profiles = {}

    def _save(self):
        with open(PROFILES_FILE, 'w') as f:
            json.dump(self.profiles, f, indent=2)

    # ── Scan workflow ─────────────────────────────────────────────────────────

    def first_scan(
        self,
        scan_type: ScanType,
        value: int = 0,
        progress_cb: Optional[Callable[[int, int], None]] = None,
    ) -> int:
        """
        Start a new scan. Returns number of candidates found.
        For UNKNOWN: snapshots all writable memory (may be slow for large processes).
        For EXACT: fast scan for specific value.
        Other types are not valid for first scan — use UNKNOWN instead.
        """
        self._snapshot = {}
        self.candidates = []

        if scan_type == ScanType.EXACT:
            self.candidates = memory_reader.scan_uint32(value)
            # Store snapshot so subsequent change-based scans work
            for addr in self.candidates:
                self._snapshot[addr] = value

        elif scan_type == ScanType.UNKNOWN:
            self._snapshot = memory_reader.snapshot_writable(progress_cb)
            self.candidates = list(self._snapshot.keys())

        return len(self.candidates)

    def next_scan(
        self,
        scan_type: ScanType,
        value: int = 0,
    ) -> int:
        """
        Filter existing candidates. Returns remaining count.
        Reads current values and compares against snapshot.
        """
        if not self.candidates:
            return 0

        kept = []
        new_snapshot: Dict[int, int] = {}

        for addr in self.candidates:
            current = memory_reader.read_uint32(addr)
            if current is None:
                continue
            prev = self._snapshot.get(addr, 0)

            match = False
            if scan_type == ScanType.EXACT:
                match = current == (value & 0xFFFFFFFF)
            elif scan_type == ScanType.CHANGED:
                match = current != prev
            elif scan_type == ScanType.UNCHANGED:
                match = current == prev
            elif scan_type == ScanType.INCREASED:
                match = current > prev
            elif scan_type == ScanType.DECREASED:
                match = current < prev
            elif scan_type == ScanType.INCREASED_BY:
                match = current == prev + value
            elif scan_type == ScanType.DECREASED_BY:
                match = current == prev - value

            if match:
                kept.append(addr)
                new_snapshot[addr] = current

        self.candidates = kept
        self._snapshot = new_snapshot
        return len(self.candidates)

    def reset_scan(self):
        self.candidates = []
        self._snapshot = {}

    def candidate_count(self) -> int:
        return len(self.candidates)

    def read_candidate(self, address: int) -> Optional[int]:
        return memory_reader.read_uint32(address)

    # ── Profile management ────────────────────────────────────────────────────

    def list_games(self) -> List[str]:
        return sorted(self.profiles.keys())

    def get_pointers(self, game: str) -> Dict[str, int]:
        return dict(self.profiles.get(game, {}))

    def save_pointer(self, game: str, name: str, address: int):
        if game not in self.profiles:
            self.profiles[game] = {}
        self.profiles[game][name] = address
        self._save()

    def delete_pointer(self, game: str, name: str):
        if game in self.profiles and name in self.profiles[game]:
            del self.profiles[game][name]
            if not self.profiles[game]:
                del self.profiles[game]
            self._save()

    def delete_game(self, game: str):
        if game in self.profiles:
            del self.profiles[game]
            self._save()

    def get_address(self, game: str, name: str) -> Optional[int]:
        return self.profiles.get(game, {}).get(name)

    def read_pointer(self, game: str, name: str) -> Optional[int]:
        addr = self.get_address(game, name)
        if addr is None:
            return None
        return memory_reader.read_uint32(addr)

    def read_all(self, game: str) -> Dict[str, Optional[int]]:
        return {
            name: memory_reader.read_uint32(addr)
            for name, addr in self.profiles.get(game, {}).items()
        }

    def export_game(self, game: str) -> Dict[str, Any]:
        return {
            'game': game,
            'pointers': {
                name: {'address': hex(addr), 'address_int': addr}
                for name, addr in self.profiles.get(game, {}).items()
            }
        }


# Global singleton
pointer_scanner = PointerScanner()
