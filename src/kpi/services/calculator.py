"""KPI Calculator v7.

Rules:
- Abandoned stories excluded from everything.
- Prorata temporis applied per-dimension (not just global).
- No dimension can be 100% with 0 RAF: est_remaining = max(est_total - effective_done, min_raf).
- min_raf = avg_velocity * weeks_remaining * weight (i.e. some work always remains).
- Columns: pts faits / pts restant estimé / % avancement.
- Current sprint stories tracked for display.
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


def filter_abandoned(stories: list[JiraStory]) -> list[JiraStory]:
    """Exclude abandoned stories from all calculations."""
    return [s for s in stories if s.status != StoryStatus.ABANDONED]


class KPICalculator:
    def __init__(self, cfg: dict[str, Any]) -> None:
        self._cfg = cfg
        self._dims = parse_dimensions(cfg["dimensions"])
        self._dw = cfg.get("domain_weight", {})
        self._wcfg = cfg["kpi"]["weather"]
        self._pcfg = cfg.get("project", {})
        self._jira_url = cfg.get("jira", {}).get("url", "")
        self._prorata = self._pcfg.get("prorata_current_sprint", True)
        self._sw = self._pcfg.get("sprint_duration_weeks", 3)
        self._show_sprint = self._pcfg.get("show_current_sprint_stories", True)
        self._unest_default = cfg.get("unestimated_default_points", 13)

    def compute(self, stories: list[JiraStory], velocities: list[SprintVelocity],
                unidentified: list[JiraStory] | None = None,
                previous: Snapshot | None = None) -> WeeklyReport:
        now = datetime.now()
        # Exclude abandoned
        live = filter_abandoned(stories)

        timeline = build_sprint_calendar(self._cfg)
        cur_sprint = find_current_sprint(timeline)
        snum = cur_sprint.number if cur_sprint else self._pcfg.get("current_sprint", 1)
        sweek = cur_sprint.current_week if cur_sprint else self._pcfg.get("current_sprint_week", 1)
        prorata_ratio = sweek / self._sw if self._prorata else 0.0

        total_pts = sum(s.story_points for s in live)
        done_pts = sum(s.story_points for s in live if s.status in COMPLETED_STATUSES)
        global_prorata = int(sum(s.story_points for s in live if s.status in ACTIVE_STATUSES) * prorata_ratio)
        effective = done_pts + global_prorata

        # Velocity
        avg_pw = 0.0
        if velocities:
            avg_pw = sum(v.completed_per_week for v in velocities) / len(velocities)
        elif done_pts > 0:
            avg_pw = done_pts / weeks_elapsed(self._pcfg.get("start_date", "2025-10-01"))

        # Per-dimension KPIs with prorata
        dim_kpis = [self._dim_kpi(n, live, total_pts, prorata_ratio, avg_pw) for n in self._dims]

        blocked = [s for s in live if s.status == StoryStatus.BLOCKED]
        raf = self._raf(total_pts, done_pts, global_prorata, velocities, live)
        ratio = effective / total_pts if total_pts > 0 else 0.0
        variations = self._vars(total_pts, effective, len(blocked), previous)

        # Current sprint stories
        cur_stories = []
        if self._show_sprint and cur_sprint:
            cur_stories = [s for s in live if s.sprint and str(snum) in s.sprint
                           and s.status not in COMPLETED_STATUSES]

        return WeeklyReport(
            generated_at=now, week_number=now.isocalendar()[1], year=now.year,
            sprint_name=f"Sprint {snum}", sprint_number=snum, sprint_week=sweek,
            dimension_kpis=dim_kpis, blocked_stories=blocked,
            unidentified_stories=filter_abandoned(unidentified or []),
            current_sprint_stories=cur_stories,
            raf=raf, velocities=velocities, variations=variations,
            total_points=total_pts, done_points=done_pts,
            prorata_points=global_prorata, effective_done=effective,
            overall_completion=ratio, overall_weather=self._weather(ratio),
            jira_base_url=self._jira_url,
            project_start=self._pcfg.get("start_date", "2025-10-01"),
            project_end=self._pcfg.get("end_date", "2026-09-30"),
            sprint_duration_weeks=self._sw,
            all_stories=live, sprint_timeline=timeline,
        )

    def _dim_kpi(self, node: DimensionNode, stories: list[JiraStory],
                 total_pts: int, prorata_ratio: float, avg_pw: float) -> DimensionKPI:
        """Compute per-dimension KPI with prorata and guaranteed RAF."""
        direct = [s for s in stories if node.label in s.labels]
        child_kpis = [self._dim_kpi(c, stories, total_pts, prorata_ratio, avg_pw) for c in node.children]

        if child_kpis:
            ckeys = set()
            for c in child_kpis:
                ckeys.update(c.stories)
            extra = [s for s in direct if s.key not in ckeys]
            all_keys = list(ckeys) + [s.key for s in extra]
            done_p = sum(c.done_points for c in child_kpis) + sum(s.story_points for s in extra if s.status in COMPLETED_STATUSES)
            prorata_p = sum(c.prorata_points for c in child_kpis) + int(sum(s.story_points for s in extra if s.status in ACTIVE_STATUSES) * prorata_ratio)
            tp = sum(c.total_points for c in child_kpis) + sum(s.story_points for s in extra)
            bds = [c.breakdown for c in child_kpis]
            if extra:
                bds.append(_bkdn(extra))
            bd = _merge(bds)
        elif direct:
            all_keys = [s.key for s in direct]
            done_p = sum(s.story_points for s in direct if s.status in COMPLETED_STATUSES)
            prorata_p = int(sum(s.story_points for s in direct if s.status in ACTIVE_STATUSES) * prorata_ratio)
            tp = sum(s.story_points for s in direct)
            bd = _bkdn(direct)
        else:
            return DimensionKPI(label=node.label, display=node.display, depth=node.depth, children=child_kpis)

        eff = done_p + prorata_p
        est_total = self._est_total(node, child_kpis, total_pts)

        # Backlog = concrete untreated work already in Jira
        backlog_pts = bd.pending + bd.blocked

        # RAF: max of (projection-based, backlog concrete, min_raf velocity)
        w_rem = weeks_remaining(self._pcfg.get("end_date", "2026-09-30"))
        weight = self._dw.get(node.label, 0.0)
        min_raf = max(int(avg_pw * w_rem * weight * 0.1), 1) if weight > 0 and avg_pw > 0 else 0
        projection_remaining = max(est_total - eff, 0)
        est_remaining = max(projection_remaining, backlog_pts, min_raf) if (est_total > 0 or backlog_pts > 0) else 0

        # Completion: based on effective_total = eff + est_remaining
        effective_total = eff + est_remaining
        if effective_total > 0:
            ratio = min(eff / effective_total, 0.99) if est_remaining > 0 else 1.0
        else:
            ratio = 0.0

        return DimensionKPI(
            label=node.label, display=node.display, depth=node.depth,
            total_points=tp, done_points=done_p, prorata_points=prorata_p,
            effective_done=eff, estimated_remaining=est_remaining,
            backlog_points=backlog_pts,
            estimated_project_total=est_total,
            completion_ratio=ratio, weather=self._weather(ratio),
            breakdown=bd, children=child_kpis, stories=all_keys,
        )

    def _est_total(self, node, child_kpis, total_pts):
        w = self._dw.get(node.label, 0.0)
        if w > 0 and total_pts > 0:
            return int(total_pts * w)
        if child_kpis:
            return sum(c.estimated_project_total for c in child_kpis)
        return 0

    def _raf(self, total_pts, done_pts, prorata_pts, velocities, live_stories):
        eff = done_pts + prorata_pts
        # Backlog = concrete untreated stories
        backlog_pts = sum(s.story_points for s in live_stories
                         if s.status not in COMPLETED_STATUSES and s.status not in ACTIVE_STATUSES)

        # Unestimated padding: stories with 0 SP, not done, not active, not planned
        unest = [s for s in live_stories
                 if s.story_points == 0
                 and s.status not in COMPLETED_STATUSES
                 and s.status not in ACTIVE_STATUSES
                 and not s.sprint]
        unest_padding = len(unest) * self._unest_default

        projection_remaining = max(total_pts - eff, 0)
        remaining = max(projection_remaining, backlog_pts) + unest_padding

        s0 = self._pcfg.get("start_date", "2025-10-01")
        e0 = self._pcfg.get("end_date", "2026-09-30")
        we = weeks_elapsed(s0); wr = weeks_remaining(e0)
        if velocities:
            avg = sum(v.completed_per_week for v in velocities) / len(velocities)
        elif done_pts > 0:
            avg = done_pts / we
        else:
            avg = 0.0
        proj = eff + int(avg * wr)
        need = remaining / wr if wr > 0 else 999.0
        return RAFEstimation(
            total_points=total_pts, completed_points=eff,
            remaining_points=max(remaining, 0), avg_velocity_per_week=round(avg, 1),
            sprints_done=len(velocities), weeks_done=we, weeks_remaining=wr,
            projected_total=proj, project_deadline=date.fromisoformat(e0),
            on_track=avg >= need, velocity_needed_per_week=round(need, 1),
            prorata_points=prorata_pts,
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
