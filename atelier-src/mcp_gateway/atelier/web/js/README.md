# Atelier Hub — frontend JS

Structure modulaire (ES modules, sans bundler).

```
js/
  app.js                 # bootstrap, wiring
  api.js                 # HTTP / SSE
  state.js               # état pur + helpers kind/view
  core/
    dom.js               # $, showBanner
    router.js            # ?view=&slug=&session=
  ui/
    context-menu.js
    modal.js
  services/
    catalog.js           # refresh projects/sessions/mcp
    vscode.js            # handoff VS Code
  views/
    shell.js             # login/hub, onglets, dispatch
    code-tree.js         # arbre projets code
    code-chat.js         # thread + composer + barre session
    connectors.js        # liste MCP
    agent.js             # profils gateway (M6/M7)
  controllers/
    auth.js
    projects.js
    sessions.js
    chat.js
    connectors.js
    agent.js
```

## Vues shell

| `?view=` | Rôle |
|----------|------|
| `code` (défaut) | Projets `kind=code`, chat Claude Code |
| `assistant` | Stub — mémoire `wikichat-memory` |
| `connecteurs` | Admin pool MCP (niveau 1 — catalogue, perso, compositions) |
| `agent` | Profils gateway + agents planifiés (pilote) |

## MCP (trois niveaux)

| Niveau | UI | Persistance |
|--------|-----|-------------|
| 1 — Pool | onglet Connecteurs | `~/work/mcp/` (gateway) |
| 2 — Binding | `.mcp.json` projet ou sous-dossier assistant | fichiers git / repo mémoire |
| 3 — Conversation | composer `+` (Code / Assistant) | `mcp_overlay` session (API, pas git) |

Références : `docs/atelier-mcp-unified.md`, `docs/atelier-wikichat-alignment.md` (§11.2 mobile).

## Responsive mobile (à venir — R1–R4)

Cible : expérience type apps Anthropic / Cursor sur téléphone. Voir `docs/atelier-wikichat-alignment.md` §11.2 et §13.3.

Implémentation actuelle : breakpoint `720px` (sidebar empilée). Composer / popovers / onglets admin : desktop-first.

**PJ** : upload → `cwd/.atelier/uploads/` ; le message harness utilise la syntaxe native Claude Code `@chemin/relatif` (pas d’inline custom).
