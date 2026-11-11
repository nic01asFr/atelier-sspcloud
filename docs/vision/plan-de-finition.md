# Plan de finition de l'Atelier : travaux et corrections, par lots

> **État au 11/11/2026. Plan, rien n'est exécuté.** Il sort d'une relecture de tout l'existant par cinq
> lecteurs (pensée d'ensemble, agents et droits, créations et hébergement, laboratoire et mémoire,
> qualité du code) et d'une vérification personnelle de l'un des constats (§ Lot 1). Il complète
> [`etat-des-lieux-et-roles.md`](etat-des-lieux-et-roles.md) §6 (lots 1 à 6), dont il reprend et
> réordonne le contenu, et [`registre-des-defauts.md`](registre-des-defauts.md) (numéros D-xx).
> La boucle d'auto-amélioration ([`auto-amelioration.md`](auto-amelioration.md)) vient **après** ce plan.

**Comment lire les niveaux de preuve.** *Mesuré* : chiffre obtenu en exécutant ou en comptant.
*Lu* : constaté dans le code, non exécuté. *Rapporté* : dit par un lecteur, non revérifié. *Déduit* :
interprétation. Un lot ne passe pas à « fait » sans la preuve qu'il énonce.

## 0. Le principe qui ordonne tout

L'Atelier tient en **trois cadres emboîtés** : le harnais Claude Code (les tours, permissions, hooks,
outils), le croisement **wikichat × gateway** (mémoire, coordination, profils et outils : ce qui fait
l'agent), et l'**Atelier global** (la personne, ses projets, créations, panneau, « À valider »). Onyxia
et SSPCloud en sont la frontière extérieure, cadrée. L'auto-évolution n'est sûre que si **chaque
cadre limite le suivant par la mécanique**. D'où l'ordre : étanchéité d'abord, définition unique du
rôle ensuite, signaux vrais, puis séparation brouillon/production, puis consolidation, puis boucle.

### 0 bis. Tout s'emboîte dans Claude Code (inventaire et préréglages par cas : [`cible.md`](cible.md) § 1.4) *(précisé le 11/11, d'après Nicolas)*

Claude Code est le **substrat** : wikichat s'appuie sur lui, les agents sont ses sessions, la gateway
est un de ses serveurs MCP, l'Atelier l'habille. Chaque notion de l'Atelier se range sur un
mécanisme natif ; **on n'écrit du code Atelier que pour ce que le natif ne fait pas** (principe 2 ter
du registre des défauts). Correspondance de travail, à confirmer sur la version du CLI du pod :

| Notion de l'Atelier | Mécanisme natif sur lequel elle repose | Ce que l'Atelier ajoute |
|---|---|---|
| Plafond d'une famille d'agents | réglages **managés** (priorité la plus haute, un `deny` l'emporte) | les écrire, les rendre inaccessibles à l'agent |
| Défauts du projet (agents code) | `.claude/settings.json` **du projet**, suivi par git | l'édition par commande engageante, le journal |
| Surcharge de session | options du lancement (`--settings`, `--allowedTools`, `--permission-mode`) | la stocker sur la fiche, la borner au plafond du projet |
| Profil d'un agent de l'Atelier | définition de **sous-agent** / **plugin** (outils, hooks, skills propres) | le catalogue, les capacités accordées, le budget |
| Ce que reçoit l'agent | `--mcp-config` + `--strict-mcp-config` ; hook `SessionStart` | la gateway filtre à la source, la carte le prouve |
| Mémoire de la personne et du projet | fichiers de mémoire (`CLAUDE.md`) + fiches wikichat | « Ma mémoire », le filtre d'origine, la validation |
| Garde-fous | hooks `PreToolUse` / `PostToolUse` / `Stop`, `permissions.deny` | les scripts, versionnés avec l'Atelier |
| Savoir-faire répétables | skills et commandes | le kit (`/reprendre`, `/verifier`…) |
| Fin honnête d'un tour | `terminal_reason`, `permission_denials`, `system/init` | l'état du lancement qui dit vrai |
| Auto-évolution | tous ces mécanismes sont des **fichiers** | les modifier sur une branche, les éprouver, les promouvoir (`auto-amelioration.md`) |

Conséquences pour les lots : le lot 3 ne crée pas un moteur de rôles parallèle, il **compile** la
résolution en couches vers les couches de réglages natives ; les lots 1 et 2 consistent à rendre la
couche haute (managée) et l'identité hors de portée de l'agent ; l'auto-évolution (lot 10) n'agit que
sur des fichiers versionnés que l'Atelier sait tester. Réserve : la priorité exacte des couches, le
comportement des sous-agents quand le parent refuse, et l'application des réglages managés en mode
`-p` sont **à confirmer sur le pod** avant de s'y appuyer (§ 4).

## 1. État mesuré, pour mémoire

| | Valeur | Niveau |
|---|---|---|
| Code | 59 045 lignes Python (160 fichiers), 26 900 lignes de front, 33 623 lignes de tests | mesuré |
| Suite de tests | 2 267 passent, 1 échoue, 2 ignorés, 6 min ; l'échec : `tests/test_socle.py:185`, module introuvable dans un venv neuf (cause probable : environnement) | mesuré |
| Couverture directe | 43 modules sur 151 (9 574 lignes) sans test qui les importe, surtout la couche gateway d'origine (`compositions`, `upstream`, `profiles`, `api.py` racine) | mesuré |
| Module « dieu » | `atelier/api.py` : 3 063 lignes, 101 routes, 68 dépendances ; 238 routes au total | mesuré |
| Cycles | une composante de 30 modules (harnais, lancements, `mcp_sync`, `commandes/*`…), via imports paresseux | mesuré |
| `except Exception` | 156, dont 38 réduits à `pass`/`continue`/`return` ; aucun trouvé masquant une erreur d'auth ou de décision | mesuré |
| Constantes dupliquées | port 8791 défini trois fois, 8787/8790 redéfinis dans les gardiens | mesuré |
| TODO / FIXME | 0 | mesuré |

## 2. Les lots

Chaque lot : **constat → travaux → preuve de réussite → retour arrière → dépend de**. Effort : S (≤ ½ jour),
M (1-2 jours), L (plus). Les tests s'écrivent **avant** le correctif.

### Lot 1 · Étanchéité de l'identité *(critique, en premier)*

**Constat (lu, vérifié par moi dans `api.py:1116`, `commandes/routes.py:105-114`, `auth.py`).**
`ATELIER_MCP_KEY` est dans l'environnement de chaque agent. `POST /v1/auth/cookie` l'échange, sans autre
condition, contre une session ; une session avec l'en-tête `X-Atelier-Interface: 1` devient l'acteur
`personne` d'origine `interface`. Le garde anti-CSRF (`GardeDesCookies`) accepte un `Origin` égal au
nôtre : un `curl` le fixe. Conséquence probable : les classes *réservée* et *engageante*, la confirmation
liée à un message humain (D-02) et `messages_humains.noter` ne protègent que contre un modèle docile.
`POST /auth/rotate` permettrait aussi à un agent de verrouiller le propriétaire dehors (rapporté).

**Travaux.**
1. **Test qui reproduit la chaîne** sur l'application de test : clé → cookie → appel d'une commande
   réservée → doit être refusé. Il échoue d'abord (sinon le constat tombe, et on le note).
2. Refuser `/auth/cookie` et `/auth/rotate` aux appelants qui portent une conversation ou le profil d'un
   agent ; exiger pour l'ouverture de session une preuve qu'un agent ne détient pas (second facteur de
   la personne, ou clé distincte de celle des agents).
3. **Capacités courtes par conversation** (D1) : jeton lié à la conversation, durée courte, HMAC du
   secret interne + identifiant + échéance ; inventaire préalable de tous les consommateurs de la clé
   (`ATELIER_OWNER_KEY`, `ATELIER_MCP_KEY`, hooks, `headersHelper`, lancements, VS Code, terminal).
   Migration par consommateur ; la clé quitte l'environnement des agents en dernier.
4. Le jeton du lanceur (`/v1/lancements`) : ne plus accepter `confirme=True`, `origine` libre ni
   `mode_de_la_definition` de la part d'un appelant non listé (`lancements.py:1346-1360, 1546`, lu).

**Preuve.** Le test de l'étape 1 passe ; un agent lancé dans le pod ne peut ni ouvrir une session
« personne », ni lire une clé propriétaire dans son environnement ; la suite complète reste verte.
**Retour.** Drapeau de compatibilité par consommateur jusqu'à migration complète. **Effort** L (étapes
1-2 : S-M ; étape 3 : L, à concevoir à part). **Décision requise** : mécanisme du second facteur.

### Lot 2 · Une garde qui n'est pas une consigne

**Constat.** Aucun `managed-settings` dans le code (lu) ; les hooks (`garde_bash`, `garde_navigation`)
sont écrits dans `~/work/.claude/settings.json`, que l'agent peut modifier ; pas de `PostToolUse`,
`SessionStart` utile à l'agent, `Stop` (lu). `garde_bash` ne refuse que `.secrets` littéral, `pkill -f` et
`0.0.0.0` ; `~/work/.sec*ts/`, `printenv ATELIER_MCP_KEY`, `cat /proc/self/environ` passent (testé par un
lecteur en important la fonction). Le périmètre du lanceur accepte `sed 'w …'` et `awk '… > …'` (rapporté).
`reponse_refusee()` garde « Refusé par l'utilisateur » par défaut (`decisions.py:387`, lu) : D-01, D-03.

**Travaux.**
1. **Essai sur le pod avant de bâtir** : les réglages managés s'appliquent-ils en `-p` ? le `deny`
   l'emporte-t-il en `bypassPermissions` ? que font les sous-agents quand le parent refuse ? (déjà en
   § 7 de l'état des lieux ; *aucune ligne de ce lot n'est une promesse tant que l'essai n'est pas fait*).
2. `managed-settings.json` dans l'image : `deny` sur la lecture des secrets et de l'environnement, sur
   les écritures hors périmètre ; hooks passés par `--settings` à chaque tour, hors de portée de l'agent.
3. Étendre la garde à `Read`, `Write`, `Edit`, `Bash` ; remplacer les listes noires par motifs par des
   listes **blanches** par rôle quand c'est possible (`sed`/`awk` : refuser l'écriture par redirection
   ou `w`).
4. Hooks `SessionStart` (outils réellement disponibles, ports, état du projet), `PostToolUse`
   (troncature, masquage `KEY`/`TOKEN`/`SECRET`), `Stop` (voir lot 4).
5. Motif de refus lisible : nom de l'outil, commande, « ne conclus pas que l'outil est en panne ».

**Preuve.** Chaque contournement listé devient un test qui doit être refusé ; un agent ne peut pas
réécrire le fichier de hooks. **Retour.** Interrupteur `ATELIER_GARDIENS_HOOKS=0` existant ; version
managée désactivable par réglage. **Effort** L. **Dépend de** l'essai de l'étape 1.

### Lot 3 · Un rôle, une définition *(le point de croisement wikichat × gateway)*

**Constat.** Un rôle n'est défini nulle part (état des lieux § 2, point 1) : le mode de permission est
recalculé à plusieurs endroits, `dontAsk` est silencieusement remplacé par `default` (`lancements.py:608`,
lu), `outils` d'un lancement devient `permissions.allow` verbatim (`lancements.py:773, 907`) et la liste
fermée vit côté Pilote, hors de ce dépôt (rapporté). Deux taxonomies coexistent : profils `code` /
`assistant` et les quatre rôles de l'état des lieux, sans pont (rapporté).

**Le modèle (précisé le 11/11, d'après Nicolas).** Deux familles d'agents, une seule mécanique de
résolution **en couches**, chaque couche ajustant à l'intérieur du plafond de la précédente :

```
 famille (code | agent de l'Atelier | assistant | gardien)   plafond fixé par l'Atelier
   └► profil de base de la famille
        └► agents code : défauts du projet        agents de l'Atelier : profil propre à l'agent
             └► agents code : surcharge de session    agents de l'Atelier : capacités accordées
```

- **Agents code** (conversation de travail d'un projet) : un profil attribuable **au projet** (ses
  défauts, valables pour tous ses agents code), modifiable **dynamiquement par session** sans toucher
  aux autres sessions ni aux défauts. Ils agissent dans leur projet ; ailleurs, ils écrivent aux agents
  de l'autre projet (wikichat).
- **Agents de l'Atelier** (page Agents) : profils et capacités attribuables et configurables **par
  agent**, y compris pour agir sur des projets, sur plusieurs, mais par capacités accordées et cadrées,
  jamais par accès général. Plusieurs formes possibles (planifié, à la demande, gardien, réparateur…).
- Aujourd'hui (lu) : deux profils par type d'acteur (`code`, `assistant`), pas de profil de projet ;
  seul le mode de permission a le double niveau projet / conversation ; les agents de la page Agents
  n'ont qu'une liste `outils` et un budget, sans profil ni capacités.
- **L'identité d'un agent est la capacité signée par conversation du lot 1** (famille, profil résolu,
  projet, surcharges, durée). L'agent ne peut ni la forger ni l'élargir.

**Travaux.**
1. `roles.py` : une table des **familles** et de leurs plafonds, un résolveur en couches, un lecteur.
   Un profil = outils, mode de permission, plafonds (tours, jetons, par jour), hooks, accès aux
   connecteurs, accès à la mémoire. Rattacher `code` / `assistant` à ce modèle.
2. **Profil de projet** : un bloc dans `projet.json` (défauts des agents code), éditable par commande
   *engageante* ; **surcharge de session** : stockée sur la fiche de la conversation, effacée avec
   elle, journalisée ; elle ne peut qu'ajuster à l'intérieur du plafond du projet.
3. **Agents de l'Atelier** : profil et capacités par agent, dans la définition d'agent (plus seulement
   `outils`) ; une capacité sur un projet est un octroi explicite, daté, révocable, dans « À valider »
   quand il élargit ; l'agent n'agit sur un projet que par les commandes de l'Atelier filtrées par ses
   capacités.
4. Compiler le résultat vers les options natives (`--tools`, `--allowedTools`, `--mcp-config` +
   `--strict-mcp-config`, `--max-turns`, `--max-budget-usd`) ; **supprimer** les trois autres sites qui
   recalculent le mode. Les listes de `coherence.py` sont lues à la source.
5. Plafond de jetons **appliqué** (il est lu et jamais appliqué). Budget imposé côté Atelier aux
   triggers wikichat (aujourd'hui seulement tours et lancements).
6. Le croisement est tracé : pour chaque agent, *ce que wikichat sait* × *ce que la gateway ouvre*
   apparaît dans la carte et le journal, comparé à `system/init` à chaque tour (pas seulement une fois
   par jour).
7. Matrice acteur × service (aujourd'hui les connecteurs du pool sont hérités en bloc, D-08,
   `mcp_sync.py:367`).

**Preuve.** Tests « instantané » par famille et par couche ; une surcharge de session n'affecte ni une autre session ni les défauts du projet ; une couche ne dépasse jamais le plafond de la précédente ; un seul site calcule le mode (grep). **Retour.** La table
produit d'abord les valeurs actuelles (aucun changement de comportement), puis on les resserre.
**Effort** L. **Dépend de** lot 2 pour les hooks.

### Lot 4 · Des états qui disent vrai

**Constat.** « Fini » = le processus s'est arrêté (D-09) ; `terminal_reason` et les refus de permission
ne sont pas lus pour fixer l'état (grep : `terminal_reason` absent, `permission_denials` lu seulement
pour l'affichage) ; pas de hook `Stop` ; D-01 dit « refus explicite », le code s'endort après 600 s
(`harness.py:858-990`), ce qui est cohérent avec `attendre-sans-refuser.md` mais pas avec le registre.

**Travaux.** (1) État d'un lancement : `livré` / `bloqué` / `échoué` / `arrêté par`, avec motif et
acteur ; (2) refus de permission → le lanceur les reçoit, le lancement est « bloqué » s'il n'a rien
livré ; (3) hook `Stop` : pas de « vérifié » avec des 401 en console, pas de « fini » sans livrable ;
(4) aligner la doc (registre D-01) sur le comportement choisi (veille).

**Preuve.** Test `test_fins_qui_disent_vrai` étendu ; un lancement qui se heurte à des refus n'est
jamais « fini ». **Retour.** Ajout seul (champ d'état), l'ancien libellé reste lisible. **Effort** M.
**Débloque** : mémoire de nuit, suivi, et plus tard les indicateurs de la boucle d'amélioration.

### Lot 5 · Brouillon et production

**Constat (lu, jalon J8).** Aucun `prod/`, `~brouillon`, worktree figé ni `atelier_artefact_proposer` :
un artefact serveur tourne depuis l'arbre de travail ; le manifeste est strict (`extra="forbid"`) et sans
`donnees`, `capacites`, `entretien`, `memoire_max_mo` (le plafond de 1,5 Gio est fixe,
`apps/manifeste.py:327`) ; `acces` ne vaut que `proprietaire` ; une app peut lire `~/work/.secrets`.

**Travaux.** (1) Production = worktree figé d'un commit ; le brouillon vit à côté ; promotion = geste
de la personne, registre des promotions ; (2) `donnees/` hors git avec sauvegarde ; (3) champs du
manifeste ajoutés par version (`v2`), sans casser la v1 ; (4) un app sous `acces: proprietaire` ne lit
pas les secrets de l'Atelier (périmètre de fichiers du superviseur) ; (5) partage : lien révocable, après
la décision sur l'authentification des tiers (`passerelle-auth`).

**Preuve.** Modifier le brouillon ne modifie pas ce qui tourne ; retour à la version précédente en un
geste. **Retour.** La production par worktree est derrière un réglage de projet. **Effort** L.
**Décision requise** : le partage à des tiers est-il dans le périmètre ?

### Lot 6 · Mémoire et wikichat : fermer les écarts

**Constat.** Le filtre d'origine repose sur `isSynthetic`/`isMeta`/`isCompactSummary` et des préfixes de
texte (`journal.py:82-95`) ; `turnOrigin` n'est nulle part alors que le registre D-14 l'annonce (grep) ;
une proposition refusée peut être reproposée (assumé dans `test_a_valider_doublons.py:66-71`) ;
l'expiration, l'acceptation en lot et la citation obligatoire (D-34) manquent ; le plafond « 3 par
conversation » retombe sur l'acteur quand la conversation est vide (`memoire.py:~291`) ;
`ensure_wikichat_data_link` n'est appelée nulle part dans le Python (D-53 : à vérifier dans
`install/atelier-init.sh`), et trois documents se contredisent sur la persistance du store.

**Travaux.** (1) Lire `turnOrigin` quand il existe, garder les heuristiques en repli ; (2) mémoriser les
refus pour ne pas reproposer (empreinte) ; (3) citation exigée à chaque candidat ; expiration ;
acceptation en lot ; (4) **vérifier D-53 en réel** (redémarrage du pod, le store survit-il ?) et fixer le
document de référence ; (5) **vérifier le filtre de profil de wikichat** (non vérifiable dans ce dépôt) par
un contrôle des gardiens ; (6) la routine de nuit n'est pas dans le dépôt : documenter son contrat et le
tester à la frontière (`test_contrat_wikichat.py` existe).

**Preuve.** Une proposition refusée n'est plus resservie ; un message d'application non préfixé n'est
pas pris pour la personne. **Retour.** Ajout seul. **Effort** M. **Décision requise** : où vit la routine
de nuit, dans ce dépôt ou ailleurs ?

### Lot 7 · Consolidation du code

**Travaux.** (1) Tests directs pour les 43 modules sans test, en commençant par la couche gateway
(`profiles`, `profile_tools`, `upstream/pool`, `compositions/*`, `commandes/connecteurs`, `apps/routes`) ;
chaque lot 1-6 ajoute ses tests, ce lot rattrape le reste ; (2) découper `api.py` par `APIRouter`, une
famille à la fois, **sans changer un test** (les 101 routes comptées par famille d'abord) ; (3) casser le
cycle de 30 modules en remontant les imports paresseux vers des interfaces (`Protocol`) à la couture
harnais ↔ lancements ↔ `mcp_sync` ; (4) constantes uniques (ports 8787/8790/8791/8080, plafonds) dans
`config` ; (5) classer les 38 handlers silencieux (journalise / relance / avale) ; (6) ruff + mypy avec
base figée, la CI n'échoue que sur le nouveau ; matrice Python 3.10-3.13 ou relèvement de
`requires-python` ; (7) l'échec `test_socle.py:185` : confirmer s'il vient de l'environnement ou d'un
défaut d'installation du module.

**Preuve.** Mêmes tests verts après chaque découpe ; couverture directe des modules cités. **Retour.**
Un routeur par PR. **Effort** L, en tâche de fond entre les autres lots.

### Lot 8 · Exploitation du pod

**Constat (organisation-cible, mesuré le 11/10, à revérifier).** 50 zombies après 1 h (D-59) ; plafonds
cumulés 12-15 Gio pour 8 de plafond (risque d'OOM qui redémarre le conteneur) ; un volume de 10 Gi à
74 % ; profils Chrome et écrans dans `/tmp`, perdus au redémarrage ; image `latest` avec dépendances en
`>=` ; pas de NetworkPolicy d'egress ; 7d3b4f6 (30/10) : « tests écrits, non exécutés », chart non
essayé sur un pod.

**Travaux.** Ramassage des orphelins (`tini` ou `waitpid`) ; budget de capacité global (refuser avant
l'OOM) ; arrêt gracieux (les tours passent en veille) ; image épinglée par empreinte, `requirements.lock`,
tag semver ; `securityContext` essayé sur un pod ; sauvegardes ; `/v1/diagnostic`.
**Preuve.** Zéro zombie après 24 h ; essai de charge sans OOM. **Effort** M-L. **À faire sur le pod.**

### Lot 9 · Documents et chantiers à trancher

**Travaux.** (1) Mettre à jour les documents périmés : `atelier-applications.md` (`X-Atelier-Conversation`
est posé, `mcp_sync.py:765` ; relais WS fusionné), `navigateur-atelier.md` § 1 (`chrome_proxy` n'existe
plus), `n8n.md` A10, `banc-d-essai-ml.md` (le code existe), `panneau.md` (propositions mêlées aux états) ;
(2) purger les contradictions de `architecture-transverse.md` (« page Gardiens » contre J-i, deux
ordonnanceurs, 14 outils contre 53 commandes, numérotation, plafond mémoire donné de trois façons,
persistance de wikichat) ; (3) une seule taxonomie rôles/profils ; (4) lexique d'interface : trancher
(S2 interdit « extension », « famille »… que l'écosystème montre ; « Code » contre « Projets »).

**Chantiers sans code, à décider un par un : garder, reporter, ou retirer du périmètre** : voix, n8n,
courtier GPU (arbitrage), commentaires sur tout, connecteur fait maison (J9), MCP Apps, « Montrer » de la
personne vers l'agent (J5), vérification des créations par le navigateur, vue de la carte, coût par
acteur au relais (T18), agents publiés. Le **laboratoire ML** est un produit à part (aucun import croisé
avec `atelier-src`) : décider s'il reste dans le monorepo (`plan-d-etude-ameliorations.md` § 5.1 prévoit
déjà un plan de séparation) ; corriger ses valeurs par défaut de recette (`regroupement="route"`,
`dedoublonner=False`, `corrections=True`, `labo/…/recette.py:59,64,66`), qui reproduisent la configuration
ayant causé la fuite d'octobre.

**Preuve.** Chaque document porte un état daté et ne contredit ni le code ni un autre document ; une
ligne par chantier dans `decisions.md`. **Effort** M, en continu.

### Lot 10 · La boucle d'auto-amélioration *(après les lots 1 à 4 au moins)*

Voir [`auto-amelioration.md`](auto-amelioration.md). Ses étapes 0 à 2 (constitution, tableau de mesure,
scénarios rejoués) peuvent commencer dès que le lot 4 fournit des états vrais ; ses étapes 3 à 6 (équipes,
promotion, voie automatique) exigent les lots 1 à 3 : une boucle qui agit avec un agent capable de se
faire passer pour la personne n'est pas un cadre.

## 2 bis. Lots ajoutés par la cible ([`cible.md`](cible.md))

### Lot 1 bis · Le miroir app / VS Code / terminal : un seul écrivain *(avec le lot 1)*

**Principe.** Un agent est un dossier + une session Claude Code (`cible.md` § 1.0) ; l'app, VS Code et le terminal
sont trois fenêtres sur la même session. Le transcript `.jsonl` du CLI est la seule vérité.
**Constat (rapporté, `fichier:ligne` dans `cible.md` § 2.3).** Aucun verrou entre surfaces (le verrou des tours est
un `threading.Lock` du seul processus de l'Atelier) ; le processus de l'app gardé 10 min ignore les écritures de
VS Code ; la synchro du home copie par date, fichier entier ; la marque `sdk-cli` n'est corrigée qu'au passage de
main ; `absorber_le_cli` écrit la fiche sans verrou ; deux chemins de configuration MCP ; l'identité est un
en-tête auto-déclaré.
**Travaux.** (1) verrou de conversation `verrous/<cli_id>.lock` (pid, surface, horodatage), pris à l'envoi, au
passage de main et par l'enveloppeur, péremption par `/proc/<pid>` ; (2) taille / mtime du transcript dans
l'empreinte du processus gardé ; (3) plus de copie par date pour `projects/` ; (4) `cli` posé à la naissance ;
(5) fiche versionnée ou verrouillée ; (6) un seul fichier de configuration effectif lu par les trois surfaces,
égalité testée à chaque ouverture ; (7) consigne d'ouverture supprimée après succès ; (8) `atelier-entetes-mcp`
devient le `headersHelper` de l'identité signée (renouvellement à chaque connexion).
**Preuve.** Tests : deux écrivains sur un même `.jsonl` ; un tour de l'app après un message VS Code avec processus
gardé ; une consigne d'ouverture qui échoue. **Retour.** Verrou désactivable par réglage. **Effort** M-L.

### Lot 3 bis · Gateway : un registre, une surcharge par connecteur, des classes pour tout outil

**Constat (rapporté).** Trois sources de connecteurs (catalogue YAML vide, registre SQLite, `mcp_registry.py`) plus le
choix par projet ; une « variante » ne fait que figer des valeurs ; la classe ne couvre que les `atelier_*` (le seul
outil amont réservé en dur est `expose_public`) ; `approval` / `elicit` validables par le modèle ; `timeout_seconds`,
`wait_until`, `ttl_seconds`, `allowed_roles` stockés sans être appliqués ; un seul mandataire borné (Onyxia).
**Travaux.** (1) registre unique déclaratif, le projet n'en est qu'une sélection ; (2) *overlay* par connecteur
(classe, arguments imposés cachés, schéma réduit, titre et description français) ; (3) classer tout outil amont
(table › annotations › regex), **défaut engageante** ; (4) moule de mandataire borné générique ; (5) journal et
plafonds des appels amont ; (6) appliquer ce que les compositions stockent déjà, et interdire au modèle de valider
`approval` / `elicit` ; (7) corriger les classes : `atelier_montrer` en réversible, outils Onyxia classés.
**Preuve.** Un connecteur déclaré une fois apparaît dans tous les profils autorisés, jamais dans les autres ; un outil
inconnu est engageant ; le modèle ne valide pas une approbation. **Effort** L. **Dépend de** lot 3.

### Lot 3 ter · Communication externe (Tchap et autres), après les lots 1 et 3

**Précondition.** Identité signée (lot 1) et mandataire générique (lot 3 bis) : sans eux, le secret reste dans
l'environnement de l'agent et le filtre ne protège rien.
**Travaux.** (1) connecteur déclaré dans le registre, capacité par *(connecteur, verbe, cible)* ; (2) tout envoi
engageant : aperçu, filtre de secrets, « À valider », plafonds, journal ; (3) lecture = donnée non fiable, enveloppée ;
(4) **contamination** : après lecture de contenu externe, pas d'action engageante dans le même tour sans nouvelle
confirmation ; (5) entrant : un message externe écrit dans « À valider » ou les événements, il ne lance jamais un agent
directement ; (6) v1 : envoi par un agent planifié sans personne = attente dans « À valider » ou interdit.
**À vérifier d'abord** : serveur Matrix de Tchap, compte bot, chiffrement de bout en bout, hébergement du serveur MCP.
**Effort** L.

### Lot 3 quater · Intégration GitHub : un projet, un dépôt, une identité par famille

**Constat (rapporté, `cible.md` § 5 bis).** Un PAT unique et global par pod, lisible par tout agent avec Bash ; un agent code
pousse où il veut ; aucune PR ni CI dans l'interface ; fusion locale jamais poussée ; connecteur GitHub MCP hérité par 8
projets sur 16.
**Travaux.** (1) un projet = un `origin` privé, lié à la création, marqué dans `projet.json` ; (2) identité GitHub par
famille (GitHub App pour les agents de l'Atelier, pas de jeton propre pour les agents code, jeton de la personne pour ses
gestes) ; (3) le secret hors de portée des agents (avec le lot 1) ; (4) classes de commande : clone et statut en lecture,
commit et push `agent/*` et PR en réversible, push inconnu, fusion et création de dépôt en engageante, étiquette `prod/…`,
bascule et suppression en réservée ; (5) la PR comme support de « À valider », la CI lue comme preuve au journal ;
(6) commits d'agent distinguables (trailer) ; (7) l'interface montre branche, retard, PR, CI, version en production ;
(8) retirer le connecteur GitHub MCP de l'héritage par défaut. **Preuve.** Un agent ne peut ni lire le jeton ni pousser sur
`main` ; une PR de gardien apparaît dans « À valider » avec sa CI. **Retour.** Le PAT actuel reste utilisable derrière un
réglage. **Effort** L. **Dépend de** lots 1 et 3 ; recoupe le lot 5 (brouillon / production).
**À vérifier d'abord** : si une GitHub App est installable sur SSPCloud, où héberger sa clé, si GitHub peut appeler le pod.

## 3. Ordre et dépendances

```
 Lot 1 identité ──► Lot 2 garde ──► Lot 3 rôle unique ──► Lot 4 états vrais ──► Lot 10 boucle
      │                                    │                      │
      └── (tests d'abord)                  └──► Lot 5 brouillon/production
 Lot 6 mémoire    ─ en parallèle dès le lot 4 (états vrais) ; D-53 et filtre wikichat à vérifier en réel tout de suite
 Lot 7 consolidation ─ en continu, un routeur ou un module par PR
 Lot 8 pod        ─ sur le pod, à interleaver avec les essais des lots 2 et 3
 Lot 9 documents  ─ à chaque lot, la doc du lot est mise à jour dans la même PR
```

**Règle de travail.** Une PR courte par étape, avec : le test qui échoue d'abord, le correctif, l'état
dans le document concerné, le retour arrière. Rien n'est écrit « fait » sans la preuve du lot.

## 4. Ce qui se vérifie sur le pod avant de bâtir

| Question | Pourquoi | Lot |
|---|---|---|
| Les réglages managés s'appliquent-ils en `-p` ? le `deny` l'emporte-t-il en `bypassPermissions` ? | tout le lot 2 en dépend | 2 |
| La chaîne clé → cookie → « personne » fonctionne-t-elle en réel ? (test local d'abord) | gravité du lot 1 | 1 |
| Le store de wikichat survit-il à un redémarrage ? | contradiction entre trois documents (D-53) | 6 |
| Le filtre de profil de wikichat est-il actif ? | non vérifiable dans ce dépôt | 6 |
| Que casse `drop: ALL` / `allowPrivilegeEscalation: false` ? | chart durci le 30/10, non essayé | 8 |
| Combien de mémoire à la charge maximale ? | plafonds additionnés > plafond du pod | 8 |

## 5. Décisions à prendre par Nicolas

0. **Surcharge de session** : peut-elle seulement *restreindre* les défauts du projet, ou aussi *élargir* jusqu'au plafond du projet (avec « À valider ») ? Un agent de l'Atelier peut-il recevoir une capacité sur un projet sans passer par « À valider » quand elle est en lecture seule ? (Recommandation : élargir = engageant, restreindre = libre, lecture seule = réversible.)

1. **Second facteur** pour l'ouverture d'une session « personne » (lot 1) : jeton à part, passkey, ou
   autre ? (Recommandation : une clé de session distincte de celle des agents, retirée de leur
   environnement, avant tout mécanisme plus lourd.)
2. **Partage à des tiers** dans le périmètre ou non (lot 5) ?
3. **Routine de nuit de wikichat** : dans ce dépôt ou ailleurs (lot 6) ?
4. **Laboratoire** : rester dans le monorepo ou se séparer (lot 9) ?
5. **Chantiers sans code** : lesquels retirer du périmètre pour que la finition soit finie ?
6. **Lexique** (S2 contre l'écosystème, « Code » contre « Projets ») : lequel gagne ?

## 6. Limites de ce plan

- Les constats de sécurité (lot 1, lot 2) sont des **lectures**, une seule vérifiée dans le code par moi ;
  aucune chaîne n'a été exécutée. Le premier travail est de les confirmer ou de les réfuter.
- Les rapports sur les agents, les créations et la mémoire viennent de lecteurs ; les écarts cités avec
  `fichier:ligne` sont à rouvrir avant correction.
- La routine de nuit de wikichat, son filtre de profil et le Pilote sont hors de ce dépôt : leur état est
  inconnu d'ici.
- Les mesures du pod datent d'octobre ; plusieurs sont probablement périmées.
- Les efforts sont des ordres de grandeur, pas des engagements.
