"""Full Disk Access preflight. Run before any extraction."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

HOME = Path.home()

PROBE_PATHS: list[tuple[str, Path, str]] = [
    ("Mail", HOME / "Library/Mail", "Required for mail aggregates"),
    ("Messages", HOME / "Library/Messages/chat.db", "Required for message graph"),
    ("Safari history", HOME / "Library/Safari/History.db", "Required for browser history"),
    ("knowledgeC", HOME / "Library/Application Support/Knowledge/knowledgeC.db", "Required for app focus history"),
    ("Biome streams", HOME / "Library/Biome/streams/restricted", "Primary behavioural source on macOS 13+"),
    ("Calendar (group container)", HOME / "Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb", "Calendar archetype"),
    ("Notes", HOME / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite", "Note titles + timestamps"),
    ("Photos", HOME / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite", "Location/time fingerprint"),
]


@dataclass
class ProbeResult:
    label: str
    path: Path
    note: str
    status: Literal["ok", "missing", "denied"]
    detail: str = ""


def probe(path: Path) -> tuple[Literal["ok", "missing", "denied"], str]:
    if not path.exists():
        return "missing", "path does not exist on this system"
    try:
        if path.is_dir():
            list(path.iterdir())
        else:
            with open(path, "rb") as f:
                f.read(1)
        return "ok", ""
    except PermissionError as e:
        return "denied", str(e)
    except OSError as e:
        return "denied", str(e)


def run_preflight() -> tuple[bool, list[ProbeResult]]:
    results: list[ProbeResult] = []
    any_denied = False
    for label, path, note in PROBE_PATHS:
        status, detail = probe(path)
        if status == "denied":
            any_denied = True
        results.append(ProbeResult(label=label, path=path, note=note, status=status, detail=detail))
    return (not any_denied), results


FDA_INSTRUCTIONS = """
================================================================================
Full Disk Access (FDA) is required for ~70% of sources.

Open System Settings -> Privacy & Security -> Full Disk Access, click +,
and add:
    1. Your terminal application (Terminal.app, iTerm.app, Ghostty, etc.)
    2. /opt/homebrew/bin/python3 (or whichever python3 binary you use)
    3. The python interpreter inside this project's venv:
       {venv_python}

Then quit & relaunch the terminal and re-run macprofile preflight.
================================================================================
"""
