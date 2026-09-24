# Lecteur Grist

Ce projet transforme un document `.grist` en application consultable et
éditable dans le navigateur, sans instance Grist : un seul fichier HTML,
aucun serveur. C'est la bonne forme pour l'Atelier, qui sait servir une page
statique derrière sa connexion.

## Ce qui existe (au 24/09/2026, après le lot « artefact »)

- `index.html` (1,52 Mo) : l'application, seule source. Elle embarque tout :
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
| Widgets externes sans copie (`https://…`) | par leur adresse ; « Récupérer » les range dans le document | non, signalés avec la marche à suivre |

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

Sections natives non rendues (données brutes + bandeau) : graphiques
(`chart` : bar, pie, line, kaplan_meier), formulaires (`form`), calendrier
natif (`custom.calendar`). `detail` est affichée comme une fiche.

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

- **`allow-downloads`** dans le `sandbox` de `CSP_SANDBOX` : sans lui, rien de
  ce qu'on édite dans l'artefact ne peut en sortir. La page n'a rien à
  changer le jour où il est ajouté.
- **`'wasm-unsafe-eval'`** : plus nécessaire pour ce projet (asm.js). À ne
  décider que si d'autres artefacts en ont besoin, ou pour retrouver les
  performances wasm (GROUP BY ~11 fois plus rapide).
- **Servir `index.html` d'un dossier d'artefact ordinaire** (pas seulement
  d'un corpus), pour que `…/lecteur/` ouvre la page.

## Ce qui reste

- Rouvrir dans une vraie instance Grist un `.grist` enregistré par le
  lecteur : l'export (`db.export()`) n'a pas changé et le fichier passe
  `PRAGMA integrity_check`, mais la réouverture dans Grist n'a pas été
  refaite.
- Vérification par l'Atelier réel (derrière sa connexion) : faite ici avec un
  serveur local qui reproduit ses en-têtes, pas à travers l'Atelier.
- Remplaçant de grist-plugin-api : pas de `cellFormat: 'typed'`, pas de tri
  de section, pas de thème, pas de modification des colonnes associées.
- Calendrier gristlabs hors ligne ; graphiques natifs de Grist ; formulaires.
- Rouvrir dans Grist un `.grist` portant des copies `_lecteur_hors_ligne`
  (non vérifié : pas d'instance Grist dans le pod).

## Règles propres au projet

- Le fichier `.grist` produit doit se rouvrir dans Grist. Tout changement de
  l'enregistrement se vérifie en rouvrant le fichier dans une vraie instance
  Grist, et le compte rendu le dit.
- Aucune donnée ne sort du navigateur : pas d'appel réseau pendant la lecture
  ou l'édition, ni télémétrie, ni polices ou scripts externes.
- Pas d'emoji dans l'interface (« Enregistrer .grist », pas une disquette).
- Joindre une instance Grist en ligne (lire ou écrire un document distant) est
  hors du périmètre actuel : cela demande un relais côté serveur qui garde la
  clé Grist hors de la page, et c'est un chantier de l'Atelier.
- Après toute modification de `index.html` : `outils/publier.sh`, puis
  `python3 outils/verifier_artefact.py`.
