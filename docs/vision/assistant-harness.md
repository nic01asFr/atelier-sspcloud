# L'Assistant : harness, outils et modèle

Réflexion du 25/09/2026, équipe « harness, outils et modèles ». **Rien n'est implémenté.**
Quel Claude Code, quels outils, quel modèle et quels réglages pour un Assistant chef d'orchestre
sur les modèles de SSPCloud ? S'appuie sur `assistant-cadre.md` (précisions de Nicolas),
`architecture-transverse.md` (§0, §1.1, §1.5, §1.8, §5.1, T11), `assistant-role.md`,
`assistant-contexte.md`. **[M]** mesuré (pod `proj-claude-code-jupyter-python-0`, `claude`
2.1.281, relais LLM 127.0.0.1:8790, 25/09 après-midi) ; **[C]** calculé sur fichiers réels, sans
modèle ; **[S]** supposé.

## En une phrase

Un Claude Code ordinaire, ouvert dans le dossier mémoire, avec **une seule porte MCP : `atelier`
en profil `assistant`**. Elle compose un noyau d'environ 20 outils tirés de trois briques :
`atelier_*`, un sous-ensemble de wikichat, le catalogue de la passerelle. Les autres familles
s'ajoutent en cours de session par `tools/list_changed`, qui fonctionne [M] et se trompe moins
que « chercher puis appeler » [M]. Modèle `qwen3-6-35b-moe`, sans thinking, effort `medium`.
L'écriture dans les dépôts et `Bash` sont refusés par `permissions.deny`.

## 1. Le problème

- **Trop d'outils, pas de tool search** (`ANTHROPIC_BASE_URL` personnalisé) : tous les schémas
  partent à chaque appel. Le pool compte 293 outils, environ 58 000 jetons [C] ; les 19 natifs,
  environ 15 700 [M] ; la fenêtre, 131 072.
- **Des commandes absentes comme outils** : créer un projet, un agent, brancher un connecteur
  n'existent qu'en API HTTP ; les 14 `atelier_*` couvrent conversations et artefacts.
- **Une frontière à tenir par construction** : l'Assistant délègue le contenu des dépôts ; la
  consigne seule ne suffit pas (usage du 25/09).
- **L'oral** : T11 estime environ 11 s jusqu'au premier mot ; le premier jeton reste à mesurer
  avec le contexte réel. **Les surfaces** : le même Assistant dans l'Atelier, VS Code, terminal.

## 2. L'existant

### 2.1 Les outils `atelier_*` (inventaire du code)

Le serveur `atelier` (`/mcp`, `mcp_endpoint.py`) est la passerelle intégrée, en exposition
`discover` (`~/work/mcp/catalog.yaml`). Il annonce trois choses : ses méta-outils, les
compositions promues et ses outils locaux (`outils_conversation.py`).

| Famille | Outils | Poids [C] |
|---|---|---|
| Conversations | `atelier_projets`, `atelier_conversations`, `atelier_ouvrir`, `atelier_envoyer` (rend la main aussitôt ; `mode`, `peut_attendre`), `atelier_suivre` (curseur, `attendre_s` ≤ 30, flux fondu), `atelier_interrompre`, `atelier_transcript` (`derniers`, défaut 4 000 car.), `atelier_decider` | 14 outils, 8 026 car., environ 2 360 jetons |
| Artefacts (si `apps`) | `atelier_artefacts`, `atelier_artefact_creer`, `_demarrer`, `_arreter`, `_journal`, `_verifier` | (inclus ci-dessus) |
| Méta-outils de la passerelle | `gateway_find_tools`, `gateway_call_tool`, 5 outils de compositions, 7 outils de profils et bundles, `gateway_status` | 15 outils, 7 943 car., environ 2 340 jetons |

Un agent reçoit donc environ 29 outils `atelier` (environ 4 700 jetons), dont 7 de profils
inutiles à un agent. La passerelle sait déjà émettre `listChanged` (`tools_change_tracker`) et
tenir un profil par session MCP (`bundles`) : c'est la brique qu'on réutilise.

### 2.2 Ce que reçoit aujourd'hui une conversation ouverte dans `wikichat-memory`

Sur le pod, le dossier est `~/work/projects/wikichat-memory/` [M]. Le document d'alignement, lui,
dit `~/work/wikichat-memory/`, qui ne contient qu'`assistant/`. Ce dossier n'a pas de `CLAUDE.md`.
Son `.mcp.json` hérite des 11 serveurs du pool (`.atelier/connecteurs-herites`).

| Serveur (cache de la passerelle ; schéma sérialisé / 3,4) | Outils | Jetons [C] | Par outil |
|---|---|---|---|
| github ; qgis ; wikichat ; n8n | 45 ; 54 ; 51 ; 24 | 15 070 ; 9 992 ; 9 967 ; 9 278 | 334 ; 185 ; 195 ; 386 |
| blender (hors ce `.mcp.json`) ; datagouv ; filesystem ; Onyxia ; llm ; chrome (cache) ; gitlab | 45 ; 10 ; 14 ; 24 ; 12 ; 5 ; 9 | 3 990 ; 2 472 ; 2 432 ; 2 376 ; 1 371 ; 534 ; 434 | 48 à 247 |
| **Total du pool** | **293** | **environ 57 900** | 198 |
| Chrome en stdio, jeu courant (`navigateur-atelier.md`) | 24 | 5 940 | 248 |

Un Assistant ouvert là paierait environ 54 000 jetons de connecteurs, 15 700 de natifs et 6 000
de prompt [C] : près de 76 000 avant le premier mot, 58 % de la fenêtre. Ce chiffre est calculé :
l'appel réel a été refusé par le classifieur d'autorisations (services partagés, vrais jetons).

### 2.3 Réglages du pod (lus dans `~/.claude/settings.json`)

`model` = `sonnet` → `qwen3-6-35b-moe` ; créneau haiku (sous-agents) et repli = `qwen3-8-27b` ;
`effortLevel` `medium` mais `modelSettings` passe `qwen3-6-35b-moe` en **`xhigh`** ;
`MAX_THINKING_TOKENS=0` ; fenêtre 131 072, sortie 8 192. Hooks : seulement `Stop` (l'ancien
`wikichat-mailbox-hook`, jusqu'à 45 s d'attente) et `SessionEnd` ; `SessionStart` et
`UserPromptSubmit` (branche `atelier-coherence`) ne sont pas déployés. Modèles servis [M] :
`agent`, `chandra-ocr-2`, `gemma4-26b-moe`, `qwen3-6-35b-moe`, `qwen3-8-27b`,
`qwen3-embedding-8b`, `qwen3-vl`. **`qwen3-cursor` n'est pas servi** : j'ai mesuré `agent` à sa
place, sans savoir quel modèle ce nom désigne.

## 3. Les mesures

### 3.1 Protocole

Dossier jetable `/tmp/assistant-mesures/` (supprimé depuis) et `CLAUDE_CONFIG_DIR` jetable :
aucun hook utilisateur, aucune écriture dans `~/.claude*`. Un `--settings` reprend l'`env` et
l'`apiKeyHelper` du pod ; aucune valeur secrète lue ni affichée. Contexte de l'Assistant : un
`CLAUDE.md` de 1 563 caractères (consigne de rôle, briefing simulé de la taille du hook
`SessionStart`, et « quand une commande existe, appelle-la plutôt que de répondre de mémoire »).
Outils : un serveur MCP stdio factice qui répond « ok ». Chaque appel `claude -p --output-format
stream-json --include-partial-messages` est chronométré ligne à ligne ; les jetons d'entrée sont
ceux du journal du relais. **40 appels `claude -p`**, le plafond ; un essai par case : des
indications, pas des statistiques.

### 3.2 Coût d'entrée [M]

| Configuration (même prompt « Réponds juste : OK. ») | Jetons d'entrée (relais) |
|---|---|
| prompt système + `CLAUDE.md`, aucun outil (`--tools ""`, sans MCP) | 6 032, puis **400** de la passerelle : `tools must not be an empty array` |
| + les 19 outils natifs (`--tools default`) | 21 771, soit **environ 15 700 pour les natifs** (environ 830 par outil) |
| `Read`, `Glob`, `Grep` + 2 outils de catalogue | 7 940 (les 3 natifs : environ 1 650) |
| `Read`, `Glob`, `Grep` + 12 commandes (noyau) | 9 080 (environ 118 par commande) |
| + 25 commandes | 10 890 |
| + 50 commandes | 13 290 (environ 96 par commande ajoutée) |
| 19 natifs + 50 commandes + 100 000 caractères passés par `--append-system-prompt` | 51 620 |

- **Nos commandes coûtent environ 100 jetons chacune** si la description est sobre ; le pool,
  198 en moyenne [C], GitHub et n8n plus de 330.
- **Les natifs sont le premier poste** (`Bash`, `Agent`, `Edit`) : les retirer fait gagner plus
  que tout le noyau ne coûte.
- **`--append-system-prompt` atteint la requête** (les 100 000 caractères sont comptés), contre le
  commentaire de `harness.py` l. 928 ; la consigne témoin (« termine par PAPILLON ») n'a pas été
  suivie, sur un essai. Inutile de toute façon : il n'existe pas dans VS Code.
- **Un Assistant sans aucun outil échoue** (`tools: []`, corrigé par le relais pour WebFetch seul).

### 3.3 Choix d'outil selon le nombre d'outils [M]

Jeux : **12** (un noyau proche de §4.2) ; **25** (plus les vrais `atelier_*` de conversation et des
outils wikichat voisins à dessein : `list_projects`, `get_briefing`) ; **50** (plus artefacts,
8 outils Chrome, `gateway_find/call_tool`, GitHub, reste de wikichat). Tâches : **T1** « qu'est-ce
qui attend ma validation ? leurs identifiants » (`atelier_a_valider`) ; **T2** « fais ajouter par
un agent un bouton Exporter en CSV à lecteur-grist » (`atelier_deleguer`) ; **T3** « l'agent du
suivi d-4821 a-t-il fini ? » (`atelier_suivre_agent`) ; **T5** « crée-moi un projet suivi-budget
dans Grist » (`atelier_projet_creer`). Réussite : l'outil attendu appelé en 2 tours au plus, sans
outil hors sujet.

| Jeu | qwen3-6-35b-moe | agent | qwen3-8-27b | Total |
|---|---|---|---|---|
| 12 (T2, T5) | 2/2 | 1/2 (T2 : a vu qu'un agent tournait déjà sur le projet et l'a vérifié au lieu d'en lancer un) | 2/2 (T2 en 14,5 s) | 5/6 |
| 25 (T1, T3) | 2/2 | 2/2 | 2/2 | 6/6 |
| 50 (T1, T2, T3, T5) | 3/4 (T2 : explore `atelier_projet`, `atelier_artefacts`, sans déléguer) | 4/4 | 3/4 (T2 : `Glob` ×2, 2 711 jetons de sortie, 35 s) | 10/12 |

**Aucun distracteur choisi en 24 essais** (ni wikichat, ni Chrome, ni GitHub) : les échecs sont
des détours, surtout sur la délégation (T2), où les modèles veulent d'abord regarder. Jusqu'à 50
outils sobres, le nombre ne dégrade pas nettement le choix sur cet échantillon ; ce qui compte,
c'est des noms et descriptions sans ambiguïté. **Hypothèse de travail [S]** : au plus environ 30
outils MCP déclarés et environ 6 000 jetons d'outils au total.

### 3.4 Catalogue « chercher puis appeler » ou familles chargées [M]

Mode **catalogue** : `catalogue_chercher(intention)` (les 5 meilleures commandes des 50, avec
schéma) et `catalogue_appeler(nom, arguments)` ; T1, T2, T5 ; 3 tours.

| Modèle | Réussites | Échecs |
|---|---|---|
| qwen3-6-35b-moe | 2/3 | T1 : **aucun appel**, a répondu depuis le briefing en inventant un détail (« export CSV livré » ; le briefing disait « demandé ») |
| agent | 1/3 | T2 : a appelé directement `atelier_deleguer`, un nom trouvé mais non déclaré, donc en erreur ; T5 : `catalogue_appeler` **sans `nom`** |
| qwen3-8-27b | 3/3 | recherche formulée en anglais une fois ; 8 à 12 s par tâche |
| **Total** | **6/9 (67 %)** | contre 21/24 (88 %) en outils déclarés |

Le catalogue coûte en plus un aller-retour, de 1 à 6 s.

Mode **familles par `tools/list_changed`** : le serveur annonce `catalogue_charger`, dont l'appel
ajoute `budget_exporter` et émet la notification. **Claude Code relit `tools/list` en cours de
tour** : le serveur reçoit un second `tools/list`. Le modèle appelle alors `budget_exporter` sous
son vrai nom, avec un argument juste (1/1, 4,1 s, 3 tours). L'entrée ne grossit que de ce qui est
chargé (6 605, 6 980, puis 7 159 jetons).

Conclusion : les familles donnent de **vrais outils à schéma déclaré**, c'est le mode le plus sûr.
Le catalogue sert la longue traîne.

### 3.5 Latence [M]

Temps compté depuis le lancement du processus. `init` (CLI et serveurs MCP) arrive vers 0,4 s ;
un processus persistant ne le paie qu'une fois.

| Modèle | Premier jeton (12 à 13 k jetons d'entrée) | Question d'état : 1 appel d'outil + réponse (tour complet) | Débit de sortie |
|---|---|---|---|
| qwen3-6-35b-moe | 1,08 à 1,26 s, soit **environ 0,7 s après la requête** | **2,1 s** | environ 175 jetons/s |
| agent | 1,11 à 1,30 s | 3,0 s | environ 160 jetons/s |
| qwen3-8-27b | 1,41 à 2,18 s | 5,9 s | environ 85 jetons/s |
| qwen3-6-35b-moe, 51 620 jetons d'entrée | 1,54 s, soit environ 1,1 s après la requête | (sans outil) 1,75 s | — |

Les 7,9 s jusqu'au premier jeton citées par `assistant-role.md` ne se reproduisent pas dans ces
conditions : effort `medium`, thinking à 0, charge de l'après-midi. **Hypothèse [S]** : cet écart
vient de l'effort `xhigh` que `modelSettings` impose à `qwen3-6-35b-moe` sur le pod, d'une
compaction, ou d'une charge plus forte. La mesure en `xhigh` n'a pas pu être faite, le plafond de
40 appels était atteint : c'est la première à faire. Le contexte pèse peu : quatre fois plus
d'entrée n'ajoute que 0,4 s [M].

## 4. La proposition

### 4.1 Un profil d'outils par type d'acteur

Un mécanisme pour tous les acteurs (§1.5 transverse) : **noyau** déclaré dans le `.mcp.json`
généré ; **familles** chargées par `list_changed` ; **catalogue** (`chercher`, `appeler`) pour la
longue traîne. Le profil se déclare dans l'entrée `atelier` du `.mcp.json` (en-tête
`X-Atelier-Profil`) ; la passerelle le rattache à la session MCP, comme elle le fait déjà avec
`bundles`.

| Acteur | Natifs | Noyau `atelier` | Familles (list_changed) | Catalogue |
|---|---|---|---|---|
| Assistant | `Read`, `Glob`, `Grep`, `Task` (sous-agents de §4.7), `TodoWrite` | environ 20 outils, `atelier_*` et wikichat (§4.2) | projets, agents, connecteurs, créations, navigateur-vérif, familles wikichat | connecteurs métier |
| Agent code | tous sauf `WebSearch` | `atelier_*` du projet (artefacts, `atelier_montrer`, `atelier_navigateur_ouvrir`) | **navigateur** (24 outils, environ 5 900 jetons) chargé au premier besoin | connecteurs du projet non déclarés |
| Agent lancé | ceux de sa mission (`--tools`) | liste fermée de sa fiche | aucune | aucun : une mission restreinte ne s'élargit pas |
| Gardien | — | — (du code, sans modèle) | — | — |

Règle de placement, tirée des mesures : **noyau** pour ce qui sert souvent ou dans l'urgence
(état, validation, délégation, interruption, montrer) ; **famille** pour les groupes cohérents
utiles dans une partie des conversations (navigateur, projets, connecteurs) ; **catalogue** pour
les outils métier nombreux (GitHub, n8n, QGIS). Il réussit 2 fois sur 3 [M] : il ne porte jamais
une commande engageante.

### 4.2 Le profil de l'Assistant : trois sources, une seule porte

Le profil se compose de trois briques existantes (§0 et §5.1 transverse) : les `atelier_*`, un
sous-ensemble des outils de wikichat (51 dans le cache de la passerelle [C]) et le catalogue de
la passerelle. **Une seule porte** : le serveur `atelier` en profil `assistant`. La passerelle
tient déjà wikichat dans son pool et sait composer un profil d'outils du pool ; les outils
wikichat y gardent leur nom qualifié (`wikichat__search_knowledge`). Déclarer wikichat à part
obligerait à refuser une à une ses 51 entrées dans `permissions.deny`, et ce refus casserait au
premier outil ajouté.

**Noyau, toujours déclaré** (chaque commande déclare `objet`, `classe`, `inverse`, `resultat`,
`regles`, §1.8 transverse) :

| Source | Outil | Classe | Statut | Rôle |
|---|---|---|---|---|
| atelier | `atelier_carte(objet?, profondeur=1)` | lecture | à écrire | voisinage de la carte, ≤ 1 500 car. |
| atelier | `atelier_fiche(objet)` | lecture | à écrire | projet, agent ou application (tête d'`ETAT.md`, santé) |
| atelier | `atelier_a_valider(projet?)` | lecture | à écrire | file « À valider » |
| atelier | `atelier_decider(demande, decision, motif)` | engageante | existe, bridée | répond à une autorisation ou une proposition |
| atelier | `atelier_deleguer(projet, bon_de_commande)` | réversible | à écrire sur `ouvrir` + `envoyer` | lance un agent code, rend un suivi |
| atelier | `atelier_suivre_delegation(suivi)` | lecture | à écrire sur le carnet | résumé ≤ 600 car., jamais le transcript |
| atelier | `atelier_interrompre`, `atelier_annuler(action)` | réversible | existe / à écrire | arrêter un tour ; appliquer l'`inverse` |
| atelier | `atelier_montrer(vue)`, `atelier_vue_lire(id, capture=false)` | lecture | à écrire (`panneau.md`) | montrer, lire le contexte de vue |
| atelier | `atelier_charger(famille)`, `atelier_decharger(famille)` | — | à écrire | `list_changed` |
| wikichat | `search_knowledge`, `recall` | lecture | existent (W1, W2 à réparer) | mémoire et connaissance |
| wikichat | `remember` | réversible (`forget`) | existe | retenir une préférence, **confirmée à l'écran** |
| wikichat | `send_message` | réversible | existe | répondre dans un fil (le courrier arrive par les hooks) |
| wikichat | `list_ideas`, `add_idea` | lecture, réversible | existent | idées de la personne |
| passerelle | `gateway_find_tools`, `gateway_call_tool` | selon l'outil | existent | longue traîne, commandes réversibles seulement |

Soit environ 20 outils et environ 2 800 jetons [S, sur la base de §3.2 et des 195 jetons par
outil wikichat]. Avec les natifs retenus, environ 5 000.

| Place | Outils wikichat | Pourquoi |
|---|---|---|
| Familles, à la demande | « projets » : `set_project_meta`, `add_project_note`, `audit_project`, `audit_all_projects`, `list_project_agents`, `scan_projects`, `close_project` (engageante) ; « idées » : `get_idea`, `update_idea`, `harmonize_ideas` ; « coordination » : `read_messages`, `list_channels`, `list_sessions`, `share_artifact` ; « carte » : `run_cartography`, `run_clustering` ; « automates » en lecture : `list_routines`, `list_triggers` | utiles dans une partie des conversations |
| Invisibles : lancements | `spawn_session`, `kill_spawn`, `respawn_project_agents`, `list_spawned` | passent par l'Atelier (lot D, `atelier_deleguer`) |
| Invisibles : automates | `register_routine`, `register_trigger`, `delete_*`, `set_trigger_enabled`, `fire_trigger`, `run_routine`, `declare_project` | passent par `atelier_agent_creer`, `_activer` et `atelier_projet_creer`, qui appliquent classe et plafonds |
| Invisibles : identité, courrier | `register`, `declare_capabilities`, `set_status`, `poll*`, `declare_delay`, `claim_task`, `release_task`, `contact_agent`, `create_channel`, `get_briefing` | tenus par les hooks, pas par le modèle |
| Invisibles : réservés | `purge_registry`, `forget` en masse | jamais par un modèle |

Côté Atelier, sont exclus : `atelier_envoyer`, `atelier_transcript` et `atelier_suivre` bruts
(remplacés), ainsi que les 7 outils de profils de la passerelle.

### 4.3 Les commandes de création cadrée (famille « projets » et « agents »)

C'est l'outil qui applique les règles, pas le modèle. Chaque commande rend une carte d'action :
ce qui a été posé, **Voir**, **Annuler**, et une preuve.

| Commande | Entrées | Garantit | Inverse | Classe |
|---|---|---|---|---|
| `atelier_projet_creer` | `titre`, `objectif` (1 phrase), `gabarit` (`application`, `donnees`, `service-mcp`, `document`, `vide`), `connecteurs[]` du catalogue | slug unique ; dépôt git sur `main` avec commit d'ouverture ; `projet.json` ; `ETAT.md` au gabarit ; `CLAUDE.md` qui importe `@.atelier/contexte.md` ; `.mcp.json` en références seulement ; « créé par l'Assistant, le … » | `atelier_projet_ranger` | réversible |
| `atelier_projet_modifier` | `projet`, `titre?`, `objectif?`, `connecteurs+/-` | ne touche que `projet.json` et `.mcp.json` | valeur d'avant | réversible |
| `atelier_agent_creer` | `nom`, `consigne`, `projets[]` (0 à n), `declencheur` (manuel, horaire, événement), `plafonds` (jetons, durée), `outils` (liste fermée) | fiche d'agent **désactivée** ; profil « agent lancé » ; branche seulement | `atelier_agent_supprimer` | réversible |
| `atelier_agent_activer` | `agent` | vérifie les plafonds ; montre le coût en part du forfait | `_desactiver` | **engageante** |
| `atelier_connecteur_ajouter` | `service` du catalogue du pool, `projets[]` | références `${ATELIER_MCP_…}` seulement ; test de santé | `_retirer` | réversible (accorder un jeton : **réservée**) |
| `atelier_app_demarrer` / `_arreter` | `projet`, `nom` | existent (`atelier_artefact_*`) | l'autre | réversible |

Elles s'appuient sur les routes existantes (`POST /v1/projects`, `/mcp/import`, `POST /agent`).
Les commandes réservées (installer, partager, pousser, accorder, supprimer) **n'existent pas comme
outils** de l'Assistant : il ouvre l'écran d'accord.

### 4.4 Ce que l'Assistant édite lui-même, et le navigateur

| Cible | Il le fait lui-même ? | Comment, garde-fou |
|---|---|---|
| Contenu d'un dépôt de projet | non | `atelier_deleguer` ; `deny` sur `Edit`, `Write`, `NotebookEdit` (`projects/**`) et `Bash`, sur toutes les surfaces |
| Objets de l'Atelier (fiches, connecteurs, applications) | oui | commandes de §4.3, avec classe, inverse et carte (`assistant-role.md` §3.2) |
| Son dossier `wikichat-memory/assistant/` (brouillons, notes) | oui | `Edit` et `Write` bornés à ce chemin ; mémoire durable par wikichat, validée à l'écran |
| Ses consignes (`CLAUDE.md`, `.claude/`) | non | il propose la modification dans « À valider » : la boucle vertueuse, sous contrôle |
| Montrer une page | oui | `atelier_montrer` (le panneau), pas le Chrome de l'agent |
| Vérifier une livraison avant de la présenter | oui | famille `navigateur-verif` : `atelier_navigateur_ouvrir(projet, chemin)` (code de passage d'agent borné), `take_snapshot`, `take_screenshot`, `navigate_page`, environ 1 000 jetons [S] ; « vérifié » seulement avec une preuve |
| Tester, cliquer, remplir, réparer, `/verifier` | non | l'agent code, avec la famille navigateur complète ; le récurrent, aux gardiens |

Le navigateur (environ 5 900 jetons) n'est dans le noyau d'**aucun** profil.

### 4.6 Le modèle

| Rôle | Modèle | Pourquoi |
|---|---|---|
| Assistant (écrit et oral) | **qwen3-6-35b-moe** | 7/8 en outils déclarés, premier jeton le plus rapide (environ 0,7 s), environ 175 jetons/s [M] |
| Repli | qwen3-8-27b | 7/8 et 3/3 en catalogue, mais 2 à 3 fois plus lent, et une dérive de 2 711 jetons observée [M] |
| Sous-agents de fond (résumé de carnet, exploration d'un connecteur) | qwen3-8-27b (créneau haiku) | personne n'attend ; plus rigoureux en catalogue [M, 3 essais] |
| Lecture d'une capture | qwen3-vl, par un sous-agent qui rend du texte | [S] les `qwen3` texte ne lisent pas l'image : à vérifier |
| `agent` | à identifier | résultats proches de qwen3-6 [M] ; 1/3 en catalogue |

**Réglages** : `MAX_THINKING_TOKENS=0`. Effort **`medium`** pour l'Assistant, c'est-à-dire ne pas
lui appliquer le `xhigh` de `modelSettings` tant que sa latence n'est pas mesurée. Sortie 8 192, et
environ 300 à l'oral [S] (`assistant-contexte.md` §3.6).

### 4.7 Réglages Claude Code du dossier de l'Assistant

| Réglage | Proposition |
|---|---|
| Consignes | `CLAUDE.md` du dossier, qui importe `@.atelier/contexte.md` et `@atelier/carte.md`, et non `--append-system-prompt` (absent de VS Code). Il dit le rôle, la frontière, le ton, et « si la carte suffit, réponds sans outil ; sinon, la commande ». Aux essais de latence, « appelle plutôt » a coûté un appel, soit environ 1 s [M] |
| `# Compact instructions` | garder les délégations en cours (identifiants), les décisions en attente, les préférences et les promesses ; jeter les sorties d'outils et la carte, que `SessionStart` (source `compact`) réinjecte |
| Hooks | wikichat au niveau utilisateur : `SessionStart` ≤ 2 500 car., `UserPromptSubmit` vide s'il n'y a rien. S'y ajoute un `UserPromptSubmit` de l'Atelier pour le carnet et le canal voix (environ 80 jetons). L'ancien `Stop` (45 s) est à remplacer avant l'oral |
| Mode | `default`, sans `bypass` : les classes sont tenues par les commandes |
| Sous-agents | `explorateur` (`Read`, `Grep`, catalogue, créneau haiku, rend 10 lignes) et `lecteur-de-vue` (`qwen3-vl`). Ils isolent le contexte, mais ne réduisent pas les schémas du parent [S] |
| Commandes, skills | `/aujourdhui`, `/fait-aujourdhui`, `/annuler`. Les skills restent légères (le déroulé d'une création) : elles n'ajoutent pas d'outils, mais peuvent faire appeler `atelier_charger` [S] |

### 4.8 Délégation sans charger le contexte

`atelier_deleguer` pose le bon de commande en 7 lignes (`assistant-role.md` §3.5), ouvre la
conversation, envoie en `acceptEdits` avec `peut_attendre=vrai`, et rend un suivi aussitôt. Le
carnet, tenu par le code, reçoit la fin, l'erreur, l'autorisation en attente et le `done`
wikichat ; il arrive par `UserPromptSubmit` au tour suivant. `atelier_suivre_delegation` rend un
résumé borné du flux déjà fondu. **Jamais de transcript dans son contexte.** Les échanges entre
agents restent dans des fils wikichat ; l'Assistant ne reçoit que les messages `expects_reply`.

### 4.9 L'oral

**Le même processus Claude Code**, persistant en `--input-format stream-json` comme le harnais
le fait déjà. Pas de second modèle rapide : les mesures ne le justifient pas (environ 0,7 s
jusqu'au premier jeton, 2,1 s pour une question d'état avec un outil [M]), et il doublerait
mémoire et contradictions. Le chemin rapide se limite à **ce qui ne demande aucun modèle** :

- un accusé préenregistré (« je regarde ») quand le premier événement est un outil ou une
  délégation ;
- des réponses d'état par gabarit depuis la carte, si la personne le veut.

| Étape | Aujourd'hui | Visé |
|---|---|---|
| Fin de parole → texte | tranche fixe de 3 s + 0,8 s [M, stt-tts] | détection de fin de parole (VAD), environ 0,3 s + 0,8 s [S] |
| Texte → premier jeton | environ 0,7 s [M] | idem, 0,4 s de moins sans relancer le CLI |
| Premier jeton → première phrase | 0,2 à 0,4 s à 175 jetons/s [M] | idem |
| Phrase → son | 0,5 à 0,6 s [M, stt-tts] | idem, phrases suivantes en parallèle |
| **Jusqu'au premier mot** | environ 5 s | **environ 2,5 s sans outil, 3,5 s avec un outil** [S, somme de mesures] |

C'est la tranche STT, pas le modèle, qui pèse.

| Question | Réponse |
|---|---|
| Découpage vers le TTS | Par le pont, pas par le modèle. Il coupe les `text_delta` sur `. ? ! :` et au saut de ligne. La première phrase est coupée à la virgule au-delà de 60 caractères. Markdown et code s'affichent sans être dits |
| Interruption | La VAD coupe le TTS, puis `atelier_interrompre` : ce qui est écrit reste écrit. Une délégation lancée continue (sa carte offre **Annuler**). L'énoncé suivant part en file (`FileDesMessages`) avec « (interrompu après : « … ») », injecté par `UserPromptSubmit` |
| Continuité | Même `session_id`, même mémoire. Le pont appelle `atelier_envoyer` avec `canal: voix`. Aucune mémoire n'est validée à la voix seule |
| Chemin du son | Le service voix devient un artefact serveur (déjà déclaré). Le son passe par l'hôte des applications et le relais WS commun (`relais_ws.py`, garde d'`Origin`), sous la session du propriétaire. Le jeton du service (`voice_token`) reste dans le mandataire. Plus de port 18920 dans les `.mcp.json` |
| Vues pendant l'oral | `atelier_montrer`, puis un commentaire depuis `atelier_vue_lire` (titre, adresse, sélection : quelques dizaines de jetons). La capture part sur le geste **Montrer** ou sur une demande acceptée, par l'outil du service s'il existe (QGIS `/api/screenshot`), puis `lecteur-de-vue`. Contrat MCP Apps (`panneau.md`) |

### 4.10 Les surfaces

Tout ce qui définit l'Assistant vit dans les fichiers de son dossier (`CLAUDE.md`,
`.claude/settings.json`, `.mcp.json`, `.claude/agents|commands`) et dans les hooks utilisateur,
sans option de lancement propre. C'est donc **le même Assistant** dans l'Atelier, VS Code et le
terminal. Le modèle vient de la fiche (`--model`), sinon du réglage global. Seule la voix est
propre à l'Atelier, où vit le pont. `atelier-verifier-coherence` gagne un cas `kind=assistant`.

### 4.11 Configuration proposée (dossier `wikichat-memory/`)

`.mcp.json` : un seul serveur, en références seulement.

```json
{ "mcpServers": { "atelier": { "type": "http", "url": "http://127.0.0.1:8787/mcp",
    "headers": { "Authorization": "Bearer ${ATELIER_MCP_ATELIER_TOKEN}",
                 "X-Atelier-Profil": "assistant" } } } }
```

`.claude/settings.json`, suivi par git. Le profil, côté serveur, décide de ce qui est
**déclaré** ; les permissions décident de ce qui passe sans question (`ask` et `deny` priment sur
`allow`).

```json
{
  "enabledMcpjsonServers": ["atelier"],
  "permissions": {
    "defaultMode": "default",
    "allow": ["Read", "Glob", "Grep", "TodoWrite", "Task", "mcp__atelier",
      "Edit(/assistant/**)", "Write(/assistant/**)"],
    "ask": ["mcp__atelier__atelier_decider", "mcp__atelier__atelier_agent_activer",
      "mcp__atelier__wikichat__remember", "mcp__atelier__wikichat__close_project",
      "mcp__atelier__gateway_call_tool"],
    "deny": ["Bash", "WebSearch", "NotebookEdit",
      "Edit(//home/onyxia/work/projects/**)", "Write(//home/onyxia/work/projects/**)",
      "Edit(/CLAUDE.md)", "Write(/CLAUDE.md)", "Edit(/.claude/**)", "Write(/.claude/**)",
      "mcp__atelier__atelier_envoyer", "mcp__atelier__atelier_transcript",
      "mcp__atelier__wikichat__spawn_session", "mcp__atelier__gateway_use_profile"]
  },
  "env": { "CLAUDE_CODE_EFFORT_LEVEL": "medium", "MAX_THINKING_TOKENS": "0" }
}
```

- **Chemins** : les règles `Edit(/…)` sont relatives au dossier des réglages. Sur le pod, le dépôt
  est sous `~/work/projects/` : il faut vérifier que `deny` sur `projects/**` laisse passer
  `/assistant/**`. Sinon, on sort le dépôt de `projects/`, comme le prévoit l'alignement.
- **Défense en profondeur** : les `deny` MCP doublent le profil. Un refus retire l'outil de la
  liste du modèle : mesuré pour `WebSearch` [M], supposé pour les outils MCP [S].
- **Sans interlocuteur** : `atelier_envoyer` refuse d'office ce qui est en `ask`, et la demande
  s'affiche dans « À valider ».

Fiche de l'Assistant, dans l'Atelier : `kind=assistant`, modèle `qwen3-6-35b-moe`, repli
`qwen3-8-27b`, mode `default`.

## 5. Parcours (vus par l'agent)

1. **« Où en est ma carte ? »** Le carnet arrive par le hook (« d-4821 fini, preuve
   `/verifier` »). Réponse sans outil, en 3 phrases, avec **Voir**.
2. **« Crée un projet budget dans Grist. »** `atelier_charger("projets")`, une question sur le
   gabarit, `atelier_projet_creer`, une carte « Annuler », puis une proposition de déléguer la
   première page.
3. **À l'oral : « Montre-moi l'application, l'export marche ? »** Accusé sans modèle,
   `atelier_montrer`, `navigateur-verif`, `take_snapshot`. Première phrase en environ 3,5 s [S].
   Si la personne coupe : TTS arrêté, tour interrompu, demande en file.

## 6. Étapes

| Étape | Contenu | Démonstration |
|---|---|---|
| **H0 Mesures manquantes** | premier jeton en `xhigh` ; T1 à T5 × 5 essais avec des résultats d'outils réalistes, pas « ok » ; noyau réel ; `deny` de `Bash` et `NotebookEdit` ; `Edit` borné à un chemin ; effet de `Task` et `TodoWrite` sur le coût | un tableau à 5 essais par case |
| **H1 Profil `assistant`** | en-tête `X-Atelier-Profil` ; profil = noyau ; méta-outils de profils masqués ; `atelier_charger` et `atelier_decharger` par `listChanged` (sur `bundles` et `tools_change_tracker`) | la liste d'outils reçue diffère selon le profil ; une famille chargée apparaît en cours de tour |
| **H2 Dossier de l'Assistant** | `CLAUDE.md`, `settings.json`, `.mcp.json`, agents, commandes ; cas `kind=assistant` dans `atelier-verifier-coherence` | même liste d'outils, même contexte et mêmes refus dans l'Atelier, VS Code et le terminal |
| **H3 Commandes de création** | `projet_creer`, `agent_creer`, `connecteur_ajouter`, avec classe, inverse, carte et preuve, sur les routes HTTP existantes | parcours 2 de bout en bout, puis **Annuler** |
| **H4 Délégation** | `atelier_deleguer`, carnet, `UserPromptSubmit`, `atelier_suivre_delegation` | parcours 1 sans transcript dans le contexte |
| **H5 Profils agent code et agent lancé** | navigateur en famille pour l'agent code ; liste fermée pour l'agent lancé | environ 5 900 jetons gagnés par appel pour un agent code qui ne navigue pas |
| **H6 Boucle orale** | processus persistant, VAD, découpage par phrase, interruption, `canal: voix` ; son par le relais WS | premier mot < 3,5 s, mesuré de bout en bout |

## 7. Risques et questions

### 7.1 Risques

- **Mesures fragiles** : un essai par case, un stub « ok » qui fausse les suites, des jetons
  estimés (caractères divisés par 3,4). H0 est un préalable.
- **Faux souvenir** : en catalogue, qwen3-6 a répondu depuis le briefing avec un détail faux. Le
  contexte injecté doit être exact et daté, et une réponse d'état cite sa source.
- **Délégation** : c'est le geste le moins sûr, le modèle explore d'abord. D'où une commande
  unique et un exemple dans `CLAUDE.md`.
- **CLI** : `list_changed` est pris en compte en 2.1.281 [M], à garder en test de
  non-régression. Le hook `Stop` actuel (45 s) est incompatible avec l'oral.

### 7.2 Questions pour Nicolas

1. `qwen3-cursor` n'est pas servi. Est-ce `agent` ? Quel modèle viser ?
2. Une seule porte (la passerelle compose `atelier_*` et un sous-ensemble de wikichat), plutôt
   que wikichat déclaré en direct ?
3. L'Assistant peut-il écrire (`Edit`/`Write`) dans `wikichat-memory/assistant/`, ou tout
   passe-t-il par des commandes ?
4. Faut-il garder `xhigh` pour `qwen3-6-35b-moe` dans `modelSettings`, malgré la latence orale ?
5. Quel est le chemin du dépôt mémoire : `~/work/projects/wikichat-memory` (pod) ou
   `~/work/wikichat-memory` (alignement) ?
6. Les familles par `list_changed` comme mécanisme principal, et le catalogue pour la longue
   traîne seulement ?
7. Les captures sont-elles lues par `qwen3-vl` en sous-agent ?

## 8. Évaluation

| | Verdict | Sur quoi |
|---|---|---|
| **Désirable** | oui | Un Assistant rapide à l'écrit comme à l'oral (0,7 s jusqu'au premier jeton [M]). Il fait les bons gestes (88 % en outils déclarés [M]) et ne peut pas sortir de son rôle. |
| **Faisable** | oui, par étapes | `list_changed`, profils de session, `atelier_*`, relais et hooks existent ou sont écrits [M]. Il manque le profil `assistant`, les commandes de création, le carnet et le pont oral. |
| **Viable** | oui | Environ 5 000 jetons d'outils au lieu d'environ 70 000 [C]. Une seule configuration par fichiers, identique sur les surfaces. Pas de second modèle à entretenir. |
| **Cohérent** | oui | Profils par acteur (`architecture-transverse.md` §1.5), catalogue de commandes (§1.8), carte et hooks (`assistant-contexte.md`), classes et cartes d'action (`assistant-role.md`), vues MCP Apps (`panneau.md`). |
