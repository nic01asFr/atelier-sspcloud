# L'Atelier, harnais et serveur MCP : tout par les primitives de Claude

> État au 11/10/2026. **Proposition d'architecture**, non implémentée. Elle s'appuie sur la lecture de
> la documentation de Claude Code (réglages, hooks, skills, sous-agents, plugins, MCP, canaux,
> modèles, environnements auto-hébergés) et sur l'étude du code faite le même jour. Les points
> marqués **[à prouver sur le pod]** sont lus dans la doc mais n'ont pas été essayés ici.
> La page MCP Apps de modelcontextprotocol.io n'a pas pu être lue depuis la session : ce qui la
> concerne vient de la page « Build an MCP server for Claude ».

## 1. L'idée

L'Atelier est présent **deux fois** dans chaque agent, par des primitives que Claude Code connaît
déjà :

- **comme harnais installé** : réglages, hooks, skills, sous-agents, plugin, variables
  d'environnement. C'est ce qui *encadre* l'agent, sans qu'il ait à le savoir ;
- **comme serveur MCP** : outils, prompts, ressources, instructions, demandes de saisie. C'est ce
  qui *sert* l'agent, et que l'agent appelle.

Les deux faces lisent **la même définition de rôle** (`roles.py`, à écrire). Une consigne ne doit
plus être qu'un texte que le harnais place au bon moment, jamais une règle que l'agent doit se
rappeler.

Règle de choix, dans cet ordre : (1) une clé de réglage ou une primitive native ; (2) un hook ou un
skill fourni par le plugin de l'Atelier ; (3) un outil MCP ; (4) du code de l'Atelier. On ne passe
au suivant que si le précédent ne sait pas le faire.

## 2. Le plancher : les réglages gérés

Les réglages gérés passent **au-dessus de tout** : fichier projet, fichier utilisateur, `--settings`
d'une session. Sous Linux : `/etc/claude-code/managed-settings.json`, un dossier
`managed-settings.d/` (un fichier par propriétaire), et `managed-mcp.json`. Ils sont lus aussi en
mode `-p` et par le SDK.

| Besoin de l'Atelier | Clé native |
|---|---|
| Seuls les hooks de l'Atelier tournent | `allowManagedHooksOnly` (un plugin forcé dans `enabledPlugins` en est exempt) |
| Seules les règles de l'Atelier comptent | `allowManagedPermissionRulesOnly` |
| Seuls les serveurs MCP de l'Atelier | `allowManagedMcpServersOnly`, `managedMcpServers`, `managed-mcp.json` |
| Pas de skill, agent, hook ou MCP « maison » dans un dépôt | `strictPluginOnlyCustomization` (`.skills`, `.agents`, `.hooks`, `.mcp`) |
| Jamais de contournement des permissions | `permissions.disableBypassPermissionsMode`, `disableAutoMode` |
| Pas de lecture hors du dossier de travail | `permissions.blockReadsOutsideWorkingDirectories` |
| Secrets masqués pour les commandes | `sandbox.credentials.*`, `permissions.deny` sur `Read(./.env*)`, `Read(./.secrets/**)` |
| Hooks HTTP limités à l'Atelier | `allowedHttpHookUrls`, `httpHookAllowedEnvVars` |
| Le CLI reste dans une plage testée | `requiredMinimumVersion`, `requiredMaximumVersion` |
| Un contexte commun à tous | `claudeMd` (instructions globales gérées) |
| Les sources de plugins | `strictKnownMarketplaces`, `blockedMarketplaces` |
| Les modèles permis, l'effort maximal | `availableModels`, `deniedModels`, `maxEffortLevel` |
| Pas de sauvegarde sur claude.ai | `disableClaudeAiConnectors`, `syncClaudeAiPlugins`, `syncClaudeAiSkills` |

Deux outils pour calculer la politique **au démarrage de chaque session**, donc par rôle :

- `policyHelper` : un exécutable que le fichier géré désigne. Sa sortie (`managedSettings`) devient
  *l'unique* politique gérée de la session. C'est le compilateur de rôle idéal : il reçoit
  l'environnement de la session (`ATELIER_SESSION`, rôle, projet) et rend allow/deny/hooks/MCP.
  **[à prouver sur le pod : les variables qu'il reçoit, et l'échec fermé s'il plante]**
- l'option `managedSettings` du SDK (« réglages du parent »), si un jour l'Atelier lance le CLI par
  le SDK plutôt que par `claude -p`.

**Condition de sécurité.** Un réglage géré ne protège que si l'agent ne peut pas le réécrire. Les
agents tournent sous le même utilisateur Unix que l'Atelier : le fichier doit appartenir à `root`
et être illisible en écriture pour l'utilisateur du pod. **[à prouver : le pod a-t-il un `root` ?]**
Sinon, la politique est une indication et non une frontière, et le hook `ConfigChange` (qui peut
bloquer toute modification des réglages hors politique) devient le filet. À vérifier aussi : un
fichier géré illisible fait démarrer la session **sans** politique, d'où la sonde `claude doctor` /
`/status` dans le contrôle de cohérence.

## 3. Les hooks : le cœur du harnais

Trois types sont utiles, tous avec la même entrée et la même sortie JSON :

- **`http`** : le CLI envoie l'événement en POST à l'Atelier (`127.0.0.1`) et applique la réponse.
  Plus de scripts à poser : un seul point d'entrée `POST /v1/hooks/<événement>`, qui connaît déjà la
  conversation (`session_id`), le rôle, le projet, la file « À valider ».
- **`mcp_tool`** : le hook appelle directement un outil du serveur MCP de l'Atelier.
- **`command`** (forme exec) : pour les gardes qui doivent marcher même si l'Atelier est arrêté
  (`garde_bash`).

Le champ `if` (syntaxe des règles de permission) évite d'appeler l'Atelier pour rien. Un hook
`PreToolUse` qui expire **ne bloque pas** par défaut : les gardes qui doivent fermer utilisent
`onFailure: "block"`.

| Événement | Ce que l'Atelier en fait |
|---|---|
| `SessionStart` (`startup`, `resume`, `compact`, `fork`) | `additionalContext` : carte, « À valider » du projet, messages en attente, état. Écrit `ATELIER_SESSION` dans `CLAUDE_ENV_FILE`. `watchPaths`, `reloadSkills`. Remplace la régénération de `contexte.md`. |
| `UserPromptSubmit` | Contexte du tour : ce qui a changé depuis le dernier tour (lancement fini, décision tranchée, message d'un autre agent). Bloque un message contraire au rôle. |
| `UserPromptExpansion` | Contrôle des commandes `/…` avant qu'elles n'atteignent le modèle. |
| `PreToolUse` | Grille de rôle : `allow`, `deny` **avec la raison et la voie de sortie**, `ask`, `defer`. `updatedInput` pour réécrire (chemin de la copie de travail, jeton). |
| `PermissionRequest` | Décision au nom de la personne quand une règle l'a déjà accordée (remplace `Regle.couvre` refait à la main) ; sinon laisse passer vers l'écran et la veille. |
| `PermissionDenied` | `retry: true` quand la personne vient d'accorder. |
| `PostToolUse` / `…Failure` | `updatedToolOutput` : masquer un secret. `additionalContext` : l'indice qui accompagne le résultat (plafond de 40 s d'un `exec` Onyxia, au lieu de le coder dans le mandataire). |
| `PostToolBatch` | Arrêt de la boucle si un garde l'exige. |
| `Stop` / `SubagentStop` | `decision: block` tant que la sortie ne remplit pas les critères (« Fini quand », `ETAT.md` à jour, message `done`). Règle D-51. |
| `StopFailure` | La fin sur erreur d'API est enregistrée comme un échec vrai (D-10). |
| `Notification` (`permission_prompt`, `idle_prompt`, `agent_needs_input`, `agent_completed`) | Alimente directement le notifieur push. |
| `PreCompact` / `PostCompact` | Instructions de compaction ; ré-injection du contexte du rôle. |
| `TaskCreated` / `TaskCompleted` | Suivi des tâches de l'agent dans « À valider ». |
| `SubagentStart` | `additionalContext` aux sous-agents. |
| `WorktreeCreate` / `WorktreeRemove` | Remplace `git worktree` fait à la main : le CLI demande, l'Atelier crée la copie de travail sur `agent/…` et pose ses garde-fous git. |
| `Elicitation` / `ElicitationResult` | Une demande de saisie d'un serveur MCP arrive à l'Atelier, qui la montre à la personne (écran ou notification) et rend la réponse. |
| `ConfigChange` | Bloque toute modification de réglages hors politique. |
| `InstructionsLoaded`, `CwdChanged`, `FileChanged`, `DirectoryAdded` | Preuve de ce qui est chargé ; surveillance de `projet.json`, `ETAT.md`. |
| `PreModelSwitch` / `PostModelSwitch` | Garde de coût et de rôle. |
| `SessionEnd` | Figer le travail (existe déjà). |
| `async` / `asyncRewake` | Veilleur en arrière-plan qui **réveille** l'agent (code 2) : lancement fini, réponse reçue. |

`PreToolUse` accepte `permissionDecision: "defer"`. La doc le liste mais ne le détaille pas dans
l'extrait lu : si c'est bien « suspendre le tour headless pour qu'un humain réponde, puis reprendre
avec `--resume` », il remplace la mécanique maison de veille (tuer le processus, garder la trace,
relancer). **[à prouver : premier essai à faire]**

## 4. Les skills : la consigne qui ne coûte que si on s'en sert

Un `SKILL.md` ne charge son corps que lorsqu'il sert ; il est ré-attaché après une compaction
(5 000 jetons par skill, 25 000 au total), ce que `CLAUDE.md` ne garantit pas. L'Atelier y range ce
qui est aujourd'hui dans `consignes/socle.md` et dans les prompts de lancement :

- une skill par geste : `reprendre`, `verifier`, `fin-de-lot`, `proposer`, `deployer`, `montrer` ;
- `disable-model-invocation: true` pour tout geste à effet de bord : seule la personne le lance ;
- `allowed-tools` limité au geste, `context: fork` + `agent` pour les analyses isolées ;
- injection dynamique `` !`atelier-contexte` `` : l'état du projet au moment de l'appel ;
- `paths` : une skill qui ne s'active que dans les fichiers du projet concerné ;
- `hooks` dans l'en-tête : un garde qui n'existe que le temps de la skill ;
- `skillOverrides` pour couper une skill sans la modifier.

Les commandes `/reprendre`, `/verifier`, `/fin-de-lot`, `/proposer`, toujours « à faire » dans
`structure-projet.md`, deviennent ainsi des skills du plugin, sans fichier à copier dans chaque
projet.

## 5. Les sous-agents : le rôle compilé en natif

Un rôle de l'Atelier est une **définition de sous-agent** (`name`, `description`, `tools`,
`disallowedTools`, `model`, `effort`, `permissionMode`, `skills`, `hooks`, `mcpServers`, `memory`,
`isolation: worktree`, `background`, `maxTurns`). Deux façons de l'appliquer :

- `claude --agent <rôle>` (ou la clé `agent`) : la session *est* ce rôle, avec sa liste d'outils
  **fermée** (`tools:`), au lieu d'une règle `allow` qui n'en est pas une (écart relevé à l'étude) ;
- `--agents '{…}'` : définitions passées à la session, non enregistrées, au plus haut rang après la
  politique gérée.

Un plugin ne peut pas déclarer `hooks`, `mcpServers` ni `permissionMode` dans ses agents, pour
sa propre sécurité : ces trois champs viennent donc de la politique gérée ou de `--agents`, jamais
d'un dépôt.

Les lancements (`lancements.py`) gardent ce que le natif ne donne pas : la durabilité, les plafonds
par jour, la supervision, « À valider », la fusion réservée. Mais leur **rôle** devient un
`--agent`, et leur copie de travail passe par `WorktreeCreate`.

La mémoire native d'un agent (`memory: project`, dossier `MEMORY.md`) et la clé
`autoMemoryDirectory` permettent de pointer la mémoire automatique vers un dossier que wikichat
tient et filtre. La règle « la mémoire n'apprend que ce qui vient de la personne » (critère f)
s'applique alors à une seule source.

## 6. Le plugin « atelier » : le paquet qui porte tout

Un plugin regroupe skills, agents, hooks, serveurs MCP, moniteurs, commandes, styles de sortie,
exécutables (`bin/` sur le `PATH` de l'outil Bash) et un `settings.json` d'`agent` par défaut.
Forcé dans `enabledPlugins` par la politique gérée, il est exempté de `allowManagedHooksOnly`.

- **Un seul paquet versionné** : `claude plugin validate` en CI devient le test de contrat contre
  la dérive du CLI (écart relevé : binaire non épinglé).
- **`userConfig`** : valeurs demandées une fois ; les `sensitive` vont au stockage sécurisé.
- **Moniteurs** (expérimental) : un processus de fond par session qui notifie l'agent (lancement
  fini, alerte de gardien, réponse à « À valider »).
- **Canaux** : un serveur MCP qui *pousse* des événements dans la session (`claude/channel`), avec
  relais des demandes d'autorisation vers un autre appareil. Utile en session interactive ;
  **ignoré en `-p`** et soumis à `channelsEnabled` / `allowedChannelPlugins`. L'Atelier garde donc
  son écriture sur l'entrée standard du processus gardé comme canal principal.
- **Les extensions de la personne** (famille « savoir-faire » de `ecosysteme.md`) sont des plugins
  du même format, dans un marché `extraKnownMarketplaces` tenu par l'Atelier ; « ajouté à mon
  Atelier » = une entrée dans `enabledPlugins`.

## 7. Le serveur MCP : tout ce que la spécification permet

| Capacité MCP | Usage dans l'Atelier |
|---|---|
| `instructions` du serveur | Une phrase par profil, livrée au connexion. |
| Outils + annotations | `readOnlyHint` / `destructiveHint` alignés sur les classes lecture / réversible / engageante / réservée ; `_meta["anthropic/maxResultSizeChars"]` pour les gros résultats (carte, journal). |
| **Prompts** | Chaque prompt devient une commande `/mcp__atelier__<nom>` : `reprendre`, `proposer`… sans fichier. À regarder si une skill suffit. |
| **Ressources** | `@atelier:carte`, `@atelier:a-valider`, `@atelier:projet/ETAT` : contexte à la demande plutôt que fichiers régénérés. |
| `list_changed` | Les outils d'un profil changent à chaud sans reconnexion. En `-p` seule la liste d'outils se rafraîchit. |
| **Élicitation** | L'outil qui a besoin d'une décision la demande dans le protocole (formulaire), au lieu du contournement `AskUserQuestion` → `deny`. Interceptée par le hook `Elicitation`. |
| Identité | `headersHelper` (existe) + variables `${…}` ; un jeton par conversation (§8). |
| **MCP Apps** | Les créations s'affichent par `ui://` dans le panneau **et** dans claude.ai, avec le même rendu. C'est le contrat unique prévu pour le panneau (P3). |
| Limites | claude.ai : 240 s par appel, ~150 000 caractères ; Claude Code : 25 000 jetons par défaut, `MCP_TOOL_TIMEOUT`. Les outils longs rendent un identifiant et se suivent (`atelier_suivre`). |
| Authentification pour claude.ai | OAuth avec enregistrement dynamique, redirection `https://claude.ai/api/mcp/auth_callback`, rafraîchissement du jeton, authentification paresseuse (les outils de lecture marchent sans compte). |
| `-p` | Pas de dialogue d'approbation ni d'OAuth : un serveur d'identité statique est donc obligatoire côté agents. |

Des serveurs locaux sous forme de paquet `.mcpb` ne servent qu'à Claude Desktop sur le poste de la
personne (accès à QGIS local, fichiers privés) : leur dépôt dans l'annuaire est abandonné. À garder
pour plus tard, comme passerelle d'un poste vers l'Atelier.

## 8. L'identité par conversation, sur le modèle de Claude

Les environnements auto-hébergés donnent à chaque session un jeton signé
(`CLAUDE_CODE_SESSION_ACCESS_TOKEN`, ES256, `iss`, `aud`, `exp` de 4 h, `jti`, chaîne `act`) que les
services vérifient avec une clé publique. Leur doc dit aussi le défaut : le jeton est dans
l'environnement, donc **tout processus de la session peut le présenter** ; il faut borner ce qu'on
en dérive et auditer par `session_id` + `jti`.

L'Atelier reprend ce modèle pour D1 (la clé propriétaire ne doit plus voyager) : un jeton court par
conversation, signé, porteur du rôle et du projet, vérifié par le serveur MCP et par les hooks
HTTP. Il prouve *quelle conversation parle*. Il **ne prouve pas qu'un humain a décidé** : la
confirmation d'une action engageante (D-02) doit donc rester un jeton qui ne passe que par
l'interface ou la notification (déjà fait pour les décisions), jamais par l'environnement de l'agent.

## 9. Les modèles et le relais

- `ANTHROPIC_BASE_URL` → relais (existe). `ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU}_MODEL` fait
  pointer les alias natifs sur les modèles de SSPCloud : un rôle écrit `model: haiku`.
- `CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY=1` : le sélecteur se remplit depuis `/v1/models` du
  relais ; `modelPicker` fixe l'ordre. `ANTHROPIC_CUSTOM_MODEL_OPTION` pour les modèles hors alias.
- `fallbackModel` (jusqu'à trois, sur erreurs 5xx) : la bascule entre modèles de SSPCloud devient
  native.
- Compaction : `CLAUDE_CODE_MAX_CONTEXT_TOKENS`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`, et
  `CLAUDE_CODE_DISABLE_UNKNOWN_MODEL_WINDOW_ENFORCEMENT=1` (compacter après un refus de l'API)
  permettraient de retirer le repli « caractères/3 ».
- L'effort : `CLAUDE_CODE_EFFORT_LEVEL` annule tout (`--effort`, `modelSettings`, frontmatter). Le
  poser en variable d'environnement globale empêche les rôles d'avoir le leur ; le préférer dans
  les définitions d'agent, avec `maxEffortLevel` comme plafond.
- Le mode rapide est réservé aux modèles Opus de l'API Anthropic, avec crédits : sans objet ici.

## 10. Les environnements auto-hébergés : une seconde porte, pas le fondement

Le produit d'Anthropic fait tourner des sessions *cloud* (lancées depuis claude.ai, l'application
mobile, les routines planifiées, `claude --cloud`) sur un **runner** que l'on héberge, avec des
scripts enveloppes par session, des hooks de cycle de vie, un orchestrateur à la demande et des
serveurs MCP. Le pod de l'Atelier pourrait en être un.

Ce que cela apporterait : les routines planifiées d'Anthropic et leurs applications comme façade,
sans réécrire de planificateur. Ce qui l'en empêche aujourd'hui : plans Team ou Enterprise
seulement, bêta, inférence par l'API Anthropic ou Bedrock / Google (pas les modèles de SSPCloud),
conversation transmise à Anthropic, incompatible avec le zéro-rétention. C'est donc une **option
pour une personne qui a un abonnement Team**, qui ne remplace ni la PWA ni la souveraineté. À
noter : *Remote Control* (disponible dès Pro et Max) pilote un Claude Code qui tourne sur une
machine à soi depuis un autre appareil, ce qui recoupe notre PWA.

## 11. wikichat et les automatisations

wikichat reste la maison de la connaissance et de la coordination ; il ne filtre plus lui-même les
outils d'un rôle.

| Besoin | Chemin natif |
|---|---|
| Briefing au démarrage | `SessionStart` `additionalContext`, rempli par l'Atelier depuis wikichat. |
| Mémoire et fiches | Ses hooks `Stop` / `SessionEnd` existants passent dans le plugin ; `autoMemoryDirectory` vers son dossier. |
| Routine / déclencheur qui lance un agent | `claude -p --agent <rôle>` avec la politique gérée, par `POST /v1/lancements`. Le rôle vient du registre commun. |
| Un événement réveille un agent | Écriture sur l'entrée du processus gardé ; hook `asyncRewake` ; moniteur du plugin. |
| Un agent planifié demande une décision | Veille (`defer` ou mécanisme actuel) + notification, jamais un refus. |
| Messagerie entre agents | Ressource `@atelier:messages` + contexte injecté par `UserPromptSubmit`. |
| Outils d'un rôle | La même liste alimente la politique gérée, la définition d'agent et le profil de la passerelle. |

## 12. Cas de la spécification pas encore utilisés

- Sandbox (`sandbox.enabled`, réseau, système de fichiers, masquage des identifiants) pour les
  agents lancés sur branche.
- Style de sortie (`outputStyle`) par rôle ; `statusLine` pour afficher rôle et projet dans le
  terminal et VS Code.
- `fileCheckpointingEnabled` / `/rewind` pour annuler un tour.
- `claudeMdExcludes` et `.claude/rules/*.md` par chemin.
- Agents en arrière-plan natifs et équipes d'agents (`teammateMode`, `crossSessionInbound`).
- `includeGitInstructions`, `attribution` (signature des commits des agents).
- `worktree.*` (`baseRef`, `sparsePaths`, `symlinkDirectories`).
- Télémétrie OpenTelemetry (`prompt_id` des hooks) pour le coût et l'audit.

## 13. À prouver sur le pod avant d'écrire du code

1. Le pod a-t-il un `root` pour poser `/etc/claude-code/` hors de portée des agents ?
2. Le CLI lancé par l'Atelier lit-il bien `managed-settings.json`, `managed-settings.d/` et
   `managed-mcp.json` en `-p --input-format stream-json` ? Le registre note que des hooks passés
   par `--settings` n'étaient pas pris : l'essai dira si c'est vrai aussi des hooks gérés.
3. Un hook `http` vers `127.0.0.1:8787` marche-t-il, avec `PermissionRequest` et
   `--permission-prompt-tool stdio` ensemble ?
4. `permissionDecision: "defer"` : sémantique exacte en `-p`.
5. `policyHelper` : environnement reçu, délai, comportement si l'exécutable échoue.
6. `UserPromptSubmit` / `SessionStart` : l'`additionalContext` atteint-il le modèle derrière le
   relais (c'est ce qu'`--append-system-prompt` n'a pas fait) ?
7. `--agent` et `tools:` : liste fermée respectée, y compris pour les outils MCP.
8. Les skills d'un plugin forcé sont-elles visibles et ré-attachées après compaction ?
9. Prompts et ressources MCP : listés et utilisables en `-p` ?

Chaque essai tient en un script court et laisse une trace dans `docs/vision/registre-des-defauts.md`.

## 14. Ordre proposé

1. **Les essais du §13** (aucune ligne de production).
2. **Le registre des rôles** (`roles.py`) et un compilateur vers quatre sorties : politique gérée,
   définition d'agent, profil de passerelle, configuration des hooks.
3. **Le plugin « atelier »** : hooks HTTP (`SessionStart`, `UserPromptSubmit`, `PreToolUse`,
   `PostToolUse`, `Stop`), skills des gestes, sous-agents des rôles.
4. **Le noyau natif** : retirer ce que le natif fait mieux (règles de permission refaites, repli
   de compaction, `contexte.md` régénéré, journal parallèle).
5. **Le jeton par conversation** (D1) et la confirmation liée à l'humain (D-02) : à soumettre à la
   personne avant tout code.
6. **MCP Apps** pour le panneau, et le serveur ouvert à claude.ai.
7. Plus tard : environnement auto-hébergé, paquet `.mcpb`.
