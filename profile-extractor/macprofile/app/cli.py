"""macprofile CLI."""
from __future__ import annotations

import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import typer
from loguru import logger
from rich.console import Console
from rich.table import Table

from macprofile.preflight import FDA_INSTRUCTIONS, run_preflight
from macprofile.settings import get_settings

app = typer.Typer(no_args_is_help=True, add_completion=False)
console = Console()

EXTRACTOR_REGISTRY: dict[str, str] = {
    # name -> "module:Class"
    "spotlight":      "macprofile.extractors.spotlight:SpotlightExtractor",
    "safari":         "macprofile.extractors.browsers:SafariExtractor",
    "chrome":         "macprofile.extractors.browsers:ChromeExtractor",
    "brave":          "macprofile.extractors.browsers:BraveExtractor",
    "knowledgec":     "macprofile.extractors.knowledgec:KnowledgeCExtractor",
    "sfl2":           "macprofile.extractors.sfl2:SFL2Extractor",
    "shell":          "macprofile.extractors.shell_history:ShellHistoryExtractor",
    "calendar":       "macprofile.extractors.calendar:CalendarExtractor",
    "notes":          "macprofile.extractors.notes:NotesExtractor",
    "reminders":      "macprofile.extractors.reminders:RemindersExtractor",
    "biome":          "macprofile.extractors.biome:BiomeExtractor",
    "photos":         "macprofile.extractors.photos:PhotosExtractor",
    "messages":       "macprofile.extractors.messages:MessagesExtractor",
    "mail":           "macprofile.extractors.mail:MailExtractor",
}


def _load(spec: str):
    mod, cls = spec.split(":")
    import importlib
    return getattr(importlib.import_module(mod), cls)


@app.command()
def preflight():
    """Probe protected paths and print FDA instructions if any are denied."""
    ok, results = run_preflight()
    table = Table(title="Full Disk Access preflight")
    table.add_column("Source")
    table.add_column("Status")
    table.add_column("Path", overflow="fold")
    for r in results:
        style = {"ok": "green", "missing": "yellow", "denied": "red"}[r.status]
        table.add_row(r.label, f"[{style}]{r.status}[/]", str(r.path))
    console.print(table)
    if not ok:
        venv_python = Path(sys.executable)
        console.print(FDA_INSTRUCTIONS.format(venv_python=venv_python), style="red")
        raise typer.Exit(code=1)
    console.print("[green]All probed sources are reachable.[/]")


@app.command()
def extract(
    only: list[str] = typer.Option(None, "--only", help="Run only these extractors"),
    skip: list[str] = typer.Option(None, "--skip", help="Skip these extractors"),
    all_: bool = typer.Option(False, "--all", help="Run every registered extractor"),
):
    """Run extractors and load events into the warehouse."""
    s = get_settings()
    from macprofile.normalize.load import Warehouse
    wh = Warehouse(s.paths.db_path)

    selected: list[str]
    if only:
        selected = list(only)
    elif all_:
        selected = list(EXTRACTOR_REGISTRY.keys())
    else:
        console.print("Pass --all or --only <name> [<name>...]")
        raise typer.Exit(code=2)
    if skip:
        selected = [x for x in selected if x not in set(skip)]

    summary: list[tuple[str, str, int, int, float]] = []
    for name in selected:
        spec = EXTRACTOR_REGISTRY.get(name)
        if not spec:
            console.print(f"[red]unknown extractor: {name}[/]")
            continue
        try:
            Cls = _load(spec)
        except ImportError as e:
            console.print(f"[yellow]{name}: not implemented ({e})[/]")
            summary.append((name, "missing", 0, 0, 0.0))
            continue
        ext = Cls(s)
        run_id = str(uuid4())
        started = datetime.now(timezone.utc)
        t0 = time.time()
        try:
            seen, loaded = wh.insert_events(ext.extract())
        except PermissionError as e:
            console.print(f"[red]{name}: permission denied ({e})[/]")
            summary.append((name, "denied", 0, 0, time.time() - t0))
            continue
        except FileNotFoundError as e:
            console.print(f"[yellow]{name}: source missing ({e})[/]")
            summary.append((name, "missing", 0, 0, time.time() - t0))
            continue
        except Exception as e:
            logger.exception(f"{name} crashed")
            console.print(f"[red]{name}: ERROR {e}[/]")
            summary.append((name, "error", 0, 0, time.time() - t0))
            continue
        elapsed = time.time() - t0
        wh.record_run(name, run_id, started, datetime.now(timezone.utc), seen, loaded, "")
        summary.append((name, "ok", seen, loaded, elapsed))
        console.print(f"[green]{name}: seen={seen} loaded={loaded} in {elapsed:.1f}s")

    t = Table(title="Extraction summary")
    t.add_column("source"); t.add_column("status"); t.add_column("seen"); t.add_column("loaded"); t.add_column("sec")
    for row in summary:
        style = {"ok": "green", "missing": "yellow", "denied": "red", "error": "red"}.get(row[1], "")
        t.add_row(row[0], f"[{style}]{row[1]}[/]", str(row[2]), str(row[3]), f"{row[4]:.1f}")
    console.print(t)

    by_src = wh.counts_by_source()
    console.print("\n[bold]Total rows by source[/]")
    for src, n in by_src:
        console.print(f"  {src:40s} {n}")
    console.print(f"\n[bold]Warehouse total: {wh.total()} events[/]")
    wh.close()


@app.command()
def status():
    s = get_settings()
    from macprofile.normalize.load import Warehouse
    wh = Warehouse(s.paths.db_path)
    console.print(f"DB: {s.paths.db_path}  total={wh.total()}")
    for src, n in wh.counts_by_source():
        console.print(f"  {src:40s} {n}")
    console.print()
    for cat, n in wh.counts_by_category():
        console.print(f"  category {cat:30s} {n}")
    wh.close()


@app.command()
def purge(
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm destructive action"),
):
    """Delete all extracts and the warehouse. Irreversible."""
    s = get_settings()
    if not yes:
        console.print("[red]Pass --yes to confirm[/]"); raise typer.Exit(code=2)
    for p in [s.paths.db_path, s.paths.raw_dir, s.paths.output_dir]:
        if p.exists():
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            console.print(f"removed {p}")
    s.paths.ensure()


@app.command()
def analyze():
    """Run all analyzers and write summaries under output/."""
    from macprofile.analyze import pipeline
    pipeline.run_all()


@app.command()
def profile(
    skip_llm: bool = typer.Option(False, "--skip-llm", help="Build profile.json from analyzers without LLM labels"),
):
    from macprofile.profile.build import build_profile
    build_profile(skip_llm=skip_llm)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8766):
    import uvicorn
    uvicorn.run("macprofile.app.api:api", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
