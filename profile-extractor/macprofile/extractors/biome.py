"""Biome SEGB stream extractor.

Tahoe layout: ~/Library/Biome/streams/restricted/<StreamName>/{local,remote/<UUID>}/<segb-files>
Each SEGB record carries an Apple absolute timestamp + a protobuf payload.
We don't have .proto files for these; use blackboxprotobuf and per-stream
heuristics to pull bundle IDs / URLs / values out.

Volume on a typical Mac: tens to hundreds of thousands of records across all
streams. We focus on ~20 high-value streams to keep extraction fast and the
warehouse useful.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import blackboxprotobuf
from ccl_segb import read_segb_file
from loguru import logger

from macprofile.extractors.base import Extractor, apple_to_dt, emit, stable_hash
from macprofile.normalize.identity import canonicalize_url, normalize_bundle_id

ROOT = Path.home() / "Library/Biome/streams/restricted"

# Stream → (category, source-suffix, target_kind, "primary" extractor key for target).
# "primary" is a heuristic name we'll resolve via `_primary_value`.
STREAM_MAP: dict[str, tuple[str, str, str, str]] = {
    "App.InFocus":              ("app_focus",   "biome.app_infocus",       "app",     "bundle"),
    "App.Activity":             ("app_activity","biome.app_activity",      "app",     "bundle"),
    "App.Intent":               ("app_intent",  "biome.app_intent",        "app",     "bundle"),
    "App.Intents.Transcript":   ("app_intent",  "biome.app_intent_xscript","app",     "bundle"),
    "App.WebApp.InFocus":       ("app_focus",   "biome.webapp_infocus",    "app",     "bundle"),
    "App.WebUsage":             ("web_visit",   "biome.app_web_usage",     "url",     "url"),
    "App.MediaUsage":           ("media_play",  "biome.app_media_usage",   "app",     "bundle"),
    "App.MenuItem":             ("app_activity","biome.menu_item",         "app",     "bundle"),
    "App.DocumentInteraction":  ("file_access", "biome.doc_interaction",   "file",    "url"),
    "App.RelevantShortcuts":    ("app_intent",  "biome.relevant_shortcuts","app",     "bundle"),
    "App.LanguageConsumption":  ("app_activity","biome.lang_consumption",  "app",     "bundle"),
    "Notification.Publication": ("notification","biome.notification_pub",  "app",     "bundle"),
    "Notification.Settings":    ("notification","biome.notification_set",  "app",     "bundle"),
    "Media.NowPlaying":         ("media_play",  "biome.now_playing",       "app",     "bundle"),
    "ScreenTime.AppUsage":      ("screen_time", "biome.screentime_app",    "app",     "bundle"),
    "UserFocus.ComputedMode":   ("user_focus",  "biome.focus_computed",    "other",   "string"),
    "UserFocus.InferredMode":   ("user_focus",  "biome.focus_inferred",    "other",   "string"),
    "Person.SharingInteraction":("message_sent","biome.sharing_interaction","contact","string"),
    "_DKEvent.Safari.History":  ("web_visit",   "biome.safari_history",    "url",     "url"),
    "_DKEvent.App.InFocus":     ("app_focus",   "biome.dk_app_infocus",    "app",     "bundle"),
    "Audio.Route":              ("device_state","biome.audio_route",       "device",  "string"),
    "Clock.Alarm":              ("device_state","biome.alarm",             "other",   "string"),
    "Device.Wireless.WiFi":     ("device_state","biome.wifi",              "device",  "string"),
    "Device.Wireless.Bluetooth":("device_state","biome.bluetooth",         "device",  "string"),
    "Device.Power.LowPowerMode":("device_state","biome.lpm",               "device",  "string"),
    "Discoverability.Usage":    ("app_activity","biome.discoverability",   "app",     "bundle"),
    "ScreenTime.AppUsageTimeline":("screen_time","biome.screentime_tl",    "app",     "bundle"),
    "App.LaunchSession":        ("app_launch",  "biome.app_launch_session","app",     "bundle"),
}

_BUNDLE_HINT = ("bundleid", "bundle_id", "bundleidentifier", "appbundleid", "applicationbundleid")
_URL_HINT = ("url", "uri", "weburl", "currenturl")
_DURATION_HINT = ("duration", "elapsed", "interval", "sessionduration")


def _walk_strings(obj: Any) -> Iterator[tuple[str, str]]:
    """Yield (path, value) for every string leaf, lower-cased path key."""
    def go(o: Any, path: list[str]):
        if isinstance(o, dict):
            for k, v in o.items():
                go(v, path + [str(k)])
        elif isinstance(o, list):
            for i, v in enumerate(o):
                go(v, path + [f"[{i}]"])
        elif isinstance(o, (bytes, bytearray)):
            try:
                s = o.decode("utf-8")
                yield "/".join(path), s
            except UnicodeDecodeError:
                pass
        elif isinstance(o, str):
            yield "/".join(path), o
    yield from go(obj, [])


def _walk_numbers(obj: Any) -> Iterator[tuple[str, float]]:
    def go(o: Any, path: list[str]):
        if isinstance(o, dict):
            for k, v in o.items():
                go(v, path + [str(k)])
        elif isinstance(o, list):
            for i, v in enumerate(o):
                go(v, path + [f"[{i}]"])
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            yield "/".join(path), float(o)
    yield from go(obj, [])


import re

_BUNDLE_RE = re.compile(r"^[a-zA-Z0-9._-]+\.[a-zA-Z][a-zA-Z0-9_-]*(?:\.[a-zA-Z0-9_-]+)+$")
# Bundle/URL patterns scanned out of the raw protobuf bytes — far more reliable
# than parsing arbitrary protobuf schemas.
_BUNDLE_BYTES_RE = re.compile(rb"[a-zA-Z][a-zA-Z0-9_-]*(?:\.[a-zA-Z][a-zA-Z0-9_-]*){2,}")
_URL_BYTES_RE   = re.compile(rb"https?://[a-zA-Z0-9._\-/?&%=#:+~,@!\$\(\)\*';]+")
_FILE_BYTES_RE  = re.compile(rb"file://[a-zA-Z0-9._\-/?&%=#:+~,@!\$\(\)\*';\s]+")


def _looks_like_bundle(s: str) -> bool:
    return bool(s) and len(s) <= 200 and bool(_BUNDLE_RE.match(s))


def _looks_like_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://") or s.startswith("file://") or s.startswith("ftp://")


def _byte_scan(data: bytes) -> dict[str, Any]:
    """Pull bundle IDs and URLs straight out of raw bytes. SEGB protobuf schemas
    vary stream-to-stream and bbpb often misreads them; this scan is robust
    because the strings are stored as raw ASCII.

    Protobuf length-delimited fields use [wire_tag][varint_length][bytes].
    For each candidate match we look at the byte immediately before the match:
    if it equals a plausible length within the matched string, we truncate the
    match to that length. This strips the trailing wire-tag byte of the *next*
    field (e.g. 'J' at 0x4a) that the greedy regex absorbed.
    """
    bundles: list[str] = []
    for m in _BUNDLE_BYTES_RE.finditer(data):
        raw = m.group(0)
        s = raw.decode("ascii", errors="ignore")
        # Try to honour the length-prefix from the byte preceding the match
        if m.start() > 0:
            prefix_byte = data[m.start() - 1]
            if 1 <= prefix_byte <= len(s):
                trimmed = s[:prefix_byte]
                if _looks_like_bundle(trimmed):
                    bundles.append(trimmed)
                    continue
        if _looks_like_bundle(s):
            bundles.append(s)
    urls: list[str] = []
    for rgx in (_URL_BYTES_RE, _FILE_BYTES_RE):
        for m in rgx.finditer(data):
            s = m.group(0).decode("ascii", errors="ignore").rstrip()
            if m.start() > 0:
                prefix_byte = data[m.start() - 1]
                if 4 < prefix_byte <= len(s):
                    s = s[:prefix_byte]
            if 4 < len(s) < 2000:
                urls.append(s)
    return {"bundles": bundles, "urls": urls}


def _primary_value(decoded: dict | None, raw: bytes, kind: str) -> tuple[str, dict[str, Any]]:
    """Best-effort target extraction. Combines protobuf walk (when decode worked)
    with a byte-level ASCII scan of `raw` (always reliable)."""
    extras: dict[str, Any] = {}
    bundle = ""
    url = ""
    longest_string = ""

    if decoded is not None:
        for path, val in _walk_strings(decoded):
            lower = path.lower()
            if not bundle and (any(h in lower for h in _BUNDLE_HINT) or _looks_like_bundle(val)):
                bundle = val
            if not url and (any(h in lower for h in _URL_HINT) or _looks_like_url(val)):
                url = val
            if len(val) > len(longest_string) and len(val) <= 200:
                longest_string = val

    # Byte scan fallback / supplement
    scan = _byte_scan(raw)
    if not bundle and scan["bundles"]:
        # prefer apple-style com.x.y bundle when multiple match
        bundles = sorted(scan["bundles"], key=lambda s: (-len(s), s))
        bundle = bundles[0]
    if not url and scan["urls"]:
        url = scan["urls"][0]

    if kind == "bundle":
        target = normalize_bundle_id(bundle) or longest_string
    elif kind == "url":
        canon, domain = canonicalize_url(url) if url else (longest_string, "")
        target = canon
        if domain:
            extras["domain"] = domain
    else:  # "string"
        target = longest_string or bundle or url

    if bundle and bundle != target:
        extras["bundle_id"] = bundle
    if url and url != target:
        extras["url"] = url
    if decoded is not None:
        for path, n in _walk_numbers(decoded):
            if any(h in path.lower() for h in _DURATION_HINT):
                extras["duration_sec"] = n
                break

    return target or "(unknown)", extras


def _iter_segb_files(stream_dir: Path) -> Iterator[Path]:
    for sub in ("local", "remote"):
        d = stream_dir / sub
        if not d.exists():
            continue
        for p in d.rglob("*"):
            if p.is_file() and p.name not in ("lock", ".DS_Store") and not p.name.startswith("tombstone"):
                # skip tombstone subdirs by checking parent name
                if "tombstone" in p.parts:
                    continue
                yield p


class BiomeExtractor(Extractor):
    name = "biome"

    def available(self) -> bool:
        return ROOT.exists()

    def extract(self) -> Iterator:
        for stream_name, (category, source, target_kind, primary_kind) in STREAM_MAP.items():
            d = ROOT / stream_name
            if not d.exists():
                continue
            files = list(_iter_segb_files(d))
            if not files:
                continue
            n = 0
            for p in files:
                try:
                    for record in read_segb_file(p):
                        ts_attr = getattr(record, "timestamp1", None) or getattr(record, "timestamp", None)
                        if ts_attr is None:
                            continue
                        try:
                            # ccl_segb returns a datetime (Apple-relative -> tz-aware) in v0.3
                            from datetime import datetime
                            if isinstance(ts_attr, datetime):
                                ts = ts_attr if ts_attr.tzinfo else ts_attr.replace(tzinfo=__import__("datetime").timezone.utc)
                            else:
                                ts = apple_to_dt(float(ts_attr))
                        except Exception:
                            continue
                        payload = getattr(record, "data", None) or getattr(record, "payload", None)
                        if not payload:
                            continue
                        raw = bytes(payload)
                        try:
                            decoded, _typedef = blackboxprotobuf.decode_message(raw)
                        except Exception:
                            decoded = None
                        target, extras = _primary_value(decoded, raw, primary_kind)
                        duration = extras.pop("duration_sec", None)
                        # Bundle for app-kind targets sometimes ends up as the longest string;
                        # if so, normalize.
                        if target_kind == "app":
                            target = normalize_bundle_id(target) or target
                        yield emit(
                            ts=ts,
                            source=source,
                            category=category,  # type: ignore[arg-type]
                            target=target,
                            target_kind=target_kind,  # type: ignore[arg-type]
                            duration_sec=duration,
                            metadata={"stream": stream_name, **extras},
                            raw_hash=stable_hash("biome", stream_name, str(p.name), record_index_marker(record)),
                        )
                        n += 1
                except Exception as e:
                    logger.warning(f"biome {stream_name}/{p.name}: {e}")
            logger.info(f"[biome] {stream_name}: {n} records from {len(files)} files")


def record_index_marker(record) -> str:
    """Stable per-record id within a stream — best effort across ccl_segb versions."""
    for attr in ("seq", "record_id", "offset", "ordinal"):
        v = getattr(record, attr, None)
        if v is not None:
            return f"{attr}={v}"
    ts = getattr(record, "timestamp1", None) or getattr(record, "timestamp", None)
    return f"ts={ts}"
