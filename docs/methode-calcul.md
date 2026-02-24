# Méthode de calcul des KPI

## Source de données

Les données proviennent de **Jira** : toutes les **user stories** du projet, avec leurs **story points**, **statuts** et **labels**.

## Statuts des stories

Chaque story Jira est mappée vers un statut interne :

| Statut interne | Exemples Jira |
|---|---|
| **backlog** | Nouveau, Ouvert |
| **specification** | Rédigée, Affinage |
| **todo** | Prêt, À faire |
| **in-progress** | En cours, En développement |
| **review** | Revue de code |
| **testing** | Recette, En test |
| **blocked** | Bloqué, En attente |
| **done** | Terminé, Fermé, Résolu |
| **delivered** | Livré, En production |
| **abandoned** | Abandonné, Annulé |

Les stories **abandonnées** sont exclues de tous les calculs.

Les stories avec un statut Jira inconnu et créées depuis plus de 21 jours sont automatiquement considérées comme "done".

## Calcul global

```
points_terminés = Σ story_points (stories done + delivered)
points_prorata  = Σ story_points (stories actives) × (semaine_courante / durée_sprint)
points_effectifs = points_terminés + points_prorata
avancement_global = points_effectifs / total_points
```

Le **prorata temporis** crédite partiellement les stories en cours (in-progress, review, testing) selon l'avancement dans le sprint courant. Exemple : un sprint de 3 semaines, semaine 2 → les stories actives comptent pour 2/3 de leurs points.

## Calcul par dimension

Le projet est organisé en **3 domaines** (Fonctionnel, Technique, Organisationnel), chacun subdivisé en sous-dimensions sur 3 niveaux. Chaque story est rattachée à une ou plusieurs dimensions via ses **labels Jira**.

Pour chaque dimension :

```
points_faits      = terminés + prorata (dans cette dimension)
restant_estimé    = max(projection_restante, backlog_concret, raf_minimum)
avancement        = points_faits / (points_faits + restant_estimé)
```

Où :
- **projection_restante** = estimation_projet × poids − points_faits
- **backlog_concret** = stories en backlog + spécification + todo + bloquées
- **raf_minimum** = vélocité_moyenne × semaines_restantes × poids × 0.1 (garantit qu'aucune dimension n'affiche 100% tant qu'il reste du travail)

Les **poids par domaine** (`domain_weight` dans config.yaml) permettent d'estimer le total de points attendu pour chaque dimension.

## Stories non estimées

Les stories sans story points (0 SP), non terminées, non en cours, et non planifiées (pas de sprint) représentent du travail caché. Pour chacune, on ajoute un forfait de **13 points** au reste à faire global (RAF).

```
stories_non_estimées = stories avec 0 SP, pas done/active, pas de sprint
padding              = nombre × 13 (configurable: unestimated_default_points)
RAF_total            = RAF_calculé + padding
```

Ce mécanisme évite de sous-estimer le travail restant quand le backlog contient des stories non chiffrées.

## Vélocité

La vélocité est calculée **par semaine** (pas par sprint) :

```
vélocité_sprint = points_livrés_sprint / durée_sprint_en_semaines
vélocité_moyenne = moyenne(vélocité de chaque sprint clos)
```

## Projection (RAF)

```
points_projetés = points_effectifs + (vélocité_moyenne × semaines_restantes)
vélocité_requise = points_restants / semaines_restantes
en_bonne_voie = vélocité_moyenne >= vélocité_requise
```

## Météo

L'avancement est traduit en icône météo :

| Icône | Seuil |
|---|---|
| ☀️ Ensoleillé | ≥ 80% |
| ⛅ Partiellement couvert | ≥ 60% |
| 🌥️ Couvert | ≥ 40% |
| 🌧️ Pluvieux | ≥ 20% |
| ⛈️ Orageux | < 20% |

## Variations

Chaque rapport compare les valeurs actuelles avec le **snapshot précédent** (stocké en TinyDB) et affiche les deltas en points et en pourcentage.
