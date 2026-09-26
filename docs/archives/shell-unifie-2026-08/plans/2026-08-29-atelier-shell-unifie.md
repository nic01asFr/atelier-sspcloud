# Shell unifié Atelier — Implementation Plan

> **For agentic workers:** Implement task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Unifier Code / Assistant / Connecteurs / Agent sur le shell sidebar+main, avec discussion réutilisable, mobile liste↔détail, et Agent (accueil + onglets Discussion|À valider|Réglages).

**Architecture:** CSS/HTML `.view-shell` partagé ; état `shellMode` list|detail par vue ; backends inchangés (pilote/gateway via API Atelier). Discussion = composer/thread existants réutilisés.

**Tech Stack:** Atelier web (vanilla JS modules), FastAPI routes existantes, CSS `app.css`.

**Spec:** `docs/archives/shell-unifie-2026-08/specs/2026-08-29-atelier-shell-unifie-design.md`

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

- [x] Ajouter classes `.view-shell`, `.shell-sidebar`, `.shell-main` ; faire `.view-code` / `.view-agent` hériter.
- [x] État `shellModeByView: { code, agent, ... }` + helpers `setShellMode` / `getShellMode`.
- [x] Sous 720 px : masquer sidebar en mode detail, masquer main en mode list ; bouton Retour/Liste dans main.
- [x] Code : sélection session → `detail` ; Retour → `list` ; sans session → `list`.
- [x] Agent : même bascule ; vérifier viewport 390px (plus de main ~120px).
- [x] Déployer + smoke Chrome mobile emulate.

**Done when:** Code et Agent basculent correctement sous 720 px.

---

## Task 2 — Agent accueil + onglets + création projets/Général

**Files:** `index.html`, `views/agent.js`, `controllers/agent.js`, `api.js` si besoin, `pilote_overview.py` (file globale)

- [x] Accueil (pas de sélection) : guide + daemon + file globale (pending tous agents).
- [x] Détail : onglets Discussion | À valider | Réglages avec badges.
- [x] Onglet À valider = file de l’agent ; Réglages = périmètre/cron/profil/actions + stub canaux.
- [x] Modal création : select projets Code + option Général (résoudre cwd via meta/projects).
- [x] Copy humaine (statuts, cron text).
- [x] Deploy + test Chrome.

**Done when:** Accueil guidé OK ; création sans chemin libre ; onglets visibles.

---

## Task 3 — Agent Discussion (MVP)

**Files:** `views/agent.js`, `controllers/agent.js`, `api.py` éventuel

- [x] Onglet Discussion : réutiliser patterns thread/composer (même skin).
- [x] Branchement backend minimal : session liée agent OU message vers pilote si déjà dispo ; sinon stub clair « bientôt » avec UI complète mais envoi désactivé + note.
- [x] Prefer real path if harness session per agent is quick ; sinon stub UI-only pour ne pas bloquer Tasks 4–5.

**Done when:** UI Discussion présente ; envoi réel ou stub explicite.

---

## Task 4 — Connecteurs shell + fiche service

**Files:** `index.html`, `views/connectors.js`, `controllers/connectors.js`, `app.css`

- [x] Layout `.view-shell` : sidebar Plateforme / Mes connecteurs collapsibles.
- [x] Main = fiche service sélectionné (tools list) ; compositions = tools du service dédié.
- [x] Import / re-probe en bandeau, pas page pleine.
- [x] Mobile list↔detail.
- [x] Deploy + test.

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

## État au 1er septembre 2026

Les tâches 1 à 4 sont en service, vérifiées dans le navigateur : bascule
liste ↔ détail sous 720 px, accueil et détail Agent en pleine page avec ses
trois onglets, discussion réelle branchée sur le pilote, shell Connecteurs
avec fiche de service. Les cases sont cochées en conséquence — elles étaient
restées vides alors que le travail était fait, ce qui faisait mentir ce
document.

La tâche 5 reste entière : l'onglet Assistant est un panneau d'attente, il
n'existe pas de vue. C'est le prochain morceau naturel — tout ce dont il a
besoin (sessions, dossiers par conversation, MCP, rendu de fil) est déjà là.

## Execution note

Après chaque task : deploy `deploy_gateway_m1.py` + smoke Chrome. Commits seulement si l’utilisateur le demande.
