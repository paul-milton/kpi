"""CLI — Click-based commands for KPI Generator v7."""
from __future__ import annotations
import logging, re, sys, traceback, webbrowser
from datetime import date
from pathlib import Path
import click
import structlog
from kpi.adapters.confluence_adapter import ConfluenceAdapter
from kpi.adapters.jira_adapter import JiraAdapter
from kpi.config.loader import load_config
from kpi.domain.models import JiraStory, Snapshot
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
    import sys
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, log_level.upper(), logging.INFO)))
    ctx.ensure_object(dict)
    offline = len(sys.argv) > 1 and sys.argv[1] == "demo"
    ctx.obj["cfg"] = load_config(Path(config) if config else None, offline=offline)
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
    if not vels:
        click.echo("  ⚠️  Velocite indisponible (pas de sprints fermes ou erreur Jira).")
    try: sprints = j.fetch_sprints()
    except Exception as e:
        logger.warning("sprints_failed", err=str(e)[:120]); sprints = []
    if not sprints:
        click.echo("  ⚠️  Sprints indisponibles (pas de board ou erreur API). Fallback: dates config.")
        click.echo("     Lancez 'kpi debug-sprints' pour diagnostiquer.")
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
        avg_velocity_per_week=r.raf.avg_velocity_per_week if r.raf else 0,
        score_global=r.score_global_project,
        score_global_date=r.score_global_date,
        score_global_project=r.score_global_project,
        tag_scores={ts.label: ts.score for ts in r.tag_scores if ts.total_points > 0},
        backlog_variation=r.backlog_stability.variation_project if r.backlog_stability else 0.0))

def _show(r, debug=False):
    click.echo(f"\n  📊 {r.total_points} pts | {r.done_points} terminés ({r.overall_completion:.1%})")
    click.echo(f"  📦 restant estimé: {r.estimated_remaining} pts")
    click.echo(f"  🚨 {len(r.blocked_stories)} bloquées")
    if r.raf:
        click.echo(f"  📈 {r.raf.avg_velocity_per_week} pts/sem | {r.raf.velocity_per_sprint} pts/sprint (besoin: {r.raf.velocity_needed_per_week}/sem)")
        if r.raf.unestimated_count: click.echo(f"  📝 {r.raf.unestimated_count} non estimées: +{r.raf.unestimated_padding} pts au RAF")
        click.echo(f"  {'✅ en bonne voie' if r.raf.on_track else '🚨 à risque'}")
    if debug:
        click.echo(f"\n  {'─'*50}")
        click.echo(f"  DEBUG score/sprints:")
        click.echo(f"    score_date={r.score_global_date:.4f}  score_project={r.score_global_project:.4f}")
        click.echo(f"    temps_ecoule={r.time_progress:.2%}  sprint={r.sprint_number}")
        ds = r.date_stories if hasattr(r, 'date_stories') else []
        click.echo(f"    date_stories={len(ds)} stories, {sum(s.story_points for s in ds)} pts")
        if ds:
            sprints_in_date = {s.sprint for s in ds if s.sprint}
            click.echo(f"    sprints dans date_stories: {sprints_in_date}")
        else:
            click.echo(f"    ⚠️  AUCUNE date_story - le score a date sera 0%")
            click.echo(f"    verifiez: les stories ont-elles un sprint assigne dans Jira ?")
            # Show sample sprints from all stories
            all_sprints = {s.sprint for s in r.all_stories if s.sprint}
            click.echo(f"    sprints sur all_stories: {list(all_sprints)[:10]}")
        click.echo(f"    velocites={len(r.velocities)} sprints")
        click.echo(f"  {'─'*50}")
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
    p.write_text(html, encoding="utf-8"); _show(r, debug=ctx.obj["log_level"] == "DEBUG")
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
@click.option("--port", default=8000, type=int, help="Server port (default 8000)")
@click.option("--cache-ttl", default=300, type=int, help="Cache TTL in seconds (default 300)")
@click.pass_context
def serve(ctx, port, cache_ttl):
    """Start a local web server with live KPI reports."""
    import uvicorn
    from kpi.server import create_app
    cfg = ctx.obj["cfg"]
    app = create_app(cfg=cfg, cache_ttl=cache_ttl)
    click.echo(f"  KPI server on http://localhost:{port} (cache TTL={cache_ttl}s)")
    click.echo(f"  Routes: /preview  /date  /project")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level=ctx.obj["log_level"].lower())


@main.command("report-date")
@click.option("-o", "--output", default=None, help="Output HTML file")
@click.pass_context
def report_date(ctx, output):
    """Generate 'a date' HTML report (current sprint view)."""
    cfg = ctx.obj["cfg"]
    s, v, u, sp = _fetch(cfg); r, store = _report(cfg, s, v, u, sp); _snap(r, store)
    html = ReportRenderer().render_date(r)
    p = Path(output) if output else Path("kpi_date.html")
    p.write_text(html, encoding="utf-8"); _show(r)
    try: webbrowser.open(p.resolve().as_uri())
    except: pass


@main.command("report-project")
@click.option("-o", "--output", default=None, help="Output HTML file")
@click.option("--compare-with", default=None, help="Compare with date (YYYY-MM-DD) or sprint (sprint-N)")
@click.pass_context
def report_project(ctx, output, compare_with):
    """Generate 'global projet' HTML report (full project view with projections)."""
    cfg = ctx.obj["cfg"]
    s, v, u, sp = _fetch(cfg)
    store = SnapshotStore(cfg); calc = KPICalculator(cfg)
    sn = cfg.get("project",{}).get("current_sprint", 1)
    prev = None
    if compare_with:
        if compare_with.startswith("sprint-"):
            try: prev = store.load_by_sprint(int(compare_with.split("-")[1]))
            except: click.echo(f"  ⚠️  sprint invalide: {compare_with}")
        else:
            prev = store.load_by_date(compare_with)
            if not prev: click.echo(f"  ⚠️  snapshot non trouvé: {compare_with}")
    if not prev: prev = store.load_previous_sprint(sn)
    r = calc.compute(s, v, u, prev, jira_sprints=sp)
    _snap(r, store)
    html = ReportRenderer().render_project(r)
    p = Path(output) if output else Path("kpi_project.html")
    p.write_text(html, encoding="utf-8"); _show(r)
    try: webbrowser.open(p.resolve().as_uri())
    except: pass


@main.command("publish-date")
@click.pass_context
def publish_date(ctx):
    """Publish 'a date' report to Confluence."""
    cfg = ctx.obj["cfg"]
    s, v, u, sp = _fetch(cfg); r, store = _report(cfg, s, v, u, sp); _snap(r, store)
    rr = ReportRenderer(); t = rr.build_title(r).replace("Hebdo", "A Date")
    ConfluenceAdapter(cfg).publish(t, rr.render_confluence(r)); _show(r)
    click.echo(f"  📄 {t}")


@main.command("publish-project")
@click.pass_context
def publish_project(ctx):
    """Publish 'global projet' report to Confluence."""
    cfg = ctx.obj["cfg"]
    s, v, u, sp = _fetch(cfg); r, store = _report(cfg, s, v, u, sp); _snap(r, store)
    rr = ReportRenderer(); t = rr.build_title(r).replace("Hebdo", "Global Projet")
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
    ok = 0; auto = False; idx = 0; tot = len(by)
    smap = {s.key: s for s in stories}
    for k, ls in by.items():
        idx += 1
        if not auto:
            summary = smap[k].summary if k in smap else ""
            _display_story_action(k, summary, ls, idx, tot, "+")
            r = _confirm_one(f"Appliquer ?")
            if r == "q": break
            if r == "n": continue
            if r == "a": auto = True
        if j.add_labels(k, ls): ok += 1; click.echo(f"    {click.style('OK', fg='green')} {k}: +{ls}")
    click.echo(f"\n  {ok}/{tot} stories modifiees\n")


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
@click.option("--regex", "use_regex", is_flag=True, default=False, help="Treat --pattern as a regex")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def purge_labels(ctx, pattern, use_regex, dry_run):
    """Remove labels matching a pattern from all stories."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    if use_regex:
        import re; rx = re.compile(pattern)
        match = lambda l: rx.search(l)
    else:
        match = lambda l: pattern in l
    total_rm = 0; affected = 0; auto = False
    for s in stories:
        to_remove = [l for l in s.labels if match(l)]
        if not to_remove: continue
        keep = [l for l in s.labels if not match(l)]
        if dry_run:
            click.echo(f"  {s.key}: ✗ {to_remove}  (garde: {keep})")
            affected += 1; total_rm += len(to_remove)
        else:
            if not auto:
                click.echo(f"  {s.key}: ✗ {to_remove}  (garde: {keep})")
                r = _confirm_one(f"Supprimer {to_remove} de {s.key} ?")
                if r == "q": break
                if r == "n": continue
                if r == "a": auto = True
            j.remove_labels(s.key, to_remove)
            affected += 1; total_rm += len(to_remove)
            click.echo(f"    ✅ {s.key}: ✗ {to_remove}")
    click.echo(f"\n  {'DRY RUN — ' if dry_run else '✅ '}{total_rm} labels sur {affected} stories")
    if dry_run and total_rm > 0:
        click.echo("  --no-dry-run pour appliquer\n")


@main.group()
@click.pass_context
def labels(ctx):
    """Manage Jira labels (add, remove, replace, list)."""
    pass


@labels.command("add")
@click.argument("label")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_add(ctx, label, filter_status, filter_sprint, filter_label, filter_key,
               filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Add a label to matching stories."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    already = [s for s in matched if label in s.labels]
    to_add = [s for s in matched if label not in s.labels]
    click.echo(f"\n  🏷️  add '{label}' — {len(to_add)} stories ({len(already)} déjà taggées, {len(stories) - len(matched)} filtrées)")
    if dry_run:
        for s in to_add[:30]:
            click.echo(f"    DRY {s.key} — {s.summary[:60]}")
        if len(to_add) > 30: click.echo(f"    ... et {len(to_add) - 30} autres")
        if to_add: click.echo("  --no-dry-run pour appliquer\n")
        return
    ok = 0; auto = False; idx = 0; tot = len(to_add)
    for s in to_add:
        idx += 1
        if not auto:
            _display_story_action(s.key, s.summary, [label], idx, tot, "+")
            r = _confirm_one(f"Appliquer ?")
            if r == "q": break
            if r == "n": continue
            if r == "a": auto = True
        if j.add_labels(s.key, [label]): ok += 1; click.echo(f"    {click.style('OK', fg='green')} {s.key}: +{label}")
    click.echo(f"\n  {ok}/{tot} modifiees\n")


@labels.command("remove")
@click.argument("pattern")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_remove(ctx, pattern, filter_status, filter_sprint, filter_label, filter_key,
                  filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Remove labels matching a regex pattern from matching stories."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    pat = re.compile(pattern)
    total_rm = 0; affected = 0; auto = False
    for s in matched:
        to_remove = [l for l in s.labels if pat.search(l)]
        if not to_remove: continue
        if dry_run:
            affected += 1; total_rm += len(to_remove)
            click.echo(f"    DRY {s.key}: ✗ {to_remove}")
        else:
            if not auto:
                click.echo(f"  {s.key}: ✗ {to_remove}")
                r = _confirm_one(f"Supprimer {to_remove} de {s.key} ?")
                if r == "q": break
                if r == "n": continue
                if r == "a": auto = True
            j.remove_labels(s.key, to_remove)
            affected += 1; total_rm += len(to_remove)
            click.echo(f"    ✅  {s.key}: ✗ {to_remove}")
    click.echo(f"\n  🏷️  remove '{pattern}' — {total_rm} labels sur {affected} stories")
    if dry_run and total_rm > 0:
        click.echo("  --no-dry-run pour appliquer\n")


@labels.command("replace")
@click.argument("old_pattern")
@click.argument("new_label")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_replace(ctx, old_pattern, new_label, filter_status, filter_sprint, filter_label, filter_key,
                   filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Replace labels matching a regex with a new label."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    pat = re.compile(old_pattern)
    count = 0; auto = False
    for s in matched:
        to_remove = [l for l in s.labels if pat.search(l)]
        if not to_remove: continue
        if dry_run:
            count += 1
            click.echo(f"    DRY {s.key}: {to_remove} → {new_label}")
        else:
            if not auto:
                click.echo(f"  {s.key}: {to_remove} → {new_label}")
                r = _confirm_one(f"Remplacer {to_remove} par '{new_label}' sur {s.key} ?")
                if r == "q": break
                if r == "n": continue
                if r == "a": auto = True
            j.remove_labels(s.key, to_remove)
            if new_label not in s.labels:
                j.add_labels(s.key, [new_label])
            count += 1
            click.echo(f"    ✅  {s.key}: {to_remove} → {new_label}")
    click.echo(f"\n  🏷️  replace '{old_pattern}' → '{new_label}' — {count} stories")
    if dry_run and count > 0:
        click.echo("  --no-dry-run pour appliquer\n")


@labels.command("env")
@click.argument("env_name", type=click.Choice(["dev", "recette", "preprod", "prod"], case_sensitive=False))
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_env(ctx, env_name, filter_status, filter_sprint, filter_label, filter_key,
               filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Assign an environment label (env:xxx) to matching stories. Replaces any existing env: label."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    new_label = f"env:{env_name.lower()}"
    changed = 0; skipped = 0; auto = False
    for s in matched:
        old_envs = [l for l in s.labels if l.startswith("env:")]
        if old_envs == [new_label]:
            skipped += 1; continue
        if dry_run:
            changed += 1
            if old_envs:
                click.echo(f"    DRY {s.key}: {old_envs} → {new_label} — {s.summary[:50]}")
            else:
                click.echo(f"    DRY {s.key}: + {new_label} — {s.summary[:50]}")
        else:
            desc = f"{s.key}: {old_envs} → {new_label}" if old_envs else f"{s.key}: + {new_label}"
            if not auto:
                click.echo(f"  {desc} — {s.summary[:50]}")
                r = _confirm_one(f"Appliquer {new_label} sur {s.key} ?")
                if r == "q": break
                if r == "n": continue
                if r == "a": auto = True
            if old_envs:
                j.remove_labels(s.key, old_envs)
            j.add_labels(s.key, [new_label])
            changed += 1
            click.echo(f"    ✅  {s.key}: {new_label}")
    click.echo(f"\n  🌍 env '{new_label}' — {changed} à modifier ({skipped} déjà ok, {len(stories) - len(matched)} filtrées)")
    if dry_run and changed > 0:
        click.echo("  --no-dry-run pour appliquer\n")


@labels.command("clear-env")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_clear_env(ctx, filter_status, filter_sprint, filter_label, filter_key,
                     filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Remove all env: labels from matching stories."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    removed = 0; auto = False
    for s in matched:
        old_envs = [l for l in s.labels if l.startswith("env:")]
        if not old_envs: continue
        if dry_run:
            removed += 1
            click.echo(f"    DRY {s.key}: ✗ {old_envs} — {s.summary[:50]}")
        else:
            if not auto:
                click.echo(f"  {s.key}: ✗ {old_envs} — {s.summary[:50]}")
                r = _confirm_one(f"Supprimer {old_envs} de {s.key} ?")
                if r == "q": break
                if r == "n": continue
                if r == "a": auto = True
            j.remove_labels(s.key, old_envs)
            removed += 1
            click.echo(f"    ✅  {s.key}: ✗ {old_envs}")
    click.echo(f"\n  🌍 clear-env — {removed} stories avec env: label")
    if dry_run and removed > 0:
        click.echo("  --no-dry-run pour appliquer\n")


@labels.command("expand-env")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex). Default: backlog|specification|todo")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex). Default: ops|devops|infrastructure")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--exclude-label", "-x", multiple=True, help="Exclude stories with these labels (regex). Default: backend|frontend|developpement|test")
@click.option("--all-statuses", is_flag=True, default=False, help="Include all statuses (override default open-only filter)")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_expand_env(ctx, filter_status, filter_sprint, filter_label, filter_key,
                      filter_summary, filter_assignee, filter_points_min, filter_points_max,
                      exclude_label, all_statuses, dry_run):
    """Create subtasks per environment for ops/infra stories.

    By default, only targets stories that are not yet started (backlog,
    specification, todo) and have ops/devops/infrastructure/observabilite labels.
    Excludes stories with backend/frontend/developpement/test labels.
    Use --all-statuses to include in-progress stories.
    """
    from kpi.domain.models import OPS_LABELS, ENV_NAMES
    cfg = ctx.obj["cfg"]
    # Apply defaults: open statuses + ops/devops/infrastructure/observabilite labels
    if not filter_status and not all_statuses:
        filter_status = ("backlog|specification|todo",)
    if not filter_label:
        filter_label = ("ops|devops|infrastructure|observabilite",)
    if not exclude_label:
        exclude_label = ("backend|frontend|developpement|test",)
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    # Exclude stories matching exclude-label patterns
    for pat in exclude_label:
        rx = re.compile(pat, re.I)
        matched = [s for s in matched if not any(rx.search(l) for l in s.labels)]
    # Build parent→children map for existing subtasks
    children_by_parent: dict[str, list[JiraStory]] = {}
    for s in stories:
        if s.parent_key:
            children_by_parent.setdefault(s.parent_key, []).append(s)

    to_create: list[tuple[JiraStory, list[str], list[str]]] = []  # (story, ops_labels, missing_envs)
    for s in matched:
        ops = [l for l in s.labels if l in OPS_LABELS]
        if not ops:
            continue
        # Check existing env: labels on story AND its subtasks
        existing_envs = set()
        for l in s.labels:
            if l.startswith("env:"):
                existing_envs.add(l.split(":", 1)[1])
        for child in children_by_parent.get(s.key, []):
            for l in child.labels:
                if l.startswith("env:"):
                    existing_envs.add(l.split(":", 1)[1])
            # Also check if subtask summary contains env name
            for env in ENV_NAMES:
                if f"[{env}]" in child.summary.lower() or f"(env:{env})" in child.summary.lower() or f"({env})" in child.summary.lower():
                    existing_envs.add(env)
        missing = [e for e in ENV_NAMES if e not in existing_envs]
        if missing:
            to_create.append((s, ops, missing))

    if not to_create:
        click.echo("\n  ✅ Toutes les stories ops/infra ont des tâches par env.")
        return

    click.echo(f"\n  🌍 expand-env — {len(to_create)} stories ops/infra à dupliquer par env\n")
    total_tasks = 0
    for s, ops, missing in to_create:
        click.echo(f"  {'─'*60}")
        click.echo(f"  📋 {s.key} — {s.summary}")
        click.echo(f"     status: {s.status}  |  points: {s.story_points}  |  assigné: {s.assignee or '—'}")
        click.echo(f"     labels ops: {ops}")
        click.echo(f"     sprint: {s.sprint or '—'}")
        click.echo(f"     → tâches à créer: {', '.join(missing)}")
        total_tasks += len(missing)

    click.echo(f"\n  {'─'*60}")
    click.echo(f"  Total: {total_tasks} sous-tâches à créer pour {len(to_create)} stories")

    if dry_run:
        click.echo("  DRY RUN — --no-dry-run pour appliquer\n")
        return

    created = 0; auto = False
    for s, ops, missing in to_create:
        for env in missing:
            summary = f"{s.summary} (env:{env})"
            env_labels = [f"env:{env}"] + ops
            if not auto:
                click.echo(f"  {s.key} → {summary}")
                r = _confirm_one(f"Créer sous-tâche env:{env} pour {s.key} ?")
                if r == "q": click.echo(f"\n  🌍 {created}/{total_tasks} sous-tâches créées\n"); return
                if r == "n": continue
                if r == "a": auto = True
            key = j.create_subtask(s.key, summary, labels=env_labels)
            if key:
                created += 1
                click.echo(f"    ✅ {key} — {summary}")
            else:
                click.echo(f"    ❌ échec — {summary}")
    click.echo(f"\n  🌍 {created}/{total_tasks} sous-tâches créées\n")


@labels.command("suggest")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--dry-run", is_flag=True, default=False, help="Print JSON of changes, don't apply")
@click.option("--interactive", "-i", is_flag=True, default=False, help="Legacy y/n per-story mode")
@click.pass_context
def labels_suggest(ctx, filter_status, filter_sprint, filter_label, filter_key,
                   filter_summary, filter_assignee, filter_points_min, filter_points_max,
                   dry_run, interactive):
    """All-in-one: cleanup orphan labels + semantic re-tag + conception + derive compounds."""
    from kpi.domain.dimensions import flatten_all, parse_dimensions
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); tagger = SemanticTagger(cfg)
    stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    dims = parse_dimensions(cfg["dimensions"])
    known = {n.label for n in flatten_all(dims)}
    rules = sorted(LABEL_DERIVE_RULES, key=lambda r: -len(r["source"]))

    actions: list[dict] = []  # {story, remove: [], add: []}
    for s in matched:
        sl = set(s.labels)
        remove = [l for l in s.labels if l not in known and not l.startswith("env:")]
        add = []
        # Semantic dimension tags
        for sug in tagger.suggest_labels(s):
            if sug.label not in sl and sug.label not in add:
                add.append(sug.label)
        # Conception tags
        for sug in tagger.suggest_conception(s):
            if sug.label not in sl and sug.label not in add:
                add.append(sug.label)
        # Derive compound labels (including from new adds)
        future_labels = (sl | set(add)) - set(remove)
        for rule in rules:
            if all(l in future_labels for l in rule["source"]):
                for t in rule["target"]:
                    if t not in future_labels and t not in add:
                        add.append(t)
                        future_labels.add(t)
        if remove or add:
            actions.append({"story": s, "remove": remove, "add": add})

    if not actions:
        click.echo("\n  rien a faire - tous les labels sont corrects.\n")
        return

    total_rm = sum(len(a["remove"]) for a in actions)
    total_add = sum(len(a["add"]) for a in actions)
    tot = len(actions)
    click.echo(f"\n  🎯 suggest - {tot} stories, {click.style(f'-{total_rm}', fg='red')} orphelins, {click.style(f'+{total_add}', fg='green')} nouveaux\n")

    # Summary table
    click.echo(f"  {'#':>3}  {'Clé':<14} {'Résumé':<45} {'Labels':}")
    click.echo(f"  {'─'*90}")
    for idx, a in enumerate(actions, 1):
        s = a["story"]
        parts = []
        if a["remove"]:
            parts.append(click.style("-" + " -".join(a["remove"]), fg="red"))
        if a["add"]:
            parts.append(click.style("+" + " +".join(a["add"]), fg="green"))
        lbl_str = "  ".join(parts)
        click.echo(f"  {idx:>3}  {click.style(s.key, bold=True):<14} {s.summary[:45]:<45} {lbl_str}")
    click.echo(f"  {'─'*90}")

    if dry_run:
        import json as _json
        result = [{"key": a["story"].key, "remove": a["remove"], "add": a["add"]} for a in actions]
        click.echo(_json.dumps(result, indent=2, ensure_ascii=False))
        click.echo(f"\n  DRY RUN - retirez --dry-run pour appliquer\n")
        return

    if interactive:
        # Legacy y/n per-story mode
        ok = 0; auto = False
        for idx, a in enumerate(actions, 1):
            s = a["story"]
            if not auto:
                click.echo(f"\n  {'─'*55}")
                click.echo(f"  [{idx}/{tot}] {click.style(s.key, bold=True)} {s.summary[:55]}")
                if a["remove"]:
                    click.echo(f"    {click.style('- ' + ', '.join(a['remove']), fg='red')}")
                if a["add"]:
                    click.echo(f"    {click.style('+ ' + ', '.join(a['add']), fg='green')}")
                r = _confirm_one(f"Appliquer ?")
                if r == "q": break
                if r == "n": continue
                if r == "a": auto = True
            success = True
            if a["remove"]:
                success = j.remove_labels(s.key, a["remove"]) and success
            if a["add"]:
                success = j.add_labels(s.key, a["add"]) and success
            if success:
                ok += 1
                click.echo(f"    {click.style('OK', fg='green')} {s.key}")
        click.echo(f"\n  {ok}/{tot} stories modifiees\n")
        return

    # Batch selection mode (default)
    prompt = click.style("  ? ", fg="cyan", bold=True) + "Selection " + click.style("[all / none / 1,3,5-8 / q]", fg="bright_black")
    sel_text = click.prompt(prompt, default="all", show_default=False).strip()
    if sel_text.lower() in ("q", "quit"):
        click.echo("  annule.\n")
        return
    selected = _parse_selection(sel_text, tot)
    if not selected:
        click.echo("  aucune selection.\n")
        return
    click.echo(f"\n  application de {len(selected)}/{tot} suggestions...")
    ok = 0
    for idx, a in enumerate(actions, 1):
        if idx not in selected:
            continue
        s = a["story"]
        success = True
        if a["remove"]:
            success = j.remove_labels(s.key, a["remove"]) and success
        if a["add"]:
            success = j.add_labels(s.key, a["add"]) and success
        if success:
            ok += 1
            click.echo(f"    {click.style('OK', fg='green')} {s.key}")
        else:
            click.echo(f"    {click.style('FAIL', fg='red')} {s.key}")
    click.echo(f"\n  {ok}/{len(selected)} stories modifiees\n")


@labels.command("suggest-conception")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_suggest_conception(ctx, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max,
                              dry_run):
    """Detect stories needing design work and tag with conception/fonctionnel/technique/tests."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); t = SemanticTagger(cfg)
    stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    # Group suggestions by story
    by_story: dict[str, list] = {}
    for s in matched:
        sugs = t.suggest_conception(s)
        if sugs:
            by_story[s.key] = sugs
    if not by_story:
        click.echo("\n  aucune suggestion de conception trouvée.\n")
        return
    total_labels = sum(len(v) for v in by_story.values())
    click.echo(f"\n  🎯 suggest-conception — {total_labels} labels pour {len(by_story)} stories\n")
    if dry_run:
        for key, sugs in list(by_story.items())[:30]:
            labels_str = ", ".join(f"{s.label}({s.confidence:.0%})" for s in sugs)
            reason = sugs[0].reason if sugs else ""
            click.echo(f"    {key} → {labels_str}")
            click.echo(f"      {sugs[0].story_summary[:70]}")
            click.echo(f"      raison: {reason}")
        if len(by_story) > 30:
            click.echo(f"    ... et {len(by_story) - 30} autres")
        click.echo("\n  DRY RUN — --no-dry-run pour appliquer\n")
        return
    ok_count = 0; auto = False; idx = 0; tot = len(by_story)
    for key, sugs in by_story.items():
        idx += 1
        new_labels = [s.label for s in sugs]
        best_conf = max(s.confidence for s in sugs)
        if not auto:
            _display_story_action(key, sugs[0].story_summary, new_labels, idx, tot, "+", best_conf)
            click.echo(f"    raison: {sugs[0].reason}")
            r = _confirm_one(f"Appliquer ?")
            if r == "q": break
            if r == "n": continue
            if r == "a": auto = True
        if j.add_labels(key, new_labels):
            ok_count += 1
            click.echo(f"    {click.style('OK', fg='green')} {key}: +{new_labels}")
    click.echo(f"\n  {ok_count}/{tot} stories modifiees\n")


# Rules: when a story has ALL source labels, derive target labels
LABEL_DERIVE_RULES = [
    # tests + fonctionnel -> tests-fonctionnels + tests-fonctionnels-automatises
    {"source": ["tests", "fonctionnel"], "target": ["tests-fonctionnels", "tests-fonctionnels-automatises"]},
    # tests + technique -> tests-unitaires + tests-integration
    {"source": ["tests", "technique"], "target": ["tests-unitaires", "tests-integration"]},
    # tests + backend -> tests-unitaires + tests-integration
    {"source": ["tests", "backend"], "target": ["tests-unitaires", "tests-integration"]},
    # tests + auto -> tests-auto
    {"source": ["tests", "auto"], "target": ["tests-auto"]},
    # tests + performance -> tests-performance
    {"source": ["tests", "performance"], "target": ["tests-performance"]},
    # conception + technique -> conception-technique
    {"source": ["conception", "technique"], "target": ["conception-technique"]},
    # conception + fonctionnel -> conception-fonctionnelle
    {"source": ["conception", "fonctionnel"], "target": ["conception-fonctionnelle"]},
]


@labels.command("derive")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_derive(ctx, filter_status, filter_sprint, filter_label, filter_key,
                  filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Derive compound labels from atomic labels (e.g. tests+fonctionnel -> tests-fonctionnels)."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    # Sort rules: longest source first (most specific match first)
    rules = sorted(LABEL_DERIVE_RULES, key=lambda r: -len(r["source"]))
    total_add = 0; affected = 0; auto = False; idx = 0
    to_apply: list[tuple] = []  # (story, labels_to_add)
    for s in matched:
        sl = set(s.labels)
        new_labels = []
        for rule in rules:
            if all(l in sl for l in rule["source"]):
                for t in rule["target"]:
                    if t not in sl and t not in new_labels:
                        new_labels.append(t)
        if new_labels:
            to_apply.append((s, new_labels))
    if not to_apply:
        click.echo("\n  aucun label compose a deriver.\n")
        return
    tot = len(to_apply)
    click.echo(f"\n  🔗 derive - {sum(len(ls) for _, ls in to_apply)} labels pour {tot} stories\n")
    if dry_run:
        for s, new_labels in to_apply[:30]:
            click.echo(f"    {click.style(s.key, bold=True)} {s.summary[:50]}")
            click.echo(f"      existants: {s.labels}")
            click.echo(f"      {click.style('+ ' + ', '.join(new_labels), fg='green')}")
        if tot > 30:
            click.echo(f"    ... et {tot - 30} autres")
        click.echo("\n  DRY RUN - --no-dry-run pour appliquer\n")
        return
    ok = 0
    for s, new_labels in to_apply:
        idx += 1
        if not auto:
            _display_story_action(s.key, s.summary, new_labels, idx, tot, "+")
            click.echo(f"    existants: {s.labels}")
            r = _confirm_one(f"Appliquer ?")
            if r == "q": break
            if r == "n": continue
            if r == "a": auto = True
        if j.add_labels(s.key, new_labels):
            ok += 1
            click.echo(f"    {click.style('OK', fg='green')} {s.key}: +{new_labels}")
    click.echo(f"\n  {ok}/{tot} stories modifiees\n")


@labels.command("check-env")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.pass_context
def labels_check_env(ctx, filter_status, filter_sprint, filter_label, filter_key,
                     filter_summary, filter_assignee, filter_points_min, filter_points_max):
    """Check ops/infra stories for missing environment coverage."""
    from kpi.domain.models import OPS_LABELS, ENV_NAMES
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    ops_labels_str = ", ".join(sorted(OPS_LABELS))
    click.echo(f"\n  🔍 check-env — labels ops: {ops_labels_str}")
    click.echo(f"  envs attendus: {', '.join(ENV_NAMES)}")
    click.echo(f"  {'─'*60}")
    warnings = 0
    for s in matched:
        ops = [l for l in s.labels if l in OPS_LABELS]
        if not ops:
            continue
        existing = [l.split(":", 1)[1] for l in s.labels if l.startswith("env:")]
        missing = [e for e in ENV_NAMES if e not in existing]
        if missing:
            warnings += 1
            click.echo(f"  ⚠️  {s.key} — {s.summary[:50]}")
            click.echo(f"      labels ops: {ops}")
            click.echo(f"      envs: {existing or ['aucun']}  manquants: {missing}")
            click.echo(f"      status: {s.status}  points: {s.story_points}")
    if warnings == 0:
        click.echo("  ✅ Toutes les stories ops/infra ont une couverture env complète.")
    else:
        click.echo(f"\n  ⚠️  {warnings} stories ops/infra sans couverture env complète")
        click.echo("  → utilisez 'kpi labels env <env> -l <ops_label>' pour assigner\n")


@labels.command("list")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--show-stories", is_flag=True, default=False, help="Show individual stories")
@click.pass_context
def labels_list(ctx, filter_status, filter_sprint, filter_label, filter_key,
                filter_summary, filter_assignee, filter_points_min, filter_points_max, show_stories):
    """List all labels with usage counts, optionally filtered."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    label_map: dict[str, list[JiraStory]] = {}
    for s in matched:
        for l in s.labels:
            label_map.setdefault(l, []).append(s)
    unlabeled = [s for s in matched if not s.labels]
    click.echo(f"\n  🏷️  {len(label_map)} labels sur {len(matched)} stories ({len(unlabeled)} sans label)")
    click.echo(f"  {'─'*55}")
    for l in sorted(label_map, key=lambda x: (-len(label_map[x]), x)):
        pts = sum(s.story_points for s in label_map[l])
        click.echo(f"  {l:30s} {len(label_map[l]):4d} stories  {pts:5d} pts")
        if show_stories:
            for s in label_map[l][:10]:
                click.echo(f"      {s.key} — {s.summary[:50]} ({s.status}, {s.story_points}pts)")
            if len(label_map[l]) > 10:
                click.echo(f"      ... et {len(label_map[l]) - 10} autres")
    click.echo()


@labels.command("cleanup")
@click.option("--filter-status", "-s", multiple=True, help="Filter by status (regex)")
@click.option("--filter-sprint", "-S", multiple=True, help="Filter by sprint name (regex)")
@click.option("--filter-label", "-l", multiple=True, help="Filter by existing label (regex)")
@click.option("--filter-key", "-k", multiple=True, help="Filter by issue key (regex)")
@click.option("--filter-summary", "-q", multiple=True, help="Filter by summary text (regex)")
@click.option("--filter-assignee", "-a", multiple=True, help="Filter by assignee (regex)")
@click.option("--filter-points-min", type=int, default=None, help="Min story points")
@click.option("--filter-points-max", type=int, default=None, help="Max story points")
@click.option("--no-dry-run", "dry_run", is_flag=True, flag_value=False, default=True)
@click.pass_context
def labels_cleanup(ctx, filter_status, filter_sprint, filter_label, filter_key,
                   filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Remove labels not defined in config dimensions (keeps env: labels)."""
    from kpi.domain.dimensions import flatten_all, parse_dimensions
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
    # Build set of known labels from dimension tree
    dims = parse_dimensions(cfg["dimensions"])
    known = {n.label for n in flatten_all(dims)}
    # Also keep env: labels and any label starting with a known prefix
    total_rm = 0; affected = 0; auto = False
    orphan_labels: dict[str, int] = {}
    for s in matched:
        to_remove = [l for l in s.labels if l not in known and not l.startswith("env:")]
        if not to_remove:
            continue
        for l in to_remove:
            orphan_labels[l] = orphan_labels.get(l, 0) + 1
        if dry_run:
            affected += 1; total_rm += len(to_remove)
            click.echo(f"    {click.style(s.key, bold=True)} {s.summary[:50]}")
            click.echo(f"      {click.style('orphelins:', fg='red')} {to_remove}")
            click.echo(f"      {click.style('gardes:', fg='green')} {[l for l in s.labels if l not in to_remove]}")
        else:
            if not auto:
                click.echo(f"\n  {'─'*55}")
                click.echo(f"  {click.style(s.key, bold=True)} {s.summary[:50]}")
                click.echo(f"    {click.style('supprimer:', fg='red')} {to_remove}")
                click.echo(f"    {click.style('garder:', fg='green')} {[l for l in s.labels if l not in to_remove]}")
                r = _confirm_one(f"Supprimer {len(to_remove)} labels orphelins de {s.key} ?")
                if r == "q": break
                if r == "n": continue
                if r == "a": auto = True
            j.remove_labels(s.key, to_remove)
            affected += 1; total_rm += len(to_remove)
            click.echo(f"    {click.style('OK', fg='green')} {s.key}: - {to_remove}")
    if orphan_labels:
        click.echo(f"\n  {'─'*55}")
        click.echo(f"  Labels orphelins (pas dans config dimensions) :")
        for l in sorted(orphan_labels, key=lambda x: -orphan_labels[x]):
            click.echo(f"    {click.style(l, fg='red'):30s} {orphan_labels[l]:4d} stories")
    click.echo(f"\n  {'DRY RUN - ' if dry_run else ''}cleanup: {total_rm} labels orphelins sur {affected} stories")
    click.echo(f"  {len(known)} labels reconnus dans config dimensions")
    if dry_run and total_rm > 0:
        click.echo("  --no-dry-run pour appliquer\n")


def _parse_selection(text: str, max_n: int) -> set[int]:
    """Parse selection string like 'all', 'none', '1,3,5-8' into set of ints (1-based)."""
    text = text.strip().lower()
    if text in ("all", "a", "tout", "*"):
        return set(range(1, max_n + 1))
    if text in ("none", "n", "aucun", "0"):
        return set()
    result = set()
    for part in text.split(","):
        part = part.strip()
        if "-" in part:
            bounds = part.split("-", 1)
            try:
                lo, hi = int(bounds[0]), int(bounds[1])
                result.update(range(max(1, lo), min(hi, max_n) + 1))
            except ValueError:
                continue
        else:
            try:
                v = int(part)
                if 1 <= v <= max_n:
                    result.add(v)
            except ValueError:
                continue
    return result


def _confirm_one(msg: str) -> str:
    """Prompt for one action: [y]es / [n]o / [a]ll / [q]uit."""
    while True:
        prompt = click.style("  ? ", fg="cyan", bold=True) + msg + click.style(" [y/n/a/q]", fg="bright_black")
        r = click.prompt(prompt, default="y", show_default=False).strip().lower()
        if r in ("y", "n", "a", "q"):
            return r
        click.echo("    y=oui, n=non, a=tout appliquer, q=quitter")


def _display_story_action(key: str, summary: str, action_labels: list[str],
                          index: int = 0, total: int = 0, action: str = "+",
                          confidence: float | None = None):
    """Display formatted story info before confirmation prompt."""
    counter = f"[{index}/{total}] " if total > 0 else ""
    click.echo(f"\n  {'─'*55}")
    click.echo(f"  {click.style(counter + key, bold=True)} {summary[:60]}")
    if action == "+":
        labels_str = "  ".join(click.style(f"+{l}", fg="green") for l in action_labels)
    else:
        labels_str = "  ".join(click.style(f"-{l}", fg="red") for l in action_labels)
    click.echo(f"    {labels_str}")
    if confidence is not None:
        pct = int(confidence * 100)
        color = "green" if pct >= 70 else "yellow" if pct >= 50 else "red"
        click.echo(f"    confiance: {click.style(f'{pct}%', fg=color)}")


def _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                    filter_summary, filter_assignee, filter_points_min, filter_points_max):
    """Apply regex filters to story list. All filters are AND-combined."""
    result = stories
    for pat in filter_status:
        rx = re.compile(pat, re.I)
        result = [s for s in result if rx.search(s.status)]
    for pat in filter_sprint:
        rx = re.compile(pat, re.I)
        result = [s for s in result if rx.search(s.sprint or "")]
    for pat in filter_label:
        rx = re.compile(pat, re.I)
        result = [s for s in result if any(rx.search(l) for l in s.labels)]
    for pat in filter_key:
        rx = re.compile(pat, re.I)
        result = [s for s in result if rx.search(s.key)]
    for pat in filter_summary:
        rx = re.compile(pat, re.I)
        result = [s for s in result if rx.search(s.summary)]
    for pat in filter_assignee:
        rx = re.compile(pat, re.I)
        result = [s for s in result if rx.search(s.assignee or "")]
    if filter_points_min is not None:
        result = [s for s in result if s.story_points >= filter_points_min]
    if filter_points_max is not None:
        result = [s for s in result if s.story_points <= filter_points_max]
    return result


main.add_command(labels)


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


@main.command("debug-sprints")
@click.pass_context
def debug_sprints(ctx):
    """Show Jira boards and sprints for diagnostics."""
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg)
    boards = j.debug_boards()
    click.echo(f"\n{'='*60}\n  boards Jira pour {j._project} - {len(boards)} trouvés\n{'='*60}")
    if not boards:
        click.echo("  ⚠️  Aucun board trouvé. Le projet n'a pas de board Scrum/Kanban.")
        click.echo("     Verifiez dans Jira: Projet > Board > Settings")
        click.echo()
        return
    for b in boards:
        err = b.get("sprint_error", "")
        sprint_info = f"{b['sprint_total']} sprints" if b["sprint_total"] >= 0 else f"erreur: {err}"
        click.echo(f"  📋 id={b['id']} {b['name']:30s} type={b['type']:10s} {sprint_info}")
    # Show actual sprints
    sprints = j.fetch_sprints()
    click.echo(f"\n  {'─'*50}")
    click.echo(f"  sprints recuperes: {len(sprints)}")
    click.echo(f"  {'─'*50}")
    for sp in sprints:
        state_icon = {"active": "🟢", "closed": "✅", "future": "⏳"}.get(sp["state"], "❓")
        dates = f"{sp['start_date']} → {sp['end_date']}" if sp["start_date"] else "pas de dates"
        click.echo(f"  {state_icon} Sprint {sp['number']:2d} {sp['name']:25s} {sp['state']:8s} {dates}")
    if not sprints:
        click.echo("  ⚠️  Aucun sprint. Le board n'a peut-etre pas de sprints configures.")
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


@main.command()
@click.option("--stories", default=300, help="Number of stories to generate")
@click.option("--noise", default=0.35, help="Noise ratio (0.0-1.0)")
@click.option("--seed", default=42, help="Random seed for reproducibility")
@click.option("-o", "--output", default="data/mock.json", help="Output JSON file")
@click.pass_context
def mock(ctx, stories, noise, seed, output):
    """Generate mock Jira data with realistic imperfections."""
    from kpi.services.mock import MockGenerator
    cfg = ctx.obj["cfg"]
    gen = MockGenerator(cfg, seed=seed)
    data = gen.generate(count=stories, noise=noise)
    vels = gen.generate_velocities(data)
    p = Path(output); p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(gen.to_json(data), encoding="utf-8")
    done = sum(1 for s in data if s.status in {"done", "delivered"})
    noisy = sum(1 for s in data if not s.labels or s.story_points == 0)
    click.echo(f"\n  🎲 {len(data)} stories generees (seed={seed}, noise={noise})")
    click.echo(f"  ✅ {done} done | 📊 {sum(s.story_points for s in data)} pts | ⚡ {len(vels)} sprints")
    click.echo(f"  🔧 ~{noisy} imperfections")
    click.echo(f"  💾 {p}\n")


@main.command()
@click.option("--stories", default=300, help="Number of mock stories")
@click.option("--noise", default=0.35, help="Noise ratio (0.0-1.0)")
@click.option("--seed", default=42, help="Random seed")
@click.pass_context
def demo(ctx, stories, noise, seed):
    """Generate mock data and produce both HTML reports (no Jira needed)."""
    from kpi.services.mock import MockGenerator
    cfg = ctx.obj["cfg"]
    gen = MockGenerator(cfg, seed=seed)
    data = gen.generate(count=stories, noise=noise)
    vels = gen.generate_velocities(data)
    untag = [s for s in data if not s.labels]

    calc = KPICalculator(cfg); store = SnapshotStore(cfg)
    sn = cfg.get("project", {}).get("current_sprint", 1)
    prev = store.load_previous_sprint(sn)
    r = calc.compute(data, vels, untag, prev)

    click.echo(f"\n  🎲 {len(data)} mock stories (seed={seed}, noise={noise})")
    _show(r)

    rr = ReportRenderer()
    p1 = Path("kpi_date_demo.html")
    p1.write_text(rr.render_date(r), encoding="utf-8")
    p2 = Path("kpi_project_demo.html")
    p2.write_text(rr.render_project(r), encoding="utf-8")
    click.echo(f"  📄 {p1}")
    click.echo(f"  📄 {p2}")
    try:
        import webbrowser
        webbrowser.open(p1.resolve().as_uri())
        webbrowser.open(p2.resolve().as_uri())
    except: pass

if __name__ == "__main__": main()
