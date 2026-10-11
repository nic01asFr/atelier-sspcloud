# État des lieux de l'Atelier et dispensation par rôle

*Écrit le 11/10/2026. Sources : le code (relu fichier par fichier), les documents de vision, le
pod réel (carte, journal et lancements lus par les outils de l'Atelier le 11/10), et la
documentation officielle de Claude Code (code.claude.com). Ce qui n'a pas été vérifié est dit.*

## 1. Le but

Chaque agent reçoit, **sans que la personne ni l'agent n'y pensent**, ce que son rôle exige :
ses outils, ses permissions, ses garde-fous, ses consignes, ses commandes. Et rien de plus.
Le tout posé **par la mécanique de Claude Code** (réglages, hooks, permissions, plugins), pas
par des consignes que le modèle pourrait ignorer ; **identique** dans l'application, VS Code et
le terminal ; **vérifié** à chaque tour.

Les principes de `cadre.md` restent : simple et lisible, natif et standard, un seul modèle,
construire sur l'existant, sûr par construction, sobre.

## 2. Verdict

**Ce qui marche bien** (vérifié) : la porte `/mcp` et ses profils (le profil se décide côté
serveur, la liste et l'appel sont filtrés), une seule fonction pour la configuration MCP de toutes
les surfaces (`configuration_du_profil`), le socle posé de façon atomique, le vérificateur de
cohérence (il a trouvé de vraies divergences sur le pod), la supervision des agents lancés,
l'interface, le journal, « À valider ».

**Ce qui ne tient pas encore** :

1. **Un rôle n'est défini nulle part.** Ses règles sont recalculées à plusieurs endroits (le mode
   de permission en 4, le refus de `WebSearch` en 4, Onyxia en 5, les listes d'outils en dur dans
   le vérificateur). Elles divergent : le mode différait selon la surface sur un projet réel.
2. **Les agents lancés échouent en silence.** Un agent lancé sans supervision, sans `outils`, sur
   une copie de travail n'a accès à **aucun outil MCP** (l'Atelier le refuse automatiquement faute
   d'interlocuteur). Constaté sur le pod les 6 et 7/10 : « les outils MCP sont verrouillés »,
   l'agent s'arrête ou demande un copier-coller, **et le lancement est marqué « fini »**. Un
   réparateur de gardien ne peut pas exécuter la vérification que son brief lui demande.
3. **Les secrets et la clé propriétaire sont donnés à tous les agents.** `ATELIER_MCP_KEY`, les
   secrets du pool et les variables de tous les projets sont dans l'environnement de chaque
   `claude`. La protection est une consigne, plus un hook qui ne regarde que `Bash` et la chaîne
   `.secrets`. L'Assistant peut lire `.secrets/**` (seule l'écriture est refusée).
4. **Les garde-fous reposent sur un fichier posé une fois.** `garde_bash` est installé par le
   processus des gardiens au démarrage, jamais redonné au tour. S'il manque, le socle dit
   « un hook refuse, sur toutes les surfaces » et c'est faux. Il ne couvre ni `Read`, ni `Write`,
   ni `Edit`.
5. **On ne sait pas ce que l'agent a réellement reçu.** Le contrôle de cohérence passe une fois
   par jour sur un projet par profil. Sur le pod, deux alertes graves restent ouvertes : le
   serveur `wikichat` est en échec dans l'application pour l'Assistant et pour un projet, donc
   ces agents travaillent sans mémoire ni coordination, sans que personne ne soit prévenu.
6. **La structure d'un projet n'est pas posée d'office** : 5 projets actifs sur 14 n'ont pas
   d'`ETAT.md`. Le kit commun (`/reprendre`, `/verifier`, `/fin-de-lot`, `/proposer`) est annoncé et
   n'existe pas.
7. **Le jeton limité par conversation (D1) n'existe pas** : tout agent qui lit la clé a un accès
   complet à `/v1`.

## 3. État des fonctions

| Fonction | État | Où | Fiabilité observée |
|---|---|---|---|
| Projets, conversations, fil, composeur | en service | `sessions.py`, `web/` | solide ; corrigés cette semaine : un tour à la fois, fin de tour sans écrasement, historique, « Nouveau projet » |
| Profils d'accès (code, assistant) | en service | `commandes/profils.py`, `mcp_sync.py` | bonne pour les outils ; **trouée** par la clé partagée et les requêtes sans conversation |
| Assistant | en service | `assistant.py` | lecture des secrets non refusée ; `wikichat` en échec (alerte ouverte) |
| Agents lancés, supervision, périmètre | en service | `lancements.py`, `perimetre_du_lanceur.py` | périmètre durci le 03/10 ; **agents non supervisés sans outils** ; plafond de jetons lu mais jamais appliqué |
| Commandes de l'Atelier, « À valider », journal, annulation | en service | `commandes/` | solide |
| Créations, panneau, bureaux, navigateur | en service | `apps/`, `panneau.py`, `navigateur.py` | bonne ; essais réels faits |
| Connecteurs, passerelle, secrets par référence | en service | `mcp_sync.py`, `accords.py` | clés de l'Atelier réservées (03/10) ; identifiants du pool en clair dans `gateway.db` |
| wikichat (coordination, mémoire) | en service | externe + `wikichat_*.py` | **filtre de profil non vérifiable dans ce dépôt**, contrôlé seulement par l'audit |
| Mémoire | en service | `memoire*.py` | 49 propositions en attente |
| Gardiens et réparateurs | en service | `gardiens/` | le geste « relancer l'Atelier » a été **refusé** le 07/10 ; réparateur sans moyen de vérifier |
| Onyxia lié au déploiement, GPU | en service / spec | `onyxia_projet.py`, `gpu-arbitrage.md` | GPU journalisé depuis le 03/10 ; arbitrage = spec seulement |
| Vérificateur de cohérence | en service | `coherence.py` | utile ; **trop rare** (1 fois par jour, 1 projet par profil) |
| Kit commun (commandes, hooks, sous-agents) | **spec seulement** | `kit-atelier.md` | rien n'est livré |
| Jeton limité par conversation (D1) | **pas fait** | `profils-acces.md` | — |
| Voix, partage, brouillon/production | pas fait | `ecosysteme.md`, `voix.md` | — |

## 4. Ce que Claude Code offre pour tenir les règles (sources officielles)

À retenir pour décider (détail et sources dans la section 9) :

- **Fiable** : `permissions.deny` (un refus à un niveau ne se lève à aucun autre, même en
  `bypassPermissions`), hooks `PreToolUse` (sortie 2 ou décision `deny`), `--tools` (ensemble des
  outils), `--permission-mode dontAsk` avec `--allowedTools`, `--strict-mcp-config`,
  `--settings` (ajoute des deny et des hooks), `--append-system-prompt-file`, `--max-turns` et
  `--max-budget-usd`. L'événement `system/init` dit les outils et serveurs MCP réellement chargés
  et le résultat final liste `permission_denials`.
- **Réglages gérés** (`/etc/claude-code/managed-settings.json`) : aucun niveau ne les surcharge,
  `--settings` compris. Mais ils valent pour **toute la machine** : on ne peut pas différencier les
  rôles avec, seulement poser un **plancher commun**.
- **Pas une garantie** : `CLAUDE.md` est du contexte, pas de la configuration (la doc le dit) ;
  les règles `Bash(...)` se contournent (`sh -c`, chemin absolu) ; le bac à sable ne couvre que
  `Bash`.
- **Pièges** : un hook qui sort en 1 ne bloque pas ; avec `--resume` le prompt système enregistré
  est réutilisé (il faut `--system-prompt-snapshot off`) ; le `permissionMode` d'un sous-agent est
  ignoré si le parent est en `bypassPermissions` ou `acceptEdits`.

## 5. Le modèle cible : un rôle = une définition, compilée vers les mécanismes natifs

Un seul module, `roles.py`, décrit chaque rôle **une fois** :

```
Role(nom, outils_natifs, outils_mcp, regles_allow, regles_deny, hooks,
     consignes, kit, env_autorise, dossier, mode_par_defaut, plafonds)
```

Rôles de départ (les mêmes que dans l'interface, en langage courant) :
« Lire et réfléchir », « Travailler dans ce projet », « Travailler et publier sur la
plateforme », « Piloter d'autres agents », plus les rôles internes (Assistant, gardien,
réparateur).

Un **compilateur** transforme un rôle en ce que Claude Code comprend, au lancement de chaque tour
**et** dans les fichiers lus par VS Code et le terminal :

| Ce que le rôle exige | Mécanisme natif | Garantie |
|---|---|---|
| Outils MCP du rôle | `--mcp-config` + `--strict-mcp-config`, filtre à la source (existe) | forte |
| Outils natifs du rôle | `--tools` (ensemble) + `--disallowedTools` | forte |
| Ce qui est autorisé d'office | `--allowedTools` avec `--permission-mode dontAsk` pour un agent sans interlocuteur | forte |
| Ce qui est interdit | `permissions.deny` dans `--settings` (compris `Read(...)` des secrets) | forte, même en bypass |
| Garde-fous d'actions | hooks `PreToolUse` **passés par `--settings`** à chaque tour, sur tous les outils concernés | forte ; plus de dépendance au fichier posé une fois |
| Consignes du rôle | `--append-system-prompt-file` (avec `--system-prompt-snapshot off`) + `CLAUDE.md` du projet | moyenne (contexte) |
| Commandes et sous-agents | un **plugin** `atelier-kit` (`--plugin-dir`), idempotent et versionné ; copie dans `~/.claude` pour VS Code et le terminal | forte pour la présence |
| Environnement | `env` minimal par rôle (plus la clé propriétaire ni les secrets du pool) | forte |
| Plafonds | `--max-turns`, `--max-budget-usd`, durée | forte |
| **Preuve** | l'événement `system/init` comparé au rôle avant d'accepter le tour ; `permission_denials` lus à la fin | détecte tout écart |

Plancher commun, posé **dans l'image** (donc non modifiable par les agents) : un
`managed-settings.json` qui refuse la lecture et l'écriture des secrets et de la clé propriétaire
pour tous les rôles et toutes les surfaces. Pas de `disableBypassPermissionsMode` : le mode
`bypassPermissions` est un choix légitime de la personne dans l'Atelier.

### Ce que ça change pour la personne et pour l'agent

- **Personne** : elle choisit un rôle en une phrase ; l'écran dit ce que l'agent peut et ne peut
  pas faire ; si l'agent n'a pas reçu ce qu'il devait (un serveur en échec), elle est prévenue
  tout de suite, pas le lendemain.
- **Agent** : il trouve ses outils, ses commandes et ses consignes sans rien configurer ; ce qui
  lui est refusé l'est par l'outil, avec la raison et le geste à faire, jamais « verrouillé »
  sans explication.

## 6. Feuille de route

Ordre par valeur et par risque. Chaque lot : analyse, tests qui échouent d'abord, correctif,
essai sur le pod, PR courte.

**Lot 1 — Voir ce que reçoit l'agent** (le plus rentable, peu risqué)
- Comparer l'événement `system/init` au rôle à chaque tour ; écart = journal, bandeau, alerte.
- Lire `permission_denials` : un lancement qui s'est heurté à des refus sans livrer est « bloqué »,
  pas « fini », et le lanceur reçoit les refus.
- Diagnostiquer et corriger `wikichat` en échec dans l'application (2 alertes graves).
- Poser d'office l'`ETAT.md` et la structure type des projets qui n'en ont pas.

**Lot 2 — Un rôle, une définition**
- `roles.py` et le compilateur ; une seule résolution du mode de permission (supprimer les 3 autres) ;
  les listes de `coherence.py` lues à la source ; tests « instantané » par rôle.
- Agents lancés : `dontAsk` + liste autorisée du rôle (outils du projet, écriture dans la copie,
  commandes de vérification de `projet.json`) ; entrées de la mission copiées dans la copie.
- Plafond de jetons appliqué (`--max-budget-usd`, `--max-turns`).

**Lot 3 — Sûr par la mécanique**
- `managed-settings.json` dans l'image ; garde d'actions passée par `--settings` à chaque tour et
  étendue à `Read`, `Write`, `Edit`, `Bash` ; `Read(.secrets/**)` refusé à l'Assistant.
- Environnement minimal par rôle ; `POST /v1/decisions/{id}` soumis au périmètre du lanceur.

**Lot 4 — D1 : jeton limité par conversation**
- Chaque conversation reçoit un jeton qui n'ouvre que ses propres appels. La clé propriétaire
  quitte l'environnement des agents. Le plus délicat : à concevoir seul, avec essai sur VS Code
  et terminal.

**Lot 5 — Le kit et les rôles en langage courant**
- Plugin `atelier-kit` : `/reprendre`, `/verifier`, `/fin-de-lot`, `/proposer`, journal d'outils,
  sous-agents en lecture seule. Les quatre rôles dans l'interface, puis la page projet.

**Lot 6 — Exploitation**
- `/v1/diagnostic`, arrêt propre au déploiement, sauvegardes, CI plus rapide, docs à jour
  (`fonctionnalites.md`, `SECURITY.md`).

## 7. À valider sur le pod avant de bâtir (essais de capacité)

Peu coûteux, avec le vrai `claude` : (1) le `managed-settings.json` s'applique-t-il à `claude -p` ;
(2) un hook passé par `--settings` s'exécute-t-il, avec ou sans `allowManagedHooksOnly` ;
(3) un sous-agent contourne-t-il un `deny` du parent ; (4) `--strict-mcp-config` contraint-il les
sous-agents ; (5) la version de `claude` du pod accepte-t-elle `--tools`, `--max-budget-usd`,
`--system-prompt-snapshot`. Chaque réponse change un choix du plan : on les mesure d'abord.

## 8. Décisions à prendre

1. **Plancher dans l'image** (`managed-settings.json`) : oui ou non.
2. **Agents lancés en `dontAsk`** avec liste autorisée par rôle, au lieu du refus automatique
   actuel.
3. **Ordre** : lots 1 à 3 avant D1, ou D1 plus tôt.
4. **Entrées d'une mission** : l'Atelier copie dans la copie de travail les fichiers que la
   mission cite hors du projet (recommandé), ou le lanceur doit les placer lui-même.

## 9. Sources

Documentation officielle Claude Code : `managed-settings`, `settings`, `permissions`,
`permission-modes`, `hooks`, `sub-agents`, `skills`, `memory`, `headless`, `cli-reference`,
`env-vars`, `sandboxing`, `plugins` (code.claude.com/docs/en/). Code : voir les chemins du
tableau de la section 3. Pod : `atelier_carte`, `atelier_journal`, `atelier_lancements` du
11/10/2026.
