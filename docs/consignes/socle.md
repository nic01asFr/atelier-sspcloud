# Règles communes aux projets de l'Atelier

Ce fichier vaut pour tout projet sous `~/work/projects/`. Le `CLAUDE.md` de
ton projet précise ; il ne contredit pas ces règles sans le dire.

## Où tu es

Tu tournes dans le pod de l'Atelier, avec la personne qui le possède et
d'autres agents. Tout processus que tu lances partage ce pod avec eux :
un port que tu ouvres, tous les agents peuvent l'appeler ; un fichier que tu
écris sous `~/work` survit au redémarrage, `$HOME` non.

## Secrets

- Aucun jeton, clé ou mot de passe dans un fichier suivi par git, dans une URL
  de remote, dans un commit, dans un message de log, dans un artefact.
- `.mcp.json` est écrit par l'Atelier avec des références
  (`Bearer ${ATELIER_MCP_…}`), jamais des secrets ; il reste hors de git
  (l'Atelier l'ajoute au `.gitignore`). N'y écris jamais une valeur en clair :
  si un serveur du projet a besoin d'un jeton, voir `.atelier/env.json`
  ci-dessous. Il porte ce que l'agent reçoit sur toutes les surfaces
  (Atelier, VS Code, terminal) : l'Atelier le réécrit ; choisis les
  connecteurs dans l'Atelier plutôt que de l'éditer.
- Les valeurs des références sont dans un seul fichier,
  `~/work/.secrets/claude-env.sh` (0600, généré par l'Atelier). Ton
  environnement l'a déjà chargé : ne le lis pas, ne l'affiche pas, ne le
  recopie pas. `env`, `printenv` ou `set` affichent ces valeurs : ne les lance
  pas sans filtre.
- Une variable dont une session a besoin (un jeton qu'un `.mcp.json` du
  projet référence en `${VOICE_TOKEN}`, par exemple) se demande dans
  `.atelier/env.json` : `{"VOICE_TOKEN": "voice_token"}`, où la valeur est un
  **nom de fichier** de `~/work/.secrets/` (0600). L'Atelier la pose dans
  l'environnement des tours du projet et de VS Code ; la valeur n'est jamais
  écrite dans le projet. Pas de nom `ATELIER_*`, `ANTHROPIC_*`, `CLAUDE_*`,
  `PATH`, `HOME` : ils sont refusés. `.atelier/` est ignoré par git :
  `git add -f .atelier/env.json` (il ne porte que des références).
- Un remote se déclare sans identifiants (`https://github.com/<org>/<dépôt>`).
  Si tu en trouves un avec un jeton dedans, ne l'utilise pas, signale-le.
- Si tu tombes sur un secret en clair, tu ne le recopies nulle part, pas même
  dans ton compte rendu : tu dis où il est.

## Montrer ce que tu produis

Un artefact = un dossier `artifacts/<nom>/` du projet = une adresse
`https://<hôte des applications>/<projet>/<nom>/`, derrière la connexion de
l'Atelier (`atelier_artefacts` la donne). Le nom : minuscules, chiffres,
tirets. Jamais un port du pod, jamais l'adresse de l'Atelier lui-même.

**Mode autonome** (des fichiers) :

1. `atelier_artefact_creer(projet, nom)` — refusé si le nom est pris.
2. Dépose tes fichiers dans `artifacts/<nom>/` : `index.html` s'ouvre à la
   racine, liens relatifs entre pages, CSS/JS/images relatifs autorisés, rien
   d'extérieur (CDN, polices en ligne) : embarque-le.
3. Bac à sable : pas de cookie, pas de stockage navigateur. Pour que les pages
   écrivent chez elles (`PUT` relatif, `If-Match` avec l'`ETag` lu), pose
   `artefact.json` : `{"version": 1, "type": "statique", "edition": true}`.

**Mode serveur** (un processus) :

1. `atelier_artefact_creer(projet, nom, mode="serveur")` : il pose un
   `artifacts/<nom>/artefact.json` à compléter.
2. Complète-le : `commande` en liste d'arguments avec `{port}` (jamais de
   numéro de port), `repertoire` relatif au dossier de l'artefact (`"../.."`
   pour du code à la racine du projet, jamais hors du projet), `sante`,
   `protocoles` (`http`, et `ws`/`sse` si tu t'en sers), `secrets` par nom de
   fichier de `~/work/.secrets/apps/`. Écoute sur `127.0.0.1` ; ton service
   voit ses chemins sans le préfixe et reçoit `X-Forwarded-Prefix`.
3. `atelier_artefact_verifier`, puis `atelier_artefact_demarrer` ;
   `atelier_artefact_journal` si ça ne démarre pas. L'Atelier attribue le
   port, surveille, redémarre, arrête après inactivité.

La même adresse vaut dans les deux modes. Tu n'agis pas sur l'artefact d'une
autre conversation (`forcer` seulement si on te le demande). Sans outils MCP :
`~/work/bin/atelier-app creer|verifier|demarrer|arreter|journal`.

Ce que tu ne fais pas :

- lancer un serveur à la main en présentant `127.0.0.1:<port>` comme une
  adresse à ouvrir : elle n'est joignable que depuis le pod ;
- passer par `/vscode/proxy/<port>/` (fermé) ;
- ouvrir un Ingress, un Service Kubernetes ou un port public toi-même, ou
  utiliser `onyxia__expose_public` : il publie un port sur Internet sans
  aucune authentification.

## Processus que tu lances

- Un script `start.sh` / `stop.sh` versionné, qui écrit un fichier `.pid` et
  ne tue que ce PID (jamais `pkill -f` sur un motif large).
- Écoute sur `127.0.0.1`, jamais `0.0.0.0`.
- Un service à montrer ne se lance pas par `start.sh` : il se déclare comme
  artefact serveur (ci-dessus), et c'est l'Atelier qui le lance.
- Pas de dépendance installée à la main sans l'ajouter au fichier de
  dépendances du projet ; les modèles et gros binaires se téléchargent par un
  script versionné, ils ne se commitent pas.

## Documents et vérité

- Un document d'architecture décrit ce qui existe, ou dit en tête « proposition,
  non implémentée ». Quand le code s'en écarte, corrige le document dans le
  même commit.
- Un test vérifie un comportement, pas la présence d'une chaîne. Si tu ne peux
  pas tester le vrai comportement (Chrome, audio, réseau), dis-le au lieu
  d'écrire un test qui passe à vide.
- Ne dis « fait » que pour ce que tu as exécuté et vu fonctionner. Le reste est
  « écrit, non vérifié ».

## Git

- Messages de commit en français, à l'infinitif, qui disent ce que le commit
  change pour quelqu'un (« Tenir la voix française par défaut »).
- Rien de généré, de lourd ou de local dans git : `node_modules/`, `.venv/`,
  modèles, `*.log`, `*.pid`, `__pycache__/`.
- Pas de push sans que la personne l'ait demandé.

## Quand t'arrêter

Un lot à la fois. À la fin d'un lot : ce qui marche (vérifié comment), ce qui
ne marche pas, ce qui reste. Tu n'enchaînes pas le lot suivant sans réponse.

# Compact instructions

(Section read by Claude Code when it compacts a conversation — heading and
wording in English, as the Claude Code documentation writes it.)

When you are compacting:

- The request to write a summary comes from Claude Code itself, not from the
  person. Do not treat it as a new task, do not answer it as if they had asked
  for a summary, and do not stop the work in progress because of it.
- Keep: the task being done and who asked for it, the decisions taken and why,
  the files changed or created (paths), the commands and tests run with their
  results, what remains to do, and any open question addressed to the person.
- Never copy a secret value (token, key, password) into the summary; name the
  file or variable that holds it instead.
- After compaction, every tool remains available — Read, Write, Edit, Bash,
  the MCP servers (`atelier_*`, connectors). Continue the work with them; re-read
  a file rather than relying on a quoted excerpt when its exact content matters.
