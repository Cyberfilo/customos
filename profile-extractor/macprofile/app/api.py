"""FastAPI query layer."""
from __future__ import annotations

import json
from pathlib import Path

import duckdb
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, PlainTextResponse

from macprofile.settings import get_settings


def make_app() -> FastAPI:
    app = FastAPI(title="macprofile", version="0.1.0")
    s = get_settings()

    def db():
        return duckdb.connect(str(s.paths.db_path), read_only=True)

    @app.get("/health")
    def health():
        return {"ok": True, "db_exists": s.paths.db_path.exists()}

    @app.get("/profile")
    def profile():
        path = s.paths.output_dir / "profile.json"
        if not path.exists():
            raise HTTPException(404, detail="profile.json not built yet — run macprofile profile")
        return JSONResponse(content=json.loads(path.read_text()))

    @app.get("/profile.md", response_class=PlainTextResponse)
    def profile_md():
        path = s.paths.output_dir / "profile.md"
        if not path.exists():
            raise HTTPException(404, detail="profile.md not built yet")
        return PlainTextResponse(path.read_text())

    @app.get("/events/by-source")
    def events_by_source():
        with db() as con:
            rows = con.execute(
                "SELECT source, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        return {src: int(n) for src, n in rows}

    @app.get("/events/by-category")
    def events_by_category():
        with db() as con:
            rows = con.execute(
                "SELECT category, COUNT(*) FROM events GROUP BY 1 ORDER BY 2 DESC"
            ).fetchall()
        return {cat: int(n) for cat, n in rows}

    @app.get("/apps/top")
    def apps_top(limit: int = 30):
        with db() as con:
            rows = con.execute(
                """
                SELECT target, COUNT(*) AS focus_events,
                       MIN(ts_local) AS first_seen, MAX(ts_local) AS last_seen
                FROM events
                WHERE category IN ('app_focus','app_usage','app_launch')
                  AND target_kind = 'app'
                  AND target NOT IN ('(unknown)','')
                GROUP BY 1 ORDER BY 2 DESC LIMIT ?
                """,
                [limit],
            ).fetchall()
        return [
            {"bundle": r[0], "focus_events": int(r[1]),
             "first_seen": r[2].isoformat() if r[2] else None,
             "last_seen": r[3].isoformat() if r[3] else None}
            for r in rows
        ]

    @app.get("/files/hotspots")
    def files_hotspots(limit: int = 30):
        from macprofile.analyze.files import directory_hotspots
        with db() as con:
            return directory_hotspots(con, top=limit)

    @app.get("/rhythms/hour-by-weekday")
    def hour_by_weekday():
        from macprofile.analyze.rhythms import hour_by_weekday as h
        with db() as con:
            return h(con)

    @app.get("/query")
    def query(
        q: str = Query(..., description="Natural-language-ish: 'tuesday morning'"),
        limit: int = 50,
    ):
        """Ad-hoc query. Currently keyword-driven; the LLM router goes here later."""
        with db() as con:
            # Hour windows
            qq = q.lower()
            mapping = {
                "morning": "EXTRACT(hour FROM ts_local) BETWEEN 6 AND 11",
                "afternoon": "EXTRACT(hour FROM ts_local) BETWEEN 12 AND 17",
                "evening": "EXTRACT(hour FROM ts_local) BETWEEN 18 AND 22",
                "night": "EXTRACT(hour FROM ts_local) >= 23 OR EXTRACT(hour FROM ts_local) < 6",
            }
            time_clauses = [v for k, v in mapping.items() if k in qq]
            day_map = {
                "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                "friday": 4, "saturday": 5, "sunday": 6,
            }
            day_clauses = [
                f"((EXTRACT(dow FROM ts_local)::INT + 6) % 7) = {idx}"
                for k, idx in day_map.items() if k in qq
            ]
            where = "1=1"
            if time_clauses:
                where += " AND (" + " OR ".join(time_clauses) + ")"
            if day_clauses:
                where += " AND (" + " OR ".join(day_clauses) + ")"
            rows = con.execute(
                f"""
                SELECT category, target, COUNT(*) AS n
                FROM events
                WHERE {where}
                GROUP BY 1,2 ORDER BY n DESC LIMIT ?
                """,
                [limit],
            ).fetchall()
        return [{"category": r[0], "target": r[1], "count": int(r[2])} for r in rows]

    return app


api = make_app()
