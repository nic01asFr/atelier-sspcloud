# L'Assistant, pour la personne : rôle et expérience

Réflexion du 25/09/2026, équipe « rôle et expérience ». **Rien n'est implémenté.** Le document
suit `assistant-cadre.md`, y compris les précisions de Nicolas du 25/09 : la porte d'entrée, un
assistant complet, la voix, et les vues diffusées vues comme un même modèle. Il s'appuie sur
`synthese.md` (lexique §3, politique d'accord §4), `relecture-grand-public.md` (Claire, Karim,
Nicolas), `panneau.md`, `atelier-wikichat-alignment.md`, le design du shell unifié et
`docs/consignes/stt-tts-atelier.md`. Les faits vus dans le code ou sur le pod sont marqués
**(mesuré)**. Ceux qui restent à éprouver sont marqués **(hypothèse)**.

## En une phrase

> **L'Assistant est la porte d'entrée de l'Atelier, à l'écrit comme à l'oral : on lui parle
> d'abord, et il mobilise le reste.** Il règle lui-même l'Atelier : projets, agents, connecteurs,
> applications. Il confie le travail dans les dépôts aux agents code et le suit. Il montre ce dont
> il parle dans le panneau. Chaque action qu'il fait est annoncée et peut être annulée. Il
> n'accorde, ne partage et ne pousse jamais à la place de la personne.

---

## 1. Le problème, vu par la personne

- **Claire** ouvre l'Atelier et trouve quatre onglets : Code, Assistant, Connecteurs, Agents.
  « Assistant » est un panneau d'attente qui parle de `wikichat-memory` **(mesuré,
  `web/index.html`)**. Elle ne sait pas où dire « je voudrais une carte de mes logements
  vacants ».
- **Karim** veut une veille sur deux projets. Pour cela, il remplit un formulaire d'agent : nom,
  consignes, outils, projet, fréquence, modèle. Ensuite, pour savoir où en est un agent, il relit
  un transcript.
- **Nicolas, un lundi**, lit le résumé des gardiens, deux files de propositions **(mesuré,
  `views/agent.js`)**, puis les fils wikichat et les `ETAT.md`, chacun ailleurs.
- **Tous les trois** voudraient parfois simplement **parler**, montrer du doigt une zone d'une
  carte et dire « ici ».

Ce qui manque est un interlocuteur unique qui voit tout, parle leur langue, agit pour eux et
montre ce qu'il fait.

---

## 2. Ce qui existe déjà

| Brique | État | Ce qu'elle apporte |
|---|---|---|
| Vue « Assistant », `wikichat-memory`, `kind=assistant` | panneau d'attente ; slug et `kind` dans l'API et `state.js` **(mesuré)** | l'emplacement et le lieu des sessions (`assistant/sessions/<uuid>/`) |
| Fil de conversation | complet côté Code : défilement ancré, reprise d'un message, attente lisible | réutilisable tel quel |
| Outils MCP `atelier_*` | 14 : conversations (`ouvrir`, `envoyer`, `suivre`, `interrompre`, `transcript`, `decider`…) et artefacts (`creer`, `demarrer`, `arreter`, `journal`, `verifier`) **(mesuré)** | déléguer, suivre, piloter une application |
| API HTTP de l'Atelier | projets (`POST /projects`, git), connecteurs (`/mcp/import`, `probe`, `profiles`), compositions, agents (`POST /agent`) **(mesuré, `api.py`)** | les commandes existent, **mais pas encore comme outils** de l'Assistant |
| `atelier_envoyer` | rend la main aussitôt ; refuse un `bypassPermissions` que la conversation n'a pas **(mesuré)** | déléguer sans élever les droits |
| Hooks wikichat, fils, `ETAT.md` | hooks entre 128 et 165 ms ; fils avec débiteur et échéance ; `ETAT.md` avec « À décider » **(mesuré)** | contexte préparé hors du modèle ; qui attend qui |
| Panneau (proposé) | onglets, `atelier_montrer`, **Montrer**, **Prendre la main**, feuille plein écran sur mobile (`panneau.md`) | le lieu où il montre, et où on lui montre |
| Service vocal | `voice_service.py` : STT faster-whisper `small` sur CPU, tranches de 3 s ; TTS Kokoro, voix `ff_siwis` ; outils MCP `dire`, `ecouter` ; WER 2,8 % sur 12 phrases **(mesuré, `stt-tts-atelier.md`)** ; aucune visio (WebRTC) | la base de l'oral ; la visio reste à écrire |
| Modèles SSPCloud | `qwen3-*`, 131 072 jetons, **premier mot à 7,9 s**, pas de recherche d'outils **(mesuré)** | peu d'outils, contexte trié, latence à masquer à l'oral |
| Usage du 25/09 | le modèle a enchaîné des appels malgré « sans rien lancer » **(mesuré)** | une limite doit être tenue par les outils |

---

## 3. La proposition

### 3.1 Qui fait quoi derrière l'Assistant

« Jarvis » est une illustration. Les capacités viennent de **l'Atelier au complet**, et
l'Assistant en est l'interface.

| Capacité perçue | Qui la fournit vraiment |
|---|---|
| « Il se souvient, il fait le lien avec ce qu'on a dit » | **wikichat** : `recall`, `search_knowledge`, clôtures, fils |
| « Il sait où en est tout » | **le code de l'Atelier** : le bloc « Atelier maintenant » (hook), le carnet de bord, `ETAT.md` écrit par les agents |
| « Il crée et règle » | **les commandes de l'Atelier** (§3.3), qui appliquent les règles |
| « Il fabrique » | **les agents code**, dans les dépôts, sur des branches, avec `/verifier` |
| « Il travaille pendant que je dors » | **les tâches automatiques**, plafonnées |
| « Il m'a prévenu d'une panne » | **les gardiens**, sans modèle ; il relaie |
| « Il me montre » | **le panneau** et l'hôte des applications ; il appelle `atelier_montrer` |
| « Il lit mes données » | **les connecteurs**, avec les autorisations de la personne |
| « Il me parle » | **le service vocal** : STT, TTS, et plus tard la visio |

L'Assistant lui-même **comprend**, **conseille**, **décide avec** la personne (une option par
défaut, et la seule alternative qui compte), **agit** par les commandes, **délègue et suit**, puis
**rend compte** en trois lignes : fait, vérifié par quoi, ce qui revient à la personne.

Ce qu'il ne fait **jamais**, tenu par construction (l'outil n'existe pas pour lui) :

- écrire dans le contenu d'un dépôt ;
- surveiller ou réparer à la place des gardiens ;
- accorder, installer, partager, fusionner, pousser, supprimer ;
- voir un secret.

### 3.2 La frontière : ce qu'il fait lui-même, ce qu'il confie

Il agit **lui-même** si les cinq critères sont réunis :

1. une commande de l'Atelier existe pour ce geste ;
2. l'effet porte sur **la configuration d'un objet de l'Atelier** : fiche de projet ou d'agent,
   connecteur, état d'une application, tâche automatique. Il ne porte **pas sur le contenu d'un
   dépôt** ;
3. il tient en quelques appels, sans essai ni erreur ;
4. une commande inverse permet de l'annuler ;
5. la commande dit elle-même si elle a réussi.

Il **confie** à un agent code s'il faut écrire du code, une page ou des données, tester, itérer,
travailler plus de quelques minutes, ou se servir d'outils lourds (navigateur, bureau, terminal).

| Demande | Qui | Pourquoi |
|---|---|---|
| « Crée un projet pour ma carte », « renomme-le » | lui | `projet_creer` pose la structure type ; renommer ne touche que le titre **(mesuré)** |
| « Fais-moi la carte » | lui, puis un agent | il crée le projet cadré, puis confie la page |
| « Une veille chaque lundi sur mes deux projets » | lui | fiche d'agent, qui naît désactivée |
| « Branche Grist », « redémarre ma carte » | lui | connecteur du catalogue ; `atelier_artefact_demarrer` **(mesuré)** |
| « Change le titre affiché sur la carte » | un agent | le titre est dans la page, donc dans un dépôt ; c'est petit, mais vérifié |
| « Fais de mon script un outil pour mes collègues » | un agent | un connecteur maison, c'est du code |
| « Partage la carte à Sophie » | la personne | il prépare l'écran d'accord ; elle clique |

À la personne, il le dit ainsi : **« je règle l'Atelier ; ce qui s'écrit dans vos créations, je
le confie à un agent et je vous montre le résultat. »**

### 3.3 Les commandes, assemblées selon la demande

Une commande est un outil qui **applique les règles**. Exemple : `projet_creer(titre, but)` pose
d'office la structure type de `structure-projet.md` :

- le dépôt et son commit d'ouverture ;
- `projet.json` ;
- `ETAT.md` au gabarit ;
- le `CLAUDE.md` qui importe le contexte ;
- le `.mcp.json`.

Elle rend ce qu'elle a fait et comment l'annuler.

Les commandes sont groupées en familles :

- **toujours chargées** : Lire, Mémoire, Déléguer (`atelier_decider` bridé), Montrer
  (`atelier_montrer`), Annuler ;
- **chargées selon la demande** : Projets, Agents, Connecteurs, Créations (démarrer, arrêter,
  préparer une installation ou un partage), Voix.

**Hypothèse (A0)** : une quinzaine d'outils de socle, plus une ou deux familles, tiennent sur
`qwen3`. Le mécanisme de chargement revient à l'équipe harness. L'effet visible attendu est
qu'il ne propose jamais un geste dont il n'a pas la commande : « je ne sais pas encore faire ça
moi-même, je peux le confier à un agent ».

### 3.4 Sa place : la porte d'entrée, à l'écran

**L'Atelier s'ouvre sur le fil de l'Assistant.** Les autres vues deviennent des lieux où l'on va
voir en détail ou reprendre la main : Projets (l'actuel « Code »), Connecteurs, Tâches
automatiques, Gardiens.

```
Grand écran, à l'écrit                          Grand écran, en visio
┌ [Assistant] Projets Connecteurs Tâches … ┐      ┌──────────────┬────────────────────────────┐
│ Fil                  │ PANNEAU            │      │ Fil (transcrit│ PANNEAU : vue diffusée     │
│ ┌ Projet créé ─────┐ │ onglets :          │      │  en direct)   │  (la carte, QGIS, n8n…)    │
│ │ Voir · Annuler   │ │  Aujourd'hui       │      │ cartes        │  ┌────────┐ désignation    │
│ └──────────────────┘ │  Carte logements   │      │ d'action      │  │ Visio  │ par l'Assistant│
│ [composeur]  [micro] │  …                 │      │ [composeur]   │  └────────┘ (vignette)     │
└──────────────────────┴────────────────────┘      └──────────────┴────────────────────────────┘
Mobile : une chose à la fois. En visio, la vue diffusée occupe l'écran, la vignette Visio est
dans un coin et le micro en bas. Le fil (sous-titres et cartes) se tire du bas en feuille.
```

- **Un fil continu** pour la personne. Il est découpé en sessions invisibles dans
  `assistant/sessions/` ; la continuité vient de la mémoire et de l'état recalculé
  **(hypothèse)**.
- **L'onglet « Aujourd'hui »** du panneau est calculé par le code, sans modèle. Il montre :
  - la file « À valider » ;
  - les délégations en cours ;
  - la santé des créations ;
  - le résumé des gardiens ;
  - « Ce que j'ai fait aujourd'hui ».
- **Disponible partout, sans second fil.** Depuis un projet, **Demander à l'Assistant** ramène à
  l'accueil avec le contexte. On évite ainsi « deux agents, deux fils » (relecture, K1).
- **Les liens** :
  - la file « À valider » reste la source unique des accords ;
  - le résumé des gardiens est cité, pas réécrit ;
  - ses délégations apparaissent dans leur projet, marquées « lancée par l'Assistant ».
- **Pour Nicolas**, un pli **Détail** montre les commandes appelées, le bon de commande et le
  coût.

### 3.5 La délégation

Le **bon de commande** fait sept lignes, lisibles dans le Détail : objectif ; « fini quand »
(`/verifier` passe) ; périmètre (projet, brouillon, lecture seule) ; hors périmètre (installer,
partager, pousser) ; plafond ; attendu à la fin (`ETAT.md` à jour, message `done`) ; conduite si
l'agent est bloqué (une question dans « À décider », puis arrêt).

Le lancement passe par l'Atelier (lot D) : `atelier_ouvrir`, puis `atelier_envoyer` en mode
**Édite** avec `peut_attendre = vrai`. Une autorisation hors périmètre arrive dans « À valider ».

**Le suivi ne réveille pas l'Assistant.** Le code tient un carnet de bord (fin, erreur,
autorisation en attente, question, `done`, plafond). Ce carnet alimente « Aujourd'hui », et il
arrive à l'Assistant au tour suivant de la personne, par le hook `UserPromptSubmit`. Le mot
**« vérifié » n'est permis qu'avec une preuve au carnet**.

### 3.6 Fiable et compréhensible alors qu'il agit beaucoup

1. **Une carte par action**, émise par la commande, pas rédigée par le modèle : verbe, objet, ce
   qui a été posé, **Voir**, **Annuler**. Un « c'est fait » sans carte se voit.
2. **Trois classes d'actions**, fixées par la commande :

| Classe | Exemples | Ce que voit la personne |
|---|---|---|
| **Réversible** | créer ou renommer un projet ; créer un agent désactivé ; ajouter un connecteur du catalogue ; démarrer une application ; lancer un agent code en brouillon dans les plafonds | fait tout de suite ; carte avec **Annuler** |
| **Engageante** | activer une tâche automatique ; dépasser un plafond ; donner de l'écriture ; **plus de trois actions à la suite** | un aperçu (la liste, le coût en part du forfait) et **Oui** ; rien avant |
| **Réservée** | installer, partager, fusionner, pousser, accorder, supprimer | il ouvre l'écran d'accord ou « À valider » ; la personne décide |

3. **Le retour arrière.** Chaque commande réversible garde l'état d'avant et son inverse : créer
   donne ranger, activer donne désactiver, ajouter donne retirer. **Annuler** est offert sur la
   carte et dans « Ce que j'ai fait aujourd'hui ». On peut aussi le dire : « annule ça ». Ce qui ne
   s'annule pas est dit **avant** : le travail d'un agent code reste sur sa branche et l'on refuse
   la proposition. Les objets qu'il crée portent « créé par l'Assistant, le … ».

### 3.7 Les limites

Cohérent avec `synthese.md` §4 : rien à accepter en brouillon ; un seul écran groupé pour
installer ou partager ; lecture seule par défaut ; dépense en part du forfait.

- **`atelier_decider`** : il peut **refuser** seul, avec un motif. Il ne peut **jamais accepter** :
  la demande passe dans « À valider ». C'est une règle du serveur.
- **Aucun secret** : aucun outil ne rend de valeur. Pour un identifiant, il renvoie à la page de
  connexion du service, ouverte dans le panneau. `atelier_transcript` et `atelier_suivre` rendent
  aujourd'hui le texte brut **(mesuré)** ; la sanitisation de l'export mémoire (onze motifs,
  **mesurée**) doit s'y appliquer.
- **Aucune dépense sans plafond** : chaque délégation et l'Assistant lui-même ont un plafond par
  jour. Il ne tourne que sur une parole ou un message de la personne, ou à l'ouverture du matin
  **(hypothèse de coût, à mesurer au relais)**.
- **Ce qu'il montre** : il n'ouvre une vue que dans le panneau de la personne. Un bureau diffusé
  ne lui est jamais transmis en silence (`panneau.md` §3.9) : il n'en voit que ce que la personne
  montre, ou une capture qu'il a demandée et qui s'affiche dans le fil.

### 3.8 Le ton, à l'écrit

| Règle | Oui | Non |
|---|---|---|
| Court, la réponse d'abord (cinq lignes au plus) | « C'est lancé, je vous préviens. » | reformuler en trois paragraphes |
| Une question au plus, avec une réponse proposée | « Fond IGN, ça vous va ? » | quatre questions avant d'agir |
| Le degré de certitude à chaque fois | « vérifié », « d'après l'agent », « je ne sais pas, je regarde » | « c'est corrigé » sans preuve |
| Le lexique de l'écran seulement | création, installer, partager, à valider | artefact, MCP, jeton, branche |
| Une initiative bornée, dite une fois | « Votre veille a été coupée. La relancer une fois ? » | relancer d'office |
| Refuser en proposant le geste permis | « Je ne pousse rien ; **Partager…** fait ce que vous voulez. » | refus sec, flatterie |

### 3.9 À l'oral : la visio est une vue du panneau

La visio n'est pas un système à part. C'est **un onglet du panneau**, servi par le même chemin que
les autres vues diffusées (hôte des applications, relais WS, contrat MCP Apps). Le son et l'image
sont des flux de plus. Pendant la conversation, **l'Assistant montre** (`atelier_montrer` ouvre la
carte, QGIS, n8n, une application) et **la personne montre** (**Montrer**, un clic ou une
sélection dans la vue). C'est un partage d'écran dans les deux sens.

| Aspect | Proposition |
|---|---|
| **Ton** | phrases parlées, sans liste ni chiffre inutile ; tutoiement ou vouvoiement repris de l'écrit ; aucun nom de fichier ou d'outil prononcé |
| **Longueur** | une à deux phrases, puis il s'arrête. Le détail va dans le fil, pas dans l'oreille : « le détail est dans le fil » |
| **Latence** | la chaîne mesurée est longue : tranche STT de 3 s, puis 7,9 s avant le premier mot du modèle **(mesuré)**. Un **accusé immédiat sans modèle** (« je regarde », « d'accord ») part dès la fin de parole. Les réponses d'état (« où en est… ») se lisent dans le carnet et se disent par gabarit, sans modèle **(hypothèse à mesurer : moins de 2 s)**. Le TTS parle phrase par phrase dès la première |
| **Pendant qu'il travaille** | une phrase à l'annonce (« c'est lancé, une dizaine de minutes »), puis le silence. Pas de meublage. Un son discret et une phrase à la fin, si la visio est encore ouverte ; sinon c'est l'écrit qui prend le relais |
| **Interruption** | la personne parle, il se tait aussitôt. La phrase coupée est marquée « interrompu » dans le fil. « Stop » ou « attends » arrêtent sa parole, **pas** le travail délégué ; « arrête l'agent » l'arrête, avec une carte |
| **Voix et écrit** | un seul fil. Chaque échange oral y est transcrit des deux côtés, avec les cartes d'action. On peut taper pendant la visio, et quitter la visio sans rien perdre. Les transcriptions se capitalisent comme toute conversation |
| **Le panneau pendant qu'il parle** | la vue dont il parle est au premier plan. Il **désigne** une zone (surlignage passé à la vue par le pont MCP Apps, **hypothèse**). Les sous-titres défilent sur la vignette Visio. Les cartes d'action s'affichent dans le fil, jamais en surimpression |
| **Accords à l'oral** | une action engageante ou réservée ne se valide **jamais à la voix seule** : l'aperçu s'affiche et l'on clique **Oui**. À la voix, on peut annuler une action réversible |

---

## 4. Parcours

Chaque parcours donne ce que voit ou entend la personne, puis **Derrière** : qui fait quoi.

**P1. Premier contact (Claire, écrit).** L'Atelier s'ouvre sur « Bonjour. Je peux fabriquer des
cartes, des tableaux ou des pages à partir de vos données, et vous prévenir si quelque chose
casse. Qu'est-ce qui vous occupe ? » Elle répond « le logement, mes données sont dans Grist ». Une
carte **Brancher Grist** apparaît, et elle se connecte sur le site de Grist, dans le panneau. Puis
: « Je vois 4 documents, dont *Études 2026*. »
*Derrière* : le message d'accueil est un gabarit (aucun jeton). L'état de l'Atelier dit que Grist
n'est pas branché ; le connecteur fait l'OAuth ; wikichat retient son domaine et sa source.

**P2. « Fais-moi X » devient un projet (Claire, écrit).** Elle dépose `logements_vacants.xlsx` :
« une carte par commune ». Une carte « Projet *Carte logements* créé · Voir · Annuler »
apparaît, puis « c'est lancé, une dizaine de minutes ». À son retour : « **Prête.** Vérifié :
elle lit vos 312 communes. Non vérifié : 3 communes sans code INSEE. **À vous :** la regarder, à
droite. »
*Derrière* : `projet_creer` pose la structure. Un agent code écrit la page et lance
`/verifier`, et le carnet le suit. L'Assistant rédige le compte rendu à partir du carnet et
d'`ETAT.md`, puis ouvre la création par `atelier_montrer`.

**P3. Créer un agent (Karim, écrit).** « Chaque lundi, un point sur *Découpage* et *Cadastre*. »
Une carte « Agent *Point du lundi* · 2 projets · lecture seule · lundi 8 h · **désactivé** ·
Annuler » apparaît. Puis l'aperçu « environ 1 % de votre forfait par mois. **Activer ?** », et il
clique **Oui**.
*Derrière* : la commande Agents écrit la fiche du pilote avec les plafonds par défaut. L'activation
est engageante. Ensuite, c'est la tâche automatique qui tournera, pas l'Assistant.

**P4. Un connecteur (Nicolas, puis Karim, écrit).** Nicolas : « Branche GitHub au *Lecteur
Grist*. » Une carte « GitHub ajouté au projet · lecture · Annuler » apparaît. Karim : « Fais de
mon script un outil pour mes collègues. » Réponse : « C'est du code : je crée le projet et je le
confie à un agent. Quand il marchera, vous pourrez l'installer. »
*Derrière* : pour GitHub, la commande écrit le `.mcp.json` du projet. Pour Karim, c'est une
délégation, puis une installation que Karim fait lui-même.

**P5. Une application (Claire, écrit).** « Ma carte ne répond plus. » Une carte « *Carte
logements* redémarrée » apparaît, puis « elle s'affiche de nouveau ». « Je veux que Sophie la
voie » : l'écran **Partager… → Sophie Martin** s'ouvre, prérempli, et Claire valide.
*Derrière* : le carnet dit « arrêtée depuis le redémarrage du pod » ; `atelier_artefact_demarrer`
rend « prête ». Le partage est un geste réservé.

**P6. Le matin (Nicolas, écrit).** « Depuis vendredi : *Lecteur Grist* a fini son lot 3, tests
verts. Deux choses à valider. La veille techno a été coupée samedi : trois fois son budget. » Il
clique **Accepter** sur une correction. S'il n'y a rien de neuf, une ligne suffit.
*Derrière* : le code calcule le bloc « Atelier maintenant ». Les gardiens ont coupé la veille. Le
modèle rédige un seul tour plafonné, et l'Atelier fusionne sur son clic.

**P7. « Où en est Y ? » (Karim, écrit).** « Il est bloqué depuis 18 minutes : il veut écrire hors
du projet. C'est dans **À valider** ; sinon je lui dis d'écrire dans le projet. » Karim répond
« dans le projet ».
*Derrière* : le carnet a vu l'autorisation en attente. L'Assistant refuse par `atelier_decider`,
avec un motif. Karim n'a lu aucun transcript.

**P8. Une panne (Claire, écrit).** « Votre carte ne s'affiche plus : la colonne *Commune* a été
renommée dans Grist. Une correction est prête. » Elle accepte. « Elle s'affiche de nouveau. »
*Derrière* : un gardien a détecté la panne et fait préparer la correction par un agent. L'Assistant
relaie, lit l'avant/après, et n'annonce le retour qu'une fois le contrôle suivant vert. Si
l'Atelier lui-même tombe, un bandeau calculé par le code le dit.

**P9. Une décision (Nicolas, écrit).** « L'agent du *Lecteur Grist* demande s'il faut passer à
OIDC. Vos notes du 12/09 disent : pas avant `passerelle-auth`. » « On attend. » « Je le lui dis,
et je note la décision. »
*Derrière* : la question vient de la section « À décider » de l'`ETAT.md`. wikichat retrouve la
note par `recall`. L'agent inscrit la décision dans `docs/decisions/`.

**P10. Annuler (Claire, écrit).** « Finalement, mets la carte dans *Études 2026*. » Une carte
« *Carte logements* rangé · Rétablir » apparaît, et la délégation repart dans *Études 2026*. Si
l'agent avait déjà travaillé : « Son travail reste récupérable dans *Projets › Rangés*. »
*Derrière* : la commande inverse de `projet_creer` range le projet ; elle liste les dépendances et
les dit.

**P11. La fin d'un projet (Karim, écrit).** « Avant de clore : l'outil est installé, pas partagé,
et une question reste ouverte. Je clos quand même ? » « Oui. » « Clos. J'ai retenu : découpage
par commune, sortie GeoPackage, 3 communes témoins. »
*Derrière* : `close_project` de wikichat produit la clôture, versée à la mémoire transverse. Le
projet est rangé, pas supprimé.

**O1. Un échange rapide à l'oral (Nicolas, sur mobile, en marchant).**

- Il appuie sur le micro : « Quoi de neuf ? » Il entend aussitôt « je regarde », puis, en deux
  phrases : « Le lot 3 du lecteur est fini, tests verts. Deux choses t'attendent à valider, je te
  les laisse à l'écran. »
- « Et la veille ? » « Coupée samedi, trop chère. Je la relance une fois ? » « Non, plus tard. »
- Le soir, sur grand écran, le fil porte l'échange transcrit et les deux éléments à valider.

*Derrière* :

- STT du service vocal, tranches de 3 s ;
- accusé par gabarit ;
- réponse d'état lue dans le carnet et le bloc « Atelier maintenant » ;
- TTS Kokoro ;
- aucune action : rien n'est validé à la voix.

**O2. Un travail long, suivi à l'oral puis retrouvé à l'écrit (Claire, grand écran, en visio).**

1. « Fais-moi une carte des logements vacants par commune, avec mes données Grist. » Elle entend
   « d'accord, je crée le projet et je lance la carte, une dizaine de minutes ». La carte
   d'action apparaît dans le fil, puis le silence.
2. Cinq minutes plus tard : « Montre-moi où en est la carte. » L'onglet *Carte logements* passe au
   premier plan, en brouillon, et la vignette Visio se range dans un coin. « Voici le brouillon.
   Les communes sont là, la légende pas encore. » La zone sans données est désignée sur la carte.
3. Elle clique deux communes et dit « ici, elles ont fusionné ». « Noté, je le passe à l'agent. »
   Une carte « Consigne transmise » apparaît dans le fil.
4. Elle coupe la visio pour une réunion. Une heure après, à l'écrit : « **Prête.** Vérifié : 312
   communes, fusion appliquée. **À vous :** la regarder. » Le fil contient tout l'échange oral.

*Derrière* :

- l'Assistant crée le projet et délègue ;
- `atelier_montrer` ouvre la vue ;
- l'hôte des applications diffuse la page ;
- **Montrer** envoie la sélection (deux communes) à l'Assistant, qui la transmet à l'agent code
  par `atelier_envoyer` ;
- le carnet déclenche le compte rendu au retour.

La page, elle, n'a jamais été modifiée par l'Assistant.

**O3. Montrer dans un bureau (Karim, QGIS en visio).** « Regarde cette couche, les limites sont
décalées. » Il sélectionne la couche dans QGIS diffusé et clique **Montrer**. « Je vois un
décalage d'environ 50 m vers l'est, sans doute une projection. Je confie la vérification à un
agent ? » À l'écran : la capture dans le fil, et dans le panneau une proposition « Confier ».
*Derrière* : le bureau QGIS est relayé par l'hôte des applications. La capture n'est envoyée que
sur le geste de Karim. L'analyse, s'il l'accepte, revient à un agent code.

---

## 5. Étapes

| Étape | À la fin, on peut… | Dépend de | Taille |
|---|---|---|---|
| **A0 Mesurer** | sur `qwen3`, vingt demandes types : bon outil, respect de la frontière, ton, comptes rendus ; latence orale de bout en bout | relais, service vocal | S |
| **A1 Fil et socle** | parler à l'Assistant sur l'accueil ; familles Lire, Mémoire, Déléguer ; `decider` bridé ; transcripts filtrés | lots A et C | M |
| **A2 Commandes** | `projet_creer` conforme, agents, connecteurs du catalogue ; cartes d'action, **Annuler**, journal du jour | lot G, API existante | M |
| **A3 « Aujourd'hui » et délégation** | panneau calculé sans modèle, carnet de bord, compte rendu ; `atelier_montrer` | lot D, J1, J2 (P1, P2) | M |
| **A4 La voix sans visio** | micro dans le composeur ; accusé et réponses d'état par gabarit ; TTS phrase par phrase ; interruption ; transcription dans le fil | service vocal servi comme artefact, A3 | M |
| **A5 La visio, vue du panneau** | onglet Visio ; vue diffusée et désignation pendant qu'il parle ; **Montrer** à l'oral ; disposition mobile | J5 (panneau P3, P4), besoin visio écrit (`stt-tts-atelier.md`) | L |

La démonstration rejouable sur le pod est P2, P7, P10, puis O1. O2 demande A5.

---

## 6. Risques et questions

**Risques**

- **Il agit trop vite** : la classe d'une action est fixée par la commande ; au-delà de trois
  actions, il présente un plan ; chaque action a sa carte et son **Annuler**.
- **Il fait écran entre Karim et ses agents** : **Voir le travail** figure sur chaque compte
  rendu.
- **La frontière glisse** : il n'a pas l'outil d'écriture, donc la frontière est dans le harnais.
- **Fausses certitudes** : « vérifié » exige une preuve au carnet.
- **L'oral est lent** : environ 11 s entre la fin de parole et le premier mot, en additionnant les
  mesures connues. Parade : accusé et réponses d'état sans modèle. **Si l'objectif de moins de
  2 s n'est pas tenu en A0, l'oral reste réservé aux échanges d'état.**
- **Un accord arraché à la voix** : aucun accord à la voix seule.
- **Le fil unique et la compaction** : ce qui compte est en mémoire et dans l'état ; sinon il dit
  « je n'ai plus le détail ».
- **L'Atelier en panne rend l'Assistant muet** : un bandeau calculé par le code prend le relais.
- **Une annulation incomplète** : la commande inverse liste les dépendances.

**Questions pour Nicolas**

1. L'accueil devient-il le fil de l'Assistant, avec « Code » renommé « Projets » ?
   *Recommandation : oui.*
2. La frontière du §3.2 s'applique-t-elle sans exception, même à la retouche d'un mot dans une
   page ? *Recommandation : oui ; c'est ce qui la rend explicable.*
3. Trois classes d'actions portées par les commandes, avec un plan au-delà de trois actions ?
   *Recommandation : oui.*
4. Lancer un agent code sans accord, en brouillon et dans les plafonds, quand la personne l'a
   demandé ? *Recommandation : oui, annoncé par une carte.*
5. Pour `atelier_decider`, refuser seul et ne jamais accepter ?
   *Recommandation : oui, tenu par le serveur.*
6. Quelle latence orale est acceptable, et faut-il des réponses d'état sans modèle à l'oral ?
   *Recommandation : oui, et moins de 2 s pour l'accusé.*
7. Un accord peut-il jamais se donner à la voix ? *Recommandation : non.*
8. Une seule file « À valider », qui absorbe celle des agents planifiés ?
   *Recommandation : oui.*
9. Le carnet de bord et le journal d'actions vivent-ils dans l'Atelier ou dans wikichat ?
   *Recommandation : dans l'Atelier, wikichat ne portant que les messages.*

---

## 7. Évaluation

| Critère | Verdict | Pourquoi |
|---|---|---|
| **Désirable** | oui : Claire d'abord, Nicolas le lundi et en mobilité, Karim s'il ne fait pas écran | on demande en phrases ou à voix haute, on voit ce qui a été fait, on annule d'un geste, on montre du doigt |
| **Faisable** | oui pour l'écrit (étapes M) ; l'oral fluide et la visio restent à prouver | commandes en API, délégation, hooks et service vocal existent **(mesuré)** ; il manque les outils qui appliquent les règles, les cartes, le carnet, le bridage, le filtre, la visio |
| **Viable** | à mesurer (A0) | peu coûteux s'il ne tourne que sur une parole ou un message et si le code prépare le contexte ; inconnues : choix d'outils et ton sur `qwen3`, latence orale |
| **Cohérente** | oui | lexique et accords de `synthese.md` ; ni gardien ni file de plus ; la visio est une vue du panneau ; lancements par le lot D |
