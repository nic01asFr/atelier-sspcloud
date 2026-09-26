# L'Assistant : contexte, mémoire et capitalisation

Vision du 25/09/2026, équipe « contexte et mémoire ». **Réflexion, rien n'est implémenté.**
S'appuie sur `assistant-cadre.md` (et ses précisions : porte d'entrée principale, liens entre
objets, capitalisation, voix), `architecture-transverse.md` (§1.2 identité, §1.3 carte, §1.7
journal, tension T7), `docs/atelier-wikichat-alignment.md`, `docs/coherence-projet.md`,
`docs/structure-projet.md`, `gardiens.md`, `docs/consignes/stt-tts-atelier.md` et wikichat,
branche `atelier-coherence`.

Convention : **[M]** mesuré (fichier, commande ou journal cité) ; **[D]** documenté (doc
officielle ou code lu, pas constaté sur le pod) ; **[S]** supposé, à mesurer.

## En une phrase

Le contexte de l'Assistant est une pile de **fichiers générés par du code** : la vue synthétique
de la carte de l'Atelier et le profil, toujours chargés (≈ 20 000 jetons avec le harnais) ; les
nouveautés, injectées par les hooks seulement s'il y en a ; le détail, lu par des outils bornés.
Chaque conversation, écrite ou orale, laisse une **fiche** rattachée à son `session_id` : faits
extraits par du code, résumé par une routine plafonnée. L'Assistant retrouve le passé par ces
fiches, sans relire les transcrits. Quand il crée ou modifie un objet, la carte et le journal se
mettent à jour **par le code** ; il ne propose lui-même que ce qu'il est seul à savoir.

---

## 1. Le problème, vu par la personne

1. *« Où en est mon lecteur Grist ? »* C'est `projet-sans-nom-5`, il sert une application, il a
   changé il y a 3 heures. Rien de cela n'arrive au modèle sans appels qu'il doit penser à faire.
2. *« Le widget dont on a parlé la semaine dernière ? »* 55 conversations d'Assistant sur le pod
   (14 Mo) [M] : personne ne peut les relire.
3. *« Pas de notification la nuit »*, dit à l'oral en marchant : la préférence doit tenir, rester
   visible et corrigible, à l'écrit comme à l'oral.

La contrainte : une fenêtre de 131 072 jetons, et un modèle (`qwen3-6-35b-moe`) qui a **déraillé
vers 105 000 jetons** dans un tour long (17/09) [M, mémoire `agent-derive-contexte-sans-usage`].

## 2. Ce qui existe déjà

### Mesuré sur le pod (lecture seule, 25/09, `proj-claude-code-jupyter-python-0`)

| Objet | Mesure |
|---|---|
| Projets | 26 dossiers ; 12 avec des conversations ; 8 actifs cette semaine |
| `ETAT.md`, `docs/decisions/`, `.atelier/contexte.md` | **aucun**, dans aucun projet |
| `CLAUDE.md` | 97 à 13 114 car. ; socle 7 207 car. (≈ 2 100 jetons), avec des `# Compact instructions` pour agent code |
| Pool de connecteurs | 11 amonts, **293 outils** ; 178 248 car. de descriptions et schémas, soit **≈ 52 000 jetons** si tout était présenté |
| Liens | 221 liens projet → connecteur ou création ; 16 projets reçoivent presque tout le pool |
| Créations, automates | 0 application supervisée ; 3 `artefact.json` ; 14 déclencheurs dont 9 actifs ; 1 routine |
| Base de connaissances | 4 axes, 21 959 car. (≈ 6 500 jetons) |
| Hooks installés | `Stop` (ancien) et `SessionEnd` : **ni `SessionStart` ni `UserPromptSubmit`** |
| `wikichat-memory` | dossier, pas un dépôt ; 7 `assistant/sessions/<uuid>/` |
| Conversations de l'Assistant | 55 transcrits ; le plus long fait 887 Ko pour 41 messages de la personne ; **0 compaction** ; les 51 fiches `sessions/*.json` sont toutes `kind=code` |
| Mémoire native de Claude Code | tous les dossiers `memory/` vides |
| Relais LLM | 36 appels. Entrée médiane 27 873 jetons ; plus petite 21 695 ; 27 401 en entrée et 65 en sortie en **1,6 s** ; 32 507 et 635 en **4,1 s** (car./3,4) |
| Compaction native | 108 257 → 16 853 jetons en 17,2 s ; 110 290 → 17 537 en 25,2 s (`coherence-projet.md`) |
| `WIKICHAT_MEMORY_REPO` | absent : la synchronisation n'a jamais tourné |

### Mesuré sur le poste

| Objet | Mesure |
|---|---|
| `~/.wikichat/knowledge` | 19 axes, 231 399 car. (≈ 68 000 jetons) ; `grist-axis.md` fait 27 697 car. (≈ 8 100) |
| Dépôt `wikichat-memory` | **existe** sur GitHub : 289 instantanés depuis le 17/06, poussés toutes les 15 min par `sync-memory.mjs` |
| Son état | 28 commits d'avance, 3 de retard : `pull --ff-only` échoue à chaque passage |
| Son contenu | 42 axes dont **19 doublons exacts** (`omen__*.md`) ; l'index de 33 projets fait 29 588 car. (≈ 8 700 jetons) |

### Mécanismes déjà écrits

- **Hooks wikichat** (poste, 16 cas) [M] : `SessionStart` ≤ 2 500 car., 538 à 658 injectés, **0**
  à la reprise sans nouveauté ; `UserPromptSubmit` 0 si rien ; réinjection à `compact` ; 120-165 ms.
- **Plafond natif** [D] : `additionalContext` coupé à **10 000 car.** ; les imports `@fichier` de
  `CLAUDE.md` n'ont pas ce plafond et sont relus après compaction.
- `projet-fichiers.mjs` (titre, tête d'`ETAT.md`, À décider, décisions) ; `close_project` ;
  `search_knowledge` (5 extraits) ; `atelier_transcript` ; `publish-memory.mjs` (11 motifs de
  secret vérifiés).
- **Voix** : `voice_service.py` (faster-whisper par tranches de 3 s, Kokoro, MCP `dire` et
  `ecouter`) ; pas encore de visio ni de flux.

### Ce qui ne va pas

- `wikichat-memory` désigne le dossier de l'Assistant sur le pod (« pas un dépôt, à dessein »,
  alignement §10) et un dépôt d'instantanés sur le poste.
- Quatre inventaires des mêmes objets en construction (T7) ; rien ne sort d'une conversation
  terminée ; la base de connaissances grossit par duplication.

## 3. La proposition

### 3.1 Quatre couches

```
 fenêtre 131 072 ───────────────────────────────────────────────────────────────────────
 │ C0 harnais       invite système + outils de l'Assistant (noyau + catalogue, jamais le pool)
 │ C1 toujours là   CLAUDE.md → @CONSIGNES.md @moi/profil.md @moi/preferences.md
 │                               @atelier/carte.md @atelier/a-valider.md   (fichiers générés)
 │ C2 chaque tour   hooks SessionStart / UserPromptSubmit : le delta seulement (0 si rien)
 │ C3 à la demande  atelier_carte · atelier_rappel · atelier_fiche · project_state ·
 │                  search_knowledge · atelier_gardiens_etat                (sorties bornées)
 │ conversation     échanges et résultats d'outils           → compaction vers ≈ 17 000
 └──────────────────────────────────────────────── sortie réservée 8 192 ───────────────
```

| Couche | Contenu | Calculé par | Fraîcheur |
|---|---|---|---|
| C1 consignes | rôle, style écrit et oral, `# Compact instructions` de l'Assistant | gabarit versionné de l'Atelier | à la version |
| C1 profil | qui est la personne, préférences validées | la personne ; propositions validées | à la validation |
| C1 carte | vue synthétique du graphe (§3.2) | **code** | au calcul du graphe |
| C1 à valider | la file « À valider » (§1.7 transverse), résumée | code | idem |
| C2 | courrier, fils, carte changée, délégation finie, nouvelle alerte | hooks (wikichat, Atelier) | à chaque tour |
| C3 | détail d'un objet, `ETAT.md`, décisions, fiches, axes | outils en lecture | à l'appel |

**C1 passe par des fichiers importés** (le hook est coupé à 10 000 car., un import est relu après
compaction). **Le hook ne porte que le delta**, par empreinte et par conversation, comme wikichat.

### 3.2 La carte : un seul graphe, lu par tous

La carte de l'Assistant **est** la carte de l'Atelier (§1.3 transverse) : le même graphe que lisent
l'inventaire des gardiens (G0), le catalogue « + » et la vue projet du panneau, et le briefing de
wikichat. Personne n'en tient de copie.

**Schéma.** Chaque nœud a un `id` stable, un `type`, un `titre`, un `etat` (`ok`, `attention`,
`alerte`, `dormant`), une date `vu` et la liste de ses `sources` (fichier ou table d'où il est
tiré).

| Objet (`type`) | Clé | Attributs d'état |
|---|---|---|
| `projet` | slug | titre, dernier commit, tête d'`ETAT.md` ou `sans_etat`, nombre d'À décider |
| `creation` | projet/nom | page ou serveur, version active (registre des promotions), santé |
| `connecteur` | nom du pool | nombre d'outils, dernière sonde (répond, refusé) |
| `acteur` | **`session_id`** (§1.2) | type (Assistant, agent code, agent lancé), surface (Atelier, VS Code, terminal, **voix**), active ou finie, fiche |
| `automate` | id du trigger, de la routine ou du contrôle | actif, dernier lancement, budget, coût de la semaine |
| `service` | nom | répond, port déclaré |
| `vue` | id | ce qu'elle diffuse (panneau) |

| Lien | De → vers | Source |
|---|---|---|
| `utilise` | projet → connecteur | `.mcp.json` du projet (déjà écrit par la liaison) |
| `sert` | création → projet | `artefact.json` |
| `expose` | connecteur → création | registre (F3) |
| `travaille_sur` | acteur → projet | fiche de session (`cwd`, `slug`) |
| `a_delegue` | acteur → acteur | journal (`atelier_ouvrir`/`atelier_envoyer` de l'Assistant), avec attendu et échéance |
| `lance` | automate → acteur | inventaire des automates, fiche |
| `vise` | automate ou alerte → objet | déclarations des gardiens, journal |

**Sources, sans double saisie** : `projet.json`, `artefact.json`, registre des promotions,
`gateway.db`, `.mcp.json`, fiches `sessions/*.json`, `triggers.json`, `routines.json`, Pilote,
journal des gardiens, `git log`, `ETAT.md`. Aucun champ n'est saisi pour la carte.

**Propriétaire : l'Atelier (recommandé).** Il possède déjà fiches, pool, manifestes et registre ;
ses commandes `atelier_*` créent et modifient les objets et peuvent donc recalculer **dans la même
opération** ; `session_id` y naît. Il écrit le graphe dans `~/work/.atelier-etat/carte.json` à
chaque calcul. L'exécuteur des gardiens **lit ce fichier** pour son inventaire et **écrit ses
résultats au journal**, que le calcul suivant intègre. Si l'Atelier tombe, son dernier fichier
reste lisible ; l'exécuteur, qui ne doit pas dépendre de ce qu'il garde, observe lui-même
processus et ports.

**Accès.** `GET /api/carte` (graphe complet, filtres `type`, `autour=<id>`, `profondeur`), l'outil
`atelier_carte(objet?, profondeur=1)` (voisinage borné à 1 500 caractères) et la vue synthétique
`atelier/carte.md`. wikichat lit `GET /api/carte?autour=<projet>` pour son briefing, au lieu de
son propre `project-state.json`.

**Calcul**, sans modèle, au plus un toutes les 10 s : en **fin de commande `atelier_*`** qui crée,
modifie ou délègue (une création de l'Assistant s'y reflète sans qu'il la note) ; sur événement
(fin de tour, commit sur `ETAT.md`, résultat de gardien, changement du pool) ; en secours toutes
les 5 minutes.

**Vue synthétique de l'Assistant** (`atelier/carte.md`, C1) : une ligne par objet **actif** (touché
depuis 14 jours, en production ou en alerte), les dormants en décompte, les liens factorisés.
Exemple abrégé, données réelles du pod :

```
Atelier de Nicolas — 26 projets (8 actifs cette semaine), 11 connecteurs, 9 automates actifs,
0 alerte (gardiens non déployés). Carte du 25/09 14:51.
- projet-sans-nom-5 « Lecteur Grist » | 3 h | 4 conv. | application | pool sauf blender | sans ETAT.md
- nouveau-projet-2 | 22 h | 4 conv. | voix | Onyxia, voice | sans ETAT.md
Dormants (18) : atelier-connecteurs, default, m3-test… (détail : atelier_carte)
Automates sans budget : 94219a5f (48 lancements), 2007ca6b (43), 85539555 (53).
```

**Budget mesuré** : une vue naïve des 26 projets (une ligne chacun, puis pool, créations,
automates) fait **3 497 car., ≈ 1 030 jetons** [M, construite en mémoire sur le pod].

| Variante | Jetons | Statut |
|---|---|---|
| Actifs seulement, liens factorisés | < 700 | [S] |
| Avec titres, `ETAT.md` et alertes | ≈ 2 000 | [S] |
| Plafond : 8 000 car. | ≈ 2 400 | au-delà, le code replie en dormants |

À titre de comparaison, l'index exporté des projets coûte 8 700 jetons [M].

### 3.3 Le budget de contexte

Mesuré [M] : sortie réservée 8 192 ; auto-compaction vers 108 000 ; dérive vers 105 000.

| Poste | Jetons | Statut |
|---|---|---|
| C0 harnais et outils de l'Assistant | 15 000 | [S]. Plancher mesuré d'un agent code : **21 695** [M] ; l'Assistant a moins d'outils |
| C1 `CONSIGNES.md` | 2 000 | [S]. Socle agent code : 2 100 [M] |
| C1 profil et préférences | 800 | [S]. Plafond de 2 700 car. |
| C1 carte | 1 030 aujourd'hui, 2 400 au plafond | [M] puis [S] |
| C1 à valider | 600 | [S]. Plafond de 2 000 car. |
| **Total fixe** | **≈ 19 500 à 21 000**, soit 15 % | |
| C2 par tour | 0 à 600 | [M] : 0 sans nouveauté, 218 pour un message |
| C3 par appel | 1 500 (borné). Un axe entier va jusqu'à 8 100 | [M] |
| Zone de travail | ≈ 70 000 | [S] : jusqu'à un seuil de **90 000**, sous la dérive |
| Après compaction | ≈ 17 000, plus C2 | [M] mesuré sur un agent code |

Conséquences : compaction vers 90 000 par un `CLAUDE_CODE_MAX_CONTEXT_TOKENS` propre à
l'Assistant [S : vérifier qu'il déplace le seuil] ; pool jamais présenté entier (≈ 52 000 [M],
assemblage : équipe harnais) ; lectures C3 bornées par l'outil, pas par le modèle.

### 3.4 Capitalisation des conversations

Toute conversation (Assistant ou agent code, écrite ou orale), rattachée à son **`session_id`**
(§1.2), passe par trois étapes.

| Étape | Par quoi | Quand | Ce qui en sort |
|---|---|---|---|
| **1. Faits** | **code**, depuis le transcrit, le journal et la carte | fin de conversation (`SessionEnd`) ou 30 min d'inactivité | en-tête de fiche : dates, surfaces (écrit, voix, VS Code), projet, objets créés ou modifiés, délégations et leur issue, commits, jetons (relais), les 3 premiers messages de la personne cités mot pour mot |
| **2. Sens** | **routine plafonnée**, petit modèle | la nuit, par lot | 5 lignes de résumé, sujets, décisions, questions ouvertes, **candidats** à la mémoire |
| **3. Rangement** | code | après l'étape 2 | la fiche, une ligne d'index, les candidats dans « À valider » |

Plafonds de l'étape 2 : entrée préparée par le code (messages de la personne et réponses finales,
sans résultats d'outils) ≤ 30 000 jetons ; sortie ≤ 800 ; 20 conversations par nuit au plus, d'au
moins 3 échanges.

**Où va chaque chose** (une source par information) :

| Ce qui est extrait | Rangé dans | Condition |
|---|---|---|
| ce qui s'est passé | `conversations/AAAA/MM/<session_id>.md`, avec une ligne dans `conversations/index.jsonl` | code, puis routine |
| préférence ou fait sur la personne | `moi/preferences.md`, `moi/profil.md` | **validé par la personne** |
| décision transverse de la personne | `decisions/NNNN-*.md` du dépôt mémoire | proposée, puis validée |
| décision ou état d'un projet | **le projet** (`ETAT.md`, `docs/decisions/`) | l'Assistant délègue à une conversation du projet, il n'écrit pas lui-même |
| savoir réutilisable | axe de `~/.wikichat/knowledge/` | chaîne `close_project` → `#library`, proposée quand un sujet revient dans 3 fiches |
| actions, délégations | **journal unique de l'Atelier** (§1.7) | la fiche le cite, elle ne le recopie pas |

**Retrouver le passé sans relire les conversations** :

| Outil | Rend | Borne |
|---|---|---|
| `atelier_rappel(requete, projet?, depuis?)` | les 5 fiches les plus proches : date, sujet, résumé d'une ligne, objets | 1 500 car. |
| `atelier_fiche(session_id)` | la fiche | 2 500 car. |
| `atelier_carte(objet)` | l'objet et ses dernières conversations (`travaille_sur`) | 1 500 car. |
| `atelier_transcript(session_id, passage)` | un extrait, en dernier recours | 3 000 car. |

`atelier_rappel` cherche en plein texte dans l'index (résumés, sujets, objets, citations), avec le
moteur de `search_knowledge`. Pas d'embeddings au départ [S : ils suffisent jusqu'à quelques
milliers de fiches]. Un rappel coûte environ 450 jetons. Relire le plus long transcrit en coûterait
jusqu'à 260 000 [M : 887 Ko / 3,4, valeur haute].

**Contre le bruit** : le modèle ne fait que **proposer** (`atelier_memoire_proposer(type, texte,
source)`, 3 par conversation, doublons ignorés par empreinte) ; `profil.md` et `preferences.md`
sont plafonnés (la consolidation remplace, n'ajoute pas) ; les faits sont écrits par le code ; un
candidat expire après 14 jours ; chaque préférence renvoie à sa fiche.

**Consolidation** : chaque nuit, par le code (expirations, dédoublonnage des axes : 19 doublons
[M]) ; chaque semaine, une routine plafonnée (≤ 40 000 jetons en entrée, ≤ 2 000 en sortie)
propose un **diff** du profil et des préférences.

**Voir et corriger** : onglet « Ma mémoire » (profil, préférences, décisions, candidats,
conversations fichées), « d'où ça vient » et « oublier » sur chaque ligne, git pour annuler. Pas
de mémoire native de Claude Code : vide sur le pod [M], invisible, non versionnée.

### 3.5 Le dépôt mémoire

> **Correction du coordinateur (25/09)** : cette proposition contredit une décision déjà prise
> (`atelier-wikichat-alignment.md` §10 et §11, 02/09). Le dossier de l'Assistant n'est **pas un
> dépôt, à dessein** : c'est de la mémoire de session tenue par wikichat. Le dépôt GitHub
> `wikichat-memory` n'est qu'une **publication** assainie de la mémoire (`export-memory`,
> `publish-memory`). Voir `assistant-synthese.md` §6, décision 1.

**Proposition (retirée)** : `wikichat-memory` devient un dépôt git privé, et la racine de travail de
l'Assistant. Il n'a **qu'un écrivain : le pod**. Le poste le lit.

```
wikichat-memory/
├── CLAUDE.md             SUIVI. Imports @CONSIGNES.md @moi/… @atelier/…
├── CONSIGNES.md          SUIVI. Gabarit de l'Atelier (empreinte) : rôle, style écrit et oral, compaction
├── moi/                  SUIVI. profil.md (≤ 1 500 car.), preferences.md (≤ 1 200)
├── conversations/        SUIVI. AAAA/MM/<session_id>.md, index.jsonl — toutes surfaces, écrit et voix
├── decisions/            SUIVI. NNNN-*.md, décisions transverses de la personne
├── atelier/              GÉNÉRÉ, IGNORÉ. carte.md et a-valider.md, vues du graphe et de la file
├── assistant/sessions/<session_id>/   cwd des conversations, comme aujourd'hui
├── instantane/           SUIVI, GÉNÉRÉ par publish-memory : lecture distante (claude.ai, mobile)
└── .wikichat/            IGNORÉ
```

**D'où vient chaque partie** : du **projet** (lu, jamais recopié) `ETAT.md`, décisions,
closures, axes ; du **code** (Atelier, gardiens, wikichat) graphe, file, journal, faits des
fiches ; du **modèle** les candidats et le résumé des fiches.

**Jamais versionné** : transcrits et audio ; état du coordinateur (`identity-bindings.json`,
`hook-cursors/`, `process-tokens/`, `triggers.json`, `routine-runs.jsonl`) ; journaux
(`librarian.log` : 18 Mo sur le poste [M]) ; `~/work/.secrets`. La vérification des secrets de
`publish-memory` s'applique à tout ce qui est suivi.

**Synchronisation `~/.wikichat` ↔ dépôt** :

1. Sur le pod, poser `WIKICHAT_MEMORY_REPO`. Publier d'abord en `--no-push`, puis pousser.
2. Préfixer `MANAGED` par `instantane/` : aujourd'hui, l'export purge `projects/` et `knowledge/`
   à la racine.
3. `~/.wikichat/knowledge/` reste la source des axes, sans lien symbolique.
4. Le poste cesse de pousser sur `main`. Deux écrivains produisent exactement le « 28 en avance,
   3 en retard » mesuré.

### 3.6 La voix

**Une seule conversation, une seule mémoire.** Le pont vocal remet chaque énoncé transcrit à la
**même conversation** (même `session_id`) que l'écrit, par `atelier_envoyer`, avec la marque
`canal: voix`. La réponse est dite par TTS et s'affiche dans le fil. D'où un seul transcrit et une
seule fiche (la surface `voix` s'ajoute à l'acteur dans la carte) ; pas d'audio conservé ; aucune
mémoire validée à la voix seule (une erreur de STT deviendrait une préférence) : à l'écran.

**À l'oral, on réduit la sortie et les outils, pas la vue d'ensemble.** Mesure au relais [M] : une
requête de 27 401 jetons finit en 1,6 s pour 65 jetons de sortie. Avec environ 20 000 jetons fixes,
le contexte pèse peu sur la première parole [S : premier jeton non chronométré à part]. Ce qui
pèse : les appels d'outils enchaînés, la longueur de la réponse, une compaction (17 à 25 s [M]).

| Règle de l'oral | Comment |
|---|---|
| C0 et C1 inchangés | Même préfixe que l'écrit : même session. On passe d'un canal à l'autre sans rien perdre |
| Style | Pour un énoncé `voix`, `UserPromptSubmit` injecte (≈ 80 jetons) : « 1 à 3 phrases parlées, sans liste ni chemin ; le long s'affiche à l'écran » |
| Outils synchrones | Lectures bornées seulement (carte, rappel, fiche, état). Une action longue est **déléguée** et annoncée |
| Pas de compaction pendant la parole | À l'ouverture d'un appel au-delà de 60 000 jetons, l'Atelier compacte avant la première phrase, ou ouvre une conversation neuve adossée à la fiche. Pendant l'appel : seulement à un silence |
| Sortie courte | Plafond réduit (≈ 300 jetons) [S] ; la synthèse vocale commence dès la première phrase du flux |

Carte et profil sont déjà dans le contexte. C'est ce qui permet une réponse courte **et** juste,
sans appel d'outil.

### 3.7 La compaction

`CONSIGNES.md` porte des `# Compact instructions` propres à l'Assistant. Le résumé **garde** les
demandes de la personne avec leur statut (faite, déléguée à tel `session_id` pour tel attendu, en
attente de sa réponse), les objets créés ou modifiés (noms), les décisions et si elles ont été
proposées en mémoire, les questions ouvertes, le canal en cours. Il **ne garde pas** ce qui se
relit (carte, profil, fichiers, résultats d'outils), ni aucun secret. Après compaction :

1. **Les imports sont relus** [D, à constater avec `qwen3`].
2. **`SessionStart`** (source `compact`) réinjecte l'identité, le courrier, les fils, les nouveaux
   « à valider » et les **délégations en cours** de l'acteur, lues dans le graphe (`a_delegue`).
   Seules les délégations sont nouvelles : wikichat réinjecte déjà le reste, en 658 car. [M].
3. **`atelier_fiche(session_id)`** donne la fiche de la conversation en cours, tenue à jour par le
   code.

### 3.8 La continuité : des sessions courtes, adossées à la mémoire

Une conversation par sujet, courte ; la continuité passe par les fiches et la carte. Raisons : la
dérive observée à 105 000 jetons, et la reprise du 17/09 réussie en un tour et 8 appels par un
brief court dans une conversation neuve [M] ; l'usage réel (55 conversations, 41 messages au plus,
0 compaction [M]) ; le coût (≈ 20 000 jetons pour une session neuve, 90 000 par appel pour un fil
long, sans cache de préfixe garanti [S]) ; des traces vérifiables (une fiche de faits, pas un
résumé de résumé). L'interface propose de **reprendre** si la conversation a moins de 4 heures et
le même sujet, ou pour un appel vocal qui suit l'écrit ; sinon une conversation neuve. Une
délégation survit à sa conversation (lien du graphe) : son issue arrive au prochain tour.

### 3.9 Gardiens et projets : l'Assistant lit, il ne recalcule pas

Il lit les états et alertes du graphe (tirés du journal des gardiens), « À valider »,
`atelier_gardiens_etat` et le résumé hebdomadaire. Il ne lance aucun contrôle et ne recalcule
aucun état ; s'il doute, il demande un calcul (`atelier_carte(rafraichir=true)`). Un projet se lit
par `project_state` ou `atelier_projet_etat` (1 300 car. [M, code]). Un projet sans `ETAT.md`
(tous, aujourd'hui) est marqué `sans_etat`, constat du gardien Cohérence : l'Assistant ne comble
pas le trou en lisant le dépôt entier.

## 4. Parcours

- **P1 — Lundi matin.** « Quoi de neuf ? » La carte et « À valider » sont déjà dans le contexte :
  la réponse vient sans appel d'outil.
- **P2 — Créer.** « Un projet marchés publics, avec data.gouv. » `atelier_projet_creer` applique
  la structure et lie `datagouv` ; en fin de commande, graphe recalculé et journal écrit. Le
  lendemain, dans une autre conversation, le projet est sur la carte sans que personne l'ait noté.
- **P3 — Retrouver.** « Le widget de carte ? » `atelier_rappel` renvoie deux fiches (environ 450
  jetons). `atelier_fiche` donne la décision et la question ouverte. Aucun transcrit n'est relu.
- **P4 — À l'oral.** « Pas de notification la nuit, et relance le lecteur Grist. » Deux phrases
  de réponse ; relance déléguée ; préférence en candidat, validée plus tard à l'écran ; le fil
  écrit montre l'échange.
- **P5 — Compaction.** Au-delà de 90 000 jetons, le résumé garde les demandes et la délégation.
  Les imports rechargent la carte et le hook réinjecte la délégation. L'attente est de 17 à 25 s,
  jamais pendant la parole.
- **P6 — Corriger.** « J'ai changé de service. » Nicolas efface la ligne dans « Ma mémoire ».
  Le commit garde l'ancienne version.

## 5. Étapes

| Étape | Contenu | Démonstration | Dépend de |
|---|---|---|---|
| **K0 Hooks au pod** | déployer `SessionStart` et `UserPromptSubmit` (`atelier-coherence` §8 bis) ; mesurer C0 au relais | C0 réel ; 0 injection sans nouveauté | wikichat |
| **K1 Graphe** | calcul dans l'Atelier, `carte.json`, `GET /api/carte`, `atelier_carte`, vue synthétique, plafond, recalcul en fin de commande | vue du pod < 2 400 jetons ; suit une création sans modèle ; G0 et wikichat la lisent | — |
| **K2 Dépôt mémoire** | gabarit, `.gitignore`, `instantane/`, un seul écrivain | clone neuf lisible, sans secret | question 1 |
| **K3 Fiches (faits)** | étape 1 par le code, rattachée au `session_id` | les 55 conversations existantes fichées sans modèle | K1 |
| **K4 Rappel** | `index.jsonl`, `atelier_rappel`, `atelier_fiche` | P3 | K3 |
| **K5 Sens et mémoire** | routine nocturne plafonnée, `atelier_memoire_proposer`, « Ma mémoire » | P6 ; coût de la nuit affiché | K3, gardien Entretien |
| **K6 Compaction et oral** | `# Compact instructions` de l'Assistant ; seuil à 90 000 ; délégations au `compact` ; règles de l'oral | P5 ; un appel vocal reprend une conversation écrite | K0, équipe voix |
| **K7 Consolidation** | diff hebdomadaire ; dédoublonnage ; proposition d'axe | 19 doublons retirés | K5 |

K0, K1, K3 et K4 n'utilisent aucun modèle. Ils apportent l'essentiel : la carte toujours présente
et la mémoire des conversations.

## 6. Risques et questions

### Risques

- **Graphe ou fiche faux** (l'Assistant sûr de lui, et faux) : date et sources par nœud, faits
  écrits par le code, gardien Cohérence qui compare le graphe à ses sources.
- **Contexte fixe qui grossit** : le plafond de la vue est appliqué par le code.
- **Mémoire empoisonnée** (une page lue ou un message d'agent devient une consigne permanente) :
  seule la personne valide, et les messages d'agents sont déjà étiquetés comme informations [M,
  code].
- **Erreur de STT** : rien ne se valide à la voix.
- **Imports non constatés après compaction sur le pod** : si c'est le cas, le hook `compact` porte
  la vue (moins de 10 000 caractères).
- **Deux écrivains sur le dépôt** : c'est déjà arrivé [M].
- **Jetons estimés** par caractères / 3,4 : l'écart avec le tokenizer de `qwen3` n'est pas mesuré
  [S].

### Questions pour Nicolas

1. ~~`wikichat-memory` devient-il un dépôt git (la maison de l'Assistant, plus un instantané) ?~~ Déjà tranché : non (alignement §10).
   Cela revient sur l'alignement §10.
2. Le pod est-il le seul écrivain ? Et que faire des 28 commits locaux et des 3 commits distants ?
3. Le graphe appartient-il à l'Atelier (recommandé), l'exécuteur des gardiens le lisant ?
4. La mémoire ne s'écrit-elle que par validation, ou certains types sont-ils validés d'office ?
5. La capitalisation nocturne : 20 conversations au plus, 30 000 jetons chacune, donc 600 000
   jetons par nuit au pire, sur `qwen3-8-27b`. Ce plafond convient-il ?
6. Compacter vers 90 000 jetons plutôt que vers 108 000 ?
7. Voix : aucun audio conservé, et une validation de mémoire à l'écran seulement ?
8. Fiche-t-on aussi les conversations des agents code (proposé) ?
9. Les projets d'essai (`m3-test`…) reçoivent-ils un statut « archivé », décidé par la personne ?

## 7. Évaluation

**Désirable.** L'Assistant sait où en est l'Atelier dès la première phrase, à l'écrit comme à
l'oral. Il retrouve ce qui a été dit sans le faire répéter, et il montre ce qu'il retient.

**Faisable.** Existent : hooks et lecture des projets, imports natifs, compaction par le relais,
`publish-memory`, `close_project`, `atelier_transcript`, `search_knowledge`, service vocal,
journal des gardiens. À construire : le calcul du graphe, le code des fiches, quatre outils, une
routine, une vue.

**Viable.** Le contexte fixe tourne autour de 20 000 jetons, quel que soit le nombre de projets. Un
tour sans nouveauté ajoute 0 jeton. Le modèle n'est appelé que la nuit et une fois par semaine,
avec des plafonds affichés.

**Cohérente.** Un seul graphe lu par l'Assistant, les gardiens, le panneau et wikichat (T7) ; une
seule identité, `session_id` ; un seul journal et une seule file « À valider » ; l'état des projets
reste dans les projets ; la voix rejoint la même conversation que l'écrit.

