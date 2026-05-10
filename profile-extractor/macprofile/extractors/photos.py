"""Photos library — date + (degraded) location.

We never extract image contents. Lat/lon are quantized to ~1km grid by default
to keep the warehouse from being a precise location log.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, apple_to_dt, emit, safe_copy, stable_hash
from macprofile.settings import get_settings

SRC = Path.home() / "Pictures/Photos Library.photoslibrary/database/Photos.sqlite"


def _quantize(v: float | None, step: float = 0.01) -> float | None:
    if v is None:
        return None
    return round(v / step) * step


class PhotosExtractor(Extractor):
    name = "photos"
    src = SRC

    def available(self) -> bool:
        return self.src.exists()

    def extract(self) -> Iterator:
        s = get_settings()
        # The library DB is large; copy is unavoidable but slow. Try opening
        # read-only directly first; fall back to copy if locked.
        path = self.src
        try:
            con = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True, timeout=2)
        except sqlite3.OperationalError:
            copied = safe_copy(self.src, self.snapshot_dir)
            if copied is None:
                return
            con = sqlite3.connect(f"file:{copied}?mode=ro&immutable=1", uri=True)
        try:
            tables = [r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            asset_table = "ZASSET" if "ZASSET" in tables else (
                "ZGENERICASSET" if "ZGENERICASSET" in tables else None
            )
            if not asset_table:
                logger.warning("photos: no ZASSET/ZGENERICASSET table found")
                return
            cols = {r[1] for r in con.execute(f"PRAGMA table_info({asset_table})").fetchall()}
            date_col = "ZDATECREATED" if "ZDATECREATED" in cols else None
            if not date_col:
                logger.warning(f"photos: no ZDATECREATED column in {asset_table}")
                return
            lat_col = "ZLATITUDE" if "ZLATITUDE" in cols else None
            lon_col = "ZLONGITUDE" if "ZLONGITUDE" in cols else None
            uuid_col = "ZUUID" if "ZUUID" in cols else None

            select_cols = ["Z_PK", date_col]
            if lat_col: select_cols.append(lat_col)
            if lon_col: select_cols.append(lon_col)
            if uuid_col: select_cols.append(uuid_col)
            q = f"SELECT {', '.join(select_cols)} FROM {asset_table} WHERE {date_col} IS NOT NULL"

            for row in con.execute(q):
                d = dict(zip(select_cols, row))
                cd = d.get(date_col)
                if cd is None:
                    continue
                # Some rows store date in seconds, others in microseconds; sniff
                try:
                    cd_f = float(cd)
                except (TypeError, ValueError):
                    continue
                if cd_f > 1e10:  # microseconds
                    cd_f /= 1_000_000
                ts = apple_to_dt(cd_f)
                lat = _quantize(d.get(lat_col)) if lat_col else None
                lon = _quantize(d.get(lon_col)) if lon_col else None
                if lat is not None and (-90.0 <= lat <= 90.0) is False:
                    lat = None
                if lon is not None and (-180.0 <= lon <= 180.0) is False:
                    lon = None
                payload = {"lat": lat, "lon": lon}
                yield emit(
                    ts=ts,
                    source="photos.asset",
                    category="photo",
                    target=d.get(uuid_col) or f"photo_{d['Z_PK']}",
                    target_kind="other",
                    metadata=payload,
                    raw_hash=stable_hash("photos", d["Z_PK"], cd_f),
                )
        finally:
            con.close()
        _ = s
