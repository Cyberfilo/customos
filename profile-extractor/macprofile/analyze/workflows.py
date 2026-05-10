"""Frequent app-focus sequence mining (PrefixSpan-lite)."""
from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any

import duckdb

from macprofile.normalize.device_scope import macos_native_sql

_NATIVE = macos_native_sql()


def app_sequences_within_window(
    con: duckdb.DuckDBPyConnection, window_minutes: int = 5, min_len: int = 3, max_len: int = 6,
) -> list[list[str]]:
    """Generate app-focus sequences. A sequence is a contiguous chain where
    consecutive events are at most `window_minutes` apart. Sequences are
    de-duplicated to remove A->A->A noise (collapse consecutive duplicates).
    Cross-device events are excluded.
    """
    rows = con.execute(
        f"""
        SELECT ts_local, target FROM events
        WHERE category = 'app_focus'
          AND target NOT IN ('(unknown)', '')
          AND {_NATIVE}
        ORDER BY ts_local
        """
    ).fetchall()
    if not rows:
        return []
    cap = timedelta(minutes=window_minutes)
    sequences: list[list[str]] = []
    cur: list[str] = []
    last_ts = None
    for ts, app in rows:
        if last_ts is None or (ts - last_ts) <= cap:
            if not cur or cur[-1] != app:  # collapse consecutive duplicates
                cur.append(app)
        else:
            if len(cur) >= min_len:
                sequences.append(cur[:max_len])
            cur = [app]
        last_ts = ts
    if len(cur) >= min_len:
        sequences.append(cur[:max_len])
    return sequences


def top_n_grams(
    sequences: list[list[str]], n_min: int = 3, n_max: int = 5, top: int = 50,
) -> list[dict[str, Any]]:
    """Count frequent n-grams of length n_min..n_max across sequences."""
    counter: Counter[tuple[str, ...]] = Counter()
    for seq in sequences:
        for k in range(n_min, n_max + 1):
            for i in range(len(seq) - k + 1):
                counter[tuple(seq[i : i + k])] += 1
    most = counter.most_common(top)
    return [{"sequence": list(seq), "frequency": c} for seq, c in most]
