# Structure d'un projet de l'Atelier

Proposition du 25/09/2026, **à valider**, tirée de l'étude du projet Lecteur
Grist (`~/work/projects/projet-sans-nom-5`, 65 commits, plusieurs agents
successifs, travail sur le poste et sur le pod). Complète
`docs/atelier-hebergement.md`.

## Ce qui existe (vague 1, 25/09)

Posé par l'équipe des fondations (branche `fondations`), dans
`atelier-src/mcp_gateway/atelier/commandes/` :

- **Schéma de `.atelier/projet.json`**, validé strictement (`structure.py`, pydantic, champs
  fermés) : `version` (1), `slug`, `titre`, `description`, `famille`, `gabarit: {nom, version}`,
  `fichiers: {etat, cahier, decisions}` (chemins relatifs, jamais hors du projet),
  `commandes: {preparer, tests, verifier}`, `chemins_proteges`, `vues_epinglees:
  [{artefact|connecteur, vue}]`, `creation: {par, le}`. Les champs que lit wikichat (`titre`,
  `description`, `slug`, `fichiers.etat`, `fichiers.decisions`) gardent leur nom.
- **Gabarit** posé à la création, sans jamais remplacer un fichier présent : `CLAUDE.md` (1re ligne
  `@.atelier/contexte.md`, ni état, ni date, ni adresse ; le socle `~/work/projects/CLAUDE.md` est
  lu en parent par Claude Code, l'importer en plus le chargerait deux fois), `ETAT.md` (tête : lot
  courant, dernière vérification, prochaine étape ; puis « À décider », « Demandé à l'Atelier »,
  « Fait et vérifié », « Non vérifié », « Écarts »), `README.md`, `docs/cahier-des-charges.md`,
  `docs/decisions/0001-structure-type.md`, `.gitignore`.
- **`.gitignore`** (`git_repos.py`) : `.atelier/*` sauf `!.atelier/projet.json` et
  `!.atelier/env.json`. Un `.gitignore` ancien qui ignore `.atelier/` entier n'est pas complété
  (git ne ré-inclut rien sous un dossier exclu) : ces projets se migrent en vague 2.
- **`atelier_projet_creer`** (réversible, inverse `atelier_projet_ranger`) : `titre`, `objectif`,
  `gabarit` (`application`, `donnees`, `service-mcp`, `document`, `vide`), `connecteurs[]`,
  `slug?`. Slug unique dérivé du titre (même règle que wikichat), dépôt git sur `main` avec un
  commit d'ouverture qui contient toute la structure, `.mcp.json` en références, trace
  `creation.par`. Carte : Voir, Annuler (ranger, jamais supprimer), preuve (commit, fichiers,
  vérification de la structure).
- **`atelier_projet_modifier`** (réversible, inverse : lui-même avec les valeurs d'avant) : `titre`,
  `description`, `connecteurs`. Ne touche que `projet.json` (commité seul, le travail en cours
  n'est pas emporté) et `.mcp.json`.
- **`projects.py`** : le titre affiché vient de `projet.json` s'il existe ; renommer par
  l'interface y écrit aussi (commit « Renommer le projet »).
- **`project_context.py`** : pour un projet dont `CLAUDE.md` importe `@.atelier/contexte.md`, le
  contexte généré va dans `.atelier/contexte.md` (ignoré) et non plus dans `CLAUDE.md`. Et il ne
  s'écrit plus que dans `~/work/projects/<slug>` (ou le dossier de l'Assistant) : jamais dans le
  `cwd` d'une conversation qui serait ailleurs (le `/tmp/CLAUDE.md` du 24/09).

Reste : `/reprendre`, `/verifier`, `/fin-de-lot` et `.claude/settings.json` du gabarit ; le hook
`SessionStart` et l'enrichissement de `contexte.md` (lot B) ; renommer un slug avec alias ; la
migration du Lecteur Grist ; `apps/manifeste.py` (`racine`, `donnees`, `preparer`, `entretien`,
`capacites`).

## Diagnostic (Lecteur Grist)

Ce qui aide : commits lisibles à l'infinitif ; provenance du code recopié
tracée (`RETOUCHES.md`) ; preuves chiffrées (`serveur/MESURES.md`) ;
vérificateurs qui font foi ; distinction « fait » / « non vérifié ».

Ce qui perd ou se désynchronise :

| # | Constat |
|---|---|
| D1 | `CLAUDE.md` du projet **non suivi par git** : les règles n'ont pas d'histoire (alors que `git_repos.py` dit qu'il se versionne). |
| D2 | La consigne sur le pod est en retard de cinq lots (« aucun serveur ») et se contredit. |
| D3 | La consigne du projet vit dans le dépôt de l'Atelier (`docs/consignes/`) et se recopie à la main (409 lignes d'un côté, 204 de l'autre). |
| D4 | Cette consigne est devenue un journal : sections non chronologiques, rien ne dit ce qui est courant. |
| D5 | L'état du projet est tenu à quatre endroits, dont deux hors du projet ; versions contradictoires (grist-core 1.7.3 contre 1.7.19). |
| D6 | Adresses périmées (`/v1/artifacts/…`) dans le readme, la consigne, `publier.sh`. |
| D7 | La section générée par l'Atelier dans `CLAUDE.md` est elle aussi en retard, sans alerte. |
| D8 | La vue du coordinateur wikichat est fausse (« Projet sans nom », pas de décisions, audit périmé). |
| D9 | Aucun commit ne dit quel agent ou quelle conversation l'a écrit. |
| D10 | Deux copies de travail (poste et pod), synchronisées à la main, sans remote. |
| D11 | Copies générées que git ne fige pas (page publiée ignorée ; code recopié entre marqueurs). |
| D12 | Données d'essai et venv codés en dur dans `artefact.json` : cassent dès qu'on fige une version. |
| D13 | Pas d'entrée unique pour vérifier : deux racines de tests, deux dossiers d'outils, trois fichiers de dépendances. |
| D14 | `.claude/` sans savoir-faire (ni commandes, ni sous-agents, ni garde-fous). |
| D15 | Le nom `projet-sans-nom-5` ne dit rien et sert à la fois de dossier, d'adresse, de nom wikichat et de préfixe d'agents. |

**Cause racine** : ni fichier d'état unique, ni règle « une information = un
seul endroit ». Chaque agent a écrit l'état là où il était, et la seule partie
générée ne s'actualise pas.

## Structure type

```
<slug>/                          slug parlant (lecteur-grist)
├── CLAUDE.md                    SUIVI. Écrit par le projet, ≤ 100 lignes : identité, fil de lecture,
│                                  règles propres. 1re ligne : @.atelier/contexte.md. Jamais d'état,
│                                  de date ni d'adresse.
├── README.md                    SUIVI. Pour les humains.
├── ETAT.md                      SUIVI. SEUL endroit de l'état : lot courant, dernière vérification,
│                                  prochaine étape, À décider (personne), Demandé à l'Atelier ;
│                                  puis fait/vérifié, non vérifié, écarts. Réécrit, pas complété.
├── docs/
│   ├── cahier-des-charges.md    SUIVI. L'intention de la personne ; prime sur tout.
│   ├── conception/*.md          SUIVI. Comment c'est construit.
│   ├── decisions/NNNN-*.md      SUIVI. Décisions courtes (contexte, décision, conséquences, statut).
│   ├── mesures/*.md             SUIVI. Preuves datées.
│   └── journal/AAAA-MM-JJ-*.md  SUIVI. Compte rendu de fin de lot.
├── <sources>/                   SUIVI. Code ; code recopié marqué (RETOUCHES.md).
├── outils/                      SUIVI. Construire, vérifier, … + hooks git.
├── tests/                       SUIVI.
├── artifacts/<nom>/
│   ├── artefact.json            SUIVI. type, racine|commande, donnees, preparer, entretien, capacites.
│   ├── .auteur                  IGNORÉ (posé par l'Atelier).
│   └── donnees/                 IGNORÉ, SAUVEGARDÉ. Jamais dans git ni dans une version figée.
├── .atelier/
│   ├── projet.json              SUIVI. Déclaration machine du projet (titre, description, fichiers
│   │                              d'état et de cahier, commandes preparer/tests/verifier, chemins protégés).
│   ├── env.json                 SUIVI (références seulement).
│   └── contexte.md              GÉNÉRÉ à chaque tour, IGNORÉ.
├── .claude/
│   ├── settings.json            SUIVI : permissions et hooks du projet.
│   ├── commands/*.md            SUIVI : commandes du projet.
│   └── agents/*.md              SUIVI : sous-agents du projet.
└── .wikichat/                   IGNORÉ : état du coordinateur, dérivé du dépôt, jamais source.
```

Règle de rangement : **git** porte le code, les manifestes et la connaissance
durable ; **`donnees/`** ce que l'artefact produit ; **`.atelier/contexte.md`
et `.wikichat/`** ce qui se régénère ; **wikichat** la coordination du moment.

## Fil d'entrée d'un agent (une responsabilité par étape)

1. Socle `~/work/projects/CLAUDE.md` : règles communes, posé par l'Atelier avec
   son empreinte, jamais à la main.
2. `CLAUDE.md` du projet : identité, fil de lecture, règles propres.
3. `.atelier/contexte.md` (généré à chaque tour) : slug, titre, artefacts,
   adresses réelles, brouillon/production et version, propositions en attente,
   version du socle, **alertes** (`CLAUDE.md` non suivi, `ETAT.md` périmé,
   copie générée plus vieille que sa source, `donnees/` suivi par erreur).
4. `ETAT.md` : où on en est.
5. `docs/cahier-des-charges.md` : ce qui est voulu.
6. `docs/decisions/` : pourquoi c'est ainsi.
7. `docs/conception/` : comment c'est construit (partie touchée).
8. `artifacts/*/artefact.json` : comment c'est servi et entretenu.

**La consigne d'un projet vit dans le projet, et nulle part ailleurs.** Le
dépôt de l'Atelier ne garde que le socle et les consignes de mécanismes
(Chrome, voix…). Ce qu'un projet demande à l'Atelier va dans le carnet de
l'Atelier, avec un identifiant repris dans `ETAT.md`. Un agent qui travaille
pour un projet depuis ailleurs ouvre une conversation dans le projet ou pousse
une branche ; il n'écrit pas l'état du projet dans un autre dépôt.

## Harnais par participant

| Acteur | Voit | Peut | Ne peut pas | Trace |
|---|---|---|---|---|
| Agent de code | socle, CLAUDE.md, contexte, ETAT, commandes, brouillons | éditer, lancer le brouillon, commit local, `atelier_artefact_*`, proposer | pousser, promouvoir, exposer, accorder, toucher les données de production, éditer un chemin protégé | commits avec `Agent:`/`Conversation:`/`Lot:` ; ETAT réécrit en fin de lot ; journal ; décisions ; propositions |
| Sous-agent | ce que le parent lui passe | lecture et vérification | écrire du code | rapport au parent |
| Routine d'entretien | projet.json, entretien, journaux | tests et vérifications sur le brouillon, sonde de production ; en cas d'échec, conversation sur une branche | modifier `main`, promouvoir (sauf autorisation écrite) | panneau, note wikichat, commits de branche |
| Agent de l'Atelier (compositions, MCP distant) | `atelier_projet_etat` | ouvrir et piloter une conversation dans le projet | écrire directement dans le projet | la conversation |
| La personne (interface) | carte du projet : titre, tête d'ETAT, artefacts, propositions, À décider | promouvoir, revenir, exposer, accorder, trancher | — | étiquettes `prod/…`, statut des décisions |

Commandes standard déposées par l'Atelier : `/reprendre` (résume ETAT,
cahier, décisions, commits depuis le dernier jalon ; dit la prochaine étape),
`/verifier` (commandes de `projet.json`), `/fin-de-lot` (vérifie, réécrit
ETAT, journal, décisions, commit, étiquette `jalon/<lot>`, s'arrête),
`/proposer <artefact>`. Commandes et sous-agents propres au projet dans
`.claude/`. Hooks : au démarrage, tête d'ETAT et alertes ; refus d'éditer les
chemins protégés ; pre-commit versionné (copies générées à jour, pas de
secret).

## Processus sur l'exemple

Reprendre (`/reprendre`) → développer sur une branche, en brouillon →
`/verifier` (+ parité Grist) → `/fin-de-lot` → `/proposer` → la personne
promeut : étiquette `prod/<artefact>/<n>`, version figée, `preparer`,
sauvegarde des données, bascule → l'entretien surveille et, en cas d'échec,
ouvre une conversation sur une branche → un autre agent reprend par
`/reprendre`, sans rien redécouvrir hors du dépôt.

## Nommage

- Projet : slug (identifiant, dossier, adresse) distinct du titre
  (`projet.json`). `projet-sans-nom-N` provisoire seulement ; renommage par un
  outil qui déplace, garde un alias, redirige les anciennes adresses et
  renomme dans wikichat. **Lecteur Grist : `projet-sans-nom-5` → `lecteur-grist`
  maintenant**, avant toute exposition.
- Artefacts : nom du rôle (`lecteur`) ; un artefact serveur = une instance par
  document (`application` → `essai` ; demain `crm`, `saint-martin`).
- Étiquettes : `prod/<artefact>/<n>`, `jalon/<lot>`.

## Migration du Lecteur Grist (un commit par étape)

1. Suivre `CLAUDE.md` tel quel.
2. Créer `ETAT.md` en fusionnant les quatre états existants (et les retirer
   ailleurs) ; « À décider » (OIDC, hôte des widgets) et « Demandé à l'Atelier ».
3. `docs/cahier-des-charges.md`, `docs/conception/application.md` (depuis
   `docs/lecteur-grist-application.md`, version corrigée) et
   `docs/conception/lecteur.md`.
4. Premières décisions : asm.js plutôt que wasm ; serveur Python et moteur
   gristlabs en sous-processus ; moteur recopié sans retouche ; règle non
   évaluable ; copie autonome derrière l'Atelier ; jeton de widget en lecture
   seule ; exemple CRESO laissé en l'état.
5. `serveur/MESURES.md` → `docs/mesures/`.
6. Réécrire `CLAUDE.md` (≤ 100 lignes, sans état ni adresse) ; `README.md` sans
   adresses ni historique.
7. Ranger le code : `lecteur/index.html`, `outils/{widgets,verifier,essais,parite}/`,
   `tests/lecteur/`.
8. Artefacts : `lecteur` servi par `racine` (fin de `publier.sh` quand
   l'Atelier le permet) ; `application` → `essai`, `dossier/` → `donnees/`,
   `{donnees}`, `preparer`, `entretien`.
9. `.atelier/projet.json`, `.claude/settings.json`, commandes et sous-agents du
   projet, hook pre-commit, `.gitattributes`.
10. Étiquettes `jalon/L0` à `jalon/L5`, puis `prod/lecteur/1`.
11. Renommer en `lecteur-grist`.
12. Un remote GitHub privé : fin de la double copie poste/pod.

## Ce qu'il faut changer dans l'Atelier

- `project_context.py` : écrire `.atelier/contexte.md` (ignoré) au lieu d'une
  section de `CLAUDE.md` ; n'ajouter à `CLAUDE.md` que la ligne d'import ;
  enrichir le contexte (titre, artefacts, versions, propositions, socle,
  alertes).
- `git_repos.py` : `.gitignore` (`.atelier/*` sauf `projet.json` et
  `env.json`, `artifacts/*/donnees/`, `artifacts/*/.auteur`, `.venv/`) ;
  gabarit de projet à la création (CLAUDE.md, ETAT.md, README.md, docs/,
  projet.json, settings.json).
- `projects.py` : titre depuis `projet.json`, slug proposé, alias, renommage.
- `apps/manifeste.py` : `racine` pour les pages, `donnees`/`{donnees}`,
  `preparer`, `entretien`, `capacites`.
- `outils_conversation.py` : `atelier_projet_etat`, `atelier_artefact_proposer`,
  `atelier_projet_renommer`.
- Socle : déployé par l'installation avec son empreinte ; section « Fil
  d'entrée et traces ».
- `docs/consignes/` : ne garder que socle et mécanismes.
- wikichat : dériver description, décisions et questions ouvertes de
  `projet.json`, `docs/decisions` et d'`ETAT.md`.
