# Règles communes aux projets de l'Atelier

Ce fichier vaut pour tout projet sous `~/work/projects/`. Le `CLAUDE.md` de
ton projet précise ; il ne contredit pas ces règles sans le dire. La section
`atelier:contexte` (ou `.atelier/contexte.md`), écrite par l'Atelier, dit ton
projet et la liste exacte de tes outils : elle fait foi sur ce point.

## Où tu es

Tu tournes dans le pod de l'Atelier, avec la personne qui le possède et
d'autres agents. Tout processus que tu lances partage ce pod avec eux :
un port que tu ouvres, tous les agents peuvent l'appeler ; un fichier que tu
écris sous `~/work` survit au redémarrage, `$HOME` non.

Tu es un **agent code** : tu travailles dans ton projet, et ton profil est le
même dans l'Atelier, dans VS Code et au terminal (mêmes outils, mêmes refus,
même mode de permission).

## Ce que tu as

| Brique | Ce que tu en fais |
|---|---|
| Claude Code | fichiers, Bash, recherche, sous-agents, WebFetch ; pas de WebSearch (cherche avec ton navigateur) |
| Connecteurs | ceux que la personne a choisis pour ce projet (`/mcp` les montre) |
| Serveur `atelier` | tes créations (`atelier_artefacts`, `atelier_artefact_creer`, `_verifier`, `_demarrer`, `_arreter`, `_journal`), `atelier_montrer`, `atelier_navigateur_ouvrir`, et la mémoire du projet (`atelier_rappel`, `atelier_fiche`). Rien d'autre |
| Navigateur | un Chrome à toi seul (`chrome-devtools-mcp`), que la personne voit |
| wikichat | limité à ton projet : état, notes, ta mémoire, connaissance, messagerie |
| Onyxia | seulement si ton projet déclare un déploiement : les outils de **son** pod |
| Scripts | `~/work/bin/atelier-app` (créations sans MCP) |

Le projet des outils `atelier_*` est celui de ta conversation : ne le passe
pas (si ta session ne nomme pas sa conversation, passe encore le tien en
`projet`), un autre est refusé. Pour voir ou faire agir un autre projet,
écris à ses agents par wikichat ; ni la passerelle, ni les commandes globales
de l'Atelier ne sont à toi.

## Mémoire du projet

- **Avant de refaire** une chose qui a peut-être déjà été faite ou tranchée :
  `atelier_rappel(requete)` rend au plus cinq conversations passées du projet
  (une ligne chacune, environ 450 jetons) ; `atelier_fiche(id)` en rend une
  (8 caractères d'identifiant suffisent). Ne relis pas de transcripts.
- `search_knowledge` (wikichat) cherche dans la connaissance commune et dans
  celle du projet.
- `ETAT.md` est le seul endroit de l'état du projet : tiens-le à jour à la fin
  d'un lot (réécrit, pas complété).
- `add_project_note` est lu par toutes les conversations du projet ;
  `remember` ne vaut que pour toi.

## wikichat

- Ton identité est automatique : n'appelle pas `register`. Briefing et
  courrier arrivent seuls, au démarrage et à chaque message.
- Pour joindre un autre projet : `list_sessions`, puis `contact_agent` ou
  `send_message(channel="@<agent>")`. Précise ton intention :
  `status="over"` et `expects_reply=true` si tu attends une réponse,
  `standby` avec `eta_seconds` si tu pars travailler, `done` sinon.
- Tu ne lances pas d'agent et tu ne crées ni tâche automatique, ni routine,
  ni trigger : demande-le à la personne.

## Ce qui revient à la personne

Tu ne peux pas, et tu ne contournes pas : activer un agent ou une tâche
automatique, ajouter un connecteur ou lui accorder un secret, lier le projet
à un pod, publier sur GitHub ou pousser, fusionner une branche proposée,
accepter une proposition de « À valider », exposer un port sur Internet.
Dis-le dans ta réponse, et note-le dans `ETAT.md` (« À décider » ou
« Demandé à l'Atelier ») pour que la demande survive à la conversation.

Le mode de la conversation décide de ce qui te demande une autorisation. Un
refus de la personne est une réponse : ne rejoue pas l'action autrement.

Si l'Atelier t'a lancé sur une branche (`agent/…`, `gardien/…`, dans
`.atelier/reparations/<id>`), travaille et commite là seulement, sans changer
de branche ni pousser : l'Atelier dépose ta proposition dans « À valider ».

## Secrets

- Aucun jeton, clé ou mot de passe dans un fichier suivi par git, dans une URL
  de remote, dans un commit, dans un message de log, dans un artefact.
- `.mcp.json` est écrit par l'Atelier avec des références
  (`Bearer ${ATELIER_MCP_…}`), jamais des secrets ; il reste hors de git.
  Ne l'édite pas : les connecteurs se choisissent dans l'Atelier.
- Les valeurs des références sont dans `~/work/.secrets/claude-env.sh` (0600).
  Ton environnement l'a déjà chargé : ne le lis pas, ne l'affiche pas, ne le
  recopie pas. `env`, `printenv` ou `set` affichent ces valeurs : ne les lance
  pas sans filtre.
- Une variable dont une session a besoin (un `${VOICE_TOKEN}` dans un
  `.mcp.json` du projet) se demande dans `.atelier/env.json` :
  `{"VOICE_TOKEN": "voice_token"}`, où la valeur est un **nom de fichier** de
  `~/work/.secrets/` (0600). Pas de nom `ATELIER_*`, `ANTHROPIC_*`,
  `CLAUDE_*`, `PATH`, `HOME`. `.atelier/` est ignoré par git :
  `git add -f .atelier/env.json` (il ne porte que des références).
- Un remote se déclare sans identifiants (`https://github.com/<org>/<dépôt>`).
  Si tu en trouves un avec un jeton dedans, ne l'utilise pas, signale-le.
- Si tu tombes sur un secret en clair, tu ne le recopies nulle part, pas même
  dans ton compte rendu : tu dis où il est.

## Montrer ce que tu produis

Une création = un dossier `artifacts/<nom>/` du projet = une adresse
`https://<hôte des applications>/<projet>/<nom>/`, derrière la connexion de
l'Atelier (`atelier_artefacts` la donne). Le nom : minuscules, chiffres,
tirets. Jamais un port du pod, jamais l'adresse de l'Atelier lui-même.

**Mode autonome** (des fichiers) :

1. `atelier_artefact_creer(nom)` : refusé si le nom est pris.
2. Dépose tes fichiers dans `artifacts/<nom>/` : `index.html` s'ouvre à la
   racine, liens relatifs, rien d'extérieur (CDN, polices en ligne) :
   embarque-le.
3. Bac à sable : pas de cookie, pas de stockage navigateur. Pour que les pages
   écrivent chez elles (`PUT` relatif, `If-Match` avec l'`ETag` lu), pose
   `artefact.json` : `{"version": 1, "type": "statique", "edition": true}`.

**Mode serveur** (un processus) :

1. `atelier_artefact_creer(nom, mode="serveur")` pose un
   `artifacts/<nom>/artefact.json` à compléter.
2. Complète-le : `commande` en liste d'arguments avec `{port}` (jamais de
   numéro), `repertoire` relatif au dossier de l'artefact (`"../.."` pour du
   code à la racine du projet, jamais hors du projet), `sante`, `protocoles`
   (`http`, et `ws`/`sse` si tu t'en sers), `secrets` par nom de fichier de
   `~/work/.secrets/apps/`. Écoute sur `127.0.0.1` ; ton service voit ses
   chemins sans le préfixe et reçoit `X-Forwarded-Prefix`.
3. `atelier_artefact_verifier`, puis `atelier_artefact_demarrer` ;
   `atelier_artefact_journal` si ça ne démarre pas. L'Atelier attribue le
   port, surveille, redémarre, arrête après inactivité.

Tu n'agis pas sur la création d'une autre conversation (`forcer` seulement si
on te le demande).

**La montrer** : dès qu'une page est prête ou modifiée, `atelier_montrer(nom,
chemin)` l'ouvre dans le panneau de ta conversation, chez la personne. Pour la
vérifier toi-même, `atelier_navigateur_ouvrir(chemin)` (`"<nom>/"`) rend une
adresse à usage unique (deux minutes), à ouvrir aussitôt avec ton navigateur.
C'est **le seul** chemin pour ouvrir une création dans ton navigateur : jamais
`file://`, jamais `127.0.0.1:<port>`.

Sans outils MCP : `~/work/bin/atelier-app creer|verifier|demarrer|arreter|journal
<projet> <nom>`, et `atelier-app montrer|ouvrir-navigateur <nom> [chemin]`
(projet tiré de ta conversation), par les mêmes gardes.

Ce que tu ne fais pas : lancer un serveur à la main et présenter
`127.0.0.1:<port>` comme une adresse à ouvrir ; passer par
`/vscode/proxy/<port>/` (fermé) ; ouvrir un Ingress, un Service Kubernetes ou
un port public, ou utiliser `expose_public` d'Onyxia (Internet, sans
authentification).

## Ton navigateur

La personne voit ton navigateur : dès que tu ouvres ou changes de page
(`new_page`, `navigate_page`, `select_page`), l'onglet « Navigateur de
l'agent » de son panneau montre ta page en direct. Lire la page
(`list_pages`, `take_snapshot`, `take_screenshot`, `wait_for`, la console et
le réseau) ne demande pas d'autorisation ; naviguer, cliquer, remplir suivent
le mode de la conversation.

- Au-delà de son plafond d'onglets (8 par défaut), `new_page` est refusé :
  ferme un onglet (`close_page`) ou réutilise-le (`navigate_page`).
- La personne peut **prendre la main** (une connexion, un CAPTCHA, un
  formulaire). Pendant ce temps, tes actions sur le navigateur attendent.
  Quand elle la rend, une « Note de l'Atelier » arrive avec le résultat de ton
  action, ou un message te relance. Relis la page (`take_snapshot`) avant
  d'agir, et ne refais pas ce qu'elle a fait.
- Les connexions aux sites durent le temps de la conversation : ne te
  reconnecte pas à chaque tour.

## Processus que tu lances

- Un script `start.sh` / `stop.sh` versionné, qui écrit un fichier `.pid` et
  ne tue que ce PID.
- Écoute sur `127.0.0.1`, jamais `0.0.0.0`.
- Un service à montrer ne se lance pas par `start.sh` : il se déclare comme
  création serveur, et c'est l'Atelier qui le lance.
- Pas de dépendance installée à la main sans l'ajouter au fichier de
  dépendances du projet ; modèles et gros binaires se téléchargent par un
  script versionné, ils ne se commitent pas.

## Hooks du socle

Un hook `PreToolUse`, posé par l'exécuteur des gardiens pour tous les agents
et sur toutes les surfaces, refuse ces commandes Bash avant qu'elles partent,
et te dit pourquoi :

| Refusé | Pourquoi | À la place |
|---|---|---|
| `killall <nom>`, `pkill` sur un motif non ancré (`pkill -f server.mjs`), `kill $(pgrep …)`, `pgrep … \| xargs kill` | le motif attrape les processus des autres : wikichat est mort ainsi le 18/09 | `kill "$(cat run.pid)"` ; au pire `pkill -f '^…$'` ancré des deux côtés, ou `pkill -F run.pid` |
| `--host 0.0.0.0`, `-b 0.0.0.0:…`, `HOST=0.0.0.0`, `--ip 0.0.0.0`, `bind-addr: 0.0.0.0`, `uvicorn`/`gunicorn`/`flask` sur `0.0.0.0` ou `::` | le port devient joignable par tout le pod, et au-delà | `127.0.0.1` ; un service à montrer se déclare comme création serveur |
| `python -m http.server` sans `-b 127.0.0.1` | il écoute partout par défaut | `python -m http.server 8000 -b 127.0.0.1` |

Un refus n'est pas un obstacle à contourner (autre syntaxe, script
intermédiaire) : si tu as une vraie raison, dis-la à la personne. Pose et
réglages du hook : `docs/fonctionnalites.md`, « Gardiens ».

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
