# Cohérence croisée des visions : panneau, écosystème, gardiens

Relecture d'architecture du 25/09/2026, sur `docs/vision/cadre.md`, `panneau.md`, `ecosysteme.md`,
`gardiens.md` et les documents qu'ils prolongent (`atelier-applications.md`, `atelier-hebergement.md`,
`structure-projet.md`, `coherence-projet.md`, `lecteur-grist-application.md`). **À valider.**
Aucun code ni autre document n'a été modifié. Abréviations : lots `H1`–`H7` de l'hébergement,
lots `CA`–`CH` de la cohérence (pour ne plus confondre le lot F de la cohérence avec F1–F9, ni le
lot G avec G0–G6), étapes `P0`–`P7` (panneau), `F1`–`F9` (écosystème), `G0`–`G6` (gardiens).

## 0. Ce que la relecture a vérifié dans le code

| Affirmation | Document | Constat dans le dépôt (branche `secrets-arguments`, sauf mention) |
|---|---|---|
| Pages d'artefacts servies avec `frame-ancestors 'self'` | panneau §2.1 | **Exact.** `artifacts.py:54-81` (`CSP_SANDBOX`, `CSP_CORPUS`), appliquées sur l'hôte des applications par `artefacts_servis.py:125-202`. `'self'` y désigne l'hôte des applications : l'Atelier ne peut pas les encadrer. P0 est bien nécessaire. |
| Le mandataire pose `frame-ancestors 'self' <Atelier>` | panneau §2.1 | **Exact, avec une réserve** : `apps/proxy.py:194-203` ne l'ajoute que si la CSP amont n'a pas déjà `frame-ancestors`, et ne touche pas `X-Frame-Options` (aucune occurrence dans le fichier). Le retrait de `X-Frame-Options` de P0 est donc entièrement à écrire. |
| Le fil est reconstruit à chaque image | panneau §2.1, §3.7 | **Exact dans l'effet, imprécis dans la forme.** `code-chat.js:156-168` regroupe les rendus à un par image ; `rendreLeFil` (`:260-338`) garde les nœuds des messages inchangés, mais les réinsère tous par `thread.replaceChildren(...voulus)` (`:332`). Détacher puis rattacher une iframe la recharge : la règle « aucune vue vivante dans le fil » tient. |
| `/chrome/view` et `/chrome/novnc` servis dans l'origine de l'Atelier | panneau §2.1 | **Exact.** `chrome_proxy.py:148-166`, montés sur l'application de l'Atelier (`api.py:2531`, garde `require_owner_nav`). |
| Deux relais WebSocket à fusionner | panneau §2.1 | **Périmé.** `relais_ws.relayer` (`:137`) porte déjà `taille_max`, `ping_s`, `unix_socket` et `connexion` ; `apps/proxy.py` n'en importe plus que des constantes ; `apps/serveur.py:395` appelle `relayer`. La fusion est faite. |
| `X-Atelier-Conversation` pas encore posé pour la porte `atelier` | panneau §2.1 | **Périmé.** `mcp_sync.declaration_atelier` (`:309-330`) le pose (`${ATELIER_SESSION:-poste}`) ; `integrer_l_atelier` le rajoute aux `.mcp.json` anciens. `atelier_montrer` a donc déjà sa clé de conversation. |
| Événements `outil_debut` / `outil_fin` sur le flux | panneau §2.1 | **Exact** (`events.py:11-12, 98-242`). |
| Manifeste `version: 1`, strict et fermé | écosystème §2 | **Exact** (`apps/manifeste.py:107-131`, `extra="forbid"`, `strict=True`). Aucun des champs `donnees`, `preparer`, `entretien`, `capacites`, `racine` n'existe encore. |
| Compositions `temporary → validated → production` | écosystème §2 | **Exact** pour `temporary` (`compositions/service.py:269`, `executor.py:97`) ; le reste du cycle n'a pas été relu en détail. |
| `max_per_day` par défaut à 100 | gardiens §2 | **Exact** sur `main` de wikichat (`src/triggers.mjs:223, 473`) ; le pilote propose 24 à la création (`src/pilote.mjs:469, 697`). |
| Dormant gate : rien ne tire sans session nommée | gardiens §2 | **Exact** (`src/dormant.mjs` : mode `any-named` par défaut, `WIKICHAT_DORMANT_DISABLED=1` pour la couper). L'effet « la nuit rien, le jour tout » est une déduction plausible, pas une mesure. |
| L'équipe stdio n'a « pas encore de changement » | panneau §2.2 | **Périmé et contraire à la recommandation.** Le commit `b36204c` (branche `chrome-stdio`, `bin/atelier-chrome`) fait lancer Chrome **par `chrome-devtools-mcp` lui-même, par un tube, sans port**, avec un profil jetable par processus MCP, effacé à la sortie. C'est exactement le cas que panneau §3.5 dit incompatible avec une vue navigateur sans VNC. Voir §5.1. |
| Le processus `claude` vit entre deux tours | (implicite, panneau §4 B) | **Oui, jusqu'à l'inactivité** (`harness.py:1100`, `cli_inactivite_s` `:1305`). Le Chrome stdio d'une conversation survit donc entre tours, puis meurt avec son profil (connexion perdue). |
| Les préfixes `/_atelier/` et `/_ui/` ne heurtent aucun projet | panneau §3.2, écosystème §3.5 | **Exact** : un slug commence par une lettre ou un chiffre (`artifacts.py:91`). |

## 1. Les modèles de données

### 1.1 Recouvrements et contradictions

| # | Sujet | Ce que disent les documents | Nature | Résolution proposée |
|---|---|---|---|---|
| M1 | Vues d'un artefact | panneau : `artefact.json` `"vues": [{nom, chemin, titre}]` (liste) ; écosystème : `offre.vue: {titre, emplacement, hauteur}` (une seule) | contradiction | `offre.vues` : **liste**, chaque vue avec `nom`, `chemin`, `titre`, `emplacements`. Une vue exige `offre.page` ou une ressource `ui://` (règle de l'écosystème, gardée). |
| M2 | Où s'affiche une vue | panneau : onglet du panneau, épinglé à la conversation ou au projet ; écosystème : `emplacement` accueil / projet / conversation | recouvrement | Un seul champ `emplacements` ⊂ {`panneau`, `projet`, `accueil`} dans le manifeste (ce que l'artefact **permet**) ; l'épinglage réel est un choix de la personne, hors manifeste (§1.2). `accueil` exige l'ajout à l'Atelier. |
| M3 | Vues des services du namespace | panneau : clé `vues` (avec `amont`, `vnc`) ajoutée à l'entrée du pool, au format `mcpServers` | risque | Ne pas mêler de clés non standard aux entrées `mcpServers` qui sont matérialisées dans `.mcp.json` : tout ce qui est propre à l'Atelier va sous une clé unique `atelier` de l'entrée, retirée à la matérialisation. |
| M4 | Connecteur issu d'un artefact | écosystème : entrée `{"source": "artefact", projet, nom}` | ajout | Même clé `atelier.source`, cohérent avec M3. |
| M5 | Commande de tests | hébergement : `entretien.tests.commande` ; structure-projet : `projet.json` `commandes.tests` | doublon | La commande vit dans `projet.json` seul ; `entretien.tests` ne dit que **quand** (`avant_promotion`, `quand`). |
| M6 | Rythme | entretien `{"toutes_les_min": 5}`, `{"quotidienne": true}`, `{"hebdomadaire": true}` ; gardiens `quand: {toutes_les_min}` ; triggers et routines wikichat : cron | vocabulaire en trois formes | Un seul objet `quand` : `{"toutes_les_min": N}` ou `{"cron": "…", "tz": "Europe/Paris"}`. |
| M7 | Budget | routines : plafond de **passes** par jour ; gardiens : **jetons** par proposition et par automate ; triggers : `max_per_day` | recouvrement | Un seul objet `budget` : `{"passes_par_jour", "jetons_par_jour", "jetons_par_passe"}`, obligatoire pour tout automate qui consomme du modèle. |
| M8 | Capacités | hébergement : `composition`, `outil`, `agent` ; écosystème : ajoute `lecture` ; panneau : appels d'outils **du même connecteur** depuis une vue (règle MCP Apps), écriture « sur geste ou accord pour cette vue » | recouvrement partiel | Quatre types (`outil`, `composition`, `agent`, `lecture`) + un champ `acces: lecture|ecriture`. Les outils du propre connecteur d'une vue sont une capacité **implicite** `outil` en lecture ; l'écriture se consent comme les autres. Un seul registre des accords, un seul journal. |
| M9 | Consentement en brouillon | écosystème : aucun pour le propriétaire en brouillon (journalisé) ; hébergement : consentement à la première promotion ; panneau : écriture sur geste | cohérent si on l'écrit | Brouillon : lecture sans consentement, écriture sur geste explicite ; promotion (Atelier ou production) : écran de consentement. |
| M10 | État accordé et version active | hébergement : dans le « panneau Applications » ; écosystème : registre des extensions (table) ; panneau : état des vues dans la fiche de session | trois endroits | Une table **registre des promotions** dans la base de la passerelle (§1.2) ; l'épinglage des vues va dans `projet.json` (M2, question 5.2-e). |
| M11 | Contrôles d'un projet | gardiens : dérivés d'`entretien` et de `projet.json`, pas de `gardiens.json` par projet ; hébergement : entretien exécuté « par les routines wikichat » | contradiction d'exécuteur | Les deux schémas n'en font qu'un (§1.2, `controle`), exécuté par l'exécuteur des gardiens ; wikichat n'exécute plus que ce qui consomme du modèle (§2). |
| M12 | Mot « panneau » | panneau : la colonne de droite ; hébergement §7 et gardiens : « panneau Applications », « apparaître au panneau » | homonyme | « Panneau » = la colonne seulement. « Applications » devient une vue du projet (lot CH), le tableau des automates reste « page Gardiens ». |
| M13 | Mot « vue » | panneau : tout onglet (page, bureau, navigateur, `ui://`) ; écosystème : « une page affichée dans l'Atelier, rien d'autre » | périmètre différent | Garder la définition du panneau pour l'**affichage**, et celle de l'écosystème pour ce qu'un **artefact** peut offrir. Un bureau n'est jamais offert par un artefact, seulement par une entrée du pool. |
| M14 | `type` de l'artefact | v1 : `service`, `statique` ; écosystème : `savoir-faire` en plus ; hébergement : « page » / « service » | ajout | Garder les valeurs du code (`statique`, `service`, `savoir-faire`) ; « page » et « application » restent des mots d'interface. |

### 1.2 Schéma unifié et propriétaires

**`.atelier/projet.json`** — suivi par git ; écrit par le projet (agent ou personne), lu par l'Atelier, wikichat, les gardiens.

| Champ | Rôle | Écrit par |
|---|---|---|
| `version`, `titre`, `description` | identité (le slug reste le dossier) | projet |
| `famille`, `gabarit: {nom, version}` | origine du projet (F1) | Atelier à la création, puis mise à jour de gabarit |
| `fichiers: {etat, cahier}` | chemins d'`ETAT.md` et du cahier | projet |
| `commandes: {preparer, tests, verifier}` | seule source des commandes (M5) | projet |
| `chemins_proteges` | refus d'édition (hook `PreToolUse`) | projet, sur geste de la personne |
| `vues_epinglees: [{artefact|connecteur, vue}]` | vues ouvertes dans toutes les conversations du projet (M2) | Atelier, sur geste de la personne |

**`artifacts/<nom>/artefact.json` v2** — suivi ; écrit par l'agent ; validé strict et fermé par `apps/manifeste.py` ; v1 toujours lu.

| Groupe | Champs | Remarque |
|---|---|---|
| identité | `version: 2`, `titre`, `type: statique|service|savoir-faire`, `atelier_min` | |
| exécution (v1 inchangée) | `commande`, `repertoire`, `ecoute`, `chemin`, `sante`, `demarrage_s`, `inactivite_min`, `protocoles`, `corps_max_mo`, `env`, `secrets`, `edition`, `acces` | |
| exécution (structure-projet) | `racine` (page), `donnees` / `{donnees}`, `preparer` | à fondre ici, pas dans une v1 élargie |
| `offre` (fermé) | `page: {chemin}`, `mcp: {chemin, prefixe, pilotage[]}`, `vues: [{nom, chemin, titre, emplacements[]}]`, et pour `savoir-faire` : `compositions`, `agents`, `routines`, `commandes`, `skills` | M1, M2, M13 |
| `capacites[]` | `{type, nom, acces, limite_par_heure, consigne_max}` | ce qui est **demandé** ; jamais ce qui est accordé |
| `entretien` | `sante: {quand}`, `tests: {avant_promotion, quand}`, `sauvegarde: {quand, garder, vers}`, `dependances: {quand}`, `github: {ci, alertes}`, `en_cas_d_echec: signaler|proposer`, `budget` | M5, M6, M7 ; dérive des `controle` |

**Registre des promotions** — table de la base de la passerelle (voisine de `compositions` et `app_sessions`), écrite **par l'Atelier seul, sur geste de la personne**. Fusionne le registre des extensions, la version de production et les accords de capacités :
`projet, artefact, destination (atelier|production), hebergement (pod|dedie), version_active, version_precedente, prises_actives[], capacites_accordees[{capacite, acces, accorde_le, par}], exposition (prive|partage|public), etat (active|inactive|suspendue|retiree)`.

**Entrée du pool de connecteurs** — base de la passerelle, écrite par l'Atelier (interface Connecteurs, ou dérivée d'une promotion).
Champs standard `mcpServers` (`type`, `url` ou `command`/`args`, `headers`, `env`, références `${ATELIER_MCP_…}`) **plus** un seul objet `atelier` non matérialisé : `source: {artefact: {projet, nom, version}}` (M4), `vues: [{nom, genre: bureau|application, amont, vnc}]` (M3), `enrichissements`.

**Contrôle** (`atelier-gardiens/gardiens.json`, ou dérivé d'`entretien`) — même schéma pour les deux :
`id, gardien, portee, quand, commande, delai_s, si_constat, geste, proposer: {apres_h, modele, budget}`. Sortie : `{etat, constats: [{empreinte, objet, resume, preuve}]}`.

**Automate** (inventaire, dérivé, **jamais écrit à la main**) — lu par la page Gardiens et l'onglet Automates :
`id, genre (controle|entretien|routine|trigger|demon), proprietaire, source (fichier et clé), quand, budget, derniere, prochaine, cout_semaine, etat (actif|coupe|sans_declaration)`.

**Descripteur de vue** (panneau §3.2) — **éphémère**, construit par l'Atelier depuis les trois sources ci-dessus ; jamais stocké tel quel, sauf la référence dans `vues_epinglees`.

## 2. Mécanismes en double : une brique chacun

| Mécanisme | Occurrences dans les documents | Une seule brique proposée |
|---|---|---|
| **Consentement et capacités** | hébergement §4 (jeton `ATELIER_APP_JETON`, `/v1/capacites`) ; écosystème §3.5 (`POST /_atelier/capacites/…` pour les pages) ; panneau §3.3 et §3.11 (appel d'outil par le pont, « accord pour cette vue ») ; écosystème §3.4 (consentement à l'ajout d'extension) | **Un vérificateur de capacités** dans l'Atelier (`capacites.py`) : lit les accords du registre des promotions, applique limites et `acces`, journalise. Trois **transports** qui l'appellent : jeton serveur (service), session d'applications (page, sur l'hôte des applications), pont MCP Apps (vue). **Un écran de consentement**, déclenché par toute promotion ou tout changement de `capacites`. |
| **Journaux** | capacités (hébergement) ; `journal/*.jsonl` des gardiens ; `routine-runs.jsonl` wikichat ; audit des compositions ; registre des extensions « journal » ; superviseur (`~/work/logs/apps`) ; relais LLM (nombres) | **Un journal d'événements** `~/work/.atelier-etat/journal/AAAA-MM.jsonl`, au format des gardiens élargi : `quand, source (controle|capacite|promotion|vue|automate|geste), acteur, objet, action {avant, apres}, resultat, cout {jetons, secondes}, empreinte`. Les journaux techniques (superviseur, relais) restent, mais tout ce qu'une personne doit lire passe par celui-ci. `routine-runs.jsonl` y est recopié par l'exécuteur. |
| **Tâches planifiées** | triggers wikichat (cron) ; routines wikichat ; `entretien` exécuté « par wikichat » (hébergement §5) ; exécuteur des gardiens (processus à part) ; routines des savoir-faire « déclarées à wikichat » (écosystème F6) | **Un ordonnanceur : l'exécuteur des gardiens.** Il exécute tout ce qui est du code (contrôles, entretien, sauvegardes), hors dormant gate. Ce qui consomme du modèle devient une **demande de lancement** à l'Atelier (`atelier_ouvrir`, lot CD), avec `budget`. Les triggers et routines wikichat existants restent en place, mais sont **inventoriés** (G0) puis migrés un par un. Une seule liste : l'inventaire des automates. |
| **Propositions** | hébergement `en_cas_d_echec: proposer` ; gardiens G5 ; écosystème `atelier_artefact_proposer(destination)` ; structure-projet `/proposer` | **Une file de propositions** (H3) et **un outil** `atelier_artefact_proposer(nom, destination, resume)` ; les gardiens et l'entretien y déposent par le même chemin (branche + conversation lancée par l'Atelier). |
| **Hôte des applications** | artefacts (existant) ; vues, `/_atelier/ecran/<conv>`, `/_atelier/bureau/<connecteur>`, `/_ui/<connecteur>/` (panneau) ; `/_atelier/capacites/…` (écosystème) | **Un hôte, des préfixes réservés** `/_atelier/*` et `/_ui/*` (sûrs : §0). Manque commun : la session d'applications n'a qu'une portée **projet** (`atelier-applications.md`, « Portée = projet ») ; il faut des portées `conversation` (écran Chrome) et `connecteur` (bureaux, `ui://`). À concevoir une fois, avant P4. |
| **Relais** | `relais_ws` (fusionné) ; mandataire HTTP `apps/proxy.py` ; `chrome_proxy.py` (origine de l'Atelier) ; relais noVNC des bureaux et WebSocket du screencast (panneau) ; relais LLM | **Deux relais seulement.** (1) Le mandataire de l'hôte des applications + `relais_ws` pour **tout** ce qui s'affiche (artefacts, bureaux, écran Chrome, n8n), avec le jeton du service posé côté serveur ; `chrome_proxy.py` est retiré à P0. (2) Le relais LLM pour **tout** ce qui parle au modèle, qui devient aussi le compteur de coût (G4, en-tête d'origine). |
| **Contexte vers l'agent** | alertes des gardiens dans `contexte.md` ; ligne « Panneau : … » ; famille et gabarit (écosystème) ; propositions en attente | **Le hook `SessionStart` + `.atelier/contexte.md` (lot CB)**, seul canal ; le contexte de vue entre tours passe par le même générateur (hook `UserPromptSubmit` si l'on veut qu'il change en cours de conversation, à vérifier). |
| **Interrupteurs d'urgence** | `WIKICHAT_TRIGGERS_DISABLED` ; `ATELIER_GARDIENS=0` ; `ATELIER_SANS_EXTENSIONS=1` | Garder les trois (portées différentes), mais les afficher ensemble en tête de la page Gardiens, avec leur état. |

## 3. Dépendances et feuille de route fusionnée

### 3.1 Recouvrements entre étapes

- **F5 = P1 + P3** (cadre de vue et pont MCP Apps) et **F7 = P3** (interfaces `ui://` des serveurs tiers) : à ne construire qu'une fois, sous le nom du panneau.
- **H5 (entretien) = G1 + G5 restreints à un artefact** : l'entretien est un cas des gardiens, pas une brique à part.
- **H3 (propositions) est le prérequis commun** de G5, F4 et de la promotion.
- **CG (structure de projet) = socle de F1** : le gabarit de famille **est** la structure type plus une couche.
- **F2 absorbe** les champs de manifeste de `structure-projet.md` (`racine`, `donnees`, `preparer`, `entretien`, `capacites`).

### 3.2 Graphe (A ──► B : B demande A)

```
 Fait : apps lots 0-5 (hôte, passage, superviseur, mandataire, relais WS), lot CA (sauf wikichat .mcp.json)

 CA-fin (wikichat relit claude-env, ne crée plus de .mcp.json) ─┬─► CD (lancements par l'Atelier) ─► G5 ─► G6
 CB (hook SessionStart, contexte.md) ─► CC (identité unique) ──┘        ▲                  ▲
    │                                    │                              │                  │
    │                                    └─► P7 (VS Code, /panneau)     H3 (propositions) ─┘
    ├─► G3 (cohérence)                                                  ▲
    └─► P3 (contexte de vue)                                            │
 G0 (inventaire, exécuteur) ─► G1 (santé) ─► H5 (entretien = G1 + G5 par artefact)
    ├─► G2 (sécurité) ◄── CA                                            │
    └─► G4 (coût) ◄── relais LLM (fait) + en-tête d'origine             │
 P0 (encadrable, /chrome déplacé) ─► P1 (panneau) ─► P2 (atelier_montrer) ─► P3 (pont MCP Apps = F5, F7)
                                      │                                  ├─► P4 (bureaux) ◄── portées de session
                                      ├─► P6 (n8n, qgis-hub)             └─► F4/F5 (vues d'extension)
                                      └─► P5 (navigateur) ◄── DÉCISION CHROME (§5.1) + chrome-stdio
 CG (gabarit, commandes) ─► F1 (familles) ─► F2 (manifeste v2) ─► H1 (brouillon/production) ─► H2 (données)
                                              │                    ├─► H3 ─► H4 (capacités) ─► F4 (extensions) ─► F6 ─► F9
                                              └─► F3 (connecteur depuis artefact) ◄── H1 ├─► H6 (dédié) ─► H7, F8
```

Chemin critique vers « ce que je produis est en production, visible et entretenu » :
`CG → F1 → F2 → H1 → H3 → (H4, G5) → F4`. Le panneau (P0–P3) et les gardiens (G0–G2) sont **hors de
ce chemin** : ils peuvent avancer en parallèle dès maintenant.

### 3.3 Jalons démontrables

| Jalon | À la fin, la personne peut… | Contenu | Prérequis | Taille |
|---|---|---|---|---|
| **J0 Assainir** | ouvrir la même conversation par l'Atelier, VS Code et le terminal et constater zéro écart (`atelier-verifier-coherence` vert **sur le pod**) ; savoir qu'aucun jeton ne traîne en clair | déploiement du lot CA ; fin de CA côté wikichat (relire `claude-env.sh`, plus de `.mcp.json`) ; rotation du jeton n8n ; `max_per_day` par défaut abaissé (24) | — | S |
| **J1 Voir ce qui tourne seul** | ouvrir la page Gardiens, voir chaque automate avec dernière exécution, prochaine, coût, et le couper d'un geste ; lire le résumé du lundi | G0 + G1 (sondes, relance par script officiel) + partie « coût » de G4 si l'en-tête d'origine passe | décision 5.2-a | M |
| **J2 Voir à côté du fil** | voir une page d'artefact à droite de la conversation, qui se recharge quand l'agent l'écrit, ouverte par l'agent lui-même | P0 + P1 + P2 ; retrait de `/chrome/*` de l'origine de l'Atelier | décisions 5.2-c, d, e | M |
| **J3 Aucun secret, aucun service ouvert sans le savoir** | être alerté en 15 min d'un jeton en clair ou d'une écoute non déclarée ; voir un `git push` d'un `ghp_` refusé | G2 + hooks `PreToolUse` du socle | J0, J1 | M |
| **J4 Même contexte partout** | reprendre une conversation dans VS Code avec la même identité wikichat, les mêmes alertes et le même panneau (`/panneau` dans *Simple Browser*) | CB + CC + G3 + P7 (partie VS Code) | J0 | L |
| **J5 Montrer à l'agent** | cliquer une parcelle et écrire « celle-ci » ; ouvrir le bureau Blender ou QGIS à côté du fil et envoyer une capture | P3 (= F5, F7) + P4 + portées de session `connecteur` | J2, CB, décision 5.3-b | L |
| **J6 Le navigateur de l'agent en direct** | regarder l'agent naviguer, prendre la main pour une connexion, la rendre | P5 (écran screencast, entrées) | J2, décision 5.1 appliquée par `chrome-stdio` | M |
| **J7 Démarrer d'une famille** | créer un projet « page », « application », « outil pour les agents » ou « savoir-faire » en un message, `/verifier` vert à la création ; Lecteur Grist migré | CG + F1 ; migration du Lecteur Grist (`structure-projet.md`, 12 étapes) | J4 conseillé (contexte.md) | M |
| **J8 Brouillon et production** | promouvoir un artefact, revenir en arrière en un geste, restaurer ses données ; voir la file des propositions | F2 + H1 + H2 + H3 | J7 | L |
| **J9 Mon connecteur fait maison** | ajouter un service MCP du projet à son Atelier et l'appeler depuis une autre conversation, puis depuis claude.ai | F3 | J8 | M |
| **J10 Réparation assistée** | trouver le matin une proposition verte sur une branche pour une CI cassée la veille ; l'entretien d'un artefact fait de même | CD + G5 + H5 | J1, J4, J8 | L |
| **J11 Capacités et extensions** | ajouter la vue « calendrier des routines » à l'accueil après un écran de consentement clair ; la voir suspendue puis rétablie | H4 + F4 + F6 | J5, J8 | L |
| **Plus tard** | héberger à part, publier, partager | H6, H7, F8 (attend `passerelle-auth`), F9, P6, G6 | J9, J11 | L chacun |

J1 et J2 sont les deux premiers jalons, **indépendants et parallélisables** ; J0 est court et doit les précéder
pour J1 (inventaire fiable) seulement.

## 4. Affirmations fragiles et vérification à peu de frais

| # | Affirmation | Pourquoi fragile | Vérification (coût) |
|---|---|---|---|
| A1 | MCP Apps « stable depuis le 26/01/2026 », SDK `@modelcontextprotocol/ext-apps` avec `/app-bridge` côté hôte | sources secondaires ; les hôtes divergent (`pip`, `tool-input-partial`) ; l'écosystème dit « version à vérifier » | lire le dossier `specification/` du dépôt `ext-apps` et ses étiquettes ; monter l'hôte d'exemple du SDK contre un serveur d'exemple dans une page jetable (1 h) |
| A2 | L'Atelier ouvre les vues MCP Apps des outils appelés en VS Code ou au terminal par un hook `PostToolUse` | le hook ne sait pas quelle conversation Atelier regarde ; `SessionStart` dans l'extension n'est lui-même pas vérifié (coherence §« Points à vérifier ») | un hook `PostToolUse` qui écrit `session_id` et nom d'outil dans un fichier, lancé en VS Code sur le pod (30 min) |
| A3 | Latence du screencast DevTools « 50 à 150 ms » | estimation, pas de mesure ; traversée de l'Ingress et du relais | script Node de 40 lignes : `Page.startScreencast` sur un Chrome du pod, horodatage à la réception dans un navigateur distant via l'hôte des applications (1 h) |
| A4 | On peut attacher `chrome-devtools-mcp` à un Chrome existant, ou rendre attachable le Chrome qu'il lance | le lanceur `atelier-chrome` passe par un tube ; un Chrome accepte-t-il `--remote-debugging-pipe` **et** `--remote-debugging-port=0` ensemble ? | ajouter `--remote-debugging-address=127.0.0.1 --remote-debugging-port=0` dans le rôle `navigateur` du lanceur et lire `DevToolsActivePort` dans le profil (30 min) |
| A5 | Routes `/desktop`, `/canvas`, `/stream/{user_id}` de `blender-remote-mcp` | vues seulement par leur 401 | lire la source de l'image ou appeler avec le jeton du service depuis le pod (30 min) |
| A6 | n8n encadrable par `N8N_CONTENT_SECURITY_POLICY` (`frame-ancestors` prime sur `X-Frame-Options`) | aucune variable n8n pour `X-Frame-Options` ; priorité à vérifier en réel | `curl -I` de l'éditeur avec la variable posée, puis une iframe dans une page de test ouverte dans Chrome et Firefox (30 min) ; sinon retrait au mandataire (M3) |
| A7 | Passage par code **dans une iframe** (cookie `__Host-` Lax, même site) | jamais essayé en cadre ; partitionnement du stockage des navigateurs | c'est la démonstration de P0 : l'essayer avant tout le reste (30 min une fois `frame-ancestors` élargi). **Fait le 25/09 (équipe P)** : fonctionne dans Chrome, dans les deux sens (code émis par l'Atelier, retour de l'hôte vers l'Atelier), en local sur deux origines du même site ; détail dans `panneau.md` « État » |
| A8 | Plugins Claude Code : prise en charge par le CLI du pod (2.1.281), l'extension VS Code, et comportement avec `--strict-mcp-config` | l'écosystème fonde F6 et F9 dessus | `claude plugin` sur le pod avec une place de marché locale d'un dépôt git ; même essai dans l'extension ; un plugin portant une commande et un serveur MCP, lancé avec `--strict-mcp-config` (1 h) |
| A9 | Dormant gate : « la nuit rien, le jour tout » | mécanisme confirmé (§0), effet non mesuré | distribution horaire de `last_fired` et des lignes de `routine-runs.jsonl` sur une semaine (15 min) |
| A10 | Le relais LLM peut savoir qui appelle (`X-Atelier-Origine`) | dépend d'un en-tête posé par chaque surface | `ANTHROPIC_CUSTOM_HEADERS` posé dans `claude-env.sh`, vérifier sa réception au relais depuis un tour, VS Code et un lancement wikichat (30 min) |
| A11 | Un connecteur ajouté à l'Atelier est utilisable « dans claude.ai sans autre réglage » | les profils et plafonds (`bundles.py`, `mcp_ceiling`) peuvent le filtrer ; OAuth du trousseau à ne pas toucher avant `passerelle-auth` | ajouter un serveur de test au pool et le lister depuis claude.ai par la porte `/mcp` (30 min) |
| A12 | Contexte de vue « au tour suivant » par le hook du lot CB | `SessionStart` ne tourne qu'au démarrage : un processus vivant entre tours (§0) ne le relira pas | vérifier `UserPromptSubmit` avec `additionalContext` en `-p` stream-json et dans VS Code (30 min) |
| A13 | L'hôte des applications est déployé sur le pod | « Rien n'est encore déployé » au 24/09 ; P0 le suppose | `curl https://<hôte apps>/_sante` (1 min) |
| A14 | « Même Chrome » dans l'Atelier et VS Code pour une conversation (panneau, parcours E) | avec `atelier-chrome`, chaque client MCP lance son Chrome et son profil | conséquence de la décision 5.1 ; à écrire comme limite si elle n'est pas levée |

## 5. Questions à Nicolas, dédoublonnées et classées

Sources : panneau (Pa1–Pa5), écosystème (E1–E10), gardiens (Ga1–Ga7), cohérence (enveloppeur de
code-server).

### 5.1 Urgent : bloque une équipe en cours

**U1. Le Chrome de l'agent appartient-il à l'Atelier ?** (Pa1 ; lié à A4, A14)
Constat : `chrome-stdio` (commit `b36204c`) a déjà choisi « Chrome lancé par le serveur MCP, par un tube,
profil jetable par processus ». C'est simple, sobre et sûr, mais rend la vue navigateur impossible sans
VNC et perd la connexion à chaque fin de processus.
**Recommandation : oui, mais par le chemin le moins coûteux, sans défaire le travail en cours.** Dire à
l'équipe maintenant : (1) garder le lanceur et son plafond ; (2) dans le rôle `navigateur`, ouvrir en plus
un port de débogage sur `127.0.0.1` (port 0, lu dans `DevToolsActivePort`) et publier dans
`$RACINE` l'association `ATELIER_SESSION → profil` ; (3) ne pas effacer le profil d'une conversation
tant qu'elle vit (connexion conservée entre deux processus). La supervision complète par l'Atelier
(`--browserUrl`) devient une étape de P5, non un préalable. Limite à écrire : tout processus du pod
peut piloter ce Chrome par le port, comme il peut déjà lire `~/work` (même utilisateur Unix).

### 5.2 Bloque le premier jalon (J1 ou J2)

| # | Question (origine) | Recommandation argumentée |
|---|---|---|
| a | **Où tourne l'exécuteur des gardiens ?** (Ga1) | Processus à part lancé par `atelier-init.sh`, comme le relais LLM. Le 17/09 et le 18/09 montrent que le gardien ne doit vivre ni dans l'Atelier ni dans wikichat. Il devient **l'ordonnanceur unique** (§2), ce qui justifie le processus de plus. |
| b | **Plafonds et naissance des automates** (Ga3, Ga4) | `max_per_day` par défaut à 24 (valeur que le pilote propose déjà) et `budget` obligatoire à la création ; un trigger créé par un agent naît **désactivé** et apparaît dans l'onglet Automates. 3 propositions par jour à 150 000 jetons : accepter pour démarrer, c'est affiché et réglable. |
| c | **Dormant gate** (Ga5) | La garder pour ce qui lance un agent, en sortir tout contrôle en code (l'exécuteur n'y est pas soumis). Mesurer d'abord l'effet réel (A9). |
| d | **Services du namespace : relayés ou encadrés à leur adresse ?** (Pa3) | Relayés par l'hôte des applications : une seule authentification, jeton du service posé côté serveur, `X-Frame-Options` réglé à un seul endroit. Seul le relais permet de retirer `/chrome/*` de l'origine de l'Atelier en P0. |
| e | **Épinglage des vues : fichier du projet ou fiche ?** (Pa5) | `projet.json` `vues_epinglees` (suivi par git) pour l'épinglage au projet, la fiche de session pour les vues d'une conversation. Même contenu vu du poste et du pod, sans nouveau fichier. |
| f | **Ouverture automatique du panneau** (Pa2) | Comme proposé : automatique pour une interface MCP Apps rendue par un outil, jamais pour un flux vivant, toujours pour `atelier_montrer`. Ne bloque que P2 ; se change d'une ligne. |

### 5.3 Peut attendre (à trancher avant le jalon indiqué)

| # | Question (origine) | Jalon | Recommandation argumentée |
|---|---|---|---|
| a | **Quatre familles, « extension » comme destination** (E1) | J7 | Oui : quatre manières de faire tourner quelque chose, et une seule chose (l'artefact) qui va à deux destinations. Moins de mots pour la personne. |
| b | **Pont des vues au format MCP Apps** (E6, implicite dans le panneau) | J5 | Oui, derrière un module unique de l'Atelier et avec le sous-ensemble utilisé seulement ; vérifier A1 d'abord. Un format maison serait une API de plus à tenir. |
| c | **Contexte de vue : hook ou pièce jointe ?** (Pa4) | J5 | Le hook, pour tenir la règle « même chose sur toutes les surfaces » ; mais `UserPromptSubmit`, pas `SessionStart` (A12). La pièce jointe reste le rendu visible dans le fil de l'Atelier. |
| d | **Deux manifestes, le reste généré** (E2) | J8 | Oui : `projet.json` pour le projet, `artefact.json` v2 pour chaque artefact, avec le schéma du §1.2. Un manifeste unique au projet ferait réécrire un fichier partagé à chaque artefact. |
| e | **Consentement en brouillon** (E8) | J8 | Lecture sans consentement, écriture sur geste explicite, consentement à toute promotion (M9). Le journal couvre le brouillon. |
| f | **Moteur des gabarits** (E3) et **où ils vivent** (E4) | J7 | Commencer par une simple copie avec `gabarit.version` inscrite dans `projet.json`, gabarits dans le dépôt de l'Atelier. `copier` ensuite, si la mise à jour d'un projet depuis son gabarit est réellement demandée ; la version inscrite suffit aux gardiens pour signaler un gabarit périmé. |
| g | **Hooks interdits dans une extension** (E5) | J11 | Oui, sans exception : les hooks restent dans le socle de l'Atelier, versionnés et relus (les gardiens en dépendent pour leurs refus en ligne). |
| h | **Capacités des pages : session par projet ou par artefact ?** (E7) | J11 | Session par projet tant qu'aucune page à capacités n'est **publiée** ; exiger un hôte par application (déjà envisagé pour Grist) avant toute publication d'une page à capacités d'écriture. |
| i | **Publication à des tiers : attendre `passerelle-auth` ?** (E9) | Plus tard | Oui, attendre ; mode « propriétaire seul » d'ici là. Cohérent avec la décision du trousseau de ne pas toucher `oauth.py` avant `passerelle-auth`. |
| j | **Place de marché** (E10) | Plus tard | Celle de Claude Code, sous réserve de A8. |
| k | **Gestes autorisés seuls** (Ga2) | J1 | Garder la liste ; relancer l'Atelier seulement après 5 min sans réponse **et** aucun tour en cours visible au superviseur ; l'arrêt d'une application supervisée exposée hors déclaration est sûr (le superviseur sait qu'elle est la sienne). |
| l | **Notification hors de l'Atelier** (Ga6) | J3 | Le résumé suffit pour démarrer ; pour les alertes rouges de sécurité, un courriel par jour au plus, une fois J3 en place. |
| m | **`atelier-gardiens` : dépôt à part ?** (Ga7) | J1 | À part : il vit au rythme de ses contrôles et sert de projet exemplaire de la structure type. |
| n | **Enveloppeur de code-server** (`claudeProcessWrapper`, cohérence lot A) | J4 | Oui : il retire les valeurs en clair des réglages de code-server, ce que G2 signalerait sinon en permanence. |

## Résumé

Les trois visions se tiennent : même vocabulaire, même hôte des applications, même règle « détecter en
code, réparer par proposition ». Les contradictions sont de forme (vues en liste ou unique, rythme et
budget en trois formats, tests à deux endroits, le mot « panneau ») et se règlent par le schéma du §1.2.
Les vrais doublons sont cinq : capacités, journaux, tâches planifiées, propositions, relais ; une brique
chacun (§2). Trois affirmations du panneau sont périmées (relais WS déjà fusionné, en-tête de conversation
déjà posé, équipe Chrome « sans changement ») ; les autres sont exactes. F5 et F7 sont P1 et P3 ; l'entretien est un cas des gardiens.

Décisions les plus urgentes :
1. **Chrome** (U1) : l'équipe `chrome-stdio` a déjà fait l'inverse de la recommandation du panneau. Lui
   demander dès maintenant un port de débogage local et un profil gardé par conversation.
2. **L'exécuteur des gardiens comme ordonnanceur unique**, dans un processus à part (5.2-a).
3. **Automates bornés** : `max_per_day` à 24, budget obligatoire, trigger d'agent créé désactivé (5.2-b).
4. **Services relayés par l'hôte des applications** et `/chrome/*` retiré de l'origine de l'Atelier (5.2-d).
5. **Premiers jalons en parallèle** : J1 (voir ce qui tourne seul) et J2 (voir à côté du fil), après J0.
