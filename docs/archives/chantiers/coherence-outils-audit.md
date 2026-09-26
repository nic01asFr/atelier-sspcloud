# Audit : les outils que reçoit l'agent, surface par surface

Mesuré le 25/09/2026 entre 21:55 et 22:20 UTC sur le pod `proj-claude-code-jupyter-python-0`.
Code en service : `~/work/atelier-src` au commit `776fb73`, Atelier démarré à 21:32:46.
Référence : `docs/coherence-projet.md` (« même chose partout »), `docs/vision/architecture-transverse.md`
§1.5 et §1.8, `docs/vision/decisions.md`.

## 1. Méthode

Chaque mesure lance le vrai `claude` en `-p --output-format stream-json --verbose` avec le
message « ok ». Le script ne lit que l'événement `system/init`, puis tue le PID. Au total,
31 lancements : 24 pour la matrice, 1 d'essai, et les 6 de `atelier-verifier-coherence`.

| Surface | Reconstitution |
|---|---|
| Atelier | Fonctions de l'Atelier appelées en Python 3.13 : `mcp_sync.materialize_session_mcp`, `ClaudeHarness._resolve_claude_bin`, `_arguments_de_reglages` et `_env`. Environnement de base : celui du processus `mcp_gateway.atelier.app` en marche (`/proc/<pid>/environ`). Mode : `settings.permission_mode`, comme pour un tour lancé depuis l'interface. Fausse conversation `a0d17…`, nom wikichat `<slug>-a0d17x`. Pour rester en lecture seule, trois fonctions ont été remplacées : `ecrire_le_fichier` ne fait que lire, `sync_claude_home` ne fait rien, et le fichier effectif est écrit dans `/tmp`. `ecrire_contexte` et `lier_le_projet` n'ont pas été appelées : les `.mcp.json` des projets sont ceux que l'Atelier a écrits à son démarrage. |
| VS Code | Même ligne de commande que l'extension 2.1.282 (`spawnClaude` dans `extension.js`) : l'enveloppeur `~/work/bin/atelier-claude-vscode`, puis le binaire de l'extension avec `--permission-prompt-tool stdio --setting-sources=user,project,local --permission-mode acceptEdits --allow-dangerously-skip-permissions --no-chrome`. Environnement : celui de code-server, plus `claudeCode.environmentVariables`, plus `CLAUDE_CODE_ENTRYPOINT=claude-vscode`. Le serveur MCP interne de l'IDE (type SDK) n'est pas reproduit. |
| Terminal | Deux variantes, `bash -ic` (terminal interactif) et `bash -lc` (demandé), avec pour base l'environnement d'un terminal code-server. On lance `exec claude -p …` dans le dossier du projet. |

Mesures prises pour éviter les effets de bord :

- `--settings '{"disableAllHooks": true}'`. La clé existe dans le binaire 2.1.281/282. Pour le tour de l'Atelier, elle est fusionnée dans son propre `--settings`.
- `--no-session-persistence` : aucun transcrit n'est écrit.
- `CLAUDE_CONFIG_DIR` pointe vers une copie, dans `/tmp`, de `~/.claude.json`, `settings.json`, `CLAUDE.md`, `commands`, `skills` et `plugins`. Le contenu est le même que la vraie configuration ; seul l'emplacement change.
- Dans les tours de l'Atelier, à partir de la 2ᵉ mesure, le pont wikichat reçoit `WIKICHAT_PORT=1`, ce qui l'empêche de se connecter. Sinon, chaque lancement fixait une identité dans wikichat. L'identité transmise est donc relevée dans l'environnement du processus du pont.
- `/tmp/audit-outils` a été supprimé à la fin, et il ne reste aucun processus.

Effets de bord qui restent :

- La première mesure (Atelier, `projet-sans-nom-5`) s'est connectée à wikichat sous le nom `projet-sans-nom-5-a0d17f` : une liaison d'identité et des messages « connecté/déconnecté ».
- 133 journaux MCP dans `~/.cache/claude-cli-nodejs/`. Ils n'ont pas été supprimés, car on ne peut pas les distinguer à coup sûr des journaux d'un tour réel lancé au même moment.
- Deux aperçus `atelier_decider` sur une demande inexistante. Rien n'est exécuté et les jetons expirent après 10 minutes.

## 2. Projets couverts

| Projet | Pourquoi | `.mcp.json` du projet |
|---|---|---|
| `projet-sans-nom-5` | Lecteur Grist, créé le 21/09 : le plus récent | hérite du pool : Onyxia, atelier, chrome-devtools-mcp, datagouv, filesystem, github, gitlab, llm, n8n, qgis, wikichat |
| `nouveau-projet-4` | agents de recherche (12 agents de projet) | restreint : Onyxia, atelier, wikichat |
| `nouveau-projet-2` | voix | restreint : Onyxia, atelier, voice, wikichat |
| `nouveau-projet` | sélection restreinte avec navigateur | Onyxia, atelier, chrome-devtools-mcp, filesystem, wikichat |
| `projet-sans-nom-4` | créé le 20/09 (le plus récent après le Lecteur Grist) | hérite du pool |
| Assistant | `~/work/wikichat-memory` (`assistant_root`), session `f5fca865…`, `kind = assistant` | pas de `.mcp.json` Claude Code : le dossier contient un « binding » `{"filesystem": {"enabled": false}}` |

## 3. Matrice projet × surface

Notation : `nom:N` = connecté, N outils ; `pend` = encore en attente au moment de l'init ; `FAIL` = échec.
« Neutralisé » = wikichat coupé volontairement par la méthode (voir §1).

| Projet | Tour de l'Atelier | VS Code | Terminal interactif (`bash -ic`) | Terminal `bash -lc` |
|---|---|---|---|---|
| projet-sans-nom-5 | atelier:36, chrome-devtools-mcp:24, datagouv:10, filesystem:14, github:46, llm:12, qgis:54, wikichat:53 (mesure non neutralisée), gitlab:0 (connecté, aucun outil), n8n FAIL, Onyxia pend — **init 30,3 s** | atelier:36, chrome:24, datagouv:10, filesystem:14, github:46, llm:12, wikichat:53 ; gitlab pend, qgis pend, Onyxia pend, n8n FAIL — 2,3 s | comme VS Code | chrome:24, datagouv:10, filesystem:14, wikichat:53 ; **atelier, github, llm, qgis, Onyxia FAIL**, n8n FAIL, gitlab pend |
| nouveau-projet-4 | atelier:36, wikichat neutralisé, Onyxia pend — 30,3 s ; 12 agents | atelier:36, wikichat:53, Onyxia pend ; 13 agents (+`claude-code-guide`) | atelier:36, wikichat:53, Onyxia pend ; 12 agents | wikichat:53 ; **atelier, Onyxia FAIL** |
| nouveau-projet-2 | atelier:36, voice:2, wikichat neutralisé, Onyxia pend — 30,3 s | atelier:36, voice:2, wikichat:53, Onyxia pend | comme VS Code | wikichat:53 ; **atelier, voice, Onyxia FAIL** |
| nouveau-projet | atelier:36, chrome:24, filesystem:14, wikichat neutralisé, Onyxia pend — 30,3 s | atelier:36, chrome:24, filesystem:14, wikichat:53, Onyxia pend, **`chrome-devtools` FAIL** | comme VS Code | chrome:24, filesystem:14, wikichat:53 ; **atelier, Onyxia, chrome-devtools FAIL** |
| projet-sans-nom-4 | comme projet-sans-nom-5 (gitlab connecté à 0 outil, qgis:54) | comme projet-sans-nom-5 | comme projet-sans-nom-5 | comme projet-sans-nom-5 |
| Assistant | atelier:36, wikichat neutralisé — 0,7 s | **atelier:36 seul** | **atelier:36 seul**, mode `default` | **atelier FAIL, aucun outil MCP**, mode `default` |

Propriétés communes aux six projets :

| | Atelier | VS Code | Terminal interactif | Terminal `bash -lc` |
|---|---|---|---|---|
| Binaire | 2.1.282 (`binaire_claude_le_plus_recent`) | 2.1.282 (extension active) | **2.1.281** (lien `~/work/bin/claude`) | **2.1.281** |
| Modèle (`init.model`) | qwen3-6-35b-moe | idem | idem | idem |
| Effort | `CLAUDE_CODE_EFFORT_LEVEL=medium` dans l'environnement, sans `--effort` (`settings.effort` vide) | medium par `~/.claude/settings.json` (`env` + `effortLevel`) | idem | idem |
| Mode de permission | `acceptEdits` (`settings.permission_mode`) ; valeur de la fiche si elle en a une ; `bypassPermissions` pour un tour sans interlocuteur | `acceptEdits` (réglage machine) **+ `--allow-dangerously-skip-permissions`** | `defaultMode` de `.claude/settings.local.json` (`acceptEdits` ici, `default` pour l'Assistant, `bypassPermissions` pour `projet-sans-nom` et `…webtools-ce`) | idem |
| Refus / autorisations | `--settings` : `deny: [WebSearch]` + règles accordées dans le fil ; plus user, project, local | user, project, local | idem | idem |
| WebSearch / WebFetch | absent / présent | absent / présent | absent / présent | absent / présent |
| Hooks chargés | ceux de `~/.claude/settings.json` (lien vers `~/work/.claude/settings.json`) : `SessionStart`, `UserPromptSubmit`, `Stop` (×2 : stop, guetter), `SessionEnd` (wikichat + `atelier-figer-le-travail.sh`), `PreToolUse:Bash` (`garde_bash`) ; aucun hook de projet ni dans `--settings` | les mêmes, plus les hooks internes de l'extension (instantané avant édition, sauvegarde, diagnostics) : propres à la surface | les mêmes | les mêmes |
| `ATELIER_MCP_*` (nombre de noms) | 7 | 7 (l'enveloppeur a bien chargé le fichier, vu dans `/proc`) | 7 | **0** |
| `X-Atelier-Conversation` vers `atelier` | identifiant de session (résolu dans le fichier effectif) | `poste` (repli de `${ATELIER_SESSION:-poste}`) | `poste` | `poste` (le serveur est de toute façon en échec) |
| Identité vers wikichat (environnement du pont) | `WIKICHAT_AGENT=<slug>-<id6>` + `CLAUDE_CODE_SESSION_ID` | `CLAUDE_CODE_SESSION_ID` seul : le nom dépend du hook `SessionStart` | idem | idem |
| Commandes « / » | 49 à 57 : les prompts MCP de qgis n'apparaissent que si qgis est connecté à l'init (l'Atelier l'attend) | 49 à 54 | 49 à 54 | 48 |

Les outils natifs (25 ou 26) sont identiques. Deux exceptions viennent de la méthode et ne sont
pas des écarts :

- `WaitForMcpServers` n'existe que si un serveur est encore en attente ;
- `AskUserQuestion`, `EnterPlanMode` et `ExitPlanMode` manquent au terminal parce que la mesure lance
  `-p` sans `--permission-prompt-tool`. Un terminal interactif les a.

## 4. Porte `/mcp`, catalogue et passerelle

- **`GET /v1/commandes`** : 29 commandes. `atelier_projet_publier` et `atelier_a_valider_accepter` sont `reservee`, non exposées.
- **`tools/list` de `/mcp`** : 36 outils, dont les **27 `atelier_*` exposés** (le compte est exact, `atelier_montrer` et `atelier_navigateur_ouvrir` compris), 7 `gateway_*` et 2 `composition_*`. Les classes `_meta["atelier/commande"].classe` sont identiques à `/v1/commandes`. Aucune commande réservée n'apparaît en MCP. Les agents reçoivent les mêmes 36 outils sur toutes les surfaces où `atelier` se connecte.
- **`gateway_find_tools` / `gateway_call_tool`** sont présents. L'inventaire complet contient 231 outils : chrome-devtools-mcp 24, datagouv 10, github 45, llm 12, **onyxia 24**, qgis 54, wikichat 53, et 9 méta-outils. Il ne contient **aucun `atelier_*`**, ni gitlab, n8n ou filesystem.
- **Un outil engageant appelé par la passerelle** (`gateway_call_tool` → `atelier_decider`, `allow`) rend bien `confirmation_requise: true`, `classe: engageante`, l'aperçu, un jeton valable 600 s et « Rien n'est fait ». L'appel direct rend la même chose.

## 5. Écarts, par gravité

### Graves

**G1. Le terminal non interactif ne reçoit aucun secret.**

- **Mesure :** avec `bash -lc`, `atelier`, github, llm, qgis, Onyxia et voice sont en échec, et l'environnement compte 0 `ATELIER_MCP_*`. Le terminal interactif, lui, est correct.
- **Qui est touché :** tout ce qui lance `claude` sans shell interactif : scripts, `ssh host cmd`, un agent qui relance `claude` par Bash, les réveils wikichat s'ils ne sourcent pas eux-mêmes le fichier.
- **Cause :** `install/atelier-init.sh` (l. 286-290) ajoute `. ~/work/.secrets/claude-env.sh` **à la fin** de `~/.bashrc`, après la garde `case $- in *i*) ;; *) return;; esac`. Un shell non interactif sort avant d'atteindre la ligne.
- **Correction :**
  - faire de `~/work/bin/claude` un enveloppeur, sur le modèle de `atelier-claude-vscode`, qui source le fichier puis fait `exec` du binaire le plus récent. Cela règle aussi G5 et wikichat ;
  - à défaut, poser la ligne avant la garde, ou dans `~/.profile`.

**G2. La garde `garde_bash` ne fait rien, sur aucune surface.**

- **Mesure :** le hook `PreToolUse:Bash` s'exécute sous la forme `/opt/python/bin/python3.13 -m mcp_gateway.gardiens.garde_bash`. Lancé depuis un dossier de projet sur `killall node`, il rend `ModuleNotFoundError: No module named 'mcp_gateway'` et le code 1, une erreur non bloquante : la commande passe. Lancé depuis `~/work/atelier-src`, il rend le code 2 et refuse, comme prévu.
- **Cause :** `garde_bash.commande_du_hook` écrit `python -m <module>` sans `PYTHONPATH`. Le paquet n'est pas installé dans `/opt/python` (`pip show` vide), et ni l'Atelier, ni code-server, ni le terminal n'ont de `PYTHONPATH`.
- **Correction :**
  - écrire la commande avec le chemin du script (`python3.13 ~/work/atelier-src/mcp_gateway/gardiens/garde_bash.py`), ou préfixer `PYTHONPATH=~/work/atelier-src` ;
  - ajouter un test qui exécute la commande posée depuis un dossier quelconque et attend le code 2 sur `killall x`.

**G3. Onyxia n'arrive jamais à l'agent et coûte 30 s à chaque nouveau tour de l'Atelier.**

- **Mesure :**
  - `Onyxia` est `pending` sur toutes les surfaces, dans les six projets ;
  - l'init d'un tour de l'Atelier prend 30,3 s dans les cinq projets qui ont Onyxia, contre 0,7 s pour l'Assistant, qui ne l'a pas. VS Code et le terminal émettent l'init en 2,3 s sans l'attendre, mais sans ses outils non plus ;
  - la passerelle Onyxia (`sspcloud-mcp` 0.2.0) répond à `initialize` et `tools/list` en moins de 0,1 s, mais **ne répond pas au POST `notifications/initialized`** (plus de 50 s). Le client de Claude Code attend cette réponse.
- **Côté Atelier :** `mcp_sync.assurer_onyxia_natif` impose Onyxia à tout projet de code dès que le pool l'a, même si le projet ne l'a pas choisi.
- **Correction :**
  - corriger le serveur, qui doit rendre 202 immédiatement pour une notification ;
  - en attendant, ne plus l'imposer en natif : il fonctionne par la passerelle, qui expose 24 outils `onyxia__*` ;
  - ajouter une sonde de poignée de main complète (initialize, puis notification, puis `tools/list`) avant d'écrire un serveur dans un `.mcp.json`.

### Moyens

**M1. Le mode de permission n'est pas le même selon la surface.**

- **Mesure :**
  - Atelier : `acceptEdits`, la valeur de la fiche si elle en a une, ou `bypassPermissions` (`MODE_SANS_INTERLOCUTEUR`) pour un tour sans interlocuteur ;
  - VS Code : `acceptEdits`, fixé au niveau machine par la dernière ouverture, et **`--allow-dangerously-skip-permissions`** ;
  - terminal : le `defaultMode` du projet, qui vaut `bypassPermissions` dans `projet-sans-nom` et `…webtools-ce`, et `default` pour l'Assistant.
- **Causes :**
  - `sessions.send` (choix du mode du tour) et `vscode_handoff.ecrire_mode_machine` (réglage machine) ;
  - `claudeCode.allowDangerouslySkipPermissions: true` reste dans `Machine/settings.json` alors que le code ne l'écrit plus.
- **Correction (lot E) :**
  - le mode vit dans `.claude/settings.local.json` ; le harnais et l'extension en dérivent ;
  - retirer `allowDangerouslySkipPermissions` au démarrage, dans `ecrire_enveloppeur_machine`.

**M2. Le terminal et wikichat ne lancent pas la même version du CLI.**

- **Mesure :** l'Atelier et VS Code lancent 2.1.282 ; le terminal et wikichat lancent 2.1.281 par le lien `~/work/bin/claude`. L'extension 2.1.282 a été installée à 22:01, après le démarrage de l'Atelier (21:32).
- **Cause :** `claude_home.aligner_le_lien_claude` n'est appelé qu'au démarrage (`api.py`, l. 622).
- **Correction :** l'enveloppeur proposé en G1 résout le binaire le plus récent à chaque lancement.

**M3. Assistant : VS Code et le terminal perdent wikichat.**

- **Mesure :** le tour de l'Atelier a `atelier` et `wikichat`. Dans le même dossier de session, VS Code et le terminal n'ont que `atelier`.
- **Cause :** le `.mcp.json` des dossiers de session de l'Assistant (et celui de `~/work/wikichat-memory`) est un « binding » à drapeaux `enabled`, pas une déclaration Claude Code. `lier_tous_les_projets` ne parcourt que `~/work/projects`, et `lier_le_projet` n'est appelé pour l'Assistant qu'au tour suivant. Aucune session de l'Assistant n'a eu de tour depuis le 28/08.
- **Correction :** lier aussi `assistant_root` et ses sessions au démarrage, et garder la sélection de la session hors du `.mcp.json`.

**M4. Un serveur résiduel `chrome-devtools` échoue dans VS Code et le terminal.**

- **Mesure :** `~/.claude.json` → `projects["…/nouveau-projet"].mcpServers.chrome-devtools` pointe vers `http://127.0.0.1:3000/mcp`, un ancien service. Il est `FAIL` dans VS Code et le terminal, et absent des tours de l'Atelier (`--strict-mcp-config`). Son nom est voisin de `chrome-devtools-mcp`.
- **Cause :** `_merge_user_claude_json` ne réécrit que `mcpServers` à la racine, pas la portée locale des projets.
- **Correction :** purger ou signaler les `projects.*.mcpServers` que l'Atelier ne gère pas, dans `lier_le_projet` et dans le vérificateur.

**M5. n8n échoue partout mais reste proposé.**

- **Mesure :** l'adresse du connecteur répond 401 avec le jeton du pool. Le serveur est `FAIL` sur toutes les surfaces, mais il reste écrit dans tous les projets qui héritent du pool.
- **Cause :** le jeton n'est plus valide (la rotation demandée dans `decisions.md` est en attente).
- **Correction :** renouveler le jeton ; une sonde en échec doit marquer le connecteur plutôt que le distribuer.

**M6. gitlab est connecté mais n'expose aucun outil, sur aucune surface.**

- **Mesure :** gitlab (npx `@modelcontextprotocol/server-gitlab`) est `connected` avec 0 outil, et absent de la passerelle.
- **Cause :** non diagnostiquée (jeton, ou `tools/list` vide).
- **Correction :** même sonde qu'en G3.

**M7. `gateway_find_tools` ne trouve pas les commandes de l'Atelier.**

- **Mesure :** la recherche ne connaît aucun `atelier_*`, alors que `gateway_call_tool` les appelle.
- **Pourquoi c'est un problème :** l'architecture (§1.8) dit que « `gateway_runtime.py` donne le catalogue à la passerelle comme famille d'outils locaux ». Pour l'Assistant, qui atteint tout par chercher puis appeler (décision A-2), les commandes seraient invisibles.
- **Correction :** indexer la famille locale dans l'inventaire de `gateway_find_tools` (`gateway_runtime`, `tool_search`).

**M8. wikichat est joignable sous deux identités.**

- **Mesure :** `gateway_find_tools` propose les 53 `wikichat__*`. Appelés par `gateway_call_tool`, ils agissent sous l'identité **`passerelle-atelier`**, pas sous celle de la conversation, alors que l'agent a déjà le pont natif. Mémoire et courrier peuvent donc partir sous un autre nom.
- **Correction (lot F) :** retirer du catalogue proposé aux agents du pod les serveurs qu'ils ont déjà en natif, wikichat d'abord.

**M9. Hors de l'Atelier, l'identité wikichat repose sur le seul hook `SessionStart`.**

- **Mesure :** dans VS Code et le terminal, le pont reçoit `CLAUDE_CODE_SESSION_ID`, mais pas `WIKICHAT_AGENT`. Sans hook (hook en échec, ou `disableAllHooks`), la session reste anonyme (`session-xxxx`).
- **À vérifier :** wikichat liste `projet-sans-nom-5-2e11c5`, la conversation de l'Atelier `2e11c55e`, avec `surface: vscode`.

### Mineurs

- **m1. Réglages VS Code :** `claudeCode.environmentVariables` ne porte que `ANTHROPIC_BASE_URL`, alors que la documentation annonce aussi `ANTHROPIC_MODEL`. C'est sans effet : le modèle vient de `settings.json`.
- **m2. Résidus dans `~/.claude.json` :**
  - des `disabledMcpServers` (`Onyxia_nic01asfr`, `datagouv`…) restent dans une douzaine de projets. Ils sont inertes aujourd'hui, mais un nom réintroduit y serait désactivé dans VS Code et au terminal seulement ;
  - `projects[projet-sans-nom-5].enabledMcpjsonServers = []`, tandis que la liste complète est dans `settings.local.json`. Claude Code réunit les deux, mais cela fait deux sources.
- **m3. Environnement commun à tous les projets :** `VOICE_TOKEN`, variable propre à `nouveau-projet-2`, est dans `claude-env.sh` et donc reçue par tous les projets sur toutes les surfaces (écart connu, `coherence-projet.md`).
- **m4. Autorisation morte :** `projet-sans-nom-3/.claude/settings.local.json` autorise `WebSearch`. Le refus global l'emporte ; cette entrée est à retirer.
- **m5. Accès large de filesystem :** le serveur `filesystem` est ouvert sur `/home/onyxia/work`, `.secrets` compris. Bash donne déjà cet accès, mais cela contredit l'esprit de J-h et du cloisonnement par projet.
- **m6. Différences voulues :** l'agent `claude-code-guide` n'existe que dans VS Code (point d'entrée `claude-vscode`), et l'en-tête `X-Atelier-Conversation` vaut `poste` hors de l'Atelier. Les deux sont prévus.

### Conforme

- **Serveur `atelier` :** 36 outils identiques partout où il se connecte ; catalogue et classes conformes (§4).
- **Recherche web :** WebSearch est refusé partout, WebFetch est présent partout.
- **Modèle :** le même partout ; effort `medium` partout.
- **Hooks :** un seul fichier de réglages, lu par toutes les surfaces ; `atelier-figer-le-travail.sh` est bien sous `SessionEnd`.
- **Secrets :** aucune valeur secrète ni motif de jeton dans 52 fichiers (`~/.claude.json`, réglages User et Machine de code-server, `claude-mcp.json`, `mcp-config.json`, `settings.json`, tous les `.mcp.json` et `settings*.json` de projet, les fichiers effectifs, les `.mcp.json` de l'Assistant). Seuls les noms ont été affichés.
- **Enveloppeur VS Code :** il charge bien les 7 variables, constaté dans `/proc`.

## 6. Ce que prouve `atelier-verifier-coherence`

Sur le pod, l'outil répond « Aucun écart » (code 0). L'intuition était juste : il ne compare
**pas** les vrais projets. Les identifiants affichés (`Bearer cle-a…`, `jeton-n8n-ve…`) sont les
12 premiers caractères de `CLE_ATELIER = "cle-atelier-verif-…"` et de `JETON_N8N` : des valeurs
d'essai écrites dans le script.

**Ce qu'il fait** (`bin/atelier-verifier-coherence`, `main`) :

- il crée dans `/tmp` un Atelier jetable : un `HOME` de test, un pool de **deux faux serveurs HTTP** (`qgis`, `n8n`) qui pointent vers une sonde locale, et des clés factices ;
- il coupe wikichat (`wikichat_url` vers le port 1) et le navigateur (`navigateur=False`), et donne au modèle une adresse morte ;
- il crée deux projets, `essai-herite` et `essai-restreint`, et lance `~/work/bin/claude` trois fois pour chacun. Les trois « surfaces » partagent un `CLAUDE_CONFIG_DIR` qui ne contient que `.claude.json`.

**Ce qu'il prouve :** sur ce binaire, la chaîne suivante donne les mêmes noms de serveurs, le
statut `connected`, et les mêmes en-têtes reçus par la sonde :

1. `materialize_mcp_config` ;
2. `lier_le_projet` et `write_project_binding` ;
3. les références `${ATELIER_MCP_…}` ;
4. leur développement par Claude Code depuis `claude-env.sh`.

Il prouve aussi que `comparer` ne trouve ni écart de déclaration ni secret en clair **dans les
fichiers du HOME de test**.

**Ce qu'il ne prouve pas :**

- les vrais projets, le vrai pool, `~/.claude.json` et les vrais réglages : `fichiers_a_inspecter` et `donnees_code_server` suivent le `HOME` de test ;
- le pont wikichat, Chrome en stdio, les serveurs stdio à `args` (n8n réel, gitlab), la poignée de main d'Onyxia : G3, M5 et M6 sont invisibles ;
- le nombre d'outils : il ne lit que `mcp_servers`, pas `tools` ;
- les hooks, les refus (WebSearch), le mode de permission, le modèle et l'effort : le dossier de configuration de test n'a pas de `settings.json` ;
- la version du binaire par surface : il lance `~/work/bin/claude` pour les trois (M2 invisible) ;
- le vrai chemin du terminal : il source `claude-env.sh` par `bash -c '. fichier && exec …'` au lieu de passer par `~/.bashrc` (G1 invisible) ;
- le vrai enveloppeur : l'environnement « vscode » est calculé en Python (`environnement_du_claude_vscode`), sans exécuter `atelier-claude-vscode` ;
- le vrai lancement de l'extension : ni `--setting-sources`, ni `--permission-mode`, ni `--allow-dangerously-skip-permissions`.

En résumé, l'outil prouve que le mécanisme des références et de la liaison est cohérent sur des
données d'essai. Il ne dit rien de ce que reçoivent les agents des projets réels.

**Pour qu'il le dise :**

- ajouter un mode `--reel` qui lit l'`init` de chaque surface sur des projets réels, avec la méthode du §1 (`disableAllHooks`, `--no-session-persistence`, `CLAUDE_CONFIG_DIR` copié) ;
- comparer `tools`, `permissionMode`, `model`, la version du binaire, et les hooks lus dans les réglages ;
- ajouter une surface « `bash -lc` » ;
- ajouter le contrôle du hook `garde_bash`, exécuté depuis un dossier de projet.
