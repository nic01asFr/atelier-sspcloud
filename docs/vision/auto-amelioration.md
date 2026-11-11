# L'Atelier qui s'améliore en continu : une boucle de rétroaction, de tests, et ses garde-fous

> **État au 11/11/2026. Proposition, rien n'est implémenté, et elle vient *après* la finition de l'Atelier actuel** (lots 1 à 6 de [`etat-des-lieux-et-roles.md`](etat-des-lieux-et-roles.md) §6 : ils fournissent les signaux fiables dont la boucle a besoin, par exemple « fini » qui dit vrai). Ce document prolonge
> [`gardiens.md`](gardiens.md) §3.6 (l'auto-amélioration par récurrence, étapes G5 et G6) et ne le
> remplace pas : là, un gardien *propose* une correction quand un problème revient ; ici, on pose
> la question plus large, celle d'une boucle qui tourne **en arrière-plan, sans arrêt**, à partir
> d'objectifs et de principes donnés par la personne. Les constats sur l'existant sont des lectures
> du dépôt (code, docs) ; ce qui reste à mesurer est marqué « à mesurer ».

## En une phrase

On écrit une fois **ce qu'on veut** (objectifs, principes, limites) ; l'Atelier **mesure** en continu
où il en est, **propose** des changements sur des branches, les **met à l'épreuve** contre des
scénarios qu'il ne peut pas truquer, ne **promeut** que ce qui progresse sans rien casser, et
**revient en arrière** seul si la mesure se dégrade. La personne fixe le cap et garde les clés ;
elle ne pilote pas chaque tour.

## 1. Le problème, vu par la personne

1. *« Je corrige le même genre de défaut tous les mois. »* Le registre des défauts compte plus de
   cinquante entrées ; sept causes expliquent presque tout (permission sans réponse, « fini » qui
   ment, contexte jamais mis en cache…). Chaque lot est un travail manuel de relecture, puis de
   correction. Rien ne dit si la correction de septembre tient encore en novembre.
2. *« L'Atelier m'annonce que c'est réglé, et ça ne l'est pas. »* Les fins de lancement « mentent »
   (D-09) : « fini » veut dire « le processus s'est arrêté ». Une boucle d'amélioration bâtie sur ce
   genre de signal améliorerait ce qui *paraît* bien.
3. *« Je veux dormir pendant que ça progresse, sans me réveiller devant une catastrophe. »* Le
   danger d'une boucle sans fin n'est pas qu'elle échoue : c'est qu'elle **réussisse sur la
   mauvaise mesure** (un test affaibli pour qu'il passe, un seuil relevé, un contrôle supprimé) et
   que tout reste vert.

## 2. Ce qui existe déjà

| Brique | Rôle dans la boucle | Statut |
|---|---|---|
| Exécuteur des **gardiens** (`mcp_gateway/gardiens/`) : ordonnanceur, contrôles en code, journal JSONL en ajout seul, homme mort, 0 jeton | les **capteurs** : ils observent sans modèle | en service (vagues 1 et 2) |
| Récurrence par classe d'empreinte, « règle de clôture d'incident » (`gardiens.md` §3.6) | l'**hypothèse** : « ce problème revient » | décrit, pas construit (G6) |
| Propositions sur branche + conversation (`gardiens.md`, G5 ; lot D, lancements par l'Atelier) | l'**action** | décrit, dépend du lot D |
| Agents planifiés : nés désactivés, **budget obligatoire** (tours, par jour, pause) | le **plafond** de chaque équipe | en service |
| « À valider », décisions, journal unique, classes de commandes (lecture / réversible / engageante / réservée) | la **porte humaine** | en service |
| Suite de tests (157 fichiers sous `atelier-src/tests`, dont `faux_claude`, `faux_chrome_mcp`, `faux_service_ws` : un harnais sans modèle) et CI (`image.yml`, `labo.yml`) | le **banc de non-régression** | en service |
| `atelier-verifier-coherence`, plafonds du pod, interrupteurs `ATELIER_GARDIENS=0` / `…_GESTES=0` | contrôle de cohérence ; **arrêt d'urgence** | en service |
| Registre des défauts, états des lieux, `decisions.md` | la **mémoire** de ce qu'on a déjà compris et décidé | docs |

Ce qui manque est précis : (a) une **mesure d'ensemble** qui dise « mieux » ou « pire » avec autre
chose que des impressions ; (b) un **banc de scénarios rejouables** qui teste le *comportement* de
l'Atelier (pas seulement ses fonctions) ; (c) la **chaîne** qui relie capteur → proposition →
épreuve → promotion → retour arrière ; (d) la **séparation** entre qui propose et qui juge.

## 3. La proposition

### 3.1 L'Atelier est le mieux placé pour se connaître, et le plus mal placé pour se juger

C'est la question posée (« il est le mieux placé pour s'évaluer, peut-être »). La réponse honnête
est **oui pour le contexte, non pour l'impartialité**. Il connaît ses journaux, ses défauts, ses
conversations ; mais un système qui note son propre travail a trois pentes connues : il se
complaît (un modèle juge mieux ce qui lui ressemble), il triche sans le vouloir (il optimise la
note, pas le but : loi de Goodhart), et il s'aveugle sur ce qu'il ne mesure pas. D'où une règle
d'architecture, la seule non négociable :

> **Celui qui propose un changement ne juge ni son résultat, ni le critère de réussite, ni le
> banc d'essai.** Le critère est écrit à l'avance, par la personne, et ne bouge pas pendant
> l'épreuve.

Tout le reste du document en découle.

### 3.2 Quatre pièces, trois de plus que ce qui existe

```
 ┌───────────────────────────────────────────────────────────────────────────────────┐
 │ 1. CONSTITUTION  (écrite par la personne, lisible, versionnée, hors d'atteinte)    │
 │    objectifs · principes · zones protégées · plafonds · critères de réussite       │
 └───────────────┬───────────────────────────────────────────────────────────────────┘
                 ▼
  CAPTEURS (gardiens, code, 0 jeton) ──► 2. TABLEAU DE MESURE ──► écarts à l'objectif
                                         (indicateurs + leur historique)     │
                                                                              ▼
                 ┌────────────────────── 3. ÉQUIPES (agents à budget) ───────────────┐
                 │ Observatrice → Analyste → Proposeuse → Réalisatrice                  │
                 │  (lit)        (cause ?)   (hypothèse    (branche + changement        │
                 │                            + critère)    + test qui l'aurait vu)     │
                 └───────────────────────────────┬──────────────────────────────────┘
                                                 ▼
                 ┌────────────────────── 4. ÉPREUVE (code, séparée) ──────────────────┐
                 │ tests · scénarios rejoués candidat vs référence · zones protégées ·  │
                 │ coût · échantillon relu par la personne                              │
                 └───────────┬───────────────────────────────┬───────────────────────┘
                             ▼ passe                          ▼ échoue
                    PROMOTION par paliers              la branche est fermée, la leçon
                    (A valider si zone sensible)       va au registre (jamais rejouée à l'identique)
                             ▼
                    SURVEILLANCE après coup ──► si la mesure se dégrade : RETOUR ARRIÈRE automatique
```

**1. La constitution** (nouveau, un fichier, `atelier-gardiens/CONSTITUTION.md` + un bloc
machine `constitution.json`). La personne y pose les « grandes lignes et objectifs » ; l'Atelier
n'a **pas le droit de l'écrire**, seulement de proposer un amendement par « À valider ». Quatre
rubriques :

| Rubrique | Exemple | Qui la lit |
|---|---|---|
| **Objectifs mesurables** | « moins de 2 % de lancements finis sans livrable » ; « coût médian d'un tour sous X » ; « zéro permission restée sans réponse plus de 5 min » | le tableau de mesure |
| **Principes** | ceux du `cadre.md` (simple, natif d'abord, un seul modèle, sûr par construction, sobre) + le principe 2 bis du registre (« la correction passe par la mécanique, pas par une ligne de plus dans la consigne ») | les relectures par modèle, comme *grille* |
| **Zones protégées** | secrets, `auth`, garde-fous Bash, la constitution elle-même, l'épreuve, le journal, les plafonds | la promotion (toujours « À valider ») |
| **Plafonds** | jetons par jour, nombre de branches ouvertes, changements promus par semaine, budget par équipe | l'ordonnanceur |

**2. Le tableau de mesure** (nouveau, `mesure.jsonl` à côté du journal des gardiens). Un
indicateur est une fonction **en code** qui lit une source que le modèle n'écrit pas : journal
unique, `permission_denials` et `terminal_reason` du CLI, durée d'attente d'une permission, taux
d'échec des tests rejoués, nombre d'alertes rouvertes, `cache_read_input_tokens`, coût par
conversation, délai de réponse du pod. Règle : **un indicateur qu'un agent peut écrire lui-même
n'en est pas un.** Chaque indicateur porte sa définition, sa dérive normale (bruit) et sa source.
C'est la traduction systématique de la leçon du 17/09 : mesurer ce qui se dégrade avec le temps.

**3. Les équipes** (les agents, nés désactivés avec budget, via le catalogue existant). Pas un
agent qui fait tout : des **rôles à périmètre étroit**, que l'Atelier organise lui-même selon la
constitution (combien, quand, sur quoi), dans les limites de ses plafonds :

| Rôle | Fait | Ne fait jamais |
|---|---|---|
| Observatrice | lit le tableau et le journal, classe les écarts par gravité et récurrence | proposer une solution |
| Analyste | cherche la cause racine (rejoue, bissecte) ; sépare « défaut de la plateforme » et « défaut du modèle » | modifier du code |
| Proposeuse | écrit l'hypothèse **et le critère de réussite avant** le changement : « si c'est vrai, cet indicateur doit passer de A à B sur ce scénario » | juger sa propre hypothèse |
| Réalisatrice | fait le changement minimal sur une branche, avec le test qui aurait vu le problème (règle de clôture d'incident) | toucher une zone protégée, étendre le périmètre |
| Arbitre | **ne modèle rien** : c'est l'épreuve (4), du code | — |

**4. L'épreuve** (nouveau, le cœur de la fiabilité). Code déterministe, hors des équipes :

- **Tests existants** : la suite complète, en CI, sur la branche. Condition nécessaire, jamais
  suffisante.
- **Scénarios rejoués** (`atelier-src/tests/scenarios/`, nouveau) : des situations réelles figées
  (anonymisées) tirées du registre et des journaux : « permission sans réponse », « fin de
  lancement sans livrable », « conversation trop lourde ». Chacune est rejouée avec le harnais
  sans modèle (`faux_claude` et consorts) sur **référence** (`main`) et **candidat** (la branche),
  et l'on compare les indicateurs. Pas de comparaison à un seuil absolu : un **différentiel** sur
  les mêmes entrées, qui annule le bruit commun.
- **Cliquet** : un scénario qui passait ne doit plus jamais échouer. Aucun test n'est supprimé,
  affaibli ou marqué `skip`/`xfail` par une branche de l'amélioration : un détecteur le refuse
  (diff des tests : lignes retirées, assertions relâchées, `skip` ajoutés).
- **Zones protégées** : tout diff qui les touche sort de la voie automatique.
- **Coût et sobriété** : le candidat ne doit pas coûter plus de jetons ou de mémoire, à scénario égal.
- **Échantillon humain** : quelques sorties, tirées au hasard, présentées à la personne dans
  « À valider », *sans* le verdict de l'Atelier (juge aveugle). C'est le seul étalon qui ne dérive
  pas ; son taux d'accord avec les relectures par modèle est lui-même un indicateur. (Le
  laboratoire sait déjà mesurer l'accord entre annotateurs : kappa, rappel moyen humain.)

### 3.3 Promotion par paliers, retour arrière automatique

Un changement qui passe l'épreuve **n'est pas promu d'un coup**.

| Palier | Ce qui se passe | Qui décide |
|---|---|---|
| 0. Proposition | branche + conversation visibles (comme `gardiens.md` G5) | l'Atelier |
| 1. Épreuve | § 3.2 (4) | le code |
| 2. Fusion sans risque | seulement si : hors zone protégée, hors engageant, diff petit, épreuve verte, plafond hebdomadaire non atteint | le code, journalisé, annulable en un geste |
| 2 bis. Fusion sensible | tout le reste | la personne, par « À valider » |
| 3. Surveillance | la mesure est suivie N jours ; l'effet attendu est comparé à l'effet réel | le code |
| 4. Retour arrière | si l'indicateur visé ne bouge pas, ou si un autre se dégrade au-delà du bruit : revert automatique, motif au journal, le changement ne se redemande pas à l'identique | le code |

Un changement qui ne produit **pas** l'effet annoncé (étape 3) est retiré **même s'il n'a rien
cassé** : la boucle ne garde que ce dont elle a la preuve. C'est ce qui la rend positive : elle ne
s'accumule pas de changements neutres.

### 3.4 Ce qui rend la boucle fiable (et non seulement active)

| Menace | Parade |
|---|---|
| **Goodhart** : on optimise l'indicateur | plusieurs indicateurs indépendants par objectif ; échantillon humain aveugle ; indicateurs rotatifs non annoncés aux équipes |
| **Triche involontaire** : on affaiblit un test, on relève un seuil | cliquet, détecteur de diff de tests, zones protégées, la constitution et l'épreuve ne sont pas inscriptibles par les équipes (droits de fichier + `permissions.deny` managé, pas une consigne) |
| **Complaisance du juge modèle** | le juge n'est jamais le proposeur ni du même fil ; modèle ou grille différents ; son accord avec l'humain est mesuré, et s'il baisse sa voix compte moins |
| **Bruit** : on prend le hasard pour un progrès | différentiel sur entrées identiques ; plusieurs répétitions ; un effet doit dépasser le bruit mesuré de l'indicateur |
| **Emballement** : trop de changements, causes mêlées | un changement promu à la fois par zone ; plafond par semaine ; fenêtre de surveillance avant le suivant |
| **Dérive lente de la constitution** | tout amendement passe par « À valider » et laisse une décision datée dans `decisions.md` |
| **Coût qui s'envole** | budget par équipe (existant), plafond global quotidien, coupure automatique ; la boucle elle-même est un contrôle surveillé |
| **La boucle meurt en silence** | homme mort (existant) ; résumé de la semaine : ce qui a été tenté, promu, retiré, et ce que ça a coûté |
| **Tout casser** | `ATELIER_AMELIORATION=0` coupe la boucle sans toucher aux gardiens ; la voie automatique est **éteinte par défaut** (pas de fusion sans la personne tant qu'un palier n'est pas validé) |

### 3.5 Ce que voit la personne

- Une section **« Progrès »** dans la vue Agents (pas une page de plus, décision J-i) : les
  objectifs de la constitution, leur courbe, et ce qui est en cours (« 3 hypothèses, 1 à l'épreuve,
  1 en surveillance »).
- Dans **« À valider »**, des cartes courtes : *ce qu'on a observé, ce qu'on propose, la preuve
  (avant/après sur le scénario), le coût, le retour en un geste*. Plus, au hasard, un échantillon
  à juger à l'aveugle.
- Une **semaine type** (le résumé) : « 4 hypothèses, 2 promues, 1 retirée faute d'effet, 1 refusée
  par l'épreuve ; l'indicateur *fins sans livrable* est passé de 9 % à 5 % ; coût de la boucle :
  X jetons ». Les chiffres viennent du code, jamais d'un modèle.
- **Un seul interrupteur** : couper la boucle, la mettre « à blanc » (elle propose mais ne promeut
  rien), ou la laisser agir dans la voie sûre.

### 3.6 Ce que voit l'agent

Rien de plus que d'habitude, et c'est voulu : un agent d'un projet ordinaire n'a pas à savoir qu'une
boucle l'observe. Les changements promus arrivent par la mécanique (hooks, socle, gabarits,
contrôles), pas par une consigne de plus. Les rôles de la boucle ont chacun un profil d'outils
réduit (principe du moindre privilège, déjà le principe de `--tools`/`--allowedTools`).

## 4. Parcours types

**A. Un défaut qui revient.** Le capteur « permission restée sans réponse » dépasse l'objectif
trois jours de suite. L'Observatrice l'écrit au tableau ; l'Analyste trouve que les agents lancés en
`acceptEdits` demandent une autorisation que personne ne voit ; la Proposeuse écrit : *« passer ces
rôles en `dontAsk` avec liste blanche fera passer l'attente médiane de 3 600 s à moins de 5 s sur le
scénario S-perm »* ; la Réalisatrice change la table des rôles et ajoute le scénario. L'épreuve
rejoue S-perm sur `main` et sur la branche, vérifie la suite et le cliquet. Zone « permissions » =
sensible : carte « À valider » avec le différentiel. La personne accepte ; fenêtre de surveillance de
sept jours ; l'indicateur baisse comme prévu ; le changement est conservé.

**B. L'amélioration qui n'améliore rien.** Une hypothèse sur le cache de préfixe passe tous les tests
mais `cache_read_input_tokens` reste à zéro en surveillance. Retour arrière automatique, ligne au
journal : « effet non démontré », et l'hypothèse rejoint le registre avec sa mesure.

**C. La tentation.** Un test échoue sur la branche d'une Réalisatrice ; le moyen le plus court est de
le relâcher. Le détecteur de diff de tests refuse la branche avant même l'épreuve ; l'incident est
compté dans l'indicateur de fiabilité *de la boucle elle-même*.

**D. La nuit.** Rien ne demande la personne : la boucle observe, analyse, propose, éprouve. Au matin :
le résumé, une ou deux cartes. Si le plafond de coût est atteint à 3 h, tout s'arrête et le dit.

## 5. Ce qu'il faut construire, par étapes démontrables

Chaque étape se livre seule, avec sa preuve et son retour arrière. Les étapes 0 à 2 ne dépensent
**aucun jeton** : on apprend d'abord à *mesurer*.

| # | Étape | Preuve de réussite | Dépend de |
|---|---|---|---|
| 0 | **Constitution** : écrire avec la personne 5 à 8 objectifs mesurables et les zones protégées (`CONSTITUTION.md` + `constitution.json`) ; protéger le fichier (droits, `deny`) | un diff de la constitution par un agent est refusé | — |
| 1 | **Tableau de mesure** : 6 à 10 indicateurs en code, `mesure.jsonl`, bruit mesuré sur deux semaines, courbe dans la vue Agents | on peut répondre « mieux ou pire que le mois dernier ? » avec des chiffres | gardiens (G0-G3), G4 coût |
| 2 | **Scénarios rejoués** : 5 scénarios tirés du registre ; commande `atelier-epreuve <branche>` qui rend un différentiel candidat/référence ; cliquet et détecteur de diff de tests | une régression volontaire est vue ; un test relâché est refusé | harnais sans modèle |
| 3 | **Voie à blanc** : G5 + Observatrice/Analyste/Proposeuse, qui proposent seulement ; tout passe par « À valider » ; plafonds | trois semaines de propositions dont la personne dit combien étaient justes (précision mesurée) | lot D, G5 |
| 4 | **Promotion par paliers** et surveillance, retour arrière automatique, résumé de la semaine | un changement volontairement inutile est retiré tout seul | 2, 3 |
| 5 | **Voie automatique restreinte** (hors zones protégées, diffs petits), allumée par la personne seulement si la précision de l'étape 3 le justifie | taux de retour arrière bas, aucune alerte de fiabilité de la boucle | 4 |
| 6 | **Auto-organisation** : l'Atelier choisit le nombre et la cadence des équipes d'après les écarts et les plafonds, et rend ses choix lisibles | la composition est expliquée, plafonnée, réversible | 5 |

Le plus tentant est de commencer par les équipes (étape 3 à 6) ; le plus utile est de commencer par
**l'étape 1 et l'étape 2**. Sans elles, une boucle d'amélioration est une boucle de changement.

## 6. Risques, limites, questions à trancher

**Risques et limites**

- **La mesure d'abord, et elle est imparfaite.** Certains objectifs (une réponse « utile », une
  explication « claire ») n'ont pas d'indicateur en code. On les traite par échantillon humain,
  plus lent et plus cher : la boucle ira plus vite sur la fiabilité que sur la qualité perçue.
- **Les modèles du pod sont `qwen3-*`** (cf. registre des défauts) : une part des défauts vient du
  modèle, pas de la plateforme, et aucun réglage de l'Atelier ne la corrige. L'Analyste doit
  séparer les deux, sinon la boucle s'acharne sur ce qu'elle ne peut pas changer.
- **Le banc rejoué teste ce qui a déjà été vu.** Il ne protège pas d'un défaut nouveau ; les capteurs
  et l'échantillon humain portent cette part.
- **Coût.** Les étapes 0 à 2 sont gratuites en modèle. La suite est plafonnée, mais non nulle ; le
  coût réel est **à mesurer** à l'étape 3 avant d'aller plus loin.
- **Une boucle qui s'améliore s'améliore aussi elle-même.** Le contrôle de la boucle (précision de
  ses propositions, taux de retour arrière, incidents de triche) est un indicateur de la
  constitution, et la boucle ne peut pas modifier ses propres garde-fous : ils sont zone protégée.
- **Surface d'attaque.** Des données externes (page web, message) lues par une Observatrice pourraient
  injecter une « amélioration ». D'où : rôles à outils réduits, aucune promotion sans épreuve,
  zones protégées, et données externes jamais traitées comme consignes.

**Questions à trancher par Nicolas**

1. Quels sont les **trois premiers objectifs** de la constitution ? (Proposition : fins de lancement
   qui disent vrai ; permission jamais sans réponse ; coût par tour.)
2. La **voie automatique** (étape 5) : jamais, ou seulement après N semaines de précision
   démontrée ? (Recommandation : seulement après, et hors zones protégées.)
3. Quel **budget quotidien** pour la boucle, en jetons, et quel modèle pour les équipes (le grand
   modèle seulement à l'Analyste ?).
4. Qui juge l'**échantillon aveugle**, et à quelle fréquence ? (Recommandation : la personne, cinq
   cartes par semaine, pas plus.)
5. La boucle peut-elle **amender les consignes du socle** (zone aujourd'hui ouverte à G6) ou
   seulement les hooks, gabarits et contrôles ? (Recommandation : hooks et contrôles d'abord, car
   ils sont testables ; le socle en dernier, parce qu'une consigne ne se teste pas aussi bien.)

## 7. Évaluation

- **Désirable.** Pour la personne qui veut confier du travail sans le suivre : elle écrit un cap, lit
  un résumé, tranche peu de cartes. Elle sort du rôle de relectrice du registre des défauts.
- **Faisable.** L'essentiel du matériel existe (capteurs, journal, budgets, file « À valider », harnais
  sans modèle, CI). Le neuf est petit et en code : une constitution, un tableau de mesure, une
  commande d'épreuve, un détecteur de diff de tests, un enchaînement de promotion. Les équipes sont
  des agents ordinaires du catalogue.
- **Viable.** Aucun jeton pour mesurer et éprouver ; le modèle n'est appelé que pour analyser et
  rédiger, sous budget. La maintenance est portée par le projet `atelier-gardiens`, qui s'améliore
  par le même processus que le reste (et sous les mêmes garde-fous).
- **Cohérente.** Même vocabulaire (projet, proposition, branche, « À valider »), même file unique,
  même journal, même schéma d'échelle que les gardiens (`gardiens.md` §3.3 : une échelle, jamais
  sautée), mêmes principes que `cadre.md` : simple et lisible, natif d'abord, sûr par construction,
  sobre. Et le principe 2 bis du registre reste la ligne directrice des *changements* proposés :
  corriger par la mécanique, jamais par une ligne de plus dans la consigne.

**À retenir.** L'Atelier peut organiser le travail, les équipes et l'arrière-plan ; ce qu'il ne doit
pas faire seul, c'est écrire le critère de ce qui est « mieux ». Ce critère, la personne le pose
dans la constitution ; l'Atelier le mesure, l'éprouve et le défend.
