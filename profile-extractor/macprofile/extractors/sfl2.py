"""sfl2 / sfl4 — recent documents, recent applications, favorites.

These are NSKeyedArchiver-encoded binary plists. Easiest path: shell out to
`plutil -convert xml1 -o - <file>`, then walk the resulting structure with
plistlib.
"""
from __future__ import annotations

import plistlib
import subprocess
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import Extractor, emit, stable_hash

SHARED = Path.home() / "Library/Application Support/com.apple.sharedfilelist"


def plist_to_xml(p: Path) -> bytes | None:
    try:
        out = subprocess.run(
            ["plutil", "-convert", "xml1", "-o", "-", str(p)],
            capture_output=True, timeout=15,
        )
        if out.returncode != 0:
            return None
        return out.stdout
    except (subprocess.TimeoutExpired, OSError):
        return None


def _resolve_archived(data: dict) -> list[dict]:
    """Resolve a NSKeyedArchiver archive's $objects table and return a list of
    dicts representing each list item, with name/url/date if available.
    """
    if data.get("$archiver") != "NSKeyedArchiver":
        return []
    objects = data.get("$objects") or []
    top = data.get("$top") or {}
    results: list[dict] = []

    def deref(uid):
        idx = uid.data if hasattr(uid, "data") else None
        if idx is None and isinstance(uid, plistlib.UID):
            idx = uid.data
        if isinstance(idx, int) and 0 <= idx < len(objects):
            return objects[idx]
        return None

    root_uid = top.get("root")
    if root_uid is None:
        return []
    root = deref(root_uid) if isinstance(root_uid, plistlib.UID) else None
    if not isinstance(root, dict):
        return []
    items_ref = root.get("NS.objects") or root.get("items")
    if items_ref is None:
        # the root might already be the items list class
        for k in ("items",):
            if k in root:
                items_ref = root[k]
                break
    if items_ref is None:
        return []
    if isinstance(items_ref, list):
        item_uids = items_ref
    else:
        return []

    for it_uid in item_uids:
        if not isinstance(it_uid, plistlib.UID):
            continue
        item = deref(it_uid)
        if not isinstance(item, dict):
            continue
        # extract a usable name + url + date
        name = ""
        url = ""
        timestamp = None
        # walk known keys
        for k in ("name", "Name", "displayName"):
            v = item.get(k)
            if isinstance(v, plistlib.UID):
                v = deref(v)
            if isinstance(v, str):
                name = v
                break
        for k in ("URL", "url", "URLBookmark", "Bookmark"):
            v = item.get(k)
            if isinstance(v, plistlib.UID):
                v = deref(v)
            if isinstance(v, str):
                url = v
                break
            if isinstance(v, bytes) and not url:
                url = ""  # bookmarks are opaque, skip
        for k in ("CreationTime", "lastVisited", "Date", "creationDate"):
            v = item.get(k)
            if isinstance(v, plistlib.UID):
                v = deref(v)
            if isinstance(v, (int, float)):
                timestamp = float(v)
                break
            if isinstance(v, datetime):
                timestamp = v
                break
        results.append({"name": name, "url": url, "timestamp": timestamp, "raw": item})
    return results


class SFL2Extractor(Extractor):
    name = "sfl2"

    def available(self) -> bool:
        return SHARED.exists()

    def extract(self) -> Iterator:
        files: list[Path] = []
        for p in SHARED.rglob("*"):
            if p.is_file() and (p.suffix in (".sfl2", ".sfl3", ".sfl4")):
                files.append(p)
        for p in files:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            xml = plist_to_xml(p)
            if not xml:
                continue
            try:
                data = plistlib.loads(xml)
            except Exception:
                continue
            list_kind = p.parent.name + "/" + p.stem
            try:
                items = _resolve_archived(data)
            except Exception as e:
                logger.debug(f"sfl2 walk fail {p}: {e}")
                continue
            for it in items:
                name = it["name"]
                url = it["url"]
                ts_raw = it["timestamp"]
                if isinstance(ts_raw, datetime):
                    ts = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
                else:
                    ts = mtime
                target = url or name
                if not target:
                    continue
                if target.startswith("file://"):
                    target_kind = "file"
                elif "://" in target:
                    target_kind = "url"
                else:
                    target_kind = "file"
                yield emit(
                    ts=ts,
                    source=f"sfl2.{list_kind}",
                    category="file_recent",
                    target=target,
                    target_kind=target_kind,  # type: ignore[arg-type]
                    metadata={"name": name, "list": list_kind, "source_file": str(p)},
                    raw_hash=stable_hash("sfl2", str(p), target, ts),
                )
