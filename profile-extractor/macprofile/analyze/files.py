"""File hotspots and project clustering by path prefix."""
from __future__ import annotations

import os
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

import duckdb


def top_files(con: duckdb.DuckDBPyConnection, top: int = 50) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT target,
               COUNT(*) AS access_count,
               MIN(ts_local) AS first_seen,
               MAX(ts_local) AS last_seen
        FROM events
        WHERE category IN ('file_access','file_recent')
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT ?
        """,
        [top],
    ).fetchall()
    return [
        {"path": r[0], "count": int(r[1]), "first": r[2].isoformat(), "last": r[3].isoformat()}
        for r in rows
    ]


def directory_hotspots(con: duckdb.DuckDBPyConnection, depth: int = 5, top: int = 50) -> list[dict[str, Any]]:
    """Cluster file accesses by directory prefix (up to `depth` segments).
    A 'project' is a hot directory under ~/Documents, ~/Projects, ~/Code, etc."""
    rows = con.execute(
        """
        SELECT target FROM events WHERE category IN ('file_access','file_recent')
        """
    ).fetchall()
    dir_count: dict[str, int] = defaultdict(int)
    dir_last: dict[str, datetime] = {}
    dir_first: dict[str, datetime] = {}
    for (path,) in rows:
        if not path:
            continue
        if path.startswith("file://"):
            from urllib.parse import unquote
            path = unquote(path[7:])
        parts = path.split(os.sep)
        for d in range(min(depth, len(parts) - 1), 1, -1):
            prefix = os.sep.join(parts[:d])
            dir_count[prefix] += 1
    # second pass for first/last seen
    for row in con.execute(
        """
        SELECT target, ts_local FROM events WHERE category IN ('file_access','file_recent')
        """
    ).fetchall():
        path, ts = row
        if not path:
            continue
        parts = path.split(os.sep)
        for d in range(2, depth + 1):
            prefix = os.sep.join(parts[:d])
            if prefix not in dir_first or ts < dir_first[prefix]:
                dir_first[prefix] = ts
            if prefix not in dir_last or ts > dir_last[prefix]:
                dir_last[prefix] = ts

    items = sorted(dir_count.items(), key=lambda kv: kv[1], reverse=True)
    out: list[dict[str, Any]] = []
    for prefix, n in items[:top]:
        if not prefix or prefix in ("/", "/Users"):
            continue
        if n < 3:
            continue
        first = dir_first.get(prefix)
        last = dir_last.get(prefix)
        days_dormant = None
        if last:
            days_dormant = (datetime.now() - last.replace(tzinfo=None)).days
        out.append({
            "directory": prefix,
            "count": n,
            "first": first.isoformat() if first else None,
            "last": last.isoformat() if last else None,
            "days_since_last": days_dormant,
        })
    return out
