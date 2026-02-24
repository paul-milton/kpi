"""CLI — Click-based commands for KPI Generator v7."""
from __future__ import annotations
import logging, sys, traceback, webbrowser
from datetime import date
from pathlib import Path
import click
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


@click.group()
@click.option("--config", type=click.Path(exists=False), default=None, help="Config YAML path")
@click.option("--log-level", default="INFO", type=click.Choice(["DEBUG","INFO","WARNING","ERROR"], case_sensitive=False))
@click.pass_context
def main(ctx, config, log_level):
    """KPI Generator v7 — Jira → HTML/Confluence reports."""
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper(), logging.INFO)))
    ctx.ensure_object(dict)
    ctx.obj["cfg"] = load_config(Path(config) if config else None)
    ctx.obj["log_level"] = log_level.upper()


def _fetch(cfg):
    j = JiraAdapter(cfg); t = SemanticTagger(cfg)
    stories = j.fetch_all_stories()
    if not stories:
        click.echo("  ⚠️  Aucune story trouvée. Vérifiez project_key et issue types.")
        click.echo("  Lancez 'kpi debug-issuetypes' pour diagnostiquer.")
    try: vels = j.fetch_velocities()
    except Exception as e:
        logger.warning("velocities_failed", err=str(e)[:120]); vels = []
    try: sprints = j.fetch_sprints()
    except Exception as e:
        logger.warning("sprints_failed", err=str(e)[:120]); sprints = []
    return stories, vels, t.find_untagged(stories), sprints

def _report(cfg, stories, vels, untag, sprints=None):
    store = SnapshotStore(cfg); calc = KPICalculator(cfg)
    sn = cfg.get("project",{}).get("current_sprint", 1)
    prev = store.load_previous_sprint(sn)
    return calc.compute(stories, vels, untag, prev, jira_sprints=sprints), store

def _snap(r, store):
    store.save(Snapshot(
        snapshot_date=date.today().isoformat(), sprint_number=r.sprint_number,
        total_points=r.total_points, done_points=r.done_points,
        blocked_count=len(r.blocked_stories), completion_ratio=r.overall_completion,
        avg_velocity_per_week=r.raf.avg_velocity_per_week if r.raf else 0))

def _show(r):
    click.echo(f"\n  📊 {r.total_points} pts | {r.done_points} terminés ({r.overall_completion:.1%})")
    click.echo(f"  📦 restant estimé: {r.estimated_remaining} pts")
    click.echo(f"  🚨 {len(r.blocked_stories)} bloquées")
    if r.raf:
        click.echo(f"  📈 {r.raf.avg_velocity_per_week} pts/sem | {r.raf.velocity_per_sprint} pts/sprint (besoin: {r.raf.velocity_needed_per_week}/sem)")
        if r.raf.unestimated_count: click.echo(f"  📝 {r.raf.unestimated_count} non estimées: +{r.raf.unestimated_padding} pts au RAF")
        click.echo(f"  {'✅ en bonne voie' if r.raf.on_track else '🚨 à risque'}")
    click.echo()


@main.command()
@click.option("-o", "--output", default=None, help="Output HTML file")
@click.option("--from", "date_from", default=None, help="Start date ISO")
@click.option("--to", "date_to", default=None, help="End date ISO")
@click.pass_context
def preview(ctx, output, date_from, date_to):
    """Generate HTML preview report."""
    cfg = ctx.obj["cfg"]
    s, v, u, sp = _fetch(cfg); r, _ = _report(cfg, s, v, u, sp)
    html = ReportRenderer().render_preview(r)
    p = Path(output) if output else Path("kpi_preview.html")
    p.write_text(html, encoding="utf-8"); _show(r)
    try: webbrowser.open(p.resolve().as_uri())
    except: pass


@main.command()
@click.option("--from", "date_from", default=None, help="Start date ISO")
@click.option("--to", "date_to", default=None, help="End date ISO")
@click.pass_context
def generate(ctx, date_from, date_to):
    """Generate and publish to Confluence."""
    cfg = ctx.obj["cfg"]
    s, v, u, sp = _fetch(cfg); r, store = _report(cfg, s, v, u, sp); _snap(r, store)
    rr = ReportRenderer(); t = rr.build_title(r)
    ConfluenceAdapter(cfg).publish(t, rr.render_confluence(r)); _show(r)
    click.echo(f"  📄 {t}")


@main.command()
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def tag(ctx, dry_run):
    """Auto-tag stories with dimension labels."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); t = SemanticTagger(cfg); stories = j.fetch_all_stories()
    sugs = t.suggest_all(stories)
    if not sugs: click.echo("  aucune suggestion."); return
    by = {}
    for s in sugs: by.setdefault(s.story_key, []).append(s.label)
    click.echo(f"\n  {len(sugs)} suggestions pour {len(by)} stories")
    if dry_run:
        for k, ls in list(by.items())[:20]: click.echo(f"    {k} → {ls}")
        click.echo("  DRY RUN — --no-dry-run\n"); return
    ok = sum(1 for k, ls in by.items() if j.add_labels(k, ls))
    click.echo(f"  ✅ {ok}/{len(by)}\n")


@main.command("migrate-labels")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def migrate_labels(ctx, dry_run):
    """Remove legacy labels and apply new ones."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); t = SemanticTagger(cfg); stories = j.fetch_all_stories()
    pfx = cfg["jira"].get("legacy_label_prefixes", []); lc = rc = 0
    for s in stories:
        rm = [l for l in s.labels if any(l.startswith(p) for p in pfx)]
        if rm:
            lc += len(rm)
            if dry_run: click.echo(f"  {s.key}: ✗ {rm}")
            else: j.remove_labels(s.key, rm)
        new = [x.label for x in t.suggest_labels(s) if x.label not in s.labels]
        if new:
            rc += len(new)
            if dry_run: click.echo(f"  {s.key}: + {new}")
            else: j.add_labels(s.key, new)
    click.echo(f"\n  {'DRY RUN — ' if dry_run else '✅ '}{lc} legacy, {rc} nouveaux\n")


@main.command("purge-labels")
@click.option("--pattern", default=":", help="Substring to match in labels (default: ':')")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def purge_labels(ctx, pattern, dry_run):
    """Remove labels matching a pattern from all stories."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    total_rm = 0; affected = 0
    for s in stories:
        to_remove = [l for l in s.labels if pattern in l]
        if not to_remove: continue
        affected += 1; total_rm += len(to_remove)
        keep = [l for l in s.labels if pattern not in l]
        if dry_run:
            click.echo(f"  {s.key}: ✗ {to_remove}  (garde: {keep})")
        else:
            j.remove_labels(s.key, to_remove)
    click.echo(f"\n  {'DRY RUN — ' if dry_run else '✅ '}{total_rm} labels sur {affected} stories")
    if dry_run and total_rm > 0:
        click.echo("  --no-dry-run pour appliquer\n")


@main.command("debug-statuses")
@click.pass_context
def debug_statuses(ctx):
    """Show Jira status mapping diagnostics."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg)
    j.fetch_issue_types()
    counts = j.debug_statuses()
    rev = {n: o for o, ns in cfg["jira"]["status_mapping"].items() for n in ns}
    click.echo(f"\n{'='*60}\n  statuts — {sum(counts.values())} stories\n{'='*60}")
    for name, cnt in sorted(counts.items(), key=lambda x: -x[1]):
        mapped = rev.get(name, "⚠️ inconnu (>3sem→done)")
        click.echo(f"  {'✅' if name in rev else '⚠️'} {name:30s} → {mapped:25s} ({cnt})")
    click.echo()


@main.command("debug-projects")
@click.pass_context
def debug_projects(ctx):
    """Show accessible Jira projects for diagnostics."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg)
    projects = j.debug_projects()
    click.echo(f"\n{'='*60}\n  projets Jira accessibles — {len(projects)} trouvés\n{'='*60}")
    click.echo(f"\n  config project_key: {cfg['jira']['project_key']}")
    click.echo(f"  résolu vers:        {j._project}")
    click.echo(f"\n  {'─'*50}")
    click.echo(f"  {'clé':15s} {'nom':35s} {'id':6s}")
    click.echo(f"  {'─'*50}")
    for p in projects:
        marker = "✅" if p["key"] == j._project else "  "
        click.echo(f"  {marker} {p['key']:15s} {p['name']:35s} {p['id']:6s}")
    if not projects:
        click.echo("  ⚠️  Aucun projet accessible. Vérifiez le token Jira.")
    click.echo()


@main.command("debug-issuetypes")
@click.pass_context
def debug_issuetypes(ctx):
    """Show issue types discovered from Jira API."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg)
    types = j.debug_issue_types()
    classified = j.fetch_issue_types()
    click.echo(f"\n{'='*60}\n  types d'issues Jira — {len(types)} trouvés\n{'='*60}")
    click.echo(f"\n  config project_key: {cfg['jira']['project_key']}")
    click.echo(f"  config story_types: {cfg['jira'].get('story_types', [])}")
    click.echo(f"  config task_types:  {cfg['jira'].get('task_types', [])}")
    click.echo(f"\n  {'─'*50}")
    click.echo(f"  {'nom':30s} {'subtask':8s} {'id':6s}")
    click.echo(f"  {'─'*50}")
    for t in types:
        marker = "📋" if t["subtask"] else "📖"
        click.echo(f"  {marker} {t['name']:30s} {'oui' if t['subtask'] else 'non':8s} {t['id']:6s}")
    click.echo(f"\n  découverts stories: {classified['stories']}")
    click.echo(f"  découverts tasks:   {classified['tasks']}")
    click.echo()


@main.command()
@click.option("--from", "date_from", default=None, help="Start date ISO")
@click.option("--to", "date_to", default=None, help="End date ISO")
@click.pass_context
def snapshot(ctx, date_from, date_to):
    """Save current KPI snapshot to TinyDB."""
    cfg = ctx.obj["cfg"]
    s, v, u, sp = _fetch(cfg); r, store = _report(cfg, s, v, u, sp); _snap(r, store)
    _show(r); click.echo(f"  💾 {date.today().isoformat()}")


@main.command()
@click.argument("date_a")
@click.argument("date_b")
@click.pass_context
def compare(ctx, date_a, date_b):
    """Compare two snapshots by date."""
    cfg = ctx.obj["cfg"]
    store = SnapshotStore(cfg); a, b = store.compare(date_a, date_b)
    if not a: click.echo(f"  ❌ {date_a}"); return
    if not b: click.echo(f"  ❌ {date_b}"); return
    click.echo(f"\n{'='*60}\n  {date_a} (S{a.sprint_number}) → {date_b} (S{b.sprint_number})\n{'='*60}")
    for l, va, vb in [("stories",a.total_stories,b.total_stories),("points",a.total_points,b.total_points),
        ("terminés",a.done_points,b.done_points),("bloquées",a.blocked_count,b.blocked_count),
        ("%",int(a.completion_ratio*100),int(b.completion_ratio*100)),
        ("vel/sem",a.avg_velocity_per_week,b.avg_velocity_per_week)]:
        d = vb - va; click.echo(f"  {l:15s} {str(va):>8s} → {str(vb):>8s}  ({'+' if d>0 else ''}{d})")
    click.echo()


if __name__ == "__main__": main()
