# Règles communes aux projets de l'Atelier

Ce fichier vaut pour tout projet sous `~/work/projects/`. Le `CLAUDE.md` de
ton projet précise ; il ne contredit pas ces règles sans le dire. La section
`atelier:contexte` (ou `.atelier/contexte.md`), écrite par l'Atelier, dit ton
projet, tes outils et la manière de montrer une création : elle fait foi, ce
fichier ne la répète pas. Il est posé par l'Atelier : une modification à la
main est remplacée au démarrage suivant (une copie datée est gardée).

## Où tu es

Le pod est partagé avec la personne et d'autres agents : un port que tu
ouvres, tous peuvent l'appeler ; `~/work` survit au redémarrage, `$HOME` non.
Tes outils `atelier_*` agissent sur le projet de ta conversation (si ta
session ne nomme pas sa conversation, passe-le en `projet`) ; un autre projet
est refusé. Pour qu'un autre projet voie ou fasse quelque chose, écris
à ses agents par wikichat ; ni la passerelle, ni les commandes globales de
l'Atelier ne sont à toi.

## Mémoire et coordination

- Avant de refaire ce qui a peut-être été fait ou tranché : `atelier_rappel`,
  puis `atelier_fiche` ; ne relis pas de transcripts. `search_knowledge`
  cherche dans la connaissance commune et celle du projet.
- `ETAT.md` est le seul endroit de l'état du projet : réécris-le à la fin d'un lot.
- Un message wikichat dit son intention : `status="over"` et
  `expects_reply=true` si tu attends une réponse, `standby` avec
  `eta_seconds` si tu pars travailler, `done` sinon.

## Ce qui revient à la personne

Tu ne peux pas, et tu ne contournes pas : lancer ou activer un agent, créer
ou activer une tâche automatique (routine, trigger), ajouter un connecteur ou lui accorder un
secret, lier le projet à un pod, publier sur GitHub ou pousser, fusionner une
branche proposée, accepter une proposition de « À valider », exposer un port
sur Internet. Dis-le dans ta réponse et note-le dans `ETAT.md` (« À décider »
ou « Demandé à l'Atelier »).

Le mode de la conversation décide de ce qui demande une autorisation. Un refus
de la personne est une réponse : ne rejoue pas l'action autrement.

## Secrets

- Aucun jeton, clé ou mot de passe dans un fichier suivi, une URL de remote,
  un commit, un log, un artefact, un compte rendu. Un secret en clair trouvé :
  tu dis où il est, tu ne le recopies pas.
- `.mcp.json` (références `${ATELIER_MCP_…}`, hors git) est écrit par
  l'Atelier : ne l'édite pas, les connecteurs se choisissent dans l'Atelier.
- `~/work/.secrets/claude-env.sh` est déjà chargé : ne le lis pas, ne
  l'affiche pas, ne le recopie pas. Pas de `env`, `printenv` ou `set` sans filtre.
- Une variable dont une session a besoin se demande dans `.atelier/env.json` :
  `{"VOICE_TOKEN": "voice_token"}`, la valeur étant un nom de fichier de
  `~/work/.secrets/` (0600). Pas de nom `ATELIER_*`, `ANTHROPIC_*`,
  `CLAUDE_*`, `PATH`, `HOME`. Commit par `git add -f .atelier/env.json`.
- Un remote se déclare sans identifiants. Un remote qui porte un jeton : ne
  l'utilise pas, signale-le.

## Montrer ce que tu produis

En plus de la section `atelier:contexte` :

- Nom d'une création : minuscules, chiffres, tirets. Jamais un port du pod ni
  l'adresse de l'Atelier comme adresse à ouvrir.
- Autonome : pas de cookie ni de stockage navigateur. Pour que les pages
  écrivent chez elles (`PUT` relatif, `If-Match` avec l'`ETag` lu), pose
  `artefact.json` : `{"version": 1, "type": "statique", "edition": true}`.
- Serveur : `{port}` dans `commande`, jamais un numéro ; `repertoire` jamais
  hors du projet (`"../.."` pour la racine) ; `ws`/`sse` dans `protocoles` si
  tu t'en sers ; `secrets` par nom de fichier de `~/work/.secrets/apps/`.
  Écoute sur `127.0.0.1` ; ton service voit ses chemins sans le préfixe et
  reçoit `X-Forwarded-Prefix`. Ça ne démarre pas : `atelier_artefact_journal`.
- Montre une page dès qu'elle est prête ou modifiée (`atelier_montrer`) : le panneau s'ouvre
  chez la personne, sans geste de sa part. Il n'existe aucun bouton « Exposer » : ne lui
  demande jamais d'exposer, de publier ni d'ouvrir une adresse pour voir ta création.
- Avant d'annoncer qu'une page est prête : `atelier_artefact_verifier` avec son `nom`. Ses
  `avertissements` disent ce que `index.html` promet sans le tenir : fichier absent, chemin
  absolu, ressource externe (une page autonome n'a pas accès au réseau). Corrige, puis annonce.
- Pour l'ouvrir toi-même : `atelier_navigateur_ouvrir`, adresse valable deux
  minutes, **seul** chemin ; jamais `file://`, jamais `127.0.0.1:<port>`.
- Tu n'agis pas sur la création d'une autre conversation (`forcer` seulement
  si on te le demande).
- Interdit : présenter `127.0.0.1:<port>` comme une adresse ;
  `/vscode/proxy/<port>/` ; un Ingress, un Service Kubernetes, un port public,
  `expose_public` d'Onyxia.

## Ton navigateur

La personne voit ta page en direct. Lire (`take_snapshot`, `take_screenshot`,
console, réseau) est libre ; naviguer, cliquer, remplir suivent le mode.

- Plafond d'onglets (8 par défaut) : ferme (`close_page`) ou réutilise
  (`navigate_page`).
- La personne peut **prendre la main** ; tes actions attendent. Quand elle la
  rend, une « Note de l'Atelier » ou un message arrive : relis la page avant
  d'agir, ne refais pas ce qu'elle a fait.
- Les connexions aux sites durent la conversation : ne te reconnecte pas à
  chaque tour.

## Processus que tu lances

- `start.sh` / `stop.sh` versionnés, qui écrivent un `.pid` et ne tuent que ce PID.
- Écoute sur `127.0.0.1`, jamais `0.0.0.0`. Un service à montrer se déclare
  comme création serveur, pas par `start.sh`.
- Toute dépendance va au fichier de dépendances du projet ; modèles et gros
  binaires se téléchargent par un script versionné, sans être commités.

## Hooks du socle

Un hook `PreToolUse` refuse, sur toutes les surfaces, et dit pourquoi :

| Refusé | À la place |
|---|---|
| `killall`, `pkill` sur un motif non ancré, `kill $(pgrep …)`, `pgrep … \| xargs kill` (le motif attrape les processus des autres) | `kill "$(cat run.pid)"`, `pkill -F run.pid`, au pire `pkill -f '^…$'` |
| écoute sur `0.0.0.0` ou `::` (`--host`, `-b`, `HOST=`, `--ip`, `bind-addr`, `uvicorn`, `gunicorn`, `flask`) | `127.0.0.1`, ou une création serveur |
| `python -m http.server` sans `-b 127.0.0.1` | `python -m http.server 8000 -b 127.0.0.1` |

Un refus ne se contourne pas (autre syntaxe, script intermédiaire) : si tu as
une vraie raison, dis-la à la personne.

## Documents, tests, git

- Un document d'architecture décrit ce qui existe, ou dit en tête
  « proposition, non implémentée » ; quand le code s'en écarte, corrige-le
  dans le même commit.
- Un test vérifie un comportement, pas la présence d'une chaîne. Si le vrai
  comportement n'est pas testable ici (Chrome, audio, réseau), dis-le.
- « Fait » seulement pour ce que tu as exécuté et vu fonctionner ; le reste est
  « écrit, non vérifié ».
- Commits en français, à l'infinitif, qui disent ce qui change pour quelqu'un.
  Rien de généré, lourd ou local dans git (`node_modules/`, `.venv/`, modèles,
  `*.log`, `*.pid`, `__pycache__/`). Pas de push sans demande.

## Quand t'arrêter

Un lot à la fois. À la fin : ce qui marche (vérifié comment), ce qui ne marche
pas, ce qui reste. Tu n'enchaînes pas le lot suivant sans réponse.

# Compact instructions

(Read by Claude Code when it compacts a conversation; written in English, as
its documentation does.)

- The request to summarize comes from Claude Code, not from the person: it is
  not a new task, and it does not stop the work in progress.
- Keep: the task and who asked for it, decisions and why, files changed
  (paths), commands and tests run with their results, what remains, open
  questions to the person.
- Never copy a secret value into the summary; name the file or variable.
- After compaction every tool remains available (Read, Write, Edit, Bash, MCP
  servers): continue with them, and re-read a file when its exact content
  matters.
