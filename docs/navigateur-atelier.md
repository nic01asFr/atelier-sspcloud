# Le navigateur des agents : Chrome DevTools MCP en stdio

Conception et mesures du 25/09/2026, pod `proj-claude-code-jupyter-python-0`
(128 cœurs ; cgroup mémoire `memory.max = max`, 15,6 Go occupés au moment des
mesures ; `/dev/shm` 10 Go ; Chrome 153.0.8010.47 dans `/usr/bin/google-chrome` ;
Node 22.23.2 de l'Atelier, le `node` du système est un Node 18).
Implémenté sur la branche `chrome-stdio`.

## 1. Point de départ

- Le navigateur était un **service HTTP distant** (`chrome-devtools-mcp`, fork
  `nouveau-projet`), joint par `ATELIER_CHROME_MCP_URL` + jeton, avec un en-tête
  `X-Atelier-Conversation` et un bureau noVNC relayé par l'Atelier
  (`/chrome/view`, `/chrome/vnc`).
- Ce service est à 0 réplique (il servait sans jeton) ; le fork n'expose que
  `raise_window` et `request_human` ; l'Atelier ne déclare donc plus aucun
  navigateur. Le pool du pod porte encore l'ancienne entrée HTTP.
- WebSearch est un outil serveur d'Anthropic : la passerelle LLM de SSPCloud
  l'accepte et le modèle **simule** une recherche, sans erreur.

## 2. Le serveur retenu

`chrome-devtools-mcp` **officiel** (ChromeDevTools, npm), version épinglée
**1.10.1** (23/09/2026), licence **Apache-2.0**, un seul paquet (dépendances
embarquées, 15 Mo), Node ≥ 20.19. Il lance Chrome avec `pipe: true` :
**aucun port de débogage ouvert**. Chrome n'est démarré qu'au premier outil
qui en a besoin.

Options utiles (lues dans `--help` de la 1.10.1) : `--headless`,
`--isolated` / `--userDataDir`, `--executablePath`, `--browserUrl` /
`--wsEndpoint` (rattachement), `--viewport`, `--logFile`, catégories
(`--no-category-performance|memory|emulation|network|debugging|input|navigation`),
`--slim` (3 outils), `--no-page-id-routing`, `--blockedUrlPattern` /
`--allowedUrlPattern`, `--proxyServer`, `--chromeArg`, `--workspace`
(dossiers où les outils écrivent ; défaut : le dossier temporaire),
`--screenshotFormat|Quality|MaxWidth|MaxHeight`, `--redactNetworkHeaders`,
`--no-usage-statistics` (télémétrie Google **active par défaut**),
`--no-performance-crux` (envoi des URL de traces à CrUX **actif par défaut**),
`CHROME_DEVTOOLS_MCP_NO_UPDATE_CHECKS`. `--experimentalScreencast` enregistre
une vidéo (ffmpeg), ce n'est pas une vue en direct.

Outils (30 en complet) : navigation (`new_page`, `navigate_page`,
`list_pages`, `select_page`, `close_page`, `wait_for`), saisie (`click`,
`hover`, `drag`, `fill`, `fill_form`, `type_text`, `press_key`,
`handle_dialog`, `upload_file`), lecture et débogage (`take_snapshot`,
`take_screenshot`, `evaluate_script`, `list_console_messages`,
`get_console_message`, `get_css_styles`, `lighthouse_audit`), réseau
(`list_network_requests`, `get_network_request`), émulation (`emulate`,
`resize_page`), performance (`performance_start_trace`,
`performance_stop_trace`, `performance_analyze_insight`), mémoire
(`take_heapsnapshot`).

Poids des schémas dans chaque conversation (`tools/list`) :

| Jeu | Outils | Octets | ≈ jetons |
|---|---|---|---|
| complet | 30 | 27 710 | 8 150 |
| sans `pageId` obligatoire | 30 | 25 256 | 7 430 |
| **courant** (sans performance, mémoire, émulation, sans `pageId`) | **24** | **20 198** | **5 940** |
| sans débogage en plus | 17 | 12 708 | 3 740 — perd `take_snapshot`, `take_screenshot`, `evaluate_script` : écarté |
| `--slim` | 3 | 1 021 | 300 |

Retenu : **courant** par défaut ; `ATELIER_CHROME_OUTILS=complet|minimal`.
Mesuré dans une vraie conversation (« Dis juste bonjour », estimation du relais
LLM) : 21 695 jetons d'entrée sans le navigateur, 27 369 avec — **+5 700
jetons par appel au modèle**, sur une fenêtre de 131 072. Claude Code ne les
a pas différés (les 24 outils sont dans la liste initiale).

## 3. Mode d'exécution : mesures

Chaque session ouvre `https://example.com` (petite page) ou
`https://fr.wikipedia.org/wiki/Marseille` (page lourde), puis `take_snapshot`.
PSS = mémoire proportionnelle (bibliothèques partagées comptées une fois).

**A. Un serveur stdio par session, chacun son Chrome sans écran**

| Sessions | Page | Démarrage serveur | 1ᵉʳ outil (dont lancement de Chrome) | PSS par session | PSS total |
|---|---|---|---|---|---|
| 1 | lourde | 0,92 s | 2,23 s | 918 Mo | 918 Mo |
| 3 | lourde | 0,97–1,01 s | 2,0–3,2 s | 743 Mo | 2 229 Mo |
| 5 | petite | 0,99 s | 0,77 s | 318 Mo | 1 589 Mo |
| 5 | lourde | 0,84 s | 1,93 s | 706 Mo | 3 532 Mo |

- Serveur seul, avant tout outil : **≈ 120 Mo** (Chrome pas encore lancé).
- Repos (10 s, 5 sessions) : 0,2 s de CPU cumulé.
- Arbre complet d'une conversation `claude -p` avec le navigateur ouvert
  (CLI + serveur + Chrome, petite page) : **≈ 780 Mo**, dont ≈ 250 Mo pour le CLI.

**B. Un Chrome partagé, un serveur par session rattaché par `--browserUrl`,
un contexte isolé (`isolatedContext`) par session**

| Sessions | Page | Chrome prêt | `new_page` | PSS total | PSS par session |
|---|---|---|---|---|---|
| 3 | petite | 0,28 s | 0,5 s | 1 040 Mo | 346 Mo |
| 5 | lourde | 0,27 s | — | 2 304 Mo | 461 Mo |

Mais **`list_pages` d'une session montre les pages de toutes les autres**, et
`select_page` les atteint : le contexte isolé ne cloisonne que les cookies,
et c'est le modèle qui choisit (ou oublie) son nom de contexte. Il faut en
plus un port de débogage ouvert en boucle locale, que tout processus du pod
peut piloter.

**Choix : A.** Le gain de B (≈ 35 % sur des pages lourdes, rien sur des
petites) ne paie ni la perte de cloisonnement entre conversations, ni le port
ouvert. Et en A, une conversation qui ne navigue pas ne coûte que 120 Mo.

### Fermeture propre (mesuré, sans exception)

| Fin | Serveur | Chrome | Profil |
|---|---|---|---|
| Entrée fermée (fin normale du client) | sort en 0,16 s | fermé | effacé |
| SIGTERM / SIGINT / SIGHUP au serveur nu | sort | fermé | **laissé** dans `/tmp` (2,4 Mo) |
| SIGKILL au serveur nu | tué | fermé (le tube se ferme) | **laissé** |
| Lanceur : entrée fermée / SIGTERM | sort (0 / 143) | fermé | **effacé** |
| Lanceur : SIGKILL | le serveur survit tant que son client tient le tube, puis sort | fermé avec lui | balayé au lancement suivant |
| `claude -p` en flux : SIGTERM / SIGKILL / entrée fermée | 0 processus restant | 0 | effacé |
| Passerelle (`ClientStdio`) : veille d'inactivité, fermeture | refermé | fermé | effacé |

Chrome ne reste jamais orphelin : il meurt avec son tube. Seul le profil
restait ; le lanceur le range (voir §4).

### Plafond

- Les tours de l'Atelier gardent au plus `cli_processus_max` (3) processus
  `claude` vivants, éteints après `cli_inactivite_s` (600 s) : autant de
  navigateurs au plus.
- VS Code, le terminal et wikichat lancent leurs propres processus. Le lanceur
  compte donc les Chrome vivants du compte et refuse d'en ouvrir plus de
  `ATELIER_CHROME_MAX` (défaut **6**, soit ≈ 2 à 5 Go selon les pages).
  Limite connue : l'agent reçoit alors une erreur de protocole
  (« Target closed ») plutôt que la phrase du lanceur.
- **Onglets par conversation** : `ATELIER_CHROME_ONGLETS_MAX` (défaut **8** ;
  `0` = sans plafond). Le lanceur place le filtre
  `bin/atelier-chrome-onglets.mjs` entre le client et le serveur. Avant de
  laisser passer un `new_page`, le filtre demande `list_pages` au serveur et
  compte sa section `## Pages` : les fenêtres ouvertes par un site sont donc
  comptées. Au plafond, l'agent reçoit une erreur d'outil lisible (« Ferme un
  onglet avec close_page… ») et le serveur ne reçoit rien. Serveur muet (15 s) :
  le filtre se fie au dernier compte vu, et laisse passer s'il n'en a aucun.
  C'est une garde de mémoire, pas de sécurité. Le lanceur trouve le filtre à
  côté de lui, sinon dans `~/work/atelier-src/bin/` (il est copié seul dans
  `~/work/bin/`) ; absent, il le dit sur sa sortie d'erreur et lance le serveur
  sans plafond. `ATELIER_CHROME_VERIFIER=1` affiche `onglets=` et `filtre=`.
- **Coût d'un onglet**, mesuré le 26/09 sous Windows (poste de développement,
  serveur 1.10.1 derrière le filtre, Chrome stable, mémoire privée des
  processus Chrome, à ne pas confondre avec la PSS du pod) : 1 onglet
  `example.com` 269 Mo, puis ≈ 30 à 50 Mo par onglet de plus ; 1 onglet
  Wikipédia « Marseille » 488 Mo, puis ≈ 200 à 260 Mo par onglet de plus. Huit
  onglets lourds coûteraient donc de l'ordre de 2 Go pour une conversation. Non
  mesuré sur le pod (lecture seule pendant ce lot).

## 4. Une déclaration pour toutes les surfaces

```json
"chrome-devtools-mcp": {"type": "stdio", "command": "/home/onyxia/work/bin/atelier-chrome", "args": []}
```

La même dans le fichier effectif d'un tour, le `.mcp.json` de chaque projet
(VS Code, terminal, wikichat) et le pool. Ni adresse, ni jeton, ni en-tête :
le processus **est** la conversation. L'identifiant `chrome-devtools-mcp` est
gardé : les sélections de connecteurs déjà faites dans les projets restent
valables. Au démarrage, `chrome_ensure` migre l'ancienne entrée HTTP du pool
(adresse, jeton et en-tête disparaissent ; l'état activé reste) ; le fichier
d'environnement ne porte plus `ATELIER_MCP_CHROME_DEVTOOLS_MCP_AUTHORIZATION`.
`ATELIER_NAVIGATEUR=0` l'éteint partout.

Le lanceur `~/work/bin/atelier-chrome` (source `atelier-src/bin/`, posé par
`install/atelier-init.sh`) :

- trouve un Node ≥ 20 (celui de l'Atelier avant celui du système), le serveur
  (`/opt/atelier/outils`, puis `~/work/.tools/chrome-devtools-mcp`) et Chrome —
  celui du volume d'abord (§9 bis) ; `ATELIER_CHROME_VERIFIER=1` dit ce qu'il
  trouve sans rien ouvrir ;
- crée un profil jetable `/tmp/atelier-chrome-<uid>/profil.<pid>` (0700) —
  jamais le profil de la personne, jamais `~/.cache` —, le range en sortant,
  relaie SIGTERM/SIGINT/SIGHUP, balaie les profils qu'aucun processus ne
  nomme plus. **Depuis la vague 3**, un processus qui appartient à une
  conversation (`ATELIER_SESSION`, sinon `CLAUDE_CODE_SESSION_ID`) garde
  plutôt le profil de la conversation, `conversation.<id>`, et fait publier
  son écran (§ 8, « Écran en direct ») ;
- pose `--headless --viewport 1280x720 --no-usage-statistics
  --no-performance-crux --redact-network-headers`, captures JPEG ≤ 1280 px,
  le jeu d'outils courant, `--workspace` = dossier temporaire + dossier du
  projet ;
- se donne lui-même comme exécutable Chrome (`--executablePath`) pour
  appliquer le plafond, puis cède la place au vrai Chrome (`exec`).

## 5. Passerelle, compositions, Assistant

La passerelle ne relayait que du HTTP : les serveurs stdio y étaient
`stdio-local`, inconnus de `gateway_find_tools` et impossibles à appeler.
`UpstreamPool` reçoit désormais la liste des serveurs stdio qu'il lance
lui-même (`stdio_lances`, fournie par `navigateur.stdio_de_la_passerelle`) —
le navigateur seul. Pour eux, `ClientStdio` (`mcp_gateway/upstream/stdio_client.py`) :

- **sonde** au démarrage (lance, lit les 24 outils en 0,9 s, referme) : les
  outils sont en cache et en ligne pour `gateway_find_tools`, sous le préfixe
  `chrome-devtools-mcp__` ;
- **relance** au premier `gateway_call_tool`, garde le serveur tant qu'on s'en
  sert, le **referme après 600 s d'inactivité** (et Chrome avec lui) ;
- lance le lanceur en **portée `passerelle`** : adresses privées refusées,
  pas d'écriture dans un projet.

C'est une instance **unique** pour tous les clients de la passerelle
(claude.ai via `/mcp`, compositions) : ils partagent ses pages. Ce sont tous
la personne elle-même ; si un jour la passerelle sert d'autres comptes, il
faudra une instance par client.

L'**Assistant** de l'Atelier, à venir, sera une conversation comme les autres :
il recevra la déclaration stdio (son propre processus, son propre Chrome) par
le fichier effectif, comme tout tour. Il ne doit pas passer par
`gateway_call_tool` pour naviguer.

## 6. Fonctions web recouvrées

Essais réels, `claude -p` sur le pod, modèle par défaut (`qwen3-6-35b-moe`) :

| Fonction | Comment | Résultat |
|---|---|---|
| Ouvrir une page, lire son titre | `navigate_page` + `evaluate_script` | « Example Domain », 4,7 s de bout en bout ; insee.fr : « Accueil - Insee - Institut national de la statistique et des études économiques », 10 s, avec le lanceur final — 0 processus et 0 profil restants après la fin |
| Lire une page | `evaluate_script(() => document.body.innerText…)` ; `take_snapshot` pour agir (identifiants `uid`) | l'arbre d'une page lourde fait 1,58 M caractères : Claude Code le range dans un fichier au-delà de sa limite et l'agent le lit par morceaux — la conversation survit, mais c'est cher |
| Formulaires, clics, saisie | `fill`, `fill_form`, `click`, `type_text`, `press_key` | outils présents (non rejoués ici) |
| Captures | `take_screenshot` | JPEG 1280×720, 23 Ko |
| Réseau, console | `list_network_requests`, `list_console_messages` | présents |
| Performance, Lighthouse | `lighthouse_audit` (courant) ; traces en `complet` | présents |
| **Recherche web** | navigateur sur `https://html.duckduckgo.com/html/?q=…` | l'agent a trouvé `github.com/ChromeDevTools/chrome-devtools-mcp` en 16 s |
| **WebFetch** | natif, extraction par le petit modèle | **cassé** : Claude Code envoie `"tools": []`, litellm répond 400 ; le modèle répondait alors de mémoire. **Réparé dans le relais LLM** (retire la liste vide) : « Example Domain » en 7 s |
| **WebSearch** | natif | simulé : **refusé partout** |

Moteurs depuis le pod : DuckDuckGo HTML 200 avec résultats ; DuckDuckGo lite
202 ; Bing 200 (balisage à lire au navigateur) ; Google redirige vers une page
de consentement ; Brave 429.

**Refus de WebSearch** : `permissions.deny: ["WebSearch"]` dans
`~/.claude/settings.json` (VS Code, terminal, wikichat) et dans le
`--settings` de chaque tour. Mesuré : l'outil disparaît de la liste du modèle
(`--disallowedTools WebSearch` fait de même). `ATELIER_WEBSEARCH_NATIF=1` le
rend, pour un fournisseur qui le servirait vraiment.

**Remplaçant structuré** : le service **WebTools** (SearXNG + extraction +
recherche approfondie) répond dans le namespace (`webtools-mcp-svc:8090/mcp`)
mais exige désormais **OAuth** (`401`, métadonnées sur
`user-nic01asfr-webtools-mcp.user.lab.sspcloud.fr`). À brancher dans le pool
comme connecteur OAuth quand son contrat sera figé ; ses outils passeront
alors par le même chemin que les autres connecteurs. En attendant : le
navigateur sur DuckDuckGo, consigne donnée à chaque agent dans la section
`atelier:contexte` de son `CLAUDE.md`.

## 7. Sécurité

- **Aucun port hors de la boucle locale** : stdio entre client et serveur,
  tube entre serveur et Chrome. Depuis la vague 3, le Chrome d'une
  conversation ouvre en plus un port de débogage **sur 127.0.0.1 seulement**
  (mesuré : `127.0.0.1:<port>` sous Windows, `0100007F` dans
  `/proc/net/tcp` sous Linux), pour l'écran en direct (§ 8). Limite (U1) :
  tout processus du pod, sous le même compte, peut piloter ce Chrome par ce
  port, comme il peut déjà lire `~/work`. Le port n'est jamais dit au
  navigateur de la personne. La passerelle n'en ouvre pas.
- **Profil jetable** par processus, 0700, effacé ; jamais le profil de la
  personne ; aucun cookie de l'Atelier (Chrome part vide).
- **Télémétrie coupée** (statistiques d'usage, CrUX, vérification de mise à
  jour).
- **Réseau interne (SSRF)** : `--blockedUrlPattern` refuse, en portée
  `passerelle`, boucle locale, 10/8, 172.16/12, 192.168/16, 169.254/16
  (métadonnées), 100.64/10, IPv6, noms sans point (services du cluster),
  `.local`, `.internal`, `.localhost` — y compris écrits en décimal ou en
  hexadécimal (`2130706433`, `0x7f000001`), mesuré. **Limite mesurée** : c'est
  un contrôle des adresses demandées, pas un pare-feu — une **redirection**
  depuis un site public (`httpbin.org/redirect-to?url=http://127.0.0.1:8787/`)
  atteint la page de connexion de l'Atelier, et un nom public qui résout en
  adresse privée passerait aussi. En conversation, rien n'est bloqué par
  défaut : l'agent a déjà `Bash` et `curl` vers tout le namespace, et
  déboguer un serveur local est l'usage premier de l'outil
  (`ATELIER_CHROME_RESEAU=public` pour bloquer quand même).
  **Recommandation** : si la passerelle doit un jour servir des tiers,
  mettre Chrome derrière un mandataire filtrant (`--proxyServer` +
  `--proxy-bypass-list=<-loopback>`) qui résout lui-même et refuse les
  adresses privées ; en l'état, les clients de la passerelle ont déjà
  `Onyxia` (exécution dans les pods) : le filtre est une défense en
  profondeur, pas une frontière.
- **Données** : `--redact-network-headers` masque les en-têtes sensibles dans
  ce que l'agent lit du réseau.

## 8. Écran en direct et « Prendre la main » (vague 3, équipe N, 26/09/2026)

Décisions J-f2 et J-f3 (`docs/vision/decisions.md`), U1
(`docs/vision/coherence-croisee.md` §5.1). Branche `v3-navigateur`.

### 8.1 Le choix : le tube de puppeteer, plus un port en boucle locale

Deux chemins étaient ouverts : (A) garder Chrome lancé par
`chrome-devtools-mcp` par son tube et lui faire ouvrir **en plus** un port de
débogage en boucle locale ; (B) faire lancer Chrome par le lanceur et
rattacher le serveur par `--browserUrl` / `--wsEndpoint`.

**Mesures** (26/09, poste Windows 11, Chrome 153.0.8010.53 et
chrome-headless-shell 154.0.8037.57 win64 ; puis Linux, conteneur de l'image
`ghcr.io/nic01asfr/atelier:latest` — Ubuntu 24.04, Python 3.13, Node 22.23.2 —,
chrome-headless-shell 154.0.8037.57 linux64, `chrome-devtools-mcp` 1.10.1) :

| Question | Mesure |
|---|---|
| Chrome accepte-t-il `--remote-debugging-pipe` **et** `--remote-debugging-port=0` ? | Oui, les deux variantes, les deux systèmes. Chrome répond par le tube (`Browser.getVersion`) et écrit `DevToolsActivePort` (port, puis `/devtools/browser/<id>`) dans le profil dans la même milliseconde |
| Où écoute le port ? | `127.0.0.1` seulement (`netstat` sous Windows ; `/proc/net/tcp` = `0100007F` sous Linux, avec `--remote-debugging-address=127.0.0.1`) |
| Une page ouverte par le tube se voit-elle par le port ? | Oui (`Target.createTarget` par le tube, visible par `Target.getTargets` au port) ; screencast JPEG par le port (première image en 36 à 350 ms), `Input.dispatchMouseEvent` accepté |
| Chrome meurt-il toujours avec son tube ? | Oui : tube fermé, sortie en 116 ms (headless shell) à 285 ms (Chrome) |
| Et puppeteer ? | `computeLaunchArguments` n'ajoute `--remote-debugging-pipe` que si **aucun** `--remote-debugging-*` n'est déjà là : demander le port par `--chromeArg` seul lui ferait perdre son tube. Le port s'ajoute donc dans le rôle « navigateur » du lanceur, **après** puppeteer |
| Chaîne entière | filtre, serveur 1.10.1, Chrome, écran de l'Atelier, page qui regarde : `tests/test_ecran_chrome_reel.py`, vert sous Windows (port par `--chromeArg=--remote-debugging-pipe` + `--chromeArg=--remote-debugging-port=0`, puppeteer ne sachant pas lancer un script bash) et sous Linux **par le vrai lanceur** (`ATELIER_ESSAI_LANCEUR=1`, trois passages). À la fin : fiche retirée, `DevToolsActivePort` retiré, profil gardé, aucun processus restant |

**Choix : A.** Il garde tout ce que § 3 avait mesuré et retenu : Chrome
n'est lancé qu'au premier outil (120 Mo tant que l'agent ne navigue pas), il
meurt avec son tube (aucun orphelin), puppeteer garde son transport, le
plafond de navigateurs reste dans le rôle « navigateur ». B aurait obligé le
lanceur à démarrer Chrome d'avance (ou à réinventer le démarrage paresseux),
à tenir lui-même sa durée de vie et le ménage des orphelins, pour le même
port en boucle locale. Le point de bascule `ATELIER_CHROME_WS` /
`ATELIER_CHROME_URL` / `attache/<session>` reste, inchangé ; un Chrome
rattaché n'a pas d'écran.

### 8.2 Ce que fait chaque pièce

**Le lanceur** (`bin/atelier-chrome`), quand le processus appartient à une
conversation (`ATELIER_SESSION`, sinon `CLAUDE_CODE_SESSION_ID` ; même forme
que dans l'Atelier, `[A-Za-z0-9][A-Za-z0-9_.-]{0,119}`), hors passerelle et
hors rattachement, et sauf `ATELIER_CHROME_ECRAN=0` :

- profil **de la conversation**, `/tmp/atelier-chrome-<uid>/conversation.<id>`
  (0700), gardé à la sortie : les connexions aux sites durent le temps de la
  conversation, d'un processus au suivant (le CLI est éteint après 600 s
  d'inactivité). Un verrou `flock` (`conversation.<id>.verrou`, hérité par le
  serveur et Chrome) le réserve : un second processus de la même conversation
  reçoit un profil jetable, sans écran, et le dit. Un profil de conversation
  dont le verrou est libre et n'a pas été touché depuis
  `ATELIER_CHROME_PROFIL_JOURS` jours (14) est balayé ;
- rôle « navigateur » : ajoute `--remote-debugging-port=0
  --remote-debugging-address=127.0.0.1` aux arguments de puppeteer ;
- le filtre est toujours placé devant le serveur quand il y a un écran, même
  avec `ATELIER_CHROME_ONGLETS_MAX=0` ;
- à la sortie : `DevToolsActivePort` retiré, fiche de l'écran retirée si le
  filtre n'a pas pu le faire ; au lancement, fiches d'un filtre mort
  balayées. `ATELIER_CHROME_VERIFIER=1` affiche `ecran=0|1`.

**Le filtre** (`bin/atelier-chrome-onglets.mjs`), en plus du plafond
d'onglets :

- publie `/tmp/atelier-chrome-<uid>/ecrans/<id>.json` (0600, écrit d'un coup)
  : `version`, `conversation`, `pid` (le sien), `port` et `chemin` (lus dans
  `DevToolsActivePort`, relu chaque seconde), `page` sélectionnée par l'agent
  (`{id, url, titre}`, lue dans la ligne `[selected]` de la section
  `## Pages` que rendent `new_page`, `navigate_page`, `select_page`,
  `close_page`, `list_pages` ; un titre peut porter des parenthèses),
  `attente` (actions retenues). Rien tant que Chrome n'a pas démarré ; retirée
  quand le filtre s'arrête ;
- **pause** : tant que `/tmp/atelier-chrome-<uid>/main/<id>.json` dit
  `{"prise": true}`, tout `tools/call` attend dans le filtre, sans atteindre
  le serveur ; un `notifications/cancelled` retire un appel retenu. Main
  rendue (`{"prise": false, "note": "…"}`), les appels repartent dans l'ordre
  (le plafond d'onglets tient toujours), et la note est **ajoutée au résultat
  du premier** ; sans appel retenu, elle attend le prochain. La note ne sert
  qu'une fois (le fichier part avec elle). Au-delà de
  `ATELIER_CHROME_MAIN_MAX_S` (1800 s), un appel retenu reçoit une erreur
  (« demande-lui où elle en est »), et une main posée depuis plus longtemps
  est tenue pour oubliée : un nouvel appel passe ;
- **page changée pendant la main** (correctif du 26/09, après essais) :
  l'Atelier écrit avec la note `"page_changee": true|false` (adresse ou titre
  de la page suivie par l'écran, avant la prise et au retour ;
  `ecran.page_a_change`). Si elle a changé, une action qui vise un élément par
  son identifiant de lecture (`uid`, `from_uid`, `to_uid`, `elements[].uid` :
  click, fill, hover, drag, fill_form, upload_file…) **n'est pas transmise** :
  l'agent reçoit une erreur d'outil qui porte la note et lui dit de relire la
  page (`take_snapshot`), et il en va de même pour toute action par `uid`
  jusqu'à son prochain `take_snapshot`. Les actions sans `uid`
  (`navigate_page`, `new_page`, `press_key`…) repartent avec la note. Page
  inchangée : rien ne change. Cause constatée : un `click uid=1_3` retenu,
  libéré après que la personne avait navigué ailleurs, a été joué sur la
  nouvelle page (« Successfully clicked »).

**L'écran** (`mcp_gateway/atelier/ecran.py`, dans le processus de l'Atelier) :

- lit la fiche (fichier ordinaire, à ce compte, 0600 sous Unix, filtre
  vivant, version, port et chemin de forme connue ; sinon ignorée) ; se
  rattache à `ws://127.0.0.1:<port>/devtools/browser/<id>` et **à rien
  d'autre** ;
- suit la page de l'agent : `Target.setDiscoverTargets`, puis la page dont
  l'adresse est celle de la fiche (celle déjà suivie si elle a la même, sinon
  la plus récemment changée) ; une page qui change d'adresse sans nouvelle
  liste (un lien cliqué) reste suivie. `Target.attachToTarget` (`flatten`),
  `Page.startScreencast` (JPEG, qualité 60, 1280 × 800 au plus) ; chaque
  image acquittée au plus `ATELIER_ECRAN_IPS` fois par seconde (8), ce qui
  règle la cadence sans rien d'autre ; titre et adresse relus toutes les
  0,5 s (`Target.getTargetInfo` : mesuré, Chrome ne signale pas toujours un
  changement de titre) ;
- **ne tourne que si quelqu'un regarde** : un registre par conversation,
  ouvert au premier spectateur ; au départ du dernier, `Page.stopScreencast`
  et la connexion se ferme (vérifié : plus aucune image acquittée) ;
- relaie des **gestes**, pas le protocole : souris (fraction de l'image,
  convertie en pixels de la page), molette, clavier, texte collé, adresse
  (`http`/`https` seulement), et seulement **main prise**. Tout le reste est
  refusé (`javascript:`, `file:`, `chrome:`, méthode inconnue, valeur hors
  bornes) ;
- porte la main : `prendre_la_main` (refusé sans navigateur ouvert) écrit
  `main/<id>.json` ; `rendre_la_main` écrit la note, ou **relance l'agent**
  par un message quand aucune action n'attend et qu'aucun tour ne travaille
  (conversation de l'Atelier). Une personne qui quitte l'écran main prise la
  rend au bout de 5 minutes sans spectateur (note « a quitté l'écran »).

**L'hôte des applications** (`apps/serveur.py`) sert, en portée
**`conversation:<id>`** (`apps/passage.py`, sur le modèle de la portée
« connecteur ») :

- `/_ecran/<id>/` (page), `ecran.js`, `ecran.css` : `default-src 'none'`,
  `script-src 'self'`, `img-src blob:`, `connect-src` vers l'hôte lui-même ;
  cadrage de l'Atelier seul, comme toute réponse de l'hôte ;
- le WebSocket `/_ecran/<id>/flux` : `Origin` égale à l'hôte, session de la
  **personne** couvrant `conversation:<id>` (une session d'agent jamais) ; il
  envoie un état JSON (`disponible`, `raison`, `url`, `titre`, `main`,
  `attente`) et des images JPEG binaires, et reçoit des gestes JSON
  (`{"type": "main", "prendre": true}`, `souris`, `clavier`, `texte`,
  `aller`).

Pourquoi pas `relais_ws` : relayer le WebSocket DevTools brut donnerait à la
page tout le navigateur de l'agent (scripts, cookies de tous les sites). Le
flux reste un WebSocket de l'hôte des applications, gardé comme ceux des
bureaux (`Origin`, session, portée), mais c'est l'Atelier qui parle à Chrome.

**L'Atelier** (`navigateur_routes.py`) : `GET /v1/ecran/<id>` (état, sans
port), `GET /v1/ecran/<id>/ouvrir` (session du navigateur exigée, code de
portée `conversation:<id>`, destination `/_ecran/<id>/` ; 404 pour une
conversation inconnue, y compris par le retour `/v1/apps/entree`),
`POST /v1/ecran/<id>/main` (`{"prendre": bool}`, 409 sans navigateur). Il
règle le registre des écrans : conversations connues, identifiant du CLI
(`claude_session_id`) comme autre nom de la fiche, tour en cours, relance par
`store.send` dans un fil, publiée en direct (`app.state.diffusion`, une ligne
dans `api.py`).

**Le panneau** (`web/js/views/panneau.js`, J-f2) : un `outil_debut` de
`mcp__chrome-devtools-mcp__new_page|navigate_page|select_page` (ou la fin
d'un tel appel, reconnue à son identifiant) ajoute l'onglet « Navigateur de
l'agent » : panneau fermé, il s'ouvre dessus ; un autre onglet regardé reste
regardé, l'onglet du navigateur porte un signal (« ● ») ; déjà regardé, rien
ne bouge. Si la personne replie le panneau pendant que le navigateur y est,
les pages suivantes ne le rouvrent plus : le signal passe sur le bouton du
panneau. L'onglet est un flux vivant (cadre retiré quand il est masqué, donc
screencast arrêté), jamais épinglé ni enregistré ; une conversation dont le
navigateur est ouvert le retrouve au chargement (`GET /v1/ecran/<id>`), sans
ouvrir le panneau. L'événement continue vers le fil (l'outil s'y affiche
comme les autres).

### 8.3 La pause de l'agent : bloquer, pas interrompre

« Prendre la main » **retient les actions de l'agent sur son navigateur**
dans le filtre, au lieu d'interrompre son tour :

- interrompre, aujourd'hui, c'est `harness.interrupt` : SIGTERM au CLI, donc
  au serveur MCP et à Chrome (mesuré en § 3 : « 0 processus restant »). La
  page que la personne voulait prendre disparaîtrait avec l'agent ;
- le filtre est sur toutes les surfaces (Atelier, VS Code, terminal,
  wikichat) ; l'Atelier, lui, ne sait interrompre que ses propres tours ;
- l'agent apprend ce qui a changé **à l'endroit même où il reprend** : la note
  s'ajoute au résultat de l'action qui attendait. S'il ne travaillait pas, le
  message de relance porte la même information.

Limite assumée : seules ses actions sur le navigateur attendent ; ses autres
outils (fichiers, Bash) continuent. Le bandeau de l'écran dit « Vous avez la
main : l'agent est en pause (n actions en attente) ».

### 8.4 J-f3 : les lectures du navigateur autorisées d'office

`navigateur.OUTILS_EN_LECTURE` (`list_pages`, `take_snapshot`,
`take_screenshot`, `wait_for`, `list_console_messages`,
`get_console_message`, `list_network_requests`, `get_network_request`,
`get_css_styles` ; relevés par `tools/list` du 1.10.1), exposée par
`regles_de_lecture_du_navigateur()` (`mcp__chrome-devtools-mcp__<outil>`) et
posée dans `permissions.allow` par `autoriser_les_lectures_du_navigateur`.
Elle est appelée par `refuser_les_outils_simules`, la fonction que passent
déjà les réglages de **chaque tour** (`harness`), ceux de VS Code, du
terminal et de wikichat (`vscode_handoff`) et le vérificateur de cohérence :
aucune ligne de `mcp_sync.py` n'a été nécessaire. Navigateur éteint
(`ATELIER_NAVIGATEUR=0`), ces règles sont retirées ; celles de la personne ne
sont jamais touchées. `select_page` n'y est pas (il change la page de
l'agent).

### 8.5 Vérifié, non vérifié

Vérifié :

- `tests/test_ecran.py` (hôte réel dans son fil, faux Chrome DevTools qui
  acquitte comme Chrome) : portée `conversation` qui refuse une autre
  conversation, un projet, une session de projet, une `Origin` étrangère, une
  requête sans session, et qu'aucun code d'agent ne peut obtenir ; ni port ni
  chemin DevTools dans la page, ses fichiers, le flux ou `GET /v1/ecran` ;
  suivi de la page sélectionnée (changement d'onglet, lien cliqué, nouvel
  onglet) ; rien ne tourne sans spectateur ; cadence bornée ; gestes refusés
  main libre, traduits main prise, `javascript:` jamais transmis ; note ou
  relance selon l'attente et le tour ; main abandonnée rendue ; fiche
  douteuse ignorée (0644, filtre mort, version, port, chemin) ; ouverture
  côté Atelier (code de la seule conversation, session du navigateur exigée) ;
- `tests/test_filtre_ecran.py` (filtre réel, faux serveur 1.10.1) : fiche
  (port, page, titre à parenthèses, 0600, retirée à la sortie) ; pause et
  reprise dans l'ordre, note une seule fois ; note sans appel retenu ; main
  trop longue ; appel retenu annulé ; plafond d'onglets tenu main rendue ;
- `tests/test_lanceur_chrome.py` sous Linux (conteneur, faux node et faux
  Chrome) : profil de conversation gardé, port ajouté en boucle locale dans le
  rôle « navigateur », pas d'écran sans conversation sûre, passerelle ou
  écran coupé, second processus en profil jetable, balayages ;
- `tests/test_ecran_chrome_reel.py` : vrai Chrome sous Windows, vrai lanceur
  sous Linux (voir 8.1) ; clic de la personne qui change le titre de la page,
  action de l'agent retenue puis rendue avec la note ;
- suites JS : `tests/js/panneau.suite.mjs` (onglet, ouverture, signal,
  repli, cadre par l'Atelier, jamais enregistré) et
  `tests/js/ecran.suite.mjs` (fractions de l'image, touches, bandeau).

Non vérifié (ne se voit que sur le pod, après déploiement) :

- la chaîne dans une vraie conversation `claude` du pod (CLI 2.1.281) : le nom
  exact des outils dans le flux (`mcp__chrome-devtools-mcp__…`), l'ouverture
  du panneau, l'image dans l'iframe sur `https`, la fluidité à travers
  l'Ingress de l'hôte des applications ;
- le bac à sable de Chrome sur le pod (dans le conteneur de mesure, il a
  fallu `seccomp=unconfined` ; sur le pod, Chrome tourne déjà, § 3) ;
- que Claude Code transmette `CLAUDE_CODE_SESSION_ID` à un serveur MCP stdio
  (VS Code, terminal) : sans lui, ces surfaces gardent le profil jetable, sans
  écran ;
- que les règles `permissions.allow` de J-f3 suppriment bien la question pour
  ces outils dans le CLI 2.1.281 (syntaxe `mcp__<serveur>__<outil>`,
  documentée, non rejouée) ;
- la relance après « Rendre la main » dans une vraie conversation (vérifiée
  en mode factice seulement).

### 8.6 Limites et suite

- La page est reconnue à son adresse : deux onglets de même adresse, l'écran
  suit le plus récemment changé.
- Le screencast montre la page, pas les boîtes de dialogue (`alert`, choix
  de fichier) : elles restent à l'agent (`handle_dialog`, `upload_file`).
- Pas de composition de saisie (IME) ; le collage passe par `Input.insertText`.
- Deux flux vivants au plus et vignettes (P4/P5) : non faits ; un onglet
  masqué s'arrête déjà.
- Un profil de conversation vit dans `/tmp` : il ne survit pas au
  redémarrage du pod.

### 8.7 Sur le pod, après le déploiement

Rien à poser à la main : le lanceur et le filtre sont recopiés dans
`~/work/bin/` par `install/atelier-init.sh` (le lanceur prend le filtre posé
à côté de lui). Les CLI déjà vivants gardent l'ancien lanceur jusqu'à leur
extinction (600 s d'inactivité).

1. `ATELIER_CHROME_VERIFIER=1 ATELIER_SESSION=essai ~/work/bin/atelier-chrome`
   : `ecran=1` et un `filtre=` qui existe.
2. Dans une conversation de l'Atelier : « ouvre https://example.com ». Le
   panneau s'ouvre sur « Navigateur de l'agent », l'image et l'adresse
   s'affichent. Changer d'onglet du panneau pendant qu'il navigue : un signal,
   pas de saut.
3. `ls -l /tmp/atelier-chrome-$(id -u)/ecrans/` : une fiche en `-rw-------`
   par conversation qui navigue ; `ss -ltnp | grep -i chrome` : seulement
   `127.0.0.1:<port>`.
4. « Prendre la main », cliquer dans la page, demander à l'agent une action
   sur le navigateur (elle attend : bandeau « 1 action en attente »),
   « Rendre la main » : son résultat porte la « Note de l'Atelier ». Main
   rendue sans action en attente et sans tour : un message relance l'agent.
5. Mode « défaut » : `take_screenshot` ne demande rien, `navigate_page`
   demande (J-f3).
6. Suivre la place : `du -sh /tmp/atelier-chrome-$(id -u)/conversation.*`.

## 9. Déploiement

Voir `docs/coherence-projet.md`, sections « Navigateur stdio » et
« Déploiement du 26/09 ».

## 9 bis. Chrome durable

Le Chrome des mesures (§ en-tête) était `/usr/bin/google-chrome`, installé à la
main dans le système du pod. Or le pod ne tourne pas sur l'image de l'Atelier
(`deploy/Dockerfile`, qui, elle, embarque Chrome) : il tourne sur l'image
Jupyter du catalogue, dont on n'extrait que le code. Tout ce qui est hors du
volume persistant `~/work` — `/usr/bin/google-chrome`, et les bibliothèques
qu'`apt` a tirées avec lui — disparaît au redémarrage du pod.

**Installation.** `install/atelier-init.sh` installe, une fois, un Chrome sans
écran sur le volume :

```sh
cd ~/work/.tools && ~/work/.tools/node-v22.23.2-linux-x64/bin/npx --yes \
  @puppeteer/browsers@3.2.3 install chrome-headless-shell@stable --path ~/work/.tools
```

- `@puppeteer/browsers` (Apache-2.0, l'outil de téléchargement de Puppeteer)
  prend Chrome for Testing sur `storage.googleapis.com/chrome-for-testing-public` ;
  il exige Node 22.12+, d'où le Node de l'Atelier et non celui du système
  (Node 18). Version épinglée (`PUPPETEER_BROWSERS_VERSION`).
- Arborescence : `~/work/.tools/chrome-headless-shell/linux-<version>/chrome-headless-shell-linux64/chrome-headless-shell`
  (ou `~/work/.tools/chrome/linux-<version>/chrome-linux64/chrome`).
- **chrome-headless-shell** par défaut : environ 100 Mo au lieu de 350, sans
  interface graphique, donc moins de bibliothèques système ; c'est le mode
  sans écran que nous utilisons de toute façon. `ATELIER_CHROME_NAVIGATEUR=chrome`
  prend Chrome for Testing complet (même moteur que `google-chrome`),
  `ATELIER_CHROME_CANAL` un autre canal ou une version (`stable` par défaut).
- Idempotent : rien n'est téléchargé si le binaire choisi est déjà là. Pour
  changer de version, supprimer le dossier `linux-<version>` et relancer l'init.
- Rien n'est fait si `ATELIER_CHROME_VOLUME=0`, si `ATELIER_CHROME_BIN` désigne
  déjà un Chrome, ou sur l'image de l'Atelier (Chrome y est). Un échec de
  téléchargement n'arrête pas l'init (journal : `~/work/logs/chrome-install.log`).

**Recherche par le lanceur.** `atelier-chrome` prend, dans l'ordre :
`ATELIER_CHROME_BIN` ; le Chrome du volume (chrome-headless-shell puis Chrome
for Testing, la version la plus récente d'abord) ; `google-chrome`,
`google-chrome-stable`, `chromium`, `chromium-browser` du `PATH` ;
`/opt/google/chrome/chrome`. Avec chrome-headless-shell, le rôle
« navigateur » remplace le `--headless=new` que demande puppeteer par
`--headless` (ce binaire est toujours sans écran).

**Bibliothèques système.** Le binaire est sur le volume, pas ses dépendances
(nss, nspr, gbm, dbus…). L'init lance `ldd` sur le Chrome du volume et **avertit**
s'il en manque (`bibliothèques système absentes : …`). Sur le pod actuel, elles
sont présentes tant que le `google-chrome` posé par `apt` l'est ; après un
redémarrage, seul l'avertissement de l'init dira si l'image Jupyter les a. Si
elles manquent : les demander dans l'image du service (ou l'init personnel
Onyxia qui tourne en root, `apt-get install -y libnss3 libgbm1 …`), ou passer au
chart de l'Atelier, dont l'image les porte. À vérifier au premier redémarrage :
`~/work/bin/atelier-chrome` avec `ATELIER_CHROME_VERIFIER=1`, puis un
`take_screenshot` réel, puis `/chrome/health`.
