"""Messages chat.db — privacy-gated. We extract counts, timestamps, hashed
contact handles. Bodies are NEVER pulled into events unless deep_content_analysis."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, emit, safe_copy, stable_hash
from macprofile.normalize.identity import hash_contact
from macprofile.settings import get_settings

SRC = Path.home() / "Library/Messages/chat.db"

# macOS 10.13+: message.date is nanoseconds since 2001-01-01 (Apple absolute).
APPLE_OFFSET = 978307200


def _msg_date_to_dt(date_val: int) -> datetime:
    if date_val is None:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    if date_val > 10**14:  # nanoseconds
        secs = date_val / 1e9
    elif date_val > 10**11:  # microseconds (very rare)
        secs = date_val / 1e6
    else:  # seconds
        secs = float(date_val)
    return datetime.fromtimestamp(secs + APPLE_OFFSET, tz=timezone.utc)


class MessagesExtractor(Extractor):
    name = "messages"
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
            logger.error(f"messages: open failed: {e}")
            return
        try:
            handles: dict[int, tuple[str, str]] = {
                r[0]: (r[1], r[2]) for r in con.execute(
                    "SELECT ROWID, id, service FROM handle"
                ).fetchall()
            }
            redact = not s.privacy.deep_content_analysis
            cur = con.execute(
                """
                SELECT m.ROWID, m.handle_id, m.date, m.is_from_me, m.service,
                       m.is_read, length(coalesce(m.text, ''))
                FROM message m
                WHERE m.date IS NOT NULL
                ORDER BY m.date
                """
            )
            for rowid, hid, date, is_from_me, service, is_read, text_len in cur:
                ts = _msg_date_to_dt(date)
                hraw, _svc = handles.get(hid, ("", ""))
                target = hash_contact(hraw) if hraw else "c_unknown"
                cat = "message_sent" if is_from_me else "message_received"
                payload = {
                    "service": service,
                    "is_read": bool(is_read),
                    "body_length": int(text_len) if text_len is not None else 0,
                }
                if not redact:
                    payload["handle_raw"] = hraw  # only if user opts in
                yield emit(
                    ts=ts,
                    source=f"messages.{cat}",
                    category=cat,  # type: ignore[arg-type]
                    target=target,
                    target_kind="contact",
                    metadata=payload,
                    raw_hash=stable_hash("messages", rowid, date),
                )
        finally:
            con.close()
