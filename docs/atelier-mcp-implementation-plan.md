# Atelier MCP — Cadrage d’implémentation (avant M1)

Document **opérationnel** : décisions à figer, périmètre exact de chaque phase, critères d’acceptation, hors-scope. À lire **avant** toute PR M1.

**Specs produit** : [`atelier-mcp-unified.md`](./atelier-mcp-unified.md) (architecture, trois niveaux MCP).

**Alignement Wikichat / workspaces** : [`atelier-wikichat-alignment.md`](./atelier-wikichat-alignment.md).

**Code gateway** : repo `Gateway_cerema` (`src/mcp_gateway/`). **Hub Atelier** : `atelier-src/mcp_gateway/atelier/` (slice partielle — voir §2).

---

## 1. Objectif de ce document

Éviter de « commencer M1 » sans trancher :

- où vit le code ;
- quel processus tourne sur le pod ;
- comment on migre `registry.json` ;
- quelle clé owner ;
- ce que M1 **ne fait pas** (UI Connecteurs complète, harness merge, Agent, etc.).

---

## 2. État du code (audit 2026-08)

| Zone | Emplacement | État |
|------|-------------|------|
| Hub Atelier (API, harness, UI shell) | `Claude Code sspcloud/atelier-src/` | Partiel — **pas** `mcp_registry.py`, `mcp_sync.py` sur disque local (déployés sur pod via tarball) |
| Package complet `mcp_gateway` | `Gateway_cerema/src/mcp_gateway/` | Gateway + pool + compositions + profils + **atelier** |
| Registre actuel pod | `~/work/mcp/registry.json` + `claude-mcp.json` | Flat JSON, materialize global |
| Harness | `materialize_mcp_config()` → `--strict-mcp-config` | Ignore `.mcp.json` projet |
| API MCP hub | `/v1/mcp/servers` (McpRegistry JSON) | Pas gateway API |
| Passerelle plateforme | `passerelle-mcp.user.lab…` | Déploiement Helm séparé — **pas** le registre pod cible |

**Décision figée (D10)** : **intégration** du code gateway dans le stack Atelier — on ne déploie pas Gateway Cerema « tel quel » (pas de second service Helm, pas de clone `gateway-src` sur le pod, pas de proxy vers une passerelle distante comme registre user).

---

## 3. Décisions d’architecture à figer avant M1

### 3.1 Registre central = Gateway sur le pod

| ID | Décision | Recommandation |
|----|----------|----------------|
| D1 | Une seule source de vérité connecteurs | `~/work/mcp/gateway.db` + `catalog.yaml` |
| D2 | `registry.json` | Migré puis **lecture seule** / supprimé après M1 |
| D3 | `claude-mcp.json` global | Remplacé par `effective/<session_id>.json` (M3+) ; bridge temporaire en M1 si besoin |
| D4 | Passerelle plateforme | Catalogue org **importé** ou monté — pas second registre user |
| D10 | **Intégration vs déploiement** | **Intégrer** le module gateway dans Atelier ; **ne pas** récupérer le chart / `main.py` standalone sur le pod |

### 3.2 Intégration code (pas « tel quel »)

**On fait** :

- Merger / vendre le package `mcp_gateway` (pool, catalog, compositions, profils) **dans** `atelier-src/` — source amont : repo `Gateway_cerema`, adapté au contexte pod Atelier.
- Un seul processus **uvicorn** `:8787` : `build_app()` initialise le **lifespan gateway** (DB, catalog, pool, compositions) + routes hub + routes MCP API + endpoint `/mcp` SSE si requis en loopback.
- Routes API unifiées sous le hub (ex. `/v1/mcp/*` = handlers gateway, pas proxy HTTP externe).
- Widget Connecteurs : assets gateway intégrés sous `/connecteurs/…` ou réutilisation progressive du widget Cerema **rebrandé** Atelier.

**On ne fait pas** :

- Clone `~/work/gateway-src` + second `uvicorn mcp_gateway.main`.
- Helm chart `mcp-gateway` dédié sur le pod studio.
- Proxy Atelier → `127.0.0.1:8790` ou → passerelle plateforme pour le registre user.
- Deux clés owner, deux journaux ops, deux healthchecks.

**Périmètre d’adaptation lors de l’intégration** (le code n’est pas copié sans filtre) :

- Chemins PVC : `ATELIER_WORK/mcp/` pour `db` + `catalog.yaml`.
- Auth : une seule couche `OwnerAuth` Atelier ; pas de middleware gateway dupliqué.
- UI Cerema standalone / routes widget publiques hors hub : retirées ou remplacées par onglets Atelier.
- `main.py` gateway standalone : **non utilisé** sur le pod — logique reprise dans `atelier/app.py` + module `gateway_runtime.py` (lifespan partagé).

### 3.3 Modèle de processus sur le pod

**Décision figée : option A — intégré, un port.**

```
Ingress public → 127.0.0.1:8787 (Atelier + gateway intégré)
                 ├── /v1/sessions, /v1/projects, …  (hub)
                 ├── /v1/mcp/*, /api/v1/*            (gateway API — chemins à harmoniser M1)
                 ├── /mcp                            (SSE MCP gateway, loopback / owner)
                 └── /connecteurs/widget/…           (M2)
```

Variables (exemple) :

```bash
ATELIER_WORK=/home/onyxia/work
GATEWAY_DB_PATH=/home/onyxia/work/mcp/gateway.db
GATEWAY_CATALOG_PATH=/home/onyxia/work/mcp/catalog.yaml
GATEWAY_OWNER_LOCK=1
# GATEWAY_OWNER_KEY = contenu de atelier_owner_key (même fichier)
```

### 3.4 Authentification

| ID | Décision | Recommandation |
|----|----------|----------------|
| D5 | Clé owner | **Une clé** : `~/work/.secrets/atelier_owner_key` |
| D6 | API gateway intégrée | Même `require_owner` que le hub — pas second middleware |
| D7 | Claude → upstreams | Inchangé (credentials SQLite registry) |

Ne pas maintenir deux clés propriétaire.

### 3.5 Trois niveaux MCP (rappel — pas tout en M1)

| Niveau | Implémentation | Phase |
|--------|----------------|-------|
| 1 Pool | Gateway DB + pool + API | **M1** (runtime) + **M2** (UI) |
| 2 Binding `.mcp.json` | Fichiers projet / assistant | **M3**, **M4** |
| 3 Conversation | `mcp_overlay` + composer `+` | **M5** |

### 3.6 Profils Agent vs session chat

| ID | Décision |
|----|----------|
| D8 | Profils gateway = onglet **Agent** uniquement (M6–M7) |
| D9 | Niveau 3 conversation = activation seule, pas profils |

---

## 4. Arborescence PVC cible (référence)

```
~/work/mcp/
├── catalog.yaml              # services org (seed + sync GitLab optionnel)
├── gateway.db                # registry perso, profils, compositions, credentials
├── tools/                    # stdio (node_modules filesystem, …)
├── effective/                # M3+ : merge binding + overlay
│   └── <session_id>.json
├── registry.json             # M1 migration input → deprecated
└── claude-mcp.json           # deprecated après M3

~/work/bin/
└── start-atelier-stack.sh    # un seul uvicorn Atelier (gateway intégré)
```

---

## 5. Périmètre par phase (IN / OUT)

### M1 — Runtime Gateway + migration registre

**IN**

- [ ] Package `mcp_gateway` intégré dans `atelier-src/` (merge depuis `Gateway_cerema`, adapté)
- [ ] `build_app()` : lifespan gateway (DB, catalog, pool, compositions) dans le même process `:8787`
- [ ] `catalog.yaml` seed minimal (wikichat local, filesystem stdio)
- [ ] Migration `registry.json` → `gateway.db` (`import_registry`)
- [ ] Script `wikichat_ensure` aligné : upsert SQLite, pas JSON flat
- [ ] Routes `/v1/mcp/*` servies par modules gateway intégrés (plus `McpRegistry` JSON local)
- [ ] Pool startup + status exposé via API hub
- [ ] Health stack : un process, un log `atelier-uvicorn.log`
- [ ] Doc ops : variables PVC, pas de second service

**OUT (explicitement pas M1)**

- UI Connecteurs gateway complète (M2)
- Widget compositions (M2)
- Merge harness `.mcp.json` / `effective/` (M3)
- `mcp_overlay` session (M5)
- Onglet Agent (M6–M7)
- Déploiement Gateway Cerema standalone / chart Helm sur pod
- Import catalogue org depuis passerelle distante automatique

**Critères d’acceptation M1**

1. `curl -H "Authorization: Bearer $KEY" http://127.0.0.1:8787/v1/mcp/...` → registry list OK (gateway intégré)
2. Entrées migrées depuis `registry.json` présentes et `enabled` cohérent
3. Pool status : wikichat + filesystem ≠ `error` (ou erreur documentée avec cause)
4. Un seul processus `python -m mcp_gateway.atelier.app` — pas de second uvicorn gateway
5. Harness **encore fonctionnel** (bridge materialize depuis export gateway intégré)
6. Redémarrage pod : stack script remonte hub + pool sans étape gateway séparée

### M2 — UI Connecteurs (niveau 1)

**IN** : widget gateway / compositions, catalogue, perso, health, import MCP.

**OUT** : bindings fichier, composer `+`, Agent.

### M3 — Binding code `.mcp.json`

**IN** : `projects/<slug>/.mcp.json`, merge → `effective/<id>.json`, harness strict.

**OUT** : assistant sous-dossiers, overlay conversation.

### M4 — Binding assistant

**IN** : `wikichat-memory/.mcp.json` + `assistant/sessions/<uuid>/`, cwd sous-dossier.

**OUT** : overlay conversation.

### M5 — Niveau 3 conversation

**IN** : `mcp_overlay` sur session, `PATCH /sessions/{id}/mcp`, composer `+`.

**OUT** : profils Agent.

### M6 — Profils (données)

**IN** : API profils exposée, CRUD custom profiles, lien connecteurs pool.

**OUT** : cron pilote.

### M7 — Onglet Agent

**IN** : instances planifiées, approbation, migration `/pilote`.

---

## 6. Migration `registry.json` → `gateway.db`

**Script** `~/work/mcp/migrate_registry_to_gateway.py` (ou commande gateway) :

1. Lire `registry.json` si présent
2. Pour chaque entrée : `upsert_registry_server` (transport, url/command, enabled)
3. Écrire `registry.json.migrated` (backup horodaté)
4. Ne pas supprimer backup tant que M3 non validé

**Mapping champs** :

| `registry.json` | Gateway SQLite |
|-----------------|----------------|
| clé serveur | `server_id` |
| `enabled` | `server_enable` registry scope |
| `command`/`args`/`env` | registry stdio |
| `url`/`type`/`headers` | registry SSE/HTTP |

**Wikichat** : une entrée canonique (`http://127.0.0.1:3777/sse` ou `localhost` — **trancher une URL** dans seed catalog/registry).

---

## 7. Couche API Atelier (compatibilité)

Phase M1 : routes hub **réimplémentées** par handlers gateway intégrés (même process, pas proxy HTTP).

| Route hub actuelle | Cible M1 |
|--------------------|----------|
| `GET /v1/mcp/servers` | `list_registry_servers` + masquage secrets |
| `PUT/PATCH/DELETE /v1/mcp/servers/{name}` | registry SQLite |
| `POST /v1/mcp/import` | `import_registry` |
| `POST /v1/mcp/sync` | pool reprobe |

Routes gateway (`compositions`, `profiles`, …) : montées sous `/v1/mcp/…` ou `/api/v1/…` selon harmonisation M1 ; pas de second serveur.

---

## 8. Harness — stratégie de transition

| Phase | Comportement |
|-------|--------------|
| **M1** | Bridge : `materialize_mcp_config()` lit export enabled depuis **pool intégré** (appel direct, pas HTTP) → `claude-mcp.json` temporaire ; log deprecation |
| **M3** | `materialize_session_mcp(session)` → `effective/<id>.json` depuis `.mcp.json` projet ∩ overlay |
| **M5** | Merge overlay conversation dans materialize |

Ne pas couper harness en M1 sans bridge.

---

## 9. Déploiement & repos

| Action | Repo | Cible pod |
|--------|------|-----------|
| Package `mcp_gateway` intégré | `Claude Code sspcloud/atelier-src/` (merge `Gateway_cerema`) | `~/work/atelier-src/` |
| Deploy | `deploy-patches/deploy_shell_ui.py` | tarball + restart **un** process |

**M1 livrable deploy** : tarball inclut gateway intégré + `catalog.yaml` seed + migration one-shot — **pas** second service.

---

## 10. Risques & mitigations

| Risque | Mitigation |
|--------|------------|
| Merge gateway complexe (lifespan) | Module `gateway_runtime.py` isolé ; tests FakeHarness + pool mock |
| Divergence amont `Gateway_cerema` | Porter fixes dans atelier-src ; cherry-pick documenté |
| Harness cassé pendant migration | Bridge materialize M1 |
| Catalogue org vide | `catalog.yaml` seed minimal pod-local |
| Wikichat down | Pool status visible ; harness sans wikichat si disabled |

---

## 11. Questions ouvertes (à trancher avant merge M1)

| # | Question | Statut |
|---|----------|--------|
| Q1 | URL canonique wikichat | **Proposition** : `http://127.0.0.1:3777/sse` |
| Q2 | `catalog.yaml` source | Seed dans `atelier-src/mcp/` + sync GitLab ultérieur |
| Q3 | Intégration vs standalone | **Figé** : intégration dans Atelier (D10) |
| Q4 | Endpoint `/mcp` SSE gateway | Intégré loopback `:8787/mcp` — owner lock |
| Q5 | Extension VS Code MCP | Resync depuis export pool intégré (M1 bridge) |

---

## 12. Ordre d’exécution M1 (checklist dev)

1. Trancher Q1 (URL wikichat)
2. Merger modules gateway dans `atelier-src/mcp_gateway/` depuis `Gateway_cerema`
3. `gateway_runtime.py` + lifespan dans `build_app()`
4. Seed `catalog.yaml` + migration `registry.json`
5. Remplacer `McpRegistry` JSON par handlers SQLite dans `api.py`
6. `mcp_sync.py` : bridge export pool intégré
7. Deploy patch + test pod (un uvicorn)
8. Mettre à jour § État dans `atelier-mcp-unified.md`

---

## 13. Definition of Done — programme MCP complet

- [ ] M1–M7 critères acceptation passés sur pod `proj-claude-code`
- [ ] Docs alignées (ce fichier + unified + alignment)
- [ ] `registry.json` / `claude-mcp.json` global supprimés ou deprecated avec warning
- [ ] Wikichat `/pilote` redirigé ou documenté deprecated
- [ ] Extension VS Code + harness + hub utilisent même export pool

---

*Dernière mise à jour : intégration gateway dans Atelier (D10), un processus :8787 — pas déploiement tel quel.*
