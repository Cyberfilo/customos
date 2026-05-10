# macprofile — handoff

This document captures the state of the profile-extractor as it sits today,
just before being migrated from `~/projects/macprofile/` into
`~/CustomOS/profile-extractor/` as a uv workspace member.

After Phase 2 of that migration this file lives at
`~/CustomOS/profile-extractor/HANDOFF.md`.

## Current state

End-to-end pipeline runs on macOS Tahoe 26.1, Apple Silicon, with Full Disk
Access granted to the terminal and `uv`'s python. Last full run produced
**357,976 events from 33 distinct sources** in `data/events.duckdb` (≈45 MB),
covering **2,629 active days** (oldest signal a 2006 photo, newest from
moments before the run). All 14 registered extractors executed; 12 produced
rows (Spotlight, Safari/Chrome/Brave history, Safari last-session,
knowledgeC, shell history, calendar, notes, biome SEGB streams, photos,
messages, mail). `sfl2` and `reminders` produced 0 rows by design (see Known
issues). A unified-log extractor was specced but never registered — the entry
exists in the CLI registry only as a future hook.

Analyzers ran from DuckDB and produced `output/analyses.json` (≈70 KB). The
LLM analysis layer ran against OpenAI `gpt-5` (Responses API, structured
outputs) using the user's `OPENAI_API_KEY`; the Anthropic path is implemented
but untested in this environment because `ANTHROPIC_API_KEY` was not set.
The first profile run truncated several LLM outputs at the 4000-token cap
and dropped them; a second run with `max_output_tokens = 16000` produced a
complete `output/profile.json` (≈97 KB) and `output/profile.md` (≈16 KB)
with rhythm description, work modes, top workflows, inferred projects,
browsing classification, idiosyncrasies, and 10 customization hooks.

The FastAPI query layer was smoke-tested on port 8766 (default 8765 was
already in use by the user's own Ripasso IGCSE study app — same machine,
unrelated). `/health`, `/events/by-source`, `/apps/top`, `/query`, and
`/profile` all returned expected payloads.

A precise summary of what came out of the run (top workflows, hooks, raw
domain/app counts) was delivered conversationally at the end of the build
session. Numbers are reproducible from `output/profile.json` and the
warehouse.

## Where things live

```
macprofile/                     # project root (~/projects/macprofile/)
├── pyproject.toml              # deps, package name "macprofile", hatch build
├── config.toml                 # paths, privacy, extract, llm sections
├── README.md                   # short usage + privacy notes
├── HANDOFF.md                  # this file
├── data/
│   ├── raw/<source>/<YYYY-MM-DD>/...   # snapshots of source DBs (gitignored)
│   ├── events.duckdb           # ≈45 MB unified event warehouse
│   └── snapshots/              # currently empty
├── output/
│   ├── analyses.json           # SQL aggregates dump from analyze.pipeline
│   ├── profile.json            # final structured profile (LLM-augmented)
│   └── profile.md              # markdown narrative rendering of profile.json
├── tests/                      # empty
└── macprofile/                 # the python package
    ├── __init__.py
    ├── schema.py               # Event Pydantic model + Category/TargetKind literals
    ├── settings.py             # config.toml loader, Paths/Privacy/ExtractCfg/LLMCfg
    ├── preflight.py            # FDA probe of protected paths + instructions
    ├── extractors/
    │   ├── base.py             # Extractor ABC, apple_to_dt, chrome_to_dt, safe_copy, emit, stable_hash
    │   ├── spotlight.py        # mdfind + mdls -plist for kMDItemUseCount/UsedDates
    │   ├── browsers.py         # Safari (History.db + LastSession + bookmarks) + Chrome + Brave
    │   ├── knowledgec.py       # ZOBJECT streams: app/web/notification/screentime/device
    │   ├── sfl2.py             # NSKeyedArchiver recents — currently no-op (see Known issues)
    │   ├── shell_history.py    # zsh extended-history parser
    │   ├── calendar.py         # Calendar.sqlitedb in group container, REAL-typed dates
    │   ├── notes.py            # ZICCLOUDSYNCINGOBJECT, Z_ENT=ICNote, COALESCE'd date columns
    │   ├── reminders.py        # ZREMCDREMINDER scan — local stores empty on this Mac
    │   ├── biome.py            # SEGB streams, byte-scan + bbpb decode hybrid
    │   ├── photos.py           # ZASSET/ZGENERICASSET, lat/lon quantized to ~1km
    │   ├── messages.py         # chat.db, contacts hashed, body lengths only by default
    │   └── mail.py             # V*/MailData/Envelope Index, schema-sniffed columns
    ├── normalize/
    │   ├── identity.py         # B4 shim — re-exports from customos_core.identity (ADR-0006); wraps hash_contact() to inject the per-install salt from settings
    │   └── load.py             # DuckDB Warehouse, schema DDL, bulk insert with raw_hash dedup
    ├── analyze/
    │   ├── rhythms.py          # hourly/weekday/hour-by-weekday histograms, coverage()
    │   ├── sessions.py         # 5-minute idle-gap session bucketing
    │   ├── workflows.py        # collapse-duplicate sequence walk + n-gram counter
    │   ├── cohabitation.py     # 30-min bucketed app-pair co-occurrence
    │   ├── files.py            # top files, directory hotspots by path-prefix depth
    │   ├── communication.py    # contact graph, domain frequency, app affinity
    │   ├── llm.py              # provider abstraction + 6 structured-output tasks
    │   └── pipeline.py         # run_all() — assembles analyses.json
    ├── profile/
    │   └── build.py            # build_profile() + render_markdown(); writes profile.{json,md}
    └── app/
        ├── cli.py              # typer entry: preflight/extract/status/analyze/profile/serve/purge
        └── api.py              # FastAPI: /health, /events/*, /apps/top, /files/hotspots, /rhythms/*, /query, /profile, /profile.md
```

## Schemas in use

The schemas below are quoted verbatim from the codebase. They are the only
typed contracts the system has today; all other shapes (analyses.json,
profile.json) are loose dicts. Lifting these into `customos-core/` is a
later-session task.

### `macprofile/schema.py`

```python
TargetKind = Literal["app", "url", "file", "contact", "event", "device", "topic", "other"]
Category = Literal[
    "app_focus",
    "app_launch",
    "app_intent",
    "app_activity",
    "app_usage",
    "file_access",
    "file_recent",
    "web_visit",
    "tab_state",
    "bookmark",
    "shell_command",
    "calendar_event",
    "note",
    "reminder",
    "photo",
    "message_sent",
    "message_received",
    "mail_seen",
    "notification",
    "media_play",
    "device_state",
    "screen_time",
    "user_focus",
    "system_log",
]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(default_factory=lambda: str(uuid4()))
    ts: datetime
    ts_local: datetime
    source: str
    category: Category
    actor: str = "user"
    target: str
    target_kind: TargetKind = "other"
    duration_sec: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_hash: str
```

### `macprofile/settings.py`

```python
class Paths(BaseModel):
    data_root: Path
    raw_dir: Path
    db_path: Path
    output_dir: Path

class Privacy(BaseModel):
    deep_content_analysis: bool = False
    contact_hash_salt: str = ""

class ExtractCfg(BaseModel):
    lookback_days: int = 365
    include_unified_log: bool = False
    include_photos_thumbnails: bool = False

class LLMCfg(BaseModel):
    preferred: list[str] = ["anthropic", "openai"]
    anthropic_model: str = "claude-sonnet-4-5"
    openai_model: str = "gpt-5"
    max_output_tokens: int = 4000

class Settings(BaseModel):
    paths: Paths
    privacy: Privacy
    extract: ExtractCfg
    llm: LLMCfg
```

### `macprofile/analyze/llm.py` — Pydantic models

```python
class WorkflowLabel(BaseModel):
    sequence: list[str]
    frequency: int
    label: str
    automation_candidate: bool
    confidence: float
    rationale: str

class WorkMode(BaseModel):
    name: str
    apps: list[str]
    description: str

class RhythmDescription(BaseModel):
    workday_window: str
    leisure_window: str
    notable_quirks: list[str]
    summary: str

class InferredProject(BaseModel):
    name: str
    paths: list[str]
    last_active: str | None = None
    phase: str
    rationale: str

class BrowsingProfile(BaseModel):
    style: str
    research_share: float
    leisure_share: float
    reference_share: float
    tab_hoarding_score: float
    notable_domains_classification: list[dict[str, Any]]

class Hook(BaseModel):
    trigger: str
    action: str
    rationale: str
    confidence: float

class IdiosyncrasyOutput(BaseModel):
    quirks: list[str]
    hooks: list[Hook]
```

### `macprofile/analyze/llm.py` — JSON schemas sent to the LLM

Each task has its own inline JSON schema passed via `text.format = {type:
"json_schema", strict: false, schema: ...}` (OpenAI Responses API) or as a
prompt prefix (Anthropic Messages API). The Pydantic models above are the
post-validation shapes; the schemas below are what the LLM sees. They live
inline in `label_workflows`, `label_work_modes`, `describe_rhythm`,
`infer_projects`, `describe_browsing`, `find_quirks_and_hooks`. See those
functions for verbatim JSON. They mirror the Pydantic models 1:1 with one
exception: `IdiosyncrasyOutput.hooks` is the `Hook` shape but the schema
calls them `hooks`, not `customization_hooks` (renamed only when written
into `profile.json`).

### `profile.json` — typed contract in `customos_core.profile`

As of session B3, `profile.json` validates against `customos_core.BehavioralProfile`
(Pydantic v2, schema_version `1.0.0`). The model and its components live at
`~/CustomOS/customos-core/customos_core/profile.py`. See
[ADR-0004](../docs/decisions/0004-behavioral-profile-typed-contract.md) for the
rationale. Top-level fields: `schema_version, generated_at, coverage, rhythms,
app_affinities, sequences, work_modes, projects, browsing, communication,
idiosyncrasies, negative_signals, privacy`.

## Configuration surface

Single `config.toml` at the project root, parsed by `settings.get_settings()`.
Defaults (also defaults in `Settings` Pydantic models):

```
[paths]
data_root  = "data"
raw_dir    = "data/raw"
db_path    = "data/events.duckdb"
output_dir = "output"

[privacy]
deep_content_analysis = false           # gate for note titles, mail subjects, message bodies
contact_hash_salt     = ""              # auto-bootstrapped on first run via _bootstrap_salt()

[extract]
lookback_days              = 365
include_unified_log        = false
include_photos_thumbnails  = false

[llm]
preferred         = ["anthropic", "openai"]
anthropic_model   = "claude-sonnet-4-5"
openai_model      = "gpt-5"
max_output_tokens = 4000                # bumped to 16000 in the live config; default still 4000
```

Environment variables consulted:

- `ANTHROPIC_API_KEY` — used by `anthropic.Anthropic()` if `preferred[0]=="anthropic"`.
- `OPENAI_API_KEY`    — used by `openai.OpenAI()` if Anthropic is missing or deselected.
- No other env vars are read.

`PROJECT_ROOT` (Python constant) is derived from `Path(__file__).parent.parent`
and is the anchor for all relative paths in `config.toml`. The salt is
written back into `config.toml` on first run by string-replace.

## Extractor inventory

| name        | source path                                                                            | output `source` label(s)                                              | status   | notes |
|-------------|----------------------------------------------------------------------------------------|------------------------------------------------------------------------|----------|-------|
| spotlight   | mdfind across `~/Documents`, `~/Desktop`, `~/Downloads`, `~/Pictures`, `~/Movies`, `~/Music`, `~/Library/Mobile Documents`, `~/Projects`, `~/CustomOS`, `~/code`, `~/src` | `spotlight.file_use`                                                  | working  | One event per `kMDItemUsedDates` entry; falls back to `kMDItemLastUsedDate`. Capped at 5000 hits/root. |
| safari      | `~/Library/Safari/History.db` + `LastSession.plist` + `Bookmarks.plist`                 | `safari.history`, `safari.last_session`, `safari.bookmarks`            | working  | Apple absolute time. RecentlyClosedTabs.plist not yet read. |
| chrome      | `~/Library/Application Support/Google/Chrome/Default/History`                            | `chrome.history`                                                       | working  | Chromium epoch (μs since 1601). |
| brave       | `~/Library/Application Support/BraveSoftware/Brave-Browser/Default/History`              | `brave.history`                                                        | working  | Same as chrome. |
| knowledgec  | `~/Library/Application Support/Knowledge/knowledgeC.db`                                  | `knowledgec.app.usage`, `knowledgec.app.webUsage`, `knowledgec.app.activity`, `knowledgec.app.inFocus`, `knowledgec.notification.usage`, `knowledgec.display.isBacklit`, `knowledgec.device.isLocked`, `knowledgec.device.isPluggedIn`, `knowledgec.safari.history`, `knowledgec.screentime.usage` | working | Stream → category map filters to known streams. |
| sfl2        | `~/Library/Application Support/com.apple.sharedfilelist/`                                | `sfl2.<list>`                                                          | **stub / no-op** | NSKeyedArchiver `$top.root` resolution returns no items on Tahoe; archive walker needs rewrite. |
| shell       | `~/.zsh_history`                                                                         | `shell.zsh_history`                                                    | working  | Extended-history `: <epoch>:<duration>;<cmd>` parser; tool = first whitespace token. |
| calendar    | `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb`                  | `calendar.event`                                                       | working  | New path on Tahoe (legacy `~/Library/Calendars/Calendar.sqlitedb` no longer exists). Lowercase columns. |
| notes       | `~/Library/Group Containers/group.com.apple.notes/NoteStore.sqlite`                      | `notes.note`                                                           | partial  | Titles + create/modify timestamps. Body decoding intentionally not implemented. Filter `Z_ENT = ICNote`, COALESCE across `ZCREATIONDATE{,1,2,3}` and `ZMODIFICATIONDATE{,1}`. |
| reminders   | `~/Library/Group Containers/group.com.apple.reminders/Container_v1/Stores/Data-*.sqlite` | `reminders.create`, `reminders.complete`                               | **0 rows** | All three local stores empty on this Mac (CloudKit-resident, no local cache). Code is correct. |
| biome       | `~/Library/Biome/streams/restricted/<StreamName>/{local,remote/<UUID>}/`                 | `biome.app_infocus`, `biome.app_activity`, `biome.app_intent`, `biome.app_intent_xscript`, `biome.webapp_infocus`, `biome.app_web_usage`, `biome.app_media_usage`, `biome.menu_item`, `biome.doc_interaction`, `biome.relevant_shortcuts`, `biome.lang_consumption`, `biome.notification_pub`, `biome.notification_set`, `biome.now_playing`, `biome.screentime_app`, `biome.screentime_tl`, `biome.focus_computed`, `biome.focus_inferred`, `biome.sharing_interaction`, `biome.safari_history`, `biome.dk_app_infocus`, `biome.audio_route`, `biome.alarm`, `biome.wifi`, `biome.bluetooth`, `biome.lpm`, `biome.discoverability`, `biome.app_launch_session` | working  | Hybrid extractor: bbpb decode + raw-byte ASCII scan with protobuf length-prefix-aware truncation. STREAM_MAP whitelists ~28 streams of ~166 available. Tahoe layout has no `streams/public/`. |
| photos      | `~/Pictures/Photos Library.photoslibrary/database/Photos.sqlite`                          | `photos.asset`                                                         | working  | Lat/lon quantized to 0.01°. Auto-detects `ZASSET` vs `ZGENERICASSET`. |
| messages    | `~/Library/Messages/chat.db`                                                              | `messages.message_sent`, `messages.message_received`                   | working  | Contact handles SHA-256 hashed with per-install salt; only `body_length` (not body) stored unless `deep_content_analysis=true`. macOS 10.13+ nanosecond Apple-time decoder. |
| mail        | `~/Library/Mail/V*/MailData/Envelope Index`                                              | `mail.message`                                                         | working  | Schema-sniffs available columns (sender/address/from_address, date_sent/date_received/received_date). Subjects never extracted; sender hashed. |
| (unified_log) | `log show ...` shell-out                                                                | `system_log` (intended)                                                 | unimplemented | No extractor file exists; no entry in `EXTRACTOR_REGISTRY`. `extract.include_unified_log` flag is read by no code today. |

## Analysis inventory

### `analyze/rhythms.py`
- `coverage(con)` — earliest/latest `ts_local`, total events, distinct sources, distinct categories, distinct days. Consumes: `events.ts_local, source, category`. Produces: dict.
- `hourly_by_category(con)` — for each category, 24-int hour histogram. Consumes: `events.ts_local, category`. Produces: `dict[str, list[int]]`.
- `weekday_by_category(con)` — for each category, 7-int weekday histogram (0=Mon). Same inputs.
- `hour_by_weekday(con)` — single 7×24 grid of total events.

### `analyze/sessions.py`
- `app_focus_sessions(con, gap_minutes=5)` — walks `category IN ('app_focus','app_launch')` events ordered by `ts_local`; starts new session when gap > 5 min. Consumes: `events.ts_local, target, source` (last 365 days only). Produces: list of `{start, end, duration_sec, apps, n_events}`.
- `session_summary(sessions)` — count, median/p90/min/max duration in seconds.

### `analyze/workflows.py`
- `app_sequences_within_window(con, window_minutes=5, min_len=3, max_len=6)` — sequences of foreground bundle IDs within 5-min gaps; collapses consecutive duplicates. Consumes: `events.ts_local, target` where `category='app_focus'`. Produces: `list[list[str]]`.
- `top_n_grams(sequences, n_min=3, n_max=5, top=50)` — n-gram counter across sequences.

### `analyze/cohabitation.py`
- `cohabitation_pairs(con, bucket_minutes=30, top=80)` — distinct app pairs that appear in the same 30-min bucket; consumes: `events` where `category='app_focus'`. Produces: `[{a, b, buckets_co_active}]`.

### `analyze/files.py`
- `top_files(con, top=50)` — by `category IN ('file_access','file_recent')`. Returns `path, count, first, last`.
- `directory_hotspots(con, depth=5, top=50)` — clusters by path prefix at depths 2..5; double-pass to attach first/last seen. Returns `[{directory, count, first, last, days_since_last}]`.

### `analyze/communication.py`
- `top_contacts(con, top=30)` — aggregates over `target_kind='contact'`; sums `message_sent`, `message_received`, `mail_seen`.
- `domain_frequency(con, top=60)` — extracts `metadata.$.domain` from `web_visit` events.
- `app_affinity(con, top=40)` — focus events + total seconds per `target_kind='app'`.

### `analyze/pipeline.py`
- `run_all()` — opens DuckDB read-only, runs the above, computes sessions + workflow n-grams, writes `output/analyses.json`. Returns the same dict in-memory.

### `analyze/llm.py` — six tasks

Provider: `OpenAILLM` (Responses API, `text.format = {type: "json_schema", strict: false}`) or `AnthropicLLM` (Messages API, schema embedded in prompt). Selection by `Settings.chosen_llm()`. JSON parsing tolerated via `_force_json` (strips code fences, falls back to first `{...}`).

| function                  | input                                                                          | schema (validated → Pydantic)        | stored in `profile.json` as            |
|---------------------------|--------------------------------------------------------------------------------|--------------------------------------|----------------------------------------|
| `label_workflows`         | top 30 sequence-frequency rows                                                 | `{workflows: [WorkflowLabel]}`       | `workflows`                            |
| `label_work_modes`        | top 60 cohabitation pairs + top 25 app-focus counts                            | `{modes: [WorkMode]}`                | `work_modes`                           |
| `describe_rhythm`         | full `rhythms` dict (hourly/weekday/grid)                                      | `RhythmDescription`                  | `rhythm_description`                   |
| `infer_projects`          | top 40 directory hotspots                                                      | `{projects: [InferredProject]}`      | `projects`                             |
| `describe_browsing`       | top 30 domains + tab_state (currently `{}`)                                    | `BrowsingProfile`                    | `browsing.llm_profile`                 |
| `find_quirks_and_hooks`   | rhythm + work_modes + top 15 workflows + 15 apps + 15 domains + 15 directories | `IdiosyncrasyOutput`                 | `rhythm_quirks` + `customization_hooks` |

## CLI surface

`uv run macprofile <cmd>`:

- `preflight` — probe protected paths (Mail, Messages, Safari, knowledgeC, Biome, Calendar, Notes, Photos), print FDA instructions if any are denied.
- `extract` — run extractors, load events. Flags: `--all`, `--only <name>` (repeatable), `--skip <name>` (repeatable). Prints summary table + total counts by source.
- `status` — count by source and by category from the warehouse.
- `purge --yes` — delete `data/`, `output/`, recreate.
- `analyze` — run all analyzers, write `output/analyses.json`.
- `profile` — `analyze` + LLM analysis layer, write `output/profile.json` + `profile.md`. Flag: `--skip-llm`.
- `serve` — FastAPI on `127.0.0.1:8766` (default port; was 8765 but that conflicted with the user's Ripasso IGCSE app).

FastAPI endpoints exposed by `serve` (all GET):

- `/health` — `{ok: bool, db_exists: bool}`.
- `/profile` — JSON; 404 until `profile.json` exists.
- `/profile.md` — plain text; 404 until `profile.md` exists.
- `/events/by-source` — `{source: count}`.
- `/events/by-category` — `{category: count}`.
- `/apps/top?limit=N` — top app bundles by focus events with first/last seen.
- `/files/hotspots?limit=N` — calls `analyze.files.directory_hotspots`.
- `/rhythms/hour-by-weekday` — 7×24 grid.
- `/query?q=<phrase>&limit=N` — keyword router for natural-language-ish phrases. Recognises `morning|afternoon|evening|night` (mapped to hour ranges) and weekday names (`monday`..`sunday`); returns top `(category, target)` aggregates inside the resulting time window. No LLM in this path today; just SQL.

## Known issues and tech debt

- **`sfl2` is a stub.** `_resolve_archived` returns `[]` for every NSKeyedArchiver `.sfl2`/`.sfl4` archive on Tahoe. The `$top.root → NS.objects` chain of dereferences doesn't match what these archives actually contain on this OS version. Extractor runs, finds the files, decodes them via `plutil`, and yields nothing. Documented but not fixed.
- **`reminders` returns 0 rows** on this Mac because all three `Data-*.sqlite` stores are empty (CloudKit without local cache). Code is correct; no action required, but consumers should not assume a populated reminders table.
- **Coverage outliers** (~~flow through unfiltered~~ — fixed in B3 by `analyze.rhythms.coverage`: an "active day" requires ≥10 macOS-native events, `latest` clips future-dated rows, and `coverage.raw_range` reports the unclipped min/max for transparency. The underlying outlier rows remain in the warehouse).
- **iPhone Biome contamination** (~~not filtered~~ — fixed in B3 by `normalize.device_scope.is_macos_native` + `macos_native_sql`, applied in `rhythms`, `sessions`, `workflows`, `cohabitation`, and `communication.app_affinity`. iOS Springboard prefixes and a small allow-list of iOS-only bundle IDs are filtered out at analysis time; the underlying rows remain in the warehouse so future cross-device analysis is still possible). The `Scope` field in `customos_core.profile` models the bit at the type level.
- **Unified log extractor is registered nowhere.** The CLI registry has no entry, no module, no tests. `config.toml`'s `extract.include_unified_log` flag is dead code.
- **`OPENAI_API_KEY` was echoed once in this session's preflight Bash output.** The leak was in a one-off shell command at startup (`echo "OPENAI_API_KEY set: ${OPENAI_API_KEY:+yes}${OPENAI_API_KEY:-no}"`, where the `:-no` fallback resolves to the actual value when set). It was not in committed code: `macprofile/preflight.py` does not log env vars, and nothing in the rest of the package reads `os.environ` for secrets and logs them. The user should rotate the key anyway because the value entered the conversation transcript.
- **`profile.json` had `workflows_raw` and `cohabitation_raw`** at the top level — ~~fixed in B3~~. `profile.json` no longer carries `_raw` fields; raw aggregates live in `analyses.json`. Sequences live under `profile.sequences` typed against `customos_core.Sequence`.
- **`profile.privacy.sources_analyzed` was empty** — ~~fixed in B3~~. Now pulled from the warehouse via a `GROUP BY source` query (`_sources_analyzed` in `profile/build.py`); contains the actual labels that contributed events to the analysis.
- **Hook predicate vocabulary is LLM-invented.** Hooks were demoted in B3 to `output/hook_suggestions.json` with an explicit `_meta` block marking them advisory. The `BehavioralProfile` schema deliberately does **not** include them. The predicate-vocabulary spec is still the gating step before any consumer of these suggestions can do useful work with them.
- **`LLMCfg.max_output_tokens` default is 4000.** That cap truncated several gpt-5 Responses-API outputs because reasoning tokens are charged against the same budget. Live `config.toml` was bumped to 16000 to make the run complete; the default in `Settings` is still 4000. Future first-run users will hit the same truncation.
- **`extractors/base.py::Extractor.run`** is dead code: it is `def run` that both yields and returns a tuple, which yields the tuple as the final value of the generator. The CLI bypasses it entirely (`wh.insert_events(ext.extract())`). It can be removed but isn't.
- **`tests/`** is empty. No test scaffolding, no fixtures.
- **`macprofile/normalize/__init__.py`, `analyze/__init__.py`, `extractors/__init__.py`, `profile/__init__.py`, `app/__init__.py`** are all empty.
- **Salt persistence is fragile.** `_bootstrap_salt` rewrites `config.toml` via `str.replace('contact_hash_salt = ""', ...)`. If the user manually changes that line's quoting style, future writes break.
- **OpenAI Responses API JSON-schema strictness is set to `False`** so partial outputs validate. Any schema drift in upstream OpenAI behaviour will silently produce malformed `profile.json` instead of erroring.

## Predicates referenced by current hooks (ungrounded)

Extracted from `output/profile.json::customization_hooks[*].trigger`. None of
the function-call identifiers and only one of the variable identifiers
(`day_of_week`, `local_time`) map to anything the system can compute today.
The "Computable from history?" column refers to whether the extractor *could*
derive the signal from `events.duckdb` alone; "Live observer only?" refers to
signals that fundamentally require a running process watching the system.

| identifier                              | kind        | from history? | live only? | LLM-invented? | notes                                                                                                |
|-----------------------------------------|-------------|---------------|------------|---------------|------------------------------------------------------------------------------------------------------|
| `day_of_week`                           | variable    | yes           | no         | no            | Trivially `EXTRACT(dow FROM ts_local)` over the warehouse, or `datetime.now()` live.                 |
| `local_time`                            | variable    | yes           | no         | no            | Same.                                                                                                |
| `next_day_is_weekday`                   | variable    | yes           | no         | no            | Derivable from local clock.                                                                          |
| `app_switch_pair_count_10m(a,b)`        | function    | yes           | yes        | no            | Pair-switch count over 10-min sliding window. Computable historically; needs a live counter for runtime evaluation. |
| `app_active_minutes_15m(bundle)`        | function    | yes           | yes        | no            | Same.                                                                                                |
| `app_active_duration_10m(bundle)`       | function    | yes           | yes        | no            | Same.                                                                                                |
| `social_app_switches_5m(list)`          | function    | yes           | yes        | no            | Same.                                                                                                |
| `domain_visits_10m(domain)`             | function    | yes           | yes        | no            | Same.                                                                                                |
| `homescreen_activations_5m`             | variable    | partial       | yes        | partial       | Today these are iPhone Biome events, not Mac. On macOS the closest analogue is Mission Control activity which we don't capture. **Cross-device contamination risk.** |
| `spotlight_activations_5m`              | variable    | partial       | yes        | partial       | Same caveat as above.                                                                                |
| `terminal_command_count_10m`            | variable    | yes           | yes        | no            | Computable from `shell.zsh_history` events.                                                          |
| `finder_file_events_10m`                | variable    | partial       | yes        | partial       | Spotlight gives historical file-access events but not "Finder-driven" specifically. Conflated.       |
| `safari_active_minutes_30m`             | variable    | yes           | yes        | no            | Computable.                                                                                          |
| `safari_tab_count`                      | variable    | partial       | yes        | partial       | We have `safari.last_session` snapshots but no continuous tab-count history.                         |
| `oldest_tab_age_days`                   | variable    | partial       | yes        | partial       | Same: only the snapshot we captured at extraction time, not continuous.                              |
| `safari_bookmarks_added_10m`            | variable    | yes           | yes        | no            | Bookmark snapshot only; deltas computable across snapshots but not currently retained as a history.  |
| `gmail_unread_count`                    | variable    | no            | yes        | yes           | Requires live IMAP/Gmail API access; not in scope of any current source.                             |
| `media_playback_active`                 | variable    | partial       | yes        | partial       | `biome.now_playing` gives historical playback events; live signal requires a NowPlaying observer.    |
| `music_playback_active`                 | variable    | partial       | yes        | partial       | Same.                                                                                                |
| `keyboard_idle_seconds`                 | variable    | no            | yes        | no            | Pure live observer signal (CGEventSource idle time, etc.).                                           |
| `downloads_dir_file_count`              | variable    | yes           | yes        | no            | A `ls -1 ~/Downloads` count; computable any time.                                                    |
| `downloads_fraction_older_than_30d`     | variable    | yes           | yes        | no            | Same; stat-time arithmetic.                                                                          |
| literal day-name tokens (`Mon`..`Sun`)  | constant    | n/a           | n/a        | no            | Used as RHS of `day_of_week IN [...]`.                                                               |
| literal time strings (`"10:30"` etc.)   | constant    | n/a           | n/a        | no            | Used as RHS of `BETWEEN`.                                                                            |
| literal bundle-ID strings               | constant    | n/a           | n/a        | no            | Arguments to function predicates.                                                                    |

Functional summary: ~20 identifiers, all but one (`gmail_unread_count`)
plausibly groundable. Most need a running observer to evaluate at runtime,
and several conflate iPhone Biome data with macOS state. **No predicate
vocabulary spec exists today.** Resolving that is the gating step before
hooks can be consumed by `customization-system/`.

## Decisions made during build that aren't obvious from the code

- **DuckDB over SQLite** — single file, columnar, ~10× faster on the
  aggregation workloads (`GROUP BY hour, category` over 350k rows). DuckDB
  also handles `JSON` columns natively (`json_extract_string`) which mattered
  for the `metadata` column. Considered Parquet + ad-hoc tools; rejected
  because we want sub-second slice queries and the warehouse fits in memory.
- **Single `events` table, not a per-source table** — schema unification is
  the whole point. Per-source tables would push joins everywhere downstream.
- **`raw_hash` (SHA-1) on the source-row identity, not a UUID** — extractors
  must be idempotent across re-runs without manual delete. The hash includes
  source-specific fields so re-running an extractor twice produces the same
  hash for the same row and the `ON CONFLICT DO NOTHING` path absorbs the
  duplicate.
- **5-minute idle gap for sessions** — chosen empirically: 1 minute was too
  fragmented (people read for 90s without focus events), 10+ minutes merged
  unrelated activity across lunch breaks. Not derived from data.
- **30-minute bucket for cohabitation** — wide enough to catch "I had Slack
  and VS Code open in the same window" without being so wide that everything
  cohabits with everything. Not tuned.
- **n-gram length 3..5 for workflow mining** — 2-grams are too noisy
  (alt-tab is not a workflow), 6+ are too rare to count reliably.
- **Notes body decoding is intentionally not implemented.** ZICNOTEDATA
  rows are gzipped protobuf-wrapped attributed strings; decoding them is
  feasible but pulls actual content into the warehouse. Privacy posture is
  "titles + timestamps only by default; only enable body decoding behind
  `deep_content_analysis = true`". The flag exists but no body decoder does.
- **Contact identifiers are SHA-256 hashed with a 16-byte hex per-install
  salt**, truncated to 16 hex chars, and prefixed with `c_`. Salt is
  generated once via `secrets.token_hex(16)` and persisted to `config.toml`
  on first run. Phone numbers and emails are normalised (lowercase,
  whitespace-stripped) before hashing so the same person produces the same
  hash across `messages` and `mail` sources.
- **URL canonicalisation strips query+fragment** — for grouping. Means we
  lose Google search query strings and similar; that was the explicit
  privacy default.
- **Spotlight roots are an explicit allowlist**, not `/Users/<me>` recursive,
  because mdfind across the whole home directory pulls in `~/Library/Caches/`
  and similar noise. The list is hand-picked and includes `~/Projects` and
  `~/CustomOS`.
- **Photos lat/lon quantised to 0.01°** (≈1 km) before storage. Original
  precision is ~10 m. This is a deliberate privacy degradation; can be
  disabled by changing `_quantize`'s `step` arg but no config knob exists.
- **Safari history table column is `history_visits.visit_time`**, not
  `visit_date` as some older ccl code assumes. Apple absolute time, decoded
  via `apple_to_dt`.
- **Calendar lives at `~/Library/Group Containers/group.com.apple.calendar/Calendar.sqlitedb` on Tahoe**.
  The legacy `~/Library/Calendars/Calendar.sqlitedb` does not exist on this
  OS version. The path was changed without a deprecation warning from Apple.
- **Calendar table names are unprefixed** (`CalendarItem`, `Calendar`,
  `Location`) on Tahoe, not the `Z`-prefixed CoreData names of older
  versions. The query uses `CalendarItem.start_date` directly.
- **Notes table is `ZICCLOUDSYNCINGOBJECT` with polymorphic `Z_ENT`**. We
  filter `Z_ENT = (SELECT Z_ENT FROM Z_PRIMARYKEY WHERE Z_NAME='ICNote')`
  rather than hard-coding `Z_ENT = 12` (which is correct on this Mac but
  not stable across Notes versions).
- **Notes date columns are polymorphic across versions**: we COALESCE
  `ZCREATIONDATE3 → ZCREATIONDATE1 → ZCREATIONDATE → ZCREATIONDATE2` and
  similarly for modification. This Tahoe install populates `*DATE3`.
- **Reminders table is auto-discovered** (any table whose name contains
  `REMINDER` or `TODOITEM`) and column names sniffed at runtime. Built that
  way to survive Apple's CoreData renumbering between releases.
- **Biome `streams/restricted/<Stream>/{local,remote/<UUID>}` layout** — on
  this Mac there is no `streams/public/` directory; everything is in
  `restricted/`. The spec brief assumed `public/` existed; it doesn't on
  Tahoe.
- **Biome bundle-ID extraction is byte-scan first, bbpb second.** Initial
  attempt used `blackboxprotobuf.decode_message` exclusively; ~40 % of
  records failed to decode (uvarint past EOF) or decoded to `{0: [0,0,0...]}`.
  Switched to: scan the raw bytes for ASCII bundle-ID patterns; for each
  match, look at the byte immediately preceding it as a length-prefix and
  truncate accordingly (catches the trailing wire-tag byte that the greedy
  regex absorbs, e.g. `com.apple.terminalJ` → `com.apple.terminal`).
  bbpb is still attempted first when it works, and contributes
  duration/structure metadata; the byte scan is the always-on fallback.
- **Biome `STREAM_MAP` is a manual whitelist of ~28 high-signal streams.**
  All ~166 streams in `streams/restricted/` were enumerated; many are
  internal Apple telemetry (`Siri.PrivateLearning.*`, `IntelligenceFlow.*`)
  with no user-meaningful payload. Adding more is cheap; pruning is what
  took time.
- **`ccl_segb` was installed from git, not PyPI.** PyPI's `ccl-segb` is
  unmaintained / pinned to `protobuf==3.10`. The maintained source is
  `git+https://github.com/cclgroupltd/ccl-segb`. PyPI's `blackboxprotobuf`
  has the same problem; we use `bbpb` instead, which is API-compatible
  (`import blackboxprotobuf` still works).
- **`ccl_bplist` was *not* installed**; sfl2 plists are converted to XML by
  shelling out to macOS' built-in `plutil -convert xml1`. One less dep,
  fewer install pitfalls.
- **All extractors copy SQLite DBs to `data/raw/<source>/<date>/` before
  reading.** Querying the live `chat.db`, `History.db`, `NoteStore.sqlite`
  while the OS process holds them risks WAL-state corruption. `safe_copy`
  also brings `-wal` and `-shm` sidecars.
- **All SQLite reads use `mode=ro&immutable=1` URI flags.** Belt and braces.
- **No retries anywhere.** The pipeline is short-running and tolerant of
  partial extractor failures (the CLI catches `PermissionError`,
  `FileNotFoundError`, generic `Exception` per-extractor and continues with
  the rest). Inside an extractor, a single bad SEGB record is logged at
  warning and skipped.
- **LLM provider preference order is `[anthropic, openai]`** but the live
  environment had no Anthropic key, so OpenAI ran. The Anthropic path is
  written but untested in this environment.
- **OpenAI Responses API, not Chat Completions.** The brief required it for
  gpt-5; structured-output entry point is `text.format = {type:
  "json_schema", strict: false}`. `strict=False` because partial outputs
  during truncation should still parse.
- **Markdown profile renderer is deterministic Python**, not LLM-rendered.
  The brief allowed an LLM-rendered `profile.md`; choosing a simple
  formatter avoids spending tokens on prose and keeps the markdown
  reproducible.
- **FastAPI default port moved from 8765 to 8766** because 8765 is occupied
  by the user's own Ripasso IGCSE study app on this machine. The new port
  is hardcoded in `cli.py::serve`.
- **Workspace pyproject (this project) uses `[tool.hatch.metadata]
  allow-direct-references = true`** because `ccl_segb` is a git URL.

## Migration target (this session, Phase 2)

The macprofile/ tree (code, data, output) moves to
`~/CustomOS/profile-extractor/` as a uv workspace member of the existing
CustomOS workspace (`customos-core`, `profile-extractor`,
`customization-system`). The Python package name stays `macprofile`;
renaming the package, lifting `Event` and friends into `customos-core/`,
fixing the bugs listed in **Known issues**, and grounding the predicate
vocabulary referenced in **Predicates** are all explicitly **out of scope**
for this session and will be handled in dedicated follow-ups.

## Post-cleanup state (session B3, 2026-05-11)

This session reshaped the profile from a loose dict into a typed contract
and resolved the contamination/cleanup items that were blocking it.

### What changed

- **Cross-device filter.** New `macprofile/normalize/device_scope.py`
  exposes `is_macos_native(target, target_kind)` and `macos_native_sql()`.
  The SQL fragment is wired into `analyze/rhythms.py`, `sessions.py`,
  `workflows.py`, `cohabitation.py`, and `communication.py::app_affinity`.
  Files/web/communication-contact paths are untouched. iOS-only bundle
  list is short and well-commented (Snapchat, Instagram, TikTok iOS,
  Google iOS YouTube, four `com.apple.mobile*`, all `com.apple.springboard.*`);
  default is "treat as Mac" for everything else with a TODO list of
  uncertain bundles in the module.
- **Coverage clipping.** `rhythms.coverage` now computes "active day = ≥10
  events" earliest/latest and clips `latest` against the current date.
  `coverage.raw_range` surfaces the unclipped min/max so the discrepancy
  isn't hidden. Schema fields: `Coverage.earliest`, `Coverage.latest`,
  `Coverage.raw_range`, `Coverage.active_day_threshold` (default 10).
- **Privacy manifest.** `profile/build.py::_sources_analyzed` queries the
  warehouse directly for sources that produced macOS-native events. The
  buggy comprehension is gone.
- **`_raw` fields removed** from `profile.json`. Raw aggregates remain in
  `analyses.json` which is the appropriate place.
- **Hooks demoted** to `output/hook_suggestions.json` with an explicit
  `_meta` block stating advisory status and pointing at the missing
  predicate vocabulary spec. `profile.md` carries a one-paragraph pointer
  to the file in place of the old hooks section.
- **`customos-core` is real**. `customos-core/pyproject.toml` adds pydantic
  v2 as a dep; `customos_core/profile.py` defines `BehavioralProfile` and
  its component models; `customos_core/__init__.py` exports them. README
  rewritten. `profile-extractor/pyproject.toml` declares
  `customos-core` as a workspace-internal dep via `[tool.uv.sources]`.
- **`profile/build.py` rewritten** to construct a typed `BehavioralProfile`
  and serialise via `.model_dump_json()`. LLM outputs are converted to
  schema types (prompts unchanged). New `profile/render.py` consumes the
  typed model.
- **Profile schema design decisions** (also captured in ADR-0004):
    - `Rhythms` carries both raw matrices and LLM narrative.
    - `Sequence.steps: list[str]` not richer Step objects.
    - Contact ID stays at the existing `c_<16hex>` SHA-256 hash.
    - `Stability` attached to `AppAffinity`, `Project`, and
      `Idiosyncrasy.stability` (optional).
    - `Scope` attached to `Rhythms`, `AppAffinity`, `Sequence`, `WorkMode`,
      `Browsing`, `Communication`. Default `mac_only` after the filter.
- **Docs**: ADR-0004 written. `docs/interface.md` `BehavioralProfile` and
  `Hook` sections now point at the source rather than being TBD.

### Last run (B3)

- `data/events.duckdb` unchanged (still ≈303 MB, ~358k rows).
- `output/analyses.json` ≈68 KB — keeps `workflows`, `cohabitation`, `files`,
  `rhythms`, `sessions_summary`, `communication`, `coverage`.
- `output/profile.json` ≈71 KB — validates against `BehavioralProfile`.
- `output/profile.md` ≈12 KB.
- `output/hook_suggestions.json` ≈6 KB.
- Top app affinity rows are now clean (Terminal, Safari, WhatsApp, Claude,
  Finder, Control Center, Music, Preview, Obsidian, Login Window, …) — no
  Springboard, no iOS-only bundles.
- Top sequences are clean (Terminal↔Safari, WhatsApp↔Control Center,
  WhatsApp↔FindMy, WhatsApp↔Revolut) — no `picaboo → home → instagram`
  patterns.

### Known issues — current state

- **`sfl2` stub** — still no-op. Unchanged.
- **`reminders` empty** — still empty on this Mac by design. Unchanged.
- **Unified log extractor** — still unimplemented. Unchanged.
- **`tests/`** — still empty. Unchanged.
- **Salt persistence is fragile** — unchanged.
- **OpenAI Responses API `strict=False`** — unchanged; partial outputs still
  pass through. The Pydantic validation in `customos_core` now catches more
  schema drift than before (the model is `extra="forbid"` everywhere).
- **`extractors/base.py::Extractor.run` dead code** — unchanged.
- **`max_output_tokens` default 4000** — unchanged; live config bumped to 16000
  to make the gpt-5 call complete.

### Known issues — new in B3

- **`negative_signals` is always empty.** The schema field exists per ADR-0004;
  no extractor populates it today. The customization-system can plan around
  this but should not assume anything in there for now.
- **`Contact.classification` defaults to `unknown` for everything.** The
  `Contact` model has the enum field; the LLM analysis layer doesn't yet
  produce classifications. Adding it requires a new LLM call that takes
  contact aggregates and emits `ContactClass` per contact. Out of scope for
  B3; the schema is ready.
- **`AppAffinity.role` is always `None`.** Schema-supported but no analyzer
  computes a role label today. Same shape as `Contact.classification`.
- **`Idiosyncrasy.when` and `Idiosyncrasy.stability` are always `None` /
  default.** The current `find_quirks_and_hooks` LLM call returns
  `quirks: list[str]`; the build layer wraps each string into an
  `Idiosyncrasy(description=..., confidence=0.6)` without structured `when`
  or stability. A follow-up could update the prompt to emit structured
  idiosyncrasies, but the brief explicitly said not to redesign prompts
  beyond mapping outputs to the new schema.
- **Project `last_active` may equal `generated_at`.** When the analyzer
  can't recover a directory's last access date from the hotspots dict, the
  build layer falls back to "now" rather than null. The stability indicator
  on the project will then look more durable than it is. Low priority since
  this only fires when an LLM-inferred project name doesn't exactly match a
  hotspot path key.
- **`schema_version` is hard-pinned via `Literal["1.0.0"]`.** Bumping it is
  a coordinated change between extractor and consumer; the model can't be
  used to read an older or newer profile until the literal accepts both.
  Intentional per ADR-0004 but worth knowing.

### Out of scope (still open)

Predicate vocabulary spec, `Event`/sessionization lift to
`customos-core`, sfl2 archive walker, unified log extractor, tests
scaffolding, salt rotation. All explicitly deferred to dedicated sessions.

## Post-cleanup state (session B4, 2026-05-11)

### What changed

- **Identifier normalization lifted.** `normalize_bundle_id`,
  `canonicalize_url`, and `hash_contact` moved from
  `macprofile/normalize/identity.py` into `customos_core.identity`.
  `hash_contact` was minimally generalised — the salt is now a keyword
  argument rather than read from `get_settings()` inside the function —
  so the helper is genuinely stateless and lives in customos-core
  without an extractor dependency.
- **`macprofile/normalize/identity.py` is a thin shim.**
  `normalize_bundle_id` and `canonicalize_url` are re-exports;
  `hash_contact()` keeps its zero-arg signature by wrapping the
  customos-core helper with the settings-loaded salt. Existing call
  sites in `extractors/{biome,browsers,knowledgec,mail,messages}.py`
  needed no changes.
- **Verification.** `uv run macprofile preflight` and
  `uv run macprofile analyze` were re-run against the live warehouse
  after the shim landed and both completed cleanly.
  `output/analyses.json` was regenerated identically.
- Driver: a silent visual bug in the customization-system prototype
  (case-sensitive bundle-ID comparison dimmed the user's most-used Dock
  apps). See [ADR-0006](../docs/decisions/0006-identifier-normalization-in-customos-core.md).

### Known issues — current state

Same as after B3, plus:

- **Salt persistence still fragile** — unchanged; tracked separately
  from this session.

### Out of scope (still open)

Predicate vocabulary spec, `Event`/sessionization lift to
`customos-core`, sfl2 archive walker, unified log extractor, tests
scaffolding, salt rotation. All explicitly deferred.
