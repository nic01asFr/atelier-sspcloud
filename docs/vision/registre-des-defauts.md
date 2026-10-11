# Registre des défauts de l'Atelier — relevé du 11/10

Ce document note **tous les défauts relevés à ce jour** et en tire une synthèse.
Il complète [`etat-des-lieux-et-roles.md`](etat-des-lieux-et-roles.md) (où en est
chaque fonction, et le plan par rôle) : ici, on ne décrit pas ce qui marche, on
dresse la liste de ce qui ne marche pas, avec la preuve et la zone de code.

## 1. D'où viennent ces constats

| Source | Ce qui a été lu |
|---|---|
| Revue de code du 03/10 et revue par matrice | les failles et les manques déjà relevés ; ceux qui sont corrigés sont au § 5 |
| Essais sur le pod (octobre) | gardiens, Onyxia, lancements, déploiement |
| **Étude du 11/10** | 5 relecteurs en lecture seule sur ~110 conversations réelles, 21 lancements, le journal depuis le 27/09, la file « À valider », les fiches et les transcripts |

**Comment lire la colonne « Statut »**

- **vérifié** : j'ai relu le code et le défaut y est.
- **rapporté** : vu dans les données par un relecteur, la cause n'est pas encore confirmée dans le code. À vérifier avant de corriger.
- **corrigé** : déjà livré (§ 5).

**Limites de l'étude.** Les outils de lecture de l'Atelier ne rendent que la fin
des longs transcripts, et ne montrent pas les appels Onyxia. Une partie des
causes est donc une hypothèse. Tous les agents observés tournent sur des modèles
`qwen3-*` (fenêtre 131 k), pas sur Claude : une part des défauts de
raisonnement vient du modèle, pas de la plateforme (marqués « modèle »). Je n'ai
pas pu ouvrir l'interface réelle du pod (voir § 7).

## 2. Synthèse : sept causes qui expliquent presque tout

1. **Une permission sans réponse bloque une heure, et ne dit rien.** C'est le
   défaut le plus répété (au moins 12 conversations, dans les cinq rapports). Un
   agent lancé en `acceptEdits` demande une autorisation que personne ne voit ;
   au bout de `attente_vive_max_s` (3 600 s) il reçoit « Personne n'a répondu à
   temps ; la question reste posée dans l'Atelier » — sans nom d'outil, sans
   commande, sans « ne conclus pas que l'outil est en panne ». Les agents en
   concluent que le réseau est cassé, que l'installation échoue, que wikichat est
   bloqué. Et la question n'apparaît pas toujours dans « À valider ».
2. **La confirmation d'une action engageante n'est pas liée à la personne.**
   Le jeton est lié à la commande, aux arguments et à l'acteur, pas à un
   message humain. Un agent peut demander l'aperçu puis confirmer dans le même
   tour. C'est arrivé.
3. **Les fins de lancement mentent.** « fini » veut dire que le processus s'est
   arrêté, pas que le travail est livré. « arrêté » n'a ni motif ni acteur. Une
   conversation morte en erreur reste « idle ».
4. **Le contexte coûte cher et ne se met jamais en cache.** 35 à 38 k jetons
   dès le premier tour, `cache_read_input_tokens = 0` partout, jusqu'à
   440 $ cumulés pour une seule conversation.
5. **Les agents lancés dans une copie de travail n'ont pas de quoi travailler** :
   pas d'outils `atelier_*`, des missions qui citent des chemins hors de la copie,
   des créations invisibles pour `atelier_montrer`.
6. **La mémoire de nuit apprend de ce qui n'est pas la personne** : résumés de
   compaction, notifications d'application, refus automatiques de permission
   présentés comme « refusé par l'utilisateur ». Résultat : 49 propositions en
   attente, des doublons, des préférences inventées.
7. **Les gardiens voient mais ne réparent pas, et ne disent pas pourquoi.** 184
   relances de wikichat refusées, sans motif lisible ; des alertes qui
   clignotent ; une alerte secrets jamais refermée.

Une huitième, plus petite, traverse tout : **les messages d'erreur sont écrits
pour le code, pas pour l'agent ni pour la personne**. Ils n'indiquent pas quoi
faire ensuite.

## 2 bis. Le principe qui guide toutes les corrections

L'Atelier existe pour **intégrer les fonctions dans le harnais des agents**, de
sorte que l'ensemble fonctionne de façon intelligente et automatique : hooks,
indices (« hints »), contextualisation. Les services de l'Atelier participent aux
logiques sans que l'agent ait à y penser dans ses consignes, et sans que la
personne ait à le lui rappeler. Le bon fonctionnement et le respect des
contraintes viennent de la mécanique, pas de la bonne volonté du modèle.

Conséquence pour ce registre : **quand un défaut est « l'agent n'a pas su »,
la correction n'est pas une ligne de plus dans le CLAUDE.md.** On cherche
d'abord le point du harnais où l'Atelier voit l'événement et peut agir :

| Ce que l'Atelier voit | Le mécanisme natif | Ce que l'agent n'a plus à faire |
|---|---|---|
| un outil vient d'être refusé ou est resté sans réponse | indice ajouté au résultat de l'outil (le refus est produit par le pont de permissions de l'Atelier) ; `permission_denials` du résultat final relu au tour suivant | savoir que « refusé » veut dire « non vérifié » et non « vide » ou « en panne » |
| il s'apprête à lancer une commande risquée ou inutile | hook `PreToolUse` : refus motivé, avec la voie de sortie | connaître la liste des interdits |
| un outil rend un résultat énorme ou sensible | hook `PostToolUse` : troncature, masquage de `KEY` / `TOKEN` / `SECRET` | se méfier de ses propres sorties |
| une session démarre ou reprend | hook `SessionStart` : `additionalContext` avec les outils réellement disponibles, le pod, les ports, l'état du projet | deviner ce qu'il a, et le déclarer |
| la personne écrit | hook `UserPromptSubmit` : contexte utile à ce message | chercher ce que l'Atelier sait déjà |
| il veut conclure | hook `Stop` : bloque « vérifié » si la console a des 401, « fini » si rien n'est livré | s'auto-contrôler |
| un message n'est pas de la personne | marqueur d'origine dans le transcript (`isSynthetic`, `turnOrigin`) | n'a pas à faire la différence ; la mémoire non plus |

Ce que cela veut dire pour l'ordre : les défauts D-01, D-03, D-15, D-22, D-45,
D-46, D-48, D-50 et D-51 se règlent **au même endroit** — le pont de permissions
et les hooks du harnais — et pas un par un dans les consignes. C'est le Lot 1 du
plan (« voir ce que reçoit l'agent ») : le construire une fois résout la
famille.

## 2 ter. Et d'abord le natif de Claude Code

Les fonctions natives de Claude Code sont **structurantes pour l'Atelier et à
privilégier** : elles sont éprouvées, elles tiennent même quand le modèle se
trompe, et elles évitent de réécrire dans l'Atelier ce que le CLI fait déjà. La
règle : **on n'écrit du code Atelier que pour ce que le natif ne fait pas** — le
pont vers la personne (« À valider »), le registre des projets, le journal et la
preuve, le lien avec Onyxia et wikichat.

| Défaut | Ce que fait déjà le natif, à employer | Ce qui reste à l'Atelier |
|---|---|---|
| D-01 permission sans réponse | `permissions.allow` / `deny` par rôle + mode `dontAsk` : ce qui n'est pas autorisé est refusé **tout de suite**, plus d'attente d'une heure ; l'invite n'existe que pour les rôles supervisés | le pont humain, pour les seuls rôles où la personne répond |
| D-06 secrets, D-45 | `permissions.deny` (lecture de `.env*`, `.secrets/**`, `env`) dans les réglages **managed** : non contournable, le refus l'emporte même en `bypassPermissions` | le message qui dit quoi faire à la place |
| D-48 outils variables | `--tools`, `--allowedTools`, `--mcp-config` + `--strict-mcp-config` : la liste est exacte, et l'événement `system/init` la rend | la définition du rôle, compilée vers ces options (Lot 2) |
| D-15 copie sans outils | la config MCP passe par `--mcp-config` : elle ne dépend plus de fichiers suivis par git | la poser à chaque lancement en copie |
| D-45, D-46, D-50, D-51 | hooks `PreToolUse`, `PostToolUse`, `Stop`, `SessionStart` (contexte ajouté) | les scripts, versionnés avec l'Atelier |
| D-09 « fini » ≠ livré | `permission_denials` et `terminal_reason` du résultat final du CLI ; hook `Stop` / `SubagentStop` | les lire pour fixer l'état du lancement |
| D-14 mémoire | `isSynthetic` et `turnOrigin` dans le transcript | filtrer avec |
| D-41 coût et contexte | compaction automatique ; chargement des outils à la demande ; **préfixe stable** : tout ce qui change d'un tour à l'autre (réglages, contexte du moment) va à la fin, jamais en tête, sinon aucun cache ne peut jouer | le proxy du modèle doit accepter le cache de préfixe (côté Albert / LiteLLM, pas dans le CLI) |
| D-47, D-50 consignes longues | **skills** et **commandes** (`/verifier`, `/reprendre`…) : chargés à la demande au lieu de gonfler le CLAUDE.md à chaque tour ; **sous-agents** `.claude/agents/*.md` avec leurs propres outils | le kit K1–K4 (déjà au plan) |
| distribution aux rôles | **plugins** (`--plugin-dir`) : un rôle = un paquet de skills, d'agents, de hooks et de commandes | le paquet par rôle |

À confirmer sur la version du CLI du pod avant de s'y appuyer (déjà prévu en
§ 7 de l'état des lieux) : que les réglages **managed** s'appliquent en mode
`-p`, que `dontAsk` + liste suffit à la place de l'invite, ce que font les
sous-agents quand le parent refuse, et les options exactes de la version.
**Aucune de ces lignes n'est une promesse tant que l'essai n'est pas fait.**

## 2 quater. Trois couches qui jouent ensemble

Le natif, le harnais de l'Atelier et le contexte ne sont pas trois chantiers :
c'est **une seule chaîne**, alimentée par **une seule définition par rôle**.

1. **Le plancher natif** (réglages managed, `allow` / `deny`, `dontAsk`, liste
   d'outils) : ce qui est interdit l'est, même si tout le reste échoue.
2. **Le harnais de l'Atelier** (pont de permissions, hooks, indices dans les
   résultats) : il voit chaque événement, explique le refus, propose la voie de
   sortie, journalise.
3. **Le contexte** (injecté au démarrage et à chaque tour) : l'agent sait où il
   est, ce qu'il a, ce qui est déjà fait.

Exemple, le défaut le plus répété (une commande hors liste) : le **plancher**
la refuse tout de suite, sans attendre ; le **harnais** rend le refus avec
l'outil, la raison, la voie de sortie, et dépose la demande dans « À valider »
si la personne peut trancher ; le **contexte** du tour suivant rappelle ce qui
est en attente. L'agent n'a rien lu dans ses consignes, la personne n'a rien
eu à relancer, et la trace est dans le journal.

**Critère de réussite, pour tous les rôles** : un agent neuf, sans une ligne de
consigne en plus, lancé dans un projet quelconque, (a) a exactement les outils de
son rôle et peut le prouver, (b) ne reste jamais bloqué sans que l'Atelier le dise,
(c) ne peut ni lire un secret ni sortir de son périmètre, (d) reçoit un refus qui
dit quoi faire, (e) laisse une fin d'exécution qui dit vrai, (f) n'apprend rien à
la mémoire qui ne vienne de la personne. Chaque défaut du § 3 et du § 4 se
rattache à l'un de ces six points ; ce sont aussi les six contrôles que la preuve
« à chaque tour » devra vérifier.

Contraintes à vérifier sur le pod avant de bâtir (déjà listées dans l'état des
lieux, § 7) : les hooks passés par `--settings` ne sont pas pris aujourd'hui,
seuls ceux des réglages posés par l'Atelier le sont ; le plancher « managed »
s'applique-t-il en `-p` ; les sous-agents contournent-ils le refus du parent.

## 3. Registre — plateforme

Gravité : **C** critique · **G** grave · **M** moyen · **m** mineur.

### Permissions et confirmation

- **D-01 (C) — Permission sans réponse : 1 h d'attente, message opaque.** *Corrigé par la
  veille et la reprise (voir `attendre-sans-refuser.md` § 4) ; reste à faire : le message de
  refus d'un vrai refus, et la liste d'outils par rôle (§ 6).*
  Preuves : 6c36f388 (`pip install torch` attend 20:07 → 21:07, l'agent conclut
  « l'installation n'aboutit pas »), 16da076d (sous-agents bouclant une nuit sur
  `echo test`), 7113b90b, a7b0d0b6, ffb218d2 (commandes de lecture `find`,
  `git log`), cf10854c (« Tool permission stream closed » sur un `curl`).
  Zone : `harness.py` (attente de décision, ligne 930), `permission-prompt-tool`,
  modes par défaut de `atelier_lancer_agent`. **Statut : vérifié** (message).
  Correction, entièrement côté harnais : le refus que le pont de permissions
  rend au CLI nomme l'outil, la commande et l'endroit où répondre, et porte
  l'indice « ne conclus pas à une panne, ne réessaie pas à l'identique » ; délai
  court (2 à 5 min) puis refus explicite ; la question toujours visible dans « À
  valider » ; état « en attente de validation » sur la conversation ; lectures et
  commandes locales autorisées d'office par la liste du rôle.
- **D-02 (C) — Le jeton de confirmation se contourne.** Preuve : 494f37f9
  (« je passe la confirmation moi-même », aperçu puis action dans le même tour) ;
  le journal du 06/10 08:51:48 montre un événement `personne` / `fait` à la même
  seconde. Zone : `commandes/catalogue.py:480-515`. **Statut : vérifié.**
  Correction : refuser le jeton tant qu'aucun message humain n'a suivi l'aperçu,
  ou un vrai bouton Oui/Non ; journaliser l'acteur réel de la confirmation ; et
  (rapporté) 15 refus « jeton invalide » dont une partie vient d'arguments
  modifiés entre l'aperçu et l'appel — renvoyer le diff. *Touche la sécurité :
  décision de la personne avant de coder.*
- **D-03 (G) — Le texte du refus de permission laisse croire que la personne a
  refusé.** Preuve : 20eaf5d2 (« Refusé par l'utilisateur » 42 s après l'appel,
  c'était une règle). Conséquence : une « préférence » fausse dans la mémoire
  (`ee4a4a3a`). **Statut : rapporté.** Correction : dire « sans réponse dans le
  délai » ; exclure les refus de permission de l'extraction mémoire.
- **D-04 (G) — La règle « toujours » ne tient pas.** Preuve : 12 réponses
  « toujours » en 20 minutes le 03/10, suivies de « une fois ». **Statut :
  rapporté.** Correction : enregistrer la règle par outil et par projet.
- **D-05 (G) — La supervision refuse le réseau local et le dit mal.** Preuve :
  `curl 127.0.0.1:1` refusé en lancement supervisé, accepté ailleurs ; le texte du
  refus recopie la consigne de l'essai (« Dis-le et arrête-toi »), on ne distingue
  plus la plateforme de l'essai. **Statut : rapporté.** Correction : autoriser
  le loopback sur les ports du projet, ou nommer la règle et l'alternative
  (`atelier_artefact_verifier`) ; séparer le motif de toute consigne de
  comportement.

### Secrets et accès

- **D-06 (C) — Des agents demandent ou cherchent des secrets.** Preuves : 1a9361a5
  (« Tu as un token GitHub ? Si tu me le donnes, je le mets dans le pod »),
  ca5a0de1 (`env | grep -i "anthropic|llm|claude|openai"`). Le chemin légitime
  (connecteur à accorder dans l'interface) n'est pas dans la consigne.
  **Statut : rapporté.** Correction par le harnais : un hook `PreToolUse` refuse
  `env | grep` et la lecture de `.env*` / `.secrets/` avec le motif et la voie
  légitime (« accorde le connecteur dans l'interface, l'Atelier le fournit
  sans que tu en voies la valeur ») ; un hook `PostToolUse` masque les sorties
  contenant KEY/TOKEN/SECRET ; un moyen de demander un accord sans recevoir la
  valeur.
- **D-07 (G) — Alerte `securite.droits` jamais refermée.** Preuve : 8 alertes
  le 30/09 à 18:35 (`.secrets/` ouvert au groupe, clés lisibles par d'autres),
  aucune « résolue » dans la fenêtre. **Statut : rapporté.** Correction :
  `chmod 700/600` côté pod, ou journaliser la résolution.
- **D-08 (M) — 8 projets sur 16 héritent de « tous » les connecteurs, GitHub
  compris depuis le 08/10.** **Statut : rapporté.** Correction : GitHub réservé
  aux projets qui en ont besoin.

### Fins de lancement et états faux

- **D-09 (G) — « fini » ≠ livré.** Preuves : `lc-…9ed5dd70` « fini » en 100 s,
  *Corrigé en partie le 11/10 : un tour qui finit sur une erreur n'est plus « fini » (D-10) ; la conclusion dit si l'agent a livré (`livre`) ; une branche vide ne propose plus de fusion (D-21). Reste : recalculer `non_commite` après la clôture.*
  aucun livrable, la conversation continue 4 h (29 erreurs) ; `lc-…db3134a6`
  « arrêté », puis 534 lignes écrites dans la copie ni commitées ni proposées,
  `conclusion` figée à la clôture ; `lc-…4ca1e104` « fini » sur des appels
  `Write` tronqués. **Statut : rapporté.** Correction : scinder « fini » en
  livré / sans livrable / bloqué ; recalculer `non_commite` à la lecture ; détecter
  les appels d'outils illisibles répétés.
- **D-10 (G) — Conversation morte en erreur mais « idle ».** Preuve : 6da335e1
  *Corrigé le 11/10 : un résultat du CLI en erreur (`is_error`) rend la conversation « en échec », même quand le processus gardé rend un code 0 ; un agent lancé dans ce cas est « échec », pas « fini ».*
  (`autocompact_thrashing`, un blob d'image a saturé le contexte ; l'état reste
  `idle`, le dernier texte est ancien). Le flux produit bien un événement
  `erreur` (`events.py:217`) : c'est le calcul d'état de l'index qui l'ignore.
  **Statut : rapporté (partiel).** Correction : état « en échec » + message en
  clair ; ne pas injecter de blob image dans le contexte.
- **D-11 (M) — Arrêt sans motif ni acteur ; interruption d'un tour absent.**
  *Corrigé le 11/10 : interrompre une conversation au repos ne la marque plus « interrompue » et le dit (`rien_a_interrompre`) ; un lancement arrêté ou coupé garde son motif (« arrêté par … », « durée dépassée »).*
  Preuve : `arrete` avec `erreur` vide ; `atelier_interrompre` répond « fait »
  95 s après la fin. **Statut : rapporté.**
- **D-12 (M) — Deux conversations pour une même session CLI.** Preuve : 2e11c55e
  et fcaf6ff5, même `cli_id`, états et derniers textes faux. **Statut :
  rapporté.** Correction : clé unique `cli_id`, `dernier_texte` = dernier message
  assistant.
- **D-13 (M) — Dates de dernière activité rafraîchies par les relectures.**
  Preuve : `maj` de 12 conversations à 12:06 le 11/10 alors que la carte les
  disait à 13 jours. **Statut : rapporté.**
- **D-14 (M) — Compteurs et mémoire comptent des messages qui ne sont pas de la
  *Corrigé le 11/10 : résumés de compaction, messages de l'Atelier (`[Atelier]`) et entrées synthétiques ne sont plus lus comme des paroles de la personne (fiche et mémoire de nuit).*
  personne.** Preuve : 5ae7334b « 122 messages de la personne » dont des résumés
  de compaction (`isSynthetic`) et des notifications d'application ; propositions
  mémoire prêtant à la personne des préférences venues du résumé du modèle.
  Les marqueurs existent dans le transcript. **Statut : rapporté.**

### Copie de travail et lancement

- **D-15 (C) — Agent en copie de travail sans outil `atelier_*`, sans
  avertissement.** Preuve : les 5 lancements en copie ont `outils: []`,
  `avertissements: []` ; leurs missions exigent `atelier_artefact_verifier` /
  `atelier_montrer`. **Statut : rapporté** (hypothèse : `.mcp.json` non suivi par
  git, absent du worktree). Correction : injecter la config MCP dans la copie, ou
  avertir à l'aperçu.
- **D-16 (G) — La mission cite des chemins hors de la copie.** Preuve :
  *Corrigé le 11/10 : l'aperçu du lancement avertit des chemins absolus d'une mission sur branche et dit quoi faire.*
  `lc-…9ed5dd70` (lecture et écriture dans `/home/onyxia/work/...`),
  `lc-…aab4f0bc`. **Statut : rapporté.** Correction : détecter à l'aperçu ; copier
  les fichiers d'entrée ; dire à l'agent le chemin de sa copie.
- **D-17 (M) — Lancement en mode `default`, donc inopérant.** Preuve :
  textureforge `lc-…23ab43b7`. **Statut : rapporté.** Correction : refuser ou
  avertir pour `default` sans supervision.
- **D-18 (M) — Pas d'avertissement quand le projet n'a pas de pod.** Preuve :
  434d86b0. **Statut : rapporté.**
- **D-19 (M) — Le nom d'un agent est accepté à la création, refusé au
  lancement.** Preuve : « Catalogueur Data Territoires » créé le 07/10, puis 14
  refus « nom d'agent invalide ou générique ». Le validateur du lancement est
  `_NOM` (`lancements.py:86`, sans espace). **Statut : rapporté** (validateur de
  `atelier_agent_creer` non relu). Correction : même validateur aux deux endroits ;
  désactiver un déclencheur après N échecs identiques.
- **D-20 (m) — Messages de refus du formulaire de lancement trompeurs** (« la
  branche commence par `agent/` » pour `atlas-compatibilite` ; « une copie tourne
  déjà » sans la nommer). **Statut : rapporté.**
- **D-21 (M) — Propositions « Travail sans modification » sur des branches
  *Corrigé le 11/10 : « Rien n'a été livré » ou « Travail non commité », sans action de fusion.*
  vides.** Preuve : 4 propositions `commits: []` acceptées, titres du type
  « personne (agent/feuille-route) », résumés tronqués au milieu d'un mot.
  **Statut : rapporté.**

### Gardiens et santé

- **D-22 (G) — Les gestes de réparation sont refusés sans motif lisible.**
  *Corrigé le 11/10 : le motif du refus est écrit au journal unique.*
  Preuve : 184 `relancer_wikichat` refusés le 27/09, un toutes les ~65 s ;
  `relancer_atelier` refusé 3 fois. Dans le code, le refus a un motif
  (`executeur.py:503-512` : à blanc, `ATELIER_GARDIENS_GESTES=0`,
  `ATELIER_AVANT_PLAN=1`, trop de relances dans l'heure), mais l'événement
  journalisé (`executeur.py:359-366`) ne garde que `resultat: refuse`, **sans le
  motif**. **Statut : vérifié.** Correction : journaliser le motif ; ouvrir une
  alerte « intervention humaine requise » au lieu de réessayer sans fin.
  À noter : avec `ATELIER_AVANT_PLAN=1`, relancer l'Atelier est refusé *par
  conception* (ce serait arrêter le conteneur) — alors la sonde seule ne suffit
  pas, il faut que la personne soit prévenue.
- **D-23 (G) — Wikichat injoignable et mode différent selon la surface.**
  Preuve : alerte `coherence.surfaces` « app : serveurs en échec ['wikichat'] »
  (rezograph 09/10, assistant, gp2oa-grist 01/10) ; `:3777` « Connection
  refused » ; modes `app/vscode: bypassPermissions`, `terminal/bash-lc: default`.
  **Statut : rapporté.** Le dépôt wikichat est maintenant cloné pour diagnostiquer.
- **D-24 (M) — Alertes qui clignotent ou se dupliquent.** `sante.atelier`
  ouverte/résolue à une minute d'intervalle ; `sante.creations` « illisible » 8
  cycles ; 35 alertes `demon.port-*` pour des services pourtant déclarés ;
  `coherence.surfaces` résolue 10 fois d'un coup. **Statut : rapporté.**
  Correction : hystérésis, empreinte sans hachage de contenu.
- **D-25 (G) — L'Atelier lui-même tombe** (`Connection refused :8787`, « Service
  Unavailable » sur le journal), alerte encore ouverte le 11/10 à 12:08.
  **Statut : rapporté.**

### Artefacts et vérification

- **D-26 (G) — « Application en échec » sans cause.** Le message arrive comme un
  message de la personne, sans stderr ni queue de journal ; un service démarre
  sans ses dépendances (`ModuleNotFoundError`), `artefact.json` n'a pas d'étape
  d'installation. **Statut : rapporté.**
- **D-27 (M) — `artefact_creer` accepte ce que `artefact_demarrer` refuse**
  (« `protocoles` ne peut pas être vide »). **Statut : rapporté.**
- **D-28 (M) — `atelier_montrer` montre un service arrêté** ; le code de
  navigation expire en cours de vérification ; une page perd le préfixe d'URL de
  l'artefact (401 sur la racine de l'hôte). **Statut : rapporté.**
- **D-29 (M) — Interpréteur du venv cassé** : le Python géré par `uv` vit hors
  projet (`.tools/uv-python`) et peut disparaître ; l'artefact échoue 7 fois de
  suite avec `[Errno 2]`. **Statut : rapporté.**

### Onyxia et GPU

- **D-30 (G) — Cercle vicieux de déclaration.** Déclarer un pod exige qu'il soit
  « Running » ; le relancer exige les outils Onyxia, qui exigent la déclaration
  (depth-models, refus du 04/10 21:46). **Statut : rapporté.** Correction :
  accepter de déclarer un pod arrêté (« à démarrer ») ; exposer `project_start`,
  `session_start`, `gpu_status` dès que le connecteur est choisi.
- **D-31 (G) — Lectures Onyxia sans risque qui passent par une demande
  d'accord** (`list_pods`, `session_status`, `list_files` : jusqu'à 1 h
  d'attente). **Statut : rapporté.**
- **D-32 (G) — Le pont Onyxia est instable** : `ConnectionClosedError`,
  `NO_SESSION`, « The operation timed out » (a9440656, 00423dff, ac2e4b50) ; les
  noyaux Jupyter ne répondent plus depuis plusieurs jours. **Statut : rapporté**,
  recoupé par mes propres essais.
- **D-33 (M) — Environnement différent d'un pod à l'autre** (pas de torch, pas
  de GPU, ports et variables non injectés) à la reprise d'une conversation.
  **Statut : rapporté.**

### Mémoire et file « À valider »

- **D-34 (G) — La file ne se vide pas et se pollue.** 49 propositions en attente
  *Corrigé en partie le 11/10 : les quasi-doublons de la mémoire se fusionnent à l'entrée. Reste : expiration, acceptation en lot, exiger une citation.*
  sur 56, 4 jours sans tri ; doublons sémantiques (empreinte sur le texte exact) ;
  tâches ou demandes produit prises pour des préférences ; 21 pour
  `wikichat-memory`, 6 pour des projets rangés ; deux propositions identiques sans
  projet depuis le 01/10. La routine de nuit tourne en lots irréguliers (jusqu'à
  34 propositions) et ses dépôts ne sont pas journalisés. **Statut : rapporté.**
  Correction : déduplication par similarité (les vecteurs existent), ne retenir
  que des déclarations explicites avec citation, expiration, acceptation en lot.

### Outils de lecture et projets

- **D-35 (M) — `atelier_transcript` refuse les identifiants courts** que
  *Corrigé le 11/10 : les outils de conversation acceptent l'identifiant court (8 caractères) ; un préfixe ambigu ne devine pas.*
  `atelier_fiche` accepte ; sortie en JSONL brut tronqué, sans pagination.
  **Statut : rapporté.**
- **D-36 (m) — `atelier_journal` et `atelier_a_valider` dépassent la limite de
  lecture** (82 k et 110 k caractères) ; `depuis=` ne pagine pas vers l'arrière.
  **Statut : rapporté.**
- **D-37 (M) — Projets mal rangés ou fantômes.** `data-territoires-…` : 4
  conversations, `ETAT.md`, 5 lancements, mais `atelier: null` et absent de
  `atelier_projets` ; slugs tronqués à 40 caractères ; `gp2oa-grist` vide alors
  que son travail est dans `projet-sans-nom-8` (rangé) ; 18 projets rangés dont
  certains reçoivent encore des conversations ; doublons `depth-models` /
  `projet-modeles-de-profondeur`. **Statut : rapporté.**
- **D-38 (m) — Essais mélangés au travail** (`essai-interface-1..5`,
  « bonjour », « Réponds seulement : ok » : 13 dans `projet-sans-nom-4`) ; 5
  projets actifs encore en `projet-sans-nom-N` ; 5 projets sans `ETAT.md`.
  **Statut : rapporté.**
- **D-39 (m) — Erreurs « projet inconnu » sans les valeurs possibles**, et un
  projet système (`wikichat-memory`) traité comme inconnu. **Statut : rapporté.**
- **D-40 (m) — `ETAT.md` périmé** (depth-models : « prochaine étape : écrire le
  cahier des charges » alors que le GPU tourne) ; fiches « résumé : à venir » et
  « fin non lue » sur les longs transcripts. **Statut : rapporté.**

### Contexte, coût, modèle

- **D-41 (G) — Contexte démesuré, aucun cache.** 35 à 38 k jetons au premier
  tour, 91 k pour un essai trivial, `cache_read_input_tokens = 0`. Coûts
  affichés : 442 $, 362 $, 358 $, 143 $ (avec `costBasis: unknown`). **Statut :
  rapporté.** Correction : cache de préfixe (proxy), outils MCP à la demande,
  CLAUDE.md allégé, compaction plus tôt, coût visible par conversation.
- **D-42 (M) — Fenêtre déclarée à 40 000 pour un modèle de 131 072** (4d9a40fe),
  et résumé de compaction injecté avec « Respond with TEXT ONLY. Do NOT call any
  tools » qui bloque l'agent. **Statut : rapporté.**
- **D-43 (M) — Défaut de compatibilité Claude Code / LiteLLM** : `Unexpected
  reasoning effort high` sur `qwen3-8-27b` (f3557c35). **Statut : rapporté.**
- **D-44 (M) — Pas de plafond contre les boucles** (6c4128a9 répète la même
  phrase jusqu'à la limite de sortie ; 5,7 M jetons). **Statut : rapporté.**

## 4. Registre — consignes et modèle

Ces défauts se voient dans le raisonnement du modèle (`qwen3-*`), mais la
correction, d'après le principe du § 2 bis, est dans le harnais : l'Atelier voit
l'événement et agit, l'agent n'a rien de plus à retenir. Chaque entrée dit où.

- **D-45 (G) — Après un outil refusé, l'agent conclut quand même.** 5bbfb09b :
  requête `journal.sqlite` refusée, puis « il ne contient pas d'événements
  d'accord réseau » — faux (20 origines accordées). Correction par le harnais :
  le pont de permissions ajoute à tout refus un indice « refusé : ce contrôle
  n'a pas eu lieu, ne rien en conclure » ; `permission_denials` du résultat final
  est relu et rappelé au tour suivant. Et un journal d'audit des accords réseau
  doit exister et être lisible.
- **D-46 (G) — « Revient à la personne » sur-appliqué, avec des conseils
  faux.** pix2hdr 78b49bcc et ffb218d2 : l'agent refuse d'exposer un port ou de
  libérer le GPU, puis propose `kubectl` alors que le compte n'a pas le droit.
  c577451e renvoie la personne « taper : Expose le port 8000 » dans le même
  chat. Correction par le harnais : le refus d'un outil réservé porte lui-même la
  voie de sortie (« déposé dans À valider : la personne n'a qu'à accepter ») —
  l'Atelier dépose la proposition à la place de l'agent ; un hook `PreToolUse`
  refuse `kubectl` avec le motif.
- **D-47 (G) — La convention du socle n'est pas appliquée au premier passage**
  (rezograph : `.atelier/projet.json` et `.atelier/env.json` à la racine ; 17
  messages de correction, 170 tours, 90 $). Correction : la structure est posée
  par l'Atelier (`atelier_projet_structurer`), puis contrôlée par un hook, pas
  rédigée par l'agent.
- **D-48 (M) — Outils d'orchestration exposés aux agents de projet** (`envoyer`,
  `decider`, `interrompre`) ; ensembles d'outils annoncés différents d'une
  session à l'autre (754ce2c3, 394226a3, 2a220ebb) ; l'agent invente des noms
  (`atelier_artefet_*`). Correction par le harnais : une seule configuration
  déterministe par rôle ; un hook `SessionStart` injecte la liste réelle des
  outils (celle de l'événement `system/init`) et en garde la preuve dans la
  fiche — l'agent n'a plus à la deviner ni à la raconter.
- **D-49 (M) — Appels parallèles malgré « dans l'ordre »** (3fc85199,
  ef5f76a6) ; **`Write` tronqué** sur de gros fichiers ; **réponse « None »**
  et tours vides. Correction : en mode supervisé, l'Atelier sérialise les
  décisions ; un `Write` illisible est détecté et ramené en indice (« fichier
  trop gros : coupe-le ») ; la sortie vide est filtrée à l'affichage.
- **D-50 (M) — Hypothèses non testées présentées comme causes** (« problème de
  cache ES module », « le pod partage l'IP », « page générée dynamiquement »
  avant de voir un 401). Correction : l'Atelier met la mesure à portée (hash
  servi, code de retour toujours rendu, état du port) dans le résultat de l'outil,
  de sorte qu'il n'y a plus à supposer.
- **D-51 (M) — Création présentée « vérifiée » avec 401/404 en console**
  (f49f75e8). Correction : hook `Stop` — `atelier_artefact_verifier` fait foi, et
  une clôture « vérifié » est renvoyée à l'agent si la console contient des 401.
- **D-52 (m) — Une consigne triviale déclenche des outils** (`send_message`
  deux fois pour « Réponds seulement : ok »). Retirer `send_message` des outils de
  l'Assistant : c'est la configuration du rôle qui tranche, pas la consigne.

- **D-53 (G) — Le store de wikichat est perdu à chaque redémarrage du pod.**
  `~/.wikichat` est un dossier de la couche éphémère, pas un lien vers le volume :
  `ensure_wikichat_data_link` (`wikichat_ensure.py`) existe mais n'est appelé nulle part
  (c'est T23). Un redémarrage vide les agents et routines du Pilote, le registre des projets,
  les messages, les canaux et le sel d'identité ; les faits, fiches, vecteurs et les trois
  déclencheurs semés au démarrage sont recalculés. Constaté le 11/10 : `agents/` et `projects/`
  vides, `migration-w2.json` daté du démarrage ; l'archive du 27/09 n'a aucun état de wikichat.
  **Statut : vérifié.** À régler avant tout nouveau redémarrage (migration de données : à
  soumettre à la personne).
- **D-54 (G) — L'environnement d'un agent est une copie de celui de l'Atelier.**
  `harness._env` part de `os.environ.copy()` : un agent qui a Bash lit `ATELIER_OWNER_KEY`,
  `ATELIER_GITHUB_TOKEN`, `ATELIER_LLM_API_KEY`. `~/work/gateway/owner_key.txt` est lisible par
  le groupe (660). Les bornages par commande et par projet sont donc des consignes pour tout
  agent qui a un shell. **Statut : vérifié.** Prérequis : jeton par conversation (D1), puis
  environnement en liste blanche.
- **D-55 (G) — `sudo` sans mot de passe pour l'utilisateur des agents**, `kubectl` installé
  dans le pod. Un agent peut réécrire le code et les réglages de l'Atelier, ou une politique
  gérée posée par `root`. **Statut : vérifié.**
- **D-56 (G) — Des secrets collés par la personne sont restés dans des transcripts**
  (une clé d'API de modèle et un jeton de session d'un outil de données, dans
  `~/work/transcripts/`, dossier `wikichat-memory`). Un fichier `.env.sspcloud` non lu dans
  `projects/claude-code/`. À révoquer, puis à purger. **Statut : rapporté.**
- **D-57 (M) — Boucle de refus du geste `relancer_wikichat`** : 216 refus et 16 alertes en
  4 h le 27/09 pendant une panne de wikichat, par l'acteur `gardiens`. Il manque un
  coupe-circuit (nombre d'essais, délai croissant). **Statut : vérifié (journal).**
- **D-58 (M) — Mesure impossible des décisions de permission** : les fichiers répondus
  disparaissent de `decisions/` et le journal ne garde ni l'outil, ni le projet, ni le délai de
  réponse. 86 demandes sont restées sans réponse (âge médian 14 jours), 16 en veille.
  **Statut : vérifié.**

- **D-59 (m) — Les processus orphelins ne sont pas ramassés.** PID 1 est l'application Python,
  qui ne fait pas `waitpid` sur les orphelins : 50 zombies une heure après le démarrage (six par
  session du navigateur de l'agent : `bash`, `npm`, `node` ×3, `chrome-devtools`, `sh`). Sans
  effet visible à l'heure, mais croissant sur un pod qui reste des jours. **Statut : vérifié.** Correction écrite : `tini` est le processus 1
  de l'image (`deploy/Dockerfile`) ; effective au prochain déploiement de l'image, à mesurer ensuite.
- **D-60 (G) — Les plafonds de l'Atelier ne tiennent pas dans la mémoire du pod.** 4 applications
  de 1,5 Gio, 6 Chrome, 3 CLI persistants, 3 lancements simultanés et la voix (2,2 Go), plus le
  socle (0,7 Go) : de l'ordre de 12 à 15 Gio pour un plafond de 8 Gi. Aucun contrôle de santé ne
  surveille la mémoire. Un dépassement est tué par le noyau ; si c'est PID 1, le conteneur
  redémarre (et le store de wikichat disparaît, D-53). Les lignes Chrome et CLI sont des
  estimations à mesurer sous charge. **Statut : rapporté (calcul sur les plafonds).**

## 5. Déjà corrigés (pour mémoire)

Livrés et fusionnés avant ce relevé : les trois failles de sécurité de la revue
(périmètre du lanceur, secrets réservés à l'Atelier, GET qui agit), les tours
simultanés, le journal unifié sans doublons, le workflow d'image
(`:sha` → fumée → `latest`), le journal et les limites GPU, le contexte
Onyxia de l'Assistant, les erreurs en français, le lancement « occupé » (il
n'est plus compté comme réussi), le modal « Nouveau projet », les connecteurs
choisis avant le premier message, la case Onyxia respectée, la mise à jour de la
page CANBT, l'état des lieux (PR #21).

## 6. Restes de la revue du 03/10 (non faits)

Arrêt propre du pod au déploiement · formulaire de déclaration Onyxia ·
accessibilité de la modale et `aria-live` · `/v1/diagnostic` · cache et
parallélisme de la CI · documentation des statuts · sauvegardes · mise à jour de
`SECURITY.md` pour les correctifs du 03/10 · `fonctionnalites.md` (Services du
projet, verdicts, aperçu, journal GPU, période du lanceur) · jeton de
l'interface (D1, cahier des charges seulement).

## 7. Ce que je n'ai pas pu faire

**Ouvrir l'interface réelle dans Chrome.** La session n'a pas d'outil
navigateur, et l'interface du pod demande la clé du propriétaire que je n'ai pas.
Ce que j'ai fait à la place : lecture de l'état réel par les outils de l'Atelier
(carte, journal, lancements, fiches, transcripts) et, pour l'interface, des essais
locaux sur une instance de démonstration. Les défauts d'affichage de la
liste ci-dessus (D-10, D-13, D-34) sont donc établis par les données, pas par
une capture. À refaire à l'écran avec vous, ou avec un navigateur branché.

## 8. Ordre de traitement proposé

1. **Lire ce que reçoit l'agent, et poser le natif d'abord** (D-01, D-03, D-15,
   D-16, D-22, D-48). Les listes `allow` / `deny` par rôle avec `dontAsk` (fin de
   l'attente d'une heure), la liste d'outils exacte et sa preuve au démarrage,
   les messages de refus actionnables, le motif des gestes journalisé, les
   avertissements à l'aperçu. Peu risqué, gain immédiat.
2. **Fins de lancement honnêtes** (D-09, D-10, D-11, D-12, D-14). Un état qui dit
   vrai.
3. **Sécurité** (D-02, D-06, D-07, D-08) : demande votre accord avant de coder.
4. **Mémoire propre** (D-14, D-34, D-03) : une fois les états justes.
5. **Contexte et coût** (D-41 à D-44) : surtout côté proxy.
6. **Onyxia, artefacts, projets** (D-26 à D-33, D-37 à D-40).

## 9. Décisions qui sont à vous

- Lier la confirmation à un message humain (D-02) : bouton Oui/Non dans
  l'interface, ou refus du jeton sans message humain ? Les deux ?
- Délai d'attente d'une permission : 2 min ? 5 min ? Que se passe-t-il ensuite
  (refus explicite, comme proposé) ?
- Lectures et commandes locales autorisées d'office pour les agents lancés : oui
  pour `list_pods`, `session_status`, `list_files`, `curl 127.0.0.1`, `ls`, `git
  log` ? Quelle liste exactement ?
- Faut-il ranger ou fusionner les projets d'essai (`projet-sans-nom*`, doublons) ?
- Brancher un navigateur sur cette session pour que je teste à l'écran.
