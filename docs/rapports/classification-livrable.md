# Classification de stationnement — les huit modèles de la consigne : ce qui est livré

> 30/10/2026. Restitution de la consigne. Complète [la reprise du 28/10](classification-etape-1-reprise.md) (audit, méthode, limites).
> **Toutes les mesures sont sur le lot de validation. Le lot de test est scellé et n'a jamais été ouvert (0 consultation).**

## 1. Ce qui est livré

Pour chacun des huit groupes de la consigne, **un modèle** (fichier `.pt`), **les listes d'images train, validation et test**, **les mesures** (rappel, précision, matrice de confusion) et **le choix argumenté**. Tout est dans un dossier unique, `livrable/` (voir §6).

## 2. Conventions (à connaître avant de lire les chiffres)

- **Réglages de la consigne**, identiques pour les huit groupes : `yolo26n-cls` puis `yolo26s-cls`, 100 époques, lot de 32, images en 64 × 64, données du zip **sans aucune correction d'étiquette**, pour les photos non panoramiques le côté opposé est noirci.
- **Images en 64 × 64 écrites telles quelles** (variante « A ») : l'image entière est réduite une fois pour toutes, sans recadrage. La réduction à la lettre, confiée au modèle (qui recadre le centre), a aussi été essayée : sur une graine, aucune différence systématique.
- **Découpage** : 70 / 15 / 15 % par collection d'images, jamais image par image. Aucune image identique n'est répartie entre deux lots (contrôlé : 0 fuite de contenu, de groupe, de source ; 0 doublon). Le découpage est le nôtre.
- **Choix du modèle** (règle fixée avant de regarder les chiffres) : meilleur rappel moyen en validation, moyenne de 3 graines ; `yolo26n` si l'écart est inférieur à 0,02.
- **Le fichier livré est le modèle de la graine 0.** Chaque colonne dit clairement si le chiffre est celui de **ce fichier** ou la **moyenne des 3 graines** (un entraînement n'est pas reproductible à l'identique : la moyenne est la mesure à retenir, le fichier est un exemplaire).
- **Rappel moyen** : moyenne des rappels de chaque catégorie, chacune comptant autant. **Hasard** : 0,33 pour trois catégories, 0,50 pour deux. **Réponse triviale** : « toujours la catégorie la plus fréquente ».

## 3. Les huit modèles

| Groupe | Modèle | Essai livré | Images train · val · test | Rappel moyen : ce fichier | Rappel moyen : 3 graines | Hasard | Exactitude / réponse triviale (ce fichier) |
|---|---|---|---|---|---|---|---|
| `panoramique_droite_nombre` | `yolo26n` | E0030 | 355 · 70 · 83 | 0,345 | 0,352 ± 0,005 | 0,33 | 60,0 % / 61,4 % |
| `panoramique_gauche_nombre` | `yolo26s` | E0035 | 342 · 69 · 75 | 0,439 | 0,436 ± 0,003 | 0,33 | 78,3 % / 73,9 % |
| `non_panoramique_droite_nombre` | `yolo26n` | E0038 | 236 · 55 · 60 | 0,400 | 0,442 ± 0,030 | 0,33 | 90,9 % / 89,1 % |
| `non_panoramique_gauche_nombre` | `yolo26s` | E0043 | 240 · 47 · 61 | **0,514** | **0,533 ± 0,014** | 0,33 | 83,0 % / 74,5 % |
| `panoramique_droite_forme` | `yolo26n` | E0032 | 65 · 8 · 17 | 0,500 | 0,500 ± 0,000 | 0,50 | 37,5 % / 62,5 % |
| `panoramique_gauche_forme` | `yolo26s` | E0037 | 29 · 5 · 6 | 0,667 | 0,639 ± 0,104 | 0,50 | 60,0 % / 60,0 % |
| `non_panoramique_droite_forme` | `yolo26n` | E0040 | 39 · 7 · 5 | 0,700 | 0,700 ± 0,000 | 0,50 | 57,1 % / 71,4 % |
| `non_panoramique_gauche_forme` | `yolo26s` | E0045 | 57 · 13 · 9 | 0,631 | 0,607 ± 0,034 | 0,50 | 61,5 % / 53,8 % |

Les trois graines de chaque groupe sont dans `trois_graines` du fichier `_mesures.json`.

## 4. Rappel, précision, matrice de confusion (validation, fichier livré)

Matrice : lignes = vraie classe, colonnes = classe prédite. Classes du nombre : **0**, **1**, **2 et plus**. Classes de la forme : **bataille**, **longitudinal**.

**Nombre de places** (rappel / précision ; nombre d'images)

| Groupe | 0 place | 1 place | 2 places et plus | Matrice |
|---|---|---|---|---|
| panoramique · droite | 0,93 / 0,62 (43) | 0,00 / 0,00 (8) | 0,11 / 0,50 (19) | `[[40,1,2],[8,0,0],[17,0,2]]` |
| panoramique · gauche | 0,94 / 0,80 (51) | 0,00 / 0,00 (2) | 0,38 / 0,86 (16) | `[[48,2,1],[2,0,0],[10,0,6]]` |
| non panoramique · droite | 1,00 / 0,91 (49) | 0,00 / — (1) | 0,20 / 1,00 (5) | `[[49,0,0],[1,0,0],[4,0,1]]` |
| non panoramique · gauche | 0,94 / 0,87 (35) | 0,00 / 0,00 (2) | 0,60 / 0,75 (10) | `[[33,1,1],[1,0,1],[4,0,6]]` |

**Forme** (rappel / précision ; nombre d'images)

| Groupe | Bataille | Longitudinal | Matrice |
|---|---|---|---|
| panoramique · droite | 1,00 / 0,38 (3) | 0,00 / — (5) | `[[3,0],[5,0]]` |
| panoramique · gauche | 0,33 / 1,00 (3) | 1,00 / 0,50 (2) | `[[1,2],[0,2]]` |
| non panoramique · droite | 0,40 / 1,00 (5) | 1,00 / 0,40 (2) | `[[2,3],[0,2]]` |
| non panoramique · gauche | 0,43 / 0,75 (7) | 0,83 / 0,56 (6) | `[[3,4],[1,5]]` |

« — » : la précision n'existe pas quand le modèle ne prédit jamais cette classe.

## 5. Ce que nous affirmons, ce que nous n'affirmons pas

**Nous affirmons :**
1. Les huit modèles ont été entraînés avec les réglages de la consigne, sur les données du zip sans correction, et mesurés sur un lot de validation sans fuite.
2. **Pour le nombre de places, les modèles reconnaissent « aucune place » (rappel de 0,93 à 1,00) et retrouvent mal les images avec places.** La catégorie « une place » n'est reconnue dans aucun des quatre groupes (rappel 0, sur 1 à 8 images de validation).
3. **Deux groupes ne font pas nettement mieux que la réponse triviale** (`panoramique_droite_nombre` : −1 point ; `non_panoramique_droite_nombre` : +2 points d'exactitude) ; deux font mieux (`panoramique_gauche_nombre` : +4 points ; `non_panoramique_gauche_nombre` : +9 points).
4. **Le meilleur candidat est `non_panoramique_gauche_nombre`** (rappel moyen 0,53 pour 0,33 au hasard, stable d'une graine à l'autre). Il retrouve 6 images sur 10 à deux places ou plus, sur 47 images de validation dont 2 seulement à une place.

**Nous n'affirmons pas :**
1. **Rien sur la forme.** Les lots de validation font 5 à 13 images, ceux de test 5 à 17 : un chiffre peut changer de 10 à 20 points avec une seule image.
2. **Rien sur la performance finale.** Le test n'est pas ouvert.
3. **Aucun classement entre `yolo26n` et `yolo26s`** : le choix suit la règle, mais les écarts sont de l'ordre du bruit entre graines pour plusieurs groupes.
4. **Pas que le modèle « ne sait pas » reconnaître une place.** Avec 8 à 46 images « une place » par groupe, 64 × 64 pixels et des photos non panoramiques issues de 3 prises de vue seulement, les données ne permettent pas de trancher entre « le modèle ne peut pas » et « il n'a pas assez d'exemples ».
5. **Rien sur la fiabilité des étiquettes** : l'accord entre annotateurs n'a pas été mesuré (la mesure est prête, voir [`accord-entre-annotateurs.md`](../vision/accord-entre-annotateurs.md)).

## 6. Les fichiers

**Téléchargement : onglet « Livrable » du laboratoire** (un lien par fichier, et « Tout télécharger » pour l'archive zip de 52 Mo). Accessible à l'administrateur et au relecteur, pas au valideur. Le dossier est constitué par `labo/outils/constituer_livrable.py` ; sur le pod du projet de classification, il est dans `labo/livrable/` :

| Fichier | Contenu |
|---|---|
| `<groupe>.pt` | le modèle (graine 0), au format ultralytics |
| `<groupe>_lots.csv` | une ligne par image : fichier, lot (`train`, `val`, `test`), classe, collection, chemin d'origine |
| `<groupe>_mesures.json` | essai et jeu de données, empreinte (SHA-256) du modèle, rappel/précision par classe, matrice de confusion, 3 graines, règle de choix |
| `<groupe>_confusion_validation.csv` | la matrice de confusion de validation |
| `synthese.csv` | le tableau du §3 |

Les jeux complets (images) sont dans `labo/donnees/variantes/v2_*`, les essais dans `labo/essais/E0030` à `E0093`.

## 7. Suite

1. **Test scellé** : à ouvrir une seule fois pour ces huit modèles, sur accord explicite. Son chiffre complétera le §3.
2. **Définition** de « place perçue » et **mesure de l'accord entre annotateurs** : elles disent si les étiquettes permettent d'aller plus loin.
3. **Plus d'images avec places** et d'autres prises de vue, avant de changer de modèle.
