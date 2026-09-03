# Atelier × Wikichat — Architecture et alignement

Document de référence pour l’intégration **Atelier** (hub SSP / Onyxia), **Wikichat** (coordination + mémoire), **Claude Code** (agent code) et **VS Code** (code-server).

**Statut** : spec cadrée, implémentation partielle (voir § État actuel).

**Audience** : dev Wikichat, dev Atelier, plateforme SSP (auth GitHub).

**MCP (pool, Connecteurs, Agent, `.mcp.json`)** : [`atelier-mcp-unified.md`](./atelier-mcp-unified.md).

---

## 1. Objectifs

1. **Projets** = dossiers versionnés (git), pas un fourre-tout `default`.
2. **Sessions** = fils de conversation dans un projet, avec historique isolé.
3. **Assistant** (chat / suivi user) ≠ **agent code** (édition, outils, repo métier).
4. **Mémoire transverse** centralisée dans un repo GitHub user (`wikichat-memory`), distinct du **code du service Wikichat**.
5. **VS Code** sur le même PVC `~/work`, ouverture sans friction (Git + Claude Code + session courante).

---

## 2. Vue d’ensemble

```
Navigateur
    → Ingress Atelier (:8787)
        → Hub web (sessions, MCP, chat SSE)
        → Proxy /vscode/ → code-server (:8080, loopback)

Pod Atelier (un PVC ~/work)
├── mcp/                 # Gateway MCP unifié (catalogue, pool, compositions) — voir MCP doc
├── wikichat-memory/     # repo GitHub USER — assistant + mémoire centrale
├── projects/<slug>/     # repos code (git init / clone)
├── sessions/<uuid>.json # métadonnées Atelier
├── transcripts/<slug>/<uuid>.jsonl
├── wikichat/            # code / runtime service Wikichat (plateforme, pas workspace agent)
└── .secrets/            # owner key, llm, github (futur)
```

| Composant | Rôle |
|-----------|------|
| **Atelier** | API, hub UI, harness Claude, proxy VS Code |
| **Wikichat (service)** | MCP coordination, `search_knowledge`, `close_project`, multi-agents |
| **wikichat-memory (repo)** | Données user : `.wikichat/`, consignes assistant, agrégation |
| **code-server** | VS Code web, extension Claude Code |
| **Claude Code** | Agent CLI + extension ; sessions nommées par le produit |

---

## 3. Deux familles de workspace

| | **Assistant** | **Code** |
|---|---------------|----------|
| **Kind** | `assistant` | `code` |
| **Repo** | `wikichat-memory` (GitHub user) | `projects/<slug>/` (git projet) |
| **cwd session** | sous-dossier session (`assistant/sessions/<uuid>/`) | racine du repo projet |
| **Binding MCP (niveau 2)** | `.mcp.json` racine + sous-dossier session | `.mcp.json` racine projet (partagé) |
| **MCP conversation (niveau 3)** | composer `+` (overlay session) | composer `+` (overlay session) |
| **UI principale** | Hub Atelier | Hub + VS Code |
| **Consignes Claude** | `CONSIGNES.md` / `.claude` mode chat | `CLAUDE.md` + `.claude` mode agent |
| **Wikichat** | `.wikichat/` central (mémoire unifiée) | `.wikichat/` local au projet |

Détail MCP (pool, Connecteurs, Agent, trois niveaux) : [`atelier-mcp-unified.md`](./atelier-mcp-unified.md).

**Règle importante** : un **repo ≠ une session**. Un projet accueille ** plusieurs sessions** (fils). Les sessions partagent le repo et le git ; seuls l’historique et l’overlay de consignes sont isolés.

---

## 4. Wikichat : code service ≠ repo mémoire

### 4.1 Repo code Wikichat (service)

- **Contenu** : MCP server, sources, déploiement (`~/work/wikichat/` sur le pod).
- **Propriétaire** : plateforme / org (SSP).
- **Workspace agent** : **non** — les sessions ne doivent pas éditer ce repo pour éviter corruption du service.
- **Permissions agents** : lecture seule ou hors workspace.

### 4.2 Repo `wikichat-memory` (mémoire user)

- **Contenu** : mémoire unifiée, consignes assistant, agrégation cross-projets.
- **Propriétaire** : utilisateur (provisionné à l’onboarding GitHub).
- **Chemin local** : `~/work/wikichat-memory/`
- **Sessions assistant** : `cwd` = sous-dossier session ; env session = ce dossier.

**Structure suggérée (template seed)** :

```
wikichat-memory/
├── README.md
├── CONSIGNES.md              # socle chat / suivi user
├── .mcp.json                 # binding MCP assistant global (niveau 2)
├── .claude/settings.json     # mode assistant (permissions légères)
├── .wikichat/
│   ├── context.json
│   ├── knowledge/            # axes compilés (grist, sig, …)
│   └── registry/             # métadonnées projets connus
└── assistant/sessions/
    └── <uuid>/
        ├── .mcp.json         # binding MCP session (niveau 2)
        └── (overlay consignes)
```

### 4.3 Projets code

```
projects/hextokenizer/
├── .git/
├── .mcp.json                 # binding MCP projet (partagé par toutes les sessions)
├── CLAUDE.md
├── .claude/
├── .wikichat/                # mémoire locale du projet
└── src/…
```

Chaque projet code a son `.wikichat/` **normal** (messages, artifacts, knowledge projet). Le repo `wikichat-memory` **centralise** via ingestion (closure), pas en remplaçant le local.

---

## 5. Trois niveaux Wikichat

| Niveau | Emplacement | Rôle |
|--------|-------------|------|
| **Global / central** | `wikichat-memory/.wikichat/` (+ miroir `~/.wikichat/`) | Mémoire unifiée, assistant, `search_knowledge(scope=all)` |
| **Projet** | `projects/<slug>/.wikichat/` | Contexte local, coordination, closure |
| **Session** | overlay (fichier ou sous-dossier) | Consignes temporaires du fil |

**Flux closure** :

```
Session code → .wikichat/ projet
       → close_project (Wikichat MCP)
       → commit + push wikichat-memory
       → axes knowledge mis à jour
       → assistant / search_knowledge en bénéficient
```

---

## 6. Sessions et consignes

### 6.1 Métadonnées Atelier

Fichier : `~/work/sessions/<uuid>.json`

Champs actuels : `session_id`, `slug`, `cwd`, `state`, `transcript_path`, …

**À ajouter** :

| Champ | Description |
|-------|-------------|
| `kind` | `assistant` \| `code` (dérivé du slug ou explicite) |
| `title` | Nom lisible (sync Claude Code, pas seulement UUID) |
| `overlay_path` | Chemin consignes session (optionnel) |
| `mcp_overlay` | Activation conversation (niveau 3) — on/off connecteurs déjà liés ; pas de définitions |

### 6.2 Consignes en couches

Au `run_turn`, merge conceptuel :

1. Consignes globales assistant (repo mémoire) ou projet (`CLAUDE.md`).
2. Overlay session si présent.
3. Message utilisateur.

### 6.3 Noms de session

Claude Code génère des titres (`default-93`, etc.) dans `~/.claude/sessions/*.json`. **Atelier doit les reprendre** dans le hub (pas seulement `0fcdaeaa…`).

---

## 7. Authentification GitHub (proposition plateforme)

### 7.1 Besoin

- `git init` / `clone` à la création de projet.
- Push `wikichat-memory` et repos code.
- Branches / worktrees pour sub-agents (phase ultérieure).
- VS Code sans login manuel.

### 7.2 Principe

- **Per-user** : OAuth ou GitHub App, token dans `~/work/.secrets/` (pas token org global).
- **Scopes minimaux** : repos user ; pas write sur repo code Wikichat service.
- **Credential helper** : `~/work/bin/git-credential-atelier` → git et code-server transparents.

### 7.3 Onboarding (ordre cible)

1. Bind GitHub (hub ou console Onyxia).
2. Créer ou lier repo `wikichat-memory` + seed template.
3. `git clone` → `~/work/wikichat-memory/`.
4. Sync `~/.wikichat/` ↔ repo mémoire (règle à fixer avec dev Wikichat).
5. Première session `kind=assistant` sur ce repo.

### 7.4 Création projet code

`POST /v1/projects` (à définir) :

- `slug`, `kind: code`
- `github: { create: true }` ou `{ clone: "org/repo" }`
- → `projects/<slug>/` + remote + premier commit si vide.

---

## 8. VS Code + Claude Code

### 8.1 Architecture déployée

```
Navigateur → /vscode/ → proxy Atelier → http://127.0.0.1:8080 (code-server, même pod)
```

- Un seul PVC `~/work` (pas de pod VS Code séparé pour le flux hub).
- Auth : clé owner Atelier ; code-server `auth: none` en loopback.

### 8.2 Ouverture depuis le hub

`GET /v1/vscode/open?slug=&session=` :

1. `prepare_vscode_handoff()` — settings, tasks, sync `.claude`.
2. Redirect vers `folder=/home/onyxia/work/projects/<slug>` (ou `wikichat-memory` pour assistant).
3. Task `runOn: folderOpen` → `atelier-vscode-handoff.sh <session> <slug>`.

### 8.3 Layout par défaut (settings)

- `workbench.startupEditor: none`
- `workbench.secondarySideBar.defaultVisibility: hidden`
- `chat.disableAIFeatures: true`
- `claudeCode.preferredLocation: sidebar`
- `task.allowAutomaticTasks: on`

Handoff script : fermer Welcome / barre Copilot, ouvrir sidebar Claude Code, `claude --resume <session>` si binaire OK.

### 8.4 Authentification extension (login Claude.ai récurrent)

**Symptôme** : écran « Claude.ai Subscription / Anthropic Console » au lieu du chat.

**Causes connues** :

1. `~/.claude/settings.json` sans source d’identification (l’extension ignore `disableLoginPrompt` si le CLI n’a aucun moyen de s’authentifier).
2. code-server lancé **sans** variables d’environnement (webview ne hérite pas du shell).
3. Bug extension : `claudeCode.environmentVariables` peut être **effacé** au reload (cf. anthropic/claude-code#10217).

**Mitigation Atelier (triple couche)** :

| Couche | Fichier / action |
|--------|------------------|
| 1 | `~/.claude/settings.json` + `~/work/.claude/settings.json` → `apiKeyHelper` (une commande qui rend la clé) + `env.ANTHROPIC_BASE_URL` |
| 2 | `claudeCode.disableLoginPrompt: true` + `claudeCode.environmentVariables` (workspace + User code-server) |
| 3 | `start-code-server.sh` source `claude-env.sh` avant le process (env du host extension) |

`prepare_vscode_handoff()` appelle `write_claude_settings_env()` après sync `.claude`.

**La clé elle-même ne s’écrit dans aucun de ces fichiers.** Elle y était, en
clair, et un agent à qui l’on demandait d’inspecter sa configuration la
recopiait dans son transcript. Les réglages ne portent plus qu’un
`apiKeyHelper` — un `cat` du fichier de secrets, resté en 0600 — dont le CLI
lit la sortie. Vérifié sur le pod : le CLI comme l’extension s’authentifient
ainsi, sans écran de login. Ne pas rétablir `env.ANTHROPIC_API_KEY` pour
« sécuriser » une reprise qui échoue : chercher la cause ailleurs.

**Si le login réapparaît** : redémarrer code-server après mise à jour secrets ; vérifier que `llm_api_key` est présent dans `~/work/.secrets/`.

### 8.5 Limites connues

- Resume session : nécessite sync `~/work/.claude/projects/…` → `~/.claude/`.
- Extension peut afficher « Untitled » tant que le nom Claude n’est pas sync.
- Mapping UUID Atelier ↔ `sessionId` extension parfois divergent.

---

## 9. API Atelier (cible)

| Endpoint | Description |
|----------|-------------|
| `GET /v1/projects` | Liste slugs + `kind` + lien GitHub |
| `POST /v1/projects` | Créer projet (init/clone) |
| `POST /v1/onboarding/github` | Bind + provision `wikichat-memory` |
| `GET/POST /v1/sessions` | Existant ; filtrer par `slug`, exposer `title` |
| `GET /v1/vscode/open` | Existant ; `cwd` selon `kind` |

**Slug canonique assistant** : `wikichat-memory` (ou alias fixe dans la config).

**Abandon** : `default` comme fourre-tout (migration progressive).

---

## 10. Politique Git

Figée pour la partie qui l'est, et ce qui reste ouvert est nommé comme tel.

**Ce qui est en service.** Un projet de code est un dépôt dès sa création, sur
`main`, avec un commit d'ouverture — sans lui il n'y a pas de branche, et rien
à lire pour la veille. Le dossier de l'assistant en est exclu : son contenu est
de la mémoire de session, tenue par wikichat, pas du travail versionné. La
publication sur GitHub est un geste par projet, **privé par défaut**, jamais
automatique.

| Dépôt | Branche | Qui écrit |
|-------|---------|-----------|
| Projet code | `main` | L'Atelier au commit d'ouverture ; les sessions travaillent, rien ne fige encore |
| `wikichat-memory` | — | Pas un dépôt, et à dessein |

**Ce que l'Atelier dépose et ce qui reste dehors.** Le `.gitignore` posé à
l'initialisation écarte l'état de la machine (`.claude/settings.local.json`,
`.atelier/`, `.wikichat/`) et tout ce dont le nom annonce un secret (`.env*`
hors `.example`, `*.pem`, `*.key`, `*_token`, `*_secret`, `credentials*`). Le
reste — `CLAUDE.md`, `.mcp.json`, `.vscode/` — dit ce qu'est le projet et se
versionne.

**Secrets.** La publication refuse de partir si un fichier dont le nom annonce
un secret figure dans **l'histoire** du dépôt, pas seulement dans son état du
jour : le retirer du suivi ne le retire pas du commit qui l'a introduit, et
c'est l'histoire que `push` emporte. Le jeton GitHub vit dans
`~/work/.secrets/github_token` et n'entre ni dans l'URL du remote ni dans une
ligne de commande — `git` le lit par un script `GIT_ASKPASS`.

**Ce qui reste à trancher :**

- **Qui commite.** Personne aujourd'hui au-delà du commit d'ouverture. Sans
  commits, la veille n'a rien à lire. Geste dans l'interface, proposition en
  fin de tour, ou l'agent lui-même ?
- **Les branches d'agent.** La cible portait `agent/<session>/<id>` et
  l'interdiction de pousser `main` directement. Rien ne l'applique : la
  publication pousse la branche courante. À reprendre avec la question
  précédente.
- **L'identité des commits.** `ATELIER_GIT_USER_NAME` /
  `ATELIER_GIT_USER_EMAIL`, par défaut `Atelier <atelier@localhost>`, posée
  localement à chaque dépôt.
- **Les dépôts clonés.** Un projet cloné de l'amont ne se traite pas comme un
  projet né ici : ses commits sont ceux d'autrui et son identité locale est
  celle du clone.

---

## 11. État actuel vs cible

| Élément | Actuel | Cible |
|---------|--------|-------|
| VS Code proxy + extension | ✅ | — |
| Layout VS Code par défaut | ✅ | — |
| Handoff session | ✅ dans les deux sens, titres concordants | — |
| Shell multi-vues (Code / Assistant / Connecteurs / Agent) | ✅ stub UI | Assistant + Agent complets |
| Arbre projets code (sans assistant) | ✅ | — |
| Panneau MCP hors sidebar Code | ✅ onglet Connecteurs | UI gateway complète (pool) |
| Registre MCP unifié (Gateway = pool) | ✅ `gateway.db` + pool (3 amonts, 0 en erreur) | — |
| `.mcp.json` projet / assistant | ❌ | binding niveau 2 (voir MCP doc) |
| Overlay MCP conversation (composer `+`) | mécanisme en place (`mcp_overlay` par session, route `/sessions/{id}/mcp`) — usage non mesuré | vérifier à la revue Connecteurs |
| Onglet Agent (profils + pilote) | ✅ 4 agents en service, cron + relance | revue de la page à faire |
| Modal création projet | ✅ dépôt git à la création | + clone GitHub |
| Menu session ⋯ visible | ✅ | — |
| Tout dans `projects/default` | ✅ un slug par projet, chacun un dépôt git | — |
| `wikichat-memory` repo | ❌ et à dessein — mémoire de session | Règle de sync, pas un dépôt |
| Service Wikichat `:3777` | ⚠️ démarre (script réparé), non supervisé | Relancé avec l'Atelier |
| Auth GitHub service | ✅ jeton + `GIT_ASKPASS` | OAuth si plusieurs comptes |
| `kind` assistant / code | ✅ API + filtre UI | — |
| Noms de session hub | ⚠️ titres sync Claude | Titre fiable + overlay |
| Overlay consignes session | ❌ | Fichiers ou API |
| Sync `~/.wikichat` ↔ repo mémoire | ❌ jamais armé — `WIKICHAT_MEMORY_REPO` absent | dépôt dans le dossier assistant, `--no-push` d'abord |

### 11.1 Shell UI (implémenté)

- **Routes** : `/?view=code|assistant|connecteurs|agent` ; en vue Code, `slug` et `session` dans l’URL.
- **État** : `state.view` + catalogue partagé (`projects`, `sessions`, `mcpServers`) ; workspace Code (`slug`, `sessionId`, `messages`).
- **Filtrage** : arbre Code = `kind=code` uniquement ; `wikichat-memory` masqué côté UI (reste dans l’API).
- **Modules frontend** : `web/js/` — `views/`, `controllers/`, `services/` (voir `web/js/README.md`).

### 11.2 Responsive mobile (cible produit)

**Exigence** : l’hub Atelier doit être **pleinement utilisable sur mobile** (iOS / Android), au niveau d’expérience des apps Anthropic (Claude) et Cursor — pas seulement « zoomable desktop ».

**État actuel** : `viewport` OK ; une seule breakpoint `@media (max-width: 720px)` (sidebar au-dessus du chat, hauteur max 40vh). Le composer, la barre session, Connecteurs et Agent ne sont pas encore adaptés mobile-first.

**Cible UX (référence Anthropic / Cursor)**

| Zone | Desktop | Mobile |
|------|---------|--------|
| Navigation | Onglets Code / Assistant / Connecteurs / Agent | Barre fixe ou drawer ; session courante visible |
| Projets / sessions | Sidebar persistante | Drawer gauche (swipe ou bouton) ; arbre repliable |
| Fil conversation | Thread + barre session | Plein écran ; barre session compacte (titre + menu ⋯) |
| Composer | Textarea auto-grow + PJ + MCP + Envoyer | Zone fixe bas de écran ; boutons touch ≥ 44px ; `safe-area` iOS |
| Popover MCP | Au-dessus du composer | Sheet / bottom sheet ou modal plein largeur |
| Connecteurs | Panneau large | Liste scroll ; cartes empilées |
| VS Code | Lien secondaire | Lien ou action « Ouvrir sur desktop » |

**Breakpoints proposés**

- `≤ 480px` — téléphone (portrait)
- `481–720px` — téléphone large / petite tablette
- `721–1024px` — tablette
- `≥ 1025px` — desktop (layout actuel)

**Technique (sans bundler)**

- CSS : mobile-first overrides dans `app.css` ; variables `--composer-pad`, `--touch-min`
- JS : `matchMedia` pour fermer popovers au rotate ; option `state.mobileDrawer` (sidebar / session)
- Pas de dépendance framework ; tester Chrome DevTools + Safari iOS réel
- PWA optionnelle (phase ultérieure) : `manifest.json`, icône, `theme-color`

**Critères d’acceptation mobile**

1. Créer / ouvrir session, envoyer message (texte + PJ), toggle MCP, arrêter génération — **sans scroll horizontal**
2. Thread lisible (bulles, outils, markdown) ; code blocks scroll horizontal interne
3. Login owner clé utilisable (clavier ne masque pas Envoyer)
4. Connecteurs : liste + import JSON accessible (textarea plein écran si besoin)

**Phasage** : voir §13.3 (phase **R1** après stabilisation composer M5 / PJ).

---

## 12. Questions ouvertes — alignement dev Wikichat

Ces points nécessitent une **réponse explicite** de l’équipe Wikichat avant implémentation finale Atelier.

### 12.1 Chemins et miroir

- Comment lier `~/work/wikichat-memory/.wikichat` et `~/.wikichat/` ?
  - Symlink, bind mount, sync au boot, ou un seul chemin canonique ?
- Le MCP doit-il lire **les deux** ou uniquement le repo cloné ?

### 12.2 Ingestion projet → mémoire

- `close_project` : push direct sur `main` de `wikichat-memory` ou PR / merge contrôlé ?
- Gestion des conflits Git si deux projets closent en parallèle.
- Format attendu des fichiers ingérés dans `knowledge/`.

### 12.3 Service vs données

- Confirmation : **aucune** écriture agent dans le repo **code** Wikichat (`~/work/wikichat/src`).
- Permissions MCP recommandées pour sessions `kind=code` vs `assistant`.

### 12.4 Runtime

- Wikichat MCP doit tourner sur `:3777` (ou URL configurable) **au start** du stack Atelier.
- Health check et redémarrage dans `start-atelier-stack.sh`.

### 12.5 Registry projets

- `declare_project` / `list_projects` : clé projet = slug Atelier ?
- Lien `repo` GitHub dans les métadonnées projet Wikichat.

---

## 13. Phasage recommandé

### 13.1 Plateforme & Wikichat

| Phase | Contenu |
|-------|---------|
| **P0** | Ce document + [`atelier-mcp-unified.md`](./atelier-mcp-unified.md) + [`atelier-mcp-implementation-plan.md`](./atelier-mcp-implementation-plan.md) + validation dev Wikichat (§12) |
| **P1** | Auth GitHub + provision `wikichat-memory` + sync paths |
| **P2** | API `kind`, création projet, abandon `default` |
| **P3** | Titres session + overlay consignes + cwd assistant sous-dossier |
| **P4** | Branches agent, worktrees, sub-agents spawn |

### 13.2 MCP & hub (détail M1–M7)

| Phase | Contenu | Dépendances |
|-------|---------|-------------|
| **M1** | Gateway sur pod, migration `registry.json` → pool | — |
| **M2** | Onglet Connecteurs = admin pool (catalogue, perso, compositions) | M1 |
| **M3** | `.mcp.json` projet code + merge harness | M1 |
| **M4** | Assistant : sous-dossiers session + `.mcp.json` + cwd | P3, M1 |
| **M5** | Overlay conversation + composer `+` (niveau 3) | M3 ou M4 |
| **M6** | Profils gateway (données Agent) | M1, M2 |
| **M7** | Onglet Agent = pilote (cron, spawn, approbation) | M6, P4 |

Phasage croisé suggéré : **P0** → **M1** → **M2** + **M3** en parallèle → **P1–P3** + **M4** → **M5** → **M6** → **M7** + **P4**.

### 13.3 UI responsive (mobile)

| Phase | Contenu | Dépendances |
|-------|---------|-------------|
| **R1** | Composer mobile (safe-area, touch targets, popover sheet), thread scroll | M5 composer |
| **R2** | Sidebar drawer projets/sessions ; barre session compacte | R1 |
| **R3** | Connecteurs + Agent responsive ; polish tablette | M2, M7 |
| **R4** | Tests Safari iOS / Chrome Android ; PWA optionnelle | R1–R3 |

---

## 14. Coordination multi-agents

Pour cadrer avec l’agent dev Wikichat via Wikichat MCP :

1. Démarrer le service (`:3777`).
2. `register(name="Atelier-Architect", role="architecte")`
3. `add_project_note(project="wikichat", type="decision", content="…")` — pointer vers ce document.
4. `add_project_note(project="atelier", …)`
5. `send_message(channel="@Wikichat-Dev", expects_reply=true, …)` — questions §12.

---

## 15. Références

- MCP unifié : [`atelier-mcp-unified.md`](./atelier-mcp-unified.md).
- Plan implémentation : [`atelier-mcp-implementation-plan.md`](./atelier-mcp-implementation-plan.md).
- Skill Wikichat : `search_knowledge`, `close_project`, chemins `~/.wikichat/` et `<projet>/.wikichat/`.
- Atelier pod : `~/work/atelier-src/mcp_gateway/atelier/`.
- Passerelle amont : `<passerelle-amont>/src/mcp_gateway/`.
- Handoff VS Code : `~/work/bin/atelier-vscode-handoff.sh`, `vscode_handoff.py`.
- Hub : `https://<user>-atelier.user.lab.sspcloud.fr/`.

---

*Dernière mise à jour : alignement MCP unifié (Gateway = pool), bindings `.mcp.json`, phasage M1–M7.*
