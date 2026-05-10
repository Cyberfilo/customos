"""Which apps appear in focus within the same time window — work-mode clusters."""
from __future__ import annotations

from collections import defaultdict

import duckdb

from macprofile.normalize.device_scope import macos_native_sql

_NATIVE = macos_native_sql()


def cohabitation_pairs(
    con: duckdb.DuckDBPyConnection, bucket_minutes: int = 30, top: int = 80,
) -> list[dict]:
    rows = con.execute(
        f"""
        SELECT date_trunc('hour', ts_local) +
               (FLOOR(EXTRACT(minute FROM ts_local) / {bucket_minutes}) * INTERVAL {bucket_minutes} MINUTE) AS bucket,
               target
        FROM events
        WHERE category = 'app_focus' AND target NOT IN ('(unknown)','')
          AND {_NATIVE}
        GROUP BY 1, 2
        """
    ).fetchall()
    by_bucket: dict[object, set[str]] = defaultdict(set)
    for bucket, target in rows:
        by_bucket[bucket].add(target)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for apps in by_bucket.values():
        a = sorted(apps)
        for i, x in enumerate(a):
            for y in a[i + 1 :]:
                pair_counts[(x, y)] += 1
    items = sorted(pair_counts.items(), key=lambda kv: kv[1], reverse=True)[:top]
    return [{"a": a, "b": b, "buckets_co_active": c} for (a, b), c in items]
