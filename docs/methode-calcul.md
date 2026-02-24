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

## Météo temps-relative

- La météo s'ajuste en fonction de l'avancement dans le temps du projet
- `ratio_relatif = avancement / (semaines_écoulées / durée_totale_projet)`
- 22% d'avancement à 40% du projet → ratio relatif ~55% → ⛅ vert clair
- Seuils : ☀️ ≥80% | ⛅ ≥60% | 🌥️ ≥40% | 🌧️ ≥20% | ⛈️ <20%

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

## Variations

- Comparaison avec le snapshot précédent (TinyDB)
- Deltas en points et en pourcentage
