# 0002 — `uv` workspace layout

- **Date:** 2026-05-08
- **Status:** Accepted

## Context

[ADR 0001](0001-three-subsystem-split.md) splits CustomOS into three
pieces. We need a repository layout that:

- Lets the profile extractor and customization system evolve as
  independent applications with their own dependencies.
- Forces them to agree on the shared contracts in `customos-core` —
  ideally at import time, not at runtime.
- Avoids the operational cost of three separate repositories with a
  manually-published shared library.

## Decision

Use a [`uv` workspace](https://docs.astral.sh/uv/concepts/workspaces/)
with three member projects:

- `customos-core`
- `profile-extractor`
- `customization-system`

The workspace root has no application code; it only declares membership.
Each member has its own `pyproject.toml` and dependencies. They share
one lockfile and one `.venv`, and they import `customos-core` as a
normal Python package.

## Consequences

- Schema changes in `customos-core` show up immediately in both
  consumers, breaking them at import time. This is the desired forcing
  function — it makes drift a build failure, not a silent bug.
- Each subproject keeps its own dependency list, so the extractor's
  LLM SDKs don't bloat the customization runtime, and vice versa.
- One `uv sync` at the workspace root sets up everyone's environment
  in one shot.
- Slight setup overhead vs. a single flat project, but the contract
  is now explicit rather than implicit.
- If a subsystem ever needs to live in a separate repository (e.g., for
  release independence), the package boundary already exists.
