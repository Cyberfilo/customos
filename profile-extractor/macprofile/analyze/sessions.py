"""Group app-focus events into sessions using idle-gap rule."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

import duckdb

from macprofile.normalize.device_scope import macos_native_sql

_NATIVE = macos_native_sql()


def app_focus_sessions(
    con: duckdb.DuckDBPyConnection, gap_minutes: int = 5,
) -> list[dict[str, Any]]:
    """Walk app_focus events in time order; start a new session whenever the
    gap exceeds `gap_minutes` minutes. Returns one dict per session.
    Limits output to the most recent ~365 days for performance.
    Cross-device events are excluded.
    """
    rows = con.execute(
        f"""
        SELECT ts_local, target, source
        FROM events
        WHERE category IN ('app_focus','app_launch')
          AND ts_local > now() - INTERVAL 365 DAY
          AND target NOT IN ('(unknown)', '')
          AND {_NATIVE}
        ORDER BY ts_local
        """
    ).fetchall()
    if not rows:
        return []
    sessions: list[dict[str, Any]] = []
    cur_start = rows[0][0]
    cur_end = rows[0][0]
    cur_apps: dict[str, int] = {}
    cur_apps[rows[0][1]] = 1
    last_ts = rows[0][0]
    gap = timedelta(minutes=gap_minutes)
    for ts, app, _src in rows[1:]:
        if ts - last_ts > gap:
            sessions.append({
                "start": cur_start.isoformat(),
                "end": cur_end.isoformat(),
                "duration_sec": (cur_end - cur_start).total_seconds(),
                "apps": cur_apps,
                "n_events": sum(cur_apps.values()),
            })
            cur_start = ts
            cur_apps = {}
        cur_apps[app] = cur_apps.get(app, 0) + 1
        cur_end = ts
        last_ts = ts
    sessions.append({
        "start": cur_start.isoformat(),
        "end": cur_end.isoformat(),
        "duration_sec": (cur_end - cur_start).total_seconds(),
        "apps": cur_apps,
        "n_events": sum(cur_apps.values()),
    })
    return sessions


def session_summary(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    if not sessions:
        return {"count": 0}
    durs = sorted(s["duration_sec"] for s in sessions)
    n = len(durs)
    median = durs[n // 2]
    p90 = durs[min(n - 1, int(n * 0.9))]
    return {
        "count": n,
        "median_duration_sec": median,
        "p90_duration_sec": p90,
        "longest_sec": durs[-1],
        "shortest_sec": durs[0],
    }
