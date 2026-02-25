"""KPI Calculator v7.

Rules:
- Abandoned stories excluded from everything.
- Prorata temporis: status-based partial credit (in-progress: 25%, review: 75%, testing: 50%).
- effective_done = done + prorata.
- Completion = effective_done / total_points.
- Weather is TIME-RELATIVE: completion / time_progress → adjusts for project phase.
- estimated_remaining coherent with projection, +10% margin.
- Unestimated padding capped at max_ratio × total_known_points.
"""
from __future__ import annotations
from datetime import date, datetime
from typing import Any
import structlog
from kpi.domain.dimensions import parse_dimensions
from kpi.domain.models import (
    ACTIVE_STATUSES, COMPLETED_STATUSES, BacklogStability, ComplementaryKPIs,
    ComparisonResult, DimensionKPI, DimensionNode, ENV_NAMES, EnvBreakdown,
    EnvCoverageWarning, JiraStory, OPS_LABELS,
    ProjectionEstimate, RAFEstimation, Snapshot, SprintVelocity, StatusBreakdown,
    StoryStatus, TagScore, Variation, WeatherIcon, WeeklyReport,
)
from kpi.services.dates import build_sprint_calendar, business_days_france, find_current_sprint, parse_date, weeks_elapsed, weeks_remaining

logger = structlog.get_logger()

# Prorata weights per active status (conservative)
PRORATA_WEIGHTS = {
    StoryStatus.IN_PROGRESS: 0.25,
    StoryStatus.REVIEW: 0.75,
    StoryStatus.TESTING: 0.50,
}

# Tag scoring: structural advancement weights per status (AC #2)
TAG_STATUS_WEIGHTS = {
    StoryStatus.DONE: 1.0,
    StoryStatus.DELIVERED: 1.0,
    StoryStatus.IN_PROGRESS: 0.5,
    StoryStatus.REVIEW: 0.75,
    StoryStatus.TESTING: 0.65,
    StoryStatus.TODO: 0.2,
    StoryStatus.BACKLOG: 0.1,
    StoryStatus.SPECIFICATION: 0.15,
    StoryStatus.BLOCKED: 0.1,
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
        self._projection_margin = cfg.get("projection_margin", 0.10)
        self._projection_default_weight = cfg.get("projection_default_weight", 0.3)

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

        # Enrich velocities with sprint dates from Jira
        if jira_sprints and velocities:
            by_num = {s["number"]: s for s in jira_sprints if s.get("number")}
            for v in velocities:
                sp = by_num.get(v.sprint_number)
                if sp:
                    v.start_date = sp.get("start_date", "")
                    v.end_date = sp.get("end_date", "")

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

        variations = self._vars(total_pts, done_pts, len(blocked), previous)  # extended below with scores

        # Tag scores: structural advancement per dimension (Story 1-1)
        # Global view: no sprint penalty (status weights only)
        cur_sprint_name = f"Sprint {snum}"
        tag_scores = [self._tag_score(n, live, cur_sprint_name,
                                       apply_sprint_weight=False) for n in self._dims]
        # Merge DimensionKPI operational data into TagScore (Story 2-2)
        self._merge_dim_into_tags(tag_scores, dim_kpis)

        # Score_Global: weighted average of top-level tag scores (Story 1-3)
        # "À date": sprint-weighted scores for current/past sprints only
        past_sprint_names = {s.name for s in timeline if s.is_past or s.is_current}
        date_stories = [s for s in live if s.sprint in past_sprint_names or s.status in COMPLETED_STATUSES]
        date_total_pts = sum(s.story_points for s in date_stories)
        date_done_pts = sum(s.story_points for s in date_stories if s.status in COMPLETED_STATUSES)
        tag_scores_date = [self._tag_score(n, date_stories, cur_sprint_name) for n in self._dims]
        score_global_date = self._score_global(tag_scores_date,
                                               time_progress=time_progress,
                                               total_project_pts=total_pts)

        # Future projection (Story 1-5)
        projection = self._compute_projection(live, raf, tag_scores)

        # "Global projet": weighted average of tag scores (consistent with domain table)
        score_global_project = self._score_global(tag_scores)

        # Backlog stability (Story 1-4)
        backlog_stability = self._backlog_stability(live, cur_sprint, raf)

        # Complementary KPIs (Story 1-6)
        complementary_kpis = self._complementary_kpis(live, tag_scores)

        # Score variations (as integer %, for delta display)
        if previous:
            variations.extend([
                Variation(label="score_date", current=round(score_global_date * 100), previous=round(previous.score_global_date * 100)),
                Variation(label="score_projet", current=round(score_global_project * 100), previous=round(previous.score_global_project * 100)),
            ])

        # Period comparison (Story 1-8)
        comparisons = self._comparisons(
            score_global_project, tag_scores, backlog_stability, complementary_kpis, previous)

        # Env breakdown + coverage warnings
        env_breakdown = self._compute_env_breakdown(live)
        env_coverage_warnings = self._check_env_coverage(live)

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
            time_progress=round(time_progress, 4),
            days_remaining=max((date.fromisoformat(self._pcfg.get("end_date", "2026-09-30")) - date.today()).days, 0),
            business_days_elapsed=business_days_france(parse_date(self._pcfg.get("start_date", "2025-10-01")), date.today()),
            business_days_remaining=business_days_france(date.today(), parse_date(self._pcfg.get("end_date", "2026-09-30"))),
            sprint_duration_weeks=self._sw,
            tag_scores=tag_scores,
            date_total_points=date_total_pts,
            date_done_points=date_done_pts,
            date_stories=date_stories,
            score_global_date=round(score_global_date, 4),
            score_global_project=round(score_global_project, 4),
            projection=projection,
            backlog_stability=backlog_stability,
            complementary_kpis=complementary_kpis,
            comparisons=comparisons,
            all_stories=live, sprint_timeline=timeline,
            env_breakdown=env_breakdown,
            env_coverage_warnings=env_coverage_warnings,
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

    def _tag_score(self, node: DimensionNode, stories: list[JiraStory],
                   current_sprint: str, *, apply_sprint_weight: bool = True) -> TagScore:
        """Compute structural advancement score for a dimension tag (AC #1-4).

        When apply_sprint_weight=False (global project view), the sprint
        proximity penalty is skipped — only status weights matter.
        """
        direct = [s for s in stories if node.label in s.labels]

        # Recurse into children first (AC #4)
        child_scores = [self._tag_score(c, stories, current_sprint,
                                         apply_sprint_weight=apply_sprint_weight) for c in node.children]

        # Collect direct stories not already counted by children
        child_keys = set()
        for cs in child_scores:
            child_keys.update(self._tag_score_keys(cs, stories))
        extra = [s for s in direct if s.key not in child_keys]

        # Compute weighted sum for direct/extra stories
        weighted_sum = 0.0
        total_pts = 0
        story_count = 0
        for s in extra:
            pts = max(s.story_points, 1)  # count 0-SP stories as 1 pt for scoring
            sw = TAG_STATUS_WEIGHTS.get(s.status, 0.0)
            if apply_sprint_weight:
                # Sprint weight (AC #3) — Done work always counts fully
                if s.status in COMPLETED_STATUSES:
                    spw = 1.0
                elif s.sprint and s.sprint == current_sprint:
                    spw = 1.0
                elif s.status in ACTIVE_STATUSES:
                    spw = 0.5
                else:
                    spw = 0.1
            else:
                spw = 1.0  # global view: no sprint penalty
            weighted_sum += pts * sw * spw
            total_pts += pts
            story_count += 1

        # Aggregate children weighted sums
        for cs in child_scores:
            weighted_sum += cs.weighted_sum
            total_pts += cs.total_points
            story_count += cs.story_count

        score = weighted_sum / total_pts if total_pts > 0 else 0.0

        return TagScore(
            label=node.label, display=node.display,
            score=score, story_count=story_count,
            total_points=total_pts, weighted_sum=weighted_sum,
            children=child_scores,
        )

    def _tag_score_keys(self, ts: TagScore, stories: list[JiraStory]) -> set[str]:
        """Collect story keys covered by a TagScore (for dedup)."""
        keys = {s.key for s in stories if ts.label in s.labels}
        for c in ts.children:
            keys.update(self._tag_score_keys(c, stories))
        return keys

    def _merge_dim_into_tags(self, tags: list[TagScore], dims: list[DimensionKPI]) -> None:
        """Merge operational DimensionKPI data into TagScore objects (Story 2-2).

        Both lists share the same tree structure (same dimension nodes),
        so we merge by matching index positions recursively.
        Weather is derived from the structural score (tag.score) so that
        the icon matches the percentage displayed in the domain table.
        """
        for tag, dim in zip(tags, dims):
            tag.weather = self._weather(tag.score)
            tag.completion_ratio = dim.completion_ratio
            tag.done_points = dim.done_points
            tag.estimated_remaining = dim.estimated_remaining
            tag.breakdown = dim.breakdown
            tag.stories = dim.stories
            if tag.children and dim.children:
                self._merge_dim_into_tags(tag.children, dim.children)

    def _backlog_stability(self, stories: list[JiraStory],
                           cur_sprint: any, raf: RAFEstimation | None) -> BacklogStability:
        """Compute scope evolution indicator (Story 1-4)."""
        total = len(stories)
        if not total:
            return BacklogStability()

        # Stories created this sprint (by created_date within sprint dates)
        created_sprint = 0
        done_sprint = 0
        if cur_sprint and cur_sprint.start_date:
            sp_start = cur_sprint.start_date
            sp_end = cur_sprint.end_date or date.today().isoformat()
            for s in stories:
                if s.created_date and sp_start <= s.created_date[:10] <= sp_end:
                    created_sprint += 1
                if s.status in COMPLETED_STATUSES and s.sprint and cur_sprint.name in s.sprint:
                    done_sprint += 1

        variation_date = (created_sprint - done_sprint) / total if total else 0.0

        # Estimated final stories from velocity projection
        est_final = total
        if raf and raf.avg_velocity_per_week > 0:
            sprints_left = max(raf.weeks_remaining // self._sw, 0)
            avg_stories_per_sprint = max(total / max(raf.sprints_done, 1), 1)
            est_final = total + int(avg_stories_per_sprint * sprints_left * 0.3)  # 30% new stories
        variation_project = total / est_final if est_final else 0.0

        return BacklogStability(
            variation_date=round(variation_date, 4),
            variation_project=round(variation_project, 4),
            stories_created_sprint=created_sprint,
            stories_done_sprint=done_sprint,
            total_stories=total,
            estimated_final_stories=est_final,
        )

    def _complementary_kpis(self, stories: list[JiraStory],
                             tag_scores: list[TagScore]) -> ComplementaryKPIs:
        """Compute additional quality KPIs (Story 1-6)."""
        total = len(stories)
        if not total:
            return ComplementaryKPIs()

        expected_top = len(self._dims)  # number of top-level dimensions

        # pct_complete: fully tagged + Done
        complete = sum(1 for s in stories
                       if s.status in COMPLETED_STATUSES
                       and len(s.labels) >= expected_top)
        pct_complete = complete / total

        # pct_partial: >=50% tags + active
        partial = sum(1 for s in stories
                      if s.status in ACTIVE_STATUSES
                      and len(s.labels) >= max(expected_top // 2, 1))
        pct_partial = partial / total

        # pct_critical_done: not available without priority field, use 0-SP as proxy
        # Stories with > avg points considered "critical"
        avg_pts = sum(s.story_points for s in stories) / total if total else 0
        critical = [s for s in stories if s.story_points > avg_pts * 1.5]
        crit_done = sum(1 for s in critical if s.status in COMPLETED_STATUSES)
        pct_critical = crit_done / len(critical) if critical else 0.0

        # doc_index: average score of documentation-related tags
        doc_labels = {"documentation", "tests-fonctionnels", "test-fonctionnel", "qualite"}
        doc_scores = []
        def _find_doc(scores):
            for ts in scores:
                if ts.label in doc_labels and ts.total_points > 0:
                    doc_scores.append(ts.score)
                _find_doc(ts.children)
        _find_doc(tag_scores)
        doc_index = sum(doc_scores) / len(doc_scores) if doc_scores else 0.0

        return ComplementaryKPIs(
            pct_complete=round(pct_complete, 4),
            pct_partial=round(pct_partial, 4),
            pct_critical_done=round(pct_critical, 4),
            doc_index=round(doc_index, 4),
        )

    def _comparisons(self, score_global: float, tag_scores: list[TagScore],
                      backlog: BacklogStability | None, comp_kpis: ComplementaryKPIs | None,
                      previous: Snapshot | None) -> list[ComparisonResult]:
        """Compute deltas vs previous snapshot (Story 1-8)."""
        if not previous:
            return []
        results = []
        # Score_Global
        results.append(ComparisonResult(
            label="Score Global", current=round(score_global, 4),
            previous=round(previous.score_global, 4)))
        # Per-tag scores
        for ts in tag_scores:
            prev_score = previous.tag_scores.get(ts.label, 0.0)
            if ts.total_points > 0 or prev_score > 0:
                results.append(ComparisonResult(
                    label=f"Tag: {ts.label}", current=round(ts.score, 4),
                    previous=round(prev_score, 4)))
        # Backlog stability
        if backlog:
            results.append(ComparisonResult(
                label="Backlog Variation", current=round(backlog.variation_project, 4),
                previous=round(previous.backlog_variation, 4)))
        # Complementary KPIs
        if comp_kpis:
            results.append(ComparisonResult(
                label="% Complete", current=round(comp_kpis.pct_complete, 4),
                previous=0.0))
            results.append(ComparisonResult(
                label="Doc Index", current=round(comp_kpis.doc_index, 4),
                previous=0.0))
        return results

    @staticmethod
    def _compute_env_breakdown(stories: list[JiraStory]) -> list[EnvBreakdown]:
        """Group stories by env: label. Max 1 env per story (warn if violated)."""
        env_map: dict[str, list[JiraStory]] = {}
        for s in stories:
            envs = [l for l in s.labels if l.startswith("env:")]
            if len(envs) > 1:
                logger.warning("multi_env_labels", key=s.key, envs=envs)
            env_name = envs[0].split(":", 1)[1] if envs else None
            if env_name:
                env_map.setdefault(env_name, []).append(s)
        out = []
        for env_name in sorted(env_map):
            group = env_map[env_name]
            out.append(EnvBreakdown(
                env_name=env_name,
                story_count=len(group),
                total_points=sum(s.story_points for s in group),
                done_points=sum(s.story_points for s in group if s.status in COMPLETED_STATUSES),
                stories=[s.key for s in group],
            ))
        return out

    @staticmethod
    def _check_env_coverage(stories: list[JiraStory]) -> list[EnvCoverageWarning]:
        """Detect ops/infra stories that lack full environment coverage."""
        warnings = []
        for s in stories:
            ops = [l for l in s.labels if l in OPS_LABELS]
            if not ops:
                continue
            existing = [l.split(":", 1)[1] for l in s.labels if l.startswith("env:")]
            missing = [e for e in ENV_NAMES if e not in existing]
            if missing:
                warnings.append(EnvCoverageWarning(
                    story_key=s.key, summary=s.summary,
                    ops_labels=ops, existing_envs=existing, missing_envs=missing,
                ))
        return warnings

    def _score_global(self, tag_scores: list[TagScore], *,
                       time_progress: float | None = None,
                       total_project_pts: int | None = None) -> float:
        """Weighted average of top-level tag scores using domain_weight (AC #1).

        When time_progress and total_project_pts are provided (mode "à date"),
        a soft dampening is applied: the raw score is reduced by up to 30%
        proportional to the remaining project time. This prevents score_date
        from reaching 100% mid-project while staying realistic (>70% when
        all sprinted stories are done).

        Formula: score_date = raw_score × (1 - dampening)
        where dampening = max(0, (1 - time_progress) × 0.3)
        """
        numerator = 0.0
        denominator = 0.0
        for ts in tag_scores:
            w = self._dw.get(ts.label, 0.0)
            if w > 0 and ts.total_points > 0:
                numerator += ts.score * w
                denominator += w
        raw = numerator / denominator if denominator > 0 else 0.0
        if time_progress is not None and total_project_pts and time_progress < 1.0:
            dampening = max(0.0, (1.0 - time_progress) * 0.3)
            raw *= (1.0 - dampening)
        return raw

    def _compute_projection(self, stories: list[JiraStory], raf: RAFEstimation | None,
                            tag_scores: list[TagScore]) -> ProjectionEstimate:
        """Project future stories based on velocity (Story 1-5 AC #1,#2,#3)."""
        if not raf or raf.avg_velocity_per_week <= 0:
            return ProjectionEstimate(default_weight=self._projection_default_weight)

        sprints_remaining = max(raf.weeks_remaining // self._sw, 0)
        vel_per_sprint = raf.avg_velocity_per_week * self._sw
        projected_pts = int(vel_per_sprint * sprints_remaining)
        # Estimate story count from avg points per story
        total_stories = len(stories)
        total_pts = sum(s.story_points for s in stories) or 1
        avg_pts_per_story = total_pts / max(total_stories, 1)
        projected_stories = int(projected_pts / max(avg_pts_per_story, 1))

        # Distribute by current tag ratio
        dist: dict[str, int] = {}
        for ts in tag_scores:
            if ts.total_points > 0 and total_pts > 0:
                ratio = ts.total_points / total_pts
                dist[ts.label] = max(int(projected_pts * ratio), 0)

        return ProjectionEstimate(
            projected_stories=projected_stories,
            projected_points=projected_pts,
            default_weight=self._projection_default_weight,
            distribution_by_tag=dist,
        )

    def _score_global_with_projection(self, tag_scores: list[TagScore],
                                       projection: ProjectionEstimate) -> float:
        """Score_Global projet including projected future stories (AC #4).

        Projected points expand the denominator only (more work ahead)
        without adding phantom progress to the numerator. This keeps
        the global score coherent with individual domain scores.
        """
        numerator = 0.0
        denominator = 0.0
        for ts in tag_scores:
            w = self._dw.get(ts.label, 0.0)
            if w <= 0:
                continue
            proj_pts = projection.distribution_by_tag.get(ts.label, 0) if projection else 0
            # Denominator includes projected future work; numerator stays real
            total_pts = ts.total_points + proj_pts
            if total_pts > 0:
                adj_score = ts.weighted_sum / total_pts
                numerator += adj_score * w
                denominator += w
        return numerator / denominator if denominator > 0 else 0.0


def score_global_text(score: float, mode: str = "date") -> str:
    """Pedagogical text for Score_Global (Story 1-3 AC #6)."""
    pct = int(score * 100)
    if mode == "date":
        return f"Score global à date {pct}% — le projet est à {pct}% de complétude structurelle sur les sprints réalisés."
    return f"Score global projet {pct}% — le projet est à {pct}% de complétude structurelle, toutes US confondues."


def projection_text(projection: ProjectionEstimate) -> str:
    """Pedagogical text for future projection (Story 1-5 AC #5)."""
    if not projection or projection.projected_stories == 0:
        return "Aucune projection — vélocité insuffisante pour estimer les US futures."
    return (f"On anticipe {projection.projected_stories} US ({projection.projected_points} pts) "
            f"dans les prochains mois, sur la base de la vélocité passée, "
            f"pour avoir une estimation crédible de l'avancement projet futur.")


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
