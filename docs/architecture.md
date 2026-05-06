# Architecture

This document captures the current architecture of CustomOS as we
understand it today. Where pieces are not yet decided, we mark them
**TBD** rather than guess.

## The three-subsystem split

CustomOS is split into three pieces, each with a distinct cadence and
failure mode:

1. **`profile-extractor`** — batch, periodic, LLM-augmented. Reads many
   macOS data sources (Biome, knowledgeC, Spotlight, Safari, shell
   history, calendar, etc.), normalizes everything into a unified event
   store, and produces a `profile.json` describing stable behavioral
   *traits* and a list of `customization_hooks`. High latency, high
   throughput, runs occasionally.
2. **`customization-system`** — continuously running. A live observer
   tracks current state (foreground app, session, idle, recent
   activity), and a coordinator fuses traits + state and dispatches
   adaptations to the appropriate macOS customization route. Low
   latency, persistent.
3. **`customos-core`** — the shared contracts package. Pydantic models
   and shared logic (Event schema, sessionization rules, Hook schema,
   identifier normalization). Imported by both of the above; this is
   what binds them.

The split is recorded in [`decisions/0001-three-subsystem-split.md`](decisions/0001-three-subsystem-split.md).
The traits-vs-state separation that follows from it is recorded in
[`decisions/0003-traits-vs-state-separation.md`](decisions/0003-traits-vs-state-separation.md).

## What's not yet decided

The following pieces are explicitly open. Do not assume defaults; check
back here (or the ADRs) before designing around any of them.

### Customization routes — TBD

Research has been done on macOS customization mechanisms (Hammerspoon,
Karabiner, yabai, Accessibility API, and others). Choices are not yet
finalized. The coordinator will eventually dispatch to one or more of
these, but the decision criteria — and which routes are in scope at
all — are pending. Raw research material lives in `docs/research/`.

### Contents of `customos-core` — TBD

The exact set of types and helpers shared between the two subsystems
will be derived from the extractor's schema (`profile-extractor/macprofile/`).
Until that lift happens, `customos-core` is an empty placeholder.

### Coordinator decision-making logic — TBD

How the coordinator fuses traits with live state to choose adaptations
is undefined. This includes hook precondition evaluation, conflict
resolution between competing hooks, debouncing, and rollback. Will be
designed when the customization system's first route lands.
