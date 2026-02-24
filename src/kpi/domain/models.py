"""Domain models for KPI v7.

All points are int. Labels are single lowercase words with dashes.
Abandoned stories are excluded from all calculations and reports.
Prorata temporis applied to every dimension, not just global.
"""
from __future__ import annotations
from datetime import date, datetime
from enum import Enum
from pydantic import BaseModel, Field


class StoryStatus(str, Enum):
    BACKLOG = "backlog"
    SPECIFICATION = "specification"
    TODO = "todo"
    IN_PROGRESS = "in-progress"
    REVIEW = "review"
    TESTING = "testing"
    BLOCKED = "blocked"
    ABANDONED = "abandoned"
    DONE = "done"
    DELIVERED = "delivered"

COMPLETED_STATUSES = frozenset({StoryStatus.DONE, StoryStatus.DELIVERED})
ACTIVE_STATUSES = frozenset({StoryStatus.IN_PROGRESS, StoryStatus.REVIEW, StoryStatus.TESTING})


class WeatherIcon(str, Enum):
    SUNNY = "☀️"
    PARTLY_CLOUDY = "⛅"
    CLOUDY = "🌥️"
    RAINY = "🌧️"
    STORMY = "⛈️"


class JiraStory(BaseModel):
    key: str
    summary: str
    description: str = ""
    status: StoryStatus = StoryStatus.BACKLOG
    story_points: int = 0
    labels: list[str] = Field(default_factory=list)
    sprint: str | None = None
    assignee: str | None = None
    created_date: str | None = None


class DimensionNode(BaseModel):
    label: str
    display: str = ""
    keywords: list[str] = Field(default_factory=list)
    depth: int = 0
    children: list[DimensionNode] = Field(default_factory=list)

    @property
    def is_taggable(self) -> bool:
        return len(self.keywords) > 0

    def all_labels(self) -> set[str]:
        out = {self.label}
        for c in self.children:
            out |= c.all_labels()
        return out


class StatusBreakdown(BaseModel):
    """Point-based breakdown (abandoned excluded upstream)."""
    backlog: int = 0
    specification: int = 0
    todo: int = 0
    in_progress: int = 0
    review: int = 0
    testing: int = 0
    blocked: int = 0
    done: int = 0
    delivered: int = 0

    @property
    def completed(self) -> int:
        return self.done + self.delivered

    @property
    def active(self) -> int:
        return self.in_progress + self.review + self.testing

    @property
    def pending(self) -> int:
        return self.backlog + self.specification + self.todo

    @property
    def total(self) -> int:
        return self.completed + self.active + self.pending + self.blocked


class DimensionKPI(BaseModel):
    """KPI for one dimension. Columns: pts faits / pts restant estimé / %."""
    label: str
    display: str = ""
    depth: int = 0
    total_points: int = 0
    done_points: int = 0           # completed (done+delivered)
    prorata_points: int = 0        # prorata for active stories in this dim
    effective_done: int = 0        # done_points + prorata_points
    estimated_remaining: int = 0   # from projection, never < backlog untreated
    backlog_points: int = 0        # concrete untreated (backlog+spec+todo+blocked)
    estimated_project_total: int = 0
    completion_ratio: float = 0.0  # effective_done / est_project_total
    weather: WeatherIcon = WeatherIcon.CLOUDY
    breakdown: StatusBreakdown = Field(default_factory=StatusBreakdown)
    children: list[DimensionKPI] = Field(default_factory=list)
    stories: list[str] = Field(default_factory=list)

    @property
    def progress_percent(self) -> int:
        return int(self.completion_ratio * 100)


class SprintInfo(BaseModel):
    number: int
    name: str = ""
    start_date: str = ""
    end_date: str = ""
    is_current: bool = False
    is_past: bool = False
    current_week: int = 0


class SprintVelocity(BaseModel):
    sprint_name: str
    sprint_number: int = 0
    committed_points: int = 0
    completed_points: int = 0
    completed_per_week: float = 0.0
    total_stories: int = 0
    completed_stories: int = 0


class Variation(BaseModel):
    label: str
    current: int = 0
    previous: int = 0

    @property
    def delta(self) -> int:
        return self.current - self.previous

    @property
    def delta_pct(self) -> float:
        return self.delta / self.previous if self.previous else 0.0

    @property
    def delta_str(self) -> str:
        return f"+{self.delta}" if self.delta > 0 else str(self.delta)

    @property
    def delta_pct_str(self) -> str:
        p = self.delta_pct * 100
        return f"+{p:.0f}%" if p > 0 else f"{p:.0f}%"


class RAFEstimation(BaseModel):
    total_points: int = 0
    completed_points: int = 0
    remaining_points: int = 0
    avg_velocity_per_week: float = 0.0
    sprints_done: int = 0
    weeks_done: int = 0
    weeks_remaining: int = 0
    projected_total: int = 0
    project_deadline: date | None = None
    on_track: bool = True
    velocity_needed_per_week: float = 0.0
    prorata_points: int = 0
    unestimated_count: int = 0          # stories without SP, not done, not planned
    unestimated_padding: int = 0        # count × default_points added to remaining


class TagSuggestion(BaseModel):
    story_key: str
    story_summary: str = ""
    label: str
    confidence: float
    reason: str


class Snapshot(BaseModel):
    snapshot_date: str
    sprint_number: int = 0
    sprint_week: int = 0
    total_stories: int = 0
    total_points: int = 0
    done_stories: int = 0
    done_points: int = 0
    blocked_count: int = 0
    completion_ratio: float = 0.0
    avg_velocity_per_week: float = 0.0


class WeeklyReport(BaseModel):
    """Complete report. No user-story row — only points."""
    generated_at: datetime = Field(default_factory=datetime.now)
    week_number: int = 0
    year: int = 0
    sprint_name: str = ""
    sprint_number: int = 0
    sprint_week: int = 0
    dimension_kpis: list[DimensionKPI] = Field(default_factory=list)
    blocked_stories: list[JiraStory] = Field(default_factory=list)
    unidentified_stories: list[JiraStory] = Field(default_factory=list)
    current_sprint_stories: list[JiraStory] = Field(default_factory=list)
    raf: RAFEstimation | None = None
    velocities: list[SprintVelocity] = Field(default_factory=list)
    variations: list[Variation] = Field(default_factory=list)
    total_points: int = 0
    done_points: int = 0
    prorata_points: int = 0
    effective_done: int = 0
    overall_completion: float = 0.0
    overall_weather: WeatherIcon = WeatherIcon.CLOUDY
    jira_base_url: str = ""
    project_start: str = ""
    project_end: str = ""
    sprint_duration_weeks: int = 3
    all_stories: list[JiraStory] = Field(default_factory=list)
    sprint_timeline: list[SprintInfo] = Field(default_factory=list)
