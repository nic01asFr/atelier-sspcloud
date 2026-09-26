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
| `assistant` | Le fil de l'Assistant, dans l'écran des conversations (`views/assistant.js`, `state.espace`) ; cartes d'action « Voir », « Annuler », « Oui » (`views/assistant-cartes.js`) |
| `connecteurs` | Admin pool MCP (niveau 1 — catalogue, perso, compositions) |
| `agent` | Tout ce qui agit seul : agents planifiés (pilote), gardiens (`views/gardiens.js`), tâches automatiques |
| `a-valider` | La file unique « À valider » (`views/a-valider.js`, `controllers/validation.js`) ; badge dans la navigation |
| `journal` | Le journal unique en phrases, filtres projet, acteur, source (`views/journal.js`) |

## MCP (trois niveaux)

| Niveau | UI | Persistance |
|--------|-----|-------------|
| 1 — Pool | onglet Connecteurs | `~/work/mcp/` (gateway) |
| 2 — Binding | `.mcp.json` projet ou sous-dossier assistant | fichiers git / repo mémoire |
| 3 — Conversation | composer `+` (Code / Assistant) | `mcp_overlay` session (API, pas git) |

Références : `docs/archives/mcp/atelier-mcp-unified.md`, `docs/archives/mcp/atelier-wikichat-alignment.md` (§11.2 mobile).

## Responsive mobile

La bascule liste ↔ détail est en place, contrairement à ce que ce fichier
annonçait. Vérifié à 501 px : la vue prend `shell-mode-detail`, la barre
latérale se replie à zéro, le panneau principal occupe toute la largeur, sans
débordement horizontal ; le bouton « ← Liste » ramène en `shell-mode-list`, où
c'est l'inverse.

Reste desktop-first : le composeur, les popovers et les onglets
d'administration. Cible d'ensemble : `docs/archives/mcp/atelier-wikichat-alignment.md`
§11.2 et §13.3.

**PJ** : upload → `cwd/.atelier/uploads/` ; le message harness utilise la syntaxe native Claude Code `@chemin/relatif` (pas d’inline custom).
