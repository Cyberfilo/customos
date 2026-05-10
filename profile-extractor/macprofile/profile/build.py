"""Assemble a typed BehavioralProfile + markdown narrative + hook_suggestions.json.

The profile is constructed as a `customos_core.BehavioralProfile` instance,
then serialized via `model_dump_json()`. LLM outputs (loose-dict-shaped to
keep prompts unchanged) are converted to schema types here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import duckdb
from loguru import logger

from customos_core import (
    SCHEMA_VERSION,
    AppAffinity,
    BehavioralProfile,
    Browsing,
    Communication,
    Contact,
    Coverage,
    CoverageRange,
    DomainEntry,
    Durability,
    Idiosyncrasy,
    Privacy,
    Project,
    ProjectPhase,
    Rhythms,
    Scope,
    Sequence,
    Stability,
    WorkMode,
)

from macprofile.analyze import pipeline as analysis_pipeline
from macprofile.normalize.device_scope import macos_native_sql
from macprofile.profile import render
from macprofile.settings import get_settings


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------

def _sources_analyzed(db_path) -> list[str]:
    native = macos_native_sql()
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            f"""
            SELECT source FROM events
            WHERE {native}
            GROUP BY 1
            HAVING COUNT(*) > 0
            ORDER BY 1
            """
        ).fetchall()
    finally:
        con.close()
    return [r[0] for r in rows]


def _parse_dt(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except ValueError:
            return None
    return None


def _durability(first_seen: datetime | None, last_seen: datetime | None, n_events: int) -> Durability:
    """Cheap, deterministic durability heuristic. Customisation-system uses
    this to decide whether to act confidently on a trait."""
    now = datetime.now(timezone.utc)
    if last_seen and last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    if first_seen and first_seen.tzinfo is None:
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    days_since_last = (now - last_seen).days if last_seen else 9999
    days_since_first = (now - first_seen).days if first_seen else 9999

    if days_since_last >= 30:
        return Durability.fading
    if days_since_first <= 30 and n_events < 100:
        return Durability.emerging
    return Durability.durable


# ----------------------------------------------------------------------------
# Build pipeline
# ----------------------------------------------------------------------------

def build_profile(skip_llm: bool = False) -> BehavioralProfile:
    s = get_settings()
    analyses = analysis_pipeline.run_all()
    generated_at = datetime.now(timezone.utc)

    # ---------- coverage / privacy ----------
    cov_d = analyses["coverage"]
    raw = cov_d.get("raw_range") or {}
    coverage = Coverage(
        earliest=_parse_dt(cov_d.get("earliest")),
        latest=_parse_dt(cov_d.get("latest")),
        raw_range=CoverageRange(
            earliest=_parse_dt(raw.get("earliest")),
            latest=_parse_dt(raw.get("latest")),
        ),
        total_events=int(cov_d.get("total_events", 0)),
        sources_active=int(cov_d.get("sources_active", 0)),
        categories_seen=int(cov_d.get("categories_seen", 0)),
        days_with_events=int(cov_d.get("days_with_events", 0)),
        active_day_threshold=int(cov_d.get("active_day_threshold", 10)),
    )
    privacy = Privacy(
        deep_content_analysis=s.privacy.deep_content_analysis,
        sources_analyzed=_sources_analyzed(s.paths.db_path),
        events_analyzed=coverage.total_events,
    )

    # ---------- rhythms (matrices only for now; LLM adds narrative below) ----------
    rhythms_d = analyses["rhythms"]
    rhythms = Rhythms(
        hourly_by_category=rhythms_d.get("hourly_by_category", {}),
        weekday_by_category=rhythms_d.get("weekday_by_category", {}),
        hour_by_weekday=rhythms_d.get("hour_by_weekday", []),
    )

    # ---------- browsing (raw domains for now; LLM adds style/shares below) ----------
    domains_raw = analyses["communication"]["domain_frequency"][:30]
    browsing = Browsing(
        top_domains=[
            DomainEntry(
                domain=d["domain"],
                visits=int(d["visits"]),
                last_visit=_parse_dt(d.get("last_visit")),
            )
            for d in domains_raw
        ],
    )

    # ---------- communication ----------
    top_contacts_d = analyses["communication"]["top_contacts"]
    communication = Communication(
        top_contacts=[
            Contact(
                contact_hash=c["contact_hash"],
                message_sent=int(c["sent"]),
                message_received=int(c["received"]),
                mail_seen=int(c["mail"]),
                total=int(c["total"]),
                first_seen=_parse_dt(c.get("first_seen")),
                last_seen=_parse_dt(c.get("last_seen")),
            )
            for c in top_contacts_d
        ],
    )

    # ---------- app_affinities (uses analyzer output + cohabitation for peers) ----------
    cohab = analyses["cohabitation"]
    peer_map: dict[str, list[str]] = {}
    for pair in cohab[:80]:
        peer_map.setdefault(pair["a"], []).append(pair["b"])
        peer_map.setdefault(pair["b"], []).append(pair["a"])
    app_affinities: list[AppAffinity] = []
    for a in analyses["communication"]["app_affinity"]:
        first = _parse_dt(a.get("first_seen"))
        last = _parse_dt(a.get("last_seen"))
        app_affinities.append(
            AppAffinity(
                bundle_id=a["bundle"],
                focus_events=int(a["focus_events"]),
                total_seconds=float(a.get("total_seconds", 0.0)),
                peer_apps=peer_map.get(a["bundle"], [])[:5],
                stability=Stability(
                    based_on_events=int(a["focus_events"]),
                    first_seen=first or generated_at,
                    last_seen=last or generated_at,
                    durability=_durability(first, last, int(a["focus_events"])),
                ),
            )
        )

    # ---------- LLM enrichments ----------
    sequences: list[Sequence] = []
    work_modes: list[WorkMode] = []
    projects: list[Project] = []
    idiosyncrasies: list[Idiosyncrasy] = []
    hooks_payload: list[dict[str, Any]] | None = None
    llm_skipped: str | None = None

    if not skip_llm:
        try:
            from macprofile.analyze import llm
            engine = llm.get_llm()
            logger.info(f"LLM: using {type(engine).__name__}")

            # workflows -> sequences
            try:
                wfs = llm.label_workflows(analyses["workflows"], engine)
                sequences = [
                    Sequence(
                        steps=w.sequence,
                        frequency=w.frequency,
                        label=w.label,
                        automation_candidate=w.automation_candidate,
                        confidence=w.confidence,
                        rationale=w.rationale,
                    )
                    for w in wfs
                ]
            except Exception as e:
                logger.exception(f"workflow labelling failed: {e}")

            # work modes
            try:
                modes = llm.label_work_modes(
                    analyses["cohabitation"], analyses["communication"]["app_affinity"], engine
                )
                work_modes = [
                    WorkMode(name=m.name, apps=m.apps, description=m.description)
                    for m in modes
                ]
            except Exception as e:
                logger.exception(f"work modes failed: {e}")

            # rhythm narrative -> attach to rhythms
            try:
                rd = llm.describe_rhythm(analyses["rhythms"], engine)
                rhythms = rhythms.model_copy(update={
                    "workday_window": rd.workday_window,
                    "leisure_window": rd.leisure_window,
                    "notable_quirks": rd.notable_quirks,
                    "summary": rd.summary,
                })
            except Exception as e:
                logger.exception(f"rhythm description failed: {e}")

            # projects
            try:
                projs = llm.infer_projects(analyses["files"]["directory_hotspots"], engine)
                dir_hotspots_by_path = {
                    d["directory"]: d for d in analyses["files"]["directory_hotspots"]
                }
                for p in projs:
                    # Sum events and date span across the project's paths
                    n_events = sum(
                        int(dir_hotspots_by_path.get(path, {}).get("count", 0))
                        for path in p.paths
                    )
                    firsts = [_parse_dt(dir_hotspots_by_path.get(path, {}).get("first"))
                              for path in p.paths]
                    lasts  = [_parse_dt(dir_hotspots_by_path.get(path, {}).get("last"))
                              for path in p.paths]
                    firsts = [f for f in firsts if f]
                    lasts = [last for last in lasts if last]
                    first_seen = min(firsts) if firsts else generated_at
                    last_seen = max(lasts) if lasts else generated_at
                    try:
                        phase = ProjectPhase(p.phase)
                    except ValueError:
                        phase = ProjectPhase.dormant
                    projects.append(
                        Project(
                            name=p.name,
                            paths=p.paths,
                            phase=phase,
                            last_active=last_seen,
                            rationale=p.rationale,
                            stability=Stability(
                                based_on_events=n_events,
                                first_seen=first_seen,
                                last_seen=last_seen,
                                durability=_durability(first_seen, last_seen, n_events),
                            ),
                        )
                    )
            except Exception as e:
                logger.exception(f"project inference failed: {e}")

            # browsing
            try:
                bp = llm.describe_browsing(
                    analyses["communication"]["domain_frequency"], {}, engine
                )
                kind_by_domain = {
                    item["domain"]: item.get("kind")
                    for item in bp.notable_domains_classification
                }
                browsing = browsing.model_copy(update={
                    "style": bp.style,
                    "research_share": bp.research_share,
                    "leisure_share": bp.leisure_share,
                    "reference_share": bp.reference_share,
                    "tab_hoarding_score": bp.tab_hoarding_score,
                    "top_domains": [
                        d.model_copy(update={"kind": kind_by_domain.get(d.domain)})
                        for d in browsing.top_domains
                    ],
                })
            except Exception as e:
                logger.exception(f"browsing profile failed: {e}")

            # quirks + hooks
            try:
                summary_for_quirks = {
                    "rhythm": {
                        "workday_window": rhythms.workday_window,
                        "leisure_window": rhythms.leisure_window,
                        "notable_quirks": rhythms.notable_quirks,
                        "summary": rhythms.summary,
                    },
                    "work_modes": [m.model_dump() for m in work_modes],
                    "top_workflows": [s.model_dump() for s in sequences[:15]],
                    "top_apps": analyses["communication"]["app_affinity"][:15],
                    "top_domains": analyses["communication"]["domain_frequency"][:15],
                    "directory_hotspots": analyses["files"]["directory_hotspots"][:15],
                }
                qh = llm.find_quirks_and_hooks(summary_for_quirks, engine)
                # quirks (list[str]) -> Idiosyncrasy (with description)
                idiosyncrasies = [
                    Idiosyncrasy(description=q, confidence=0.6) for q in qh.quirks
                ]
                hooks_payload = [h.model_dump() for h in qh.hooks]
            except Exception as e:
                logger.exception(f"quirks/hooks failed: {e}")

        except RuntimeError as e:
            logger.warning(f"skipping LLM: {e}")
            llm_skipped = str(e)

    profile = BehavioralProfile(
        schema_version=SCHEMA_VERSION,
        generated_at=generated_at,
        coverage=coverage,
        rhythms=rhythms,
        app_affinities=app_affinities,
        sequences=sequences,
        work_modes=work_modes,
        projects=projects,
        browsing=browsing,
        communication=communication,
        idiosyncrasies=idiosyncrasies,
        negative_signals=[],  # extractor does not currently mine these
        privacy=privacy,
    )

    out_json = s.paths.output_dir / "profile.json"
    out_json.write_text(profile.model_dump_json(indent=2))
    logger.info(f"wrote {out_json}  ({out_json.stat().st_size:,} bytes)")

    hooks_path = s.paths.output_dir / "hook_suggestions.json"
    hook_doc = {
        "_meta": {
            "generated_at": generated_at.isoformat(),
            "kind": "llm_suggestions",
            "status": "advisory",
            "warning": (
                "These hooks are LLM-generated suggestions, not specifications. "
                "Triggers reference predicates that may not be computable by any "
                "current CustomOS subsystem; treat them as inspiration for future "
                "automation work, not as a contract."
            ),
            "predicate_vocabulary_spec": "not yet defined — see HANDOFF.md",
        },
        "suggestions": hooks_payload or [],
    }
    hooks_path.write_text(json.dumps(hook_doc, indent=2, default=str))
    logger.info(f"wrote {hooks_path}  ({hooks_path.stat().st_size:,} bytes)")

    md = render.render_markdown(profile, hooks_filename=hooks_path.name, llm_skipped=llm_skipped)
    out_md = s.paths.output_dir / "profile.md"
    out_md.write_text(md)
    logger.info(f"wrote {out_md}  ({out_md.stat().st_size:,} bytes)")

    return profile
