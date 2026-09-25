# Plan d'implémentation de la vision

Ouvert le 25/09/2026. Ce plan organise les équipes et le travail pour aller de ce qui tourne
aujourd'hui (déploiement du 26/09, `main` = `952b3b8`) jusqu'à ce qui a été posé dans
`docs/vision/`, de bout en bout.

Références :

- `architecture-transverse.md` : structures communes, catalogue des briques, tensions ;
- `decisions.md` : ce qui est tranché ;
- `synthese.md` et `assistant-synthese.md` : les cibles ;
- les documents de thème : le détail.

## 1. Règles communes à toutes les équipes

1. **Partir de l'existant.** Avant d'écrire une fonction, chercher la brique qui la porte, dans le
   catalogue du transverse §5 et dans le code. Une brique cassée se répare, elle ne se double pas.
2. **Une équipe, un périmètre de fichiers** (§3). Pour toucher un fichier d'une autre équipe, on
   passe par le coordinateur. Les fichiers partagés (`api.py`, `app.py`, `config.py`) ne reçoivent
   que des ajouts d'une ligne : l'enregistrement d'un routeur ou d'un réglage.
3. **Chaque équipe travaille dans son worktree et sur sa branche**, partie de la base commune.
   Rien n'est poussé. C'est le coordinateur qui intègre, pousse et déploie.
4. **Fini veut dire :**
   - les tests passent : toute la suite `pytest`, plus `npm test` pour wikichat ;
   - un test couvre le comportement réel, pas la présence d'une chaîne ;
   - la documentation du thème est mise à jour dans le même commit (« ce qui existe » et « ce qui
     reste ») ;
   - le rapport sépare « vérifié » et « non vérifié ».
5. **Contrats d'abord.** Quand deux équipes se branchent l'une sur l'autre (API, schéma JSON,
   outil), le contrat est écrit dans le transverse avant le code, et celle qui le consomme écrit
   un test contre lui.
6. **Pod** : lecture seule, sauf pour l'équipe Mesures, dans un dossier jetable. Aucun
   redémarrage de service. Aucun secret lu ni affiché.
7. **Règles du socle** (`docs/consignes/socle.md`) :
   - commits en français, à l'infinitif ;
   - pas d'emojis dans le code ;
   - pas de `pkill -f`, pas d'écoute sur `0.0.0.0`.
8. **Lexique** : tout texte d'interface nouveau suit les 12 mots (`decisions.md` S2).

## 2. Vagues

La **vague 1** ne dépend d'aucune décision en attente. Ses équipes travaillent en parallèle, sur
des fichiers disjoints. Chaque vague se termine par une intégration et un déploiement, avec le go
de Nicolas avant les redémarrages.

### Vague 1 : réparer, poser les fondations, voir

| Équipe | Contenu | Jalons couverts |
|---|---|---|
| **W : wikichat** | lot W : W1 (un seul lecteur de connaissance), W2 (données sous `~/.wikichat`), W3 (étape et action `job` qui appellent les fonctions JS ; les crons de cartographie et de clustering passent par elle), W4 (`GET /api/cartographie` avec les vrais liens : relations déclarées, clustering, instantanés, audits), W5 (Closer, absorption des closures), W6 (inventaire des triggers en échec, **sans rien couper** : liste et recommandations), W7 (documentation) ; écriture de `settings.json` à travers le lien (`realpath`) ; `max_per_day` à 24 par défaut et naissance désactivée des triggers créés par un agent (J-b) | A1, carte (couche wikichat) |
| **F : fondations Atelier** | catalogue de commandes (transverse §1.8 : `objet`, `classe`, `inverse`, `resultat`, `regles`), avec vérification de classe par le serveur, y compris via `gateway_call_tool` ; journal unique (§1.7) ; file « À valider » (modèle et API) ; structure de projet (lot G : `projet.json`, `ETAT.md`, gabarit) ; `atelier_projet_creer` cadré ; défauts du déploiement (`atelier-relancer` et adresses publiques, `atelier-verifier-coherence` et chemin) | A3 (base), J7 (base) |
| **P : panneau et interface** | P0 (vues encadrables : CSP `frame-ancestors`, retrait de `X-Frame-Options` au mandataire), P1 (colonne panneau hors du fil), P2 (`atelier_montrer`) ; code de passage d'agent et outil `atelier_navigateur_ouvrir` (J-h) ; affichage des `systemMessage` et des fils wikichat ; lot H (défauts d'interface relevés le 25/09) | J2, lot H |
| **G : gardiens** | exécuteur à part (module et processus séparés, comme le relais) ; G0 (inventaire des automates, lu de wikichat et de l'Atelier), G1 (santé : Atelier, relais, wikichat, créations servies, CI, image comparée à `main`), G2 (sécurité : ports déclarés, secrets par empreinte, droits 0600) ; journal JSONL ; API de lecture (la page viendra en vague 2) ; hooks `PreToolUse` du socle (refus de `pkill -f` et de `0.0.0.0`) | J1 (moteur), J3 (base) |
| **M : mesures** | A0 et H0 sur le pod : effort `xhigh` comparé à `medium` (latence, qualité) ; méta-outils réels de la passerelle, 5 essais par cas ; latence de bout en bout de l'oral (STT de `voice_service.py`) ; vérifications peu coûteuses A1 à A13 de `coherence-croisee.md` §4 | lève les hypothèses |

### Vague 2 : relier

- **Carte** (couche Atelier, assemblage `/api/carte`, `atelier_carte`), sur W4 et F.
- **Page Gardiens** et **onglet Automates** : P, sur G.
- **Contexte** : lot B (`SessionStart`, `contexte.md`), lot C (une identité) et lot D
  (lancements par l'Atelier) : F, avec W.
- **Hôte MCP Apps** (P3), puis **bureaux** (P4, portées de session) : P.
- **Commandes de création** : agents, connecteurs, liens entre projets (F). Migration du Lecteur
  Grist vers la structure type.

### Vague 3 : l'Assistant et le navigateur en direct

- **Assistant (A4)** :
  - profil `assistant` ;
  - méta-outils ;
  - dossier `wikichat-memory` ;
  - `CLAUDE.md` et imports C1 ;
  - accueil sur son fil ;
  - délégation.
- **Mémoire (A5)** : capitalisation des conversations dans wikichat (W8), filtre des secrets (T10),
  « Ma mémoire ».
- **Navigateur en direct** (J6, P5) : Chrome possédé par l'Atelier, screencast, « Prendre la
  main », profil gardé par conversation.
- **Brouillon, installation et partage** : J8 (manifeste v2, registre des promotions).

### Vague 4 : étendre

- Tableaux de bord système (A6).
- Voix et visio (A7) : le service vocal devient une création serveur authentifiée.
- Connecteur fait maison (J9), autorisations et extensions (J11), réparation assistée (J10).
- Hébergement dédié et partage à des tiers après `passerelle-auth`.
- Refonte de la vitrine, puis publication.

## 3. Périmètres de fichiers (vague 1)

| Équipe | Dépôt, worktree, branche | Possède | Ajoute seulement |
|---|---|---|---|
| W | wikichat, `C:/Users/Omen/Desktop/LAVAL/wikichat-lot-w`, `lot-w` (depuis `atelier-coherence`) | tout le dépôt wikichat | — |
| F | Atelier, `…/atelier-fondations`, `fondations` | `mcp_gateway/atelier/commandes/` (nouveau), `journal.py`, `decisions.py`, `projects.py`, `project_context.py`, `git_repos.py`, `bin/atelier-relancer`, `bin/atelier-verifier-coherence`, `install/`, `mcp_gateway/mcp/gateway.py` (vérification de classe) | une ligne dans `api.py` et `config.py` |
| P | Atelier, `…/atelier-panneau`, `panneau` | `mcp_gateway/atelier/web/`, `artifacts.py`, `artefacts_servis.py`, `apps/` (dont `passage.py`, `proxy.py`), `outils_conversation.py` | une ligne dans `api.py` |
| G | Atelier, `…/atelier-gardiens`, `gardiens` | `mcp_gateway/gardiens/` (nouveau), `docs/consignes/socle.md` (section hooks), hooks du socle | une ligne dans `install/atelier-init.sh`, coordonnée avec F |
| M | aucun code ; documents `docs/vision/mesures-*.md` | — | — |

Base commune : `main` + les documents de vision (commit local `vision-et-plan`).

## 4. Intégration

Le coordinateur :

1. relit chaque rapport ;
2. fusionne les branches dans `integration-vague-N`, dans l'ordre F, W, G, P (du plus fondamental
   à l'interface), et fait passer toute la suite ;
3. met à jour le journal du transverse ;
4. demande le go de Nicolas ;
5. pousse `main`, attend l'image, déploie, vérifie en réel et consigne.

Un conflit de contrat découvert en cours de route est tranché dans le transverse, puis transmis
aux équipes concernées.

## 5. Suivi

| Vague | État |
|---|---|
| 1 | lancée le 25/09 |
| 2 | — |
| 3 | — |
| 4 | — |
