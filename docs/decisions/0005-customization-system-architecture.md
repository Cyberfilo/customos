# 0005 — customization-system architecture (Layer 1)

- **Date:** 2026-05-11
- **Status:** Accepted

## Context

The customization-system is the live half of CustomOS
([ADR-0001](0001-three-subsystem-split.md)). It consumes a behavioural
profile and changes the user's macOS environment in response. Before any
piece of it is built, four shape decisions need to be locked in, because
each one rules out large families of designs that look reasonable in
isolation but combine badly:

1. **What is the unit of customization?** A persistent change to user
   defaults / dock plist / launchd? A runtime overlay that vanishes
   with the process? A scriptable rule that writes back to the system?
2. **Where do customization choices come from?** Hand-coded heuristics
   over the profile? An LLM that maps profile → freeform actions? An
   LLM that picks from a fixed catalog?
3. **When does the LLM decide?** Once at startup? Continuously, in
   response to live state? On every profile refresh?
4. **How do live signals enter the loop?** Are they part of the same
   selection mechanism as profile-derived choices, or a separate
   layer on top?

There is no precedent in the user's environment for any of these. The
risk of getting (1)+(2) wrong is the largest: a system that "modifies"
macOS in opaque, persistent ways becomes a debugging nightmare and an
operational liability. The risk of getting (3)+(4) wrong is structural:
conflating live state with the profile recreates the trait/state
conflation that [ADR-0003](0003-traits-vs-state-separation.md) rejected.

## Decision

The customization-system is built in two **layers**, with this session
delivering only Layer 1.

### Layer 1 — durable customizations from the profile

1. **Customizations are runtime overlays.** Process up = customizations
   active. Process killed = full revert. Crash = approximate revert
   (atexit + `applicationShouldTerminate:` delegate; SIGKILL is the
   exception we accept). No persistent installation, no writes to
   `defaults`, no launchd units, no Dock plist edits. The system is a
   single Python process whose lifetime is the customization's lifetime.

2. **The vocabulary is fixed by code.** A catalog of `VocabularyEntry`
   structs lives in `vocabulary.py`. Each entry pairs a description and
   parameter schema with a `CustomizationExecutor` subclass that knows
   how to both `apply` and `revert`. The LLM picks from this catalog
   only; it cannot return entries the executor layer can't realize.

3. **The LLM call is one-shot at startup.** `select_plan(profile,
   vocabulary, llm)` is called once, returns a validated plan
   (jsonschema-checked parameters; unknown ids dropped), and never runs
   again in Layer 1. The selection runs in a subprocess at human
   timescales (one to two minutes for gpt-5 reasoning) — that's
   acceptable because it happens once.

4. **The notch widget is built from scratch.** Apple's MediaRemote
   framework was restricted in macOS 14.4; third-party processes can't
   read now-playing data via that private API any more. The widget is
   instead a borderless `NSWindow` driven by
   `NSDistributedNotificationCenter` posts from Music.app and Spotify.
   This trades coverage (only those two apps) for the public, durable
   API surface.

### Layer 2 — live, state-driven adjustments (future)

Layer 2 adds a live observer that tracks current state (foreground app,
session, idle, recent activity) and a coordinator that fuses traits +
state into momentary adaptations on top of Layer 1. It is **not built
in this session.** Layer 1 is shaped to make Layer 2 easy to add
later: the executor / runner / vocabulary boundary stays the same, and
Layer 2 introduces a separate decision loop rather than mutating Layer
1's plan.

### Profile-refresh handling

Re-running selection when `profile.json` changes is recognised as a
future need (the profile is regenerated periodically; a long-running
customization-system process would silently grow stale). The
architecture leaves room for it — re-running `select_plan` against the
new profile and diffing the resulting plans against the live applied
set is straightforward — but it is **not** built this session. Don't
rely on it; restart the process for now.

## Consequences

- **Crashes are recoverable.** The worst-case state after any failure
  is the macOS environment as it was before the process started.
  Concretely: a panicked notch window, a stuck overlay, a half-applied
  hotkey — all evaporate when the process dies. This is a deliberate
  safety property, not a bug ("crash = revert is approximate" is the
  shorthand).
- **The LLM is sandboxed by the catalog.** It can't propose
  customizations the executor layer doesn't implement, and can't
  parameterise an entry in shapes the schema doesn't allow.
  Misalignment between LLM imagination and what's actually realisable
  becomes impossible by construction.
- **Per-executor failures don't take down the rest.** `PlanRunner`
  catches per-entry exceptions during apply and during revert; one
  broken executor shouldn't cause two working ones to skip revert.
- **Layer 1 produces no live behaviour.** What's running between
  startup and shutdown is just whatever the executors set up at apply
  time. If the user's situation changes mid-session (focus shift,
  becoming idle, opening a different app), Layer 1 will not react.
  That's the gap Layer 2 fills.
- **Vocabulary growth is the extension point.** Adding capability is
  a new vocabulary entry + executor subclass; no plumbing to thread,
  no plugin system to register against, no IPC. Three executors today
  exercise the three architectural shapes (long-running visual
  overlay; spatial overlay over system UI; input interception +
  AX-driven action), so a fourth entry of any of these shapes is
  cheap.
- **Adoption of `customos-core.BehavioralProfile` is deferred.**
  Layer 1 reads `profile.json` as a loose `dict` to keep this session
  decoupled from the parallel customos-core work. Switching to the
  typed contract from
  [ADR-0004](0004-behavioral-profile-typed-contract.md) is a small,
  isolated change once both sides settle.
- **The decision to build the notch widget from scratch (rather than
  via MediaRemote.framework or a third-party menu-bar SDK) limits
  source coverage** to apps that post the documented distributed
  notifications. That's Apple Music and Spotify today. Adding apps
  means writing per-app integrations (e.g. Apple Events to other
  players, MPRemoteCommandCenter, AVRoutePickerView for system-level
  audio) — not pulling in the private framework. The trade is
  deliberate: durable, reviewable code over a fragile shortcut.
