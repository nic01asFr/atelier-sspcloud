# Le laboratoire d'essais des projets d'apprentissage automatique

> 20/10/2026. **Proposition**, non implémentée. Elle sort du projet de classification d'images de stationnement
> (voir le §6 de [`cadrage-des-agents.md`](cadrage-des-agents.md)), où deux entraînements « réussis » ne valaient rien : critère de
> choix faussé, validation de quatre images, miroir sur un modèle de côté, aucune trace des réglages. Première version : un banc
> qui liste des essais. Cette version va plus loin : **un laboratoire** où l'on fait varier les données, leur structure, les
> méthodes et les réglages, et où l'on voit ce qui compte vraiment dans le résultat final.

## 1. Ce qu'on veut pouvoir faire

Depuis un navigateur, sur le pod GPU, sans rien exposer sur Internet :

1. **Voir et travailler les données** : leur structure, leurs effectifs, leurs images, leurs défauts ; fabriquer des variantes (autres classes,
   autre découpage, rognage ou masque, rééquilibrage) sans écrire de script.
2. **Choisir une méthode** : un modèle, ses réglages, avec une aide en français sur chacun.
3. **Lancer des essais isolés ou des expériences entières** : on choisit ce qui varie, le laboratoire fabrique le plan, annonce son coût, le
   met en file.
4. **Mesurer honnêtement** : rappel par classe, intervalle d'incertitude, comparaison à une réponse triviale, jeu de test verrouillé.
5. **Comprendre** : quel paramètre pèse le plus, où le modèle se trompe, où il regarde, combien de données de plus aideraient.
6. **Décider et garder la trace** : promouvoir un modèle, écrire la décision dans le projet.

## 2. Cinq objets, et rien d'autre

Tout ce que le laboratoire manipule est l'un de ces cinq objets. Chacun est écrit en configuration, versionné, rejouable.

| Objet | C'est | Exemple |
|---|---|---|
| **Jeu de données** (une variante) | le résultat d'une **recette** appliquée aux données brutes ; porte une empreinte et un manifeste | « côté droit, nombre en 3 classes, moitié utile rognée, découpage par collection, graine 7 » |
| **Méthode** | une famille de modèle et ses réglages | « YOLO classify taille n, résolution 224, 40 époques, sans miroir » |
| **Essai** | un jeu × une méthode × une graine (× un pli) | un entraînement, ses courbes, ses résultats, ses erreurs |
| **Expérience** | un plan d'essais : ce qui varie, ce qui reste fixe | « résolution {64, 224, 320} × préparation {masque, rognage} × modèle {n, s} × 3 graines » |
| **Modèle retenu** | un essai promu, avec sa fiche | `non_panoramique_droite_nombre.pt`, version 3 |

Les **recettes** sont des enchaînements de blocs : *extraire → étiqueter selon une règle → regrouper les classes → rogner ou masquer → découper par groupe → rééquilibrer*.
Faire varier la **structure du jeu** (trois classes ou quatre, un modèle par côté ou un seul, « nombre » et « forme » séparés ou joints, avec ou sans panoramiques)
revient à changer un bloc : ce n'est pas un projet à part.

## 3. Les écrans

```
┌──────────────────────────────────────────────────────────────────────────────────────────┐
│ Laboratoire · Classification d'images de stationnement          GPU ● en marche  file : 3│
├────────────┬─────────────────────────────────────────────────────────────────────────────┤
│ Accueil    │  Résultats · expérience « résolution × préparation »        [ Comparer ] [ + ]│
│ Données    │ ─────────────────────────────────────────────────────────────────────────────│
│ Méthodes   │  Rappel moyen (validation croisée, 5 plis × 3 graines)                       │
│ Expériences│                                                                              │
│ Résultats ◀│   224 · rognage   ████████████████████░░░░  0,71 ± 0,04                      │
│ Modèles    │   224 · masque    ███████████████░░░░░░░░░  0,58 ± 0,05                      │
│ Journal    │    64 · rognage   █████████████░░░░░░░░░░░  0,52 ± 0,06                      │
│            │    64 · masque    ████████████░░░░░░░░░░░░  0,48 ± 0,06                      │
│            │   ┄┄ réponse triviale « toujours 0 place » : 0,33 ┄┄                        │
│            │                                                                              │
│            │  Ce qui pèse le plus :  résolution ▓▓▓▓▓▓▓ +0,19    préparation ▓▓▓ +0,08     │
│            │                         modèle (n → s) ▓ +0,02  (dans le bruit)              │
│            │  Fiabilité : la classe « 1 place » n'a que 6 images en test — non fiable.    │
└────────────┴─────────────────────────────────────────────────────────────────────────────┘
```

| Écran | Ce qu'on y fait |
|---|---|
| **Accueil** | l'état du pod et de la file ; les derniers résultats ; les **alertes** (classe rare, fuite entre jeux, disque, pod coupé) ; **« que faire ensuite ? »**, des suggestions calculées (« la résolution pèse plus que le modèle : explorer 320 », « la classe 1 manque de données : 54 images, en collecter ») |
| **Données** | l'**explorateur** : arborescence réelle et vue en graphe des variantes (brut → recette → variante) ; effectifs par classe, jeu, collection ; **grille d'images** filtrable (classe, collection, jeu, étiquette douteuse), avec la préparation appliquée visible (masque, rognage) ; marquer ou corriger une étiquette (écrit un fichier de corrections versionné, le brut n'est jamais touché) ; **éditeur de recette par blocs** avec aperçu immédiat (« 886 → 887 images, classe 1 : 54 → 54 ») et contrôles automatiques ; **diff entre deux variantes** (qui change de classe, quels effectifs bougent) |
| **Méthodes** | le catalogue des modèles et des préréglages ; chaque réglage a sa bulle d'aide (ce qu'il fait, la plage utile, un défaut sensé) et ses bornes |
| **Expériences** | le **constructeur de plan** : on coche ce qui varie, on voit le tableau d'essais fabriqué, le **coût annoncé** (essais, durée, GPU) ; planification dans la file (priorité, reprise, arrêt) ; **arrêt précoce des mauvais essais** pour ne pas dépenser le GPU sur ce qui ne mènera nulle part |
| **Résultats** | tableau d'essais configurable ; **effet de chaque paramètre** sur le rappel moyen ; **comparaison appariée** (mêmes plis, mêmes graines) qui dit si A > B ou si c'est du bruit ; courbes d'apprentissage ; matrice de confusion ; rappel et précision par classe ; **seuil de décision** réglable ; **courbe de données** (qualité selon 25, 50, 75, 100 % du jeu : de combien de données de plus a-t-on besoin ?) |
| **Erreurs** | galerie des erreurs regroupées par collection ou par type ; **erreurs communes à tous les modèles** (souvent une étiquette fausse) ; **cartes de chaleur** (où le modèle regarde) |
| **Essayer** | déposer une image, choisir un ou plusieurs modèles, voir les probabilités, la préparation appliquée ; **deux modèles côte à côte sur la même image** |
| **Modèles** | le registre : promotion sous conditions (rappel minimal par classe, fiabilité), fiche, export, versions ; le jeu de test s'ouvre ici, **une fois** |
| **Journal** | journaux en direct, ressources, durées ; arrêt d'un essai avec confirmation |

## 4. Mesurer proprement (intégré, pas optionnel)

- **Réponse triviale toujours affichée** à côté de chaque chiffre (« toujours la classe la plus fréquente », « au hasard ») : un résultat se lit en gain sur elle.
- **Rappel par classe et rappel moyen** comme mesure reine ; l'exactitude globale seulement à titre d'information.
- **Découpage par groupe** (collection) et **validation croisée par groupes** ; graines multiples ; chaque chiffre vient avec son écart-type, ou son intervalle par rééchantillonnage.
- **Comparaison appariée** pour dire qu'une différence est réelle.
- **Fiabilité d'un chiffre** : moins de 20 images dans une classe en validation ou en test, la case devient « non fiable ».
- **Contrôles du jeu** à chaque variante : fuite d'une collection entre jeux, doublons, classe absente d'un jeu, classes déséquilibrées.
- **Test verrouillé** : il ne sert pas à choisir ; un compteur dit combien de fois il a été consulté.
- **Reproductibilité** : graine, empreinte du jeu, version des bibliothèques, commit des scripts ; tout essai se rejoue en un clic.

## 5. Les méthodes sont des adaptateurs

Une **famille de modèle** s'ajoute par un adaptateur d'une centaine de lignes qui déclare son schéma de réglages, sait entraîner, prédire et expliquer.
Au départ : YOLO classify (tailles n, s, m). Ensuite, sans toucher au reste : un réseau de la bibliothèque timm, un modèle linéaire sur des
représentations d'images (rapide, bon repère), un ajustement partiel. Les **recettes de données** fonctionnent de même : un bloc déclare ses paramètres et son aperçu.
C'est ce qui permet de comparer des méthodes, pas seulement des réglages.

## 6. Qui s'en sert, et comment

Une **seule interface de programmation** (le service du laboratoire), utilisée à la fois par la page et par les agents :

| Qui | Comment |
|---|---|
| **La personne** | la page, relayée par le panneau de l'Atelier |
| **L'agent du projet** | la même interface, par une petite commande (`labo essai lancer …`), qui lui rend des identifiants et des résultats lisibles ; il ne lance plus `yolo` à la main |
| **L'Assistant** | lecture : état, comparaisons, conclusions ; il propose, la personne décide |

Actions engageantes (supprimer un essai, promouvoir un modèle, ouvrir le test) : aperçu puis accord, comme le reste de l'Atelier.
**Notes et décisions** : chaque essai et chaque expérience porte une note ; un bouton écrit la conclusion dans `docs/decisions/` du projet,
pour que l'agent et la personne partagent la même mémoire.

## 7. Où vit quoi, et comment on y accède

Sur le volume du pod, donc persistant : `~/work/projects/<projet>/labo/` — `donnees/` (recettes, manifestes, variantes), `essais/<id>/` (configuration,
journal, métriques, résultats, erreurs, poids), `corrections.csv`, `labo.db` (SQLite : l'index que lisent les pages). Le service est un processus du pod
(FastAPI, une page unique, bibliothèques de tracé servies localement : pas de CDN) avec un travailleur qui prend la file, un essai à la fois (davantage si la mémoire du GPU le permet).

**Accès.** L'Atelier relaie déjà les services du namespace dans son panneau (`apps/bureaux.py` : Blender, QGIS, n8n, sous `/_services/…`, session propriétaire, cadrage,
jetons gardés côté serveur). Le laboratoire en est une vue de plus, `amont: http://proj-<nom>-gpu-jupyter-pytorch-gpu:<port>`. **Mesuré le 20/10** : depuis le pod de l'Atelier,
`…-gpu-jupyter-pytorch-gpu:8888/api` répond (200). Reste à vérifier le port du laboratoire. `expose_public` reste le geste de la personne ; le laboratoire n'a aucune
authentification propre et n'est atteignable que par l'Atelier.

**Garder le pod éveillé.** Le watchdog du serveur Onyxia coupe un pod dont le GPU reste sous 5 % pendant 30 minutes, même en plein entraînement (D-81). Tant qu'un essai
tourne, le travailleur fait travailler le GPU une seconde toutes les deux minutes. Contournement assumé, écrit comme tel, à retirer quand le serveur sera corrigé.

## 8. Mise en place

| Lot | Contenu |
|---|---|
| **L0** | finir l'étape en cours de l'agent (réglages corrigés, rappel moyen) |
| **L1, le socle** | service, file, essais, journaux, résultats par classe, réponse triviale ; YOLO classify seul ; écrans Essais, Un essai, Journal |
| **L2, les données** | explorateur, recettes par blocs, variantes, contrôles, diff ; grille d'images |
| **L3, les expériences** | constructeur de plan, coût annoncé, validation croisée, graines, effet des paramètres, comparaison appariée |
| **L4, comprendre** | erreurs, cartes de chaleur, seuil, courbe de données, « Essayer » |
| **L5, décider** | registre, promotion, notes vers `docs/decisions/`, accès pour l'Assistant |
| **L6, élargir** | autres familles de modèles, nouveaux blocs de recette |
| **Vue dans l'Atelier** | déclaration du connecteur : la personne accepte, une fois |
| **Gabarit `ml-gpu`** | pose un laboratoire vide dans tout projet qui déclare un GPU (lot D de `cadrage-des-agents.md`) |

Chaque lot est livré utilisable seul. L1 suffit à ne plus refaire les erreurs de ce projet.

## 9. À décider

1. **Écrire la page ou adopter un outil existant.** MLflow suit les essais et les compare, mais n'a ni éditeur de recettes, ni explorateur d'images, ni plan d'expérience, ni
   galerie d'erreurs. Recommandation : page maison, avec export vers MLflow possible plus tard.
2. **Le contournement du watchdog** (§7) : l'accepter, ou attendre la correction du serveur.
3. **Le périmètre de L1** : commencer par le socle et les données (L1, L2), puis les expériences (L3).
4. **Le port** du laboratoire et la déclaration de la vue.
