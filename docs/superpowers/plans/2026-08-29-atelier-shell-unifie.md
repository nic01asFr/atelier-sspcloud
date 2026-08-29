# Shell unifié Atelier — Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Unifier Code / Assistant / Connecteurs / Agent sur le shell sidebar+main, avec discussion réutilisable, mobile liste↔détail, et Agent (accueil + onglets Discussion|À valider|Réglages).

**Architecture:** CSS/HTML `.view-shell` partagé ; état `shellMode` list|detail par vue ; backends inchangés (pilote/gateway via API Atelier). Discussion = composer/thread existants réutilisés.

**Tech Stack:** Atelier web (vanilla JS modules), FastAPI routes existantes, CSS `app.css`.

**Spec:** `docs/superpowers/specs/2026-08-29-atelier-shell-unifie-design.md`

## Global Constraints

- Pas de recode backend pilote/gateway.
- Compositions = tools d’un service, pas entrées sidebar séparées.
- Création agent : projet Code optionnel ; sinon espace par défaut implicite (pas de mention « Général »).
- Mobile &lt; 720 px : un panneau à la fois (list ↔ detail).
- Messagerie/webmessage : stub Réglages seulement.
- Réponses UI en français, jargon en secondaire.

## File map

| Fichier | Rôle |
|---------|------|
| `atelier/.../web/css/app.css` | `.view-shell`, mobile list/detail, Agent tabs |
| `atelier/.../web/index.html` | Structure shell Agent/Connecteurs/Assistant |
| `atelier/.../web/js/state.js` | `shellMode`, `selectedAgentId`, `selectedConnectorId`, pins |
| `atelier/.../web/js/core/router.js` | Query `agent`, `connector` |
| `atelier/.../web/js/views/shell.js` | Dispatch + mobile mode |
| `atelier/.../web/js/views/agent.js` | Accueil, onglets, détail |
| `atelier/.../web/js/controllers/agent.js` | Actions + create modal projets |
| `atelier/.../web/js/views/connectors.js` | Sidebar groupes + fiche |
| `atelier/.../web/js/controllers/connectors.js` | Select connector |
| `atelier/.../web/js/views/assistant.js` | Liste sessions + chat |
| `atelier/.../web/js/app.js` | Wiring |
| `atelier/.../api.py` | Si besoin overview file globale (agrégat) |

---

## Task 1 — Shell CSS + mobile list↔detail (Code + Agent)

**Files:** `app.css`, `index.html`, `state.js`, `shell.js`, `app.js`

- [ ] Ajouter classes `.view-shell`, `.shell-sidebar`, `.shell-main` ; faire `.view-code` / `.view-agent` hériter.
- [ ] État `shellModeByView: { code, agent, ... }` + helpers `setShellMode` / `getShellMode`.
- [ ] Sous 720 px : masquer sidebar en mode detail, masquer main en mode list ; bouton Retour/Liste dans main.
- [ ] Code : sélection session → `detail` ; Retour → `list` ; sans session → `list`.
- [ ] Agent : même bascule ; vérifier viewport 390px (plus de main ~120px).
- [ ] Déployer + smoke Chrome mobile emulate.

**Done when:** Code et Agent basculent correctement sous 720 px.

---

## Task 2 — Agent accueil + onglets + création projets/Général

**Files:** `index.html`, `views/agent.js`, `controllers/agent.js`, `api.js` si besoin, `pilote_overview.py` (file globale)

- [ ] Accueil (pas de sélection) : guide + daemon + file globale (pending tous agents).
- [ ] Détail : onglets Discussion | À valider | Réglages avec badges.
- [ ] Onglet À valider = file de l’agent ; Réglages = périmètre/cron/profil/actions + stub canaux.
- [ ] Modal création : select projets Code + option Général (résoudre cwd via meta/projects).
- [ ] Copy humaine (statuts, cron text).
- [ ] Deploy + test Chrome.

**Done when:** Accueil guidé OK ; création sans chemin libre ; onglets visibles.

---

## Task 3 — Agent Discussion (MVP)

**Files:** `views/agent.js`, `controllers/agent.js`, `api.py` éventuel

- [ ] Onglet Discussion : réutiliser patterns thread/composer (même skin).
- [ ] Branchement backend minimal : session liée agent OU message vers pilote si déjà dispo ; sinon stub clair « bientôt » avec UI complète mais envoi désactivé + note.
- [ ] Prefer real path if harness session per agent is quick ; sinon stub UI-only pour ne pas bloquer Tasks 4–5.

**Done when:** UI Discussion présente ; envoi réel ou stub explicite.

---

## Task 4 — Connecteurs shell + fiche service

**Files:** `index.html`, `views/connectors.js`, `controllers/connectors.js`, `app.css`

- [ ] Layout `.view-shell` : sidebar Plateforme / Mes connecteurs collapsibles.
- [ ] Main = fiche service sélectionné (tools list) ; compositions = tools du service dédié.
- [ ] Import / re-probe en bandeau, pas page pleine.
- [ ] Mobile list↔detail.
- [ ] Deploy + test.

**Done when:** Connecteurs suit le shell Code ; détail tools lisible.

---

## Task 5 — Assistant shell + sessions + épinglés

**Files:** `index.html`, `views/assistant.js`, `controllers/assistant.js`, `state.js`, `app.js`

- [ ] Remplacer placeholder par shell : sidebar sessions assistant + épinglés (localStorage).
- [ ] Main = chat session (réutiliser code-chat patterns / kind assistant).
- [ ] Mobile list↔detail.
- [ ] Deploy + test.

**Done when:** Assistant liste sessions et ouvre un chat.

---

## Execution note

Après chaque task : deploy `deploy_gateway_m1.py` + smoke Chrome. Commits seulement si l’utilisateur le demande.
