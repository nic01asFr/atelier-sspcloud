# Les acteurs de l'Atelier : qui agit, avec quel profil, quels accès

Carte du 16/10/2026, lue dans le code (`mcp_sync.py`, `commandes/profils.py`, `lancements.py`, `commandes/agents.py`, `automates.py`, `auth.py`, `gardiens/`) et dans `architecture-transverse.md` §1.1, `profils-acces.md`, `cadrage-des-agents.md`. Les §1 à §6 sont lus dans le code ; « doc » veut dire annoncé par un document, non retrouvé dans le code. Le §7 est un **relevé fait sur le pod le 16/10** (lecture seule, aucune valeur secrète affichée) ; le §8 décrit l'état visé.

## 1. Les acteurs

| # | Acteur | Ce que c'est | Identité | Profil d'accès |
|---|---|---|---|---|
| 1 | **Personne** (l'App) | la propriétaire, par l'interface web (PWA) ou la clé du propriétaire | session de l'interface, ou clé du propriétaire | aucun profil : décide, active, confirme. Invités : plus tard |
| 2 | **Assistant** | une conversation `kind=assistant`, dossier de l'Assistant, sans projet à lui | `session_id` | `assistant` |
| 3 | **Agent de projet** | une conversation `kind=code` dans un projet | `session_id` | `code` |
| 4 | **Agent lancé, supervisé** | un agent qu'un autre agent (l'Assistant) a lancé, après aperçu et « Oui » de la personne | fiche avec `lance_par` | `code` du projet visé |
| 5 | **Agent déclaré** (Pilote) | un agent planifié ou « à la demande » : un trigger `cron` de wikichat dont l'action est de lancer une session | fiche avec `lance_par`, origine `trigger:…` ou `routine:…` | `code` du projet visé, plus sa liste d'outils |
| 6 | **Agent réparateur** | lancé par un gardien sur une branche `gardien/…` | origine `gardien:<nom>` | `code`, en plus bridé |
| 7 | **Sous-agent natif** | un agent défini dans le projet (`.claude/agents`), appelé par un agent de projet | celui de son parent | hérite de la conversation du parent (à vérifier : cadrage §188) |
| 8 | **Gardien** | du code sans modèle, exécuté par un démon (port 8791), 0 jeton | `gardien:<nom>` | liste fermée de gestes (`gardiens.json`) |
| 9 | **Application** | une création en mode serveur d'un projet | processus du projet | aucun profil d'agent ; jeton de capacité prévu, non construit (J8) |
| 10 | **Client externe** | VS Code, terminal, claude.ai, la passerelle | en-têtes `X-Atelier-*` | `code` par défaut ; sans conversation, ancien comportement (tout) |

Trois mots recouvrent des choses différentes :

- **Profil d'accès** (`code`, `assistant`) : ce que `mcp_sync.configuration_du_profil` distribue. C'est le sens du présent document.
- **Profil de la passerelle** (org, personnalisés, `resolve_web_profile`) : un ensemble de connecteurs de la passerelle. Il pré-remplit le formulaire d'un agent déclaré, et n'est pas le profil d'accès.
- **Profil wikichat** (`WIKICHAT_PROFIL`) : le pont dit à wikichat quel profil servir.

Les « cinq niveaux » de la page Agents (Observateur, Assistant, Automate de routine, Agent de projet, Agent plateforme) sont dans `cadrage-des-agents.md` §2.6 (doc) et n'existent pas dans le code.

## 2. Comment un acteur reçoit son profil

- **Côté serveur, par la fiche de la conversation** (`profil_effectif`, code). `kind=assistant` donne `assistant` ; tout le reste donne `code`.
- Pour une conversation connue, l'en-tête `X-Atelier-Profil` ne peut que **restreindre**. Pour une conversation inconnue (VS Code, terminal), l'en-tête décide, `code` par défaut ; `assistant` exige un dossier sous celui de l'Assistant et l'absence de projet annoncé.
- Un appel **sans conversation** garde l'ancien comportement (tout) et est journalisé. C'est le chemin de la passerelle et de claude.ai.
- Les agents lancés n'ont pas de profil à eux : ils ont **le profil `code` du projet visé**, plus des plafonds et un mode (§4).
- **Limite assumée par le code** : la clé de la porte est celle du propriétaire, lisible par tous les agents du pod. Un agent qui omet l'en-tête de conversation garde l'accès complet.

## 3. Accès par acteur et par service

`✔` complet · `◐` borné · `✘` rien · `?` non établi

| Service | Assistant | Agent de projet (`code`) | Agent lancé / déclaré | Réparateur de gardien | Gardien |
|---|---|---|---|---|---|
| **Outils `atelier_*`** | tous (carte, « À valider », journal, décider, lancer, ouvrir, envoyer, suivre) ✔ | seulement ceux de son projet : créations, `montrer`, `navigateur_ouvrir`, `rappel`, `fiche` ◐ | idem + `demander_au_lanceur` si supervisé ◐ | idem ◐ | — |
| **Méta-outils de la passerelle** (`gateway_find_tools`, `gateway_call_tool`) | ✔, classes d'action vérifiées côté serveur | ✘ | ✘ | ✘ | — |
| **wikichat** | complet ✔ | limité à son projet (notes, mémoire, fils, messagerie) ◐ | idem ◐ | idem ◐ | — |
| **Onyxia** | complet, par `/mcp/onyxia` ✔ | seulement par le `deploiement` déclaré par son projet, borné à ses pods (`cible` cpu / gpu) ◐ | idem ◐ | idem ◐ | — |
| **Navigateur** | `navigateur_ouvrir` en désignant un projet ✔ | sa propre fenêtre Chrome isolée, plafonds d'onglets ◐ | idem ◐ | idem ◐ | garde de navigation |
| **Autres connecteurs du pool** (QGIS, Blender, GitHub, data.gouv, LLM, filesystem, GitLab) | ceux choisis pour l'Assistant ; le reste par les méta-outils ◐ | **tous ceux du pool si le projet n'a pas choisi** (héritage), sinon son choix ; **au grain du connecteur, jamais de l'outil** ✔/◐ | connecteurs du projet ; `outils` du lancement ou de l'agent = règles `permissions.allow` ◐ | idem ◐ | — |
| **Outils natifs** (fichiers, Bash, recherche) | `?` (sous-agents refusés, doc) | tous sauf `WebSearch` ✔ | selon la liste fermée (`Read`, `Glob`, `Grep`, `WebFetch`, `Bash`, `Write`, `Edit`) ◐ | dans la copie de travail seulement ◐ | — |
| **Écrire sur `main`, pousser** | non | selon le mode et le projet | **jamais** : branche `agent/…`, crochets git qui refusent le reste | branche `gardien/…`, jamais poussée | — |
| **Lancer un agent** | `atelier_lancer_agent` (engageante, aperçu, jeton) ✔ | ✘ | ✘ (le Pilote passe par `/v1/lancements`, clé du lanceur) | ✘ | demande une réparation, sous plafond |
| **Activer un agent déclaré** | ✘ | ✘ | ✘ | ✘ | ✘ — **réservé à la personne** |

## 4. Caractéristiques de chaque rôle

### Personne (l'App)
Seule à décider : activer un agent déclaré, couper un gardien, répondre à « À valider », choisir le mode de permission (dont `bypass`), déclarer le `deploiement` d'un projet (commande engageante), accorder une capacité. Accès par session de l'interface ou clé du propriétaire ; les invités viendront plus tard. L'App est le seul endroit où elle voit tout : conversations, vue Agents (agents planifiés **et** gardiens, J-i), « À valider », panneau (créations, navigateur, bureaux).

### Assistant
Sans projet, il **délègue plutôt qu'il n'agit** (principe, « à revoir à l'usage »). Il gère les objets de l'Atelier, lance des agents (aperçu, jeton, « Oui »), montre les créations d'un projet qu'il nomme et ouvre un navigateur sur un projet désigné. Les gestes lourds passent par « À valider » ou un accord explicite. Il reçoit les connecteurs que la personne lui a choisis et atteint le reste par les méta-outils, dont la classe (lecture, engageante, réservée) est vérifiée côté serveur à l'appel.

### Agent de projet
Travaille **dans son projet**. Voit les créations et le contexte de son projet, pas les autres projets : pour agir ailleurs il écrit aux agents de ce projet (wikichat), et `atelier_demander` n'existe pas encore (cadrage §2.4). Mode de permission par projet, remplaçable par conversation ; `bypass` n'est pas hérité par les agents lancés.

### Agent lancé (délégation supervisée)
Une conversation comme les autres (donc une fiche, visible dans l'App), avec :
- `lance_par` et un lien avec son lanceur : ses demandes d'autorisation, **dans le périmètre du lanceur**, remontent à celui-ci (`atelier_decider`) ; le reste revient à la personne ;
- ce périmètre est tracé en code (`perimetre_du_lanceur.py`) : lire et écrire dans le dossier du projet, commandes locales courantes ; hors périmètre : secrets, `.git`, réseau, `git push`, suppressions récursives, installation de dépendances, autres outils (Onyxia, wikichat, web) ;
- sur branche (`agent/…`) : copie de travail (`git worktree`), crochets git, fin vérifiée par le code et déposée dans « À valider » ; l'action de fusion est réservée à la personne ;
- plafonds : durée (1800 s au plus), simultanés, lancements par jour et par origine (24).

### Agent déclaré (Pilote)
Un trigger `cron` de wikichat dont l'action lance une session ; « à la demande » = un horaire qui ne tombe jamais. Règles de création (J-b, J-b2) :
- naît **désactivé** ; budget obligatoire (tours ≤ 100, lancements par jour ≤ 24, pause) ;
- l'activer est réservé à la personne ; le désactiver est permis à tous ; une modification faite par un modèle le désactive ; un modèle ne supprime pas un agent actif ;
- outils en **liste fermée**, intégrés ou connecteurs du pool au grain du connecteur (`mcp__<connecteur>`), par défaut `Read`, `Glob`, `Grep`, jamais `WebSearch`.

Nuance, lue dans `lancements.py` : la liste d'`outils` d'un lancement devient des règles `permissions.allow`, donc une **pré-autorisation**, pas une restriction de ce qui est visible. Le mode par défaut est `acceptEdits`, ou celui du projet ; `bypassPermissions` n'est accordé qu'à une définition de routine ou de trigger **et** si le projet l'accorde lui-même. L'agent reçoit donc les connecteurs de son projet ; ce qui n'est pas autorisé est refusé ou posé en question, selon le mode. Un lancement ne coupe pas la liste des outils visibles : il ne réduit que ce qu'il peut faire sans demander.

### Réparateur de gardien
Lancé par un gardien (origine `gardien:<nom>`) sur une branche `gardien/…`. Jamais supervisé (personne pour répondre), jamais `bypass`, plafond de réparations par jour, durée plafonnée. L'Atelier (le code, pas le modèle) vérifie que la base n'a pas bougé et dépose une proposition dans « À valider ».

### Sous-agent natif
Défini dans `.claude/agents` du projet ; passe par le natif pour son propre projet, par `demander` (à créer) pour un autre. Deux points ouverts dans `cadrage-des-agents.md` : héritent-ils des serveurs MCP du parent, et sous quel profil ? Des sous-agents par défaut (`relecteur`, `explorateur`, outils fermés) sont prévus.

### Gardien
Du code, pas un modèle : contrôles en JSON (`sante.*`, `securite.*`, `entretien.*`, `coherence.*`), gestes en liste fermée (relancer un service…), 0 jeton. Pilotage par un jeton local que le navigateur ne voit jamais. Couper un gardien est réservé à la personne (c'est retirer un filet) ; le relancer ne l'est pas. Chaque geste va au journal unique.

### Application
Une création en mode serveur : même utilisateur Unix que les agents, quatre au plus, 1,5 Gio, arrêt après 30 min d'inactivité, accès par l'hôte des applications (code de passage de la session de la personne), cadrage `frame-ancestors`. Elle n'appelle pas l'Atelier : le jeton de capacité est conçu, pas construit.

## 5. Ce que la carte montre

1. **Un projet hérite par défaut de tout le pool.** Un agent de projet qui n'a pas de `.mcp.json` choisi reçoit QGIS, Blender, GitHub, GitLab, n8n, data.gouv, LLM, filesystem. Seuls `atelier`, wikichat, le navigateur et Onyxia sont filtrés par rôle.
2. **Le grain est celui du connecteur**, jamais de l'outil, pour tout sauf Onyxia. Aucun rôle « QGIS en lecture ».
3. **Les agents lancés n'ont pas de profil propre.** Un agent de revue, de recherche ou de routine reçoit celui d'un agent de projet, réduit par des permissions, pas par la distribution.
4. **`outils` pré-autorise plus qu'il ne restreint** (voir plus haut). La « liste fermée » n'est donc fermée que si le mode ne l'ouvre pas.
5. **La frontière des profils est une politique.** La clé du propriétaire est lisible par tous les agents du pod (limite écrite dans `commandes/profils.py`). Des capacités courtes par conversation la transformeraient en frontière.
6. **Trois sens du mot « profil »**, et des « niveaux » de la page Agents qui ne sont que dans la doc.
7. **Pas de gestes entre agents** : `atelier_demander` (cible, message, réponse liée) n'existe pas ; entre agents, on a le courrier de wikichat et, pour les agents qu'on a lancés, `atelier_demander_au_lanceur`.
8. **Les sous-agents natifs et les clients externes** (VS Code, terminal) sont le point le moins établi : leur profil dépend d'en-têtes que l'agent pose lui-même.

## 6. Suite possible

- Une **matrice déclarative** (acteur × service × niveau : aucun, lecture, projet, tout) lue par `mcp_sync`, le vérificateur de cohérence et les gardiens, au lieu d'être répartie entre quatre modules.
- Des **profils d'agent lancé** nommés (lecteur, rédacteur, déployeur), choisis à la création d'un agent déclaré, qui réduisent la distribution et non seulement les permissions.
- **Capacités courtes par conversation** pour fermer le point 5.
- Un **moule de mandataire borné** commun (point A1 de `n8n.md`) pour appliquer cette matrice à QGIS, Blender et n8n.

## 7. Relevé sur le pod (16/10/2026)

Mesuré dans `atelier-0`, par les fonctions mêmes de l'Atelier (`configuration_du_profil`, `herite_du_pool`) et par des appels réels à la porte `/mcp`.

| Constat | Mesure |
|---|---|
| Conversations ouvertes | 59 de code (personne), 41 de l'Assistant, 27 lancées (13 par la personne, 12 par un client distant, 2 par une conversation) |
| Projets qui **héritent de tout le pool** | **27 sur 40** (10 ou 11 connecteurs chacun) |
| Connecteurs reçus par un agent de projet | `atelier` 40 · `wikichat` 40 · `filesystem` 33 · `chrome-devtools-mcp` 33 · `datagouv` 31 · `llm` 31 · `qgis` 29 · `blender` 28 · `gitlab` 28 · `grist-coder` 28 · `Onyxia` 4. `n8n` et `github` ne sont distribués nulle part |
| Connecteurs reçus par l'Assistant | `Onyxia`, `atelier`, `chrome-devtools-mcp`, `filesystem`, `wikichat` |
| `tools/list` de `/mcp`, Assistant | 52 outils : 43 `atelier_*` + 7 `gateway_*` |
| `tools/list` de `/mcp`, agent de projet | **11** `atelier_*`, aucun `gateway_*` ; ni `lancer_agent`, ni `decider`, ni `a_valider`, ni `agent_creer`, ni `projet_deployer_declarer` |
| Agent de projet qui annonce `X-Atelier-Profil: assistant` | reste à 11 : l'en-tête ne peut que restreindre (**bon**) |
| Agent lancé (par la personne) | 11 `atelier_*`, comme un agent de projet |
| **Appel avec la clé du propriétaire, sans conversation ni profil** | **57 outils**, dont `lancer_agent`, `decider`, `agent_creer`, `projet_deployer_declarer` ; 5 outils de plus que l'Assistant |
| Appel sans clé | 401 |
| `filesystem` | racine **`~/work` tout entier** (tous les projets, les secrets, l'état de l'Atelier), distribué à 33 projets et à l'Assistant |
| `gitlab` | jeton personnel dans l'environnement du connecteur, distribué à 28 projets |
| Agents déclarés (Pilote) | **0** ; 3 triggers de wikichat (2 « sans déclaration », 1 coupé), tous sans budget ; le gardien Entretien alerte deux fois « trigger actif sans budget déclaré » |
| Lancements depuis l'origine | 27 : 13 personne, 12 client distant, 2 conversation. **Aucun** par un trigger, une routine ou un gardien. 16 supervisés, 9 sur branche, **0 avec liste d'outils**. Modes : `default` 13, `acceptEdits` 12, `plan` 2 ; jamais `bypass`. Aucune branche hors `agent/` ou `gardien/` |
| Modes de permission des projets | `acceptEdits` 38, `default` 1, `bypassPermissions` 1 ; sur les fiches : `bypassPermissions` 9, `auto` 3 |
| Gardiens | Sécurité ok · Santé « attention » (CI et commit de `main` illisibles, disque à 85 %, volume à 89 %) · Cohérence « alerte » : `wikichat` en échec pour l'Assistant et pour un agent de projet (cause non établie : wikichat tourne, son port répond) · Entretien « attention » |

À retenir :
- Le filtrage du **profil** marche : un agent de projet n'a que 11 outils de l'Atelier et ne peut pas s'élever par un en-tête.
- Il ne tient qu'à un en-tête : sans lui, la clé du propriétaire ouvre **tout**. Or cette clé est dans la configuration de chaque agent (`${ATELIER_MCP_KEY}`) et le fichier est lisible par le même utilisateur Unix.
- La distribution des **services** n'est pas bornée par rôle : 27 projets sur 40 reçoivent QGIS, Blender, GitLab, Grist et un `filesystem` qui couvre tout le volume.
- Les trois chemins d'agents automatiques (déclaré, trigger, réparateur de gardien) n'ont **jamais servi en production** : leurs règles sont écrites et testées, pas éprouvées.

## 8. L'état optimal, par type d'agent

### Principes

1. **Refus par défaut.** Un projet part avec `atelier`, wikichat (borné à lui) et le navigateur. Tout autre service entre par une **déclaration du projet** (comme `deploiement`), avec un niveau : *aucun, lecture, projet, tout*.
2. **Une matrice, pas quatre modules.** Acteur × service × niveau, dans un fichier lu par `mcp_sync`, les mandataires, le vérificateur de cohérence et les gardiens. Un écart devient une alerte lisible.
3. **Une vraie frontière.** Une **capacité courte par conversation** (jeton signé : session, projet, profil, durée) remplace la clé du propriétaire dans la configuration d'un agent. Sans capacité, pas d'accès : « sans conversation » cesse d'ouvrir tout.
4. **Des rôles nommés pour les agents lancés** (lecteur, rédacteur, déployeur, automate, réparateur), qui fixent la **distribution** (ce que l'agent voit) et pas seulement les permissions (ce qu'il peut faire sans demander).
5. **Toute ressource unique a un verrou et un propriétaire** (QGIS, Blender, GPU, éditeur n8n) : un agent à la fois, ou lecture seule.
6. **Un budget partout** : tout automate déclare tours, lancements par jour et durée ; sans budget, il ne part pas.
7. **Une identité et une provenance dans chaque couche** (`session_id`, origine, profondeur de lancement), journalisées.

### Par type

| Acteur | État actuel (mesuré ou lu) | État optimal | Écart principal |
|---|---|---|---|
| **Personne / App** | clé du propriétaire ou session ; seule à activer, couper, confirmer | idem, plus **invités avec rôles** ; la clé du propriétaire ne quitte jamais l'interface | invités absents ; clé présente dans l'environnement des agents |
| **Assistant** | 52 outils (43 + 7), `filesystem` sur tout le volume, Onyxia complet | atelier complet + méta-outils + wikichat + Onyxia ; **pas de `filesystem`**, pas d'écriture dans les projets (il délègue) ; services directs seulement par mandataire | `filesystem` ; 41 conversations ouvertes (hygiène) |
| **Agent de projet** | 11 outils `atelier_*` ; hérite de tout le pool dans 27 projets sur 40 | atelier (11) + wikichat de son projet + navigateur + **services déclarés à leur niveau** (Onyxia, n8n par étiquette, QGIS/Blender en lecture par défaut, GitHub limité à son dépôt) ; pas de `filesystem` | héritage ; grain du connecteur ; pas de mandataire hors Onyxia |
| **Agent lancé, supervisé** | profil `code` du projet, branche `agent/…`, périmètre du lanceur ; 16 supervisés dont 9 sur branche, 0 liste d'outils | rôle *rédacteur* ou *déployeur* : **surface ⊆ celle du lanceur**, distribution réduite à ce que le rôle exige, branche obligatoire pour le code | `outils` n'a jamais servi ; surface non calculée |
| **Agent déclaré / cron** | 0 agent déclaré ; 3 triggers sans budget ; `outils` = pré-autorisation | rôle *automate* : naît désactivé, **budget obligatoire (refus sinon)**, distribution réduite à ses connecteurs, activation par la personne, jamais `bypass` ; origine visible dans l'App | chemin jamais exercé ; triggers de wikichat hors règles J-b |
| **Réparateur de gardien** | règles écrites (branche `gardien/…`, base vérifiée, « À valider ») ; **jamais lancé** | idem, **exercé** sur un cas réel avant d'être compté comme acquis | non éprouvé |
| **Sous-agent natif** | hérite du parent ; MCP hérité ou non : à mesurer | outils fermés dans sa définition ; **surface ⊆ parent** ; pas de lancement d'agent | non mesuré |
| **Gardien** | du code, liste fermée de gestes ; alerte Cohérence ouverte sur `wikichat` | idem, plus **contrôle de la matrice** (écart de distribution = alerte) | la matrice n'existe pas |
| **Application** | même utilisateur Unix que les agents ; jeton de capacité non construit | **capacité déclarée puis accordée**, quotas, plus de clé de l'Atelier dans son environnement | J8 non construit |
| **Client externe** (VS Code, terminal, claude.ai, passerelle) | `code` par défaut ; sans conversation, **tout** | **capacité courte émise par l'Atelier** par session ; profil `externe` minimal sans elle | clé du propriétaire = accès complet |

### Ordre pour y arriver

1. **Retirer `filesystem` de la distribution** (ou le limiter au dossier du projet) et sortir les services sans mandataire de l'héritage : sans effet de bord, grand gain. Mesure : le relevé du §7 doit tomber à 0 projet qui hérite de tout.
2. **Matrice déclarative** + contrôle des gardiens, qui rend le §7 vérifiable chaque jour.
3. **Moule de mandataire borné** (`n8n.md`, A1), puis QGIS et Blender en lecture par défaut.
4. **Rôles nommés** pour les agents lancés ; budget obligatoire pour tout automate ; distribution réduite par rôle.
5. **Capacités courtes par conversation**, puis clé du propriétaire retirée de l'environnement des agents.
6. **Exercer** les trois chemins jamais servis (déclaré, trigger, réparateur) sur un cas réel, avant de les compter comme acquis.
