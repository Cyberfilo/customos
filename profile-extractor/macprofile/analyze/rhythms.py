"""Hourly + weekly rhythm fingerprints from the warehouse.

All histograms filter to macOS-native events (see normalize.device_scope) so
that iCloud-synced iPhone Biome data doesn't contaminate hour-of-day or
day-of-week patterns.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

import duckdb

from macprofile.normalize.device_scope import macos_native_sql

_NATIVE = macos_native_sql()


def hourly_by_category(con: duckdb.DuckDBPyConnection) -> dict[str, list[int]]:
    """For each category, returns 24 ints (events at each hour, summed across days)."""
    rows = con.execute(
        f"""
        SELECT category, EXTRACT(hour FROM ts_local) AS h, COUNT(*) AS n
        FROM events
        WHERE {_NATIVE}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).fetchall()
    out: dict[str, list[int]] = defaultdict(lambda: [0] * 24)
    for cat, h, n in rows:
        out[cat][int(h)] = int(n)
    return dict(out)


def weekday_by_category(con: duckdb.DuckDBPyConnection) -> dict[str, list[int]]:
    rows = con.execute(
        f"""
        SELECT category, ((EXTRACT(dow FROM ts_local)::INT + 6) % 7) AS dow,
               COUNT(*) AS n
        FROM events
        WHERE {_NATIVE}
        GROUP BY 1, 2
        ORDER BY 1, 2
        """
    ).fetchall()
    out: dict[str, list[int]] = defaultdict(lambda: [0] * 7)
    for cat, dow, n in rows:
        out[cat][int(dow)] = int(n)
    return dict(out)


def hour_by_weekday(con: duckdb.DuckDBPyConnection) -> list[list[int]]:
    """7x24 matrix of total events. Row 0 = Monday."""
    rows = con.execute(
        f"""
        SELECT ((EXTRACT(dow FROM ts_local)::INT + 6) % 7) AS dow,
               EXTRACT(hour FROM ts_local) AS h,
               COUNT(*) AS n
        FROM events
        WHERE {_NATIVE}
        GROUP BY 1, 2
        """
    ).fetchall()
    grid = [[0] * 24 for _ in range(7)]
    for dow, h, n in rows:
        grid[int(dow)][int(h)] = int(n)
    return grid


def coverage(con: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Coverage with outlier clipping.

    An "active day" is a calendar day with at least 10 macOS-native events.
    `earliest` is the first such day; `latest` is the last such day that is
    not in the future (future-dated rows from recurring calendar events are
    excluded from `latest`). `raw_range` reports the unclipped min/max so the
    discrepancy is visible.
    """
    # Raw, unclipped range (across all events, including contaminating ones).
    raw = con.execute(
        """
        SELECT MIN(ts_local) AS earliest,
               MAX(ts_local) AS latest
        FROM events
        """
    ).fetchone()

    today = datetime.now(timezone.utc).date()
    # Active days = days with >= 10 macOS-native events that are not in the future.
    # We need both "earliest active day" and "latest non-future active day".
    bounds = con.execute(
        f"""
        WITH day_counts AS (
            SELECT date_trunc('day', ts_local) AS day, COUNT(*) AS n
            FROM events
            WHERE {_NATIVE}
            GROUP BY 1
        )
        SELECT
            (SELECT MIN(day) FROM day_counts WHERE n >= 10) AS earliest_active,
            (SELECT MAX(day) FROM day_counts WHERE n >= 10 AND day <= ?) AS latest_active,
            (SELECT COUNT(*) FROM day_counts WHERE n >= 10) AS active_day_count
        """,
        [today],
    ).fetchone()

    # Total events used in analysis (macOS-native, not future-dated).
    totals = con.execute(
        f"""
        SELECT
            COUNT(*) AS total_native,
            COUNT(DISTINCT source) AS sources_native,
            COUNT(DISTINCT category) AS categories_native
        FROM events
        WHERE {_NATIVE}
          AND ts_local <= ?
        """,
        [today],
    ).fetchone()

    return {
        "earliest": bounds[0].isoformat() if bounds[0] else None,
        "latest": bounds[1].isoformat() if bounds[1] else None,
        "raw_range": {
            "earliest": raw[0].isoformat() if raw[0] else None,
            "latest": raw[1].isoformat() if raw[1] else None,
        },
        "total_events": int(totals[0]) if totals[0] else 0,
        "sources_active": int(totals[1]) if totals[1] else 0,
        "categories_seen": int(totals[2]) if totals[2] else 0,
        "days_with_events": int(bounds[2]) if bounds[2] else 0,
        "active_day_threshold": 10,
    }
