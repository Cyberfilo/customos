# Interface

The contract between the profile extractor and the customization system,
expressed through `customos-core`.

The `BehavioralProfile` and `Hook` sections below now have authoritative
homes; the other sections remain TBD.

## BehavioralProfile schema

Defined in [`customos_core.profile`](../customos-core/customos_core/profile.py).
The canonical Pydantic model is `customos_core.BehavioralProfile`; its
component models (`Coverage`, `Rhythms`, `AppAffinity`, `Sequence`,
`WorkMode`, `Project`, `Browsing`, `Communication`, `Contact`,
`Idiosyncrasy`, `NegativeSignal`, `Privacy`) and the shared markers
(`Stability`, `Scope`, `Durability`, `ProjectPhase`, `ContactClass`,
`NegativeSignalKind`) are exported from the same module. Do not duplicate
the field list here — read the source. Rationale and design decisions are
captured in [ADR-0004](decisions/0004-behavioral-profile-typed-contract.md).

`profile-extractor` produces a `BehavioralProfile` via
`.model_dump_json()` into `output/profile.json`. The (future)
`customization-system` will validate the same file with
`BehavioralProfile.model_validate(json.loads(...))` on load. Schema
version is pinned via `schema_version: Literal["1.0.0"]`; bumping it is
a two-side coordination point.

## Hook schema

Hooks have been demoted to `output/hook_suggestions.json` and are
explicitly **advisory**: the LLM-generated `trigger` strings reference
predicates that no current CustomOS subsystem can evaluate. A typed
`Hook` schema in `customos-core` waits on the predicate-vocabulary spec
landing. Until then, the file's `_meta` block is the contract: see
`hook_suggestions.json`'s `_meta` warning string.

## Event schema

TBD — to be defined when the extractor's `Event` model
(`profile-extractor/macprofile/schema.py`) is lifted into
`customos-core`. The lift waits on the customization-system needing it
to replay events against trait logic. Currently the model lives in the
extractor only.

## Sessionization rules

TBD — to be defined when the live observer in the customization-system
needs them. Currently a private helper inside
`profile-extractor/macprofile/analyze/sessions.py` (idle-gap walker, 5
minute default).

## Identifier normalization

Defined in [`customos_core.identity`](../customos-core/customos_core/identity.py).
Three helpers, all pure (no I/O, no state, no warehouse access):

- `normalize_bundle_id(b)` — canonical lowercase form of a macOS
  bundle ID; idempotent; never lossy on inputs that don't match the
  reverse-DNS shape.
- `canonicalize_url(url)` → `(canonical_url, domain)` — strips query
  + fragment, lowercases scheme and host, defaults path to `/`.
- `hash_contact(identifier, *, salt)` — `c_<16hex>` SHA-256 hash of
  the salt + normalized handle. Salt is parameterized; callers that
  keep a per-install salt (e.g. profile-extractor's
  `settings.privacy.contact_hash_salt`) wrap with their own loader.

`profile-extractor/macprofile/normalize/identity.py` re-exports all
three; the extractor's existing `hash_contact()` zero-arg signature is
preserved as a thin wrapper that injects the settings-loaded salt.
Rationale lives in
[ADR-0006](decisions/0006-identifier-normalization-in-customos-core.md).
The contract is: any consumer comparing identifiers across subsystem
boundaries (OS surfaces ↔ profile data) MUST route both sides through
these helpers.

## Profile-to-coordinator query API

TBD — the customization-system reads `profile.json` and validates it
against `BehavioralProfile`; beyond that, the query surface (e.g. helper
methods on the model, indexed lookups) is undefined until the
customization-system's first feature lands.
