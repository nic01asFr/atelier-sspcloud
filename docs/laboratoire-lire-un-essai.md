# Lire un essai du laboratoire

Le laboratoire d'essais range chaque entraînement de modèle sous un identifiant (`E0030`…) avec **tout ce qu'il faut pour le relire** : les données, les réglages, le modèle obtenu et ses mesures. Cette page explique comment le lire. Pour le fonctionnement complet, voir [`banc-d-essai-ml.md`](vision/banc-d-essai-ml.md).

## Ce qu'est un essai

Un essai, c'est **un jeu de données + un modèle + des réglages + une graine**. Rien d'autre ne varie. Pour comparer deux essais, on ne change qu'une de ces quatre choses.

| Élément | Où le lire | Exemple |
|---|---|---|
| **Jeu de données** (une *variante*) | `labo/donnees/variantes/<jeu>/` : `manifeste.csv` (une ligne par image : lot, classe, collection), `recette.json` (comment il a été construit), `controles.json` (ce qui a été vérifié) | `v2_recadrage_droite_nombre_A-…` |
| **Modèle et réglages** | `essais/<id>/config.json` | `yolo26n-cls`, 100 époques, images 64 px, lot de 32 |
| **Graine** | `essais/<id>/config.json` | 0, 1 ou 2 (l'aléa de l'entraînement) |
| **Modèle obtenu** | `essais/<id>/poids/last.pt` | le dernier poids : celui qui est mesuré |
| **Mesures** | `essais/<id>/resultats.json`, ou la page « Un essai » du laboratoire | voir ci-dessous |

Le jeu de données est découpé en trois lots, **par collection d'images** (jamais image par image) : **train** pour apprendre, **val** pour comparer et choisir, **test** gardé fermé (« scellé »), qu'on n'ouvre qu'une fois pour donner le chiffre final. Le manifeste dit dans quel lot est chaque image.

## Lire les mesures

Toutes les mesures d'un essai (`resultats.json`) portent sur le lot **val**, sauf mention contraire.

| Mesure | Ce que c'est | Comment la lire |
|---|---|---|
| **Rappel** (d'une classe) | Parmi les images de cette classe, la part que le modèle a retrouvées. | « 47 sur 53 images sans place » = rappel de 89 %. |
| **Précision** (d'une classe) | Parmi les images que le modèle a rangées dans cette classe, la part qui y était vraiment. | Précision faible = le modèle déclare cette classe à tort. |
| **Matrice de confusion** | Un tableau : en lignes la vraie classe, en colonnes la classe prédite. | La diagonale = les bonnes réponses ; le reste, ce que le modèle confond avec quoi. |
| **Rappel moyen** | La moyenne des rappels, **chaque classe comptant autant**. | **C'est la mesure principale** : l'exactitude seule récompense « toujours la classe la plus fréquente ». |
| **Hasard** | Le rappel moyen d'un modèle qui répondrait au hasard : 1 ÷ nombre de classes (0,33 pour 3 classes, 0,50 pour 2). | Un rappel moyen proche du hasard = le modèle ne distingue presque rien. |
| **Exactitude** et **réponse triviale** | La part d'images bien classées ; et ce qu'obtiendrait « toujours la classe majoritaire ». | **Une exactitude qui ne dépasse pas la réponse triviale n'apporte rien.** |
| **Classe non fiable** | Une classe de moins de 20 images dans le lot mesuré. | Son rappel est indicatif seulement : une image de plus déplace le chiffre de 5 points ou plus. |

## Règles de lecture

1. **Un essai ne prouve rien tout seul.** L'entraînement n'est pas reproductible à l'identique : deux essais de même configuration peuvent différer de plusieurs points. On compare donc des **moyennes sur 3 graines**.
2. **Un écart plus petit que l'écart entre graines est du bruit.**
3. **Le lot val sert à choisir ; le lot test sert une fois, à la fin.** Si on choisit en regardant le test, il ne mesure plus rien.
4. **Les contrôles du jeu** (`controles.json`) disent avant l'essai ce qui rendrait les mesures trompeuses : collections ou images présentes dans deux lots, **images identiques sous deux noms**, classes absentes ou rares. Un contrôle bloquant empêche de construire le jeu.

## Dans l'interface

- **Essais** : la liste, avec le rappel moyen de validation et l'exactitude de chaque essai ;
- **Un essai** : réglages, courbes d'entraînement, matrice de confusion, rappel et précision par classe, et la comparaison à la réponse triviale ;
- **Données** : les jeux, leurs effectifs par lot et leurs contrôles ;
- **Livrable** : les modèles retenus avec leurs chiffres, et de quoi les télécharger (chaque fichier, ou tout en une archive zip).
