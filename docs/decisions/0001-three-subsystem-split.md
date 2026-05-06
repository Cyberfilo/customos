# 0001 — Three-subsystem split

- **Date:** 2026-05-08
- **Status:** Accepted

## Context

CustomOS has two fundamentally different jobs to do:

- Build a *profile* of the user's stable behavioral patterns from
  longitudinal usage data. This is heavy, periodic, LLM-augmented, and
  doesn't care about latency.
- Adapt the macOS environment to the user *right now*. This requires
  continuous observation of live state (foreground app, session, idle,
  recent activity) and low-latency reaction.

These two jobs have different update cadences, different latency
requirements, different failure modes, and different persistence
semantics. Mixing them in one process couples unrelated risks: a slow
LLM call in the profiler shouldn't be able to delay a UI adaptation,
and a crash in a Hammerspoon binding shouldn't lose hours of event
ingestion.

They also share something important: the schema of events,
sessionization rules, identifier normalization, and the hook contract.
If those drift between the two sides, the system silently breaks.

## Decision

Split CustomOS into three pieces:

1. **`profile-extractor`** — batch, periodic, produces `profile.json`
   with traits + customization hooks.
2. **`customization-system`** — continuously running, live observer
   plus coordinator, consumes `profile.json` and current state.
3. **`customos-core`** — shared contracts package (Pydantic models +
   shared logic) imported by both.

## Consequences

- Three deployable units with one explicit contract between them
  (`customos-core`).
- Sessionization logic must be shared code, not duplicated. This is
  enforced by living in `customos-core`.
- The two top-level subsystems can fail independently without taking
  the other down.
- The main ongoing risk is **drift**: trait semantics changing in the
  extractor without the customization system being updated. The
  workspace layout in
  [0002](0002-uv-workspace-layout.md) is the mitigation —
  schema changes break both sides at import time.
