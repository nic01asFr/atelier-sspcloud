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
| Onyxia | non (ou général si la personne l'a configuré) | pod / service / GPU si déclaré ; déploiement engageant | **général, cadré par les classes** | par octroi (général si la personne l'a configuré) | non | par octroi |
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

### 4.3 Onyxia : trois niveaux d'accès *(précisé le 11/11, d'après Nicolas)*

Onyxia n'est pas « jamais en accès général » : **l'accès général existe quand la personne le configure explicitement, et
il reste cadré**. Trois niveaux, du plus étroit au plus large :

| Niveau | Qui | Ce qu'il ouvre | État |
|---|---|---|---|
| **Borné par projet** (défaut) | agents code d'un projet qui déclare `deploiement` | le mandataire du projet : session `proj-<slug>` et pod lié imposés, pas de préemption GPU, `expose_public` refusée | *lu* (`onyxia_projet.py`, 81 tests) |
| **Général, cadré, pour l'Assistant** | l'Assistant | les 24 outils d'Onyxia ; `expose_public` et `unexpose_public` réservées à la personne ; `project_start`, `service_deploy`, désinstallation à classer **engageantes** (question ouverte, `onyxia-projet.md` § 5) | *lu* pour les 24 outils ; classes **cible** |
| **Général, configuré par la personne** | l'agent, le projet ou la famille qu'elle désigne | un mandataire général au profil choisi : outils, espace de noms, quotas, durée ; journalisé et révocable | **cible**, rien n'existe |

Règles communes : l'accès général est un **octroi explicite de la personne** (jamais un défaut ni une demande d'agent
acceptée en silence) ; il passe par le même moule de mandataire (§ 4.2, 4) avec **arguments imposés, classes de commande,
plafonds et journal** ; il est **daté et révocable** ; il se résout dans les couches de profil (§ 1.2) comme n'importe quelle
capacité. Ce qui est général pour l'Assistant reste cadré par les classes ; ce que la personne élargit pour un autre agent
l'est par ce qu'elle a écrit dans la configuration.
*Précaution* (rapportée) : les sessions d'Onyxia sont globales, donc un accès général permet de rattacher `proj-<slug>` ailleurs ;
le mandataire le détecte aujourd'hui sans le réparer.

### 4.4 Les structures Onyxia liables à un projet, pour la partie code *(cadré le 11/11 ; base : `onyxia-projet.md`, `commandes/structure.py`, rapporté pour le reste)*

**Principe.** Un projet lie à Onyxia **par un seul endroit** : le bloc `deploiement` de `.atelier/projet.json` (schéma strict).
Ce bloc **borne ce qu'Onyxia donne aux agents code du projet** : c'est le mandataire du projet (§ 4.3, niveau « borné »),
jamais Onyxia en direct. Le lien se déclare par une commande **engageante** (aperçu, jeton, accord de la personne), se retire
par `retirer: true`, et « Annuler » remet l'état d'avant.

**Ce qu'un projet peut lier (existant, lu).**

| Structure | Déclaration | Sessions Onyxia imposées | Ce que reçoit l'agent code |
|---|---|---|---|
| **Pod de développement** | `pod` (+ `namespace`) | `proj-<slug>` (pod CPU) | `exec`, `job_poll`, `read_file`, `write_file`, `list_files`, `session_status`, `project_bind` |
| **Service** | `service` : chemin d'un `<nom>.service.yml` | `proj-<slug>` | `service_status`, `service_deploy`, `service_stop`, `service_warm`, `service_provision` ; `yaml_path` imposé |
| **GPU** | `gpu: true` (avec un pod, un service, ou **seul**) | `proj-<slug>-gpu` (pod GPU, nom court au-delà de 23 caractères, D-72) | `gpu_switch` (projet imposé, **sans préemption**), `gpu_release`, `gpu_status` ; les outils d'exécution prennent `cible` (cpu ou gpu) |
| **Commande et port** | `commande`, `port` | — | annoncés dans les consignes du serveur |

Règles de validité : `pod` **ou** `service`, pas les deux ; sinon `gpu: true` seul ; un champ inconnu, un nom Kubernetes invalide ou
un port hors 1-65535 sont refusés ; un projet dont le slug dépasse ~32 caractères n'a que son pod GPU.

**Ce que le cadre cible ajoute.**

1. **Un lien nommé par rôle**, pour permettre le **pod de développement et le service publié ensemble** (aujourd'hui : l'un ou
   l'autre) : deux entrées nommées dans le bloc (`dev`, `publie`), chacune avec sa session imposée ; le GPU reste un attribut.
2. **Un seul propriétaire de la commande de démarrage** : `artefact.json` pour un artefact local, `deploiement` pour Onyxia ; un
   champ `cible: local | pod | service` dit lequel s'applique (aujourd'hui, deux champs `commande` coexistent).
3. **Un cycle de vie classé**, chaque étape ayant sa classe de commande :

   | Étape | Outils | Classe cible |
   |---|---|---|
   | déclarer, lier | `atelier_projet_deployer_declarer`, `project_bind` | engageante (existe) |
   | lire l'état | `session_status`, `service_status`, `gpu_status`, `list_files`, `read_file`, `job_poll` | lecture |
   | travailler dans le pod | `exec`, `write_file` | réversible, **borné au pod** |
   | réchauffer, libérer | `service_warm`, `gpu_release` | réversible |
   | démarrer ce qui engage le quota | `project_start`, `service_deploy`, `service_provision`, `gpu_switch` | **engageante** |
   | arrêter, désinstaller | `service_stop`, `session_stop(uninstall)` | engageante / **réservée** pour la désinstallation |
   | exposer au public | `expose_public`, `unexpose_public` | **réservée** (existe) |

4. **Un geste de déploiement enchaîné** : `atelier_projet_deployer_lancer` fait `service_scaffold` → `service_provision` →
   `service_deploy` après **un seul** accord ; le gabarit `ml-gpu` pose le squelette de `<nom>.service.yml` et le bloc
   `deploiement` à la création.
5. **GPU** : l'agent code **ne préempte pas** le GPU d'un autre projet ; pour obtenir un GPU occupé, une demande dans « À valider »
   (ou une file ou un bail : décision), jamais une préemption silencieuse ; chaque acquisition et libération est journalisée.
6. **Le droit du pod n'est pas la borne** : `exec` donne un shell dans le pod, avec ce que son compte de service peut faire
   (Kubernetes, S3). Cible : droits du compte de service **réduits au projet**, secrets par le coffre (§ 5 ter), jamais en dur.
7. **Les fichiers** : `push_repo` et `pull_artifact` (refusés au profil code) pourraient s'ouvrir **bornés au dossier du projet**.
8. **L'identité** : le mandataire du projet s'appuie sur l'**identité signée** de la conversation (lot 1), plus sur la clé
   propriétaire, qui ouvre aujourd'hui les deux portes (`/mcp` et `/mcp/onyxia`).
9. **Les sessions d'Onyxia étant globales**, le mandataire **répare** une session détachée au lieu de seulement la refuser ;
   préfixe de session propre à l'Atelier (aujourd'hui `proj-<slug>` ; le pod de l'Atelier utilise déjà `proj-claude-code`).
10. **L'état visible** : la carte du projet montre le pod (actif ou non), le service, le slot GPU et leurs coûts, lus par les
    outils de lecture ; chaque appel du mandataire laisse une ligne au journal.

**À trancher** (reprend les points ouverts de `onyxia-projet.md` § 7) : (a) le pod et le service ensemble, avec deux entrées
nommées ? (b) préemption du GPU : demande dans « À valider », file, ou bail ? (c) ouvrir `push_repo` et `pull_artifact` bornés au
dossier ? (d) deux outils dédiés pour démarrer et arrêter `deploiement.commande` en tâche de fond (aujourd'hui par `exec`) ?
(e) préfixe de session propre à l'Atelier ? (f) l'Assistant garde-t-il `project_start`, `service_deploy` et la désinstallation en
accès libre, ou en engageante ? *(recommandation : engageante)* (g) droits du compte de service du pod : qui les réduit, et comment ?

### 4.5 Créer, tester et rattacher un service MCP, comme on crée un projet Onyxia *(cadré le 11/11, d'après Nicolas)*

**Principe.** On sait structurer les MCP en général et sur Onyxia ; un **service MCP est un projet comme un autre** (gabarit
`service-mcp`), avec le même cycle, les mêmes classes et les mêmes preuves qu'un projet Onyxia :

| Projet Onyxia (§ 4.4) | Service MCP (cible) |
|---|---|
| déclarer le bloc `deploiement` (engageante) | déclarer le bloc `mcp` du projet (engageante) |
| lier : `project_bind` | rattacher : l'ajouter au registre de la gateway comme connecteur |
| démarrer, utiliser, arrêter | démarrer (supervisé ou service Onyxia), tester, arrêter |
| mandataire borné, arguments imposés | surcharge par connecteur : classe par outil, arguments imposés, schéma réduit |
| journal des appels du mandataire | journal des appels amont et des tests |

*Aujourd'hui (lu / rapporté)* : le gabarit `service-mcp` existe mais ne change que la ligne « Prochaine étape » d'`ETAT.md` ;
`atelier_connecteur_ajouter` appelle `sonder` après l'ajout et `decrire_connecteur` fait décrire un connecteur par le modèle
**sans appeler ses outils** ; il n'existe **aucun `source: artefact`** dans le registre : un service MCP écrit par un agent ne
devient pas un connecteur sans geste manuel (J9).

**1 · La déclaration.** Un bloc `mcp` dans `.atelier/projet.json`, un par service exposé par le projet :
`{nom, transport: stdio | streamable-http, source: artefact | onyxia | distant, commande, port | url, auth: secret://…, outils
attendus (le contrat), profils autorisés}`. Les trois sources reprennent ce qui existe : un **processus local supervisé** (pont
stdio), un **artefact serveur** du projet (adresse locale), un **service Onyxia** (bloc `deploiement.service` + URL). Un service
distant tiers (URL et secrets) suit la même déclaration, sans code du projet.

**2 · La création.** `atelier_projet_creer(gabarit: service-mcp)` pose un squelette qui fonctionne : serveur MCP minimal, **le
contrat des outils** (`outils.md` : noms, schémas, classe voulue), `tests/`, l'artefact ou le `deploiement`, et le bloc `mcp`.
Aujourd'hui le gabarit ne pose rien de tout cela.

**3 · Le test, condition du rattachement.** Une commande `atelier_mcp_tester` rend un rapport avec preuve, par étapes :
démarrage → `initialize` (protocole, capacités) → `tools/list` **conforme au contrat** → appel de chaque outil en **lecture** avec un
jeu d'essai (les outils d'écriture ne s'appellent **jamais** sans accord, ou en bac à sable) → authentification (refus sans jeton) →
**reconnexion** (session expirée, serveur redémarré) → limites (taille, délai) → sécurité (aucun secret en sortie ; contenu rendu
traité comme non fiable). `sonder` et la description par le modèle en sont les premières étapes déjà là. Classe : lecture ou
réversible ; **chaque rapport est au journal**.

**4 · Le rattachement.** Il passe par `atelier_connecteur_ajouter` étendu à une **source projet** : commande **engageante**
(aperçu : outils, classes, profils concernés) ; secrets **par référence** (coffre, § 5 ter) ; **version figée** (un commit du
service) : une mise à jour redemande un test et un accord. Par défaut le connecteur n'est **exposé à personne** : la personne
choisit les profils (famille, projet, agent) et les classes par outil, **engageante pour tout outil non classé**. L'agent qui
développe le service **propose** le rattachement ; il ne l'accomplit pas.

**5 · La surveillance.** Sonde périodique, états visibles et honnêtes, alerte d'un gardien (contrôle déterministe) quand le service
ne répond plus ; désactivation et retrait **réversibles**. Le cycle de connexion, d'actualisation et de reconnexion d'un connecteur
streamable (jeton expiré, session expirée, flux coupé, serveur redémarré) est cadré au § 4.6.

**À trancher** : (a) où vit le bloc `mcp` et si un projet peut en exposer plusieurs ; (b) la batterie de tests de conformité : minimale
(`initialize`, `tools/list`) ou complète ; (c) un bac à sable pour tester les outils d'écriture ; (d) qui peut rattacher, et si un agent
de l'Atelier peut proposer un rattachement ; (e) un catalogue de services partageables entre personnes ; (f) une montée de version
automatique ou toujours soumise à accord.

### 4.6 Connexion, actualisation et reconnexion des connecteurs *(étudié le 11/11 ; *rapporté*, `fichier:ligne` à rouvrir avant correction)*

**Constat : aujourd'hui, un connecteur n'est sondé qu'une fois, au démarrage, et sur un geste de la personne ; rien ne tourne en tâche de fond.**

```
 Démarrage de l'Atelier ──► pool.startup() (UNE fois, séquentiel) : pour chaque serveur
     désactivé → « disabled » · stdio non lancé par la passerelle → « stdio-local » (jamais connecté)
     HTTP : streamable (initialize 2025-03-26, puis 2024-11-05) → repli SSE → « connected » | « error: … »
     401 / 403 → fichier sondes-authentification.json → connecteur RETIRÉ de la distribution
 Appel d'outil : SSE coupé → une réouverture + un rejeu · streamable → 1 POST, AUCUNE gestion d'erreur · stdio → relance si mort
 Re-sonde : seulement sur geste humain (/mcp/reprobe, enregistrer un identifiant, activer, modifier, accorder)
```

**Les trous (rapporté).**
1. **Jeton amont expiré** : rien ne le détecte ; le streamable reçoit un 401 brut. **Aucun OAuth sortant** dans le dépôt : les jetons amont
   sont des Bearer statiques, fixés dans le client à la connexion (un nouveau secret n'est pris qu'après une re-sonde). L'OAuth de
   `oauth.py` est celui de la gateway comme **serveur**, sans `refresh_token`, jetons de 90 jours.
2. **Session streamable expirée** : `call_tool` ne ré-initialise pas sur 404 ; après un redémarrage du serveur, tout appel échoue jusqu'à
   une re-sonde manuelle. Côté porte `/mcp`, une session inconnue est acceptée telle quelle au lieu de renvoyer 404, donc Claude Code ne
   ré-initialise jamais.
3. **SSE** : réouverture sans `Last-Event-ID`, un seul rejeu, pas de keepalive ; un appel en vol est perdu ou **rejoué** (double effet possible
   sur un outil d'écriture).
4. **États mensongers** : « connecté · N outils » reste affiché après une panne (l'état dérive de `tools` en mémoire) ; « local · N outils »
   ne dit rien du jeton ni du serveur ; 404 et erreurs réseau ne se distinguent pas d'un 401 ; un seul bouton global « relancer la sonde »,
   pas de « reconnecter » par connecteur, pas d'état « expiré » ni « refusé ».
5. **Pas de backoff ni de plafond** ; un connecteur lent bloque le démarrage séquentiel.
6. **`listChanged: true` est annoncé mais jamais émis** (`toolsRevision` est compté, aucune notification n'est envoyée), et la porte `/mcp`
   n'a ni GET ni flux SSE ; un agent en cours ne voit pas un connecteur ajouté ou retiré avant son prochain tour.
7. **Un connecteur refusé est retiré des projets**, mais ne revient pas quand le jeton est corrigé sans nouvelle sonde.
8. **La sonde horaire des gardiens** (`gardiens.md`) **n'existe pas dans le code**.

**La cible.**

```
 non_configuré ─► connexion ─► connecté ◄─► dégradé
                                 │  │            │
              401 + refresh ──► expiré ─► connexion          refusé (401/403 après refresh, ou jeton absent)
                                 └── hors_ligne (réseau, 5xx, délai) ─► connexion (backoff) ─► …
```

- **Une machine à états par connecteur**, dans une table de `gateway.db` (qui remplace le fichier `sondes-authentification.json`) :
  `{état, depuis, cause (code et `WWW-Authenticate` court), prochaine tentative}`. Le badge de l'interface vient de cet état, **jamais** du
  nombre d'outils.
- **Actualisation avant expiration** : pour un OAuth amont, `expires_at` et `refresh_token` stockés **par référence** (coffre, § 5 ter) ;
  rafraîchir à ~80 % de `expires_in`, ou sur un 401 puis rejeu ; jamais de valeur au journal.
- **Reconnexion** : backoff exponentiel avec gigue (1 s à 5 min), plafond de tentatives (au-delà : `hors_ligne` et sonde lente), **un seul
  vol par connecteur** (verrou).
- **Streamable** : sur 404 avec `Mcp-Session-Id`, ré-`initialize` puis rejeu **des seuls outils de lecture** ; une écriture ne se rejoue
  qu'avec l'accord prévu par sa classe. SSE : reprise avec `Last-Event-ID`, ping périodique.
- **Sonde de santé** : tâche asynchrone par connecteur, parallèle et bornée (30 s à 5 min selon l'état), écrivant au journal ; le gardien Santé
  **lit l'état**, il ne sonde pas le réseau lui-même (contrôle déterministe, 0 jeton).
- **Interface honnête** : « refusé (401) », « expiré, renouvellement en cours », « hors ligne depuis 12 min », « non sondé » pour un connecteur
  local ; **bouton « reconnecter » par connecteur** ; l'ajout d'un connecteur lance la sonde et montre le résultat.
- **Propagation aux agents** : émettre `notifications/tools/list_changed` à chaque changement d'état (`toolsRevision` existe déjà), et faire
  répondre **404 à une session inconnue** pour que Claude Code ré-initialise ; repli : réécrire le `.mcp.json` et signaler au prochain tour.
  *Par famille* : un agent code (`--strict-mcp-config`, configuration fixée au lancement) voit le changement au tour suivant ; l'Assistant, qui
  passe par `gateway_call_tool`, le voit tout de suite ; VS Code et le terminal lisent le même `.mcp.json`.
- **Classes** : `sonder`, `reconnecter` (mêmes hôte et identifiants) et `actualiser` (rafraîchir un jeton sans changer le secret) sont
  **réversibles** ; changer l'hôte, renouveler ou accorder un secret sont **réservés** (aujourd'hui, accorder est réversible) ; les sondes
  automatiques ne changent aucune configuration ; seul le **retrait automatique** d'un connecteur refusé est journalisé.

**À trancher** : (a) a-t-on des connecteurs à OAuth sortant (`refresh_token`), ou seulement des Bearer statiques ? (b) état en table
SQLite ou en fichier ? (c) rejeu automatique limité aux outils de lecture ? (d) un connecteur refusé reste-t-il retiré des projets, ou
seulement signalé ? (e) fréquence de sonde : 1 h (doc des gardiens) est trop lent, viser 1 à 5 min en bon état avec backoff en panne ;
(f) implémenter le GET SSE de `/mcp`, ou garder POST seul avec 404 sur session inconnue ? (g) un `refresh_token` pour les jetons de la porte
(90 jours aujourd'hui) ? (h) **D-23** : wikichat « en échec » est-il un problème de connecteur ou de service ? à vérifier avant de le rattacher.

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

## 5 ter. Les secrets, le navigateur et la gateway configurable *(étudié le 11/11 ; *rapporté* par un lecteur, `fichier:ligne` à rouvrir avant correction)*

**Principe.** Un secret est **confié sans être vu** : l'agent s'en sert, il ne le lit jamais. La valeur est résolue côté serveur
au moment de l'usage, et l'agent ne manipule qu'une **référence**.

### 5 ter.1 Le modèle actuel

```
 Personne (UI) ─ PUT /v1/secrets/<nom> ─► ~/work/.secrets/<nom>  (0600, en clair)            accords.py
        │  atelier_connecteur_accorder (réservée) : lit le fichier et COPIE la valeur dans la config du connecteur
        ▼
 gateway.db  (config + table server_credentials : bearer, en-têtes)  EN CLAIR, fichier 0600
        │  .mcp.json et fichier effectif : seulement des références ${ATELIER_MCP_<SERVICE>_<CLÉ>}
        ▼
 ~/work/.secrets/claude-env.sh (0600) : clé propriétaire ATELIER_MCP_KEY + variables du pool + .atelier/env.json des projets
        ▼  lu par le harnais (chaque tour), ~/.bashrc, code-server, wikichat
 Agent (Bash) : hérite de TOUTES les variables (harness.py:652-694 : os.environ.copy() + update)
```

*Lu, et solide* : références déduites sans état (`mcp_secrets.py`) ; fichiers 0600 créés atomiquement ; noms réservés à l'Atelier
refusés ; valeurs masquées `••••xxxx` en réponse d'API ; écritures journalisées sans valeur ; aucun secret en argument d'une
commande d'ajout de connecteur ; filtre de transcripts qui remplace les valeurs connues par `<secret:empreinte>`.
*Documenté seulement* : les identifiants sont en clair dans `gateway.db`, sans chiffrement (`SECURITY.md:146`) ; D-06 (hooks,
« moyen de demander un accord sans recevoir la valeur ») est une correction **prévue**.

### 5 ter.2 Les fuites possibles

**Navigateur (identifiants confiés à un agent).** *Il n'existe aucun mécanisme de saisie par référence.* Les voies actuelles :
1. la personne tape l'identifiant dans la conversation → transcript Claude Code, journal wikichat, mémoire (déjà arrivé pour
   une clé d'API, D-56) ; le filtre ne masque que les valeurs déjà connues ;
2. l'agent appelle `fill` / `fill_form` / `type_text` avec la valeur en argument → transcript et audit ;
3. `take_snapshot` après saisie (l'arbre d'accessibilité contient la valeur d'un champ texte, *déduit*), `take_screenshot`
   (champ non `password`), `evaluate_script`, console et réseau (corps POST, en-têtes `Authorization`, cookies) : **tout
   est en lecture autorisée d'office** et rejoint le transcript ; `garde_navigation` ne filtre que les URL ;
4. « Prendre la main » : la personne tape elle-même, **seul chemin sans fuite**, mais l'agent doit attendre ;
5. le profil Chrome par conversation garde cookies et sessions sur disque ; l'agent, avec Bash et `sudo`, peut les lire (*déduit*).

**Connecteurs.** Valeurs en clair dans `gateway.db` (une copie par accord) ; **la clé propriétaire et tous les jetons de
connecteurs sont dans l'environnement de chaque agent** (un `env` ou `cat` suffit ; les règles `Read` ne couvrent pas `env`) ;
« accorder » **copie** la valeur dans la config, ce n'est pas une vraie référence ; changer l'URL d'un connecteur envoie ses
secrets vers un autre hôte (garde : commande réservée) ; `PUT /catalog/credentials` reçoit encore des valeurs par l'API ;
deux stockages parallèles (`server_credentials` et les accords du registre) ; le filtre agit au rendu des transcripts, pas
sur le `.jsonl` source de Claude Code (*déduit*).

### 5 ter.3 La cible

1. **Un coffre.** Objet `secret` : identifiant, libellé, type (mot de passe, jeton, identifiant + mot de passe, TOTP),
   propriétaire, dates de création, de rotation, d'expiration ; valeur **chiffrée au repos** avec une clé maître hors du
   volume (ou référence vers un coffre externe) ; `gateway.db` ne porte que des références `secret://id`.
2. **Un accord** : *(secret, bénéficiaire : famille / projet / session / agent, capacité : « utiliser sur l'hôte H, dans le
   champ C », durée, nombre d'usages)*. Création par commande **réservée** ou carte « À valider » ; révocation immédiate ;
   chaque usage au journal (qui, quel secret, quel hôte, résultat), **jamais la valeur**.
3. **Injection côté serveur.** Le mandataire résout la référence au moment de l'appel amont ; un connecteur local reçoit la
   valeur dans l'environnement d'un processus enfant, **pas** dans celui de l'agent. L'environnement de l'agent est une
   **liste blanche** (fin de `os.environ.copy()`), et la clé propriétaire est remplacée par la capacité courte de la
   conversation (lot 1).
4. **Navigateur.** Un outil `atelier_navigateur_remplir(uid, secret_ref)` (réversible, consentement une fois par domaine) :
   le pont tape la valeur par CDP, l'agent ne la voit jamais ; refus si l'origine de la page diffère de l'origine
   accordée ; la valeur s'ajoute au filtre de masquage. **Masquage** : post-traitement de `take_snapshot`
   (`<secret:ref>`), flou des champs `password` et des champs remplis par référence dans `take_screenshot`, masquage de la
   console et du réseau (`Authorization`, `Set-Cookie`, corps contenant la valeur) ; `evaluate_script` et `fill` avec
   valeur brute interdits ou masqués au retour sur une page portant un secret accordé. TOTP et CAPTCHA : saisie humaine.
   Une option « saisie par la personne » (Prendre la main) avec bandeau dédié.
5. **Hygiène par les hooks** : `PreToolUse` refuse `env`, `printenv`, la lecture de `.secrets` et de `claude-env.sh` ;
   `PostToolUse` masque les sorties qui contiennent une valeur accordée ; le transcript source est filtré.

### 5 ter.4 La gateway, entièrement configurable depuis l'Atelier

*Déjà faisable (lu)* : ajouter, retirer, sonder, activer, accorder, renouveler, modifier un connecteur (interface, API
`/v1/mcp/servers`, commandes `atelier_connecteur_*`) ; profils et bundles ; compositions (CRUD, promotion, exécution) ;
épingles d'outils ; import / export du registre ; secrets.
*Reste dans des fichiers, la base ou le code* : le catalogue d'organisation (YAML) ; les indications d'outils (regex dans
`tool_hints.py`) ; les profils d'accès natifs ; **les classes de commande hors `atelier_*`** (inexistantes) ; les
plafonds d'appels amont (introuvables) ; **les arguments imposés** (seul Onyxia a un mandataire borné) ; les deux
stockages de secrets ; `.atelier/env.json`.

**Cible : deux écrans et leurs commandes.**

| Écran | Contenu | Commandes (classe) |
|---|---|---|
| **Secrets** (coffre) | liste, création, rotation, révocation, usages, accords par portée | `atelier_secret_creer` (réservée) ; `_accorder` (réservée ; via « À valider » pour un agent) ; `_revoquer` (réversible) ; `_renouveler` |
| **Passerelle** | registre unique ; surcharge par connecteur (classe par outil, titre français, arguments imposés, schéma réduit) ; profils par famille, projet, agent ; accès par capacité ; plafonds (appels par minute et par jour) ; journal d'appels amont filtrable | `atelier_passerelle_surcharger` (engageante) ; `_plafonner` (engageante) ; `_profil_modifier` (réversible) ; `_journal` (lecture) |

Classes : **lecture** (lister, journal) ; **réversible** (profil, épingle) ; **engageante** (ajouter un connecteur, surcharge,
plafond) ; **réservée** (accorder ou renouveler un secret, changer l'hôte d'un connecteur, clé propriétaire).

### 5 ter.5 À trancher

1. **Chiffrement au repos** : où vit la clé maître (secret Kubernetes, KMS, Vault) ? `SECURITY.md` juge que ça n'apporte guère
   tant que la clé vit sur le même disque.
2. **Navigateur** : masquer au niveau du pont `chrome-devtools-mcp` (proxy de filtrage) ou fournir un outil maison ?
   Que faire d'`evaluate_script`, qui peut tout lire ?
3. **Consentement** : par domaine, par session, ou par usage via « À valider » ? Durée par défaut ?
4. Supprimer `os.environ.copy()` et la clé propriétaire de l'environnement des agents : calendrier (prérequis : capacité
   courte par conversation).
5. Fusionner `server_credentials` et les accords du registre en un seul stockage.
6. TOTP / 2FA et CAPTCHA : saisie toujours humaine ?
7. Portée « famille » : définition, et héritage par rapport à D-08 (8 projets sur 16 héritent de tous les connecteurs).
8. Rétention du `.jsonl` source de Claude Code : filtrer à l'écriture ?

## 5 quater. Voix et audio, pour l'Atelier et ses agents *(étudié le 11/11 ; *rapporté* ; mesures d'après `voix.md`, non revérifiées)*

### 5 quater.1 Ce qui existe

- **Un service sur le pod, hors de ce dépôt** : projet `nouveau-projet-2`, FastAPI sur `127.0.0.1:18920`, CPU seul, lancé à la main,
  hors superviseur. STT : faster-whisper `small` (int8) ; TTS : Kokoro-82M, voix `ff_siwis` ; modèles locaux, aucun appel sortant.
  Routes : `/health`, `/tts`, `/stt`, un flux `WS /audio/stream/{id}`, `/mcp` (outils `dire` et `ecouter`). *Mesuré (26/09)* :
  2,18 Go résidents, STT environ 1,1 s, TTS 0,4 à 0,8 s, deux STT et un TTS simultanés dépassent 2 s chacun, WER 2,8 % sur 12 phrases
  synthétisées (aucune voix humaine testée). Le code n'a aucun remote : il n'existe que sur le volume.
- **Correction** : la prémisse « service sans authentification » est périmée ; un jeton est exigé partout sauf `/health` depuis le
  24/09 (commit `dc13e80`). Reste exposé : tout processus du pod qui lit `~/work/.secrets/voice_token`, et `VOICE_TOKEN` figure dans
  `claude-env.sh`, donc dans l'environnement de **tous** les agents.
- **Côté Atelier : rien.** Aucun `MediaRecorder`, `getUserMedia`, `speechSynthesis` dans `web/js` ; aucune route `/v1/voix` ; seulement
  un commentaire marquant l'emplacement d'un futur bouton micro. Les canaux sortants se limitent au Web Push vers l'appareil de la
  personne, fermé aux agents. `docs/vision/voix.md` (lots V0 à V6, décisions V-1 à V-9 en attente) n'est qu'une proposition.
- **Rien pour la page Agents** : ni entrée ni sortie vocale pour un agent planifié, un gardien ou un réparateur ; pas de classe de
  commande, de capacité, de plafond ni de budget pour la voix ; pas de consentement de capture ; pas de banc sur voix humaines.

### 5 quater.2 La cible

- **Où.** Une brique système unique `atelier-voix` sous le superviseur (hors du plafond des applications, plafond propre ~3 Go, arrêt
  après inactivité, préchauffage) ; la voix interactive reste sur CPU ; un pod GPU ne sert qu'aux traitements différés
  (transcription de réunion longue) via le bail de `gpu-arbitrage.md`.
- **Accès.** Navigateur : l'origine de l'Atelier (`/v1/voix/…`, session, jeton posé côté serveur). Agents : une famille d'outils `voix` de
  la gateway **par le mandataire** (pas de connecteur dans le pool, **plus de `VOICE_TOKEN` dans l'environnement**). Un résultat d'outil ne
  porte jamais d'audio, seulement un chemin et une durée.
- **Identité.** Capacité portée par l'identité signée ; pour un agent de l'Atelier, une capacité **accordée, datée, révocable**, avec arguments
  imposés et plafonds.
- **Classes.** `transcrire` un fichier du projet : **lecture** ; `dire` (synthèse vers un fichier) : **réversible** ; `ecouter` en
  continu (micro ouvert) : **réservée à la personne, geste d'interface, jamais lancé par un agent** ; `parler` à un tiers ou `appeler` :
  **engageante** (aperçu du texte et du destinataire, « À valider », jamais d'accord oral) ; administration du service : réservée.
- **Données.** L'audio brut n'est **jamais conservé** ; la transcription est la seule trace, filtrée comme tout transcript ; l'API Web Speech
  du navigateur est interdite (le son partirait chez un tiers).
- **Consentement.** Le micro s'ouvre par un geste de la personne dans la page de l'Atelier, avec indicateur visible, **jamais depuis un cadre
  du panneau ni une création** ; aucun micro permanent pour un agent.
- **Injection par la voix.** Toute transcription est une **donnée non fiable** ; un agent qui a transcrit un contenu externe ne déclenche
  pas d'action engageante dans le même tour (règle de contamination, § 5) ; un enregistrement ne lance jamais un agent, il écrit dans
  « À valider » ou les événements. Seule la voix de la personne par le micro de l'Atelier a le poids d'une consigne, **sans pouvoir d'accord**.
- **Plafonds et journal.** Durée par énoncé, par conversation et par jour (ordres de grandeur à régler) ; une conversation vocale à la fois ;
  budget obligatoire pour un agent planifié. Une ligne de journal par appel (acteur, durée, latence, classe), **jamais le texte ni l'audio**.

### 5 quater.3 Les formes d'agents vocaux de l'Atelier

| Forme | Nature | Capacités accordées | Budget proposé |
|---|---|---|---|
| **Briefing parlé** | agent planifié, dossier propre | lire les fiches du jour et les lancements (lecture) ; `dire` vers un fichier ; livraison par notification avec lien, jamais de lecture automatique | 1 passage par jour, 3 000 caractères |
| **Lecture d'un compte rendu** | bouton « Écouter » de l'interface, ou agent à `dire` réversible sur un fichier du projet | `dire` | 20 000 caractères par jour |
| **Transcription de réunion vers la mémoire** | agent à capacités sur un dossier d'enregistrements fourni par la personne | `transcrire` (lecture) ; la mémoire **seulement en proposition** (« À valider ») ; sorties non fiables | 60 min d'audio par jour, différé ou GPU |
| **Alertes parlées des gardiens** | gardien en lecture seule | alertes d'abord textuelles et poussées ; la lecture vocale vient de l'appareil de la personne, jamais d'un haut-parleur du pod | plafond d'alertes par jour |
| *Dictée vers un projet* | **un geste d'interface, pas un agent** | le texte va au composeur, jamais envoyé seul | — |
| *Dialogue vocal avec l'Assistant* | **canal de l'Assistant, pas un agent** | aucun outil vocal pour le modèle ; accord par clic | — |

**Liens externes.** Téléphonie ou messagerie vocale (Tchap) : tout reste à construire ; la règle de § 5 s'applique (capacité par
connecteur, verbe et cible, envoi engageant, attente dans « À valider », liste blanche, plafonds) ; l'audio ne doit pas sortir de SSPCloud,
ce qui exclut la plupart des services de téléphonie ; une voix de synthèse parlant à un tiers exige de dire qu'il s'agit d'un agent. Une
**pièce jointe vocale différée** est plus plausible qu'un appel en direct.

### 5 quater.4 À trancher

1. Les décisions V-1 à V-9 de `voix.md` (statut système, dépôt privé, chemin, ordre des lots, GPU).
2. Retirer `VOICE_TOKEN` de l'environnement des agents dès la première étape ?
3. Une capacité voix distincte pour les agents de l'Atelier (V5 ne couvre que `code`) ?
4. Seuils de plafonds : hypothèses à calibrer par la mesure.
5. Qualité sur voix humaines et accents : aucun banc ; décide d'un modèle plus gros ou d'un GPU.
6. Le point d'accès LLM de SSPCloud peut-il servir de la transcription (aujourd'hui écarté du catalogue) ?
7. Lecture automatique des alertes ; mention « voix synthétique » pour tout tiers.
8. Transcription de réunion : qui consent, où est stockée la transcription ?
9. Téléphonie : fournisseur hébergé en France, ou rester sur le texte et le vocal différé ?
10. Ajouter le service voix aux écoutes déclarées des gardiens.

## 5 quinquies. Agents utilisables par API de l'extérieur, et canaux de communication (Tchap, Telegram…) *(étudié le 11/11, Colaig v3 lu ; *rapporté*)*

**But (Nicolas).** Pouvoir **définir** les agents et **s'en servir en API depuis l'extérieur**, les **brancher dans Tchap** (structure inspirée de Colaig) et
dans d'autres services de communication **sur standard** (Telegram, etc.), pour en disposer depuis ces canaux.

### 5 quinquies.1 Ce que Colaig v3 apporte *(lu le 11/11 : `nic01asFr/Colaig_v3`, un commit du 20/04/2026 ; la copie de juillet 2025 (v0.2) n'avait ni API ni modèle d'agent)*

*Lu* : README, `CLAUDE.md`, `AGENTS.md`, `docs/GATEWAY.md`, `docs/MCP_SESSIONS.md`, `protocols.py`, l'authentification des jetons, les adaptateurs Telegram et Matrix, le routage des
messages, les ACL, le serveur MCP et les en-têtes du planificateur. *Non lu* : l'orchestrateur, le RAG, le stockage, le validateur OIDC, le provisionneur, le corps de `PHASE6` et d'`ARCHITECTURE.md` ; **les tests
(≈ 22 800 lignes) n'ont pas été exécutés**, et ils couvrent surtout des simulations.

```
 Canaux (Matrix/Tchap · Telegram · webchat WS)  ──► MessagingProtocol.on_message → IncomingMessage ──► MessageHandler
 HTTP : POST /ask · /mcp (MCP streamable) · /workspaces* · /webhooks/storage · /platform*                  │
                                                                                          ContextResolver : salon → espace
                                                                                          Analyseur → Orchestrateur → Synthétiseur
 Monolithe Python 3.11 / FastAPI, 1 conteneur, « Zero Database » : tout est fichiers ({espace}/.colaig/…), multi-clients par config
```

| Sujet | Ce que fait Colaig v3 |
|---|---|
| **Agent** | **pas d'entité Agent** ; le plus proche est l'**espace de travail** (`WorkspaceConfig` : consigne, ton, outils, connecteurs MCP, utilisateurs autorisés, conversations liées, visibilité), complété par des fichiers `.colaig/` (identité, comportements, savoir-faire, prompts : documentés, non vérifiés). Le pipeline Analyseur → Orchestrateur → Synthétiseur est **fixe**, pas configurable. |
| **Appel en API** | l'outil MCP `colaig_ask(question, workspace_id, conversation_id, user_id)` (synchrone) et une trentaine d'autres outils MCP (créer un espace, lier une conversation, jetons, tâches) ; `POST /ask` **sans authentification** ; **pas d'API REST d'agents**, pas de tâche asynchrone ni d'idempotence ; `conversation_id` sert de clé de session persistée. |
| **Asynchrone** | tâches planifiées en JSON (une fois, cron, intervalle ; `max_steps`, désactivation après trois échecs, état « attend la personne »). |
| **Canaux** | un contrat `MessagingProtocol` (`connect`, `run`, `send`, `send_typing`, `on_message`) et un message normalisé `IncomingMessage` (utilisateur, conversation, corps, type DM / privé / public, identifiant, horodatage, réponse, plateforme, pièces jointes). **Matrix / Tchap** : assez abouti (jeton persistant, E2E, auto-join, mention requise hors message direct, filtre des messages de plus de 5 min, audio vers Whisper). **Telegram** : long polling fonctionnel, **webhook inachevé** (aucune route de réception). **Webchat** : expérimental, identité auto-déclarée. Slack, Teams, mail, voix : absents. **Pas d'appairage** : la liaison se fait par la commande « colaig lier ». Ni liste blanche d'expéditeurs, ni dédoublonnage, ni limite de débit par canal. |
| **Jetons** | `colaig_{slug}_{64 hex}`, **haché** (SHA-256), expiration 365 j, portée (tout ou un espace), rôle admin, révocation par suppression ; OIDC par JWKS ; **auth désactivée par défaut**, `user_id` alors déclaratif et usurpable. |
| **Signature** | HMAC-SHA256 avec clé primaire et secondaire, comparaison en temps constant, mais **seulement pour le webhook de stockage** ; rien pour Telegram. |
| **Messages entrants** | **aucun traitement dédié** de l'injection ni confirmation avant action ; protections pour les champs de config, l'anti-SSRF, la troncature des résultats d'outils, le filtre de secrets dans les journaux. |
| **Trous** | « colaig lier » permet à **n'importe quel membre** d'un salon non lié de l'attacher à n'importe quel espace existant ; secrets **en clair** dans `clients.yml` ; une instance partagée entre clients, isolation par chemins. |
| **Claude Code** | Colaig est **serveur et client MCP** (FastMCP) ; pas de session d'agent ; `AGENTS.md` décrit une équipe de développeurs-agents, pas des agents d'exécution. |

**À reprendre comme patron** : le contrat `MessagingProtocol` + `IncomingMessage` (à enrichir : identité signée, identifiant de dédoublonnage, plateforme toujours renseignée, agent visé) ; « un canal = un adaptateur » et le mappage salon → espace ;
le **jeton auto-localisant haché** avec portée et révocation, et la configuration MCP générée ; la validation HMAC à deux clés ; la politique de plateforme, l'anti-SSRF, la troncature, le filtre de secrets ; la séquence Matrix / Tchap ;
les **tâches planifiées** (états, désactivation après échecs, « attend la personne ») comme modèle d'agent planifié ; `conversation_id` comme clé de session.
**À refaire** : un **modèle d'agent déclaratif** ; une **API REST d'agents** (asynchrone, idempotence, signature) ; les **classes de commande** ; dédoublonnage, limite de débit, liste blanche ; **authentification fermée par défaut** ; appairage par code ;
**secrets par référence** ; isolation par dossier et processus ; messages entrants non fiables. Remarque (*déduit*) : le principe « Zero Database, tout est fichiers » s'accorde avec « un agent = un dossier » de l'Atelier.

### 5 quinquies.1 bis Ce que Colaig v3 contient *(lu par un lecteur, ~15 % des documents et le code principal ; aucun test lu ; rien exécuté)*

```
 Canaux : Matrix/Tchap · Telegram (long polling) · WebChat WS ──► MessagingProtocol.on_message ──► IncomingMessage ──► MessageHandler
 HTTP FastAPI : /ask, /workspaces*, /chat*, /health /metrics · MCP streamable /mcp (~23 outils) + jeton
   ──► ContextResolver (salon → workspace) ──► Analyseur ─► Orchestrateur (boucle d'outils) ─► Synthétiseur
   ──► stockage « zéro base » : {workspace}/.colaig/{config.yaml, profile/, skills/, prompts/, conversations/, tasks/, indexes/}
```

- **Il n'y a pas d'entité « agent »** : l'unité est le **workspace** (identité, ACL, stockage, liaisons de salon mêlés ; pas de versionnement, pas de retour arrière).
  Pipeline fixe Analyseur → Orchestrateur → Synthétiseur ; seuls prompts, température et outils se règlent. *Conclusion pour l'Atelier : un schéma d'agent neuf, à base de dossier.*
- **Appel de l'extérieur** : un outil MCP `colaig_ask` (synchrone) et `POST /ask` **sans authentification** ; pas de route d'administration d'agents, pas de SSE (`synthesise_stream`
  existe mais n'est pas câblé), pas de webhook sortant, pas d'idempotence. L'asynchrone passe par des **tâches planifiées** (`TaskDefinition` : once/cron/interval, plafond d'étapes,
  désactivation après 3 échecs, état `waiting_for_user`).
- **Authentification** : jetons `colaig_{slug}_{64hex}` **hachés**, portée, expiration, révocation ; OIDC par JWKS ; **mais l'absence de jeton laisse passer**, et l'authentification est
  désactivée par défaut.
- **Canaux** : un contrat `MessagingProtocol` (`connect`, `run`, `send`, `send_typing`, `on_message`) et un message normalisé. **Matrix/Tchap est le plus abouti** (connexion, reconnexion, E2E,
  pièces jointes déchiffrées, audio transcrit, Markdown → HTML Matrix) mais **auto-confiance de tous les appareils**, jeton en clair sur disque, auto-join sur invitation, pas de liste blanche
  d'expéditeurs, pas de dédoublonnage ni de limite de débit. **Telegram** : long polling fonctionnel, webhook inachevé. WebChat : démonstration, identité auto-déclarée. Slack : non implémenté ;
  mail, voix : absents ; la « passerelle séparée » (ponts mautrix) est seulement documentée.
- **« Réflexif »** ne veut **pas** dire auto-amélioration : c'est l'**administration par la conversation** (en message direct, des méta-outils créent un workspace, le lient, changent son
  prompt, gèrent ses propriétaires). Garde-fous lus : refus par défaut (`can_manage`, message direct seulement, admin global ou propriétaire), garde fine par cible, anti-escalade, liste blanche
  de champs modifiables, nettoyage du prompt. **Pas de validation humaine, ni journal d'audit, ni versionnement, ni retour arrière.** À côté : auto-spécialisation (facultative, à blanc par défaut,
  ne remplace jamais un prompt écrit à la main) et mémoire utilisateur.
- **Connecteurs MCP par workspace** (`tool_policy` all / read_only / explicit, domaines autorisés, plages IP bloquées, portée de session, **limite d'appels par minute**, longueur de résultat) :
  une bonne source pour la surcharge par connecteur (§ 4.2).

**Failles lues dans Colaig v3** (à vérifier par vous ; **à ne pas reprendre**) : `colaig_link_conversation` et `colaig_update_workspace` **sans contrôle de droit** (tout appelant MCP peut modifier le
prompt de n'importe quel workspace) ; les routes `POST/PUT /workspaces*` et `/ask` n'appellent jamais le contrôle d'administration ; dans un salon non lié, **n'importe quel membre** peut lier ou créer ;
secrets en clair dans `clients.yml` et `.env` ; aucun traitement des messages entrants non fiables hors documents.

**Transposable dans l'Atelier** : le contrat d'adaptateur (à enrichir : plateforme toujours renseignée, identifiant de dédoublonnage, agent visé, fil, mentions) ; la séquence de connexion Matrix/Tchap
**avec une politique explicite à la place de l'auto-confiance des appareils** ; le jeton haché à portée ; le modèle de tâche planifiée comme modèle d'agent planifié ; les garde-fous d'administration
(refus par défaut, garde par cible, anti-escalade, champs modifiables en liste blanche) ; `url_validator`, `path_validator`, filtre de secrets ; **Colaig comme connecteur MCP** de connaissance rattaché
(§ 4.5), sans y brancher les canaux. **À refaire** : le pipeline fixe et la pile RAG (ils remplacent la session Claude Code), l'agent-workspace sur un backend de stockage, l'isolation par chemins dans un
processus partagé, l'appairage, la liste blanche d'expéditeurs, la limite de débit, l'API asynchrone avec SSE et webhooks signés, le coffre de secrets.
**Pour l'auto-amélioration** (`auto-amelioration.md`) : ne retenir de la v3 que le refus par défaut, la liste blanche de champs, l'écriture à blanc par défaut et le principe de ne jamais écraser un travail
manuel ; elle n'apporte ni preuve, ni validation humaine, ni retour arrière.

### 5 quinquies.1 ter Colaig comme modèle d'un agent de l'Atelier *(précisé le 11/11, d'après Nicolas)*

**Colaig est un agent : ce qu'on veut pouvoir configurer pour un agent de l'Atelier.** Son workspace réunit en un seul objet ce que la page Agents doit faire exprimer par
un agent. Les dimensions de configuration de Colaig se retrouvent dans le cadre de l'Atelier :

| Dimension configurable (Colaig v3) | Équivalent dans l'agent de l'Atelier | État dans l'Atelier |
|---|---|---|
| identité, prompt système, ton, langue, niveau d'expertise | `CLAUDE.md` et consignes du **dossier de l'agent** | existe (fichiers) ; pas de gabarit d'agent |
| *behaviors* déclenchés par des phrases, *skills* | **skills et sous-agents** (`.claude/`) | absents (kit en spec) |
| `tools_enabled`, `tool_policy` des connecteurs (all / read_only / explicit), domaines, débit | **capacités accordées** et surcharge par connecteur (§ 4.2) | cible |
| `mcp_connectors` du workspace | connecteurs **sélectionnés** dans le registre (§ 4.2) | partiel (choix par projet) |
| liaison à des salons et canaux, utilisateurs autorisés | **liaisons de canal** (§ 5 quinquies.3), liste blanche d'identités | cible |
| tâches planifiées (cron, plafond d'étapes, attente de la personne) | **agent planifié** : horaire, budget, `waiting_for_user` → « À valider » | existe (budget, horaire) |
| propriétaires, accès public ou privé | propriétaire = la personne ; **visibilité** par capacité | cible |
| mémoire utilisateur, espace documentaire | mémoire du dossier, wikichat | existe |
| administration par la conversation (en message direct) | commandes de l'Atelier classées, **validation dans « À valider »** | existe (commandes), à ouvrir aux canaux |

**Ce que cela change dans le cadre.** Un agent de l'Atelier est défini par **un dossier et une configuration versionnée** qui expriment ces neuf dimensions ; la page Agents les rend
éditables. **Colaig en est le cahier des charges fonctionnel**, pas une dépendance : sa v3 sert de liste de ce qu'on veut pouvoir régler.

**Deux façons de l'avoir dans l'Atelier, qui ne s'excluent pas.**
1. **Agent externe** : Colaig reste son propre système (pipeline Analyseur → Orchestrateur → Synthétiseur et RAG), et l'Atelier l'appelle comme un agent distant (outil MCP `colaig_ask`,
   ou son API) avec une **capacité accordée** ; c'est une **troisième famille** dans les couches de profil (§ 1.2), « agent externe » : l'Atelier ne contrôle ni sa session ni son profil, seulement ce
   qu'il lui envoie et ce qu'il reçoit, **non fiable**. Ses envois vers l'extérieur passent par sa propre configuration, hors du cadre de l'Atelier.
2. **Agent natif de même forme** : on réexprime la configuration de Colaig comme un agent de l'Atelier (session Claude Code dans un dossier), ses canaux Tchap et Telegram devenant des liaisons de
   canal de l'Atelier. Dans ce cas la règle « un agent = une session Claude Code » reste entière.

*Recommandation* : commencer par **1** (peu coûteux, utile tout de suite, sans toucher à Colaig), et construire **2** à mesure que l'adaptateur de canal et le schéma d'agent existent.

### 5 quinquies.2 Un agent utilisable par API

*Existant (lu / rapporté)* : `POST /v1/lancements` (route interne pour wikichat et l'exécuteur) ; commandes `atelier_agent_*` ; l'Atelier comme connecteur MCP
distant (8 verbes de conduite, clé propriétaire, « agents publiés » L3 non commencés) ; rien d'un appelant extérieur à capacité limitée.

**Cible.** Une **API d'agents** de l'Atelier, qui est la même chose que ses commandes, ouverte à un appelant extérieur par capacité :

| Fonction | Route (proposition) | Classe |
|---|---|---|
| lister, lire la définition d'un agent | `GET /v1/agents`, `GET /v1/agents/{id}` | lecture |
| définir, modifier (profil, capacités, budget) | `POST` / `PATCH /v1/agents/{id}` | réversible pour restreindre ; **engageante** pour élargir |
| activer un agent | `POST /v1/agents/{id}/activer` | **réservée** à la personne |
| s'en servir : lui envoyer un message | `POST /v1/agents/{id}/messages` (clé d'idempotence ; réponse asynchrone) | réversible, plafonné |
| suivre : état, flux | `GET /v1/agents/{id}/lancements/{n}`, flux SSE, rappel signé | lecture |
| interrompre | `POST …/interrompre` | réversible |

- **Un agent = un dossier et une session Claude Code** ; sa définition est un fichier du dossier (profil, capacités, canaux autorisés) plus ses consignes, **versionnée** ;
  l'API la lit et l'écrit par les commandes de l'Atelier, jamais en direct.
- **Authentification par capacité** : clé d'API **hachée**, **portée par agent ou par projet**, durée, rotation, révocation, journal d'usage ; comparaison en temps constant ;
  jamais la clé propriétaire. Quotas par appelant et par agent. **Webhooks de rappel signés** (HMAC, horodatage, anti-rejeu).
- **Standards** : HTTP/JSON, SSE, MCP distant pour les agents publiés ; option à trancher : un point d'accès compatible avec les API de conversation usuelles.

### 5 quinquies.3 Un adaptateur de canal commun

Un **contrat unique** pour tout canal, dont la base est le `MessagingProtocol` de Colaig v3 (`connect`, `run`, `send`, `send_typing`, `on_message`, message normalisé `IncomingMessage`), enrichi de l'identité signée, d'un identifiant de dédoublonnage, de l'agent visé et d'une limite de débit :

```
 canal externe ─► receive/normaliser ─► policy (identité ? faut-il répondre ?) ─► route (canal, conversation) → (agent, session)
                   {canal, id_événement, conversation, fil, expéditeur,                                   │
                    texte, pièces jointes, mentions, direct?}                                              ▼
 canal externe ◄─ send (texte, fichier, fil) ◄─ accusé (saisie, réaction) ◄──────── la session Claude Code de l'agent
                  dédoublonnage · limite de débit par utilisateur / salon / agent · journal sans contenu
```

- **Implémentations** : **Tchap / Matrix** (reprendre de Colaig v3 la séquence de connexion, l'E2E, l'auto-join, les règles message direct / mention / fil, le filtre des vieux messages, le déchiffrement des
  pièces jointes, et ajouter le dédoublonnage et la liste blanche qui lui manquent) ; **Telegram** (Bot API) ; **mail** ; **webhook générique** entrant et sortant signé. Un adaptateur est un **service MCP / pont** rattaché
  comme un connecteur (§ 4.5), déclaré au registre, avec ses **secrets dans le coffre** (§ 5 ter), supervisé comme une brique système.
- **Un canal lié, pas un canal ouvert.** La personne **associe explicitement** (canal, conversation) à un agent ; sinon rien ne passe. Trois niveaux de confiance :
  **la personne liée** (identité vérifiée par appariement), **des invités autorisés** (liste blanche), **les inconnus** (rien, ou file d'attente d'appariement).
- **Un message de canal est l'entrée d'une conversation, à autorité limitée** : il **ne donne jamais d'accord** (la règle existe pour la voix : « aucun accord ne se donne à la voix »),
  n'exécute ni commande réservée ni engageante sans carte « À valider » **dans l'interface** ; le texte d'un tiers dans un salon est **non fiable** (§ 5, contamination).
- **Classes de l'envoi** : *répondre dans le canal lié* = réversible, plafonné ; *écrire ailleurs*, *inviter*, *créer un salon* = engageante ou réservée (§ 5.2).
- **Sécurité** (à rebours des défauts de Colaig v3 : auth ouverte par défaut, « lier » sans contrôle, secrets en clair, pas de traitement de l'injection) : jetons **hors dépôt et hors journaux** ; webhook entrant **signé, horodaté, anti-rejeu**, jeton retrouvé par table indexée ;
  chiffrement de bout en bout à traiter **explicitement** (un bot ne lit pas un salon chiffré sans gestion de clés ; vérification des appareils) ; **isolation réelle** par dossier
  et processus, pas par chemins partagés ; aucun lancement d'agent par un message d'un inconnu.

### 5 quinquies.4 De Colaig v3 à l'Atelier

| Colaig v3 | Atelier |
|---|---|
| espace de travail (`config.yaml`, `.colaig/`) | **dossier** de l'agent ou du projet : consignes, réglages, profil et capacités |
| `colaig_ask` (MCP, synchrone) | `POST /v1/agents/{id}/messages`, asynchrone, avec clé d'idempotence |
| jetons `colaig_*` hachés, portée, révocation | clés d'API **par capacité**, mêmes principes, plus journal et quotas |
| `user_ids` d'un espace | **liste blanche d'identités** dans la liaison de canal, par agent |
| « colaig lier » dans un salon | **appairage par code**, saisi dans l'interface par la personne ; jamais par un membre du salon |
| planificateur de tâches | **agents planifiés** de l'Atelier (budget obligatoire, nés désactivés) |
| pipeline Analyseur → Orchestrateur → Synthétiseur | **la session Claude Code** de l'agent, dans son dossier |
| Colaig comme serveur MCP | un **connecteur** rattachable (§ 4.5) : base de connaissance ou RAG pour les agents de l'Atelier |

**Deux façons de s'en servir, à choisir** : (a) **reprendre le contrat et les adaptateurs** Matrix / Tchap et Telegram dans une brique `atelier-canaux` de l'Atelier, qui tient l'identité, les classes et les secrets ;
(b) **rattacher Colaig v3** comme connecteur MCP de connaissance et garder ses canaux à part. *Recommandation* : (a) pour les canaux, parce que l'Atelier doit contrôler qui peut parler à quel agent ; (b) pour le RAG, si son usage est utile.

### 5 quinquies.5 À trancher

1. **Colaig v3 : source d'adaptateurs, ou service rattaché ?** (recommandation : adaptateurs repris pour les canaux, connecteur pour la connaissance).
2. Reprend-on l'**espace de travail** comme modèle d'agent, ou un schéma d'agent neuf (**recommandation : neuf**, un dossier) ?
3. **Une passerelle séparée** (comme `GATEWAY.md`) ou des adaptateurs dans le même service ?
4. **Tchap** : un bot par agent ou un bot unique qui route par salon ? Serveur Matrix, compte bot, E2E et vérification des appareils (la v3 « auto-trust » les appareils) ?
5. Un message d'une **personne liée** peut-il lancer un agent planifié, ou seulement converser avec un agent déjà actif ?
6. **Appairage** par code à usage unique : confirmé ?
7. Politique des messages non fiables : liste blanche d'expéditeurs, confirmation (dans l'interface) pour toute action engageante.
8. Le standard d'API d'agent : l'API de l'Atelier seulement, ou aussi un point d'accès compatible avec les API de conversation usuelles ?
9. **Telegram** : long polling ou webhook entrant, et **où cet entrant arrive** (l'Ingress n'expose que l'interface et les applications).
10. Les **réponses** d'un agent dans un salon à plusieurs, et ce qu'un invité voit du contexte du projet ; quotas par défaut par canal et coût en jetons.

## 6. Ce que cela change pour le plan

Le plan de finition garde son ordre (identité → garde → rôle unique → états vrais → brouillon/production) et reçoit
trois lots de plus, décrits dans [`plan-de-finition.md`](plan-de-finition.md) § 2 bis : **lot 1 bis** (verrou de
conversation et miroir), **lot 3 bis** (registre unique et surcharge par connecteur, classes des outils amont),
**lot 3 ter** (communication externe, après les lots 1 et 3) **lot 3 quater** (intégration GitHub, § 5 bis) et **lot 2 bis** (coffre de secrets, § 5 ter) **lot 3 quinquies** (voix, § 5 quater) et **lot 3 sexies** (API d'agents et canaux, § 5 quinquies).

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
16. **Accès général à Onyxia configuré par la personne** : quelle portée (espace de noms entier, ou liste de ressources), quels quotas, quelle durée par défaut, et pour quelle cible (un agent, un projet, une famille) ?
