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
        avg_velocity_per_week=r.raf.avg_velocity_per_week if r.raf else 0,
        score_global=r.score_global_project,
        score_global_date=r.score_global_date,
        score_global_project=r.score_global_project,
        tag_scores={ts.label: ts.score for ts in r.tag_scores if ts.total_points > 0},
        backlog_variation=r.backlog_stability.variation_project if r.backlog_stability else 0.0))

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
    total_rm = 0; affected = 0
    for s in stories:
        to_remove = [l for l in s.labels if match(l)]
        if not to_remove: continue
        affected += 1; total_rm += len(to_remove)
        keep = [l for l in s.labels if not match(l)]
        if dry_run:
            click.echo(f"  {s.key}: ✗ {to_remove}  (garde: {keep})")
        else:
            j.remove_labels(s.key, to_remove)
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
    for s in to_add[:30]:
        click.echo(f"    {'DRY' if dry_run else '  ✅'} {s.key} — {s.summary[:60]}")
    if len(to_add) > 30: click.echo(f"    ... et {len(to_add) - 30} autres")
    if dry_run and to_add:
        click.echo("  --no-dry-run pour appliquer\n"); return
    ok = sum(1 for s in to_add if j.add_labels(s.key, [label]))
    click.echo(f"  ✅ {ok}/{len(to_add)} modifiées\n")


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
    total_rm = 0; affected = 0
    for s in matched:
        to_remove = [l for l in s.labels if pat.search(l)]
        if not to_remove: continue
        affected += 1; total_rm += len(to_remove)
        if dry_run:
            click.echo(f"    DRY {s.key}: ✗ {to_remove}")
        else:
            j.remove_labels(s.key, to_remove)
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
    count = 0
    for s in matched:
        to_remove = [l for l in s.labels if pat.search(l)]
        if not to_remove: continue
        count += 1
        if dry_run:
            click.echo(f"    DRY {s.key}: {to_remove} → {new_label}")
        else:
            j.remove_labels(s.key, to_remove)
            if new_label not in s.labels:
                j.add_labels(s.key, [new_label])
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
    changed = 0; skipped = 0
    for s in matched:
        old_envs = [l for l in s.labels if l.startswith("env:")]
        if old_envs == [new_label]:
            skipped += 1; continue
        changed += 1
        if dry_run:
            if old_envs:
                click.echo(f"    DRY {s.key}: {old_envs} → {new_label} — {s.summary[:50]}")
            else:
                click.echo(f"    DRY {s.key}: + {new_label} — {s.summary[:50]}")
        else:
            if old_envs:
                j.remove_labels(s.key, old_envs)
            j.add_labels(s.key, [new_label])
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
    removed = 0
    for s in matched:
        old_envs = [l for l in s.labels if l.startswith("env:")]
        if not old_envs: continue
        removed += 1
        if dry_run:
            click.echo(f"    DRY {s.key}: ✗ {old_envs} — {s.summary[:50]}")
        else:
            j.remove_labels(s.key, old_envs)
            click.echo(f"    ✅  {s.key}: ✗ {old_envs}")
    click.echo(f"\n  🌍 clear-env — {removed} stories avec env: label")
    if dry_run and removed > 0:
        click.echo("  --no-dry-run pour appliquer\n")


@labels.command("expand-env")
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
def labels_expand_env(ctx, filter_status, filter_sprint, filter_label, filter_key,
                      filter_summary, filter_assignee, filter_points_min, filter_points_max, dry_run):
    """Create subtasks per environment for ops/infra stories.

    Detects stories with ops labels (ops, devops, deploiement, infrastructure,
    observabilite, logging, spans, metriques) and creates a Jira subtask per
    missing environment (dev, recette, preprod, prod). Shows source story
    details and asks for confirmation before creating.
    """
    from kpi.domain.models import OPS_LABELS, ENV_NAMES
    cfg = ctx.obj["cfg"]
    j = JiraAdapter(cfg); stories = j.fetch_all_stories()
    matched = _filter_stories(stories, filter_status, filter_sprint, filter_label, filter_key,
                              filter_summary, filter_assignee, filter_points_min, filter_points_max)
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
                if f"[{env}]" in child.summary.lower() or f"({env})" in child.summary.lower():
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

    if not click.confirm(f"\n  Créer {total_tasks} sous-tâches dans Jira ?"):
        click.echo("  Annulé.\n")
        return

    created = 0
    for s, ops, missing in to_create:
        for env in missing:
            summary = f"[{env.upper()}] {s.summary}"
            env_labels = [f"env:{env}"] + ops
            key = j.create_subtask(s.key, summary, labels=env_labels)
            if key:
                created += 1
                click.echo(f"    ✅ {key} — {summary}")
            else:
                click.echo(f"    ❌ échec — {summary}")
    click.echo(f"\n  🌍 {created}/{total_tasks} sous-tâches créées\n")


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
