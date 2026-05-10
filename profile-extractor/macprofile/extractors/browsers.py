"""Safari, Chrome, Brave: history + tab/window state where available."""
from __future__ import annotations

import plistlib
import sqlite3
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from macprofile.extractors.base import (
    Extractor,
    apple_to_dt,
    chrome_to_dt,
    emit,
    safe_copy,
    stable_hash,
)
from macprofile.normalize.identity import canonicalize_url
from macprofile.settings import get_settings

HOME = Path.home()


def _open_ro(db: Path) -> sqlite3.Connection:
    """Open a SQLite DB read-only. The caller is responsible for closing."""
    uri = f"file:{db}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True, timeout=2)


# ---------------------------------------------------------------- Safari

class SafariExtractor(Extractor):
    name = "safari"
    src_history = HOME / "Library/Safari/History.db"
    src_last = HOME / "Library/Safari/LastSession.plist"
    src_bookmarks = HOME / "Library/Safari/Bookmarks.plist"
    src_recent = HOME / "Library/Safari/RecentlyClosedTabs.plist"

    def available(self) -> bool:
        return self.src_history.exists()

    def extract(self) -> Iterator:
        s = get_settings()
        copied = safe_copy(self.src_history, self.snapshot_dir)
        if copied is None:
            logger.warning("safari: history.db copy failed")
        else:
            yield from self._history_events(copied)
        if self.src_last.exists():
            try:
                safe_copy(self.src_last, self.snapshot_dir)
                yield from self._tabs_from_last_session(self.src_last)
            except Exception as e:
                logger.warning(f"safari: LastSession parse failed: {e}")
        if self.src_bookmarks.exists():
            try:
                safe_copy(self.src_bookmarks, self.snapshot_dir)
                yield from self._bookmark_events(self.src_bookmarks)
            except Exception as e:
                logger.warning(f"safari: Bookmarks parse failed: {e}")
        _ = s  # silence unused

    def _history_events(self, db: Path) -> Iterator:
        try:
            con = _open_ro(db)
        except sqlite3.OperationalError as e:
            logger.error(f"safari: open ro failed: {e}")
            return
        try:
            cur = con.execute(
                """
                SELECT v.id, v.visit_time, h.url, h.visit_count, h.domain_expansion
                FROM history_visits v
                JOIN history_items h ON h.id = v.history_item
                ORDER BY v.visit_time DESC
                """
            )
            for row in cur:
                vid, vtime, url, vcount, _ = row
                if vtime is None or url is None:
                    continue
                dt = apple_to_dt(float(vtime))
                canon, domain = canonicalize_url(url)
                yield emit(
                    ts=dt,
                    source="safari.history",
                    category="web_visit",
                    target=canon,
                    target_kind="url",
                    metadata={"domain": domain, "visit_count_total": vcount},
                    raw_hash=stable_hash("safari.visit", vid, vtime),
                )
        finally:
            con.close()

    def _tabs_from_last_session(self, plist: Path) -> Iterator:
        with plist.open("rb") as fp:
            data = plistlib.load(fp)
        # Newer Safari stores tabs under SessionWindows -> TabStates -> URL/Title
        windows = data.get("SessionWindows") or []
        snapshot_ts = datetime.fromtimestamp(plist.stat().st_mtime, tz=timezone.utc)
        for w_idx, w in enumerate(windows):
            tabs = w.get("TabStates") or []
            for t_idx, t in enumerate(tabs):
                url = t.get("TabURL") or t.get("URL") or ""
                title = t.get("TabTitle") or t.get("Title") or ""
                if not url:
                    continue
                canon, domain = canonicalize_url(url)
                yield emit(
                    ts=snapshot_ts,
                    source="safari.last_session",
                    category="tab_state",
                    target=canon,
                    target_kind="url",
                    metadata={
                        "domain": domain,
                        "title": title,
                        "window_index": w_idx,
                        "tab_index": t_idx,
                        "tab_count_in_window": len(tabs),
                        "window_count": len(windows),
                    },
                    raw_hash=stable_hash("safari.lastsession", w_idx, t_idx, canon, snapshot_ts),
                )

    def _bookmark_events(self, plist: Path) -> Iterator:
        with plist.open("rb") as fp:
            data = plistlib.load(fp)
        snapshot_ts = datetime.fromtimestamp(plist.stat().st_mtime, tz=timezone.utc)
        # Walk recursively, leaves with WebBookmarkType == WebBookmarkTypeLeaf carry URLString
        def walk(node):
            if isinstance(node, dict):
                if node.get("WebBookmarkType") == "WebBookmarkTypeLeaf":
                    url = node.get("URLString") or ""
                    if url:
                        canon, domain = canonicalize_url(url)
                        title = (node.get("URIDictionary") or {}).get("title") or ""
                        yield emit(
                            ts=snapshot_ts,
                            source="safari.bookmarks",
                            category="bookmark",
                            target=canon,
                            target_kind="url",
                            metadata={"domain": domain, "title": title, "uuid": node.get("WebBookmarkUUID")},
                            raw_hash=stable_hash("safari.bookmark", node.get("WebBookmarkUUID"), canon),
                        )
                for v in node.values():
                    yield from walk(v)
            elif isinstance(node, list):
                for item in node:
                    yield from walk(item)
        yield from walk(data)


# ---------------------------------------------------------------- Chromium-based

class _ChromiumExtractor(Extractor):
    src: Path
    label: str

    def available(self) -> bool:
        return self.src.exists()

    def extract(self) -> Iterator:
        copied = safe_copy(self.src, self.snapshot_dir)
        if copied is None:
            return
        try:
            con = _open_ro(copied)
        except sqlite3.OperationalError as e:
            logger.error(f"{self.label}: open ro failed: {e}")
            return
        try:
            cur = con.execute(
                "SELECT id, url, title, visit_count, last_visit_time FROM urls"
            )
            urls = {row[0]: row for row in cur}
            cur = con.execute(
                "SELECT id, url, visit_time, transition FROM visits"
            )
            for vid, url_id, vtime, transition in cur:
                if vtime is None:
                    continue
                u = urls.get(url_id)
                if not u:
                    continue
                _, url, title, vcount, _ = u
                dt = chrome_to_dt(int(vtime))
                canon, domain = canonicalize_url(url or "")
                yield emit(
                    ts=dt,
                    source=f"{self.label}.history",
                    category="web_visit",
                    target=canon,
                    target_kind="url",
                    metadata={"domain": domain, "title": title, "visit_count_total": vcount, "transition": transition},
                    raw_hash=stable_hash(self.label, "visit", vid),
                )
        finally:
            con.close()


class ChromeExtractor(_ChromiumExtractor):
    name = "chrome"
    label = "chrome"
    src = HOME / "Library/Application Support/Google/Chrome/Default/History"


class BraveExtractor(_ChromiumExtractor):
    name = "brave"
    label = "brave"
    src = HOME / "Library/Application Support/BraveSoftware/Brave-Browser/Default/History"
