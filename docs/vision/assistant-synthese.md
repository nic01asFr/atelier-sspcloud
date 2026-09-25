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
