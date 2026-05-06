# 0007 — Plan caching in customization-system

- **Date:** 2026-05-11
- **Status:** Accepted

## Context

[ADR-0005](0005-customization-system-architecture.md) committed
customization-system to a **one-shot LLM call at startup**: read profile,
ask the LLM to pick from the fixed vocabulary, validate, apply, hold. The
Layer 1 prototype proved that flow end-to-end. It also surfaced one
property of the current LLM (gpt-5 reasoning) that the architecture didn't
yet account for:

- Across five `plan-preview` runs against the same `profile.json`, the
  same vocabulary, and the same provider/model, the LLM returned plan
  candidate counts of **3, 2, 3, 2, 3**. The selected vocabulary entries
  also shifted across runs (e.g. `dock_dim_unused` was sometimes
  included, sometimes not).
- Each call cost 18–64 seconds of wall time (reasoning tokens) and a few
  cents in API spend.

Neither cost on its own is fatal, but the combination makes Layer 1's
"start the process and your Mac becomes the configured environment"
contract weaker than it should be. The same inputs producing different
plans means "what does my Mac do when customization-system starts" is
not actually a function of the user's profile — it's a function of the
profile *and* whichever roll of the dice the model happens to make this
time. That's the bit ADR-0005 implicitly assumed away.

The cheapest principled fix is to cache the validated plan. The first
run against any given (profile, vocabulary, model) tuple pays the LLM
cost and freezes its decision; subsequent runs return that frozen
decision without calling the LLM at all. The cache must invalidate
automatically on real input changes and must never invalidate on
irrelevant ones (cosmetic edits to vocabulary descriptions, OS clock,
process restart, …). Time-based eviction is explicitly the wrong tool:
a 30-day-old plan against an unchanged profile is exactly as correct as
a fresh one; a one-second-old plan against a changed profile is wrong.

## Decision

`customization-system` writes the validated plan to disk after every
successful LLM call, and looks the cache up before every LLM call. The
mechanics:

### Key

```
sha256( json.dumps({
    "schema_version": CACHE_SCHEMA_VERSION,
    "profile":        <full profile dict>,
    "vocabulary":     [{id, category, parameters_schema} for e in VOCABULARY],
    "provider":       llm.name,
    "model":          llm.model,
}, sort_keys=True) )
```

The vocabulary slice deliberately includes only `id`, `category`, and
`parameters_schema` — the fields that change *which* entries the LLM
chooses or *what shapes* its parameters are allowed to take. Descriptions
and `profile_signals` (free prose the LLM reads but that don't constrain
its output) are excluded so copy edits don't blow the cache.
`executor_class` is excluded because it isn't JSON-serialisable and
because changes there don't change the LLM's choice — they only change
what runs when the plan is applied (which the runner catches at apply
time).

`CACHE_SCHEMA_VERSION` is a single-character version pin in
`plan_cache.py`. Bumping it invalidates every cache entry; this is the
escape hatch for when the system prompt, the curated-profile shape, or
the `PlanEntry` shape itself changes.

### Storage

`customization-system/cache/plans/<key>.json`, one file per key.
Contents: the validated plan plus a metadata block (timestamp,
provider, model, profile path, profile mtime, candidate count). Both
`cache/` and `logs/` are gitignored. The cache is single-machine,
single-user; nothing is ever shared across users or sessions.

### Lookup

`select_plan(profile, vocabulary, llm, *, use_cache=True, profile_path=None)`:

1. Compute key.
2. If `use_cache` and a cache entry exists *and* it parses cleanly into
   `list[PlanEntry]`, return it together with a provenance dict
   `{"source": "cache", "metadata": {...}}`.
3. Otherwise call the LLM, validate, write the result to cache, return
   it together with the raw LLM response.

A failed parse on the cache file is treated as a miss (logged at WARNING)
and the LLM is called as if no entry existed. The fresh result overwrites
the corrupt file.

### CLI surface

The full management surface is three things:

- `--no-cache` on `run` and `plan-preview` — force a fresh LLM call. The
  fresh plan still overwrites the cache entry; `--no-cache` is "I want a
  re-selection right now", not "don't write".
- `customization-system cache list` — show provenance of cached plans.
- `customization-system cache clear` — delete every cached entry
  (confirmation prompt; `--yes` to skip).

There is deliberately no selective invalidation, no time-based eviction,
no cache warming, no "preview but don't save" mode. The cache is
small enough and dumb enough that adding management surface would cost
more than it saves.

## Consequences

- **Reproducible startups.** Calling `customization-system run` twice
  against an unchanged profile applies *the same* customizations both
  times. This is now a function of the inputs, not the model's mood.
- **LLM cost is paid once per profile change.** Profiles regenerate on
  the user's cadence (currently manual); the 18–64s call moves from
  every startup to every profile refresh.
- **Cache invalidates automatically on every input that matters.** Edit
  `profile.json`, add a vocabulary entry, tighten a `parameters_schema`,
  switch from gpt-5 to claude-opus-4-7 — any of these produces a new key,
  so the next startup falls through to the LLM. The user never has to
  remember to invalidate.
- **Cache does NOT invalidate on irrelevant changes.** Editing a
  vocabulary entry's `description` for clarity, restarting the process,
  upgrading the model SDK to a new minor — none of those force a
  re-selection.
- **The "approximate revert" property from ADR-0005 still holds.** Cache
  is at the plan-selection layer, before any system mutation; what the
  runner applies and what it reverts are unchanged.
- **`plan-preview` and `run` now answer the same question.** Previously
  `plan-preview` would show one plan and a subsequent `run` could apply
  a different one. With the cache they agree (assuming the same flags),
  which makes preview-then-apply a meaningful workflow.
- **`--no-cache` is the user's only override.** Removed: time-based
  expiry, partial-key invalidation, per-entry caches. The contract is
  small enough to keep in the user's head: "use it, don't use it, list
  what's there, wipe it."
- **Risk: a stale cache outlives a meaningful prompt change.** If the
  system prompt in `plan.py` is rewritten in a way that would
  meaningfully shift what the LLM picks, the cache will keep returning
  the old plan because the key didn't change. Mitigation: bump
  `CACHE_SCHEMA_VERSION`. The cost of forgetting is a confusing run
  against stale logic, not a system-state corruption, so this is treated
  as a maintenance discipline rather than a runtime safeguard.
- **Risk: a future LLM provider quirk leaks into the cached plan.** If
  gpt-5 has a bug today that produces a bad-but-validating plan and we
  cache it, that plan persists. Mitigation: `--no-cache` is one
  invocation away.

Related: [ADR-0005](0005-customization-system-architecture.md),
[ADR-0006](0006-identifier-normalization-in-customos-core.md).
