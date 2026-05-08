# customos-core

Shared contracts between `profile-extractor` and the future
`customization-system`. This package is the seam between them: the
extractor produces a `BehavioralProfile` that matches the schema
defined here, and the customization system reads `profile.json` by
validating it against the same models. Drift between producer and
consumer becomes a type error at import time rather than a silent
runtime breakage.

## What's in here

- `customos_core.profile` — the `BehavioralProfile` Pydantic v2 model
  and its component models (`Coverage`, `Rhythms`, `AppAffinity`,
  `Sequence`, `WorkMode`, `Project`, `Browsing`, `Communication`,
  `Idiosyncrasy`, `NegativeSignal`, `Privacy`, plus the shared
  `Stability` / `Scope` markers).

- `customos_core.identity` — pure normalization helpers shared by both
  subsystems: `normalize_bundle_id`, `canonicalize_url`, `hash_contact`.
  These are the canonical implementations; the extractor's
  `macprofile/normalize/identity.py` is now a thin shim that re-exports
  them. See [ADR-0006](../docs/decisions/0006-identifier-normalization-in-customos-core.md)
  for why these moved here — the short version is that identifier
  drift between subsystems caused a silent visual bug
  (case-sensitive comparison dimmed the user's most-used Dock apps),
  and typed schemas don't catch *value normalization* drift.

The package follows the trait-only stance from
[ADR-0003](../docs/decisions/0003-traits-vs-state-separation.md):
`BehavioralProfile` describes *stable behavioral traits*. State (live
foreground app, idle time, current focus) lives in the customization
system and is never written back into the profile.

## What's not in here, yet

- `Event` schema (the warehouse row type). Still defined in
  `profile-extractor/macprofile/schema.py`; the lift is a later
  session.
- `Hook` schema. Hooks have been demoted to `output/hook_suggestions.json`
  in the extractor and are explicitly advisory; defining a typed `Hook`
  schema waits on the predicate-vocabulary spec.
- Sessionization rules. Currently a private helper inside the
  extractor; the live observer in the customization system will need
  the same rule, but that lift waits for the observer to exist.

See [ADR-0004](../docs/decisions/0004-behavioral-profile-typed-contract.md)
for the rationale on lifting the profile schema in particular.
