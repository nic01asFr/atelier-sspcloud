# Le laboratoire « profondeur » (projet depth-models)

Même laboratoire que la classification (file d'essais, pod CPU toujours allumé + pod GPU à la demande, journaux qu'on n'efface pas, commentaires sur tout), adapté à ce que le projet cherche : **comparer des modèles de profondeur monoculaire sur des panoramas 360° de Panoramax**, et choisir celui qui sert.

## Ce qui diffère de la classification

| | Classification | Profondeur |
|---|---|---|
| Un essai | entraîner un modèle puis le mesurer | faire tourner un modèle existant sur tous les panoramas d'un jeu |
| La donnée | images étiquetées | panoramas Panoramax, licence et producteur gardés avec chaque image |
| La référence | des étiquettes | **aucune** profondeur mesurée |
| Ce qu'on mesure seul | rappel moyen, baselines | cohérence d'un modèle avec lui-même, accord entre modèles, temps, mémoire |
| Ce qui tranche | la validation, puis le test scellé | **le vote humain par paires, à l'aveugle** |

## Les modèles

| Modèle | Entrée | Sortie | Licence |
|---|---|---|---|
| MoGe-2 | une vue en perspective | distances en mètres | MIT |
| Depth Anything V2 (small / base / large) | une vue en perspective | relief relatif | Apache-2.0 (small) ; CC BY-NC 4.0 (base, large) |
| DAP (Depth Any Panorama) | le panorama entier | distances en mètres | CC BY-NC 4.0 |

Les modèles « CC BY-NC » ne s'emploient pas à des fins commerciales : la comparaison est permise, un usage en production demande de vérifier.

## Comment on compare sans référence

Chaque panorama est découpé en vues en perspective (un tour d'horizon tous les 45°, plus une rangée inclinée de 15°, champ de 90°). Chaque modèle donne une carte par vue. Tout est ramené à `q` = inverse de la distance au centre de prise de vue, ce qui rend comparables des profondeurs en mètres et des disparités relatives.

- **Incohérence** : deux vues qui se recouvrent voient le même point à la même distance. On ajuste une droite entre leurs `q` sur les points communs ; l'incohérence est la part de variation que la droite n'explique pas (0 : parfait). Elle écarte les mauvais modèles, elle ne désigne pas le meilleur. **Elle n'est pas comparable entre un modèle de panorama et un modèle par vue** : le premier est cohérent par construction.
- **Dérive d'échelle** (modèles en mètres) : l'échelle change-t-elle d'une vue à l'autre ?
- **Accord entre modèles** : corrélation du relief vue par vue. Les paires en désaccord sont celles à regarder.
- **Vote par paires** : une personne voit deux cartes de la même scène, sans savoir de quels modèles ni de quel côté ; elle dit laquelle rend le mieux le relief, ou « égales », ou « impossible à juger ». Les jugements alimentent un classement de Bradley–Terry avec un intervalle à 90 % obtenu en rééchantillonnant des **panoramas** (les votes d'un même panorama ne sont pas indépendants). Classement jugé fiable à partir de 30 jugements sur 10 panoramas.

## Ce que ça ne dit pas

- Aucune de ces mesures n'est une erreur de profondeur. Si une mesure de terrain existe (lidar, mesure au sol), elle se branche comme une mesure de plus : c'est la seule façon de parler d'exactitude.
- Les panoramas de Panoramax ne sont pas tous parfaitement horizontaux (tangage et roulis de la prise sont gardés dans le manifeste, non corrigés).
- Un jeu de 36 panoramas de 4 zones n'est pas la France : le classement vaut pour ce jeu.

## Constituer un jeu

    python -m laboratoire.profondeur.panoramax --racine <labo> --jeu panoramax-36 --n 36 --par-sequence 3 \
        --bbox 5.70,45.15,5.76,45.21 --bbox 2.28,48.84,2.40,48.90

Seules des licences ouvertes sont gardées, seuls les panoramas déclarés 360° sont téléchargés, et on prend d'abord une prise par séquence de prise de vue (le « groupe » du jeu), puis des prises espacées d'une même séquence.

## Ajouter un modèle

Une classe dans `profondeur/modeles_profondeur.py` : `charger(appareil)` et `predire(rgb, fov)` (une vue) ou `predire_panorama(erp)` (le panorama entier), qui rendent `q` et un masque. Le reste (file, GPU, cartes, mesures, vote, classement) ne change pas.
