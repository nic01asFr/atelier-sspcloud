# Attendre sans refuser : veille, notifications, PWA et cadre des rôles

Conception du 11/10, posée avec Nicolas. Elle répond aux cinq questions du
[registre des défauts](registre-des-defauts.md) § 9 et fixe la forme du Lot 1.

## 1. Ce qui est décidé

| Question | Décision |
|---|---|
| Notifications et retour de la personne | **L'Atelier est une PWA** : notifications directes, avec la réponse possible depuis la notification elle-même. Réglages faciles, clairs, grand public. |
| Permission sans réponse | **Pas de refus.** On attend, on prévient, on met en veille, et la reprise est **toujours** possible. |
| Lectures et commandes à autoriser d'office | Cadrées **par rôle**, en regardant la logique des agents de projet, de l'Assistant, des sessions, de la passerelle, des profils, des compositions et des outils (§ 6). |
| Projets d'essai (`projet-sans-nom*`) | Regarder à quoi ils correspondent réellement, les **renommer et les rattacher** quand c'est possible (§ 7). |
| Lot 1 | Procéder, de façon optimale et fiable, une fois les enjeux compris (ce document). |

## 2. Ce qui existe (vérifié dans le code)

- **Une attente vive et une trace.** `decisions.py` : la question est écrite sur
  le disque à l'instant où elle est posée ; le processus garé attend ; après
  `attente_vive_max_s` (3 600 s) on le libère pour rendre ses ~130 Mo.
- **Mais le tour reçoit alors un refus** (`harness.py:925-933`) : « Personne n'a
  répondu à temps… ». C'est ce texte qui fait conclure à l'agent que l'outil est
  en panne. Et répondre plus tard **retient la règle sans reprendre le tour**
  (`api.py:1886-1891` : `reprise: false`).
- **Les tours sans interlocuteur sont refusés d'emblée** (`peut_attendre=False`,
  `harness.py:881-897`) : agents lancés non supervisés, client distant
  (claude.ai), route bloquante.
- **Une mise en veille existe déjà dans un autre cas** : quand le contexte
  devient trop lourd, `sessions._send` compacte puis **rejoue un message de
  reprise** (`sessions.py:1682-1720`). La reprise automatique d'un tour est donc
  un geste que le code sait faire.
- **Les compositions font déjà « suspendue → prévenue → reprise »** : une
  composition qui attend une approbation déclenche `prevenir(...)`
  (`compositions/service.py:605`). C'est la même logique que celle visée ici.
- **Le code d'envoi des notifications existe** (`notifications.py` : paire VAPID,
  abonnements, `pywebpush`, nettoyage des abonnements morts, jamais bloquant).
- **Mais il n'est pas branché dans l'Atelier** : pas de routes `/push`, pas de
  service worker, pas de manifeste PWA, et `pywebpush` n'est pas dans les
  dépendances (`pyproject.toml`) — l'image ne l'installe pas, donc l'envoi
  s'arrêterait en silence (`notifications.py` : « pywebpush absent »).
- **L'authentification de navigation** est un cookie de session révocable, sans
  pouvoir propre (`auth.py`) ; la clé propriétaire reste lisible par les agents
  du pod (limite connue, D1).

## 3. Le principe

> **Une question à la personne n'est jamais un refus.**

Trois issues possibles pour toute action qu'un agent veut faire, et trois seulement :

1. **Autorisée d'office** : le rôle l'a prévu. Elle passe, sans bruit.
2. **À demander** : on pose la question, on **prévient la personne**, l'agent
   **dort** sans rien savoir d'un refus, et **la réponse relance le travail
   là où il en était**.
3. **Interdite** : jamais, quel que soit le mode. Le refus dit **pourquoi et quoi
   faire à la place** (déposer l'action dans « À valider », ou la commande
   Atelier exacte).

Le refus sans issue (« Personne n'a répondu ») disparaît. Un refus qui reste est
un vrai refus, avec sa raison.

## 4. Veille et reprise

### 4.1 Les états d'une question

```
posée ──(réponse < délai)──────────────────────────► rendue au CLI, le tour continue
  │
  └─(pas de réponse après `veille_apres_s`)──► en veille
         │   le processus est arrêté, le tour s'achève proprement,
         │   la conversation affiche « en attente de vous », la question reste
         │   dans « À décider », la personne a été prévenue
         │
         └─(réponse, à tout moment, même après un redémarrage)──► reprise
                 un nouveau tour part avec `--resume`, avec un message de reprise
                 écrit par l'Atelier ; une autorisation « pour cette fois » est
                 déposée pour que l'action relancée passe sans reposer la question
```

- **Délai de veille** : `veille_apres_s`, 600 s par défaut (les 3 600 s actuels
  gardent un processus de 130 Mo pour rien ; sans zone d'échange sur le pod,
  c'est cher). Réglable. Tant que le délai n'est pas écoulé, rien ne change : la
  réponse est rendue au processus garé, sans rejouer.
- **Mise en veille** : le tour **ne reçoit aucune réponse**. On arrête le
  processus (`_eteindre(de_force=True)`) et on rend le tour avec un événement
  `veille`. Aucun refus n'atteint le modèle, donc aucune fausse conclusion.
- **Fiche de la conversation** : un champ `en_attente_de` (identifiant de la
  question). L'état reste `idle` (aucun écran existant ne casse) ; l'interface
  affiche « en attente de vous » à partir de ce champ.
- **Reprise** : `POST /v1/decisions/{id}` sur une question sans tour vivant
  (veille **ou** redémarrage du service) rend `reprise: true` et lance un tour
  en arrière-plan. Ses événements partent sur le flux en direct de la
  conversation (`diffusion.publier`), que l'interface écoute déjà.
- **Message de reprise** (écrit par l'Atelier, jamais par l'agent, jamais à
  recomposer par la personne) :
  - *autorisée* : « Tu attendais l'autorisation de la personne pour
    `<Outil>` `<résumé>`. Elle est accordée. Relance exactement cette action. »
  - *refusée* : « La personne a refusé `<Outil>` `<résumé>` : `<motif>`. Ne la
    relance pas ; dis ce que tu fais à la place, ou ce qu'il te manque. »
  - *question* : « La personne a répondu à ta question : … »
- **Autorisation pour cette fois** : une règle à usage unique, portée par
  l'outil et ses arguments exacts. Elle n'est **pas** passée au CLI par
  `--settings` (elle ne vaut qu'une fois) : la question est reposée au pont, qui
  la reconnaît, répond « autorisé » et **consomme** la règle.
- **Si l'agent relance autre chose** : la nouvelle question repart au même
  circuit. Rien de perdu, rien de refusé.
- **Si la personne écrit un message pendant la veille** : il part normalement,
  précédé d'une ligne « Une autorisation attend toujours : … ». La question
  reste ouverte.
- **Plafond de durée d'un agent lancé** : le temps de veille ne compte pas
  (déjà le cas pour l'attente vive : `_attendre_la_decision` rend le temps passé
  pour prolonger l'échéance).
- **Les tours sans interlocuteur** (agents lancés non supervisés, client
  distant) ne sont plus refusés : ils attendent, dorment et reprennent comme les
  autres. Un lancement dont l'agent dort est **« en attente de vous »**, jamais
  « fini » (registre D-09). Les lancements **supervisés** gardent leur circuit :
  le lanceur décide dans son périmètre (`atelier_decider`) ; au-delà, c'est la
  personne.
- **Journal** : chaque étape est écrite (posée, notifiée, en veille, répondue,
  reprise) avec l'acteur réel de la réponse.

### 4.2 Pourquoi c'est sûr

- La trace sur disque existe déjà et survit au redémarrage. La reprise ne
  *rejoue* rien : elle demande à l'agent de relancer **une** action, après sa
  dernière réponse enregistrée, avec `--resume`. Si l'agent avait enchaîné
  d'autres appels en parallèle, ils sont simplement reposés s'il les relance.
- Une question n'est jamais accordée d'avance ; une règle « toujours » reste
  celle que le CLI a lui-même suggérée.
- La règle à usage unique est liée à la conversation, à l'outil et aux
  arguments exacts, et se consomme : elle ne devient pas une permission durable.

## 5. Notifications et PWA

### 5.1 Ce que voit la personne

- **Installer l'Atelier** : une invitation simple (« Ajouter à l'écran d'accueil »),
  sur téléphone comme sur ordinateur. Sur iPhone, c'est la condition pour recevoir
  des notifications : l'écran l'explique en une phrase.
- **Une notification, trois formes** :
  - *Une action attend* : « Réparateur · veut lancer `pip install torch` »
    → boutons **Autoriser** · **Refuser** (sur Android et ordinateur ; sur iPhone,
    un toucher ouvre la carte de décision).
  - *Une question* : « Assistant vous demande : … » → un toucher ouvre la
    question (on ne répond pas à une question à l'aveugle).
  - *Un travail est terminé ou bloqué* : « atlas-grist · agent terminé » /
    « bloqué : il lui manque X ».
- **Elle se referme toute seule** quand on a répondu ailleurs (même `tag` : la
  même notification est remplacée par « Autorisé » puis disparaît).
- **Réglages (Réglages → Notifications)**, en langage courant :
  - un interrupteur **« Me prévenir sur cet appareil »** (c'est lui qui demande
    la permission au navigateur, jamais au chargement de la page) ;
  - des cases : *Une action attend mon accord* (cochée) · *Une question m'est
    posée* (cochée) · *Un agent a terminé* · *Un agent est bloqué* (cochée) ·
    *Une alerte grave de surveillance* (cochée) ;
  - **Heures calmes** : de-à, pendant lesquelles on ne sonne pas (les demandes
    restent en veille et la notification part au matin) ;
  - un bouton **« Envoyer un essai »** qui dit honnêtement le résultat (« reçu
    sur 1 appareil » / « aucun appareil atteint : voir ci-dessous ») ;
  - la liste des appareils, chacun avec « Retirer ».

### 5.2 Architecture

- **Serveur** : un module `push.py` qui s'appuie sur `notifications.py`
  (VAPID, abonnements, envoi). Routes `/v1/push/cle-publique`,
  `/v1/push/abonnements` (POST, DELETE), `/v1/push/preferences` (GET, PUT),
  `/v1/push/essai`. Les préférences vivent dans la base de l'Atelier.
- **Quand l'Atelier prévient** : un `notifier` branché sur les événements déjà
  émis — `decision_attendue` (immédiat), mise en veille, fin et blocage d'un
  lancement, alerte grave des gardiens. Il ne lève jamais : une notification qui
  échoue ne fait pas échouer ce qu'elle annonce.
- **Jeton de décision, à usage unique** : la charge de la notification contient
  `request_id`, une expiration et une signature HMAC (secret du service). Le
  service worker l'envoie à `POST /v1/decisions/{id}/notification` : la route
  n'accepte **que ce jeton** et **que ce geste** (autoriser / refuser **cette**
  question). Il ne donne aucun autre pouvoir, n'est jamais dans une URL, et ne
  sort que dans une charge chiffrée de bout en bout (RFC 8291) vers l'appareil
  de la personne. Le service worker ne détient donc ni cookie ni clé.
- **Service worker** (`/sw.js`, à la racine : sa portée couvre l'application) :
  affiche (`push`), répond aux boutons (`notificationclick`), ouvre ou focalise
  l'application sur la bonne carte, ferme une notification devenue sans objet.
  Il ne met **rien d'autre** en cache dans cette première version : pas de mode
  hors ligne à maintenir, donc pas de page périmée à servir.
- **Manifeste** (`manifest.webmanifest`) : nom, couleurs, icônes 192 et 512 px et
  « maskable », `display: standalone`, `start_url: /`.
- **Dépendance** : `pywebpush` ajouté à `pyproject.toml`. Sans lui, l'interface le
  dit (« notifications indisponibles sur ce service ») au lieu d'échouer en silence.

### 5.3 Ce qui ne peut pas être vérifié ici

L'envoi réel dépend de la sortie du pod vers les services de poussée (FCM,
Mozilla, Apple). Je le teste par le bouton « Envoyer un essai » sur le pod, pas
dans ce bac à sable. Dans le bac à sable je vérifie : le chiffrement et la
charge (envoi simulé), les routes, le jeton (signature, expiration, usage
unique), le service worker (événement `push` simulé par DevTools), le manifeste
et l'installabilité.

## 6. Cadre des rôles : qui peut quoi, sans y penser

Un seul mot d'ordre : **chaque rôle a une liste « d'office », une liste « à
demander » et une liste « interdite »**, écrites **une fois** (c'est le futur
`roles.py` du Lot 2) et compilées vers les mécanismes natifs de Claude Code
(`allow` / `deny`, `--tools`, `--mcp-config`, hooks). L'agent ne les lit nulle
part ; la personne ne les configure pas.

### 6.1 Les rôles, tels qu'ils existent dans le code

| Rôle | Où il naît | Qui répond à une question |
|---|---|---|
| **Agent de projet** (profil `code`) | une conversation d'un projet | la personne |
| **Assistant** (profil `assistant`) | `kind = assistant` | la personne |
| **Agent lancé, supervisé** | `atelier_lancer_agent(supervise=true)` | le lanceur dans son périmètre (`atelier_decider`), la personne au-delà |
| **Agent lancé, non supervisé** | `atelier_lancer_agent` | la personne (veille + notification) |
| **Gardien / réparateur** | `gardiens/` | la personne ; gestes réversibles listés |
| **Client distant** (claude.ai) | porte `/mcp` sans conversation | la personne |
| **Sessions VS Code et terminal** | `X-Atelier-Conversation` inconnu | la personne, dans l'outil lui-même |
| **Compositions** | passerelle | la personne (approbation) — déjà en veille + notification |

### 6.2 La grille commune

**D'office, pour tous les rôles** (lecture et local : rien qui sorte ou qui
détruise) :

- outils natifs de lecture (`Read`, `Glob`, `Grep`, `LS`) dans le projet et sa copie ;
- `Bash` en lecture ou local, y compris composé (`;`, `&&`, `|`, `2>/dev/null`,
  `git -C`) : `ls`, `cat`, `wc`, `find` (sans `-delete` ni `-exec`), `git status`,
  `git log`, `git diff`, `sqlite3` en lecture seule, `curl` sur `127.0.0.1` et sur
  les ports du projet, `python -m venv` et `pip install` **dans le `.venv` du projet** ;
- outils MCP de lecture : `list_pods`, `session_status`, `list_files`,
  `gpu_status`, `read_file`, `atelier_carte`, `atelier_fiche`, `atelier_rappel`…

**À demander (veille + notification), pour tous** :

- toute sortie réseau vers un hôte nouveau, tout `pip` / `npm` / `apt` hors du
  `.venv` du projet ;
- `git push`, écrire hors du projet, supprimer en masse ;
- les outils Onyxia qui agissent (`exec` qui écrit, `session_start`, `gpu_switch`) ;
- les commandes « engageantes » de l'Atelier (lancer un agent, déclarer un
  déploiement…).

**Interdit, avec la voie de sortie** :

- lire ou écrire `.secrets/`, `.env*`, la clé propriétaire → « accorde le
  connecteur dans l'interface : l'Atelier le fournit sans que tu en voies la valeur » ;
- `pkill -f` non ancré, écoute sur `0.0.0.0`, `kubectl` (le compte n'a pas le
  droit) → le motif ;
- `expose_public` (réservée à la personne) → **l'Atelier dépose lui-même la
  proposition dans « À valider »**, l'agent n'a rien d'autre à faire ;
- sortir de son périmètre (agent lancé), ou agir sur un autre projet que le
  sien → « passe par les agents de ce projet ».

### 6.3 Ce qui change d'un rôle à l'autre

| Rôle | Écrire dans le projet | Autres outils MCP | Particularités |
|---|---|---|---|
| Agent de projet | d'office | ceux de son projet (créations, `montrer`, navigateur, mémoire du projet), Onyxia seulement via son déploiement | profil `code` filtré à la source |
| Assistant | dans son dossier d'office ; ailleurs, déléguer | tout l'Atelier + passerelle + wikichat | confirmation des commandes engageantes ; pas de lecture de secrets |
| Agent lancé | dans **sa copie** d'office, jamais ailleurs | ceux du lancement (la liste figure dans l'aperçu) | périmètre du lanceur ; plafonds ; **avertissement à l'aperçu** si la mission cite des chemins hors de la copie ou des outils qu'il n'aura pas |
| Gardien / réparateur | seulement les gestes de la liste | lecture | tout le reste est à demander |
| Client distant | non (pas de dossier) | selon profil annoncé | sans conversation : tout, **mais** journalisé ; à restreindre |
| VS Code / terminal | selon son mode | comme l'agent de projet | le mode vient du projet (`modes_permission`) |

### 6.4 Comment ça se compile

- Les listes « d'office » deviennent `permissions.allow` ; les « interdites »,
  `permissions.deny` (qui l'emporte même en `bypassPermissions`) ; le reste est
  « à demander » et passe par le pont (le CLI pose la question, l'Atelier la
  tient, prévient, endort et reprend).
- Pour les agents lancés, le mode `dontAsk` + liste devient possible **parce
  qu'on ne refuse plus** : ce qui n'est pas d'office n'est pas écarté, c'est
  demandé. À valider sur le pod avant de s'y appuyer (§ 7 de l'état des lieux).
- Les refus portent leur raison et leur voie de sortie, produites par le pont
  et les hooks, pas par une consigne.

## 7. Projets d'essai

Procédure, par projet : (1) lire son contenu (conversations, créations,
`ETAT.md`, lancements) ; (2) nommer ce qu'il est réellement ; (3) rattacher au
bon projet quand il en existe un (par exemple le travail GP2OA de
`projet-sans-nom-8` vers `gp2oa-grist`) ; (4) sinon **renommer** par un titre
lisible ; (5) ranger les essais purs. Rien n'est supprimé. Chaque changement est
écrit dans le journal de l'Atelier (donc annulable). Le travail est fait **projet
par projet** et le tableau avant/après est rendu à la personne.

## 8. Ordre de réalisation

1. **Veille et reprise** (§ 4) : le cœur. Tests : durée, redémarrage, refus,
   question, règle à usage unique, message pendant la veille, lancement non
   supervisé.
2. **Notifications côté serveur** (§ 5.2) : routes, préférences, jeton de
   décision, branchement sur les événements, dépendance.
3. **PWA côté interface** (§ 5.1) : manifeste, service worker, réglages,
   invitation à installer, carte « en attente de vous ».
4. **Cadre des rôles** (§ 6) : grille `allow` / `deny` par rôle, motifs et voies
   de sortie dans les refus, dépôt automatique dans « À valider » pour les
   actions réservées, avertissements à l'aperçu du lancement.
5. **Projets d'essai** (§ 7), en parallèle, par lecture puis renommage.

Chaque étape : tests écrits d'abord, suite complète (pytest et les deux suites
JS), PR, CI verte, fusion, vérification de l'image, redémarrage du pod s'il n'y
a aucune conversation en cours, essai réel.

## 9. Ce que cette conception ne règle pas

**La confirmation des commandes engageantes (registre D-02)** : tant que la clé
propriétaire est lisible par les agents, un agent peut présenter lui-même la
« confirmation ». La notification apporte un **canal humain réel** (jeton chiffré
vers l'appareil, limité à une question), mais fermer la faille demande de séparer
la clé des agents de celle de la personne (D1). C'est un changement
d'authentification : il fait l'objet d'une proposition séparée, **soumise à
Nicolas avant tout code**.
