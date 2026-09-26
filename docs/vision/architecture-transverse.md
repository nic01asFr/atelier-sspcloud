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
| Journal unique | champ `acteur` (`conversation:<session_id>`, `personne`, `cle-proprietaire`, `client-distant`, `gardien:<nom>`) | existe (vague 1, `commandes/journal.py`) |

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
  l'assemble avec sa couche opérationnelle et sert la carte complète par `GET /v1/carte` et
  l'outil `atelier_carte`. Il la recalcule après chaque commande réussie (§1.8), et wikichat
  recalcule sa couche après chaque instantané. **Existe** (vague 2, équipe C) : contrat
  ci-dessous.
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

#### Carte : ce qui existe (vague 2, équipe C, branche `v2-carte`)

**Existe.** Deux modules :

| Module | Rôle |
|---|---|
| `atelier/carte.py` | lecteurs de la couche Atelier, assemblage avec wikichat, formes, cache (`Carte`) |
| `atelier/commandes/carte.py` | commande `atelier_carte`, route `GET /v1/carte`, crochet d'invalidation |

Branchés par une ligne dans `commandes.enregistrer` (`inscrire_la_carte(app, catalogue)`), plus
les mots d'intention de `atelier_carte` dans `tool_search.MOTS_CLES_PAR_OUTIL`.

**Sources, lues là où elles vivent, sans double saisie** :

| Couche | Source | Lecteur |
|---|---|---|
| projets de l'Atelier | `ProjectStore.list_projects(include_archived=True)`, `.atelier/projet.json` (`structure.lire`) | `lire_projets` |
| connecteurs choisis | `.atelier/connecteurs-choisis.json`, sinon héritage du pool (`mcp_sync.herite_du_pool`) | `connecteurs_choisis` |
| pool | noms des connecteurs activés de `gateway.db` (jamais leurs réglages, qui portent des secrets) | `lire_pool` |
| créations | `ServiceApps.lister_tout()` : mode et état au superviseur | `lire_creations` |
| conversations | fiches non rangées, `Harness.tour_en_cours` | `lire_conversations` |
| « À valider » | commande `atelier_a_valider` (file et pilote wikichat) | par le catalogue |
| tâches automatiques | gardiens `GET 127.0.0.1:8791/automates` (inventaire G0) | HTTP |
| alertes ouvertes | gardiens `GET 127.0.0.1:8791/alertes` | HTTP |
| projets, liens, santé, `ETAT.md` | wikichat `GET 127.0.0.1:3777/api/cartographie` (contrat `version: 1`) | HTTP |

Adresse des gardiens : `ATELIER_GARDIENS_URL`, sinon `http://127.0.0.1:${ATELIER_GARDIENS_PORT:-8791}`.
Délai HTTP : 5 s. Les textes venus de wikichat, des gardiens et des fiches passent par le filtre
du journal unique (`FiltreDesSecrets` : valeurs de `claude-env.sh`, clés au nom de secret).

**Accès.**

- `GET /v1/carte?forme=synthetique|complete|projet&projet=<slug>&rafraichir=true` : `projet`
  seul vaut `forme=projet` ; sans rien, la forme synthétique. 200 avec la forme ; 403 hors
  profil ; 422 pour une forme ou un projet inconnus. Même authentification que `/v1/commandes`.
- `atelier_carte {forme?, projet?, rafraichir?}` : classe `lecture`, objet `carte`. La route
  passe par cette commande, donc par les mêmes gardes. Elle n'est pas dans
  `OUTILS_DU_PROFIL_CODE` : un agent code ne la voit ni ne l'appelle, par `/mcp`,
  `/v1/commandes` ou `/v1/carte`, même en annonçant `assistant`. L'Assistant la reçoit. Sans
  conversation, le comportement de compatibilité des profils s'applique (tout).

**Cache.** Un calcul est gardé 20 s (`DELAI_CACHE_S`). Toute commande réussie qui agit (classe
autre que `lecture`) l'invalide par `Catalogue.apres_commande` ; `rafraichir=true` force le
calcul. Mesuré sur le pod : 0,3 s par calcul.

**Forme complète** : le graphe de wikichat, étendu.

```json
{"forme": "complete", "version": 1, "calcule_le": "…", "duree_s": 0.3,
 "sources": {"atelier": {"etat": "ok", "notes": {}},
             "wikichat": {"etat": "ok|absent|erreur", "calcule_le": "…", "noeuds": 39, "aretes": 281, "detail": "…"},
             "gardiens": {"etat": "ok|absent|erreur"}, "a_valider": {"etat": "ok", "note": "…"}},
 "resume": {"projets": 10, "projets_actifs": 8, "projets_ranges": 13, "hors_atelier": 16,
            "connecteurs": 10, "creations": 7, "creations_en_marche": 0, "conversations": 54,
            "conversations_en_cours": 0, "automates": {"actif": 17, "…": 0},
            "alertes": {"alerte": 2, "attention": 16}, "a_valider": 0},
 "noeuds": ["…"], "aretes": ["…"], "groupes": ["… de wikichat"], "alertes": ["…"],
 "a_valider": ["…"], "limites": {"… de wikichat": 0}}
```

Un compte à `null` dans `resume` veut dire « inconnu » (source absente), pas zéro.

Nœuds (`type`) :

| `type` | `id` | Champs |
|---|---|---|
| `projet` | slug (celui de wikichat) | tous les champs du contrat wikichat (`null` si wikichat ne le connaît pas, `origine: ["atelier"]`, `statut: "atelier"`), plus `atelier` |
| `creation` | `creation:<slug>/<nom>` | `projet`, `nom`, `titre`, `mode` (`autonome`, `serveur`, `invalide`), `etat` (superviseur, `statique`, `invalide`) |
| `conversation` | `conversation:<session_id>` | `session_id`, `projet`, `kind`, `titre`, `etat`, `en_cours`, `maj`, `tours` |
| `connecteur` | `connecteur:<nom>` | `nom`, `au_pool`, `projets` (nombre) |
| `automate` | `automate:<id G0>` | `genre`, `etat`, `titre`, `proprietaire`, `budget` (booléen), `plafond_par_jour`, `lancements`, `derniere`, `prochaine` |

Le champ `atelier` d'un nœud projet (réservé par wikichat) : `null` pour un dossier que wikichat
connaît mais qui n'est pas un projet de l'Atelier ; sinon

```json
{"type": "code|assistant", "titre": "…", "systeme": false, "range": false,
 "projet_json": "valide|absent|invalide", "gabarit": "vide", "deploiement": {"pod": "…", "service": null, "gpu": false},
 "vues_epinglees": 0, "connecteurs": {"herite_du_pool": false, "choisis": ["grist"]},
 "creations": {"total": 1, "en_marche": 0, "en_echec": 0},
 "conversations": {"total": 1, "en_cours": 0, "derniere": "…"},
 "a_valider": 1, "alertes": 1, "derniere_activite": "…", "actif": true}
```

`actif` : non rangé, et touché depuis 14 jours (conversations, dernier commit, `ETAT.md`,
fiche du projet), ou une conversation en cours, une création en marche, une alerte ou une
proposition. `systeme` : `atelier`, `atelier-gardiens` et le dossier de l'Assistant.

Arêtes : celles de wikichat (`relation`, `proximite`) restent telles quelles. Ses
`meme_connecteur` sont corrigées (correctif du 26/09, après essais) : un lien « même
connecteur » ne compte que les connecteurs **choisis explicitement** par les deux projets
(`connecteurs.choisis`), jamais l'héritage du pool, ni les connecteurs communs. wikichat lit
`.mcp.json`, où l'héritage ne se distingue pas d'un choix : entre deux projets de l'Atelier, le
lien est recalculé ; entre un projet de l'Atelier et un dossier qu'il ne connaît pas, il ne garde
que les choix du premier ; un lien vide est retiré (181 liens sur le pod, presque tous nés du
pool blender, github, gitlab, llm, qgis). L'Atelier ajoute, au même format (`id`, `type`, `de`,
`vers`, `oriente`, `source`) :

| `type` | De → vers | `source` |
|---|---|---|
| `sert` | création → projet | `artifacts` |
| `travaille_sur` | conversation → projet | `fiches` |
| `utilise` | projet → connecteur | `connecteurs-choisis`, ou `pool` quand le projet hérite |
| `meme_connecteur` | projet ~ projet, s'il manque chez wikichat | `atelier` (connecteurs choisis par les deux, hors héritage du pool et connecteurs communs) |

`de` et `vers` sont toujours des `id` de `noeuds`.

`alertes[]` : `{empreinte, gardien, controle, niveau, objet, resume, depuis, compte, vise}` ; la
preuve reste chez les gardiens. `vise` est l'objet de la carte visé quand on sait le dire
(`automate:<id>`, ou le slug d'un projet trouvé dans l'objet ou dans un chemin
`/projects/<slug>` de la preuve), sinon `null`. `a_valider[]` : `{id, source, titre, projet, creee_le}`.

**Forme projet** : `{forme, projet, calcule_le, sources, noeud, creations, conversations (5 plus
récentes), conversations_non_montrees, liens (12 au plus : relation, puis proximité par poids,
puis connecteur partagé ; `{projet, type, poids?, sous_type?, sens?, connecteurs?}`), alertes,
a_valider}`.

**Forme synthétique** : `{forme, calcule_le, sources, texte, taille: {caracteres,
unites_estimees, plafond_unites: 2400}}`. Le texte fait au plus 8 000 caractères (moins de
2 400 unités à 3,4 caractères) : en-tête chiffré, état des sources, une ligne par projet actif
(âge, conversations, créations, connecteurs, `ETAT.md`, déploiement, alertes, à valider, santé
sous 50, trois liens), puis dormants, dossiers hors Atelier, tâches wikichat sans budget, alertes
graves, décompte des autres, « À valider ». Au-delà du budget, les actifs les moins récents se
replient en dormants, puis les listes de noms raccourcissent. Sans wikichat, le texte le dit et ne
prétend rien sur `ETAT.md`.

**Mesuré sur le pod** (26/09, lecture seule : le module chargé en mémoire dans le noyau du
connecteur Onyxia, contre les vraies API de wikichat et des gardiens ; aucune écriture ; le
pilote de wikichat non lu, faute de clé ; états des créations serveur lus dans `apps.json`) :

- 26 dossiers sous `projects/` : 3 dossiers d'agent (`.atelier-agent`), 13 projets rangés,
  10 projets affichés (8 actifs), dossier de l'Assistant compris ; 39 nœuds wikichat dont 16
  hors Atelier ; 54 conversations ; 10 connecteurs ; 38 tâches automatiques ; 18 alertes ;
- forme synthétique : **2 369 caractères, 697 unités** ; pire cas sur les mêmes données, les
  23 projets affichés et actifs : 4 704 caractères, 1 384 unités ;
- forme projet (`projet-sans-nom-5`) : 4 415 caractères ; forme complète : 190 967
  caractères (149 nœuds, 521 arêtes) ;
- calcul : 0,3 s.

**Ce qui reste** :

- le fichier `atelier/carte.md` importé par le `CLAUDE.md` de l'Assistant (C1, vague 3) : il
  s'écrit à partir de la forme synthétique ;
- `wikichat` peut lire `GET /v1/carte?projet=<slug>` pour son briefing (clé du propriétaire
  requise aujourd'hui) ;
- invalidation sur événement hors commande (fin de tour, résultat de gardien) : le délai de
  20 s la couvre ;
- les accords (§1.4) et les vues ne sont pas encore sur la carte ;
- les liens `a_delegue` et `lance` (`assistant-contexte.md` §3.2) attendent le lot D ;
- l'exécuteur des gardiens ne lit pas encore la carte pour son inventaire (il a le sien, G0,
  que la carte reprend).

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

#### Mémoire : ce qui existe (vague 3, équipe M, branches `v3-memoire`)

**T10 réglé à la source.** `mcp_gateway/atelier/filtre_transcripts.py` réutilise
`FiltreDesSecrets` du journal unique, sans coupe ni masque par nom de clé : les valeurs de
`~/work/.secrets/claude-env.sh` et des fichiers d'une ligne de `~/work/.secrets/` deviennent
leur empreinte (`<secret:0123456789ab>`, comme le journal des gardiens), y compris sous leur
forme échappée JSON ; les motifs de jetons du gardien Sécurité deviennent `<jeton masqué>`.
Il s'applique à **toute** charge rendue par un outil `atelier_*` (`OutilsAtelier.appeler` :
`atelier_transcript`, `atelier_suivre`, `atelier_conversations`, erreurs comprises), à
`GET /v1/sessions/{id}/transcript` (le JSON reste lisible), au fil d'un agent du pilote
(`GET /v1/agent/{id}/transcript`) et à tout ce que l'Atelier fournit à la capitalisation.
Non filtré : le flux en direct d'un tour vers l'écran de la personne (SSE), qui n'est lu par
aucun modèle.

**Frontière avec wikichat** (`mcp_gateway/atelier/memoire.py`), clé du lanceur
(`X-Atelier-Lanceur`) ou propriétaire :

| Route | Rôle |
|---|---|
| `GET /v1/memoire/conversations?repos_min=30` | les conversations : projet, genre (`assistant` ou `code`), état, `au_repos`, `empreinte` (change quand elle grandit). Les lancements de la routine de nuit (`wikichat:memoire:*`) en sont exclus |
| `GET /v1/memoire/conversations/{id}` | le transcript **filtré et réduit** (lecture seule, par `fondre`, sans l'absorption qui écrit) : paroles de la personne, textes du modèle, outils (nom et quelques champs d'entrée, chemins relatifs), erreurs (300 caractères), fins de tour et leurs jetons. Jamais le contenu d'un résultat d'outil. Accepte l'identifiant du CLI |
| `POST /v1/memoire/propositions` | une préférence, un trait du profil ou une interprétation proposés par un modèle : « À valider », source `memoire`, action `atelier_memoire_retenir`. Trois par conversation au plus, doublons ignorés, texte filtré |

**Commandes** (`commandes/rappel.py`, une ligne dans `commandes/enregistrer`) :

| Commande | Classe | Profil | Ce qu'elle garantit |
|---|---|---|---|
| `atelier_rappel(requete, projet?, depuis?, limite?)` | lecture | assistant ; **code : son projet** | au plus 5 fiches, une ligne chacune (identifiant court, date, projet, titre, résumé), **≤ 1 530 caractères, soit ≈ 450 jetons** (caractères / 3,4) |
| `atelier_fiche(id)` | lecture | assistant ; **code : son projet** | une fiche, 2 500 caractères au plus ; l'identifiant court de 8 caractères suffit ; une fiche d'un autre projet est introuvable |
| `atelier_memoire` | lecture | assistant | profil, préférences, interprétations, faits, propositions en attente |
| `atelier_memoire_proposer(type, texte, raison?)` | reversible (inverse : `atelier_a_valider_refuser`) | assistant | ne retient rien : dépose dans « À valider » |
| `atelier_memoire_retenir`, `_corriger`, `_oublier` | **reservee**, non exposées en MCP | la personne | écrivent chez wikichat ; chacune a son inverse (oublier ↔ retenir, corriger ↔ corriger) |

En profil `code`, `atelier_rappel` et `atelier_fiche` sont dans `OUTILS_DU_PROFIL_CODE` ; le
projet vient de la conversation (`cadrer_les_arguments`), un autre projet est refusé avant
tout appel à wikichat, et le résultat est refiltré par projet. Mots d'intention dans
`tool_search.MOTS_CLES_PAR_OUTIL`.

**Vue « Ma mémoire »** (`web/js/views/memoire.js`, onglet de la navigation) : qui vous êtes,
vos préférences, ce que l'Assistant a compris, faits retenus d'office ; « d'où ça vient » sur
chaque ligne ; « Corriger » (champ en place) et « Oublier » (avec confirmation), par les
commandes réservées ; renvoi vers « À valider » pour les propositions en attente.

**Côté wikichat** (`src/memoire/`, `docs/atelier-coherence.md` §14) : faits extraits par le
code toutes les 15 min et à la fin d'une conversation ; fiches
`~/.wikichat/knowledge/conversations/<projet>/<id>.md` et leur index, lues par
`search_knowledge` (profil `code` : son projet) ; routine de nuit par des lancements de
l'Atelier (20 × 30 000 jetons au plus, `qwen3-8-27b`, mode `dontAsk`, sans autorisation
d'outil), trigger né désactivé ; mémoire de la personne (`memoire/personne.json`) avec les
faits enregistrés d'office ; export assaini qui inclut les fiches (S6).

**Mesuré sur le pod** (lecture seule, 26/09) : 54 conversations de l'Atelier, toutes d'agent
code, 44 d'au moins 3 échanges ; registres de 3,4 Mo en moyenne (14,7 Mo au plus) ; entrée
préparée de 47 000 caractères en moyenne (≈ 13 800 jetons), 209 000 au plus ; environ 4,5
conversations par jour. Nuit estimée à ≈ 35 000 jetons par conversation (entrée ≤ 17 000,
plus le harnais d'un agent code, 21 695), soit ≈ 0,7 M pour chacune des deux nuits de
rattrapage et ≈ 120 000 en régime.

**Écart à A-7** : le lot D refuse un message de plus de 60 000 caractères ; l'entrée effective
est donc plafonnée à 58 000 caractères (≈ 17 000 jetons), pas à 30 000 jetons. 15
conversations du pod sont raccourcies au milieu. Voir « En attente » dans `decisions.md`.

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
- **État (vague 1)** : le journal et la file existent, avec leur API ; leurs contrats sont
  au §1.8 (« Commandes : ce qui existe »).
- **État (vague 2, équipe V)** : l'écran « À valider » (onglet de la navigation, badge du
  nombre en attente relu toutes les 30 s ; détail, ce qu'accepter fera, précisions demandées
  par un agent du pilote ; Accepter, réservé à la personne par le catalogue ; Refuser en un
  clic, motif facultatif) et le journal (onglet, phrases en langage humain, filtres projet,
  acteur, source) existent, sur les API ci-dessus. Les propositions d'un agent du pilote,
  tranchées depuis sa fiche, passent aussi par `/v1/a-valider/<id>/decision`. L'inventaire des
  automates n'est plus une page : c'est la liste « Tâches automatiques » de la vue Agents
  (`GET /v1/automates`, `mcp_gateway/atelier/automates.py`) ; activer une tâche y est réservé à la
  personne (J-b2), côté serveur. Les accords réservés de l'équipe K ont leur écran : « Activer »
  sur un agent désactivé (fiche, menu, liste des tâches) appelle `atelier_agent_activer`, et
  « Désactiver » son inverse ; « Accorder un secret » (vue Connecteurs) liste les noms de
  `GET /v1/secrets/noms` (`accords.py` : la personne seule, jamais une valeur, ni les secrets de
  l'Atelier lui-même) et appelle `atelier_connecteur_accorder` ; une proposition qui porte l'une
  d'elles s'accepte par « À valider ». Les agents lancés par l'Atelier (équipe L) ont leur
  section « En cours et récents » dans la vue Agents (`GET /v1/lancements`) : origine en mots
  (réveil, tâche automatique, gardien réparateur), projet, état, durée, branche, « Arrêter »
  (`POST /v1/lancements/<id>/arreter`) et, pour un réparateur, « Voir sa proposition ». Après un
  changement de mode, la note de `GET /v1/sessions/{id}/processus` s'affiche sous la saisie,
  avec l'écart si l'onglet VS Code vivant est plus permissif. Écrit et testé contre le contrat, avec de fausses
  commandes au même nom et à la même classe, avant la fusion de `v2-creations`. Reste : les
  gestes des gardiens et des tâches de la plateforme passent encore par
  `POST /v1/automates/action`, hors catalogue.

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

#### Commandes : ce qui existe (vague 1, équipe F, branche `fondations`)

**Existe.** Le catalogue vit dans `atelier-src/mcp_gateway/atelier/commandes/` :

| Module | Rôle |
|---|---|
| `modele.py` | `Commande` (`nom`, `objet`, `classe`, `inverse`, `regles`, `schema`, `executer`, `apercu`, `allegement`, `exposee_mcp`), `Effet`, `Contexte` |
| `catalogue.py` | la porte unique : vérification de classe, jetons de confirmation, carte d'action, journal |
| `existants.py` | les 14 outils `atelier_*` d'avant, déclarés sans changer de nom ni de code |
| `natives.py` | projets, conversations, « À valider », journal, annuler |
| `journal.py` | le journal unique (§1.7) |
| `a_valider.py` | la file « À valider » (S3) |
| `structure.py` | schéma de `projet.json` et gabarit de projet (lot G) |
| `routes.py` | `/v1/commandes`, `/v1/journal`, `/v1/a-valider` |

Branché par une ligne dans `api.py` (`enregistrer_les_commandes(app)`) ; `gateway_runtime.py` donne le
catalogue à la passerelle comme famille d'outils locaux.

**Classes.** `lecture` s'ajoute aux trois classes, pour ce qui ne change rien (lister, lire) : ni
carte, ni ligne au journal (un `atelier_suivre` toutes les trente secondes le noierait).

| Classe | Appel d'un modèle (MCP, ou clé du propriétaire en HTTP) | Appel de la personne (session de l'interface) |
|---|---|---|
| `lecture` | exécutée | exécutée |
| `reversible` | exécutée ; carte avec « Annuler » | idem |
| `engageante` | **aperçu + jeton**, rien n'est fait ; rappel avec `confirmation` = jeton | idem ; ou `POST /v1/commandes/confirmer` sur le jeton d'un agent : c'est son « Oui » |
| `reservee` | **refusée** | exécutée |

La vérification a lieu dans `Catalogue.executer`, à chaque appel. `gateway_call_tool` repasse par
`McpGateway.tools_call`, donc par le catalogue : il ne contourne rien (testé). La clé du
propriétaire n'est pas « la personne » : les agents du pod la lisent. Le jeton ne vaut qu'une
fois, dix minutes, pour la même commande, les mêmes arguments et le même acteur (la personne peut
confirmer celui d'un agent). `Commande.allegement` peut rendre un appel plus léger selon ses
arguments, jamais plus lourd : `atelier_decider` avec `deny` est réversible (A-5, refuser seul),
avec `allow` engageant.

**Schéma publié d'une commande** (`GET /v1/commandes`, et `_meta["atelier/commande"]` des outils MCP) :

```json
{"nom": "atelier_projet_creer", "description": "…", "objet": "projet", "classe": "reversible",
 "inverse": "atelier_projet_ranger", "regles": ["slug unique, dérivé du titre", "…"],
 "schema": {"type": "object", "properties": {"…": {}}}, "exposee_mcp": true}
```

**Résultat d'une commande qui agit** : la charge de la commande, plus une `carte` construite par
elle (jamais rédigée par le modèle) :

```json
{"carte": {"titre": "Projet créé", "resume": "…", "voir": {"libelle": "Voir", "lien": "/?slug=carte"},
  "annuler": {"libelle": "Annuler", "commande": "atelier_annuler", "arguments": {"action": "<id>"},
              "inverse": "atelier_projet_ranger"},
  "preuve": {"commit": {"commit": "…", "message": "Ouvrir le projet"}, "…": "…"},
  "action": "<id du journal>", "par": "conversation:<session_id>", "quand": "…"}}
```

HTTP : `POST /v1/commandes/<nom>` `{arguments, confirmation?}` rend
`{statut: fait|apercu|refus|erreur, action, resultat}` (200, 200, 403, 422).

**Les commandes** (`GET /v1/commandes` fait foi) :

| Commande | Classe | Inverse | État |
|---|---|---|---|
| `atelier_projets`, `atelier_conversations`, `atelier_suivre`, `atelier_transcript`, `atelier_artefacts`, `atelier_artefact_journal`, `atelier_artefact_verifier` | lecture | — | existent (enrobées) |
| `atelier_ouvrir` | reversible | `atelier_conversation_ranger` | existe (enrobée) |
| `atelier_envoyer` | reversible | `atelier_interrompre` | existe (enrobée) |
| `atelier_interrompre` | reversible | — (arrêter ne défait rien) | existe (enrobée) |
| `atelier_decider` | engageante (`deny` : reversible) | — | existe (enrobée) |
| `atelier_artefact_creer` | reversible | — (pas de suppression d'artefact) | existe (enrobée) |
| `atelier_artefact_demarrer` / `_arreter` | reversible | l'une l'autre | existent (enrobées) |
| `atelier_projet_creer`, `_modifier`, `_ranger`, `_ressortir` | reversible | `_ranger` ; valeurs d'avant ; `_ressortir` ; `_ranger` | existent |
| `atelier_projet_publier` | reservee (non exposée en MCP) | — | existe |
| `atelier_conversation_ranger` / `_ressortir` | reversible | l'une l'autre | existent |
| `atelier_a_valider` | lecture | — | existe |
| `atelier_a_valider_refuser` / `_rouvrir` | reversible | l'une l'autre | existent |
| `atelier_a_valider_accepter` | reservee (non exposée en MCP) | — (l'action exécutée a sa propre carte) | existe |
| `atelier_journal` | lecture | — | existe |
| `atelier_annuler` | reversible | — | existe : applique l'inverse notée au journal, une seule fois |
| `atelier_montrer`, `atelier_navigateur_ouvrir` (équipe P) | lecture ; reversible | — | déclarées d'avance, annoncées dès que P les sert |

Un outil `atelier_*` servi par `outils_conversation.py` sans déclaration passe en `reversible`,
`objet: non_declare`, et le journal le montre. Pour en déclarer un :
`catalogue.declarer_outil(nom, DeclarationOutil(objet, classe, inverse, regles, carte))`.

Les descriptions de `atelier_artefacts` et voisins portent les mots de l'interface (« création »,
« page », « application », « ce que j'ai fabriqué ») et disent qu'une composition est autre chose
(mesure E1 : « créations » menait aux compositions, 0 sur 6).

**Journal unique** (§1.7, `coherence-croisee.md` §2) : `~/work/.atelier-etat/journal/AAAA-MM.jsonl`,
une ligne par événement :

```json
{"id": "20260925-3fa9c1d2e4", "quand": "2026-09-25T14:02:11.412+00:00", "source": "commande",
 "acteur": "conversation:<session_id>", "objet": {"type": "projet", "id": "carte"},
 "action": {"commande": "atelier_projet_creer", "classe": "reversible", "origine": "mcp",
            "via": "gateway_call_tool", "arguments": {}, "avant": null, "apres": {},
            "inverse": {"commande": "atelier_projet_ranger", "arguments": {"projet": "carte"}}},
 "resultat": "fait|apercu|refus|erreur", "cout": {"jetons": 0, "secondes": 0.41}, "empreinte": "…"}
```

`source` ∈ `commande`, `controle`, `capacite`, `promotion`, `vue`, `automate`, `geste`,
`validation` ; toute autre est refusée. Écriture par `Journal(dossier).ecrire(Evenement(...))`,
utilisable hors du service (l'exécuteur des gardiens). Aucune valeur secrète : une clé dont le nom
annonce un secret est masquée, et toute valeur de `claude-env.sh` est remplacée par `[secret]`
partout où elle apparaît. Lecture : `GET /v1/journal?depuis&source&acteur&objet_type&objet&commande&limite`,
ou l'outil `atelier_journal`. `atelier/journal.py` (fusion des registres d'une conversation) est
une autre chose et reste tel quel.

**File « À valider »** (S3) : un fichier par proposition dans `~/work/.atelier-etat/a-valider/`.

- Dépôt, par une seule fonction : `FileAValider.deposer(source, titre, resume, *, acteur, projet,
  detail, action={commande, arguments}, empreinte)`, ou `POST /v1/a-valider`.
  `source` ∈ `gardien`, `agent`, `creation`, `memoire`, `assistant`. Une même `empreinte` encore
  en attente n'est pas dupliquée (`occurrences` augmente).
- Modèle : `{id, source, titre, resume, acteur, projet, detail, action, empreinte, creee_le,
  modifiee_le, occurrences, statut: en_attente|acceptee|refusee, decision: {par, quand, motif, resultat}}`.
- Lecture : `GET /v1/a-valider?statut&projet&source` ou `atelier_a_valider`.
- Décision : `POST /v1/a-valider/<id>/decision` `{decision: accepter|refuser, motif, complete?}`,
  qui passe par `atelier_a_valider_accepter` (réservée : exécute l'action proposée par le
  catalogue) ou `_refuser`.
- **Branchement sur le pilote de wikichat, sans migration** : les actions `pending` de
  `.wikichat/proposed-actions.json` sont lues par `/pilote/api/data` et apparaissent sous l'id
  `pilote:<agent>:<action>` ; la décision part à `/pilote/api/agent/<id>/decide`. wikichat reste la
  maison de la coordination (S5). `decisions.py` (autorisations d'un tour vivant du CLI) reste à
  part : ce n'est pas une proposition, et y toucher casserait la reprise du tour.

#### Commandes de création (vague 2, équipe K, branche `v2-creations`)

**Existe.** Cinq modules nouveaux dans `commandes/`, branchés par une ligne
(`inscrire_les_creations(app, catalogue)`) dans `commandes/__init__.py` :

| Module | Rôle |
|---|---|
| `creations.py` | ce qu'elles partagent : lecture des arguments, et les accès extérieurs rangés dans `app.state.creations` (Pilote, outils wikichat par le pool, cartographie, sonde d'un connecteur), qu'un test remplace par des faux |
| `agents.py` | agents planifiés ou à la demande, dans le Pilote de wikichat |
| `connecteurs.py` | pool de la passerelle, choix d'un projet, accord d'un secret |
| `liens.py` | relations entre projets, écrites dans wikichat |
| `migration.py` | migration d'un projet d'avant vers la structure type |

| Commande | Classe | Inverse | Ce qu'elle garantit |
|---|---|---|---|
| `atelier_agent_creer` | reversible | `atelier_agent_supprimer` | naît **désactivé** (J-b) ; **budget obligatoire** (`tours` 1-100 par lancement, `par_jour` 1-24, `pause_s`) ; outils en liste fermée (intégrés sauf WebSearch, ou connecteurs du pool) ; dédié à un projet (son dossier) ou non (`~/work/agents/<id>`) ; horaire cron, ou à la demande |
| `atelier_agent_modifier` | reversible | elle-même (valeurs d'avant) | une modification par un modèle **désactive** l'agent ; la personne le réactive |
| `atelier_agent_supprimer` | reversible | `atelier_agent_creer` (même id, désactivé) | un modèle ne supprime pas un agent actif ; dossier et propositions gardés |
| `atelier_agent_activer` | **reservee**, non exposée en MCP | `atelier_agent_desactiver` | la personne seule (J-b2) ; refusée sans budget lisible |
| `atelier_agent_desactiver` | reversible | `atelier_agent_activer` | permise à tous ; l'annuler (réactiver) revient à la personne |
| `atelier_connecteur_ajouter` | **engageante** | `atelier_connecteur_retirer` | ajoute au pool (`gateway.db`), régénère par `mcp_sync.sync_summary`, rend la sonde (`probe_registry_server`) ; **aucun secret en argument** (en-tête ou variable secrète, `${…}`, adresse à jeton : refusés) ; `projets[]` facultatif |
| `atelier_connecteur_retirer` | reversible | `atelier_connecteur_ajouter` avec `reprendre` (engageante) | met hors service sans effacer : l'annulation remet la déclaration, secret compris, sans qu'il passe par un argument ; `reprendre` n'ouvre que ce que l'Atelier a retiré |
| `atelier_connecteur_choisir` | reversible | elle-même (choix d'avant, ou `heriter`) | `connecteurs[]` du pool, ou `heriter=true` ; passe par `mcp_sync.write_project_binding` et donc par `configuration_du_profil` (appelée, pas modifiée) |
| `atelier_connecteur_accorder` | **reservee**, non exposée en MCP | — | donne un secret **désigné par son nom** (fichier du dossier des secrets, lu par le serveur) à `headers.<Nom>` ou `env.<NOM>` ; la valeur n'apparaît ni au journal, ni dans la carte, ni dans un `.mcp.json` |
| `atelier_projets_lier` | reversible | elle-même (`relations` d'avant) | écrit `set_project_meta.relations` par l'outil `wikichat__set_project_meta` (pool) ; garde les autres relations (lues dans `GET /api/cartographie`, puis réécrites en entier) ; `retirer=true` ; déclare d'abord un projet inconnu de wikichat |
| `atelier_projet_structurer` | **engageante** (`a_blanc=true` : lecture) | `atelier_projet_destructurer` | migration vers la structure type, décrite dans `docs/structure-projet.md` |
| `atelier_projet_destructurer` | reversible | `atelier_projet_structurer` | remet l'état d'avant la migration ; refuse si un fichier posé a changé depuis |

**Choix : les agents vivent dans le Pilote de wikichat.** Un agent y est un trigger `cron` +
`spawn_session` ; c'est déjà ce que la vue Agents crée (`POST /v1/agent`) et montre, et wikichat
ordonne les automates (§1.7, J-a). Écrire ailleurs aurait fait un second registre. Les profils
d'agents de l'Atelier (`pilote-bindings`) ne servent qu'à pré-remplir des outils dans le formulaire :
la commande prend la liste fermée directement. Le Pilote ne connaissant que l'horaire, un agent à
la demande y a l'horaire `0 0 31 2 *` (jamais) et ne part que par « Lancer ». La bascule du Pilote
est un `toggle` : `activer` et `desactiver` relisent l'état avant et après.

**Clé `atelier` d'une entrée du pool** (vues relayées des bureaux, équipe B, `apps/bureaux.py`).
`atelier_connecteur_ajouter` la refuse à un modèle, dès l'aperçu : une vue relayée ouvre un service
interne dans le navigateur de la personne, qui seule la pose (interface, ou « À valider », dont
l'acceptation s'exécute au nom de la personne). Elle n'est jamais rendue : ni dans l'aperçu, ni
dans la réponse, ni dans le journal (`Commande.arguments_au_journal`, appliqué par le catalogue),
remplacée par `vues_relayees: <nombre>`. `retirer`, sa reprise et `accorder` réécrivent l'entrée en
la gardant telle quelle. Testé.

**Recherche.** Leurs mots d'intention, en français et en anglais, sont dans
`tool_search.MOTS_CLES_PAR_OUTIL` (« créer un agent », « ajouter un connecteur », « lier des
projets », « structurer le projet », « create a scheduled agent », « link projects »…) ; vérifié
par 11 requêtes contre les vraies déclarations du catalogue (`test_recherche_intention.py`).

**Profil.** Aucune n'est dans la liste du profil `code` (refus à la liste et à l'appel, testé) ;
le profil `assistant` voit les exposées, jamais les deux réservées.

**Vérifié** (`tests/test_commandes_agents.py`, `_connecteurs.py`, `_liens.py`, `_migration.py`,
76 tests) : classe, inverse et exposition de chacune ; refus en profil `code` ; journal (acteur,
classe, inverse, `apercu` puis `fait` pour les engageantes, `refus` pour une réservée appelée
par un modèle) ; chaque « Annuler » par `atelier_annuler`. Le Pilote et wikichat sont des faux
qui suivent leur API (`pilote.mjs`, `tools.mjs`, contrat de la cartographie) ; le pool, `mcp_sync`,
git et la migration sont réels.

**Aperçu qui refuse** (corrigé dans `catalogue.py`). Un aperçu d'engageante qui lève `Refus`
(arguments faux) rend `statut: refus`, sans jeton, journalisé `refus`, au lieu de faire tomber
l'appel en exception. `atelier_projet_deployer_declarer` en profite (testé).

**Annuler une inverse engageante** (`natives.py`, `atelier_annuler`). Quand l'auteur de l'action
(même acteur) ou la personne l'annule, son geste vaut accord pour l'inverse : elle s'exécute sans
nouvel aperçu, avec cet acteur, et son journal porte `via: atelier_annuler:<action>` ; la carte
d'annulation le dit (`preuve.consentement_de_l_action`). Un autre modèle retombe sur l'aperçu
(refus). Une inverse réservée reste refusée à tout modèle (la classe est revérifiée). `retirer` a
donc de nouveau son inverse naturelle, `atelier_connecteur_ajouter` avec `reprendre`, **engageante**
(l'allègement en réversible est retiré) ; `atelier_projet_deployer_declarer` s'annule aussi.

**Non vérifié** : contre le vrai Pilote et le vrai wikichat du pod (aucun essai en réel, pod en
lecture seule) ; la sonde réelle d'un connecteur ajouté ; le budget en jetons, que le Pilote ne
plafonne pas (seuls les tours, les lancements par jour et la pause le sont ; plafonds de lancement :
lot D, équipe L) ; une relation vers un projet absent de la cartographie serait perdue à la
réécriture (le nombre est rendu dans la preuve).

**Ce qui reste** : recalcul de la carte après commande (le crochet `apres_commande` existe, la carte
non) ; « plus de trois actions à la suite » comme engageant ; coût en part du forfait dans
l'aperçu ; inverses de `atelier_artefact_creer` et `atelier_interrompre` ; l'écran d'accord qui appelle
`atelier_agent_activer` et `atelier_connecteur_accorder` ; l'écran « À valider » (équipe P).

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
| T10 | `atelier_transcript` et `atelier_suivre` rendent le texte brut d'une conversation : un secret affiché par un agent atteindrait l'Assistant, puis sa mémoire | outils `atelier_*` | filtrer à la source, dans le code, les valeurs connues de `claude-env.sh` (par empreinte, comme le gardien Sécurité) avant de rendre un transcript ; même filtre à la capitalisation | **réglé** sur `v3-memoire` (équipe M) : `filtre_transcripts.py` sur toute charge des outils `atelier_*`, la route du transcript, le fil du pilote et le transcript fourni à wikichat (§1.6 bis, « Mémoire : ce qui existe ») |
| T12 | La publication GitHub `wikichat-memory` a divergé : 28 commits d'avance, 3 de retard, 289 instantanés, 19 axes sur 42 en double. Elle est publiée depuis le poste par une tâche planifiée. Rappel : la décision du 02/09 (alignement §10) tient. Le dossier de l'Assistant n'est **pas un dépôt, à dessein**, et le dépôt GitHub n'est qu'une publication assainie de la mémoire | poste, `atelier-wikichat-alignment.md` | un seul éditeur de la publication (le wikichat du pod) ; réconciliation unique ; arrêt de la tâche du poste | Nicolas (exécution) |
| T13 | Le pool compte 293 outils, soit environ 52 000 jetons s'il était présenté en entier. Le plancher d'un agent code est de 21 695 jetons en entrée (mesuré au relais) | pod | confirme §1.5 : noyau et catalogue par profil, jamais le pool entier | équipe harness |
| T14 | Aucun `ETAT.md` dans les 26 projets du pod ; les hooks wikichat ne sont pas encore déployés | pod | la couche C2 est vide tant que le lot G (structure de projet) et le déploiement du 26/09 ne sont pas faits | lots G et `deploiement-26-09` |
| T11 | Oral lent : environ 11 s entre la fin de la parole et le premier mot (tranche STT de 3 s, puis 7,9 s jusqu'au premier jeton du modèle ; somme de mesures connues, non mesurée de bout en bout) | voix | accusé immédiat sans modèle ; réponses d'état calculées par le code à partir de la carte ; chemin rapide à instruire (équipe harness) | en cours |
| T15 | L'Atelier a écrit un bloc `atelier:contexte` (projet `projet-sans-nom-5`) dans `/tmp/CLAUDE.md`. Toute session lancée sous `/tmp` le chargeait, y compris les essais des équipes | `project_context.py` | fichier mis de côté (`/tmp/CLAUDE.md.ecarte-25-09`) ; écriture du contexte limitée au dossier du projet résolu | équipe F |
| T16 | L'éditeur n8n n'envoie aucun en-tête anti-cadrage : il est encadrable par n'importe quel site | namespace | relais par l'hôte des applications (J-d) et `frame-ancestors` limité à l'Atelier sur tout amont | équipe P (P0) ; réglage n8n à poser |
| T17 | La porte dormante ne coupe pas la nuit : 11 passages de routine sur 34 entre 0 h et 6 h en 7 jours | wikichat | plafonds et budgets (J-b) plutôt que la porte ; à reprendre avec l'inventaire G0 | équipes W et G |
| T18 | L'en-tête `X-Atelier-Origine` arrive au relais LLM, mais celui-ci ne le lit ni ne le journalise : pas de coût par acteur | `relais_llm.py` | lecture de l'en-tête et journal des jetons par acteur | vague 2 (G4) |
| T19 | Les plugins Claude Code marchent dans le CLI, mais `--strict-mcp-config` écarte leur serveur MCP | CLI 2.1.281 | à prendre en compte pour les extensions (F6, F9) | vague 4 |
| T20 | Constats de l'exécution à blanc des gardiens (25/09) : jeton n8n en clair dans un fichier effectif antérieur au déploiement (`~/work/mcp/effective/394226a3-….json`, mis en 0600) ; jeton `ghp_` toujours dans le remote de `projects/nouveau-projet` ; 8 triggers actifs sans budget ; routine `paradox-research` à 27 passages en 7 jours ; écoutes non déclarées (`cerveau/outils/serveur.py` 8082, voix 18920, `http.server` 9999, `ipykernel` sur `0.0.0.0:8000`) ; fichiers effectifs écrits en 0644 | pod | rotation des jetons (Nicolas) ; fichiers effectifs en 0600 ; écoutes à déclarer ou à passer en créations serveur ; budgets (J-b) | Nicolas ; vague 2 |
| T21 | En mode image (`ATELIER_AVANT_PLAN=1`), le geste `relancer_atelier` des gardiens tuerait le processus principal, donc le pod | `gardiens/gestes.py` | geste désactivé en mode image ; seule la sonde reste | intégration vague 1 |
| T22 | Le commit en service est illisible sur le pod (copie sans `.git` ni `VERSION`), et la CI d'un dépôt privé est illisible sans jeton | déploiement | écrire `VERSION` à l'extraction ; jeton GitHub en lecture seule dans `~/work/.secrets/` | déploiement suivant |
| T23 | Sur le pod, `~/.wikichat` est un dossier de la couche éphémère, pas le lien vers le volume que prévoit l'Atelier (`ensure_wikichat_data_link` ne remplace pas un dossier non vide). Triggers, routines, registre et connaissance seraient perdus au redémarrage du pod | pod | procédure `docs/atelier-coherence.md` §11.3 de wikichat (sauvegarde, lien, puis migration W2), au déploiement de la vague 1 | intégration vague 1 |

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
| Capitalisation des conversations | `src/memoire/` (W8) | écrit (vague 3), non déployé | Assistant, projets | fiches dans la connaissance ; `atelier_rappel`, `atelier_fiche` (§1.6 bis) |
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
- **25/09, `mesures-vague1.md`** :
  - A-1 : `medium`, et la ligne `xhigh` morte est retirée ;
  - A-2 confirmée : 17 sur 20, sans `list_changed` ; s'y ajoutent des alias d'intention et une consigne forte ;
  - A-8 révisée : son préenregistré et détection de fin de parole ;
  - A5, A6, A8, A9, A10, A12 et A13 levées ;
  - T15 à T19 ouvertes.
- **25/09, équipe G (gardiens)** :
  - exécuteur livré sur la branche `gardiens` (G0, G1, G2, gestes en liste fermée, journal, homme mort, hook `garde_bash`) ;
  - contrat de l'API de lecture sur `127.0.0.1:8791`, routes `/sante`, `/etat`, `/alertes`, `/echeances`, `/resultats`, `/automates`, dans `gardiens.md` (État) : c'est la source de la page Gardiens (équipe P, vague 2) ;
  - T20 à T22 ouvertes.
- **25/09, équipe W (lot W)** :
  - briques de wikichat réparées et branchées (W1 à W5, W7), jobs déterministes sans agent, clôtures absorbées par le code ;
  - la couche wikichat de la carte est servie par `GET /api/cartographie`, contrat dans `docs/cartographie-contrat.md` de wikichat : nœuds (slug, état, santé, décisions, connecteurs par nom, champ `atelier` réservé) et arêtes typées `relation`, `proximite` et `meme_connecteur`. C'est la source de la carte de la vague 2 ;
  - W6 : inventaire des triggers en échec, sans rien couper ;
  - T23 ouverte ; décision J-b2 ajoutée.
- **25/09, équipe F (fondations)** :
  - catalogue de commandes, journal unique, file « À valider » et structure de projet livrés sur la branche `fondations` ; contrats détaillés au §1.8 de cette branche, repris ici à l'intégration ;
  - écarts assumés :
    - une quatrième classe `lecture`, sans carte, dont les réussites ne sont pas journalisées pour ne pas noyer le journal (les refus et erreurs le sont) ;
    - la clé du propriétaire en HTTP compte comme un modèle pour les commandes `reservee`, car les agents du pod peuvent la lire. Seule la session de l'interface peut accepter ;
    - le gabarit n'importe pas le socle, que Claude Code charge déjà par le dossier parent ;
  - le Pilote de wikichat est branché sur « À valider » sans migration (S5) ;
  - T15 est corrigée à la source (le contexte n'est écrit que dans le dossier du projet) ; la cause exacte de `/tmp` sur le pod reste non identifiée.
- **25/09 au soir, déploiement de la vague 1** (`main` = `776fb73`) :
  - l'intégration a fondu F, W, G et P ;
  - raccords faits par le coordinateur :
    - gardiens branchés sur le journal unique ;
    - pas de relance de l'Atelier en mode image (T21) ;
    - épinglage aligné sur le schéma de `projet.json` ;
    - rejeu d'un envoi refusé ;
    - substituts isolés du transcrit retirés ;
    - docstring qui empêchait l'import sous Python 3.13 corrigée ;
  - T23 est réglée : `~/.wikichat` est un lien vers le volume ;
  - `cron-routine-4h` est coupé ;
  - le fichier effectif périmé qui portait le jeton n8n est supprimé ;
  - le jeton `ghp_` est retiré de l'adresse du remote de `nouveau-projet` ;
  - les sauvegardes `.avant-26-09` sont supprimées ;
  - reste ouvert : `ipykernel` sur `0.0.0.0:8000` (noyau du connecteur Onyxia) ; CI et `main` illisibles depuis le pod faute de jeton GitHub en lecture (T22) ; rotation des jetons n8n et GitHub (Nicolas).
- **26/09, équipe C (carte, vague 2)** :
  - la carte existe : couche Atelier lue à ses sources, assemblée avec `GET /api/cartographie`
    par le slug, servie par `GET /v1/carte` et `atelier_carte` (profil `assistant`), gardée 20 s
    et invalidée par `apres_commande` ; contrat au §1.3 (« Carte : ce qui existe ») ;
  - la route est `/v1/carte`, comme `/v1/commandes`, et non `/api/carte` ;
  - mesurée sur le pod : 697 unités pour la forme synthétique (1 384 au pire cas), sous le
    plafond de 2 400 ;
  - constaté : aucun projet du pod n'a encore d'`ETAT.md` (T14) ; la couche wikichat compte
    16 dossiers qui ne sont pas des projets (dossier parent, dossiers de session, dossiers
    d'agent), que la vue courte relègue en décompte.
- **26/09, équipe M (mémoire, vague 3)** :
  - T10 réglé à la source (`filtre_transcripts.py`) ;
  - W8 écrit dans wikichat (`src/memoire/`) : faits par le code, routine de nuit plafonnée
    par des lancements de l'Atelier, fiches dans la connaissance, mémoire de la personne ;
  - `atelier_rappel` et `atelier_fiche` (profil `code` : son projet), propositions de mémoire
    par « À valider », vue « Ma mémoire » ; l'export assaini inclut les fiches (S6) ;
  - écart à A-7 constaté : l'entrée de la nuit est plafonnée par le message du lot D (58 000
    caractères, ≈ 17 000 jetons) ; chaque lancement paie en plus le harnais (≈ 21 700 jetons) ;
  - `qwen3-embedding-8b` non mesuré sur de vraies fiches (garde des permissions : ce serait
    envoyer le texte des conversations) ; recherche lexicale seule.
- **26/09, équipe A (Assistant, vague 3)** :
  - le dossier `~/work/wikichat-memory` est généré par l'Atelier (pas un dépôt) : `CLAUDE.md`
    qui importe rôle, outils, carte et « À valider », rafraîchis avant chaque tour ;
  - deux réglages du CLI sans lesquels rien ne marchait, posés par l'Atelier : approbation des
    imports externes, confiance au dossier exact ;
  - coût d'entrée mesuré ≈ 16 000 jetons (budget 20 000), premier mot en 1,7 à 3,8 s ; bon
    choix de commande 17 fois sur 17 ; exécution de bout en bout non rejouée ;
  - risque vu : invention d'un résultat après un refus ; consigne « un refus n'est pas un
    résultat » et marque « non vérifié » dans l'interface ;
  - `HORS_LISTE_ASSISTANT` : les anciennes commandes de conversation restent joignables par
    `gateway_find_tools` et `gateway_call_tool` sans être déclarées ;
  - noyau wikichat de l'Assistant (10 outils, fait par M) : ≈ 11 100 → 2 470 jetons.
- **26/09, équipe N (navigateur en direct, vague 3)** :
  - Chrome garde son tube (`chrome-devtools-mcp`) et reçoit en plus un port DevTools en
    boucle locale ; le lanceur l'ajoute après puppeteer pour ne pas lui faire perdre le tube ;
  - profil gardé par conversation sous verrou ; un second processus de la même conversation
    reçoit un profil jetable, sans écran ;
  - l'écran passe par `ecran.py` (images JPEG et gestes validés), jamais par un relais
    DevTools brut, portée `conversation:<id>` ;
  - « Prendre la main » retient les actions de l'agent sur le navigateur au lieu d'interrompre
    le tour (interrompre tuerait Chrome et la page) ;
  - J-f3 : les neuf lectures du navigateur passent par `refuser_les_outils_simules`, déjà appelé
    par toutes les surfaces, donc le vérificateur les voit ;
  - à confirmer sur le pod : bac à sable de Chrome, `CLAUDE_CODE_SESSION_ID` transmis aux
    serveurs stdio par VS Code et le terminal.
- **Explication de T12** : sur le poste, une tâche planifiée publie la mémoire toutes les 15 min depuis
    `Github Repositories/wikichat`, pendant que le dépôt évolue ailleurs.
- **26/09, correctifs après essais de la vague 3** (branche `v3-correctifs`, huit défauts vus dans
  Chrome, chacun avec un test qui échouait avant) :
  - l'état d'un outil se lit dans le `is_error` du CLI, porté par `outil_fin` (champ `erreur`),
    plus dans le texte de sa sortie : `take_snapshot` de https://example.com (« without needing
    permission ») s'affichait « permission refusée » ;
  - page changée pendant la main (adresse ou titre, `ecran.page_a_change`, `page_changee` dans le
    fichier de la main) : le filtre ne transmet plus une action par `uid` retenue, l'agent reçoit
    une erreur qui porte la note et lui dit de relire la page, jusqu'à son prochain
    `take_snapshot` ; les actions sans `uid` repartent comme avant (`navigateur-atelier.md` §8.2) ;
  - écran : « Aller » envoyait l'ancienne adresse, le blur du champ la remettait avant la
    soumission (reproduit) ; l'adresse modifiée non soumise n'est plus écrasée par l'état du
    serveur ;
  - une conversation prend son titre du premier message dès l'envoi, Assistant et Code
    (« wikichat-memory-a5827138 » pendant tout le premier tour) ;
  - fil de l'Assistant : résultats d'outils repliés, cartes d'action visibles ; même composant que
    Code, replié partout au-delà de 1 500 caractères ou 25 lignes ; le libellé de la colonne suit
    la vue ;
  - carte : un `meme_connecteur` ne compte que les connecteurs choisis par les deux projets,
    jamais l'héritage du pool (contrat du §1.3 révisé ; 181 liens sur le pod, presque tous nés
    du pool) ;
  - vérificateur : « [wikichat-memory] profil code » était `~/work/projects/wikichat-memory`,
    reste de l'ancienne reprise dans VS Code, pas le dossier de l'Assistant (profil `assistant`
    sur toutes les surfaces, constaté sur le pod). Le reste recevait pourtant un `.mcp.json` de
    profil `code` annonçant le slug de l'Assistant, accepté comme projet d'un agent `code` :
    corrigé à la source (`settings.masque_par_l_assistant`) ; le dossier reste à ranger (Nicolas).
