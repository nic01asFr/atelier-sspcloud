# La cible : comment l'Atelier doit fonctionner

> **État au 11/11/2026. Document de référence de la cible, rien de ce qui est décrit comme « cible » n'est
> implémenté.** Il fixe le récit validé par Nicolas (l'Atelier habille Claude Code ; trois cadres emboîtés ;
> deux familles d'agents ; identité signée) et le détaille pour le miroir app / VS Code / terminal, les
> capacités des agents, la gateway et les liens avec l'extérieur. Il s'accompagne de
> [`plan-de-finition.md`](plan-de-finition.md) (les travaux, par lots) et de
> [`auto-amelioration.md`](auto-amelioration.md) (la boucle, qui vient après). Un diagramme illustré en est
> tiré (artefact « Fonctionnement de l'Atelier »).
>
> **Niveaux de preuve.** *Lu* : constaté dans le code ou la doc. *Rapporté* : dit par un lecteur, non
> revérifié par moi. *Déduit* : interprétation. *Cible* : proposition. Les chiffres et `fichier:ligne`
> viennent des lectures du 11/11 ; ils sont à rouvrir avant correction.

## 1. Le principe

L'Atelier est une **couche qui habille Claude Code**. Chaque règle est portée par un mécanisme natif
(fichier de réglages, hook, serveur MCP, sous-agent). L'Atelier sert à **les poser, à les rendre
inaccessibles à l'agent, à les prouver et à les montrer** à la personne. Il n'écrit du code que pour ce que
le natif ne fait pas : le pont vers la personne (« À valider »), le registre des projets, le journal et la
preuve, le lien avec wikichat et Onyxia.

### 1.0 La nature d'un agent *(précisé le 11/11, d'après Nicolas)*

**Tout agent de la plateforme, quel qu'il soit, est une session Claude Code, localisée dans un dossier sur le
disque.** C'est sa nature ; tout le reste (configurations, capacités, liens avec wikichat et Onyxia) en découle.

- Un agent = **(dossier de travail, identifiant de session, options de lancement)**. Le dossier porte ses fichiers
  natifs : `CLAUDE.md`, `.claude/` (réglages, sous-agents, commandes, skills), `.mcp.json`, et pour un projet
  `.atelier/projet.json`.
- La **famille se lit à l'endroit où vit le dossier** : sous `projects/<slug>`, un agent code ; sous le dossier de
  l'Assistant, l'Assistant (le code le fait déjà pour une conversation inconnue : `profils.py`, lu) ; dans le dossier
  propre d'un agent déclaré (`dossier_de`, `commandes/agents.py`, lu), un agent de l'Atelier ; dans une copie de
  travail sur branche, un agent lancé ou un réparateur.
- Les **couches de profil sont des fichiers autour du dossier** : réglages managés (hors d'atteinte) › utilisateur
  (`~/.claude`) › projet (`.claude/settings.json`) › local › options du lancement. La surcharge de session est une
  option du lancement, pas un fichier.
- **wikichat et Onyxia sont des attributs de configuration, pas la nature de l'agent** : entrées de `.mcp.json`,
  bloc `deploiement` de `projet.json`, capacités accordées. Ils changent sans que l'agent change de nature.

Conséquences : (a) **définir un agent, c'est définir un dossier** : reproductible, diffable, testable ; (b) le miroir
app / VS Code / terminal est **évident par principe** (mêmes dossier et session, donc même agent, § 2) ; (c) l'identité
signée lie *famille, dossier, session, profil résolu, durée* ; (d) l'auto-évolution agit sur les **fichiers du
dossier** et du socle ; (e) un agent de l'Atelier ne diffère d'un agent code que par le dossier où il vit, ses
options de lancement et ses capacités accordées, **pas par une autre technologie**.
*Question ouverte* : où vit le dossier d'un agent de l'Atelier qui agit sur plusieurs projets ? Hypothèse : son
dossier propre, avec une copie de travail sur branche par projet touché, et les commandes de l'Atelier pour le reste.

### 1.1 Vue d'ensemble : tout part de Claude Code

```
 PERSONNE   interface de l'Atelier : projets, panneau, « À valider », journal, Ma mémoire, page Agents
    ▲          (seule à décider ce qui engage)
    │
 ┌──┴─ POD ONYXIA · le code de l'Atelier tourne sur Onyxia · volume ~/work ──────────────────────────┐
 │                                                                                                  │
 │  ┌─ CLAUDE CODE · chaque agent est une session, dans son dossier ──┐      ┌─ ATELIER ──────────┐   │
 │  │  agent code        projects/<projet>/   (+ .mcp.json .claude/ .wikichat/)  ◄─ lance, signe │   │
 │  │  Assistant         wikichat-memory/assistant/…   ──── /mcp ───►  identité · profils · gateway│  │
 │  │  agent de l'Atelier  dossier propre + capacités accordées      │      │ journal · À valider │   │
 │  │  règles natives : managés › projet › lancement · hooks · skills│      │ gardiens            │   │
 │  └──────────────┬─────────────────────────────────────────────────┘      └──────┬──────────────┘   │
 │        MCP · hooks · .wikichat · identité                          projets déclarés │ mémoire      │
 │                 ▼                                                                   ▼              │
 │         wikichat · service local : identité de chaque session, mémoire, messages, carte des projets │
 └──────────────────────────────────────────────────────────────────────┬───────────────────────────┘
                                                                        │ mandataire borné par projet
                                                                        ▼
                                                      Onyxia / SSPCloud : API, pods dédiés, GPU, services
```

Chaque cadre **limite le suivant par la mécanique** : l'agent ne peut modifier ni la couche managée, ni
l'identité signée, ni le filtre de la gateway. C'est la condition de toute auto-évolution sûre.

### 1.2 Deux familles d'agents, une seule résolution en couches

```
 famille (code | agent de l'Atelier | assistant | gardien)     plafond fixé par l'Atelier (managé)
   └► profil de base
        └► agents code : défauts du projet           agents de l'Atelier : profil propre à l'agent
             └► agents code : surcharge de session        agents de l'Atelier : capacités accordées
```

- **Agents code** : un profil attribué au **projet** (ses défauts, pour tous ses agents code), modifiable
  **par session** sans toucher aux autres sessions ni aux défauts. Ils agissent dans leur projet ; pour agir
  ailleurs, ils écrivent aux agents de l'autre projet par wikichat.
- **Agents de l'Atelier** (page Agents) : profil et **capacités** configurables par agent ; ils peuvent agir
  sur un ou plusieurs projets, mais par **octroi explicite, daté et révocable**, jamais par accès général.
  Les gardiens en font partie (contrôles en code, gestes fermés).
- Règle commune : **une couche ajuste à l'intérieur de la précédente, jamais au-delà**, et un `deny` l'emporte.
- **Identité = capacité signée par conversation** : famille, profil résolu, projet, surcharges, durée. L'agent
  ne peut ni la forger ni l'élargir, et il ne porte plus la clé propriétaire.

*Aujourd'hui (lu)* : deux profils par type d'acteur (`code`, `assistant`), pas de profil de projet ; seul le mode de
permission a le double niveau projet / conversation ; les agents de la page Agents n'ont qu'une liste d'outils et
un budget ; l'identité vient d'un en-tête `X-Atelier-Conversation` que l'agent peut omettre.

### 1.3 Ce qui se passe quand la personne demande

1. Elle écrit dans un projet ; l'Atelier ouvre une session Claude Code et lui donne l'**identité signée**.
2. Le **profil se résout par couches** (plafond managé › défauts du projet › options du lancement).
3. L'agent reçoit **exactement** ce qu'il faut : configuration MCP stricte, outils filtrés par la gateway à la
   liste et à l'appel, contexte de départ par hook.
4. Il travaille : les hooks refusent avec le motif et la voie de sortie, masquent les secrets ; il ne lit pas les
   secrets (le plancher managé s'y oppose) ; ce qu'il fabrique est servi en **brouillon** sur une origine séparée.
5. Une action **engageante** produit un aperçu puis une carte « À valider » ; seule la personne confirme. Sans
   réponse, l'agent **s'endort et reprend** : il ne reçoit jamais un refus à la place de la personne.
6. Il conclut : un hook de fin vérifie ; « fini » veut dire **livré**, sinon « bloqué » ou « échoué » avec motif.
7. **Journal unique** (acteur, preuve, inverse). La mémoire apprend de la personne, pas des messages d'application.

### 1.4 Tirer parti du natif au maximum, puis un cadre local, puis des services configurables *(précisé le 11/11, d'après Nicolas)*

Trois étages, dans cet ordre, et **chacun s'appuie sur le précédent** :

1. **Le fonctionnement de Claude Code, exploité au maximum.** On ne code dans l'Atelier que ce que le natif ne fait pas.
2. **Un cadre local wikichat, lui-même bâti sur Claude Code** : ses agents sont des sessions Claude Code (lancements
   `claude -p`, reprise par identifiant de session, MCP, hooks) ; il ajoute la coordination, la mémoire et la carte des
   projets, pas une autre mécanique d'agent. *(Lu : les déclencheurs, routines et `spawn_session` de wikichat relancent
   des sessions Claude Code ; le code de wikichat lui-même est hors de ce dépôt, donc non relu.)*
3. **Des services de base, avec des configurations par cas** : navigateur, créations, Onyxia, mémoire, gateway… Chacun a
   une configuration par défaut selon le cas d'usage, et des options pour la resserrer ou l'élargir dans le plafond.

**Inventaire des mécanismes natifs à exploiter** (à confirmer sur la version du CLI du pod avant de s'y appuyer) :

| Mécanisme natif | Ce qu'on en tire | État dans l'Atelier |
|---|---|---|
| Réglages **managés** | plafond non contournable, `deny` qui l'emporte | **absent** |
| `permissions` allow / deny / ask, modes (`dontAsk`, `acceptEdits`…) | profil d'un rôle | calculé à plusieurs endroits ; `dontAsk` remplacé par `default` (lu) |
| `--permission-prompt-tool` | le pont vers « À valider » | **utilisé** (lu) |
| `--mcp-config` + `--strict-mcp-config` | exactement les outils du profil | **utilisé** pour l'app ; `.mcp.json` pour VS Code et terminal (rapporté) |
| `--settings`, `--resume`, `--session-id` | surcharge de session, reprise, miroir | **utilisés** (lu) |
| `--max-turns` | plafond de tours | utilisé pour les agents déclarés (lu) |
| `--max-budget-usd` | plafond de coût | **absent** |
| Hooks `PreToolUse` | garde (`garde_bash`, `garde_navigation`) | **utilisés**, posés dans le fichier utilisateur (modifiable par l'agent) |
| Hooks `PostToolUse`, `Stop`, `SubagentStop` | masquage, fin qui dit vrai | **absents** |
| Hook `SessionStart` | contexte de départ réel de l'agent | traces dans `project_context.py` et `assistant.py` ; usage à confirmer |
| `system/init`, `terminal_reason`, `permission_denials` | preuve de ce que l'agent a reçu, état de fin | `system/init` lu par la cohérence (1 fois par jour) ; les deux autres **non lus** pour l'état |
| `CLAUDE.md` et imports `@` | consigne et contexte par couches | **utilisés** (socle, projet, contexte généré) |
| Skills, commandes, sous-agents (`.claude/…`) | savoir-faire à la demande, agents à outils réduits | **absents** (le kit est de la spec) |
| Plugins (`--plugin-dir`) | un rôle = un paquet de skills, sous-agents, hooks, commandes | **absents** |

**Services de base : configuration par cas.** Un *cas* est un type d'usage ; un *préréglage* donne la configuration par
défaut de chaque service pour ce cas. **Resserrer est libre ; élargir (jusqu'au plafond de la famille) est
engageant.** Tableau cible, d'après ce qui existe et ce qui est posé (proposition) :

| Service | A · agent code, projet simple | B · agent code, projet Onyxia | C · Assistant | D · agent planifié (veille) | E · gardien / réparateur | F · agent à communication externe |
|---|---|---|---|---|---|---|
| Dossier | projet | projet | `wikichat-memory/assistant/sessions/<id>/` | dossier propre | copie de travail sur branche | dossier propre |
| wikichat | limité à son projet ; messages vers les autres projets | idem | vue globale, Pilote | ses fils seulement | une note | ses fils seulement |
| Gateway / outils | profil `code` (10 outils) | profil `code` + mandataire Onyxia du projet | `assistant` + méta-outils | liste fermée déclarée | lecture + gestes fermés | liste fermée + connecteur de communication |
| Navigateur | oui, un Chrome par conversation | oui | lecture | par octroi | non | par octroi |
| Créations | brouillon, vérifier, démarrer | idem | délègue (ne crée pas) | non | vérification en lecture | non |
| Onyxia | non | pod / service / GPU si déclaré ; déploiement engageant | par délégation | par octroi | non | par octroi |
| Mémoire | fiches du projet | idem | « Ma mémoire » | non | non | non |
| Garde (hooks, deny) | socle + secrets refusés | idem | socle + secrets refusés | liste blanche, `dontAsk` | périmètre de la branche | liste blanche + contamination |
| Budget | plafond du projet | idem | par tour | **obligatoire** (tours, par jour, pause), né désactivé | plafonné, branche `gardien/…` | obligatoire + plafond d'envois |
| Envoi externe | non | non | non | non | non | capacité par (connecteur, verbe, cible), « À valider » |

Un préréglage est **un fichier** (profil de projet, définition d'agent), donc versionné, comparable et testable ;
l'Atelier le compile vers les mécanismes ci-dessus. *Aujourd'hui (lu)* : seuls les cas A et C existent comme profils
(`code`, `assistant`) ; B n'est qu'un bloc `deploiement` ; D est une liste d'outils et un budget ; E et F n'ont pas de
préréglage.

### 1.5 wikichat : identité par session, espace par dossier, lien local *(précisé le 11/11, d'après Nicolas)*

wikichat est un **service local** bâti sur le fonctionnement de Claude Code. Il relie l'ensemble comme support cohérent
de l'Atelier : mémoire de la personne et plateforme globale.

- **Chaque session Claude Code, comme agent, a une identité wikichat.** *Lu* : le harnais pose `WIKICHAT_AGENT`
  (`harness.py:706`), et l'Atelier passe aussi `WIKICHAT_PROJET` et `WIKICHAT_PROFIL` (rapporté). Cette identité est la clé
  par laquelle wikichat sait qui parle, de quel projet, avec quel profil.
- **wikichat est disponible par défaut pour tous les agents d'un espace, d'un dossier, d'un projet** (par la
  configuration MCP du dossier). **Chaque session peut être particulière dans le cadre que permet la configuration de son
  dossier** : même mécanique de couches que le profil (§ 1.2), pas une exception.
- **Les assistants vivent dans le dossier wikichat.** *Lu* : le dossier de l'Assistant est `~/work/wikichat-memory`
  (`assistant.py:8`) ; chaque conversation a son dossier de travail `assistant/sessions/<id>/` ; Claude Code lit les
  `CLAUDE.md` du dossier **et de ses parents**, donc le `CLAUDE.md` de la racine vaut pour toutes les conversations, dans
  l'Atelier, VS Code et le terminal. L'accès à la mémoire wikichat est ainsi **par défaut, par le seul fonctionnement de
  Claude Code**. Le contexte passe par des imports `@` (relus après compaction, sans la coupe à 10 000 caractères du
  contexte d'un hook) ; le hook de wikichat ne porte que le delta.
- **Les projets code sont des dossiers au niveau wikichat.** *Lu* : « un projet de l'Atelier et un projet wikichat sont la
  même chose : un dossier de travail, ses agents, sa mémoire » (`wikichat_projects.py`) ; l'Atelier déclare chaque projet à
  wikichat (`declare_project`), silencieusement si wikichat est absent. Le `.wikichat/` du dossier est l'état du
  coordinateur, dérivé, jamais une source.
- **wikichat fait le lien** par les `.wikichat` et par les capacités et supports qu'il propose à ses clients locaux : un
  agent d'un projet joint les agents d'un autre, retrouve la mémoire de la personne, voit la carte de la plateforme
  selon son profil.
- **Onyxia.** Le service permet d'accéder au code de l'Atelier, qui tourne lui aussi sur Onyxia. Les outils MCP Onyxia,
  définis par défaut, sont donc **configurés pour cadrer ce fonctionnement dans Onyxia**, et les capacités Onyxia suivent
  le même mécanisme que tout le reste : le préréglage du cas (§ 1.4), le mandataire borné du projet (§ 4), l'octroi pour
  un agent de l'Atelier.
- **Des indications contextuelles, finement appropriées au cas.** L'Atelier fournit à chaque agent un contexte
  d'ensemble par couches : `.atelier/contexte.md` généré à chaque tour pour un projet (lu), la carte et « À valider » pour
  l'Assistant (lu, `assistant.py`). Cible : la même couche pour tous, choisie par le préréglage du cas, et **auto-
  apprenante** : ces fichiers de contexte et de consigne sont ce que la boucle d'amélioration ajuste, éprouve et promeut
  ([`auto-amelioration.md`](auto-amelioration.md)), nourrie par « Ma mémoire ». L'apprentissage n'est donc pas un
  mécanisme à part : ce sont des fichiers versionnés, comme le reste.

**Ce que cela impose.**
- L'identité wikichat étant posée par une variable d'environnement, **un agent pourrait la changer**. Cible : elle est
  **dérivée de l'identité signée** (§ 1.2) par le pont qui relie l'agent à wikichat, et non déclarée par l'agent
  (*déduit* ; le pont stdio qui identifie les agents est décrit dans `wikichat_mcp.py`, non relu en détail).
- *À vérifier avant de s'y appuyer* : la routine de nuit de wikichat et son filtre de profil (hors de ce dépôt), la
  persistance du store après redémarrage (D-53, trois documents se contredisent), et que `WIKICHAT_PROJET` /
  `WIKICHAT_PROFIL` sont bien posés sur toutes les surfaces (app, VS Code, terminal).

## 2. Le miroir app / VS Code / terminal

*Principe cible : trois fenêtres sur **une seule session Claude Code**.* Le transcript `.jsonl` du CLI est la seule
vérité ; la fiche de l'Atelier en est un **index**, le journal de l'Atelier un **cache jetable**.

### 2.1 Modèle actuel (rapporté)

Il n'y a ni « session Atelier » ni serveur de session : trois lanceurs du même binaire `claude` se rejoignent par
des fichiers sous `~/.claude` et `~/work`.

```
 APP (harness.py)                  VS CODE (extension Claude Code)      TERMINAL
 claude -p stream-json             claude via claudeProcessWrapper      alias claude
  --resume <cli_id>                 = atelier-claude-vscode              = atelier-claude-vscode
  --mcp-config <effectif> strict    lit .mcp.json du dossier             lit .mcp.json
  --settings {env, règles}                                  
          \                              |                           /
           '─► ~/.claude/projects/<cwd>/<cli_id>.jsonl   ◄─ vérité de la conversation
               ~/.claude/sessions/<pid>.json   (qui est vivant, quelle surface)
 Fiche  sessions/<id>.json (index)   ·   Journal Atelier (copie filtrée, un seul sens)
 Mode   magasin partagé : conversation › projet › service
 Secrets  ~/work/.secrets/claude-env.sh : clé propriétaire + secrets des connecteurs
```

### 2.2 Invariants que le miroir doit garantir

| Invariant | État (rapporté) | Cible |
|---|---|---|
| Même historique partout | un seul `.jsonl` côté CLI ; le journal Atelier est une copie à sens unique | le `.jsonl` est la seule écriture ; plus de copie par date |
| Même mode | tenu à l'ouverture (magasin partagé + enveloppeur) ; **pas** pour un onglet déjà ouvert | idem, plus relecture à chaque tour |
| Mêmes outils | vérifié une fois par jour, un projet par profil ; **deux chemins** (fichier effectif strict pour l'app, `.mcp.json` pour le reste) | **un seul fichier effectif** lu par les trois surfaces, égalité testée à chaque ouverture |
| Même identité | non : en-tête déclaratif + clé unique lisible par tous | capacité signée, vérifiée par la porte `/mcp` |
| **Un seul écrivain à la fois** | **non tenu entre surfaces** | verrou de conversation |

### 2.3 Fragilités et réponses

| # | Fragilité (rapporté) | Réponse cible |
|---|---|---|
| 1 | Le verrou des tours est un `threading.Lock` du seul processus de l'Atelier ; `_send` et le passage de main ne regardent ni `sessions/<pid>.json` ni la présence d'un `claude` VS Code ou terminal (`sessions.py:1498-1521, 1594-1608`) | **verrou de conversation** : fichier `verrous/<cli_id>.lock` (pid, surface, horodatage), pris à l'envoi, au passage de main et par l'enveloppeur ; péremption par `/proc/<pid>` |
| 2 | Le processus de l'app est gardé 10 min ; son « empreinte » ignore taille et date du transcript (`harness.py:1371-1422`) : écrire dans VS Code entre deux tours fait diverger l'historique, les deux écrivent dans le même fichier | ajouter taille / mtime du transcript à l'empreinte, ou éteindre le processus au passage de main |
| 3 | Synchronisation du home vers le PVC par date, fichier entier (`claude_home.py:375-389`) : une suppression ne se propage pas, deux ajouts concurrents perdent le plus ancien | un lien ou montage du PVC pour `projects/` ; la synchro ne garde que les autres dossiers |
| 4 | La marque `sdk-cli` est corrigée seulement au passage de main, par réécriture sur place dans les 64 Ko de tête (`vscode_handoff.py:520-560`) ; avant cela, une conversation de l'app est invisible dans l'extension | poser `cli` à la création de la session par l'app |
| 5 | `dossier_transcripts_claude` n'applique pas `resolve()` (`vscode_handoff.py:501-507`) | aligner sur `folder_abs` |
| 6 | `absorber_le_cli` lit, modifie, `save(rec)` sans verrou (`sessions.py:1966`) | verrou de fichier ou numéro de version ; écriture seulement sous le verrou de conversation |
| 7 | La consigne d'ouverture est supprimée avant l'ouverture ; si elle échoue, elle est perdue ; une conversation laissée ouverte est fermée (`extension.js:39-78`) | supprimer après succès ; ne fermer que ce qu'on a restitué |
| 8 | Identité faussable : en-tête auto-déclaré, repli « poste » (`mcp_endpoint.py:151`, `profils.py:374, 467`) | identité signée ; `atelier-entetes-mcp` devient le `headersHelper` qui demande un jeton à chaque connexion |
| 9 | `session_mcp.py:23-25` dit « plus de désactivation par conversation » alors que `mcp_overlay` reste passé à `materialize_session_mcp` (`sessions.py:1660`) | supprimer la survivance ou la rendre visible à toutes les surfaces |

Une **identité signée résout 8 et la moitié de 9 ; elle ne résout pas 1, 2, 3, 4 et 6**, qui sont des
problèmes de fichiers et de concurrence. D'où un lot propre (plan de finition, lot 1 bis).
*Note.* Le jeton étant court, il doit se **renouveler** : il se délivre par `headersHelper` à chaque connexion, pas
par une variable figée dans `claude-env.sh`.

## 3. Les capacités des agents, rangées par capacité

Une **capacité** accorde une action, à une famille, avec une portée, une classe de commande
(lecture / réversible / engageante / réservée) et une preuve au journal. Tableau cible, d'après la lecture
(« code » = agent code ; « Atelier » = agent de la page Agents) :

| Capacité | Code | Atelier | Portée | Classe cible | Preuve |
|---|---|---|---|---|---|
| Naviguer en lecture (`take_snapshot`, `list_pages`) | oui | par octroi | la conversation | lecture | **à journaliser** (aucune aujourd'hui) |
| Naviguer en action (clic, saisie, navigation) | oui | par octroi | la conversation | réversible | à journaliser |
| Prendre la main sur l'écran | non | non | la conversation | réservée à la personne | fiche `main/<id>.json` |
| Montrer une création (`atelier_montrer`) | oui | non | un projet | **réversible** (déclarée lecture à tort : elle épingle une vue) | fichier de panneau |
| Ouvrir une création dans son navigateur | oui | non | un projet | réversible | à journaliser |
| Artefact page : créer, vérifier, lister, journal | oui | non | un projet | créer = réversible ; le reste = lecture | `.auteur` |
| Artefact serveur : démarrer, arrêter | oui | non | un projet | réversible | journal du processus |
| Proposer une promotion (`atelier_artefact_proposer`) | oui | oui | un artefact | engageante | file de propositions |
| **Promouvoir, revenir en arrière, exposer, accorder** | non | non | un artefact | **réservée** | étiquette `prod/<nom>/<n>` |
| Déclarer un déploiement Onyxia | demande | non | un projet | engageante | commit + liaison |
| Exécuter dans le pod du projet (`exec`, fichiers) | oui, borné | par octroi | un pod | **à classer** (aujourd'hui sans classe) | note du mandataire |
| GPU : `gpu_switch` sans préemption, `gpu_release` | si `gpu: true` | par octroi | un pod GPU | réversible ; **préemption refusée** | à définir |
| `service_deploy`, `service_provision`, `project_start` | avec `yaml_path` imposé | par octroi | un service | **engageante** (engage le quota ; aujourd'hui sans classe) | à définir |
| `expose_public` | non | non | — | réservée | « À valider » |
| Gérer les agents de l'Atelier (créer, modifier, désactiver) | non | Assistant | un agent | réversible | commande journalisée |
| **Activer** un agent de l'Atelier | non | non | un agent | **réservée** | « Oui » de la personne |

### 3.1 Incohérences à lever (rapporté)

- **Gabarits de projet en trois versions** : le code (`application`, `donnees`, `service-mcp`, `document`, `vide`),
  `ecosysteme.md` (page, application, service-mcp, savoir-faire), `cadrage-des-agents.md` (+ `ml-gpu`). Dans le code,
  le gabarit ne change que la ligne « Prochaine étape » d'`ETAT.md` ; le dossier `gabarits/` n'existe pas ; le
  `.gitignore` généré n'exclut ni `artifacts/*/donnees/`, ni `.auteur`, ni `.venv/`.
- **Deux façons d'héberger** : artefact serveur local (`artefact.json`) et `deploiement` Onyxia (pod ou service),
  chacun avec son champ `commande`. Le bloc `deploiement` refuse `pod` et `service` ensemble.
- **Trois façons de « voir »** : `atelier_montrer`, `atelier_navigateur_ouvrir`, l'écran en direct ; le descripteur
  unique de `panneau.md` (genres page, application, navigateur, bureau, MCP App) n'existe pas.
- **Navigateur** : un Chrome stdio par conversation, mais l'instance de la passerelle est unique et partagée.
- **Templates Onyxia** : le format du `<nom>.service.yml` n'est ni écrit ni documenté dans ce dépôt (`service_scaffold`
  n'apparaît que dans un tableau de `onyxia-projet.md`).

### 3.2 Structure cible

**Un gabarit de projet** : familles *page · application · service-mcp · savoir-faire · ml-gpu* ; les gabarits du code
deviennent des variantes. Fichiers communs : `CLAUDE.md` (≤ 100 lignes), `ETAT.md`, `README.md`,
`docs/{cahier-des-charges,decisions}`, `.atelier/projet.json`, `.gitignore` complet, `.claude/` (commandes et
sous-agents du kit). Propres au gabarit : `artifacts/<nom>/artefact.json` (v2) et `tests/` ; un squelette
`<nom>.service.yml` pour `ml-gpu`. **Un seul propriétaire de la commande de démarrage** : `artefact.json` pour le
local, `deploiement` pour Onyxia.

**Bloc `deploiement`** : `{cible: local|pod|service, pod|service, gpu: bool, commande, port}`, posé à la création si
le gabarit annonce du GPU. Un geste `deployer_lancer` enchaîne `service_scaffold` → `service_provision` →
`service_deploy` après **un seul** accord de la personne.

**Un artefact** : *création* → *brouillon* (tourne depuis l'arbre de travail, adresse `…/<nom>/~brouillon/`) →
*vérification* (tests, santé, capture) → *proposition* (engageante, par l'agent) → *promotion* (par la personne :
copie git figée en lecture seule `prod/<nom>/<n>` ; `donnees/` hors git, sauvegarde avant bascule) → *retour arrière*
(la personne rebascule). Preuve au journal : étiquette, résultats, capture, auteur.

**Une seule vue** : un descripteur de vue (page, application, navigateur, bureau, MCP App) remplace les trois chemins.

## 4. La gateway : structure et configuration

### 4.1 Modèle actuel (rapporté)

```
 Clients (agent code | Assistant | claude.ai | VS Code)
   │ /mcp (clé propriétaire ou OAuth + en-têtes X-Atelier-Conversation / -Profil / -Projet)
   ▼
 McpGateway.tools_list / tools_call
   ├─ profil « code » : seuls les atelier_* locaux passent
   ├─ atelier_* → catalogue de commandes à classes (aperçu + jeton 10 min, journal filtré des secrets)
   ├─ méta-outils gateway_* (find_tools, call_tool, compositions)
   └─ outil amont : filtre du profil exposé, puis pool.call ; SEUL garde en dur : {expose_public, unexpose_public}
 Pool amont : http, sse, stdio
 Sources de connecteurs : catalogue d'organisation (YAML, vide) · registre perso (SQLite) · mcp_registry.py (JSON) ·
                          choix par projet (.atelier/connecteurs-choisis.json)  → trois sources, pas un registre
```

### 4.2 Structure cible

1. **Un registre unique de connecteurs**, déclaratif, versionné : identifiant stable, transport, secrets par
   **référence** (jamais en `args`), famille, outils exposés. Le choix par projet n'est qu'une **sélection** dans ce
   registre, calculée dans les couches de profil.
2. **Une couche de surcharge par connecteur** (*overlay*) plutôt que des « variantes » : par outil, une classe
   (lecture / réversible / engageante / réservée), des **arguments imposés et cachés**, un schéma réduit, un titre et
   une description en français, des annotations. Aujourd'hui une variante ne fait que figer des valeurs (composition à
   une étape), et la classe ne couvre que les commandes `atelier_*`.
3. **Classer tout outil amont** : par table déclarative d'abord, annotations MCP en repli, regex de nom en dernier ;
   **défaut pour un connecteur inconnu : engageante**.
4. **Un moule de mandataire borné générique** (aujourd'hui un seul, Onyxia, ~1 050 lignes) : arguments imposés ou
   refusés, jamais réécrits en silence, outils hors borne absents de `tools/list`.
5. **Journal et plafonds pour les appels amont** (aujourd'hui seules les commandes `atelier_*` sont journalisées
   avec filtre de secrets).
6. **Compositions** : conserver `tool`, `elicit`, `approval`, `wait_until`, et combler ce qui est stocké sans être
   appliqué (`timeout_seconds`, `wait_until`, `ttl_seconds`) ; `allowed_roles` vérifié ; **`approval` et `elicit` ne
   doivent pas pouvoir être validés par le modèle** (sinon ne pas compter dessus pour un envoi). Boucle, condition,
   retry : seulement après, avec `max_iterations` obligatoire.
7. **Le secret d'un connecteur n'est pas dans l'environnement de l'agent** : il passe par un mandataire (connexion
   indirecte), pas par une connexion directe. Sinon le filtre ne protège rien.

## 5. Capacités externes des agents de l'Atelier, et services de communication

*Aujourd'hui (lu)* : aucune intégration de communication externe (ni Tchap/Matrix, ni mail, ni Mattermost, ni
webhook) ; n8n est proposé, jamais posé ; le seul canal sortant est le Web Push vers l'appareil de la personne
(`push.py`), qui n'est pas ouvert aux agents ; `Bash` et `WebFetch` donnent aux agents une sortie réseau non filtrée.

### 5.1 Un connecteur de communication, déclaré dans le registre (cible)

```
connecteur: tchap          # préfixe d'outils tchap__
transport: http | stdio    # serveur MCP Matrix, ou pont maison
secrets: {token: ref://ATELIER_MCP_TCHAP_TOKEN}
famille: communication
outils:
  send_message: {classe: engageante, arguments_imposes: {room_id: …}, schema_reduit, description_fr}
  read_room:    {classe: lecture, sortie: non_fiable}
  list_rooms:   {classe: lecture}
plafonds: {envois_par_jour: 20, par_salon: 5/h, taille_max}
```

### 5.2 Règles

- **Capacité par (connecteur, verbe, cible)**, jamais « tout Tchap » : par exemple `tchap.send@salon-X`,
  accordée par la personne à un profil, un projet ou un agent. Sans la capacité, l'outil **n'est pas listé** et est
  refusé à l'appel.
- **Tout envoi est engageant** (message, mail, invitation, réaction publique) : aperçu du texte et du destinataire
  exacts, jeton lié aux arguments, carte « À valider ». Un agent planifié sans humain présent met l'envoi **en
  attente** (on ne refuse jamais), sauf liste blanche de salons pré-approuvés par la personne.
- **Administration** (créer un salon, inviter, changer des droits) : **réservée** à la personne.
- **Sortant, dans l'ordre** : arguments imposés → filtre de secrets sur le corps → aperçu et « À valider » → envoi →
  journal (qui, quelle capacité, empreinte du texte, résultat) → plafonds par agent et par jour.
- **Entrant** : tout contenu lu est une **donnée non fiable**, enveloppée et jamais interprétée comme consigne.
  **Contamination** (cible, à construire) : un agent qui a lu du contenu externe ne peut pas, dans le même tour,
  déclencher une action engageante sans nouvelle confirmation humaine. Un message externe ne **lance** jamais un
  agent directement : il écrit dans « À valider » ou dans les événements, avec comptage par origine et profondeur
  bornée.
- **Précondition** : identité signée (lot 1) et mandataire générique (§ 4.2, 4) avant d'ouvrir un canal sortant.

*À vérifier avant de bâtir* : côté Tchap, le serveur Matrix, un compte bot, le chiffrement de bout en bout (un bot ne
lit pas les salons chiffrés sans gestion de clés) et l'hébergement du serveur MCP Matrix ne sont pas vérifiables
depuis ce dépôt.

## 5 bis. GitHub et les projets *(étudié le 11/11 ; tout est *rapporté* par un lecteur, `fichier:ligne` à rouvrir avant correction)*

### 5 bis.1 Ce qui existe

```
 Chart / secret Helm (git.token) ──► pod ──► ~/work/.secrets/github_token   (0600, UN seul PAT par pod)
                                                       │  lu à chaque usage par :
        ├─ l'Atelier : GIT_ASKPASS (git_repos.py:549-575), API github.com (github_compte._get)
        ├─ un credential helper GLOBAL github.com/https (git_repos.py:577-603) : tout `git push/clone`
        │   d'un agent code, du terminal, de VS Code
        ├─ les gardiens G1 : `gh api`, sinon l'API avec le même fichier (commun.py:374-398)
        └─ les connecteurs MCP qui ont reçu le secret (renouvelé à la reconnexion, api.py:947)
 Agents : la variable ATELIER_GITHUB_TOKEN est retirée de leur environnement (harness.py:655, commit d61c7b1) ;
          le fichier reste lisible par tout processus du pod.
```

| Geste | Qui le fait aujourd'hui |
|---|---|
| Cloner | la personne (Réglages › « Ouvrir comme projet »), l'Assistant (`atelier_projet_depuis_github`, réversible), un agent code (`git clone` via le helper) |
| Créer un projet | `git init -b main` + un premier commit, **sans remote** ; un projet cloné garde `origin` sans secret |
| Commiter | l'Atelier (`add -A`, `--no-verify`) et les agents |
| Pousser | un agent code **pousse où il veut** avec le PAT (aucun garde-fou trouvé hors copies sur branche) ; la personne publie (`atelier_projet_publier`, réservée, dépôt privé par défaut, refuse un secret dans l'historique) |
| Ouvrir une PR, fusionner côté GitHub | **personne** : aucune route, aucune commande, rien dans l'interface |
| Fusion locale | `atelier_reparation_fusionner` : `git merge --no-ff` dans la base locale, **jamais poussée**, réservée à la personne |
| Agents lancés sur branche | copie `git worktree` ; branches `agent/` et `gardien/` ; crochets `reference-transaction` et `pre-push`, `pushInsteadOf` ; base vérifiée en fin de tour ; proposition déposée dans « À valider » (le code se dit « une garde, pas une prison ») |
| CI | seul le gardien G1 lit les runs de `main` (un dépôt listé à la main) ; ni statut de CI, ni PR, ni branche distante dans l'interface |

### 5 bis.2 Les trous

1. **Un PAT unique et global par pod** ; un jeton classique est accepté avec un simple avertissement (`github_compte.py:178`) ; la portée n'est pas vérifiée.
2. **Tout agent avec Bash lit le fichier** (`cat ~/work/.secrets/github_token`) : retirer la variable ne retire que la copie périmée. D-54 et D-55 (sudo) restent ouverts.
3. **Push hors périmètre** : hors copie sur branche, rien n'empêche de pousser sur `main` ou sur un dépôt tiers où le jeton a le droit d'écrire, car le helper répond pour tout `github.com`.
4. **Divergence copie / dépôt** : pas de `fetch` ni de `pull`, `add -A` et `--no-verify`, et la fusion locale n'est jamais poussée : une perte du volume perd les fusions non publiées (déduit).
5. **Ni PR ni CI dans l'interface** ; l'état d'un dépôt se réduit à branche, commits en attente, remote.
6. **Le connecteur GitHub MCP** est un second canal hors des gardes git, hérité par 8 projets sur 16 (D-08).
7. **Les gardiens** utilisent `gh api` d'abord : une seconde identité non gérée (déduit).
8. **Les commits d'agent** ne se distinguent pas (identité de la personne ou `atelier@localhost` ; un trailer `Agent:` est évoqué en doc, non vérifié).
9. **Documenté, non codé** : crochets pre-commit / pre-push de secrets « de chaque projet », pousser sur `agent/*`, `pull` d'un dépôt ouvert, étiquettes `prod/<nom>/<n>`, bloc `github` de `projet.json`.

### 5 bis.3 La cible

- **Un projet = un dépôt = un `origin` GitHub privé**, créé ou lié à la création du projet, marqué dans
  `.atelier/projet.json` avec sa branche de base. La vérité de ce qui est fusionné est **sur GitHub**.
- **Une identité GitHub par famille**, jamais un PAT global lisible par tous :
  - *agents de l'Atelier* : **GitHub App** installée sur les dépôts choisis, jetons d'installation d'une heure obtenus
    par le serveur de l'Atelier, jamais par l'agent ; droits minimaux (Contents en écriture limité aux branches
    `agent/*` et `gardien/*` par règle de protection, Pull requests en écriture, Checks et Actions en lecture) ;
  - *agents code* : **pas de jeton propre** ; ils commitent, et c'est l'Atelier (ou un mandataire local limité à la
    branche de la conversation signée) qui pousse ; à défaut, un jeton fine-grained par dépôt ;
  - *la personne* : son propre jeton, pour les seuls gestes qu'elle fait seule.
- **Le secret n'est pas lisible par l'agent** (propriétaire distinct ou service local, plus de `sudo`, environnement en
  liste blanche) ; `git` passe par un proxy ou un helper qui vérifie la branche de l'identité signée.
- **Des branches protégées côté GitHub** : même si un agent contourne les crochets, GitHub refuse le push sur `main`.
- **Classes de commande** :

| Geste | Classe |
|---|---|
| clone, fetch, statut de dépôt, lecture de PR et de CI | lecture |
| commit sur la branche de la conversation, push `agent/*`, ouverture et commentaire de PR | réversible |
| push d'une branche inconnue, fusion d'une PR en `main`, création de dépôt | **engageante** (la personne valide) |
| étiquette `prod/<nom>/<n>`, bascule de production, suppression de branche ou de dépôt, rotation du jeton | **réservée** |

- **La PR est le support de « À valider »** : la carte reprend l'avant / après actuel, pointe vers la PR et sa CI ;
  fusionner, c'est fusionner la PR (par la personne), plus un `git merge` local.
- **La CI est une preuve au journal** : le statut de checks du commit proposé est lu et inscrit avec la commande ;
  G1 s'étend à toutes les branches de proposition et aux PR.
- **Lien avec la promotion** : l'étiquette `prod/<nom>/<n>` se crée sur le commit de `main` après PR verte et accord
  de la personne ; la production se reconstruit depuis GitHub.
- **Interface** : par projet, branche, retard et avance, PR ouvertes, dernier run de CI, version en production.
- **Les commits d'agent se distinguent** : trailer `Agent:` / `Conversation:` (prévu dans `structure-projet.md`) ou compte bot.
- **Le connecteur GitHub MCP** quitte l'héritage par défaut dès que les commandes natives le remplacent (D-08).

### 5 bis.4 À trancher

1. **GitHub App ou jeton fine-grained par dépôt ?** Contraintes SSPCloud à vérifier : héberger la clé privée de l'App
   hors de portée des agents, et savoir si GitHub peut appeler le pod (webhooks) ou seulement l'inverse.
2. Les agents code **poussent-ils eux-mêmes** (sur leur branche), ou l'Atelier pousse-t-il à leur place ?
3. Le jeton de la personne reste-t-il sur le pod ? Si oui, comment le rendre illisible aux agents ?
4. L'Atelier **impose-t-il** la protection de branche à la liaison, ou la recommande-t-il seulement ?
5. Fusion : PR GitHub seulement, ou aussi la fusion locale pour les projets sans remote ?
6. Le dépôt GitHub est-il **obligatoire** à la création d'un projet, ou garde-t-on `git init` local avec publication différée ?
7. Source de vérité de la production : l'étiquette poussée ou le worktree local ?

## 6. Ce que cela change pour le plan

Le plan de finition garde son ordre (identité → garde → rôle unique → états vrais → brouillon/production) et reçoit
trois lots de plus, décrits dans [`plan-de-finition.md`](plan-de-finition.md) § 2 bis : **lot 1 bis** (verrou de
conversation et miroir), **lot 3 bis** (registre unique et surcharge par connecteur, classes des outils amont),
**lot 3 ter** (communication externe, après les lots 1 et 3) et **lot 3 quater** (intégration GitHub, § 5 bis).

## 7. Décisions à prendre

1. Gateway : fusionner catalogue YAML, registre SQLite et `mcp_registry.py` en **un registre**, et où vivent les
   surcharges (SQLite versionné, ou fichier déclaratif) ?
2. Surcharge d'outil : étendre les « variantes » (réutilise l'existant) ou créer l'*overlay* par connecteur
   (plus propre) ? **Recommandation** : l'overlay.
3. Classe d'un outil amont inconnu : **engageante** par défaut ?
4. Gabarits : lesquels retenir, un moteur de copie ou une simple copie ?
5. Un seul champ `commande` : dans `artefact.json` ou dans `deploiement` ?
6. Classe des outils Onyxia de l'Assistant (`project_start`, `service_deploy`, désinstallation) : engageante ?
7. GPU : préemption par file d'attente, bail, ou demande dans « À valider » ?
8. Fusionner `atelier_montrer`, `atelier_navigateur_ouvrir` et l'écran en un seul descripteur de vue ?
9. Classes du navigateur (lectures et actions) : à journaliser ?
10. Envoi par un agent planifié sans personne : attente dans « À valider », liste blanche, ou **interdit en v1** ?
11. Après lecture de contenu externe : bloquer les actions engageantes, ou exiger une confirmation renforcée ?
12. Entrant : n8n comme relais ou webhook natif ? Qui arme un déclencheur entrant ?
13. Mail : SMTP direct ou via n8n ? Un envoi mail est-il toujours engageant, y compris vers soi-même ?
14. Capacités d'artefact : consenties dès le brouillon ?
15. Identité signée et capacités : d'abord pour les agents de l'Atelier, ou pour tous ? **Recommandation** : pour tous,
    parce que c'est la même pièce que la fermeture de la clé propriétaire.
