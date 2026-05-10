# profile-extractor

Batch, periodic pipeline that reads many on-device macOS data sources
(Biome SEGB streams, knowledgeC, Spotlight, Safari/Chrome/Brave history,
zsh history, Calendar, Notes, Photos, Messages, Mail), normalizes
everything into a unified DuckDB event store, runs LLM-augmented
analysis on the aggregates, and produces a `profile.json` describing
stable behavioral *traits* and a list of `customization_hooks`.
Downstream consumers (the customization-system) read from
`output/profile.json`. All raw data stays local; only aggregate
statistics ever reach an LLM API.

The package name is still `macprofile` (Python-side); the workspace
member name is `profile-extractor` per the CustomOS naming convention.
Renaming the package is deferred to a later session.

See [`HANDOFF.md`](HANDOFF.md) for the current state of the pipeline,
the schemas in use, the extractor inventory, known issues (sfl2 stub,
empty reminders stores, iPhone Biome contamination, ungrounded hook
predicate vocabulary), and the design decisions taken during the
build. Read that before changing anything here.

For how this subsystem fits with `customos-core/` and
`customization-system/`, see [`../README.md`](../README.md) and
[`../docs/architecture.md`](../docs/architecture.md).

## Quick start

```bash
# from the workspace root
uv sync

# from this directory
uv run macprofile preflight       # Full Disk Access check
uv run macprofile extract --all   # run every registered extractor
uv run macprofile analyze         # SQL aggregates -> output/analyses.json
uv run macprofile profile         # LLM analysis -> output/profile.{json,md}
uv run macprofile serve           # FastAPI query layer at 127.0.0.1:8766
uv run macprofile purge --yes     # wipe data/ and output/
```

## Privacy posture

- Extraction is read-only; SQLite databases are copied to
  `data/raw/<source>/<YYYY-MM-DD>/` before being queried.
- `data/` and `output/` are gitignored.
- `[privacy].deep_content_analysis = false` (default) keeps note titles,
  mail subjects, and message bodies out of LLM payloads.
- Contact identifiers are SHA-256 hashed with a per-install salt
  bootstrapped on first run.
- `macprofile purge --yes` removes the warehouse, the raw snapshots,
  and the produced outputs.
