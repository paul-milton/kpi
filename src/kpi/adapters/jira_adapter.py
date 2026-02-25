"""Jira adapter — fetch stories, velocities, manage labels.

Unknown statuses on stories older than N days → auto-done.
"""
from __future__ import annotations
import re
from typing import Any
import structlog
from atlassian import Jira
from kpi.adapters.network import resolve_proxies, resolve_ssl
from kpi.domain.models import COMPLETED_STATUSES, IssueType, JiraStory, SprintVelocity, StoryStatus
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
        self._configured_project = j["project_key"]
        self._status_map = j["status_mapping"]
        self._sp_field = j.get("story_points_field", "customfield_10106")
        self._legacy_prefixes = j.get("legacy_label_prefixes", [])
        self._done_after_days = j.get("unknown_status_done_after_days", 21)
        self._sprint_weeks = cfg.get("project", {}).get("sprint_duration_weeks", 3)
        self._story_types = j.get("story_types", ['Story', 'User Story'])
        self._task_types = j.get("task_types", ['Task', 'Sub-task', 'Subtask', 'Sous-tâche', 'Tâche'])
        self._client = Jira(url=j["url"], token=j["token"],
                            verify_ssl=resolve_ssl(cfg), proxies=resolve_proxies())
        self._project = self._resolve_project_key(self._configured_project)

    def _resolve_project_key(self, configured_key: str) -> str:
        """Validate and resolve the project key dynamically.

        1. Try a lightweight API call with the configured key.
        2. If it fails (404/400), fetch all projects and match by key or name.
        3. Return the resolved key, or fall back to the configured one.
        """
        # Quick validation: try to hit the project endpoint
        try:
            resp = self._client.get(f"rest/api/2/project/{configured_key}", advanced_mode=True)
            if resp.status_code == 200:
                real_key = resp.json().get("key", configured_key)
                logger.info("project_key_valid", configured=configured_key, resolved=real_key)
                return real_key
            logger.warning("project_key_invalid", configured=configured_key, status=resp.status_code)
        except Exception as e:
            logger.warning("project_key_check_error", configured=configured_key, err=str(e)[:80])

        # Fetch all projects and try to match
        projects = self._fetch_all_projects()
        if not projects:
            logger.error("no_projects_found", configured=configured_key)
            return configured_key

        # Try exact key match (case-insensitive)
        low_key = configured_key.lower()
        for p in projects:
            if p["key"].lower() == low_key:
                logger.info("project_key_resolved_by_key", configured=configured_key, resolved=p["key"])
                return p["key"]

        # Try name match (configured key appears in project name)
        for p in projects:
            if low_key in p["name"].lower():
                logger.info("project_key_resolved_by_name", configured=configured_key,
                           resolved=p["key"], name=p["name"])
                return p["key"]

        # Log available projects for diagnostics
        available = [f"{p['key']} ({p['name']})" for p in projects[:20]]
        logger.error("project_key_unresolved", configured=configured_key, available=available)
        return configured_key

    def _fetch_all_projects(self) -> list[dict]:
        """Fetch all accessible projects from Jira."""
        try:
            resp = self._client.get("rest/api/2/project", advanced_mode=True)
            if resp.status_code == 200:
                data = resp.json()
                if isinstance(data, list):
                    projects = [{"key": p.get("key", ""), "name": p.get("name", ""),
                                 "id": p.get("id", "")} for p in data if p.get("key")]
                    logger.info("projects_fetched", count=len(projects))
                    return projects
        except Exception as e:
            logger.warning("fetch_projects_error", err=str(e)[:80])
        return []

    def debug_projects(self) -> list[dict]:
        """Return all accessible projects for diagnostics."""
        return self._fetch_all_projects()

    def fetch_issue_types(self) -> dict[str, list[str]]:
        """Discover issue type names from Jira, classified as stories or tasks.

        Returns {"stories": [...], "tasks": [...]}.
        Tries multiple API endpoints with fallback chain:
        1. /project/{key} (project-specific types)
        2. /issuetype (all instance types)
        3. Config fallback (story_types / task_types)
        """
        issue_types = self._fetch_project_types() or self._fetch_global_types()
        if not issue_types:
            logger.warning("fetch_issue_types_all_failed")
            return {"stories": self._story_types, "tasks": self._task_types}
        return self._classify_types(issue_types)

    def _fetch_project_types(self) -> list[dict] | None:
        """Try /project/{key} for project-specific issue types."""
        try:
            resp = self._client.get(f"rest/api/2/project/{self._project}", advanced_mode=True)
            if resp.status_code == 200:
                types = resp.json().get("issueTypes", [])
                if types:
                    logger.info("issue_types_from_project", count=len(types))
                    return types
        except Exception as e:
            logger.debug("project_types_error", err=str(e)[:80])
        return None

    def _fetch_global_types(self) -> list[dict] | None:
        """Try /issuetype for all instance issue types."""
        try:
            resp = self._client.get("rest/api/2/issuetype", advanced_mode=True)
            if resp.status_code == 200:
                types = resp.json() if isinstance(resp.json(), list) else []
                if types:
                    logger.info("issue_types_from_global", count=len(types))
                    return types
        except Exception as e:
            logger.debug("global_types_error", err=str(e)[:80])
        return None

    def _classify_types(self, issue_types: list[dict]) -> dict[str, list[str]]:
        """Classify issue types into stories, tasks, and subtask types."""
        stories, tasks, subtask_types = [], [], []
        for it in issue_types:
            name = it.get("name", "")
            if not name:
                continue
            is_subtask = it.get("subtask", False)
            low = name.lower()
            if is_subtask:
                subtask_types.append(name)
                tasks.append(name)
            elif any(kw in low for kw in ("task", "tâche", "sous-", "subtask")):
                tasks.append(name)
            elif any(kw in low for kw in ("story", "récit", "user story", "histoire")):
                stories.append(name)
            elif not any(kw in low for kw in ("epic", "bug", "défaut", "incident")):
                stories.append(name)
        logger.info("discovered_issue_types", stories=stories, tasks=tasks, subtask_types=subtask_types)
        return {"stories": stories or self._story_types, "tasks": tasks or self._task_types,
                "subtask_types": subtask_types}

    def debug_issue_types(self) -> list[dict]:
        """Return all discovered issue types for diagnostics."""
        types = self._fetch_project_types() or self._fetch_global_types() or []
        return [{"name": t.get("name", ""), "subtask": t.get("subtask", False),
                 "id": t.get("id", "")} for t in types]

    def fetch_all_stories(self) -> list[JiraStory]:
        """Fetch all stories and linked tasks in the project.

        Tasks are included only if they have a parent story (subtask) or
        are linked to a story via issuelinks.
        Discovers issue type names dynamically from Jira API.
        Falls back to trying types one by one if batch JQL fails.
        """
        discovered = self.fetch_issue_types()
        self._discovered_story_types = discovered["stories"]
        self._discovered_task_types = discovered["tasks"]
        self._discovered_subtask_types = discovered.get("subtask_types", [])

        stories = self._jql_with_type_fallback(self._discovered_story_types)
        if not stories:
            logger.error("no_stories_found", project=self._project,
                        types=self._discovered_story_types)
        story_keys = {s.key for s in stories}

        # Also fetch tasks (graceful: skip on failure)
        linked_tasks = []
        if self._discovered_task_types:
            tasks = self._jql_with_type_fallback(self._discovered_task_types)
            linked_tasks = [t for t in tasks if t.parent_key and t.parent_key in story_keys]
            logger.info("tasks_linked", total_tasks=len(tasks), linked=len(linked_tasks))
        return stories + linked_tasks

    def _jql_with_type_fallback(self, types: list[str]) -> list[JiraStory]:
        """Try batch JQL first, then individual types on failure."""
        # Try all types at once
        try:
            return self._jql(
                f'project="{self._project}" AND issuetype in ({_jql_list(types)})')
        except Exception as e:
            logger.warning("batch_jql_failed", types=types, err=str(e)[:120])

        # Fallback: try each type individually
        results = []
        for t in types:
            try:
                found = self._jql(
                    f'project="{self._project}" AND issuetype={_jql_list([t])}')
                results.extend(found)
                logger.info("type_ok", type=t, count=len(found))
            except Exception:
                logger.debug("type_not_found", type=t)
        return results

    def fetch_velocities(self) -> list[SprintVelocity]:
        """Compute velocity per closed sprint (pts/week)."""
        st = getattr(self, '_discovered_story_types', self._story_types)
        tt = getattr(self, '_discovered_task_types', self._task_types)
        all_types = list(dict.fromkeys(st + tt))  # deduplicated, order preserved
        stories = self._jql(
            f'project="{self._project}" AND sprint in closedSprints() '
            f'AND issuetype in ({_jql_list(all_types)})')
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

    def create_subtask(self, parent_key: str, summary: str, labels: list[str] | None = None,
                       story_points: int | None = None) -> str | None:
        """Create a subtask linked to parent_key. Returns new issue key or None."""
        # Prefer actual subtask types (Jira requires issuetype.subtask=true for parent field)
        subtask_types = getattr(self, '_discovered_subtask_types', [])
        if subtask_types:
            task_type = subtask_types[0]
        elif hasattr(self, '_discovered_task_types') and self._discovered_task_types:
            task_type = self._discovered_task_types[0]
        else:
            task_type = self._task_types[0]
        fields: dict[str, Any] = {
            "project": {"key": self._project},
            "parent": {"key": parent_key},
            "summary": summary,
            "issuetype": {"name": task_type},
        }
        if labels:
            fields["labels"] = labels
        if story_points is not None:
            fields[self._sp_field] = story_points
        try:
            resp = self._client.create_issue(fields=fields)
            key = resp.get("key", "") if isinstance(resp, dict) else ""
            if key:
                logger.info("subtask_created", parent=parent_key, key=key, summary=summary[:60])
                return key
            logger.error("subtask_no_key", parent=parent_key, resp=str(resp)[:120])
            return None
        except Exception as e:
            logger.error("subtask_failed", parent=parent_key, err=str(e)[:120])
            return None

    def fetch_sprints(self) -> list[dict]:
        """Fetch sprints from the Jira board for this project.

        Returns list of dicts with keys: name, number, state, start_date, end_date.
        """
        try:
            boards = self._client.get(f"rest/agile/1.0/board?projectKeyOrId={self._project}",
                                       advanced_mode=True)
            if boards.status_code != 200:
                logger.warning("boards_fetch_failed", status=boards.status_code)
                return []
            boards_data = boards.json().get("values", [])
            if not boards_data:
                logger.warning("no_boards_found", project=self._project)
                return []
            board_id = boards_data[0]["id"]
            sprints_raw = []
            start = 0
            while True:
                resp = self._client.get(
                    f"rest/agile/1.0/board/{board_id}/sprint?startAt={start}&maxResults=50",
                    advanced_mode=True)
                if resp.status_code != 200:
                    break
                data = resp.json()
                sprints_raw.extend(data.get("values", []))
                if data.get("isLast", True):
                    break
                start += 50
            result = []
            for sp in sprints_raw:
                num = _sprint_number(sp.get("name", ""))
                result.append({
                    "name": sp.get("name", ""),
                    "number": num,
                    "state": sp.get("state", "future"),
                    "start_date": sp.get("startDate", "")[:10] if sp.get("startDate") else "",
                    "end_date": sp.get("endDate", "")[:10] if sp.get("endDate") else "",
                })
            result.sort(key=lambda s: s["number"])
            logger.info("jira_sprints", count=len(result))
            return result
        except Exception as e:
            logger.warning("fetch_sprints_error", err=str(e)[:120])
            return []

    def debug_statuses(self) -> dict[str, int]:
        """Fetch raw Jira status names and counts."""
        st = getattr(self, '_discovered_story_types', self._story_types)
        raw = self._client.jql(
            f'project="{self._project}" AND issuetype in ({_jql_list(st)})',
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
        fields = f"summary,description,status,labels,{self._sp_field},assignee,sprint,created,issuetype,parent,issuelinks"
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
        # Detect issue type
        raw_type = (f.get("issuetype", {}).get("name", "") or "").lower()
        is_task = "task" in raw_type or "tâche" in raw_type or "sous-" in raw_type or "subtask" in raw_type
        # Detect parent (subtask parent or issuelinks)
        parent = _extract_parent(f)
        return JiraStory(
            key=raw["key"], summary=f.get("summary", ""),
            description=f.get("description") or "",
            status=self._resolve_status(f.get("status", {}).get("name", ""), created),
            story_points=safe_int(f.get(self._sp_field)),
            labels=f.get("labels", []),
            sprint=_sprint_name(f.get("sprint")),
            assignee=_assignee(f.get("assignee")),
            created_date=created[:10] if created else None,
            issue_type=IssueType.TASK if is_task else IssueType.STORY,
            parent_key=parent)

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


def _jql_list(values: list[str]) -> str:
    """Format a list of values for JQL IN clause, quoting those with spaces/hyphens."""
    parts = []
    for v in values:
        if ' ' in v or '-' in v:
            parts.append(f'"{v}"')
        else:
            parts.append(v)
    return ','.join(parts)


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


def _extract_parent(fields: dict[str, Any]) -> str | None:
    """Extract parent key from subtask parent field or issuelinks."""
    # Subtask parent (Jira native)
    parent = fields.get("parent")
    if isinstance(parent, dict) and parent.get("key"):
        return parent["key"]
    # Issuelinks: look for inward links of type "is child of" / "est un enfant de"
    for link in fields.get("issuelinks", []):
        inward = link.get("inwardIssue")
        if inward and inward.get("key"):
            return inward["key"]
    return None
