"""Reminders — Data-*.sqlite CoreData stores."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, apple_to_dt, emit, safe_copy, stable_hash
from macprofile.settings import get_settings

STORE_DIR = Path.home() / "Library/Group Containers/group.com.apple.reminders/Container_v1/Stores"


class RemindersExtractor(Extractor):
    name = "reminders"

    def available(self) -> bool:
        return STORE_DIR.exists() and any(STORE_DIR.glob("Data-*.sqlite"))

    def extract(self) -> Iterator:
        s = get_settings()
        for src in sorted(STORE_DIR.glob("Data-*.sqlite")):
            copied = safe_copy(src, self.snapshot_dir)
            if copied is None:
                continue
            try:
                con = sqlite3.connect(f"file:{copied}?mode=ro&immutable=1", uri=True)
            except sqlite3.OperationalError as e:
                logger.warning(f"reminders {src.name}: {e}")
                continue
            try:
                # CoreData reminder schema. Be defensive about column names across versions.
                # Discover any table whose name contains "REMINDER" or "TODOITEM".
                tables = [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()]
                target_table = next(
                    (t for t in tables if "REMINDER" in t.upper() or "TODOITEM" in t.upper()),
                    None,
                )
                if not target_table:
                    continue
                col_info = con.execute(f"PRAGMA table_info({target_table})").fetchall()
                cols = {c[1].upper(): c[1] for c in col_info}
                created_col = cols.get("ZCREATIONDATE")
                due_col = cols.get("ZDUEDATE")
                completed_col = cols.get("ZCOMPLETIONDATE") or cols.get("ZCOMPLETEDDATE")
                title_col = cols.get("ZTITLE") or cols.get("ZTITLE1")
                pk = cols.get("Z_PK", "Z_PK")
                if not created_col:
                    continue
                select = [pk, title_col or "NULL", created_col, due_col or "NULL", completed_col or "NULL"]
                q = f"SELECT {', '.join(select)} FROM {target_table}"
                redact = not s.privacy.deep_content_analysis
                for row in con.execute(q):
                    rpk, title, cd, due, completed = row
                    if cd is None:
                        continue
                    created = apple_to_dt(float(cd))
                    payload = {
                        "store": src.name,
                        "due_date": apple_to_dt(float(due)).isoformat() if due else None,
                        "completed_date": apple_to_dt(float(completed)).isoformat() if completed else None,
                    }
                    if not redact and title:
                        payload["title"] = title
                    yield emit(
                        ts=created,
                        source="reminders.create",
                        category="reminder",
                        target=f"r_{rpk}",
                        target_kind="other",
                        metadata=payload,
                        raw_hash=stable_hash("reminders.create", src.name, rpk, cd),
                    )
                    if completed:
                        yield emit(
                            ts=apple_to_dt(float(completed)),
                            source="reminders.complete",
                            category="reminder",
                            target=f"r_{rpk}",
                            target_kind="other",
                            metadata={**payload, "kind": "completed"},
                            raw_hash=stable_hash("reminders.complete", src.name, rpk, completed),
                        )
            finally:
                con.close()
