# Le banc d'essai des projets d'apprentissage automatique

> 20/10/2026. **Proposition**, non implémentée. Elle sort du projet de classification d'images de stationnement
> (voir le §6 de [`cadrage-des-agents.md`](cadrage-des-agents.md)), où deux entraînements « réussis » ne valaient rien : critère de
> choix faussé, validation de quatre images, miroir sur un modèle de côté, aucune trace des réglages. Le banc d'essai est le
> cadre qui rend ces erreurs impossibles à commettre sans qu'on le voie.

## 1. Ce qu'on veut

Pouvoir, depuis un navigateur, **voir, comparer, lancer, arrêter et rejouer des essais** qui tournent sur le pod GPU, avec leurs
journaux et leurs résultats, sans rien exposer sur Internet et sans que l'agent ni la personne ne doivent connaître les chemins.

Six règles :

1. **Un essai = une configuration écrite**, avec sa graine et l'empreinte de son jeu de données. Rien ne s'écrase, tout se rejoue.
2. **Une seule porte pour entraîner** (`banc/lancer.py`). Elle journalise, évalue et range de la même façon pour tous ; un agent qui
   appelle `yolo` à la main contourne le banc et n'a pas de résultat comparable.
3. **La mesure qui compte est le rappel par classe** (et sa moyenne), jamais l'exactitude seule : sur un jeu où 80 % des images sont
   d'une classe, répondre toujours cette classe donne 0,8.
4. **Le jeu de test ne sert pas à choisir.** Il s'ouvre pour confirmer ; le banc compte combien de fois il a été consulté.
5. **Un chiffre dit sa fiabilité** : une classe de moins de 20 images en validation ou en test est marquée « non fiable ».
6. **Un pod en action n'est pas arrêté** : le banc tient le pod éveillé tant qu'un essai tourne (§4).

## 2. Où vit quoi

Sur le volume du pod GPU, donc persistant, dans `~/work/projects/<projet>/banc/` :

| Chemin | Contenu |
|---|---|
| `essais/<id>/config.json` | jeu, modèle, résolution, époques, rééquilibrage, graine, empreinte du jeu, version d'ultralytics |
| `essais/<id>/journal.log` | la sortie complète, relue en direct par l'interface |
| `essais/<id>/metriques.csv` | une ligne par époque : pertes, rappel par classe sur la validation |
| `essais/<id>/resultats.json` | validation et test : rappel par classe, rappel moyen, F1, matrice de confusion, effectifs |
| `essais/<id>/erreurs/` | les images mal classées, avec classe vraie et classe prédite |
| `essais/<id>/poids/` | `last.pt`, `best.pt` |
| `banc.db` | index SQLite des essais (état, durée, jeu, modèle, rappel moyen) : ce que l'interface lit vite |
| `corrections.csv` | étiquettes jugées douteuses par la personne ; les données brutes ne sont jamais modifiées |

Le code (`lancer.py`, `evaluer.py`, l'interface) est écrit dans l'Atelier, versionné avec le projet, et copié sur le pod.

## 3. L'interface

Une page web servie par le pod (FastAPI et une page unique, bibliothèques servies localement : le pod n'a pas à joindre un CDN).

| Page | Ce qu'on y fait |
|---|---|
| **Essais** | tableau trié par rappel moyen ; colonnes : jeu, modèle, résolution, rappel de chaque classe (validation et test), état, durée ; cocher 2 à 4 essais pour comparer |
| **Un essai** | courbes par époque, journal en direct, matrice de confusion, galerie des erreurs filtrée par classe vraie ou prédite, configuration, bouton « rejouer avec… » |
| **Comparer** | essais côte à côte : mêmes classes, mêmes échelles, différences surlignées |
| **Jeux** | effectifs par classe, par jeu et par collection, exemples d'images, alertes (classe rare, collection dans deux jeux, valeurs hors plage) |
| **Lancer** | formulaire **borné** (jeu, modèle, résolution, époques, rééquilibrage, graine, plis) ; l'essai entre dans une file, un à la fois |
| **Pod** | état du GPU, mémoire, essais en cours, bouton d'arrêt avec confirmation ; c'est le seul endroit où l'on arrête un essai |

Manipuler, c'est lancer, arrêter, rejouer et marquer une étiquette douteuse. Pas d'édition de fichier, pas de ligne de commande libre.

## 4. Comment la personne y accède, sans rien exposer

L'Atelier relaie déjà les services du namespace dans son panneau (`apps/bureaux.py` : Blender, QGIS, n8n, sous
`/_services/<connecteur>/<vue>/`, session propriétaire, cadrage, jetons qui ne quittent pas le serveur). Le banc s'y branche comme
une **vue de connecteur** : `amont: http://proj-<nom>-gpu-jupyter-pytorch-gpu:<port>`.

**Mesuré le 20/10** : depuis le pod de l'Atelier, `http://proj-classification-6fb3e27e-gpu-jupyter-pytorch-gpu:8888/api` répond (200) ; le service
du pod est joignable par son nom stable, sans passer par Internet. Reste à vérifier que le port du banc l'est aussi (service sans
sélecteur de ports : probable, à essayer avant de coder).

`expose_public` reste le geste de la personne, pour qui voudrait un lien hors de l'Atelier. L'interface n'a de toute façon aucune
authentification propre : elle n'est atteignable que par l'Atelier.

## 5. Garder le pod éveillé

Le watchdog du serveur Onyxia coupe un pod dont le GPU reste sous 5 % pendant 30 minutes, **même quand un entraînement tourne** (D-81 :
un entraînement limité par le processeur affiche 0 % de GPU). La correction est côté serveur et n'est pas faite. En attendant, le
banc peut, **tant qu'un essai tourne**, faire travailler le GPU une seconde toutes les deux minutes (un petit calcul sur le GPU). C'est un contournement
assumé, écrit comme tel dans le code, à retirer quand le serveur le sera.

## 6. Mesurer proprement

- **Découpage par collection** (déjà fait) et **validation croisée par groupes** : cinq plis, le rappel moyen est rendu avec son
  écart-type ; avec 28 collections, un seul découpage de quatre collections est du hasard.
- **Rééquilibrage dans l'entraînement seulement.**
- **Critère de choix** : le rappel moyen sur la validation, jamais l'exactitude ; le poids évalué est le dernier d'un nombre d'époques
  fixé, pas celui d'un arrêt anticipé sur un critère faussé.
- **Jeu de test** : consulté à la fin, le compteur de consultations est affiché.

## 7. Mise en place, par lots

| Lot | Contenu | Qui |
|---|---|---|
| **B0** | finir l'étape 1 en cours (réglages corrigés, rappel moyen) | l'agent du projet |
| **B1** | le moteur : `lancer.py` (configuration, empreinte du jeu, journal, évaluation uniforme, erreurs, `banc.db`) | l'agent, relu avant chaque envoi |
| **B2** | l'interface en lecture : Essais, Un essai, Comparer, Jeux | l'agent |
| **B3** | lancer, file d'attente, arrêt, rejouer, étiquette douteuse | l'agent |
| **B4** | la vue dans l'Atelier (déclaration du connecteur) | la personne accepte la déclaration |
| **B5** | validation croisée par groupes et rapport | l'agent |
| **B6** | le « battement » du §5, retiré quand le serveur est corrigé | l'agent |

Un gabarit `ml-gpu` (lot D de `cadrage-des-agents.md`) pourra ensuite poser le banc vide dans tout projet qui déclare un GPU.

## 8. À décider

1. **Une page maison ou MLflow.** MLflow (suivi d'essais, comparaison, standard) est prêt mais lourd, et n'a ni galerie d'erreurs, ni
   formulaire de lancement borné, ni file. Recommandation : page maison légère, avec export vers MLflow possible plus tard.
2. **Le « battement »** du §5 : l'accepter comme contournement le temps que le serveur soit corrigé, ou attendre.
3. **Le port** du banc, et la déclaration du connecteur (B4).
