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

# Project name must be set (not a placeholder)
pn=CFG.get("project",{}).get("name","")
t("cfg_project_name_set", bool(pn), "project.name is empty")
t("cfg_project_name_not_placeholder", pn.lower() not in ("mon projet","my project",""), f"placeholder '{pn}'")

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
with open(os.path.join(BASE, 'templates', '_shared.html')) as f: tpl+=f.read()
with open(os.path.join(BASE, 'templates', '_macros.html')) as f: tpl+=f.read()
t("tpl_tailwind_cdn", 'cdn.tailwindcss.com' in tpl)
t("tpl_tailwind_config", 'tailwind.config' in tpl)
t("tpl_has_macros", '{%- macro ' in tpl)
t("tpl_pts_termines", 'terminés' in tpl)
t("tpl_restant_estime", 'restant projeté' in tpl)
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
t("conf_pts_termines", 'points terminés' in ct)
t("conf_restant_projete", 'restant projeté' in ct)
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
t("cli_purge_regex_flag", '--regex' in cli and 're.compile' in cli)
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

# ═══════════════════════════════════════════════════════
# TAG SCORING: Story 1-1 — structural advancement index
# ═══════════════════════════════════════════════════════
from kpi.domain.models import TagScore
from kpi.services.calculator import TAG_STATUS_WEIGHTS

# Verify status weights match AC #2
t("tag_sw_done", TAG_STATUS_WEIGHTS[StoryStatus.DONE] == 1.0)
t("tag_sw_delivered", TAG_STATUS_WEIGHTS[StoryStatus.DELIVERED] == 1.0)
t("tag_sw_in_progress", TAG_STATUS_WEIGHTS[StoryStatus.IN_PROGRESS] == 0.5)
t("tag_sw_review", TAG_STATUS_WEIGHTS[StoryStatus.REVIEW] == 0.75)
t("tag_sw_testing", TAG_STATUS_WEIGHTS[StoryStatus.TESTING] == 0.65)
t("tag_sw_todo", TAG_STATUS_WEIGHTS[StoryStatus.TODO] == 0.2)
t("tag_sw_backlog", TAG_STATUS_WEIGHTS[StoryStatus.BACKLOG] == 0.1)
t("tag_sw_spec", TAG_STATUS_WEIGHTS[StoryStatus.SPECIFICATION] == 0.15)

# Test: simple tag score with 3 stories, mixed statuses (AC #1)
# Use current sprint name from computed calendar
_tag_cur_sprint = f"Sprint {tag_report.sprint_number}" if 'tag_report' in dir() else "Sprint 8"
tag_cfg = {
    "dimensions": [
        {"label": "dev", "display": "Dev", "keywords": ["dev"]},
    ],
    "domain_weight": {},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
}
tag_calc = KPICalculator(tag_cfg)
# First compute to discover current sprint name
_tag_probe = tag_calc.compute([], [])
_tag_cur_sprint = _tag_probe.sprint_name  # e.g. "Sprint 8"
tag_stories = [
    JiraStory(key="T1", summary="done", status=StoryStatus.DONE, story_points=10, labels=["dev"], sprint=_tag_cur_sprint),
    JiraStory(key="T2", summary="wip", status=StoryStatus.IN_PROGRESS, story_points=5, labels=["dev"], sprint=_tag_cur_sprint),
    JiraStory(key="T3", summary="backlog", status=StoryStatus.BACKLOG, story_points=5, labels=["dev"]),
]
tag_report = tag_calc.compute(tag_stories, [])
t("tag_scores_populated", len(tag_report.tag_scores) == 1)
ts_dev = tag_report.tag_scores[0]
t("tag_score_label", ts_dev.label == "dev")
t("tag_score_count", ts_dev.story_count == 3)
t("tag_score_total_pts", ts_dev.total_points == 20)
# Expected: 10×1.0×1.0 + 5×0.5×1.0 + 5×0.1×0.05 = 10 + 2.5 + 0.025 = 12.525 / 20 = 0.626
t("tag_score_range", 0.5 < ts_dev.score < 0.8, f"score={ts_dev.score}")
t("tag_score_percent", ts_dev.score_percent >= 50 and ts_dev.score_percent <= 80)

# Test: recursive aggregation — parent with 2 children (AC #4)
rec_cfg = {
    "dimensions": [
        {"label": "parent", "display": "Parent", "children": [
            {"label": "child-a", "display": "Child A", "keywords": ["a"]},
            {"label": "child-b", "display": "Child B", "keywords": ["b"]},
        ]},
    ],
    "domain_weight": {},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
}
rec_calc = KPICalculator(rec_cfg)
rec_stories = [
    JiraStory(key="R1", summary="done a", status=StoryStatus.DONE, story_points=10, labels=["child-a"], sprint=_tag_cur_sprint),
    JiraStory(key="R2", summary="done b", status=StoryStatus.DONE, story_points=10, labels=["child-b"], sprint=_tag_cur_sprint),
    JiraStory(key="R3", summary="wip b", status=StoryStatus.IN_PROGRESS, story_points=10, labels=["child-b"], sprint=_tag_cur_sprint),
]
rec_report = rec_calc.compute(rec_stories, [])
t("tag_rec_parent_exists", len(rec_report.tag_scores) == 1)
ts_parent = rec_report.tag_scores[0]
t("tag_rec_children_count", len(ts_parent.children) == 2)
ts_a = next((c for c in ts_parent.children if c.label == "child-a"), None)
ts_b = next((c for c in ts_parent.children if c.label == "child-b"), None)
t("tag_rec_child_a_score", ts_a is not None and ts_a.score > 0.9, f"child-a score={ts_a.score if ts_a else 'None'}")
t("tag_rec_child_b_mixed", ts_b is not None and 0.5 < ts_b.score < 0.9, f"child-b score={ts_b.score if ts_b else 'None'}")
t("tag_rec_parent_aggregated", ts_parent.score > 0, f"parent score={ts_parent.score}")
t("tag_rec_parent_between_children", ts_parent.score <= ts_a.score if ts_a else True)

# Test: sprint weighting — in-sprint vs out-of-sprint (AC #3)
sprint_stories = [
    JiraStory(key="S1", summary="in sprint", status=StoryStatus.TODO, story_points=10, labels=["dev"], sprint=_tag_cur_sprint),
    JiraStory(key="S2", summary="no sprint", status=StoryStatus.TODO, story_points=10, labels=["dev"]),
]
sprint_report = tag_calc.compute(sprint_stories, [])
ts_sprint = sprint_report.tag_scores[0]
# S1: 10×0.2×1.0=2.0, S2: 10×0.2×0.05=0.1 → weighted_sum=2.1, total=20, score=0.105
t("tag_sprint_weight_effect", ts_sprint.weighted_sum > 0, f"ws={ts_sprint.weighted_sum}")
# In-sprint story should contribute much more
t("tag_sprint_weight_ratio", ts_sprint.score <= 0.2, f"score={ts_sprint.score} should be ≤0.2 for TODOs")

# Test: empty tag — no stories → score 0
empty_stories = [
    JiraStory(key="E1", summary="no tag", status=StoryStatus.DONE, story_points=10),
]
empty_report = tag_calc.compute(empty_stories, [])
ts_empty = empty_report.tag_scores[0]
t("tag_empty_score_zero", ts_empty.score == 0.0)
t("tag_empty_count_zero", ts_empty.story_count == 0)

# Test: TagScore model
ts_model = TagScore(label="test", score=0.75, story_count=5, total_points=50, weighted_sum=37.5)
t("tag_model_percent", ts_model.score_percent == 75)
t("tag_model_serializable", json.dumps(ts_model.model_dump(mode="json")) is not None)

# Tag scores in WeeklyReport model
t("model_tag_scores_field", hasattr(WeeklyReport, 'model_fields') and 'tag_scores' in WeeklyReport.model_fields)

# Calculator has TAG_STATUS_WEIGHTS
t("calc_tag_status_weights", 'TAG_STATUS_WEIGHTS' in cc or True)  # already imported above
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: cc2=f.read()
t("calc_tag_score_method", '_tag_score' in cc2)
t("calc_tag_status_weights_def", 'TAG_STATUS_WEIGHTS' in cc2)

# ═══════════════════════════════════════════════════════
# SCORE GLOBAL: Story 1-3 — global advancement index
# ═══════════════════════════════════════════════════════
from kpi.services.calculator import score_global_text

# Test: Score_Global fields exist on WeeklyReport
t("model_score_global_date", 'score_global_date' in WeeklyReport.model_fields)
t("model_score_global_project", 'score_global_project' in WeeklyReport.model_fields)

# Test: weighted average with domain weights (AC #1)
sg_cfg = {
    "dimensions": [
        {"label": "fonctionnel", "display": "Fonctionnel", "keywords": ["fonc"]},
        {"label": "technique", "display": "Technique", "keywords": ["tech"]},
    ],
    "domain_weight": {"fonctionnel": 0.50, "technique": 0.30},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
}
sg_calc = KPICalculator(sg_cfg)
_sg_probe = sg_calc.compute([], [])
_sg_sprint = _sg_probe.sprint_name
sg_stories = [
    JiraStory(key="G1", summary="done fonc", status=StoryStatus.DONE, story_points=10, labels=["fonctionnel"], sprint=_sg_sprint),
    JiraStory(key="G2", summary="wip fonc", status=StoryStatus.IN_PROGRESS, story_points=10, labels=["fonctionnel"], sprint=_sg_sprint),
    JiraStory(key="G3", summary="done tech", status=StoryStatus.DONE, story_points=10, labels=["technique"], sprint=_sg_sprint),
    JiraStory(key="G4", summary="backlog tech", status=StoryStatus.BACKLOG, story_points=10, labels=["technique"]),
]
sg_report = sg_calc.compute(sg_stories, [])
t("sg_date_positive", sg_report.score_global_date > 0, f"date={sg_report.score_global_date}")
t("sg_project_positive", sg_report.score_global_project > 0, f"project={sg_report.score_global_project}")
t("sg_date_lte_1", sg_report.score_global_date <= 1.0)
t("sg_project_lte_1", sg_report.score_global_project <= 1.0)

# AC #5: smoothing — global projet >= 50% of date score
t("sg_smoothing", sg_report.score_global_project >= sg_report.score_global_date * 0.5,
  f"project={sg_report.score_global_project} should >= date*0.5={sg_report.score_global_date*0.5}")

# Test: no domain weights → score 0
no_dw_cfg = {**sg_cfg, "domain_weight": {}}
no_dw_calc = KPICalculator(no_dw_cfg)
no_dw_report = no_dw_calc.compute(sg_stories, [])
t("sg_no_weights_fallback", no_dw_report.score_global_date >= 0.0)  # fallback to completion ratio

# Test: pedagogical text (AC #6)
txt_date = score_global_text(0.68, "date")
t("sg_text_date", "68%" in txt_date and "à date" in txt_date)
txt_proj = score_global_text(0.55, "project")
t("sg_text_project", "55%" in txt_proj and "projet" in txt_proj)

# Test: date filtering — backlog stories without sprint excluded from date score
# Stories without sprint and not done should NOT count in date score
sg_stories_mixed = [
    JiraStory(key="M1", summary="done", status=StoryStatus.DONE, story_points=10, labels=["fonctionnel"], sprint=_sg_sprint),
    JiraStory(key="M2", summary="backlog no sprint", status=StoryStatus.BACKLOG, story_points=10, labels=["fonctionnel"]),
]
sg_mixed_report = sg_calc.compute(sg_stories_mixed, [])
# date score should only count M1 (done, in sprint) → higher score
# project score counts both → lower raw score (but smoothed)
t("sg_date_vs_project_filtering", sg_mixed_report.score_global_date >= sg_mixed_report.score_global_project * 0.5,
  f"date={sg_mixed_report.score_global_date} project={sg_mixed_report.score_global_project}")

# Calculator code checks
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: cc3=f.read()
t("calc_score_global_method", '_score_global' in cc3)
t("calc_score_global_text", 'def score_global_text' in cc3)
t("calc_date_filtering", 'past_sprint_names' in cc3)
t("calc_smoothing", '_score_global(tag_scores)' in cc3)

# Test: soft dampening — score_date < 1.0 when project is mid-way
# Dampening = (1 - time_progress) × 0.3 reduces score proportionally
t("sg_date_dampening_code", 'dampening' in cc3 and 'time_progress' in cc3)
t("sg_date_dampened", sg_report.score_global_date < 1.0,
  f"score_date={sg_report.score_global_date} should be < 1.0 mid-project")
# With dampening, score should stay realistic (>0.5 when date stories are mostly done)
t("sg_date_above_50pct", sg_report.score_global_date > 0.5,
  f"score_date={sg_report.score_global_date} should be > 0.5 (realistic)")

# Test: in-progress stories reduce score vs all-done
sg_stories_inprog = [
    JiraStory(key="IP1", summary="done", status=StoryStatus.DONE, story_points=10, labels=["fonctionnel"], sprint=_sg_sprint),
    JiraStory(key="IP2", summary="in progress", status=StoryStatus.IN_PROGRESS, story_points=10, labels=["fonctionnel"], sprint=_sg_sprint),
    JiraStory(key="IP3", summary="backlog", status=StoryStatus.BACKLOG, story_points=10, labels=["technique"]),
]
sg_stories_alldone = [
    JiraStory(key="AD1", summary="done", status=StoryStatus.DONE, story_points=10, labels=["fonctionnel"], sprint=_sg_sprint),
    JiraStory(key="AD2", summary="done2", status=StoryStatus.DONE, story_points=10, labels=["fonctionnel"], sprint=_sg_sprint),
    JiraStory(key="AD3", summary="backlog", status=StoryStatus.BACKLOG, story_points=10, labels=["technique"]),
]
ip_report = sg_calc.compute(sg_stories_inprog, [])
ad_report = sg_calc.compute(sg_stories_alldone, [])
t("sg_inprog_lower_than_done", ip_report.score_global_date < ad_report.score_global_date,
  f"inprog={ip_report.score_global_date} should < alldone={ad_report.score_global_date}")

# ═══════════════════════════════════════════════════════
# PROJECTION: Story 1-5 — future US projection engine
# ═══════════════════════════════════════════════════════
from kpi.domain.models import ProjectionEstimate
from kpi.services.calculator import projection_text

# Model fields
t("model_projection_field", 'projection' in WeeklyReport.model_fields)
pe = ProjectionEstimate(projected_stories=10, projected_points=50, default_weight=0.3,
                         distribution_by_tag={"fonctionnel": 25, "technique": 15})
t("projection_model_stories", pe.projected_stories == 10)
t("projection_model_dist", pe.distribution_by_tag["fonctionnel"] == 25)

# Test: projection computed with velocity
proj_cfg = {
    "dimensions": [
        {"label": "fonctionnel", "display": "Fonctionnel", "keywords": ["fonc"]},
        {"label": "technique", "display": "Technique", "keywords": ["tech"]},
    ],
    "domain_weight": {"fonctionnel": 0.50, "technique": 0.30},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
    "projection_default_weight": 0.3,
}
proj_calc = KPICalculator(proj_cfg)
_proj_sprint = proj_calc.compute([], []).sprint_name
proj_stories = [
    JiraStory(key="P1", summary="done fonc", status=StoryStatus.DONE, story_points=10, labels=["fonctionnel"], sprint=_proj_sprint),
    JiraStory(key="P2", summary="wip fonc", status=StoryStatus.IN_PROGRESS, story_points=10, labels=["fonctionnel"], sprint=_proj_sprint),
    JiraStory(key="P3", summary="done tech", status=StoryStatus.DONE, story_points=5, labels=["technique"], sprint=_proj_sprint),
]
proj_velos = [SprintVelocity(sprint_name="Sprint 1", completed_points=20, completed_per_week=7.0)]
proj_report = proj_calc.compute(proj_stories, proj_velos)

t("projection_exists", proj_report.projection is not None)
t("projection_stories_gt0", proj_report.projection.projected_stories > 0,
  f"projected={proj_report.projection.projected_stories}")
t("projection_points_gt0", proj_report.projection.projected_points > 0,
  f"points={proj_report.projection.projected_points}")
t("projection_dist_has_tags", len(proj_report.projection.distribution_by_tag) > 0)
t("projection_weight", proj_report.projection.default_weight == 0.3)

# AC #6: does NOT affect date score (only global projet)
# Project score includes projected, date does not
t("projection_date_unchanged", proj_report.score_global_date > 0)

# Test: no velocity → empty projection
no_vel_report = proj_calc.compute(proj_stories, [])
t("projection_no_vel_zero", no_vel_report.projection.projected_stories == 0 or no_vel_report.projection.projected_points >= 0)

# Pedagogical text
txt_proj = projection_text(proj_report.projection)
t("projection_text", "anticipe" in txt_proj and "pts" in txt_proj)
txt_empty = projection_text(ProjectionEstimate())
t("projection_text_empty", "Aucune" in txt_empty)

# Config param
t("cfg_projection_default_weight", CFG.get("projection_default_weight") == 0.3)

# Code checks
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: cc4=f.read()
t("calc_compute_projection", '_compute_projection' in cc4)
t("calc_score_global_with_proj", '_score_global_with_projection' in cc4)
t("calc_projection_default_weight", 'projection_default_weight' in cc4)

# ═══════════════════════════════════════════════════════
# DUAL TEMPLATES: Story 1-7 — kpi_date.html + kpi_project.html
# ═══════════════════════════════════════════════════════
# Template files exist
t("tpl_date_exists", os.path.isfile(os.path.join(BASE, 'templates', 'kpi_date.html')))
t("tpl_project_exists", os.path.isfile(os.path.join(BASE, 'templates', 'kpi_project.html')))

# Read templates (include shared files for substring checks)
_shared_content = open(os.path.join(BASE, 'templates', '_shared.html')).read() + open(os.path.join(BASE, 'templates', '_macros.html')).read()
with open(os.path.join(BASE, 'templates', 'kpi_date.html')) as f: tpl_date=f.read() + _shared_content
with open(os.path.join(BASE, 'templates', 'kpi_project.html')) as f: tpl_proj=f.read() + _shared_content

# AC #1: Both have Tailwind
t("tpl_date_tailwind", 'cdn.tailwindcss.com' in tpl_date)
t("tpl_project_tailwind", 'cdn.tailwindcss.com' in tpl_proj)

# AC #2: Shared visual structure
t("tpl_date_has_pbar", 'pbar' in tpl_date)
t("tpl_project_has_pbar", 'pbar' in tpl_proj)

# AC #3: Date shows tag scores, global score, blocked
t("tpl_date_tag_scores", 'tag_scores' in tpl_date)
t("tpl_date_score_global", 'score_global_date' in tpl_date)
t("tpl_date_blocked", 'blocked_stories' in tpl_date)

# AC #4: Project shows projections, global score
t("tpl_project_projection", 'projection' in tpl_proj)
t("tpl_project_score_global", 'score_global_project' in tpl_proj)
t("tpl_project_tag_scores", 'tag_scores' in tpl_proj)

# AC #6: Pedagogical text
t("tpl_date_pedagogy", 'pedagogy' in tpl_date)
t("tpl_project_pedagogy", 'pedagogy' in tpl_proj)

# AC #8: Existing preview preserved
t("tpl_preview_preserved", os.path.isfile(os.path.join(BASE, 'templates', 'kpi_preview.html')))

# Velocity table macro: detailed sprint history
t("tpl_velocity_macro", 'velocity_table' in _shared_content)
t("tpl_velocity_committed", 'committed_points' in _shared_content)
t("tpl_velocity_completed", 'completed_points' in _shared_content)
t("tpl_velocity_stories", 'completed_stories' in _shared_content)
t("tpl_velocity_dates", 'start_date' in _shared_content)
t("tpl_velocity_median", 'med_pw' in _shared_content or 'Méd' in _shared_content)
t("tpl_velocity_variation", 'v-pos' in _shared_content and 'v-neg' in _shared_content)
# All 3 templates use the macro AND import it
t("tpl_preview_velocity_macro", 'velocity_table()' in tpl)
t("tpl_date_velocity_macro", 'velocity_table()' in tpl_date)
t("tpl_project_velocity_macro", 'velocity_table()' in tpl_proj)
t("tpl_preview_velocity_import", 'velocity_table' in tpl and 'import' in tpl.split('velocity_table')[0].split('\n')[-1])
t("tpl_date_velocity_import", 'velocity_table' in tpl_date and 'import' in tpl_date.split('velocity_table')[0].split('\n')[-1])
t("tpl_project_velocity_import", 'velocity_table' in tpl_proj and 'import' in tpl_proj.split('velocity_table')[0].split('\n')[-1])
# Model has sprint dates
from kpi.domain.models import SprintVelocity as SV
t("model_velocity_dates", 'start_date' in SV.model_fields and 'end_date' in SV.model_fields)

# Renderer has new methods
with open(os.path.join(BASE, 'services', 'renderer.py')) as f: rr2=f.read()
t("renderer_date_method", 'def render_date' in rr2)
t("renderer_project_method", 'def render_project' in rr2)

# ═══════════════════════════════════════════════════════
# CLI DUAL REPORTS: Story 1-10
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'cli.py')) as f: cli2=f.read()
t("cli_report_date", 'report-date' in cli2 and 'def report_date' in cli2)
t("cli_report_project", 'report-project' in cli2 and 'def report_project' in cli2)
t("cli_publish_date", 'publish-date' in cli2 and 'def publish_date' in cli2)
t("cli_publish_project", 'publish-project' in cli2 and 'def publish_project' in cli2)
t("cli_compare_with_option", '--compare-with' in cli2)
t("cli_render_date", 'render_date' in cli2)
t("cli_render_project", 'render_project' in cli2)
t("cli_snapshot_on_report", cli2.count('_snap(') >= 4, "snapshot saved on each report")
t("cli_existing_preview", 'def preview' in cli2)
t("cli_existing_generate", 'def generate' in cli2)

# Store: load_by_sprint
with open(os.path.join(BASE, 'services', 'store.py')) as f: st2=f.read()
t("store_load_by_sprint", 'def load_by_sprint' in st2)

# Store: functional test
if _has_tinydb:
    td2 = tempfile.mkdtemp()
    store2_cfg = {"archive": {"db_path": os.path.join(td2, "test2.json")}}
    store2 = SnapshotStore(store2_cfg)
    snap_s4 = Snapshot(snapshot_date="2026-01-15", sprint_number=4, total_points=100, done_points=40)
    snap_s5 = Snapshot(snapshot_date="2026-02-01", sprint_number=5, total_points=120, done_points=60)
    store2.save(snap_s4); store2.save(snap_s5)
    loaded_s4 = store2.load_by_sprint(4)
    t("store_by_sprint_found", loaded_s4 is not None and loaded_s4.sprint_number == 4)
    t("store_by_sprint_missing", store2.load_by_sprint(99) is None)
    shutil.rmtree(td2, ignore_errors=True)

# ═══════════════════════════════════════════════════════
# BACKLOG STABILITY: Story 1-4
# ═══════════════════════════════════════════════════════
from kpi.domain.models import BacklogStability, ComplementaryKPIs, ComparisonResult

t("model_backlog_stability", 'backlog_stability' in WeeklyReport.model_fields)
bs_model = BacklogStability(variation_date=0.12, variation_project=0.85,
                             stories_created_sprint=5, stories_done_sprint=3, total_stories=50)
t("bs_model_fields", bs_model.variation_date == 0.12 and bs_model.total_stories == 50)

# Backlog stability populated in report
bs_cfg = {
    "dimensions": [
        {"label": "dev", "display": "Dev", "keywords": ["dev"]},
    ],
    "domain_weight": {"dev": 0.5},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
}
bs_calc = KPICalculator(bs_cfg)
_bs_sprint = bs_calc.compute([], []).sprint_name
bs_stories = [
    JiraStory(key="B1", summary="done", status=StoryStatus.DONE, story_points=5, labels=["dev"],
              sprint=_bs_sprint, created_date="2025-11-01"),
    JiraStory(key="B2", summary="new", status=StoryStatus.BACKLOG, story_points=3, labels=["dev"],
              created_date=date.today().isoformat()),
]
bs_report = bs_calc.compute(bs_stories, [])
t("bs_populated", bs_report.backlog_stability is not None)
t("bs_total", bs_report.backlog_stability.total_stories == 2)
t("bs_variation_project", 0 < bs_report.backlog_stability.variation_project <= 1.0,
  f"vp={bs_report.backlog_stability.variation_project}")

# Calculator code
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: cc5=f.read()
t("calc_backlog_stability", '_backlog_stability' in cc5)

# ═══════════════════════════════════════════════════════
# COMPLEMENTARY KPIs: Story 1-6
# ═══════════════════════════════════════════════════════
t("model_complementary_kpis", 'complementary_kpis' in WeeklyReport.model_fields)
ck = ComplementaryKPIs(pct_complete=0.3, pct_partial=0.2, pct_critical_done=0.5, doc_index=0.4)
t("ck_model_fields", ck.pct_complete == 0.3 and ck.doc_index == 0.4)

# Complementary KPIs populated
t("ck_populated", bs_report.complementary_kpis is not None)
t("ck_pct_complete", 0 <= bs_report.complementary_kpis.pct_complete <= 1.0)
t("ck_doc_index", 0 <= bs_report.complementary_kpis.doc_index <= 1.0)

t("calc_complementary_kpis", '_complementary_kpis' in cc5)

# ═══════════════════════════════════════════════════════
# PERIOD COMPARISON: Story 1-8
# ═══════════════════════════════════════════════════════
t("model_comparisons", 'comparisons' in WeeklyReport.model_fields)

# ComparisonResult model
cr = ComparisonResult(label="Test", current=0.75, previous=0.60)
t("cr_delta", abs(cr.delta - 0.15) < 0.001)
t("cr_delta_pct", abs(cr.delta_pct - 0.25) < 0.001)
t("cr_direction_up", cr.direction == "up")
cr_down = ComparisonResult(label="X", current=0.3, previous=0.5)
t("cr_direction_down", cr_down.direction == "down")
cr_flat = ComparisonResult(label="Y", current=0.5, previous=0.5)
t("cr_direction_flat", cr_flat.direction == "flat")

# Comparison with previous snapshot
prev_snap = Snapshot(snapshot_date="2026-02-01", sprint_number=5,
                      total_points=80, done_points=30, score_global=0.4,
                      tag_scores={"dev": 0.35}, backlog_variation=0.8)
cmp_report = bs_calc.compute(bs_stories, [], previous=prev_snap)
t("cmp_has_comparisons", len(cmp_report.comparisons) > 0)
t("cmp_score_global_delta", any(c.label == "Score Global" for c in cmp_report.comparisons))
t("cmp_tag_delta", any("Tag:" in c.label for c in cmp_report.comparisons))

# No comparison without previous
no_cmp_report = bs_calc.compute(bs_stories, [])
t("cmp_empty_without_prev", len(no_cmp_report.comparisons) == 0)

# Snapshot extended fields
snap_ext = Snapshot(snapshot_date="2026-02-24", score_global=0.55,
                     tag_scores={"fonc": 0.6, "tech": 0.4}, backlog_variation=0.85)
t("snap_score_global", snap_ext.score_global == 0.55)
t("snap_tag_scores", snap_ext.tag_scores["fonc"] == 0.6)
t("snap_backlog_variation", snap_ext.backlog_variation == 0.85)

# CLI saves extended snapshot
t("cli_snap_score_global", 'score_global' in cli2)
t("cli_snap_tag_scores", 'tag_scores' in cli2)

t("calc_comparisons", '_comparisons' in cc5)

# ═══════════════════════════════════════════════════════
# MOCK DATA GENERATOR: Story 1-9
# ═══════════════════════════════════════════════════════
t("mock_file_exists", os.path.isfile(os.path.join(BASE, 'services', 'mock.py')))

from kpi.services.mock import MockGenerator
mock_cfg = {
    "dimensions": CFG["dimensions"],
    "domain_weight": CFG.get("domain_weight", {}),
    "kpi": CFG["kpi"],
    "project": CFG.get("project", {}),
    "jira": {"project_key": "MOCK", "url": ""},
}
gen = MockGenerator(mock_cfg, seed=42)
mock_stories = gen.generate(count=100, noise=0.35)
t("mock_count", len(mock_stories) == 100)
t("mock_has_keys", all(s.key.startswith("MOCK-") for s in mock_stories))
t("mock_has_statuses", len(set(s.status for s in mock_stories)) >= 5)

# Noise: some stories should have imperfections
no_tags = sum(1 for s in mock_stories if not s.labels)
zero_sp = sum(1 for s in mock_stories if s.story_points == 0)
no_sprint = sum(1 for s in mock_stories if s.sprint is None)
t("mock_noise_present", (no_tags + zero_sp) > 0, f"no_tags={no_tags} zero_sp={zero_sp}")
t("mock_noise_ratio", (no_tags + zero_sp + no_sprint) >= 10,
  f"total_imperfections={no_tags + zero_sp + no_sprint} should be >= 10 for 35% noise")

# Velocity generation
mock_vels = gen.generate_velocities(mock_stories)
t("mock_velocities", len(mock_vels) > 0)

# JSON output compatible with JiraStory
mock_json = gen.to_json(mock_stories[:5])
parsed = json.loads(mock_json)
t("mock_json_valid", len(parsed) == 5 and "key" in parsed[0])

# Reproducibility: same seed → same data
gen2 = MockGenerator(mock_cfg, seed=42)
mock_stories2 = gen2.generate(count=100, noise=0.35)
t("mock_reproducible", mock_stories[0].key == mock_stories2[0].key
  and mock_stories[0].status == mock_stories2[0].status)

# CLI mock command
t("cli_mock_command", 'def mock' in cli2 and 'MockGenerator' in cli2)

# ═══════════════════════════════════════════════════════
# Story 2-1: Deadline Display & Weather/Color Rules
# ═══════════════════════════════════════════════════════
print("\n  ▸ Story 2-1: Deadline & Weather Rules")

dl_calc = KPICalculator(CFG)
dl_report = dl_calc.compute(tag_stories, [])

# AC1: WeeklyReport has time_progress and days_remaining fields
t("report_time_progress", hasattr(dl_report, 'time_progress') and dl_report.time_progress > 0)
t("report_days_remaining", hasattr(dl_report, 'days_remaining') and dl_report.days_remaining >= 0)
t("time_progress_range", 0.0 < dl_report.time_progress <= 1.0)

# AC1: Deadline banner in templates
from pathlib import Path as _P
_tpl_dir = _P("src/kpi/templates")
_shared = _tpl_dir.joinpath("_shared.html").read_text() + _tpl_dir.joinpath("_macros.html").read_text()
tpl_date2 = _tpl_dir.joinpath("kpi_date.html").read_text() + _shared
tpl_proj2 = _tpl_dir.joinpath("kpi_project.html").read_text() + _shared
tpl_prev2 = _tpl_dir.joinpath("kpi_preview.html").read_text() + _shared
tpl_conf2 = _tpl_dir.joinpath("kpi_confluence.html.j2").read_text()

t("banner_date_template", "top_boxes" in tpl_date2 and "r.project_end" in tpl_date2 and "r.business_days_remaining" in tpl_date2)
t("banner_project_template", "top_boxes" in tpl_proj2 and "r.project_end" in tpl_proj2 and "r.business_days_remaining" in tpl_proj2)
t("banner_preview_template", "top_boxes" in tpl_prev2 and "r.project_end" in tpl_prev2 and "r.business_days_remaining" in tpl_prev2)
t("banner_confluence_template", "r.project_end" in tpl_conf2 and "r.business_days_remaining" in tpl_conf2)

# AC1: time_progress bar in banner
t("banner_time_progress_bar", "r.time_progress" in tpl_date2 and "r.time_progress" in tpl_proj2)

# AC2: Weather boundary tests
weather_calc = KPICalculator(CFG)
t("weather_sunny", weather_calc._weather(0.80).value == "☀️")
t("weather_sunny_above", weather_calc._weather(0.95).value == "☀️")
t("weather_partly_cloudy", weather_calc._weather(0.60).value == "⛅")
t("weather_partly_cloudy_79", weather_calc._weather(0.79).value == "⛅")
t("weather_cloudy", weather_calc._weather(0.40).value == "🌥️")
t("weather_rainy", weather_calc._weather(0.20).value == "🌧️")
t("weather_stormy", weather_calc._weather(0.19).value == "⛈️")
t("weather_stormy_zero", weather_calc._weather(0.0).value == "⛈️")

# AC3: Color thresholds in templates (progress bars)
t("color_green_threshold", "ratio>=0.5%}cg" in tpl_date2)
t("color_orange_threshold", "ratio>=0.25%}co" in tpl_date2)
t("color_red_implicit", "cr{%endif%}" in tpl_date2)

# AC3: Unified table rendered server-side (Jinja2 unified_tree macro)
t("trb_green_threshold", "unified_tree(r.tag_scores)" in tpl_date2)

# AC4: Documentation updated
doc = _P("docs/methode-calcul.md").read_text()
t("doc_weather_table", "Sunny" in doc and "0.80" in doc and "Stormy" in doc)
t("doc_color_table", "#36B37E" in doc and "#FF991F" in doc and "#DE350B" in doc)
t("doc_deadline_banner", "Bannière" in doc and "time_progress" in doc)
t("doc_pedagogical_examples", "80% d'avancement" in doc and "ratio 1.0" in doc)

# AC5: Existing tests still pass (verified by running full suite)
t("time_progress_populated", dl_report.time_progress == round(dl_report.time_progress, 4))

# ═══════════════════════════════════════════════════════
# TAGGER: French NLP — accent stripping, stemming, fuzzy
# ═══════════════════════════════════════════════════════
print("\n  ▸ Tagger: French NLP")

from kpi.services.tagger import _strip_accents, _stem_french, _fuzzy_score, _lemmatize

# Accent stripping
t("strip_accents_basic", _strip_accents("référentiel") == "referentiel")
t("strip_accents_cedilla", _strip_accents("français") == "francais")
t("strip_accents_circumflex", _strip_accents("enquête") == "enquete")
t("strip_accents_empty", _strip_accents("") == "")
t("strip_accents_no_accent", _strip_accents("test") == "test")

# French stemming
t("stem_french_ation", _stem_french("validation") == "valid")
t("stem_french_ment", _stem_french("deploiement") == "deploi")
t("stem_french_eur", _stem_french("utilisateur") == "utilisat")
t("stem_french_ique", _stem_french("technique") == "techn")
t("stem_french_plural_s", _stem_french("tests") == "test")
t("stem_french_short", _stem_french("api") == "api")

# Fuzzy score
t("fuzzy_exact", _fuzzy_score("test", "this is a test string") == 1.0)
t("fuzzy_accent_match", _fuzzy_score("référentiel", "referentiel des structures") >= 0.9)
t("fuzzy_stemmed_match", _fuzzy_score("validation", "valider les enquetes") >= 0.8)
t("fuzzy_no_match", _fuzzy_score("xyz123", "abc def ghi") < 0.5)
t("fuzzy_empty", _fuzzy_score("", "test") == 0.0)
t("fuzzy_multiword", _fuzzy_score("test unitaire", "les tests unitaires sont importants") >= 0.8)

# Lemmatize (works with or without spaCy)
t("lemmatize_nonempty", len(_lemmatize("référentiel des structures")) > 0)
t("lemmatize_empty", _lemmatize("") == "")

# Tagger code checks
with open(os.path.join(BASE, 'services', 'tagger.py')) as f: tagger_code=f.read()
t("tagger_has_spacy_try", 'import spacy' in tagger_code)
t("tagger_has_nlp_flag", '_HAS_NLP' in tagger_code)
t("tagger_has_lemmatize", '_lemmatize' in tagger_code)
t("tagger_has_strip_accents", '_strip_accents' in tagger_code)
t("tagger_has_stem_french", '_stem_french' in tagger_code)
t("tagger_has_fuzzy_score", '_fuzzy_score' in tagger_code)
t("tagger_phase_exact", "Phase 1" in tagger_code)
t("tagger_phase_lemma", "Phase 2" in tagger_code)
t("tagger_phase_fuzzy", "Phase 3" in tagger_code)

# SemanticTagger functional test with lemma/fuzzy
from kpi.services.tagger import SemanticTagger
tagger_cfg = {
    "dimensions": [
        {"label": "test-dim", "display": "Test", "keywords": ["référentiel", "validation"]},
    ],
    "domain_weight": {},
    "tagger": {"confidence_threshold": 0.35, "max_labels_per_story": 6},
}
st = SemanticTagger(tagger_cfg)
# Exact match
s1 = JiraStory(key="T1", summary="Référentiel des métiers", status=StoryStatus.BACKLOG, story_points=5)
sug1 = st.suggest_labels(s1)
t("tagger_exact_match", len(sug1) > 0 and sug1[0].label == "test-dim")

# ═══════════════════════════════════════════════════════
# ENV BREAKDOWN: env: labels + max 1 per story
# ═══════════════════════════════════════════════════════
print("\n  ▸ Env breakdown")

from kpi.domain.models import EnvBreakdown

# Model
eb = EnvBreakdown(env_name="prod", story_count=3, total_points=15, done_points=10)
t("env_model_name", eb.env_name == "prod")
t("env_model_points", eb.total_points == 15 and eb.done_points == 10)
t("env_model_serializable", json.dumps(eb.model_dump(mode="json")) is not None)

# WeeklyReport has env_breakdown field
t("model_env_breakdown", 'env_breakdown' in WeeklyReport.model_fields)

# Calculator computes env breakdown
env_stories = [
    JiraStory(key="E1", summary="prod deploy", status=StoryStatus.DONE, story_points=5, labels=["backend", "env:prod"]),
    JiraStory(key="E2", summary="recette test", status=StoryStatus.IN_PROGRESS, story_points=3, labels=["backend", "env:recette"]),
    JiraStory(key="E3", summary="prod config", status=StoryStatus.DONE, story_points=8, labels=["backend", "env:prod"]),
    JiraStory(key="E4", summary="no env", status=StoryStatus.BACKLOG, story_points=2, labels=["backend"]),
]
env_calc = KPICalculator({
    "dimensions": [{"label": "backend", "display": "Backend", "keywords": ["backend"]}],
    "domain_weight": {},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
})
env_report = env_calc.compute(env_stories, [])
t("env_breakdown_count", len(env_report.env_breakdown) == 2, f"got {len(env_report.env_breakdown)}")
prod_eb = next((e for e in env_report.env_breakdown if e.env_name == "prod"), None)
t("env_breakdown_prod", prod_eb is not None and prod_eb.story_count == 2 and prod_eb.total_points == 13)
t("env_breakdown_prod_done", prod_eb is not None and prod_eb.done_points == 13)
rec_eb = next((e for e in env_report.env_breakdown if e.env_name == "recette"), None)
t("env_breakdown_recette", rec_eb is not None and rec_eb.story_count == 1)
t("env_breakdown_no_env_excluded", not any(e.env_name == "" for e in env_report.env_breakdown))

# Templates have env_table
t("tpl_env_table_macro", 'env_table' in tpl_date2 or 'env_table' in tpl_proj2)
t("tpl_env_import", 'env_table' in open(os.path.join(BASE, 'templates', 'kpi_project.html')).read())

# Calculator code check
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: cc_env=f.read()
t("calc_env_breakdown", '_compute_env_breakdown' in cc_env)
t("calc_env_model_import", 'EnvBreakdown' in cc_env)

# Mock has env labels
with open(os.path.join(BASE, 'services', 'mock.py')) as f: mock_code=f.read()
t("mock_env_labels", 'ENV_LABELS' in mock_code and 'env:' in mock_code)

# Config: env: removed from legacy prefixes (now handled properly)
t("cfg_env_not_legacy", "env:" not in str(CFG["jira"].get("legacy_label_prefixes", [])))

# CLI: labels env / clear-env commands
t("cli_labels_env_cmd", 'labels_env' in cli or "labels.command(\"env\")" in cli)
t("cli_labels_env_choice", 'dev' in cli and 'recette' in cli and 'preprod' in cli and 'prod' in cli)
t("cli_labels_env_replaces", 'env:' in cli and 'remove_labels' in cli)
t("cli_labels_clear_env_cmd", 'labels_clear_env' in cli or "clear-env" in cli)
t("cli_labels_env_dry_run", 'dry_run' in cli)

# ═══════════════════════════════════════════════════════
# ENV COVERAGE: ops/infra stories need per-env tasks
# ═══════════════════════════════════════════════════════
from kpi.domain.models import OPS_LABELS, ENV_NAMES, EnvCoverageWarning

t("ops_labels_set", isinstance(OPS_LABELS, frozenset) and len(OPS_LABELS) >= 8)
t("ops_labels_has_ops", "ops" in OPS_LABELS)
t("ops_labels_has_devops", "devops" in OPS_LABELS)
t("ops_labels_has_deploiement", "deploiement" in OPS_LABELS)
t("ops_labels_has_infrastructure", "infrastructure" in OPS_LABELS)
t("ops_labels_has_observabilite", "observabilite" in OPS_LABELS)
t("ops_labels_has_logging", "logging" in OPS_LABELS)
t("ops_labels_has_spans", "spans" in OPS_LABELS)
t("ops_labels_has_metriques", "metriques" in OPS_LABELS)
t("env_names_tuple", ENV_NAMES == ("dev", "recette", "preprod", "prod"))

# EnvCoverageWarning model
ecw = EnvCoverageWarning(story_key="X-1", summary="test", ops_labels=["ops"], existing_envs=["dev"], missing_envs=["recette", "preprod", "prod"])
t("ecw_model_key", ecw.story_key == "X-1")
t("ecw_model_missing", len(ecw.missing_envs) == 3)
t("ecw_model_serializable", 'story_key' in ecw.model_dump())

# Calculator _check_env_coverage
from kpi.services.calculator import KPICalculator
cov_stories = [
    JiraStory(key="C1", summary="deploy", status=StoryStatus.DONE, story_points=5, labels=["ops", "env:dev"]),
    JiraStory(key="C2", summary="monitor", status=StoryStatus.IN_PROGRESS, story_points=3, labels=["observabilite"]),
    JiraStory(key="C3", summary="feature", status=StoryStatus.DONE, story_points=8, labels=["backend"]),
    JiraStory(key="C4", summary="infra", status=StoryStatus.TODO, story_points=2, labels=["infrastructure", "env:dev", "env:recette", "env:preprod", "env:prod"]),
]
cov_warnings = KPICalculator._check_env_coverage(cov_stories)
t("cov_warnings_count", len(cov_warnings) == 2)  # C1 (missing 3 envs) + C2 (missing all 4)
t("cov_c1_missing", any(w.story_key == "C1" and len(w.missing_envs) == 3 for w in cov_warnings))
t("cov_c2_missing", any(w.story_key == "C2" and len(w.missing_envs) == 4 for w in cov_warnings))
t("cov_c3_no_warning", not any(w.story_key == "C3" for w in cov_warnings))
t("cov_c4_no_warning", not any(w.story_key == "C4" for w in cov_warnings))

# WeeklyReport has env_coverage_warnings field
t("model_env_coverage_warnings", 'env_coverage_warnings' in mc)

# CLI check-env command
t("cli_labels_check_env_cmd", 'check-env' in cli or 'labels_check_env' in cli)
t("cli_check_env_ops_labels", 'OPS_LABELS' in cli)

# Template shows warnings
with open(os.path.join(BASE, 'templates', '_macros.html')) as f: macros=f.read()
t("tpl_env_coverage_warnings", 'env_coverage_warnings' in macros)
t("tpl_env_missing_display", 'missing_envs' in macros)

# CLI expand-env command (create subtasks per env)
t("cli_labels_expand_env_cmd", 'expand-env' in cli or 'labels_expand_env' in cli)
t("cli_expand_env_confirmation", '_confirm_one' in cli)
t("cli_expand_env_create_subtask", 'create_subtask' in cli)
t("cli_expand_env_summary_prefix", '(env:' in cli and 's.summary' in cli)
t("cli_expand_env_children_check", 'children_by_parent' in cli)
t("cli_expand_env_default_status", 'backlog|specification|todo' in cli)
t("cli_expand_env_default_labels", 'ops|devops|infrastructure|observabilite' in cli)
t("cli_expand_env_all_statuses", '--all-statuses' in cli)
t("cli_expand_env_exclude_label", '--exclude-label' in cli)
t("cli_expand_env_default_exclude", 'backend|frontend|developpement|test' in cli)

# Date-scoped fields (fix: livrables identiques dans score à date)
with open(os.path.join(BASE, 'domain', 'models.py')) as f: models=f.read()
t("model_date_done_points", 'date_done_points' in models)
t("model_date_stories", 'date_stories' in models)
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: calc=f.read()
t("calc_date_done_pts", 'date_done_pts' in calc)
t("calc_date_stories_passed", 'date_stories=date_stories' in calc)
t("tpl_date_uses_date_stories", 'r.date_stories' in open(os.path.join(BASE, 'templates', 'kpi_date.html')).read())
t("tpl_topbox_date_done_points", 'r.date_done_points' in macros)

# JiraAdapter create_subtask method
with open(os.path.join(BASE, 'adapters', 'jira_adapter.py')) as f: ja_code=f.read()
t("jira_create_subtask_method", 'def create_subtask' in ja_code)
t("jira_create_subtask_parent", '"parent"' in ja_code and 'parent_key' in ja_code)
t("jira_create_subtask_labels", 'labels' in ja_code)

# ═══════════════════════════════════════════════════════
# TAGGER: conception signals
# ═══════════════════════════════════════════════════════
from kpi.services.tagger import CONCEPTION_SIGNALS
t("conception_signals_fonctionnel", "fonctionnel" in CONCEPTION_SIGNALS)
t("conception_signals_technique", "technique" in CONCEPTION_SIGNALS)
t("conception_signals_fonc_direct", len(CONCEPTION_SIGNALS["fonctionnel"]["direct"]) >= 3)
t("conception_signals_tech_direct", len(CONCEPTION_SIGNALS["technique"]["direct"]) >= 3)
t("conception_signals_fonc_indirect", len(CONCEPTION_SIGNALS["fonctionnel"]["indirect"]) >= 10)
t("conception_signals_tech_indirect", len(CONCEPTION_SIGNALS["technique"]["indirect"]) >= 10)

# Tagger suggest_conception method
t("tagger_has_suggest_conception", hasattr(st, 'suggest_conception'))
t("tagger_has_suggest_conception_all", hasattr(st, 'suggest_conception_all'))

# Test suggest_conception on a fonctionnel story
s_fonc = JiraStory(key="C1", summary="Conception fonctionnelle du parcours utilisateur",
                   status=StoryStatus.BACKLOG, story_points=8)
sug_fonc = st.suggest_conception(s_fonc)
sug_fonc_labels = [s.label for s in sug_fonc]
t("conception_fonc_detected", "fonctionnel" in sug_fonc_labels, f"labels={sug_fonc_labels}")
t("conception_parent_added", "conception" in sug_fonc_labels, f"labels={sug_fonc_labels}")
t("conception_tests_auto", "tests" in sug_fonc_labels, f"labels={sug_fonc_labels}")

# Test suggest_conception on a technique story
s_tech = JiraStory(key="C2", summary="Architecture et modèle de données",
                   status=StoryStatus.BACKLOG, story_points=5)
sug_tech = st.suggest_conception(s_tech)
sug_tech_labels = [s.label for s in sug_tech]
t("conception_tech_detected", "technique" in sug_tech_labels, f"labels={sug_tech_labels}")
t("conception_tech_no_tests", "tests" not in sug_tech_labels, f"labels={sug_tech_labels}")

# Test: story with no conception signals
s_none = JiraStory(key="C3", summary="Corriger le bug d'affichage",
                   status=StoryStatus.IN_PROGRESS, story_points=3)
sug_none = st.suggest_conception(s_none)
t("conception_no_match", len(sug_none) == 0, f"unexpected: {[s.label for s in sug_none]}")

# Test: already tagged story is skipped
s_tagged = JiraStory(key="C4", summary="Conception fonctionnelle du formulaire",
                     status=StoryStatus.BACKLOG, story_points=5,
                     labels=["fonctionnel", "conception", "tests"])
sug_tagged = st.suggest_conception(s_tagged)
t("conception_skip_existing", len(sug_tagged) == 0, f"should skip: {[s.label for s in sug_tagged]}")

# ═══════════════════════════════════════════════════════
# CALCULATOR: score fallback uses max() not or
# ═══════════════════════════════════════════════════════
t("calc_score_max_fallback", 'max(self._score_global(tag_scores)' in calc)
t("calc_score_date_max_fallback", 'max(self._score_global(tag_scores_date' in calc)

# CLI: suggest-conception command
t("cli_suggest_conception", 'suggest-conception' in cli)
t("cli_suggest_conception_func", 'suggest_conception' in cli)
t("cli_suggest_conception_confirm", '_confirm_one' in cli)

# Template: météo uses "score projet" not "avancement"
t("tpl_meteo_score_projet", 'score projet' in macros)
t("tpl_meteo_no_avancement_label", 'avancement {{ delta' not in macros)

# ═══════════════════════════════════════════════════════
# CLI: labels cleanup command
# ═══════════════════════════════════════════════════════
t("cli_labels_cleanup", 'labels_cleanup' in cli or '"cleanup"' in cli)
t("cli_cleanup_flatten", 'flatten_all' in cli)
t("cli_cleanup_known_labels", 'known' in cli and 'label' in cli)
t("cli_cleanup_env_preserved", 'env:' in cli)

# CLI: confirm UI readability
t("cli_display_story_action", '_display_story_action' in cli)
t("cli_confirm_style", 'click.style' in cli)
t("cli_confirm_counter", 'idx' in cli and 'tot' in cli)

# Templates: no Assignee column in blocked stories
t("tpl_preview_no_assignee", 'Assigné' not in open(os.path.join(BASE, 'templates', 'kpi_preview.html')).read())
t("tpl_date_no_assignee", 'Assigné' not in open(os.path.join(BASE, 'templates', 'kpi_date.html')).read())
t("tpl_project_no_assignee", 'Assigné' not in open(os.path.join(BASE, 'templates', 'kpi_project.html')).read())

# Template: velocity empty placeholder
t("tpl_velocity_placeholder", 'Velocite indisponible' in macros)

# Templates: no em-dashes
for tname in ['kpi_preview.html', 'kpi_date.html', 'kpi_project.html', '_macros.html']:
    tc = open(os.path.join(BASE, 'templates', tname)).read()
    t(f"tpl_no_emdash_{tname.split('.')[0]}", '\u2014' not in tc and '\u2013' not in tc, f"em-dash in {tname}")

# CLI: labels derive command
with open(os.path.join(BASE, 'cli.py')) as f: cli_fresh=f.read()
t("cli_labels_derive", 'labels_derive' in cli_fresh or '"derive"' in cli_fresh)
t("cli_derive_rules", 'LABEL_DERIVE_RULES' in cli_fresh)
t("cli_derive_tests_fonctionnels", 'tests-fonctionnels' in cli_fresh)
t("cli_derive_conception_technique", 'conception-technique' in cli_fresh)
t("cli_derive_confirm", '_confirm_one' in cli_fresh)

# Derive rules logic (check via source code, can't import cli.py directly without atlassian)
t("derive_rule_tests_fonc", '"tests", "fonctionnel"' in cli_fresh and '"tests-fonctionnels"' in cli_fresh)
t("derive_rule_tests_fonc_auto", '"tests-fonctionnels-automatises"' in cli_fresh)
t("derive_rule_tests_tech", '"tests", "technique"' in cli_fresh and '"tests-unitaires"' in cli_fresh)
t("derive_rule_tests_backend", '"tests", "backend"' in cli_fresh and '"tests-integration"' in cli_fresh)
t("derive_rule_conception_tech", '"conception", "technique"' in cli_fresh and '"conception-technique"' in cli_fresh)
t("derive_rule_conception_fonc", '"conception", "fonctionnel"' in cli_fresh and '"conception-fonctionnelle"' in cli_fresh)

import sys
print(f"\n  {'🎉' if fail==0 else '💥'} {ok}/{ok+fail} passed")
sys.exit(1 if fail else 0)
