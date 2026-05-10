"""Apple Notes — titles + timestamps only (body decryption gated by privacy)."""
from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, apple_to_dt, emit, safe_copy, stable_hash
from macprofile.settings import get_settings

SRC = Path.home() / "Library/Group Containers/group.com.apple.notes/NoteStore.sqlite"


class NotesExtractor(Extractor):
    name = "notes"
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
            logger.error(f"notes: open failed: {e}")
            return
        try:
            # Notes (not folders) have ZNOTEDATA IS NOT NULL pointing into ZICNOTEDATA
            note_ent_pk = con.execute(
                "SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME='ICNote'"
            ).fetchone()
            note_ent = note_ent_pk[0] if note_ent_pk else 12
            cur = con.execute(
                """
                SELECT
                  o.Z_PK,
                  COALESCE(o.ZTITLE1, o.ZTITLE, o.ZTITLE2)                                AS title,
                  COALESCE(o.ZCREATIONDATE3, o.ZCREATIONDATE1, o.ZCREATIONDATE,
                           o.ZCREATIONDATE2)                                              AS created,
                  COALESCE(o.ZMODIFICATIONDATE1, o.ZMODIFICATIONDATE)                     AS modified,
                  o.ZLASTOPENEDDATE,
                  o.ZIDENTIFIER,
                  o.ZFOLDER
                FROM ZICCLOUDSYNCINGOBJECT o
                WHERE o.Z_ENT = ?
                  AND COALESCE(o.ZCREATIONDATE3, o.ZCREATIONDATE1, o.ZCREATIONDATE,
                               o.ZCREATIONDATE2) IS NOT NULL
                """,
                (note_ent,),
            )
            redact = not s.privacy.deep_content_analysis
            n = 0
            for pk, title, cd, md, last_opened, ident, folder in cur:
                if cd is None:
                    continue
                created = apple_to_dt(float(cd))
                payload = {
                    "folder_id": folder,
                    "modification_date": apple_to_dt(float(md)).isoformat() if md else None,
                    "last_opened_date": apple_to_dt(float(last_opened)).isoformat() if last_opened else None,
                }
                if not redact and title:
                    payload["title"] = title
                yield emit(
                    ts=created,
                    source="notes.note",
                    category="note",
                    target=ident or f"note_{pk}",
                    target_kind="other",
                    metadata=payload,
                    raw_hash=stable_hash("notes.create", pk, cd),
                )
                # Modification event (if distinct) is a separate behavioural signal
                if md and md != cd:
                    modified = apple_to_dt(float(md))
                    yield emit(
                        ts=modified,
                        source="notes.note",
                        category="note",
                        target=ident or f"note_{pk}",
                        target_kind="other",
                        metadata={**payload, "kind": "modified"},
                        raw_hash=stable_hash("notes.modify", pk, md),
                    )
                n += 1
            logger.info(f"notes: {n} notes processed")
        except sqlite3.OperationalError as e:
            logger.error(f"notes query failed (schema mismatch?): {e}")
        finally:
            con.close()
