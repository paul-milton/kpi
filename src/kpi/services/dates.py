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
                current_week=min((today - s_start).days // 7 + 1, dur_weeks) if is_cur else 0,
                jira_id=int(sp.get("id", 0)) if sp.get("id") else 0))
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

def _fr_holidays(year: int) -> set[date]:
    """Fixed + moveable French public holidays for a given year."""
    from datetime import timedelta as _td
    holidays = {
        date(year, 1, 1), date(year, 5, 1), date(year, 5, 8),
        date(year, 7, 14), date(year, 8, 15), date(year, 11, 1),
        date(year, 11, 11), date(year, 12, 25),
    }
    # Easter (anonymous Gregorian algorithm)
    a, b, c = year % 19, year // 100, year % 100
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = (h + l - 7 * m + 114) % 31 + 1
    easter = date(year, month, day)
    holidays.add(easter + _td(days=1))   # Lundi de Pâques
    holidays.add(easter + _td(days=39))  # Ascension
    holidays.add(easter + _td(days=50))  # Lundi de Pentecôte
    return holidays


def business_days_france(d1: date, d2: date) -> int:
    """Count business days (Mon-Fri excl. French holidays) between d1 and d2 (exclusive of d2)."""
    if d1 >= d2:
        return 0
    years = set(range(d1.year, d2.year + 1))
    holidays: set[date] = set()
    for y in years:
        holidays |= _fr_holidays(y)
    count = 0
    cur = d1
    one_day = timedelta(days=1)
    while cur < d2:
        if cur.weekday() < 5 and cur not in holidays:
            count += 1
        cur += one_day
    return count


def days_since_iso(iso_str: str | None) -> int | None:
    if not iso_str: return None
    try: return (date.today() - date.fromisoformat(iso_str[:10])).days
    except Exception: return None
