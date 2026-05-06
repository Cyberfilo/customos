# 0004 — BehavioralProfile as a typed contract in customos-core

- **Date:** 2026-05-11
- **Status:** Accepted

## Context

The `profile-extractor` produces a `profile.json` describing the user's
stable behavioral traits. The future `customization-system` will consume
this file to decide which adaptations to dispatch. Up to the previous
session the profile was an untyped dict assembled in
`profile-extractor/macprofile/profile/build.py`; the only documented
shape was an enumeration of top-level keys in `HANDOFF.md`. There was
no `BehavioralProfile` Pydantic model anywhere in the repo.

That arrangement is unsafe in two specific ways:

1. The customization-system, once it exists, would have no compile-time
   guarantee that fields it depends on (`work_modes`, `projects[].phase`,
   `coverage.raw_range`, etc.) are present in the shape it expects.
   Drift between producer and consumer becomes a silent runtime failure.
2. The LLM also reads `profile.json` (as background context). Without a
   schema, every prompt construction site has to re-derive what's in the
   file and where, and any rename leaks into prompts that nobody updated.

ADR-0001 set up `customos-core` precisely as the home for cross-subsystem
contracts. The profile is the largest and most load-bearing such contract
between the extractor and the customization-system. Defining it formally
there is the natural next step.

## Decision

`BehavioralProfile` is now a Pydantic v2 model defined in
`customos-core/customos_core/profile.py`, alongside the component models
(`Coverage`, `Rhythms`, `AppAffinity`, `Sequence`, `WorkMode`, `Project`,
`Browsing`, `Communication`, `Contact`, `Idiosyncrasy`, `NegativeSignal`,
`Privacy`) and the shared markers (`Stability`, `Scope`,
`Durability`, `ProjectPhase`, `ContactClass`, `NegativeSignalKind`).

The schema is the single source of truth for the contract:

- `profile-extractor` imports `customos_core.BehavioralProfile` and
  constructs an instance, serialised via `.model_dump_json()`.
- The (future) `customization-system` will validate `profile.json`
  with `BehavioralProfile.model_validate(json.loads(...))` on load.
- Documentation (`docs/interface.md`) points at the model rather than
  describing the shape narratively.

The model carries a `schema_version: Literal["1.0.0"]` field and
intentionally version-pins. Bumping the version requires touching both
the producer and consumer.

### Design decisions baked into v1.0.0

- **Rhythms carries both raw matrices and an LLM narrative.** Code
  consumers need per-hour-per-weekday counts to answer "what does the
  user do at 14:00 on Wednesday?"; humans reading `profile.md` benefit
  from prose like "Mon–Fri 09:30–18:30". Both are needed.
- **Sequences carry `steps: list[str]` (bundle IDs).** No per-step
  dwell time today; promoting to `list[Step]` later only requires
  changing one field type.
- **Contact identifiers stay at `c_<16hex>`.** SHA-256 of the normalized
  handle salted with a per-install random salt, truncated to 16 hex
  chars. Matches what the warehouse already produces; no rehash.
- **Stability is attached per-trait where flakiness matters**
  (`AppAffinity`, `Project`, optionally `Idiosyncrasy`). Coverage and
  Privacy are population statistics — no stability indicator there.
- **Scope is attached where data could mix Mac and iPhone signals.**
  After the same session's Workstream 1, the analyzers default to
  `mac_only`. Carrying the field future-proofs against later
  cross-device work without a schema migration.

### What's explicitly not in the model

- `customization_hooks`. Demoted to a separate `output/hook_suggestions.json`
  in the same session. Hooks reference predicates that aren't computable
  by any CustomOS subsystem yet; defining a typed `Hook` schema waits on
  the predicate-vocabulary spec.
- State (current app, idle time, last keystroke). Per
  [ADR-0003](0003-traits-vs-state-separation.md), state lives in the
  customization-system, not the profile.
- Raw aggregates (`workflows_raw`, `cohabitation_raw`, …). Diagnostic,
  not contractual. They stay in `output/analyses.json`.
- `Event`, sessionization rules, identifier normalization. These exist
  in the extractor but the lift to `customos-core` is intentionally
  deferred until the customization-system needs them.

## Consequences

- `customos-core` gains a hard dependency on Pydantic v2 (added to its
  `pyproject.toml`).
- `profile-extractor` declares `customos-core` as a workspace-internal
  dependency via `[tool.uv.sources]`. `uv sync` resolves it from the
  workspace.
- The customization-system, once it starts, imports
  `customos_core.BehavioralProfile` and validates on read. Drift in
  field names or types between extractor and consumer becomes a load-time
  error rather than a silent miss.
- Bumping `schema_version` is a two-side coordination point. The minor
  version is reserved for additive changes; the major version is reserved
  for incompatible ones.
- The model is *trait-only*. Adding state fields requires either a
  superseding ADR or moving the field to a separate state-side schema.

Related: [ADR-0001](0001-three-subsystem-split.md),
[ADR-0002](0002-uv-workspace-layout.md),
[ADR-0003](0003-traits-vs-state-separation.md).
