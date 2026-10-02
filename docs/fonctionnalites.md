# Fonctionnalités de l'Atelier : guide de référence

État au 26/09/2026 : vagues 1 à 3 et leurs correctifs, reprise de l'interface (v4) comprise. Ce guide dit, pour
chaque fonctionnalité, à quoi elle sert, comment s'en servir (la personne, dans l'interface ; un
agent, par quel outil et avec quel profil), ce qu'elle ne fait pas, où est le code et où est la
doc détaillée. Il a été vérifié contre le code ; quand un document plus ancien le contredit,
c'est le code (et ce guide) qui fait foi.

Les noms de vues cités (Code, Assistant, Connecteurs, Agents, À valider, Journal, Ma mémoire)
sont ceux de l'interface actuelle. Ils sont **susceptibles d'évoluer** : une reprise de
l'interface est en cours. Ce guide décrit les usages, pas la mise en page.

Statuts employés :

- **en service** : déployé et vérifié en réel sur le pod ;
- **intégré** : dans `main`, testé par la suite, essayé sur le pod, avec des points encore non
  vérifiés en réel (listés dans la doc de la brique) ;
- **pas fait** : prévu par la vision (`docs/vision/`), absent du code.

Pour un agent, la version courte et opérationnelle de ce guide est le socle des consignes,
[`atelier-src/mcp_gateway/atelier/consignes/socle.md`](../atelier-src/mcp_gateway/atelier/consignes/socle.md).

---

## Sommaire

1. [Vue d'ensemble](#1-vue-densemble)
2. [Projets et conversations](#2-projets-et-conversations)
3. [Profils d'accès](#3-profils-daccès)
4. [L'Assistant](#4-lassistant)
5. [Commandes de l'Atelier](#5-commandes-de-latelier)
6. [« À valider », journal, annulation](#6--à-valider--journal-annulation)
7. [Créations, panneau, bureaux](#7-créations-panneau-bureaux)
8. [Le navigateur de l'agent](#8-le-navigateur-de-lagent)
9. [Connecteurs et passerelle MCP](#9-connecteurs-et-passerelle-mcp)
10. [wikichat](#10-wikichat)
11. [Mémoire](#11-mémoire)
12. [Gardiens et réparateurs](#12-gardiens-et-réparateurs)
13. [Onyxia et déploiement d'un projet](#13-onyxia-et-déploiement-dun-projet)
14. [Vérificateur de cohérence](#14-vérificateur-de-cohérence)
15. [Voix](#15-voix)
16. [Combinaisons d'usage](#16-combinaisons-dusage)
17. [Ce qui n'existe pas encore](#17-ce-qui-nexiste-pas-encore)
18. [Repères : processus, ports, scripts](#18-repères--processus-ports-scripts)

---

## 1. Vue d'ensemble

L'Atelier fait travailler Claude Code sur un pod SSPCloud, un pod par personne. Deux maisons
se partagent le travail (`docs/vision/architecture-transverse.md` §0) :

- **l'Atelier** tient l'état opérationnel : conversations et tours, connecteurs et secrets par
  référence, créations servies, navigateur, commandes, journal, « À valider », interface ;
- **wikichat** tient la connaissance et la coordination : registre des projets, cartographie,
  connaissance, mémoire, messagerie entre agents, agents planifiés et automates.

Chacun lit l'autre par API, aucun ne recopie les données de l'autre.

**Les acteurs** :

| Acteur | Qui | Profil |
|---|---|---|
| Personne | la propriétaire du pod | l'interface ; seule à accepter, activer, accorder, publier |
| Assistant | les conversations de son dossier (`~/work/wikichat-memory`) | `assistant` |
| Agent code | toute conversation d'un projet | `code` |
| Agent lancé | un agent démarré par l'Atelier pour wikichat, un gardien ou l'Assistant | `code`, avec plafonds |
| Gardien | contrôles en code, sans modèle, dans un processus à part | aucun outil de modèle |
| Application | une création en mode serveur | ce que déclare son `artefact.json` |

**Les vues de l'interface** (port 8787 du service Onyxia) :

| Vue | Ce qu'on y fait |
|---|---|
| Code | les conversations, rangées par projet ; le fil, le composeur, le mode, le panneau |
| Assistant | les conversations de l'Assistant, même fil et même panneau que Code |
| Connecteurs | le pool de connecteurs, leurs outils, les compositions, l'accord d'un secret |
| Agents | agents planifiés, gardiens, tâches automatiques, agents lancés en cours et récents |
| À valider | la file unique de ce qui attend l'accord de la personne (badge du nombre en attente) |
| Journal | qui a fait quoi, sur quoi, avec quel résultat |
| Ma mémoire | ce que l'Atelier retient de la personne, avec « Corriger » et « Oublier » |

---

## 2. Projets et conversations

**En service.**

**À quoi ça sert.** Un projet est un dossier de travail sous `~/work/projects/<slug>`, dépôt git
dès sa création. Une conversation est un fil avec un agent code dans ce projet. La même
conversation s'ouvre dans l'interface, dans VS Code et au terminal, avec les mêmes outils.

**La personne.**

- Dans Code : une nouvelle conversation crée son projet à l'envoi du premier message ; on peut
  aussi créer, renommer, ranger et ressortir projets et conversations (rien n'est effacé).
- Le fil montre les textes, les outils appelés (résultats repliés au-delà de 1 500 caractères
  ou 25 lignes), les demandes d'autorisation (cartes « Autoriser / Refuser », avec « toujours
  pour ce fil ») et les questions à choix de l'agent.
- On peut écrire pendant qu'un tour travaille : le message se met en file. On peut joindre des
  fichiers. Plusieurs écrans (un autre onglet, VS Code) regardent la même conversation sans la
  déclencher.
- « Ouvrir dans VS Code » ouvre code-server sur la conversation elle-même ; ce qui s'y dit
  apparaît en direct dans l'interface, et inversement.
- Le bouton « Échanges » paraît quand la conversation a des fils wikichat ouverts avec d'autres
  agents.

**Modes de travail.** Une seule liste, identique sur toutes les surfaces :

| Mode (CLI) | Libellé | Effet |
|---|---|---|
| `plan` | Plan | l'agent réfléchit et propose, sans rien modifier |
| `default` | Demande | il demande avant d'écrire ou d'exécuter |
| `acceptEdits` | Édite | il modifie les fichiers sans demander (défaut du service) |
| `bypassPermissions` | Sans garde-fou | il agit sans rien demander, y compris hors du projet ; confirmation demandée |

Un défaut par projet (`.claude/settings.local.json`, `PUT /v1/projets/{slug}/mode`) et un choix par
conversation qui le remplace (magasin de l'extension VS Code, sous l'identifiant du CLI) : choisir
un mode dans l'interface le met aussi dans VS Code et au terminal. Un onglet VS Code déjà ouvert
garde son mode jusqu'à sa fermeture ; l'interface le signale sous la saisie. Le gardien Sécurité
signale tout processus `claude` sans garde-fou sans fiche de l'Atelier.

**Mêmes outils partout.** Chaque projet reçoit un `.mcp.json` en références (jamais de secret),
écrit par l'Atelier à partir de son profil ; les tours de l'Atelier lisent un fichier effectif
équivalent. VS Code et le terminal passent par l'enveloppeur `atelier-claude-vscode`, qui charge
`~/work/.secrets/claude-env.sh` et applique le mode ; `atelier-entetes-mcp` dit au serveur
`atelier` quelle conversation l'appelle. Le vérificateur de cohérence (§14) contrôle l'égalité.

**Un processus par conversation**, gardé entre les tours : il s'éteint après 10 minutes de silence
(`cli_inactivite_s`), trois au plus à la fois (`cli_processus_max`). Le modèle passe par le relais
LLM local (port 8790), qui porte la compaction et corrige les réponses de la passerelle de modèles.

**Structure type d'un projet** (`atelier_projet_creer`, ou `atelier_projet_structurer` pour un
projet ancien) : `CLAUDE.md` dont la première ligne importe `@.atelier/contexte.md`, `ETAT.md`
(seul endroit de l'état : lot courant, « À décider », « Demandé à l'Atelier »…), `README.md`,
`docs/cahier-des-charges.md`, `docs/decisions/`, `.atelier/projet.json` (déclaration machine :
titre, commandes, chemins protégés, vues épinglées, déploiement), `.gitignore`.

**Ce que lit un agent en entrant.** Claude Code charge le `CLAUDE.md` du projet et celui du
dossier parent :

1. `~/work/projects/CLAUDE.md` : le socle, commun à tous les projets
   ([`atelier-src/mcp_gateway/atelier/consignes/socle.md`](../atelier-src/mcp_gateway/atelier/consignes/socle.md)),
   posé depuis le code déployé par `install/atelier-init.sh` et à chaque démarrage de l'Atelier
   (`atelier-relancer` compris) : écriture atomique, et un fichier modifié à la main est gardé
   en copie datée sous `~/work/.atelier-etat/socle/`, avec une ligne au journal, avant d'être
   remplacé (`atelier/socle.py`). Il ne répète pas ce que dit la section suivante ;
2. la section `atelier:contexte` (ou `.atelier/contexte.md` pour un projet à la structure type),
   régénérée par l'Atelier : projet, liste exacte des outils `atelier_*` du profil, wikichat,
   Onyxia, manière de montrer ses créations ;
3. le reste du `CLAUDE.md` du projet, qui lui appartient ;
4. le briefing et le courrier de wikichat, par ses hooks `SessionStart` et `UserPromptSubmit`.

**Un agent.** Un agent code ne gère ni projets ni conversations. L'Assistant le fait par les
commandes `atelier_projet_*` et `atelier_conversation_*` (§5).

**Ce que ça ne fait pas.**

- La publication sur GitHub (`POST /v1/projects/{slug}/git/publish`, commande réservée
  `atelier_projet_publier`) n'a pas de bouton ; elle demande `~/work/.secrets/github_token` et
  `ATELIER_GITHUB_OWNER`.
- Une conversation ouverte directement dans VS Code, jamais vue par l'Atelier, n'a pas de fiche :
  ses outils `atelier_*` reposent sur le projet annoncé par son `.mcp.json`.

**Code** : `atelier/sessions.py`, `harness.py`, `projects.py`, `git_repos.py`,
`project_context.py`, `modes_permission.py`, `modes_routes.py`, `decisions.py`, `vscode_handoff.py`,
`mcp_sync.py`, `commandes/structure.py`, `commandes/migration.py` ; `web/js/views/code-*.js`.
**Doc** : [`structure-projet.md`](structure-projet.md),
[`atelier-vscode-passage-de-main.md`](atelier-vscode-passage-de-main.md),
[`vision/profils-acces.md`](vision/profils-acces.md) (« Mode de permission »).

---

## 3. Profils d'accès

**Intégré** (vague 1 à 3 ; contrat [`vision/profils-acces.md`](vision/profils-acces.md)).

**À quoi ça sert.** Ce qu'un agent reçoit dépend de son profil, jamais de la surface. Le profil
est filtré **à la source**, par le serveur qui expose les outils, à la liste (`tools/list`) et à
l'appel (`tools/call`).

| Brique | Profil `code` (agent code, agent lancé) | Profil `assistant` |
|---|---|---|
| Outils natifs | tous sauf WebSearch | lecture, écriture limitée à `notes/` ; Bash, WebSearch, sous-agents et planification refusés |
| Serveur `atelier` | **10 outils** : `atelier_artefacts`, `atelier_artefact_creer`, `_verifier`, `_demarrer`, `_arreter`, `_journal`, `atelier_montrer`, `atelier_navigateur_ouvrir`, `atelier_rappel`, `atelier_fiche` ; projet imposé par la conversation | toutes les commandes exposées, plus `gateway_find_tools` et `gateway_call_tool` |
| Connecteurs | ceux choisis pour le projet | tout le pool, par les méta-outils |
| wikichat | 26 outils bornés au projet (état, notes, mémoire, connaissance, messagerie, tâches, idées) ; ni lancement d'agent, ni trigger, ni routine, ni vue globale | noyau de 10 outils ; le reste par le catalogue de la passerelle |
| Navigateur | une fenêtre Chrome à lui | idem |
| Onyxia | seulement les outils du pod déclaré par le projet (§13) | les 24 outils ; `expose_public` et `unexpose_public` réservés |

**Qui décide du profil** (`commandes/profils.py`, `profil_effectif`) : la fiche de la
conversation, côté serveur. Une conversation de l'Assistant donne `assistant`, toute autre
`code` ; l'en-tête `X-Atelier-Profil` ne peut que restreindre. Une conversation inconnue (VS Code,
terminal) reçoit `code` et son projet vient de `X-Atelier-Projet`.

**Ce que ça ne fait pas.** La clé de la porte `/mcp` est celle du propriétaire, que les agents du
pod peuvent lire : un agent qui la lit et omet l'en-tête de conversation garde un accès complet.
Le fermer demande des capacités courtes par conversation (décision « trousseau », hors de ces
vagues).

**Code** : `atelier/commandes/profils.py`, `mcp_endpoint.py`, `mcp/gateway.py`, `mcp_sync.py`,
`assistant.py` ; wikichat `src/profils.mjs`. **Doc** : [`vision/profils-acces.md`](vision/profils-acces.md).

---

## 4. L'Assistant

**Intégré** (vague 3).

**À quoi ça sert.** La porte d'entrée de la personne : il connaît l'Atelier (la carte), règle ses
objets par les commandes, et confie le travail dans les projets à des agents code.

**La personne.** Vue Assistant : « Nouvelle conversation », puis on parle. Le réglage « Ouvrir
l'Atelier sur l'Assistant » (désactivé par défaut) en fait l'accueil. Chaque commande qui agit
laisse dans le fil une **carte d'action** construite par la commande (jamais rédigée par le
modèle) : titre, résumé, preuve, « Voir », « Annuler ». Une commande engageante laisse un aperçu
avec « Oui ». Un « fait » annoncé sans carte est marqué « non vérifié ».

**Comment il travaille.**

- **Contexte toujours présent (C1)** : son `CLAUDE.md` importe `atelier/consignes.md`,
  `outils.md`, `carte.md` (vue synthétique de la carte) et `a-valider.md`, régénérés avant chaque
  tour et relus après compaction. Environ 16 000 unités d'entrée mesurées.
- **Commandes `atelier_*`** déclarées, appelées par leur nom.
- **Tout le reste** (connecteurs, wikichat hors noyau, Onyxia) par deux méta-outils :
  `gateway_find_tools` (chercher, avec deux formulations dont une en anglais, avant de conclure
  qu'une capacité manque) puis `gateway_call_tool(name, arguments)` avec un nom exact rendu par la
  recherche. La classe d'action est vérifiée par le serveur à l'appel : le méta-outil ne
  contourne rien.
- **Faire ou confier** : il agit seul si une commande existe, touche un objet de l'Atelier, tient
  en quelques appels, a une inverse et rend une preuve. Sinon il **délègue** :
  `atelier_lancer_agent(projet, message)` (engageante : aperçu, puis « Oui » de la personne),
  suit par `atelier_lancements`, rend compte depuis la carte d'action.
- Il peut refuser une proposition de « À valider », jamais l'accepter.

**Ce que ça ne fait pas.** Il n'écrit pas dans les projets (seulement dans son dossier `notes/`),
n'active pas d'agent, n'accorde pas de secret, ne publie pas. Il n'a pas de voix aujourd'hui
(§15). Un outil `wikichat__*` appelé par `gateway_call_tool` part sous le nom
`passerelle-atelier`, pas sous celui de la conversation.

**Code** : `atelier/assistant.py`, `commandes/`, `mcp/gateway.py`, `tool_search.py`
(mots d'intention), `lancements.py` ; `web/js/views/assistant*.js`.
**Doc** : [`vision/assistant-synthese.md`](vision/assistant-synthese.md),
[`vision/assistant-role.md`](vision/assistant-role.md),
[`vision/assistant-contexte.md`](archives/vision/assistant-contexte.md).

---

## 5. Commandes de l'Atelier

**En service** (vague 1, complétées en vagues 2 et 3).

**À quoi ça sert.** L'interface, l'Assistant et les agents agissent sur les objets de l'Atelier
par **les mêmes commandes**, exposées en outils MCP (`/mcp`), en HTTP
(`GET /v1/commandes`, `POST /v1/commandes/<nom>`) et par le catalogue de la passerelle. Chaque
commande déclare son objet, sa **classe**, son **inverse**, ses règles, et rend une carte
d'action. La vérification a lieu dans `Catalogue.executer`, à chaque appel.

**Les classes.**

| Classe | Appelée par un modèle | Appelée par la personne |
|---|---|---|
| `lecture` | exécutée, sans carte ni ligne au journal (sauf refus et erreurs) | exécutée |
| `reversible` | exécutée ; carte avec « Annuler » | idem |
| `engageante` | **aperçu et jeton**, rien n'est fait ; le « Oui » de la personne confirme (jeton d'usage unique, 10 minutes, mêmes arguments) | idem, ou confirmation du jeton d'un agent |
| `reservee` | **refusée** (non exposée en MCP) | exécutée, depuis l'interface |

La clé du propriétaire en HTTP compte comme un modèle pour les commandes réservées : seule la
session de l'interface est « la personne ».

**Le catalogue** (53 commandes ; `GET /v1/commandes` fait foi). Profil `code` : les 10 marquées
« code » ; profil `assistant` : toutes les exposées.

| Objet | Commande | Classe | Inverse | Code |
|---|---|---|---|---|
| projet | `atelier_projets` | lecture | | |
| | `atelier_projet_creer` | reversible | `atelier_projet_ranger` | |
| | `atelier_projet_modifier` | reversible | elle-même | |
| | `atelier_projet_ranger` / `_ressortir` | reversible | l'une l'autre | |
| | `atelier_projet_structurer` | engageante (`a_blanc` : lecture) | `atelier_projet_destructurer` | |
| | `atelier_projet_destructurer` | reversible | `atelier_projet_structurer` | |
| | `atelier_projet_deployer_declarer` | engageante | elle-même | |
| | `atelier_projets_lier` | reversible | elle-même | |
| | `atelier_connecteur_choisir` | reversible | elle-même | |
| | `atelier_projet_publier` | **reservee** | | |
| | `atelier_reparation_fusionner` | **reservee** | | |
| conversation | `atelier_conversations`, `atelier_suivre`, `atelier_transcript` | lecture | | |
| | `atelier_ouvrir` | reversible | `atelier_conversation_ranger` | |
| | `atelier_envoyer` | reversible | `atelier_interrompre` | |
| | `atelier_interrompre` | reversible | | |
| | `atelier_conversation_ranger` / `_ressortir` | reversible | l'une l'autre | |
| autorisation | `atelier_decider` | engageante (`deny` : reversible) | | |
| création | `atelier_artefacts`, `atelier_artefact_verifier`, `atelier_artefact_journal` | lecture | | oui |
| | `atelier_artefact_creer` | reversible | | oui |
| | `atelier_artefact_demarrer` / `_arreter` | reversible | l'une l'autre | oui |
| vue, accès | `atelier_montrer` | lecture | | oui |
| | `atelier_navigateur_ouvrir` | reversible | | oui |
| mémoire | `atelier_rappel`, `atelier_fiche` | lecture | | oui (son projet) |
| | `atelier_memoire` | lecture | | |
| | `atelier_memoire_proposer` | reversible | `atelier_a_valider_refuser` | |
| | `atelier_memoire_retenir`, `_corriger`, `_oublier` | **reservee** | oublier / corriger / retenir | |
| agent | `atelier_agent_creer` | reversible | `atelier_agent_supprimer` | |
| | `atelier_agent_modifier` | reversible | elle-même | |
| | `atelier_agent_supprimer` | reversible | `atelier_agent_creer` | |
| | `atelier_agent_desactiver` | reversible | `atelier_agent_activer` | |
| | `atelier_agent_activer` | **reservee** | `atelier_agent_desactiver` | |
| | `atelier_lancer_agent` | engageante | | |
| | `atelier_lancements` | lecture | | |
| connecteur | `atelier_connecteur_ajouter` | engageante | `atelier_connecteur_retirer` | |
| | `atelier_connecteur_retirer` | reversible | `atelier_connecteur_ajouter` (reprise) | |
| | `atelier_connecteur_accorder` | **reservee** | | |
| carte | `atelier_carte` | lecture | | |
| validation | `atelier_a_valider` | lecture | | |
| | `atelier_a_valider_refuser` / `_rouvrir` | reversible | l'une l'autre | |
| | `atelier_a_valider_accepter` | **reservee** | | |
| journal, action | `atelier_journal` | lecture | | |
| | `atelier_annuler` | reversible | | |

`atelier_envoyer`, `atelier_transcript`, `atelier_suivre` et `atelier_ouvrir` ne sont plus
déclarées à l'Assistant (il délègue par `atelier_lancer_agent`) mais restent joignables par ses
méta-outils.

**Règles notables.** Un agent créé naît **désactivé**, avec un budget obligatoire (`tours`,
`par_jour` de 1 à 24) ; une modification par un modèle le désactive. Un connecteur s'ajoute sans
aucun secret en argument ; le secret s'accorde ensuite, par son **nom** de fichier, par la
personne. `atelier_projet_creer` pose la structure type et commite.

**Ce que ça ne fait pas.** Pas encore de règle « plus de trois actions à la suite = engageante »
côté serveur (c'est une consigne de l'Assistant) ; pas de coût dans l'aperçu ; pas d'inverse pour
`atelier_artefact_creer`. Les gestes sur les gardiens passent encore par
`POST /v1/automates/action`, hors catalogue.

**Code** : `atelier/commandes/` (`modele.py`, `catalogue.py`, `existants.py`, `natives.py`,
`agents.py`, `connecteurs.py`, `liens.py`, `migration.py`, `deploiement.py`, `carte.py`,
`rappel.py`, `routes.py`). **Doc** : [`vision/architecture-transverse.md`](vision/architecture-transverse.md) §1.8.

---

## 6. « À valider », journal, annulation

**En service** (vague 1 pour le modèle et l'API, vague 2 pour les écrans).

**« À valider »** : la liste unique de ce qui attend l'accord de la personne. Elle reçoit :

- les propositions des gardiens et de leurs réparateurs (une branche à fusionner) ;
- la fin de travail d'un agent lancé sur une branche ;
- les propositions de mémoire (préférences, interprétations) ;
- les propositions des agents planifiés du Pilote de wikichat (lues sans migration, identifiant
  `pilote:<agent>:<action>`) ;
- toute action qu'un modèle ne peut pas faire seul et qu'il dépose pour la personne.

*La personne* : vue À valider ; chaque proposition dit ce qui était constaté, ce qu'accepter fera,
et porte « Accepter » (réservé à la personne, exécute l'action proposée par le catalogue) et
« Refuser » (motif facultatif). *L'Assistant* : `atelier_a_valider`, `atelier_a_valider_refuser`,
`_rouvrir` ; jamais accepter. *Un agent code* : aucun outil ; il dit ce qui revient à la personne
et le note dans `ETAT.md`. Stockage : un fichier par proposition dans
`~/work/.atelier-etat/a-valider/` ; une même empreinte en attente n'est pas dupliquée.

**Journal unique** : `~/work/.atelier-etat/journal/AAAA-MM.jsonl`, une ligne par événement
(commande, contrôle de gardien, geste, lancement, validation, résumé de mémoire…), avec son acteur
(`conversation:<id>`, `personne`, `cle-proprietaire`, `gardien:<nom>`…), son résultat, son coût,
et l'inverse quand il y en a une. Aucune valeur secrète : les valeurs de `claude-env.sh` sont
remplacées partout. *La personne* : vue Journal, en phrases, filtrable par projet, acteur et source.
*L'Assistant* : `atelier_journal`. API : `GET /v1/journal`.

**Annulation** : « Annuler » sur une carte d'action appelle `atelier_annuler(action)`, qui
applique une fois l'inverse notée au journal. Quand l'auteur de l'action ou la personne annule,
son geste vaut accord pour une inverse engageante ; une inverse réservée reste refusée à un modèle.

**Ce que ça ne fait pas.** Pas d'avant/après visuel des créations (attend J8) ; pas de
notification hors de l'Atelier.

**Code** : `commandes/a_valider.py`, `commandes/journal.py`, `commandes/natives.py`,
`commandes/routes.py` ; `web/js/views/a-valider.js`, `journal.js`, `assistant-cartes.js`.
**Doc** : [`vision/architecture-transverse.md`](vision/architecture-transverse.md) §1.7 et §1.8.

---

## 7. Créations, panneau, bureaux

### 7.1 Créations

**En service.**

**À quoi ça sert.** Montrer ce qu'un agent fabrique sans jamais ouvrir de port : une création =
un dossier `artifacts/<nom>/` du projet = une adresse
`https://<hôte des applications>/<projet>/<nom>/`, derrière la connexion de l'Atelier. L'hôte des
applications (port 8788) est une **autre origine** que l'Atelier : rien de ce qu'un agent produit
ne s'exécute dans l'origine de l'Atelier.

| Mode | Ce que c'est | Ce que fait l'Atelier |
|---|---|---|
| autonome | des fichiers (`index.html` à la racine, tout embarqué) | les sert en bac à sable (CSP, sans cookie ni stockage) ; écriture par `PUT` si `artefact.json` déclare `"edition": true` |
| serveur | un processus déclaré par `artefact.json` (`commande` avec `{port}`, `sante`, `protocoles`, `repertoire`, `secrets`) | attribue le port (19000-19099), lance, sonde, redémarre, arrête après inactivité (30 min), relaie HTTP, WS et SSE déclarés ; journal dans `~/work/logs/apps/` |

*Un agent code* : `atelier_artefact_creer(nom, mode?)`, `atelier_artefact_verifier`,
`_demarrer`, `_arreter`, `_journal`, `atelier_artefacts` ; sans MCP, `~/work/bin/atelier-app`.
Il n'agit pas sur la création d'une autre conversation (`forcer` sur demande). *La personne* :
dans le panneau, le catalogue des créations du projet (mode, état, auteur ; Montrer, Démarrer,
Arrêter, Journal, Copier l'URL).

**Codes de passage et portée.** Les deux origines ne partagent aucun cookie. Pour ouvrir une
création, l'Atelier émet un **code** d'usage unique (60 s pour la personne), lié à une **portée**,
que l'hôte échange contre sa propre session `__Host-atelier_apps`. Portées : un projet (ses
créations), un connecteur (`connecteur:qgis`, ses vues relayées), une conversation
(`conversation:<id>`, l'écran du navigateur de l'agent). Elles ne se recouvrent jamais. Le code
d'**agent** (`atelier_navigateur_ouvrir`) est borné au seul projet de la conversation, vaut deux
minutes, ouvre une session d'une heure qui ne s'élargit jamais, et ne donne jamais le cookie de
l'Atelier. Seule la personne ouvre un connecteur ou l'écran d'une conversation.

**Secrets d'une création** : `secrets` de `artefact.json` nomme des fichiers de
`~/work/.secrets/apps/` ; les variables d'une session se demandent dans `.atelier/env.json` (nom de
variable vers nom de fichier de `~/work/.secrets/`).

**Ce que ça ne fait pas.** Pas de brouillon, d'installation ni de partage à d'autres (J8, pas
fait) : `acces` vaut `proprietaire` seulement. Sans hôte des applications déclaré, « Ouvrir » est
grisé.

**Code** : `atelier/artifacts.py`, `artefacts_servis.py`, `outils_conversation.py`, `apps/`
(`manifeste.py`, `superviseur.py`, `proxy.py`, `passage.py`, `serveur.py`, `cadrage.py`),
`bin/atelier-app` ; `web/js/views/applications.js`.
**Doc** : [`atelier-applications.md`](atelier-applications.md),
[`atelier-hebergement.md`](atelier-hebergement.md).

### 7.2 Panneau

**En service.**

La colonne à droite du fil, en onglets, hors du fil (une vue ne se recharge pas quand le fil se
redessine). Une vue est épinglée à la conversation (`~/work/panneau/<conversation>.json`) ou, par
« Épingler au projet », au projet (`vues_epinglees` de `projet.json`).

- *Un agent code* : `atelier_montrer(nom, chemin?, titre?)` épingle la création à la conversation
  et **ouvre le panneau** chez la personne (décision J-f), sans geste de sa part : il n'existe aucun
  bouton « Exposer ». Il ne montre que les créations de son projet.
- *L'Assistant* : `atelier_montrer(projet, nom, …)` montre la création **d'un autre projet** dans le
  panneau de sa conversation, sans rien écrire dans ce projet. Son panneau est le même que celui des
  projets, avec trois différences : le catalogue (« + ») range les créations **de tous les projets**,
  un bloc par projet, et la personne en choisit une comme l'agent ; chaque onglet d'un autre projet que
  celui de la conversation dit son projet (« autre · secret »), car deux projets peuvent avoir une
  création du même nom ; l'épingle « au projet » n'est pas proposée pour ces vues, qui restent à la
  conversation. Il n'a pas de projet à lui et n'écrit
  que dans `notes/` : `atelier_artefact_creer` et `atelier_navigateur_ouvrir` lui sont refusés, avec
  la voie à suivre (déléguer à un agent code par `atelier_lancer_agent`, puis montrer).
- *Avant d'annoncer qu'une page est prête* : `atelier_artefact_verifier` (avec `nom`) et
  `atelier_montrer` rendent des `avertissements` pour une page autonome : `index.html` absent ou
  dossier vide, fichier référencé introuvable, chemin absolu, ressource externe (une page autonome
  n'a pas accès au réseau). Ils n'empêchent rien : le panneau s'ouvre quand même.
- *Le cadre du panneau* : la CSP de l'interface nomme l'hôte des applications dans `frame-src`
  (`apps/cadrage.py`, `politique_interface`) ; sans lui le navigateur refuse la redirection de
  `/v1/apps/…/ouvrir` et le cadre reste vide.
- *La personne* : le catalogue du panneau (créations du projet, onglet « Bureaux ») ; onglet
  « Navigateur de l'agent » (§8).
- Un flux vivant (bureau, navigateur) ne s'ouvre que sur un geste ou un événement de navigation,
  n'est jamais épinglé, et s'arrête quand son onglet est masqué.

**Code** : `atelier/panneau.py`, `web/js/views/panneau.js`. **Doc** : [`vision/panneau.md`](vision/panneau.md).

### 7.3 Bureaux relayés (QGIS, Blender, n8n)

**En service** (bureau QGIS vérifié en direct dans le panneau le 26/09).

Les services du namespace (bureau noVNC de QGIS ou Blender, éditeur n8n) sont relayés par l'hôte
des applications sous `/_services/<connecteur>/<vue>/`, avec le jeton du service posé côté serveur
et caviardé au retour. Ils se déclarent dans l'entrée du pool du connecteur, sous une clé
`atelier.vues` jamais écrite dans un `.mcp.json` ; **seule la personne** la pose (un modèle se la
voit refuser par `atelier_connecteur_ajouter`). *La personne* : onglet « Bureaux » du catalogue
du panneau (`GET /v1/bureaux`). Un bureau se corrige aussi à la main : la personne et l'agent
travaillent sur le même objet, l'agent par les outils du connecteur.

**Code** : `apps/bureaux.py`, `apps/proxy.py`. **Doc** : [`vision/panneau.md`](vision/panneau.md).

---

## 8. Le navigateur de l'agent

**Intégré** (Chrome par conversation depuis le 25/09 ; écran en direct et « Prendre la main » en
vague 3).

**À quoi ça sert.** Chaque conversation a son propre Chrome (`chrome-devtools-mcp` en stdio,
lancé par `~/work/bin/atelier-chrome` au premier outil). Il sert à chercher sur le web (il
remplace WebSearch, refusé), à **tester ce que l'agent fabrique**, et à utiliser des sites qui
demandent une connexion.

**Un agent** (tous profils) :

- lectures autorisées d'office, quel que soit le mode : `list_pages`, `take_snapshot`,
  `take_screenshot`, `wait_for`, console et réseau (J-f3) ; naviguer, cliquer, remplir suivent le
  mode de la conversation ;
- plafond de 8 onglets par conversation (`ATELIER_CHROME_ONGLETS_MAX`) ;
- pour ouvrir une création du projet : `atelier_navigateur_ouvrir(chemin)` puis naviguer vers
  l'adresse rendue, jamais `file://` ni `127.0.0.1:<port>` ;
- le profil du navigateur est gardé le temps de la conversation (connexions aux sites
  comprises), sous `/tmp` : il ne survit pas au redémarrage du pod.

**La personne.** Dès que l'agent ouvre ou change de page, l'onglet « Navigateur de l'agent »
s'ajoute au panneau : il s'ouvre si le panneau est fermé, et porte un signal si un autre onglet
est regardé. L'écran montre la page en direct (images JPEG, au plus 8 par seconde, seulement quand
quelqu'un regarde). **« Prendre la main »** : la personne clique, tape, change d'adresse
(`http`/`https` seulement) ; les actions de l'agent sur le navigateur **attendent** (son tour
n'est pas interrompu, ses autres outils continuent). « Rendre la main » : l'action en attente
repart avec une « Note de l'Atelier », ou un message relance l'agent. Si la page a changé pendant
la main, une action qui visait un élément par son identifiant est refusée jusqu'à une relecture.
Une main oubliée est rendue après 5 minutes sans spectateur.

**Ce que ça ne fait pas.** Pas de boîtes de dialogue ni de choix de fichier à l'écran ; deux
onglets de même adresse se confondent ; dans VS Code et au terminal, l'écran dépend de la
transmission de `CLAUDE_CODE_SESSION_ID` au serveur stdio (non vérifié). Le gardien Santé ne se
sert pas encore du navigateur pour vérifier une création.

**Code** : `bin/atelier-chrome`, `bin/atelier-chrome-onglets.mjs`, `atelier/navigateur.py`,
`navigateur_routes.py`, `ecran.py`, `apps/page_ecran/`, `web/js/views/panneau.js`.
**Doc** : [`navigateur-atelier.md`](navigateur-atelier.md) (§8 pour l'écran).

---

## 9. Connecteurs et passerelle MCP

**En service.**

**À quoi ça sert.** Le **pool** (`~/work/mcp/gateway.db`) tient tous les serveurs MCP : le socle
fourni par l'Atelier et ceux que la personne branche. La **passerelle** intégrée les sert aux
agents, projet par projet, avec leurs secrets par référence.

**La personne** (vue Connecteurs) : ajouter, sonder, activer, décrire un connecteur ; voir ses
outils ; « Accorder un secret » (liste des **noms** de `~/work/.secrets/`, jamais une valeur) ;
choisir les connecteurs d'un projet ou d'une conversation ; créer des **compositions** (plusieurs
outils enchaînés, `${input.x}` et `${etape.champ}`), les tester et les promouvoir.

**Un agent code** : reçoit les connecteurs choisis pour son projet (`/mcp` les montre). Un
connecteur en échec d'authentification n'est pas distribué. Il ne peut rien ajouter.

**L'Assistant** : `atelier_connecteur_ajouter` (engageante, aucun secret en argument),
`_retirer` (garde la déclaration hors service), `atelier_connecteur_choisir` ; tout outil du pool
par `gateway_find_tools` / `gateway_call_tool`.

**L'Atelier comme connecteur distant.** `/mcp` sur le port 8787 se branche dans un client distant
(claude.ai) par OAuth ; la page de consentement demande la clé de l'Atelier ; renouveler la clé
révoque les jetons accordés.

**Ce que ça ne fait pas.** Un connecteur fait maison d'un projet n'est pas encore publiable dans
le pool (J9). Les plugins Claude Code et leurs serveurs MCP sont écartés par
`--strict-mcp-config` (tension T19).

**Code** : `mcp_gateway/` (`registry.py`, `upstream/`, `mcp/gateway.py`, `tool_search.py`,
`compositions/`, `oauth.py`), `atelier/mcp_sync.py`, `mcp_registry.py`, `mcp_secrets.py`,
`accords.py`, `commandes/connecteurs.py` ; `web/js/views/connectors.js`, `composition-builder.js`.
**Doc** : [`atelier-mcp-unified.md`](archives/mcp/atelier-mcp-unified.md),
[`atelier-mcp-distant.md`](atelier-mcp-distant.md).

---

## 10. wikichat

**En service** (service local sur `127.0.0.1:3777`, données sous `~/.wikichat`, lien vers le
volume).

**Coordination.** Chaque conversation a une identité wikichat automatique (`<slug>-<id6>`, par le
pont stdio qui porte l'identifiant du CLI) : un agent n'appelle pas `register`. Briefing et
courrier arrivent par les hooks `SessionStart` et `UserPromptSubmit`. Pour joindre un autre
projet, un agent passe par ses agents : `list_sessions`, `contact_agent`,
`send_message(channel="@<agent>")`, avec le protocole `over` / `standby` / `done`. La personne
voit les fils d'une conversation par le bouton « Échanges ».

**Connaissance.** Axes de connaissance sous `~/.wikichat/knowledge/`, clôtures de projet
absorbées par le code, idées ; `search_knowledge` (profil `code` : commun et son projet). Notes
partagées d'un projet : `add_project_note` ; mémoire privée : `remember` / `recall`.

**Cartographie et carte de l'Atelier.** wikichat publie le graphe des projets
(`GET /api/cartographie` : relations déclarées, proximités, santé, connecteurs choisis) ; l'Atelier
l'assemble avec sa couche opérationnelle (créations, conversations, connecteurs, tâches
automatiques, alertes, « À valider ») et sert la **carte** par `GET /v1/carte` et `atelier_carte`
(formes synthétique, projet, complète ; 20 s de cache, recalculée après toute commande qui agit).
Seul l'Assistant la lit ; elle n'a pas de vue dans l'interface. Lier deux projets :
`atelier_projets_lier` (Assistant).

**Agents planifiés et automates.** Un agent de la vue Agents est un trigger du **Pilote** de
wikichat : horaire cron ou à la demande, budget obligatoire, **né désactivé** ; seule la personne
l'active (« Activer »), tout le monde peut le désactiver. wikichat ordonne ses triggers, routines
et jobs déterministes (cartographie, clustering, audits) ; la liste « Tâches automatiques » de la
vue Agents les montre tous, avec les gardiens (`GET /v1/automates`).

**Lancements par l'Atelier.** wikichat (réveil sur mention, trigger, routine) et les gardiens ne
lancent plus `claude` eux-mêmes : ils le demandent à l'Atelier (`POST /v1/lancements`, clé du
lanceur). L'Atelier crée une conversation visible, applique le profil `code` et le mode du projet,
et tient les plafonds (3 simultanés, 24 par origine et par jour, 100 par jour, 15 minutes par
défaut et 30 au plus). Un lancement avec `branche` (`agent/…` ou `gardien/…`) travaille dans une
copie `.atelier/reparations/<id>`, ne peut ni pousser ni toucher `main`, et sa fin est déposée
dans « À valider » avec l'action réservée `atelier_reparation_fusionner`. Vue Agents, « En cours
et récents » : origine en mots, projet, état, durée, branche, « Arrêter ».

**Ce que ça ne fait pas.** Un agent code ne voit pas les autres projets, ne lance pas d'agent, ne
crée ni trigger ni routine. La porte dormante ne coupe pas la nuit (tension T17) ; ce sont les
plafonds qui bornent.

**Code** : dépôt wikichat (branche `atelier-coherence`) ; côté Atelier `wikichat_mcp.py`,
`wikichat_pilote_proxy.py`, `pilote_client.py`, `carte.py`, `commandes/carte.py`,
`commandes/agents.py`, `commandes/liens.py`, `lancements.py`, `automates.py` ;
`web/js/views/agent.js`, `lancements.js`, `fils.js`.
**Doc** : [`atelier-wikichat-alignment.md`](archives/mcp/atelier-wikichat-alignment.md),
[`vision/architecture-transverse.md`](vision/architecture-transverse.md) §1.3 et §5.1, et
`docs/atelier-coherence.md` du dépôt wikichat.

---

## 11. Mémoire

**Intégré** (vague 3 ; résumé direct et recherche par le sens décidés le 26/09).

**À quoi ça sert.** Retrouver le passé sans relire les transcripts, et retenir ce que la personne
accepte qu'on retienne d'elle.

**Fiches de conversation.** wikichat extrait par le code les faits de chaque conversation (projet,
créations, fichiers touchés, agents lancés, erreurs), toutes les 15 minutes et à la fin d'une
conversation, à partir du transcript **filtré** fourni par l'Atelier (les valeurs secrètes
deviennent des empreintes). Les fiches vivent sous
`~/.wikichat/knowledge/conversations/<projet>/<id>.md`, avec un index.

**Retrouver.**

- `atelier_rappel(requete, projet?, depuis?, limite?)` : au plus 5 fiches, une ligne chacune,
  environ 450 jetons. Profil `code` : son projet seulement.
- `atelier_fiche(id)` : une fiche (2 500 caractères au plus ; 8 caractères d'identifiant
  suffisent). Profil `code` : une fiche d'un autre projet est introuvable.
- **Recherche par le sens** : les fiches sont aussi vectorisées (`qwen3-embedding-8b`, par
  `POST /v1/memoire/vecteurs` de l'Atelier) ; le rappel fusionne les rangs lexical et sens, et
  retombe sur le lexical seul si le point d'accès ne répond pas.

**Résumé des conversations.** Le résumé d'une conversation est un **appel direct** de l'Atelier
(`POST /v1/memoire/resumer`, clé du lanceur, identifiant de conversation seulement) : l'Atelier
lit, filtre, borne l'entrée à 58 000 caractères, appelle `qwen3-8-27b` (1 200 jetons de sortie au plus, `SORTIE_MAX_JETONS`),
20 par jour, un à la fois, chaque appel au journal. La **routine de nuit** de wikichat, qui
enchaîne ces résumés (20 conversations au plus), **naît désactivée** : son activation attend la
décision du propriétaire.

**Mémoire de la personne.** Les faits extraits par le code sont retenus d'office ; préférences,
traits et interprétations ne sont que **proposés** (`atelier_memoire_proposer`, Assistant, trois
par conversation au plus) et passent par « À valider ». *La personne* : vue **Ma mémoire** (qui
vous êtes, préférences, ce que l'Assistant a compris, faits retenus ; « d'où ça vient » ;
« Corriger », « Oublier » ; un fait oublié n'est plus réenregistré). *L'Assistant* :
`atelier_memoire` pour la lire.

**Ce que ça ne fait pas.** La mémoire ne donne jamais le contenu d'un résultat d'outil ; le flux en
direct vers l'écran de la personne n'est pas filtré (aucun modèle ne le lit). Non vérifié en réel :
le point d'accès des vecteurs sur SSPCloud, le seuil de similarité (0,35), une nuit complète.

**Code** : `atelier/memoire.py`, `memoire_modele.py`, `filtre_transcripts.py`,
`commandes/rappel.py` ; `web/js/views/memoire.js` ; wikichat `src/memoire/`.
**Doc** : [`vision/architecture-transverse.md`](vision/architecture-transverse.md) §1.6 bis,
[`vision/decisions.md`](vision/decisions.md) A-7 et A-9.

---

## 12. Gardiens et réparateurs

**En service** (exécuteur et vue Agents déployés en vagues 1 et 2 ; réparateurs intégrés).

**À quoi ça sert.** Surveiller l'Atelier sans modèle ni jeton, prévenir, et proposer une
réparation que la personne accepte.

**L'exécuteur** : un processus à part (`python -m mcp_gateway.gardiens`, lancé par
`install/atelier-init.sh`), API en boucle locale sur `127.0.0.1:8791`. Il fait tourner les
contrôles déclarés dans `mcp_gateway/gardiens/gardiens.json`, écrit chaque exécution au journal,
tient **une alerte par empreinte** (avec un compteur), et signale un contrôle qui n'a pas tourné à
l'heure (homme mort).

| Contrôle | Ce qu'il regarde | Geste seul |
|---|---|---|
| `entretien.automates` | inventaire des tâches automatiques (wikichat, gardiens, créations serveur) : budget, échecs | |
| `sante.atelier`, `sante.relais`, `sante.wikichat` | le service répond | relance par le script officiel (`atelier-relancer`, relais, `start_wikichat.sh`) |
| `sante.creations` | l'état des créations serveur au superviseur (`en_echec`) | |
| `sante.ci-main`, `sante.image-main` | CI de `main` et image publiée | |
| `sante.disque` | la place | |
| `securite.ecoutes` | ports en écoute non déclarés, `0.0.0.0` | |
| `securite.secrets-en-clair` | jetons dans les fichiers que lisent Claude Code ou git (par empreinte) | |
| `securite.droits` | droits des fichiers de secrets (0600) | |
| `securite.bypass` | processus `claude` sans garde-fou sans fiche, ou plus permissif que son mode | |
| `coherence.surfaces` | une fois par jour (5 h 40), le vérificateur du §14 en mode rapide : chaque écart entre surfaces et profil est une alerte | |

Les gestes forment une **liste fermée** (trois relances), coupables par
`ATELIER_GARDIENS_GESTES=0`, et ne s'appliquent pas à l'Atelier en mode image.

**La personne** : dans la vue Agents, chaque gardien est une carte (état, derniers constats,
alertes) avec « Lancer maintenant » et « Couper / Réactiver » ; la personne seule coupe un
gardien. Les alertes figurent aussi sur la carte de l'Atelier, que lit l'Assistant.

**Réparateurs** (G5) : un contrôle peut déclarer `proposer` (après N heures ou N occurrences, dans
un **projet** nommé). Le gardien demande alors un lancement à l'Atelier sur une branche
`gardien/<gardien>/<date>-<sujet>` ; l'agent reproduit, corrige, vérifie et commite ; l'Atelier
dépose la proposition dans « À valider » (constat, commits, écart) ; « Accepter » exécute
`atelier_reparation_fusionner`, qui fusionne sans pousser. Au plus 3 par jour
(`ATELIER_REPARATIONS_PAR_JOUR`), coupables par `ATELIER_GARDIENS_REPARATIONS=0`. **Dans la
déclaration livrée, seul `sante.ci-main` porte `proposer`, et sans projet : il reste un
signalement.** Aucun réparateur ne part donc tant qu'un projet n'est pas déclaré.

**Le hook du socle** : `garde_bash` refuse, avant qu'elles partent, les commandes Bash qui tuent
par motif (`pkill -f`, `killall`, `kill $(pgrep …)`) ou écoutent partout (`0.0.0.0`,
`http.server` sans `-b`). L'exécuteur le pose à son démarrage dans `~/work/.claude/settings.json`
(le fichier réel derrière le lien `~/.claude/settings.json`), entrée `hooks.PreToolUse`,
`matcher: "Bash"`, commande `<python> -m mcp_gateway.gardiens.garde_bash`, délai 10 s ; il suit
le lien, ne touche à aucun autre hook, et sa commande ne contient pas « wikichat » pour survivre à
la fusion des réglages. `ATELIER_GARDIENS_HOOKS=0` empêche la pose ;
`python -m mcp_gateway.gardiens.garde_bash --poser [fichier]` la fait à la main,
`--verifier <commande>` dit si une commande serait refusée. Si le module ne s'importe pas, le hook
échoue sans bloquer.

**Ce que ça ne fait pas.** Le contrôle de cohérence ne vérifie qu'un projet par profil (la
vérification complète se lance à la main, §14) et ne répare rien ; pas de vérification des
créations par le navigateur ; pas de notification hors de
l'Atelier ; pas de page Gardiens (décision J-i).

**Code** : `mcp_gateway/gardiens/` (`executeur.py`, `controles/`, `gestes.py`, `reparations.py`,
`garde_bash.py`, `api.py`, `gardiens.json`), `atelier/automates.py`, `lancements.py` ;
`web/js/views/gardiens.js`, `lancements.js`. **Doc** : [`vision/gardiens.md`](vision/gardiens.md).

---

## 13. Onyxia et déploiement d'un projet

**Intégré** (lot « profils » ; mandataire écrit et testé, liaison réelle d'un projet à un pod non
vérifiée).

**À quoi ça sert.** Relier un projet à un pod (ou à un service) Onyxia, et, s'il le faut, au GPU,
pour que ses agents y travaillent sans recevoir tout Onyxia.

**Déclarer.** `atelier_projet_deployer_declarer(projet, pod | service, namespace?, gpu?,
commande?, port?)` (engageante : aperçu, puis « Oui ») écrit le bloc `deploiement` de
`.atelier/projet.json` et attache la session `proj-<slug>` au pod ; `retirer: true` enlève la
liaison, « Annuler » remet l'état d'avant.

**Ce que reçoit un agent code** (par le mandataire `/mcp/onyxia/projet/<slug>` de l'Atelier) :

| Déclaration | Outils |
|---|---|
| aucune | aucun outil Onyxia |
| `pod` | `exec`, `job_poll`, `read_file`, `write_file`, `list_files`, `session_status`, `project_bind`, bornés à `proj-<slug>` et à son pod |
| `service` | `service_status`, `service_deploy`, `service_stop`, `service_warm`, `service_provision`, `yaml_path` imposé |
| `gpu: true` | en plus `gpu_status`, `gpu_switch` (sans préemption), `gpu_release` |

Un argument imposé qui diffère, ou un argument non prévu, est refusé. L'Assistant reçoit les 24
outils (`/mcp/onyxia`). `expose_public` et `unexpose_public` sont refusés à tout modèle.

**Ce que ça ne fait pas.** `exec` donne un shell dans le pod du projet : la borne est le pod, pas
ses droits. Un projet choisit un pod **ou** un service. Le correctif du serveur Onyxia
(`Content-Length` sur les 202) n'est pas déployé ; le mandataire le contourne.

**Code** : `atelier/onyxia_projet.py`, `commandes/deploiement.py`, `commandes/structure.py`.
**Doc** : [`onyxia-projet.md`](onyxia-projet.md).

---

## 14. Vérificateur de cohérence

**En service** (0 écart constaté au déploiement de la vague 2 : 27 dossiers, 4 surfaces).

**À quoi ça sert.** Vérifier, avec le vrai binaire `claude`, que chaque surface donne à l'agent ce
que dit son profil. Pour chaque projet (ou un échantillon) et le dossier de l'Assistant, et pour
chaque surface (app, VS Code, terminal interactif, `bash -lc`), il lance
`claude -p --output-format stream-json`, lit `system/init` et compare : serveurs, outils,
version, mode, modèle, effort, outils interdits au profil `code`, méta-outils de l'Assistant,
WebSearch refusé, hook de garde exécutable. Aucun secret affiché.

**Qui s'en sert.** La personne ou un agent qui travaille sur l'Atelier, sur le pod :

```bash
~/work/bin/atelier-verifier-coherence              # tous les projets, toutes les surfaces
~/work/bin/atelier-verifier-coherence --rapide     # un projet par profil
~/work/bin/atelier-verifier-coherence --projets carte,assistant --surfaces app,vscode --json
```

Sortie 0 sans écart, 1 sinon.

**Planifié** (intégré, pas encore vu tourner sur le pod) : le gardien Cohérence le lance une fois
par jour, à 5 h 40 et dix minutes après chaque démarrage de l'exécuteur (contrôle
`coherence.surfaces`, `gardiens/controles/coherence.py`) : `--rapide --json`, 45 s au plus par
surface, plafond de 540 s au-delà duquel le vérificateur et les `claude` qu'il a lancés sont tués.
Chaque écart est une alerte de la vue Agents (carte « Cohérence »), fermée quand il disparaît ; un
plafond atteint est une alerte d'erreur, qui ne ferme rien.

**Ce que ça ne fait pas.** Il ne répare rien. Le contrôle quotidien ne couvre qu'un projet par
profil (le plus récemment modifié).

**Code** : `bin/atelier-verifier-coherence`, `atelier/coherence.py`.
**Doc** : [`coherence-projet.md`](archives/chantiers/coherence-projet.md), [`coherence-outils-audit.md`](archives/chantiers/coherence-outils-audit.md).

---

## 15. Voix

**Pas intégrée à l'Atelier.** Une équipe étudie son intégration.

Ce qui existe : un **projet** du pod (`nouveau-projet-2`, consigne
[`consignes/stt-tts-atelier.md`](consignes/stt-tts-atelier.md)) qui sert un STT (faster-whisper)
et un TTS (Kokoro) auto-hébergés, avec un serveur MCP (`dire`, `ecouter`), un jeton dans
`~/work/.secrets/voice_token`, et une déclaration en création serveur (`artifacts/voix/`).
D'après sa consigne (24/09), il tourne aussi par `start.sh` sur `127.0.0.1:18920`, sans passer
par l'Atelier (tension T4). L'interface de l'Atelier n'a ni micro ni
lecture à voix haute ; l'Assistant n'a pas de canal oral.

Décisions déjà prises pour la suite (`vision/decisions.md` A-8) : aucun audio conservé, aucun
accord donné à l'oral, accusé par un son préenregistré, détection de fin de parole requise.

---

## 16. Combinaisons d'usage

### Une création serveur, testée par l'agent, puis montrée

1. La personne, dans une conversation du projet : « fais-moi une carte des parcelles, servie par
   une petite application ».
2. L'agent : `atelier_artefact_creer("carte", mode="serveur")`, complète `artefact.json`
   (`commande` avec `{port}`, `sante`, `protocoles`), `atelier_artefact_verifier`, puis
   `atelier_artefact_demarrer`. En cas d'échec, `atelier_artefact_journal`.
3. Il vérifie lui-même : `atelier_navigateur_ouvrir(chemin="carte/")`, `navigate_page` vers
   l'adresse rendue, `take_snapshot`, `list_console_messages`. La personne voit son navigateur en
   direct dans le panneau.
4. Il corrige, recharge, puis `atelier_montrer("carte")` : la création s'ouvre dans le panneau,
   à côté du fil.
5. La personne l'épingle au projet pour la retrouver dans toutes les conversations.

### Une connexion qu'un agent ne peut pas faire seul

1. L'agent navigue vers un site qui demande une connexion ou un CAPTCHA, et le dit.
2. La personne clique « Prendre la main » dans l'onglet « Navigateur de l'agent », se connecte.
3. Elle rend la main : l'action de l'agent qui attendait repart avec la « Note de l'Atelier » ;
   l'agent relit la page et continue. La connexion dure le temps de la conversation.

### Une alerte de gardien, jusqu'à la preuve dans le journal

1. `sante.ci-main` constate que la CI de `main` est rouge : une alerte ouverte, visible sur la
   carte du gardien Santé (vue Agents) et sur la carte de l'Atelier.
2. Si le contrôle déclare `proposer` avec un projet, après 24 h le gardien demande un
   réparateur : l'Atelier lance un agent sur `gardien/sante/<date>-…`, visible dans « En cours et
   récents ».
3. À la fin du tour, la proposition arrive dans « À valider » : constat, commits, écart.
4. La personne accepte : `atelier_reparation_fusionner` fusionne la branche, sans pousser.
5. Le journal montre la chaîne : contrôle, lancement, validation, fusion, avec leurs acteurs ; au
   prochain passage, le constat disparaît et l'alerte se ferme.

Aujourd'hui, l'étape 2 demande d'ajouter un `projet` au `proposer` de `sante.ci-main` dans
`gardiens.json` ; sinon la chaîne s'arrête au signalement.

### Déléguer depuis l'Assistant

1. « Ajoute un export CSV au Lecteur Grist. »
2. L'Assistant cherche au besoin (`gateway_find_tools`), puis `atelier_lancer_agent(projet,
   message)` : un aperçu s'affiche, la personne répond « Oui ».
3. Un agent code part dans le projet, sous son profil et son mode, avec un plafond de durée.
4. L'Assistant suit par `atelier_lancements`, et rend compte en trois lignes depuis l'état du
   lancement ; le travail est lisible dans la conversation lancée, vue Code.

### Retrouver une décision passée

Un agent code, avant de changer un format de fichier : `atelier_rappel("format export csv")`, puis
`atelier_fiche("3fa9c1d2")` sur la ligne pertinente. S'il faut l'avis d'un autre projet :
`contact_agent` vers un agent de ce projet, `status="over"`, `expects_reply=true`.

### Un nouvel agent planifié

L'Assistant : `atelier_agent_creer(...)` avec un budget ; l'agent naît désactivé. La personne
l'active dans la vue Agents (« Activer »), et le coupe au même endroit. Ses propositions arrivent
dans « À valider ».

---

## 17. Ce qui n'existe pas encore

| Prévu | Où c'est décrit | État |
|---|---|---|
| « Montrer » de la personne vers l'agent (un clic ou une sélection dans le panneau) | `vision/panneau.md`, J5 | pas fait ; le bouton « Montrer » du catalogue ouvre une création dans le panneau |
| Brouillon, installation, partage d'une création ; registre des promotions | `vision/ecosysteme.md`, J8 | pas fait |
| Connecteur fait maison d'un projet, appelable depuis claude.ai | J9 | pas fait |
| Vérification des créations par le navigateur, par les gardiens | `vision/synthese.md` §2 | pas fait |
| Vue de la carte, tableaux de bord système | `architecture-transverse.md` §5.3 | pas fait (la carte n'est lue que par l'Assistant) |
| Coût par acteur au relais LLM | T18 | pas fait |
| Voix dans l'interface | A-8 | pas fait (§15) |
| Capacités courtes par conversation (fermer l'accès complet par la clé du propriétaire) | `vision/profils-acces.md` | pas fait |

---

## 18. Repères : processus, ports, scripts

| Processus | Adresse | Rôle |
|---|---|---|
| Atelier | port 8787 (interface, `/v1`, `/mcp`, `/vscode/`) | le service |
| Hôte des applications | port 8788, second Ingress `…-apps` | créations, bureaux, écran du navigateur |
| Relais LLM | `127.0.0.1:8790` | chemin unique vers le modèle, compaction |
| Gardiens | `127.0.0.1:8791` | contrôles, alertes, pilotage par l'Atelier |
| wikichat | `127.0.0.1:3777` | coordination, connaissance, Pilote |
| Créations serveur | `127.0.0.1:19000-19099` | ports attribués par l'Atelier, jamais à ouvrir à la main |

Scripts posés dans `~/work/bin/` par `install/atelier-init.sh` :

| Script | Usage |
|---|---|
| `atelier-app` | créations sans MCP : `liste`, `creer`, `verifier`, `demarrer`, `arreter`, `journal`, `montrer`, `ouvrir-navigateur` |
| `atelier-relancer` | relancer le service sans tuer par motif (détenteur du port par l'inode de sa socket) |
| `atelier-verifier-coherence` | le vérificateur du §14 |
| `atelier-chrome`, `atelier-chrome-onglets.mjs` | lanceur du navigateur de l'agent et son filtre (plafond, écran, pause) |
| `atelier-claude-vscode` | enveloppeur de `claude` pour VS Code et le terminal (secrets, mode) |
| `atelier-entetes-mcp` | dit au serveur `atelier` quelle conversation l'appelle |
| `atelier-bashrc` | charge `claude-env.sh` avant la garde non interactive de `~/.bashrc` |
| `atelier-figer-le-travail.sh` | hook `SessionEnd` (posé par l'installation) : commite le travail non commité, sans pousser |
| `node-relais` | lance un serveur MCP en JavaScript avec le `node` épinglé de l'Atelier |

Installation et réglages : [`installer.md`](installer.md). Consignes des agents :
[`consignes/`](consignes/README.md).
