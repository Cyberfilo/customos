"""knowledgeC.db extractor.

Tahoe still records app focus/usage/web/notification streams here, even though
biome holds richer signal. We pull what's there, treating each ZSTREAMNAME
as a source.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, apple_to_dt, emit, safe_copy, stable_hash
from macprofile.normalize.identity import normalize_bundle_id

SRC = Path.home() / "Library/Application Support/Knowledge/knowledgeC.db"

STREAM_TO_CATEGORY: dict[str, str] = {
    "/app/inFocus": "app_focus",
    "/app/usage": "app_usage",
    "/app/activity": "app_activity",
    "/app/webUsage": "web_visit",
    "/safari/history": "web_visit",
    "/notification/usage": "notification",
    "/screentime/usage": "screen_time",
    "/display/isBacklit": "device_state",
    "/device/isLocked": "device_state",
    "/device/isPluggedIn": "device_state",
}


class KnowledgeCExtractor(Extractor):
    name = "knowledgec"
    src = SRC

    def available(self) -> bool:
        return self.src.exists()

    def extract(self) -> Iterator:
        copied = safe_copy(self.src, self.snapshot_dir)
        if copied is None:
            return
        try:
            con = sqlite3.connect(f"file:{copied}?mode=ro&immutable=1", uri=True)
        except sqlite3.OperationalError as e:
            logger.error(f"knowledgec: open failed: {e}")
            return
        try:
            cur = con.execute(
                """
                SELECT
                  ZOBJECT.Z_PK,
                  ZOBJECT.ZSTREAMNAME,
                  ZOBJECT.ZVALUESTRING,
                  ZOBJECT.ZSTARTDATE,
                  ZOBJECT.ZENDDATE,
                  ZSOURCE.ZBUNDLEID
                FROM ZOBJECT
                LEFT JOIN ZSOURCE ON ZOBJECT.ZSOURCE = ZSOURCE.Z_PK
                WHERE ZOBJECT.ZSTREAMNAME IS NOT NULL
                ORDER BY ZOBJECT.ZSTARTDATE
                """
            )
            for pk, stream, value, zstart, zend, bundle in cur:
                if zstart is None:
                    continue
                cat = STREAM_TO_CATEGORY.get(stream)
                if cat is None:
                    continue
                start = apple_to_dt(float(zstart))
                duration = None
                if zend is not None:
                    duration = max(0.0, float(zend) - float(zstart))
                target = normalize_bundle_id(bundle or value or "")
                target_kind = "app" if cat in ("app_focus", "app_usage", "app_activity") else "other"
                if cat in ("web_visit",):
                    target_kind = "url"
                    target = (value or bundle or "").strip()
                yield emit(
                    ts=start,
                    source=f"knowledgec{stream.replace('/', '.')}",
                    category=cat,  # type: ignore[arg-type]
                    target=target or "(unknown)",
                    target_kind=target_kind,  # type: ignore[arg-type]
                    duration_sec=duration,
                    metadata={"value_string": value, "bundle_id": bundle, "stream": stream},
                    raw_hash=stable_hash("knowledgec", pk, stream, zstart),
                )
        finally:
            con.close()
