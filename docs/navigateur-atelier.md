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
  (`/opt/atelier/outils`, puis `~/work/.tools/chrome-devtools-mcp`) et Chrome ;
  `ATELIER_CHROME_VERIFIER=1` dit ce qu'il trouve sans rien ouvrir ;
- crée un profil jetable `/tmp/atelier-chrome-<uid>/profil.<pid>` (0700) —
  jamais le profil de la personne, jamais `~/.cache` —, le range en sortant,
  relaie SIGTERM/SIGINT/SIGHUP, balaie les profils qu'aucun processus ne
  nomme plus ;
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

- **Aucun port** : stdio entre client et serveur, tube entre serveur et
  Chrome. (Le mode partagé en aurait ouvert un.)
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

## 8. Reprise de main et vue en direct

En headless il n'y a plus de bureau : les routes `/chrome/view`,
`/chrome/novnc/…`, `/chrome/vnc` et le lien « Bureau » sont retirés.
`/chrome/health` dit désormais l'état local (lanceur prêt, Chrome ouverts,
plafond), et la fiche du connecteur l'affiche.

- **Voir** : l'agent prend une capture (`take_screenshot`, avec `filePath`
  dans le projet pour la garder) — suffisant pour presque tout.
- **Reprendre la main** (connexion, CAPTCHA) : pas en headless. Xvfb + x11vnc
  partagé rendrait un bureau, mais pour un Chrome par conversation il faudrait
  un écran par conversation ; ce n'est pas recommandé.
- **Vue en direct** (contrainte de l'équipe « panneau », `docs/vision/panneau.md`
  §7) : elle passera par le screencast DevTools (`Page.startScreencast`) et
  l'injection d'entrées, ce qui suppose un **Chrome lancé et possédé par
  l'Atelier**, auquel `chrome-devtools-mcp` se **rattache** au lieu de lancer
  le sien. Le lanceur garde ce point d'entrée : `ATELIER_CHROME_WS` /
  `ATELIER_CHROME_URL`, ou un fichier
  `/tmp/atelier-chrome-<uid>/attache/<ATELIER_SESSION>` écrit par le
  superviseur, font passer `--wsEndpoint` / `--browserUrl` au lieu de
  `--headless --executablePath`. Conséquences à assumer alors : le
  superviseur ouvre un port de débogage (en boucle locale, un Chrome par
  conversation pour garder le cloisonnement mesuré en §3), gère lui-même la
  durée de vie et le plafond de ces Chrome, et la fermeture ne vient plus du
  tube.

## 9. Déploiement

Voir `docs/coherence-projet.md`, section « Navigateur stdio ».
