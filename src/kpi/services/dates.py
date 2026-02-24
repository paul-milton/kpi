"""Date and sprint utilities using stdlib + dateutil."""
from __future__ import annotations
from datetime import date, timedelta
from typing import Any
from kpi.domain.models import SprintInfo

def build_sprint_calendar(cfg: dict[str, Any], jira_sprints: list[dict] | None = None) -> list[SprintInfo]:
    """Generate sprint calendar. Priority: jira_sprints > config.sprints > computed.

    jira_sprints: list of dicts from JiraAdapter.fetch_sprints()
    """
    proj = cfg.get("project", {})
    weeks_per = proj.get("sprint_duration_weeks", 3)
    today = date.today()

    # Priority 1: real Jira sprint data
    if jira_sprints:
        sprints = []
        for sp in jira_sprints:
            if not sp.get("start_date") or not sp.get("end_date"):
                continue
            s_start = parse_date(sp["start_date"])
            s_end = parse_date(sp["end_date"])
            is_cur = s_start <= today <= s_end
            dur_weeks = max((s_end - s_start).days // 7, 1)
            sprints.append(SprintInfo(
                number=sp.get("number", 0), name=sp.get("name", f"Sprint {sp.get('number', 0)}"),
                start_date=s_start.isoformat(), end_date=s_end.isoformat(),
                is_current=is_cur, is_past=today > s_end,
                current_week=min((today - s_start).days // 7 + 1, dur_weeks) if is_cur else 0))
        if sprints:
            return sprints

    # Priority 2: manual override in config
    if "sprints" in proj:
        return [SprintInfo(number=s["number"], name=f"Sprint {s['number']}",
                start_date=str(s["start"]), end_date=str(s["end"])) for s in proj["sprints"]]

    # Priority 3: compute from start/end/duration
    start = parse_date(proj.get("start_date", "2025-10-01"))
    end = parse_date(proj.get("end_date", "2026-09-30"))
    sprints = []; cur = start; num = 1
    while cur < end:
        s_end = min(cur + timedelta(days=weeks_per * 7 - 1), end)
        is_cur = cur <= today <= s_end
        sprints.append(SprintInfo(
            number=num, name=f"Sprint {num}",
            start_date=cur.isoformat(), end_date=s_end.isoformat(),
            is_current=is_cur, is_past=today > s_end,
            current_week=min((today - cur).days // 7 + 1, weeks_per) if is_cur else 0))
        cur = s_end + timedelta(days=1); num += 1
    return sprints

def find_current_sprint(sprints: list[SprintInfo]) -> SprintInfo | None:
    for s in sprints:
        if s.is_current: return s
    return None

def weeks_between(d1: date, d2: date) -> int:
    return max((d2 - d1).days // 7, 0)

def weeks_elapsed(start: str | date) -> int:
    d = parse_date(start) if isinstance(start, str) else start
    return max(weeks_between(d, date.today()), 1)

def weeks_remaining(end: str | date) -> int:
    d = parse_date(end) if isinstance(end, str) else end
    return max(weeks_between(date.today(), d), 1)

def parse_date(val: str | date) -> date:
    if isinstance(val, date): return val
    return date.fromisoformat(str(val))

def days_since_iso(iso_str: str | None) -> int | None:
    if not iso_str: return None
    try: return (date.today() - date.fromisoformat(iso_str[:10])).days
    except Exception: return None
