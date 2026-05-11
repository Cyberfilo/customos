# customization-system

Runtime-overlay macOS customizations driven by the CustomOS behavioral
profile. A single Python process loads `profile.json`, asks an LLM to pick
customizations from a fixed vocabulary at startup, applies them via PyObjC
+ AppKit + the Accessibility API, and holds them for its lifetime. On
`SIGINT` / `SIGTERM` (or normal exit) every applied customization is
reverted before the process dies. Process running = customizations active;
process killed = full revert.

This is **Layer 1**. A future **Layer 2** will add a live observer +
coordinator that adjusts customizations in response to live state. Layer 1
must work cleanly first.

## Architecture (Layer 1)

```
   profile.json ──┐
                  ▼
            select_plan() ──── LLM (Anthropic / OpenAI)
                  │              picks from VOCABULARY,
                  │              returns parameters,
                  ▼              rationale, confidence
            validated plan ─── jsonschema check on
                  │             each entry's parameters
                  ▼
            PlanRunner.apply_plan()
                  │
                  ▼
        ┌─────────┴─────────┐
        │       NSApp       │   single process,
        │   .run() (block)  │   main thread runs the
        │                   │   AppKit run loop until
        │  ┌─ executors ─┐  │   SIGINT / SIGTERM / atexit
        │  │ notch       │  │
        │  │ dock dim    │  │
        │  │ hotkey tap  │  │
        │  └─────────────┘  │
        └─────────┬─────────┘
                  ▼
           PlanRunner.revert_all()  (reverse-order, idempotent)
```

Every commitment that makes this design possible is in
[`docs/decisions/0005-customization-system-architecture.md`](../docs/decisions/0005-customization-system-architecture.md).
The non-negotiables in one line each:

- **Runtime overlays only.** Process exits, customizations vanish. No
  persistent installation. Crash = approximate revert (atexit + delegate).
- **Fixed vocabulary.** The LLM picks from a catalog whose entries each
  point at executor code that can both apply and revert. No invented
  customizations.
- **One-shot LLM at startup.** Layer 1 makes a single decision per
  process lifetime. Live, stateful adjustments belong to Layer 2 (future).
- **Trait-only profile consumption.** This subsystem reads the profile
  for stable behavioural traits ([ADR-0003](../docs/decisions/0003-traits-vs-state-separation.md));
  state is observed live by the customization-system itself, never read
  back from `profile.json`.

## The vocabulary (this session)

Three executors, exercising different parts of the architecture so the
foundation is real rather than hypothetical:

| id | tests architecturally | implementation |
|----|------------------------|----------------|
| [`notch_now_playing`](customization_system/executors/notch_now_playing.py) | long-running visual overlay above system UI | borderless NSWindow under the notch + `NSDistributedNotificationCenter` observers for Music.app / Spotify |
| [`dock_dim_unused`](customization_system/executors/dock_dim_unused.py) | spatial overlay over arbitrary system UI elements | walks Dock children via the AX API, opens one transparent NSWindow per stale icon |
| [`focus_pair_hotkey`](customization_system/executors/focus_pair_hotkey.py) | input interception + AX-driven action on other processes | session-level CGEventTap + AX `kAXPosition` / `kAXSize` setters |

Adding a fourth entry is a new vocabulary entry + a new
`CustomizationExecutor` subclass; nothing else changes. There is no
plugin system on purpose — generality comes from the catalog growing,
not from machinery.

## CLI

Three commands; only `run` mutates the system.

```bash
# Show the catalog
uv run customization-system vocabulary

# Pick a plan and print it as JSON, do not apply
uv run customization-system plan-preview [--profile PATH] [--max-output-tokens N] [--no-cache]

# Apply, hold for process lifetime, revert on Ctrl-C / SIGTERM / exit
uv run customization-system run        [--profile PATH] [--max-output-tokens N] [--no-cache]

# Inspect the local plan cache
uv run customization-system cache list

# Delete every cached plan
uv run customization-system cache clear [--yes]
```

Default `--profile` is `<workspace>/profile-extractor/output/profile.json`.

## Plan caching

The LLM selection is non-deterministic — gpt-5 returned 3, 2, 3, 2, 3
entries across five runs against the same profile during the Layer 1
prototype. To make startups reproducible and to avoid paying the 18–64s
LLM call on every restart, `run` and `plan-preview` cache the *validated*
plan to `cache/plans/<key>.json`, keyed by `sha256(profile JSON + the
plan-affecting slice of the vocabulary + provider + model)`. The cache is
local-only and gitignored. See
[ADR-0007](../docs/decisions/0007-plan-caching.md).

Cache invalidation is hash-based, never time-based: editing
`profile.json`, adding/removing a vocabulary entry, changing a
`parameters_schema`, or switching provider/model all produce a new key.
Use `--no-cache` to force a fresh LLM call (the result still overwrites
the cache entry). The three management commands above (`cache list`,
`cache clear`, plus the `--no-cache` flag) are the entire surface — no
selective invalidation, no time-based eviction.

## Permissions

Accessibility is required (System Settings → Privacy & Security →
Accessibility — add the Python interpreter that's running this process).
Without it, CGEventTap returns `NULL` and `AXUIElementCopyAttributeValue`
returns no children. We refuse to start in that state with a copy-pasteable
hint to the user; we never try to bypass.

Screen Recording and Input Monitoring are **not** required by Layer 1.

## Logging

Every run writes a JSONL file to `logs/runs/<ISO-timestamp>.jsonl` with
the LLM call, the validated plan, every apply, every revert. The
directory is gitignored. Stderr also receives a colorised stream at
INFO+ for live tailing.

## Out of scope this session

- Layer 2 (live observer + coordinator).
- Profile-refresh-on-change (rerun selection when `profile.json` updates).
- Vocabulary entries beyond the three above.
- Adoption of `customos-core`'s `BehavioralProfile` Pydantic model. The
  system ingests `profile.json` as a loose `dict` for now; switching to
  the typed contract is a small follow-up.
- Persistent config, launchd integration, fancy IPC, sub-processes.
