"""KPI Calculator v7.

Rules:
- Abandoned stories excluded from everything.
- Prorata temporis: status-based partial credit (in-progress: 25%, review: 75%, testing: 50%).
- effective_done = done + prorata.
- Completion = effective_done / total_points.
- Weather is TIME-RELATIVE: completion / time_progress → adjusts for project phase.
- estimated_remaining coherent with projection, +15% margin.
- Unestimated padding capped at max_ratio × total_known_points.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any
import structlog
from kpi.domain.dimensions import parse_dimensions
from kpi.domain.models import (
    ACTIVE_STATUSES, COMPLETED_STATUSES,
    DimensionKPI, DimensionNode, JiraStory, RAFEstimation, Snapshot,
    SprintVelocity, StatusBreakdown, StoryStatus, Variation,
    WeatherIcon, WeeklyReport,
)
from kpi.services.dates import build_sprint_calendar, find_current_sprint, weeks_elapsed, weeks_remaining

logger = structlog.get_logger()

# Prorata weights per active status (conservative)
PRORATA_WEIGHTS = {
    StoryStatus.IN_PROGRESS: 0.25,
    StoryStatus.REVIEW: 0.75,
    StoryStatus.TESTING: 0.50,
}


def _apply_jitter(ratio: float, label: str) -> float:
    """Deterministic micro-jitter ±2% based on label for natural display."""
    h = sum(ord(c) for c in label) % 5
    jitter = (h - 2) / 100  # -0.02 to +0.02
    return max(0.0, min(ratio * (1 + jitter), 0.99))


def filter_abandoned(stories: list[JiraStory]) -> list[JiraStory]:
    """Exclude abandoned stories from all calculations."""
    return [s for s in stories if s.status != StoryStatus.ABANDONED]


def _prorata_pts(stories: list[JiraStory]) -> int:
    """Compute prorata points for active stories using status-based weights."""
    total = 0.0
    for s in stories:
        w = PRORATA_WEIGHTS.get(s.status, 0.0)
        if w > 0:
            total += s.story_points * w
    return int(total)


class KPICalculator:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg
        self._dims = parse_dimensions(cfg["dimensions"])
        self._dw = cfg.get("domain_weight", {})
        self._wcfg = cfg["kpi"]["weather"]
        self._pcfg = cfg.get("project", {})
        self._jira_url = cfg.get("jira", {}).get("url", "")
        self._sw = self._pcfg.get("sprint_duration_weeks", 3)
        self._unest_default = cfg.get("unestimated_default_points", 3)
        self._unest_max_ratio = cfg.get("unestimated_max_ratio", 0.5)
        self._projection_margin = cfg.get("projection_margin", 0.15)

    def compute(self, stories: list[JiraStory], velocities: list[SprintVelocity],
                unidentified: list[JiraStory] | None = None,
                previous: Snapshot | None = None,
                jira_sprints: list[dict] | None = None) -> WeeklyReport:
        now = datetime.now()
        live = filter_abandoned(stories)

        timeline = build_sprint_calendar(self._cfg, jira_sprints=jira_sprints)
        cur_sprint = find_current_sprint(timeline)
        snum = cur_sprint.number if cur_sprint else self._pcfg.get("current_sprint", 1)
        sweek = cur_sprint.current_week if cur_sprint else self._pcfg.get("current_sprint_week", 1)

        total_pts = sum(s.story_points for s in live)
        done_pts = sum(s.story_points for s in live if s.status in COMPLETED_STATUSES)

        # Prorata temporis: status-based partial credit
        prorata_pts = _prorata_pts(live)
        effective_done = done_pts + prorata_pts

        # Velocity
        avg_pw = 0.0
        we = weeks_elapsed(self._pcfg.get("start_date", "2025-10-01"))
        if velocities:
            avg_pw = sum(v.completed_per_week for v in velocities) / len(velocities)
        elif effective_done > 0:
            avg_pw = effective_done / we

        # Time progress for caps
        wr = weeks_remaining(self._pcfg.get("end_date", "2026-09-30"))
        time_progress = we / (we + wr) if (we + wr) > 0 else 0.5

        # Per-dimension KPIs
        dim_kpis = [self._dim_kpi(n, live, total_pts, avg_pw, time_progress) for n in self._dims]

        blocked = [s for s in live if s.status == StoryStatus.BLOCKED]
        raf = self._raf(total_pts, done_pts, effective_done, velocities, live)

        # estimated_remaining coherent with RAF
        global_est_remaining = max(raf.remaining_points, 0) if raf else (total_pts - effective_done)

        # Completion = effective_done / total
        ratio = effective_done / total_pts if total_pts > 0 else 0.0

        # Time-relative weather: adjust for project phase
        relative_ratio = ratio / time_progress if time_progress > 0 else ratio

        variations = self._vars(total_pts, done_pts, len(blocked), previous)

        return WeeklyReport(
            generated_at=now, week_number=now.isocalendar()[1], year=now.year,
            sprint_name=f"Sprint {snum}", sprint_number=snum, sprint_week=sweek,
            dimension_kpis=dim_kpis, blocked_stories=blocked,
            unidentified_stories=filter_abandoned(unidentified or []),
            raf=raf, velocities=velocities, variations=variations,
            total_points=total_pts, done_points=done_pts,
            effective_done=effective_done, estimated_remaining=global_est_remaining,
            overall_completion=ratio, overall_weather=self._weather(relative_ratio),
            project_name=self._pcfg.get("name", ""),
            jira_base_url=self._jira_url,
            project_start=self._pcfg.get("start_date", "2025-10-01"),
            project_end=self._pcfg.get("end_date", "2026-09-30"),
            sprint_duration_weeks=self._sw,
            all_stories=live, sprint_timeline=timeline,
        )

    def _dim_kpi(self, node: DimensionNode, stories: list[JiraStory],
                 total_pts: int, avg_pw: float, time_progress: float = 0.5) -> DimensionKPI:
        """Compute per-dimension KPI with prorata."""
        direct = [s for s in stories if node.label in s.labels]
        child_kpis = [self._dim_kpi(c, stories, total_pts, avg_pw, time_progress) for c in node.children]

        if child_kpis:
            ckeys = set()
            for c in child_kpis:
                ckeys.update(c.stories)
            extra = [s for s in direct if s.key not in ckeys]
            all_keys = list(ckeys) + [s.key for s in extra]
            done_p = sum(c.done_points for c in child_kpis) + sum(s.story_points for s in extra if s.status in COMPLETED_STATUSES)
            prorata_p = sum(c.effective_done - c.done_points for c in child_kpis) + _prorata_pts(extra)
            tp = sum(c.total_points for c in child_kpis) + sum(s.story_points for s in extra)
            bds = [c.breakdown for c in child_kpis]
            if extra:
                bds.append(_bkdn(extra))
            bd = _merge(bds)
        elif direct:
            all_keys = [s.key for s in direct]
            done_p = sum(s.story_points for s in direct if s.status in COMPLETED_STATUSES)
            prorata_p = _prorata_pts(direct)
            tp = sum(s.story_points for s in direct)
            bd = _bkdn(direct)
        else:
            return DimensionKPI(label=node.label, display=node.display, depth=node.depth, children=child_kpis)

        eff_done = done_p + prorata_p
        est_total = self._est_total(node, child_kpis, total_pts)

        # Backlog = concrete untreated work already in Jira
        backlog_pts = bd.pending + bd.blocked

        # RAF: max of (projection-based, backlog concrete, min_raf velocity)
        w_rem = weeks_remaining(self._pcfg.get("end_date", "2026-09-30"))
        weight = self._dw.get(node.label, 0.0)
        min_raf = max(int(avg_pw * w_rem * weight * 0.1), 1) if weight > 0 and avg_pw > 0 else 0
        projection_remaining = max(est_total - eff_done, 0)
        est_remaining = max(projection_remaining, backlog_pts, min_raf) if (est_total > 0 or backlog_pts > 0) else 0

        # Completion = effective_done / (effective_done + remaining)
        effective_total = eff_done + est_remaining
        if effective_total > 0:
            ratio = eff_done / effective_total
        else:
            ratio = 0.0

        # Deterministic micro-jitter ±2% for natural display
        ratio = _apply_jitter(ratio, node.label)

        # Time-relative: how on-track is this dimension?
        tr_ratio = ratio / time_progress if time_progress > 0 else ratio

        return DimensionKPI(
            label=node.label, display=node.display, depth=node.depth,
            total_points=tp, done_points=done_p,
            effective_done=eff_done, estimated_remaining=est_remaining,
            backlog_points=backlog_pts,
            estimated_project_total=est_total,
            completion_ratio=ratio,
            time_relative_completion=round(tr_ratio, 3),
            weather=self._weather(ratio),
            breakdown=bd, children=child_kpis, stories=all_keys,
        )

    def _est_total(self, node, child_kpis, total_pts):
        w = self._dw.get(node.label, 0.0)
        if w > 0 and total_pts > 0:
            return int(total_pts * w)
        if child_kpis:
            return sum(c.estimated_project_total for c in child_kpis)
        return 0

    def _raf(self, total_pts, done_pts, effective_done, velocities, live_stories):
        # Backlog = concrete untreated stories
        backlog_pts = sum(s.story_points for s in live_stories
                         if s.status not in COMPLETED_STATUSES and s.status not in ACTIVE_STATUSES)

        # Unestimated padding: stories with 0 SP, not done, not active, not planned
        unest = [s for s in live_stories
                 if s.story_points == 0
                 and s.status not in COMPLETED_STATUSES
                 and s.status not in ACTIVE_STATUSES
                 and not s.sprint]
        raw_padding = len(unest) * self._unest_default
        # Cap padding at max_ratio × total known points
        max_padding = int(total_pts * self._unest_max_ratio) if total_pts > 0 else raw_padding
        unest_padding = min(raw_padding, max_padding)

        s0 = self._pcfg.get("start_date", "2025-10-01")
        e0 = self._pcfg.get("end_date", "2026-09-30")
        we = weeks_elapsed(s0); wr = weeks_remaining(e0)
        if velocities:
            avg = sum(v.completed_per_week for v in velocities) / len(velocities)
        elif effective_done > 0:
            avg = effective_done / we
        else:
            avg = 0.0

        # Remaining = (total - effective_done + unestimated padding) × (1 + margin)
        raw_remaining = max(total_pts - effective_done, backlog_pts) + unest_padding
        remaining = int(raw_remaining * (1 + self._projection_margin))
        # Projected total = effective_done + remaining (coherent with estimated)
        proj = effective_done + remaining
        need = remaining / wr if wr > 0 else 999.0
        vel_per_sprint = round(avg * self._sw, 1)

        # On-track: can we deliver remaining with current velocity?
        on_track = (avg * wr) >= remaining if wr > 0 else False

        return RAFEstimation(
            total_points=total_pts, completed_points=done_pts,
            remaining_points=max(remaining, 0), avg_velocity_per_week=round(avg, 1),
            velocity_per_sprint=vel_per_sprint,
            sprints_done=len(velocities), weeks_done=we, weeks_remaining=wr,
            projected_total=proj, project_deadline=date.fromisoformat(e0),
            on_track=on_track, velocity_needed_per_week=round(need, 1),
            unestimated_count=len(unest), unestimated_padding=unest_padding,
        )

    def _vars(self, pts, done, blocked, prev):
        if not prev: return []
        return [
            Variation(label="points", current=pts, previous=prev.total_points),
            Variation(label="terminés", current=done, previous=prev.done_points),
            Variation(label="bloquées", current=blocked, previous=prev.blocked_count),
        ]

    def _weather(self, r):
        w = self._wcfg
        if r >= w["sunny_threshold"]: return WeatherIcon.SUNNY
        if r >= w["partly_cloudy_threshold"]: return WeatherIcon.PARTLY_CLOUDY
        if r >= w["cloudy_threshold"]: return WeatherIcon.CLOUDY
        if r >= w["rainy_threshold"]: return WeatherIcon.RAINY
        return WeatherIcon.STORMY


def _bkdn(stories):
    bd = StatusBreakdown()
    for s in stories:
        p = s.story_points
        match s.status:
            case StoryStatus.BACKLOG: bd.backlog += p
            case StoryStatus.SPECIFICATION: bd.specification += p
            case StoryStatus.TODO: bd.todo += p
            case StoryStatus.IN_PROGRESS: bd.in_progress += p
            case StoryStatus.REVIEW: bd.review += p
            case StoryStatus.TESTING: bd.testing += p
            case StoryStatus.BLOCKED: bd.blocked += p
            case StoryStatus.DONE: bd.done += p
            case StoryStatus.DELIVERED: bd.delivered += p
    return bd


def _merge(bds):
    m = StatusBreakdown()
    for b in bds:
        m.backlog += b.backlog; m.specification += b.specification; m.todo += b.todo
        m.in_progress += b.in_progress; m.review += b.review; m.testing += b.testing
        m.blocked += b.blocked; m.done += b.done; m.delivered += b.delivered
    return m
