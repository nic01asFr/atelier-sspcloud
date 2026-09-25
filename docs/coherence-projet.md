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
- Chrome et `X-Atelier-Conversation` utilisent la même clé.

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
- Mode par défaut du projet dans le même fichier ; le réglage machine de
  VS Code en est dérivé à l'ouverture ; `allowDangerouslySkipPermissions`
  retiré.
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
| Secrets par références partout | fait : fichier effectif, `~/.claude.json`, `claude-mcp.json`, `~/work/.claude/mcp-config.json`, `.mcp.json` n'ont que `${ATELIER_MCP_…}` ; un jeton propre au projet différent de celui du pool reste tel quel (et `atelier-verifier-coherence` le signale) |
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
  `?agent=atelier` (pool) ou `${WIKICHAT_AGENT:-}` ailleurs — lot C.
- `claudeCode.environmentVariables` porte les valeurs en clair dans les
  réglages utilisateur de code-server (comme avant). L'extension connaît
  `claudeCode.claudeProcessWrapper` : un enveloppeur qui source
  `claude-env.sh` avant `exec claude` retirerait ces valeurs du fichier de
  code-server et relirait un jeton renouvelé à chaque lancement — à décider.

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
