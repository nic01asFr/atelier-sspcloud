# Vision de l'Atelier — synthèse

> **État au 26/09/2026.** Les vagues 1 à 3 sont intégrées. Décisions postérieures : pas de page Gardiens, les gardiens sont montrés dans la vue Agents (J-i) ; wikichat ordonne ses automates, l'exécuteur des gardiens ne fait que les siens (J-a). Ce qui existe : [`../fonctionnalites.md`](../fonctionnalites.md).

Synthèse du 25/09/2026 des travaux de réflexion. **Proposition, non implémentée.** Elle s'appuie
sur :

- `cadre.md` : cadre commun ;
- `panneau.md` : voir et manipuler à côté de la conversation ;
- `ecosysteme.md` : ce qu'on crée, où ça va ;
- `gardiens.md` : ce qui garde l'ensemble fiable ;
- `relecture-grand-public.md` : ce que voit une personne qui ne code pas ;
- `coherence-croisee.md` : modèles unifiés, doublons, feuille de route, vérifications dans le code.

Ce document dit ce qui est retenu et dans quel ordre on le construit. Il donne aussi les
décisions qui reviennent à Nicolas. Le détail reste dans les documents d'origine.

## 1. La promesse

> **Je demande, je vois, je montre du doigt, je partage, et on me prévient si ça casse.**

Chaque équipe porte un morceau de cette phrase :

| Morceau | Porté par | Ce que la personne vit |
|---|---|---|
| je demande | l'existant (conversation, projets, agents) | une conversation dans un projet |
| je vois | panneau | ce que l'agent fabrique s'ouvre à droite du fil, dans un onglet, sans quitter la page |
| je montre du doigt | panneau | un clic ou une sélection, **Montrer**, et l'agent sait de quoi elle parle ; **Prendre la main** quand l'agent agit |
| je partage | écosystème | une création passe du brouillon à « installée chez moi », puis à « partagée », sur un seul écran d'accord |
| on me prévient | gardiens | des vérifications sans IA surveillent créations et Atelier ; une correction préparée attend un clic |

La démonstration qui la rend concrète dure 3 minutes (relecture grand public §4) :

1. un fichier Excel déposé ;
2. une carte sur fond IGN dans le panneau ;
3. une commune montrée du doigt et corrigée ;
4. la carte partagée à une collègue ;
5. une semaine plus tard, une panne réparée d'un clic.

Son équivalent le plus proche d'être vrai aujourd'hui : **QGIS dans le panneau et un connecteur
fait maison utilisable depuis claude.ai** (parcours de Karim).

## 2. Le modèle retenu

```
                         ┌──────────── Atelier (origine de l'Atelier) ────────────┐
   personne ───────────► │  fil de conversation  │  PANNEAU (onglets)             │
                         │                       │   page · application ·         │
                         │  « Montrer »  ◄───────┤   navigateur · bureau ·        │
                         │  « Prendre la main »  │   interface d'outil (MCP Apps) │
                         └───────────┬───────────┴──────────────┬─────────────────┘
                                     │ outils atelier_*         │ iframes isolées
                                     ▼                          ▼
   agent (Claude Code) ──► PROJET ──► CRÉATIONS ──► hôte des applications (autre origine)
                            projet.json  artefact.json v2       mandataire + relais WS
                                                   │            (un seul chemin d'affichage)
                              brouillon ──installer──► chez moi ──partager──► d'autres
                                                   │
                            registre des promotions (versions, accords, exposition)
                                                   │
   GARDIENS (exécuteur à part, sans modèle) ── contrôles ── journal unique ── « À valider »
        santé · sécurité · cohérence · dépenses            (une seule file de propositions)
```

Cinq règles tiennent l'ensemble. Elles viennent des équipes et la relecture de cohérence les a
vérifiées :

1. **Un seul chemin d'affichage.** Tout ce qui s'affiche passe par l'hôte des applications, dans
   une autre origine que l'Atelier : pages, applications, bureaux, écran de Chrome, n8n. Le jeton
   du service y est ajouté côté serveur. `/chrome/*` quitte l'origine de l'Atelier.
2. **L'état partagé est l'objet, pas le panneau.** La personne agit dans la vue, l'agent agit par
   ses outils, et tous deux travaillent sur le même objet. Conséquence à dire clairement : une
   **page** se corrige en montrant, un **bureau** ou un **éditeur** (QGIS, Blender, n8n) se corrige
   aussi à la main.
3. **Deux manifestes, le reste est dérivé.** `projet.json` décrit le projet, `artefact.json` v2
   décrit chaque création. Le registre des promotions est écrit par l'Atelier seul, sur geste de
   la personne. Les contrôles, l'inventaire des automates et les descripteurs de vue en sont
   dérivés (schéma : `coherence-croisee.md` §1.2).
4. **Une brique par besoin** : un vérificateur d'autorisations et un écran d'accord ; un journal ;
   un ordonnanceur (l'exécuteur des gardiens) ; une file « À valider » ; deux relais seulement
   (affichage et modèle).
5. **Détecter en code, réparer par proposition.** Un gardien est du code : les contrôles ne
   consomment aucun jeton. Seule une réparation mobilise un agent, sur une branche, avec un
   plafond. Les gestes permis sans la personne forment une liste fermée et réversible.

Standard retenu pour les vues : **MCP Apps**, derrière un module unique de l'Atelier et avec le
seul sous-ensemble utilisé. Le panneau est propriétaire du cadre de vue et du pont. L'écosystème
s'y branche au lieu de le reconstruire (F5 et F7 sont P1 et P3).

### Le navigateur, brique transverse (précision de Nicolas, 25/09)

Le navigateur des agents (Chrome en stdio, `docs/navigateur-atelier.md`, branche `chrome-stdio`)
ne sert pas qu'à chercher sur le web. Il sert aussi à **utiliser et tester l'Atelier lui-même**
et ce qu'on y crée. Il devient une brique du fonctionnement interne.

| Usage | Qui | Ce que fait le navigateur |
|---|---|---|
| Vérifier une création après l'avoir modifiée | agent code | ouvrir la page ou l'application, lire la console et le réseau, capturer, cliquer ; boucle « modifier → voir → corriger » |
| `/verifier` d'un projet | commande de projet | parcours de bout en bout de ses créations, sans modèle si le scénario est écrit |
| Santé d'une création installée ou partagée | gardien Santé | « la création s'affiche et lit ses données » : chargement, absence d'erreur console, élément attendu présent. C'est du code, sans jeton. |
| Réparation assistée | agent lancé par une proposition | reproduire la panne vue par le gardien, puis vérifier la correction avant de proposer |
| Montrer | Assistant, agents | capture ou vue en direct dans le panneau (`atelier_montrer`, P5) |
| Rendu et affichage | Atelier | vignettes des créations, aperçus pour « À valider », captures pour la vitrine et la documentation |
| Tester l'interface de l'Atelier | agents qui travaillent sur l'Atelier | parcours de l'interface réelle, mesures (non-régression, accessibilité) |

**Prérequis constaté dans le code : un accès authentifié et borné.** Aujourd'hui, le Chrome d'un
agent démarre vide. Or l'hôte des applications exige une session d'applications
(`__Host-atelier_apps`), obtenue par un code de passage émis depuis la session du propriétaire
(`apps/passage.py`). Un agent ne peut donc pas ouvrir les créations de son projet.

Ce qu'il faut :

- **Code de passage d'agent** : un outil `atelier_navigateur_ouvrir(projet, chemin)` émet un code
  de passage à usage unique. Sa portée :
  - le seul projet de la conversation, ou les projets que l'Assistant a le droit de voir ;
  - une durée courte ;
  - l'agent comme acteur dans le journal.
- **Chrome de l'agent** : il consomme ce code et reçoit un cookie d'applications. Il ne reçoit
  jamais le cookie de l'Atelier lui-même.
- **Interface de l'Atelier** : l'ouvrir dans le navigateur d'un agent demande une session à part,
  en lecture, à décider.
- **Contrôles des gardiens** : ils utilisent le même mécanisme, avec un profil de navigateur
  dédié à l'exécuteur, sans modèle.
- **Nettoyage** : la session d'applications de l'agent meurt avec son profil jetable.

Ce prérequis s'ajoute au jalon **J2** (voir à côté du fil) : une création qu'on montre doit aussi
pouvoir être vérifiée par l'agent qui l'a faite. Il sert ensuite J6, J10 et le gardien Santé des
créations.

## 3. Ce qu'on dit à l'écran

Lexique proposé par la relecture grand public. Tout autre mot reste interne (documents,
manifestes, outils de l'agent).

| Mot | Pour tous |
|---|---|
| Projet | Un dossier de travail qui regroupe vos conversations et ce que vous y fabriquez. |
| Création | Ce que l'agent fabrique pour vous : une page, une application, un connecteur, une tâche qui revient. |
| Panneau | La colonne à droite de la conversation où s'affiche ce que vous regardez, en onglets. |
| Montrer | Envoyer à l'agent ce que vous voyez ou avez sélectionné dans le panneau. |
| Brouillon | La version en cours de travail, que vous seul voyez et que l'agent peut modifier. |
| Installer | Figer une version et l'ajouter à votre Atelier pour vous en servir partout. |
| Partager | Rendre une version figée utilisable par d'autres, avec un lien. |
| Connecteur | Un branchement vers un service qui donne des outils à l'agent. |
| Autorisation | Ce qu'une création a le droit de faire en votre nom. |
| Tâche automatique | Ce qui se lance seul à heure fixe, avec une limite de dépense affichée. |
| Gardien | Une vérification automatique, sans IA, qui surveille et prévient. |
| À valider | La liste unique de ce qui attend votre accord. |

Les mots internes, jamais affichés : artefact, vue, extension, famille, gabarit, prise,
composition, MCP, jeton, production.

## 4. Défauts retenus : ce que l'Atelier décide à la place de la personne

- **Type de création** : l'agent choisit la famille (page, application, connecteur, tâche) et le
  dit en une phrase ; on peut en changer plus tard.
- **Accords** :
  - rien à accepter en brouillon ;
  - un geste dans le panneau vaut accord pour l'outil de ce connecteur, le temps de la
    conversation ;
  - un seul écran d'autorisations, groupé, au moment d'installer ou de partager ;
  - par défaut en lecture seule, limité aux seules tables utilisées.
- **Partager…** : un seul bouton qui demande « avec qui ? » (moi partout, des personnes, tout
  le monde). Il fait sortir la création du pod dès qu'elle est partagée à d'autres.
- **Alertes** :
  - elles sont rédigées par effet (« votre carte ne s'affiche plus »), sur la création
    concernée et dans l'accueil ;
  - la page Gardiens garde le détail technique ;
  - la santé des **créations installées ou partagées** est contrôlée, pas seulement celle des
    connecteurs.
- **Corrections** : présentées dans « À valider », avec ce qui était cassé, un avant/après et
  **Accepter / Refuser**. L'Atelier fusionne lui-même la branche.
- **Dépenses** : affichées en part du forfait ou en fréquence, jamais en jetons.
- **Tâches automatiques** :
  - le plafond par défaut est bas (24 par jour) et le budget est obligatoire ;
  - une tâche créée par un agent naît désactivée ;
  - une tâche coupée le dit sur la création elle-même.
- **Deux trous à combler dès le premier gabarit** :
  - un fichier déposé devient une table (Grist ou `donnees/`), lue en lecture seule ;
  - une liste blanche de fonds de carte (Géoplateforme IGN, OSM) est autorisée aux pages.

## 5. Feuille de route

Jalons démontrables, fusionnés à partir des étapes P (panneau), F (écosystème) et G (gardiens)
et des lots existants (`coherence-croisee.md` §3). Tailles : S, M, L.

| Jalon | À la fin, on peut… | Taille |
|---|---|---|
| **J0 Assainir** | ouvrir la même conversation partout sans écart, sans aucun jeton en clair ; tâches automatiques plafonnées | S |
| **J1 Voir ce qui tourne seul** | ouvrir la page Gardiens, voir chaque tâche automatique (dernière exécution, prochaine, coût) et la couper d'un geste ; résumé du lundi | M |
| **J2 Voir à côté du fil** | voir une création à droite de la conversation, ouverte et rafraîchie par l'agent ; plus d'onglet perdu | M |
| J3 Aucun secret, aucun port ouvert à l'insu | être alerté en 15 min d'un jeton en clair ou d'une écoute non déclarée ; `git push` d'un secret refusé | M |
| J4 Même contexte partout | reprendre une conversation dans VS Code avec la même identité, les mêmes alertes, le même panneau | L |
| J5 Montrer à l'agent | cliquer une parcelle et dire « celle-ci » ; QGIS ou Blender dans le panneau, capture envoyée | L |
| J6 Le navigateur de l'agent en direct | regarder l'agent naviguer, prendre la main pour une connexion, la rendre | M |
| J7 Démarrer d'un modèle | créer un projet d'une famille en un message, vérifié à la création ; Lecteur Grist migré | M |
| J8 Brouillon et installation | installer une version, revenir en arrière, restaurer ses données ; file « À valider » | L |
| J9 Mon connecteur fait maison | ajouter un connecteur d'un projet à l'Atelier et l'appeler depuis claude.ai | M |
| J10 Réparation assistée | trouver le matin une correction prête pour ce qui a cassé la nuit | L |
| J11 Autorisations et extensions de l'Atelier | ajouter une vue à l'accueil après un écran d'accord clair | L |
| Plus tard | héberger à part, partager à des tiers (attend `passerelle-auth`), publier | L |

**Ordre proposé** : J0, puis **J1 et J2 en parallèle**, parce qu'ils sont indépendants et que
chacun règle une douleur actuelle. Le chemin critique vers « ce que je produis est installé,
visible et entretenu » est J7 → J8 → J10 et J11. Le panneau et les gardiens avancent à côté,
sans le bloquer. La démonstration de Karim demande J2, J5 et J9 ; celle de Claire demande
J2, J5, J8, J10, les deux trous du §4 et le partage nommé.

## 6. À vérifier avant de construire

Chaque vérification prend moins d'une heure (`coherence-croisee.md` §4). Les cinq qui
conditionnent les premiers jalons :

1. **Passage par code dans une iframe** : le cookie `__Host-` de l'hôte des applications, une
   fois `frame-ancestors` élargi. C'est la démonstration de P0, à faire en premier.
2. **Hôte des applications joignable sur le pod** (`/_sante`).
3. **Chrome** : le Chrome lancé par tube peut-il aussi ouvrir un port de débogage local
   (`DevToolsActivePort`) ?
4. **MCP Apps** : état réel de la spécification et de l'hôte d'exemple du SDK, monté contre un
   serveur d'exemple.
5. **Compteur de coût** : le relais LLM reçoit-il un en-tête d'origine depuis chaque surface
   (`ANTHROPIC_CUSTOM_HEADERS`) ?

Faits déjà vérifiés dans le code :

- `frame-ancestors 'self'` bloque aujourd'hui le cadrage des créations ;
- le mandataire ne retire pas `X-Frame-Options` ;
- `/chrome/view` est servi dans l'origine de l'Atelier ;
- le fil réinsère ses nœuds à chaque rendu : aucune vue vivante ne doit s'y trouver ;
- les relais WS sont déjà fusionnés ;
- `X-Atelier-Conversation` est déjà posé.

## 7. Décisions pour Nicolas

**Urgente (une équipe travaille dessus en ce moment)**

- **U1. Le Chrome de l'agent appartient-il à l'Atelier ?** La branche `chrome-stdio` fait lancer
  Chrome par `chrome-devtools-mcp`, par un tube, avec un profil jetable. C'est sobre, mais la vue
  en direct devient impossible sans VNC, et la connexion (session du site) est perdue à chaque
  fin de processus.
  *Recommandation* : oui, par le chemin le moins coûteux et sans défaire le travail :
  - un port de débogage en plus, sur 127.0.0.1 ;
  - l'association conversation → profil ;
  - un profil gardé tant que la conversation vit.

  La supervision complète par l'Atelier viendra avec J6.

**Structurantes (tout le reste en dépend)**

1. **Pour qui est l'Atelier ?** Pour toi seul, ou aussi pour des personnes qui ne codent pas
   (Claire, Karim) ? Les documents techniques supposent le premier, le cadre promet le second.
   *Recommandation* : conçu pour les deux, construit d'abord pour toi. Le lexique et les défauts
   du §4 coûtent peu s'ils sont posés maintenant, et beaucoup à rattraper plus tard.
2. **Le lexique du §3** : l'adopter pour l'interface.
3. **Une seule file « À valider »** et **une politique d'accord** : celles du §4.

**Pour le premier jalon (J1, J2)**

| # | Question | Recommandation |
|---|---|---|
| a | Où tourne l'exécuteur des gardiens ? | Dans un processus à part, lancé comme le relais LLM ; il est aussi l'ordonnanceur unique. |
| b | Plafonds des tâches automatiques | 24 par jour par défaut, budget obligatoire, tâche créée par un agent désactivée à la naissance. |
| c | Dormant gate | La garder pour ce qui lance un agent ; les contrôles en code n'y sont pas soumis ; mesurer d'abord son effet réel. |
| d | Services du namespace (Blender, QGIS, n8n) : relayés ou encadrés à leur adresse ? | Relayés par l'hôte des applications. |
| e | Où s'épinglent les vues ? | Au projet dans `projet.json`, à la conversation dans sa fiche. |
| f | Le panneau s'ouvre-t-il tout seul ? | Oui pour une interface rendue par un outil et pour « Montrer », jamais pour un flux vivant. |
| g | `atelier-gardiens` : un dépôt à part ? | Oui ; il sert aussi de projet exemplaire. |

**Plus tard**, avec le jalon concerné (détail et recommandations : `coherence-croisee.md` §5.3,
`relecture-grand-public.md` §5) :

- partager à qui (comptes SSPCloud, lien signé, public) et qui fait la revue ;
- canal des notifications hors de l'Atelier ;
- unité de dépense affichée ;
- mode d'édition à la main pour les pages ;
- moteur et emplacement des modèles de projet ;
- hooks interdits dans une extension ;
- place de marché (plugins Claude Code, sous réserve de vérification).

## 8. Évaluation

| Critère | Verdict | Pourquoi |
|---|---|---|
| **Cohérente** | oui, une fois le schéma unifié appliqué | Les trois visions partagent l'hôte des applications, la règle « détecter en code, réparer par proposition » et les manifestes. Les contradictions sont de forme : vues en liste ou unique, rythme et budget sous trois formes, le mot « panneau », « gardien » agent ou non. Elles se règlent par `coherence-croisee.md` §1.2. |
| **Envisageable** | oui, par jalons de taille M | J0 à J2 réutilisent ce qui tourne déjà : hôte des applications, superviseur, relais, noVNC sur le pod, MCP Apps. Rien n'exige de réécrire l'Atelier. |
| **Souhaitable** | oui | Chaque jalon règle une douleur mesurée : onglets perdus, tâches invisibles, jetons en clair, CI rouge une semaine, dérive de contexte, wikichat tué. La table d'incidents de `gardiens.md` le montre. |
| **Désirable** | à condition du §3 et du §4 | Sans le lexique et les défauts, c'est un outil d'exploitant. Avec eux, la démonstration de 3 minutes n'a aucun mot technique, un seul écran d'accord, et la panne est réparée avant d'être vue. |
| **Possible** | oui pour toi dès J2 ; pour des tiers après `passerelle-auth` | Le partage à d'autres, l'hébergement à part et la publication dépendent d'une authentification et d'une revue qui ne sont pas encore là. |

## 9. Suites

- Appliquer aux documents d'équipe les corrections relevées (`relecture-grand-public.md` §5,
  `coherence-croisee.md` §1) une fois les décisions structurantes prises, pour ne pas les
  réécrire deux fois.
- Faire les cinq vérifications du §6 avant d'engager J2.
- Les défauts du §4 et le lexique du §3 alimenteront aussi la refonte de la vitrine : capacités,
  cas d'usage et associations de fonctions y trouvent leur récit.
