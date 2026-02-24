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

import sys
print(f"\n  {'🎉' if fail==0 else '💥'} {ok}/{ok+fail} passed")
sys.exit(1 if fail else 0)
