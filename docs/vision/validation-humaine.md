# La validation humaine : une boucle qui fait grandir le jeu de données

*Conception — 21 octobre 2026. Prolonge [le laboratoire d'essais](banc-d-essai-ml.md). Rien de ce document n'est encore construit.*

## 1. Le problème qu'on résout

Onze essais le montrent : aucune configuration ne reconnaît la classe « 1 place ». Deux explications restent possibles, et aucun réglage ne les départage :

- les images « 1 place » sont **trop peu nombreuses ou trop fines** à voir ;
- leurs **étiquettes sont incertaines** : une même scène étiquetée « 1 » par l'un, « 0 » ou « 2 » par l'autre.

Seul un regard humain, organisé, tranche. Et ce regard doit **rester** : chaque décision enrichit le jeu, sert au réentraînement, et mesure la qualité des étiquettes elles-mêmes.

L'outil qui a créé les datasets (une application d'annotation, saisie d'août-septembre 2026) a disparu avec son pod. On en garde le **modèle de données** : un fichier `.gpkg` par collection et par ville (`panoramax_classif.gpkg`) avec `id_picture`, `id_collection`, `url` Panoramax, `cote`, `n_places`, `forme`, `path`, `user`, `created_time`. L'interface se refait, ce format se conserve.

## 2. La boucle

1. **Choisir** quoi faire valider (files, §4).
2. **Valider** vite et sans ambiguïté (écrans, §3).
3. **Journaliser** chaque décision, jamais en écrasant (§5).
4. **Reconstruire** une variante avec les décisions (le laboratoire sait déjà le faire : `corrections.csv`).
5. **Réentraîner, mesurer, comparer** au modèle en place, sur un jeu de référence que la validation ne touche pas (§6).
6. **Reboucler** : le nouveau modèle propose de nouvelles files.

## 3. Les écrans

Tout se fait **au clavier** (un téléphone ou une tablette marchent avec de gros boutons).

**Écran unitaire (le cœur).**
- L'image en grand, **le rognage que voit le modèle** en vignette à côté (bascule : image entière).
- L'étiquette actuelle, la prédiction du modèle et sa confiance — **cachées sur demande** : en validation « à l'aveugle », on ne les montre pas.
- **Le contexte** : les deux images voisines de la même séquence Panoramax (précédente, suivante) et un mini-plan (la géométrie est dans le `.gpkg`). Une place de stationnement se juge mieux en voyant la rue.
- Touches : `0` `1` `2` `3+` la classe ; `Espace` confirme l'étiquette actuelle ; `D` douteuse (image inexploitable) ; `←` `→` naviguer ; `Z` annuler ; `?` aide. Un champ note, facultatif.
- Le côté (droite/gauche) et la forme (bataille/longitudinal) se valident au même écran.

**Grille de triage (pour la masse).** 24 vignettes de la **même** étiquette ; on clique les intruses, le reste est confirmé d'un coup. C'est ce qui rend raisonnable la validation des milliers d'images « 0 ».

**Journal et équipe.** Qui a validé quoi, quand, à quelle vitesse, avec quel taux de désaccord. Un tableau de bord de la boucle : décisions par jour, étiquettes corrigées par classe, rappel de la classe « 1 » dans le temps.

## 4. Les files (ce qu'on montre, dans quel ordre)

| File | Pourquoi |
|---|---|
| **Audit de la classe « 1 »** : toutes les images « 1 » + un tirage de « 0 » et « 2 » | Premier lot, valeur immédiate : dit si le problème vient des étiquettes |
| **Erreurs du modèle** sur la validation | Voir ce qu'il rate, et si c'est lui ou l'étiquette qui a tort |
| **Incertitudes** : faible écart entre les deux classes les plus probables | Les images les plus utiles à apprendre |
| **Désaccords** entre modèles ou entre graines | Cas difficiles |
| **Tirage au hasard** (≈ 10 % de chaque session) | Évite le biais d'une file faite que d'erreurs ; sert d'étalonnage |
| **Nouvelles images** de Panoramax | Fait grandir le jeu |

Un cas ambigu passe à un **deuxième validateur qui ne voit pas la décision du premier** ; s'ils divergent, un arbitre tranche.

## 5. Les données

Chaque décision est une ligne **jamais modifiée** : image, valideur, date, décision, ancienne étiquette, file d'origine, version du modèle qui a proposé, temps passé, note. Un journal SQLite (dans le registre du laboratoire) fait foi ; on en tire à volonté :
- `corrections.csv` (déjà lu par les recettes) ;
- les `.gpkg` avec `user` et `created_time`, au format d'origine ;
- les statistiques (accord entre validateurs, taux de correction par classe).

Les nouvelles images arrivent par **lots datés** dans le brut (le brut d'origine n'est jamais touché), avec l'`url` Panoramax et les mêmes colonnes.

## 6. Les garde-fous (sans eux, on se ment)

- **Fuite** : une image choisie parce que le modèle s'y trompe n'entre **jamais** dans le jeu de test. Un **jeu de référence figé**, validé par deux personnes, ne sert qu'à mesurer ; la validation ne le modifie pas.
- **Biais** : jamais une file faite uniquement d'erreurs (tirage au hasard mêlé).
- **Qualité des étiquettes** : on mesure l'accord entre validateurs, pas seulement la vitesse. Une classe où les humains divergent n'a pas de « vérité » à apprendre : on la redéfinit (par exemple en fusionnant « 1 » et « 2 »).
- **Promotion** d'un modèle réentraîné : seulement si le gain dépasse le bruit, par comparaison appariée sur le jeu de référence.
- **Traçabilité** : chaque modèle dit de quelles validations il vient.

## 7. Où ça vit

Dans le **laboratoire** (même service, même jeton, même page), onglets **Valider**, **Files**, **Équipe**. Pas de second outil à maintenir. Les routes sont les mêmes pour la personne, l'agent et l'Assistant :
`GET /api/validation/file?type=…` · `POST /api/validation/decisions` · `GET /api/validation/stats`.

## 8. Les lots

| Lot | Contenu | Ce que ça apporte |
|---|---|---|
| **V1** | Journal des décisions, écran unitaire au clavier, file « audit de la classe 1 », export `corrections.csv` | Savoir si le problème vient des étiquettes |
| **V2** | Prédictions du modèle sur tout le brut, files erreurs/incertitudes, grille de triage | La masse devient vérifiable |
| **V3** | Deuxième validateur à l'aveugle, accord, jeu de référence figé | Une mesure fiable |
| **V4** | Lots d'images Panoramax, réentraînement déclenché, promotion | La boucle tourne |
| **V5** | Export `.gpkg` au format d'origine, tableau de bord de la boucle | La boucle se pilote |

## 9. Ce qu'on ne sait pas encore

- **Combien de validateurs**, et sous quels noms : un seul (vous) ou plusieurs ?
- **La définition de « 1 place »** : une place seule, ou « moins de 2 » ? C'est la première chose à fixer avant d'étiqueter davantage.
- **Panoramax** : l'accès aux images par `url` depuis le pod GPU n'est pas vérifié.
