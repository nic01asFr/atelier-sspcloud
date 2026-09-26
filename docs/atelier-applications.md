# Applications des projets : exposer un service derrière l'Atelier

Conception retenue le 24/09/2026. Elle remplace le bricolage constaté à l'audit
(serveurs lancés à la main sur des ports injoignables, voie accidentelle
`/vscode/proxy/<port>/`, corpus servi hors bac à sable dans l'origine de
l'Atelier).

## Principes

1. Aucun contenu produit par un agent ne s'exécute dans l'origine de l'Atelier.
   Tout passe par une **seconde origine** : `https://<premier-label>-apps.<domaine>`
   (ex. `user-<idep>-atelier-apps.user.lab.sspcloud.fr`), un chemin par
   artefact `/<slug>/<nom>/`. Un seul niveau de sous-domaine : couvert par
   le certificat wildcard de la classe d'Ingress `onyxia`.
2. `sspcloud.fr` n'est pas dans la Public Suffix List : tous les hôtes
   `*.user.lab.sspcloud.fr` sont « même site ». `SameSite=Lax` ne protège donc
   de rien entre pods ; Origin et `Sec-Fetch-Site` sont vérifiés partout.
3. L'Atelier est le seul superviseur des processus. Il attribue les ports ; le
   proxy n'atteint que les ports qu'il a attribués.
4. Les processus lancés reçoivent un environnement construit, jamais celui du
   service (`ATELIER_OWNER_KEY`, `ATELIER_LLM_API_KEY`, `ATELIER_GITHUB_TOKEN`
   n'y passent pas).
5. Hypothèse assumée : les applications d'un même propriétaire forment un seul
   domaine de confiance (comme les agents du pod). Un hôte par application
   viendra si un relais sensible (Grist) l'exige.

## Serveur

- Seconde application ASGI `apps_app`, port 8788, même processus (`app.py` :
  deux `uvicorn.Server` sous `asyncio.gather`). Aucune route `/v1`, `/vscode`,
  `/mcp`, `/chrome`, ni l'interface. `Host` différent de l'hôte des
  applications : 421 (sauf `/_sante`).
- Passage d'authentification :
  1. « Ouvrir » → `GET /v1/apps/{slug}/{nom}/ouvrir` sur l'origine Atelier
     (garde owner).
  2. Code de 32 octets, en mémoire, 60 s, usage unique, lié à la session
     owner, à la portée (le projet `{slug}`) et à la destination.
  3. 302 vers `https://apps…/_atelier/entree?code=…` (`Referrer-Policy:
     no-referrer`, `no-store`).
  4. `apps_app` consomme le code, crée une session d'applications (table
     `app_sessions(id, parent_sid, portee, expire)`), pose
     `__Host-atelier_apps` (HttpOnly, Secure, Lax, Path=/, sans Domain, 12 h),
     302 vers la destination (chemin commençant par `/` et pas `//`).
  5. Sans session : renvoi vers `https://atelier/v1/apps/entree?suite=…`.
  6. Révocation en cascade : fermer la session owner ou faire tourner la clé
     ferme les sessions d'applications liées.
  7. Aucun cookie accepté d'un hôte sur l'autre.
- Sans second hôte (installation de secours) : `ATELIER_APPS_PUBLIC_URL` vide,
  « Ouvrir » grisé ; jamais de repli sous un chemin de l'origine Atelier.

## Chart

- `_helpers.tpl` : `atelier.appsHostname` (valeur `apps.hostname`, sinon
  premier label de `ingress.hostname` + `-apps` + reste du domaine).
- `ingress.yaml` : second Ingress `…-apps` vers le port `apps`, annotations
  `proxy-buffering: "off"`, `proxy-request-buffering: "off"`,
  `proxy-read-timeout`/`proxy-send-timeout: "3600"`, `proxy-body-size` depuis
  `apps.bodySize`, `connect-timeout: "30"`. Pas de bloc `tls`.
- `service.yaml` : port `apps` 8788. `statefulset.yaml` : containerPort
  `apps`, `ATELIER_APPS_PORT`, `ATELIER_APPS_PUBLIC_URL`, `ATELIER_APPS_MAX`,
  `ATELIER_APPS_PORTS=19000-19099`. `networkpolicy.yaml` : port 8788.
- `values.yaml` : `apps: {enabled: true, port: 8788, hostname: "", bodySize:
  "0", max: 4, idleMinutes: 30}` ; schéma : section « Applications ».
- `NOTES.txt` : ligne « Applications des projets : https://<appsHost> ».

## Artefacts : une règle unique

Cadrage du 24/09/2026, qui remplace le manifeste `.atelier/apps/<nom>.json`
(jamais déployé) : **un artefact = un dossier `artifacts/<nom>/` = une
adresse `https://<hôte des applications>/<projet>/<nom>/`**. Le nom suit
`^[a-z0-9][a-z0-9-]{0,39}$`. Sans hôte des applications, un artefact
autonome reste lisible à l'adresse de secours `/v1/artifacts/<projet>/<nom>/`.

- **Autonome** (défaut) : le dossier ne contient que des fichiers. Servi en
  bac à sable : page autonome, ou pages multiples reliées en relatif — chaque
  dossier d'artefact se lit sous un jeton borné à lui (le fichier `.corpus`
  n'est plus nécessaire pour cela). Lecture seule, sauf si l'artefact
  déclare `{"version": 1, "type": "statique", "edition": true}` dans son
  `artefact.json` : ses pages écrivent alors chez elles par `PUT` (les
  dossiers qui portent encore un `.corpus` gardent ce droit).
- **Serveur** : le même dossier porte `artefact.json` de `type: "service"`.
  La même adresse est relayée vers le processus supervisé. Passer d'un mode
  à l'autre ne change pas l'adresse. Les fichiers d'un artefact serveur ne
  sont jamais servis comme des fichiers (son code resterait lisible).
- `artefact.json` et tout nom qui commence par un point ne sont jamais
  servis, ni écrasables par `PUT`.
- **Pas de conflit** : `atelier_artefact_creer(projet, nom, mode)` fait un
  `mkdir` atomique et refuse un nom existant ; il écrit
  `artifacts/<nom>/.auteur` (la conversation créatrice). Démarrer et arrêter
  refusent d'agir sur l'artefact d'une autre conversation, sauf
  `forcer=true`. L'interface agit pour le propriétaire, sans cette règle.

```json
{
  "version": 1,
  "titre": "STT & TTS",
  "type": "service",
  "commande": [".venv/bin/uvicorn", "voice_service:app", "--host", "127.0.0.1", "--port", "{port}"],
  "repertoire": "../..",
  "chemin": "retire",
  "sante": "/health",
  "demarrage_s": 180,
  "inactivite_min": 30,
  "protocoles": ["http", "ws"],
  "corps_max_mo": 50,
  "env": {"MODELE": "whisper-small"},
  "secrets": {"VOICE_TOKEN": "voice"},
  "acces": "proprietaire"
}
```

- `commande` : liste d'arguments, jamais de shell ; substitutions `{port}`,
  `{prefixe}`, `{projet}` (`{socket}` si `ecoute: unix`). Aucun champ port.
- `repertoire` : relatif au dossier de l'artefact (défaut `.`) ; peut
  remonter dans le projet, jamais en sortir (liens résolus).
- `chemin` : `retire` (l'application voit `/`) ou `garde`.
- `protocoles` : WS et SSE relayés seulement s'ils sont déclarés.
- `secrets` : références vers `~/work/.secrets/apps/<ref>` (0600) — jamais
  la racine du dossier, où vivent la clé owner et celle du modèle.
- `acces` : `proprietaire` seul en v1 ; le partage sera un geste du
  propriétaire, jamais un champ de manifeste.

## Variables d'un projet : `.atelier/env.json`

`{"VOICE_TOKEN": "voice_token"}` : un nom de variable pour un nom de fichier
de `~/work/.secrets/` (0600, sans `/` ni `..`). L'Atelier les pose dans
l'environnement des tours du CLI (résolues à chaque lancement ; un secret qui
change relance le processus gardé vivant) et dans les réglages de
l'extension VS Code (réunion de tous les projets). Refusés : `ATELIER_*`,
`ANTHROPIC_*`, `CLAUDE_*`, `WIKICHAT_*`, `LD_*`, `PYTHON*`, `PATH`, `HOME` et
voisines. Le dossier `.atelier/` est ignoré par le `.gitignore` des projets :
ce fichier s'ajoute par `git add -f` (il ne porte que des références).

## Cycle de vie (`apps/superviseur.py`)

- `create_subprocess_exec`, `start_new_session=True`, journaux
  `~/work/logs/apps/<slug>/<nom>.log` (rotation 5 Mo × 2).
- Environnement : `PATH`, `HOME`, `LANG`, venv du projet, `env`, `secrets`,
  `PORT`, `ATELIER_APP_PREFIX`, `ATELIER_APP_URL`, `ATELIER_APP_NOM`.
- Démarrage à la demande, sonde `sante` toutes les 0,5 s pendant
  `demarrage_s` ; page « Démarrage… » pour une navigation, 503 +
  `Retry-After: 2` pour un appel.
- Supervision : sonde toutes les 30 s ; 3 échecs ou mort → redémarrage avec
  attente 1, 2, 4… s ; plus de 5 en 10 min → `en_echec`.
- Arrêt sur inactivité (WS/SSE ouverts comptent comme activité) ; SIGTERM au
  groupe puis SIGKILL à 10 s ; arrêt de tout au `lifespan`.
- État `~/work/.atelier-etat/apps.json` ; au redémarrage de l'Atelier, groupes
  orphelins tués après vérification de `/proc/<pid>/cmdline`.
- Ports dans `ATELIER_APPS_PORTS`, test de bind, 127.0.0.1 ; `ATELIER_APPS_MAX`
  applications simultanées ; `RLIMIT_NOFILE`, `nice 10`, plafond RSS 1,5 Gio.
- `GET /v1/apps/{slug}/{nom}/journal?lignes=N` en `text/plain`.

## Proxy (`apps/proxy.py`)

- HTTP en flux dans les deux sens, `read=None`, plafond `corps_max_mo`,
  fermeture amont en `finally`, `X-Accel-Buffering: no`.
- Retirés à l'entrée : hop-by-hop, `Host`, `Authorization`, le cookie
  `__Host-atelier_apps`, `Forwarded`, `X-Forwarded-*`, `X-Atelier-*` du
  client. Ajoutés : `X-Forwarded-Prefix/Host/Proto/For`,
  `X-Atelier-Utilisateur`, `X-Atelier-Acces`. L'amont est joint en
  `Host: 127.0.0.1:<port>`.
- Réponses : hop-by-hop et `Service-Worker-Allowed` retirés ; `Set-Cookie`
  sans `Domain`, `Path` ramené au préfixe, `__Host-*` refusé ; `Location`
  réécrit ; défauts `nosniff`, `Referrer-Policy: same-origin`,
  `frame-ancestors 'self' <origine Atelier>`.
- Anti-CSRF même site : méthodes modifiantes et WS refusés si
  `Sec-Fetch-Site` vaut `same-site`/`cross-site` ou si `Origin` diffère ; WS :
  `Origin` obligatoire et exact, sinon 4403.
- Relais WS : amont d'abord (sous-protocoles du client), puis `accept` avec
  celui de l'amont ; `asyncio.wait(FIRST_COMPLETED)` ; codes de fermeture
  propagés ; `max_size` 16 Mio ; ping amont 20 s.
- SSE : battement < 30 s exigé des applications (délai d'Ingress 3600 s).

## Interface et agents

- Panneau « Applications » du projet (remplace le lien « Artefacts ») : index
  du dossier, puis chaque artefact avec mode, état, auteur ; Ouvrir,
  Démarrer/Arrêter, Journal (rendu en texte seul), Copier l'URL.
- Outils MCP dans `OutilsAtelier` : `atelier_artefacts`,
  `atelier_artefact_creer`, `atelier_artefact_demarrer`,
  `atelier_artefact_arreter`, `atelier_artefact_journal`,
  `atelier_artefact_verifier`.
- `~/work/bin/atelier-app` pour les agents sans MCP (même règle d'auteur,
  `$WIKICHAT_AGENT`, `--forcer`).
- Section « Montrer ce que tu produis » dans `bloc_contexte`
  (`project_context.py`).

## Artefacts sur l'hôte des applications

Tout contenu d'agent passe sur l'hôte des applications, sous
`https://apps…/<projet>/…`. `/v1/artifacts/*` devient un 302 par l'échange
de code ; le `PUT` par jeton déménage sur l'hôte des applications. Page
autonome : `CSP_SANDBOX` ; pages d'un artefact sous jeton : `CSP_CORPUS`, avec
`connect-src` limité à `https://apps…/<projet>/`. Le second cerveau deviendra
un artefact serveur (écriture + SSE de rechargement).

## Lots

0. Sécurité préalable : fermer `/vscode/(abs)proxy/`, Origin vérifiée sur les
   WS, garde CSRF même site, nouveau relais WS. (Engagé le 24/09.)
1. Second hôte et passage d'authentification (chart, `app.py`, `app_sessions`).
2. Manifeste et superviseur, sans web.
3. Proxy.
4. Artefacts sur l'hôte des applications.
5. Agents et interface (outils MCP, CLI, panneau, consigne, migration de
   Transcripts, STT, cerveau).
6. Plus tard : liens de partage révocables, interface des secrets, relais
   Grist, hôtes par application.

## État de la mise en œuvre (24/09/2026)

Lots 1 à 5 écrits dans `atelier-src` (non commités à cette date), chart dans
la branche `packaging-vitrine`. Suite locale complète verte ; sur le pod
(Python de l'Atelier, 3.13), superviseur et hôte des applications éprouvés
avec de vrais processus. Rien n'est encore déployé : le pod tourne toujours
l'ancien code.

### Fait

- **Serveur** : `apps/serveur.py` (`construire_app_apps`), servi par `app.py`
  sur `ATELIER_APPS_PORT` seulement si `ATELIER_APPS_PUBLIC_URL` est posé ;
  le second `uvicorn.Server` ne capte pas les signaux, il s'arrête quand
  celui de l'Atelier s'arrête. 421 pour tout autre `Host` (sauf `/_sante`,
  4421 pour une WebSocket).
- **Passage** : `apps/passage.py`. Codes en mémoire, 60 s, usage unique même
  raté. Table `app_sessions(id, parent_sid, portee, expire, created_at)` dans
  la base de la passerelle ; une session ne vaut que jointe à sa session
  owner vivante (`oauth_sessions`) : fermer celle-ci ou faire tourner la clé
  ferme les sessions d'applications sans ménage à faire.
- **Routes** `/v1/apps` (`apps/routes.py`) : liste, `creer`, `demarrer`,
  `arreter`, `journal` (texte, `nosniff`), `ouvrir`, `entree`.
- **Superviseur** au `lifespan`, après `nettoyer_orphelins()` ; fermé à
  l'arrêt. `ServiceApps` (`apps/service.py`) est la façade commune des
  routes, des outils MCP et du mandataire.
- **Mandataire** et **relais WS** (`apps/proxy.py`).
- **Artefacts** : `artefacts_servis.py` sert les deux adresses ;
  `/v1/artifacts/*` devient un 302 par l'échange de code dès qu'un second
  hôte existe (navigateur avec session) ; sans second hôte, il sert comme
  avant. `allow-downloads` dans les deux bacs à sable ; `index.html` d'un
  dossier servi à sa racine.
- **Agents et interface** : outils `atelier_artefact*`, `bin/atelier-app`
  (posé dans `~/work/bin` par `install/atelier-init.sh`), `bloc_contexte`,
  panneau « Applications ».
- **Variables de projet** : `.atelier/env.json` (`env_projet.py`).
- **OAuth** : cookie `__Host-gateway_owner_session` (l'ancien est lu puis
  remplacé) ; consentement posté d'ailleurs refusé ; sans `Sec-Fetch-Site`
  ni `Origin`, la session ne dispense plus de la clé.
- **Projets du pod** : `projet-sans-nom-4` (Transcripts) porte
  `artifacts/youtube-transcript/artefact.json` et n'a plus d'`atelier.app.json` ;
  `nouveau-projet-2` (voix) porte `artifacts/voix/artefact.json` et
  `.atelier/env.json`. Commits locaux dans ces deux dépôts.

### Écarts et précisions

- **Portée = projet.** Un seul cookie par hôte, et tous les artefacts d'un
  projet forment un domaine de confiance : la session porte une liste de
  projets, élargie à chaque ouverture (même session owner). Chaque requête
  vérifie que `/<projet>/…` est ouvert ; le code borne la destination au
  projet.
- **Ouvrir** exige la session owner d'un navigateur : la clé au porteur seule
  ne peut pas émettre de code (400), faute de session à laquelle rattacher
  la cascade. Sans hôte des applications, « ouvrir » un artefact autonome
  renvoie vers `/v1/artifacts/…` ; un artefact serveur, 409.
- **Auteur** : la conversation appelante est lue dans l'en-tête
  `X-Atelier-Conversation` de la session MCP (via `mcp_endpoint`), à défaut
  dans l'argument `auteur`. La déclaration de la porte MCP de l'Atelier
  (`mcp_sync.declaration_atelier`) ne pose pas encore cet en-tête : à ajouter
  (`"X-Atelier-Conversation": "${ATELIER_SESSION}"`) quand ce module sera
  libre. En attendant, `$WIKICHAT_AGENT` sert d'identité (consigne,
  `atelier-app`). Règle de voisinage, pas frontière de sécurité.
- **Relais WS** : `relais_ws.relayer` n'accepte ni plafond de message, ni
  réglage du ping, ni amont sur socket Unix ; `apps/proxy.relayer_ws` en
  reprend l'ordre et les codes avec ces trois ajouts, et n'importe de
  `relais_ws` que `sous_protocoles_demandes`. À fusionner.
- **`X-Forwarded-For`** : le pair TCP vu par uvicorn (le contrôleur
  d'Ingress en production), pas une valeur du client.
- **Protocoles non déclarés** : `Accept: text/event-stream` sans `sse` → 406 ;
  WebSocket sans `ws` → 4404. Pas encore prête : 503 + `Retry-After: 2` (page
  « Démarrage… » qui se recharge), 1013 pour une WebSocket. `en_echec` : page
  502, aucune relance par simple navigation.
- **Corps** : `Content-Length` au-delà de `corps_max_mo` → 413 avant tout
  contact ; en flux sans longueur, coupure au plafond et 413.
- **Voix** : son `.mcp.json` vise `127.0.0.1:18920` (instance lancée par
  `start.sh`) ; l'artefact serveur est une seconde instance, sur un port
  attribué, démarrée à l'ouverture et arrêtée après 30 min d'inactivité. Deux
  jeux de modèles en mémoire pendant ce temps. Un port stable pour les
  sessions (variable posée par l'Atelier) reste à concevoir.
- **Une application lit le disque** : l'environnement est construit, mais le
  processus tourne sous le même utilisateur et peut lire
  `~/work/.secrets/*` s'il le veut (Transcripts lit `llm_api_key` ainsi).
  L'isolement est celui des variables, pas des fichiers.

### Pas fait

- Second cerveau en service (écriture + SSE de rechargement).
- Plafond RSS : mesuré à chaque passage de surveillance (30 s), pas imposé
  par le noyau.
- Tests du relais WS sur socket Unix et de la page « Démarrage… » en
  navigateur réel (le rendu HTML n'est vérifié que par son statut).
