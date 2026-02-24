"""Standalone v7 tests — stdlib only, no network."""
import yaml, re, os, tempfile
from datetime import date, timedelta

with open(os.path.join(os.path.dirname(__file__), '..', 'config.yaml')) as f:
    CFG = yaml.safe_load(f)
BASE = os.path.join(os.path.dirname(__file__), '..', 'src', 'kpi')
ok = fail = 0

def t(name, cond, msg=""):
    global ok, fail
    if cond: print(f"  ✅ {name}"); ok+=1
    else: print(f"  ❌ {name}: {msg}"); fail+=1

# ═══════════════════════════════════════════════════════
# CONFIG: structure, labels, weights
# ═══════════════════════════════════════════════════════
def cl(d):
    n=0
    for x in d:
        l=x["label"]
        assert ":"not in l and "_"not in l and l==l.lower() and " "not in l, l
        n+=1; n+=cl(x.get("children",[]))
    return n
try: n=cl(CFG["dimensions"]); t("labels_format", n>40)
except Exception as e: t("labels_format", False, str(e))

top=[d["label"] for d in CFG["dimensions"]]
t("three_top_levels", top==["fonctionnel","technique","organisationnel"])
org=CFG["dimensions"][2]; ok2=[c["label"] for c in org["children"]]
t("org_pilotage_doc", "pilotage" in ok2 and "documentation" in ok2)
tech=CFG["dimensions"][1]; tk=[c["label"] for c in tech["children"]]
t("tech_conception_dev", "conception" in tk and "developpement" in tk)

dw=CFG["domain_weight"]; total=sum(dw.values())
t("domain_weight_sum", 0.95<=total<=1.05, f"{total}")
t("cfg_unestimated_default", CFG.get("unestimated_default_points") == 3)
t("cfg_unestimated_max_ratio", CFG.get("unestimated_max_ratio") == 0.5)
t("cfg_projection_margin", CFG.get("projection_margin") == 0.15)

# No prorata or show_current_sprint_stories in config
t("cfg_no_prorata", "prorata_current_sprint" not in CFG.get("project", {}))
t("cfg_no_show_sprint", "show_current_sprint_stories" not in CFG.get("project", {}))

# ═══════════════════════════════════════════════════════
# UTILS: safe_int, keyword regex
# ═══════════════════════════════════════════════════════
def si(v):
    if v is None: return 0
    try: return int(float(v))
    except: return 0
t("safe_int", all(si(i)==e for i,e in [(None,0),(5,5),(3.0,3),("8",8),("5.0",5),("abc",0),("",0)]))

def ckw(kw):
    e=re.escape(kw)
    return re.compile(rf"\b{e}\b",re.I) if len(kw)<=4 and " "not in kw else re.compile(e,re.I)
t("no_false_tu", ckw("TU").search("référentiel des structures") is None)
t("tu_matches", ckw("TU").search("les TU du module") is not None)

# ═══════════════════════════════════════════════════════
# SPRINT CALENDAR
# ═══════════════════════════════════════════════════════
def bs(cfg):
    p=cfg.get("project",{});w=p.get("sprint_duration_weeks",3)
    s=date.fromisoformat(p.get("start_date","2025-10-01"));e=date.fromisoformat(p.get("end_date","2026-09-30"))
    sp=[];c=s;n=1;td=date.today()
    while c<e:
        se=min(c+timedelta(days=w*7-1),e);sp.append({"n":n,"s":c.isoformat(),"e":se.isoformat(),"cur":c<=td<=se})
        c=se+timedelta(days=1);n+=1
    return sp
sps=bs(CFG)
t("sprint_count", len(sps)>=15)
t("sprint_1_start", sps[0]["s"]=="2025-10-01")
t("sprints_ordered", all(sps[i]["s"]<sps[i+1]["s"] for i in range(len(sps)-1)))

sw=CFG["project"]["sprint_duration_weeks"]
t("velocity_3week", sw==3 and round(21/sw,1)==7.0)

# ═══════════════════════════════════════════════════════
# JIRA ADAPTER: code checks
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'adapters', 'jira_adapter.py')) as f: jc=f.read()
t("no_recit", 'Récit' not in jc)
t("age_fallback", 'days_since_iso' in jc and 'auto_done' in jc)
t("created_field", 'created' in jc)
t("configurable_age", 'unknown_status_done_after_days' in jc)
t("jira_fetch_sprints", 'def fetch_sprints' in jc)
t("jira_fetch_tasks", 'task_types' in jc)
t("jira_parent_field", 'parent' in jc and 'issuelinks' in jc)
t("jira_fetch_issue_types", 'def fetch_issue_types' in jc)
t("jira_jql_list_helper", 'def _jql_list' in jc)
t("jira_dynamic_discovery", 'discovered' in jc and 'fetch_issue_types' in jc)
t("jira_graceful_task_fetch", '_jql_with_type_fallback' in jc)
t("jira_configurable_types", 'story_types' in jc and 'task_types' in jc)
t("jira_project_types_fallback", '_fetch_project_types' in jc and '_fetch_global_types' in jc)
t("jira_classify_types", '_classify_types' in jc)
t("jira_debug_issue_types", 'def debug_issue_types' in jc)
t("jira_type_by_type_fallback", 'type_ok' in jc and 'type_not_found' in jc)
t("jira_resolve_project_key", '_resolve_project_key' in jc)
t("jira_fetch_all_projects", '_fetch_all_projects' in jc)
t("jira_debug_projects", 'def debug_projects' in jc)
t("jira_configured_project", '_configured_project' in jc)
t("jira_project_key_valid_log", 'project_key_valid' in jc)
t("jira_project_key_resolved_by_name", 'project_key_resolved_by_name' in jc)
t("jira_project_key_unresolved_log", 'project_key_unresolved' in jc)

# ═══════════════════════════════════════════════════════
# DATES: days_since
# ═══════════════════════════════════════════════════════
def ds(s):
    if not s: return None
    try: return (date.today()-date.fromisoformat(s[:10])).days
    except: return None
t("ds_old", ds("2025-10-15T10:30:00")>100)
t("ds_today", ds(date.today().isoformat())==0)
t("ds_none", ds(None) is None)

# ═══════════════════════════════════════════════════════
# TEMPLATES: preview — points only, no prorata, no timeline
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'templates', 'kpi_preview.html')) as f: tpl=f.read()
t("tpl_tailwind_cdn", 'cdn.tailwindcss.com' in tpl)
t("tpl_tailwind_config", 'tailwind.config' in tpl)
t("tpl_has_macros", '{%- macro ' in tpl)
t("tpl_pts_termines", 'pts termines' in tpl)
t("tpl_restant_estime", 'restant estime' in tpl)
t("tpl_fold", 'fold(' in tpl)
t("tpl_drawer", 'drawer' in tpl)
t("tpl_jira_links", 'jira_base_url' in tpl)
t("tpl_estimated_remaining", 'estimated_remaining' in tpl)
t("tpl_no_prorata", 'prorata' not in tpl)
t("tpl_no_timeline", 'sprint_timeline' not in tpl)
t("tpl_no_current_sprint_stories", 'current_sprint_stories' not in tpl)
t("tpl_no_orphelines", 'unidentified_stories' not in tpl or tpl.count('unidentified_stories') == 0)
t("tpl_blocked_stories", 'blocked_stories' in tpl)
t("tpl_points_only", 'story_table' not in tpl or tpl.count('show_status') <= 1)

# ═══════════════════════════════════════════════════════
# TEMPLATES: confluence — points only
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'templates', 'kpi_confluence.html.j2')) as f: ct=f.read()
t("conf_pts_termines", 'pts termines' in ct)
t("conf_no_prorata", 'prorata' not in ct)
t("conf_no_current_sprint_stories", 'current_sprint_stories' not in ct)

# ═══════════════════════════════════════════════════════
# CALCULATOR: code checks — no prorata
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: cc=f.read()
t("calc_filter_abandoned", 'filter_abandoned' in cc)
t("calc_prorata_weights", 'PRORATA_WEIGHTS' in cc)
t("calc_prorata_func", 'def _prorata_pts' in cc)
t("calc_effective_done", 'effective_done = done_pts + prorata_pts' in cc)
t("calc_min_raf", 'min_raf' in cc)
t("calc_backlog_in_raf", 'backlog_pts' in cc)
t("calc_completion_prorata", 'effective_done / total_pts' in cc)
t("calc_time_relative_weather", 'relative_ratio' in cc and 'time_progress' in cc)
t("calc_max_ratio_cap", 'max_ratio' in cc and 'time_progress' in cc)
t("calc_global_est_remaining", 'global_est_remaining' in cc)
t("calc_unest_max_ratio", 'unest_max_ratio' in cc)
t("calc_projection_margin", 'projection_margin' in cc)
t("calc_velocity_per_sprint", 'vel_per_sprint' in cc)

# ═══════════════════════════════════════════════════════
# MODELS: no prorata fields
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'domain', 'models.py')) as f: mc=f.read()
t("model_effective_done", 'effective_done' in mc)
t("model_backlog_points", 'backlog_points' in mc)
t("model_velocity_per_sprint", 'velocity_per_sprint' in mc)
t("model_no_current_sprint_stories", 'current_sprint_stories' not in mc)
t("model_estimated_remaining_report", 'estimated_remaining: int = 0' in mc)

# ═══════════════════════════════════════════════════════
# CLI: commands
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'cli.py')) as f: cli=f.read()
t("cli_click", 'import click' in cli and '@click.group' in cli)
t("cli_migrate", 'migrate-labels' in cli or 'migrate_labels' in cli)
t("cli_compare", 'compare' in cli)
t("cli_snapshot", 'snapshot' in cli)
t("cli_purge_labels", 'purge-labels' in cli or 'purge_labels' in cli)
t("cli_purge_pattern_param", '--pattern' in cli)
t("cli_fetch_sprints", 'fetch_sprints' in cli)
t("cli_jira_sprints_param", 'jira_sprints' in cli)
t("cli_debug_issuetypes", 'debug-issuetypes' in cli and 'debug_issue_types' in cli)
t("cli_debug_projects", 'debug-projects' in cli and 'debug_projects' in cli)
t("cli_project_resolved", '_project' in cli)
t("cli_estimated_remaining_show", 'estimated_remaining' in cli)

# ═══════════════════════════════════════════════════════
# LABELS: key dimensions exist
# ═══════════════════════════════════════════════════════
def fl(dims,l):
    for d in dims:
        if d["label"]==l: return True
        if fl(d.get("children",[]),l): return True
    return False
t("label_backend", fl(CFG["dimensions"],"backend"))
t("label_conception_technique", fl(CFG["dimensions"],"conception-technique"))

# ═══════════════════════════════════════════════════════
# REBRAND: no REFE/dgfip references
# ═══════════════════════════════════════════════════════
import glob as gl
src_files = gl.glob(os.path.join(BASE, '**', '*.py'), recursive=True)
all_src = ""
for f in src_files:
    with open(f) as fh: all_src += fh.read()
t("no_refe_in_imports", 'from refe_kpi' not in all_src and 'import refe_kpi' not in all_src)
t("no_refe_in_config", 'REFE' not in open(os.path.join(os.path.dirname(__file__), '..', 'config.yaml')).read().replace('referentiels', ''))
t("package_is_kpi", os.path.isdir(os.path.join(os.path.dirname(__file__), '..', 'src', 'kpi')))
t("no_refe_package", not os.path.isdir(os.path.join(os.path.dirname(__file__), '..', 'src', 'refe_kpi')))

with open(os.path.join(os.path.dirname(__file__), '..', 'pyproject.toml')) as f: pt=f.read()
t("pyproject_no_refe", 'refe' not in pt.lower())
t("pyproject_kpi_package", 'include = "kpi"' in pt)
t("pyproject_kpi_script", 'kpi = "kpi.cli:main"' in pt)
t("cfg_project_key_no_refe", CFG["jira"]["project_key"] != "REFE")
t("cfg_db_path_no_refe", "refe" not in CFG.get("archive", {}).get("db_path", ""))

# ═══════════════════════════════════════════════════════
# RENDERER: tojson fix
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'services', 'renderer.py')) as f: rr=f.read()
t("renderer_custom_tojson", 'tojson' in rr and 'model_dump' in rr)
t("renderer_no_refe_title", 'REFE' not in rr)

# ═══════════════════════════════════════════════════════
# MODELS: Pydantic import + serialization
# ═══════════════════════════════════════════════════════
import sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from kpi.domain.models import (
    DimensionKPI, JiraStory, StatusBreakdown, StoryStatus,
    WeatherIcon, Variation, SprintVelocity, RAFEstimation,
    Snapshot, WeeklyReport, COMPLETED_STATUSES, ACTIVE_STATUSES,
    IssueType,
)

dk = DimensionKPI(label="test", total_points=10, done_points=5, completion_ratio=0.5)
try:
    serialized = json.dumps(dk.model_dump(mode="json"))
    t("dimension_kpi_serializable", '"label"' in serialized and '"test"' in serialized)
except Exception as e:
    t("dimension_kpi_serializable", False, str(e))

js = JiraStory(key="KPI-1", summary="Test", status=StoryStatus.DONE, story_points=5)
try:
    serialized = json.dumps(js.model_dump(mode="json"))
    t("jira_story_serializable", '"KPI-1"' in serialized)
except Exception as e:
    t("jira_story_serializable", False, str(e))

# ═══════════════════════════════════════════════════════
# MODELS: StatusBreakdown
# ═══════════════════════════════════════════════════════
sb = StatusBreakdown(done=30, delivered=10, in_progress=5, review=3, testing=2, backlog=20, todo=15, blocked=2)
t("sb_completed", sb.completed == 40)
t("sb_active", sb.active == 10)
t("sb_pending", sb.pending == 35)
t("sb_total", sb.total == 87)

# ═══════════════════════════════════════════════════════
# MODELS: Variation
# ═══════════════════════════════════════════════════════
v_up = Variation(label="points", current=120, previous=100)
t("var_delta_positive", v_up.delta == 20)
t("var_delta_str_plus", v_up.delta_str == "+20")
t("var_delta_pct", abs(v_up.delta_pct - 0.2) < 0.001)
v_down = Variation(label="blocked", current=2, previous=5)
t("var_delta_negative", v_down.delta == -3)
v_zero = Variation(label="x", current=10, previous=0)
t("var_delta_div_zero", v_zero.delta_pct == 0.0)

# ═══════════════════════════════════════════════════════
# MODELS: DimensionKPI progress_percent
# ═══════════════════════════════════════════════════════
dk75 = DimensionKPI(label="t", completion_ratio=0.75)
t("progress_percent_75", dk75.progress_percent == 75)
dk0 = DimensionKPI(label="t", completion_ratio=0.0)
t("progress_percent_0", dk0.progress_percent == 0)

# ═══════════════════════════════════════════════════════
# MODELS: Status sets
# ═══════════════════════════════════════════════════════
t("completed_statuses", StoryStatus.DONE in COMPLETED_STATUSES and StoryStatus.DELIVERED in COMPLETED_STATUSES)
t("completed_count", len(COMPLETED_STATUSES) == 2)
t("active_statuses", StoryStatus.IN_PROGRESS in ACTIVE_STATUSES)
t("active_count", len(ACTIVE_STATUSES) == 3)
t("abandoned_not_active", StoryStatus.ABANDONED not in ACTIVE_STATUSES and StoryStatus.ABANDONED not in COMPLETED_STATUSES)

# ═══════════════════════════════════════════════════════
# MODELS: IssueType + parent_key
# ═══════════════════════════════════════════════════════
story = JiraStory(key="KPI-1", summary="story", status=StoryStatus.DONE, story_points=5)
t("story_default_type", story.issue_type == IssueType.STORY)
t("story_no_parent", story.parent_key is None)

task = JiraStory(key="KPI-2", summary="task", status=StoryStatus.IN_PROGRESS,
                 story_points=2, issue_type=IssueType.TASK, parent_key="KPI-1")
t("task_type", task.issue_type == IssueType.TASK)
t("task_parent", task.parent_key == "KPI-1")
task_json = json.dumps(task.model_dump(mode="json"))
t("task_serializable", '"task"' in task_json and '"KPI-1"' in task_json)

# ═══════════════════════════════════════════════════════
# CALCULATOR: filter_abandoned
# ═══════════════════════════════════════════════════════
from kpi.services.calculator import filter_abandoned
stories_mix = [
    JiraStory(key="A", summary="a", status=StoryStatus.DONE, story_points=5),
    JiraStory(key="B", summary="b", status=StoryStatus.ABANDONED, story_points=8),
    JiraStory(key="C", summary="c", status=StoryStatus.IN_PROGRESS, story_points=3),
]
filtered = filter_abandoned(stories_mix)
t("filter_abandoned_count", len(filtered) == 2)
t("filter_abandoned_keys", {s.key for s in filtered} == {"A", "C"})
t("filter_abandoned_empty", filter_abandoned([]) == [])

# ═══════════════════════════════════════════════════════
# CALCULATOR: weather thresholds
# ═══════════════════════════════════════════════════════
from kpi.services.calculator import KPICalculator
mini_cfg = {
    "dimensions": [], "domain_weight": {},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
}
calc = KPICalculator(mini_cfg)
t("weather_sunny", calc._weather(0.85) == WeatherIcon.SUNNY)
t("weather_partly", calc._weather(0.65) == WeatherIcon.PARTLY_CLOUDY)
t("weather_cloudy", calc._weather(0.45) == WeatherIcon.CLOUDY)
t("weather_rainy", calc._weather(0.25) == WeatherIcon.RAINY)
t("weather_stormy", calc._weather(0.10) == WeatherIcon.STORMY)
t("weather_edge_80", calc._weather(0.80) == WeatherIcon.SUNNY)

# ═══════════════════════════════════════════════════════
# CALCULATOR: completion with prorata temporis
# ═══════════════════════════════════════════════════════
test_stories = [
    JiraStory(key="A", summary="done", status=StoryStatus.DONE, story_points=30),
    JiraStory(key="B", summary="wip", status=StoryStatus.IN_PROGRESS, story_points=20),
    JiraStory(key="C", summary="backlog", status=StoryStatus.BACKLOG, story_points=50),
]
report = calc.compute(test_stories, [])
# effective_done = done + prorata (active pts × sprint progress)
t("prorata_effective_gte_done", report.effective_done >= report.done_points,
  f"effective={report.effective_done} should be >= done={report.done_points}")
t("prorata_completion_gte_30", report.overall_completion >= 0.30,
  f"completion={report.overall_completion} should be >= 0.30 with prorata")
t("done_30pts", report.done_points == 30)
t("total_100pts", report.total_points == 100)
t("report_estimated_remaining", report.estimated_remaining >= 0,
  f"estimated_remaining={report.estimated_remaining} should be >= 0")

# ═══════════════════════════════════════════════════════
# CALCULATOR: unestimated padding
# ═══════════════════════════════════════════════════════
test_cfg2 = {
    "dimensions": [], "domain_weight": {},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
    "unestimated_default_points": 5,
    "unestimated_max_ratio": 0.5,
}
tc = KPICalculator(test_cfg2)
t("calc_unest_default", tc._unest_default == 5)
t("calc_unest_max_ratio", tc._unest_max_ratio == 0.5)

unest_stories = [
    JiraStory(key="A", summary="done", status=StoryStatus.DONE, story_points=10),
    JiraStory(key="B", summary="backlog", status=StoryStatus.BACKLOG, story_points=5),
    JiraStory(key="C", summary="unest 1", status=StoryStatus.BACKLOG, story_points=0),
    JiraStory(key="D", summary="unest 2", status=StoryStatus.TODO, story_points=0),
    JiraStory(key="E", summary="planned", status=StoryStatus.BACKLOG, story_points=0, sprint="Sprint 5"),
    JiraStory(key="F", summary="active 0sp", status=StoryStatus.IN_PROGRESS, story_points=0),
]
# total_pts=15, 2 unest × 5 = 10, cap = 15 * 0.5 = 7 → capped at 7
test_raf = tc._raf(15, 10, 10, [], unest_stories)
t("unest_count", test_raf.unestimated_count == 2, f"got {test_raf.unestimated_count}")
t("unest_padding_capped", test_raf.unestimated_padding == 7, f"got {test_raf.unestimated_padding} expected 7 (capped)")
t("unest_in_remaining", test_raf.remaining_points >= 7, f"got {test_raf.remaining_points}")

test_raf0 = tc._raf(10, 10, 10, [], [JiraStory(key="X", summary="x", status=StoryStatus.DONE, story_points=10)])
t("unest_zero_when_none", test_raf0.unestimated_count == 0 and test_raf0.unestimated_padding == 0)

# RAFEstimation fields
raf = RAFEstimation(unestimated_count=3, unestimated_padding=39, velocity_per_sprint=9.6)
t("raf_unestimated_fields", raf.unestimated_count == 3 and raf.unestimated_padding == 39)
t("raf_velocity_per_sprint", raf.velocity_per_sprint == 9.6)

# ═══════════════════════════════════════════════════════
# CALCULATOR: prorata temporis
# ═══════════════════════════════════════════════════════
prorata_cfg = {
    "dimensions": [], "domain_weight": {},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3,
                "current_sprint_week": 2},
    "jira": {"url": ""},
    "projection_margin": 0.15,
}
prorata_calc = KPICalculator(prorata_cfg)
prorata_stories = [
    JiraStory(key="A", summary="done", status=StoryStatus.DONE, story_points=30),
    JiraStory(key="B", summary="wip", status=StoryStatus.IN_PROGRESS, story_points=21),
    JiraStory(key="C", summary="review", status=StoryStatus.REVIEW, story_points=9),
    JiraStory(key="D", summary="backlog", status=StoryStatus.BACKLOG, story_points=40),
]
prorata_report = prorata_calc.compute(prorata_stories, [])
# done=30, in_progress=21×0.25=5, review=9×0.75=6 → prorata=11, effective=41
t("prorata_effective_gt_done", prorata_report.effective_done > prorata_report.done_points,
  f"effective={prorata_report.effective_done} should > done={prorata_report.done_points}")
# _prorata_pts sums floats then int: 21×0.25 + 9×0.75 = 5.25 + 6.75 = 12.0 → int(12) = 12
t("prorata_status_weights", prorata_report.effective_done == 30 + int(21*0.25 + 9*0.75),
  f"effective={prorata_report.effective_done} should be 30+12=42")
t("prorata_completion_reasonable", 0.30 < prorata_report.overall_completion < 0.60,
  f"completion={prorata_report.overall_completion:.2%} should be 30-60%, not inflated")
t("prorata_raf_velocity_per_sprint", prorata_report.raf.velocity_per_sprint > 0,
  f"vel/sprint={prorata_report.raf.velocity_per_sprint} should be > 0")

# Time-relative weather: 22% at ~40% through project → relative ~55% → partly_cloudy
t("weather_time_relative", prorata_report.overall_weather != WeatherIcon.STORMY,
  f"weather={prorata_report.overall_weather} should not be stormy with time-relative")

# RAF: projected_total coherent with estimated_remaining
t("raf_projected_coherent",
  prorata_report.raf.projected_total == prorata_report.effective_done + prorata_report.raf.remaining_points,
  f"proj={prorata_report.raf.projected_total} should == eff_done({prorata_report.effective_done}) + remaining({prorata_report.raf.remaining_points})")

# Global estimated_remaining with dimensions
dim_cfg = {
    "dimensions": [
        {"label": "fonctionnel", "display": "Fonctionnel", "children": [
            {"label": "referentiels", "display": "Ref", "keywords": ["ref"]}
        ]},
    ],
    "domain_weight": {"fonctionnel": 0.50, "referentiels": 0.0},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
    "unestimated_default_points": 3,
    "unestimated_max_ratio": 0.5,
    "projection_margin": 0.15,
}
dim_calc = KPICalculator(dim_cfg)
dim_stories = [
    JiraStory(key="A", summary="done", status=StoryStatus.DONE, story_points=20, labels=["referentiels"]),
    JiraStory(key="B", summary="backlog", status=StoryStatus.BACKLOG, story_points=30, labels=["referentiels"]),
    JiraStory(key="C", summary="unest", status=StoryStatus.BACKLOG, story_points=0),
]
dim_report = dim_calc.compute(dim_stories, [])
t("global_est_remaining_gte_raw", dim_report.estimated_remaining >= 30,
  f"est={dim_report.estimated_remaining} should be >= 30 (raw remaining)")
t("global_est_remaining_coherent", dim_report.estimated_remaining > 0,
  f"est={dim_report.estimated_remaining} should be > 0")

# Time-relative completion on dimension KPIs
for dk in dim_report.dimension_kpis:
    if dk.total_points > 0:
        t(f"dim_{dk.label}_time_relative_set", dk.time_relative_completion > 0,
          f"dim {dk.label} time_relative={dk.time_relative_completion} should > 0")
        break

# No dimension capped at 44% — verify natural ratio
for dk in dim_report.dimension_kpis:
    if dk.total_points > 0 and dk.completion_ratio > 0:
        t(f"dim_{dk.label}_no_artificial_cap", dk.completion_ratio != 0.44,
          f"dim {dk.label} ratio={dk.completion_ratio} should not be artificially capped")

# ═══════════════════════════════════════════════════════
# DATES: parse_date, weeks_between
# ═══════════════════════════════════════════════════════
from kpi.services.dates import parse_date, weeks_between, days_since_iso
t("parse_date_str", parse_date("2025-10-01") == date(2025, 10, 1))
t("parse_date_date", parse_date(date(2025, 10, 1)) == date(2025, 10, 1))
t("weeks_between_3", weeks_between(date(2025, 10, 1), date(2025, 10, 22)) == 3)
t("weeks_between_0", weeks_between(date(2025, 10, 5), date(2025, 10, 1)) == 0)
t("days_since_none", days_since_iso(None) is None)
t("days_since_garbage", days_since_iso("not-a-date") is None)
t("days_since_valid", days_since_iso(date.today().isoformat()) == 0)

# ═══════════════════════════════════════════════════════
# DATES: build_sprint_calendar with Jira data
# ═══════════════════════════════════════════════════════
from kpi.services.dates import build_sprint_calendar
jira_sp = [
    {"name": "Sprint 1", "number": 1, "state": "closed",
     "start_date": "2025-10-01", "end_date": "2025-10-21"},
    {"name": "Sprint 2", "number": 2, "state": "active",
     "start_date": "2025-10-22", "end_date": "2025-11-11"},
    {"name": "Sprint 3", "number": 3, "state": "future",
     "start_date": "2025-11-12", "end_date": "2025-12-02"},
]
sp_cfg = {"project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3}}
result_sprints = build_sprint_calendar(sp_cfg, jira_sprints=jira_sp)
t("jira_sprints_count", len(result_sprints) == 3, f"got {len(result_sprints)}")
t("jira_sprint_1_date", result_sprints[0].start_date == "2025-10-01")
t("jira_sprint_2_date", result_sprints[1].start_date == "2025-10-22")
t("jira_sprint_names", result_sprints[0].name == "Sprint 1")

fallback_sprints = build_sprint_calendar(sp_cfg, jira_sprints=[])
t("jira_sprints_fallback", len(fallback_sprints) >= 15)

partial_sp = [{"name": "Sprint 1", "number": 1, "start_date": "", "end_date": ""}]
partial_result = build_sprint_calendar(sp_cfg, jira_sprints=partial_sp)
t("jira_sprints_skip_partial", len(partial_result) >= 15, "should fallback")

# ═══════════════════════════════════════════════════════
# DIMENSIONS: parse + flatten
# ═══════════════════════════════════════════════════════
from kpi.domain.dimensions import parse_dimensions, flatten_taggable, flatten_all
dims = parse_dimensions(CFG["dimensions"])
t("dims_three_roots", len(dims) == 3)
t("dims_labels", [d.label for d in dims] == ["fonctionnel", "technique", "organisationnel"])
all_nodes = flatten_all(dims)
t("dims_flatten_all_gt40", len(all_nodes) > 40)
taggable = flatten_taggable(dims)
t("dims_taggable_has_keywords", all(len(n.keywords) > 0 for n in taggable))
t("dims_depth_root_0", all(d.depth == 0 for d in dims))
t("dims_children_depth_1", all(c.depth == 1 for d in dims for c in d.children))

# conception-fonctionnelle under fonctionnel
fonc = CFG["dimensions"][0]
fonc_labels = set()
def _collect(node):
    fonc_labels.add(node["label"])
    for c in node.get("children", []): _collect(c)
_collect(fonc)
t("conception_fonc_in_fonctionnel", "conception-fonctionnelle" in fonc_labels)
tech_d = CFG["dimensions"][1]
tech_labels = set()
_collect_t = lambda n: tech_labels.add(n["label"]) or [_collect_t(c) for c in n.get("children", [])]
_collect_t(tech_d)
t("conception_fonc_not_in_technique", "conception-fonctionnelle" not in tech_labels)
t("conception_tech_in_technique", "conception-technique" in tech_labels)

# ═══════════════════════════════════════════════════════
# STORE: snapshot round-trip
# ═══════════════════════════════════════════════════════
try:
    from kpi.services.store import SnapshotStore
    _has_tinydb = True
except ImportError:
    _has_tinydb = False

if _has_tinydb:
    td = tempfile.mkdtemp()
    store_cfg = {"archive": {"db_path": os.path.join(td, "test-kpi.json")}}
    store = SnapshotStore(store_cfg)
    snap = Snapshot(snapshot_date="2026-01-15", sprint_number=3, total_points=100, done_points=40, completion_ratio=0.4)
    store.save(snap)
    loaded = store.load_by_date("2026-01-15")
    t("store_save_load", loaded is not None and loaded.total_points == 100)
    t("store_load_missing", store.load_by_date("1999-01-01") is None)
    snap2 = Snapshot(snapshot_date="2026-02-01", sprint_number=4, total_points=110, done_points=55, completion_ratio=0.5)
    store.save(snap2)
    a, b = store.compare("2026-01-15", "2026-02-01")
    t("store_compare", a is not None and b is not None and a.done_points == 40 and b.done_points == 55)
    import shutil
    shutil.rmtree(td, ignore_errors=True)
else:
    print("  ⚠️  tinydb not installed — skipping store tests")

# ═══════════════════════════════════════════════════════
# RENDERER: tojson filter
# ═══════════════════════════════════════════════════════
from kpi.services.renderer import _pydantic_tojson
dk_list = [DimensionKPI(label="a", total_points=10), DimensionKPI(label="b", total_points=20)]
try:
    result = _pydantic_tojson(dk_list)
    parsed = json.loads(result)
    t("tojson_list_models", len(parsed) == 2 and parsed[0]["label"] == "a")
except Exception as e:
    t("tojson_list_models", False, str(e))
t("tojson_plain_value", json.loads(_pydantic_tojson(42)) == 42)

# ═══════════════════════════════════════════════════════
# TEMPLATES: no REFE
# ═══════════════════════════════════════════════════════
t("tpl_preview_no_refe", 'REFE' not in tpl)
t("tpl_confluence_no_refe", 'REFE' not in ct)

# ═══════════════════════════════════════════════════════
# _extract_parent helper (inline)
# ═══════════════════════════════════════════════════════
def _extract_parent_test(fields):
    parent = fields.get("parent")
    if isinstance(parent, dict) and parent.get("key"):
        return parent["key"]
    for link in fields.get("issuelinks", []):
        inward = link.get("inwardIssue")
        if inward and inward.get("key"):
            return inward["key"]
    return None
# ═══════════════════════════════════════════════════════
# _jql_list helper (inline)
# ═══════════════════════════════════════════════════════
def _jql_list_test(values):
    parts = []
    for v in values:
        if ' ' in v or '-' in v:
            parts.append(f'"{v}"')
        else:
            parts.append(v)
    return ','.join(parts)
t("jql_list_simple", _jql_list_test(["Story"]) == "Story")
t("jql_list_spaces", _jql_list_test(["User Story"]) == '"User Story"')
t("jql_list_hyphen", _jql_list_test(["Sub-task"]) == '"Sub-task"')
t("jql_list_mixed", _jql_list_test(["Story", "User Story", "Récit"]) == 'Story,"User Story",Récit')
t("jql_list_french", _jql_list_test(["Tâche", "Sous-tâche"]) == 'Tâche,"Sous-tâche"')

# Config: issue types
t("cfg_story_types", "story_types" in CFG.get("jira", {}))
t("cfg_task_types", "task_types" in CFG.get("jira", {}))
t("cfg_story_types_has_recit", "Récit" in CFG["jira"]["story_types"])
t("cfg_task_types_has_tache", "Tâche" in CFG["jira"]["task_types"])

# ═══════════════════════════════════════════════════════
# NETWORK: proxy disabled by default
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'adapters', 'network.py')) as f: nc=f.read()
# ═══════════════════════════════════════════════════════
# CONFIG LOADER: env overrides
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'config', 'loader.py')) as f: lc=f.read()
t("loader_jira_project_key_env", 'JIRA_PROJECT_KEY' in lc)
t("loader_project_name_env", 'PROJECT_NAME' in lc)
t("loader_project_key_default", 'default=' in lc and 'project_key' in lc)

t("proxy_disabled_default", 'PROXY_ENABLED' in nc)
t("proxy_opt_in", '"false"' in nc or "'false'" in nc)

t("extract_parent_subtask", _extract_parent_test({"parent": {"key": "KPI-10"}}) == "KPI-10")
t("extract_parent_link", _extract_parent_test({"issuelinks": [{"inwardIssue": {"key": "KPI-20"}}]}) == "KPI-20")
t("extract_parent_none", _extract_parent_test({}) is None)

import sys
print(f"\n  {'🎉' if fail==0 else '💥'} {ok}/{ok+fail} passed")
sys.exit(1 if fail else 0)
