# Design — Shell unifié Atelier

**Date** : 2026-08-29  
**Statut** : validé (cadrage)  
**Approche** : shell partagé minimal (pas d’Explorer générique pour l’instant)

## Objectif

Unifier Code, Assistant, Connecteurs et Agent sur le même pattern de page que Code aujourd’hui : **sidebar (liste) + zone centrale (contexte)**, avec un **modèle de discussion** réutilisable, une UX mobile **liste ↔ détail plein écran**, et des libellés plus explicites pour un usage réel (pas seulement power-user).

## Principes

1. **Même squelette partout** — `.view-shell` = sidebar + main ; Code reste la référence visuelle et comportementale.
2. **Discussion = composant partagé** — fil + composer (bulles, PJ, connecteurs de fil) réutilisé là où on « parle » (Code, Assistant, détail Agent).
3. **Atelier relaie, ne réinvente pas** — pool MCP / pilote Wikichat / gateway restent les backends ; l’UI Atelier agrège et présente.
4. **Mobile d’abord utilisable** — sous 720 px : un seul panneau à la fois (liste ou détail), pas une grille écrasée.
5. **Jargon en secondaire** — libellés humains en premier ; technique en meta / tooltip.

## Hors scope (cette passe)

- Composant Explorer générique abstrait (approche 2).
- Recoder le backend pilote ou gateway.
- Branchement réel webmessage / messagerie externe (point d’extension seulement dans Réglages agent).
- Assistant chat « mémoire riche » au-delà du shell + sessions + discussion de base.
- Drawer mobile type app native (gestes swipe) — phase ultérieure ; phase 1 = bouton Retour/Liste.

---

## 1. Shell commun

```
┌─ navbar Atelier ────────────────────────────────┐
│ Code | Assistant | Connecteurs | Agent | Quitter │
├────────────────┬────────────────────────────────┤
│  SIDEBAR       │  MAIN                          │
│  liste + CTA   │  sélection OU accueil          │
└────────────────┴────────────────────────────────┘
```

| Élément | Rôle |
|---------|------|
| `.view-shell` | Grille 2 colonnes (≥ 720 px) |
| `.shell-sidebar` | Liste scrollable + actions (`+`, actualiser) |
| `.shell-main` | Contenu contextuel |
| URL | `?view=` + ids (`session`, `agent`, `connector` selon l’onglet) |

État shell mobile : `shellMode: "list" | "detail"` par vue ; sans sélection → forcer `"list"`.

---

## 2. Responsive &lt; 720 px

### Comportement cible (tous les shells)

| Mode | Affichage | Navigation |
|------|-----------|------------|
| **list** | Sidebar plein écran | Tap item → `detail` |
| **detail** | Main plein écran | Contrôle **Retour / Liste** → `list` |

- Remplace le stack actuel Code (sidebar ~38 vh + chat) qui laisse les deux trop étroits.
- Agent / Connecteurs / Assistant : même contrat.
- ≥ 720 px : sidebar + main côte à côte (comportement desktop actuel de Code).

### Agent / Connecteurs (correctif immédiat)

Supprimer la grille côte-à-côte fixe sous 720 px qui réduisait le main à ~120 px ; appliquer le basculement list/detail ci-dessus.

---

## 3. Code (référence)

Inchangé fonctionnellement ; **alignement mobile** sur list ↔ detail.

- Sidebar : projets → sessions.
- Main : fil + composer (session sélectionnée).

---

## 4. Assistant

| Zone | Contenu |
|------|---------|
| Sidebar | Liste **plate** des sessions assistant ; section **Épinglés** en tête (favoris) |
| Main | Même modèle discussion que Code |

- Épinglés phase 1 : `localStorage` (ou meta session si déjà disponible) — pas de backend dédié obligatoire.
- Pas d’arbre multi-projets : un espace mémoire / transverse.

---

## 5. Connecteurs

### Sidebar

Deux groupes **collapsibles** :

1. **Plateforme** — services catalogue org / plateforme  
2. **Mes connecteurs** — registry perso  

### Compositions

Une composition **n’est pas** une entrée sidebar séparée.  
C’est un **service** du pool gateway ; ses **tools** = les compositions.  
Au détail du service « compositions » (ou équivalent), la liste des tools *est* la liste des compositions.

### Main

Au clic sur un service :

- Fiche : statut, activer/désactiver (si perso), liste des tools.
- Actions globales (re-probe, import JSON) : bandeau main ou pied de sidebar — pas une page pleine largeur isolée comme aujourd’hui.

Les outils gateway qui gèrent tools / services / compositions par agent restent la source de vérité ; l’UI les relaie.

---

## 6. Agent

### Sidebar

- Liste des agents (statut humain, prochain run, badge « N à valider »).
- `+ Nouvel agent`, Actualiser.

### Main — aucun agent sélectionné (accueil)

1. **Guide / onboarding** court (rôle d’un agent, lien vers Connecteurs pour les outils).
2. **Daemon** : armés / prochain réveil / pause-reprise.
3. **File globale** : propositions `pending` tous agents, avec agent source + Approuver / Rejeter.

Pas de chat sur l’accueil.

### Main — agent sélectionné (onglets B)

| Onglet | Contenu |
|--------|---------|
| **Discussion** (défaut) | Fil + composer partagés ; conversation avec cet agent |
| **À valider** | File d’approbation de *cet* agent ; badge compteur sur l’onglet |
| **Réglages** | Périmètre, cron (avec libellé humain), profil Connecteurs, mission, activer/supprimer/lancer ; **emplacement prévu** pour exposition canaux (messagerie / webmessage) — UI stub ou section « Bientôt » |

### Création d’agent

- **Projet** : select des projets Code + option **Général** (= cwd espace assistant / mémoire, pas un chemin texte libre).
- Profil Connecteurs → bindings tools + consignes (`pilote-bindings`).
- Cron, modèle, mission — copy explicative.

### Discussion agent & exposition future

Le détail agent est le lieu où l’on **configure** un agent destiné à être rendu disponible depuis d’autres fronts (services de messagerie, webmessage, etc.).  
Aujourd’hui : discussion dans Atelier.  
Plus tard : mêmes agents exposés via canaux — sans changer le modèle mental (identité + outils + mission + conversation).

Backend discussion agent : à brancher sur le canal existant le plus proche (session harness liée à l’agent / pilote) dans le plan d’implémentation ; le design impose le **contrat UI**, pas le protocole exact.

---

## 7. Modèle de discussion (partagé)

Comportements attendus partout où le chat apparaît :

- Composer (textarea auto-grow, envoi, stop).
- Pièces jointes (`@chemin` côté harness, comme Claude Code).
- Overlay connecteurs de fil (popover `+`) là où pertinent (Code ; Agent si le profil le permet).
- Rendu bulles user / assistant / outils.

Code et Assistant : sessions classiques.  
Agent : conversation **scopée à l’agent** (identité stable), pas une session projet Code générique — même skin UI.

---

## 8. Ordre d’implémentation

1. CSS shell commun + **mobile list ↔ detail** (Code en premier, puis Agent / Connecteurs).
2. Agent : accueil (guide + daemon + file globale) ; onglets détail ; création projet/Général ; copy.
3. Agent : onglet Discussion (branchement backend minimal viable).
4. Connecteurs : layout shell + fiche service (compositions = tools).
5. Assistant : shell + liste sessions + épinglés + chat de base.

---

## 9. Critères d’acceptation

- [ ] Sous 720 px, Code : bascule liste ↔ chat plein écran (plus de double panneau étroit).
- [ ] Sous 720 px, Agent / Connecteurs : même bascule ; détail lisible.
- [ ] Agent sans sélection : guide + daemon + file globale.
- [ ] Agent sélectionné : onglets Discussion | À valider | Réglages avec badges.
- [ ] Création agent : projets + Général, pas d’input chemin libre obligatoire.
- [ ] Connecteurs : sidebar Plateforme / Perso ; détail service avec tools ; compositions via tools du service dédié.
- [ ] Assistant : sidebar sessions plates + épinglés ; main = discussion.
- [ ] Aucune réinvention backend gateway/pilote ; API Atelier = couche d’agrégation.

---

## 10. Décisions tranchées (historique cadrage)

| Sujet | Décision |
|-------|----------|
| Approche shell | Minimal partagé (pas Explorer générique) |
| Connecteurs sidebar | Groupes Plateforme + Mes connecteurs |
| Compositions | Service pool ; tools = compositions |
| Assistant sidebar | Liste plate + épinglés |
| Création agent cwd | Projets Code + Général |
| Accueil Agent | Guide + daemon + file globale |
| Détail Agent | Onglets Discussion \| À valider \| Réglages |
| Mobile | Liste ↔ détail plein écran &lt; 720 px |
| Messagerie / webmessage | Point d’extension Réglages ; hors implémentation immédiate |
