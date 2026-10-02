# Outils, profils, supervision et auto-évolution : audit et cadre cible

État au 2 octobre 2026. Ce document prend du recul sur la distribution des outils aux agents, les hooks,
wikichat, Chrome, Onyxia, les compositions, le rôle de l'Assistant comme superviseur, et l'idée que l'Atelier
s'améliore lui-même dans un cadre défini. Il part de **mesures** (ce que les agents ont réellement fait sur le
pod) et de la **lecture du code**, puis propose un cadre cible et un ordre de réalisation.

Ce qui n'a pas pu être vérifié est dit à chaque fois : le code de wikichat n'est pas dans ce dépôt, le projet
de référence « bigmcp » n'a pas été lu, et rien de ce qui suit n'a été déployé.

## 1. Ce que les agents ont réellement fait

Mesure sur les 721 transcripts du pod (24 septembre au 2 octobre) : 15 968 appels d'outils, 2 588 échecs
(16 %). Les échecs se regroupent en causes précises, dont la plupart sont **déjà corrigées**.

| Cause | Ampleur | État |
|---|---|---|
| Canal d'autorisation fermé (« Stream closed ») | 152 | Ancien : 24 au 26 septembre, aucun depuis |
| Mode « auto » du CLI | quelques cas | Obsolète |
| L'Assistant refusé (« projet refusé : … ») | 13 | Corrigé le 2 octobre |
| `atelier_lancer_agent` : « jeton de confirmation invalide » | 7 appels sur 19 | **Actuel** |
| Onyxia `read_file` / `write_file` : `KeyError: 'session_id'` | 25 | **Actuel** (serveur Onyxia) |
| Onyxia `push_repo` : « source non reconnue » | 10 sur 10 | **Actuel** (usage) |
| `gateway_call_tool` : « Argument 'name' requis » | 13 sur 570 appels (39 % d'échec au total) | **Actuel** (usage) |
| `atelier_artefact_creer` : « projet et nom requis », « existe déjà » | 4 sur 21 | **Actuel** |
| Connecteur QGIS en 400 via la passerelle | 70 | Connecteur indisponible |

Lecture : l'infrastructure de permissions est saine depuis le 27 septembre. Ce qui reste, c'est **l'écart
entre ce que l'agent croit pouvoir faire et ce que l'outil attend**.

## 2. La carte actuelle

### Profils et niveaux de configuration

- Deux profils, **déduits** du type de conversation et codés en dur (`commandes/profils.py`) : `code` (10 outils
  `atelier_*`, bornés au projet de la conversation) et `assistant` (41 déclarés, 4 permis non déclarés :
  `atelier_envoyer`, `_transcript`, `_suivre`, `_ouvrir`).
- Niveaux où l'on peut agir : service (pool de connecteurs, profil de la passerelle), projet
  (`connecteurs-choisis.json`, `deploiement` Onyxia, mode de permission), agent du Pilote (`outils`).
  **Il n'y a pas de profil nommé au niveau d'un projet ni d'un agent.**
- `projet.json` est strict : aucun champ ne touche les outils.

### Ce que reçoit un agent aujourd'hui

| | Agent code | Assistant |
|---|---|---|
| Atelier | 10 outils, projet imposé | 41 déclarés + méta-outils de la passerelle |
| Connecteurs | `atelier`, `chrome`, `filesystem` (sur tout `~/work`), `github`, `wikichat` | `Onyxia` (complet), `atelier`, `chrome`, `wikichat` |
| Onyxia | seulement si le projet déclare un `deploiement`, borné à ce pod ou service | les 22 outils utilisables |
| Natifs | tous sauf `WebSearch` | 19 refusés, écriture limitée à `notes/` |

### Hooks

Un seul fichier de réglages (`~/work/.claude/settings.json`), lu par toutes les surfaces : wikichat
(SessionStart, UserPromptSubmit, Stop, guetteur, SessionEnd), `garde_bash` (PreToolUse), `figer-le-travail`
(SessionEnd). Rien n'est posé par conversation ni par le gabarit de projet.

### Compositions

Moteur séquentiel à étapes `tool`, `elicit`, `approval`, `wait_until`. Pas de boucle, de condition, de retry, de
mémoïsation. Pas de test dédié du moteur.

## 3. Constats

Gravité : **G** grave, **M** moyenne, **m** mineure. Les points marqués ✔ ont été vérifiés par moi (code ou pod).

### A. Frontières et secrets

- **A1 (G) ✔ Tout agent voit la clé propriétaire, le jeton GitHub et la clé du modèle.** Le service les porte dans
  son environnement ; un tour d'agent part d'une copie de cet environnement (`harness._env`) ; les mêmes
  secrets sont dans `~/work/.secrets/`, lisibles par le même utilisateur. Les consignes interdisent de publier ou
  de pousser, mais rien ne le verrouille.
- **A2 (G) La clé propriétaire sert de clé d'agent.** Les agents l'envoient à `/mcp` et à `/mcp/onyxia[/projet/<slug>]`.
  Le filtrage par profil et par projet est donc **déclaratif** : un agent qui omet l'en-tête de conversation, ou
  vise le point d'entrée d'un autre projet, obtient plus. Le code le reconnaît pour `/mcp`, pas pour Onyxia.
- **A3 (G) ✔ « Réservé » n'est appliqué que dans le mandataire Onyxia.** `expose_public` est refusé par
  `onyxia_projet.py`, nulle part ailleurs ; la passerelle route les noms du pool tels quels. Via
  `gateway_call_tool`, l'Assistant (ou une session sans conversation) peut l'atteindre. À confirmer sur le pod.
- **A4 (M) Un pod déclaré `atelier-0` donnerait à ses agents un `exec` dans l'Atelier.** Rien ne l'interdit.
- **A5 (G) La confirmation « Oui de la personne » est une consigne.** Le jeton d'aperçu est consommable par le
  même acteur. Un Assistant qui s'en affranchit déclare un déploiement, lance un agent ou annule une commande
  sans accord.
- **A6 (M) `atelier_envoyer` est « réversible »** : il peut déclencher un tour de travail sur n'importe quelle
  conversation, sans aperçu, alors que `atelier_lancer_agent` en demande un.
- **A7 (M) `atelier_connecteur_ajouter` accepte une commande `stdio` arbitraire** derrière un aperçu que le modèle
  peut confirmer lui-même.
- **A8 (M) `chemins_proteges` est prévu dans le schéma et jamais appliqué** : un agent peut éditer les garde-fous.
- **A9 (m) Pas de règle de sortie réseau** (NetworkPolicy en entrée seulement) ; `filesystem` est ouvert sur
  tout `~/work`, donc sur les autres projets.

### B. Distribution des outils

- **B1 (G) ✔ `outils` d'un agent n'est pas une liste fermée.** Le schéma dit « liste fermée » ; l'implémentation
  écrit seulement une règle `permissions.allow`. Les outils hors liste restent visibles, et ne sont refusés que
  parce qu'un agent lancé n'a personne à qui demander. Le défaut `Read, Glob, Grep` donne l'illusion d'un agent
  en lecture seule ; en `acceptEdits`, il écrit.
- **B2 (G) Le serveur `atelier` est irretirable.** Il n'existe aucun profil « Onyxia sans Atelier ».
- **B3 (M) Pas de profil par projet ni par agent.** Trois leviers disjoints (connecteurs, déploiement, mode).
- **B4 (M) Une liste de connecteurs incomplète retire `wikichat` et `chrome` sans avertissement**, alors que les
  consignes en dépendent.
- **B5 (M) Des outils déclarés à l'Assistant échouent toujours** : `atelier_artefact_creer` et
  `atelier_navigateur_ouvrir` lui sont refusés (il n'écrit pas de fichiers), mais restent dans sa liste et son
  schéma.
- **B6 (M) Les consignes et le contexte généré décrivent plus que la configuration effective** : navigateur,
  wikichat, `WebSearch`, outils Onyxia annoncés même sans `exec`, `projet` « à passer » alors que le profil code
  ne le lit pas.
- **B7 (m) Les profils de passerelle perdent leur liste blanche** quand on les traduit en outils d'agent.

### C. Supervision par l'Assistant

- **C1 (G) Aucun retour automatique.** Un agent fini, en erreur ou bloqué n'est vu que si la personne parle à
  l'Assistant ou s'il interroge `atelier_lancements`. Il n'y a ni message de fin de lancement, ni hook
  orienté vers lui.
- **C2 (G) Le suivi en direct n'est pas annoncé à l'Assistant** (`atelier_suivre`, `_transcript`, `_envoyer` sont
  « hors liste ») et `atelier_suivre` ne voit que les tours lancés depuis son propre canal.
- **C3 (M) Un message envoyé pendant un tour attend la fin du tour**, jusqu'à 45 minutes, et la file est vidée si le
  tour tombe en erreur.
- **C4 (M) Le guetteur de wikichat** (réveil après le tour) n'est pas mesuré avec les processus gardés : une
  réponse hors tour pourrait être perdue.
- **C5 (M) Un agent lancé ne peut pas lancer de commandes utiles** (tests, installation) sans `bypass`.

### D. Compositions

- **D1 (G) Une étape `approval` ou `elicit` peut être validée par le modèle lui-même** (`gateway_resume_composition`
  accepte n'importe quelle réponse ; `allowed_roles` n'est jamais vérifié) et l'Atelier ne monte aucune route de
  réponse humaine.
- **D2 (G) Un run ne mémorise ni la session ni le profil** : repris, il continue sous les droits de celui qui
  reprend.
- **D3 (M) N'importe quel brouillon s'exécute** ; la promotion ne conditionne que l'exposition en outil.
- **D4 (M) Aucune boucle, condition, retry** ; aucun point de reprise, délai d'étape ni annulation effective ;
  `wait_until` et `ttl_seconds` sont inertes ; pas de limite de récursion.
- **D5 (M) L'écran ne peut pas créer d'étape `elicit`**, et l'assistant ne sait créer que des étapes `tool` aux
  identifiants déformés par les accents.
- **D6 (M) Découvrabilité** : recherche lexicale sans lemmatisation, aucun mot-clé renseigné pour un connecteur
  ajouté, descriptions lisibles non utilisées par la recherche. `wikichat` n'est pas déclaré par défaut dans le pool
  en production ; `Onyxia` n'est jamais déclaré par l'Atelier.

### E. Fiabilité des outils (les échecs mesurés)

- **E1** `atelier_lancer_agent` : la confirmation en deux temps (aperçu, puis rappel avec `confirmation`) est mal
  comprise : 7 appels sur 19 échouent sur un jeton « donné pour d'autres arguments ».
- **E2** Onyxia : `read_file` et `write_file` plantent en `KeyError` quand `session_id` manque ; `push_repo`
  reçoit un chemin local au lieu d'une URL git. Ce sont des défauts du connecteur Onyxia (hors de ce dépôt) et
  de ce que l'agent est invité à faire (aucun mode d'emploi du connecteur dans son contexte).
- **E3** `gateway_call_tool` : le méta-outil est mal utilisé (`name` oublié) ; son schéma et son erreur
  n'orientent pas assez.
- **E4** `atelier_artefact_creer` : créer une page est une action de base ; elle ne doit jamais échouer pour une
  raison évitable (`existe déjà`, `projet et nom requis`).

## 4. Cadre cible

### Principes

1. **Le profil est une donnée, pas du code.** Un profil nommé dit : outils de l'Atelier, connecteurs, natifs
   refusés, accès Onyxia, niveau wikichat, mode de permission, plafonds.
2. **Trois niveaux de définition, du plus général au plus précis** : défaut du service → profil du projet → profil
   d'un agent ou d'un lancement. Le plus précis ne peut que **restreindre** (jamais élargir au-delà du projet).
3. **Moindre privilège par défaut, élargissement explicite et tracé.** Un agent reçoit ce que son profil dit, rien de
   plus.
4. **Ce que l'agent croit = ce qu'il a.** Son contexte (`CLAUDE.md`), ses consignes et les descriptions d'outils sont
   **générés depuis la configuration effective**, pas écrits à part.
5. **La frontière est technique, pas déclarative.** Les accès se prouvent par un jeton, pas par un en-tête que
   l'agent peut omettre.
6. **L'agent sait ce qu'il fait et ce qu'il obtient.** Les actions de base (créer une page) ne peuvent pas échouer
   pour une raison évitable ; un échec dit quoi faire ensuite.

### Profils nommés proposés

| Profil | Pour qui | Atelier | Connecteurs | Onyxia | Réseau/natifs |
|---|---|---|---|---|---|
| `local` | travail dans le projet, pages et applis locales | artefacts, montrer | aucun (ni wikichat) | non | pas de WebFetch |
| `code` (défaut actuel) | développement courant | 10 outils du projet | wikichat, chrome, + choisis | seulement si `deploiement` | tous sauf WebSearch |
| `code-onyxia` | projet déployé sur un pod | 10 outils, ou aucun | wikichat, chrome | borné au pod/service/GPU du projet | idem |
| `lecteur` | analyse, audit, rapport | lecture seule | wikichat | non | pas d'écriture |
| `mainteneur` | modifier l'Atelier (voir §6) | 10 outils, sur branche | wikichat | **non** | pas de GitHub en écriture |
| `superviseur` | l'Assistant | 41 + suivi live | wikichat complet, Onyxia complet hors `expose_*` | oui, sans exposition publique | notes seulement |

Un projet choisit son profil par défaut ; un agent ou un lancement peut en choisir un plus étroit. La possibilité
« Atelier sans Onyxia » existe déjà (pas de `deploiement`) ; « Onyxia sans Atelier » et « local » sont nouveaux.

### Où ça se décide

- `.atelier/projet.json › profil` (nom) et `› outils` (surcharges qui restreignent), lus par `profil_effectif`, le
  fichier MCP de la conversation, `--settings` et le contexte généré. Une commande engageante la pose.
- Un agent du Pilote et un lancement portent un champ `profil` et, au besoin, `outils` — **appliqués pour de vrai** :
  fichier `--mcp-config` propre à l'agent, `--allowedTools` et `deny` des natifs non listés, plutôt qu'une simple
  pré-autorisation.
- L'Assistant décide, par commande engageante, du profil d'un projet et de celui d'un agent qu'il crée.

### Faire tenir la frontière

- **Un jeton par conversation**, signé, portant profil et projet, à la place de la clé propriétaire dans le fichier
  MCP. Les points d'entrée (`/mcp`, `/mcp/onyxia[…]`) lisent le profil **dans le jeton**, pas dans un en-tête.
  Cela ferme A2 et A3 d'un coup, et rend les accès révocables.
- **Les secrets sortent de l'agent** : ni clé propriétaire ni jeton GitHub dans l'environnement du tour ; lecture de
  `~/work/.secrets/` refusée ; variables retirées des sous-processus. Pour une vraie isolation, un utilisateur
  Unix distinct ou un cloisonnement du processus de l'agent.
- **« Réservé » se vérifie dans la passerelle**, pas seulement dans le mandataire.
- **La confirmation « Oui » est vérifiée par le code** : un jeton d'aperçu ne se consomme que par une réponse de
  l'interface de la personne, pas par le même modèle.
- `atelier_envoyer` devient engageante hors des conversations que l'Assistant a lancées lui-même.

### L'Assistant superviseur

Boucle visée : **déléguer → suivre → recevoir → piloter → rendre compte**.

1. *Déléguer* : `atelier_lancer_agent` (aperçu confirmé par la personne), avec le profil voulu.
2. *Suivre* : `atelier_suivre` / `_transcript` déclarés, et visibles pour **tous** les lancements (pas seulement
   ceux de son canal).
3. *Recevoir* : à la fin d'un lancement, un message wikichat `done` adressé à l'Assistant, et un récapitulatif
   `lancements-recents` rafraîchi avec la carte ; le hook `UserPromptSubmit` de wikichat est le vecteur.
4. *Piloter* : `atelier_envoyer` (engageante), `atelier_interrompre`, `atelier_decider`.
5. *Rendre compte* : le carnet de bord et « À valider ».

### Aucune erreur évitable sur les actions de base

- `atelier_artefact_creer` devient **idempotent** : si la page existe, il le dit et rend son adresse ; `nom` a un
  défaut tiré de la demande ; le message d'erreur dit toujours la suite.
- Les outils qu'un profil ne peut pas utiliser **ne sont pas dans sa liste** (retirer `artefact_creer` et
  `navigateur_ouvrir` de l'Assistant).
- Le contexte généré liste les outils réels du profil, et un mode d'emploi **par connecteur** (Onyxia : « appeler
  `session_start`, passer `session_id` à chaque outil » ; `push_repo` : « une URL git, jamais un chemin »).
- `gateway_call_tool` : schéma et erreur orientés (« donnez `name` : voici les noms proches »).
- `atelier_lancer_agent` : l'aperçu dit en une phrase « rappelez avec la même demande et `confirmation=…` ».

### Compositions

Ordre : **sécurité** (mémoriser session et profil dans le run, appliquer `allowed_roles`, réserver la reprise d'un
`approval` à la personne, exiger `production` pour exécuter, routes humaines de statut, reprise et abandon),
**ergonomie** (étape `elicit` dans l'écran, identifiants d'étape stables, `isError` sur échec), puis **boucles**.

Boucles : types additifs `for_each`, `until`/`while`, `when`, `branch`, `retry` ; `max_iterations` **obligatoire**
et plafond dur global ; plafonds de run (étapes, appels, durée, taille d'état) ; délai effectif par appel ;
annulation coopérative avec écriture conditionnelle ; point de reprise par étape et par itération ; grammaire
d'expressions fermée, sans `eval` ; interdiction de la récursion ; chaque itération repasse par le garde de profil
de l'appelant ; journal d'événements par étape. Le schéma détaillé et ses contraintes sont dans l'analyse de la
passerelle ; il reste à le confronter à bigmcp, non lu ici.

Découvrabilité : mots-clés français pour chaque connecteur, descriptions lisibles et libellés utilisés par la
recherche, `wikichat` et `Onyxia` déclarés par défaut dans le pool.

## 5. L'Atelier qui s'améliore lui-même

C'est faisable avec ce qui existe, **à condition de fermer d'abord A1, A2, A3, A8** : tant qu'un agent peut lire
la clé propriétaire et le jeton GitHub, tout cadre de sécurité se contourne.

### Ce qui existe déjà et sert de cadre

Agent sur branche `agent/…` dans une copie de travail, crochets git (`pre-push` refuse tout envoi, un seul nom de
branche), règles du CLI refusées (`push`, `merge`, `rebase`, `reset --hard`), plafonds (3 simultanés, 900 s par
défaut, 1 800 s au plus), fin de tour vérifiée par le code (base intacte, commits, écart), proposition dans « À
valider », fusion locale réservée à la personne, journal. Gardiens avec gestes en liste fermée.

### Ce qui manque

Aucun projet `atelier` n'existe sur le pod ; le dépôt n'est pas structuré ; le réparateur de `sante.ci-main`
est déclaré sans projet ; `chemins_proteges` n'est pas appliqué ; `plafonds.jetons` est lu mais jamais appliqué ;
rien n'empêche de fusionner une PR dont les tests échouent ; pas de rollback d'une image cassée ; le code en service
est modifiable à chaud et un correctif à chaud est perdu au redémarrage.

### Le cadre proposé

- Un projet `atelier` structuré, profil **`mainteneur`** : agent code sur branche, sans Onyxia, sans GitHub en
  écriture, `acceptEdits`, jamais `bypass`, 20 à 30 minutes, une copie à la fois.
- Étapes : demande (aperçu confirmé) → branche et copie de travail → tests (`projet.json › commandes.tests`) →
  commits → proposition dans « À valider » → **relecture humaine du diff**, avec vigilance sur les fichiers de
  garde-fous → fusion locale (réservée) → la personne pousse, ouvre la PR, ne fusionne que si les tests sont verts →
  l'image se construit → la personne redémarre le pod.
- **Chemins protégés** appliqués par un hook (`PreToolUse`) : profils, catalogue, passerelle, mandataire Onyxia,
  lanceur, harnais, gardiens, `.github/`, chart, `deploy/`, `install/`, socle. Les modifier relève d'un lot
  ouvert explicitement par la personne.
- **Protection de `main`** sur GitHub : tests obligatoires, revue obligatoire, pas de push direct. C'est la seule
  barrière qui tient même si un agent avait un jeton.
- Le test d'import de l'image passe **avant** le push de `latest`.
- **Aucun projet ne peut déclarer le pod de l'Atelier** comme déploiement.
- Supervision : l'Assistant propose et suit le lancement, refuse une proposition, ne l'accepte jamais ; le gardien
  de cohérence détecte une dérive de profil ou de hooks après déploiement.
- Réservé à la personne : fusion, envoi vers GitHub, PR, redémarrage, accord d'un connecteur, déclaration d'un
  déploiement, exposition publique, `bypass`.

## 6. Ordre de réalisation

| Lot | Contenu | Effort | Dépend de |
|---|---|---|---|
| 1 | **Frontières** : secrets hors de l'agent, jeton par conversation, « réservé » dans la passerelle, `atelier_envoyer` engageante, pod de l'Atelier non déclarable, confirmation vérifiée | élevé | — |
| 2 | **Fiabilité d'usage** (rapide, forte valeur) : artefact idempotent, outils inutilisables retirés de la liste de l'Assistant, contexte généré depuis la config effective, mode d'emploi par connecteur, schéma de `gateway_call_tool`, aperçu de lancement clarifié, consignes corrigées | faible à moyen | — |
| 3 | **Profils nommés** par projet, agent et lancement, appliqués pour de vrai (`outils` fermé), « Onyxia sans Atelier », profil `local` | élevé | 1 |
| 4 | **Supervision** : suivi live déclaré, retour automatique de fin de lancement, hooks `Stop`/`UserPromptSubmit` de l'Atelier, `garde_bash` posé aussi au démarrage de l'Atelier et en échec fermé | moyen | 2 |
| 5 | **Compositions** : sécurité d'abord, ergonomie, boucles, portée projet, découvrabilité, `wikichat`/`Onyxia` déclarés par défaut | élevé | 1, 3 |
| 6 | **Mainteneur de l'Atelier** : projet `atelier`, chemins protégés, protection de `main`, plafond de jetons, image testée avant `latest` | moyen | 1, 3 |

Le lot 2 peut partir tout de suite et ne dépend de rien. Le lot 1 est le prérequis de tout le reste.

## 7. Décisions à prendre

1. Isolation des secrets : jeton scopé par conversation **et** utilisateur Unix distinct pour les agents, ou jeton
   scopé seul pour commencer ?
2. L'Assistant garde-t-il Onyxia complet, ou passe-t-il `exec`, l'arrêt de service et le déploiement d'un autre
   service en « engageant » ?
3. Les profils nommés : la liste du §4 convient-elle ?
4. Le mainteneur de l'Atelier : on l'ouvre après les lots 1 et 3, ou plus tôt, en lecture seule (propositions de
   correctif sans exécution) ?
5. Compositions : on aligne les boucles sur bigmcp ; il faut me donner accès à ce projet, ou son schéma.

## 8. Limites de cet audit

- Le code de wikichat n'est pas dans ce dépôt : le contenu réel de ses hooks, la liste exacte de ses outils par
  profil et leur comportement en cas d'indisponibilité sont **non vérifiés**.
- « bigmcp » n'a pas été lu : le schéma de boucles repose sur le moteur actuel et des principes d'ingénierie.
- Vérifié par moi : les secrets dans l'environnement du service et dans `~/work/.secrets/` ; `outils` d'un agent
  écrit seulement une règle `allow` ; « réservé » n'est cité que dans le mandataire Onyxia ; les chiffres d'usage.
  Les autres points viennent de la lecture du code par des analyses séparées.
- Non vérifié sur le pod : le contournement de `expose_public` par la passerelle, un déploiement visant
  `atelier-0`, l'effet de `asyncRewake` en mode `-p`.
