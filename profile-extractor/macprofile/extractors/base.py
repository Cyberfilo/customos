"""Base classes for extractors."""
from __future__ import annotations

import hashlib
import shutil
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from macprofile.schema import Event
from macprofile.settings import LOCAL_TZ, Settings


APPLE_EPOCH_OFFSET = 978307200  # seconds between 1970-01-01 and 2001-01-01


def apple_to_dt(ts: float) -> datetime:
    """Apple absolute time (seconds since 2001-01-01 UTC) -> aware UTC datetime."""
    return datetime.fromtimestamp(ts + APPLE_EPOCH_OFFSET, tz=timezone.utc)


def chrome_to_dt(ts: int) -> datetime:
    """Chromium epoch (microseconds since 1601-01-01) -> aware UTC datetime."""
    if ts <= 0:
        return datetime(1601, 1, 1, tzinfo=timezone.utc)
    return datetime(1601, 1, 1, tzinfo=timezone.utc).fromtimestamp(
        (ts / 1_000_000) - 11644473600, tz=timezone.utc,
    )


def to_local(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def stable_hash(*parts: object) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(repr(p).encode("utf-8", errors="replace"))
    return h.hexdigest()


def safe_copy(src: Path, dst_dir: Path) -> Path | None:
    """Copy a SQLite DB along with -wal and -shm sidecars. Returns the dst path or None."""
    if not src.exists():
        logger.warning(f"safe_copy: source missing: {src}")
        return None
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    try:
        shutil.copy2(src, dst)
    except PermissionError as e:
        logger.error(f"safe_copy: permission denied for {src}: {e}")
        return None
    for ext in ("-wal", "-shm"):
        sidecar = src.with_name(src.name + ext)
        if sidecar.exists():
            try:
                shutil.copy2(sidecar, dst_dir / sidecar.name)
            except PermissionError:
                pass
    return dst


class Extractor(ABC):
    name: str

    def __init__(self, settings: Settings):
        self.settings = settings
        self.raw_dir = settings.paths.raw_dir / self.name
        self.snapshot_dir = self.raw_dir / datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")

    def available(self) -> bool:  # noqa: B027 — default true; override to gate
        return True

    @abstractmethod
    def extract(self) -> Iterator[Event]: ...

    def run(self) -> tuple[int, int]:
        if not self.available():
            logger.info(f"[{self.name}] not available, skipping")
            return (0, 0)
        self.snapshot_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        try:
            for ev in self.extract():
                yield ev  # type: ignore[misc]
                n += 1
        except Exception:
            logger.exception(f"[{self.name}] extractor crashed after {n} events")
            raise
        return (n, 0)


def emit(
    *,
    ts: datetime,
    source: str,
    category: str,
    target: str,
    target_kind: str,
    duration_sec: float | None = None,
    metadata: dict | None = None,
    raw_hash: str,
) -> Event:
    return Event(
        ts=ts.astimezone(timezone.utc) if ts.tzinfo else ts.replace(tzinfo=timezone.utc),
        ts_local=to_local(ts),
        source=source,
        category=category,  # type: ignore[arg-type]
        target=target,
        target_kind=target_kind,  # type: ignore[arg-type]
        duration_sec=duration_sec,
        metadata=metadata or {},
        raw_hash=raw_hash,
    )
