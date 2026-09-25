# Lecteur Grist

Ce projet transforme un document `.grist` en application consultable et
éditable dans le navigateur, sans instance Grist : un seul fichier HTML,
aucun serveur. La cible principale est le **fichier local** (`file://`,
double-clic, n'importe quelle machine) ; l'Atelier peut aussi le servir comme
artefact statique derrière sa connexion.

## Ce que doit être le lecteur (spécification de Nicolas, 24/09/2026)

Elle prime sur tout ce qui suit.

1. Un seul fichier HTML, qui marche en `file://` sans installation, sans
   serveur, **sans aucune connexion à un serveur Grist**.
2. Il lit des `.grist` **normaux, non modifiés** : pré-embarquer par un outil
   n'est jamais nécessaire.
3. Les widgets tournent comme dans Grist : chargés **à leur adresse** (GitHub
   Pages, jsDelivr…) sur une machine connectée, y compris leurs requêtes web
   (tuiles, `?scene=…`, API) ; **hors ligne**, depuis une copie (cache du
   navigateur, et/ou copie rangée dans un `.grist` enregistré — optionnelle) ;
   « construits si besoin » ; Builder et embarqués depuis le document ;
   widget inaccessible signalé avec sa raison, sans casser le reste.
4. Toutes les pages et vues utilisables (grilles, fiches, listes de fiches,
   graphiques, formulaires ; signaler ce qui ne l'est pas).
5. Jetons (`app_token=…`) jamais affichés en clair. Pas de dépendance réseau
   pour le lecteur lui-même.
6. À terme, le lecteur servira de **modèle d'application** servi par un petit
   serveur (fichier SQLite de l'application côté serveur, accès public réglé
   par les ACL du document) : tout accès aux données passe par `Donnees`, tout
   accès réseau pour les widgets par `ReseauWidgets` (voir le readme).

## Mode application, lots 0 à 5 (25/09/2026)

Conception : `docs/lecteur-grist-application.md` (dépôt de l'Atelier). Code
dans `serveur/` du projet (paquet `lecteur_grist`), installé par
`sh serveur/installer.sh` dans `.venv` (Python 3.11 par uv, rangé sous
`~/work/.tools/uv-python` dans le pod).

- **Moteur** : `serveur/lecteur_grist/moteur_grist/` = `sandbox/grist` de
  **gristlabs**/grist-core v1.7.19, sans retouche (tests retirés ; LICENSE,
  NOTICE, `RETOUCHES.md`). Client en sous-processus (`moteur.py`,
  `PIPE_MODE=minimal`, marshal ; tube lu **tamponné**, sinon marshal croit à
  une fin de fichier), chargement comme ActiveDoc (`document.py`), écriture
  des actions stockées comme DocStorage (`stockage.py`).
- **Mesures (lot 0)** : `serveur/MESURES.md`. Démarrage 0,7–0,9 s ;
  ouverture 0,15 s à 7,4 s (111 Mo) ; actions en millisecondes sauf
  `RenameColumn` (0,5–1,4 s) ; mémoire 73 à 490 Mo ; fidélité des formules
  égale à Grist (seuls écarts : formules « date du jour », les mêmes dans
  Grist) ; documents écrits par le moteur rouverts dans un vrai Grist sans
  écart.
- **Réouverture dans Grist** : grist-core 1.7.19 **construit depuis les
  sources** (pod : `/tmp/lg/grist-core`, 2,5 min ; poste Windows :
  `yarn install` + `bash buildtools/build.sh prod`, lancé en `unsandboxed`
  avec un Python 3.11), import par l'API et comparaison :
  `serveur/outils/verifier_dans_grist.py`. « Saint Martin_local_test.grist »
  (enregistré par le lecteur) se rouvre ; les copies `_lecteur_hors_ligne`
  survivent (3/3 et 1/1).
- **L'exemple CRESO embarqué n'est pas un document Grist** (pas de
  `schemaVersion`, ni `_grist_Pages`, ni `_gristsys_*`) : Grist refuse de
  l'importer, `init` aussi. Pas remplaçable simplement : le moteur ne le
  migre depuis aucune version supposée ; il faudrait le reconstruire dans
  Grist à partir de ses données.
- **Serveur (lot 1, lecture seule)** : `lecteur-grist init|serve|verifier`
  (`python -m lecteur_grist`). Routes GET compatibles Grist (`tables`,
  `columns`, `data`, `records`), `/api/app`, `/api/evenements` (SSE),
  `/_sante`, préfixe lu dans `X-Forwarded-Prefix`, `--auth aucune` refusé
  hors 127.0.0.1/::1. Comparées à grist-core sur Saint Martin, Charts v4,
  CRM : mêmes tables, colonnes, valeurs (hors « date du jour » et hors ACL,
  non appliquées avant L4).
- **Lecteur en mode serveur** : `SourceServeur` (dans `index.html`)
  implémente `Donnees` sur l'API : réplique sql.js construite depuis
  `/data`, valeurs rangées comme DocStorage ; activée quand `api/app`
  répond, sinon mode fichier inchangé. Vérifié par
  `outils/verifier_serveur.py` (Chrome sans tête : fichier contre serveur,
  puis derrière un relais à préfixe).
- **Transfert poste → pod** : aucun canal binaire (les outils Onyxia
  n'acceptent que du texte). Les documents réels restent sur le poste ; le
  code passe fichier par fichier, et chaque commit du pod est comparé à celui
  du poste par son arbre git.
- **Écriture (lot 2)** : `serve` charge le moteur (verrou `.verrou`, WAL,
  `Calculate` de l'ouverture rangé comme action système), une file unique
  (`actif.py`) : moteur puis une transaction SQLite (actions stockées +
  `_gristsys_ActionHistory` tenu comme Grist, `historique.py` et
  `marshal_js.py` : même empreinte octet pour octet) ; moteur mort ou
  transaction refusée : rien d'écrit, moteur relancé. Routes au format Grist :
  `POST /apply`, `POST|PATCH|PUT …/records`, `…/records/delete`, `…/data`,
  `GET …/download` (`nohistory`) ; erreurs comme Grist (`operations.py`).
  `journal.sqlite`, sauvegardes `VACUUM INTO` (48 + 14 quotidiennes),
  `lecteur-grist sauvegarder|restaurer|exporter`. SSE `actions` : le
  lecteur (`SourceServeur`) relit les tables touchées ; ses écritures passent
  par `/apply`. Stockage 7 et 8 migrés (migrations 8 et 9 de DocStorage
  portées), avant 7 refusé.
- **Parité d'écriture** : `serveur/outils/parite_grist.py` joue la même suite
  contre grist-core (`GRIST_URL`, `GRIST_CLE`) et contre `serve`, compare
  réponses, toutes les tables, l'historique, puis rouvre notre `/download`
  dans Grist. 0 écart sur 16 documents (hors règle d'accès de CRM, L4).
  Chrome : `outils/verifier_ecriture_navigateur.py DOC.grist` (le document
  est obligatoire hors du poste). À l'arrêt, `serve` coupe les flux SSE au
  bout de 5 s (`timeout_graceful_shutdown`), sinon uvicorn attend les
  navigateurs indéfiniment.
- **Règles d'accès (lot 4)** : `acl_formule.py` (compilePredicateFormula,
  sémantique de JavaScript : ne pas « simplifier » en Python), `acl_regles.py`
  (ACLRuleCollection, PermissionInfo, mémos), `acces.py` (GranularAccess :
  lecture filtrée, métadonnées censurées, contrôles avant et après le
  moteur, `ApplyUndoActions` sur refus). `actif.appliquer(actions, origine,
  user)` : sans `user`, le propriétaire sans contrôle (outils, tests du
  lot 2, règles ajoutées par les outils). Les règles se modifient dans Grist,
  pas depuis l'application.
- **Identité (lot 4)** : `identite.py` ; `serve --auth motdepasse|jetons|
  entete|aucune` ; comptes par `lecteur-grist utilisateurs …`, jetons par
  `lecteur-grist jetons …`, secrets dans `secrets/` (0600). `application.json`
  est relu quand la CLI change un rôle pendant que `serve` tourne.
- **Test différentiel** : `serveur/outils/acl_differentiel.py` contre un
  grist-core lancé avec `GRIST_FORWARD_AUTH_HEADER=X-Forwarded-User`,
  `GRIST_IGNORE_SESSION=true`, `GRIST_IN_SERVICE=true` (sans ce dernier, un
  nouvel utilisateur reçoit 503 « Grist is not yet configured »). Grist sert
  les métadonnées filtrées depuis son DocData : l'ordre des lignes y change
  à chaque suppression (la dernière prend la place) ; `acces.py` tient cet
  ordre. Les adresses lues dans CRM ne sortent pas du test (alias).
  Chrome à deux comptes : `outils/verifier_acces_navigateur.py DOC.grist`
  (contextes de navigation séparés, `Target.createBrowserContext`).
- **Widgets servis (lot 3)** : `widgets.py` ; `lecteur-grist widgets
  recuperer|lister|autoriser`, et les mêmes actions dans le lecteur pour le
  propriétaire (`/api/admin/widgets/recuperer|reseau`). Miroir par chemin
  et copie autonome sous `widgets/<clé>/` (dossier d'application),
  récupérés hors requête par le `Recuperateur` d'`outils/embarquer_widgets.py` ;
  jamais une adresse à jeton. **Règle : le mode servi ne fait jamais moins
  bien que le mode fichier** : même ordre (à son adresse si elle répond,
  puis copie du serveur, du document, du navigateur), même statut, même
  compteur ; `outils/verifier_parite_widgets.py --serveur URL…` le vérifie
  (0 écart attendu, hors copies du serveur comptées à part). Parmi les
  copies du serveur, derrière l'Atelier (`X-Atelier-Acces`), l'autonome
  d'abord. `/widgets/*` : CSP `sandbox` sans
  `allow-same-origin`, réseau = serveur + liste blanche de la section,
  **jamais accordée d'office** (le propriétaire accorde ce qui lui est
  proposé). `--port-widgets` : vraie origine distincte, seule façon d'avoir
  un `Referer` (tuiles OpenStreetMap). `POST /api/jeton` + `?auth=`
  (getAccessToken : 15 min, lecture seule en « read table », règles de
  l'utilisateur). Document d'essai : `outils/fabriquer_essai_widgets.py
  --moteur` (écrit par le moteur, accepté par `init`). Tests :
  `serveur/tests/test_widgets.py`.
- **Artefact serveur (lot 5)** : `artifacts/application/` (`artefact.json`
  au format du manifeste déployé, lu dans `apps/manifeste.py` ; dossier
  d'application `artifacts/application/dossier/`, ignoré par git). Créer
  par `~/work/bin/atelier-app creer projet-sans-nom-5 <nom> serveur` (il
  pose un gabarit et `.auteur`), démarrer par `atelier-app demarrer` avec
  le même `ATELIER_AUTEUR`. `--auth entete --entete-utilisateur
  X-Atelier-Utilisateur` : l'Atelier envoie `proprietaire`, traduit par la
  table `identites` d'`application.json`. Adresse :
  `https://user-nic01asfr-atelier-apps.user.lab.sspcloud.fr/projet-sans-nom-5/application/`.
  Vérification de bout en bout sans navigateur ouvert : passage par code
  (`POST /v1/auth/cookie` avec la clé lue sur le disque, jamais affichée,
  puis `…/ouvrir`) ; le cookie `__Host-atelier_apps` ne se montre pas.
  Limites relevées : un widget qui appelle lui-même l'API avec son jeton
  reçoit 401 du relais (pas de cookie depuis une origine opaque) ; pas de
  tuiles à `Referer` derrière l'Atelier.

## Lot « widgets par leur adresse » (24/09/2026, nuit)

- **Côté hôte de grain-rpc** (`HoteWidget`, d'après `WidgetFrame.ts`,
  `CustomView.ts`) pour un cadre **à l'adresse réelle** du widget, sans
  sandbox, avec son propre `grist-plugin-api.js` : paramètres d'adresse de
  Grist (`access`, `readonly`, `culture`, `language`, `timeZone`,
  `currency`), événements retenus jusqu'au `Ready`, thème GristLight
  (couleurs calculées depuis grist-core, nécessaires au calendrier),
  `fetchTable` des tables de métadonnées, bandeau quand un widget demande
  `getAccessToken`. Le remplaçant local de grist-plugin-api ne sert plus
  qu'aux `srcdoc` (Builder, embarqués, copies) et parle le même protocole
  (thème compris).
- **Sonde** de l'adresse avant de charger (CORS, puis `no-cors`) : 404,
  hôte injoignable, `localhost` d'une autre machine, pas de réponse → raison
  affichée. Page servie en `text/plain` (jsDelivr, raw) → exécutée depuis son
  code avec `<base href>` (« construire si besoin »).
- **Copies hors ligne** : copie du document d'abord, sinon **copie gardée par
  le navigateur** (IndexedDB, prise en arrière-plan quand la page a tourné en
  ligne, refaite après 7 jours, jamais pour une adresse à jeton). « Rendre ce
  document autonome » reprend ces copies sans réseau.
- **Jetons masqués** partout à l'affichage (`masquerUrl`).
- Un widget qui n'appelle pas `grist.ready` n'est plus déclaré en panne
  (l'Atlas n'en appelle pas).
- **Vues** : graphiques natifs redessinés en SVG (barres, lignes, aires,
  nuage, camembert, anneau, multiséries ; Kaplan-Meier signalé), liste de
  fiches, formulaires (mise en page `layoutSpec`, envoi = ligne ajoutée),
  calendrier natif (`custom.calendar` = widget calendrier de gristlabs).
  Valeurs marshalées toutes décodées ; dates en secondes (le lecteur les
  prenait pour des jours).
- **Deux interfaces** : `Donnees` (`ouvrir`, `requete`, `appliquerActions`,
  `ecrireMeta`, `exporter` ; aujourd'hui `SourceMemoire`) et `ReseauWidgets`
  (`fetch`, `disponible`).

Vérifié en `file://` dans Chrome 153, Edge 153 et Firefox 155 (Playwright),
réseau puis hors ligne (`offline` et résolution DNS coupée) : « Saint
Martin.grist » d'origine (Etude/Builder, Atlas avec scène et fond de carte en
ligne, scène sans fond hors ligne depuis la copie du navigateur, Coder par son
adresse avec jeton masqué, Atlas (copy) `localhost:8443` signalé) ; carte,
markdown et calendrier gristlabs (« Modèle gestion du patrimoine », document
d'essai) ; markdown servi par jsDelivr construit ; graphiques de
« Pression_Fonciere_Sete », « Untitled document » ; formulaire de
« flood_grist_v3 » envoyé. Puis `outils/verifier_artefact.py` (CSP de
l'Atelier). Captures : scratchpad de la session, `lecteur-final/`.

Limites par navigateur (`file://`) : copies partagées par tous les fichiers
locaux dans Chrome et Edge, propres au fichier dans Firefox (déplacer le
lecteur repart d'un cache vide) ; rien de gardé en navigation privée ;
`allow="clipboard-write"` ignoré par Firefox ; hôtes sans CORS
(`uicdn.toast.com`) : le widget tourne en ligne, mais sa copie navigateur est
incomplète (l'outil Python ou un pack la complète).

## Ce qui existe (au 24/09/2026, après le lot « artefact »)

- `index.html` (1,74 Mo) : l'application, seule source. Elle embarque tout :
  sql.js 1.14.2 en asm.js (`sql-asm-memory-growth.js`, pur JavaScript, sans
  WebAssembly, licence MIT recopiée, 1,33 Mo), l'exemple CRESO (64 Ko de
  `.grist`, 87 Ko en base64), le code. Aucun appel réseau pour lire ou éditer.
- `artifacts/lecteur/index.html` : copie générée par `outils/publier.sh`,
  ignorée par git. Relancer le script après chaque modification de
  `index.html`.
- `outils/embarquer_sqljs.py` : régénère le moteur entre les marqueurs
  `sqljs:debut` / `sqljs:fin` (archive npm figée, sha512 vérifié).
- `outils/verifier_artefact.py` : sert la page avec la CSP exacte de
  l'Atelier sur 127.0.0.1, la pilote dans Chrome sans tête (protocole
  DevTools), déroule le parcours complet en artefact et en `file://`, et
  rend un rapport JSON. C'est lui qui fait foi pour dire « ça marche ».
- `readme.md` : à jour (nom du fichier, fonctionnement en artefact, limites).

## Être servi par l'Atelier

La page est à `/v1/artifacts/projet-sans-nom-5/lecteur/index.html`.
L'adresse du dossier (`…/lecteur/`, slash final) affiche la liste de ses
fichiers, pas la page : l'Atelier ne sert l'`index.html` d'un dossier que
pour un corpus.

Sous la CSP des artefacts (`sandbox allow-scripts allow-forms allow-popups
allow-modals; default-src 'none'; …`), vérifié dans Chrome 153 :

| | En local (`file://`) | Dans l'Atelier |
|---|---|---|
| Ouvrir un `.grist` (glisser, choisir, exemple) | oui | oui |
| Naviguer, sections liées, mode Données | oui | oui |
| Éditer (renommer, écrire par un widget) | oui | oui, en mémoire |
| Enregistrer `.grist`, exporter CSV | oui | **non** : téléchargement bloqué |
| Widgets embarqués (`data:`, `_html`/`_js`), Builder, externes rangés hors ligne | oui, sans réseau | oui |
| Widgets externes, machine connectée | par leur adresse, comme Grist ; copie gardée par le navigateur | depuis la copie du document |
| Widgets externes hors ligne | copie du document, sinon du navigateur ; sinon signalés avec la raison | copie du document, sinon signalés |

Ce qui a été fait, et comment :

1. **Moteur** : la version wasm embarquée échouait sous la CSP
   (`WebAssembly.instantiate` refusé). Remplacée par la version asm.js.
   Mesuré sur 100 000 lignes, asm contre wasm : initialisation 124 contre
   24 ms, insertion 657 contre 336 ms, lecture 372 contre 263 ms, GROUP BY 669
   contre 59 ms. Acceptable pour des documents Grist ordinaires.
2. **Stockage** : tout en mémoire, rien dans le navigateur. Enregistrement et
   CSV par Blob + lien. Dans l'artefact, Chrome refuse le téléchargement
   (« Download is disallowed… sandboxed, but the flag 'allow-downloads' is
   not set ») sans que la page le sache : elle le tente et affiche un avis
   qui renvoie vers le fichier local.
3. **Widgets** : un widget embarqué tourne en `srcdoc` (la CSP bloque tout
   cadre chargé par adresse, `data:` compris, mais pas `srcdoc`), dans une
   origine à part. Son `grist-plugin-api.js` distant est remplacé par un
   équivalent écrit dans la page (`gristPluginApiLocal`), qui parle le même
   grain-rpc. Un widget externe est signalé « Widget externe, non disponible
   ici » avec son adresse, puis les données brutes de sa table.
4. **Exemple** : déjà embarqué, assez petit : le bouton reste dans l'artefact.
5. **Emoji** : retirés (disquette, armoire, avertissements).

## Lot « widgets hors ligne » (24/09/2026, soir)

Objectif de Nicolas : tout le document, widgets compris, tourne en local et
dans l'Atelier sans réseau.

- **Builder** : le constat « Widget externe, non disponible ici :
  …/custom-widget-builder/index.html » venait d'un jugement sur l'adresse. Le
  code est dans le document (`customView.widgetOptions._html`/`_js`) ; le
  lecteur l'exécute comme `api.js` du Builder (lu dans gristlabs/grist-widget,
  identique chez gristgouv) : `_html`, puis grist-plugin-api, puis
  `<script>_js</script>`. Pas de `_css`, aucune bibliothèque injectée : la page
  du Builder n'est pas nécessaire. L'exemple CRESO embarqué n'a **pas** de
  widget Builder (sections « Widget demo » et « Artefactory » sans options) :
  le constat venait d'un autre document.
- **Résolution d'une section** : copie `_lecteur_hors_ligne` (dans
  `customView`, forme de outils/embarquer_widgets.py, `ref` compris ; lue aussi
  dans `widgetOptions`) > pack importé (rangé à l'import dans le document) >
  code Builder > `data:` / `_html` > adresse en direct hors artefact >
  « non disponible », avec la marche à suivre.
- **grist-plugin-api local** réécrit d'après grist-core (grist-plugin-api.ts,
  objtypes.ts, WidgetFrame.ts, CustomView.ts, ViewSectionRec.ts) : mappings,
  `mapColumnNames`, Ref affichée par sa colonne d'affichage, `Reference`,
  `GristDate`, format colonnes de `fetchSelectedTable`, niveaux d'accès,
  `setOptions` écrit dans le document, `setSelectedRows`/`allowSelectBy`
  filtrent les sections liées, `applyUserActions` tout ou rien.
- **Fléchage** : Données > Widgets (et « Widgets n/N » dans la barre
  latérale) ; couverture en tête, statut et marche à suivre par widget, clic
  vers la section.
- **Rendre ce document autonome** : en local avec Internet, le lecteur
  récupère les widgets par `outils/embarqueur-widgets.js` (écrit par l'autre
  agent, recopié dans la page par `outils/embarquer_embarqueur.py` entre
  `embarqueur:debut`/`fin`), range les copies, et le `.grist` enregistré
  tourne ensuite dans l'artefact.
- **Pack de widgets** (`{"version":1,"widgets":[…]}`) : choisi ou glissé.

Vérifié par `outils/verifier_artefact.py --autonome …` (Chrome 153, CSP
exacte, `file://` puis artefact), document d'essai fabriqué par
`outils/fabriquer_essai_widgets.py` : Builder (mappings, Ref, dates,
ChoiceList, setSelectedRows, setCursorPos, setOptions, fetchTable, create),
carte gristlabs (3 marqueurs, sans tuiles), markdown gristlabs : tournent dans
l'artefact, après outils/embarquer_widgets.py, après import de pack, et après
« Rendre ce document autonome » + enregistrement + réouverture sous la CSP.
**Calendrier gristlabs : ne tourne pas** (`tui is not defined`, CORS de
uicdn.toast.com depuis le lecteur) : côté récupérateur.

(Les sections natives graphiques, formulaires, calendrier et listes de
fiches sont rendues depuis le lot « widgets par leur adresse ».)

## Widgets externes hors ligne (outils, au 24/09/2026)

Objectif : faire tourner sans réseau tout un document, widgets compris.

- `outils/embarqueur-widgets.js` : module ES sans dépendance, le même dans le
  lecteur (recopié entre `embarqueur:debut` / `embarqueur:fin` par
  `outils/embarquer_embarqueur.py`, sous `window.EmbarqueurWidgets`) et dans
  Node. Télécharge la page d'un widget et ses ressources (scripts, CSS et
  leurs `@import`/`url()`, polices, images, modules ES réunis par un petit
  lieur), en fait une page autonome pour la CSP des artefacts, remplace
  `grist-plugin-api.js` par `<script data-lecteur-grist-plugin-api></script>`,
  liste `manquants` (fetch/XHR, tuiles, eval, wasm, workers…), `echecs_cors`
  par adresse, et retente une page `*.github.io` par jsDelivr (`miroirs`).
  Lecture balise par balise, sans analyseur DOM : même html, même sha256
  partout pour les mêmes octets.
- `outils/embarquer_widgets.py` : le même module dans Node, réseau par Python
  (refus des adresses privées après résolution DNS, à chaque redirection ;
  plafonds 10 Mo par ressource, 20 Mo et 300 ressources par widget). Sert
  pour les hôtes sans CORS (`uicdn.toast.com`, calendrier), écrit un nouveau
  `.grist` (`integrity_check`), rend un bilan (code de sortie 1 si un widget
  est impossible, sauf `--tolerer`), et `--pack` fabrique le pack des widgets
  des catalogues gristlabs et gristgouv (63 widgets, 36 Mo, 0 échec le
  24/09).
- Format : `customView._lecteur_hors_ligne = {version: 1, source,
  recupere_le, sha256, html, manquants, echecs_cors, miroirs}` ou renvoi
  `{version, source, recupere_le, ref: <section>}` ; une copie dont `source`
  n'est plus l'adresse du widget est périmée (Grist garde la clé quand on
  change de widget).
- Vérifié : `node --test tests/` (13), `python3 -m pytest tests/` (46 + essai
  réel `ESSAI_RESEAU=1`), pages produites dans Chrome sous la CSP (grist.ready
  appelé, rien de bloqué qui ne soit annoncé), récupérateur dans Chrome depuis
  `file://` et `http://127.0.0.1` (pages GitHub, jsDelivr, cdnjs : sans échec
  CORS). **Non vérifié** : réouverture d'un `.grist` produit dans une vraie
  instance Grist (pas de Docker ; l'extraction de l'image lancée en `chroot`
  a été refusée) — lu dans le source de grist-core que la clé survit.
- Limites : Vue 2/3 qui compilent leurs gabarits (`eval`) ne s'affichent pas
  sous la CSP (factures, bons de commande, bouton d'action, vibe-view) ; les
  cartes n'ont pas de tuiles ; JupyterLite (WebAssembly) ne tourne pas.

## Décisions qui reviennent à l'Atelier

- **Un hôte des widgets** à côté de l'hôte des applications (ou accepter,
  sur `/api/docs/*` d'un artefact serveur, une requête sans cookie qui porte
  un jeton de widget) : sans lui, derrière l'Atelier, les widgets tournent
  en origine opaque, sans `Referer` et sans appel direct à l'API.

- **`allow-downloads`** dans le `sandbox` de `CSP_SANDBOX` : sans lui, rien de
  ce qu'on édite dans l'artefact ne peut en sortir. La page n'a rien à
  changer le jour où il est ajouté.
- **`'wasm-unsafe-eval'`** : plus nécessaire pour ce projet (asm.js). À ne
  décider que si d'autres artefacts en ont besoin, ou pour retrouver les
  performances wasm (GROUP BY ~11 fois plus rapide).
- **Servir `index.html` d'un dossier d'artefact ordinaire** (pas seulement
  d'un corpus), pour que `…/lecteur/` ouvre la page.

## Ce qui reste

- Mode application : L7 (OIDC, public), qui attend les décisions de
  Nicolas ; L6 (configuration, `/api/admin`) ; parseStrings complet, pièces
  jointes, commentaires sous règles, partages. Voir la section « État » de
  la conception.
- Le lecteur servi par l'Atelier, ouvert par la personne depuis
  l'interface de l'Atelier (vérifié par requêtes et par Chrome sans tête
  dans le pod, pas par le bouton « Ouvrir »).
- Remplaçant de grist-plugin-api : pas de `cellFormat: 'typed'`, pas de tri
  de section, pas de modification des colonnes associées.
- Calendrier gristlabs hors ligne depuis la copie du navigateur (CSS de
  `uicdn.toast.com` sans CORS ; il tourne en mode serveur, récupéré par le
  serveur) ; graphiques Kaplan-Meier ; pièces jointes
  (formulaires, `Donnees.pieceJointe`) ; disposition des sections selon
  `layoutSpec` (elles s'empilent).

## Règles propres au projet

- Le fichier `.grist` produit doit se rouvrir dans Grist. Tout changement de
  l'enregistrement se vérifie en rouvrant le fichier dans une vraie instance
  Grist, et le compte rendu le dit.
- Le document ne sort pas du navigateur : ni télémétrie, ni polices ou
  scripts externes pour le lecteur lui-même. Seuls les widgets vont sur le
  réseau, comme dans Grist : chargés à leur adresse, ils reçoivent ce que
  leur niveau d'accès permet ; le lecteur demande leur page (sans cookie)
  pour la sonder et en garder une copie. Toute autre requête passe par
  `ReseauWidgets`.
- Tout accès aux données passe par `Donnees` : rien d'autre ne touche à
  SQLite.
- Aucune adresse ne s'affiche avec un jeton (`masquerUrl`).
- Pas d'emoji dans l'interface (« Enregistrer .grist », pas une disquette).
- Joindre une instance Grist en ligne (lire ou écrire un document distant) est
  hors du périmètre actuel : cela demande un relais côté serveur qui garde la
  clé Grist hors de la page, et c'est un chantier de l'Atelier.
- Après toute modification de `index.html` : `outils/publier.sh`, puis
  `python3 outils/verifier_artefact.py` (mode fichier) et
  `.venv/bin/python outils/verifier_serveur.py DOC.grist` (mode serveur).
- Widgets servis : pas de CSP restrictive sur la page du lecteur servie (les
  widgets en `srcdoc` en hériteraient) ; après toute modification des
  widgets, `outils/verifier_parite_widgets.py`. `lecteur-grist widgets
  recuperer` (ou le bouton du propriétaire) ne tourne jamais pendant
  une requête de lecture ; le réseau d'un widget ne s'accorde qu'à la main
  (`widgets autoriser`), jamais depuis ce que la récupération propose.
- Serveur : `.venv/bin/python -m pytest serveur/tests` ; le moteur
  (`moteur_grist/`) ne se modifie pas à la main (voir `RETOUCHES.md`) ;
  toute écriture du `.grist` se vérifie par réouverture dans grist-core
  (`serveur/outils/verifier_dans_grist.py`).
