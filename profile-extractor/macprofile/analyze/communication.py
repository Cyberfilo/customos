"""Communication graph aggregates."""
from __future__ import annotations

from typing import Any

import duckdb

from macprofile.normalize.device_scope import macos_native_sql

_NATIVE = macos_native_sql()


def top_contacts(con: duckdb.DuckDBPyConnection, top: int = 30) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT target,
               SUM(CASE WHEN category='message_sent' THEN 1 ELSE 0 END) AS sent,
               SUM(CASE WHEN category='message_received' THEN 1 ELSE 0 END) AS received,
               SUM(CASE WHEN category='mail_seen' THEN 1 ELSE 0 END) AS mail,
               MAX(ts_local) AS last_seen,
               MIN(ts_local) AS first_seen,
               COUNT(*) AS total
        FROM events
        WHERE target_kind = 'contact' AND target <> 'c_unknown'
        GROUP BY 1
        ORDER BY total DESC
        LIMIT ?
        """,
        [top],
    ).fetchall()
    return [
        {
            "contact_hash": r[0],
            "sent": int(r[1]),
            "received": int(r[2]),
            "mail": int(r[3]),
            "last_seen": r[4].isoformat() if r[4] else None,
            "first_seen": r[5].isoformat() if r[5] else None,
            "total": int(r[6]),
        }
        for r in rows
    ]


def domain_frequency(con: duckdb.DuckDBPyConnection, top: int = 60) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT
          json_extract_string(metadata, '$.domain') AS domain,
          COUNT(*) AS visits,
          MAX(ts_local) AS last_visit
        FROM events
        WHERE category = 'web_visit'
          AND json_extract_string(metadata, '$.domain') IS NOT NULL
          AND json_extract_string(metadata, '$.domain') <> ''
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT ?
        """,
        [top],
    ).fetchall()
    return [{"domain": r[0], "visits": int(r[1]), "last_visit": r[2].isoformat()} for r in rows]


def app_affinity(con: duckdb.DuckDBPyConnection, top: int = 40) -> list[dict[str, Any]]:
    rows = con.execute(
        f"""
        SELECT target,
               COUNT(*) AS focus_events,
               MIN(ts_local) AS first_seen,
               MAX(ts_local) AS last_seen,
               SUM(coalesce(duration_sec, 0)) AS total_seconds
        FROM events
        WHERE category IN ('app_focus','app_usage','app_launch')
          AND target_kind = 'app'
          AND target NOT IN ('(unknown)', '')
          AND {_NATIVE}
        GROUP BY 1
        ORDER BY focus_events DESC
        LIMIT ?
        """,
        [top],
    ).fetchall()
    return [
        {
            "bundle": r[0],
            "focus_events": int(r[1]),
            "first_seen": r[2].isoformat() if r[2] else None,
            "last_seen": r[3].isoformat() if r[3] else None,
            "total_seconds": float(r[4]) if r[4] else 0.0,
        }
        for r in rows
    ]
