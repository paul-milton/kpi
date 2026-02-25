"""FastAPI live server - serves KPI reports with TTL caching."""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from kpi.adapters.jira_adapter import JiraAdapter
from kpi.config.loader import load_config
from kpi.services.calculator import KPICalculator
from kpi.services.dates import parse_date
from kpi.services.renderer import ReportRenderer
from kpi.services.store import SnapshotStore
from kpi.services.tagger import SemanticTagger


def create_app(cfg: dict | None = None, cache_ttl: int = 300) -> FastAPI:
    """Create FastAPI app with routes and caching."""
    app = FastAPI(title="KPI Generator")
    app.state.cfg = cfg or load_config()
    app.state.cache_ttl = cache_ttl
    app.state.cache: dict[str, Any] = {}  # {report, html_preview, html_date, html_project, etag_*, ts}

    def _fetch_report() -> Any:
        """Fetch Jira data and compute report, with TTL cache."""
        cache = app.state.cache
        now = time.time()
        if cache.get("report") and (now - cache.get("ts", 0)) < app.state.cache_ttl:
            return cache["report"]

        cfg = app.state.cfg
        j = JiraAdapter(cfg)
        t = SemanticTagger(cfg)
        stories = j.fetch_all_stories()
        try:
            vels = j.fetch_velocities()
        except Exception:
            vels = []
        try:
            sprints = j.fetch_sprints()
        except Exception:
            sprints = []
        untag = t.find_untagged(stories)

        store = SnapshotStore(cfg)
        calc = KPICalculator(cfg)
        sn = cfg.get("project", {}).get("current_sprint", 1)
        prev = store.load_previous_sprint(sn)
        report, _ = calc.compute(stories, vels, untag, prev, jira_sprints=sprints), store

        rr = ReportRenderer()
        html_preview = rr.render_preview(report)
        html_date = rr.render_date(report)
        html_project = rr.render_project(report)

        cache.update({
            "report": report,
            "html_preview": html_preview,
            "html_date": html_date,
            "html_project": html_project,
            "etag_preview": hashlib.md5(html_preview.encode()).hexdigest(),
            "etag_date": hashlib.md5(html_date.encode()).hexdigest(),
            "etag_project": hashlib.md5(html_project.encode()).hexdigest(),
            "ts": now,
            "last_modified": datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        })
        return report

    def _serve_report(request: Request, key: str) -> Response:
        """Serve a cached report with ETag/Last-Modified headers."""
        _fetch_report()
        cache = app.state.cache
        etag = cache.get(f"etag_{key}", "")
        last_modified = cache.get("last_modified", "")

        # Conditional request: If-None-Match
        if_none_match = request.headers.get("if-none-match", "")
        if if_none_match and if_none_match.strip('"') == etag:
            return Response(status_code=304)

        # Conditional request: If-Modified-Since
        if_modified = request.headers.get("if-modified-since", "")
        if if_modified and if_modified == last_modified:
            return Response(status_code=304)

        html = cache.get(f"html_{key}", "")
        return HTMLResponse(
            content=html,
            headers={
                "ETag": f'"{etag}"',
                "Last-Modified": last_modified,
                "Cache-Control": f"public, max-age={app.state.cache_ttl}",
            },
        )

    @app.get("/")
    def root():
        return RedirectResponse(url="/preview")

    @app.get("/preview")
    def preview(request: Request):
        return _serve_report(request, "preview")

    @app.get("/date")
    def report_date(request: Request):
        return _serve_report(request, "date")

    @app.get("/project")
    def report_project(request: Request):
        return _serve_report(request, "project")

    return app
