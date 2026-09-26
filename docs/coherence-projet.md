# Un projet, le même partout : Atelier, VS Code, terminal, agents

Conception du 25/09/2026. S'appuie sur deux études : les mécanismes natifs de
Claude Code (documentation officielle) et l'audit de ce que chaque surface
fournit aujourd'hui pour le projet Lecteur Grist. Complète
`docs/structure-projet.md` et `docs/atelier-hebergement.md`.

## Le constat

Pour la même conversation (`72b08c5c`, Lecteur Grist) :

| | Tour de l'Atelier | VS Code | Terminal | Réveil wikichat |
|---|---|---|---|---|
| Connecteurs | 10 (fichier effectif, `--strict-mcp-config`) | 7 (`disabledMcpServers` figé) | 7 | `.mcp.json` créé avec wikichat seul |
| Outils de l'Atelier (`atelier_*`) | absents | absents | absents | absents |
| Secrets | variables **et** valeurs en clair dans le fichier effectif | en clair dans `~/.claude.json` | en clair | environnement de wikichat seulement |
| Identité wikichat | `projet-sans-nom-5-2e11c5` (ou `-fcaf6f` : deux fiches pour un fil) | `atelier` (partagée par tout) | `atelier` | nom mémorisé |
| Contexte Atelier dans CLAUDE.md | réécrit avant le tour | périmé | périmé | périmé |
| Mode de permission | par tour, `bypass` sans interlocuteur | réglage machine unique + `allowDangerouslySkipPermissions` | `defaultMode` du dossier | `bypass` codé en dur |
| Règles accordées | registre de l'Atelier (`--settings`) | perdues | perdues | perdues |
| Consigne `register` | « ne l'appelle pas » | « appelle-le » (bloc wikichat) | idem | exigé |

Conséquences : mémoire, courrier et contexte Chrome séparés selon la
fenêtre ; un réveil wikichat reprend la conversation hors de l'Atelier (sans
fiche, sans secrets, en `bypass`) et ampute les connecteurs des tours suivants ;
les secrets sont en clair à trois endroits alors que le socle affirme le
contraire ; une copie de `.claude/settings.json` de projet écraserait les
réglages globaux (`vscode_handoff.py:172-181`).

## Le principe

**Le projet se décrit dans ses fichiers ; Claude Code les charge par ses
mécanismes natifs ; l'Atelier et wikichat ne fournissent que ce qu'eux seuls
savent, par ces mêmes mécanismes, identiques sur toutes les surfaces.** Aucune
information n'est injectée par une surface et pas par les autres.

## Une source par information

| Information | Source unique | Mécanisme natif | Qui l'écrit |
|---|---|---|---|
| Règles communes | `~/work/projects/CLAUDE.md` (socle) | CLAUDE.md d'un dossier parent | l'Atelier, avec empreinte de version |
| Règles du projet | `CLAUDE.md` du projet, suivi par git | CLAUDE.md du projet | le projet |
| Ce que seul l'Atelier sait (identité, artefacts, adresses, alertes) | `.atelier/contexte.md`, ignoré | import `@.atelier/contexte.md` + hook `SessionStart` | le hook, à chaque démarrage de session, **sur toutes les surfaces** |
| État, décisions | `ETAT.md`, `docs/decisions/` | lus par l'agent (fil d'entrée) | les agents, en fin de lot |
| Connecteurs du projet | `.mcp.json` du projet (références seulement) + portée utilisateur | chargement natif, `enabledMcpjsonServers` | l'Atelier (liaison du projet) |
| Secrets | `~/work/.secrets/` | variables `${VAR}` développées par Claude Code | un seul fichier d'environnement généré, chargé par toutes les surfaces |
| Permissions accordées | `.claude/settings.local.json` du projet | `permissions.allow/deny` | l'Atelier quand la personne accorde |
| Règles de permission du projet | `.claude/settings.json` du projet, suivi | natif (non hérité des parents) | le projet |
| Mode par défaut | `.claude/settings.local.json` (`defaultMode`) | natif | l'Atelier |
| Modèle, effort, hooks globaux | `~/.claude/settings.json` | natif | l'Atelier (installation) — jamais écrasé par un projet |
| Sous-agents, commandes, skills | `.claude/agents|commands|skills` (projet) et `~/.claude/` (Atelier) | natifs | le projet / l'Atelier |
| Identité d'une conversation | l'identifiant de session Claude | `session_id` des hooks | — (dérivée : fiche Atelier et nom wikichat en découlent) |
| Historique | `~/.claude/projects/<projet>/<session>.jsonl` | natif | Claude Code ; `CLAUDE_CODE_PROJECT_DIR_NAME=<slug>` pour survivre aux renommages |

## Ce que cela change

### 1. Secrets : références partout, une seule valeur
- Le fichier effectif, `~/.claude.json` et `.mcp.json` ne portent que des
  références `${ATELIER_MCP_…}` (aujourd'hui seul `.mcp.json` le fait).
- Un fichier `~/work/.secrets/claude-env.sh` (0600), généré par l'Atelier,
  porte les valeurs ; il est chargé par le harnais, par code-server (réglage
  `claudeCode.environmentVariables` généré depuis lui), par le shell
  (`~/.bashrc`) et par wikichat pour ses processus.
- Attention au point natif : certaines variables (`ANTHROPIC_API_KEY`…) ne sont
  jamais développées dans les en-têtes — les noms `ATELIER_MCP_*` ne sont pas
  concernés.

### 2. Contexte : un hook, pas une réécriture de CLAUDE.md
- Hook `SessionStart` au niveau utilisateur (`~/.claude/settings.json`) :
  appelle l'Atelier en local avec `session_id` et `cwd` ; l'Atelier régénère
  `.atelier/contexte.md` et renvoie en `additionalContext` l'identité, le
  briefing wikichat et les alertes. Il tourne en `-p`, dans VS Code et au
  terminal, et pour les processus lancés par wikichat.
- `CLAUDE.md` du projet n'est plus réécrit ; il importe `@.atelier/contexte.md`.
- Le bloc wikichat de `~/.claude/CLAUDE.md` est réduit à ce qui est vrai
  partout : l'identité est automatique (plus de réflexe `register`), le
  briefing arrive par le hook.

### 3. Identité : une conversation = une identité
- Clé : l'identifiant de session Claude. Le hook `SessionStart` le déclare à
  l'Atelier, qui adopte la conversation (fiche créée si elle vient de VS Code
  ou du terminal, jamais deux fiches pour un même fil) et en dérive le nom
  wikichat.
- La connexion wikichat porte ce nom par `headersHelper` (natif) plutôt que par
  `?agent=` dans l'URL ; plus d'identité commune `atelier`.
- `X-Atelier-Conversation` porte cette clé vers la passerelle. Le navigateur
  n'en a plus besoin : il tourne en stdio dans le processus de la
  conversation (voir « Navigateur stdio » plus bas).

### 4. Lancements : tout passe par l'Atelier
- Réveil sur mention, routines, spawns : wikichat demande à l'Atelier d'ouvrir
  ou de reprendre la conversation (API existante `atelier_ouvrir` /
  `atelier_envoyer`), qui la lance avec le même harnais que les autres tours.
  Plus de `claude -p --resume` direct, plus de `bypassPermissions` codé en dur,
  plus de `.mcp.json` créé par wikichat.
- Une routine déclare son mode et ses plafonds (`projet.json` / `artefact.json`
  `entretien`).

### 5. Outils
- Le serveur MCP de l'Atelier (`atelier_*` : artefacts, projet) est présent
  dans tous les projets, sur toutes les surfaces.
- Les connecteurs sont présentés au modèle comme des serveurs MCP natifs
  (chargement différé natif) ; `gateway_find_tools`/`gateway_call_tool` restent
  pour les clients distants (claude.ai), pas pour les agents du pod.
- Par projet : `.mcp.json` choisit les connecteurs ; `enabledMcpjsonServers`
  les approuve ; plus de `disabledMcpServers` figé par la dernière ouverture.

### 6. Permissions et mode
- Les règles accordées dans l'Atelier sont écrites dans
  `.claude/settings.local.json` du projet : elles suivent la conversation dans
  VS Code et au terminal.
- Mode : voir « Profils et surfaces » ci-dessous (un défaut par projet, un
  choix par conversation, plus aucun réglage machine qui l'impose).
- Plus de copie de `.claude/settings.json` de projet sur le réglage global.

### 7. Mémoire et état
- Connaissance durable : fichiers du projet (`ETAT.md`, décisions).
- Apprentissages de l'agent : mémoire native de Claude Code.
- wikichat : coordination du moment ; `add_project_note` dérivé d'`ETAT.md`,
  `remember`/`recall` rattachés à l'identité unique.

## Lots

| Lot | Contenu | Pourquoi d'abord |
|---|---|---|
| A | Secrets par références partout, fichier d'environnement unique, serveur `atelier` dans tous les projets, fin de l'écrasement des réglages globaux, wikichat ne crée plus de `.mcp.json` | sécurité et outils manquants |
| B | Hook `SessionStart` + `.atelier/contexte.md` + import ; bloc wikichat réduit | même contexte partout |
| C | Identité unique (session → fiche → nom), adoption VS Code/terminal, une fiche par fil, `headersHelper` | mémoire, courrier, Chrome cohérents |
| D | Lancements wikichat par l'Atelier ; plus de `bypass` codé en dur | fin des sessions hors Atelier |
| E | Permissions et mode natifs ; `allowDangerouslySkipPermissions` retiré | règles qui suivent la conversation |
| F | Connecteurs en serveurs natifs pour les agents du pod ; passerelle réservée aux clients distants | présentation des outils |
| G | Structure de projet (`docs/structure-projet.md`) : gabarit, commandes `/reprendre` `/verifier` `/fin-de-lot` `/proposer`, migration du Lecteur Grist | reprise par les agents successifs |

Chaque lot se vérifie par le même test : ouvrir la même conversation par
l'Atelier, VS Code, le terminal et un réveil wikichat, et comparer ce que voit
l'agent (connecteurs, outils, contexte, identité, permissions). L'écart doit
être nul.

## Ce que montre l'usage (Atelier utilisé dans Chrome, 25/09)

- **Pas de vue « projet ».** Cliquer un projet déplie la liste ; la zone
  principale reste « Nouvelle conversation » (sélecteur non positionné sur le
  projet). Applications, état, connecteurs du projet ne sont visibles que dans
  une conversation.
- **Titres de conversation** tirés du premier message brut (« <!DOCTYPE html>
  <html lang=… ») ; deux fiches pour un même fil visibles côte à côte.
- **Autorisations** :
  - chaque appel d'outil, même en lecture (`wikichat__get_briefing`,
    `filesystem__list_allowed_directories`, `github__get_me`), demande une
    autorisation en mode « Réglage du service » ;
  - refuser demande une seconde confirmation (« Confirmer le refus ») peu
    visible : l'agent reste bloqué ;
  - les demandes d'un tour disparu restent affichées avec des boutons actifs
    (« Question sans réponse possible »), 7 dans la conversation Lecteur Grist.
- **Le modèle n'a pas respecté « sans rien lancer »** et a enchaîné des appels
  d'outils : la consigne seule ne suffit pas, le mode « Plan » existe pour ça.
- **Boutons « + » (nouvelle conversation)** qui ne réagissent pas au pointeur
  simulé (probablement visibles au survol seulement) : à vérifier au tactile.
- **Panneau Applications** : fonctionne ; auteur affiché brut
  (`projet-sans-nom-5-lecteur-l5`) ; ni version, ni santé, ni sauvegarde.
- **Sécurité côté navigateur** : conforme (aucune clé en `localStorage`,
  cookie invisible aux scripts).

## Liaison complète du harnais Claude Code

À vérifier et à assurer fonction par fonction, sur toutes les surfaces, en
natif si possible, sinon adaptée par l'Atelier — et **documentée** dans un
tableau tenu à jour (`docs/harnais.md`) :

| Fonction | Natif | État actuel | Cible |
|---|---|---|---|
| Mémoire (CLAUDE.md, imports, rules) | oui | section réécrite par l'Atelier | import + hook `SessionStart` (lot B) |
| Réglages, permissions, mode | oui | `--settings` par tour, réglage machine VS Code | `settings.local.json` du projet (lot E) |
| MCP | oui | fait (lot A) : `.mcp.json` du projet = fichier effectif, portée utilisateur = `atelier`, références partout | connecteurs natifs pour les agents du pod (lot F) |
| Outils différés (tool search) | oui, **désactivé par `ANTHROPIC_BASE_URL` personnalisé** | passerelle `find/call` en remplacement | vérifier `ENABLE_TOOL_SEARCH=true` avec la passerelle LLM ; sinon garder la passerelle |
| Compaction | oui (auto et réactive) | **native sur toutes les surfaces** via le relais LLM (branche `harnais-relais-secrets`, voir « État ») ; compaction de l'Atelier en repli si le relais manque | — |
| Hooks | oui | `Stop` wikichat, `SessionEnd` figer | `SessionStart` contexte, `PreToolUse` chemins protégés, `Stop` courrier unifié |
| Sous-agents, commandes, skills | oui | commandes wikichat seulement | projet + Atelier (`/reprendre`, `/verifier`…) |
| Sessions, reprise, titres | oui | deux fiches pour un fil ; titres bruts | une fiche par fil ; titre `/rename` natif synchronisé |
| Modèle, effort | oui | trois sources contradictoires | `~/.claude/settings.json` seul + surcharge de fiche |
| Autorisations interactives | oui (`--permission-prompt-tool`) | fonctionne dans l'Atelier ; refus en deux temps | règles par défaut pour la lecture, refus en un geste |
| Tâches de fond, `Monitor` | oui | non exposés dans l'Atelier | afficher et laisser arrêter |
| Plan mode | oui | proposé (« Plan ») | défaut pour les questions d'exploration |

## Interface, en correspondance avec le fonctionnement (lot H)

- **Vue projet** : titre, tête d'`ETAT.md`, applications (version, santé,
  sauvegarde), propositions, conversations, connecteurs **tels que l'agent les
  reçoit**, commandes du projet, bouton « Nouvelle conversation » visible.
- **Conversation** : titre natif (généré ou `/rename`) ; autorisations
  regroupées, refus en un geste, demandes périmées repliées en historique ;
  indication claire du mode (Plan / Demande / Édite / Sans garde-fou) et de
  l'identité ; même rendu que VS Code pour les tâches de fond.
- **Cohérence** : ce que montre l'interface est lu aux mêmes sources que ce
  que reçoit l'agent (`projet.json`, `.mcp.json`, `settings.local.json`,
  `contexte.md`) — plus d'affichage « actif » pour un serveur absent.

## Points à vérifier au lot A

Priorité entre deux entrées de même nom (portée utilisateur et `--mcp-config`) ;
comportement du hook `SessionStart` dans l'extension VS Code ; disponibilité
de l'identifiant de session pour `headersHelper` ; priorité entre
`CLAUDE_CODE_EFFORT_LEVEL` et `modelSettings`.

Mesuré le 25/09 sur le pod (binaire 2.1.281, `CLAUDE_CONFIG_DIR` de test,
serveur MCP sonde) :

- `${VAR}` est développé dans `url`/`headers` de la portée utilisateur
  (`.claude.json`), du `.mcp.json` d'un projet et d'un `--mcp-config` ;
  `${ANTHROPIC_API_KEY}` ne l'est pas (en-tête reçu : `Bearer` vide) — nos
  noms `ATELIER_MCP_*` ne sont pas concernés ;
- même nom en portée utilisateur et dans `.mcp.json` : **le projet gagne**
  (`source: project`) ;
- l'`env` de `~/.claude/settings.json` **l'emporte sur l'environnement du
  processus**, et `--settings` l'emporte sur lui : ce qu'un tour doit imposer
  passe donc par `--settings` (le harnais le fait pour l'adresse du modèle et
  la fenêtre).

Restent à vérifier : `SessionStart` dans l'extension, identifiant de session
pour `headersHelper`, `CLAUDE_CODE_EFFORT_LEVEL` contre `modelSettings`.

## État du lot A et de la compaction (branche `harnais-relais-secrets`)

### Compaction native par le relais LLM — fait, mesuré

`mcp_gateway/atelier/relais_llm.py`, processus à part sur `127.0.0.1:8790`
(`ATELIER_RELAIS_LLM_PORT`) : il doit survivre aux redémarrages de
l'Atelier, puisque VS Code, le terminal et wikichat parlent au modèle par lui.
Lancé par `install/atelier-init.sh` avant code-server et wikichat, et par
l'Atelier à son démarrage s'il manque. Il relaie tout en flux sans tampon,
remplit l'usage nul (caractères / 3,4, `ATELIER_RELAIS_LLM_RATIO`), répond à
`count_tokens`, réécrit le 400 `ContextWindowExceededError` en « prompt is too
long: N tokens > M maximum », ne journalise que des nombres.

Réglages, toutes surfaces : `ANTHROPIC_BASE_URL` = le relais ;
`CLAUDE_CODE_MAX_CONTEXT_TOKENS` = fenêtre du modèle du tour
(`FENETRES_DES_MODELES`, 131 072) pour le harnais, la plus petite pour
VS Code/terminal ; `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8192`. Retirés :
`CLAUDE_CODE_AUTO_COMPACT_WINDOW`, `autoCompactWindow`,
`CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT`, le plafond 40 000 (un
`settings.json` existant est corrigé au démarrage de l'Atelier). Compaction de
l'Atelier (`compaction_seuil_jetons`, `contexte_plafond_jetons`) : seulement
si le relais ne répond pas ; plus aucune conversation n'est déclarée
irrécupérable. Consigne « # Compact instructions » dans le socle.

Essai réel (25/09, relais de la branche sur le port 8795 du pod, `claude`
2.1.281, qwen3-6-35b-moe, dix dossiers de ~36 000 jetons lus un par tour, même
protocole que l'essai B) :

| Essai | Réglage | Résultat |
|---|---|---|
| R (auto) | fenêtre 131 072 | auto-compaction aux tours 5 (108 257 → 16 853 jetons, 17,2 s) et 9 (110 290 → 17 537, 25,2 s) ; les dix codes restitués au tour 10 |
| X (réactive) | fenêtre 400 000 (auto neutralisée) | au tour 6 la passerelle refuse (≈129 000 estimés), le relais réécrit l'erreur, le CLI compacte (126 391 → 17 109, 25,2 s) et répond ; tours 7-9 justes |

gemma4-26b-moe retiré du créneau opus et des replis (échec au premier tour) :
opus = qwen3-6-35b-moe, repli = qwen3-8-27b (`ATELIER_MODELE_OPUS`,
`ATELIER_MODELES_DE_REPLI`).

### Lot A

| Point | État |
|---|---|
| Secrets par références partout | fait : fichier effectif, `~/.claude.json`, `claude-mcp.json`, `~/work/.claude/mcp-config.json`, `.mcp.json` n'ont que `${ATELIER_MCP_…}` ; un jeton propre au projet différent de celui du pool reste tel quel (et `atelier-verifier-coherence` le signale) ; les `args` des serveurs stdio aussi (branche `secrets-arguments`, ci-dessous) |
| Fichier d'environnement unique | fait : `~/work/.secrets/claude-env.sh` (0600, `export NOM='valeur'`), régénéré à chaque tour, à chaque changement du pool et au démarrage ; chargé par le harnais, par code-server (`claudeCode.environmentVariables` tiré du fichier), par le shell (`~/.bashrc`, ligne posée une fois par l'init), par wikichat au démarrage (init) |
| Serveur `atelier` partout | fait : fichier effectif de tout tour, portée utilisateur (seule entrée de `~/.claude.json`), tout `.mcp.json` ; une conversation ne peut plus s'en priver ; l'interface lit sa présence là où l'agent la reçoit, sans case à décocher |
| Fin de l'écrasement des réglages globaux | fait : `sync_claude_home` ne copie plus le `.claude/settings.json` d'un projet |
| Sélection des connecteurs dans `.mcp.json` | fait : avant chaque tour, à l'ouverture VS Code et au démarrage, l'Atelier écrit dans le `.mcp.json` du dossier ce que le tour reçoit et l'approuve (`enabledMcpjsonServers`) ; plus de `disabledMcpServers` figé ; un projet qui n'a pas choisi suit le pool (`.atelier/connecteurs-herites`) |
| wikichat ne crée plus de `.mcp.json` | **non fait** (dépôt wikichat, lot D) |
| Test de cohérence | fait : `tests/test_coherence_surfaces.py` ; `bin/atelier-verifier-coherence` (vrai binaire, dossier jetable) exécuté sur un poste local (2.1.86) sans écart, **pas encore sur le pod** |
| `atelier_envoyer` sans interlocuteur | fait : `mode` et `peut_attendre` ; défaut « refus d'office » pour la clé du propriétaire ; bypass seulement s'il est déjà accordé |

Écarts qui restent, connus :

- L'environnement est la **réunion** des variables de tous les projets sur
  toutes les surfaces, harnais compris (un projet voit les `.atelier/env.json`
  des autres) ; la valeur propre au projet prime dans nos tours.
- La désactivation d'un connecteur **par conversation** (`mcp_overlay`) n'existe
  que dans les tours de l'Atelier ; VS Code n'a pas d'équivalent par fil.
- L'identité wikichat diffère encore : `?agent=<nom>` résolu dans nos tours,
  `?agent=atelier` (pool) ou `${WIKICHAT_AGENT:-}` ailleurs — lot C. Réglé au
  « Déploiement du 26/09 » (pont stdio, plus de nom `atelier`).
- `claudeCode.environmentVariables` porte les valeurs en clair dans les
  réglages utilisateur de code-server (comme avant). L'extension connaît
  `claudeCode.claudeProcessWrapper` : un enveloppeur qui source
  `claude-env.sh` avant `exec claude` retirerait ces valeurs du fichier de
  code-server et relirait un jeton renouvelé à chaque lancement. Fait au
  « Déploiement du 26/09 » (`bin/atelier-claude-vscode`).

### Secrets dans les arguments (branche `secrets-arguments`)

Constaté après déploiement : le connecteur `n8n`, un pont stdio, porte son
jeton dans `args[4]` (`--header` puis `Authorization: Bearer <jeton>`) ; la
conversion ne traitait que `headers` et `env`, le jeton restait en clair dans
tous les `.mcp.json` de projets. Désormais `mcp_secrets` convertit aussi
`args`, en gardant le préfixe littéral :

| Forme dans `args` | Devient | Variable |
|---|---|---|
| `--header`/`-H` puis `Authorization: Bearer …` (ou `Authorization:Bearer …`), `--header=…` | `Authorization: Bearer ${…}` | `ATELIER_MCP_<SERVICE>_<EN-TÊTE>` (ex. `ATELIER_MCP_N8N_AUTHORIZATION`) |
| `--token=…`, `--api-key=…` (option au nom secret) | `--token=${…}` | `ATELIER_MCP_<SERVICE>_ARG_<OPTION>` |
| `--api-key` puis `…` | `${…}` | idem |
| `Bearer …` ailleurs | `Bearer ${…}` | `ATELIER_MCP_<SERVICE>_ARG_<N>` |
| valeur secrète du même serveur (en-tête, `env`) recopiée | sa référence | celle de l'en-tête ou de `env` |

Un en-tête non secret (`Accept: …`) passe tel quel. La valeur va dans
`claude-env.sh` comme les autres. Un `.mcp.json` existant est migré à la
liaison suivante si le pool fournit la même valeur (la forme écrite peut
différer) ; sinon l'argument reste et est signalé (`<service>.args[N]`), comme
un en-tête inconnu. Vérifié sur un poste (2.1.86) : `claude --mcp-config`
développe `${VAR}` dans `args` d'un serveur stdio. Après déploiement :
relancer l'Atelier (liaison de tous les projets), puis **faire tourner le jeton
n8n**, parti en clair dans les `.mcp.json`.

### Secrets pour wikichat

wikichat lance des `claude` (réveils, routines) : leur `.mcp.json` et
`~/.claude.json` n'ont que des références, les valeurs doivent être dans leur
environnement. L'init démarre wikichat avec le fichier déjà sourcé ; mais un
jeton renouvelé après ce démarrage n'y serait pas. wikichat doit donc relire
le fichier **à chaque lancement** :

```js
// avant chaque spawn de claude
const env = { ...process.env, ...lireEnvAtelier(`${WORK}/.secrets/claude-env.sh`) };
// lireEnvAtelier : chaque ligne `export NOM='valeur'`, où une apostrophe
// s'écrit '\'' — ou bien : spawn('bash', ['-c', '. "$F" && exec claude "$@"', ...])
```

Ni afficher ni journaliser ces valeurs ; ne pas les recopier dans un fichier.

### Déploiement (à faire, dans l'ordre)

1. Fusionner la branche ; attendre l'image (`image.yml`) ou mettre à jour le
   clone du pod.
2. Démarrer le relais sans toucher au reste :
   `cd ~/work/atelier-src && setsid nohup python3 -m mcp_gateway.atelier.relais_llm >> ~/work/logs/relais-llm.log 2>&1 &`,
   puis `curl -s http://127.0.0.1:8790/_relais/sante`.
3. Relancer l'Atelier (`~/work/bin/atelier-relancer`) : il réécrit
   `~/.claude/settings.json` (relais, 131 072, anciens réglages retirés,
   gemma retiré), `~/.claude.json` (portée utilisateur = `atelier`), les
   `.mcp.json` de tous les projets et `~/work/.secrets/claude-env.sh`.
4. Poser la ligne de `~/.bashrc` (ou rejouer `install/atelier-init.sh`, qui
   le fait et installe `atelier-verifier-coherence` dans `~/work/bin`).
5. Recharger la fenêtre VS Code (nouvelles variables de l'extension) ;
   redémarrer wikichat avec le fichier sourcé, et y faire relire le fichier à
   chaque lancement (ci-dessus).
6. Vérifier : `~/work/bin/atelier-verifier-coherence` (aucun écart attendu),
   `grep -c ATELIER_MCP ~/.claude.json ~/work/mcp/effective/*.json` (références
   seulement), une conversation longue qui compacte d'elle-même (événement
   `compact_boundary` dans le journal du tour).
7. Faire tourner les jetons qui ont pu être en clair dans `~/.claude.json` et
   les fichiers effectifs avant ce lot (n8n, Onyxia…).

## Navigateur stdio (branche `chrome-stdio`)

Conception et mesures : `docs/navigateur-atelier.md`.

- Le navigateur est `chrome-devtools-mcp` officiel (1.10.1, Apache-2.0) en
  **stdio**, lancé par `~/work/bin/atelier-chrome` : un processus et un Chrome
  sans écran par conversation, profil jetable, aucun port, tout s'arrête avec
  le client (mesuré : 0 processus et 0 profil restants après `claude -p`, sur
  fin normale, SIGTERM et SIGKILL).
- **Même déclaration sur toutes les surfaces** (fichier effectif, `.mcp.json`
  des projets, pool) : `{"type": "stdio", "command": ".../atelier-chrome"}`.
  Plus d'adresse, de jeton ni d'en-tête ; l'ancienne entrée HTTP du pool est
  migrée au démarrage. `ATELIER_NAVIGATEUR=0` l'éteint.
- **Passerelle** : le pool lance lui-même ce serveur stdio (`ClientStdio`),
  en portée `passerelle` (adresses privées refusées), sondé au démarrage,
  relancé au premier `gateway_call_tool`, refermé après 600 s d'inactivité.
  Ses 24 outils sont dans `gateway_find_tools`.
- **Plafond** : `ATELIER_CHROME_MAX` (6) Chrome vivants pour le compte, toutes
  surfaces confondues.
- **Web** : WebSearch refusé partout (`permissions.deny`, global et par tour) ;
  WebFetch réparé par le relais LLM (liste d'outils vide retirée) ; recherche
  par le navigateur sur DuckDuckGo HTML, consigne dans la section
  `atelier:contexte` des `CLAUDE.md`.
- **Bureau** retiré (`/chrome/view`, `/chrome/novnc`, `/chrome/vnc`, lien
  « Bureau ») ; `/chrome/health` dit l'état local ; la fiche du connecteur
  l'affiche. Point d'entrée gardé pour une vue en direct future : rattachement
  à un Chrome de l'Atelier (`ATELIER_CHROME_WS`, ou
  `/tmp/atelier-chrome-<uid>/attache/<conversation>`).

### Déploiement du navigateur (dans l'ordre)

1. Fusionner `chrome-stdio` ; attendre l'image (Chrome et chrome-devtools-mcp
   y sont) ou, sur le pod actuel, mettre à jour le clone.
2. Sur le pod actuel (Chrome déjà dans `/usr/bin/google-chrome`, posé à la
   main hors du volume : il disparaîtra au prochain redémarrage du pod s'il
   ne vient pas de l'image) : `chrome-devtools-mcp@1.10.1` est **déjà
   installé** dans `~/work/.tools/chrome-devtools-mcp` (fait le 25/09). Sinon :
   `npm install --prefix ~/work/.tools/chrome-devtools-mcp --save-exact chrome-devtools-mcp@1.10.1`.
3. Poser le lanceur : `cp ~/work/atelier-src/bin/atelier-chrome ~/work/bin/ && chmod +x ~/work/bin/atelier-chrome`
   (ou rejouer `install/atelier-init.sh`), puis
   `ATELIER_CHROME_VERIFIER=1 ~/work/bin/atelier-chrome` (node, serveur, chrome).
4. Relancer le relais LLM (pour WebFetch) : arrêter le processus
   `mcp_gateway.atelier.relais_llm` et le relancer comme au lot A — les
   conversations hors Atelier perdent le modèle pendant une seconde.
5. Relancer l'Atelier (`~/work/bin/atelier-relancer`) : migration de l'entrée
   du pool, `~/.claude/settings.json` (refus de WebSearch), `.mcp.json` de
   tous les projets, `claude-env.sh` sans le jeton du navigateur.
6. Recharger VS Code ; redémarrer wikichat (réglages globaux relus).
7. Vérifier : `curl` authentifié sur `/chrome/health` (`pret: true`) ; une
   conversation qui ouvre une page et en lit le titre ; `pgrep -fc
   chrome-devtools-mcp` revenu à 0 après sa fermeture ;
   `grep -c CHROME_DEVTOOLS_MCP_AUTHORIZATION ~/work/.secrets/claude-env.sh` à 0.
8. Nettoyage laissé à la personne : le fichier `chrome_mcp_token` du dossier
   de secrets et `ATELIER_CHROME_MCP_URL` ne servent plus ; le déploiement
   `chrome-devtools-mcp` (0 réplique) et le fork `nouveau-projet` ne sont plus
   utilisés par l'Atelier.

## Déploiement du 26/09 (branche `deploiement-26-09`)

La branche part de `main` (`2b5df53`, lot A et compaction) et réunit :
`secrets-arguments` (`557433a`), `chrome-stdio` (`3e2bb04`), puis quatre
changements propres au déploiement :

- **Enveloppeur de l'extension VS Code** : `claudeCode.claudeProcessWrapper`
  (portée machine, relevé dans le manifeste de l'extension 2.1.280 à 2.1.282)
  désigne `~/work/bin/atelier-claude-vscode`, qui source
  `~/work/.secrets/claude-env.sh` sans rien afficher puis fait `exec "$@"`.
  `claudeCode.environmentVariables` ne porte plus que `ANTHROPIC_BASE_URL` et le
  modèle. Le réglage est écrit dans les réglages utilisateur **et** machine de
  code-server, au démarrage de l'Atelier et à chaque ouverture dans VS Code ;
  une liste machine qui porterait des valeurs en est purgée.
- **wikichat, côté Atelier** (contrat `hooks-et-dialogue.md` §8 de wikichat) :
  l'entrée `wikichat` des fichiers que lit Claude Code (fichier effectif,
  `.mcp.json` des projets, `claude-mcp.json`) est le **pont stdio**
  `~/work/wikichat/src/scripts/wikichat-mcp-stdio.mjs`, lancé par
  `~/work/bin/node`. Choisi plutôt que l'en-tête `x-wikichat-claude-session`
  d'un `headersHelper` : Claude Code pose `CLAUDE_CODE_SESSION_ID` dans
  l'environnement des serveurs stdio (documenté), alors que rien ne dit qu'un
  `headersHelper` le reçoit, que le pont note que l'extension VS Code n'envoie
  pas ces en-têtes, et que le serveur a journalisé 6 970 connexions SSE sans
  une seule identité restaurée par ce chemin. Le pont transmet la conversation
  (`?claude_session=`) et, dans nos tours, `WIKICHAT_AGENT` (`?agent=<slug>-<id6>`).
  Coût : un processus node par client. La passerelle garde l'entrée SSE du
  pool, renommée au démarrage `?agent=passerelle-atelier` (wikichat tient
  `atelier` pour générique). `atelier` n'est plus écrit comme nom nulle part ;
  la formule `<slug>-<session_id[:6]>` est inchangée.
- **Un seul fichier de réglages** : `~/.claude/settings.json` est un lien vers
  `~/work/.claude/settings.json`. Trois auteurs y écrivent — l'Atelier (dont le
  refus de WebSearch), wikichat (ses hooks, à son démarrage) et Claude Code — et
  la recopie du fichier entier d'un côté à l'autre (`sync_claude_home`, le plus
  récent gagnant) effaçait les entrées de l'un d'eux : mesuré sur l'ordre réel
  du pod, les hooks posés par wikichat juste avant le démarrage de l'Atelier
  disparaissaient au premier tour. `settings.json` sort de la synchronisation ;
  `claude_home.unifier_les_reglages` pose le lien (init, démarrage, chaque
  tour). **wikichat écrit par renommage** (`overlay-installer.mjs` :
  `writeFileSync(tmp)` puis `renameSync`), ce qui remplace le lien par un
  fichier ; ce fichier, écrit à partir de ce qu'il lisait à travers le lien,
  est alors fusionné dans celui du volume sans rien perdre (clés et `env` : le
  plus récent l'emporte ; listes de `permissions` réunies ; hooks réunis,
  l'ancien `wikichat-mailbox-hook.mjs` retiré dès que `wikichat-hook.mjs` est
  là), et le lien est reposé. Claude Code n'a pas été observé sur ce point : s'il
  écrit lui aussi par renommage, la même réparation s'applique. Là où un lien
  est impossible (poste Windows sans privilège), les deux fichiers reçoivent le
  même contenu fusionné. Test : `test_contrat_wikichat.py`
  (`test_refus_websearch_hooks_wikichat_et_vscode_coexistent`).
- **Chrome durable** : l'init installe une fois `chrome-headless-shell` dans
  `~/work/.tools` (`npx @puppeteer/browsers@3.2.3`, Node de l'Atelier) et
  `atelier-chrome` le prend avant le Chrome du système
  (`docs/navigateur-atelier.md` §9 bis).

### Étapes sur le pod (dans l'ordre)

Préalable : `main` (lot A, relais LLM) est déjà en service sur le pod ; sinon,
d'abord la section « Déploiement (à faire, dans l'ordre) » ci-dessus. La
branche doit être poussée et fusionnée dans `main` (pas fait ici).

0. **Sauvegarder** (pour le retour arrière) :
   `cp -a ~/work/.claude/settings.json ~/work/.claude/settings.json.avant-26-09`,
   `cp -a ~/.claude/settings.json ~/.claude/settings.json.avant-26-09`,
   `cp -a ~/.claude.json ~/.claude.json.avant-26-09`,
   `cp -a ~/.local/share/code-server/User/settings.json{,.avant-26-09}` et de
   même pour `Machine/settings.json` s'il existe ; noter le commit du code de
   l'Atelier en service (`git -C ~/work/atelier-src log -1 --oneline`, ou celui
   du clone `~/work/repos/atelier-sspcloud`) et celui de wikichat
   (`git -C ~/work/wikichat/src log -1 --oneline`). Ces copies contiennent des
   secrets : 0600, ne pas les afficher, les supprimer une fois le déploiement
   validé.
1. **Code de l'Atelier** : mettre `~/work/atelier-src` sur la branche fusionnée
   (clone suivi, ou copie posée à la main selon le pod) ; `pip install -e`
   inutile (aucune dépendance ajoutée).
2. **`chrome-stdio`, étapes 2 à 4** de « Déploiement du navigateur » :
   `chrome-devtools-mcp@1.10.1` est déjà dans `~/work/.tools` ; poser les
   lanceurs :
   `cp ~/work/atelier-src/bin/atelier-chrome ~/work/atelier-src/bin/atelier-claude-vscode ~/work/bin/ && chmod +x ~/work/bin/atelier-chrome ~/work/bin/atelier-claude-vscode`
   (ne pas rejouer toute l'init sur le pod en marche : elle suit le dépôt par
   `git merge --ff-only` et relancerait l'installation de ce qui manque) ;
   relancer le relais LLM comme au lot A.
3. **Chrome durable** (sans attendre un redémarrage) :
   `cd ~/work/.tools && PATH="$HOME/work/bin:$PATH" npx --yes @puppeteer/browsers@3.2.3 install chrome-headless-shell@stable --path ~/work/.tools`
   — le `PATH` donne le Node 22 de l'Atelier (`@puppeteer/browsers` refuse le
   Node 18 du système). Puis `ldd ~/work/.tools/chrome-headless-shell/linux-*/chrome-headless-shell-linux64/chrome-headless-shell | grep 'not found'`
   (vide attendu tant que les bibliothèques tirées par `google-chrome` sont là)
   et `ATELIER_CHROME_VERIFIER=1 ~/work/bin/atelier-chrome` : `chrome=` doit
   désigner le binaire du volume. Relever la liste des bibliothèques dont il
   dépend (`ldd … | awk '{print $1}'`) : c'est elle qu'il faudra retrouver
   après redémarrage.
4. **wikichat, §8 bis de son `docs/atelier-coherence.md`** :
   `cd ~/work/wikichat/src && git pull --ff-only origin atelier-coherence`
   (aucune dépendance ajoutée) ; redémarrer wikichat **depuis
   `~/work/wikichat/src`**, avec `claude-env.sh` sourcé comme dans l'init. Au
   démarrage il fusionne ses hooks dans `~/.claude/settings.json`
   (`SessionStart`, `UserPromptSubmit`, `Stop` et guetteur `asyncRewake`,
   `SessionEnd`) et retire `wikichat-mailbox-hook.mjs`. Le faire **avant** de
   relancer l'Atelier : l'unification du démarrage reprend alors ces hooks
   dans le fichier du volume. Variables éventuelles du service : §8 bis.5
   (`WIKICHAT_STOP_ATELIER=jamais` pour interdire les relances dans nos tours).
5. **Relancer l'Atelier** (`~/work/bin/atelier-relancer`). Au démarrage :
   entrée wikichat du pool renommée (`passerelle-atelier`), entrée du
   navigateur migrée en stdio, `~/.claude/settings.json` fusionné puis lié au
   volume (refus de WebSearch compris), réglages utilisateur et machine de
   code-server réécrits (enveloppeur, plus de valeur), `.mcp.json` de tous les
   projets reliés (pont wikichat, navigateur stdio, secrets des `args` en
   références), `claude-env.sh` régénéré.
6. **Recharger VS Code** (« Developer: Reload Window ») : l'extension relit
   `claudeCode.claudeProcessWrapper` et lance désormais `claude` par
   l'enveloppeur. Une conversation déjà ouverte garde son processus jusqu'à sa
   reprise.
7. **Faire tourner le jeton n8n** (`secrets-arguments`) : il est parti en clair
   dans les `.mcp.json` de projets ; de même pour tout jeton vu en clair dans
   les sauvegardes de l'étape 0.

### Vérifications après redémarrage du pod

À faire après un **vrai redémarrage** du pod (c'est lui que vise le Chrome
durable), l'init personnelle rejouée. Aucune commande ci-dessous n'affiche de
valeur secrète.

1. **`materialize_mcp_config`** :
   `cd ~/work/atelier-src && python3 -c "from mcp_gateway.atelier.config import AtelierSettings as S; from mcp_gateway.atelier.mcp_sync import materialize_mcp_config as m; print(m(S()))"`,
   puis `jq -c .mcpServers.wikichat ~/work/mcp/claude-mcp.json` (le pont :
   `command` = `~/work/bin/node`, `args` = le script du pont) ;
   `grep -l 'agent=atelier' ~/work/projects/*/.mcp.json ~/work/mcp/effective/*.json ~/.claude.json`
   vide ; `~/work/bin/atelier-verifier-coherence` sans écart.
2. **Aucun secret en clair** dans `~/.claude.json` ni dans les réglages de
   code-server :
   `cd ~/work/atelier-src && python3 -c "from pathlib import Path as P; from mcp_gateway.atelier.config import AtelierSettings as S; from mcp_gateway.atelier.coherence import secrets_en_clair as s; from mcp_gateway.atelier.env_secrets import variables_secretes as v; h=P.home(); c=h/'.local/share/code-server'; print(s([h/'.claude.json', c/'User/settings.json', c/'Machine/settings.json'], v(S())) or 'aucun')"`
   (ne rend que des chemins et des noms de variables) ;
   `jq -r '."claudeCode.claudeProcessWrapper"' ~/.local/share/code-server/{User,Machine}/settings.json`
   donne `~/work/bin/atelier-claude-vscode` deux fois ;
   `jq -r '."claudeCode.environmentVariables"[].name' ~/.local/share/code-server/User/settings.json`
   ne liste que `ANTHROPIC_BASE_URL` (et `ANTHROPIC_MODEL`). Puis, une
   conversation ouverte dans VS Code :
   `for p in $(pgrep -f 'native-binary/claude'); do tr '\0' '\n' < /proc/$p/environ | cut -d= -f1 | grep -c '^ATELIER_MCP_'; done`
   — des noms comptés, jamais les valeurs ; un compte non nul prouve que
   l'enveloppeur a chargé `claude-env.sh`.
3. **`/chrome/health`** : `curl -s -H "Authorization: Bearer $(cat ~/work/.secrets/atelier_owner_key)" http://127.0.0.1:8787/chrome/health`
   (la clé n'est pas affichée) → `pret: true`, et le Chrome désigné est celui
   du volume. Si l'init a averti « bibliothèques système absentes », le
   navigateur ne démarrera pas : voir `docs/navigateur-atelier.md` §9 bis.
   Puis une conversation qui ouvre une page et en prend une capture ;
   `pgrep -fc chrome-devtools-mcp` revenu à 0 après sa fermeture.
4. **Hooks wikichat** : `ls -l ~/.claude/settings.json` (lien vers
   `~/work/.claude/settings.json`) ;
   `jq -c '.hooks | map_values([.[].hooks[].command])' ~/.claude/settings.json`
   → une entrée `wikichat-hook.mjs` par événement (et le guetteur sous `Stop`),
   `atelier-figer-le-travail.sh` sous `SessionEnd`, plus de
   `wikichat-mailbox-hook.mjs` ; `jq .permissions.deny` contient `WebSearch`.
   Après un redémarrage de wikichat, le lien est un fichier jusqu'au tour
   suivant de l'Atelier, puis de nouveau un lien, hooks intacts. Ouvrir une
   conversation dans VS Code sur un projet :
   `curl -s 127.0.0.1:3777/api/conversations/<session>` → `<slug>-<id6>`,
   `surface: vscode` ; la même dans l'Atelier → même nom ; `list_sessions` ne
   montre plus `atelier` (la passerelle y est `passerelle-atelier`). Le
   journal de wikichat montre, pour le pont, `conv:oui` ou `claude_session`.
   Restent à constater (wikichat §8 bis.4) : `systemMessage` d'une relance
   `Stop` dans un tour, réveil d'une session VS Code inactive.
5. **Compaction dans une vraie longue conversation** : mener une conversation
   de l'Atelier au-delà de la fenêtre (131 072) sans la relancer à la main ;
   elle doit compacter d'elle-même (entrée `compact_boundary` dans son
   transcrit `~/.claude/projects/<dossier>/<session>.jsonl` et dans le journal
   du tour) et **continuer à répondre** après, y compris une fois reprise dans
   VS Code.

### Retour arrière

Dans l'ordre inverse, en gardant la rotation des jetons (étape 7) :

1. **Atelier** : remettre le code noté à l'étape 0 et relancer
   (`atelier-relancer`). Avant de relancer, remettre l'adresse de l'entrée
   wikichat du pool à ce qu'elle était (écran Connecteurs, ou la retirer) :
   l'ancien code recopie l'entrée du pool dans les `.mcp.json`, et
   `passerelle-atelier` y deviendrait le nom commun de toutes les fenêtres.
   Le navigateur stdio n'est pas compris par l'ancien code : désactiver le
   connecteur `chrome-devtools-mcp` dans l'écran Connecteurs.
2. **Réglages** : l'ancien code attend deux fichiers.
   `rm ~/.claude/settings.json && cp -a ~/work/.claude/settings.json ~/.claude/settings.json`
   (le fichier du volume porte déjà les hooks et le refus de WebSearch) ; en
   cas de doute, les sauvegardes `.avant-26-09`. Retirer l'enveloppeur des
   réglages machine :
   `jq 'del(."claudeCode.claudeProcessWrapper")' ~/.local/share/code-server/Machine/settings.json > /tmp/m.json && mv /tmp/m.json ~/.local/share/code-server/Machine/settings.json`
   (les réglages utilisateur sont réécrits par l'ancien code à la prochaine
   ouverture dans VS Code, valeurs comprises) ; recharger VS Code. Laisser
   l'enveloppeur en place serait sans danger : il ne fait que sourcer le
   fichier et lancer `claude`.
3. **wikichat** : §8 bis.6 de son document (`git checkout 9138bd0`,
   redémarrer, remettre à la main l'entrée `Stop` = `wikichat-mailbox-hook.mjs`).
4. **Chrome du volume** : l'ancien code ne le connaît pas et n'y touche pas ;
   `rm -rf ~/work/.tools/chrome-headless-shell` pour libérer ~100 Mo.
5. Supprimer les sauvegardes `.avant-26-09` une fois l'état stable.

### Reste, hors de ce déploiement

- **Interface** : afficher les `systemMessage` du flux stream-json (relance
  `Stop` par wikichat) et les fils d'une conversation
  (`GET /api/fils?session=…`) — contrat wikichat §8 point 4.
- **wikichat** : écrire `~/.claude/settings.json` à travers le lien
  (`fs.realpathSync` avant le renommage) éviterait la réparation ; à proposer
  sur sa branche. Vérifier aussi que Claude Code n'écrit pas par renommage.
- **Pont stdio sur le pod** : réception de `CLAUDE_CODE_SESSION_ID` par un
  serveur stdio lancé par l'extension, à constater (wikichat §10).
- **Bibliothèques de Chrome** : si l'image Jupyter ne les a pas, les faire
  porter par l'image du service ou passer au chart de l'Atelier.
- **Enveloppeur** : lu par l'extension en portée machine ; qu'il soit pris
  depuis les réglages utilisateur de code-server n'est pas mesuré (il est
  écrit dans les deux).

## Profils et surfaces (lot « profils », équipe S, branche `lot-surfaces`)

Contrat : `docs/vision/profils-acces.md`. Écarts traités : `docs/coherence-outils-audit.md`
G1, G2, G3 (côté Atelier), M1, M2, M3, M4, M5.

### Ce qui existe

**Une configuration par profil, générée par une seule fonction.**
`mcp_sync.configuration_du_profil(settings, profil=…, cwd=…)` calcule ce que reçoit
un dossier. Trois fichiers en sortent, et rien d'autre :

| Surface | Ce qu'elle lit | Écrit par |
|---|---|---|
| App (tour de l'Atelier) | `effective/<conversation>.json` (`--mcp-config --strict-mcp-config`) | `materialize_session_mcp` : la configuration du profil, plus les désactivations de la conversation et `${ATELIER_SESSION}` résolu |
| VS Code, terminal | `<dossier>/.mcp.json`, approuvé dans `~/.claude.json` (`enabledMcpjsonServers`) | `lier_le_projet` |
| Tout dossier (portée utilisateur), `claude-mcp.json` | l'entrée `atelier` seule (profil `code`) | `materialize_mcp_config` |

- Profil `code` (un projet) : les connecteurs choisis pour le projet (ou le pool, s'il
  n'a pas choisi) ; `atelier` ; le pont wikichat ; le navigateur s'il est choisi.
- Profil `assistant` (`assistant_root` et ses conversations) : `atelier`, wikichat,
  Onyxia, et les seuls connecteurs choisis pour l'Assistant. Le reste passe par
  les méta-outils de la passerelle. Son `.mcp.json`, jusqu'ici au format interne
  (`{"filesystem": {"enabled": false}}`), est converti au format Claude Code. Il
  est relié au démarrage avec les projets (M3).
- Le choix des connecteurs vit dans `.atelier/connecteurs-choisis.json`, hors du
  `.mcp.json` qui est désormais une sortie. Un connecteur retiré de la sortie
  (échec d'authentification, Onyxia) reste dans le choix.

**Contrats avec les autres équipes.**

- (a) L'entrée `atelier` porte `X-Atelier-Profil: code|assistant`. Elle porte aussi
  `X-Atelier-Conversation` (`${ATELIER_SESSION:-poste}`, résolu dans l'app) et, pour
  un projet, `X-Atelier-Projet: <slug>`. Elle a en plus un `headersHelper`,
  `~/work/bin/atelier-entetes-mcp`, qui donne hors de l'Atelier l'identifiant de la
  conversation du `claude` parent, lu dans `<config>/sessions/<pid>.json`.
  La forme `${ATELIER_SESSION:-${CLAUDE_CODE_SESSION_ID}}` ne marche pas. Relevé
  dans le binaire 2.1.282 : l'expression
  `/\$\{([A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?)\}/g` développe en un seul passage, et
  son repli ne peut pas contenir `}`. De plus, `CLAUDE_CODE_SESSION_ID` n'est pas
  dans l'environnement du CLI : seuls les serveurs stdio et les hooks le reçoivent.
- (b) Le pont wikichat reçoit `WIKICHAT_PROFIL=code|assistant` et
  `WIKICHAT_PROJET=<slug>` (`assistant` pour l'Assistant) dans son `env`.
- (c) L'entrée `Onyxia` vient de
  `onyxia_pour_projet(settings, slug, profil, *, pool=None)` (équipe O,
  `onyxia_projet.py`). Tant que ce module manque, un bouchon de même signature
  répond `None` pour `code` et le mandataire `/mcp/onyxia` pour `assistant`.
  `assurer_onyxia_natif` est retiré (G3). Plus aucune surface ne joint Onyxia en
  direct : ni les `.mcp.json`, ni le fichier effectif, ni `claude-mcp.json`, ni
  `~/.claude.json` (racine et portées de projet).

**Filtrage à la source, côté configuration.** Une entrée autre que `atelier` qui
vise la porte `/mcp` de l'Atelier est une porte déguisée : elle donnerait les
méta-outils sans en-tête de profil. Elle est retirée, comme l'alias
`Onyxia_nic01asfr`.

**Connecteurs refusés en authentification (M5).** `noter_les_sondes` est appelé
après chaque sonde du pool (démarrage, `/mcp/reprobe`). Il retient, dans
`mcp/sondes-authentification.json`, les connecteurs en 401 ou 403 (le code
seulement, pas le message). Ces connecteurs ne sont plus distribués et ils sont
signalés (`echec_authentification` dans l'état des connecteurs d'un projet). Une
sonde réussie les rend.

**Serveurs obsolètes (M4).** `chrome-devtools` est retiré des portées de projet de
`~/.claude.json` à chaque matérialisation et à chaque liaison.

**Mode de permission (M1).** Module `modes_permission`.

- Quatre modes : `default`, `acceptEdits`, `plan`, `bypassPermissions`. `manual`
  est lu comme `default`. `auto` aussi : il demandait avant d'écrire, là où
  `acceptEdits` écrit.
- Défaut du projet : `permissions.defaultMode` de `.claude/settings.local.json`,
  que le CLI résout de lui-même. Le défaut du service (`acceptEdits`, jamais
  `bypassPermissions`) y est posé à la liaison d'un projet qui n'en a pas. Sans
  cela, VS Code et le terminal partaient en `default` quand l'app partait en
  `acceptEdits`.
- Choix d'une conversation : le magasin où l'extension VS Code tient déjà le mode
  de chaque conversation,
  `<code-server>/User/globalStorage/anthropic.claude-code/session-permission-modes/<id-cli>.json`
  (`{"mode", "updatedAt"}`, ignoré après 30 jours). Relevé dans `extension.js`
  2.1.282. Ce choix d'emplacement se justifie ainsi :
  - c'est l'endroit que l'extension écrit quand on change de mode dans une
    conversation, et qu'elle relit pour la rouvrir ;
  - l'app y écrit (`PATCH /v1/sessions/{id}`) et y lit à chaque tour, sous
    l'identifiant du CLI. Un choix fait d'un côté vaut donc de l'autre ;
  - la fiche de la conversation n'en garde qu'une copie de lecture ;
  - au terminal, `claude` (le script `~/work/bin/surfaces/claude`, en tête du
    PATH par `atelier-bashrc`) passe par `atelier-claude-vscode`, qui applique
    ce choix à `claude --resume <id>`.
- Résolution, la même partout (`mode_resolu`) : la conversation, puis le projet,
  puis le service. Un tour sans interlocuteur ne reçoit plus `bypassPermissions`
  par défaut.
- Enveloppeur `atelier-claude-vscode`. Avec un enveloppeur, l'extension passe
  `--permission-mode default` d'office (`resolvePermissionModeInCli` faux).
  - Sans choix pour la conversation, l'enveloppeur retire ce drapeau d'un lancement
    de l'extension (`CLAUDE_CODE_ENTRYPOINT=claude-vscode`). Le CLI résout alors le
    défaut du projet.
  - Avec un choix, l'enveloppeur impose ce choix.
- Résidus retirés :
  - `claudeCode.initialPermissionMode` (réglage machine) ;
  - `claudeCode.allowDangerouslySkipPermissions`, posé seulement tant qu'un projet
    ou une conversation a choisi `bypassPermissions`. Sinon l'extension rabat ce
    mode sur `default`. Le drapeau *permet* le mode sans l'imposer ;
  - l'ancien `ecrire_mode_du_dossier`, qui recopiait le mode de la conversation
    ouverte dans VS Code en défaut du projet (d'où les `bypassPermissions` de
    `projet-sans-nom` et `…webtools-ce`).

  Un rangement unique au démarrage (`nettoyer_les_residus`, marque
  `mcp/.modes-permission-v1`) fait deux choses. Il réécrit les défauts de projet
  dans la liste et y remplace `bypassPermissions` par le défaut du service. Il
  passe dans le magasin les modes des fiches.
- Interface : le sélecteur propose le défaut du projet et les quatre modes. Le
  mode sans garde-fou demande une confirmation et se signale. Le bouton « Défaut
  du projet » écrit le mode affiché (`PUT /v1/projets/{slug}/mode`).

**Version (M2).** Le lien `~/work/bin/claude` est réaligné sur le binaire de
l'extension la plus récente à chaque tour (`_resolve_claude_bin`), plus seulement au
démarrage. Le terminal, wikichat et l'Atelier lancent donc la même version, au
plus tard depuis le dernier tour.

**G1.** `bin/atelier-bashrc` pose le chargement de `claude-env.sh` en tête de
`~/.bashrc`, avant la garde non interactive. Il déplace une ligne déjà mal placée
et pose l'alias `claude`. Il est idempotent. `install/atelier-init.sh` passe par lui.

**G2.** La commande du hook `garde_bash` porte
`PYTHONPATH=<atelier-src> python -m mcp_gateway.gardiens.garde_bash`. Un test la
lance depuis un dossier quelconque, sans paquet installé, et obtient le code 2.

**Vérificateur (`bin/atelier-verifier-coherence`, `coherence.verifier_reel`).**
- Pour chaque vrai projet et le dossier de l'Assistant, et pour chaque surface
  (app, VS Code par l'enveloppeur, `bash -ic`, `bash -lc`), il lance
  `claude -p --output-format stream-json --verbose` dans ces conditions :
  - hooks désactivés ;
  - `--no-session-persistence` ;
  - copie du dossier de configuration ;
  - adresse de modèle morte ;
  - pont wikichat neutralisé, sauf `--avec-wikichat`.
- Il lit `system/init` et tue ce processus et ses descendants, par PID.
- Il compare les surfaces entre elles : serveurs, outils, version, mode, modèle,
  effort.
- Il les compare au profil :
  - serveurs de `configuration_du_profil` ;
  - version de l'extension ;
  - mode résolu ;
  - outils interdits au profil `code` (`gateway_*`, `composition_*`, outils
    globaux de wikichat) ;
  - méta-outils de l'Assistant ;
  - WebSearch.
- Il lance le hook de garde à blanc depuis le projet (code 2 attendu) et vérifie
  que chaque programme de hook existe.
- Options : `--rapide` (un projet par profil, pour les gardiens), `--projets a,b`,
  `--surfaces`, `--json`. L'ancien essai reste en `--auto-test`.
- Code de retour 1 en cas d'écart. Aucune valeur secrète n'est affichée.
- L'effort n'est pas annoncé par `system/init` : il est déduit des réglages.

### Ce qui reste

- **Vérifié en tests seulement** (Windows, suite complète). Rien n'a été lancé
  sur le pod : ni le vérificateur réel, ni l'enveloppeur, ni l'aide aux
  en-têtes. Les tests POSIX (enveloppeur, shells, `/proc`) sont sautés sous
  Windows et tourneront en CI Linux.
- `atelier-entetes-mcp` n'est pas éprouvé sur le pod. Deux points sont à
  constater :
  - le fichier `sessions/<pid>.json` existe-t-il au moment où le CLI connecte ses
    serveurs ?
  - le `headersHelper` d'un `.mcp.json` de projet ne tourne qu'avec la confiance
    du dossier (`hasTrustDialogAccepted`) ; sans elle, l'en-tête reste « poste ».
- Écarts attendus du vérificateur tant que les autres équipes ne sont pas
  déployées :
  - outils `gateway_*` pour le profil `code` (équipe A) ;
  - outils globaux de wikichat (équipe W) ;
  - Onyxia de l'Assistant par `/mcp/onyxia` (équipe O).
- Le lien `~/work/bin/claude` n'est réaligné qu'au tour suivant une mise à jour de
  l'extension. Les gardiens pourraient le réaligner aussi ; le vérificateur le
  signale en attendant.
- Un choix de mode fait dans VS Code *avant* le premier message d'une conversation
  neuve est remplacé par le défaut du projet (l'enveloppeur ne distingue pas ce
  choix de l'état global de l'extension) ; il vaut dès qu'il est fait en cours de
  conversation.

### Déploiement sur le pod (dans l'ordre, avec le go de Nicolas pour le redémarrage)

1. Mettre à jour le code : `git -C ~/work/repos/atelier-sspcloud pull --ff-only`
   (ou la procédure habituelle vers `~/work/atelier-src`).
2. Poser les scripts dans `~/work/bin` :
   `for s in atelier-bashrc atelier-entetes-mcp atelier-claude-vscode atelier-verifier-coherence atelier-chrome-onglets.mjs; do [ -f ~/work/atelier-src/bin/$s ] && cp -f ~/work/atelier-src/bin/$s ~/work/bin/$s && chmod +x ~/work/bin/$s; done`.
   L'Atelier repose aussi l'enveloppeur et l'aide aux en-têtes à son démarrage.
3. Corriger `~/.bashrc` (G1) :
   `sh ~/work/bin/atelier-bashrc ~/.bashrc ~/work/.secrets/claude-env.sh ~/work/bin/atelier-claude-vscode ~/work/bin/claude`,
   puis `bash -lc 'env | grep -c ^ATELIER_MCP_'`. Le nombre de variables doit
   être supérieur à 0 ; seuls les noms sont comptés, aucune valeur n'est affichée.
4. Reposer le hook (G2) :
   `cd ~/work/atelier-src && /opt/python/bin/python3.13 -m mcp_gateway.gardiens.garde_bash --poser`
   (les gardiens le font aussi à leur démarrage). Puis, depuis un projet,
   `echo '{"tool_name":"Bash","tool_input":{"command":"killall node"}}' | sh -c "$(jq -r '.hooks.PreToolUse[]|.hooks[]|select(.command|contains("garde_bash")).command' ~/.claude/settings.json)"; echo $?`
   doit afficher `2`.
5. Redémarrer l'Atelier (`~/work/bin/atelier-relancer`). Au démarrage, il fait
   dans l'ordre :
   - relier tous les projets et l'Assistant : profils, conversion du `.mcp.json`
     de l'Assistant, défaut de mode, purge de `chrome-devtools` et d'Onyxia
     direct ;
   - ranger les modes une fois ;
   - noter les sondes : n8n en 401 cesse d'être distribué.
6. Recharger la fenêtre VS Code : l'extension relit les réglages machine.
7. Vérifier : `~/work/bin/atelier-verifier-coherence --rapide`, puis sans option.
   Relever les écarts qui restent et les rapprocher des lots A, W et O.
8. Retour arrière :
   - revenir au commit précédent et redémarrer ;
   - `~/.bashrc` garde une ligne en tête, sans effet sur l'ancien code ;
   - les fichiers `.atelier/connecteurs-choisis.json` et
     `mcp/sondes-authentification.json` sont ignorés par l'ancien code ;
   - les défauts de mode réécrits restent valides pour le CLI.

### Correctif du 26/09 (branche `correctif-surfaces`), après le premier passage du vérificateur

Le vérificateur réel a relevé 15 écarts (`--rapide`) puis 136 (tous les projets). Leurs causes ont été établies sur le pod :

| Écart | Cause mesurée | Correction |
|---|---|---|
| wikichat `failed` partout | le vérificateur coupait le pont (`WIKICHAT_PORT=1`) | le pont se connecte désormais par défaut, sous un seul nom fixe, `verificateur-coherence`. Ainsi, pas une identité par lancement. `--sans-wikichat` coupe le pont, et wikichat est alors rapporté « non mesuré » |
| mode `default` dans VS Code | avec `CLAUDE_CODE_ENTRYPOINT=claude-vscode`, le CLI ignore `defaultMode`. L'essai a été fait sur le pod : `acceptEdits` au terminal, `default` avec ce point d'entrée | sans choix pour la conversation, l'enveloppeur passe lui-même le défaut du projet (`settings.local.json`, puis `settings.json`) |
| gitlab `failed` hors de l'app | `Executable not found in $PATH: "npx"` (journal MCP du CLI). Le harnais met `~/work/bin` dans le PATH ; ni code-server, ni le terminal ne le faisaient | l'enveloppeur met `~/work/bin` en tête du PATH ; `atelier-bashrc` aussi |
| `bash -lc` sans `system/init` | `claude` introuvable : l'alias n'existe qu'en interactif, et `~/work/bin` n'est pas dans le PATH | `atelier-bashrc` pose, avant la garde, `~/work/bin/surfaces` puis `~/work/bin` dans le PATH. Il pose aussi le script `surfaces/claude`, qui passe par l'enveloppeur, et l'alias disparaît |
| n8n distribué en 401 | pont stdio `mcp-remote`, marqué `stdio-local` et jamais sondé par le pool | `noter_les_sondes` (appelé à la sonde du démarrage) sonde ces ponts en HTTP (`initialize`) ; un 401 ou un 403 les retire. `stdio-local` n'efface plus un échec |
| sélection différente app / VS Code | le « + » du fil désactivait des connecteurs pour la seule conversation, ce que VS Code, qui lit un `.mcp.json` par dossier, ne peut pas suivre. `settings.local.json` gardait en outre une ancienne `enabledMcpjsonServers` (`Onyxia`, `n8n`) | le « + » règle le choix du dossier : le projet, ou le dossier de la conversation de l'Assistant. C'est la seule façon de garantir l'égalité. `mcp_overlay` est ignoré. L'approbation de `settings.local.json` est réécrite à l'identique du `.mcp.json` |
| méta-outils absents pour l'Assistant | règle de profil du serveur `atelier` | `X-Atelier-Dossier: <dossier de l'Assistant>` dans l'entrée `atelier` de l'Assistant. Le reste revient à l'équipe A |

Le vérificateur rapporte en notes ce qu'il ne mesure pas : wikichat coupé, et les serveurs encore `pending` à l'init, dont les outils ne sont pas comparés. Il marque « (équipe A) » les écarts qui attendent le filtrage du serveur `atelier`.

Étapes de déploiement en plus de celles ci-dessus :
- copier `bin/atelier-bashrc` et `bin/atelier-claude-vscode` dans `~/work/bin`
  (l'Atelier repose l'enveloppeur à son démarrage) ;
- relancer
  `sh ~/work/bin/atelier-bashrc ~/.bashrc ~/work/.secrets/claude-env.sh ~/work/bin/atelier-claude-vscode ~/work/bin/claude`.
  Cette commande crée `~/work/bin/surfaces/claude` et remplace l'alias par le PATH ;
- redémarrer l'Atelier : la sonde du démarrage retire n8n, et la liaison réécrit les approbations.
