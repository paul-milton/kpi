"""Jira adapter — fetch stories, velocities, manage labels.

Unknown statuses on stories older than N days → auto-done.
"""
from __future__ import annotations
import re
from typing import Any
import structlog
from atlassian import Jira
from kpi.adapters.network import resolve_proxies, resolve_ssl
from kpi.domain.models import COMPLETED_STATUSES, JiraStory, SprintVelocity, StoryStatus
from kpi.services.dates import days_since_iso

logger = structlog.get_logger()


def safe_int(value: Any) -> int:
    """Convert any value to int safely. None/float/str/garbage → 0."""
    if value is None: return 0
    try: return int(float(value))
    except (ValueError, TypeError): return 0


class JiraAdapter:
    """Adapter for Jira Server/Data Center REST API."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        j = cfg["jira"]
        self._project = j["project_key"]
        self._status_map = j["status_mapping"]
        self._sp_field = j.get("story_points_field", "customfield_10106")
        self._legacy_prefixes = j.get("legacy_label_prefixes", [])
        self._done_after_days = j.get("unknown_status_done_after_days", 21)
        self._sprint_weeks = cfg.get("project", {}).get("sprint_duration_weeks", 3)
        self._client = Jira(url=j["url"], token=j["token"],
                            verify_ssl=resolve_ssl(cfg), proxies=resolve_proxies())

    def fetch_all_stories(self) -> list[JiraStory]:
        """Fetch all stories in the project."""
        return self._jql(f'project="{self._project}" AND issuetype in (Story,"User Story")')

    def fetch_velocities(self) -> list[SprintVelocity]:
        """Compute velocity per closed sprint (pts/week)."""
        stories = self._jql(
            f'project="{self._project}" AND sprint in closedSprints() '
            f'AND issuetype in (Story,"User Story")')
        by_sprint: dict[str, list[JiraStory]] = {}
        for s in stories:
            if s.sprint: by_sprint.setdefault(s.sprint, []).append(s)
        vels = []
        for name, ss in by_sprint.items():
            num = _sprint_number(name)
            committed = sum(s.story_points for s in ss)
            completed = sum(s.story_points for s in ss if s.status in COMPLETED_STATUSES)
            done_n = sum(1 for s in ss if s.status in COMPLETED_STATUSES)
            vels.append(SprintVelocity(
                sprint_name=name, sprint_number=num,
                committed_points=committed, completed_points=completed,
                completed_per_week=round(completed / self._sprint_weeks, 1),
                total_stories=len(ss), completed_stories=done_n))
        vels.sort(key=lambda v: v.sprint_number)
        if vels:
            avg = sum(v.completed_per_week for v in vels) / len(vels)
            logger.info("velocities", n=len(vels), avg_pw=round(avg, 1))
        return vels

    def add_labels(self, key: str, labels: list[str]) -> bool:
        """Add labels to a Jira issue."""
        try:
            self._client.update_issue(key, {"update": {"labels": [{"add": l} for l in labels]}})
            return True
        except Exception as e:
            logger.error("add_labels_failed", key=key, err=str(e)[:80]); return False

    def remove_labels(self, key: str, labels: list[str]) -> bool:
        """Remove labels from a Jira issue."""
        try:
            self._client.update_issue(key, {"update": {"labels": [{"remove": l} for l in labels]}})
            return True
        except Exception as e:
            logger.error("remove_labels_failed", key=key, err=str(e)[:80]); return False

    def debug_statuses(self) -> dict[str, int]:
        """Fetch raw Jira status names and counts."""
        raw = self._client.jql(
            f'project="{self._project}" AND issuetype in (Story,"User Story")',
            limit=500, fields="status,created")
        counts: dict[str, int] = {}
        for issue in raw.get("issues", []):
            name = issue["fields"]["status"]["name"]
            counts[name] = counts.get(name, 0) + 1
        return counts

    def _jql(self, jql: str) -> list[JiraStory]:
        """Execute paginated JQL and map results."""
        results: list[JiraStory] = []
        start = 0
        fields = f"summary,description,status,labels,{self._sp_field},assignee,sprint,created"
        while True:
            resp = self._client.jql(jql, start=start, limit=100, fields=fields)
            for issue in resp.get("issues", []):
                results.append(self._map(issue))
            start += 100
            if start >= resp.get("total", 0): break
        logger.info("jql_results", n=len(results))
        return results

    def _map(self, raw: dict[str, Any]) -> JiraStory:
        """Map raw Jira issue to JiraStory."""
        f = raw["fields"]
        created = f.get("created")
        return JiraStory(
            key=raw["key"], summary=f.get("summary", ""),
            description=f.get("description") or "",
            status=self._resolve_status(f.get("status", {}).get("name", ""), created),
            story_points=safe_int(f.get(self._sp_field)),
            labels=f.get("labels", []),
            sprint=_sprint_name(f.get("sprint")),
            assignee=_assignee(f.get("assignee")),
            created_date=created[:10] if created else None)

    def _resolve_status(self, raw: str, created: str | None = None) -> StoryStatus:
        """Map Jira status → StoryStatus. Unknown + old → DONE."""
        if not raw: return StoryStatus.BACKLOG
        # Exact match
        for ours, names in self._status_map.items():
            if raw in names: return StoryStatus(ours)
        # Case-insensitive
        low = raw.lower().strip()
        for ours, names in self._status_map.items():
            if low in [n.lower() for n in names]: return StoryStatus(ours)
        # Age-based fallback
        age = days_since_iso(created)
        if age is not None and age > self._done_after_days:
            logger.info("auto_done", status=raw, age=age)
            return StoryStatus.DONE
        logger.warning("unknown_status", status=raw)
        return StoryStatus.BACKLOG


def _sprint_number(name: str) -> int:
    m = re.search(r"(\d+)", name)
    return int(m.group(1)) if m else 0

def _sprint_name(field: Any) -> str | None:
    if isinstance(field, dict): return field.get("name")
    if isinstance(field, list) and field:
        last = field[-1]
        return last.get("name") if isinstance(last, dict) else str(last)
    return None

def _assignee(field: Any) -> str | None:
    return field.get("displayName") if isinstance(field, dict) else None
