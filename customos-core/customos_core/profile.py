"""BehavioralProfile schema.

The contract between profile-extractor (producer) and the future
customization-system (consumer). Trait-only per ADR-0003: no state, no
hooks, no raw aggregates.

Design notes (the ones not obvious from the field list):

  * Two-shaped Rhythms. The schema carries both raw matrices (so the
    customization-system can answer hour-level queries directly from
    the profile) and an LLM-rendered narrative (so the profile reads
    well as background context). Picked because both consumers matter.

  * Sequences carry bundle IDs as strings, not Step objects. We don't
    capture reliable per-step dwell time yet; promoting list[str] to
    list[Step] later requires only changing one field type without
    breaking the surrounding shape.

  * Contact identifiers are the c_<16hex> hashes the extractor already
    produces (SHA-256 of normalized handle salted with a per-install
    random salt, truncated to 16 hex chars, c_-prefixed). Keeping this
    matches the warehouse and avoids re-hashing.

  * Every trait that could be flaky carries a Stability indicator. The
    coordinator uses durability to decide whether to act confidently
    on a trait. Coverage, Privacy and Rhythms don't carry one — they're
    either definitional (coverage describes the input) or population
    statistics where flakiness isn't meaningful.

  * Every aggregate that could mix Mac and iPhone data carries a Scope.
    After Workstream 1 of session B3 the analyzers default to
    `mac_only`. The schema field exists so any future cross-device
    work doesn't require a schema migration.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Shared markers
# ---------------------------------------------------------------------------

class Durability(str, Enum):
    durable = "durable"   # high event count, recent activity, stable over time
    emerging = "emerging" # new pattern, not yet enough history to be confident
    fading = "fading"     # historically present but recency low


class Scope(str, Enum):
    mac_only = "mac_only"       # all underlying events are local-Mac
    cross_device = "cross_device"  # cross-device data deliberately included
    unknown = "unknown"            # provenance not determinable


class Stability(BaseModel):
    """How much we trust a trait. Attached to fields that could be flaky."""
    model_config = ConfigDict(extra="forbid")

    based_on_events: int = Field(..., ge=0)
    first_seen: datetime
    last_seen: datetime
    durability: Durability


# ---------------------------------------------------------------------------
# Coverage / Privacy / Rhythms
# ---------------------------------------------------------------------------

class CoverageRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    earliest: datetime | None = None
    latest: datetime | None = None


class Coverage(BaseModel):
    """Time and breadth of the analyzed event store."""
    model_config = ConfigDict(extra="forbid")

    earliest: datetime | None = Field(
        None,
        description="First active day after outlier clipping.",
    )
    latest: datetime | None = Field(
        None,
        description="Last non-future active day after clipping.",
    )
    raw_range: CoverageRange = Field(
        default_factory=CoverageRange,
        description="Unclipped min/max ts_local across the warehouse. Surface for transparency.",
    )
    total_events: int = Field(..., ge=0)
    sources_active: int = Field(..., ge=0)
    categories_seen: int = Field(..., ge=0)
    days_with_events: int = Field(..., ge=0)
    active_day_threshold: int = Field(
        10,
        description="Minimum event count for a day to count as 'active'. Used by earliest/latest.",
    )


class Privacy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    deep_content_analysis: bool = Field(
        False,
        description="If true, raw note titles, mail subjects, message bodies may have been sent to the LLM.",
    )
    sources_analyzed: list[str] = Field(
        default_factory=list,
        description="Warehouse `source` labels that contributed events to the analysis.",
    )
    events_analyzed: int = Field(..., ge=0)


# Free-form category strings — keep flexible across schema versions.
Category = str


class Rhythms(BaseModel):
    """Temporal fingerprint. Carries both raw matrices and LLM narrative.

    `hourly_by_category` / `weekday_by_category` / `hour_by_weekday` are the
    machine inputs for hour/day queries. `workday_window`, `leisure_window`,
    `notable_quirks`, `summary` are the LLM rendering for human reading.
    """
    model_config = ConfigDict(extra="forbid")

    scope: Scope = Scope.mac_only
    hourly_by_category: dict[Category, list[int]] = Field(
        default_factory=dict,
        description="category -> 24-int hour histogram. Sum across all observed days.",
    )
    weekday_by_category: dict[Category, list[int]] = Field(
        default_factory=dict,
        description="category -> 7-int weekday histogram (0=Mon).",
    )
    hour_by_weekday: list[list[int]] = Field(
        default_factory=list,
        description="7x24 grid of total events, row 0 = Monday.",
    )
    workday_window: str | None = Field(
        None,
        description="LLM-rendered narrative, e.g. 'Mon-Fri 09:30-18:30'.",
    )
    leisure_window: str | None = Field(
        None,
        description="LLM-rendered narrative, e.g. '20:00-01:00'.",
    )
    notable_quirks: list[str] = Field(default_factory=list)
    summary: str | None = None


# ---------------------------------------------------------------------------
# App affinities
# ---------------------------------------------------------------------------

class AppAffinity(BaseModel):
    """Per-app usage trait."""
    model_config = ConfigDict(extra="forbid")

    bundle_id: str
    focus_events: int = Field(..., ge=0)
    total_seconds: float = Field(0.0, ge=0)
    role: str | None = Field(
        None,
        description="LLM-inferred role in user's life (e.g. 'primary terminal', 'messaging hub').",
    )
    peer_apps: list[str] = Field(
        default_factory=list,
        description="Bundle IDs that co-occur frequently with this app in the same 30-min window.",
    )
    scope: Scope = Scope.mac_only
    stability: Stability


# ---------------------------------------------------------------------------
# Sequences (workflows)
# ---------------------------------------------------------------------------

class Sequence(BaseModel):
    """Frequent ordered app-focus sequence. Bundle IDs as strings; promoting
    to richer Step objects later does not require restructuring the model."""
    model_config = ConfigDict(extra="forbid")

    steps: list[str] = Field(..., min_length=2, description="Bundle IDs in order.")
    frequency: int = Field(..., ge=1)
    label: str | None = None
    automation_candidate: bool = False
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    rationale: str | None = None
    scope: Scope = Scope.mac_only


# ---------------------------------------------------------------------------
# Work modes (app clusters)
# ---------------------------------------------------------------------------

class WorkMode(BaseModel):
    """A cluster of apps the user uses together — a 'mental mode'."""
    model_config = ConfigDict(extra="forbid")

    name: str
    apps: list[str] = Field(..., min_length=1, description="Bundle IDs in this mode.")
    description: str
    scope: Scope = Scope.mac_only


# ---------------------------------------------------------------------------
# Projects (file-hotspot clusters)
# ---------------------------------------------------------------------------

class ProjectPhase(str, Enum):
    early_explore = "early-explore"
    deep_build = "deep-build"
    polish = "polish"
    dormant = "dormant"


class Project(BaseModel):
    """A project inferred from filesystem hotspots."""
    model_config = ConfigDict(extra="forbid")

    name: str
    paths: list[str] = Field(..., min_length=1)
    phase: ProjectPhase
    last_active: datetime | None = None
    related_apps: list[str] = Field(default_factory=list, description="Bundle IDs typically used alongside.")
    rationale: str | None = None
    stability: Stability


# ---------------------------------------------------------------------------
# Browsing
# ---------------------------------------------------------------------------

class DomainEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    domain: str
    visits: int = Field(..., ge=0)
    last_visit: datetime | None = None
    kind: str | None = Field(
        None,
        description="LLM classification: research/leisure/reference/tooling/communication.",
    )


class Browsing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope = Scope.mac_only  # browser history is technically per-device but treated as mac
    style: str | None = None
    research_share: float = Field(0.0, ge=0.0, le=1.0)
    leisure_share: float = Field(0.0, ge=0.0, le=1.0)
    reference_share: float = Field(0.0, ge=0.0, le=1.0)
    tab_hoarding_score: float = Field(0.0, ge=0.0, le=1.0)
    top_domains: list[DomainEntry] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Communication
# ---------------------------------------------------------------------------

class ContactClass(str, Enum):
    family = "family"
    close_friend = "close-friend"
    professional = "professional"
    acquaintance = "acquaintance"
    one_off = "one-off"
    unknown = "unknown"


class Contact(BaseModel):
    """A communication-graph contact. Identifier is always the c_<16hex> hash.

    Hash scheme: SHA-256(salt + normalize(handle))[:16], prefixed `c_`. Salt
    is a per-install random hex string generated on first run and persisted
    in the extractor's config.toml. Handles are normalized to lowercase with
    whitespace stripped before hashing, so the same person produces the same
    hash across the `messages` and `mail` sources.
    """
    model_config = ConfigDict(extra="forbid")

    contact_hash: str = Field(..., pattern=r"^c_[0-9a-f]{16}$")
    message_sent: int = Field(0, ge=0)
    message_received: int = Field(0, ge=0)
    mail_seen: int = Field(0, ge=0)
    total: int = Field(0, ge=0)
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    classification: ContactClass = ContactClass.unknown


class Communication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Scope = Scope.mac_only
    top_contacts: list[Contact] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Idiosyncrasies
# ---------------------------------------------------------------------------

class Idiosyncrasy(BaseModel):
    """An observation that doesn't fit other categories — 'midnight terminal
    burst', 'lunch media break', 'Friday Downloads cleanup'."""
    model_config = ConfigDict(extra="forbid")

    description: str
    when: str | None = Field(
        None,
        description="Human-readable time window, e.g. 'Thu 23:50 - Fri 00:30'.",
    )
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    stability: Stability | None = None


# ---------------------------------------------------------------------------
# Negative signals
# ---------------------------------------------------------------------------

class NegativeSignalKind(str, Enum):
    app_installed_not_used = "app_installed_not_used"
    abandoned_tab = "abandoned_tab"
    dismissed_notification_category = "dismissed_notification_category"
    declined_calendar_event = "declined_calendar_event"
    other = "other"


class NegativeSignal(BaseModel):
    """Something the user has rejected or avoided. Empty list is valid;
    the extractor doesn't currently mine these but the field exists for the
    customization-system to plan around."""
    model_config = ConfigDict(extra="forbid")

    kind: NegativeSignalKind
    target: str
    description: str | None = None
    last_seen: datetime | None = None


# ---------------------------------------------------------------------------
# Top-level model
# ---------------------------------------------------------------------------

class BehavioralProfile(BaseModel):
    """Top-level profile produced by `profile-extractor`, consumed by the
    future `customization-system`. Versioned by `schema_version`."""
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0.0"] = SCHEMA_VERSION
    generated_at: datetime

    coverage: Coverage
    rhythms: Rhythms
    app_affinities: list[AppAffinity] = Field(default_factory=list)
    sequences: list[Sequence] = Field(default_factory=list)
    work_modes: list[WorkMode] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    browsing: Browsing
    communication: Communication
    idiosyncrasies: list[Idiosyncrasy] = Field(default_factory=list)
    negative_signals: list[NegativeSignal] = Field(
        default_factory=list,
        description="Currently empty for all extractors; see customos_core.profile.NegativeSignalKind for the kinds the schema can carry.",
    )
    privacy: Privacy
