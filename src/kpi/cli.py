"""CLI — preview, generate, tag, migrate-labels, debug-statuses, snapshot, compare."""
from __future__ import annotations
import argparse, logging, webbrowser
from datetime import date
from pathlib import Path
import structlog
from kpi.adapters.confluence_adapter import ConfluenceAdapter
from kpi.adapters.jira_adapter import JiraAdapter
from kpi.config.loader import load_config
from kpi.domain.models import Snapshot
from kpi.services.calculator import KPICalculator
from kpi.services.dates import parse_date
from kpi.services.renderer import ReportRenderer
from kpi.services.store import SnapshotStore
from kpi.services.tagger import SemanticTagger
logger = structlog.get_logger()

def main() -> None:
    a = _args()
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, a.log_level, logging.INFO)))
    cfg = load_config(a.config)
    match a.command:
        case "preview":    _preview(cfg, a)
        case "generate":   _generate(cfg, a)
        case "tag":        _tag(cfg, a.dry_run)
        case "migrate-labels": _migrate(cfg, a.dry_run)
        case "purge-labels": _purge_labels(cfg, a.pattern, a.dry_run)
        case "debug-statuses": _debug(cfg)
        case "snapshot":   _snapshot(cfg, a)
        case "compare":    _compare(cfg, a.date_a, a.date_b)

def _dates(a) -> tuple[date|None, date|None]:
    s = parse_date(a.date_from) if getattr(a, "date_from", None) else None
    e = parse_date(a.date_to) if getattr(a, "date_to", None) else None
    return s, e

def _fetch(cfg):
    j = JiraAdapter(cfg); t = SemanticTagger(cfg)
    stories = j.fetch_all_stories()
    try: vels = j.fetch_velocities()
    except: vels = []
    return stories, vels, t.find_untagged(stories)

def _report(cfg, stories, vels, untag, a=None):
    store = SnapshotStore(cfg); calc = KPICalculator(cfg)
    sn = cfg.get("project",{}).get("current_sprint", 1)
    prev = store.load_previous_sprint(sn)
    return calc.compute(stories, vels, untag, prev), store

def _snap(r, store):
    store.save(Snapshot(
        snapshot_date=date.today().isoformat(), sprint_number=r.sprint_number,
        sprint_week=r.sprint_week, total_points=r.total_points,
        done_points=r.done_points,
        blocked_count=len(r.blocked_stories), completion_ratio=r.overall_completion,
        avg_velocity_per_week=r.raf.avg_velocity_per_week if r.raf else 0))

def _show(r):
    print(f"\n  📊 {r.total_points} pts | {r.effective_done} faits ({r.overall_completion:.1%})")
    print(f"  🚨 {len(r.blocked_stories)} bloquées | ❓ {len(r.unidentified_stories)} orphelines")
    if r.raf:
        print(f"  📈 {r.raf.avg_velocity_per_week} pts/sem (besoin: {r.raf.velocity_needed_per_week})")
        if r.raf.prorata_points: print(f"  ⏱️  prorata: +{r.raf.prorata_points} pts")
        if r.raf.unestimated_count: print(f"  📝 {r.raf.unestimated_count} stories non estimées: +{r.raf.unestimated_padding} pts au RAF")
        print(f"  {'✅ en bonne voie' if r.raf.on_track else '🚨 à risque'}")
    tl = r.sprint_timeline
    if tl:
        past = sum(1 for s in tl if s.is_past)
        print(f"  📅 sprint {r.sprint_number} s{r.sprint_week}/{r.sprint_duration_weeks} ({past}/{len(tl)} écoulés)")
    print()

def _preview(cfg, a):
    s, v, u = _fetch(cfg); r, _ = _report(cfg, s, v, u, a)
    html = ReportRenderer().render_preview(r)
    p = Path(a.output) if a.output else Path("kpi_preview.html")
    p.write_text(html, encoding="utf-8"); _show(r)
    try: webbrowser.open(p.resolve().as_uri())
    except: pass

def _generate(cfg, a):
    s, v, u = _fetch(cfg); r, store = _report(cfg, s, v, u, a); _snap(r, store)
    rr = ReportRenderer(); t = rr.build_title(r)
    ConfluenceAdapter(cfg).publish(t, rr.render_confluence(r)); _show(r)
    print(f"  📄 {t}")

def _tag(cfg, dry=True):
    j = JiraAdapter(cfg); t = SemanticTagger(cfg); stories = j.fetch_all_stories()
    sugs = t.suggest_all(stories)
    if not sugs: print("  aucune suggestion."); return
    by = {}
    for s in sugs: by.setdefault(s.story_key, []).append(s.label)
    print(f"\n  {len(sugs)} suggestions pour {len(by)} stories")
    if dry:
        for k, ls in list(by.items())[:20]: print(f"    {k} → {ls}")
        print("  DRY RUN — --no-dry-run\n"); return
    ok = sum(1 for k, ls in by.items() if j.add_labels(k, ls))
    print(f"  ✅ {ok}/{len(by)}\n")

def _migrate(cfg, dry=True):
    j = JiraAdapter(cfg); t = SemanticTagger(cfg); stories = j.fetch_all_stories()
    pfx = cfg["jira"].get("legacy_label_prefixes", []); lc = rc = 0
    for s in stories:
        rm = [l for l in s.labels if any(l.startswith(p) for p in pfx)]
        if rm:
            lc += len(rm)
            if dry: print(f"  {s.key}: ✗ {rm}")
            else: j.remove_labels(s.key, rm)
        new = [x.label for x in t.suggest_labels(s) if x.label not in s.labels]
        if new:
            rc += len(new)
            if dry: print(f"  {s.key}: + {new}")
            else: j.add_labels(s.key, new)
    print(f"\n  {'DRY RUN — ' if dry else '✅ '}{lc} legacy, {rc} nouveaux\n")

def _purge_labels(cfg, pattern, dry=True):
    """Remove labels matching a pattern (e.g. ':') from all stories."""
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    total_rm = 0; affected = 0
    for s in stories:
        to_remove = [l for l in s.labels if pattern in l]
        if not to_remove: continue
        affected += 1; total_rm += len(to_remove)
        keep = [l for l in s.labels if pattern not in l]
        if dry:
            print(f"  {s.key}: ✗ {to_remove}  (garde: {keep})")
        else:
            j.remove_labels(s.key, to_remove)
    print(f"\n  {'DRY RUN — ' if dry else '✅ '}{total_rm} labels sur {affected} stories")
    if dry and total_rm > 0:
        print("  --no-dry-run pour appliquer\n")

def _debug(cfg):
    j = JiraAdapter(cfg); counts = j.debug_statuses()
    rev = {n: o for o, ns in cfg["jira"]["status_mapping"].items() for n in ns}
    print(f"\n{'='*60}\n  statuts — {sum(counts.values())} stories\n{'='*60}")
    for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        mapped = rev.get(name, "⚠️ inconnu (>3sem→done)")
        print(f"  {'✅' if name in rev else '⚠️'} {name:30s} → {mapped:25s} ({cnt})")
    print()

def _snapshot(cfg, a):
    s, v, u = _fetch(cfg); r, store = _report(cfg, s, v, u, a); _snap(r, store)
    _show(r); print(f"  💾 {date.today().isoformat()}")

def _compare(cfg, da, db):
    store = SnapshotStore(cfg); a, b = store.compare(da, db)
    if not a: print(f"  ❌ {da}"); return
    if not b: print(f"  ❌ {db}"); return
    print(f"\n{'='*60}\n  {da} (S{a.sprint_number}) → {db} (S{b.sprint_number})\n{'='*60}")
    for l, va, vb in [("stories",a.total_stories,b.total_stories),("points",a.total_points,b.total_points),
        ("terminés",a.done_points,b.done_points),("bloquées",a.blocked_count,b.blocked_count),
        ("%",int(a.completion_ratio*100),int(b.completion_ratio*100)),
        ("vel/sem",a.avg_velocity_per_week,b.avg_velocity_per_week)]:
        d = vb - va; print(f"  {l:15s} {str(va):>8s} → {str(vb):>8s}  ({'+' if d>0 else ''}{d})")
    print()

def _add_dates(p):
    p.add_argument("--from", dest="date_from", default=None, help="Start date ISO")
    p.add_argument("--to", dest="date_to", default=None, help="End date ISO")

def _args():
    p = argparse.ArgumentParser(description="KPI Generator v7")
    p.add_argument("--config", type=Path, default=None)
    p.add_argument("--log-level", default="INFO")
    s = p.add_subparsers(dest="command", required=True)
    pv = s.add_parser("preview"); pv.add_argument("-o","--output",default=None); _add_dates(pv)
    g = s.add_parser("generate"); _add_dates(g)
    t = s.add_parser("tag"); t.add_argument("--no-dry-run",dest="dry_run",action="store_false",default=True)
    m = s.add_parser("migrate-labels"); m.add_argument("--no-dry-run",dest="dry_run",action="store_false",default=True)
    pl = s.add_parser("purge-labels"); pl.add_argument("--pattern",default=":",help="Substring to match in labels (default: ':')"); pl.add_argument("--no-dry-run",dest="dry_run",action="store_false",default=True)
    s.add_parser("debug-statuses")
    sn = s.add_parser("snapshot"); _add_dates(sn)
    c = s.add_parser("compare"); c.add_argument("date_a"); c.add_argument("date_b")
    return p.parse_args()

if __name__ == "__main__": main()
