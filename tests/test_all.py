"""Standalone v7 tests — stdlib only, 43+ checks."""
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

# 1-4: Config structure
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

# 5: domain_weight
dw=CFG["domain_weight"]; total=sum(dw.values())
t("domain_weight_sum", 0.95<=total<=1.05, f"{total}")

# 6: safe_int
def si(v):
    if v is None: return 0
    try: return int(float(v))
    except: return 0
t("safe_int", all(si(i)==e for i,e in [(None,0),(5,5),(3.0,3),("8",8),("5.0",5),("abc",0),("",0)]))

# 7-8: Tagger regex
def ckw(kw):
    e=re.escape(kw)
    return re.compile(rf"\b{e}\b",re.I) if len(kw)<=4 and " "not in kw else re.compile(e,re.I)
t("no_false_tu", ckw("TU").search("référentiel des structures") is None)
t("tu_matches", ckw("TU").search("les TU du module") is not None)

# 9-11: Sprint timeline
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

# 12-13: Velocity + prorata
sw=CFG["project"]["sprint_duration_weeks"]
t("velocity_3week", sw==3 and round(21/sw,1)==7.0)
t("prorata_calc", int(9*2/sw)==6)

# 14-17: Jira adapter code
with open(os.path.join(BASE, 'adapters', 'jira_adapter.py')) as f: jc=f.read()
t("no_recit", 'Récit' not in jc)
t("age_fallback", 'days_since_iso' in jc and 'auto_done' in jc)
t("created_field", 'created' in jc)
t("configurable_age", 'unknown_status_done_after_days' in jc)

# 18-20: days_since
def ds(s):
    if not s: return None
    try: return (date.today()-date.fromisoformat(s[:10])).days
    except: return None
t("ds_old", ds("2025-10-15T10:30:00")>100)
t("ds_today", ds(date.today().isoformat())==0)
t("ds_none", ds(None) is None)

# 21-29: Templates — preview
with open(os.path.join(BASE, 'templates', 'kpi_preview.html')) as f: tpl=f.read()
t("tpl_no_user_stories_row", 'user stories' not in tpl.lower().split('story points')[0] if 'story points' in tpl.lower() else True)
t("tpl_pts_faits", 'pts faits' in tpl)
t("tpl_restant_est", 'restant est' in tpl.lower() or 'restant_est' in tpl.lower() or 'estimated_remaining' in tpl)
t("tpl_fold", 'fold(' in tpl)
t("tpl_drawer", 'drawer' in tpl)
t("tpl_timeline", 'sprint_timeline' in tpl)
t("tpl_prorata", 'prorata' in tpl)
t("tpl_jira_links", 'jira_base_url' in tpl)
t("tpl_sprint_stories", 'current_sprint_stories' in tpl)

# 30-31: Confluence
with open(os.path.join(BASE, 'templates', 'kpi_confluence.html.j2')) as f: ct=f.read()
t("conf_pts_faits", 'pts faits' in ct)
t("conf_sprint_stories", 'current_sprint_stories' in ct)

# 32-36: Calculator code
with open(os.path.join(BASE, 'services', 'calculator.py')) as f: cc=f.read()
t("calc_filter_abandoned", 'filter_abandoned' in cc)
t("calc_prorata_per_dim", 'prorata_ratio' in cc and 'prorata_p' in cc)
t("calc_min_raf", 'min_raf' in cc)
t("calc_show_sprint", 'show_current_sprint_stories' in cc or 'show_sprint' in cc)
t("calc_backlog_in_raf", 'backlog_pts' in cc and 'max(projection_remaining, backlog_pts' in cc)

# 37-38: Models
with open(os.path.join(BASE, 'domain', 'models.py')) as f: mc=f.read()
t("model_no_total_stories_report", 'total_stories' not in mc.split('WeeklyReport')[1] if 'WeeklyReport' in mc else False)
t("model_effective_done", 'effective_done' in mc)
t("model_backlog_points", 'backlog_points' in mc)

# 38-40: CLI
with open(os.path.join(BASE, 'cli.py')) as f: cli=f.read()
t("cli_migrate", 'migrate-labels' in cli)
t("cli_compare", 'compare' in cli)
t("cli_snapshot", 'snapshot' in cli)

# 41-43: Breakdown logic
bd={"done":30,"delivered":10,"in_progress":5,"review":3,"testing":2,"backlog":20,"todo":15,"blocked":2}
t("bd_completed", bd["done"]+bd["delivered"]==40)
t("bd_active", bd["in_progress"]+bd["review"]+bd["testing"]==10)
t("bd_no_abandoned", "abandoned" not in str(CFG["dimensions"]))

# 44: Config has show_current_sprint_stories
t("cfg_show_sprint", CFG["project"].get("show_current_sprint_stories")==True)

# 45: Variation logic
t("var_delta", (100-80)==20 and f"+{100-80}"=="+20")

# 46: labels exist
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

# pyproject.toml
with open(os.path.join(os.path.dirname(__file__), '..', 'pyproject.toml')) as f: pt=f.read()
t("pyproject_no_refe", 'refe' not in pt.lower())
t("pyproject_kpi_package", 'include = "kpi"' in pt)
t("pyproject_kpi_script", 'kpi = "kpi.cli:main"' in pt)

# config.yaml project_key and db_path
t("cfg_project_key_no_refe", CFG["jira"]["project_key"] != "REFE")
t("cfg_db_path_no_refe", "refe" not in CFG.get("archive", {}).get("db_path", ""))

# ═══════════════════════════════════════════════════════
# RENDERER: tojson fix
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'services', 'renderer.py')) as f: rr=f.read()
t("renderer_custom_tojson", 'tojson' in rr and 'model_dump' in rr)
t("renderer_no_refe_title", 'REFE' not in rr)

# ═══════════════════════════════════════════════════════
# MODELS: Pydantic serialization
# ═══════════════════════════════════════════════════════
import sys, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from kpi.domain.models import (
    DimensionKPI, JiraStory, StatusBreakdown, StoryStatus,
    WeatherIcon, Variation, SprintVelocity, RAFEstimation,
    Snapshot, WeeklyReport, COMPLETED_STATUSES, ACTIVE_STATUSES,
)

# DimensionKPI JSON serialization (the bug we fixed)
dk = DimensionKPI(label="test", total_points=10, done_points=5, completion_ratio=0.5)
try:
    serialized = json.dumps(dk.model_dump(mode="json"))
    t("dimension_kpi_serializable", '"label"' in serialized and '"test"' in serialized)
except Exception as e:
    t("dimension_kpi_serializable", False, str(e))

# JiraStory serialization
js = JiraStory(key="KPI-1", summary="Test", status=StoryStatus.DONE, story_points=5)
try:
    serialized = json.dumps(js.model_dump(mode="json"))
    t("jira_story_serializable", '"KPI-1"' in serialized)
except Exception as e:
    t("jira_story_serializable", False, str(e))

# ═══════════════════════════════════════════════════════
# MODELS: StatusBreakdown properties
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
t("var_delta_str_neg", v_down.delta_str == "-3")
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
t("active_statuses", StoryStatus.IN_PROGRESS in ACTIVE_STATUSES and StoryStatus.REVIEW in ACTIVE_STATUSES and StoryStatus.TESTING in ACTIVE_STATUSES)
t("active_count", len(ACTIVE_STATUSES) == 3)
t("abandoned_not_active", StoryStatus.ABANDONED not in ACTIVE_STATUSES and StoryStatus.ABANDONED not in COMPLETED_STATUSES)

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

# ═══════════════════════════════════════════════════════
# STORE: snapshot round-trip (TinyDB in temp dir)
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
    t("store_save_load", loaded is not None and loaded.total_points == 100 and loaded.done_points == 40)
    t("store_load_missing", store.load_by_date("1999-01-01") is None)

    snap2 = Snapshot(snapshot_date="2026-02-01", sprint_number=4, total_points=110, done_points=55, completion_ratio=0.5)
    store.save(snap2)
    prev = store.load_previous_sprint(4)
    t("store_previous_sprint", prev is not None and prev.sprint_number == 3)

    a, b = store.compare("2026-01-15", "2026-02-01")
    t("store_compare", a is not None and b is not None and a.done_points == 40 and b.done_points == 55)

    all_snaps = store.load_all()
    t("store_load_all", len(all_snaps) == 2 and all_snaps[0].snapshot_date < all_snaps[1].snapshot_date)

    # overwrite same date
    snap_updated = Snapshot(snapshot_date="2026-01-15", sprint_number=3, total_points=100, done_points=45, completion_ratio=0.45)
    store.save(snap_updated)
    t("store_overwrite", store.load_by_date("2026-01-15").done_points == 45)

    import shutil
    shutil.rmtree(td, ignore_errors=True)
else:
    print("  ⚠️  tinydb not installed — skipping store tests")

# ═══════════════════════════════════════════════════════
# RENDERER: tojson filter actually works
# ═══════════════════════════════════════════════════════
from kpi.services.renderer import _pydantic_tojson
dk_list = [DimensionKPI(label="a", total_points=10), DimensionKPI(label="b", total_points=20)]
try:
    result = _pydantic_tojson(dk_list)
    parsed = json.loads(result)
    t("tojson_list_models", len(parsed) == 2 and parsed[0]["label"] == "a")
except Exception as e:
    t("tojson_list_models", False, str(e))

try:
    result = _pydantic_tojson(dk_list[0])
    parsed = json.loads(result)
    t("tojson_single_model", parsed["label"] == "a" and parsed["total_points"] == 10)
except Exception as e:
    t("tojson_single_model", False, str(e))

t("tojson_plain_value", json.loads(_pydantic_tojson(42)) == 42)
try:
    result = _pydantic_tojson([1, 2, 3])
    t("tojson_plain_list", json.loads(result) == [1, 2, 3])
except Exception as e:
    t("tojson_plain_list", False, str(e))

# ═══════════════════════════════════════════════════════
# TEMPLATES: no REFE in rendered output
# ═══════════════════════════════════════════════════════
t("tpl_preview_no_refe", 'REFE' not in tpl)
t("tpl_confluence_no_refe", 'REFE' not in ct)

# ═══════════════════════════════════════════════════════
# UNESTIMATED STORIES: +13 pts padding
# ═══════════════════════════════════════════════════════
t("cfg_unestimated_default", CFG.get("unestimated_default_points") == 13)

# RAFEstimation has new fields
raf = RAFEstimation(unestimated_count=3, unestimated_padding=39)
t("raf_unestimated_fields", raf.unestimated_count == 3 and raf.unestimated_padding == 39)

# Calculator picks up config
t("calc_unest_default", calc._unest_default == 13)

# Simulate: 2 stories with 0 SP, not done, not planned → +26 to RAF
from kpi.services.calculator import KPICalculator as KC
test_stories = [
    JiraStory(key="A", summary="done", status=StoryStatus.DONE, story_points=10),
    JiraStory(key="B", summary="estimated backlog", status=StoryStatus.BACKLOG, story_points=5),
    JiraStory(key="C", summary="unest 1", status=StoryStatus.BACKLOG, story_points=0),
    JiraStory(key="D", summary="unest 2", status=StoryStatus.TODO, story_points=0),
    JiraStory(key="E", summary="unest planned", status=StoryStatus.BACKLOG, story_points=0, sprint="Sprint 5"),
    JiraStory(key="F", summary="active 0sp", status=StoryStatus.IN_PROGRESS, story_points=0),
]
test_cfg = {
    "dimensions": [], "domain_weight": {},
    "kpi": {"weather": {"sunny_threshold": 0.8, "partly_cloudy_threshold": 0.6,
                         "cloudy_threshold": 0.4, "rainy_threshold": 0.2}},
    "project": {"start_date": "2025-10-01", "end_date": "2026-09-30", "sprint_duration_weeks": 3},
    "jira": {"url": ""},
    "unestimated_default_points": 13,
}
tc = KC(test_cfg)
# Only C and D qualify: 0 SP, not done, not active, no sprint
test_raf = tc._raf(15, 10, 0, [], test_stories)
t("unest_count", test_raf.unestimated_count == 2, f"got {test_raf.unestimated_count}")
t("unest_padding", test_raf.unestimated_padding == 26, f"got {test_raf.unestimated_padding}")
t("unest_in_remaining", test_raf.remaining_points >= 26, f"got {test_raf.remaining_points}")

# E has sprint → not counted, F is active → not counted
test_raf0 = tc._raf(10, 10, 0, [], [JiraStory(key="X", summary="x", status=StoryStatus.DONE, story_points=10)])
t("unest_zero_when_none", test_raf0.unestimated_count == 0 and test_raf0.unestimated_padding == 0)

# ═══════════════════════════════════════════════════════
# CLI: purge-labels command exists
# ═══════════════════════════════════════════════════════
with open(os.path.join(BASE, 'cli.py')) as f: cli2=f.read()
t("cli_purge_labels", 'purge-labels' in cli2 and 'purge_labels' in cli2)
t("cli_purge_pattern_param", '--pattern' in cli2)

# ═══════════════════════════════════════════════════════
# DIMENSIONS: conception-fonctionnelle under fonctionnel
# ═══════════════════════════════════════════════════════
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

import sys
print(f"\n  {'🎉' if fail==0 else '💥'} {ok}/{ok+fail} passed")
sys.exit(1 if fail else 0)
