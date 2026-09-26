# L'Assistant de l'Atelier — synthèse

Synthèse du 25/09/2026. **Proposition, non implémentée** : l'implémentation viendra une fois la
vision validée. Elle réunit :

- `assistant-cadre.md` : l'idée de Nicolas et ses précisions ;
- `assistant-role.md` : rôle et expérience ;
- `assistant-contexte.md` : contexte et mémoire ;
- `assistant-harness.md` : harness, outils et modèles, mesurés sur le pod ;
- les structures communes de `architecture-transverse.md`.

## 1. Ce qu'est l'Assistant

**La porte d'entrée de l'Atelier.** L'Atelier s'ouvre sur son fil, et on peut le solliciter depuis
partout, à l'écrit comme à la voix. Il comprend l'ensemble de l'Atelier de la personne : ses
projets, leurs liens, ses créations, ses connecteurs, ses agents et ses tâches automatiques.

Il agit par les commandes de l'Atelier : créer un projet déjà cadré, un agent, un connecteur, une
application, régler, lier, clore. Il confie le travail de code à des agents code, suit ce travail
et en rend compte.

« Jarvis » est une illustration. Les capacités viennent de l'Atelier au complet, et l'Assistant
en est l'interface :

| Capacité perçue | Brique qui la porte | Où |
|---|---|---|
| Il connaît tout mon Atelier | la carte : projets et liens par wikichat, état opérationnel par l'Atelier | `architecture-transverse.md` §1.3 |
| Il se souvient | capitalisation des conversations, axes de connaissance, closures, mémoire validée | wikichat (§1.6 bis) |
| Il agit | catalogue de commandes, avec classe, inverse et preuve | Atelier (§1.8) |
| Il fait faire | agents code lancés par l'Atelier, suivis par les fils wikichat | lot D |
| Il me prévient | gardiens et détection de changements | exécuteur, wikichat |
| Il me montre | panneau, vues, navigateur | Atelier |
| Il m'écoute et me parle | STT et TTS comme création serveur, par le chemin d'affichage | Atelier (T4) |
| Il travaille pendant que je dors | routines et triggers plafonnés | wikichat |

## 2. Les règles qui le rendent fiable

1. **Il agit seul seulement si cinq conditions sont réunies** (`assistant-role.md` §3.2) :
   - une commande existe ;
   - elle touche un objet de l'Atelier, pas le contenu d'un dépôt ;
   - elle est courte ;
   - elle a une inverse ;
   - elle rend une preuve.

   Dans les autres cas, il confie le travail à un agent code, avec un bon de commande.
2. **Chaque action produit une carte**, émise par la commande et non rédigée par le modèle, avec
   « Voir » et « Annuler ».
3. **Trois classes d'action**, portées par les commandes :
   - réversible : il agit ;
   - engageante : aperçu, puis « Oui » ;
   - réservée : la personne seule décide.

   Au-delà de trois actions, il présente d'abord un plan.
4. **Il n'édite jamais un dépôt de projet.** `Edit`, `Write` et `Bash` sont refusés hors de son
   dossier.
5. **Il dit « vérifié » seulement avec une preuve.** Pour une livraison, il peut se servir du
   navigateur (`navigateur-verif`).
6. **Aucun secret** : les transcripts sont filtrés à la source (T10). Aucun accord ne se donne à
   la voix.
7. **Des plafonds partout**, affichés.

## 3. Son contexte

Le contexte est préparé par le code, pas recalculé par le modèle (`assistant-contexte.md`).

| Couche | Contenu | Budget |
|---|---|---|
| C0 et C1, toujours présentes | harness, consignes, profil de la personne, vue synthétique de la carte, « À valider » | environ 20 000 jetons (estimation) |
| C2, à chaque tour | ce qui a changé : courrier, alertes, état | 0 jeton s'il n'y a rien de neuf |
| C3, à la demande | détail d'un objet, fiches, décisions | environ 450 jetons par rappel |

- **Compaction** : vers 90 000 jetons, sous la dérive observée à 105 000. Le contexte C1 est
  relu après chaque compaction, grâce aux imports `@`.
- **Sessions** : courtes, une par sujet, adossées aux fiches de mémoire.
- **Mémoire** : le modèle ne fait que proposer ; les propositions arrivent dans « À valider ».
- **Voix** : même conversation et même mémoire que l'écrit.

## 4. Son harness (mesuré)

Mesures du 25/09 sur le pod, un essai par case : ce sont des indications, pas des statistiques.

- **Modèle** : `qwen3-6-35b-moe`, thinking à 0, effort `medium`. Premier jeton en 0,7 s environ.
  Repli et tâches de fond : `qwen3-8-27b`, 2 à 3 fois plus lent. Captures : `qwen3-vl`
  (supposé).
- **Outils : les méta-outils de l'Atelier** (orientation de Nicolas, 25/09, qui remplace les
  « familles par `list_changed` » de `assistant-harness.md`).
  - L'Assistant a les outils de l'Atelier, enrichis au besoin. Il atteint **l'ensemble** des
    outils (connecteurs, `atelier_*`, wikichat) par les deux méta-outils de la passerelle :
    `gateway_find_tools` et `gateway_call_tool`.
  - Son contexte reste petit et stable, quelle que soit la taille du pool.
  - Garanties déjà dans le code (`mcp/gateway.py`, `tool_search.py`) :
    - `gateway_call_tool` passe par le même garde de profil que tout appel, et n'élargit jamais
      le périmètre ;
    - un nom inconnu est refusé, avec des suggestions ;
    - une erreur d'arguments rend le schéma pour se corriger ;
    - la recherche ne classe que les outils déjà permis.
  - À ajouter : la classe d'action (§1.8 du transverse) est appliquée **par le serveur** à la
    commande appelée. Passer par `gateway_call_tool` ne contourne donc jamais un « aperçu puis
    Oui ».
  - Ce qui reste à mesurer (H0), avec les vrais méta-outils de la passerelle et 5 essais par
    cas. La mesure indicative donnait 6 réussites sur 9, avec trois types d'échec :
    - l'outil appelé sous un nom inventé : **déjà couvert** par le refus du serveur ;
    - l'appel sans nom : **déjà couvert** ;
    - la réponse de mémoire sans chercher : à traiter par la consigne (« ne conclus jamais qu'une
      capacité manque sans avoir cherché », déjà dans les instructions de la passerelle) et par
      la mesure.
  - Si la mesure reste insuffisante : `gateway_find_tools` peut aussi **charger** les outils
    trouvés dans la liste déclarée, par `list_changed`. L'interface reste la même (deux outils)
    et la fiabilité rejoint celle des outils déclarés. Option sous réserve de mesure : une
    recherche assistée par `qwen3-embedding-8b`, servi sur SSPCloud, si la recherche lexicale
    rate des intentions.
- **Coût d'entrée** : environ 6 000 jetons de prompt et 15 700 pour les outils natifs ; une
  commande sobre coûte environ 100 jetons. Un Assistant ouvert aujourd'hui avec le pool entier
  paierait environ 76 000 jetons avant son premier mot.
- **Commandes de création cadrée**, spécifiées : `atelier_projet_creer`, `agent_creer`,
  `agent_activer`, `connecteur_ajouter`, `projet_modifier`.
- **Oral** : le même processus Claude Code, qui reste vivant entre les tours. Le chemin rapide
  n'utilise pas de modèle : un accusé immédiat, et des réponses d'état calculées depuis la carte.
  - Le premier poste de latence est la tranche STT de 3 s.
  - Cible : 2,5 à 3,5 s jusqu'au premier mot (supposé).
- **Même Assistant** dans l'Atelier, dans VS Code et au terminal.

## 5. Ce qu'il faut construire, dans l'ordre

Chaque étape s'appuie sur des briques existantes. Elle les branche, les répare ou les expose ;
elle ne les double pas.

| Étape | Contenu | Prérequis |
|---|---|---|
| **A0 Mesurer** | effort `xhigh` et latence ; 5 essais par case ; noyau réel ; bout en bout de l'oral | — |
| **A1 Le socle** | déploiement du 26/09 : hooks, identité, secrets ; lot W de wikichat (connaissance, stockage, jobs directs) | go de Nicolas |
| **A2 La carte** | couche wikichat (`/api/cartographie`, vrais liens) et couche Atelier, assemblées (`/api/carte`, `atelier_carte`) | A1 |
| **A3 Les commandes** | catalogue unique avec classe, inverse, preuve et carte d'action ; commandes de création cadrée ; profil `assistant` et familles par `list_changed` | A2, structure de projet (lot G) |
| **A4 L'Assistant écrit** | dossier `wikichat-memory` (auteur unique), `CLAUDE.md` et imports C1, accueil sur son fil, « À valider », délégation par le lot D | A3 |
| **A5 La mémoire** | capitalisation des conversations dans wikichat, filtre des secrets, « Ma mémoire » | A4 |
| **A6 Tableaux de bord** | vues système Atelier et projet dans le panneau, ouvertes et commentées par l'Assistant | A2, panneau J2 |
| **A7 La voix** | STT et TTS comme création serveur authentifiée, visio dans le panneau, chemin rapide sans modèle | A4, A6, panneau J5 |

## 6. Décisions pour Nicolas

Les trois équipes posent 25 questions. Dédoublonnées, elles se ramènent à dix, chacune avec une
recommandation.

**Pour démarrer (A0 à A2)**

1. **Domicile et mémoire publiée : déjà tranché** (`atelier-wikichat-alignment.md` §10 et §11,
   02/09).
   - Le dossier de l'Assistant **n'est pas un dépôt, à dessein**. Son contenu est de la mémoire de
     session, tenue par wikichat.
   - Le dépôt GitHub `wikichat-memory` est une **publication** de la mémoire, exportée et
     assainie par wikichat (`export-memory`, `publish-memory`), selon une règle de
     synchronisation (« `--no-push` d'abord »).
   - La question « domicile versionné » de `assistant-contexte.md` est donc retirée.
   - Il reste un point d'exécution, pas de principe : aujourd'hui, c'est **le poste** qui publie
     toutes les 15 min, depuis `Github Repositories/wikichat`, et la publication a divergé (28
     commits d'avance, 3 de retard, 19 axes en double). *Recommandation* : un seul éditeur de la
     publication, le wikichat du pod, qui voit toute la mémoire. On arrête la tâche du poste
     après une réconciliation unique. Pour le chemin du dossier de l'Assistant, on garde celui
     que l'Atelier utilise déjà (à constater sur le pod).
2. **Les modèles.** Liste relevée sur le pod le 25/09 (`/api/models`, 7 modèles) :

   | Modèle | Rôle proposé |
   |---|---|
   | `qwen3-6-35b-moe` | **l'Assistant** (déjà le défaut du pod) : le meilleur mesuré, premier jeton vers 0,7 s |
   | `agent` | à éviter dans Claude Code : c'est un modèle OpenWebUI construit sur `qwen3-6-35b-moe`, avec ses propres réglages et outils intégrés, qui s'ajoutent à ceux du harness |
   | `qwen3-8-27b` | tâches de fond : capitalisation nocturne, extraction. Il est 2 à 3 fois plus lent, donc jamais à l'oral |
   | `qwen3-vl` | lecture des captures et des vues montrées, dans un sous-agent |
   | `chandra-ocr-2` | documents scannés déposés par la personne |
   | `qwen3-embedding-8b` | recherche sémantique : mémoire, connaissance wikichat, et en option recherche d'outils |
   | `gemma4-26b-moe` | marqué « test » ; échoue dans Claude Code |

   `qwen3-cursor` n'est plus servi. Le pod impose l'effort `xhigh` à `qwen3-6-35b-moe`
   (`modelSettings`) : mesurer son effet sur la latence et la qualité avant de le changer.
3. **Les outils : méta-outils de l'Atelier** (orientation de Nicolas, voir §4). *À valider* :
   - une seule porte, la passerelle, et ses deux méta-outils ;
   - la classe d'action appliquée par le serveur ;
   - la mesure H0 avant de décider s'il faut, en plus, charger les outils trouvés.

4. *(fusionnée avec la décision 3)*

**Pour l'expérience (A3, A4)**

5. **L'accueil devient le fil de l'Assistant**, et « Code » devient « Projets ».
   - *Recommandation* : oui, derrière un réglage le temps de la transition.
6. **Lancer un agent code sans accord**, quand la personne l'a demandé, en brouillon et dans les
   plafonds ?
   - *Recommandation* : oui. La délégation est annoncée par une carte d'action avec « Arrêter ».
7. **Pour les propositions en attente** : l'Assistant peut-il refuser seul, sans jamais accepter ?
   - *Recommandation* : oui.
8. **L'écriture de l'Assistant.** `Edit` et `Write` dans son propre dossier, ou tout par des
   commandes ?
   - *Recommandation* : son dossier seulement, pour ses notes de travail.
   - La mémoire et les objets de l'Atelier passent par des commandes.

**Pour la mémoire et la voix (A5, A7)**

9. **La mémoire ne s'écrit que par validation**, et la capitalisation nocturne est plafonnée.
   - Plafond proposé : 20 conversations de 30 000 jetons au plus, sur `qwen3-8-27b`.
   - *Recommandation* : oui. Les faits extraits par le code (projet créé, décision) s'enregistrent
     d'office ; les préférences et interprétations passent par « À valider ».
   - Les conversations des agents code sont capitalisées aussi, en fiches de projet.
10. **La voix.**
    - Aucun audio conservé.
    - Aucun accord donné à l'oral ; une mémoire ne se valide qu'à l'écran.
    - Latence visée : moins de 2 s pour l'accusé, moins de 3,5 s pour le premier mot.
    - *Recommandation* : oui aux trois.

## 7. Évaluation

| Critère | Verdict |
|---|---|
| **Cohérent** | Oui. L'Assistant ne crée aucune brique parallèle : il est l'interface des structures communes (carte, commandes, journal, « À valider », chemins) et des briques de wikichat. |
| **Envisageable** | Oui. Les mesures montrent que le modèle choisit bien ses outils jusqu'à 50, que `list_changed` marche, et que la latence du modèle est bonne. Le plus gros travail est de brancher : la carte, les commandes et le lot W. |
| **Souhaitable** | Oui. Aujourd'hui il faut connaître l'Atelier pour s'en servir ; l'Assistant renverse cela. |
| **Désirable** | Oui, si les cartes d'action, « Annuler », les preuves et la sobriété sont tenues. La voix et les vues montrées en visio le rendent vivant. |
| **Possible** | Pour Nicolas, dès A4. Pour des personnes qui ne codent pas, une fois A3 (commandes cadrées) et le lexique en place. |

## 8. État (vague 3, équipe A, branche `v3-assistant`, 26/09/2026)

Lot A4 : l'Assistant écrit. « Vérifié » veut dire exécuté et vu fonctionner (tests de
comportement, ou essai réel nommé) ; « non vérifié », écrit seulement.

### 8.1 Ce qui est fait

**Le dossier de l'Assistant** (`mcp_gateway/atelier/assistant.py`). Il reste celui que l'Atelier
utilise déjà, `settings.assistant_root` : `~/work/wikichat-memory` (constaté sur le pod, 7
conversations dans `assistant/sessions/`). Le dossier `~/work/projects/wikichat-memory` du pod
est un reste de l'ancienne reprise dans VS Code : à ranger. Le dossier n'est **pas un dépôt**
(S6). Tout y est généré par l'Atelier, au démarrage et avant chaque tour :

| Fichier | Contenu |
|---|---|
| `CLAUDE.md` | imports `@atelier/consignes.md`, `@atelier/outils.md`, `@atelier/carte.md`, `@atelier/a-valider.md`, puis `# Compact instructions` propres à l'Assistant. Un `CLAUDE.md` étranger est mis de côté (`CLAUDE.md.avant-atelier`), jamais écrasé |
| `atelier/consignes.md` | le rôle, court : les cinq conditions (§3.2 d'`assistant-role.md`), les trois classes, ce qu'il ne fait jamais, le ton, le lexique S2 |
| `atelier/outils.md` | la **consigne forte** (« Ne conclus JAMAIS qu'une capacité manque sans avoir cherché… deux formulations, dont une en anglais »), le mode d'emploi de `gateway_find_tools` puis `gateway_call_tool`, une table demande → commande, la délégation |
| `atelier/carte.md` | la forme synthétique d'`atelier_carte`, datée, recalculée avant chaque tour de l'Atelier (8 s au plus ; sinon la carte d'avant reste, avec son heure) |
| `atelier/a-valider.md` | la file « À valider », bornée à 2 000 caractères, avec « tu peux refuser, jamais accepter » |
| `notes/` | le seul endroit où il écrit (A-6) |
| `.claude/settings.json` (racine et chaque conversation) | refus : `Bash`, `NotebookEdit`, `WebSearch`, 16 natifs qui ne lui servent pas, l'écriture dans `projects/`, `bin/`, `mcp/`, les secrets et ses propres consignes ; permis : `Read`, `Glob`, `Grep`, `mcp__atelier`, `mcp__wikichat`, l'écriture dans `notes/` |

Les conversations vivent dans `assistant/sessions/<id>/` (création et reprise, `sessions.py`) ;
chacune reçoit ses réglages dès sa naissance, pour VS Code et le terminal. Le `.mcp.json` reste
celui de `configuration_du_profil` (profil `assistant`). L'ancienne section de contexte écrite
dans le dossier d'une conversation est retirée : une seule consigne, celle de la racine.

**Deux réglages natifs, trouvés par la mesure**, posés dans `~/.claude.json` pour chaque dossier
de l'Assistant (`assistant.APPROBATIONS`) :

- `hasClaudeMdExternalIncludes*` : le `CLAUDE.md` de la racine est lu depuis le dossier d'une
  conversation (Claude Code remonte les parents), mais ses imports sont **hors** de ce dossier.
  Sans approbation, Claude Code les ignore en silence : l'Assistant ne voyait ni sa carte ni ses
  consignes (mesure m00) ;
- `hasTrustDialogAccepted` : sans lui, Claude Code **ignore les `allow`** du
  `.claude/settings.json` d'un dossier (« this workspace has not been trusted ») ; les refus, eux,
  s'appliquent. La clé est lue au dossier exact, sans remonter aux parents (lu dans le binaire
  2.1.282).

**Budget C1.** Calculé par le code : environ 2 500 unités avec la carte réelle du pod
(`GET /v1/assistant` le rend), 6 000 au pire (carte au plafond, file pleine), testé. Mesuré au
relais : §8.2.

**Délégation.** Par `atelier_lancer_agent` (lot D, classe engageante) : un premier appel rend un
aperçu ; la personne dit « Oui » (bouton de la carte, ou réponse écrite) ; le suivi passe par
`atelier_lancements` ; le compte rendu, par la carte d'action. Le bon de commande en sept lignes
est dans `outils.md`. Écart avec A-4 (« sans accord ») : le lot D a fait la commande engageante ;
on suit le code.

**Interface (A-3).** `?view=assistant` ouvre le fil de l'Assistant dans l'écran des
conversations : même fil, même composeur, même panneau (`views/assistant.js`, `state.espace`). La
colonne de gauche montre ses conversations et le réglage « Ouvrir l'Atelier sur l'Assistant »,
**désactivé par défaut**, réservé à la personne (`PUT /v1/assistant/reglages`, 403 à la clé).
Activé, l'Atelier s'ouvre sur l'Assistant quand l'adresse ne dit rien, l'onglet passe en tête et
« Code » devient « Projets ». Les cartes d'action du fil (`views/assistant-cartes.js`) offrent
« Voir » et « Annuler » (par `atelier_annuler`, au nom de la personne) ; l'aperçu d'une commande
engageante offre « Oui » (`POST /v1/commandes/confirmer`) et dit « Rien n'est fait », sans jeton
ni nom de commande à l'écran. La carte garde l'issue quand le fil se redessine.

**Vérificateur.** `coherence.ecarts_du_dossier` signale un Assistant qui a `Bash`, `NotebookEdit`
ou `WebSearch`.

**Profil allégé** (`commandes/profils.py`, `HORS_LISTE_ASSISTANT`). `atelier_envoyer`,
`atelier_transcript`, `atelier_suivre` et `atelier_ouvrir` ne sont plus **déclarés** à
l'Assistant : il délègue par `atelier_lancer_agent`. Ils restent **permis** : `gateway_find_tools`
les trouve avec leur schéma, et `gateway_call_tool` les appelle, par les mêmes gardes. Sans
conversation (passerelle, claude.ai), rien ne change. Gain, compté sur les schémas : 41 → 37
commandes déclarées, 26 924 → 24 227 caractères, soit **2 697 caractères, environ 790 unités** par
requête (`atelier_envoyer` à lui seul : 349).

**Contre l'invention après un refus.** `consignes.md` porte une règle : un appel refusé ou en
échec ne s'est pas produit ; aucun résultat sans carte d'action ni preuve ; dire « refusé », ou
« en attente de votre Oui ». À l'écran, un message de l'Assistant qui affirme un résultat (« c'est
fait », « projet créé », « j'ai lancé », « vérifié »…) sans carte d'action dans le même tour (depuis
le dernier message de la personne) est marqué **« non vérifié »** (`assistant-cartes.nonVerifie`).
Une négation juste avant (« rien n'est fait », « non vérifié », « quand ce sera créé ») ne compte
pas. Le cas d4-a du pod (« Lien créé… vérifié » après un refus) est marqué ; testé.

### 8.2 Mesures sur le pod (26/09, CLI 2.1.282, `qwen3-6-35b-moe`, effort `medium`)

Protocole : 20 `claude -p` dans un dossier jetable (`/var/tmp/am/`, supprimé depuis), avec un
`CLAUDE_CONFIG_DIR` jetable et les hooks désactivés. Le dossier de l'Assistant y est celui que
génère la branche, avec la **vraie carte du pod** (2 213 caractères, 651 unités, calculée en
lecture seule par `carte.py`). Les outils sont **exactement ceux du profil `assistant`** : 41
commandes du vrai catalogue et 7 méta-outils, soit 48 outils. Ils sont servis par un serveur de
mesure qui n'exécute rien, car la clé du propriétaire, nécessaire pour joindre la vraie porte
`/mcp`, n'a pas été utilisée. « À valider » (1 proposition) et les lancements (1 en cours, 1 fini)
sont simulés. Les jetons sont ceux que rend le relais, qui les estime quand le flux n'en donne pas.

**Coût d'entrée** (« Réponds en une ligne, sans outil : l'heure de ta carte, le nombre de
projets »)

| Essai | Réglages | Outils annoncés | Entrée (relais) | Premier mot | Réponse |
|---|---|---|---|---|---|
| m00 | refus de `Bash`, `NotebookEdit`, `WebSearch` ; imports non approuvés | 67 (19 natifs, 48) | 26 655 | 2,6 s | fausse : ne voit pas sa carte |
| m01 | et imports approuvés | 67 | 29 006 | 2,2 s | juste, sans outil |
| m02 | et 13 natifs refusés (Task, Skill, Cron…, Workflow…) | 54 (6 natifs, 48) | **16 015** | 1,7 s | juste, sans outil |

- C1 mesurée : 29 006 − 26 655 = **2 351**.
- Les 13 natifs retirés pesaient **12 991**.
- C0 + C1 tient sous 20 000 **sans le pont wikichat natif**. Avec lui (51 outils, environ 10 000
  calculés, `assistant-harness.md` §2.2), on arrive vers 26 000 : voir §8.4.

**Six demandes types, 17 essais.** Pendant ces essais, les `allow` du dossier étaient ignorés : la
confiance n'était posée que sur la racine, alors que la clé est lue au dossier exact. Chaque
commande a donc été **tentée, puis refusée par le CLI**. On mesure le choix de la commande et de
ses arguments, les jetons et la latence, mais pas le parcours de bout en bout. Le correctif
(`hasTrustDialogAccepted` sur chaque dossier) est dans le code et testé ; il n'a pas pu être
rejoué, les 20 essais étaient consommés.

| Demande | Bonne commande, bons arguments | Appels tentés | Entrée, 1re requête | Entrée cumulée | Premier mot | Remarques |
|---|---|---|---|---|---|---|
| « Où en est le projet Lecteur Grist ? » | 3/3 : `atelier_carte(forme=projet, projet=projet-sans-nom-5)` | 1, 2, 2 | 15 989 | 32 000 à 49 000 | 2,8 à 3,7 s | après le refus, répond juste depuis la carte (2/3) |
| « Crée un projet cadré Budget 2027 » | 3/3 : `atelier_projet_creer(titre, objectif, gabarit)` | 1 | 16 006 | 32 300 | 2,6 à 3,8 s | après le refus, **invente un aperçu** (la commande est réversible) |
| « Quels agents tournent ? » | 3/3 : `atelier_lancements(etat=en_cours)` | 2 à 4 | 15 990 | 49 000 à 98 000 | 2,2 s ; 2,4 s ; **47,8 s** | l'essai b dérive : 10 397 unités de sortie |
| « Relie Lecteur Grist et BigStarter » | 3/3 : `atelier_projets_lier(projet-sans-nom-5 → projet-sans-nom-2)` | 1 ou 2 | 15 990 | 32 300 à 49 000 | 3,0 à 3,5 s | essai a : « Lien créé… vérifié » **malgré le refus** |
| « Délègue la correction du bouton Exporter CSV » | 3/3 : `atelier_lancer_agent(projet-sans-nom-5, bon de commande de 554 à 662 caractères, 15 min)` | 3 ou 4 : il regarde d'abord (carte, créations, conversations) | 16 010 | 66 000 | 2,8 à 3,7 s | bon de commande en sept lignes 3/3 ; **aucune confirmation tentée** (0/3) ; demande « Oui » 3/3 ; une fois `Glob` sur son propre dossier |
| « Qu'est-ce qui attend mon accord ? » | 2/2 | 0 ; 2 | 15 989 | 16 000 ; 48 600 | 1,7 s ; 4,0 s | sans outil, depuis C1 (a) ; n'accepte jamais, propose de refuser |

- **Choix de la commande : 17 sur 17**, arguments justes, slugs retrouvés depuis la carte, aucun
  nom inventé. Les commandes sont déclarées : aucun passage par `gateway_call_tool`.
- **Premier mot** : médiane d'environ 3,0 s depuis le lancement du processus (dont 0,4 s
  d'init), avec un pic à 47,8 s.
- **Aperçu de la délégation** : pas rendu sur le pod, puisque le CLI a refusé l'appel avant le
  serveur. Le rendu et « rien n'est fait » sont vérifiés par les tests.
- **Risque constaté** : après un refus, le modèle invente parfois un résultat (aperçu fictif,
  « lien créé »). Avec les `allow` actifs, la commande rend sa carte ; la consigne « vérifié
  seulement avec une preuve » ne suffit pas seule.

### 8.3 Vérifié, non vérifié

- **Vérifié par les tests** (`tests/test_assistant.py`, 21 tests ; `tests/js/assistant.suite.mjs`,
  71 vérifications ; `test_profils_acces.py` pour le profil allégé) :
  - fichiers générés et idempotents, imports qui désignent des fichiers existants,
    `# Compact instructions`, `CLAUDE.md` étranger mis de côté ;
  - consigne forte ; chaque commande citée existe et est permise au profil `assistant` ;
  - réglages sur la racine et sur chaque conversation, approbations dans `~/.claude.json` ;
  - carte et « À valider » rafraîchies avant un tour ; une carte en panne ne bloque pas le tour ;
  - budget C1 au pire cas ;
  - création et reprise d'une conversation ;
  - délégation : aperçu, « Oui » de la personne, suivi, jeton à usage unique ;
  - réglage d'accueil : désactivé par défaut, réservé à la personne ;
  - vue : espace, arrivée, liste, gestes, cartes « Voir », « Annuler », « Oui », lexique S2 ;
  - écart du vérificateur ;
  - les quatre commandes absentes de la liste de l'Assistant, trouvées et appelées par les
    méta-outils ;
  - la règle contre l'invention, et la marque « non vérifié » (affirmation, négation, preuve dans
    le tour, tour suivant, message en cours).
- **Vérifié sur le pod** (lecture seule, CLI 2.1.282) : les refus retirent les outils de la liste ;
  les imports du `CLAUDE.md` parent ne sont lus qu'approuvés ; la carte réelle et C1 tiennent dans
  le budget ; le choix des commandes (§8.2).
- **Non vérifié** :
  - un tour réel de bout en bout avec `hasTrustDialogAccepted` sur le dossier de la conversation ;
  - l'interface dans un vrai navigateur ;
  - VS Code (mêmes approbations dans `~/.claude.json` : supposé) ;
  - la relecture des imports après une compaction avec `qwen3` ;
  - l'effet de la règle contre l'invention sur `qwen3` (aucun essai restant) ;
  - la réécriture de `~/.claude.json` par un `claude` en cours, qui peut effacer une approbation
    (déjà vu pour `enabledMcpjsonServers`) : elle est reposée avant chaque tour.

### 8.4 Pour Nicolas

1. **Le pont wikichat natif** coûte environ 10 000 unités par requête à l'Assistant (51 outils) :
   C0 + C1 passerait vers 26 000. Faut-il le garder, le filtrer côté wikichat
   (`WIKICHAT_PROFIL=assistant`, équipe M), ou passer wikichat par les méta-outils ?
   *Recommandation* : le filtrer à une dizaine d'outils.
2. **Délégation sans accord (A-4)** : la commande du lot D est engageante. Faut-il la garder ainsi
   (un « Oui » par délégation), ou l'alléger en réversible pour l'Assistant quand la personne l'a
   demandé ?
3. ~~Les commandes anciennes au profil~~ : retirées de la liste déclarée (décision du coordinateur,
   26/09), joignables par les méta-outils ; gain d'environ 790 unités (§8.1).

### 8.5 Déploiement sur le pod

1. Fusionner `v3-assistant`, déployer le code de l'Atelier et redémarrer le service.
2. Au démarrage, l'Atelier écrit le dossier `~/work/wikichat-memory` (gabarit, réglages, carte) et
   pose les approbations dans `~/.claude.json`. Rien d'autre n'est touché.
3. Vérifier `GET /v1/assistant` (C1 dans le plafond). Ouvrir `/?view=assistant` et écrire « quoi de
   neuf ? » : la réponse vient sans outil, depuis la carte. Demander une délégation : une carte
   d'aperçu s'affiche, avec « Oui ».
4. Lancer `atelier-verifier-coherence` sur le dossier `assistant` : pas de `Bash`, les méta-outils
   présents.
5. Ranger `~/work/projects/wikichat-memory`, reste de l'ancienne reprise dans VS Code.
6. Activer « Ouvrir l'Atelier sur l'Assistant » quand la transition est jugée faite.
