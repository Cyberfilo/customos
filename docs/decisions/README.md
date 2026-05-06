# Architecture Decision Records

This folder holds Architecture Decision Records (ADRs) for CustomOS.
An ADR captures a single architectural decision: what was decided, why,
and what we now have to live with.

ADRs are **append-only**. A decision that is replaced by a later one is
marked `Superseded by NNNN`, but the original file stays in place. The
new ADR opens by referencing the one it replaces.

## Format

```
# NNNN — Title

- **Date:** YYYY-MM-DD
- **Status:** Proposed | Accepted | Superseded by NNNN

## Context
What is the problem? What forces are at play?

## Decision
What did we choose to do?

## Consequences
What does this commit us to? What gets easier? What gets harder?
What new risks does it introduce?
```

## Numbering

Files are named `NNNN-short-slug.md` with a zero-padded four-digit
number. New ADRs take the next available number, regardless of which
ADRs are still active.

## Current ADRs

- [0001 — Three-subsystem split](0001-three-subsystem-split.md) — Accepted
- [0002 — `uv` workspace layout](0002-uv-workspace-layout.md) — Accepted
- [0003 — Traits vs. state separation](0003-traits-vs-state-separation.md) — Accepted
- [0004 — BehavioralProfile as a typed contract in customos-core](0004-behavioral-profile-typed-contract.md) — Accepted
- [0005 — customization-system architecture (Layer 1)](0005-customization-system-architecture.md) — Accepted
- [0006 — Identifier normalization in customos-core](0006-identifier-normalization-in-customos-core.md) — Accepted
- [0007 — Plan caching in customization-system](0007-plan-caching.md) — Accepted
