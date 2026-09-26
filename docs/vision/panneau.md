# Le panneau : voir et manipuler à côté de la conversation

Équipe « Panneau de visualisation », réflexion sur la vision de l'Atelier,
25/09/2026. Suit le format de `docs/vision/cadre.md`. **Proposition, à
valider.** Aucun code n'a été modifié pour l'écrire.

## État (vague 3, équipe N, 26/09/2026, branche `v3-navigateur`) : P5, le navigateur de l'agent en direct

Détail, mesures et limites : `docs/navigateur-atelier.md` § 8.

### Fait

| Quoi | Ce qui existe | Où |
|---|---|---|
| **Chrome visible par l'Atelier (U1)** | Le Chrome de chaque conversation reste lancé par `chrome-devtools-mcp` par son tube (démarrage au premier outil, mort avec le tube) ; le rôle « navigateur » du lanceur lui ajoute un port de débogage **sur 127.0.0.1**, port 0, lu dans `DevToolsActivePort`. Mesuré : Chrome et chrome-headless-shell acceptent tube et port ensemble (Windows et Linux). Profil **par conversation** (`conversation.<id>`, verrou `flock`), gardé tant qu'elle vit : les connexions aux sites survivent au processus | `bin/atelier-chrome` |
| **Association conversation -> écran** | Le filtre publie `ecrans/<conversation>.json` (0600) : port, page sélectionnée par l'agent (ligne `[selected]` des réponses du serveur), actions en attente ; retirée à la sortie | `bin/atelier-chrome-onglets.mjs` |
| **Écran en direct** | Rattachement CDP en boucle locale, suivi de la page sélectionnée (`Target.*`), screencast JPEG (8 images/s au plus, par l'acquittement), **rien tant que personne ne regarde** | `ecran.py` |
| **Portée `conversation`** | `conversation:<id>`, racine `/_ecran/<id>/`, sur le modèle de la portée « connecteur » : une session ouverte pour l'écran de la conversation X n'ouvre ni Y, ni un projet, ni un connecteur ; jamais par un code d'agent | `apps/passage.py`, `apps/serveur.py`, `apps/routes.py` |
| **Page de l'écran** | Sur l'hôte des applications : image, adresse courante, « Prendre la main » / « Rendre la main », bandeau « l'agent est en pause (n actions en attente) » ; ne reçoit que des images et un état, n'envoie que des gestes (jamais le protocole DevTools, jamais le port) | `apps/page_ecran/` |
| **Prendre la main** | Clics, molette, clavier, collage, adresse (`http`/`https`) par `Input.dispatch*` / `Page.navigate`, seulement main prise. L'agent est **mis en pause par blocage** : ses actions sur le navigateur attendent dans le filtre (une interruption tuerait son CLI, donc Chrome et la page). « Rendre la main » les libère, la première avec une note qui dit ce qui a changé ; sans action ni tour en cours, un message relance l'agent. Main abandonnée : rendue après 5 min sans spectateur | `ecran.py`, filtre |
| **Panneau (J-f2)** | Un outil `new_page`, `navigate_page` ou `select_page` dans le flux ajoute l'onglet « Navigateur de l'agent » : panneau fermé, il s'ouvre dessus ; autre onglet regardé, un signal ; replié par la personne, le signal passe sur le bouton du panneau. Flux vivant (cadre retiré masqué), jamais épinglé ; retrouvé au chargement d'une conversation dont le navigateur est ouvert | `web/js/views/panneau.js` |
| **Routes de l'Atelier** | `GET /v1/ecran/<id>` (état, sans port), `GET /v1/ecran/<id>/ouvrir` (code de portée `conversation:<id>`), `POST /v1/ecran/<id>/main` | `navigateur_routes.py` ; `app.state.diffusion` (une ligne dans `api.py`) |
| **J-f3** | Lectures du navigateur autorisées d'office (`permissions.allow`) dans les réglages de chaque tour, de VS Code, du terminal et de wikichat | `navigateur.py` (`OUTILS_EN_LECTURE`, `regles_de_lecture_du_navigateur`) |
| **Consignes** | `atelier_navigateur_ouvrir`, jamais `file://` ; lectures libres ; main de la personne et note de reprise | `docs/consignes/socle.md`, `docs/consignes/chrome-devtools-atelier.md` |

### Vérifié

- `tests/test_ecran.py`, `tests/test_filtre_ecran.py`, `tests/test_lanceur_chrome.py` (sous Linux, dans un conteneur de l'image de l'Atelier), suites JS `panneau` et `ecran` : portée qui refuse une autre conversation ; ni jeton ni port côté navigateur ; suivi de la page sélectionnée ; pause et reprise de l'agent ; plafond d'onglets tenu ; rien ne tourne sans spectateur.
- `tests/test_ecran_chrome_reel.py` contre un **vrai Chrome** et le vrai `chrome-devtools-mcp` 1.10.1 : sous Windows (Chrome 153), et sous Linux **par le vrai lanceur** (chrome-headless-shell 154) : images JPEG, suivi de `new_page` et `select_page`, clic de la personne qui agit dans la page, action de l'agent retenue puis rendue avec la note, port en boucle locale seulement, tout rangé à la fin (profil gardé).

### Non vérifié (ne se voit que sur le pod)

- Une vraie conversation `claude` du pod : noms d'outils dans le flux, panneau qui s'ouvre, image dans l'iframe sur `https` à travers l'Ingress, relance réelle après « Rendre la main ».
- `CLAUDE_CODE_SESSION_ID` transmis aux serveurs MCP par VS Code et le terminal (sans lui : pas d'écran sur ces surfaces, profil jetable comme avant).
- L'effet des règles J-f3 dans le CLI 2.1.281.

### Reste

- Deux flux vivants au plus, vignettes (P4/P5).
- Boîtes de dialogue et choix de fichier : hors du screencast.
- Liseré « l'agent agit » sur l'onglet pendant un outil du navigateur.

## État (vague 2, équipe B, 26/09/2026, branche `v2-bureaux`) : P4, les bureaux

### Fait

| Quoi | Ce qui existe | Où |
|---|---|---|
| **Services du namespace relayés (J-d)** | L'hôte des applications relaie `/_services/<connecteur>/<vue>/…` (HTTP en flux et WebSocket, par `relais_ws`) vers l'adresse **interne** que déclare le connecteur. Un amont en boucle locale (`127.0.0.1`, `localhost`, `::1`, `169.254.*`, `0.0.0.0`) est refusé : l'hôte n'est pas une porte vers ce pod. | `apps/bureaux.py`, `apps/serveur.py` |
| **Déclaration (M3)** | Clé `atelier.vues` de l'entrée du pool : `{nom, genre: bureau\|application, amont, vnc, accueil, titre, chemin: retire\|garde, jeton: {depuis, pose}}`. La clé `atelier` entière est retirée à la matérialisation (`IntegratedMcpStore.enabled_mcp_servers`) : elle n'apparaît dans aucun `.mcp.json` ni `claude-mcp.json`. Une déclaration fautive est écartée seule, et dite (`refusees` de `GET /v1/bureaux`). | `apps/bureaux.py`, `gateway_mcp.py` |
| **Jeton côté serveur** | `depuis` : `entete:<Nom>` (l'en-tête de l'entrée du connecteur, sans `Bearer`, référence `${…}` développée) ou `secret:<réf>` (`~/work/.secrets/apps/`). `pose` : `cookie:<nom>`, `entete:<Nom>` ou `requete:<nom>`, après avoir retiré ce que le navigateur aurait mis au même endroit. Au retour : tout en-tête qui porte le jeton disparaît (`Set-Cookie`, `Location`…), le corps est caviardé en flux (brut ou encodé, même coupé entre deux morceaux) ; l'amont est appelé en `Accept-Encoding: identity`, et une réponse compressée quand même n'est pas relayée (502). L'adresse d'ouverture et le catalogue ne portent ni jeton ni amont. | `apps/bureaux.py`, `apps/serveur.py` |
| **Cadrage** | La politique de P0 (`apps/cadrage.py`), sans rien de neuf : `frame-ancestors <Atelier>` seul, `X-Frame-Options` retiré, sur un amont sans aucun en-tête comme sur un amont contraire. | `apps/proxy.py`, `apps/cadrage.py` |
| **Portée « connecteur »** | Une portée est un projet (`demo`) ou un connecteur (`connecteur:qgis`, racine `/_services/qgis/`). Un code ouvert pour le bureau QGIS n'ouvre ni un projet, ni un autre connecteur (et réciproquement) ; `/v1/apps/entree` n'émet de code de connecteur que pour une vue déclarée ; un code d'agent reste borné à un projet. Comme pour les projets, une session owner s'élargit d'une portée à l'autre (un seul cookie par hôte), une session d'agent jamais. | `apps/passage.py`, `apps/routes.py` |
| **Routes de l'Atelier** | `GET /v1/bureaux` (catalogue : connecteur, nom, genre, titre, adresse d'ouverture) ; `GET /v1/bureaux/{connecteur}/{vue}/ouvrir` (session du navigateur exigée, 302 vers l'entrée de l'hôte avec un code de portée `connecteur:<nom>`). Aucune ligne dans `api.py` : posées par `enregistrer_routes_apps`. | `apps/routes.py` |
| **Panneau** | Le « + » du panneau a deux rayons, « Créations » et « Bureaux ». « Montrer » sur un bureau ouvre son onglet (cadre par `/v1/bureaux/…/ouvrir`, même bac à sable). Un service ne s'ouvre **jamais** sur un événement : un `panneau_montrer` qui en décrit un est ignoré (J-f). Il n'est ni épinglé ni enregistré (il ne revient pas seul) ; son cadre n'existe que tant que son onglet est affiché : onglet masqué ou panneau replié, le cadre part et le flux s'arrête. | `web/js/views/panneau.js` |

Tests : `tests/test_bureaux.py` (hôte réel et service factice du namespace dans leurs fils : jeton dans le corps, coupé, dans `Set-Cookie`, `Location`, réponse compressée ; cadrage d'un amont nu et d'un amont contraire ; portée qui refuse un autre connecteur et un projet ; WebSocket relayé dont l'amont exige le jeton ; catalogue et ouverture côté Atelier ; clé `atelier` absente de la matérialisation) et le bloc « bureaux » de `tests/js/panneau.suite.mjs`.

### Les services du namespace, découverts sur le pod (lecture seule, 26/09)

Namespace `user-nic01asfr`. L'hôte des applications tourne dans le pod `proj-claude-code-jupyter-python-0` du même namespace : les noms courts des Services s'y résolvent.

| Service | Service Kubernetes et ports | Ce qui répond | Authentification |
|---|---|---|---|
| Blender (`blender-remote-mcp-0`, StatefulSet, `ghcr.io/nic01asfr/blender-remote-mcp:latest`) | `blender-remote-mcp` (ClusterIP) : **8100**, **6080** | 8100 : API (`/mcp`, `/desktop` = `/canvas`, `/stream/{user_id}`, `/api/session/info`, `/health`). 6080 : websockify avec le noVNC d'origine (`/vnc.html`, WebSocket `/websockify`, sous-protocole `binary`). Ingress `user-nic01asfr-blender-mcp` (8100) | 8100 : `/desktop` accepte le cookie `blender_token` égal au jeton porteur de l'entrée `blender` du pool (200 ; l'en-tête `Authorization` y est refusé : 401). 6080 : **aucune** (RFB 3.8, type de sécurité 1 « None ») |
| Bureau QGIS (`qgis-workspace-nic01asfr`) | `qgis-workspace-nic01asfr` (ClusterIP) : 8100, **8080**, **6080** | 8080 : API du bureau (`/api/layers`, `/api/screenshot`…) ; `/vnc` renvoie vers `http://localhost:6080/vnc.html` (inutilisable relayé). 6080 : websockify et noVNC, `/websockify` | 8080 et 6080 : **aucune** dans le cluster (`/api/layers` 200 sans jeton ; RFB type 1) |
| Portail QGIS (`qgis-hub`) | `qgis-hub` (sans IP, headless) : **8888** | `/desk` (bureau noVNC encadré + discussion), `/workspace/vnc/…` et `/workspace/vnc/websockify` (relais vers le bureau). Ingress `user-nic01asfr-qgis` (http) | cookie `hub_api_key` égal à la clé `qgis_…` de l'entrée `qgis` du pool (`/desk` et `/workspace/vnc/vnc.html` : 200) ; sans : 401 JSON avec `portal_url`. La page `/desk` emploie des chemins **absolus** (`/static`, `/workspace`) |
| n8n (Deployment `n8n`, `n8nio/n8n:2.38.6` ; conteneurs `n8n`, `mcp`, `portal`, `runners`) | `n8n` (ClusterIP) : **5678**, 3000, 3100 | 5678 : éditeur (`/healthz` 200). 3000 : serveur MCP (`n8n-mcp`). 3100 : portail d'actions. Ingress `user-nic01asfr-n8n`, `-n8n-mcp`, `-n8n-portail` | éditeur : la connexion utilisateur de n8n (`/rest/login` 401), pas de jeton de service. En interne, l'éditeur envoie `X-Frame-Options: SAMEORIGIN` (la mesure A6, faite par l'Ingress public, n'en voyait aucun) ; le relais le retire. Chemins **absolus** (`/assets`, `/rest`, `/static`) : `N8N_PATH` n'est pas réglé |

Constats de sécurité, à confier aux gardiens (rien n'a été changé) :

- les websockify de Blender et du bureau QGIS (`:6080`) et l'API du bureau QGIS (`:8080`) ne demandent **aucune** authentification : tout pod qui les joint prend la main sur le bureau. Le relais de l'Atelier devient la seule porte gardée ; une `NetworkPolicy` qui réserve ces ports à l'Atelier et au portail QGIS fermerait le reste ;
- l'entrée `n8n` du pool porte son jeton **en clair dans `args`** (`--header Authorization: Bearer …`), là où les autres entrées l'ont dans `headers`. Il a transité par la sortie d'une commande de découverte de cette équipe (sortie non recopiée ici) : c'est une raison de plus de le faire tourner (question déjà « en attente » dans `decisions.md`).

### Déclarations à poser sur le pod (après déploiement de cette branche)

| Connecteur | `atelier.vues` | Statut |
|---|---|---|
| `blender` | `[{"nom": "bureau", "genre": "bureau", "amont": "http://blender-remote-mcp:6080", "vnc": "/websockify", "titre": "Bureau Blender"}]` | à poser : noVNC d'origine, chemins relatifs, aucun jeton |
| `qgis` | `[{"nom": "bureau", "genre": "bureau", "amont": "http://qgis-workspace-nic01asfr:6080", "vnc": "/websockify", "titre": "Bureau QGIS"}]` | à poser : même forme que Blender |
| `n8n` | `[{"nom": "editeur", "genre": "application", "amont": "http://n8n:5678", "chemin": "garde", "titre": "Éditeur n8n"}]` | **seulement si** n8n est réglé avec `N8N_PATH=/_services/n8n/editeur/`, ce qui déplace aussi son adresse publique : décision de Nicolas. Sans cela, ses chemins absolus tombent hors du préfixe |
| `qgis` (`/desk`) | `{"nom": "portail", "genre": "application", "amont": "http://qgis-hub:8888", "accueil": "/desk", "jeton": {"depuis": "entete:Authorization", "pose": "cookie:hub_api_key"}}` | **pas en l'état** : `/desk` charge `/static/…` et `/workspace/…` en absolu. Il faudrait que le portail sache vivre sous un préfixe |
| `blender` (`/canvas`) | `{"nom": "canvas", "genre": "application", "amont": "http://blender-remote-mcp:8100", "accueil": "/canvas", "jeton": {"depuis": "entete:Authorization", "pose": "cookie:blender_token"}}` | **à essayer** : le cookie est vérifié (200), mais la page n'a pas été lue (lecture refusée pendant la découverte) ; si elle emploie des chemins absolus ou son jeton côté navigateur, elle ne marchera pas relayée (le relais caviarde le jeton) |

Procédure : dans le pod de l'Atelier, avec le Python de l'Atelier, poser la clé sans toucher au reste de l'entrée (ni `_metadata`, ni les en-têtes : un aller-retour par `PUT /v1/mcp/servers/{nom}` réécrirait les en-têtes masqués) et sans rien afficher :

```python
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.db import connect
from mcp_gateway.registry import get_registry_server

VUES = {
    "blender": [{"nom": "bureau", "genre": "bureau", "amont": "http://blender-remote-mcp:6080",
                 "vnc": "/websockify", "titre": "Bureau Blender"}],
    "qgis": [{"nom": "bureau", "genre": "bureau", "amont": "http://qgis-workspace-nic01asfr:6080",
              "vnc": "/websockify", "titre": "Bureau QGIS"}],
}
conn = connect(AtelierSettings().gateway_db_path)
store = IntegratedMcpStore(conn)
actifs = {n: e.get("enabled", True) for n, e in store.list_servers().items()}
for nom, vues in VUES.items():
    config = dict(get_registry_server(conn, nom).config)  # _metadata compris
    config["atelier"] = {**(config.get("atelier") or {}), "vues": vues}
    store.upsert(nom, {**config, "enabled": actifs[nom]})
conn.close()
print("déclarées :", ", ".join(VUES))
```

Puis `GET /v1/bureaux` (liste et `refusees`), et ouvrir chaque bureau depuis le panneau. Aucun redémarrage : l'hôte relit le pool toutes les 5 s.

### Vérifié

- Tout ce qui est dit dans « Fait », par les tests (Python et suite JS), contre un vrai serveur de l'hôte et un vrai service factice.
- Sur le pod, au niveau du protocole : les adresses et ports ci-dessus ; la poignée de main RFB des deux websockify (`binary`, RFB 3.8, sans mot de passe) ; `blender_token` et `hub_api_key` acceptés ; les en-têtes de l'éditeur n8n.

### Non vérifié (ne se voit que sur le pod, après déploiement)

- Le **rendu réel** d'un bureau dans le panneau (noVNC de Blender ou de QGIS dans l'iframe, souris et clavier, fluidité), et le cookie `__Host-atelier_apps` dans l'iframe sur `https` (A7 n'a été fait qu'en local).
- Le passage de l'Ingress de l'hôte des applications pour les WebSocket longs de noVNC (délais de l'Ingress Onyxia).
- L'éditeur n8n relayé (`N8N_PATH`, contrôle d'`Origin` de sa connexion `push`), `/canvas` de Blender, `/desk` du portail QGIS.

### Reste

- Le contenu des trames WebSocket n'est pas caviardé (flux VNC binaire) : un service qui renverrait son jeton par son WebSocket le livrerait.
- Deux flux vivants au plus, vignettes, liseré « l'agent agit », « Prendre la main », capture par outil (suite de P4) ; épingler un éditeur (non vivant) au projet.
- Proposer à l'équipe K que `atelier_connecteur_ajouter` refuse `atelier.vues` venu d'un agent (un agent ne doit pas se déclarer un amont), ou le passe par « À valider ».
- `NetworkPolicy` des ports 6080 et 8080 (constat ci-dessus).

## État (vague 1, équipe P, 25/09/2026, branche `panneau`)

Ce document reste la proposition d'origine ; cette section dit ce qui en est
construit. Le mot « vue » ci-dessous est un mot interne : à l'écran, on dit
« panneau », « onglet », « création », « Montrer » (`decisions.md` S2).

### Fait

| Étape | Ce qui existe | Où |
|---|---|---|
| **P0 — encadrable** | Une seule politique de cadrage pour toute réponse de l'hôte des applications : `frame-ancestors <origine de l'Atelier>`, ni `'self'` ni ce que l'amont déclare ; `X-Frame-Options` retiré ; `'none'` sans origine connue. Posée par un intergiciel à la sortie de l'hôte (fichiers des créations, mandataire, pages d'erreur), et par le mandataire lui-même. Un amont qui n'envoie aucun en-tête (l'éditeur n8n, mesure A6) sort restreint. | `apps/cadrage.py`, `apps/serveur.py`, `apps/proxy.py` |
| **A7 vérifié** | Voir ci-dessous. | — |
| **P1 — le panneau** | Colonne à droite du fil, **hors du fil** : un cadre par onglet, gardé d'un rendu à l'autre (mesuré dans Chrome : un tour complet affiché, zéro rechargement du cadre). Boutons : Épingler au projet / Épinglée au projet, Recharger, Détacher (onglet du navigateur), Fermer ; « + » ouvre le catalogue des créations du projet, dont « Montrer » remplace l'ancien lien « Ouvrir » vers un nouvel onglet. Au téléphone (≤ 720 px) : feuille plein écran, « Replier » ramène au fil. Entre 721 et 1280 px, la liste des conversations cède sa place quand le panneau est ouvert. | `web/js/views/panneau.js`, `web/index.html`, `web/css/app.css` |
| **Épingler (J-e)** | À la conversation : `<work>/panneau/<conversation>.json`, **à côté** de la fiche et non dedans (un tour en cours réécrit sa fiche en finissant : une vue montrée pendant le tour y serait perdue). Au projet : `.atelier/projet.json`, clé `vues_epinglees` (`[{nom, chemin, titre}]`), le reste du fichier intact. | `panneau.py` |
| **P2 — `atelier_montrer`** | Outil de la porte `atelier` : la conversation vient de `X-Atelier-Conversation` (refus sans lui), le projet est celui de la conversation (refus d'un autre), la création doit exister. Épingle à la conversation et publie `systeme/panneau_montrer` sur le flux en direct : le panneau s'ouvre seul sur l'onglet (J-f), même pendant le tour. Classe `reversible`, déclarée par l'équipe F (`commandes/existants.py`). | `outils_conversation.py`, `panneau.py`, `controllers/chat.js` |
| **Passage d'agent (J-h)** | `atelier_navigateur_ouvrir(projet, chemin)` émet un code d'agent : acteur `agent:<conversation>`, projet de la conversation seul, deux minutes, usage unique. Consommé à `/_atelier/entree`, il ouvre une session d'applications d'une heure, sans session owner, qui ne s'élargit jamais (ni par un code owner ni par un autre code d'agent). L'Atelier ne reconnaît pas ce cookie. L'application relayée reçoit `X-Atelier-Acces: agent`. Aucune destination de passage (owner ou agent) ne porte de segment `.` ou `..`. | `apps/passage.py`, `outils_conversation.py` |
| **Routes** | `GET /v1/panneau/{id}`, `PUT /v1/panneau/{id}/vues`, `DELETE /v1/panneau/{id}/vues/{vue}`, `GET /v1/apps/{projet}/{nom}/ouvrir?chemin=`, `GET /v1/sessions/{id}/fils`. Une ligne d'enregistrement dans `api.py`. | `panneau.py`, `apps/routes.py` |
| **wikichat dans l'interface** | Le `systemMessage` d'un hook (relance `Stop`) devient l'événement `systeme/message_systeme`, affiché dans le fil à sa place, en direct et au rechargement. Les fils d'une conversation (`127.0.0.1:3777/api/fils?session=`, identifiant Claude puis Atelier) s'affichent sous la barre : bouton « Échanges » (seulement s'il y en a), qui attend qui, retard, trois derniers messages. wikichat injoignable : liste vide, dite telle. | `events.py`, `panneau.py`, `web/js/views/fils.js` |
| **Lot H** | Réponse en double (la traîne d'un tour lancé d'ici, arrivée en retard par le flux en direct, ouvrait une seconde bulle) ; titres tirés d'un premier message HTML ou en code (et réparation des fiches déjà mal titrées) ; double fiche pour un même fil (adoption concurrente, reproduite en test sans verrou) ; « + » d'un projet agrandi et nommé, gestes des messages visibles au doigt ; mode choisi avant le premier message ; demandes d'un tour disparu repliées en une ligne, « Classer » les retire ; demi-emoji (substitut isolé) dans le flux SSE et l'absorption du transcript du CLI. | `web/js/…`, `sessions.py`, `events.py` |
| **Cartes d'action** | Le champ `carte` que rendent les commandes (format de F, transverse §1.8) se lit dans le détail d'un outil (titre, résumé, preuve, « Voir » limité à une adresse de l'Atelier ou en https). | `ui/message-render.js` |

### Vérification A7 (passage par code et cookie `__Host-atelier_apps` dans une iframe)

Essai dans Chrome le 25/09, Atelier lancé en local en mode factice sur deux
origines du même site, `http://atelier.app.localhost:8787` et
`http://apps.app.localhost:8788` (même site `app.localhost`, comme
`*.user.lab.sspcloud.fr` sur le pod), iframe avec l'attribut `sandbox` du
panneau (dont `allow-same-origin`) :

- **iframe vers `/v1/apps/demo/site/ouvrir`** : 302 → `/_atelier/entree?code=…`
  → 302 → `/demo/site/` (le cookie d'applications posé dans l'iframe est
  renvoyé : pas de retour vers l'Atelier) → 302 → page sous jeton, 200, feuille
  de style chargée, script exécuté, `top` inaccessible. **Fonctionne.**
- **iframe directement sur l'hôte des applications, sans cookie** : 302 →
  `/v1/apps/entree?suite=…` sur l'Atelier (le cookie Lax de l'Atelier part dans
  l'iframe) → code → 302 → page. **Fonctionne.**
- **encadrement par une autre origine du même site** (`voisin.app.localhost`) :
  bloqué par `frame-ancestors` (« violates … frame-ancestors
  http://atelier.app.localhost:8787 »).

Limites : en `http` sur `*.localhost` (où Chrome accepte `Secure`) et non en
`https` sur le pod ; un artefact **serveur** n'a pas été essayé en cadre (le
superviseur ne lance pas de processus sous Windows), seulement des fichiers.
Le comportement attendu sur le pod est le même (même site, cookies Lax), à
confirmer au déploiement.

### Vérifié dans Chrome (local, mode factice)

Catalogue et « Montrer » depuis le panneau ; onglet gardé pendant un tour
(zéro rechargement) ; épingler au projet (écrit `.atelier/projet.json`, visible
dans une nouvelle conversation du projet) ; feuille plein écran à 390 px sans
défilement horizontal ; mode « Plan » choisi avant le premier message et posé
sur la conversation dès sa création ; composeur tenant dans la colonne
rétrécie. Une fois, un premier envoi est parti deux fois (deux
`/events?message=…` à 1,3 s d'écart), non reproduit ensuite : voir « Reste ».

### Non vérifié

- `atelier_montrer` appelé par un vrai agent (la porte `/mcp` n'existe pas en
  mode factice) : la chaîne outil → flux en direct → panneau est couverte par
  les tests (Python et suite JS), pas vue de bout en bout.
- Le format réel du `systemMessage` dans le flux stream-json du CLI du pod
  (2.1.281) : le CLI local (2.1.86) ne l'émet pas en `-p`. L'analyse accepte
  `systemMessage`, `informational`, `hook_response` et voisins ; à mesurer
  (équipe M).
- Les échanges wikichat contre un vrai wikichat (testé contre le contrat, en
  double).
- Le tactile réel (émulé seulement).

### Reste

- **Vague 2** : P3 (hôte MCP Apps : pont `postMessage`, contexte de vue,
  « Montrer » depuis une vue, interfaces `ui://`) ; P4 (fait en vague 2 par
  l'équipe B, voir plus haut) ; page Gardiens et onglet Automates (sur l'API de G) ;
  « Annuler » des cartes d'action.
- **Envoi rejoué** : l'adresse du flux porte le message ; une reconnexion
  d'`EventSource` relancerait le tour. Proposition au coordinateur (fichier
  partagé `api.py`) : un identifiant d'envoi dans l'adresse, refusé la seconde
  fois.
- **Journal** (équipe F) : `journal.fondre` relit le transcript du CLI ; un
  demi-emoji y ferait encore échouer la réponse de
  `/v1/sessions/{id}/transcript`. Appliquer `events.sans_substituts` à la
  lecture.
- Fiches déjà doublées sur le pod : à ranger à la main (le verrou empêche les
  nouvelles).
- Assistant qui ouvre le navigateur sur les projets qu'il a le droit de voir
  (J-h, second cas) ; profil de navigateur des gardiens ; l'acteur au journal
  unique de F (aujourd'hui : journal du service).
- `/chrome/view` et `/chrome/novnc` toujours servis dans l'origine de
  l'Atelier (P4/P5).
- Iframes imbriquées dans une création : `frame-ancestors` exclut l'hôte des
  applications lui-même, une création ne peut donc pas en encadrer une autre.
  Voulu ; à revoir si un besoin apparaît.
- Poignée de largeur du panneau, deux flux vivants au plus, vignettes (P4/P5).

---

## En une phrase

À droite de chaque conversation, un **panneau** à onglets montre des **vues** :
une page ou une application du projet, le navigateur de l'agent, le bureau de
Blender ou de QGIS, l'éditeur n8n, l'interface d'un serveur MCP. Toutes
respectent **un seul contrat**, celui des *MCP Apps* (iframe isolée + pont
`postMessage` en JSON-RPC), que l'Atelier implémente comme hôte. La personne
agit dans la vue, l'agent agit par ses outils, et chacun voit ce que fait
l'autre parce qu'**ils agissent sur le même objet** (le service), pas parce que
le panneau recopie des clics.

---

## 1. Le problème, vu par la personne

**Scénario A — « Montre-moi ».** Nicolas demande à l'agent du projet Lecteur
Grist une nouvelle page de tableau. L'agent crée l'artefact, le démarre, et
écrit « c'est prêt, ouvre Applications → Ouvrir ». Nicolas ouvre un nouvel
onglet, perd la conversation de vue, revient pour dire « la colonne est trop
large », retourne voir, etc. Il voudrait que la page **apparaisse à côté du
fil, se recharge quand l'agent la modifie**, et pouvoir **cliquer sur la
colonne** pour dire « celle-là ».

**Scénario B — « Regarde ce que fait l'agent ».** L'agent pilote Chrome pour
remplir un formulaire de l'IGN. Aujourd'hui le lien « Bureau » ouvre un noVNC
dans un autre onglet, quand il marche (le service `chrome-devtools-mcp` du
namespace est à 0 réplique ; il passe en stdio local dans le pod). Nicolas
voudrait **voir le navigateur en direct dans le panneau**, **prendre la main**
pour passer un captcha ou une connexion, puis la rendre.

**Scénario C — « On travaille à deux sur la même scène ».** Dans un projet
Blender (ou QGIS), l'agent place des objets par ses outils MCP ; Nicolas
tourne la caméra, sélectionne un objet dans le bureau et écrit « agrandis
celui-ci ». L'agent doit savoir **ce qui est sélectionné** sans que Nicolas le
décrive, et Nicolas doit **voir l'effet** des outils de l'agent sans recharger.
Même chose pour un workflow n8n : l'agent crée les nœuds, Nicolas les voit
apparaître dans l'éditeur et corrige un paramètre à la main.

Ce qui manque en commun : un endroit **stable, rattaché à la conversation**,
où ce que l'agent produit ou pilote se voit et se manipule, et un **canal
explicite** pour ce que la personne y montre à l'agent.

---

## 2. Ce qui existe déjà

### 2.1 Dans l'Atelier (lu dans `atelier-src`, 25/09)

| Brique | Où | Ce qu'elle apporte au panneau | Limite constatée |
|---|---|---|---|
| Hôte des applications, origine séparée | `apps/serveur.py`, `apps/passage.py` | l'origine où toute vue doit vivre ; passage par code d'usage unique, cookie `__Host-atelier_apps` | « Ouvrir » est un lien `target=_blank` ; rien n'est pensé pour un cadre |
| Artefacts page / serveur | `artefacts_servis.py`, `apps/manifeste.py` | une vue par artefact, adresse stable | pages servies avec `frame-ancestors 'self'` (`artifacts.py`, `CSP_SANDBOX`/`CSP_CORPUS`) : **sur l'hôte des applications, l'Atelier ne peut pas les encadrer** ; à élargir à l'origine de l'Atelier comme le fait déjà le mandataire |
| Mandataire HTTP/WS/SSE | `apps/proxy.py` | pose `frame-ancestors 'self' <Atelier>` sur les artefacts serveur | `X-Frame-Options` de l'amont passe tel quel (n8n rend `SAMEORIGIN`) |
| Relais WS commun | `relais_ws.py` | garde d'`Origin`, relais binaire : c'est ce que demande noVNC | deux relais à fusionner (`apps/proxy.relayer_ws`) |
| Bureau du navigateur | `chrome_proxy.py` | modèle « l'Atelier relaie en posant le jeton du service, que le navigateur ne voit jamais » | **noVNC tiers servi dans l'origine de l'Atelier** (`/chrome/view`, `/chrome/novnc/…`) : contraire au principe 1 d'`atelier-applications.md` ; service actuellement à 0 réplique |
| Panneau « Applications » | `web/js/views/applications.js` | la liste des artefacts, états, gestes | liste déroulante sous la barre, liens vers un nouvel onglet |
| Barre de session | `index.html`, `code-chat.js` | boutons Applications, Bureau, VS Code | trois portes vers trois onglets du navigateur |
| Flux de la conversation | `GET /v1/sessions/{id}/events` (SSE), `events.py` | événements `outil_debut`/`outil_fin` avec nom d'outil : l'Atelier **sait quel outil de quel connecteur tourne** | pas d'événement « vue » |
| Rendu du fil | `code-chat.js`, `rendreLeFil` | — | le fil est **reconstruit à chaque image** : une iframe dans le fil serait détruite et rechargée en continu. Les vues vivantes doivent être **hors du fil** |
| Verbes MCP de l'Atelier | `outils_conversation.py` (`atelier_artefact_*`, `atelier_envoyer`…) | la place naturelle d'`atelier_montrer` | l'en-tête `X-Atelier-Conversation` n'est pas encore posé pour la porte `atelier` |
| Capacités consenties | `docs/atelier-hebergement.md` §4 | liste déclarée, écran de consentement, journal | pensé côté serveur (jeton), pas côté navigateur |
| Assistant, Agents | `index.html`, `views/agent.js` | — | l'Assistant est un panneau d'attente ; les agents planifiés n'ont pas de fil en direct |

### 2.2 Sur le pod SSPCloud (lecture seule, `kubectl` le 25/09)

| Service | Interface web existante | Flux interactif | Pour le panneau |
|---|---|---|---|
| `chrome-devtools-mcp` | `/view` noVNC (port 6080) | VNC | déploiement à 0/0 ; remplacé par le stdio local en cours (branche `chrome-stdio`, pas encore de changement) |
| `blender-remote-mcp` | page d'accueil `:8100/` ; routes `/desktop`, `/canvas`, `/stream/{user_id}` (authentifiées) | noVNC sur `:6080` (websockify, **non exposé** par l'Ingress) ; `/stream` semble un flux d'images | bureau par le relais de l'Atelier, jeton du service posé côté serveur |
| `qgis-hub` / `qgis-agent` | portail de connexion `:8888`, page `/desk` : **bureau noVNC en iframe + chat en panneau droit** | noVNC relayé same-origin (`/workspace/vnc/websockify`) | c'est déjà, à l'envers, le motif proposé ici |
| `qgis-workspace-<user>` | API `:8080` : `/api/screenshot`, `/api/input`, `/api/layers`, `/api/project`, `/vnc` (→ noVNC `:6080`) | noVNC | capture et injection d'entrée **déjà exposées** : le contrat « capture à la demande » est gratuit |
| `n8n` | éditeur `:5678` (`X-Frame-Options: SAMEORIGIN`), portail d'actions `:3100` (CSP `frame-ancestors` Grist), MCP `:3000` | interface web native | encadrable en réglant `N8N_CONTENT_SECURITY_POLICY` (`frame-ancestors` = origine de l'Atelier), qui prime sur `X-Frame-Options` dans les navigateurs récents ; à défaut, retrait au relais. `N8N_SAMESITE_COOKIE=none` inutile : Atelier et n8n sont « même site » |

Conclusion : **deux familles** seulement. Les services à bureau (Chrome,
Blender, QGIS) exposent tous noVNC/websockify ; les services web (n8n,
artefacts, portails) exposent une page. Et **tous ont un serveur MCP** : l'agent
n'a jamais besoin du panneau pour agir, il a besoin du panneau pour **que la
personne voie et montre**.

### 2.3 Standards et produits comparables

Voir « Sources » en fin de document. En résumé :

- **MCP Apps** (extension officielle `io.modelcontextprotocol/ui`, SEP-1865,
  stable depuis le 26/01/2026, co-écrite par Anthropic, OpenAI et MCP-UI ;
  implémentée par Claude, ChatGPT, VS Code, Goose…) : un outil annonce une
  interface par `_meta.ui.resourceUri`, qui pointe une ressource `ui://…` de
  type `text/html;profile=mcp-app` ; l'hôte la
  rend dans une iframe isolée, avec une CSP déclarée par la ressource ; l'iframe
  parle à l'hôte en JSON-RPC sur `postMessage` : recevoir l'entrée et le
  résultat de l'outil, **appeler des outils du même serveur**, envoyer un
  message dans la conversation, **mettre à jour le contexte du modèle**,
  demander un mode d'affichage (`inline`, `fullscreen`, `pip`). Les hôtes web
  utilisent une **double iframe** : un « proxy de bac à sable » sur une origine
  distincte de l'hôte, qui reçoit le HTML et la CSP (`_meta.ui.csp` :
  `connectDomains`, `resourceDomains`, `frameDomains`) puis l'exécute. Un outil
  marqué `visibility: ["app"]` n'est appelable que depuis l'interface. SDK
  `@modelcontextprotocol/ext-apps` (`/app-bridge` côté hôte).
- **MCP-UI** : la bibliothèque communautaire qui a précédé et nourri MCP Apps
  (HTML brut, URL externe, Remote DOM ; actions `tool`, `prompt`, `link`,
  `notify`).
- **OpenAI Apps SDK** : même idée (gabarit HTML déclaré par l'outil,
  `window.openai.callTool`, `widgetState`, modes d'affichage) ; sa
  documentation actuelle recommande les champs et méthodes partagés de MCP
  Apps, `openai/outputTemplate` restant un alias.
- **Artefacts de Claude** : panneau latéral à côté du fil, iframe isolée sur
  `claudeusercontent.com`, publication par lien ; l'artefact peut rappeler le
  modèle (`window.claude.complete`) et garder un stockage (`window.storage`).
- **Bureaux dans le navigateur** : noVNC/websockify (déjà partout sur le pod),
  Selkies (WebSocket ou WebRTC, 60 i/s, base des images Blender de
  linuxserver) pour la fluidité ; Guacamole et Xpra plus lourds ou plus
  spécialisés ; et pour Chrome, le **screencast du protocole DevTools**
  (`Page.startScreencast`, expérimental, images JPEG à acquitter ;
  `Input.dispatchMouseEvent`), qui ne demande ni X ni VNC.
  `chrome-devtools-mcp` sait s'attacher à un Chrome existant
  (`--browserUrl`, `--wsEndpoint`) ; son `--experimentalScreencast` enregistre
  une vidéo, ce n'est pas une vue en direct.

---

## 3. La proposition

### 3.1 Trois mots

| Mot | Ce que c'est pour la personne |
|---|---|
| **Panneau** | la colonne à droite du fil, avec ses onglets |
| **Vue** | un onglet du panneau : une chose qu'on regarde et qu'on manipule |
| **Montrer** | le geste qui envoie à l'agent ce qu'on voit (sélection, capture, clic) |

Tout le reste (hôte, relais, pont, jeton) est l'affaire de l'Atelier.

### 3.2 Le contrat unique : une vue

Une vue est décrite par un **descripteur** normalisé, quelle que soit son
origine. L'agent et l'interface ne manipulent que lui.

```json
{
  "id": "v_7f3a",
  "genre": "page | application | navigateur | bureau | mcp-app",
  "titre": "Carte des parcelles",
  "source": {"artefact": {"projet": "lecteur-grist", "nom": "carte"}},
  "adresse": "https://…-atelier-apps…/lecteur-grist/carte/",
  "pont": "mcp-apps | aucun",
  "interaction": "lecture | directe",
  "capture": "pont | outil | cadre | aucune",
  "rattachement": {"conversation": "72b08c5c", "projet": "lecteur-grist", "epinglee": false},
  "etat": "prete | demarrage | endormie | echec"
}
```

Les sources possibles, et d'où vient leur descripteur :

| Genre | Source | Déclarée par | Adresse servie par | Pont |
|---|---|---|---|---|
| `page` | artefact autonome | le dossier `artifacts/<nom>/` (rien à écrire) | hôte des applications | `mcp-apps` si la page charge le client du pont, sinon `aucun` |
| `application` | artefact serveur **ou** service web du namespace (n8n) | `artefact.json` / entrée de connecteur `vues` | hôte des applications (mandataire) | idem |
| `navigateur` | le Chrome de la conversation | intégré à l'Atelier | hôte des applications, page « écran » de l'Atelier | `mcp-apps` (page de l'Atelier) |
| `bureau` | Blender, QGIS, tout noVNC | entrée de connecteur `vues` | hôte des applications, relais noVNC | `mcp-apps` (page de l'Atelier qui encadre noVNC) |
| `mcp-app` | ressource `ui://` d'un serveur MCP | le serveur lui-même (standard) | hôte des applications, sous `/_ui/<connecteur>/…` | `mcp-apps` |

Deux ajouts de déclaration seulement, au même format :

```json
// artefact.json (facultatif : un artefact est déjà une vue)
"vues": [{"nom": "principale", "chemin": "/", "titre": "Carte"}]

// entrée de connecteur dans le pool (Blender, QGIS, n8n)
"vues": [
  {"nom": "bureau",  "genre": "bureau",      "amont": "http://blender-remote-mcp:6080", "vnc": "/websockify"},
  {"nom": "editeur", "genre": "application", "amont": "http://n8n:5678"}
]
```

L'amont reste une adresse **interne** au namespace ; le navigateur ne voit que
l'hôte des applications, et le jeton du service est posé par l'Atelier (le
modèle de `chrome_proxy.py`, déplacé hors de l'origine de l'Atelier).

### 3.3 Le pont : MCP Apps, partout

Le point clé du modèle : **l'Atelier est un hôte MCP Apps**, et l'hôte des
applications joue exactement le rôle du « proxy de bac à sable » que la
spécification demande aux hôtes web (origine distincte de l'hôte). L'Atelier habille
les vues qui ne parlent pas le protocole (bureau, navigateur) d'une page à
lui qui, elle, le parle. Le panneau n'a donc **qu'un seul protocole** à
connaître, celui du standard :

| Message (sens) | Usage dans l'Atelier | Garde |
|---|---|---|
| initialisation (hôte → vue) | thème, taille, langue, conversation, mode d'affichage | — |
| entrée / résultat d'outil (hôte → vue) | la vue d'un outil reçoit ses données | — |
| appel d'outil (vue → hôte) | la vue agit sur **son** serveur (la page Blender appelle `blender__select`) | outils du même connecteur seulement ; lecture libre, écriture sur geste de la personne ou après accord « pour cette vue » |
| mise à jour du contexte du modèle (vue → hôte) | **« ce que je vois »** : sélection, calque actif, onglet, URL | texte borné (4 Ko), remplacé et non cumulé, lu par l'agent au tour suivant |
| message (vue → hôte) | « Montrer » : un message dans le fil, au nom de la personne | toujours visible dans le fil, marqué « depuis la vue X » |
| lien, mode d'affichage (vue → hôte) | ouvrir un lien, passer en plein écran | liens en nouvel onglet, jamais la page de l'Atelier |
| notification d'activité (hôte → vue) | « l'agent agit » (outil en cours sur ce connecteur) | dérivé des événements `outil_debut`/`outil_fin` |

Les deux ajouts propres à l'Atelier passent par les points d'extension du
standard (notifications nommées sous un préfixe `atelier/`), pour qu'une vue
tierce les ignore sans casser :

- `atelier/agent-actif` : l'agent est en train d'agir sur ce que montre la vue
  (pour afficher un liseré et éviter les gestes croisés) ;
- `atelier/capture` : l'hôte demande à la vue une image de ce qu'elle montre
  (canvas noVNC, `captureVisibleTab` n'existant pas en iframe).

### 3.4 L'état partagé est le service, pas le panneau

La manipulation directe ne passe pas par un « bus de clics ». Elle se règle en
une règle :

> La personne agit **dans la vue** ; l'agent agit **par ses outils** ; les deux
> touchent le **même objet** (la scène Blender, le projet QGIS, le workflow n8n,
> le Chrome de la conversation, les fichiers de l'artefact). La vue montre
> l'objet en direct ; l'agent le relit par ses outils.

Le panneau n'ajoute que trois choses, parce qu'elles ne se déduisent pas de
l'objet :

1. **Ce que la personne regarde** (contexte de vue : sélection, viewport,
   page) — par le pont, sans image, léger ;
2. **Montrer** : une capture ou un extrait, **sur geste explicite** ou sur
   demande de l'agent visible dans le fil ;
3. **Qui a la main** : un liseré « l'agent agit » et un bouton « Prendre la
   main » qui interrompt le tour en cours (verbe `interrupt` existant) et
   laisse un message.

Pour les services qui savent déjà capturer (`qgis-workspace /api/screenshot`,
outils de capture de Blender et de Chrome), la capture passe **par l'outil**
(`capture: "outil"`), pas par le panneau : l'agent voit la même chose que la
personne, même quand le panneau est fermé.

### 3.5 Le navigateur de l'agent, en stdio local

Recommandation à l'équipe qui passe `chrome-devtools-mcp` en stdio :

- **Que l'Atelier possède le Chrome, pas le serveur MCP.** Le superviseur lance
  un Chrome par conversation (sans interface, port de débogage attribué dans
  la plage des applications, 127.0.0.1), et le `chrome-devtools-mcp` stdio de
  la conversation s'y **attache** (`--browserUrl`). Si le serveur MCP lance
  Chrome lui-même par un tube, personne d'autre ne peut s'y joindre, et la vue
  est impossible sans VNC.
- La vue « navigateur » est alors une **page de l'Atelier** sur l'hôte des
  applications : elle reçoit par WebSocket les images du *screencast* DevTools
  (`Page.startScreencast`, JPEG, cadence réglée, arrêtée dès que l'onglet du
  panneau est masqué) et renvoie la souris et le clavier
  (`Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`). Ni Xvfb, ni VNC, ni
  mot de passe.
- Même clé de conversation qu'aujourd'hui (`X-Atelier-Conversation` /
  `ATELIER_SESSION`) : le Chrome de la conversation est celui que montre son
  panneau.
- Plan de repli : si le screencast déçoit (latence, saisie), garder Xvfb +
  noVNC dans le pod, derrière le même contrat `bureau`.

### 3.6 Où et comment : le schéma

```
 Origine de l'Atelier (confiance)                   Hôte des applications (contenu)
 ┌──────────────────────────────────────────────┐
 │ barre : titre · projet · mode · [Vue ▸]      │
 │┌───────────────────────┐┌───────────────────┐│
 ││ fil de la conversation ││ PANNEAU           ││
 ││                        ││ [Carte][Chrome●][+]│   ┌─────────────────────────────┐
 ││ agent : « j'ai ouvert  ││ ┌───────────────┐ │   │ /lecteur-grist/carte/       │
 ││  la carte ▸ »          ││ │  <iframe>     │◀┼───┤ page d'artefact             │
 ││                        ││ │  sandbox      │ │   └─────────────────────────────┘
 ││ vous : « celle-ci »    ││ │               │ │   ┌─────────────────────────────┐
 ││  ⟨vue Carte : parcelle ││ └───────────────┘ │   │ /_atelier/ecran/<conv>      │
 ││   AB-12 sélectionnée⟩  ││ ● l'agent agit    │   │ screencast Chrome (WS)      │
 ││                        ││ [Montrer][Prendre │   ├─────────────────────────────┤
 ││ [composeur………………]    ││  la main][⤢][📌]  │   │ /_atelier/bureau/blender    │
 │└───────────────────────┘└───────────────────┘│   │ noVNC → blender-remote:6080 │
 │          ▲ hôte MCP Apps (pont postMessage)  │   ├─────────────────────────────┤
 └──────────┼───────────────────────────────────┘   │ /_ui/<connecteur>/…  ui://  │
            │                                        └─────────────────────────────┘
            │ appels d'outils, contexte de vue, messages
            ▼
   API de l'Atelier ── passerelle MCP ── serveurs (blender, qgis, n8n, chrome stdio)
            │
            └── contexte de vue → tour suivant de Claude Code (hook ou pièce jointe)
```

### 3.7 Ce que voit la personne

- **Le panneau s'ouvre** : quand l'agent montre quelque chose
  (`atelier_montrer`), quand un outil rend une interface (MCP Apps), ou par le
  bouton **Vue** / **+** (catalogue : artefacts du projet, navigateur, bureaux
  et éditeurs des connecteurs actifs). Il ne s'ouvre jamais seul pour une
  simple lecture d'outil.
- **Onglets** : plusieurs vues, une seule active. Au plus deux **flux vivants**
  (bureau, navigateur) à la fois ; les autres sont suspendus et gardent une
  vignette de leur dernière image (sobriété : pas de flux qui tourne pour rien).
- **Épingler** : une vue épinglée au **projet** apparaît dans toutes les
  conversations du projet et dans la vue projet ; sinon elle appartient à la
  **conversation** et revient quand on la rouvre. **Détacher** (⤢) l'ouvre
  en plein onglet, à la même adresse.
- **Dans le fil** : jamais d'iframe (le fil est reconstruit à chaque image).
  Une **carte** compacte « Vue : Carte des parcelles — Afficher » à l'endroit
  où l'agent l'a montrée, et les messages « Montrer » marqués de leur vue.
- **Liseré** « l'agent agit » sur l'onglet quand un outil du connecteur de la
  vue tourne ; **Prendre la main** interrompt le tour.
- **Mobile** : le panneau devient une feuille plein écran, basculée par le
  bouton Vue (même logique liste/détail que la barre latérale).
- La barre de session perd ses trois portes (Applications, Bureau, VS Code
  deviennent : le catalogue du panneau, un onglet du panneau, et le lien
  VS Code qui reste une porte).

### 3.8 Ce que voit l'agent

- **Un outil** `atelier_montrer(vue)` dans la porte `atelier` : ouvre une vue
  dans le panneau **de sa conversation** (identifiée par
  `X-Atelier-Conversation`). Arguments : `artefact`, `connecteur/vue`,
  `navigateur`, ou une URL de l'hôte des applications. Rend le descripteur.
- **Un outil** `atelier_vue_lire(id, capture=false)` : le contexte de vue
  courant, et une image si demandé (l'appel est visible dans le fil ; la
  capture passe par l'outil du service quand il en a un).
- **Au début d'un tour**, s'il a changé : une ligne de contexte « Panneau :
  Carte des parcelles (sélection : parcelle AB-12) ; Chrome : ign.fr/… ». Par
  le même mécanisme que le reste du contexte (`coherence-projet.md`, lot B :
  hook, identique sur toutes les surfaces).
- **Les interfaces MCP Apps** des serveurs tiers fonctionnent sans rien
  écrire : l'Atelier lit la métadonnée d'interface des outils qu'il connaît
  (catalogue de la passerelle) et, quand l'événement `outil_fin` arrive, ouvre
  la vue avec l'entrée et le résultat. Claude Code lui-même n'a pas besoin de
  connaître MCP Apps : c'est l'hôte qui rend.
- Une consigne courte dans le socle : « Pour montrer ce que tu produis, appelle
  `atelier_montrer` ; ne demande pas d'ouvrir un onglet. »

### 3.9 Sécurité

| Règle | Comment |
|---|---|
| Aucune vue dans l'origine de l'Atelier | toutes sur l'hôte des applications ; `/chrome/view` et `/chrome/novnc` y déménagent |
| L'Atelier seul peut encadrer | `frame-ancestors <origine Atelier>` sur toutes les réponses de l'hôte des applications (à étendre aux pages d'artefacts) ; `X-Frame-Options` amont retiré par le mandataire pour les vues déclarées |
| Attribut `sandbox` sur l'iframe | `allow-scripts allow-forms allow-popups allow-downloads` ; `allow-same-origin` seulement pour les applications et bureaux (origine de l'hôte des applications, pas de l'Atelier) ; jamais `allow-top-navigation` |
| Pont authentifié | l'hôte n'accepte un message que si `event.source` est l'iframe de cette vue ; chaque vue a son identifiant ; JSON-RPC validé ; rien de l'Atelier (clé, jeton) ne traverse le pont |
| Outils depuis une vue | seulement les outils de **son** connecteur (règle MCP Apps), passés par la passerelle avec l'identité de la conversation ; écriture sur geste de la personne ou accord « pour cette vue », enregistré et révocable |
| Contexte vers l'agent | texte borné, remplacé et non cumulé ; images seulement sur geste ou appel visible ; l'agent ne reçoit **jamais** en silence ce qu'affiche un bureau |
| Messages vers le fil | toujours visibles, marqués de la vue d'origine ; une vue ne peut pas envoyer de message sans geste (activation utilisateur) |
| Jetons des services | posés par le relais côté serveur, jamais dans la page (modèle `chrome_proxy`) |
| Même site | `sspcloud.fr` hors Public Suffix List : cookie Lax envoyé dans l'iframe (utile au passage), mais **Origin vérifiée** sur chaque WS (déjà la règle) |
| Mode « Sans garde-fou » | ne s'étend pas aux vues : un appel d'outil d'une vue garde ses gardes |

### 3.10 VS Code, Assistant, agents, compositions

- **Un seul panneau, une seule page.** Le panneau est une route de l'Atelier
  (`/panneau?conversation=…`) qui fonctionne aussi seule. La vue Code
  l'intègre à droite ; **VS Code** (code-server du pod) l'ouvre dans son
  navigateur intégré (commande *Simple Browser*), à côté de la conversation de
  l'extension Claude Code, avec la même conversation — ce qui suppose
  l'identité unique du lot C de `coherence-projet.md`. Seule la route
  `/panneau` autorise l'origine de code-server en `frame-ancestors`. Plus tard,
  une petite extension VS Code peut remplacer *Simple Browser* par un webview
  ancré.
- **Assistant** : sa vue reste à écrire ; elle reprend la même disposition
  fil + panneau. Rien de spécifique.
- **Agents planifiés et routines** : pas de personne en direct. Leurs vues
  s'affichent **en lecture** dans le détail de l'exécution (dernière capture,
  artefact produit) ; « Reprendre dans une conversation » ouvre une
  conversation avec les mêmes vues.
- **Compositions et outils de la passerelle** : une composition peut déclarer
  une interface MCP Apps comme n'importe quel outil ; l'Atelier la rend. Les
  clients distants (claude.ai, autres hôtes MCP Apps) verront la même
  interface, puisque c'est le standard.

### 3.11 Lien avec l'hébergement et les capacités

Le pont d'une vue est l'équivalent **dans le navigateur** du jeton de capacité
de `atelier-hebergement.md` §4. Une application promue qui déclare
`"capacites"` les obtient **par le même écran de consentement**, qu'elle les
demande côté serveur (`ATELIER_APP_JETON`) ou depuis sa vue (appel d'outil par
le pont). Une seule liste, un seul journal.

---

## 4. Parcours types

**A. Une page qui se construit sous les yeux.**
1. « Fais-moi une carte des parcelles. » L'agent crée `artifacts/carte/`,
   écrit, appelle `atelier_montrer(artefact="carte")`.
2. Le panneau s'ouvre sur la carte ; une carte « Vue : Carte » s'insère dans
   le fil.
3. L'agent modifie le fichier ; la vue se recharge (fin d'outil d'écriture
   sur ce dossier).
4. Nicolas clique une parcelle (la page, qui charge le client du pont, met à
   jour le contexte : « parcelle AB-12 ») et écrit « colore celle-ci ».
   L'agent reçoit la ligne de contexte et sait laquelle.

**B. Le navigateur de l'agent.**
1. L'agent appelle un outil de `chrome-devtools-mcp` ; l'onglet
   « Navigateur » apparaît (s'il n'y était pas), en direct, liseré « l'agent
   agit ».
2. Page de connexion : l'agent écrit « à toi ». Nicolas clique **Prendre la
   main**, se connecte dans la vue, écrit « c'est bon ».
3. L'agent reprend ; Nicolas regarde. Onglet masqué : le screencast s'arrête.

**C. La scène Blender partagée.**
1. Nicolas ouvre **+ → Blender → Bureau**. La page de l'Atelier encadre
   noVNC relayé vers `blender-remote-mcp:6080`.
2. L'agent ajoute des objets par ses outils ; Nicolas les voit apparaître.
3. Nicolas sélectionne un objet et clique **Montrer** : capture jointe au
   message (via l'outil de capture de Blender), plus le nom de l'objet
   sélectionné si l'outil de Blender le rend. « Agrandis celui-ci. »

**D. Un workflow n8n.**
1. L'agent crée le workflow par l'outil MCP de n8n, puis
   `atelier_montrer(connecteur="n8n", vue="editeur", chemin="/workflow/42")`.
2. L'éditeur s'ouvre dans le panneau ; Nicolas corrige un paramètre et
   enregistre. L'agent relira le workflow par son outil au tour suivant.

**E. Depuis VS Code.**
Nicolas reprend la conversation dans code-server, ouvre le panneau dans
*Simple Browser* : mêmes onglets, même Chrome, même carte.

---

## 5. Ce qu'il faut construire, par étapes démontrables

| Étape | Contenu | Démonstration |
|---|---|---|
| **P0 — Encadrable** | `frame-ancestors <Atelier>` sur les pages d'artefacts ; retrait de `X-Frame-Options` pour les vues déclarées ; passage par code **dans une iframe** vérifié (cookie Lax même site) ; `/chrome/*` déplacé sur l'hôte des applications | un artefact du Lecteur Grist s'affiche dans une iframe de l'Atelier |
| **P1 — Le panneau** | colonne à droite, onglets, catalogue « + » (remplace Applications et Bureau), épingler/détacher, état par conversation (fiche de session), feuille mobile | parcours A sans pont : voir et recharger une page à côté du fil |
| **P2 — `atelier_montrer`** | outil dans la porte `atelier`, événement `vue` sur le SSE de la conversation, carte dans le fil, rechargement sur écriture | l'agent ouvre lui-même la vue |
| **P3 — Hôte MCP Apps** | pont `postMessage` (SDK officiel côté hôte si possible), appels d'outils par la passerelle, contexte de vue → tour suivant, « Montrer », interfaces `ui://` des serveurs tiers | parcours A complet ; un serveur MCP Apps de démonstration s'affiche sans code Atelier |
| **P4 — Bureaux** | vues `bureau` déclarées dans le pool ; page noVNC de l'Atelier (relais `relais_ws`, jeton côté serveur) ; capture par outil ; liseré « l'agent agit » ; Prendre la main | parcours C (Blender) et QGIS workspace |
| **P5 — Navigateur** | avec l'équipe stdio : Chrome supervisé par l'Atelier, `--browserUrl` ; page écran screencast + entrées | parcours B |
| **P6 — Applications tierces** | n8n éditeur ; qgis-hub `/desk` comme vue `application` | parcours D |
| **P7 — Surfaces** | route `/panneau` autonome, VS Code *Simple Browser*, Assistant, détail d'exécution des agents | parcours E |

P0 à P2 livrent déjà l'essentiel de la valeur (fin des onglets perdus) sans
rien de nouveau côté sécurité ; P3 est le cœur du modèle.

---

## 6. Risques, limites, questions à trancher

**Risques et limites**

- **Même utilisateur Unix** : une vue d'artefact serveur tourne dans le pod
  (`atelier-hebergement.md` §9). Le panneau n'aggrave rien, mais rend ces
  applications plus présentes : le service dédié reste la réponse.
- **Toutes les applications d'un projet partagent l'origine** de l'hôte des
  applications : une vue `allow-same-origin` peut lire le stockage d'une
  autre du même hôte. Acceptable dans l'hypothèse « un propriétaire = un
  domaine de confiance » ; à revoir avec les hôtes par application.
- **n8n dans un cadre** : autoriser l'encadrement ouvre l'éditeur au
  *clickjacking* depuis tout ce qui peut l'encadrer ; seul l'Atelier le peut
  (`frame-ancestors`), mais les applications du même hôte aussi, en théorie.
- **Fluidité** : noVNC et screencast suffisent pour regarder et corriger ; pas
  pour modéliser longtemps dans Blender. WebRTC (Selkies) est l'étape suivante
  si l'usage le demande — même contrat `bureau`, autre transport.
- **Contexte de vue et coût** : chaque tour qui porte un contexte de vue coûte
  quelques dizaines de jetons ; les captures, beaucoup plus. D'où : texte
  borné, images sur geste seulement.
- **MCP Apps côté Claude Code** : l'hôte est l'Atelier, pas le CLI. Un outil
  appelé en VS Code ou au terminal n'ouvre la vue que si l'Atelier voit
  passer l'appel (flux du harnais, ou hook `PostToolUse` sur les autres
  surfaces).
- **Maturité du standard** : la spécification MCP Apps est récente ; suivre sa
  version, isoler l'implémentation du pont dans un module.

**Questions à trancher par Nicolas**

1. **Le Chrome de l'agent appartient-il à l'Atelier** (superviseur,
   `--browserUrl`) plutôt qu'au serveur MCP stdio ? C'est la condition de la
   vue navigateur sans VNC ; à dire à l'équipe stdio **avant** qu'elle fige
   son choix.
2. **Le panneau s'ouvre-t-il automatiquement** quand un outil rend une
   interface, ou seulement sur `atelier_montrer` et geste de la personne ?
   (proposé : automatiquement pour une interface MCP Apps, jamais pour un flux
   vivant.)
3. **Les services du namespace** (Blender, QGIS, n8n) sont-ils relayés par
   l'hôte des applications (une porte, une authentification) ou encadrés à
   leur propre adresse (moins de code, mais leur propre connexion et leurs
   `X-Frame-Options`) ? Proposé : relayés.
4. **Contexte de vue au modèle** : hook identique partout (lot B), ou pièce
   jointe au message (visible, native, mais seulement dans l'Atelier) ?
5. **Épinglage au projet** : fichier du projet (`.atelier/vues.json`, suivi par
   git) ou fiche de l'Atelier (ignorée) ?

---

## 7. Évaluation

**Désirable.** Pour Nicolas d'abord : c'est la boucle « je vois, je montre,
l'agent corrige » qui manque à chaque projet (Lecteur Grist, QGIS, Blender,
n8n), et la fin des trois portes vers trois onglets. Pour une personne non
technicienne : un seul geste (« Montrer ») et un seul endroit (le panneau),
sans savoir ce qu'est noVNC ou MCP.

**Faisable.** Presque tout existe : hôte des applications, passage par code,
mandataire et relais WS, garde d'Origin, SSE avec les événements d'outil,
noVNC déjà servi par Chrome, Blender et QGIS, captures déjà exposées par QGIS.
Le neuf : la colonne du panneau (JS sans cadriciel, comme le reste),
`atelier_montrer`, l'hôte MCP Apps (SDK officiel), la page écran du
screencast. Aucune dépendance lourde.

**Viable.** Un seul protocole à maintenir (le standard), une seule page par
genre de vue (écran, bureau), des déclarations de deux lignes. Coût de
fonctionnement : nul quand le panneau est fermé ; flux arrêtés quand l'onglet
est masqué ; aucune consommation de modèle sans geste ou appel visible.

**Cohérent.**
- *Hébergement* : une vue = un artefact ou un service ; brouillon et
  production donnent deux vues (`~brouillon` et production) ; les capacités
  ont une seule liste et un seul écran de consentement, serveur ou pont.
- *Cohérence projet* : mêmes vues sur toutes les surfaces grâce à l'identité
  unique (lot C) et au contexte par hook (lot B).
- *Applications* : aucune entorse au principe « aucun contenu d'agent dans
  l'origine de l'Atelier » — le panneau le rend même plus strict en déplaçant
  `/chrome/view`.
- *Standards* : MCP Apps comme contrat unique, donc les interfaces que
  produisent les projets de l'Atelier s'afficheront aussi dans claude.ai,
  ChatGPT ou VS Code, et inversement.

---

## Sources

Code et pod (lecture seule, 25/09/2026) : `atelier-src/mcp_gateway/atelier/`
(`web/index.html`, `web/js/views/code-chat.js`, `web/js/views/applications.js`,
`web/js/api.js`, `artifacts.py`, `artefacts_servis.py`, `apps/proxy.py`,
`relais_ws.py`, `chrome_proxy.py`, `navigateur.py`, `events.py`,
`outils_conversation.py`) ; `kubectl get svc,ingress,pods` et sondes HTTP
internes dans le namespace `user-nic01asfr` ; dépôt `qgis-sspcloud`
(`hub/hub/main.py`, `hub/templates/desk.html`).

Standards et produits (consultés le 25/09/2026) :

- MCP Apps, spécification stable 2026-01-26 :
  https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx ;
  dépôt et SDK : https://github.com/modelcontextprotocol/ext-apps ;
  présentation : https://modelcontextprotocol.io/extensions/apps/overview ;
  annonce : https://blog.modelcontextprotocol.io/posts/2026-01-26-mcp-apps/ ;
  hôtes : https://theregister.com/2026/01/26/claude_mcp_apps_arrives ,
  https://goose-docs.ai/blog/2026/01/06/mcp-apps/ ,
  https://alpic.ai/blog/mcp-apps-goes-official-claude-chatgpt-support ;
  écarts entre hôtes : https://www.devmoment.dev/journal/mcp-apps-field-log-2026
- MCP-UI : https://mcpui.dev/guide/introduction ,
  https://mcpui.dev/guide/protocol-details , https://github.com/MCP-UI-Org/mcp-ui
- OpenAI Apps SDK : https://developers.openai.com/apps-sdk/build/state-management ,
  https://github.com/openai/openai-apps-sdk-examples
- Artefacts Claude :
  https://support.claude.com/en/articles/17153992-what-are-artifacts-and-how-do-i-use-them ,
  https://simonwillison.net/2025/Jun/25/ai-powered-apps-with-claude/
- Chrome DevTools Protocol (`Page.startScreencast`, `Input.dispatchMouseEvent`) :
  https://chromedevtools.github.io/devtools-protocol/tot/Page/ ;
  options de `chrome-devtools-mcp` :
  https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/main/docs/configuration.md
- Bureaux : https://github.com/novnc/noVNC , https://github.com/novnc/websockify ,
  https://github.com/selkies-project/selkies ,
  https://github.com/linuxserver/docker-blender , https://github.com/kasmtech/KasmVNC ,
  https://guacamole.apache.org/ , https://github.com/Xpra-org/xpra-html5
- Blender : https://github.com/ahujasid/blender-mcp ,
  https://igamenovoer.github.io/blender-remote/
- QGIS : https://github.com/qgis/qwc2 , https://github.com/qgis/qgis-js ,
  https://github.com/nic01asFr/QgisRemoteMCP , https://github.com/nic01asFr/QgisStreamMCP
- n8n : https://docs.n8n.io/deploy/host-n8n/configure-n8n/basic-configuration/use-environment-variables/security ,
  https://community.n8n.io/t/is-it-possible-to-run-n8n-in-iframe/8980 ;
  `frame-ancestors` face à `X-Frame-Options` :
  https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/frame-ancestors

Incertitudes : la part de MCP Apps réellement respectée varie selon les hôtes
(`pip`, `tool-input-partial`, `permissions`) ; aucune latence officielle pour
le screencast DevTools (50 à 150 ms en local est une estimation) ; aucune
variable n8n dédiée à `X-Frame-Options` (priorité de `frame-ancestors` à
vérifier en réel) ; les routes `/desktop`, `/canvas`, `/stream` de
`blender-remote-mcp` n'ont été vues que par leur réponse 401.
