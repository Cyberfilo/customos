"""Run all analyzers and dump JSON summaries to output/analyses.json."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
from loguru import logger

from macprofile.analyze import cohabitation, communication, files, rhythms, sessions, workflows
from macprofile.settings import get_settings


def run_all() -> dict:
    s = get_settings()
    if not s.paths.db_path.exists():
        raise FileNotFoundError(f"warehouse not found at {s.paths.db_path}")
    con = duckdb.connect(str(s.paths.db_path), read_only=True)
    try:
        out = {
            "coverage": rhythms.coverage(con),
            "rhythms": {
                "hourly_by_category": rhythms.hourly_by_category(con),
                "weekday_by_category": rhythms.weekday_by_category(con),
                "hour_by_weekday": rhythms.hour_by_weekday(con),
            },
            "sessions_summary": None,
            "workflows": [],
            "cohabitation": cohabitation.cohabitation_pairs(con),
            "files": {
                "top_files": files.top_files(con),
                "directory_hotspots": files.directory_hotspots(con),
            },
            "communication": {
                "top_contacts": communication.top_contacts(con),
                "domain_frequency": communication.domain_frequency(con),
                "app_affinity": communication.app_affinity(con),
            },
        }
        sess = sessions.app_focus_sessions(con, gap_minutes=5)
        out["sessions_summary"] = sessions.session_summary(sess)
        seqs = workflows.app_sequences_within_window(con)
        out["workflows"] = workflows.top_n_grams(seqs)
    finally:
        con.close()
    target = s.paths.output_dir / "analyses.json"
    target.write_text(json.dumps(out, indent=2, default=str))
    logger.info(f"wrote {target}  ({target.stat().st_size:,} bytes)")
    return out
