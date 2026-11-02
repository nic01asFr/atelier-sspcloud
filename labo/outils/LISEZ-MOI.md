# Livrable : classification du stationnement

Ce dossier contient, pour chacun des huit groupes (panoramique ou non, côté droit ou gauche, tâche « nombre » ou « forme »), le modèle retenu et de quoi le relire.

## Les fichiers

| Fichier | Contenu |
|---|---|
| `<groupe>.pt` | le modèle (format ultralytics), celui de la graine 0 |
| `<groupe>_lots.csv` | une ligne par image : fichier, lot (`train`, `val`, `test`), classe, collection, origine |
| `<groupe>_mesures.json` | essai et jeu de données, empreinte du modèle, rappel et précision par classe, matrice de confusion, les 3 graines, règle de choix |
| `<groupe>_confusion_validation.csv` | la matrice de confusion (lignes : vraie classe ; colonnes : classe prédite) |
| `synthese.csv` | une ligne par groupe |
| `lire_le_livrable.ipynb` | un carnet Jupyter qui présente les modèles, refait les calculs et contrôle le dossier |

Les groupes : `panoramique_droite_nombre`, `panoramique_gauche_nombre`, `non_panoramique_droite_nombre`, `non_panoramique_gauche_nombre`, et les quatre mêmes en `_forme`.

## Les trois lots

- **train** : les images sur lesquelles le modèle apprend.
- **val** (validation) : les images avec lesquelles on compare et on décide (yolo26n ou yolo26s, préparation d'image…). **Tous les chiffres de ce dossier sont des chiffres de validation.**
- **test** : des images qui n'ont servi à aucun choix. **Il est scellé et n'a jamais été ouvert.**

Le découpage se fait par collection d'images, jamais image par image : des images voisines se ressemblent, et sans cela le modèle « tricherait ».

## Pourquoi un test scellé, et quand on l'ouvre

Chaque fois qu'on choisit « le meilleur » en regardant la validation, on s'adapte un peu à ses images. Avec peu d'images, un choix qui paraît meilleur peut être un coup de chance : la validation est un peu optimiste. Le test, qui n'a servi à aucun choix, est le seul à dire ce que vaut le modèle sur des images jamais vues. Le sceller empêche de s'en servir par inadvertance.

On l'ouvre **une seule fois, à la fin**, quand les étiquettes sont jugées assez fiables (définition de « place perçue », accord entre annotateurs mesuré), que les données sont arrêtées et que les modèles retenus sont fixés. Si on change quoi que ce soit après l'ouverture, le test ne vaut plus rien et il faut un nouveau lot.

## Lire les chiffres

- **Rappel** (d'une catégorie) : parmi les images de cette catégorie, la part que le modèle a retrouvées.
- **Précision** (d'une catégorie) : parmi les images rangées dans cette catégorie, la part qui y était vraiment.
- **Rappel moyen** : moyenne des rappels, chaque catégorie comptant autant. C'est la mesure principale.
- **Hasard** : le rappel moyen d'un modèle qui répondrait au hasard (1 ÷ nombre de catégories : 0,33 ou 0,50).
- **Réponse triviale** : répondre toujours la catégorie la plus fréquente. Une exactitude qui ne la dépasse pas n'apporte rien.
- **3 graines** : un entraînement n'est pas reproductible à l'identique. La moyenne sur 3 graines (± écart) est la mesure à retenir ; le fichier `.pt` est un exemplaire (graine 0).
- Une catégorie de **moins de 20 images** est « non fiable » : une image de plus déplace son rappel de 5 points ou plus.

## Réglages

Ceux de la consigne : `yolo26n-cls` puis `yolo26s-cls`, 100 époques, lot de 32, images en 64 × 64, données du zip sans correction d'étiquette ; pour les photos non panoramiques, le côté opposé est noirci. Le choix entre n et s suit une règle fixée avant de regarder les chiffres : meilleur rappel moyen en validation (moyenne de 3 graines), `yolo26n` si l'écart est inférieur à 0,02.

Pour le détail et les limites : `docs/rapports/classification-livrable.md` du dépôt.
