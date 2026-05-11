"""CLI entry point.

Commands:
  - run            apply the plan and hold it for process lifetime
  - plan-preview   print the LLM-selected plan as JSON, do not apply
  - vocabulary     list available customizations as a table
  - cache list     list cached plans on disk
  - cache clear    delete all cached plans

`run` is the only command that touches the system. Everything else is
read-only inspection or local-cache maintenance.
"""
from __future__ import annotations

import atexit
import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import objc
import typer
from AppKit import NSApp, NSApplication, NSApplicationActivationPolicyAccessory, NSEvent
from Foundation import NSObject, NSPoint, NSTimer
from loguru import logger
from rich.console import Console
from rich.table import Table

from customization_system.executor import PlanRunner
from customization_system.llm import get_llm
from customization_system.logging_setup import setup_logging
from customization_system.permissions import check_permissions, render_missing
from customization_system.plan import PlanEntry, select_plan
from customization_system.plan_cache import (
    cache_root,
    clear_cache,
    list_cached_keys,
    load_cached_metadata,
)
from customization_system.vocabulary import VOCABULARY


# Default profile path: walk up from this file to the workspace root, then
# down into profile-extractor/output. Resolved at import time so the CLI's
# --help reports it correctly.
_PACKAGE_DIR = Path(__file__).resolve().parent
_WORKSPACE_ROOT = _PACKAGE_DIR.parent.parent
_DEFAULT_PROFILE_PATH = _WORKSPACE_ROOT / "profile-extractor" / "output" / "profile.json"
_LOG_DIR = _PACKAGE_DIR.parent / "logs" / "runs"

app = typer.Typer(
    add_completion=False,
    help="Apply behavioural-profile-driven macOS customizations as runtime overlays.",
    no_args_is_help=True,
)


# ---- shared helpers ----

def _load_profile(path: Path) -> dict:
    if not path.exists():
        typer.echo(f"profile not found at {path}", err=True)
        raise typer.Exit(2)
    return json.loads(path.read_text())


# ---- commands ----

@app.command()
def vocabulary() -> None:
    """Print the catalog of available customizations."""
    console = Console()
    t = Table(title="customization-system vocabulary", show_lines=True)
    t.add_column("id", style="bold cyan", no_wrap=True)
    t.add_column("category", style="magenta", no_wrap=True)
    t.add_column("description")
    t.add_column("profile signals", style="dim")
    for e in VOCABULARY:
        t.add_row(e.id, e.category, e.description, e.profile_signals)
    console.print(t)


@app.command("plan-preview")
def plan_preview(
    profile: Path = typer.Option(
        _DEFAULT_PROFILE_PATH,
        "--profile",
        help="Path to profile.json produced by profile-extractor.",
    ),
    max_output_tokens: int = typer.Option(4000, "--max-output-tokens"),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Force a fresh LLM call; overwrite any cached plan for this key.",
    ),
) -> None:
    """Run plan selection and print the validated plan as JSON. Does not apply."""
    log_path = setup_logging(_LOG_DIR)
    logger.info("plan-preview start", profile=str(profile), log=str(log_path), no_cache=no_cache)
    prof = _load_profile(profile)
    llm = get_llm()
    validated, raw = select_plan(
        prof, VOCABULARY, llm,
        max_output_tokens=max_output_tokens,
        use_cache=not no_cache,
        profile_path=profile,
    )
    out = {
        "provider": llm.name,
        "model": llm.model,
        "source": raw.get("source", "llm") if isinstance(raw, dict) else "llm",
        "raw_response": raw,
        "validated_plan": [pe.model_dump() for pe in validated],
    }
    typer.echo(json.dumps(out, indent=2, default=str))


@app.command()
def run(
    profile: Path = typer.Option(
        _DEFAULT_PROFILE_PATH,
        "--profile",
        help="Path to profile.json produced by profile-extractor.",
    ),
    max_output_tokens: int = typer.Option(4000, "--max-output-tokens"),
    no_cache: bool = typer.Option(
        False,
        "--no-cache",
        help="Force a fresh LLM call; overwrite any cached plan for this key.",
    ),
) -> None:
    """Apply the LLM-selected plan, hold for process lifetime, revert on exit."""
    log_path = setup_logging(_LOG_DIR)
    logger.info("run start", profile=str(profile), log=str(log_path), no_cache=no_cache)

    perms = check_permissions()
    if not perms.all_granted:
        typer.echo(render_missing(perms), err=True)
        raise typer.Exit(3)

    prof = _load_profile(profile)
    # Make profile available to executors that need it (dock_dim_unused).
    from customization_system.context import set_profile

    set_profile(prof, profile)

    llm = get_llm()
    validated, raw = select_plan(
        prof, VOCABULARY, llm,
        max_output_tokens=max_output_tokens,
        use_cache=not no_cache,
        profile_path=profile,
    )
    if not validated:
        logger.warning("LLM returned no validated entries; nothing to apply")
        typer.echo("No customizations selected. Exiting cleanly.", err=True)
        return
    logger.info("validated plan", entries=[pe.model_dump() for pe in validated])

    # NSApplication setup before any NSWindow is touched.
    ns_app = NSApplication.sharedApplication()
    ns_app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    runner = PlanRunner(VOCABULARY)
    delegate = _AppDelegate.alloc().initWithRunner_(runner)
    ns_app.setDelegate_(delegate)
    # NSApplication.setDelegate_ does NOT retain in PyObjC; keep our own
    # strong ref on the runner (which outlives this function via atexit).
    runner._delegate = delegate  # type: ignore[attr-defined]

    atexit.register(runner.revert_all)

    runner.apply_plan(validated)
    if not runner.applied:
        logger.warning("no executors applied; exiting")
        return

    # Heartbeat NSTimer so the run loop wakes every 250ms. Each wake gives
    # CPython an opportunity to process queued POSIX signals — without this,
    # NSApp.run() blocks on a Mach port wait that never yields, and SIGINT /
    # SIGTERM stay queued indefinitely.
    heartbeat = NSTimer.scheduledTimerWithTimeInterval_repeats_block_(
        0.25, True, lambda _t: None
    )

    def _on_signal(signum, _frame):
        logger.info("signal received", signum=signum)
        NSApp().stop_(None)
        # NSApp.stop_ sets a flag that's only checked after the *next*
        # event is dequeued. Post a no-op event so the loop unblocks
        # immediately rather than waiting on the next user input.
        wake = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
            15,  # NSEventTypeApplicationDefined
            NSPoint(0, 0),
            0,
            0.0,
            0,
            None,
            0,
            0,
            0,
        )
        NSApp().postEvent_atStart_(wake, True)

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    typer.echo(
        f"Applied {len(runner.applied)} customization(s). "
        "Press Ctrl-C to revert and exit.",
        err=True,
    )

    try:
        ns_app.run()
    finally:
        try:
            heartbeat.invalidate()
        except Exception:
            pass
        runner.revert_all()
        logger.info("run exit")


class _AppDelegate(NSObject):
    """Application delegate that runs revert during NSApp.terminate_."""

    def initWithRunner_(self, runner):  # noqa: N802 (ObjC selector)
        self = objc.super(_AppDelegate, self).init()
        if self is None:
            return None
        self._runner = runner  # type: ignore[attr-defined]
        return self

    def applicationShouldTerminate_(self, sender):  # noqa: N802 (ObjC selector)
        try:
            self._runner.revert_all()  # type: ignore[attr-defined]
        except Exception:
            logger.exception("revert during terminate failed")
        return 1  # NSTerminateNow


cache_app = typer.Typer(
    add_completion=False,
    help="Inspect and clear the local plan cache (cache/plans/<hash>.json).",
    no_args_is_help=True,
)
app.add_typer(cache_app, name="cache")


def _format_age(iso_ts: str | None) -> str:
    if not iso_ts:
        return "?"
    try:
        ts = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
    except ValueError:
        return "?"
    delta = datetime.now(timezone.utc) - ts
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


@cache_app.command("list")
def cache_list() -> None:
    """List cached plans with provenance metadata."""
    console = Console()
    keys = list_cached_keys()
    if not keys:
        typer.echo(
            f"No cached plans. (cache directory: {cache_root()})",
            err=True,
        )
        return
    t = Table(title=f"plan cache — {cache_root()}", show_lines=False)
    t.add_column("key (12)", style="bold cyan", no_wrap=True)
    t.add_column("age", style="green", no_wrap=True)
    t.add_column("provider/model", no_wrap=True)
    t.add_column("entries", justify="right", no_wrap=True)
    t.add_column("profile", style="dim")
    for key in keys:
        meta = load_cached_metadata(key) or {}
        provider = meta.get("provider") or "?"
        model = meta.get("model") or "?"
        n_validated = meta.get("candidates_validated", "?")
        profile_path = meta.get("profile_path") or ""
        t.add_row(
            key[:12],
            _format_age(meta.get("timestamp")),
            f"{provider} / {model}",
            str(n_validated),
            profile_path,
        )
    console.print(t)


@cache_app.command("clear")
def cache_clear(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Delete every cached plan."""
    keys = list_cached_keys()
    if not keys:
        typer.echo("Cache is already empty.", err=True)
        return
    if not yes:
        confirm = typer.confirm(f"Delete {len(keys)} cached plan(s) at {cache_root()}?")
        if not confirm:
            typer.echo("Aborted.", err=True)
            raise typer.Exit(1)
    n = clear_cache()
    typer.echo(f"Deleted {n} cached plan(s).", err=True)


if __name__ == "__main__":
    app()
