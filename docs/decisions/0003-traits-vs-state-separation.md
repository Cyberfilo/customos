# 0003 — Traits vs. state separation

- **Date:** 2026-05-08
- **Status:** Accepted

## Context

Both the profile and the live observer carry "facts about the user" —
but those facts have very different semantics:

- **Traits** are stable behavioral patterns: "this user typically does
  deep-focus work between 9am and 11am", "this user uses Slack as a
  primary communication channel". They change slowly (days/weeks) and
  are derived from longitudinal data.
- **State** is right-now-ness: "Slack is foreground", "user has been
  idle for 4 minutes", "last keystroke was 2 seconds ago". It changes
  constantly, must be observed live, and is meaningless once stale.

Conflating these into a single schema leads to a profile that's either
stale on the live side or noisy on the trait side. It also makes the
update cadence and persistence contract impossible to reason about.

## Decision

The profile produced by the extractor describes only **traits**. State
is owned exclusively by the customization system's live observer.

Customization hooks express the connection between the two: a hook is a
trait-derived rule with **state preconditions** that the coordinator
evaluates live.

## Consequences

- The profile schema is trait-only. No "current app", no "last seen at",
  no live counters.
- The live observer's state lives in the customization system's
  process and is never written back into the profile.
- Hooks become the API between the two systems: the profile produces
  them, the coordinator interprets them. Their schema lives in
  `customos-core` (per [ADR 0002](0002-uv-workspace-layout.md)).
- Any new piece of information has to be classified as trait or state
  before it has a home. This is the desired forcing function.
