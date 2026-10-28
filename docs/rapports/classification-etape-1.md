# Classification d'images de stationnement — étape 1 : les huit modèles de la consigne

> **⚠ 28/10/2026 — résultats invalidés en partie.** Un audit a trouvé une fuite de données (des images identiques dans le train et la validation, surtout pour « non panoramique droit »), trois étiquettes corrigées à la main et d'autres limites. Les chiffres de ce document ne doivent plus être cités. Voir [la reprise du 28/10](classification-etape-1-reprise.md).

> 23/10/2026. Ce document dit ce qu'on a fait, comment, ce qu'on a mesuré, et **ce qu'on peut et ne peut pas en conclure**. Les chiffres sont traduits en
> phrases. Tous les essais sont dans le laboratoire d'essais (registre `labo/labo.db` du pod, essais E0013 à E0028) ; le fonctionnement du laboratoire
> est décrit dans [`banc-d-essai-ml.md`](../vision/banc-d-essai-ml.md).
>
> **État : les mesures ci-dessous sont des mesures de *validation*. Le jeu de test scellé n'a pas encore été ouvert.** Le résultat définitif de la consigne
> sera celui du test (voir §6).

## 1. Ce que demande la consigne

À partir d'un zip de données déjà annotées, entraîner des modèles qui regardent une image de rue et disent, pour **un côté de la rue** :

- **le nombre de places de stationnement perçues** : aucune, une, ou deux et plus ;
- **la forme du stationnement** : en bataille ou en longitudinal.

Comme certaines images sont panoramiques et d'autres non, la consigne demande **huit modèles** : {panoramique, non panoramique} × {gauche, droite} × {nombre, forme}, en commençant par `panoramique_droite_nombre`. Entraînement demandé :
un classifieur YOLO léger (`yolo26n-cls`, 100 époques, images réduites à 64 × 64 pixels), puis aussi `yolo26s-cls`.

## 2. Les données

Les données sont celles du zip, **utilisées telles quelles** : aucune image n'a été ré-annotée, aucune étiquette changée. Elles sont rangées par ville, route et collection d'images, puis par côté (`gauche`, `droite`), puis par nombre de places (et forme).
Elles contiennent **1 771 images**, de deux sortes (voir [`validation-humaine.md`](../vision/validation-humaine.md), §11) :

- **les images « panoramiques »** (1 021 images, 768 × 512 pixels) : ce sont des morceaux d'une vue à 360°, **déjà tournés vers le côté** concerné. Il y a un fichier différent pour chaque côté ;
- **les images « non panoramiques »** (750 images, 2 048 × 1 536 pixels) : ce sont des photos prises vers l'avant. **Le même fichier** est rangé sous `gauche` et sous `droite`, avec une étiquette pour chaque côté : le côté n'est qu'une moitié de la photo.

La grande majorité des images n'a **aucune place** (1 323 sur 1 771). Les images à une place sont rares : 105. Les images à deux places ou plus sont 343 (dont 140 à deux places et 166 à trois), regroupées dans « 2 et plus ». Pour la forme, 174 images sont en bataille et 104 en longitudinal.

| Groupe | Sans place | 1 place | 2 places et plus | Bataille | Longitudinal |
|---|---|---|---|---|---|
| panoramique, droite | 329 | 46 | 137 | 63 | 27 |
| panoramique, gauche | 392 | 27 | 90 | 24 | 16 |
| non panoramique, droite | 316 | 8 | 50 | 35 | 23 |
| non panoramique, gauche | 286 | 24 | 66 | 52 | 38 |

## 3. La démarche

Pour chacun des huit groupes :

1. **On garde les images du groupe** (type d'image et côté) ; pour la forme, uniquement celles qui ont une forme annotée (donc au moins une place).
2. **Préparation de l'image.** Panoramique : image entière. Non panoramique : **la moitié du côté opposé est noircie** (comme la consigne le demande), pour que le modèle ne regarde que le côté concerné.
3. **Découpage en trois lots, par collection d'images** : environ 70 % pour apprendre (entraînement), 15 % pour choisir et comparer (validation), 15 % mis de côté (test, scellé). Les images d'une même collection sont toutes dans le même lot : sinon le modèle verrait au test des images presque identiques à celles de l'entraînement, et le résultat serait trop beau.
4. **Entraînement** : `yolo26n-cls` (réglages de la consigne : 100 époques, 64 × 64 pixels), puis `yolo26s-cls` avec exactement les mêmes réglages. Pas de rééquilibrage des classes, un seul tirage (graine 0). Chaque essai dure environ deux minutes sur le GPU.
5. **Mesure sur le lot de validation**, avec les indicateurs expliqués ci-dessous.

Rien d'autre n'a été changé d'un modèle à l'autre : les différences viennent donc du groupe d'images et de la taille du modèle (`n` ou `s`).

*Historique.* Un premier essai du 19/10 (deux modèles « droite, nombre ») avait été entraîné sur toutes les images mélangées, sans séparer les deux types. Il ne répondait pas à la consigne et n'est pas repris ici.

## 4. Comment lire les mesures

- **Images retrouvées** (« rappel ») : pour une catégorie, la part des images de cette catégorie que le modèle a bien classées. Exemple : « 47 sur 53 images sans place » veut dire que, sur 53 images sans place, le modèle en a reconnu 47.
- **Rappel moyen** : la moyenne de ces parts, **chaque catégorie comptant pour autant, quel que soit son nombre d'images**. C'est l'indicateur principal, parce qu'avec très peu d'images à une place, l'exactitude seule est trompeuse.
- **Hasard** : le rappel moyen d'un modèle qui répondrait au hasard vaut un divisé par le nombre de catégories : 0,33 pour le nombre (trois catégories), 0,50 pour la forme (deux). Un rappel moyen proche de cette valeur veut dire que le modèle ne discrimine presque pas.
- **Exactitude** : la part de toutes les images bien classées. À comparer à la **réponse triviale** : répondre toujours la catégorie la plus fréquente (ici « sans place » pour le nombre, « en bataille » pour la forme). **Un modèle dont l'exactitude n'est pas au-dessus de la réponse triviale n'apporte rien sur ce critère.**
- **Fourchette** (entre crochets) : l'étendue plausible du rappel moyen, obtenue en refaisant le calcul après avoir retiré au sort des collections entières. Plus elle est large, moins le chiffre est solide.
- **Trop peu d'images pour s'y fier** : une catégorie de moins de 20 images dans le lot mesuré. Son chiffre est indicatif seulement.
- **Validation et test.** La validation sert à comparer les modèles et à en choisir un. Le **test** est un lot gardé fermé (« scellé ») qu'on n'ouvre qu'une fois, **pour donner le chiffre final** : si on le consultait pour choisir, il ne serait plus une mesure honnête.

## 5. Résultats (validation)

Pour chaque groupe : d'abord `yolo26n` (réglages de la consigne), puis `yolo26s`.

### Nombre de places

**Panoramique, côté droit** — 79 images mesurées : 53 sans place, 6 avec une place, 20 avec deux places ou plus.
- `yolo26n` : retrouve 47 sur 53 images sans place (89 %), 1 sur 6 images avec une place (17 %, trop peu d'images pour s'y fier) et 2 sur 20 images avec deux places ou plus (10 %). Exactitude 63 %, **moins que la réponse triviale (67 %)**. Rappel moyen 0,38 [0,35–0,63], à peine au-dessus du hasard (0,33).
- `yolo26s` : 43 sur 53 sans place (81 %), 1 sur 6 avec une place, 8 sur 20 avec deux places ou plus (40 %). Exactitude 66 %, toujours **un peu sous la réponse triviale (67 %)**. Rappel moyen 0,46 [0,36–0,51].
- *En clair :* le modèle reconnaît surtout les images sans place. `yolo26s` trouve nettement plus d'images avec places (8 sur 20 au lieu de 2) mais se trompe davantage sur les images sans place.

**Panoramique, côté gauche** — 74 images : 58 sans place, 3 avec une place, 13 avec deux places ou plus.
- `yolo26n` : 58 sur 58 sans place (100 %), 0 sur 3 avec une place, 2 sur 13 avec deux places ou plus (15 %). Exactitude 81 %, **3 points au-dessus de la réponse triviale (78 %)**. Rappel moyen 0,38 [0,33–0,48].
- `yolo26s` : 50 sur 58 sans place (86 %), 0 sur 3, 1 sur 13 (8 %). Exactitude 69 %, **sous la réponse triviale (78 %)**. Rappel moyen 0,31 [0,26–0,39], **en dessous du hasard (0,33)**.
- *En clair :* ici, `yolo26n` est meilleur, mais il ne fait guère mieux que répondre « aucune place » à chaque image.

**Non panoramique, côté droit** — 57 images : 48 sans place, 1 avec une place, 8 avec deux places ou plus.
- `yolo26n` : 44 sur 48 sans place (92 %), 0 sur 1, 6 sur 8 avec deux places ou plus (75 %). Exactitude 88 %, **4 points au-dessus de la réponse triviale (84 %)**. Rappel moyen 0,56 [0,29–0,93].
- `yolo26s` : 48 sur 48 sans place (100 %), 0 sur 1, 6 sur 8 (75 %). Exactitude 95 %, **11 points au-dessus de la réponse triviale (84 %)**. Rappel moyen 0,58 [0,33–1,00].
- *En clair :* c'est le meilleur résultat du nombre de places. Mais il repose sur une seule image à une place et huit à deux places ou plus, et la fourchette du rappel moyen est très large : on ne peut pas encore le tenir pour acquis.

**Non panoramique, côté gauche** — 55 images : 42 sans place, 2 avec une place, 11 avec deux places ou plus.
- `yolo26n` : 37 sur 42 sans place (88 %), 0 sur 2, 3 sur 11 avec deux places ou plus (27 %). Exactitude 73 %, **sous la réponse triviale (76 %)**. Rappel moyen 0,38 [0,30–0,45].
- `yolo26s` : 39 sur 42 sans place (93 %), 0 sur 2, 3 sur 11 (27 %). Exactitude 76 %, **égale à la réponse triviale (76 %)**. Rappel moyen 0,40 [0,30–0,48].
- *En clair :* le modèle ne fait pas mieux que de répondre « aucune place ».

### Forme du stationnement

La mesure ne porte que sur 5 à 17 images par groupe : **aucune conclusion ne peut en être tirée**. Les chiffres montrent que la chaîne fonctionne, pas qu'un modèle est bon ou mauvais.

**Panoramique, côté droit** — 17 images : 13 en bataille, 4 en longitudinal.
- `yolo26n` : 12 sur 13 en bataille, 1 sur 4 en longitudinal. Exactitude 76 %, égale à la réponse triviale. Rappel moyen 0,59 [0,25–0,92].
- `yolo26s` : 9 sur 13 en bataille, 0 sur 4 en longitudinal. Exactitude 53 %, **sous la réponse triviale (76 %)**. Rappel moyen 0,35 [0,00–0,69].

**Panoramique, côté gauche** — 5 images : 3 en bataille, 2 en longitudinal.
- `yolo26n` : 3 sur 3 en bataille, 0 sur 2 en longitudinal. Exactitude 60 %, égale à la réponse triviale. Rappel moyen 0,50.
- `yolo26s` : 3 sur 3, 1 sur 2. Exactitude 80 %. Rappel moyen 0,75 [0,75–1,00]. Avec cinq images, un seul cas de plus ou de moins change tout : ce chiffre ne veut rien dire.

**Non panoramique, côté droit** — 10 images : 7 en bataille, 3 en longitudinal.
- `yolo26n` et `yolo26s` donnent le même résultat : 6 sur 7 en bataille, 3 sur 3 en longitudinal. Exactitude 90 %, **20 points au-dessus de la réponse triviale (70 %)**. Rappel moyen 0,93 [0,75–1,00].
- *En clair :* c'est le meilleur résultat de la forme, mais sur dix images seulement.

**Non panoramique, côté gauche** — 15 images : 8 en bataille, 7 en longitudinal.
- `yolo26n` : 5 sur 8 en bataille, 2 sur 7 en longitudinal. Exactitude 47 %, **sous la réponse triviale (53 %)**. Rappel moyen 0,46 [0,27–1,00].
- `yolo26s` : 6 sur 8, 1 sur 7. Exactitude 47 %, même constat. Rappel moyen 0,45 [0,33–1,00].

## 6. Ce qu'on peut affirmer, ce qu'on ne peut pas

**On peut affirmer :**
- les huit modèles de la consigne existent ; ils ont été entraînés et mesurés avec la méthode et les réglages demandés, sur les données du zip telles quelles ;
- sur la validation, **les modèles reconnaissent presque toujours les images sans place, et retrouvent mal celles qui ont des places** ; la catégorie « une place » n'est presque jamais reconnue (0 à 17 % selon le groupe) ;
- **un seul groupe fait nettement mieux que la réponse triviale pour le nombre de places : non panoramique, côté droit** (95 % d'exactitude avec `yolo26s`, contre 84 % pour la réponse triviale), mais sur 57 images dont une seule à une place ;
- `yolo26s` n'est **pas nettement meilleur** que `yolo26n` : mieux sur certains groupes, pire sur d'autres, avec des fourchettes qui se chevauchent presque toutes.

**On ne peut pas affirmer :**
- un classement entre modèles, sauf différence très nette (aucune ne l'est à coup sûr) ;
- la performance finale : **le test n'a pas été ouvert** ;
- quoi que ce soit sur la forme : les lots mesurés sont trop petits ;
- que le modèle « ne sait pas » reconnaître une place : avec 64 × 64 pixels et si peu d'exemples, il se peut que l'information manque au modèle, ou que certaines étiquettes de la catégorie « une place » soient discutables. Rien n'a été fait ici pour le vérifier : les étiquettes sont celles de la consigne.

## 7. Suite proposée

1. **Fixer à l'avance la règle de choix**, avant de regarder le test : pour chacun des huit groupes, on retient le modèle au meilleur rappel moyen en validation ; à écart inférieur à 0,02, on garde `yolo26n`, plus simple.
2. **Ouvrir le test scellé une seule fois**, pour ces huit modèles, et rendre ces chiffres comme **résultat de la consigne**, dans le même format que ci-dessus.
3. Ensuite seulement, si on veut améliorer : changer **une seule chose à la fois** par rapport à ce tableau de référence (taille d'image, rééquilibrage, durée d'entraînement) et mesurer l'écart.

L'outil de validation humaine des étiquettes (écran « Valider » du laboratoire) existe, mais **il ne fait pas partie de cette consigne** et n'a pas servi ici.
