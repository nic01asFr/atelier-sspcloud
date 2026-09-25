# Familles de projets et écosystème

Proposition du 25/09/2026, **à valider**. Équipe « Familles de projets et
écosystème » de la réflexion sur la vision (`docs/vision/cadre.md`).
Prolonge `docs/atelier-hebergement.md` (brouillon/production, capacités,
entretien, service dédié), `docs/structure-projet.md` (structure type,
`projet.json`, commandes), `docs/atelier-applications.md` (artefacts, hôte des
applications, superviseur), `docs/coherence-projet.md` (une source par
information, mécanismes natifs) et `docs/lecteur-grist-application.md`
(application témoin).

## L'idée en une phrase

**Quatre familles de projets, un seul manifeste par chose produite, deux
destinations.** On crée un projet depuis le gabarit d'une famille (page,
application, service MCP, savoir-faire) ; ce qu'il produit est toujours un
artefact décrit par `artefact.json` ; quand il est prêt, on l'**ajoute à son
Atelier** (il devient une vue, un connecteur, une composition, un agent) ou on
le **publie en production** (il vit à part et se pilote depuis l'Atelier) —
les deux par le même geste de promotion, avec le même consentement.

« Extension » n'est pas une famille de plus : c'est **ce que devient un
artefact quand on l'ajoute à son Atelier**.

---

## 1. Le problème, vu par la personne

**Scénario A — « Je veux un tableau de bord de mes données Grist. »**
Aujourd'hui, un agent écrit une page HTML dans `artifacts/`, la page ne peut
pas lire Grist (bac à sable, `connect-src` limité à son hôte), l'agent colle
des données figées dans le HTML ou invente un petit serveur avec la clé Grist
en dur. Rien ne dit comment la rendre vivante, ni comment la retrouver ailleurs
que dans le panneau Applications du projet.

**Scénario B — « Je veux un outil MCP qui interroge mon service. »**
L'agent écrit un serveur MCP qui marche au terminal. Pour qu'il devienne un
connecteur de l'Atelier, il faut le lancer à la main, trouver un port, écrire
une entrée dans le registre des connecteurs, et il s'arrête au prochain
redémarrage du pod. Pour qu'il serve depuis claude.ai ou à un collègue,
personne ne sait par où passer.

**Scénario C — « Je veux ajouter à mon Atelier une vue calendrier de mes
routines. »** Il n'existe aucune prise : il faudrait modifier le code de
l'interface (`atelier/web/js/views/`), reconstruire l'image, redéployer. Une
erreur casse l'Atelier entier ; rien ne permet de revenir en arrière en un
geste, ni de savoir ce que la vue peut voir.

Ce qui manque dans les trois cas : **un point de départ cadré** (gabarit), **un
chemin connu** jusqu'à l'usage réel, et **des prises** par lesquelles un
projet peut compléter l'Atelier sans le toucher.

---

## 2. Ce qui existe déjà

### Dans l'Atelier

| Brique | Où | Ce qu'elle donne aux familles |
|---|---|---|
| Projet = dépôt git, créé sans rien demander ; publication GitHub délibérée | `atelier/git_repos.py`, `atelier/projects.py` | le support de tout projet ; `projects.py` ne connaît que `assistant`/`code`, pas de famille ni de gabarit |
| Artefact = dossier `artifacts/<nom>/` = une adresse sur l'hôte des applications | `apps/manifeste.py` (modèle strict et fermé, `version: 1`, `type: statique|service`) | le manifeste unique à étendre |
| Superviseur, relais HTTP/WS/SSE, passage d'authentification, second origine | `apps/superviseur.py`, `apps/proxy.py`, `apps/passage.py` | faire tourner et montrer n'importe quel artefact sans toucher l'origine de l'Atelier |
| Outils `atelier_artefact_*` (créer, démarrer, arrêter, journal, vérifier) | `outils_conversation.py` | ce que les agents savent déjà faire |
| Secrets par référence (`~/work/.secrets/apps/<ref>`, `${ATELIER_MCP_…}`) | `manifeste.py`, `mcp_secrets.py` | aucun secret dans un gabarit ni dans un dépôt |
| Registre des connecteurs (format `mcpServers`, remote/stdio) | `atelier/mcp_registry.py`, `registry.py` | l'endroit où un service MCP devient connecteur |
| Compositions avec statut `temporary → validated → production`, `promote`/`demote`, journal d'audit | `compositions/service.py`, `validate.py` | **le cycle brouillon → production existe déjà** pour les compositions ; on le généralise |
| Profils et plafonds (`BundleSession`, `mcp_ceiling`) | `profiles.py`, `bundles.py` | borner ce qu'un client ou une extension atteint |
| Porte `/mcp` de l'Atelier pour clients distants, OAuth (claude.ai branché, L0/L1 faits) | `oauth.py`, `mcp_endpoint.py`, `docs/atelier-mcp-distant.md` | la voie la plus courte pour qu'un connecteur fait maison serve dans claude.ai |
| Agents publiés = promus comme une composition (D9, non commencé) | `docs/atelier-mcp-distant.md` L3 | la famille savoir-faire |
| Routines et déclencheurs wikichat | coordinateur wikichat | l'entretien et les agents planifiés |
| Enrichissements de connecteurs (libellés humains, familles d'outils) | `atelier/enrichissements.py` | présenter un connecteur fait maison comme les autres |
| Application témoin complète (Lecteur Grist : page `lecteur` + service `essai`) | `docs/lecteur-grist-application.md` | preuve qu'un projet mêle plusieurs sortes d'artefacts |

Proposé mais pas construit : brouillon/production par étiquette
`prod/<nom>/<n>`, capacités consenties et jeton `ATELIER_APP_JETON`,
entretien, service dédié (`atelier-hebergement.md`) ; `projet.json`, gabarit
de projet, commandes `/verifier` `/proposer` (`structure-projet.md`).

### Standards à réutiliser plutôt qu'inventer

| Standard | Ce qu'il apporte | Usage proposé |
|---|---|---|
| **MCP** (outils, ressources, prompts) | contrat unique entre agents et services | toute fonction offerte aux agents passe par un serveur MCP |
| **MCP Apps** (extension de MCP : un outil annonce une ressource `ui://…` en HTML, l'hôte l'affiche dans une iframe isolée et relaie les appels d'outils par `postMessage`) | une interface qui s'affiche **dans** la conversation, chez tout hôte compatible (claude.ai, Claude Desktop, VS Code, d'autres) | la forme commune des vues : la même page sert dans l'Atelier et dans claude.ai. **Version de la spécification à vérifier au moment de construire.** |
| **Plugins Claude Code** (`.claude-plugin/plugin.json` : commandes, sous-agents, skills, hooks, serveurs MCP) et **places de marché** (`marketplace.json`, un dépôt git) | emballage natif du savoir-faire, installable sur toutes les surfaces (CLI, VS Code) | la forme de la famille savoir-faire et le support du partage entre Ateliers |
| **Skills** (`SKILL.md`) | savoir-faire chargé à la demande | contenu d'un savoir-faire |
| **OAuth 2.1 pour MCP** (métadonnées de ressource protégée, DCR, PKCE) | clients externes sans secret dans la configuration | publication d'un service MCP ; plus tard via `passerelle-auth` du trousseau |
| **Registre MCP** (`server.json`) | fiche descriptive d'un serveur publié | fiche générée à la publication, jamais écrite à la main |
| **copier** (gabarits de projet avec mise à jour, fichier de réponses) | un projet sait de quel gabarit et de quelle version il vient, et peut se mettre à jour | moteur des gabarits, à décider (§6) |

### Produits comparables

- **Home Assistant** : intégrations et cartes ajoutées sans toucher au cœur,
  « mode sans échec » qui démarre sans elles — le modèle de §3.4.
- **Val Town / Replit / Vercel** : de la fonction au service publié en un
  geste, avec prévisualisation séparée de la production — c'est notre
  brouillon/production.
- **Obsidian** : communauté de greffons, mais un greffon a tous les droits dans
  l'application — **le contre-exemple** : ici, jamais de code d'extension dans
  l'origine de l'Atelier.
- **VS Code** : points d'extension déclarés dans un manifeste
  (`contributes`), activation à la demande — le principe des « prises ».

---

## 3. La proposition

### 3.1 Les éléments

| Mot (vu par la personne) | Ce que c'est | Où ça vit |
|---|---|---|
| **Famille** | le genre du projet, choisi à la création | `.atelier/projet.json` : `famille` |
| **Gabarit** | le point de départ d'une famille : fichiers, consigne, tests, commandes | `gabarits/<famille>/` (dépôt de l'Atelier) ou un projet marqué gabarit |
| **Artefact** | chaque chose que le projet produit et montre | `artifacts/<nom>/artefact.json` (existant, étendu) |
| **Prise** | ce qu'un artefact offre : une page, des outils MCP, une vue, des compositions, des agents | `artefact.json` : `offre` |
| **Extension** | un artefact ajouté à mon Atelier, à une version figée | registre des extensions |
| **Production** | un artefact publié, qui vit à part | étiquette `prod/<nom>/<n>`, service dédié ou non |
| **Capacité** | ce qu'un artefact peut demander à l'Atelier | `artefact.json` : `capacites`, accordée par la personne |

Pour la personne, trois mots nouveaux seulement : famille, gabarit,
extension. « Prise » reste un mot interne ; l'interface dit « ce qu'il
offre ».

### 3.2 Les quatre familles

Le moins possible : quatre, parce qu'il y a quatre façons de *faire tourner*
quelque chose — des fichiers (page), un processus avec une interface
(application), un processus sans interface propre (service MCP), des
déclarations sans processus (savoir-faire). La famille n'est qu'**un point de
départ** : un projet peut ensuite porter plusieurs artefacts de sortes
différentes (le Lecteur Grist a une page et un service).

| | **Page** | **Application** | **Service MCP** | **Savoir-faire** |
|---|---|---|---|---|
| Pour | un artefact interactif : tableau de bord, formulaire, visualisation, outil de calcul | une app avec ses données, ses utilisateurs, son API | des fonctions offertes aux agents : interroger un service, transformer des données | apprendre à l'Atelier à faire : compositions, agents, routines, commandes, skills |
| Tourne | rien (fichiers servis en bac à sable) | un processus supervisé | un processus supervisé | rien (déclarations lues par la passerelle, wikichat, Claude Code) |
| `artefact.json` `type` | `statique` | `service` | `service` | `savoir-faire` (nouveau) |
| Offre (prises) | `page`, et `vue` si ajoutée à l'Atelier | `page` + `mcp` (outils d'usage et de **pilotage**) | `mcp` (+ ressources `ui://` MCP Apps facultatives) | `compositions`, `agents`, `routines`, `commandes`, `skills` |
| Données | aucune ou via capacités | `donnees/` hors git, sauvegardées | via capacités ou secrets par référence | aucune |
| Ajoutée à mon Atelier devient | une **vue** (panneau, onglet de projet, carte d'accueil) | une carte Applications + un **connecteur** de pilotage | un **connecteur** du pool | des **compositions**, des **agents**, des **commandes** disponibles partout |
| Publiée en production devient | une adresse partagée ou publique | un service dédié avec son hôte | un serveur MCP public (OAuth), fiche de catalogue | un paquet partageable (place de marché) |
| Témoin | tableau de bord Grist (§4) | Lecteur Grist | connecteur « mon service » (§4) | « veille hebdomadaire » (§4) |

#### Gabarits

Chaque gabarit dépose la structure type de `structure-projet.md` (`CLAUDE.md`
≤ 100 lignes, `ETAT.md`, `docs/`, `.atelier/projet.json`, `.claude/`) et ce qui
est propre à sa famille :

**Page** (`gabarits/page/`)
```
artifacts/<nom>/index.html        page autonome, sans dépendance réseau hors de son hôte
artifacts/<nom>/atelier.js        petit pont : appelle ses capacités (§3.5) ; vide si inutile
artifacts/<nom>/artefact.json     type statique, offre {page, vue?}, capacites []
tests/page.spec.mjs               ouverture en navigateur (service Chrome du pod), zéro erreur console
```
Commandes : `/apercu` (ouvre le brouillon), `/verifier`, `/proposer`.
Consigne : « une page ne contient ni clé ni donnée personnelle ; elle obtient
ses données par ses capacités ; elle tient en largeur de téléphone ».
Vérification : chargement sans erreur, capture d'écran jointe à la proposition.

**Application** (`gabarits/application/`, un par langage : Python/Starlette,
Node)
```
<paquet>/                         code ; route /_sante ; route /mcp (outils d'usage et de pilotage)
artifacts/<nom>/artefact.json     type service, commande avec {port}, sante, protocoles, donnees,
                                  preparer, entretien, capacites, offre {page, mcp}
tests/                            unitaires + test de fumée contre le brouillon
outils/verifier                   point d'entrée unique de vérification
```
Commandes : `/apercu`, `/verifier`, `/proposer`, `/journal`.
Consigne : adresses relatives (préfixe), battement SSE < 30 s, identité par
`X-Atelier-Utilisateur`, rien sur le disque hors `{donnees}`, outils de
pilotage marqués (`sauvegarder`, `etat`, `purger`…).

**Service MCP** (`gabarits/service-mcp/`, Python FastMCP ou SDK TypeScript)
```
<paquet>/serveur.py               serveur MCP en HTTP « streamable », route /_sante
<paquet>/ui/                      ressources ui:// facultatives (MCP Apps)
artifacts/<nom>/artefact.json     type service, offre {mcp: {chemin: "/mcp"}}, secrets par référence
tests/test_outils.py              chaque outil appelé par un vrai client MCP (liste, appel, erreur)
```
Commandes : `/apercu` (liste les outils et en appelle un), `/verifier`,
`/proposer`.
Consigne : description d'outil écrite pour un modèle qui ne connaît pas le pod,
schéma d'entrée strict, annotations (lecture seule / destructif), pas de secret
en argument.

**Savoir-faire** (`gabarits/savoir-faire/`)
```
artifacts/<nom>/artefact.json     type savoir-faire, offre {compositions, agents, routines, commandes, skills}
artifacts/<nom>/.claude-plugin/plugin.json   GÉNÉRÉ depuis artefact.json
artifacts/<nom>/commands/*.md     commandes Claude Code
artifacts/<nom>/agents/*.md       sous-agents Claude Code
artifacts/<nom>/skills/*/SKILL.md skills
artifacts/<nom>/compositions/*.json   compositions de la passerelle (même format que l'export existant)
artifacts/<nom>/routines/*.json   routines wikichat : quand, quoi, plafond de passes par jour
tests/                            chaque composition validée à blanc (validate_for_promotion) ; chaque routine
                                  jouée une fois en brouillon
```
Commandes : `/essayer <composition>`, `/verifier`, `/proposer`.
Consigne : un agent planifié est un **proposeur** (il dépose, il n'écrit pas
dehors) ; chaque routine a un plafond affiché ; **pas de hook** (§3.4).

### 3.3 Ce qui unifie : deux manifestes, pas trois

**Un fichier par niveau, et une information à un seul endroit.**

- `.atelier/projet.json` — le **projet** : titre, famille, gabarit et sa
  version, commandes `preparer`/`tests`/`verifier`, chemins protégés (déjà
  proposé par `structure-projet.md` ; on ajoute deux champs).
- `artifacts/<nom>/artefact.json` — chaque **artefact** : ce qu'il est, ce
  qu'il offre, ce qu'il demande, comment il s'entretient (existant, passé en
  `version: 2`, toujours strict et fermé).

Tout le reste est **généré** depuis ces deux fichiers, jamais écrit à la main :
`plugin.json` d'un savoir-faire, entrée du registre des connecteurs, fiche
`server.json` d'un service publié, carte de l'interface, section de
`.atelier/contexte.md`.

```json
// .atelier/projet.json (ajouts)
{
  "famille": "service-mcp",
  "gabarit": {"nom": "service-mcp-python", "version": "3"}
}
```

```json
// artifacts/meteo-interne/artefact.json (version 2)
{
  "version": 2,
  "titre": "Mon service météo",
  "type": "service",
  "commande": [".venv/bin/python", "-m", "meteo.serveur", "--port", "{port}"],
  "repertoire": "../..",
  "sante": "/_sante",
  "secrets": {"METEO_CLE": "meteo"},

  "offre": {
    "mcp":  {"chemin": "/mcp", "prefixe": "meteo",
             "pilotage": ["meteo_etat", "meteo_vider_cache"]},
    "page": {"chemin": "/"},
    "vue":  {"titre": "Météo", "emplacement": "projet", "hauteur": "moyenne"}
  },
  "capacites": [
    {"type": "outil", "nom": "grist__list_records", "limite_par_heure": 120}
  ],
  "entretien": {"sante": {"toutes_les_min": 5}, "tests": {"avant_promotion": true}},
  "atelier_min": "2026.10"
}
```

Règles nouvelles, dans l'esprit du manifeste actuel :

- `offre` est **fermé** : `page`, `mcp`, `vue`, et pour `savoir-faire`
  `compositions`, `agents`, `routines`, `commandes`, `skills`. Aucune autre
  prise.
- `offre.mcp.prefixe` devient le préfixe des outils dans le pool ; il doit être
  libre (refus nommé sinon).
- `offre.mcp.pilotage` liste les outils réservés au propriétaire et à ses
  agents ; ils ne sont **jamais** publiés à des tiers.
- `atelier_min` : la version de l'Atelier requise (contrat des prises, §3.4).
  Une extension trop récente reste inactive, avec la raison.
- Une `vue` n'est permise que si l'artefact offre une `page` (ou une ressource
  `ui://`) : **une vue est une page affichée dans l'Atelier**, rien d'autre.

MCP Apps donne la forme commune : une vue de l'Atelier est hébergée comme une
MCP App (iframe sur l'hôte des applications, messages `postMessage` au format
MCP Apps). Conséquence : la vue calendrier écrite pour l'Atelier s'affiche
aussi dans claude.ai si le service qui la porte est branché là-bas, et une MCP
App trouvée ailleurs s'affiche dans l'Atelier. **Un seul modèle, deux usages.**

### 3.4 Comment une extension s'ajoute sans fragiliser l'Atelier

#### Cinq prises, et rien d'autre

Une extension **ajoute** par une prise déclarée ; elle ne **modifie** jamais le
cœur. Changer le comportement de l'Atelier lui-même (son interface, ses règles)
reste un travail sur le dépôt de l'Atelier (branche, tests, image) : ce n'est
pas une extension.

```
                         MON ATELIER (origine de l'Atelier, code de l'Atelier seul)
   ┌───────────────────────────────────────────────────────────────────────────┐
   │ Interface          Passerelle MCP            wikichat         Claude Code │
   │  ┌─────────┐       ┌──────────────┐          ┌─────────┐      ┌─────────┐ │
   │  │ cadre   │       │ pool         │          │ routines│      │ plugins │ │
   │  │ de vue  │       │ compositions │          │ agents  │      │ (user)  │ │
   │  └────▲────┘       └──────▲───────┘          └────▲────┘      └────▲────┘ │
   └───────┼───────────────────┼───────────────────────┼────────────────┼──────┘
     prise │vue         prise  │mcp / compositions     │agents/routines │commandes/skills
           │                   │                       │                │
   ┌───────┴─────┐   ┌─────────┴───────┐   ┌───────────┴────────────────┴─────┐
   │ iframe sur  │   │ processus       │   │ fichiers déclaratifs lus à       │
   │ l'hôte des  │   │ supervisé, port │   │ une version figée                │
   │ applications│   │ attribué        │   │ (worktree prod/<nom>/<n>)        │
   └─────────────┘   └─────────────────┘   └──────────────────────────────────┘
          ▲ toutes lues depuis la VERSION FIGÉE de l'artefact, jamais le brouillon
```

| Prise | Ce que l'extension apporte | Ce qu'elle voit | Ce qu'elle ne peut pas |
|---|---|---|---|
| **Vue** | un panneau (accueil, projet, conversation) | ce que le pont lui passe : le contexte déclaré (projet courant, thème), le résultat de ses capacités | lire le DOM, les cookies ou la clé de l'Atelier (autre origine) ; appeler `/v1` ; appeler un outil non accordé |
| **Connecteur** (`mcp`) | des outils dans le pool, sous son préfixe | les arguments qu'on lui passe ; ses secrets par référence | voir les autres connecteurs ; recevoir la clé owner ; s'ajouter à un profil sans geste de la personne |
| **Compositions** | des compositions importées au statut `validated` | — | passer seules en `production` ; appeler un outil hors du plafond du profil qui les exécute |
| **Agents / routines** | des déclencheurs wikichat | ce que leur consigne et leurs outils leur donnent | écrire dehors (proposeurs) ; dépasser leur plafond de passes ; tourner sans apparaître au panneau |
| **Commandes / skills / sous-agents** | du savoir-faire chargé par Claude Code sur toutes les surfaces | le texte qu'ils contiennent | exécuter quoi que ce soit par eux-mêmes |

**Hooks interdits dans une extension.** Un hook de plugin s'exécute à chaque
session, avec tous les droits de l'agent, sur toutes les surfaces. C'est
exactement ce que les prises évitent. Un savoir-faire qui en déclare est
refusé à la vérification ; s'il en faut un, il passe par le dépôt de l'Atelier.

#### Le registre des extensions

Une table dans la base de la passerelle (même endroit que `compositions` et
`app_sessions`), lisible dans l'interface « Mon Atelier › Extensions » et par
l'outil `atelier_extensions` :

| Champ | Exemple |
|---|---|
| nom, projet source, artefact | `calendrier-routines`, `vues-perso`, `calendrier` |
| version active, version précédente | `prod/calendrier/4`, `prod/calendrier/3` |
| prises actives | `vue:accueil` |
| capacités accordées (et date, par qui) | `wikichat.list_routines` (lecture) |
| état | `active` / `inactive (atelier_min)` / `suspendue (santé)` / `retirée` |
| journal | ajouts, bascules, suspensions, appels de capacités |

Une seule source : le registre. L'interface, le contexte des agents et la
passerelle le lisent ; `plugin.json` et l'entrée du registre des connecteurs
en sont **dérivés** à chaque bascule.

#### Isolation, versions, retour arrière

- **Isolation d'origine** : tout ce qui s'affiche vient de l'hôte des
  applications, jamais de l'origine de l'Atelier (règle 1 de
  `atelier-applications.md`), avec `frame-ancestors` limité à l'Atelier.
- **Isolation de processus** : dans le pod, celle du superviseur (même
  utilisateur Unix : une extension-processus peut lire `~/work`). Le dire à
  l'ajout ; proposer « Héberger à part » pour ce qui touche des données
  sensibles.
- **Version figée** : une extension tourne depuis `prod/<nom>/<n>` (worktree
  en lecture seule), jamais depuis l'arbre de travail. Un agent qui modifie le
  projet ne modifie pas l'Atelier.
- **Retour arrière** : un geste, qui rebascule sur l'étiquette précédente et
  régénère les dérivés (entrée de connecteur, `plugin.json`, compositions).
- **Mise hors circuit automatique** : trois échecs de santé ou une erreur au
  chargement → l'extension passe `suspendue`, l'Atelier continue, une alerte
  le dit.
- **Mode sans extensions** : un bouton, et une variable
  (`ATELIER_SANS_EXTENSIONS=1`) lue au démarrage. L'Atelier ne charge alors
  aucune prise ; c'est la sortie de secours si une extension empêche d'ouvrir
  l'interface.
- **Contrat versionné** : les prises et le pont forment une API publique de
  l'Atelier, avec une version (`atelier_min`). On ne la casse qu'avec une
  version majeure et une période où les deux coexistent.

#### Ajouter une extension : le geste

1. L'agent propose (`atelier_artefact_proposer(nom, destination="atelier")`).
2. La personne voit une page claire : « Cette extension ajoute : une vue
   *Calendrier* sur l'accueil. Elle demande : lire vos routines. Elle ne
   pourra pas : modifier vos routines, voir vos conversations. »
3. Elle accorde tout, une partie ou rien → étiquette `prod/<nom>/<n>`, entrée
   au registre, prises activées.
4. Retirer = désactiver les prises et révoquer les capacités ; le projet reste.

### 3.5 Comment un artefact se sert de l'Atelier (capacités)

Le mécanisme est celui de `atelier-hebergement.md` §4 (déclaration,
consentement, jeton, journal). On l'étend à trois porteurs :

| Porteur | Comment il appelle | Ce qui l'authentifie |
|---|---|---|
| **Service** (application, service MCP) dans le pod | `ATELIER_APP_API` + `ATELIER_APP_JETON` | jeton lié à l'artefact, à la version et à la liste accordée ; renouvelé à chaque démarrage |
| **Service** en service dédié | adresse interne de l'Atelier, NetworkPolicy qui n'ouvre que ce chemin | même jeton ; à terme un jeton court du trousseau (`sub` = la personne, `act` = l'application, audience `atelier-capacites`, 10 min) |
| **Page ou vue** (pas de processus, pas de secret possible) | `POST /_atelier/capacites/<nom>/<capacité>` **sur son propre hôte** (l'hôte des applications) | la session d'applications `__Host-atelier_apps` (bornée au projet), vérifiée contre les capacités accordées **à cet artefact** ; dans une vue, le pont MCP Apps relaie de même |

Les capacités possibles, en petit nombre et toutes nommées :

| Type | Exemple | Limite |
|---|---|---|
| `outil` | `grist__list_records` | par heure ; lecture seule par défaut, écriture seulement si l'outil est déclaré ainsi et accordé comme tel |
| `composition` | `relancer_la_veille` | seulement une composition en `production` |
| `agent` | `{"projet": "creso", "consigne_max": 2000}` | le résultat est une **proposition** (file d'approbation), jamais une action faite |
| `lecture` | `wikichat.list_routines`, `atelier.projets` | vues de l'Atelier en lecture seule |

Chaque appel est vérifié, limité, **journalisé** (qui, quoi, quand, résultat,
coût de modèle s'il y en a), consultable depuis la carte de l'artefact. Une
capacité qui consomme du modèle affiche son plafond au consentement.

### 3.6 Les services MCP : du projet au connecteur, puis au service publié

Trois étapes, trois portées, **le même code** :

```
 brouillon            ajouté à mon Atelier              publié
 (le projet)          (connecteur du pool)              (service dédié)
 ┌─────────┐ proposer ┌──────────────────────┐ publier  ┌─────────────────────────┐
 │ serveur │ ───────► │ entrée du registre   │ ───────► │ son hôte, OAuth,        │
 │ /mcp en │          │ source: artefact     │          │ fiche server.json,      │
 │ essai   │          │ prod/<nom>/<n>       │          │ outils d'usage seuls    │
 └─────────┘          └─────────┬────────────┘          └───────────┬─────────────┘
   agents du projet             │ agents du pod,                    │ tout client MCP
   seulement                    │ compositions,                     │ autorisé (claude.ai,
                                │ claude.ai via /mcp de l'Atelier   │ collègues, autres)
```

1. **Brouillon** : l'artefact tourne depuis l'arbre de travail ; seules les
   conversations du projet le voient (entrée ajoutée au `.mcp.json` du projet
   par la liaison existante, adresse locale du superviseur).
2. **Ajouté à mon Atelier** : nouvelle sorte d'entrée dans le registre des
   connecteurs, `{"source": "artefact", "projet": …, "nom": …}`. La passerelle
   la résout par le superviseur (démarrage à la demande, port attribué) au
   lieu d'une URL fixe ; les enrichissements (`enrichissements.py`) sont tirés
   de la description des outils. Le connecteur rejoint le pool, les profils,
   les compositions — **et donc claude.ai**, déjà branché sur la porte `/mcp`
   de l'Atelier par OAuth. Pour la personne, « l'utiliser dans claude.ai » ne
   demande rien de plus.
3. **Publié** : « Héberger à part » + « Publier » : service dédié, hôte propre,
   `/mcp` protégé en ressource OAuth (bibliothèque `passerelle-auth` du
   trousseau quand elle est montée ; d'ici là, accès limité au propriétaire),
   outils de `pilotage` retirés, fiche `server.json` générée. Revue de sécurité
   avant le premier accès de tiers (règle d'exposition existante). L'Atelier
   garde la carte : santé, version, journal, retour arrière.

Compatibilité avec les clients externes : HTTP « streamable » seul (pas de
stdio pour un service publié), OAuth sans en-tête `Authorization` dans la
configuration du client (règle du trousseau), ressources `ui://` au format MCP
Apps pour qu'un hôte compatible affiche l'interface, annotations d'outils
renseignées.

**Catalogue** : un service publié peut être *listé* — d'abord dans un
catalogue de l'Atelier lisible par d'autres Ateliers (fichier généré, §3.8),
éventuellement dans le catalogue de l'organisation (`catalog.yaml` de la
passerelle) ou un registre MCP public. Toujours un geste, jamais un défaut.

### 3.7 Une application en production qui pilote et est pilotée

Deux sens, deux mécanismes, aucun nouveau :

- **L'Atelier pilote l'application** par ses outils de `pilotage`
  (connecteur réservé au propriétaire) : un agent peut lire l'état, lancer une
  sauvegarde, lire le journal. Promouvoir, exposer, restaurer restent des
  gestes de la personne. L'entretien (`atelier-hebergement.md` §5) tourne
  dessus.
- **L'application se sert de l'Atelier** par ses capacités (§3.5) : lancer une
  composition, demander une tâche à un agent (qui rend une proposition),
  appeler un outil d'un connecteur. Pour un usager de l'application qui n'est
  pas la personne, l'appel reste **au nom de la personne propriétaire** : le
  consentement le dit (« les utilisateurs de cette application pourront
  déclencher *relancer_la_veille*, 20 fois par heure au plus »).

### 3.8 Partage et communauté (facultatif)

Rien n'y oblige ; un Atelier seul est complet. Quand on veut partager :

- **Un gabarit** : tout projet peut être marqué « gabarit » ; il est alors
  proposé à la création de projets. Partager un gabarit = publier son dépôt
  (GitHub, déjà un geste délibéré de `git_repos.publier`).
- **Une extension** : la place de marché est **celle de Claude Code** — un
  dépôt git portant `marketplace.json`. L'Atelier en tient une par personne,
  générée depuis ses extensions marquées « partageables » ; un autre Atelier
  l'ajoute comme source. À l'installation, le même écran de consentement
  s'affiche : **ce qui vient d'ailleurs ne reçoit aucune capacité d'office**,
  et n'est jamais activé sans avoir été lu (le texte des commandes, skills et
  compositions est montré).
- **Un service MCP** : on partage l'adresse du service publié, pas le code.

---

### Ce que voit la personne

- À la création d'un projet : « Que voulez-vous faire ? » et quatre cartes —
  *Une page* (« un tableau de bord, un formulaire »), *Une application*
  (« avec ses données et ses utilisateurs »), *Un outil pour les agents*
  (« un service MCP »), *Un savoir-faire* (« une routine, un agent, une
  commande »). Plus « Partir d'un gabarit » si elle en a.
- Sur la carte d'un artefact : deux boutons qui disent où il va — **Ajouter à
  mon Atelier** et **Publier** — actifs quand une proposition est prête.
- « Mon Atelier › Extensions » : la liste du registre, avec pour chacune ce
  qu'elle ajoute, ce qu'elle peut faire, sa version, **Revenir en arrière**,
  **Retirer**, et le bouton **Mode sans extensions**.

### Ce que voit l'agent

- Dans `.atelier/contexte.md` : la famille du projet, le gabarit et sa
  version, les artefacts et leurs prises, ce qui est ajouté à l'Atelier ou
  publié, et à quelle version.
- Dans la consigne du gabarit (`CLAUDE.md` du projet) : les règles de la
  famille.
- Outils : `atelier_gabarits` (lister), `atelier_projet_creer(famille,
  titre, gabarit?)`, `atelier_artefact_proposer(nom, destination, resume)`
  (`destination` : `atelier` ou `production`), `atelier_extensions` (lecture).
  Aucun outil pour ajouter, publier, accorder ou retirer : ce sont des gestes
  de la personne.

---

## 4. Parcours types

### « Je veux un tableau de bord de mes données Grist » (page)

1. Nouvelle conversation, « Je veux un tableau de bord de mes contacts
   Grist ». L'agent propose la famille *Page* ; la personne valide ; le projet
   `tableau-contacts` naît du gabarit.
2. L'agent écrit `artifacts/tableau/index.html` et déclare
   `capacites: [{"type": "outil", "nom": "grist__list_records"}]`. En
   brouillon, la page appelle `/_atelier/capacites/tableau/grist__list_records`
   sur son hôte : en brouillon, les capacités du projet valent pour le
   propriétaire qui regarde (pas de consentement pour soi-même, mais journal).
3. L'aperçu s'ouvre à côté de la conversation. « Ajoute un filtre par ville. »
4. `/proposer` : capture d'écran jointe. La personne clique **Ajouter à mon
   Atelier**, accepte « lire la table Contacts ». La vue *Contacts* apparaît
   sur son accueil.
5. Plus tard : **Publier** pour un collègue. L'Atelier prévient : « cette page
   lit Grist en votre nom ; vos invités verront ce que vous voyez » et propose
   la lecture d'une seule table.

### « Je veux un outil MCP qui interroge mon service » (service MCP)

1. « Je veux que mes agents puissent interroger l'API de mon service de
   réservations. » Famille *Outil pour les agents*.
2. L'agent écrit le serveur depuis le gabarit ; la clé de l'API est demandée
   par l'interface des secrets et référencée (`secrets: {"RESA_CLE": "resa"}`) ;
   jamais dans la conversation.
3. `/apercu` : l'agent liste les outils et en appelle un, en brouillon.
4. **Ajouter à mon Atelier** → connecteur *Réservations* dans « Mes
   connecteurs », utilisable dans toute conversation, dans les compositions, et
   dans claude.ai sans autre réglage.
5. Six mois plus tard, **Publier** pour l'équipe : service dédié, connexion
   OAuth, outils de pilotage retirés. La carte reste dans l'Atelier ; une
   routine d'entretien surveille la santé et propose une correction sur une
   branche en cas d'échec.

### « Je veux ajouter à mon Atelier une vue calendrier de mes routines » (page, destination Atelier)

1. Famille *Page*, `offre: {page, vue: {emplacement: "accueil"}}`,
   `capacites: [{"type": "lecture", "nom": "wikichat.list_routines"}]`.
2. En brouillon, la vue s'essaie dans l'onglet du projet (jamais sur l'accueil
   tant qu'elle n'est pas ajoutée).
3. **Ajouter à mon Atelier** : « ajoute une vue *Calendrier* sur l'accueil ;
   peut lire vos routines ; ne peut pas les modifier ». Accordé.
4. Une erreur dans une version suivante ? La vue est suspendue, l'accueil
   s'affiche sans elle, **Revenir en arrière** la rétablit en un geste.
5. Plus tard : « et je veux pouvoir décaler une routine depuis la vue » →
   nouvelle capacité demandée → nouvel écran de consentement, rien d'office.

### « Chaque lundi, fais-moi une synthèse de ma veille » (savoir-faire)

1. Famille *Savoir-faire* : une composition (`collecter → résumer →
   déposer dans Grist`) et une routine (`lundi 8 h`, plafond 1 passe).
2. `/essayer veille` joue la composition à blanc ; la routine tourne une fois
   en brouillon.
3. **Ajouter à mon Atelier** : la composition passe `production`, la routine
   est déclarée à wikichat avec son plafond, la commande `/veille` devient
   disponible dans VS Code et au terminal.

### « Mon application de réservation doit pouvoir relancer un agent » (application en production)

L'application publiée déclare `{"type": "agent", "projet": "resa",
"consigne_max": 1000}`. Au consentement : « cette application pourra demander
une tâche à un agent du projet *resa* ; le résultat vous sera proposé avant
toute action ». Chaque demande apparaît dans la file des propositions et dans
le journal de l'application.

---

## 5. Ce qu'il faut construire, par étapes démontrables

Prérequis : lots 1 (brouillon/production), 3 (panneau et propositions) et 4
(capacités) de `atelier-hebergement.md`, et le gabarit de base de
`structure-projet.md`. Les étapes ci-dessous s'y ajoutent.

| Étape | Contenu | Démonstration |
|---|---|---|
| **F1 — Familles et gabarits** | `famille` et `gabarit` dans `projet.json` ; `gabarits/{page,application,service-mcp,savoir-faire}/` dans le dépôt de l'Atelier ; `projects.py` crée depuis un gabarit ; `atelier_gabarits`, `atelier_projet_creer` ; quatre cartes à la création | créer les quatre projets témoins en un message chacun ; `/verifier` vert à la création |
| **F2 — Manifeste v2** | `artefact.json` `version: 2` : `offre`, `capacites`, `entretien`, `atelier_min`, `type: savoir-faire` ; v1 toujours lu ; modèle strict et fermé comme aujourd'hui | refus nommés sur manifestes fautifs (tests de `manifeste.py`) |
| **F3 — Connecteur depuis un artefact** | entrée de registre `source: artefact` résolue par le superviseur ; brouillon visible du seul projet ; enrichissement automatique | le service MCP témoin appelé depuis une conversation d'un autre projet, puis depuis claude.ai |
| **F4 — Registre des extensions** | table, écran de consentement, version figée, dérivés régénérés, retour arrière, suspension automatique, mode sans extensions ; `atelier_extensions` | ajouter, casser volontairement, voir la suspension, revenir en arrière |
| **F5 — Vues** | cadre de vue dans l'interface (accueil, projet, conversation), iframe sur l'hôte des applications, pont au format MCP Apps (sous-ensemble : initialisation, thème, appel de capacité) ; `/_atelier/capacites` pour pages et vues | la vue calendrier des routines sur l'accueil |
| **F6 — Savoir-faire** | import des compositions (statut `validated` puis `production` à l'ajout), déclaration des routines à wikichat avec plafonds, place de marché locale Claude Code générée (commandes, skills, sous-agents), refus des hooks | `/veille` disponible dans VS Code et au terminal après ajout |
| **F7 — Affichage de MCP Apps dans les conversations** | une ressource `ui://` renvoyée par un outil s'affiche dans la conversation de l'Atelier (même cadre que F5) | l'interface d'un service MCP tiers compatible affichée dans l'Atelier |
| **F8 — Publication d'un service MCP** | service dédié (lot 6 d'hébergement) + `/mcp` en ressource OAuth (`passerelle-auth`) + retrait du pilotage + `server.json` | un second compte SSPCloud branche le service dans son claude.ai |
| **F9 — Partage** | projet marqué gabarit ; place de marché d'extensions partageables ; installation avec consentement | un gabarit et une extension installés dans un second Atelier |

Ordre proposé : F1 → F2 → F3 (le plus de valeur tout de suite, et la preuve
que le modèle tient), puis F4 → F5 (les extensions sûres), F6, puis F7, F8,
F9. F1 à F3 ne demandent ni nouveau pod ni nouvelle origine.

---

## 6. Risques, limites, questions à trancher

### Risques et limites

- **Une extension-processus lit le disque du pod** (même utilisateur Unix que
  les agents). L'isolation réelle est le service dédié. Le dire à l'ajout ;
  ne pas prétendre le contraire.
- **Pages et capacités au nom du propriétaire** : une page publiée qui lit
  Grist expose ce que voit le propriétaire. Il faut des capacités fines
  (une table, lecture seule) avant toute publication d'une page à capacités.
- **Plugins et `--strict-mcp-config`** : les tours de l'Atelier chargent un
  fichier MCP effectif strict ; un serveur MCP déclaré dans un plugin pourrait
  être ignoré dans l'Atelier et chargé dans VS Code — l'écart que
  `coherence-projet.md` interdit. D'où la règle : **un savoir-faire ne déclare
  pas de serveur MCP** ; les connecteurs passent par la prise `mcp` et le
  registre. À vérifier aussi : prise en charge des plugins par l'extension
  VS Code et par la version du CLI du pod.
- **MCP Apps évolue** : n'implémenter que le sous-ensemble nécessaire,
  derrière le pont de l'Atelier, pour absorber les changements à un seul
  endroit.
- **Contrat des prises** : dès qu'il existe, c'est une API publique à
  maintenir. Le garder petit (cinq prises, quatre types de capacité).
- **Gabarits qui vieillissent** : un gabarit figé devient une dette dans
  chaque projet qui en est né. D'où le besoin de mise à jour depuis le gabarit
  (question 3).
- **Coût de modèle** : routines et agents des savoir-faire consomment ; le
  plafond de passes et son affichage sont obligatoires, pas optionnels.
- **Réentrance** : une application qui demande un agent qui appelle une
  composition qui appelle l'application. Borne proposée : une capacité `agent`
  ne peut pas être exercée depuis un tour lancé par une capacité (profondeur 1).

### Questions à trancher par Nicolas

1. **Quatre familles** (page, application, service MCP, savoir-faire), et
   « extension » comme **destination** plutôt que comme famille : d'accord ?
2. **Deux manifestes** (`projet.json`, `artefact.json` v2) et tout le reste
   généré : d'accord, ou préférer un manifeste unique au niveau du projet ?
3. **Moteur des gabarits** : `copier` (mise à jour d'un projet depuis une
   nouvelle version du gabarit, fichier de réponses suivi) ou simple copie
   (plus simple, pas de mise à jour) ?
4. **Où vivent les gabarits** : dans le dépôt de l'Atelier (versionnés avec
   son API, proposé) ou dans un dépôt à part ?
5. **Hooks interdits dans les extensions**, sans exception : d'accord ?
6. **Pont des vues au format MCP Apps** plutôt qu'un format propre à
   l'Atelier : d'accord, sachant que la spécification bouge encore ?
7. **Capacités des pages** par la session d'applications (bornée au projet,
   sans jeton dans la page) : suffisant, ou faut-il une session par artefact
   (un hôte par application, déjà envisagé pour Grist) ?
8. **Brouillon et capacités** : en brouillon, les capacités déclarées valent
   sans consentement pour le propriétaire qui regarde (journalisées) — ou
   faut-il consentir dès le brouillon ?
9. **Publication d'un service MCP à des tiers** : attendre `passerelle-auth`
   (trousseau) ou ouvrir d'abord un mode « propriétaire seul » ?
10. **Place de marché** : celle de Claude Code (proposé) ou un catalogue propre
    à l'Atelier ?

---

## 7. Évaluation

**Désirable.** Pour la personne non technicienne : quatre cartes au lieu d'une
page blanche, deux boutons (« Ajouter à mon Atelier », « Publier ») au lieu
d'un savoir-faire de déploiement, et une page qui dit en clair ce que chaque
extension peut faire. Pour Nicolas : l'Atelier se complète sans toucher son
cœur ni reconstruire l'image, et ce qui est fait pour soi (un connecteur, une
vue) devient partageable par le même chemin. Pour les agents : un point de
départ cadré (structure, consigne, tests) qui évite de redécouvrir à chaque
projet ce que le Lecteur Grist a appris en 65 commits.

**Faisable.** Presque tout existe : artefacts et superviseur, hôte des
applications, registre des connecteurs, compositions avec leur cycle
`validated → production`, porte `/mcp` et OAuth, routines wikichat, plugins
Claude Code. Le neuf : les gabarits (fichiers), le manifeste v2 (extension
d'un modèle pydantic), l'entrée de registre `source: artefact`, le registre des
extensions (une table), le cadre de vue et son pont. F1–F3 se livrent sans
nouveau pod.

**Viable.** Coût de fonctionnement nul pour les pages et savoir-faire (pas de
processus), arrêt sur inactivité pour les services, plafonds pour les
routines. Maintenance concentrée en deux points : les gabarits (un par
famille) et le contrat des prises (versionné, petit). Le plus gros risque de
maintenance — un format d'extension maison — est évité en s'appuyant sur MCP,
MCP Apps et les plugins Claude Code.

**Cohérent avec les autres thèmes.**
- *Hébergement* : on réutilise brouillon/production, capacités, entretien,
  service dédié et exposition sans rien redéfinir ; on ajoute une destination
  (« mon Atelier ») à côté de la production.
- *Structure et cohérence des projets* : le gabarit **est** la structure type ;
  `projet.json` et `artefact.json` restent les seules sources ; les dérivés
  (`plugin.json`, entrée de connecteur, contexte) suivent la règle « une
  information = un endroit » et le principe « même chose sur toutes les
  surfaces » (un savoir-faire ajouté est chargé nativement par Claude Code
  partout).
- *Agents gardiens* : l'entretien de chaque artefact et la suspension
  automatique des extensions sont leur terrain ; les agents restent
  proposeurs, les gestes (ajouter, publier, accorder, revenir) restent à la
  personne.
- *Interface* : une vue d'extension est une page de l'hôte des applications
  affichée dans un cadre — le même que pour l'aperçu d'un artefact à côté de la
  conversation.
