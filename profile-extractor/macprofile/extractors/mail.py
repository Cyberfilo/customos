"""Mail Envelope Index — aggregates only (sender + send time)."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, emit, safe_copy, stable_hash
from macprofile.normalize.identity import hash_contact
from macprofile.settings import get_settings

CANDIDATES = list((Path.home() / "Library/Mail").glob("V*/MailData/Envelope Index"))


def _epoch_to_dt(v) -> datetime | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    # date_received in Mail is unix epoch seconds
    if f > 1e12:  # ms
        f /= 1000
    if f < 1e8:
        return None
    return datetime.fromtimestamp(f, tz=timezone.utc)


class MailExtractor(Extractor):
    name = "mail"

    def available(self) -> bool:
        return bool(CANDIDATES)

    def extract(self) -> Iterator:
        s = get_settings()
        for src in CANDIDATES:
            copied = safe_copy(src, self.snapshot_dir / src.parent.parent.name)
            if copied is None:
                continue
            try:
                con = sqlite3.connect(f"file:{copied}?mode=ro&immutable=1", uri=True)
            except sqlite3.OperationalError as e:
                logger.error(f"mail: open failed for {src}: {e}")
                continue
            try:
                # discover schema
                tables = [r[0] for r in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()]
                if "messages" not in tables:
                    logger.warning(f"mail {src}: no messages table; tables={tables[:10]}")
                    continue
                msg_cols = {c[1] for c in con.execute("PRAGMA table_info(messages)").fetchall()}
                sender_col = next((c for c in ("sender", "address", "from_address") if c in msg_cols), None)
                date_col = next((c for c in ("date_sent", "date_received", "received_date") if c in msg_cols), None)
                if not date_col:
                    logger.warning(f"mail {src}: no date column; cols={sorted(msg_cols)[:10]}")
                    continue
                addr_lookup: dict[int, str] = {}
                if "addresses" in tables:
                    addr_cols = {c[1] for c in con.execute("PRAGMA table_info(addresses)").fetchall()}
                    label_col = next((c for c in ("address", "comment") if c in addr_cols), None)
                    if label_col:
                        addr_lookup = {
                            r[0]: r[1] for r in con.execute(f"SELECT ROWID, {label_col} FROM addresses").fetchall()
                        }
                redact = not s.privacy.deep_content_analysis
                select_cols = ["ROWID", date_col]
                if sender_col:
                    select_cols.append(sender_col)
                if "read" in msg_cols:
                    select_cols.append("read")
                if "flagged" in msg_cols:
                    select_cols.append("flagged")
                cur = con.execute(f"SELECT {', '.join(select_cols)} FROM messages")
                for row in cur:
                    d = dict(zip(select_cols, row))
                    ts = _epoch_to_dt(d.get(date_col))
                    if ts is None:
                        continue
                    sender_raw = ""
                    if sender_col:
                        sender_val = d.get(sender_col)
                        if isinstance(sender_val, int):
                            sender_raw = addr_lookup.get(sender_val, "")
                        elif isinstance(sender_val, str):
                            sender_raw = sender_val
                    target = hash_contact(sender_raw) if sender_raw else "c_unknown"
                    payload = {
                        "is_read": bool(d.get("read")) if "read" in d else None,
                        "flagged": bool(d.get("flagged")) if "flagged" in d else None,
                        "version": src.parent.parent.name,
                    }
                    if not redact:
                        payload["sender_raw"] = sender_raw
                    yield emit(
                        ts=ts,
                        source="mail.message",
                        category="mail_seen",
                        target=target,
                        target_kind="contact",
                        metadata=payload,
                        raw_hash=stable_hash("mail", src.parent.parent.name, d["ROWID"], d.get(date_col)),
                    )
            finally:
                con.close()
