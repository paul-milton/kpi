"""Mock data generator for realistic but imperfect Jira data (Story 1-9)."""
from __future__ import annotations
import json
import random
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from kpi.domain.dimensions import flatten_all, parse_dimensions
from kpi.domain.models import (
    COMPLETED_STATUSES, IssueType, JiraStory, SprintVelocity, StoryStatus,
)
from kpi.services.dates import build_sprint_calendar

# Weighted status distribution (realistic project ~40% through)
STATUS_DISTRIBUTION = [
    (StoryStatus.DONE, 0.25),
    (StoryStatus.DELIVERED, 0.05),
    (StoryStatus.IN_PROGRESS, 0.10),
    (StoryStatus.REVIEW, 0.05),
    (StoryStatus.TESTING, 0.05),
    (StoryStatus.TODO, 0.15),
    (StoryStatus.BACKLOG, 0.25),
    (StoryStatus.SPECIFICATION, 0.05),
    (StoryStatus.BLOCKED, 0.03),
    (StoryStatus.ABANDONED, 0.02),
]

POINT_VALUES = [0, 1, 2, 3, 5, 8, 13]
POINT_WEIGHTS = [0.05, 0.10, 0.15, 0.25, 0.25, 0.15, 0.05]

SUMMARIES = [
    "Implement {tag} module", "Fix {tag} regression", "Add {tag} validation",
    "Refactor {tag} service", "Update {tag} documentation", "Test {tag} integration",
    "Configure {tag} pipeline", "Review {tag} design", "Migrate {tag} data",
    "Optimize {tag} performance", "Deploy {tag} feature", "Audit {tag} security",
]

ENV_LABELS = ["env:dev", "env:recette", "env:preprod", "env:prod"]


class MockGenerator:
    def __init__(self, cfg: dict[str, Any], seed: int = 42) -> None:
        self._cfg = cfg
        self._rng = random.Random(seed)
        self._dims = parse_dimensions(cfg["dimensions"])
        self._all_nodes = flatten_all(self._dims)
        self._tag_labels = [n.label for n in self._all_nodes if n.is_taggable]
        self._timeline = build_sprint_calendar(cfg)
        self._project_key = cfg.get("jira", {}).get("project_key", "MOCK")

    def generate(self, count: int = 300, noise: float = 0.35) -> list[JiraStory]:
        """Generate N stories with realistic distribution and noise injection."""
        stories = []
        past_sprints = [s for s in self._timeline if s.is_past]
        current = [s for s in self._timeline if s.is_current]
        future = [s for s in self._timeline if not s.is_past and not s.is_current]
        all_sprints = past_sprints + current + future

        statuses = [s for s, _ in STATUS_DISTRIBUTION]
        weights = [w for _, w in STATUS_DISTRIBUTION]

        for i in range(1, count + 1):
            key = f"{self._project_key}-{i}"
            status = self._rng.choices(statuses, weights=weights, k=1)[0]
            pts = self._rng.choices(POINT_VALUES, weights=POINT_WEIGHTS, k=1)[0]

            # Assign tags from dimension tree
            n_tags = self._rng.randint(1, min(4, len(self._tag_labels)))
            labels = self._rng.sample(self._tag_labels, min(n_tags, len(self._tag_labels)))
            # ~30% of stories get an env: label (max 1)
            if self._rng.random() < 0.30:
                labels.append(self._rng.choice(ENV_LABELS))
            tag_display = labels[0] if labels else "general"

            # Sprint assignment: done→past, active→current, backlog→future/none
            sprint = None
            if status in COMPLETED_STATUSES and past_sprints:
                sprint = self._rng.choice(past_sprints).name
            elif status in {StoryStatus.IN_PROGRESS, StoryStatus.REVIEW, StoryStatus.TESTING} and current:
                sprint = current[0].name
            elif status == StoryStatus.TODO and all_sprints:
                sprint = self._rng.choice(all_sprints[:len(past_sprints) + len(current) + 2]).name
            elif status == StoryStatus.BLOCKED and current:
                sprint = current[0].name

            # Created date: spread across project timeline
            proj_start = date.fromisoformat(self._cfg.get("project", {}).get("start_date", "2025-10-01"))
            days_range = max((date.today() - proj_start).days, 1)
            created = proj_start + timedelta(days=self._rng.randint(0, days_range))

            summary = self._rng.choice(SUMMARIES).format(tag=tag_display)

            story = JiraStory(
                key=key, summary=summary, status=status,
                story_points=pts, labels=labels, sprint=sprint,
                assignee=f"dev-{self._rng.randint(1, 8)}",
                created_date=created.isoformat(),
                issue_type=self._rng.choices([IssueType.STORY, IssueType.TASK], weights=[0.7, 0.3])[0],
            )
            stories.append(story)

        # Noise injection
        noise_count = int(count * noise)
        noise_indices = self._rng.sample(range(count), min(noise_count, count))
        for idx in noise_indices:
            s = stories[idx]
            defect = self._rng.choice(["no_tags", "zero_sp", "no_sprint", "wrong_combo"])
            if defect == "no_tags":
                stories[idx] = s.model_copy(update={"labels": []})
            elif defect == "zero_sp":
                stories[idx] = s.model_copy(update={"story_points": 0})
            elif defect == "no_sprint":
                stories[idx] = s.model_copy(update={"sprint": None})
            elif defect == "wrong_combo":
                # In-progress but no sprint
                stories[idx] = s.model_copy(update={"status": StoryStatus.IN_PROGRESS, "sprint": None})

        return stories

    def generate_velocities(self, stories: list[JiraStory]) -> list[SprintVelocity]:
        """Generate velocity data from story completion patterns."""
        past_sprints = [s for s in self._timeline if s.is_past]
        velocities = []
        for sp in past_sprints:
            sp_stories = [s for s in stories if s.sprint == sp.name]
            completed = sum(s.story_points for s in sp_stories if s.status in COMPLETED_STATUSES)
            dur = max(int(sp.end_date[:10] > sp.start_date[:10]) * 3, self._cfg.get("project", {}).get("sprint_duration_weeks", 3))
            velocities.append(SprintVelocity(
                sprint_name=sp.name, sprint_number=sp.number,
                completed_points=completed,
                completed_per_week=round(completed / dur, 1) if dur else 0,
                total_stories=len(sp_stories),
                completed_stories=sum(1 for s in sp_stories if s.status in COMPLETED_STATUSES),
            ))
        return velocities

    def to_json(self, stories: list[JiraStory]) -> str:
        """Serialize stories to JSON compatible with JiraStory."""
        return json.dumps([s.model_dump(mode="json") for s in stories], indent=2, ensure_ascii=False)
