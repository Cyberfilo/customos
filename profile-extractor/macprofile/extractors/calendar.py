"""Calendar.sqlitedb (group container path on macOS Tahoe).

Tables use lowercase names, dates are REAL CFAbsoluteTime (Apple epoch).
"""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, apple_to_dt, emit, safe_copy, stable_hash
from macprofile.settings import get_settings

SRC = Path.home() / "Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb"


class CalendarExtractor(Extractor):
    name = "calendar"
    src = SRC

    def available(self) -> bool:
        return self.src.exists()

    def extract(self) -> Iterator:
        s = get_settings()
        copied = safe_copy(self.src, self.snapshot_dir)
        if copied is None:
            return
        try:
            con = sqlite3.connect(f"file:{copied}?mode=ro&immutable=1", uri=True)
        except sqlite3.OperationalError as e:
            logger.error(f"calendar: open failed: {e}")
            return
        try:
            cur = con.execute(
                """
                SELECT
                  ci.ROWID,
                  ci.summary,
                  ci.start_date,
                  ci.end_date,
                  ci.all_day,
                  ci.has_attendees,
                  ci.has_recurrences,
                  ci.calendar_id,
                  ci.UUID,
                  ci.creation_date,
                  ci.entity_type
                FROM CalendarItem ci
                WHERE ci.start_date IS NOT NULL
                """
            )
            redact = not s.privacy.deep_content_analysis
            for row in cur:
                rid, summary, sd, ed, all_day, has_att, has_rec, cal_id, uuid, cd, ent = row
                ts = apple_to_dt(float(sd))
                duration = None
                if ed is not None:
                    duration = max(0.0, float(ed) - float(sd))
                payload = {
                    "calendar_id": cal_id,
                    "all_day": bool(all_day),
                    "has_attendees": bool(has_att),
                    "has_recurrences": bool(has_rec),
                    "entity_type": ent,
                    "creation_date": apple_to_dt(float(cd)).isoformat() if cd else None,
                }
                if not redact and summary:
                    payload["summary"] = summary
                yield emit(
                    ts=ts,
                    source="calendar.event",
                    category="calendar_event",
                    target=uuid or f"event_{rid}",
                    target_kind="event",
                    duration_sec=duration,
                    metadata=payload,
                    raw_hash=stable_hash("calendar", rid, sd, uuid),
                )
        finally:
            con.close()
