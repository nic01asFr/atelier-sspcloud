# Relecture grand public des trois visions

Relecture du 25/09/2026 de `panneau.md`, `ecosysteme.md` et `gardiens.md`, à la lumière de
`cadre.md`, vue par une personne qui ne sait pas ce qu'est un port, un JSON ou un serveur MCP.
Critique volontairement : les trois documents sont solides techniquement ; ce qui suit porte sur
ce que la personne **voit, lit et doit décider**.

## Le constat en cinq lignes

1. Les trois visions s'emboîtent bien techniquement, mais sont écrites **pour Nicolas**. Aucun
   parcours ne part d'une personne qui ne connaît ni git, ni les jetons, ni les « connecteurs ».
2. Le principe 1 du cadre (« peu de mots, les mêmes partout ») n'est pas tenu : **« vue » a trois
   sens**, « service » quatre, « production » deux, et « gardien » contredit le cadre.
3. Il y a trop de moments de consentement, et trop de décisions techniques remises à la personne
   (famille du projet, portée d'une autorisation, budget en jetons, fusion de branche).
4. Deux promesses implicites ne tiennent pas : **corriger à la main** une page (rien ne
   l'enregistre) et **être prévenu** d'une panne (l'alerte reste dans une page que personne n'ouvre).
5. La démonstration qui ferait envie existe presque, mais elle est éparpillée entre les étapes P,
   F et G ; il faut la construire comme un seul chemin.

---

## 1. Personas et parcours

### Les personnes

| Qui | Ce qu'elle sait faire | Ce qu'elle veut de l'Atelier | Ce qu'elle ne fera jamais |
|---|---|---|---|
| **Claire**, chargée d'études | tableur, Grist, un peu de SIG en consultation | des cartes et des tableaux de bord à partir de ses données, à montrer à sa cheffe | ouvrir un terminal, lire un JSON, fusionner une branche |
| **Karim**, géomaticien | QGIS avancé, scripts Python courts, notion de git | automatiser ses traitements, les rendre utilisables par ses collègues | écrire un serveur OAuth, régler une CSP |
| **Nicolas**, bâtisseur de l'Atelier | tout | que l'Atelier se complète lui-même, et qu'il sache ce qui tourne | accepter une boîte noire |

### Claire — parcours C1 : « une carte interactive de mes données »

| Étape | Ce qu'elle voit et lit | Ce qu'on lui demande | Où elle se perd |
|---|---|---|---|
| 1. Nouvelle conversation : « fais-moi une carte des logements vacants par commune, mes données sont dans Grist » | L'agent répond « je propose un projet de famille *Page* » (écosystème §4, parcours 1, étape 1) | **Valider la famille** | Elle ne sait pas si c'est une *Page* ou une *Application* ; le choix n'a aucun sens pour elle (§3.2 : la différence est « ce qui tourne ») |
| 2. L'agent écrit la page | Le panneau s'ouvre à droite, onglet « Carte des logements », une carte « Vue : … — Afficher » dans le fil (panneau §3.7) | rien | Si la page appelle Grist en brouillon, **pas de consentement** (écosystème §4, étape 2) : bien. Mais le fond de carte est bloqué : le gabarit *Page* impose « sans dépendance réseau hors de son hôte » (§3.2, Gabarits). **Une carte sans tuiles IGN est une carte vide** |
| 3. Elle clique une commune et écrit « celle-ci est fausse » | Si la page charge le pont, l'agent reçoit « commune X sélectionnée » (panneau §3.3, §4 A) | rien | Si l'agent a oublié le client du pont (`atelier.js`), le clic n'est vu de personne. Elle ne peut pas savoir pourquoi l'agent « ne voit pas » |
| 4. Elle veut **corriger à la main** un libellé, déplacer une étiquette | Rien ne le permet | — | Le panneau (§3.4) dit que l'état partagé est « le service » ; pour une page, l'objet, ce sont les fichiers : **une retouche dans la page disparaît au rechargement**. La seule correction possible est de la décrire à l'agent |
| 5. « Montre-la à Sophie » | Deux boutons : **Ajouter à mon Atelier** et **Publier** (écosystème, « Ce que voit la personne ») | Choisir la destination, puis accorder « lire la table Logements » ; au moment de publier : « vos invités verront ce que vous voyez », et réduire la portée à une table (§4, étape 5) | Elle ne sait pas ce que change « ajouter à mon Atelier ». Elle ne sait pas si Sophie a besoin d'un compte SSPCloud. « Héberger à part » (§3.4, Isolation de processus) lui est proposé sans critère qu'elle puisse appliquer |
| 6. Trois semaines plus tard, la colonne Grist est renommée ; la carte est vide | Rien dans son accueil | — | Le gardien Santé sonde les **connecteurs** (gardiens §3.2, « Connecteurs : `initialize` + `tools/list` »), pas les **créations** ; une page statique ne « tombe » pas. L'alerte, s'il y en a une, va au tableau « Gardiens », dans `contexte.md` et sur un canal wikichat (§3.3, *Signaler*) : **trois endroits qu'elle n'ouvre jamais**. C'est Sophie qui la prévient |

### Claire — parcours C2 : « chaque lundi, la synthèse de ma veille »

1. Elle demande la synthèse hebdomadaire. L'agent propose un *Savoir-faire* (écosystème §4, parcours 4).
   Le mot ne lui dit rien : elle demandait **une tâche qui revient**.
2. `/essayer veille` : elle voit une commande avec une barre oblique dans le fil. Elle ne sait pas
   si elle doit la taper.
3. **Ajouter à mon Atelier** : la composition « passe en production », la routine est « déclarée à
   wikichat avec son plafond ». Elle lit « plafond 1 passe » et « budget jetons ». Elle ne sait pas
   ce qu'est une passe ni combien vaut un jeton.
4. Un lundi, pas de synthèse. Le gardien Entretien l'a **coupée** pour dépassement du plafond global
   des automates (gardiens §4, P4). Le message « réactiver avec un budget ou supprimer » est dans la
   page Gardiens, onglet Automates. Pour elle, l'Atelier « a oublié » sa veille.

### Karim — parcours K1 : « je travaille dans QGIS avec l'agent »

1. Il ouvre **+ → QGIS → Bureau** (panneau §4 C, P4). Il voit son QGIS dans le panneau, plus
   petit que d'habitude ; le panneau s'étire mais le plein écran le fait sortir de la conversation.
2. S'il choisit plutôt la vue `application` de `qgis-hub /desk` (panneau §2.2 et P6), il voit
   **un second chat** dans le panneau, à côté du fil : deux agents, deux fils, lequel parle à qui ?
3. Il sélectionne une couche, clique **Montrer**. L'agent reçoit la capture et le nom de la couche.
   Ici la promesse tient : l'état partagé est le projet QGIS, ses retouches à la main sont gardées.
4. Liseré « l'agent agit » ; il veut corriger une symbologie en même temps. **Prendre la main**
   interrompt le tour (§3.4) : que devient le traitement à moitié appliqué ? Le document ne le dit pas.

### Karim — parcours K2 : « mon traitement devient un outil pour les collègues »

1. Il demande « transforme ce traitement de découpage en outil ». Carte *Un outil pour les agents
   (« un service MCP »)* (écosystème, « Ce que voit la personne »). Il comprend « outil », pas « MCP ».
2. `/apercu` « liste les outils et en appelle un » (§3.2). Il lit une liste de noms `decoupe__…`.
   Le préfixe « doit être libre (refus nommé sinon) » (§3.3) : s'il est refusé, il doit en choisir un.
3. **Ajouter à mon Atelier** : il devient un connecteur « utilisable dans claude.ai sans autre
   réglage » (§3.6). C'est le meilleur moment du parcours.
4. **Publier** pour l'équipe : F8 exige `passerelle-auth`, un service dédié, une revue de sécurité
   « avant le premier accès de tiers » (§3.6, étape 3). Qui fait la revue ? Combien de temps ?
   Le collègue doit « brancher le service dans son claude.ai » : personne ne lui explique comment.
5. S'il avait fait une *Application* : ses collègues agissent **au nom de Karim** (§3.7) avec ses
   droits Grist. Le consentement le dit en une phrase, mais c'est le piège le plus grave pour lui.
6. Une nuit, la sauvegarde de `donnees/` manque. Le gardien Santé l'a vu (« moins de 26 h »,
   gardiens §3.2) ; le lendemain, une **proposition** l'attend sur la branche
   `gardien/sante/2026-…` (§3.3). Il sait fusionner dans VS Code, Claire ne saurait pas.

### Nicolas — parcours N1 : « une vue calendrier de mes routines sur l'accueil »

1. Famille *Page*, `offre.vue.emplacement: "accueil"` (écosystème §4, parcours 3). En brouillon,
   la vue s'essaie dans l'onglet du projet ; le panneau, lui, l'appelle « vue » aussi, dans un autre
   endroit (panneau §3.7) : **deux cadres de vue construits par deux équipes** (panneau P1–P3,
   écosystème F5 et F7).
2. **Ajouter à mon Atelier** → écran « ajoute une vue *Calendrier* ; peut lire vos routines ».
3. Version 5 cassée : elle passe « suspendue », l'accueil s'affiche sans elle. Il la retrouve dans
   **Mon Atelier › Extensions**. L'alerte, elle, est dans la page **Gardiens**, et l'artefact dans
   le catalogue **+** du panneau : trois écrans d'état pour un même objet.
4. Qui l'a suspendue ? Écosystème §3.4 dit « le registre » ; écosystème §7 dit « les gardiens » ;
   la liste fermée des gestes des gardiens (gardiens §3.3) **ne contient pas** « suspendre une
   extension ». À clarifier avant construction.

### Nicolas — parcours N2 : « mon lundi »

1. En tête de l'Atelier : le résumé de la semaine (gardiens §3.5) ; il est bien écrit, et c'est le
   passage le plus lisible des trois documents.
2. Trois files à relire : les **propositions** des gardiens (§3.3), les **propositions** des agents
   (`/proposer`, écosystème §3.2), les **propositions** nées d'une capacité `agent` (écosystème
   §3.5, « file d'approbation »). Le mot est le même ; la file est-elle la même ? Rien ne le dit.
3. Il ignore une alerte « jusqu'au 15/10 » avec un motif : pour lui cinq minutes, pour Claire une
   corvée incompréhensible.

---

## 2. Vocabulaire

### Termes qu'une personne verrait, par document

| Terme | cadre | panneau | écosystème | gardiens | Problème |
|---|---|---|---|---|---|
| **vue** | — | un onglet du panneau, quel qu'il soit (§3.1), y compris navigateur et bureau | « une page affichée dans l'Atelier, rien d'autre » (§3.3), avec emplacement accueil/projet/conversation | — | **contradiction** ; et l'interface a déjà des « vues » (vue Code, vue projet) |
| **panneau** | — | la colonne de droite | « un panneau (accueil, projet, conversation) » (§3.4, table des prises) | — | le panneau Applications existant a le même nom |
| **page / application** | apps | *genres* de vue (§3.2) | *familles* de projet (§3.2) | — | même mot, deux classements ; en plus `type: statique|service` dans le manifeste |
| **artefact** | mot commun | page d'artefact | tout ce qu'un projet produit, y compris un savoir-faire | — | jargon ; chez claude.ai, un artefact est une page |
| **service** | chose produite | « l'objet partagé » (§3.4), services du namespace | *Service MCP*, service dédié | wikichat, relais (§3.2) | **quatre sens** |
| **connecteur / service MCP / outil pour les agents / serveur MCP** | — | connecteur | les quatre (§3.2, cartes de création) | connecteurs | **doublons** pour une seule chose |
| **extension** | une chose qu'on crée (L'idée) | extension VS Code, MCP Apps « extension officielle » | une **destination**, pas une famille (§L'idée) | — | **contradiction** avec le cadre ; homonymes techniques |
| **production / publier** | « publier en production » | `~brouillon` et production (§7) | « Ajouter à mon Atelier » crée aussi une étiquette `prod/` ; une composition « passe production » à l'ajout | « ne touche jamais la production » | deux sens : « installé chez moi » et « ouvert aux autres » |
| **brouillon / aperçu / essai** | brouillon | `~brouillon` | brouillon, `/apercu`, « `/mcp` en essai » | brouillon | trois mots pour un état |
| **capacité** | « ce qu'une app peut faire » | accord « pour cette vue » (§3.3) | capacité déclarée (§3.5) | — | deux consentements distincts pour la même idée |
| **gardien** | « agents gardiens (routines, wikichat) » | — | « agents gardiens » (§7) | « du code qui regarde, **pas un agent** » (En une phrase) | **contradiction** frontale |
| **automate / routine / trigger / déclencheur / agent planifié / démon** | routines | agents planifiés et routines | routines, agents | automate, trigger, routine, démon | six mots, une idée : « ce qui se lance tout seul » |
| **proposition / proposer** | — | — | `/proposer`, résultat d'une capacité `agent` | conversation sur branche | même mot, trois origines ; bon mot si une seule file |
| **entretien** | — | — | champ `entretien` d'un artefact (santé, tests, sauvegarde) | gardien *Entretien* (coût, vieillissement) | la santé d'un artefact relève du gardien *Santé*, pas *Entretien* |
| **composition** | outils, compositions | — | partout | — | jamais défini pour la personne |
| **savoir-faire, famille, gabarit, prise, offre** | — | — | §3.1 | — | savoir-faire regroupe cinq choses hétérogènes ; « gabarit » se dit « modèle » |
| **constat, empreinte, alerte, attention, homme mort, geste** | — | — | — | §3.1–3.5 | vocabulaire d'exploitant |
| **montrer, prendre la main, épingler, détacher, liseré** | — | §3.1, §3.7 | — | — | bons mots, à garder |

Compte : le cadre promet « peu de mots » ; la personne en rencontre **plus de quarante**, dont
trois nouveaux par document présentés chaque fois comme « seulement trois » (panneau §3.1,
écosystème §3.1). Les états ajoutent leurs listes : vue `prete|demarrage|endormie|echec`,
extension `active|inactive|suspendue|retirée`, composition `temporary|validated|production`,
gardien `ok|attention|alerte`, superviseur `en_echec`.

### Lexique minimal proposé (douze mots, visibles dans l'interface)

| Mot | Définition pour tous | Remplace |
|---|---|---|
| **Projet** | Un dossier de travail qui regroupe vos conversations et ce que vous y fabriquez. | — |
| **Création** | Ce que l'agent fabrique pour vous : une page, une application, un connecteur, une tâche qui revient. | artefact, extension, savoir-faire, famille |
| **Panneau** | La colonne à droite de la conversation où s'affiche ce que vous regardez, en onglets. | vue, cadre de vue |
| **Montrer** | Envoyer à l'agent ce que vous voyez ou avez sélectionné dans le panneau. | contexte de vue, capture |
| **Brouillon** | La version en cours de travail, que vous seul voyez et que l'agent peut modifier. | aperçu, essai, arbre de travail |
| **Installer** | Figer une version d'une création et l'ajouter à votre Atelier pour vous en servir partout. | ajouter à mon Atelier, extension, prod/ |
| **Partager** | Rendre une version figée utilisable par d'autres personnes, avec un lien. | publier, production, service dédié |
| **Connecteur** | Un branchement vers un service (Grist, QGIS, GitHub, votre outil) qui donne des outils à l'agent. | service MCP, serveur MCP, outil pour les agents |
| **Autorisation** | Ce qu'une création a le droit de faire en votre nom ; vous l'accordez ou la refusez. | capacité, accord « pour cette vue » |
| **Tâche automatique** | Ce qui se lance seul à heure fixe, avec une limite de dépense affichée. | routine, trigger, automate, agent planifié |
| **Gardien** | Une vérification automatique, sans IA, qui surveille vos créations et l'Atelier et vous prévient. | contrôle, constat, empreinte |
| **À valider** | La liste unique de ce qui attend votre accord : corrections, installations, demandes. | propositions, file d'approbation |

« Composition », « prise », « gabarit », « famille », « MCP », « pont », « jeton » restent des
mots **internes** (documents, manifestes, outils de l'agent) et n'apparaissent jamais à l'écran.

---

## 3. Frictions et décisions par défaut

| # | Décision demandée | Où | Pourquoi elle ne peut pas la prendre | Ce que l'Atelier décide par défaut |
|---|---|---|---|---|
| F1 | Choisir la famille (page, application, service MCP, savoir-faire) | écosystème §3.2, « Ce que voit la personne » | la différence est technique (« ce qui tourne ») | **L'agent choisit** d'après la demande et le dit en une phrase ; les quatre cartes restent une option « Commencer par un modèle » ; changer de famille plus tard sans recréer le projet |
| F2 | Installer ou partager | écosystème §3.2, §3.6 | elle ne voit pas la différence d'effet | Un seul bouton **Partager…** qui demande « avec qui ? » : *moi partout* (= installer), *des personnes précises*, *tout le monde* ; l'Atelier en déduit la destination |
| F3 | « Héberger à part » | écosystème §3.4, §3.6 | critère « données sensibles » impossible à juger | Automatique dès qu'on partage une application ou un connecteur à d'autres ; jamais proposé pour soi seul |
| F4 | Portée d'une autorisation (une table, lecture seule, 120 par heure) | écosystème §3.5, §4 étape 5 ; §6 « capacités fines » | elle ne connaît ni les noms d'outils ni les quotas | Par défaut : **lecture seule, les seules tables utilisées par la page**, quota choisi par l'Atelier ; l'écran parle du document et de la table (« lire *Logements* dans *Études 2026* »), jamais de `grist__list_records` |
| F5 | Consentements répétés : accord « pour cette vue » (panneau §3.3), autorisation à l'installation, au partage, à chaque nouvelle autorisation, à l'installation depuis ailleurs, sans compter les permissions de Claude Code | panneau §3.3, §3.11 ; écosystème §3.4, §3.8 | fatigue : elle finira par tout accepter | **Un geste dans la vue vaut accord** pour l'outil de ce connecteur, le temps de la conversation ; les autorisations ne se demandent **qu'au moment de partager**, groupées sur un seul écran ; rien en brouillon (déjà proposé, écosystème Q8) |
| F6 | Budget en jetons, « passes », plafond par jour | écosystème §3.2 (savoir-faire) ; gardiens §3.2, §3.4 | le jeton n'est pas une unité humaine | Afficher en **part du forfait du mois** (ou en euros si le modèle est payant) et en « fois par semaine » ; plafond fixé par l'Atelier, modifiable ensuite |
| F7 | Fusionner une branche `gardien/…` | gardiens §3.3, §4 P3 | Claire ne connaît pas git | Dans « À valider » : ce qui était cassé, ce qui a été changé en une phrase, un aperçu avant/après, **Accepter** / **Refuser** ; la fusion est faite par l'Atelier |
| F8 | Ignorer une alerte « avec motif et échéance » | gardiens §3.4, §4 P6 | corvée pour elle | Boutons **Me le rappeler dans une semaine** / **Ce n'est pas un problème** ; motif facultatif |
| F9 | Réactiver une tâche coupée « avec un budget ou supprimer » | gardiens §4 P4 | elle ne sait pas qu'elle a été coupée | Message **sur la création elle-même** et dans son accueil : « Votre synthèse du lundi a été suspendue : elle a coûté trois fois plus que prévu. Relancer une fois / Relancer avec une limite plus haute » |
| F10 | Choisir un préfixe d'outils libre | écosystème §3.3 | nom technique | Préfixe dérivé du titre, dédoublonné en silence |
| F11 | Épingler au projet ou à la conversation | panneau §3.7, Q5 | peu d'enjeu | Défaut : ce que l'agent a montré reste avec la conversation ; toute création installée apparaît dans le projet |
| F12 | Clé d'API à saisir dans l'interface des secrets | écosystème §4, parcours 2 | elle ne sait pas où la trouver | Préférer la connexion (OAuth) quand le service la propose ; sinon un pas-à-pas propre au service, jamais « collez votre jeton » |
| F13 | Brouillon et version figée affichés comme deux onglets `~brouillon` / production | panneau §7 | deux onglets au même titre | Un onglet, un sélecteur **Brouillon / Installée** en tête |
| F14 | `/apercu`, `/verifier`, `/proposer`, `/essayer` | écosystème §3.2 | commandes à taper | Boutons sous la création ; les commandes restent pour Karim et Nicolas |
| F15 | Prendre la main pendant que l'agent agit | panneau §3.4, §4 B | peur de casser | Dire ce qui se passe : « l'agent s'arrête ; ce qu'il a déjà fait reste ; il reprendra quand vous direz *à toi* » |

Deux trous plutôt que des frictions :

- **Données personnelles** : aucun document ne dit où va le fichier CSV ou Excel que Claire
  dépose. Le gabarit *Page* interdit les données dans la page (écosystème §3.2) et renvoie aux
  autorisations. Il faut un défaut : un fichier déposé devient une table Grist (ou `donnees/`) et
  la page le lit par une autorisation créée d'office, en lecture seule.
- **Fonds de carte** : les pages et les vues MCP Apps n'ont accès qu'à leur hôte (écosystème §3.2 ;
  panneau §2.3, `_meta.ui.csp`). Il faut une **liste blanche par défaut** (Géoplateforme IGN, OSM)
  et des bibliothèques cartographiques dans le gabarit, sinon le cas d'usage phare échoue.

---

## 4. Ce qui rend l'ensemble désirable

La promesse qui parle à tout le monde tient en une phrase : **je demande, je vois, je montre du
doigt, je partage, et on me prévient si ça casse.** Aucun des trois documents ne l'écrit ainsi ;
chacun en porte un morceau (panneau : voir et montrer ; écosystème : partager ; gardiens :
prévenir).

### La démonstration de 3 minutes (Claire)

| Temps | À l'écran |
|---|---|
| 0:00 | Claire dépose `logements_vacants.xlsx` dans la conversation : « fais-moi une carte par commune ». |
| 0:30 | La carte apparaît dans le panneau, sur fond IGN, avec une légende. Personne n'a choisi de famille. |
| 1:00 | Elle clique une commune, **Montrer** : « celle-ci et sa voisine ont fusionné en 2024, regroupe-les ». La carte se redessine sous ses yeux. |
| 1:40 | « Ajoute un filtre par année. » Un curseur apparaît. |
| 2:00 | **Partager… → Sophie Martin**. Un seul écran : « Sophie verra cette carte et les données *Logements* en lecture ». Lien copié. |
| 2:30 | On avance d'une semaine (démonstration jouée) : dans son accueil, « Votre carte ne s'affichait plus : la colonne *Commune* a été renommée dans vos données. Une correction est prête. **Accepter** ». Elle accepte ; la carte revient. |

Ce qui ferait dire « je le veux » : **0 mot technique, 0 onglet perdu, 1 seul écran d'accord, et
une panne réparée avant qu'elle ne la découvre.**

### Ce qui doit exister pour qu'elle marche vraiment

| Besoin | Étape existante | Manque à ajouter |
|---|---|---|
| Panneau, ouverture par l'agent, rechargement | panneau P0, P1, P2 | — |
| Clic dans la page vu par l'agent | panneau P3 (pont), écosystème `atelier.js` | le client du pont **inclus d'office** dans le gabarit, vérifié par `/verifier` |
| Fichier déposé devient données lisibles | aucune | import vers Grist ou `donnees/` + autorisation en lecture créée d'office |
| Fond de carte | aucune | liste blanche de domaines cartographiques ; gabarit « carte » |
| Famille choisie par l'agent | écosystème F1 | règle de choix dans la consigne, bascule de famille |
| Partage à une personne nommée | écosystème lot 1 hébergement, F5 ; question d'authentification ouverte | accès par compte SSPCloud ou lien signé : **à trancher** |
| Écran d'accord unique, lisible | écosystème F4, capacités lot 4 | libellés humains des autorisations (étendre `enrichissements.py` aux capacités) |
| Panne détectée **sur la création** | gardiens G1 (connecteurs seulement) | contrôle « la création partagée s'affiche et lit ses données », dérivé de `entretien` |
| Alerte dans l'accueil de la personne | aucune (gardiens Q6) | bloc « Vos créations » dans l'accueil, notification hors Atelier pour une création partagée |
| Correction acceptée d'un clic | gardiens G5, hébergement lot 3 | présentation « avant / après » et fusion par l'Atelier |
| Pod éveillé en moins de 30 s | hors des trois documents | préchauffage du pod (service de réveil existant) avant toute démonstration |

La même démonstration, version Karim, remplace la carte par un QGIS partagé dans le panneau
(panneau P4) et le partage par un connecteur utilisable dans claude.ai (écosystème F3) : c'est
aujourd'hui **la plus proche d'être vraie**, parce que l'état partagé est le service et que F3 ne
demande ni nouveau pod ni nouvelle origine.

---

## 5. Recommandations

### À changer dans `cadre.md`

| Section | Raison | Proposition |
|---|---|---|
| L'idée | « extensions » listées comme chose créée ; « agents gardiens » | Écrire « créations » ; « des gardiens (vérifications sans IA) » |
| Principe 1 | la liste de mots est ouverte (« … ») | Y mettre le lexique de douze mots ci-dessus et interdire à l'écran tout mot hors liste sans décision |
| Format de rendu | aucun persona non technicien imposé | Ajouter : chaque parcours décrit aussi ce que voit une personne qui ne code pas |

### À changer dans `panneau.md`

| Section | Raison | Proposition |
|---|---|---|
| §3.1 Trois mots | « vue » contredit écosystème §3.3 | Garder **panneau** et **montrer** ; à l'écran, « onglet » ; « vue » reste interne |
| §3.2 Descripteur, `genre` | `page`/`application` recoupent les familles | Renommer en `fichiers`, `site`, `navigateur`, `bureau`, `interface` |
| §3.3 Pont, appel d'outil | accord « pour cette vue » = second consentement | Aligner sur §3.11 : le geste vaut accord ; une seule liste d'autorisations |
| §3.4 État partagé | laisse croire qu'on corrige tout à la main | Dire clairement : **pages = on corrige en montrant** ; bureaux et éditeurs = on corrige à la main |
| §3.7 Prendre la main | effet sur le travail en cours non décrit | Décrire ce qui est gardé, et le message affiché |
| §5 P6 | `qgis-hub /desk` apporte un second chat | Ne relayer que le bureau (`/vnc`), jamais le chat |
| §5 P1–P3 | double emploi avec écosystème F5 et F7 | Déclarer le panneau propriétaire du cadre, du pont et de MCP Apps ; écosystème s'y branche |
| §7 Désirable | « pour une personne non technicienne » affirmé sans parcours | Ajouter le parcours C1 ou le renvoyer ici |

### À changer dans `ecosysteme.md`

| Section | Raison | Proposition |
|---|---|---|
| §L'idée, §3.1 | « extension » contredit le cadre ; sept mots dans la table | À l'écran : **création**, **installer**, **partager** ; famille, gabarit, prise, extension internes |
| §3.2 Familles, « Ce que voit la personne » | choix de famille imposé | L'agent choisit ; cartes en option ; « Un outil pour les agents » devient « Un connecteur », « Un savoir-faire » devient « Une tâche automatique » (commandes et skills à part, pour les initiés) |
| §3.2 Gabarit *Page* | « sans dépendance réseau hors de son hôte » bloque les cartes | Liste blanche par défaut ; variante « carte » du gabarit |
| §3.3 `offre.vue` vs panneau `vues` | deux champs pour la même chose | Un seul champ, défini par le panneau |
| §3.4 Suspension automatique | qui suspend ? contredit §7 et gardiens §3.3 | L'exécuteur des gardiens, geste ajouté à la liste fermée ; le registre enregistre |
| §3.5, §4 étape 5 | autorisations au nom du propriétaire, portée à choisir | Défaut « lecture seule, tables utilisées » ; refus de partager une page à autorisations larges |
| §3.6, §3.7 | personne ne sait comment un collègue se branche, ni qui fait la revue | Une page « Comment l'utiliser » générée avec la fiche ; revue = liste de contrôle Sécurité automatique + accord de Nicolas |
| §3.8 Partage | consentement à chaque installation venue d'ailleurs | Grouper, montrer ce qui a changé depuis la dernière version seulement |
| Manque | dépôt de fichiers de données | Paragraphe « d'où viennent les données d'une page » |

### À changer dans `gardiens.md`

| Section | Raison | Proposition |
|---|---|---|
| En une phrase / cadre | « pas un agent » contre « agents gardiens » | Garder la définition de gardiens.md et corriger cadre et écosystème |
| §3.2 Santé | surveille l'infrastructure, pas les créations | Ajouter « chaque création installée ou partagée s'affiche et lit ses données », dérivé de `entretien` |
| §3.2 Entretien vs champ `entretien` | même mot, deux périmètres | Renommer le gardien **Dépenses** (coût, croissance, dépendances) ou le champ `suivi` |
| §3.3 Signaler | tableau, `contexte.md`, wikichat : aucun n'est l'accueil | Ajouter l'**accueil** et la **carte de la création concernée** ; rédiger par effet (« votre carte… »), jamais par contrôle |
| §3.3 Liste fermée | manque « suspendre une création installée » | L'ajouter (réversible, déjà prévu par écosystème §3.4) |
| §3.4 Page Gardiens | colonnes d'exploitant (portée, empreinte, prochaine) | Deux lectures : **Vos créations** (vert/orange/rouge, une phrase) et **Détail technique** pour Nicolas |
| §3.2, §3.4 coûts | en jetons | En part du forfait ou en euros |
| §4 P3, P6 | fusion d'une branche | Présentation « À valider » avec avant/après, fusion par l'Atelier |
| §6 Q6 | notification hors Atelier laissée ouverte | Recommander : oui pour une création partagée tombée et pour une alerte Sécurité rouge |

### À trancher par Nicolas (par ordre d'impact)

1. **Pour qui est l'Atelier ?** Pour Nicolas seul, ou aussi pour Claire et Karim ? Les trois
   documents supposent le premier ; le cadre promet le second. Tout le reste en dépend.
2. **Le lexique** : adopter les douze mots, dont « création » à la place d'« artefact » à l'écran,
   et bannir « vue », « extension », « production », « capacité » de l'interface.
3. **Une seule file « À valider »** pour les propositions des gardiens, des agents et des
   créations qui demandent un agent.
4. **Politique d'accord** : rien en brouillon, le geste vaut accord dans le panneau, un seul écran
   groupé au partage, lecture seule par défaut.
5. **Qui choisit la famille** : l'agent, par défaut (recommandé).
6. **Partager à qui** : comptes SSPCloud seulement, liens signés, ou public ; et qui fait la revue
   avant le premier accès d'un tiers.
7. **Corriger à la main une page** : l'accepter comme limite (on corrige en montrant) ou prévoir
   un mode édition qui écrit dans le brouillon.
8. **Notification hors de l'Atelier** (gardiens Q6) : canal et seuil.
9. **Unité de dépense** affichée : jetons, part du forfait, ou euros.
10. **Propriétaire du cadre de vue** : panneau (recommandé) plutôt que deux constructions (P1–P3
    et F5/F7).
11. **Fonds de carte et domaines externes autorisés par défaut** pour les pages.
