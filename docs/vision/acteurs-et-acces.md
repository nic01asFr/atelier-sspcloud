# Les acteurs de l'Atelier : qui agit, avec quel profil, quels accès

Carte du 16/10/2026, lue dans le code (`mcp_sync.py`, `commandes/profils.py`, `lancements.py`, `commandes/agents.py`, `automates.py`, `auth.py`, `gardiens/`) et dans `architecture-transverse.md` §1.1, `profils-acces.md`, `cadrage-des-agents.md`. Rien n'a été testé sur le pod pour ce document. Ce qui est dit « code » est lu dans le code ; « doc » veut dire annoncé par un document, non retrouvé dans le code.

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
