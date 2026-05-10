"""DuckDB warehouse loader. Idempotent — uses raw_hash for dedup."""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import duckdb
from loguru import logger

from macprofile.schema import Event

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    ts           TIMESTAMPTZ NOT NULL,
    ts_local     TIMESTAMP NOT NULL,
    source       TEXT NOT NULL,
    category     TEXT NOT NULL,
    actor        TEXT NOT NULL DEFAULT 'user',
    target       TEXT NOT NULL,
    target_kind  TEXT NOT NULL,
    duration_sec DOUBLE,
    metadata     JSON,
    raw_hash     TEXT NOT NULL UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_category_ts ON events(category, ts);
CREATE INDEX IF NOT EXISTS idx_events_target_ts ON events(target, ts);
CREATE INDEX IF NOT EXISTS idx_events_source_ts ON events(source, ts);

CREATE TABLE IF NOT EXISTS extraction_runs (
    run_id       TEXT,
    extractor    TEXT,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ,
    rows_seen    BIGINT,
    rows_loaded  BIGINT,
    notes        TEXT
);
"""


class Warehouse:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.con = duckdb.connect(str(db_path))
        self.con.execute(SCHEMA_DDL)

    def insert_events(self, events: Iterable[Event]) -> tuple[int, int]:
        seen = 0
        loaded = 0
        batch: list[tuple] = []
        for ev in events:
            seen += 1
            d = ev.to_row()
            batch.append((
                d["event_id"], d["ts"], d["ts_local"].replace(tzinfo=None),
                d["source"], d["category"], d["actor"],
                d["target"], d["target_kind"],
                d["duration_sec"], d["metadata"], d["raw_hash"],
            ))
            if len(batch) >= 1000:
                loaded += self._flush(batch)
                batch.clear()
        if batch:
            loaded += self._flush(batch)
        return seen, loaded

    def _flush(self, batch: list[tuple]) -> int:
        before = self.con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        self.con.executemany(
            """
            INSERT INTO events
              (event_id, ts, ts_local, source, category, actor, target, target_kind,
               duration_sec, metadata, raw_hash)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (raw_hash) DO NOTHING
            """,
            batch,
        )
        after = self.con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        return after - before

    def record_run(self, extractor: str, run_id: str, started, finished, seen, loaded, notes=""):
        self.con.execute(
            "INSERT INTO extraction_runs VALUES (?,?,?,?,?,?,?)",
            (run_id, extractor, started, finished, seen, loaded, notes),
        )

    def counts_by_source(self) -> list[tuple[str, int]]:
        return self.con.execute(
            "SELECT source, COUNT(*) FROM events GROUP BY source ORDER BY 2 DESC"
        ).fetchall()

    def counts_by_category(self) -> list[tuple[str, int]]:
        return self.con.execute(
            "SELECT category, COUNT(*) FROM events GROUP BY category ORDER BY 2 DESC"
        ).fetchall()

    def total(self) -> int:
        return self.con.execute("SELECT COUNT(*) FROM events").fetchone()[0]

    def close(self):
        self.con.close()


def load_into(db_path: Path, events: Iterable[Event]) -> tuple[int, int]:
    wh = Warehouse(db_path)
    try:
        seen, loaded = wh.insert_events(events)
        logger.info(f"warehouse: seen={seen} loaded={loaded} (deduped {seen - loaded})")
        return seen, loaded
    finally:
        wh.close()
