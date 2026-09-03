# Design — Shell unifié Atelier

**Date** : 2026-08-29 (maj 12:06)  
**Statut** : validé  
**Approche** : shell partagé minimal

## Objectif

Shell **sidebar + main** partout ; discussion réutilisable ; mobile liste ↔ détail ; copy grand public ; pastilles d’état homogènes.

## Principes

1. Même squelette partout (`.view-shell`).
2. Discussion = composant partagé (Code / Assistant / Agent).
3. Atelier relaie gateway / pilote — ne réinvente pas.
4. Mobile &lt; 720 : un panneau à la fois.
5. Jargon en secondaire ; libellés type outils grand public (GPT / Copilot / Zapier).
6. **Pastilles d’état** dans toutes les listes (Agent, Code, Assistant, Connecteurs).
7. **`+` en tête de liste** : nouveau projet / conversation / connecteur / agent.

## Agent — trois pages centrales

| Panel | Contenu |
|-------|---------|
| **home** | Vue d’ensemble (planificateur + file globale) — **pas** une entrée de la liste |
| **create** | Formulaire pleine page (pas de modale) |
| **detail** | Agent sélectionné : Discussion \| À valider \| Réglages |

La **sidebar** ne contient que les vrais agents (+ pour créer).  
L’accueil = main sans sélection (titre « Agents » en sidebar pour y revenir).  
Ne jamais mettre « Accueil » / « Création » comme fausse carte agent.

### Création (pleine page) — champs

- Nom, Description  
- Consignes  
- Outils (profil Connecteurs — raffiné plus tard)  
- Projet (optionnel → défaut silencieux)  
- Quand : presets + **Personnaliser…**  
- Modèle (liste `/v1/models`)  

Vocabulaire : pas « personnalité » — c’est un **outil** ; consignes + outils.

### Pastilles Agent (liste)

| État | Pastille |
|------|----------|
| Actif / en cours | vert |
| En veille (armé) | ambre |
| Désactivé / pause | gris |
| À valider (N&gt;0) | accent + compteur |

## Connecteurs (cadrage)

- Sidebar Plateforme / Perso + `+` ajouter.
- Ajout en **étapes dans le détail** : déclaration (JSON/form) → vérif → credentials → test → enregistrement.
- Services plateforme : credentials dans le détail.
- Alignement design liste → passe ultérieure.

## Code — la conversation crée le projet

**Principe** : quand l'entité d'une page est une **conversation**, l'accueil *est* le
formulaire de création. Quand c'est un objet configuré (agent, connecteur), la
création reste un panel dédié. Code suit la première règle, Agent et Connecteurs
la seconde.

### La barre de conversation (haut du panneau)

Un seul composant, l'actuel `#session-bar`, dans deux états :

| État | Titre | Projet | Actions |
|------|-------|--------|---------|
| Conversation ouverte | nom de la session | **figé** (nom du projet) | état, copier l'id, VS Code |
| Accueil (aucune session) | — | **sélecteur** : « Nouveau projet » + projets existants | aucune |

Le projet est figé en conversation parce que `PATCH /v1/sessions/{id}` n'accepte
que `title` et `archived` : une conversation ne peut pas changer de projet.

### Les quatre entrées

| Geste | Projet | Session |
|-------|--------|---------|
| `+ Nouveau projet` (sidebar) | créé **immédiatement**, nom « Nouveau projet », édition inline ouverte | à l'envoi du 1er message |
| `+` sur un projet existant | inchangé | à l'envoi du 1er message |
| Accueil, aucun projet choisi | créé **à l'envoi**, nommé d'après le 1er message | à l'envoi |
| Accueil, projet choisi | inchangé | à l'envoi |

Aucune session n'est créée tant qu'aucun message n'est envoyé : c'est ce qui
produit aujourd'hui les sessions « created · 0 tour(s) » qui encombrent la liste.

### Nommage

- Depuis `+ Nouveau projet` : « Nouveau projet », éditable immédiatement.
- Depuis un premier message : les premiers mots du message (tronqués), repli sur
  « Nouveau projet » si rien d'exploitable.
- Dans tous les cas le nom reste modifiable ensuite.

### Renommage — inline partout

Double-clic sur le nom dans la sidebar : champ inline, Entrée valide, Échap annule.
`PATCH /v1/projects/{slug}` ne modifie que le **titre** ; le slug reste le nom du
dossier sur disque. Renommer est donc sans effet de bord, autant de fois qu'on veut.

### Contraintes connues

- `ProjectStore.create()` fait `mkdir(exist_ok=True)` : deux projets de même nom
  réutiliseraient le même dossier. Le slug doit être rendu unique côté client
  (`nouveau-projet`, `nouveau-projet-2`, …).
- `DELETE /v1/projects/{slug}` existe désormais, et refuse tant qu'une conversation
  subsiste ou que le dossier contient du travail. Ce que l'Atelier y a lui-même
  déposé — réglages VS Code, consigne d'ouverture, déclaration de connecteurs — ne
  compte pas comme du travail : sans cela, un projet ouvert une fois dans VS Code
  devenait indestructible.

### Ce qui disparaît

- Modale « Nouveau projet code » et modale « Renommer le projet ».
- L'écran vide « Choisis ou crée une session code ».

### À reprendre plus tard (Code)

- ~~**Ouverture VS Code cassée**~~ — réparée, et étendue : l'extension Claude Code
  s'ouvre sur la conversation courante, et une conversation née dans l'extension
  remonte comme session du projet. Mécanisme et faits mesurés dans
  [`atelier-vscode-passage-de-main.md`](../../atelier-vscode-passage-de-main.md).
- **Page projet** — un écran propre au projet lui-même, distinct de la
  conversation : revue de projet, fonctions Wikichat (mémoire, closure,
  capitalisation). À cadrer dans une réflexion plus globale, pas au fil de l'eau.

## Profils — la brique partagée entre Connecteurs et Agents

**Constat** : la configuration d'outils d'un agent (côté pilote) et le pool de
connecteurs (côté gateway) décrivent la même chose — *quels services, quels
outils, avec quelles consignes*. Il ne faut pas deux mécanismes.

### Le profil est cette brique, et il existe déjà

`GET /v1/mcp/profiles` renvoie déjà des profils complets :

| Champ | Rôle |
|-------|------|
| `org_servers` / `registry_servers` | les services retenus dans le pool |
| `tool_allowlist` | les outils retenus dans ces services |
| `meta_tools` | les méta-outils gateway (bundles, recherche, appel) |
| `mcp_instructions` | les consignes — le pilote les lit comme `mission_prefix` |
| `bundle_id`, `audience` | rattachement gateway et destination |

Créer, modifier et supprimer un profil personnel est déjà exposé
(`POST`/`PUT`/`DELETE /v1/mcp/profiles/custom`). **Ce qui manque est l'écran**,
pas le modèle.

### Où chaque chose vit

La gateway sert **tout client LLM** : elle a besoin de profils réutilisables,
définis en amont. L'Atelier est déjà cadré : un agent a un besoin précis, connu
au moment où on le crée. D'où la répartition :

| Notion | Écran | Archétype |
|--------|-------|-----------|
| Déclaration d'un service (JSON) | Connecteurs → **nouveau** | fait |
| Pool des services et leur état | Connecteurs → **liste** + **détail** | fait |
| Compositions (assembler des services pour créer un outil) | Connecteurs → **3ᵉ groupe de liste** + détail + nouveau | à construire |
| Personnalisation d'un outil (paramètres figés) | Connecteurs → détail du service | à construire |
| **Sélection d'outils d'un agent** | **Agent → création**, sur mesure | à construire |
| Sélection d'outils d'une conversation | Code → composer MCP | fait |

**Règle** : Connecteurs **fabrique** ce qui n'existe pas encore (services,
compositions, variantes d'outils). Agent **choisit** parmi ce qui existe, et
compose sa sélection lui-même plutôt que de piocher un profil préétabli.
Reprendre un profil existant reste possible — un raccourci, pas le passage obligé.

Les profils gateway (`/v1/mcp/profiles`) gardent leur rôle : ils servent les
clients LLM externes et le repiquage, pas la définition d'un agent.

### Un seul sélecteur d'outils

Agent, conversation Code et assistant sélectionnent tous des outils dans le même
pool. **Le composant de sélection doit être unique**, avec trois stockages
différents (spec de l'agent, overlay de la conversation, réglage de l'assistant).
Sinon trois sélecteurs à maintenir en parallèle.

### La sélection d'origine est exposée — fait

`handlePiloteCreate` conservait déjà la sélection dans `action.params.servers`,
mais l'overview ne relayait que `scope.tools`, aux noms nettoyés. `scope.servers`
expose désormais la sélection brute (`pilote.mjs`, sauvegarde horodatée à côté
du fichier), ce qui rend un agent relisible donc modifiable.

## Discussion agent — reprendre la session plutôt que relancer

La conversation d'un agent **est une session Claude Code ordinaire** : le pilote
la retrouve dans `~/.claude/projects/<slug>/<sessionId>.jsonl`, et l'Atelier sait
déjà reprendre une session (`harness.py` passe `--resume <claude_session_id>`).

Deux voies, dont une seule permet le dialogue :

| Voie | Message libre | Coût |
|------|---------------|------|
| `POST /pilote/api/agent/:id/continue` | **non** — prompt fixe, aucun paramètre | aucun, en place |
| Harness Atelier avec `--resume <claude_session_id>` | **oui** | rattacher une session Atelier à l'agent |

La seconde voie donne le composer, le streaming SSE et le même rendu que Code,
sans modifier le pilote. Elle suppose de créer une session Atelier dont le
`cwd` est le dossier de l'agent et le `claude_session_id` celui de son dernier
passage.

**À trancher avant de l'implémenter** : cette session doit-elle apparaître dans
la liste des conversations (elle y polluerait Code ou Assistant), rester
invisible et rattachée à l'agent, ou n'exister que le temps de l'échange ?

### Attention aux titres

Les agents de session se déclarent auprès de wikichat avec un nom, et
`sync_titles` recopie ce nom dans le titre de la conversation. Un titre saisi à
la main est désormais protégé (`title_source: "user"`), mais **renommer une
conversation reste sans effet sur le nom déclaré côté wikichat** : les deux
identités coexistent. Même remarque pour les agents, dont le renommage n'est pas
exposé (voir plus bas).

### Modifier et renommer un agent — fait

Le remplacement en place (`POST /pilote/api/agent` avec `id`) conserve id,
historique et session. Vérifié sur un agent ayant tourné : après renommage,
mêmes id et `fired`, `canResume` toujours vrai, outils inchangés, transcript
toujours lisible, aucun doublon créé.

Accès : « Modifier » dans les Réglages, ou le menu contextuel de la liste.

## Pastilles (contrat global)

Même composant `.status-dot` + variante :

| Vue | Signaux |
|-----|---------|
| Agent | actif / veille / off / à valider |
| Code | idle / en réponse / erreur |
| Assistant | en attente / terminée / erreur |
| Connecteurs | connecté / local / erreur / off |

## Le fil de conversation — ce qui le clôt

Les mécanismes sont en place : envoi au clavier et au bouton, composeur qui
grandit, pièces jointes, sélection MCP par conversation, arrêt en cours de tour,
rendu du raisonnement, des appels d'outils et de leurs sorties. Le flux est
réel — mesuré, 269 fragments étalés sur 1,7 s.

Trois manques d'usage restent, et ce sont eux qui séparent « ça marche » de
« c'est fini ». Ils valent d'être traités maintenant : l'onglet Assistant
réutilisera ce fil tel quel, et l'onglet Agent y viendra ensuite.

### Le défilement doit s'ancrer, pas se recoller

`renderThread` reconstruit le fil à chaque rendu et termine par
`thread.scrollTop = thread.scrollHeight`. Pendant qu'une réponse s'écrit —
plusieurs centaines de fragments — remonter pour relire est impossible : chaque
fragment ramène en bas.

Règle : ne recoller au bas que si l'on y était déjà, à une marge près. Sinon
rendre la position telle qu'elle était. C'est ce que fait tout fil qui se
respecte, et cela ne se remarque que quand ça manque.

### Un message doit pouvoir être repris

On ne peut rien faire d'un message : ni le copier, ni renvoyer sa question.
Copier une réponse est le geste le plus attendu d'une interface
conversationnelle.

Deux gestes, discrets, sur la ligne du message : **copier** le texte, et pour une
question, **la corriger et repartir d'elle**.

J'avais d'abord écarté la correction : une session Claude ne se rembobine pas.
C'était vrai, et la conclusion était fausse — on ne rembobine pas, on **forke**.
Le transcript porte une chaîne `parentUuid` complète : on recopie la conversation
jusqu'au message qui précède, sous une nouvelle identité, et la version corrigée
s'y envoie. L'originale reste intacte.

Le fork hérite de tout ce qui fait la conversation — dossier de travail, projet,
connecteurs — parce que ce sont des propriétés du dossier, pas de la session.
Vérifié : interrogé, un fork restitue la première question de son aînée ; le
transcript tronqué est donc valide pour `--resume`.

Ce qui a été écarté, en revanche : recopier les enregistrements annexes — file
d'attente, dernier prompt, titre. Ils n'appartiennent pas à la chaîne des
messages et désignent une session qui n'est plus la bonne ; ils se
reconstruisent d'eux-mêmes.

À noter pour plus tard : `--fork-session` existe côté CLI, mais il repart de la
fin. Pour reprendre à un endroit choisi il faut écrire le préfixe soi-même,
comme le fait l'extension Claude Code.

### L'attente doit se lire

Le modèle met plusieurs secondes avant son premier mot — mesuré à 7,9 s sur la
passerelle du pod. Pendant ce temps la bulle est muette : une pastille, rien
d'autre. Rien ne distingue « le modèle réfléchit » de « c'est bloqué ».

Or les événements arrivent bien avant le texte : `systeme` dès l'ouverture, puis
les fragments de raisonnement. La bulle en cours doit dire où l'on en est —
en attente, puis en réflexion — et s'effacer dès que le texte commence. Sans
inventer d'étapes : on n'affiche que ce que les événements disent réellement.

## Sollicitation d'un agent — deux choses à trancher

### Reprendre la session, ou en ouvrir une neuve

Les deux comportements existent déjà côté pilote : `continue` relance avec
`resumeSessionId`, `fire` ouvre une session neuve. Mais **c'est le bouton pressé
qui décide** — il n'y a pas de réglage par agent. Sollicité autrement que par ce
bouton, cron ou réveil sur mention, un agent repart systématiquement sur une
session neuve.

Ce n'est pas un détail : un agent de veille qui reprend son fil sait ce qu'il a
déjà signalé ; le même agent relancé à neuf le resignale. À l'inverse, une tâche
qui doit repartir propre ne veut surtout pas traîner le contexte du passage
précédent.

Le réglage appartient donc à l'agent, pas à celui qui le déclenche : *à chaque
sollicitation, reprendre mon fil* ou *ouvrir un fil neuf*.

La saturation du contexte n'est pas un obstacle : la compaction automatique de
Claude Code est déjà active pour toutes les sessions que l'Atelier lance —
`autoCompactEnabled: true`, `autoCompactWindow: 50000`, dans `~/.claude` comme
dans la copie durable du PVC. Un fil repris longtemps se compacte tout seul.
Aucun de nos transcripts n'en porte encore la trace, faute d'avoir atteint le
seuil, mais le mécanisme est en place et ne demande rien.

Reste une question, d'un autre ordre : la compaction résume, donc elle oublie
ce qu'elle juge secondaire. Un agent de veille qui reprend un fil compacté peut
resignaler ce qu'il avait déjà signalé. Si cela devait compter, la mémoire
appartiendrait à wikichat — une note de projet — plutôt qu'au fil.

### Un service de messagerie associé

Aujourd'hui l'onglet Réglages d'un agent porte une phrase, et rien d'autre :
« Canaux de messagerie : configuration à venir ici. »

L'idée : associer à un agent un canal — Tchap, Telegram — pour pouvoir **le
déclencher par message**, et lui répondre par le même chemin. C'est le
prolongement naturel des déclencheurs : le cron réveille l'agent à heure dite,
la mention le réveille depuis le réseau wikichat, un message le réveillerait
depuis l'extérieur.

À regarder avant de concevoir : comment Colaig s'y prend pour ce même besoin.

Trois questions à trancher : où vivent les jetons du canal (pas dans le dossier
de projet, qui se partage) ; qui a le droit de déclencher un agent par message —
un canal ouvert est une porte d'entrée ; et si la réponse revient dans le canal
ou reste dans l'Atelier.

## Git, dépôts et GitHub — fait, et ce qui reste

Le point relevé comme crucial est traité. Un projet de code est un dépôt dès sa
naissance, sur `main`, avec un premier commit qui fait exister l'histoire même
sur un projet vide — sans quoi il n'y a pas de branche et rien à lire. Le
dossier de l'assistant reste à l'écart : ce qu'il contient est de la mémoire de
session, tenue par wikichat, pas du travail dont on suit les versions.

La publication sur GitHub existe, projet par projet, privée par défaut. Elle
n'est pas automatique et ne doit pas le devenir : ouvrir un projet est un geste
de travail, le publier en est un autre, et c'est celui-là qui ne se rattrape
pas. Le jeton vit dans `~/work/.secrets/github_token` ; il ne passe ni par
l'URL du remote, que tout clone emporterait, ni par la ligne de commande, où un
`ps` le lirait.

Deux gardes ont été apprises en cassant. Le premier `git init` a versionné un
`.env` qui portait une clé et disait « ne pas committer » sur sa première
ligne : le `.gitignore` écarte désormais ce qui annonce un secret. Et la
publication regarde **l'histoire**, pas l'état du jour — un secret retiré du
suivi hier est toujours dans le commit qui l'a introduit, et c'est l'histoire
que `push` emporte.

Ce qui reste ouvert, et se décide en une fois :

- **Qui commite.** Aujourd'hui personne : l'Atelier pose le dépôt, les sessions
  y travaillent, rien ne fige. Sans commits, la veille n'a toujours rien à
  lire au-delà du premier. C'est la question qui décide si le travail de la
  passe git sert à quelque chose. Voir la section suivante : le mécanisme
  existe déjà ailleurs dans la maison, il n'y a pas à l'inventer.
- **L'identité.** `ATELIER_GIT_USER_NAME` / `ATELIER_GIT_USER_EMAIL`, par
  défaut `Atelier <atelier@localhost>`. C'est elle qui partira sur GitHub.
- **Les dépôts déjà là.** `nouveau-projet` est un clone amont : ses commits
  sont ceux d'autrui, et son identité locale porte une adresse d'emprunt.
  Un projet cloné et un projet né ici ne se traitent pas pareil.

### Qui commite — reprendre ce que wikichat fait déjà

Avant d'écrire quoi que ce soit : **wikichat porte déjà le motif**, éprouvé et
en service. Deux briques à regarder plutôt qu'à refaire.

**`scripts/publish-memory.mjs` + `src/memory-publish-hook.mjs`** — commiter sur
événement, sans y penser. Le script est idempotent : il ne commite que si un
hash de contenu a changé, fait `git add -A` puis lit `status --porcelain` pour
ne rien faire s'il n'y a rien, écrit un message généré, et pousse en option
(`--no-push`). Le hook le lance **détaché** — la réponse de l'outil appelant
n'attend jamais le push — et il est **opt-in** : sans `WIKICHAT_MEMORY_REPO`,
no-op silencieux, aucun couplage forcé. Il est déclenché depuis
`close_project`. `scripts/ingest-inbox.mjs` reprend la même forme avec un
`git add` limité à un sous-dossier, et un `pull --ff-only` d'abord.

**`src/repo-audit.mjs`, exposé en `audit_project` / `audit_all_projects`** — la
mesure existe aussi. Il rend, par projet : dépôt ou non, branche, dernier
commit et son âge, **nombre de fichiers non commités**, distant, avance et
retard sur lui, un score sur 100 et des avertissements en clair. Son score
**pénalise déjà le travail non commité** — `uncommitted === 0` vaut 15 points,
`≤ 5` en vaut 8, au-delà rien. Wikichat tient donc depuis le début qu'un
travail qui ne se fige pas est un défaut de santé ; il lui manquait seulement
des dépôts à auditer. Il résout le chemin par le `path` que l'Atelier déclare
déjà à la création : mesuré sur le pod, il fonctionne sans rien brancher —
`default` 58/100, `claude-code` 65/100.

**Ce qu'il reste à décider**, donc, n'est plus le mécanisme mais l'événement et
le garde-fou :

- **L'événement.** `close_project` convient à une mémoire qui bouge peu. Pour
  du travail, la fin de tour est la bonne granularité — c'est l'unité qui a un
  sens, et le message de l'utilisateur fait un sujet de commit honnête.
- **Le garde-fou.** Opt-in par projet, sur le modèle de la variable
  d'environnement de wikichat. Un projet d'essai n'a pas à se remplir de
  commits.
- **Ce qu'on ne refait pas.** Ni la détection « y a-t-il quelque chose à
  figer » (`status --porcelain`, déjà dans les deux scripts), ni la mesure de
  ce qui traîne (`audit_all_projects`). L'Atelier garde son `git_repos.etat()`
  — lecture locale, sans dépendance, pour une pastille d'interface — mais
  c'est un doublon assumé, pas un oubli.

Corollaire déjà appliqué : la mission de l'agent de veille part de
`audit_all_projects` au lieu d'une boucle `git` écrite à la main, et **écrit
son compte rendu avant de déposer ses notes** — une passe s'était arrêtée juste
avant de conclure, sur un « laisse-moi ajouter les dernières notes ».

## MCP Apps — afficher une interface dans le fil

L'extension existe et elle est arrêtée : SEP-1865, close, étiquetée `final` et
`extension`, dernière révision le 4 juin 2026. Elle ne fait pas partie du
protocole de base. Documentation de référence :
`apps.extensions.modelcontextprotocol.io`.

### Ce que la spec prévoit

La description d'un outil porte `_meta.ui.resourceUri`, qui désigne une
ressource `ui://`. L'hôte lit cette ressource — une page HTML, généralement
livrée avec son JS et son CSS — et peut la précharger avant même l'appel. Il la
rend dans une iframe en bac à sable, dans le fil. `_meta.ui.csp` déclare les
origines externes que l'app a le droit de charger ; `_meta.ui.permissions`
demande micro, caméra, etc. L'app et l'hôte dialoguent en JSON-RPC par
`postMessage` : un dialecte de MCP, où certaines méthodes sont communes
(`tools/call`) et d'autres nouvelles, préfixées `ui/` (`ui/initialize`).

### Pourquoi rien n'arrivera tout seul

Mesuré, pas supposé. Dans le binaire du CLI 2.1.248 : aucune occurrence de
`ui://`, `ui/initialize` ni `resourceUri`. Or dans l'Atelier c'est le CLI qui
est le client MCP — il ne rend qu'un résultat texte. Rien ne passera par ce
chemin, quoi qu'on branche en amont.

Et la passerelle jette ce qu'il faudrait, sur deux points :

- le client amont ne parle que `tools/list` et `tools/call`, jamais
  `resources/read` — donc pas moyen d'aller chercher la ressource `ui://` ;
- les outils sont rangés en base réduits à nom, description et schéma : le
  `_meta` disparaît au passage.

### Ce que ça implique

**C'est l'Atelier qui doit devenir l'hôte, pas le CLI.** Il en a la place : il
tient déjà la passerelle, le fil, et le chemin d'envoi.

Dans l'ordre, du plus utile au plus lourd :

1. **Le passe-plat.** Garder `_meta` sur les outils, et apprendre
   `resources/read` au client amont. Utile en soi, même sans rendu : c'est ce
   qui permet de *savoir* qu'un connecteur propose une interface.
2. **Le rendu.** Un bloc iframe dans le fil, à côté du résultat d'outil dont il
   dépend, avec la CSP annoncée par le serveur.
3. **Le dialecte `ui/`** sur `postMessage`, avec une liste blanche explicite de
   ce que l'app a le droit de demander.

### Le point d'architecture à trancher

Dans la spec, l'hôte **est** le client de l'agent : quand l'app appelle un
outil, le résultat revient dans la conversation du modèle. Ici l'agent est un
sous-processus CLI et la page est une surface séparée. Un appel venu de l'app
passerait par la passerelle **sans que le modèle le sache**, et le fil
raconterait une histoire fausse.

Trois issues, à choisir avant d'écrire la moindre ligne :

- réinjecter le résultat comme un tour de l'utilisateur — l'Atelier tient le
  chemin d'envoi, c'est faisable, mais ça pollue le fil ;
- traiter l'app comme un panneau **en lecture seule**, sans `tools/call` : on
  affiche, on n'agit pas. Le plus simple, et suffisant pour un tableau de bord ;
- accepter la divergence et l'assumer, en marquant à l'écran ce qui vient de
  l'app et n'est pas passé par le modèle.

### Sécurité — l'inverse exact du rendu markdown, et c'est voulu

Le rendu des messages ne doit **jamais** exécuter de contenu étranger. Une MCP
App **est** du contenu étranger exécuté exprès, et le bac à sable est tout
l'objet. Les deux règles ne se contredisent pas, elles se répondent.

Ce qui ne doit pas être raté :

- `sandbox="allow-scripts"` **sans** `allow-same-origin`. Avec les deux,
  l'iframe s'échappe — et l'origine de l'Atelier porte la clé propriétaire dans
  son `localStorage`.
- Servir les apps depuis une **origine distincte**, si on peut en obtenir une.
- Aucune capacité par défaut : `_meta.ui.permissions` est une *demande*, pas un
  droit.
- La liste blanche des méthodes `ui/` est côté hôte, jamais négociée avec l'app.

### L'usage qui justifierait de s'y mettre

`nouveau-projet` est un service Chrome headful. Le voir dans la conversation
plutôt que par noVNC est exactement ce pour quoi cette extension existe. C'est
le premier cas à viser — pas un tableau de bord générique.

### Quand

Après l'onglet Assistant et la messagerie des agents. Le passe-plat (§1) peut
partir avant, il ne coûte presque rien et ne s'engage sur rien.

## Hors scope immédiat

- Wizard connecteur multi-étapes complet  
- Pastilles Code / Assistant (contrat posé, UI avec leurs shells)  
- Raffinement riche des profils  

## Critères (passe courante)

- [x] Accueil Agent = overview utile (cartes états)
- [x] Création = pleine page, pas modale
- [x] Détail = pleine page onglets
- [x] Pastilles Agent dans la liste
- [x] Fréquence : presets + personnaliser
- [x] Modèles depuis `/v1/models`
