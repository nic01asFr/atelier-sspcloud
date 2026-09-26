# Atelier — Registre MCP unifié (Gateway = Pool)

Document de référence pour la **fusion de la passerelle et du pool MCP sur le pod**, les **quatre onglets** du hub (Code / Assistant / Connecteurs / Agent), et la **configuration MCP en trois niveaux**.

**Statut** : cadrage validé — implémentation partielle (voir § État actuel).

**Documents liés** : [`atelier-wikichat-alignment.md`](./atelier-wikichat-alignment.md) (workspaces, Wikichat, VS Code, phasage global).

**Implémentation (avant code)** : [`atelier-mcp-implementation-plan.md`](./atelier-mcp-implementation-plan.md) — décisions M1, périmètres IN/OUT, critères d’acceptation.

**Code** : `atelier-src/mcp_gateway/atelier/` + stack de la passerelle amont (`<passerelle-amont>/src/mcp_gateway/`).

---

## 1. Vision

Un **seul runtime MCP** sur le pod (`~/work/mcp/`) :

- **Catalogue** services org (`catalog.yaml`)
- **Registry perso** (SQLite) — connecteurs user (stdio, SSE, HTTP)
- **Pool upstream** (`UpstreamPool`) — connexions actives + health
- **Compositions** — workflows multi-outils exposés comme outils gateway
- **Méta-outils gateway** — `gateway_find_tools`, `gateway_use_profile`, …
- **Profils** — assemblages (serveurs + tools + consignes) pour l’onglet **Agent**

L’onglet **Connecteurs** administre ce pool. Les **fichiers `.mcp.json`** et l’**overlay conversation** ne redéfinissent pas le pool : ils **sélectionnent** et **activent** des entrées déjà disponibles.

---

## 2. Architecture runtime

```
Navigateur → Atelier Hub (:8787) — **gateway intégré** (un processus)
    ├── Code / Assistant     → harness Claude (--mcp-config effectif)
    ├── Connecteurs          → admin pool (modules gateway dans le hub)
    └── Agent                → profils gateway + instances planifiées (pilote)

~/work/mcp/  (Gateway sur pod)
├── catalog.yaml
├── gateway.db              # registry perso, profils, compositions
├── tools/                  # binaires stdio (filesystem, …)
├── effective/              # projection harness (merge binding + overlay)
│   └── <session_id>.json
└── (registry.json / claude-mcp.json → dépréciés, migration S1)
```

Wikichat (`:3777`) = **connecteur registry normal** (coordination, knowledge), pas le registre central.

---

## 3. Trois niveaux de configuration MCP

| Niveau | Où | Écrit quoi ? | Rôle |
|--------|-----|--------------|------|
| **1 — Pool** | Gateway / onglet **Connecteurs** | Définitions | Services org, connecteurs perso, compositions, personnalisation tools (prefix, allowlist, exposure) |
| **2 — Binding persistant** | Fichiers `.mcp.json` (format Claude Code natif) | Sélection durable | Quels connecteurs du pool le projet ou l’env session assistant peut utiliser |
| **3 — Conversation** | Composer `+` + overlay session (API, pas git) | **Visibilité / activation seule** | On/off pour **ce fil** ; ne crée pas de connecteurs, ne modifie pas le pool ni les profils Agent |

**Harness** : merge niveau 2 ∩ niveau 3 → `effective/<session_id>.json` pour `--strict-mcp-config`.

Le niveau 3 correspond au composant connecteurs de Claude Desktop : rattacher / détacher pour la conversation courante sans réécrire la config globale.

---

## 4. Bindings par kind de workspace

### 4.1 Projet code (`kind=code`)

| Élément | Règle |
|---------|--------|
| **cwd harness** | `projects/<slug>/` (racine repo) |
| **Binding persistant** | **Un seul** `.mcp.json` à la racine — **toutes les sessions partagent** |
| **Overlay conversation** | Toggles composer (niveau 3) — variations par fil sans toucher le fichier projet |
| **Git** | `.mcp.json` projet versionné avec le repo |

```
projects/hextokenizer/
├── .mcp.json          # binding projet (niveau 2)
├── CLAUDE.md
├── .claude/
└── src/…
```

### 4.2 Assistant (`kind=assistant`)

| Élément | Règle |
|---------|--------|
| **« Projet » assistant** | `wikichat-memory/` (repo mémoire user) |
| **Session = sous-dossier** | `assistant/sessions/<uuid>/` (env session) |
| **cwd harness** | Sous-dossier session |
| **Binding persistant** | `.mcp.json` racine assistant **+** `.mcp.json` sous-dossier session |
| **Overlay conversation** | Composer `+` si besoin au-delà des fichiers |

```
wikichat-memory/
├── .mcp.json                    # binding assistant global (niveau 2)
├── CONSIGNES.md
├── .wikichat/
└── assistant/sessions/<uuid>/
    ├── .mcp.json                # binding session (niveau 2)
    └── (overlay consignes)
```

Découverte native Claude Code : remontée depuis `cwd` ; le harness peut aussi matérialiser le merge pour `--strict-mcp-config`.

---

## 5. Mapping des quatre onglets

| Onglet | Périmètre | Niveaux MCP |
|--------|----------|-------------|
| **Code** | Chat agent code, VS Code | Niveau 2 (`.mcp.json` projet) + niveau 3 (composer) |
| **Assistant** | Chat suivi user | Niveau 2 (fichiers) + niveau 3 |
| **Connecteurs** | Admin pool | **Niveau 1** seul |
| **Agent** | Agents planifiés, approbation | **Profils gateway** (pas niveau 3 conversation) |

**Menu `+` du composer** (Code / Assistant) : connecteurs **effectifs** de la conversation (niveau 3), badges health, lien « Gérer dans Connecteurs ».

**Ne pas confondre** : Connecteurs = catalogue pool · Composer `+` = activation conversation.

---

## 6. Profils gateway ↔ onglet Agent

Un **profil** (`ResolvedProfile`) = définition d’**agent autonome** :

- `org_servers`, `registry_servers` (connecteurs du pool)
- `meta_tools`, compositions activées
- `tool_allowlist`, `mcp_instructions`, `tool_exposure`

L’onglet **Agent** = **instances** liées à un profil :

- cron / fire / pause (runtime pilote Wikichat `/pilote`, migré progressivement)
- spawn headless via harness + profil matérialisé
- file d’approbation (`proposed-actions.json`)
- mode proposeur (lecture seule) vs applicateur (écriture)

Les profils **réutilisent** les connecteurs configurés dans Connecteurs — une seule source de vérité (pool).

---

## 7. API cible

### Pool / Connecteurs

```
GET    /v1/mcp/catalog
GET    /v1/mcp/registry
POST   /v1/mcp/registry
GET    /v1/mcp/compositions
POST   /v1/mcp/compositions
GET    /v1/mcp/pool/status
POST   /v1/mcp/import
POST   /v1/mcp/sync
```

### Conversation (niveau 3)

```
GET    /v1/sessions/{id}/mcp     # effectif = binding ∩ overlay
PATCH  /v1/sessions/{id}/mcp     # overlay activation (pas définitions)
```

### Agent

```
GET    /v1/agents/profiles
POST   /v1/agents/profiles
GET    /v1/agents/instances
POST   /v1/agents/instances
GET    /v1/agents/proposed-actions
POST   /v1/agents/proposed-actions/{id}/decide
```

---

## 8. Sécurité

- **Plafond MCP** (`mcp_ceiling` catalogue) : session chat ne peut pas élargir au-delà.
- **Profils Agent** headless : peuvent être plus larges avec owner key (comme pilote aujourd’hui).
- **Mode proposeur** : `tool_allowlist` lecture seule ; applicateur séparé.
- **`--strict-mcp-config`** sur l’effectif matérialisé : pas d’héritage implicite non mergé.

---

## 9. État actuel vs cible

| Élément | Actuel | Cible |
|---------|--------|-------|
| Registre | ✅ `gateway.db` intégré dans hub `:8787` | Gateway SQLite + pool sur pod |
| Harness MCP | ✅ merge projet + overlay, recalculé à chaque message | Merge projet + overlay → `effective/<id>.json` |
| Connecteurs UI | ✅ familles, socle non cochable, compositions | UI gateway complète |
| Composer `+` MCP | ✅ overlay par conversation | overlay conversation (niveau 3) |
| `.mcp.json` projet code | ✅ écrit et pris en compte | binding partagé sessions |
| Assistant cwd | ✅ sous-dossier session ; les anciennes fiches migrent au tour suivant, journal compris | sous-dossier session |
| Agent onglet | ✅ agents systèmes et personnels, discussion, sélection d'outils | profils + pilote |
| Wikichat `/pilote` | pilote déployé avec le service, `/pilote` encore en place | migré vers onglet Agent |
| Passage de main VS Code | ✅ dans les deux sens, voir [`atelier-vscode-passage-de-main.md`](../../atelier-vscode-passage-de-main.md) | — |

---

## 10. Phasage MCP (intégré au plan global)

| Phase | Contenu | Livrable |
|-------|---------|----------|
| **M1** | Gateway sur pod remplace `registry.json` | pool up, migration SQLite |
| **M2** | UI Connecteurs = gateway (catalogue, perso, compositions, health) | onglet fonctionnel |
| **M3** | `.mcp.json` projet code + merge harness | binding persistant code |
| **M4** | Assistant : sous-dossiers session + `.mcp.json` + cwd | binding assistant |
| **M5** | API + UI overlay conversation (composer `+`) | niveau 3 |
| **M6** | Profils gateway exposés | données Agent |
| **M7** | Onglet Agent = pilote (cron, spawn, approbation) | remplace `/pilote` |

Voir phasage croisé dans [`atelier-wikichat-alignment.md`](./atelier-wikichat-alignment.md) § 13.

Détail opérationnel (IN/OUT, critères M1, décisions processus) : [`atelier-mcp-implementation-plan.md`](./atelier-mcp-implementation-plan.md).

---

## 11. Wikichat après fusion

| Composant | Rôle |
|-----------|------|
| Wikichat MCP `:3777` | Connecteur pool (coordination, knowledge) |
| `/pilote` | Déprécié → onglet Agent Atelier |
| `wikichat-memory` | Repo assistant ; pas le registre MCP |

---

*Dernière mise à jour : état repris après la mise en service du passage de main VS Code — conversations alignées dans les deux sens, journaux de conversation allégés, sous-dossiers assistant.*
