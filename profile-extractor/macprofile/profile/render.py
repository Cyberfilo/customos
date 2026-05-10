"""Markdown rendering of a typed BehavioralProfile.

The output is a deterministic narrative. The schema gives us stability and
scope; we surface them where it costs nothing (project phase + durability
on the project line, durability badge on the top app rows). Length stays
in the ~12-16 KB range matched to the previous run.
"""
from __future__ import annotations

from customos_core import BehavioralProfile


def _dur_badge(d: str) -> str:
    return {"durable": "●", "emerging": "○", "fading": "◌"}.get(d, "")


def render_markdown(
    profile: BehavioralProfile,
    hooks_filename: str = "hook_suggestions.json",
    llm_skipped: str | None = None,
) -> str:
    p = profile
    lines: list[str] = []
    lines.append("# Behavioural profile")
    lines.append("")
    lines.append(f"_Generated {p.generated_at.isoformat()}  ·  schema {p.schema_version}_")
    lines.append("")
    if llm_skipped:
        lines.append(f"> ⚠ LLM analysis skipped: `{llm_skipped}`. Profile contains structured aggregates only.")
        lines.append("")

    # Coverage
    cov = p.coverage
    lines.append("## Coverage")
    earliest = cov.earliest.isoformat() if cov.earliest else "?"
    latest = cov.latest.isoformat() if cov.latest else "?"
    lines.append(
        f"- {cov.total_events:,} events from {cov.sources_active} sources, "
        f"{cov.days_with_events:,} active days from {earliest} to {latest} "
        f"(active day = ≥{cov.active_day_threshold} events)"
    )
    raw = cov.raw_range
    if raw.earliest and raw.latest:
        lines.append(
            f"- Raw range (unclipped): {raw.earliest.isoformat()} to {raw.latest.isoformat()} — "
            "outliers from old photos and future-dated calendar events are excluded above."
        )
    lines.append("")

    # Rhythm
    r = p.rhythms
    if r.workday_window or r.summary:
        lines.append("## Rhythm")
        if r.workday_window:
            lines.append(f"- Workday window: {r.workday_window}")
        if r.leisure_window:
            lines.append(f"- Leisure window: {r.leisure_window}")
        if r.notable_quirks:
            lines.append("- Notable quirks:")
            for q in r.notable_quirks:
                lines.append(f"  - {q}")
        lines.append("")
        if r.summary:
            lines.append(f"> {r.summary}")
            lines.append("")

    # Work modes
    if p.work_modes:
        lines.append("## Work modes")
        for m in p.work_modes:
            apps = ", ".join(m.apps)
            lines.append(f"- **{m.name}** — {apps}")
            lines.append(f"  - {m.description}")
        lines.append("")

    # Sequences (workflows)
    if p.sequences:
        lines.append("## Top workflows")
        for sq in p.sequences[:10]:
            arrow = " → ".join(sq.steps)
            star = " ⚙️" if sq.automation_candidate else ""
            label = sq.label or "(unlabelled)"
            lines.append(f"- ({sq.frequency}× ) **{label}**{star}")
            lines.append(f"    `{arrow}`")
            if sq.rationale:
                lines.append(f"    _{sq.rationale}_")
        lines.append("")

    # Projects
    if p.projects:
        lines.append("## Inferred projects")
        for pr in p.projects:
            badge = _dur_badge(pr.stability.durability.value)
            lines.append(f"- {badge} **{pr.name}** ({pr.phase.value})")
            for path in pr.paths[:5]:
                lines.append(f"  - `{path}`")
            if pr.rationale:
                lines.append(f"  - _{pr.rationale}_")
        lines.append("")

    # Browsing
    b = p.browsing
    if b.style:
        lines.append("## Browsing")
        lines.append(f"- Style: **{b.style}**")
        lines.append(
            f"- Research / Leisure / Reference share: "
            f"{b.research_share:.0%} / {b.leisure_share:.0%} / {b.reference_share:.0%}"
        )
        lines.append(f"- Tab-hoarding score: **{b.tab_hoarding_score:.2f}** / 1.0")
        lines.append("")

    # Idiosyncrasies
    if p.idiosyncrasies:
        lines.append("## Idiosyncrasies")
        for ido in p.idiosyncrasies:
            when = f" ({ido.when})" if ido.when else ""
            lines.append(f"- {ido.description}{when}")
        lines.append("")

    # Hooks pointer
    lines.append("## Customisation hooks")
    lines.append(
        f"LLM-suggested customisation hooks were moved out of `profile.json` and now live in "
        f"`output/{hooks_filename}`. They are advisory — triggers reference predicates that "
        "may not yet be computable by any CustomOS subsystem. Treat them as inspiration for "
        "future automation work, not as a contract."
    )
    lines.append("")

    # Top apps (raw, with stability badges)
    lines.append("## Top apps (raw)")
    for a in p.app_affinities[:15]:
        badge = _dur_badge(a.stability.durability.value)
        lines.append(f"- {badge} {a.focus_events:>5}× — {a.bundle_id}")
    lines.append("")

    # Top domains
    lines.append("## Top domains (raw)")
    for d in b.top_domains[:15]:
        kind = f"  ·  _{d.kind}_" if d.kind else ""
        lines.append(f"- {d.visits:>5} visits — {d.domain}{kind}")

    return "\n".join(lines) + "\n"
