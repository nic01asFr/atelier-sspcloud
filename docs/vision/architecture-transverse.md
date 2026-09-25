# Architecture transverse de l'Atelier

Document vivant, ouvert le 25/09/2026 et tenu à jour à chaque retour d'équipe. **Proposition,
non implémentée**, sauf mention « existe ».

Il dégage ce que les chantiers ont en commun, pour que chacun se branche sur la même structure au
lieu d'en inventer une. Les chantiers couverts :

- les visions (panneau, écosystème, gardiens, Assistant, voix) ;
- les branches en cours (`chrome-stdio`, `secrets-arguments`, wikichat `atelier-coherence`,
  `deploiement-26-09`).

Chaque section suit le même plan :

- la structure retenue ;
- qui l'utilise ;
- ce qui existe déjà ;
- ce qui s'en écarte aujourd'hui.

## 0. Principe directeur (Nicolas, 25/09)

> Tout se base autant que possible sur les briques existantes, et elles sont nombreuses. Le
> travail consiste à les **structurer**, les **organiser** et les **rendre disponibles** de manière
> appropriée partout où elles peuvent être utiles.

Conséquences :

- Avant de concevoir une fonction, chercher la brique qui la porte déjà. Le catalogue du §5 la
  donne.
- Une brique cassée ou jamais armée se **répare et se branche**. On n'en écrit pas une autre à
  côté.
- Rendre une brique disponible, c'est l'exposer par les canaux communs, avec les mêmes règles
  d'accès et de journal (§1.4, §1.7) :
  - outil MCP ;
  - catalogue de commandes ;
  - API ;
  - hook de contexte ;
  - vue du panneau.
- **Deux maisons, deux rôles.**
  - **L'Atelier** tient l'**état opérationnel** :
    - conversations et tours ;
    - pool de connecteurs, secrets par référence ;
    - créations servies et superviseur, registre des promotions, accès ;
    - relais, navigateur, interface.
  - **wikichat** tient la **connaissance et la coordination** :
    - registre des projets, instantanés, cartographie et liens ;
    - audits ;
    - connaissance, idées, closures ;
    - mémoire de la personne ;
    - routines, triggers, pilote ;
    - messagerie, fils, hooks.
  - Chacun lit l'autre par API. Aucun ne recopie les données de l'autre.

## 1. Six structures communes

### 1.1 Les acteurs

Tout ce qui agit dans l'Atelier est l'un de ces six acteurs. Chacun a une identité, un profil
d'outils, un mode de permission et un budget.

| Acteur | Qui | Profil d'outils | Accords | Budget |
|---|---|---|---|---|
| **Personne** | la propriétaire, plus tard ses invités | interface | décide | forfait |
| **Assistant** | conversation `kind=assistant`, dossier `wikichat-memory` | noyau Assistant + catalogue (§1.5) | agit sur les objets de l'Atelier ; les gestes lourds passent par « À valider » ou par un accord explicite | par conversation |
| **Agent code** | conversation `kind=code` d'un projet | outils de fichiers, Bash, navigateur, `atelier_*` du projet | projet de la conversation | par conversation |
| **Agent lancé** | routine, trigger, proposition d'un gardien, délégation de l'Assistant | celui de sa mission, restreint | branche seulement, jamais `main` | plafond déclaré |
| **Gardien** | l'exécuteur, du code sans modèle | contrôles (JSON) | liste fermée de gestes | 0 jeton |
| **Application** | création en mode serveur | capacités déclarées puis accordées | registre des promotions | quotas |

Écarts actuels :

- L'Assistant n'existe pas encore comme acteur distinct : aujourd'hui, toutes les conversations
  sont des agents code.
- Les agents lancés par wikichat ne passent pas encore par l'Atelier (lot D).

### 1.2 L'identité d'un acteur

L'identité d'un acteur est une seule clé, que toutes les couches reprennent au lieu d'en créer une
chacune. Pour une conversation, c'est **`session_id`**. Il circule sous plusieurs noms :

| Couche | Porteur | État |
|---|---|---|
| Atelier (tours, fiches) | `ATELIER_SESSION` | existe |
| Serveur MCP `atelier` | en-tête `X-Atelier-Conversation` | existe |
| wikichat | nom `<slug>-<session[:6]>`, hooks, pont stdio | écrit sur `atelier-coherence` ; `.mcp.json` à changer (`deploiement-26-09`) |
| Navigateur | profil jetable et, plus tard, association conversation → profil | profil par processus ; association à faire (P5) |
| Hôte des applications | acteur du code de passage d'agent | à faire (`synthese.md`, navigateur) |
| Relais LLM (coût) | en-tête d'origine `X-Atelier-Origine` | à vérifier (A10) |
| Journal unique | champ `acteur` | à faire |

**Règle** : une couche qui a besoin de savoir « qui » lit cette clé. Elle ne crée pas son propre
identifiant. Une surface qui ne sait pas la transmettre (VS Code, terminal) l'obtient par le hook
`SessionStart`.

### 1.3 La carte de l'Atelier

C'est **un seul graphe d'objets et de liens, calculé par du code**. Aujourd'hui, quatre consommateurs
en ont besoin, et chacun en construisait une version à part :

| Consommateur | Ce qu'il en lit |
|---|---|
| Assistant | contexte synthétique toujours présent et détail à la demande (`assistant-contexte.md`) |
| Gardiens | l'inventaire à contrôler : créations, connecteurs, automates, ports, dépôts (`gardiens.md` G0) |
| Interface | accueil, catalogue « + » du panneau, vue projet, page Gardiens |
| wikichat | briefing de projet, présents, fils |

Contenu de la carte :

- **Objets** : projets, créations (avec leur version active), connecteurs, agents et
  conversations, tâches automatiques, services, vues.
- **Liens** : un projet utilise un connecteur ; une création sert un projet ; un agent travaille
  sur un projet ; un connecteur vient d'une création (F3) ; une tâche vise un objet.
- **État** : dernier contrôle, alertes, ce qui attend dans « À valider ».

Sources, sans double saisie :

- les deux manifestes (`projet.json`, `artefact.json`) ;
- le registre des promotions ;
- le pool de connecteurs ;
- les fiches de session ;
- l'inventaire des automates ;
- les résultats des gardiens.

La carte est **dérivée**. Personne ne l'écrit à la main, et une création ou une modification par
l'Assistant s'y reflète au calcul suivant.

**Deux couches, un seul point de lecture** (révisé après l'inventaire de wikichat, §5 ; remplace
la proposition « l'Atelier propriétaire » de `assistant-contexte.md` §1.3).

- **Couche projets et connaissance : wikichat**, qui en a déjà les briques.
  - Le registre des projets (`scan_projects`, `registry.json`).
  - Les instantanés git et fichiers, avec détection de changements toutes les 5 min
    (`snapshot.mjs`).
  - Les relations déclarées (`set_project_meta.relations`) et les proximités par dépendances
    (`run_clustering`).
  - La santé des dépôts (`audit_project`).
  - Les thèmes et la disposition (`run_cartography`, `map-generator`).
  - Les idées et leurs regroupements (`harmonize_ideas`).
  - Les axes de connaissance.
- **Couche opérationnelle : l'Atelier.**
  - Conversations et agents actifs.
  - Connecteurs utilisés par projet.
  - Créations, leur version active et leur exposition.
  - Accords.
  - Tâches automatiques de l'Atelier.
- **Assemblage.** wikichat publie le graphe des projets (`GET /api/cartographie`). L'Atelier
  l'assemble avec sa couche opérationnelle et sert la carte complète par `GET /api/carte` et
  l'outil `atelier_carte`. Il la recalcule après chaque commande réussie (§1.8), et wikichat
  recalcule sa couche après chaque instantané.
- **Lecteurs.** L'Assistant, l'interface, le panneau et l'exécuteur des gardiens lisent tous
  cette carte. Aucun ne tient d'inventaire à lui.

À corriger pour que la couche wikichat soit juste :

- **Liens.** Les ponts de `map-generator` sont codés en dur entre thèmes. Il faut les remplacer
  par les vrais liens : relations déclarées, clustering, connecteurs partagés.
- **Relations.** Croiser relations déclarées et clustering.
- **Crons.** Les crons de cartographie et de clustering lancent un agent LLM pour appeler une
  fonction JS : il faut appeler la fonction directement (§5, W3).

Taille mesurée pour l'Atelier de Nicolas :

- une carte naïve des 26 projets fait 3 497 caractères, soit environ 1 030 jetons ;
- plafond proposé pour la vue synthétique : environ 2 400 jetons.

### 1.4 Les accès

**Un vérificateur d'autorisations, plusieurs transports.** Toute ouverture d'un droit passe par la
même brique, qui journalise :

| Transport | Qui ouvre | Pour qui | État |
|---|---|---|---|
| Code de passage | session de la personne | navigateur de la personne vers l'hôte des applications | existe (`apps/passage.py`) |
| Code de passage d'agent | outil `atelier_navigateur_ouvrir` | navigateur d'un agent ou d'un gardien | à faire |
| Jeton de capacité | Atelier | application serveur, qui appelle l'Atelier | conçu (`atelier-hebergement.md` §4) |
| Pont de vue | panneau | vue MCP Apps, qui appelle un outil | conçu (`panneau.md` §3.3) |
| Références de secrets | Atelier | processus, par `${ATELIER_MCP_…}` et `claude-env.sh` | existe |

**Règles communes :**

- une portée (projet, conversation ou connecteur), une durée et un acteur ;
- rien ne donne jamais le cookie de l'Atelier lui-même à un agent ;
- aucun secret n'est visible par un modèle.

### 1.5 Les outils : un noyau et un catalogue

Le même problème se pose pour trois acteurs :

- l'Assistant, avec beaucoup de commandes ;
- l'agent code, qui paie 24 outils de navigateur, soit environ 5 700 jetons par appel ;
- l'agent lancé, qui doit être restreint.

Il n'y a pas de recherche d'outils native avec nos modèles.

Structure proposée : **un profil d'outils par type d'acteur, composé d'un petit noyau déclaré et
d'un catalogue**. Le catalogue offre trois actions (chercher, décrire, appeler), comme
`gateway_find_tools` et `gateway_call_tool` de la passerelle, qui existent déjà.

Le navigateur devient un candidat naturel au catalogue pour les agents qui ne s'en servent pas à
chaque tour. Les profils se déclarent au même endroit que les `.mcp.json` générés.

**Mesuré sur le pod** (`assistant-harness.md`, un essai par case : ce sont des indications, pas
des statistiques) :

- **Outils déclarés** : 21 bons choix sur 24, avec 12, 25 ou 50 outils ; aucun distracteur n'a
  été choisi.
- **Catalogue « chercher puis appeler »** : 6 réussites sur 9. Deux des échecs sont dangereux :
  une réponse de mémoire avec un détail inventé, et l'appel d'un outil sous un nom non déclaré.
- **Chargement par familles** : Claude Code 2.1.281 prend en compte `tools/list_changed` en
  cours de tour, et le modèle appelle l'outil ajouté.
- **Coût** : environ 100 jetons par commande sobre. Les 19 outils natifs coûtent environ
  15 700 jetons. Le pool entier de 293 outils coûterait environ 58 000 jetons (calculé).

Structure retenue, en trois étages :

1. **un noyau** déclaré par profil, d'une vingtaine d'outils ;
2. **des familles** d'outils que le serveur `atelier` ajoute ou retire selon la demande, par
   `list_changed` : c'est le mécanisme principal ;
3. **le catalogue** de la passerelle pour la longue traîne des connecteurs, **jamais pour une
   commande engageante**.

L'Assistant passe par une seule porte : le serveur `atelier` en profil `assistant`, qui compose
les outils `atelier_*`, un sous-ensemble de wikichat et la passerelle.

**Orientation de Nicolas (25/09) pour l'Assistant.** Il reçoit les méta-outils de l'Atelier et
atteint tout le reste par `gateway_find_tools` et `gateway_call_tool`, qui existent dans la
passerelle. Le garde de profil, le refus des noms inconnus et le rendu du schéma en cas d'erreur
y sont déjà. La classe d'action se vérifie côté serveur à l'appel. Le chargement par
`list_changed` n'est plus le mécanisme principal : il reste une option de `gateway_find_tools`
si la mesure H0, sur les vrais méta-outils, le justifie (`assistant-synthese.md` §4).

### 1.6 Les chemins

Trois chemins, et rien ne passe à côté :

1. **Affichage et flux** : hôte des applications, mandataire et relais WS. Il sert :
   - les pages et les applications ;
   - les bureaux noVNC et l'écran de Chrome ;
   - n8n ;
   - **la voix et la visio**, le service STT/TTS devenant une création serveur de l'Atelier et
     cessant d'être un port nu.
2. **Modèle** : relais LLM. Il porte :
   - la compaction (existe) ;
   - le coût par acteur (à venir) ;
   - les corrections d'adaptateur (existe : `usage`, erreurs, `tools: []`).
3. **Contexte vers les agents** : les hooks (`SessionStart` et `UserPromptSubmit` de wikichat)
   et `.atelier/contexte.md`. Ils portent :
   - l'identité et le briefing ;
   - le courrier ;
   - les alertes des gardiens ;
   - la ligne du panneau ;
   - la carte synthétique pour l'Assistant.

### 1.6 bis Contexte en couches et mémoire (`assistant-contexte.md`)

Ce modèle vaut pour tout acteur à modèle. Seuls les budgets changent d'un acteur à l'autre.

| Couche | Contenu | Canal | Qui calcule |
|---|---|---|---|
| C0 | harnais : outils du profil, system prompt | Claude Code | configuration |
| C1 | toujours présent : consignes, profil de la personne, vue synthétique de la carte, « À valider » | imports `@` du `CLAUDE.md`, relus après compaction ; le hook est coupé à 10 000 caractères | code |
| C2 | ce qui a changé depuis le dernier tour : courrier, alertes, état | hooks `UserPromptSubmit` et `SessionStart` ; 0 jeton s'il n'y a rien de neuf | wikichat, serveur |
| C3 | à la demande : détail d'un objet, fiches, décisions | outils bornés (`atelier_carte`, `atelier_rappel`, `atelier_fiche`) | code |

**Budget de l'Assistant** :

- partie fixe (C0 et C1) : 19 500 à 21 000 jetons, en estimation caractères / 3,4 ;
- compaction vers 90 000 jetons, sous la dérive observée à 105 000 ;
- 8 192 jetons réservés à la sortie.

**Capitalisation : dans wikichat, sur ses briques.** Le code fait le plus possible.

Ce qui existe déjà :

- les closures de projet (`close_project`) et leur absorption dans les axes de connaissance ;
- les axes eux-mêmes et `search_knowledge` ;
- les idées ;
- l'export assaini de la mémoire (`export-memory.mjs`, avec anti-secret), sa publication et le
  serveur MCP de mémoire à distance.

Ce qui manque et s'ajoute **dans wikichat** : la capitalisation des conversations complètes.

1. Le code extrait les faits d'une conversation, rattachés à son `session_id`. La source est le
   transcript filtré fourni par l'Atelier (T10).
2. Une routine plafonnée en tire le sens la nuit.
3. Le code range le tout en fiches, avec un index. C'est le même stockage et le même
   `search_knowledge` que les axes, pas un deuxième système.
4. L'Assistant retrouve le passé par une recherche bornée (environ 450 jetons), sans relire les
   transcrits.

Les mêmes briques produisent aussi, par projet et pour l'ensemble :

- les **synthèses** (closures, axes, digest) ;
- les **analyses** : audits, clustering, détection de changements ;
- la **journalisation** (instantanés, journal).

**Mémoire de la personne** :

- le modèle ne fait que **proposer** ;
- les propositions arrivent dans la file « À valider » (§1.7) ;
- la page « Ma mémoire » est la vue sur ce qui a été retenu ;
- le journal, la carte et les faits sont écrits par le code.

**Voix** : même `session_id` et même mémoire que l'écrit. Ce qui est réduit à l'oral, c'est la
sortie, pas la vue d'ensemble.

### 1.7 Automates, journal, validation

- **Ordonnancement : deux étages, sans doublon** (révisé après l'inventaire de wikichat).
  - **wikichat ordonne** les routines et triggers existants (cron, événements, webhooks, porte
    dormante, plafonds, pilote et sa file d'approbation), y compris les jobs déterministes de
    connaissance : cartographie, clustering, audits, harmonisation, capitalisation. Ces jobs
    appellent la fonction JS directement, sans agent (W3). Un lancement d'agent passe par
    l'Atelier (lot D).
  - **L'exécuteur des gardiens** reste un petit processus à part. Il n'exécute que les contrôles
    de santé et de sécurité de l'Atelier **et de wikichat**, car un gardien ne vit pas dans ce
    qu'il garde. Il n'est pas un second ordonnanceur généraliste.
  - L'inventaire des automates (page Gardiens) lit les deux.
- **Un journal** d'événements, lisible par la personne. Le « carnet de bord » des délégations et
  le « journal d'actions » de l'Assistant (`assistant-role.md`) sont des **vues filtrées** de ce
  journal : ce ne sont pas des stockages de plus. Il vit dans l'Atelier.
- **Une file « À valider »** : propositions des gardiens, des agents et des créations, et
  décisions en attente de l'Assistant.

### 1.8 Les commandes de l'Atelier

L'Assistant, l'interface et les agents agissent sur les objets de l'Atelier par **les mêmes
commandes**. La cible est un seul catalogue de commandes, exposé de trois façons :

- une API HTTP pour l'interface (existe en partie : projets, connecteurs, agents) ;
- des outils MCP pour l'Assistant et les agents (14 outils `atelier_*` aujourd'hui) ;
- le catalogue « chercher, décrire, appeler » de §1.5.

Chaque commande déclare dans sa définition, et non dans la consigne du modèle :

| Propriété | Rôle |
|---|---|
| `objet` | quel type d'objet de la carte elle touche (§1.3) |
| `classe` | `reversible` \| `engageante` \| `reservee` (`assistant-role.md` §3.6). Une commande engageante montre un aperçu puis attend « Oui » ; une commande réservée n'est jamais appelée par un modèle |
| `inverse` | la commande qui l'annule (base du bouton « Annuler ») |
| `resultat` | ce qu'elle rend : une carte d'action affichable, avec « Voir » et « Annuler », et une preuve de réussite |
| `regles` | ce qu'elle garantit (par exemple `projet_creer` pose la structure type et `projet.json`) |

Le vérificateur d'autorisations (§1.4) lit `classe`. Le journal (§1.7) enregistre chaque appel
avec son acteur (§1.2). La carte (§1.3) est recalculée après chaque commande réussie.

Critère pour qu'un acteur agisse seul plutôt que de confier le travail à un agent code
(`assistant-role.md` §3.2) : une commande existe ; elle touche un objet de l'Atelier et non le
contenu d'un dépôt ; elle est courte ; elle a une `inverse` ; elle rend une preuve.

## 2. Projets système

Trois projets appartiennent à l'Atelier lui-même. Ils suivent la structure type (`ETAT.md`,
`projet.json`, consignes) et servent d'exemples :

| Projet | Rôle | Acteur principal |
|---|---|---|
| `wikichat-memory` | domicile de l'Assistant (dossier non versionné, à dessein : alignement §10), mémoire de la personne, profil, synthèses ; publié en export assaini sur le dépôt GitHub du même nom | Assistant |
| `atelier-gardiens` | contrôles, seuils, décisions des gardiens | Gardiens (exécuteur) |
| `atelier` (le dépôt de l'Atelier) | le code de l'Atelier, travaillé par des agents code | Agents code |

Ils apparaissent dans la carte comme les autres projets, marqués « système ». Une personne grand
public ne les voit que par leurs effets : l'Assistant, la page Gardiens.

## 3. Tensions relevées

Ces tensions ont été relevées en lisant le code et les rapports. Chacune est à régler une fois,
au bon endroit.

| # | Tension | Où | Proposition | Qui |
|---|---|---|---|---|
| T1 | `~/.claude/settings.json` a trois auteurs : refus WebSearch et passage VS Code par l'Atelier, hooks par wikichat. Le miroir `~/work/.claude` ↔ `~/.claude` recopie le fichier **entier**, et la copie la plus récente gagne : les entrées d'un auteur peuvent être effacées | `claude_home.py`, `navigateur.py`, `vscode_handoff.py`, wikichat `overlay-installer.mjs` | un seul fichier physique (lien symbolique vers le volume durable), ou une fonction de fusion unique | **réglé** sur `deploiement-26-09` (a7af330) : lien, plus une fusion sans perte si un auteur l'a remplacé par un fichier ; bug démontré par un test. Reste côté wikichat : écrire à travers le lien |
| T2 | Le navigateur d'un agent ne peut pas ouvrir les créations de son projet (session d'applications requise) | `apps/passage.py` | code de passage d'agent (§1.4) | à ajouter au jalon J2 |
| T3 | Chrome par processus MCP, profil jetable, sans port : incompatible avec la vue en direct et avec « même Chrome sur toutes les surfaces » | `chrome-stdio` | point de bascule déjà prévu (`ATELIER_CHROME_WS`, fichier d'attache) ; supervision par l'Atelier à J6 | décidé plus tard |
| T4 | Le service vocal écoute sur `127.0.0.1:18920` sans authentification | `nouveau-projet-2/voice_service.py` | le déclarer en création serveur (`artefact.json`) : l'Atelier le lance et l'authentifie, et la visio passe par le chemin d'affichage | équipes Assistant et voix |
| T5 | Les `.mcp.json` du pod appellent wikichat avec `?agent=atelier` : identité générique | `mcp_sync.py` | transmettre `session_id` (§1.2) | **réglé** sur `deploiement-26-09` (4e92eb9) : pont stdio de wikichat ; à constater sur le pod |
| T6 | Le blocage des adresses privées du navigateur de la passerelle filtre les URL, pas les redirections | `navigateur-atelier.md` | acceptable tant que la passerelle ne sert que la personne ; mandataire filtrant avant tout tiers | noté |
| T7 | Quatre inventaires en construction : carte de l'Assistant, G0 des gardiens, catalogue « + », briefing wikichat | visions | une seule carte (§1.3) | à dire aux équipes Assistant |
| T8 | « Propositions » : trois files | écosystème, gardiens, structure-projet | une file « À valider » | décidé dans `synthese.md` |
| T9 | `/chrome/*` était servi dans l'origine de l'Atelier | `chrome_proxy.py` | **réglé** par `chrome-stdio` (routes retirées) | — |
| T10 | `atelier_transcript` et `atelier_suivre` rendent le texte brut d'une conversation : un secret affiché par un agent atteindrait l'Assistant, puis sa mémoire | outils `atelier_*` | filtrer à la source, dans le code, les valeurs connues de `claude-env.sh` (par empreinte, comme le gardien Sécurité) avant de rendre un transcript ; même filtre à la capitalisation | à faire avec le lot Assistant |
| T12 | La publication GitHub `wikichat-memory` a divergé : 28 commits d'avance, 3 de retard, 289 instantanés, 19 axes sur 42 en double. Elle est publiée depuis le poste par une tâche planifiée. Rappel : la décision du 02/09 (alignement §10) tient. Le dossier de l'Assistant n'est **pas un dépôt, à dessein**, et le dépôt GitHub n'est qu'une publication assainie de la mémoire | poste, `atelier-wikichat-alignment.md` | un seul éditeur de la publication (le wikichat du pod) ; réconciliation unique ; arrêt de la tâche du poste | Nicolas (exécution) |
| T13 | Le pool compte 293 outils, soit environ 52 000 jetons s'il était présenté en entier. Le plancher d'un agent code est de 21 695 jetons en entrée (mesuré au relais) | pod | confirme §1.5 : noyau et catalogue par profil, jamais le pool entier | équipe harness |
| T14 | Aucun `ETAT.md` dans les 26 projets du pod ; les hooks wikichat ne sont pas encore déployés | pod | la couche C2 est vide tant que le lot G (structure de projet) et le déploiement du 26/09 ne sont pas faits | lots G et `deploiement-26-09` |
| T11 | Oral lent : environ 11 s entre la fin de la parole et le premier mot (tranche STT de 3 s, puis 7,9 s jusqu'au premier jeton du modèle ; somme de mesures connues, non mesurée de bout en bout) | voix | accusé immédiat sans modèle ; réponses d'état calculées par le code à partir de la carte ; chemin rapide à instruire (équipe harness) | en cours |

## 5. Catalogue des briques

Ce qui existe, où ça vit, qui doit y accéder et par quel canal. Le catalogue sert à **brancher**,
pas à reconstruire. État :

- **marche** ;
- **partiel** : existe mais mal branché ;
- **dormant** : écrit, jamais armé ou en échec ;
- **manque**.

Sources :

- inventaire wikichat du 25/09 (branche `atelier-coherence`) ;
- code de l'Atelier ;
- rapports des équipes.

### 5.1 wikichat : connaissance, projets, coordination

| Brique | Code | État | Utile à | Canal à donner |
|---|---|---|---|---|
| Registre et scan des projets | `scan_projects`, `registry.json` | marche | carte, Assistant, gardiens | carte (§1.3) |
| Instantanés git/fichiers, détection de changements (5 min) | `snapshot.mjs`, événements sur #insights | marche | carte, hooks (C2), gardien Cohérence | carte et hook `UserPromptSubmit` |
| Relations entre projets | `set_project_meta.relations` | marche, non croisé | carte, Assistant | carte ; commande « lier deux projets » |
| Proximité par dépendances | `run_clustering` | dormant (dernier le 30/08) | carte | job direct (W3) |
| Cartographie (thèmes, disposition) | `run_cartography`, `map-generator` | partiel (ponts codés en dur, aucune page) | tableau de bord global | vue « Carte de l'Atelier » (§5.3) |
| Santé des dépôts | `audit_project`, `audit_all_projects` | marche, manuel | gardiens, carte, tableau de bord projet | job direct planifié ; lu par les gardiens |
| Axes de connaissance | `~/.wikichat/knowledge/*-axis.md` | partiel (écrits seulement par LLM ; trois lecteurs incohérents) | Assistant (C3), agents | `search_knowledge` réparé (W1) |
| Closures de projet et absorption | `close_project`, trigger #library | dormant (1 absorption) | capitalisation | commande « clore un projet » ; chemins du Closer corrigés (W5) |
| Idées et regroupement | `ideas.mjs`, `harmonize_ideas` | marche, manuel | Assistant, création de projet | job direct ; Bootstrapper (idée → projet cadré) = commande `projet_creer` de l'Atelier |
| Mémoire clé/valeur | `remember`, `recall` | partiel (dépend du dossier de lancement) | agents | stockage sous `~/.wikichat` (W2) |
| Export, publication, mémoire à distance | `export-memory`, `publish-memory`, `remote/memory-mcp-server` | marche sur le poste | Assistant, claude.ai | un seul éditeur : le pod (T12) ; c'est la publication, pas le domicile |
| Routines, triggers, pilote, file d'approbation | `routines.mjs`, `triggers.mjs`, `pilote.mjs` | marche ; plusieurs triggers en échec | tâches automatiques, gardiens (lecture) | onglet Automates ; étape `job` dans les routines (W3) ; « À valider » (§1.7) |
| Messagerie, fils, hooks, identité | `fils.mjs`, `hooks-serveur.mjs`, `conversations.mjs` | écrit, non déployé | tous les acteurs à modèle | hooks (§1.6) |
| Capitalisation des conversations | — | manque | Assistant, projets | ajout dans wikichat (§1.6 bis) |
| Tableaux de bord | — (seul `pilote.html` existe) | manque | personne, Assistant | vues du panneau (§5.3) |

### 5.2 Atelier : état opérationnel

| Brique | État | Utile à | Canal |
|---|---|---|---|
| Conversations, tours, fiches, harness | marche | tous | API, outils `atelier_*` |
| Pool de connecteurs, `.mcp.json` générés, secrets par référence | marche | tous les acteurs | profils d'outils (§1.5) |
| Créations : hôte des applications, superviseur, mandataire, relais WS | marche | panneau, gardiens, voix | chemin d'affichage (§1.6) |
| Codes de passage | marche (personne) ; manque (agent) | navigateur, gardiens | §1.4 |
| Relais LLM (usage, compaction, erreurs) | marche | tous les acteurs à modèle | chemin modèle |
| Navigateur stdio | écrit (`chrome-stdio`) | agents, Assistant, gardiens | profil d'outils ; catalogue |
| Passerelle : compositions, `gateway_find_tools` et `gateway_call_tool` | marche | catalogue (§1.5) | modèle du catalogue |
| Vérification de cohérence | marche | gardien Cohérence | contrôle |

### 5.3 Rendre disponible : tableaux de bord et vues

Les tableaux de bord n'ont pas besoin d'un système à part. Ce sont des **créations système**,
affichées comme vues du panneau et nourries par les API de la carte et de wikichat :

- **Atelier** : la carte (couches wikichat et Atelier), l'état des projets, les tâches
  automatiques, « À valider ». C'est aussi l'onglet « Aujourd'hui » de l'Assistant.
- **Projet** :
  - `ETAT.md` ;
  - santé (audit), changements récents (instantanés) ;
  - liens (relations, clustering) ;
  - conversations et agents ;
  - créations et leur santé ;
  - décisions.

L'Assistant les ouvre par `atelier_montrer` et les commente, à l'écrit comme à l'oral.

### 5.4 Remise en état de wikichat (lot W)

Chaque point répare ou branche une brique existante. Aucun n'en crée une nouvelle.

| # | Correction |
|---|---|
| W1 | Un seul lecteur de connaissance : les axes à plat de `~/.wikichat/knowledge/`, lus par `search_knowledge`, `/api/knowledge` et `wikichat://kb/{topic}` |
| W2 | Toutes les données sous `~/.wikichat/` (`memories.json`, `messages.json`, `fils.json`, `sessions/`, `projects/`), plus sous `process.cwd()` |
| W3 | Étape `job` dans les routines et action `job` dans les triggers, qui appellent directement cartographie, clustering, audits, harmonisation et instantanés. Fin des agents LLM qui appellent une fonction JS |
| W4 | Carte : vrais liens (relations, clustering, connecteurs partagés) au lieu des ponts codés en dur ; `GET /api/cartographie` |
| W5 | Closer : chemins à jour ; `close_project` sur un projet « à fichiers » ; absorption des closures réarmée |
| W6 | Triggers en échec : inventaire et décision pour chacun (Agent Finances, Synthèses-colaig, `evt-wake-any`, digest vers un Librarian désactivé) |
| W7 | Documentation : 53 outils, ressources réelles, `what_is` retiré ou écrit |
| W8 | Capitalisation des conversations (§1.6 bis) |

## 4. Journal de cohérence

Le journal consigne, dans l'ordre, ce que chaque retour a changé dans la structure.

- **25/09, visions** :
  - panneau, écosystème et gardiens se rejoignent sur l'hôte des applications, les deux
    manifestes et « détecter en code, réparer par proposition » ;
  - la relecture de cohérence fusionne les doublons (§1.4, §1.7) ;
  - la relecture grand public fixe le lexique.
- **25/09, `chrome-stdio`** :
  - le navigateur passe en stdio par conversation ;
  - T9 est réglé ;
  - T3 est ouvert, avec son point de bascule ;
  - WebFetch est réparé par le relais, ce qui confirme le relais comme chemin unique du modèle.
- **25/09, wikichat `atelier-coherence`** :
  - l'identité par `session_id` et les hooks deviennent le chemin du contexte (§1.2, §1.6) ;
  - T5 est ouvert côté Atelier ;
  - T1 est découvert.
- **25/09, précisions de Nicolas** :
  - l'Assistant est la porte d'entrée : acteur distinct (§1.1), outils en noyau et catalogue (§1.5),
    domicile système (§2) ;
  - la voix passe par le chemin d'affichage (§1.6, T4) ;
  - le navigateur devient une brique interne (T2).
- **25/09, `assistant-role.md`** :
  - les commandes deviennent une structure commune (§1.8), avec classe d'action, inverse, carte
    d'action et preuve ;
  - le carnet de bord et le journal d'actions sont fondus dans le journal unique (§1.7) ;
  - T10 (transcripts non filtrés) et T11 (latence orale) sont ouverts.
- **25/09, `assistant-contexte.md`** :
  - la carte a un propriétaire, l'Atelier, et une taille mesurée ;
  - le contexte en couches C0 à C3 et la capitalisation par le code deviennent communs (§1.6 bis) ;
  - les propositions de mémoire rejoignent « À valider » ;
  - T12 (dépôt mémoire divergent), T13 (293 outils) et T14 (couche C2 vide) sont ouverts.
- **25/09, inventaire de wikichat et principe de Nicolas** (§0, §5) :
  - wikichat porte déjà la plupart des briques de connaissance, de graphe, de capitalisation et
    d'ordonnancement, souvent mal branchées ;
  - la carte devient deux couches (wikichat pour les projets et la connaissance, l'Atelier pour
    l'opérationnel), assemblées en un point ;
  - la capitalisation des conversations s'ajoute dans wikichat ;
  - l'exécuteur des gardiens se limite à la santé et à la sécurité ;
  - les tableaux de bord deviennent des vues système ;
  - lot W de remise en état.
  - T12 s'explique (voir ci-dessous).
- **25/09, `assistant-harness.md`** :
  - le §1.5 passe à trois étages (noyau, familles par `list_changed`, catalogue pour la longue
    traîne), sur mesures ;
  - la latence orale de 7,9 s ne se reproduit pas : 0,7 s jusqu'au premier jeton avec
    `qwen3-6-35b-moe`. T11 se resserre donc sur la tranche STT et sur l'effort `xhigh` imposé
    sur le pod, qui reste à mesurer ;
  - `qwen3-cursor` n'est plus servi ;
  - un harness sans outils reçoit une erreur 400.
- **Explication de T12** : sur le poste, une tâche planifiée publie la mémoire toutes les 15 min depuis
    `Github Repositories/wikichat`, pendant que le dépôt évolue ailleurs.
