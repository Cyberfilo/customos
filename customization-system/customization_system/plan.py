"""Plan selection: ask the LLM to pick from the vocabulary, then validate.

The LLM gets:
  - A *curated* slice of the profile (Mac-only signals; iPhone Biome
    contamination filtered out — see profile-extractor/HANDOFF.md
    'iPhone Biome contamination' for context).
  - The full vocabulary (id, category, description, profile_signals,
    parameters_schema for each entry).
  - A schema for its own response.

It returns a list of plan entries. We validate each:
  - id must exist in the vocabulary
  - parameters must validate against the matching entry's parameters_schema
Failed entries are dropped (and logged); the rest become the plan.
"""
from __future__ import annotations

import json
from typing import Any

from customos_core.identity import normalize_bundle_id
from jsonschema import Draft202012Validator
from loguru import logger
from pydantic import BaseModel, Field, ValidationError

from customization_system.llm import LLM
from customization_system.vocabulary import VocabularyEntry


# Bundle IDs that arrive in the profile only because the user's iPhone
# syncs Biome streams via iCloud (HANDOFF.md, "iPhone Biome contamination").
# These are not Mac-installable apps and must not influence Mac
# customization choices.
_IOS_ONLY_BUNDLE_PREFIXES = ("com.apple.springboard.",)
_IOS_ONLY_BUNDLE_IDS = frozenset(
    {
        "com.zhiliaoapp.musically",
        "com.burbn.instagram",
        "com.toyopagroup.picaboo",
        "com.apple.incallservice",
        "com.apple.mobilesafari",
        "com.apple.mobilemail",
    }
)


def _is_ios_only(bundle: str) -> bool:
    if not bundle:
        return False
    # Normalize incoming bundle so canonical-case OS-derived IDs collide
    # with the lowercased _IOS_ONLY_BUNDLE_IDS set. ADR-0006.
    norm = normalize_bundle_id(bundle)
    if norm in _IOS_ONLY_BUNDLE_IDS:
        return True
    return any(norm.startswith(p) for p in _IOS_ONLY_BUNDLE_PREFIXES)


def curate_profile_for_llm(profile: dict[str, Any], max_apps: int = 20) -> dict[str, Any]:
    """Strip iOS-contaminated bundles from the profile and trim to essentials.

    Returns a small dict (~5–10 KB) suitable for one LLM call.
    """
    apps = [a for a in profile.get("apps", []) if not _is_ios_only(a.get("bundle", ""))]
    apps = sorted(apps, key=lambda a: -a.get("focus_events", 0))[:max_apps]
    apps_summary = [
        {
            "bundle": a["bundle"],
            "focus_events": a.get("focus_events"),
            "total_seconds": a.get("total_seconds"),
            "last_seen": a.get("last_seen"),
        }
        for a in apps
    ]

    work_modes = []
    for m in profile.get("work_modes", []) or []:
        clean_apps = [b for b in m.get("apps", []) if not _is_ios_only(b)]
        if not clean_apps:
            continue
        work_modes.append({"name": m.get("name"), "apps": clean_apps, "description": m.get("description")})

    workflows = []
    for w in (profile.get("workflows") or [])[:30]:
        seq = w.get("sequence", []) if isinstance(w, dict) else []
        if not seq or any(_is_ios_only(b) for b in seq):
            continue
        workflows.append(
            {
                "sequence": seq,
                "frequency": w.get("frequency"),
                "label": w.get("label"),
                "automation_candidate": w.get("automation_candidate"),
            }
        )

    projects = [
        {"name": p.get("name"), "phase": p.get("phase")}
        for p in (profile.get("projects") or [])[:12]
    ]

    rhythm = profile.get("rhythm_description") or {}
    rhythm_quirks = profile.get("rhythm_quirks") or []

    browsing = profile.get("browsing") or {}
    top_domains = []
    for d in (browsing.get("top_domains") or [])[:15]:
        if isinstance(d, dict):
            top_domains.append({"domain": d.get("domain"), "visits": d.get("visits")})

    return {
        "generated_at": profile.get("generated_at"),
        "top_apps_mac_only": apps_summary,
        "work_modes_mac_only": work_modes,
        "workflows_mac_only": workflows[:12],
        "rhythm_description": rhythm,
        "rhythm_quirks": rhythm_quirks,
        "projects": projects,
        "top_domains": top_domains,
    }


class PlanEntry(BaseModel):
    id: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


_SYSTEM_PROMPT = """You are the plan selector for CustomOS, a system that personalises a single \
user's macOS environment. You receive (1) a behavioural profile of the user and (2) a fixed \
vocabulary of available customisations. You must choose which customisations to apply right \
now. You may only choose from the vocabulary; you cannot invent new entries.

For each chosen entry, return:
  - id: must exactly match a vocabulary entry id.
  - parameters: must validate against that entry's parameters_schema.
  - rationale: a short, evidence-grounded sentence pointing at specific signals from the profile \
that justify the choice. Reference real bundle IDs, time windows, or app names from the profile.
  - confidence: 0..1 reflecting how strongly the profile supports this choice.

Important about the input:
  - The profile has been pre-filtered to remove iPhone Biome contamination (iOS-only bundles \
that synced from the user's phone). Use only what's in `top_apps_mac_only`, `work_modes_mac_only`, \
`workflows_mac_only` etc. when choosing parameters.
  - Bundle IDs in any executor's `parameters` MUST come from `top_apps_mac_only` or be a \
well-known Mac bundle the user clearly uses; do NOT invent bundle IDs.
  - You are NOT required to pick every vocabulary entry. Pick only the ones the profile \
actually supports. Picking nothing is allowed.
  - Aim for 1–5 entries total. More than that and the user's session will feel cluttered.
"""


_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "plan": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "parameters": {"type": "object"},
                    "rationale": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["id", "parameters", "rationale", "confidence"],
            },
        }
    },
    "required": ["plan"],
}


def _vocabulary_for_llm(vocabulary: list[VocabularyEntry]) -> list[dict[str, Any]]:
    return [
        {
            "id": e.id,
            "category": e.category,
            "description": e.description,
            "profile_signals": e.profile_signals,
            "parameters_schema": e.parameters_schema,
        }
        for e in vocabulary
    ]


def select_plan(
    profile: dict[str, Any],
    vocabulary: list[VocabularyEntry],
    llm: LLM,
    *,
    max_output_tokens: int = 4000,
    use_cache: bool = True,
    profile_path: Any = None,
) -> tuple[list[PlanEntry], dict[str, Any]]:
    """Pick a plan (cache-first), validate, return.

    Returns ``(validated_plan, source_info)``.

    ``source_info`` is the raw LLM response dict on a fresh call (so
    ``plan-preview`` can show the unvalidated candidates), or a small
    provenance dict ``{"source": "cache", "metadata": {...}}`` on a cache
    hit. Either way the validated plan is identical to what would have been
    returned without caching — invalid entries are dropped at validation
    time before save.

    The cache lookup happens before any network call. Pass ``use_cache=False``
    to force a fresh LLM call (the result is still written to cache,
    overwriting any stale entry). See ADR-0007.
    """
    # Local import keeps plan_cache → plan a one-way edge (plan_cache imports
    # PlanEntry from this module). Avoids a circular import at module load.
    from customization_system.plan_cache import (
        cache_key,
        load_cached_metadata,
        load_cached_plan,
        save_cached_plan,
    )

    key = cache_key(profile, vocabulary, provider=llm.name, model=llm.model)

    if use_cache:
        cached = load_cached_plan(key)
        if cached is not None:
            meta = load_cached_metadata(key) or {}
            logger.info(
                "Plan loaded from cache",
                key=key[:12],
                entries=len(cached),
                provider=meta.get("provider"),
                model=meta.get("model"),
                cached_at=meta.get("timestamp"),
            )
            return cached, {"source": "cache", "metadata": meta}

    curated_profile = curate_profile_for_llm(profile)
    payload = {
        "profile_summary": curated_profile,
        "vocabulary": _vocabulary_for_llm(vocabulary),
    }
    logger.info(
        "calling LLM",
        provider=llm.name,
        model=llm.model,
        vocab_count=len(vocabulary),
        payload_kb=round(len(json.dumps(payload, default=str)) / 1024, 1),
    )
    raw = llm.call_json(
        system=_SYSTEM_PROMPT,
        user_payload=payload,
        schema=_RESPONSE_SCHEMA,
        max_tokens=max_output_tokens,
    )
    plan_raw = raw.get("plan", []) or []
    logger.info("LLM returned plan candidates", count=len(plan_raw))
    validated = _validate_plan(plan_raw, vocabulary)

    profile_mtime: float | None = None
    if profile_path is not None:
        try:
            from pathlib import Path as _P

            p = _P(profile_path)
            if p.exists():
                profile_mtime = p.stat().st_mtime
        except Exception:
            profile_mtime = None

    save_cached_plan(
        key,
        validated,
        metadata={
            "provider": llm.name,
            "model": llm.model,
            "profile_path": str(profile_path) if profile_path else None,
            "profile_mtime": profile_mtime,
            "candidates_returned": len(plan_raw),
            "candidates_validated": len(validated),
        },
    )
    logger.info("Plan generated and cached", key=key[:12], entries=len(validated))
    return validated, raw


def _validate_plan(
    plan_raw: list[dict[str, Any]], vocabulary: list[VocabularyEntry]
) -> list[PlanEntry]:
    by_id = {e.id: e for e in vocabulary}
    validated: list[PlanEntry] = []
    for entry in plan_raw:
        try:
            pe = PlanEntry(**entry)
        except ValidationError as exc:
            logger.warning("plan entry rejected: bad shape", entry=entry, errors=exc.errors())
            continue
        vocab = by_id.get(pe.id)
        if vocab is None:
            logger.warning("plan entry rejected: unknown id", id=pe.id)
            continue
        validator = Draft202012Validator(vocab.parameters_schema)
        errors = sorted(validator.iter_errors(pe.parameters), key=lambda e: e.path)
        if errors:
            logger.warning(
                "plan entry rejected: parameters do not validate",
                id=pe.id,
                params=pe.parameters,
                errors=[e.message for e in errors],
            )
            continue
        validated.append(pe)
    logger.info("plan validated", accepted=len(validated), rejected=len(plan_raw) - len(validated))
    return validated
