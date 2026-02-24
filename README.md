# KPI Generator v7

Jira → Auto-tagging → KPI → Preview HTML / Confluence → TinyDB Archive

## Quick Start

```bash
poetry install
cp .env.example .env  # renseigner JIRA_URL, JIRA_TOKEN, CONFLUENCE_URL, CONFLUENCE_TOKEN

# 1. Vérifier les statuts Jira (et leur mapping)
poetry run kpi debug-statuses

# 2. Migrer les anciens labels (colon → mot unique)
poetry run kpi migrate-labels          # dry run
poetry run kpi migrate-labels --no-dry-run

# 3. Purger les labels contenant un caractère (ex: ':')
poetry run kpi purge-labels                          # dry run, par défaut ':'
poetry run kpi purge-labels --pattern "_"            # dry run, pattern '_'
poetry run kpi purge-labels --no-dry-run             # applique

# 4. Tagger les stories
poetry run kpi tag                     # dry run
poetry run kpi tag --no-dry-run

# 5. Preview (ouvre le navigateur, ne publie pas)
poetry run kpi preview

# 6. Publier sur Confluence + sauver snapshot
poetry run kpi generate

# 7. Sauver un snapshot sans publier
poetry run kpi snapshot

# 8. Comparer deux dates
poetry run kpi compare 2026-01-15 2026-02-20
```

## Fonctionnalités

### Labels = un seul mot
- `referentiels`, `ventilation`, `tests-unitaires` — plus de `:`, plus de `_`
- `migrate-labels` : supprime les anciens labels et retag

### 3 domaines de niveau 1
- **Fonctionnel** : référentiels, campagnes, enquêtes, annuaire, écran d'accueil, conception fonctionnelle
- **Technique** : conception technique, design/UX, développement (back/front), ops, devops, qualité, perf, observabilité, sécurité
- **Organisationnel** : pilotage (tableaux de bord, suivi), habilitations, documentation (tech/utilisateur/formation)

### Stories non estimées
- Les stories à 0 SP, non planifiées (pas de sprint), et non terminées ajoutent **+13 pts** chacune au reste à faire (RAF)
- Configurable via `unestimated_default_points` dans config.yaml

### Purge de labels
- `purge-labels` : supprime les labels contenant un pattern (`:` par défaut) sans toucher aux autres

### Multi-dimension
- Une story peut avoir `conception-technique` ET `backend` → apparaît dans les deux branches
- Le parent déduplique les stories enfants

### Statuts inconnus → done si > 21 jours
- `unknown_status_done_after_days: 21` dans config.yaml

### Vélocité en pts/semaine
- Sprint 3 semaines → on divise par 3
- Prorata temporis configurable (`prorata_current_sprint: true`)

### Dashboard 3 lignes
- 🎯 Story points : total / livrés (+prorata) / restants / projeté
- 📊 Synthèse : % avancement / vélocité moy. / vélocité requise / statut
- Deltas en % vs snapshot précédent

### Sprint timeline
- Barre visuelle des sprints (passés vert, courant bleu, futurs gris)
- Calculée depuis `start_date` / `end_date` / `sprint_duration_weeks`

### TinyDB
- Snapshots dans `data/kpi.json`
- `snapshot` : sauve l'état courant
- `compare DATE_A DATE_B` : compare deux dates

### Est. projet
- Colonne "estimation projet" via `domain_weight` dans config.yaml
- Parents sans poids agrègent les enfants

## Architecture

```
config.yaml                          # dimensions, status mapping, domain_weight, sprints
data/kpi.json                        # TinyDB snapshots
src/kpi/
  adapters/
    jira_adapter.py                  # fetch, labels, velocity, age-based status fallback
    confluence_adapter.py            # publish pages
    network.py                       # SSL, proxy
  domain/
    models.py                        # pydantic v2, int story_points, SprintInfo
    dimensions.py                    # parse config → DimensionNode tree
  services/
    calculator.py                    # KPIs, velocity/week, prorata, multi-dim
    dates.py                         # sprint timeline, weeks_elapsed, days_since
    tagger.py                        # keyword matching → single-word labels
    store.py                         # TinyDB snapshot persistence
    renderer.py                      # jinja2 → HTML
  config/
    loader.py                        # YAML + env
  templates/
    kpi_preview.html                 # JS vanille, fold/unfold, story drawers
    kpi_confluence.html.j2           # Confluence storage format
  cli.py                             # 8 commands
tests/
  test_all.py                        # 43 tests (standalone, no network)
```
