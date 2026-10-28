# Mesurer l'accord entre annotateurs

*28 octobre 2026. Prolonge [la validation humaine](validation-humaine.md) (lot V3 : « deuxième valideur à l'aveugle, accord »). Le calcul, la file d'échantillonnage et la route existent ; reste à faire annoter.*

## 1. Pourquoi c'est le chiffre qui borne tout le reste

Un modèle apprend à reproduire des étiquettes. Si deux personnes sérieuses, devant la même image, ne mettent pas la même étiquette une fois sur trois, il n'existe pas de « bonne réponse » unique à apprendre : le meilleur modèle possible reproduira *l'une* des deux personnes, et sera « faux » une fois sur trois contre l'autre. L'accord entre humains est donc le **plafond** de ce qu'on peut attendre d'un modèle.

C'est ce qui manque pour lire nos résultats. Le meilleur modèle de la reprise du 28/10 atteint un rappel moyen de 0,53 (contre 0,33 au hasard). Est-ce peu ou beaucoup ?
- si deux humains obtiennent entre eux 0,60, le modèle est proche du plafond : il faut changer la tâche ou la définition, pas le modèle ;
- si deux humains obtiennent 0,95, le modèle a une grande marge : c'est la donnée ou le modèle qui limite.

Aujourd'hui on ne sait pas lequel des deux. Le seul signal : sur les 4 décisions de validation du 21/10, 3 ont changé l'étiquette d'origine. Quatre images ne mesurent rien, mais cela suffit à justifier la mesure.

## 2. Ce qu'on mesure

À partir du journal des décisions (la dernière décision en vigueur de chacun), pour **le nombre de places** (0, 1, 2 et plus) et **la forme** (aucune, bataille, longitudinal) :

| Mesure | Ce que c'est | À quoi elle sert |
|---|---|---|
| **Accord par classe** | Pour les images d'une classe donnée par l'une des deux sources, la part où l'autre redit la même classe. | Dit **quelles classes** sont ambiguës (probablement « 1 »). Fiable dès ~20 images par classe. |
| **Rappel moyen humain** | La moyenne des accords par classe. | **Même unité que le rappel moyen d'un modèle** : on compare directement. |
| **Kappa de Cohen** | L'accord brut, corrigé de celui qu'on aurait au hasard. 1 = parfait, 0 = hasard. | Résumé en un chiffre. Indicatif ici (voir §5). |
| **Matrice de confusion** | Qui met quoi à la place de quoi. | Dit **comment** on se trompe : « 1 » pris pour « 0 » ou pour « 2 et plus ». |

Deux comparaisons :
- **origine contre valideur** : l'étiquette du jeu de données contre une personne qui ne la voyait pas ;
- **valideur contre valideur** : deux personnes sur les mêmes images, chacune sans voir la réponse de l'autre. C'est la mesure la plus propre.

Grille de lecture du kappa (Landis et Koch) : moins de 0,2 faible · 0,2 à 0,4 passable · 0,4 à 0,6 modéré · 0,6 à 0,8 bon · plus de 0,8 très bon.

## 3. Avant de commencer : trancher la définition

Sans consigne commune, l'accord mesure surtout *nos désaccords sur la consigne*. À écrire, avec trois ou quatre images d'exemple, **avant** que deux personnes annotent (questions à poser à qui a construit le jeu) :

1. **Qu'est-ce qu'une « place perçue » ?** Une place de stationnement marquée (libre ou occupée) ? Ou un véhicule garé ? Dans le second cas, la valeur dépend de l'heure de la prise de vue, pas de la rue.
2. Un véhicule **à cheval sur deux places**, **partiellement masqué** ou **coupé par le bord de l'image** : on le compte ou non ?
3. **Jusqu'à quelle distance** compte-t-on ? Une place très loin, minuscule, compte-t-elle ?
4. Pour les **photos non panoramiques**, on ne juge que **la moitié du côté étudié** (l'autre est assombrie à l'écran).
5. **Forme** : un alignement mixte (bataille et longitudinal sur la même image) ? Le choix par défaut proposé : l'écran laisse « douteuse » (`D`) pour les cas non tranchables.

## 4. Le protocole

1. **Qui** : au moins deux personnes, plus l'étiquette d'origine. Le plus utile : vous et la personne qui a demandé le travail.
2. **Quelle liste** : la file **`accord`** de l'écran Valider. 150 images tirées par étiquette d'origine (0, 1, 2 et plus) et par type (recadrage, photo plate), 25 par case ; si une case compte moins de 25 images, toutes sont prises. **La même liste pour tout le monde**, déterministe : c'est ce qui permet de comparer.
3. **Comment** : écran Valider, en mode **aveugle** (par défaut : l'étiquette d'origine et les prédictions sont cachées). Touches `0` `1` `2` `3+`, `D` pour une image douteuse. **Ne pas se parler pendant l'annotation.**
4. **Durée** : environ 20 minutes pour 150 images.
5. **Lire** : `GET /api/validation/accord`. Le résultat donne, pour chaque tâche, les deux comparaisons avec accord brut, kappa, matrice, accord par classe et rappel moyen humain.

## 5. Précautions

- **Un échantillon tiré par classe rend fiable l'accord par classe, pas l'accord brut ni le kappa globaux** : ceux-ci dépendent de la part de chaque classe dans l'échantillon (ici égale), pas dans le jeu (où « 0 » domine à 75 %). C'est pour cela que la lecture principale est le rappel moyen humain.
- **150 images = ± 0,1 sur le kappa** et ± 0,2 sur l'accord d'une classe de 25 images : on lit des ordres de grandeur, pas des décimales.
- **Les décisions ne modifient pas les jeux de la reprise du 28/10** (construits avec `corrections: false`), donc ni leurs lots de validation ni leur test. Elles modifieraient toute recette `corrections: true` : à ne pas activer sans le dire.
- **Ne pas corriger les étiquettes à partir de cette mesure** : on mesure d'abord. Corriger les lots de validation ou de test après coup rendrait toutes les mesures précédentes non comparables.
- Un valideur qui voit les prédictions d'un modèle est influencé : ne pas montrer les prédictions pendant cette mesure.

## 6. Comment lire le résultat

| Rappel moyen humain (nombre) | Lecture | Suite |
|---|---|---|
| **≥ 0,8** | Les étiquettes sont fiables ; le plafond est haut. | Le modèle est loin du plafond : plus de données, autre résolution, autre approche. |
| **0,5 à 0,8** | Les humains hésitent, surtout sur une classe. | Regarder la matrice : si « 1 » est pris pour « 0 » ou « 2 et plus », **fusionner ou redéfinir** cette classe. Le modèle ne peut guère faire mieux que le plafond. |
| **< 0,5** | La tâche telle que définie n'a pas de réponse stable. | **Revoir la définition** (§3) avant tout nouvel entraînement. |

Pour comparer à un modèle : mettre son rappel moyen en validation à côté du rappel moyen humain **de la même tâche**. Un modèle au-dessus du plafond humain a probablement appris des particularités du jeu (voir l'audit du 28/10), pas la tâche.

## 7. Ce qui existe dans le laboratoire

- `laboratoire.validation.accord` : kappa de Cohen, matrice, accord par classe, rappel moyen humain (fonctions pures, testées) ;
- la file `accord` (`/api/validation/files`) ;
- `GET /api/validation/accord` ;
- le journal conserve, pour chaque décision, l'étiquette d'origine, le valideur et le caractère aveugle : rien à ajouter à la saisie.

**Pas encore fait** : un affichage de l'accord dans l'écran Valider (aujourd'hui, la route rend du JSON) et la consigne de validation illustrée d'exemples (§3).
