"""Spotlight metadata extractor.

mdfind for files with kMDItemUseCount > 0 in the user's primary trees, then
mdls -plist for each path to get use counts, last/all-used dates, content type.
Each used-date becomes one file_access event.
"""
from __future__ import annotations

import plistlib
import subprocess
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, emit, stable_hash, to_local
from macprofile.settings import get_settings

# Trees that are typically user-driven. Library/Caches and node_modules are explicitly excluded
# at mdfind time via -onlyin and at the path level via _SKIP_PREFIXES.
ROOTS = [
    Path.home() / "Documents",
    Path.home() / "Desktop",
    Path.home() / "Downloads",
    Path.home() / "Pictures",
    Path.home() / "Movies",
    Path.home() / "Music",
    Path.home() / "Library/Mobile Documents",  # iCloud Drive
    Path.home() / "Projects",
    Path.home() / "CustomOS",
    Path.home() / "code",
    Path.home() / "src",
]

_SKIP_SUBSTR = (
    "/.git/",
    "/node_modules/",
    "/.venv/",
    "/__pycache__/",
    "/Library/Caches/",
    "/.Trash/",
    "/DerivedData/",
    "/.next/",
    ".DS_Store",
)

_LIMIT_PER_ROOT = 5000  # cap per tree to keep mdls calls bounded


def mdfind_used(root: Path, lookback_days: int) -> list[Path]:
    if not root.exists():
        return []
    query = (
        f"kMDItemUseCount > 0 && kMDItemFSContentChangeDate > $time.today(-{lookback_days})"
    )
    out = subprocess.run(
        ["mdfind", "-onlyin", str(root), query],
        capture_output=True, text=True, timeout=120,
    )
    if out.returncode != 0:
        logger.warning(f"mdfind {root}: {out.stderr.strip()[:200]}")
        return []
    paths: list[Path] = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        if any(s in line for s in _SKIP_SUBSTR):
            continue
        paths.append(Path(line))
        if len(paths) >= _LIMIT_PER_ROOT:
            break
    return paths


def mdls_meta(path: Path) -> dict | None:
    try:
        out = subprocess.run(
            ["mdls", "-plist", "-", str(path)],
            capture_output=True, timeout=10,
        )
        if out.returncode != 0 or not out.stdout:
            return None
        return plistlib.loads(out.stdout)
    except (subprocess.TimeoutExpired, plistlib.InvalidFileException, OSError):
        return None


class SpotlightExtractor(Extractor):
    name = "spotlight"

    def available(self) -> bool:
        return any(r.exists() for r in ROOTS)

    def extract(self) -> Iterator:
        s = get_settings()
        seen_paths: set[str] = set()
        for root in ROOTS:
            if not root.exists():
                continue
            paths = mdfind_used(root, s.extract.lookback_days)
            logger.info(f"[spotlight] {root}: {len(paths)} candidate paths")
            for p in paths:
                key = str(p)
                if key in seen_paths:
                    continue
                seen_paths.add(key)
                meta = mdls_meta(p)
                if not meta:
                    continue
                last = meta.get("kMDItemLastUsedDate")
                used_dates = meta.get("kMDItemUsedDates") or []
                use_count = meta.get("kMDItemUseCount") or 0
                content_type = meta.get("kMDItemContentType") or meta.get("kMDItemKind") or ""
                kind = meta.get("kMDItemKind") or ""

                # If no specific used-dates, fall back to lastUsed only.
                events_dts: list[datetime] = []
                for u in used_dates:
                    if isinstance(u, datetime):
                        events_dts.append(u if u.tzinfo else u.replace(tzinfo=timezone.utc))
                if not events_dts and isinstance(last, datetime):
                    events_dts = [last if last.tzinfo else last.replace(tzinfo=timezone.utc)]

                if not events_dts:
                    continue

                meta_payload = {
                    "kind": kind,
                    "content_type": content_type,
                    "use_count": int(use_count) if use_count else 0,
                    "size": meta.get("kMDItemFSSize"),
                }
                # One event per used-date (each is a real file-open)
                for dt in events_dts:
                    yield emit(
                        ts=dt,
                        source="spotlight.file_use",
                        category="file_access",
                        target=str(p),
                        target_kind="file",
                        metadata=meta_payload,
                        raw_hash=stable_hash("spotlight", str(p), dt.isoformat()),
                    )
