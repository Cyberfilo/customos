# CustomOS

CustomOS builds a longitudinal behavioral profile of a single macOS user from on-device usage data (Biome, knowledgeC, Spotlight, Safari, shell history, calendar, etc.) and uses that profile — combined with live system state — to drive personalized customizations of the macOS user experience.

Part research project, part personal tool, part portfolio piece.

## Status & scope

- **Type**: research project + personal tool + portfolio piece
- **Stage**: early-stage scaffolding. Extractor subsystem is the most developed; coordinator pending; shared core has schema in place
- **Persona**: a single macOS user — the one running the daemon — wanting to introspect their own usage and have the OS adapt to them
- **Not designed for**: multi-user, cloud-sync, or surveillance-of-others scenarios. The privacy posture below is non-negotiable.
- **Open to scale**: no by design — this is intentionally single-machine, single-user, local-only

## The three subsystems

```
                        +---------------------------+
                        |     customos-core         |
                        |   (shared contracts)      |
                        |  Event / Hook schema,     |
                        |  sessionization, IDs      |
                        +-------------+-------------+
                                      ^
                            imports   |   imports
                  +-------------------+-------------------+
                  |                                       |
   +--------------+--------------+         +--------------+--------------+
   |     profile-extractor       |         |    customization-system     |
   |  (batch, periodic, LLM)     | profile |   (live observer +          |
   |                             | ------> |    coordinator)             |
   |  many macOS sources         |  .json  |                             |
   |     ->  unified events      |  +hooks |  traits + live state        |
   |     ->  traits + hooks      |         |     ->  adaptations         |
   +-----------------------------+         +-----------------------------+
                                                       |
                                                       v
                                          Hammerspoon / Karabiner /
                                            yabai / Accessibility
                                              (routes pending)
```

1. **`profile-extractor/`** — periodic batch pipeline. Reads many macOS data sources, normalizes everything into a unified event store, and produces `profile.json` describing stable behavioral *traits* and a list of `customization_hooks`.
2. **`customization-system/`** — continuously running. A live observer tracks current state (foreground app, session, idle, recent activity), and a coordinator fuses traits + state and dispatches adaptations to the appropriate macOS customization route.
3. **`customos-core/`** — Pydantic schemas and shared logic used by both of the above.

## Privacy posture

This system collects detailed behavioral data about **a single user** — the person who installs and runs it on their own machine. The design assumes:

- All processing is local. No network calls. No telemetry. No cloud sync.
- The user is the data subject and the data controller. They can `SELECT * FROM events` at any time and see exactly what's recorded.
- The user can delete the profile at any time (`rm -rf data/`).
- Source data (Biome / knowledgeC / Spotlight / Safari history) stays in its system locations until you opt in to extracting it.

**Do not run this on a machine that isn't yours, or on a machine used by others.** It is built for personal introspection, not for surveillance of other people.

## Status

Early-stage. The extractor subsystem is the most developed; the customization system is scaffolded but not yet routing to Hammerspoon/yabai/etc.; the shared core has its schema in place. Treat anything not covered by an ADR in `docs/decisions/` as subject to change.

## Quickstart

```bash
git clone https://github.com/Cyberfilo/customos.git
cd customos

uv sync                                  # installs all three subsystems
uv run python -m customos.extractor      # initial extraction (will prompt for permissions)
uv run uvicorn customos.api:app --reload # local API for inspecting your profile
# Visit http://localhost:8000/docs
```

## Pointers

- `docs/README.md` — documentation entry point
- `docs/architecture.md` — current architecture and what's still TBD
- `docs/interface.md` — contract between subsystems
- `docs/decisions/` — ADRs
- `customos-core/README.md`
- `profile-extractor/README.md`
- `customization-system/README.md`

