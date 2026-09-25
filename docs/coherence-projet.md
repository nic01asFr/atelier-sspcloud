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
| MCP | oui | fichier effectif `--strict-mcp-config` ≠ `~/.claude.json` | `.mcp.json` + portée utilisateur, références (lots A, F) |
| Outils différés (tool search) | oui, **désactivé par `ANTHROPIC_BASE_URL` personnalisé** | passerelle `find/call` en remplacement | vérifier `ENABLE_TOOL_SEARCH=true` avec la passerelle LLM ; sinon garder la passerelle |
| Compaction | oui (auto), **inopérante** : la passerelle LLM rapporte 0 jeton | pilotée par l'Atelier, pas dans VS Code | corriger le décompte côté passerelle LLM si possible ; sinon hook `PreCompact`/`Stop` commun à toutes les surfaces |
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
