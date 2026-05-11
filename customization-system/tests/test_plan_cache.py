"""Tests for customization_system.plan_cache.

Scope: cache key determinism / invalidation, persistence round-trip, and the
"missing key returns None" path. The LLM and the executors are NOT exercised
here; everything uses a tmp cache directory and stub VocabularyEntry objects
so the suite stays hermetic and fast.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from customization_system.executor import CustomizationExecutor
from customization_system.plan import PlanEntry
from customization_system.plan_cache import (
    CACHE_SCHEMA_VERSION,
    cache_key,
    clear_cache,
    list_cached_keys,
    load_cached_metadata,
    load_cached_plan,
    save_cached_plan,
)
from customization_system.vocabulary import VocabularyEntry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _StubExecutor(CustomizationExecutor):
    """No-op executor so VocabularyEntry has a valid executor_class."""

    def apply(self, parameters):  # noqa: D401
        pass

    def revert(self):  # noqa: D401
        pass


def _entry(eid: str, *, category: str = "test", schema: dict | None = None) -> VocabularyEntry:
    return VocabularyEntry(
        id=eid,
        category=category,
        description=f"desc for {eid}",
        profile_signals=f"signals for {eid}",
        parameters_schema=schema if schema is not None else {"type": "object"},
        executor_class=_StubExecutor,
    )


@pytest.fixture
def vocab() -> list[VocabularyEntry]:
    return [_entry("alpha"), _entry("beta")]


@pytest.fixture
def profile() -> dict:
    return {
        "generated_at": "2026-05-08T08:57:02",
        "apps": [{"bundle": "com.apple.terminal", "focus_events": 5938}],
        "rhythm_description": {"summary": "Mon-Fri 09:30-18:30"},
    }


@pytest.fixture
def llm_id() -> tuple[str, str]:
    return ("openai", "gpt-5")


# ---------------------------------------------------------------------------
# cache_key
# ---------------------------------------------------------------------------

class TestCacheKey:
    def test_deterministic(self, profile, vocab, llm_id):
        provider, model = llm_id
        a = cache_key(profile, vocab, provider=provider, model=model)
        b = cache_key(copy.deepcopy(profile), list(vocab), provider=provider, model=model)
        assert a == b
        assert len(a) == 64  # sha256 hex

    def test_profile_change_invalidates(self, profile, vocab, llm_id):
        provider, model = llm_id
        a = cache_key(profile, vocab, provider=provider, model=model)
        modified = copy.deepcopy(profile)
        modified["apps"][0]["focus_events"] = 9999
        b = cache_key(modified, vocab, provider=provider, model=model)
        assert a != b

    def test_vocab_add_invalidates(self, profile, vocab, llm_id):
        provider, model = llm_id
        a = cache_key(profile, vocab, provider=provider, model=model)
        b = cache_key(profile, [*vocab, _entry("gamma")], provider=provider, model=model)
        assert a != b

    def test_vocab_remove_invalidates(self, profile, vocab, llm_id):
        provider, model = llm_id
        a = cache_key(profile, vocab, provider=provider, model=model)
        b = cache_key(profile, vocab[:1], provider=provider, model=model)
        assert a != b

    def test_vocab_schema_change_invalidates(self, profile, vocab, llm_id):
        provider, model = llm_id
        a = cache_key(profile, vocab, provider=provider, model=model)
        new_vocab = [
            _entry(
                vocab[0].id,
                schema={"type": "object", "properties": {"foo": {"type": "string"}}},
            ),
            vocab[1],
        ]
        b = cache_key(profile, new_vocab, provider=provider, model=model)
        assert a != b

    def test_provider_change_invalidates(self, profile, vocab):
        a = cache_key(profile, vocab, provider="openai", model="gpt-5")
        b = cache_key(profile, vocab, provider="anthropic", model="gpt-5")
        assert a != b

    def test_model_change_invalidates(self, profile, vocab):
        a = cache_key(profile, vocab, provider="openai", model="gpt-5")
        b = cache_key(profile, vocab, provider="openai", model="gpt-4o")
        assert a != b

    def test_description_change_does_not_invalidate(self, profile, vocab, llm_id):
        """Prose edits to entry descriptions must not blow the cache."""
        provider, model = llm_id
        original = cache_key(profile, vocab, provider=provider, model=model)
        edited = [vocab[0].model_copy(update={"description": "totally rewritten"}), vocab[1]]
        assert cache_key(profile, edited, provider=provider, model=model) == original


# ---------------------------------------------------------------------------
# load_cached_plan / save_cached_plan
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_missing_key_returns_none(self, tmp_path):
        assert load_cached_plan("nonexistent" * 8, cache_dir=tmp_path) is None
        assert load_cached_metadata("nonexistent" * 8, cache_dir=tmp_path) is None

    def test_round_trip(self, tmp_path):
        plan = [
            PlanEntry(id="alpha", parameters={"k": 1}, rationale="why a", confidence=0.9),
            PlanEntry(id="beta", parameters={}, rationale="why b", confidence=0.4),
        ]
        save_cached_plan(
            "abc123",
            plan,
            metadata={"provider": "openai", "model": "gpt-5"},
            cache_dir=tmp_path,
        )
        loaded = load_cached_plan("abc123", cache_dir=tmp_path)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded[0].id == "alpha"
        assert loaded[0].parameters == {"k": 1}
        assert loaded[0].confidence == 0.9
        assert loaded[1].id == "beta"

    def test_metadata_round_trip(self, tmp_path):
        save_cached_plan(
            "metakey",
            [PlanEntry(id="alpha", parameters={}, rationale="r", confidence=1.0)],
            metadata={"provider": "openai", "model": "gpt-5", "candidates_validated": 1},
            cache_dir=tmp_path,
        )
        meta = load_cached_metadata("metakey", cache_dir=tmp_path)
        assert meta is not None
        assert meta["provider"] == "openai"
        assert meta["model"] == "gpt-5"
        assert meta["candidates_validated"] == 1
        # save_cached_plan adds a timestamp even if the caller didn't.
        assert "timestamp" in meta

    def test_overwrite(self, tmp_path):
        save_cached_plan(
            "k",
            [PlanEntry(id="alpha", parameters={}, rationale="v1", confidence=0.5)],
            metadata={"provider": "openai", "model": "gpt-5"},
            cache_dir=tmp_path,
        )
        save_cached_plan(
            "k",
            [PlanEntry(id="beta", parameters={}, rationale="v2", confidence=0.6)],
            metadata={"provider": "openai", "model": "gpt-5"},
            cache_dir=tmp_path,
        )
        loaded = load_cached_plan("k", cache_dir=tmp_path)
        assert loaded is not None and loaded[0].id == "beta"

    def test_corrupt_file_returns_none(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("not json at all {")
        assert load_cached_plan("bad", cache_dir=tmp_path) is None

    def test_unknown_shape_returns_none(self, tmp_path):
        # Valid JSON but doesn't match the cache schema.
        (tmp_path / "weird.json").write_text(json.dumps({"plan": [{"id": "x"}]}))
        # Missing rationale / confidence — PlanEntry validation will fail.
        assert load_cached_plan("weird", cache_dir=tmp_path) is None


# ---------------------------------------------------------------------------
# list_cached_keys / clear_cache
# ---------------------------------------------------------------------------

class TestListAndClear:
    def test_list_empty(self, tmp_path):
        assert list_cached_keys(cache_dir=tmp_path) == []

    def test_list_and_clear(self, tmp_path):
        for k in ("k1", "k2", "k3"):
            save_cached_plan(
                k,
                [PlanEntry(id="alpha", parameters={}, rationale="r", confidence=1.0)],
                metadata={"provider": "openai", "model": "gpt-5"},
                cache_dir=tmp_path,
            )
        keys = list_cached_keys(cache_dir=tmp_path)
        assert sorted(keys) == ["k1", "k2", "k3"]
        n = clear_cache(cache_dir=tmp_path)
        assert n == 3
        assert list_cached_keys(cache_dir=tmp_path) == []

    def test_clear_when_dir_missing(self, tmp_path):
        gone = tmp_path / "does-not-exist"
        assert clear_cache(cache_dir=gone) == 0


# ---------------------------------------------------------------------------
# Cache schema version sanity
# ---------------------------------------------------------------------------

def test_schema_version_is_pinned():
    """If you change the LLM input shape, bump CACHE_SCHEMA_VERSION."""
    assert CACHE_SCHEMA_VERSION == "1"
