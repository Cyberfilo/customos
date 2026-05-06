# 0006 — Identifier normalization in customos-core

- **Date:** 2026-05-11
- **Status:** Accepted

## Context

[ADR-0004](0004-behavioral-profile-typed-contract.md) lifted the
`BehavioralProfile` schema into `customos-core`, giving the extractor and
the customization-system a shared typed contract. The customization-system
prototype session ([B3 deliverable / ADR-0005](0005-customization-system-architecture.md))
then ran end-to-end against the real `profile.json` and produced a
silent, visually obvious bug: the `dock_dim_unused` executor dimmed
*Safari, Terminal, Music, WhatsApp, Photos* — the user's five most-used
apps — when those exact apps appeared at the top of `profile.apps[*]`.

The cause was identifier drift across the seam:

- `profile-extractor/macprofile/normalize/identity.py::normalize_bundle_id`
  lowercases bundle IDs before they're written into `profile.json`. So
  `profile.apps[].bundle` carries `com.apple.safari`, `com.apple.terminal`,
  …
- The customization-system reads bundle IDs from macOS surfaces:
  `NSBundle.bundleIdentifier()` (Dock items via `kAXURLAttribute`),
  `NSWorkspace.runningApplications()`, `NSRunningApplication`. Those
  return the canonical Info.plist form: `com.apple.Safari`,
  `com.apple.Terminal`, `net.whatsapp.WhatsApp`.
- The executor compared with case-sensitive `==`. Top apps fell through
  the staleness check as "never seen", and the overlay went on top of
  them.

The lesson is structural rather than situational: a typed `BehavioralProfile`
schema catches *shape* drift (renamed fields, missing fields, wrong
types), but it does nothing about *value* drift — two sides of the seam
producing the same logical identifier in different lexical forms. As the
customization-system grows more vocabulary entries, more cross-source
identifier comparisons will exist, and every one of them is a place for
this bug class to recur.

The fix has to live somewhere both sides import. `customos-core` is
already that place for types; it should be that place for normalization
too.

## Decision

`customos-core` owns identifier normalization helpers, not just the
profile schema. A new module, `customos_core.identity`, holds three
pure helpers lifted from the extractor:

- `normalize_bundle_id(b: str) -> str` — moved verbatim.
- `canonicalize_url(url: str) -> tuple[str, str]` — moved verbatim.
- `hash_contact(identifier: str, *, salt: str) -> str` — moved with one
  minimal generalisation: the salt was previously read inside the
  function from `macprofile.settings.get_settings()`. The lift promotes
  it to a keyword argument so the helper has no extractor dependency.
  The extractor's old zero-arg `hash_contact(identifier)` survives as a
  thin wrapper that loads the settings-stored salt and delegates.

The extractor's `macprofile/normalize/identity.py` becomes a 25-line
shim that re-exports the lifted helpers and provides the salt-loading
wrapper. Existing call sites in
`extractors/{biome,browsers,knowledgec,mail,messages}.py` keep working
without changes.

The customization-system gains `customos-core` as a workspace
dependency (`[tool.uv.sources] customos-core = { workspace = true }`)
and routes every cross-source identifier comparison through
`normalize_bundle_id`: `dock_dim_unused`'s staleness lookup table,
`focus_pair_hotkey`'s `_pid_for_bundle`, `plan.py`'s `_is_ios_only`
filter. Both sides of the comparison are normalized; canonical-case
OS-derived identifiers and lowercased profile identifiers now collide
on the same key.

The contract for any *future* cross-subsystem consumer of identifiers
is now explicit: **route both sides through the helpers in
`customos_core.identity`** before any comparison, lookup, or set
operation. This is non-negotiable in the same way that
`BehavioralProfile.model_validate()` on load is non-negotiable.

## Consequences

- The dock-dimming bug is fixed structurally rather than locally. The
  customization-system test suite includes a regression case
  (`tests/test_identity.py::test_dock_canonical_case_matches_profile_lowercase`)
  that pins the canonical/lowercase equivalence.
- `customos-core` gains zero runtime dependencies (the helpers are
  stdlib-only) and gains pytest as a dev-only dependency
  (`[dependency-groups] dev`).
- The extractor's behaviour is unchanged. `uv run macprofile preflight`
  and `uv run macprofile analyze` were re-run after the shim landed and
  passed with no diff in `output/analyses.json`. The extractor's
  warehouse content, hashes, and downstream `profile.json` shape are
  byte-for-byte unaffected.
- `hash_contact`'s call signature changed in `customos_core` but not in
  the extractor. Any new caller (in the customization-system, in tests,
  in `customos-core` itself) MUST pass `salt=` explicitly, which keeps
  the helper genuinely stateless and makes per-install salt handling an
  explicit caller responsibility rather than a hidden import-time read.
- Future identifier types (account UUIDs, contact-handle classes,
  normalized file paths) join `customos_core.identity` rather than
  growing in either subsystem.
- The HANDOFF.md "extractor-internal helpers" footprint shrinks; the
  customos-core surface grows. This trade was already the directional
  goal in [ADR-0004](0004-behavioral-profile-typed-contract.md);
  ADR-0006 just extends it from types to normalisation.
- Risk: a future contributor adds a new vocabulary entry that compares
  identifiers from a *new* OS surface (e.g. `LSCopyApplicationURLsForBundleIdentifier`,
  `NSPasteboard` types) and forgets to normalize. The mitigation is the
  ADR-as-code-review-anchor and the regression test, not a runtime
  enforcement mechanism — there's no easy way to enforce "use this
  helper" at the type system level.

Related: [ADR-0001](0001-three-subsystem-split.md),
[ADR-0002](0002-uv-workspace-layout.md),
[ADR-0004](0004-behavioral-profile-typed-contract.md),
[ADR-0005](0005-customization-system-architecture.md).
