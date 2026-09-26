# Chrome devtools atelier

> **25/09/2026 — l'Atelier ne se sert plus de ce fork.** Son navigateur est
> désormais le serveur **officiel** `chrome-devtools-mcp` (npm, 1.10.1), en
> **stdio**, lancé par `~/work/bin/atelier-chrome` dans le processus de chaque
> agent : un Chrome sans écran par conversation, sans service, sans jeton,
> sans en-tête de conversation, sans bureau (`docs/navigateur-atelier.md` du
> dépôt de l'Atelier). Le contrat HTTP ci-dessous (`X-Atelier-Conversation`,
> `CDM_API_KEY`, `/view`, `/vnc`) n'a plus de client côté Atelier.
>
> **26/09/2026 — la vue en direct existe sans ce fork** (vague 3, équipe N) :
> le lanceur fait ouvrir au Chrome de chaque conversation, en plus de son
> tube, un port de débogage en boucle locale ; l'Atelier s'y rattache en
> DevTools, diffuse le screencast dans l'onglet « Navigateur de l'agent » du
> panneau et porte « Prendre la main » (`docs/navigateur-atelier.md`,
> « Écran en direct »). Le bureau noVNC de ce fork n'a donc plus d'usage
> prévu.
>
> **Pour un agent qui navigue** : pour ouvrir une création de son projet, il
> appelle `atelier_navigateur_ouvrir` (par l'hôte des applications, code
> d'agent à usage unique), **jamais `file://`** ni `127.0.0.1:<port>`. Ses
> lectures (`list_pages`, `take_snapshot`, `take_screenshot`, `wait_for`,
> console, réseau) sont autorisées d'office ; quand la personne prend la main,
> ses actions attendent, et une « Note de l'Atelier » lui dit ce qui a changé
> quand elle la rend (`docs/consignes/socle.md`, « Ton navigateur »).

Ce projet est un fork de `ChromeDevTools/chrome-devtools-mcp` avec une couche
`src/cerema/` : un navigateur Chrome piloté par MCP, **une conversation
Atelier = un Chrome = un profil isolé**, et un bureau visible pour que la
personne reprenne la main. Il sert l'Atelier : ses agents pilotent Chrome par
ce serveur, et la personne regarde ou intervient par `/chrome/view` dans
l'Atelier, qui relaie le bureau du serveur.

Remote de travail : `origin` = `github.com/nic01asFr/chrome-devtools-mcp`,
branche `deploy-ghcr`. `upstream` = le projet Google, en lecture seule.
Le découpage en lots est dans `ROADMAP.md` ; un lot à la fois.

## Le contrat (écrit dans `docs/ATELIER-SPEC.md`, implémenté des deux côtés)

- **Conversation** : l'en-tête `X-Atelier-Conversation`, obligatoire à
  l'ouverture d'une session MCP (400 sinon, y compris pour un
  `${ATELIER_SESSION}` non résolu). Toutes les sessions MCP d'une conversation
  partagent le même Chrome. Chrome n'est fermé, profil supprimé, que par
  l'expiration d'inactivité (`CDM_SESSION_TIMEOUT`, en secondes, défaut 1800),
  `DELETE /conversations/:id` ou l'arrêt du serveur. Plafond
  `CDM_MAX_SESSIONS` conversations (défaut 3), 429 au-delà.
- **Jeton** : `Authorization: Bearer <CDM_API_KEY>` sur toutes les routes, y
  compris le WebSocket `/vnc`. Le serveur ne démarre pas sans clé, avec une
  clé connue (`changeme`) ou de moins de 24 caractères. `/health` sans jeton
  ne rend que `{"status":"ok"}`.
- **Écoute** : `127.0.0.1` par défaut ; l'image et le chart posent
  `CDM_HOST=0.0.0.0`. Le Service ne publie que 3100.
- **Bureau** : x11vnc et websockify en boucle locale du conteneur ; noVNC
  servi par Node en `/novnc`, page `/view`, WebSocket `/vnc` relayé vers
  websockify, tout derrière le jeton. Mot de passe VNC tiré au sort à chaque
  démarrage s'il n'est pas fourni. `/health` (avec jeton) dit `bureau: true`
  quand noVNC et websockify sont là.
- **Côté Atelier** : déclaration
  `{"url": <ATELIER_CHROME_MCP_URL>, "headers": {"X-Atelier-Conversation":
  "${ATELIER_SESSION}", "Authorization": "Bearer
  ${ATELIER_MCP_CHROME_DEVTOOLS_MCP_AUTHORIZATION}"}}` ; le jeton n'est jamais
  écrit en clair dans un fichier. Hors conversation (HOME, VS Code), la
  conversation vaut `${ATELIER_SESSION:-poste}`.

## Ce qui est établi (24/09/2026)

- **Ce qui tourne dans le namespace n'est aucune version publiée du fork** :
  le pod `chrome-devtools-mcp-*` rend le `/health` du fork, mais sans jeton sur
  `/mcp` ni `/view`, avec des outils (`navigate`, `screenshot`, `snapshot`)
  absents de l'historique git et de toutes les images GHCR. Et son port 6080
  (websockify) est ouvert sans jeton à tout le namespace. Détail et méthode :
  `docs/DIVERGENCES.md`. Il reste à déployer l'image construite depuis ce dépôt.
- **Le serveur de ce dépôt n'expose que `raise_window` et `request_human`** :
  les outils de l'amont (navigation, capture, inspection) ne sont pas branchés
  sur son `McpServer`. Tant qu'ils ne le sont pas, il ne permet pas de
  naviguer. C'est le prochain lot utile.
- Un serveur de développement de ce fork (lancé par `tsx src/cerema/index.ts`
  depuis ce dossier, il y a plusieurs jours) écoute sur `0.0.0.0:3000` du pod
  de l'Atelier. Il exige un jeton sur `/mcp` et `/view`, mais publie le détail
  de `/health` et accepte les jetons clients restés dans
  `~/work/cerema/tokens.json`. L'Atelier ne s'en sert pas. À arrêter par la
  personne.
- Des jetons ont été commités (commit `21d9a4b`, `.mcp.json`, désormais hors
  suivi) et le remote `origin` porte un PAT en clair. Ne réutilise aucun de
  ces jetons ; ne repousse pas un historique qui les contient.

## Règles propres au projet

- L'identifiant de session MCP ne sert jamais d'identifiant de conversation
  Atelier : c'est le transport qui le fixe. La conversation passe par
  `X-Atelier-Conversation`, et tout changement de ce canal s'écrit d'abord
  dans `docs/ATELIER-SPEC.md`.
- Un Chrome est fermé par la fin de sa **conversation** : expiration,
  `DELETE /conversations/:id`, arrêt du serveur, chacun détruit le profil.
  La fin d'une session MCP ne ferme pas Chrome. Des tests le vérifient contre
  un vrai Chrome headless en comptant les processus
  (`src/cerema/conversation.test.ts`).
- Plafond et délai configurables, défauts sobres ; `/health` dit combien de
  conversations sont ouvertes, jamais lesquelles, et seulement avec le jeton.
- Aucune route sans jeton, hors le `/health` minimal. Aucun port autre que
  3100 publié hors du conteneur.
- Les outils propres (`raise_window`, `request_human`) sont testés contre un
  vrai Chrome headless, pas par des doubles.
- Aucune divergence avec `upstream` hors de `src/cerema/`, du Dockerfile, du
  chart et de la CI. Toute autre divergence est justifiée dans
  `docs/DIVERGENCES.md`.
- Tests : `./node_modules/.bin/vitest run` (Node 18 dans le pod de l'Atelier,
  Chrome dans `/usr/bin/google-chrome`).

## Côté Atelier

Ce qui se corrige dans `atelier-src/mcp_gateway/atelier/` ne se corrige pas
ici. Le navigateur y vit dans `navigateur.py` (déclaration stdio, portée de la
passerelle, état local, refus de WebSearch, lectures autorisées d'office),
`chrome_ensure.py` (crée le connecteur une fois, migre l'ancienne entrée HTTP,
respecte une désactivation ou une suppression), `navigateur_routes.py`
(`/chrome/health`, `/v1/ecran/…`), `ecran.py` (l'écran en direct et la main
de la personne), `mcp_gateway/upstream/stdio_client.py` (la passerelle lance
le serveur pour ses propres clients), `atelier-src/bin/atelier-chrome` (le
lanceur) et `atelier-src/bin/atelier-chrome-onglets.mjs` (le filtre : plafond
d'onglets, fiche de l'écran, pause pendant la main de la personne). Les routes
`/chrome/view`, `/chrome/novnc/…` et `/chrome/vnc` n'existent plus.
