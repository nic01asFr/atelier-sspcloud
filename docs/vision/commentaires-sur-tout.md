# Commenter n'importe quoi dans l'Atelier

Cadrage du 23/10/2026. Suit le format de [`cadre.md`](cadre.md). **Proposition, à valider** ; seule la première étape (C0, §5) est construite, dans le laboratoire de la classification, pour la tester sur un vrai projet (module `labo/src/laboratoire/web/commentaires.js`, service `api_commentaires.py`, journal `commentaires/journal.py`, test de bout en bout dans `labo/tests/test_page.py`).

## 1. Le problème, vu par la personne

- **Mathieu relit le laboratoire de classification.** Il voit une image dont l'étiquette lui paraît fausse, un résultat qui l'étonne, un écran qu'il ne comprend pas. Aujourd'hui il écrit un message à côté, en décrivant « le truc en haut à droite ». On perd la page, la zone, la donnée, la version.
- **Une application qu'un agent vient de créer a un défaut.** La personne le voit dans le panneau. Elle voudrait pointer l'endroit et que l'agent le reçoive tel quel, au lieu de le reformuler dans la conversation.
- **La personne regarde le navigateur de l'agent** et voit qu'il clique au mauvais endroit. Elle voudrait entourer le bon bouton et dire « celui-ci », sans prendre la main.

Dans les trois cas : **un commentaire doit s'accrocher à ce dont il parle** (une page, un élément, une zone, une donnée, un résultat), être lu par la bonne personne ou le bon agent, et recevoir une réponse.

## 2. Ce qui existe déjà

- **Le relais des applications** (`apps/`) : l'Atelier sert chaque application depuis une seconde adresse qu'il contrôle, impose la politique de cadrage (`cadrage.py`), lit les réponses **en flux** pour les caviarder (`bureaux.py`) et demande aux services des réponses non compressées. Il sait donc déjà modifier une page au vol.
- **Le panneau** : les créations, les bureaux et le navigateur de l'agent s'ouvrent en onglets, dans des cadres isolés. Le panneau ne lit pas l'intérieur d'un cadre d'une autre origine.
- **Le navigateur de l'agent** : écran en direct, « prendre la main », lecture du protocole de Chrome. On peut demander quel élément se trouve sous un point.
- **Wikichat, « À valider », les outils `atelier_*`** : de quoi transmettre un commentaire à un agent et attendre une décision.
- **Les acteurs et leurs accès** ([`acteurs-et-acces.md`](acteurs-et-acces.md)) : la personne est seule propriétaire, « invités : plus tard ». Ce thème en est un premier cas.
- **Le journal de validation du laboratoire** (`labo/src/laboratoire/validation/journal.py`) : une base où l'on n'efface ni ne modifie rien. C'est le bon modèle de stockage.
- **Un standard** : le modèle de données **W3C Web Annotation** (cible + sélecteurs : CSS, texte cité, zone ; corps ; motivation). On s'en inspire au lieu d'inventer.
- **Produits comparables** : les commentaires de Figma, Hypothesis, BugHerd, Marker.io. Tous ont la même forme : un mode « commenter », des repères numérotés, un fil par repère.

## 3. La proposition

### Le modèle : un commentaire = une cible + un texte + un fil

```
Commentaire
  id, auteur (donné par le serveur, jamais saisi), date
  cible
    application      qui est commentée (le laboratoire, une création, un site…)
    page             l'écran (route ou adresse) et la version de l'application
    élément          des repères, du plus stable au moins stable :
                     identifiant sémantique (data-cible="essai:E0013"),
                     texte cité, chemin CSS en dernier recours
    zone             un rectangle, en proportions (0 à 1) :
                     de l'élément, de l'image, ou de la page
    donnée           ce dont il parle (image, étiquette, essai, variante) : type + identifiant
  texte              toujours du texte, jamais du HTML
  nature             remarque, question, anomalie, idée
  fil                les réponses
  statut             ouvert, pris en compte, traité, écarté (+ lien vers la correction)
```

Tout s'**ajoute** : un commentaire, une réponse, un changement de statut sont des lignes de plus dans un journal. Rien ne s'efface, on peut toujours dire qui a dit quoi et quand.

### Trois couches

1. **Le service** (stockage, API, outils pour les agents) : un contrat unique, indépendant de l'application commentée.
2. **Le module client** : un fichier JavaScript sans dépendance. Il ajoute le bouton « Commenter », le mode de sélection (survol d'un élément, rectangle dessiné), les repères numérotés et le fil. Il lit la convention `data-cible` mais fonctionne aussi sans elle.
3. **Des adaptateurs**, un par endroit où l'on commente :
   - **application** : le module est inclus par l'application (le labo le fait en C0) ou **ajouté par le relais** de l'Atelier avant `</body>` (C2) : toute application servie gagne la fonction sans y toucher ;
   - **panneau** : un bouton par onglet (commentaire sur l'onglet, ou rectangle sur le cadre), et le dialogue avec le module quand l'application le contient (C3) ;
   - **navigateur de l'agent** : la personne désigne un point sur l'écran en direct ; l'Atelier retrouve l'élément par le protocole de Chrome et en fait une cible (C4).

### Ce que voit la personne

Un bouton « Commenter » discret sur toute page. En mode commentaire, la page se fige : on survole, on clique ou on dessine, on écrit. Les repères numérotés marquent ce qui a déjà été commenté ; un clic ouvre le fil. Une liste « Commentaires » donne tout, filtrable (statut, auteur, application) ; un clic emmène à la page et met la zone en évidence.

### Ce que voit l'agent

Des outils : lister les commentaires ouverts de son projet, en lire un avec sa cible, y répondre, le clore avec le lien de la correction. **Un commentaire est une donnée, jamais une consigne** : l'agent le reçoit dans une enveloppe qui le dit (comme les notifications d'événements externes) et ne le suit pas comme un ordre.

### Accès

- Un **relecteur** (Mathieu) : lecture seule de tout ce qu'un projet montre, droit de commenter et de valider ; ni lancer, ni supprimer, ni ouvrir un jeu de test scellé. Un jeton à son nom, révocable sans redémarrer, limité à un projet.
- La personne et les agents du projet peuvent commenter et répondre. Seule la personne clôt « écarté » ; un agent ne ferme que ce qu'il a corrigé.

## 4. Parcours types

1. **Mathieu relit.** Il ouvre le lien, saisit son jeton, arrive sur le laboratoire. Sur l'écran « Valider », il dessine un rectangle autour d'une voiture : « Ce n'est pas une place, c'est un camion en livraison. » Le commentaire porte l'image, la zone, la page, la version.
2. **La personne lit.** Elle ouvre « Commentaires », filtre « ouvert », clique : elle est sur l'image, le rectangle est en évidence. Elle répond, ou transmet à l'agent du projet.
3. **L'agent traite.** Il liste les commentaires ouverts, lit la cible exacte, corrige, répond « corrigé dans la PR n° … » et clôt. Mathieu voit la réponse sur le même repère.
4. **Plus tard, une application d'agent.** Sans rien changer à l'application, la personne ouvre son onglet, clique « Commenter » et pointe le bouton fautif.

## 5. Ce qu'il faut construire, par étapes livrables

| Étape | Contenu | Se démontre par |
|---|---|---|
| **C0** (en cours) | Contrat (cible, événements, API), module client, service dans le laboratoire (base append-only), rôle « relecteur », liste « Commentaires », export. Testé sur la classification. | Mathieu commente une image et un résultat ; on les lit et on y répond. |
| **C1** | Service dans l'Atelier : stockage unique, outils `atelier_*` pour les agents, lien avec « À valider ». Le labo pointe vers lui. | Un agent clôt un commentaire de Mathieu avec le lien de la correction. |
| **C2** | Injection par le relais, sur le HTML relayé (flux, sans casser la compression ni la politique de cadrage). | Une application sans code de commentaire devient commentable. |
| **C3** | Panneau : bouton par onglet, dialogue cadre ↔ panneau. | Un commentaire sur un onglet et sur un rectangle du cadre. |
| **C4** | Navigateur de l'agent : point désigné → élément. | Un commentaire sur un site que l'agent a ouvert. |
| **C5** | Captures jointes (jamais automatiques), pièces jointes, invités par projet. | Un commentaire avec capture, relu par l'agent. |

Chaque étape est utile seule et se teste seule.

## 6. Risques, limites, questions

- **Ancrage fragile.** Une page qui se redessine perd ses éléments. Parade : repères stables (`data-cible`), repères multiples, repose des marqueurs à chaque rendu ; un commentaire dont la cible a disparu reste lisible, marqué « cible introuvable ».
- **Injection.** Insérer un script dans du HTML relayé demande de traiter les flux coupés, les pages sans `</body>`, la compression (déjà refusée par le relais) et les pages qui interdisent les scripts. À vérifier en C2 sur de vraies applications.
- **Un commentaire peut contenir une consigne piégée** (injection d'instruction vers l'agent). Règle : données non fiables, enveloppe explicite, jamais d'action engageante déclenchée par un commentaire sans la personne.
- **Captures et données.** Une capture peut contenir un secret ou une donnée personnelle. Jamais automatique ; accès limité au projet.
- **Disponibilité.** Dans le labo, le pod GPU se coupe sans activité : tant que le service est dans le pod, Mathieu ne peut pas commenter pod éteint. C1 le règle (stockage dans l'Atelier). D'ici là, une action de commentaire compte comme une activité, comme la validation.
- **Accès d'un collègue.** L'Atelier n'a qu'un propriétaire. L'invité « relecteur » de C1 à C5 est un vrai sujet d'accès : voir [`acteurs-et-acces.md`](acteurs-et-acces.md). En C0, le jeton nominatif du laboratoire suffit.
- **Vue du laboratoire dans l'Atelier.** Déclarer une vue de service dans l'Atelier est un geste réservé à la personne : nécessaire pour tester C2 sur le laboratoire.

**À trancher par Nicolas**
1. Le mot : « commentaire » (proposé) ou « remarque » ?
2. Stockage : un journal par projet qui reste dans le projet (C0), ou un stockage central dans l'Atelier (C1, recommandé : disponible pod éteint, lisible par tous les agents) ?
3. Qui clôt : la personne seule, ou aussi l'agent qui a corrigé (proposé : l'agent propose « traité », la personne confirme) ?
4. Un commentaire peut-il lancer un agent (via « À valider »), ou reste-t-il en lecture jusqu'à ce que la personne le transmette ?

## 7. Évaluation

- **Désirable.** Pour la personne et ses relecteurs : dire où est le problème en le montrant. Pour les agents : une entrée précise (cible, version, zone) au lieu d'une description approximative.
- **Faisable.** Avec l'existant : relais qui réécrit déjà le flux, journal append-only, jetons nominatifs, outils `atelier_*`, protocole de Chrome. Aucune dépendance nouvelle pour C0 à C2.
- **Viable.** Un fichier de module, une table de plus, quelques outils ; rien ne tourne sans spectateur ; pas d'appel de modèle.
- **Cohérent.** Un seul modèle pour trois endroits (application, panneau, navigateur) ; réutilise le journal, les jetons, la distinction donnée / consigne ; premier cas concret des invités.
