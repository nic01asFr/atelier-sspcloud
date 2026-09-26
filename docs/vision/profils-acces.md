# Profils d'accès : qui reçoit quels outils

Contrat du 26/09/2026, posé avec Nicolas après l'audit `docs/coherence-outils-audit.md`. Il
précise `architecture-transverse.md` §1.1 (acteurs) et §1.5 (outils), et il fait foi pour les
équipes du lot « profils ».

## Principe

- **Un profil par type d'acteur, identique sur toutes les surfaces.** Une conversation d'agent
  code reçoit exactement la même chose dans l'app, dans VS Code et au terminal : mêmes serveurs,
  mêmes outils, mêmes refus, mêmes hooks, même mode de permission, même version du CLI.
- **Ce qu'on voit dépend du profil, pas de la surface.**
- Un profil se **filtre à la source**, par le serveur qui expose les outils, et pas seulement par
  une consigne au modèle.
- **Voir un autre projet passe par ses agents.** Un agent code travaille dans son projet. Pour
  voir ou faire agir un autre projet, il s'adresse aux agents de ce projet par wikichat
  (message, fil). L'Assistant procède de même pour explorer ou agir : il délègue plutôt que
  d'agir directement, sauf pour les commandes de l'Atelier qui sont les siennes.
  **À revoir à l'usage.**

## Profil « agent code »

| Brique | Accès | Encadrement |
|---|---|---|
| Outils natifs de Claude Code | tous (fichiers, Bash, recherche, sous-agents, WebFetch) | WebSearch refusé ; son remplacement (navigateur, WebTools) viendra plus tard. Hook du socle actif, qui refuse `pkill -f` et l'écoute sur `0.0.0.0` |
| Connecteurs du projet | ceux que la personne a choisis pour ce projet | secrets par référence ; un connecteur en échec d'authentification n'est pas distribué |
| wikichat | **limité à son projet** : état et notes de son projet, sa mémoire, sa connaissance et celle de son projet, messagerie et fils (pour s'adresser aux agents d'autres projets) | pas de vue globale des projets, pas de lancement d'agent, pas de trigger ni de routine, pas d'audit global ; filtré par le serveur wikichat selon le profil annoncé par le pont |
| Navigateur | **sa propre fenêtre Chrome isolée**, avec les onglets qu'il veut | plafond d'onglets par conversation (performance) ; plafond global de Chrome (6) |
| Atelier | **les seuls outils de son projet** : ses créations (créer, vérifier, démarrer, arrêter, journal), `atelier_montrer`, `atelier_navigateur_ouvrir` | le serveur `atelier` en profil `code` n'expose que ces outils, bornés au projet de la conversation ; ni méta-outils, ni passerelle, ni commandes globales, ni « À valider » |
| Onyxia | **seulement par le déploiement de son projet** | voir plus bas |

## Profil « Assistant »

- **Tous les outils de l'Atelier** : le serveur `atelier` au complet, en profil `assistant`, avec
  commandes globales, carte, « À valider », journal et décider.
- **Tous les autres outils**, par les deux méta-outils de la passerelle (`gateway_find_tools`,
  `gateway_call_tool`), classes d'action vérifiées par le serveur.
- **wikichat au complet.**
- **Onyxia au complet**, pour gérer l'ensemble. À étudier au regard des usages.
- Les règles de `assistant-synthese.md` §2 s'appliquent : confirmation, inverse, preuve,
  « À valider ».

## Onyxia : lié au déploiement d'un projet

Le but : relier **de façon standard un projet à un pod** (et, s'il le faut, à un accès GPU).
L'accès d'un agent code à Onyxia est alors cadré par le fait de vouloir déployer **ce** projet.

1. Le projet déclare son déploiement dans `.atelier/projet.json`, en posant un bloc
   `deploiement` : pod ou service lié, besoin de GPU, commande de démarrage. Cette déclaration
   se fait par une commande de l'Atelier, en classe `engageante`.
2. Un agent code de ce projet reçoit les outils Onyxia **bornés à ce pod** : exécuter, lire,
   état, démarrer et arrêter son service, basculer son GPU. Il ne reçoit pas les autres pods,
   `expose_public` ni le déploiement d'un autre service.
3. Un projet sans `deploiement` : pas d'Onyxia pour ses agents.
4. L'Assistant peut tout, avec les confirmations d'usage. `expose_public` reste `reservee` pour
   tout le monde (socle).
5. Correction préalable : le serveur Onyxia ne doit plus bloquer le démarrage d'un tour.
   Aujourd'hui il ne répond pas à `initialized`, et chaque tour attend 30 s (audit G3).

## Mode de permission

- **Une seule liste** : défaut, accepter les modifications, plan, **bypass**.
- **Un défaut par projet** et **un choix par conversation** qui le remplace, écrits à un seul
  endroit que lisent l'app, VS Code et le terminal.
- Choisir bypass dans l'app le met aussi dans VS Code pour cette conversation, et inversement.
- **Aucun résidu** : ni réglage machine qui impose `--allow-dangerously-skip-permissions`, ni
  `bypassPermissions` codé en dur dans un projet.

## Vérification

- **Le vérificateur de cohérence** compare, pour chaque vrai projet et chaque surface (app,
  VS Code, terminal interactif, shell non interactif), ce que Claude Code annonce au démarrage
  (`system/init`) :
  - serveurs et outils ;
  - version ;
  - mode ;
  - modèle et effort ;
  - hooks réellement exécutables depuis le projet.
- Il compare les deux profils à ce contrat.
- Les gardiens le font tourner régulièrement, sans modèle.

## État — équipe A (serveur `atelier`, navigateur, `atelier-app`), 26/09/2026

Branche `lot-profils`. « Vérifié » = exécuté et vu fonctionner (tests `pytest`
de comportement, ou essai réel nommé) ; « non vérifié » = écrit seulement.

### Serveur `atelier` par profil

La porte `/mcp` et `/v1/commandes` lisent `X-Atelier-Profil` et
`X-Atelier-Conversation` (`commandes/profils.py`). Le filtre tient à la liste
(`tools/list`, `GET /v1/commandes`) **et** à l'appel (`tools/call`,
`POST /v1/commandes/<nom>`), dans la passerelle (`mcp/gateway.py`) et dans le
catalogue (`commandes/catalogue.py`).

| Profil | Outils |
|---|---|
| `code` | exactement 8 : `atelier_artefacts`, `atelier_artefact_creer`, `atelier_artefact_verifier`, `atelier_artefact_demarrer`, `atelier_artefact_arreter`, `atelier_artefact_journal`, `atelier_montrer`, `atelier_navigateur_ouvrir`. Schémas adaptés : `projet` facultatif, `auteur` retiré. Consignes d'initialisation propres ; `prompts` et `resources` de la passerelle vides |
| `assistant` | les 27 commandes exposées (`atelier_a_valider`, `_a_valider_refuser`, `_a_valider_rouvrir`, `atelier_annuler`, les 6 des créations, `atelier_conversation_ranger`, `_ressortir`, `atelier_conversations`, `atelier_decider`, `atelier_envoyer`, `atelier_interrompre`, `atelier_journal`, `atelier_montrer`, `atelier_navigateur_ouvrir`, `atelier_ouvrir`, `atelier_projet_creer`, `_modifier`, `_ranger`, `_ressortir`, `atelier_projets`, `atelier_suivre`, `atelier_transcript`), plus ce que le profil de la passerelle expose (méta-outils `gateway_*`, compositions). `atelier_projet_publier` et `atelier_a_valider_accepter` restent `reservee`, jamais exposées |

**Qui décide du profil : la conversation, côté serveur**
(`profils.profil_effectif`). La porte lit `X-Atelier-Conversation` et sa fiche :

| Requête | Profil retenu |
|---|---|
| conversation de l'Assistant (`kind = assistant`, ou dossier sous `assistant_root`) | `assistant` ; `code` si l'en-tête annonce `code` |
| toute autre conversation connue | `code`, quel que soit l'en-tête |
| conversation inconnue (VS Code, terminal, lancement hors de l'app ; `poste` compris) | l'en-tête, `code` par défaut ; `assistant` seulement sans `X-Atelier-Projet` et avec un `X-Atelier-Dossier` sous `assistant_root` (correctif du 26/09 : l'Assistant hors de l'app ne recevait que les 8 outils de `code`) |
| sans conversation (passerelle, claude.ai, ancien client) | comportement d'avant (tout), sauf en-tête `code` ; journalisé |
| en-tête de valeur inconnue | `code` |

**Projet d'une conversation inconnue** (VS Code, terminal) : en profil `code`
seulement, le projet vient de `X-Atelier-Projet` (écrit par S dans le
`.mcp.json` du projet), s'il nomme un dossier existant sous `projects_dir` ;
sinon refus. Pour une conversation connue, la fiche décide et un désaccord
avec l'en-tête est journalisé. L'en-tête ne donne jamais `assistant`.
**Vérifié** : création écrite dans le projet annoncé, projet inexistant ou
forgé refusé, en-tête ignoré par une conversation connue, jamais `assistant`.
Limite : `atelier_montrer` et `atelier_navigateur_ouvrir` demandent encore une
conversation connue de l'Atelier (le panneau est celui d'une conversation).

`X-Atelier-Profil` ne peut que restreindre. Une conversation sans en-tête ou
sans conversation est notée dans le journal `atelier.profils` (une ligne par
conversation, rappelée au plus toutes les dix minutes). L'équipe O peut
reprendre `profil_effectif` pour son mandataire Onyxia : la conversation
décide, l'en-tête restreint.

- **Vérifié** (`tests/test_profils_acces.py`, par la vraie porte `/mcp`, la vraie
  passerelle et le vrai catalogue ; seul le pool amont est simulé) : liste
  exacte des deux profils ; refus à l'appel en `code` de `gateway_find_tools`,
  `gateway_call_tool`, `gateway_list_compositions`, d'une composition, d'un
  outil du pool (rien n'atteint le pool), de `atelier_decider`, `_journal`,
  `_a_valider`, `_projets`, `_suivre`, `_transcript`, `_envoyer`,
  `_projet_creer` ; refus au journal avec l'acteur `conversation:<id>` ;
  projet tiré de la conversation (liste bornée à ses créations, création
  écrite dans son dossier avec la conversation pour auteur, `projet` étranger
  refusé) ; refus sans conversation, avec `poste`, une conversation inconnue
  ou un identifiant forgé (`../..`) ; conversation retrouvée par
  `claude_session_id` (reprise dans VS Code) ; mêmes gardes par
  `/v1/commandes` ; profil déduit : un agent code qui annonce `assistant`
  reste en `code` (liste et appel, par `/mcp` et `/v1/commandes`), une
  conversation inconnue est en `code`, la conversation de l'Assistant a tout,
  et restreinte si elle annonce `code` ; compatibilité sans conversation et sa
  ligne de journal.
- **Recherche de l'Assistant (audit M7)** : `gateway_find_tools` cherche aussi
  dans les commandes `atelier_*` (`kind` et `server` = `atelier`), avec des mots
  d'intention pour chacune (`tool_search.MOTS_CLES_PAR_OUTIL`). Un refus d'une
  commande appelée par `gateway_call_tool` n'est plus présenté comme « nom
  inconnu ». **Vérifié** par 7 requêtes d'intention (« montrer ma page dans le
  panneau » → `atelier_montrer`, « autorisation en attente » →
  `atelier_decider`, etc.), le filtre `server="atelier"` et l'inventaire.
- **Non vérifié** : le comportement sur le pod avec un vrai `claude` (la
  déclaration qui pose `X-Atelier-Profil` est à l'équipe S) ; le nombre réel
  d'outils `gateway_*` et `composition_*` que verra l'Assistant dépend du
  profil de passerelle actif (7 et 2 mesurés par l'audit).
- **Limite du correctif** : pour une conversation inconnue, le profil
  `assistant` repose sur la configuration écrite par l'Atelier (en-têtes
  `X-Atelier-Profil`, `X-Atelier-Dossier`, absence de `X-Atelier-Projet`).
  C'est le même niveau de confiance que la clé propriétaire : un agent qui
  lit la clé peut aussi écrire ces en-têtes. **Vérifié** : conversation
  inconnue avec `assistant` et le dossier de l'Assistant → méta-outils ; avec
  un `X-Atelier-Projet`, sans dossier ou avec un dossier hors de
  `assistant_root` → `code` ; conversation connue de `code` qui annonce
  `assistant` (dossier compris) → `code`.
- **Limite connue** : la clé de la porte, `ATELIER_MCP_KEY`, est celle du
  propriétaire. Un agent qui la lit et **omet l'en-tête de conversation** garde
  un accès complet (cas « sans conversation »). Il peut aussi nommer la
  conversation d'un autre. Fermer ce trou demande des capacités courtes par
  conversation, émises par l'Atelier et vérifiées par la porte : hors de ce
  lot.
- **Changement visible dès maintenant** : VS Code et le terminal envoient
  aujourd'hui `X-Atelier-Conversation: poste`. Ils passent donc en `code`, et
  comme `poste` ne nomme aucun projet, leurs 8 outils répondent « le projet ne
  peut pas être établi ». `atelier-app` (qui prend `CLAUDE_CODE_SESSION_ID`)
  marche pour une conversation reprise de l'Atelier.
- **À la charge de S** : écrire `X-Atelier-Profil: code` dans la déclaration
  `atelier` des projets de code (`.mcp.json` et fichier effectif) et
  `assistant` pour l'Assistant ; hors de l'Atelier, faire porter à
  `X-Atelier-Conversation` l'identifiant du CLI plutôt que `poste`
  (`${ATELIER_SESSION:-${CLAUDE_CODE_SESSION_ID}}`, si Claude Code développe
  cette variable dans les en-têtes : à vérifier). Une conversation ouverte
  directement dans VS Code, jamais vue par l'Atelier, restera inconnue : le
  profil `code` n'y trouve pas de projet tant que l'Atelier n'adopte pas la
  conversation.

### Navigateur

- Une fenêtre Chrome isolée par conversation : inchangé (un processus
  `atelier-chrome` par client, `docs/navigateur-atelier.md` §3).
- **Plafond d'onglets** `ATELIER_CHROME_ONGLETS_MAX` (8 par défaut, 0 = sans) :
  filtre stdio `bin/atelier-chrome-onglets.mjs` que le lanceur place devant
  `chrome-devtools-mcp`. **Vérifié** : `tests/test_plafond_onglets.py` (faux
  serveur au format 1.10.1) ; essai réel sous Windows, filtre devant le vrai
  `chrome-devtools-mcp` 1.10.1 et un vrai Chrome, plafond 4 : trois `new_page`
  passent, le quatrième rend « Plafond d'onglets atteint… Ferme un onglet ».
  Le format `## Pages` / `<id>: …` a été relu dans le `McpResponse.js` installé
  sur le pod (lecture seule). **Non vérifié** : le lanceur modifié sur Linux
  (ses tests, `tests/test_lanceur_chrome.py`, sont sautés hors Linux ; seule la
  sortie `ATELIER_CHROME_VERIFIER=1` a été vue sous Git Bash).
- **Coût mesuré** d'un onglet (Windows, mémoire privée) : ≈ 30 à 50 Mo pour une
  page légère, ≈ 200 à 260 Mo pour une page lourde (détail :
  `docs/navigateur-atelier.md` §3, « Plafond »). Pas de mesure sur le pod.
- **Identité `passerelle-atelier`** (documentée, inchangée) : quand un outil
  `wikichat__*` est appelé par `gateway_call_tool` (ou par une composition), il
  part par l'entrée SSE du pool, que `wikichat_mcp.renommer_la_passerelle`
  réécrit au démarrage en `?agent=passerelle-atelier`. wikichat voit donc
  l'auteur `passerelle-atelier`, pas la conversation qui a appelé (audit M8) :
  mémoire, messages et notes écrits par ce chemin portent ce nom. Un agent code
  n'a plus ce chemin (profil `code` : pas de passerelle) ; il parle à wikichat
  par son pont natif, sous son propre nom. L'Assistant l'a encore : qu'il
  préfère son pont natif pour wikichat. Retirer wikichat du catalogue proposé
  reste au lot F / à l'équipe W.

### `atelier-app`

- `atelier-app montrer <nom> [chemin]` et `atelier-app ouvrir-navigateur <nom>
  [chemin]` appellent `POST /v1/commandes/atelier_montrer` et
  `…/atelier_navigateur_ouvrir` avec `X-Atelier-Conversation`
  (`ATELIER_SESSION`, sinon `CLAUDE_CODE_SESSION_ID`) et `X-Atelier-Profil:
  code` : mêmes gardes que les outils. Code 1 sur un refus, 2 sans
  conversation. **Vérifié** : `tests/test_atelier_app_montrer.py` lance le vrai
  script (`sh`, `curl`, `python3`) contre un Atelier de test servi par
  uvicorn. Les sous-commandes d'avant (`creer`… `journal`) passent toujours par
  `/v1/apps`, sans profil.

### Consignes

`docs/consignes/socle.md`, « Montrer ce que tu produis », réécrite pour le
profil `code` ; `transcripts-youtube.md` ne passe plus `projet`. À reposer sur
le pod (`~/work/projects/CLAUDE.md` et le projet concerné) : **non fait**, pod
en lecture seule pendant ce lot.
