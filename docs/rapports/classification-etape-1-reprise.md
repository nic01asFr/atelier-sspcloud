# Classification d'images de stationnement — reprise du 28/10 après audit

> 28/10/2026. **Ce document remplace les résultats du [rapport du 23/10](classification-etape-1.md)**, que l'audit ci-dessous a invalidés en partie.
> Les huit modèles à restituer, avec leurs fichiers et leurs mesures : [`classification-livrable.md`](classification-livrable.md).
> Tous les chiffres sont des mesures de **validation**. Le jeu de test scellé n'a pas été ouvert (0 consultation).

## 1. Ce que l'audit a trouvé

| # | Constat | Gravité | Ce que cela change |
|---|---|---|---|
| 1 | **Fuite de données.** Des images identiques d'octet à octet se trouvaient dans le train *et* dans la validation : 21 des 57 images de validation de « non panoramique droit, nombre » (37 %), 7 sur 10 pour « non panoramique droit, forme ». La même photo est rangée sous plusieurs routes du brut (`MEYLAN/22708/…`, `MEYLAN/1 (poches)/…`) ; le contrôle de groupe ne regardait que les noms. | grave | Les essais E0015, E0019, E0021, E0022 étaient surévalués : c'est le groupe qui paraissait réussir (95 % d'exactitude). |
| 2 | **Les 750 photos non panoramiques ne viennent que de 3 enregistrements.** Même sans doublon exact, validation et test viennent des mêmes prises de vue que le train. | moyen | Limite des données, à garder en tête pour les groupes « non panoramique ». |
| 3 | **Trois étiquettes avaient été corrigées** (vos décisions de validation du 21/10) dans les jeux de la consigne, alors que le rapport disait « telles quelles ». | moyen | Les nouveaux jeux sont construits **sans** correction (`corrections: false`) : les données du zip sont prises telles quelles. |
| 4 | **Recadrage central.** À 64 × 64, ultralytics redimensionne le petit côté puis recadre au centre : un tiers de la largeur des panoramiques, un quart de celle des photos, est perdu à l'évaluation, alors que l'entraînement voit l'image entière. | moyen | Vérifié dans le code d'ultralytics 8.4.182. Mesuré ci-dessous : pas d'effet systématique sur les résultats. |
| 5 | **Fourchettes peu solides.** Les « fourchettes » du rapport du 23/10 reposent sur 2 à 5 collections de validation. | moyen | Elles ne sont plus reprises. On donne la moyenne et l'écart sur 3 graines. |
| 6 | **Un entraînement n'est pas reproductible.** Les essais E0008 et E0012, de même configuration et de même graine, donnent 0,576 et 0,635. | moyen | Un seul entraînement ne départage pas deux modèles proches : d'où 3 graines. |
| 7 | **Les modèles « nombre » et « forme » d'un même groupe n'ont pas les mêmes lots.** | mineur | Aucune fuite dans un modèle, mais on ne peut pas les enchaîner sans refaire un découpage commun. |
| 8 | Les effectifs du rapport du 23/10 différaient de ceux des données (conséquence du point 3) ; la graine de découpage (7) n'était pas indiquée. | mineur | Corrigé ici. |

## 2. Ce qui a été fait

- **Laboratoire** (PR #81) : contrôle bloquant `fuite_contenu` (même image sous deux noms dans deux lots) ; avertissement `enregistrement_partage` ; options de recette `regroupement` (`route`, `contenu`, `enregistrement`), `dedoublonner` (un seul exemplaire par image ; si les étiquettes se contredisent, tous écartés) et `taille` (réduction carrée explicite, sans recadrage).
- **Regroupement retenu** : par **enregistrement** (fusionné par contenu) pour les panoramiques (21 à 22 enregistrements) ; par **contenu** pour les photos non panoramiques (3 enregistrements seulement : un découpage par enregistrement est impossible).
- **16 jeux reconstruits** : les 8 groupes de la consigne, en variante **A** (réduction à 64 × 64 écrite sur disque) et **L** (à la lettre : le modèle réduit lui-même). Vérifié : 0 fuite de groupe, de source ou de contenu ; 0 doublon.
- **64 essais** (E0030 à E0093) : 100 époques, 64 px, lot de 32, réglages d'ultralytics inchangés, `yolo26n-cls` et `yolo26s-cls`. Variante A sur **3 graines** (0, 1, 2) ; variante L sur la graine 0.
- **Règle de choix**, fixée avant de regarder les chiffres : meilleur rappel moyen en validation (moyenne des 3 graines) ; `yolo26n` si l'écart est inférieur à 0,02.

## 3. Résultats (validation, variante A, moyenne de 3 graines)

« Hasard » : rappel moyen d'un modèle qui répondrait au hasard (0,33 pour le nombre, 0,50 pour la forme). « Triviale » : exactitude de la réponse « toujours la classe la plus fréquente ».

| Groupe | Modèle retenu | Essais (graines 0, 1, 2) | Rappel moyen ± écart | Exactitude / triviale | Images de validation |
|---|---|---|---|---|---|
| nombre · panoramique · droite | `yolo26n` | E0030, E0062, E0078 | 0,35 ± 0,01 | 60 % / 61 % | 70 : 43 · 8 · 19 |
| nombre · panoramique · gauche | `yolo26s` | E0035, E0067, E0083 | 0,44 ± 0,00 | 80 % / 74 % | 69 : 51 · 2 · 16 |
| nombre · non panoramique · droite | `yolo26n` | E0038, E0070, E0086 | 0,44 ± 0,03 | 92 % / 89 % | 55 : 49 · 1 · 5 |
| nombre · non panoramique · gauche | `yolo26s` | E0043, E0075, E0091 | **0,53 ± 0,01** | 84 % / 75 % | 47 : 35 · 2 · 10 |
| forme · panoramique · droite | `yolo26n` | E0032, E0064, E0080 | 0,50 ± 0,00 | 38 % / 63 % | 8 : 3 · 5 |
| forme · panoramique · gauche | `yolo26s` | E0037, E0069, E0085 | 0,64 ± 0,10 | 67 % / 60 % | 5 : 3 · 2 |
| forme · non panoramique · droite | `yolo26n` | E0040, E0072, E0088 | 0,70 ± 0,00 | 57 % / 71 % | 7 : 5 · 2 |
| forme · non panoramique · gauche | `yolo26s` | E0045, E0077, E0093 | 0,61 ± 0,03 | 59 % / 54 % | 13 : 7 · 6 |

Pour le nombre, les images de validation sont comptées « 0 place · 1 place · 2 places et plus » ; pour la forme, « bataille · longitudinal ».

**Rappel et précision par classe**, mêmes essais (moyenne des 3 graines ; rappel / précision) :

| Groupe | Sans place / bataille | Une place / longitudinal | Deux places et plus |
|---|---|---|---|
| nombre · panoramique · droite | 0,91 / 0,62 | 0,00 / — | 0,14 / 0,48 |
| nombre · panoramique · gauche | 0,97 / 0,80 | 0,00 / — | 0,33 / 0,90 |
| nombre · non panoramique · droite | 0,99 / 0,92 | 0,00 / — | 0,33 / 0,83 |
| nombre · non panoramique · gauche | 0,93 / 0,87 | 0,00 / — | 0,67 / 0,92 |
| forme · panoramique · droite | 1,00 / 0,38 | 0,00 / — | |
| forme · panoramique · gauche | 0,78 / 0,78 | 0,50 / 0,50 | |
| forme · non panoramique · droite | 0,40 / 1,00 | 1,00 / 0,40 | |
| forme · non panoramique · gauche | 0,38 / 0,72 | 0,83 / 0,54 | |

Les matrices de confusion de chaque essai sont dans `resultats.json` (clé `rapport.confusion`, lignes = vrai, colonnes = prédit) et dans la page « Un essai » du laboratoire.

**Variante A (réduction explicite) contre variante L (à la lettre), graine 0 seulement.** Sur les 16 couples (8 groupes × 2 modèles), A est meilleure dans 7 cas, L dans 6, égale dans 3 ; les écarts vont dans les deux sens. Avec une seule graine pour L, **aucun effet systématique du recadrage central n'est mesurable**.

## 4. Ce qu'on peut affirmer, ce qu'on ne peut pas

**On peut affirmer :**
- les jeux sont sains : plus aucune image identique entre train, validation et test, et les données du zip sont prises telles quelles ;
- **aucun des huit modèles n'est convaincant** ; le résultat « 95 % pour non panoramique droit » du 23/10 était dû à la fuite : il retombe à 92 % pour une réponse triviale à 89 % ;
- le **meilleur candidat** est « nombre, non panoramique, côté gauche » avec `yolo26s` (rappel moyen 0,53 contre 0,33 au hasard, stable d'une graine à l'autre) ; il retrouve 7 images sur 10 à deux places ou plus, mais sur 47 images dont 2 seulement à une place ;
- la catégorie « **une place** » n'est reconnue dans aucun des quatre groupes (rappel 0), avec 1 à 8 images par groupe en validation ;
- `yolo26s` n'est pas nettement meilleur que `yolo26n` : mieux dans 4 groupes sur 8, pire ou égal dans les autres.

**On ne peut pas affirmer :**
- quoi que ce soit sur la **forme** : 5 à 13 images de validation ;
- la performance finale : le test n'a pas été ouvert ;
- que le recadrage central soit sans effet : un seul essai à la lettre par cas ;
- que les photos non panoramiques généralisent : elles viennent de 3 enregistrements.

## 5. Limites des données

- Classes très rares : 1 place = 8 à 46 images selon le groupe sur tout le jeu ; la forme = 40 à 90 images par groupe.
- Découpages parfois très déséquilibrés pour la forme (par exemple « panoramique droit » : train 57 bataille · 8 longitudinal ; test 3 · 14), conséquence d'un découpage par enregistrement avec très peu d'images.
- 3 étiquettes corrigées à la main le 21/10 ne sont **pas appliquées** dans ces jeux ; si les corrections sont justes, il faut les réintégrer **en le disant**.

## 6. Suite proposée

1. **Test scellé** : à ouvrir **une seule fois**, pour les huit modèles retenus, uniquement sur accord explicite. Les lots de test de la forme font 6 à 12 images : ce chiffre ne dira presque rien pour la forme.
2. Pour progresser, il faut surtout **plus d'images avec places** et **d'autres enregistrements**, avant de changer le modèle.
3. Ensuite seulement, changer **une chose à la fois** par rapport à ce tableau de référence (rognage au lieu du masque, durée, rééquilibrage) en gardant 3 graines.

## 7. Où trouver les éléments

| Quoi | Où (sur le pod du projet de classification) |
|---|---|
| Essais et mesures | `labo/essais/E0030` à `E0093` : `config.json`, `resultats.json`, `metriques.csv`, `journal.log` |
| Modèles entraînés | `labo/essais/<essai>/poids/last.pt` |
| Jeux de données (train/val/test) | `labo/donnees/variantes/v2_*` : `manifeste.csv`, `recette.json`, `controles.json` |
| Code | PR #81 du dépôt (`labo/src/laboratoire/donnees/`) |
