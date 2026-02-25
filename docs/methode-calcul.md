# Méthode de calcul des KPI

## Source de données

- Données Jira : user stories + tasks liées (via `parent` ou `issuelinks`)
- Tasks orphelines ignorées
- Stories abandonnées exclues de tous les calculs

## Statuts

| Statut | Exemples Jira |
|---|---|
| backlog | Nouveau, Ouvert |
| specification | Rédigée, Affinage |
| todo | Prêt, À faire |
| in-progress | En cours |
| review | Revue de code |
| testing | Recette, En test |
| blocked | Bloqué |
| done | Terminé, Fermé |
| delivered | Livré |
| abandoned | Abandonné |

- Statut Jira inconnu + créé depuis > 21 jours → auto-done

## Prorata temporis (crédit partiel)

- **in-progress** : 25% des story points comptés comme effectifs
- **review** : 75% des story points comptés comme effectifs
- **testing** : 50% des story points comptés comme effectifs
- `effective_done = done + prorata`

## Avancement global

- `avancement = effective_done / total_points`
- Inclut le prorata des stories actives

## Bannière Échéance

Chaque rapport affiche en haut une bannière avec :
- **Date de début** (`project.start_date`)
- **Barre de progression temporelle** : % du temps écoulé (vert ≥80%, orange ≥50%, rouge <50%)
- **Date d'échéance** (`project.end_date`) avec le nombre de jours restants
- Couleur de l'échéance : rouge si ≤30j, orange si ≤90j, neutre sinon

Formule : `time_progress = semaines_écoulées / (semaines_écoulées + semaines_restantes)`

## Météo temps-relative

La météo s'ajuste en fonction de l'avancement **relatif au temps écoulé** du projet.

**Formule :** `ratio_relatif = avancement / time_progress`

**Exemple :** 22% d'avancement à 40% du projet → ratio relatif ~55% → ⛅

### Règles météo (configurable dans `config.yaml` → `kpi.weather`)

| Icône | Seuil (ratio_relatif) | Signification |
|---|---|---|
| ☀️ Sunny | ≥ 0.80 | En avance ou dans les temps |
| ⛅ Partly Cloudy | ≥ 0.60 | Légèrement en retard |
| 🌥️ Cloudy | ≥ 0.40 | En retard modéré |
| 🌧️ Rainy | ≥ 0.20 | En retard significatif |
| ⛈️ Stormy | < 0.20 | Retard critique |

**Exemples pédagogiques :**
- 80% d'avancement à 80% du projet → ratio 1.0 → ☀️ (dans les temps)
- 30% d'avancement à 50% du projet → ratio 0.6 → ⛅ (légèrement en retard)
- 10% d'avancement à 60% du projet → ratio 0.17 → ⛈️ (retard critique)

## Couleurs des barres de progression

### Barres d'avancement (% réalisé)

| Couleur | Seuil | Code hex |
|---|---|---|
| Vert | ratio ≥ 0.80 | #36B37E |
| Orange | ratio ≥ 0.50 | #FF991F |
| Rouge | ratio < 0.50 | #DE350B |

### Barres temps-relatif (vs objectif)

| Couleur | Seuil | Code hex |
|---|---|---|
| Vert | time_relative ≥ 1.0 | #36B37E |
| Orange | time_relative ≥ 0.70 | #FF991F |
| Rouge | time_relative < 0.70 | #DE350B |

## Avancement par dimension

- Deux colonnes : **% réalisé** (brut) + **vs objectif** (relatif au temps)
- `% réalisé = effective_done / (effective_done + restant)`
- `vs objectif = % réalisé / avancement_temporel` (>100% = en avance)
- Micro-jitter déterministe ±2% par dimension pour affichage naturel
- Restant estimé = max(projection, backlog concret, RAF minimum)
- RAF minimum = vélocité × semaines restantes × poids × 0.1

## Stories non estimées

- Stories à 0 SP, pas terminées, pas en cours, pas planifiées
- Forfait : **3 pts** par story (configurable)
- **Cappé à 50%** du total connu pour éviter les chiffres absurdes
- `padding = min(nb_stories × 3, total_pts × 0.5)`

## Restant estimé global

- `raw_remaining = max(total - effective_done, backlog) + padding`
- **Marge +15%** : `restant_estimé = raw_remaining × 1.15`
- Cohérent avec la projection

## Vélocité

- Par semaine : `pts_livrés / durée_sprint_semaines`
- Par sprint : `vélocité/sem × durée_sprint`
- Sans sprints clos : `effective_done / semaines_écoulées`

## Projection

- `projeté = effective_done + restant_estimé` (cohérent, même champ)
- `besoin/sem = restant_estimé / semaines_restantes`
- En bonne voie si `vélocité × semaines_restantes ≥ restant_estimé`

## Paramètres

| Paramètre | Défaut | Description |
|---|---|---|
| `unestimated_default_points` | 3 | Forfait par story non estimée |
| `unestimated_max_ratio` | 0.5 | Cap du padding (ratio du total) |
| `projection_margin` | 0.15 | Marge d'erreur (+15%) |
| `sprint_duration_weeks` | 3 | Durée sprint en semaines |
| `PROJECT_NAME` (env) | — | Nom du projet (surcharge config) |

## Score projet à date

Mesure l'avancement structurel pondéré des livrables planifiés jusqu'au sprint courant.

**Formule brute :**
- `score_brut = Σ(tag_score × poids_dim) / Σ(poids_dim)`

**Amortissement temps-proportionnel :**
- `amortissement = max(0, (1 - time_progress) × 0.3)`
- `score_date = score_brut × (1 - amortissement)`

L'amortissement réduit le score de **jusqu'à 30%** en début de projet, proportionnellement au temps restant. Cela empêche un score de 100% en milieu de projet tout en restant réaliste (>70% quand tous les sprints réalisés sont complets).

**Exemples :**

| time_progress | amortissement | score_brut | score_date |
|---|---|---|---|
| 20% | 24% | 100% | 76% |
| 40% | 18% | 100% | 82% |
| 60% | 12% | 100% | 88% |
| 80% | 6% | 100% | 94% |
| 100% | 0% | 100% | 100% |

En fin de projet (`time_progress → 1.0`), l'amortissement disparaît et le score reflète l'avancement brut.

## Variations

- Comparaison avec le snapshot précédent (TinyDB)
- Deltas en points et en pourcentage
