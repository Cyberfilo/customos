"""On-disk cache for LLM-selected plans.

Why this exists: the Layer 1 prototype showed gpt-5 returning 3, 2, 3, 2, 3
plan entries across five runs against the same profile. That non-determinism
makes "what does my Mac do when I start customization-system" unreliable
across restarts and pays an 18–64s LLM call on every startup for variation
that isn't useful. Caching the validated plan keyed by a hash of the
inputs makes the second-and-later starts deterministic and ~instant. See
ADR-0007.

Cache invalidation is hash-based, never time-based. The key incorporates:
  - the full profile JSON (sort-keys-canonical),
  - the *plan-affecting* slice of the vocabulary (id, category,
    parameters_schema — anything that would change the LLM's choice or
    invalidate the validated parameters; descriptions are deliberately
    excluded so copy edits don't trigger a fresh call),
  - the LLM provider and model name (so switching providers always
    re-selects).

If you change the system prompt, the curated-profile shape, or anything
else that would change what the LLM actually receives, bump
``CACHE_SCHEMA_VERSION`` so all existing entries are invalidated.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger
from pydantic import ValidationError

from customization_system.plan import PlanEntry
from customization_system.vocabulary import VocabularyEntry


# Bump on any change that would alter the LLM's input or the validated
# plan's structure (system prompt, curated-profile shape, PlanEntry shape).
CACHE_SCHEMA_VERSION = "1"


def _default_cache_dir() -> Path:
    """Return the package-relative default cache directory.

    Cache lives at ``customization-system/cache/plans/`` so it sits next to
    the package's ``logs/`` and is gitignored alongside it.
    """
    return Path(__file__).resolve().parent.parent / "cache" / "plans"


def _vocabulary_for_cache(vocabulary: list[VocabularyEntry]) -> list[dict[str, Any]]:
    """Per-entry serialisation used for hashing.

    Includes only the fields that would change which entries the LLM picks
    or which parameter shapes are valid: id, category, parameters_schema.
    Excludes ``description`` and ``profile_signals`` so prose edits don't
    invalidate the cache. Excludes ``executor_class`` because it's not
    JSON-serialisable.
    """
    return [
        {
            "id": e.id,
            "category": e.category,
            "parameters_schema": e.parameters_schema,
        }
        for e in vocabulary
    ]


def cache_key(
    profile_dict: dict[str, Any],
    vocabulary: list[VocabularyEntry],
    *,
    provider: str,
    model: str,
) -> str:
    """Deterministic hex SHA-256 over profile + canonical vocab + provider+model."""
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "profile": profile_dict,
        "vocabulary": _vocabulary_for_cache(vocabulary),
        "provider": provider,
        "model": model,
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _cache_path(key: str, *, cache_dir: Path | None = None) -> Path:
    return (cache_dir or _default_cache_dir()) / f"{key}.json"


def load_cached_plan(
    key: str, *, cache_dir: Path | None = None
) -> list[PlanEntry] | None:
    """Read a cached plan. Returns None when missing or unparseable."""
    path = _cache_path(key, cache_dir=cache_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        plan = [PlanEntry(**e) for e in raw.get("plan", [])]
        return plan
    except (json.JSONDecodeError, ValidationError, KeyError, TypeError) as exc:
        # Corrupt or stale-shape cache entry — log and treat as miss.
        logger.warning("cached plan failed to load; treating as miss", key=key[:12], err=str(exc))
        return None


def load_cached_metadata(
    key: str, *, cache_dir: Path | None = None
) -> dict[str, Any] | None:
    """Read just the metadata block from a cache entry. Used by `cache list`."""
    path = _cache_path(key, cache_dir=cache_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        return raw.get("metadata") or {}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_cached_plan(
    key: str,
    plan: list[PlanEntry],
    metadata: dict[str, Any],
    *,
    cache_dir: Path | None = None,
) -> Path:
    """Persist the validated plan + caller-supplied metadata."""
    path = _cache_path(key, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    full_meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **metadata,
    }
    payload = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "metadata": full_meta,
        "plan": [pe.model_dump() for pe in plan],
    }
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def list_cached_keys(*, cache_dir: Path | None = None) -> list[str]:
    """Return the cache keys currently on disk, sorted by mtime descending."""
    d = cache_dir or _default_cache_dir()
    if not d.exists():
        return []
    entries = sorted(
        (p for p in d.glob("*.json")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return [p.stem for p in entries]


def clear_cache(*, cache_dir: Path | None = None) -> int:
    """Remove every cached plan. Returns count of files deleted."""
    d = cache_dir or _default_cache_dir()
    if not d.exists():
        return 0
    count = 0
    for p in d.glob("*.json"):
        p.unlink()
        count += 1
    # Don't remove the directory itself; keep it as a stable target.
    return count


def cache_root() -> Path:
    """Public accessor for the default cache directory (used by the CLI)."""
    return _default_cache_dir()


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "cache_key",
    "cache_root",
    "clear_cache",
    "list_cached_keys",
    "load_cached_metadata",
    "load_cached_plan",
    "save_cached_plan",
]
