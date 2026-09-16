# Atelier

Un hub qui fait travailler Claude Code sur un pod SSPCloud : conversations de
projet, agents, connecteurs MCP, et une face VS Code intégrée. Un pod par
personne, un Atelier par pod : ce dépôt en porte le code, l'installation et la
documentation.

Interface : le port 8787 de votre service Onyxia, sous
`https://user-<idep>-<service>.user.lab.sspcloud.fr/`. Pour l'installer :
[`docs/installer.md`](docs/installer.md).

---

## Ce que ça contient

| Chemin | Rôle |
|--------|------|
| `atelier-src/mcp_gateway/atelier/` | le service : API FastAPI, registre de sessions, harnais `claude`, passerelle MCP |
| `atelier-src/mcp_gateway/atelier/web/` | l'interface, JavaScript sans cadre applicatif |
| `atelier-src/vscode-extension/` | la petite extension qui ouvre Claude Code sur la bonne conversation |
| `atelier-src/tests/`, `atelier-src/tests-js/` | la suite Python et le filet JavaScript |
| `install/atelier-init.sh` | l'installation sur un pod SSPCloud, rejouable à chaque démarrage |
| `wikichat-atelier/` | le pilote wikichat déployé avec le service |
| `deploy-patches/deploy_agent_ui.py` | outil de l'auteur : pousser l'arbre de travail vers un pod par le MCP Onyxia, sans passer par git |
| `docs/` | installation, cadrage, plans, mécanismes |
| `filtre.mjs` | garde-fou d'un autre projet, resté ici par accident — à déplacer |

Le reste de `deploy-patches/` n'est pas suivi : ce sont des fichiers de travail
d'anciennes sessions de déploiement.

---

## Les quatre onglets

**Code** — les conversations, rangées par projet. Une conversation crée son
projet à l'envoi du premier message. Chaque conversation peut s'ouvrir dans VS
Code, sur elle-même.

**Assistant** — la mémoire des projets, qui travaille dans son propre dossier,
une conversation par sous-dossier.

**Connecteurs** — les services MCP : le socle que l'Atelier fournit, ceux que
l'on branche, et les compositions.

**Agents** — les agents systèmes et personnels, leur outillage et leur activité.

---

## Installation et déploiement

Le service tourne sur le pod, pas en local. Le chemin normal est le
**catalogue Onyxia** : un chart [`charts/atelier`](charts/atelier) publié dans
[`helm-repo/`](helm-repo/), une image [`deploy/Dockerfile`](deploy/Dockerfile)
(`ghcr.io/nic01asfr/atelier`, même base que le Jupyter du catalogue) qui
embarque node, code-server, l'extension Claude Code, wikichat et l'Atelier.
Onyxia remplit le formulaire depuis le profil de l'utilisateur — adresse, clé
du modèle, identité git — et l'utilisateur n'a qu'à ouvrir. Le chemin de
secours, pour un Jupyter déjà garni, est le script
[`install/atelier-init.sh`](install/atelier-init.sh), que le conteneur utilise
aussi comme point d'entrée. La recette complète est dans
[`docs/installer.md`](docs/installer.md).

L'auteur dispose en plus d'un raccourci, `deploy-patches/deploy_agent_ui.py`,
qui pousse l'arbre de travail vers son pod par le MCP Onyxia sans passer par
git ; il vise son pod et lit son jeton, et n'est pas le chemin d'installation.
Les modules Python demandent un redémarrage du service pour prendre effet ; les
fichiers de l'interface, non.

La clé propriétaire (`atelier_owner_key`) ne transite jamais par le dépôt ni par
les fichiers de projet : elle vit dans `~/work/.secrets/` sur le pod, et n'est
transmise au processus `claude` que par son environnement.

Pour relancer le service, utilisez `~/work/bin/atelier-relancer` plutôt qu'un
`kill` sur le motif du processus : celui-ci tue aussi le shell qui l'exécute, sa
propre ligne de commande contenant le motif, et laisse des orphelins — quatre
instances s'étaient ainsi accumulées, pour 364 Mo. Le script trouve le
détenteur du port par l'inode de sa socket d'écoute, puis escalade en `SIGKILL`
si l'arrêt gracieux traîne : uvicorn attend la fermeture des connexions, or les
flux d'événements restent ouverts par conception.

L'image du pod n'a pas de `node`. L'installation en pose un, épinglé, dans
`~/work/.tools`, et `~/work/bin/node` y mène : wikichat et les serveurs MCP en
JavaScript en dépendent.

---

## Documentation

| Document | Contenu |
|----------|---------|
| [`docs/installer.md`](docs/installer.md) | installer l'Atelier sur son propre pod SSPCloud |
| [`docs/atelier-mcp-unified.md`](docs/atelier-mcp-unified.md) | le registre MCP unifié : vision, trois niveaux de configuration, état et phasage |
| [`docs/atelier-mcp-implementation-plan.md`](docs/atelier-mcp-implementation-plan.md) | le détail opérationnel du phasage |
| [`docs/atelier-wikichat-alignment.md`](docs/atelier-wikichat-alignment.md) | l'articulation avec wikichat |
| [`docs/atelier-vscode-passage-de-main.md`](docs/atelier-vscode-passage-de-main.md) | comment une conversation s'ouvre dans VS Code, et pourquoi c'est indirect |
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | le design du shell unifié |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | le plan d'implémentation correspondant |

---

## Claude Code

Ce dépôt **ne distribue pas** Claude Code. Le CLI d'Anthropic est requis à
l'exécution et s'installe séparément ; son usage reste soumis aux conditions
d'Anthropic. L'inférence passe par la passerelle de modèles configurée via
`ANTHROPIC_BASE_URL`, et non par un compte partagé.

Le service vise **un pod par utilisateur**. Ce n'est pas un détail de
déploiement : il n'existe qu'une identité propriétaire, et elle ouvre tout. Le
jour d'une installation pour plusieurs personnes, chacune doit s'authentifier
avec ses propres identifiants, sans clé mutualisée derrière l'interface — rien
dans le code ne l'assure aujourd'hui. Voir [`SECURITY.md`](SECURITY.md).

---

## Licence

Apache-2.0, voir [`LICENSE`](LICENSE). Elle ne couvre que le code de ce dépôt.

---

## État

Le shell unifié, les conversations de projet, les connecteurs et les
compositions sont en service ; les vues Assistant et Agents existent, et
attendent un état des lieux mesuré avant qu'on les dise en service.

**Une conversation, une histoire.** L'Atelier et le CLI n'écrivent plus deux
cahiers : ce qui se dit dans VS Code apparaît en direct dans l'onglet, et
inversement. Le mode de permission et les connecteurs choisis pour un fil
valent des deux côtés.

**Un processus par conversation, gardé entre les tours.** Chaque tour repayait
près de quatre secondes de démarrage et de reconnexion des connecteurs, mesuré ;
le processus reste maintenant en vie, s'éteint après dix minutes de silence, et
l'on n'en garde que trois à la fois. Sa file de messages devient la nôtre.

**Une conversation demande l'autorisation avant d'agir**, quand son mode le
veut — `acceptEdits` par défaut : le CLI pose la question à l'Atelier plutôt
que de refuser, une carte s'affiche dans le fil, et le tour attend aussi
longtemps qu'il le faut. Une réponse peut valoir « toujours » pour ce fil, et
c'est le CLI qui l'applique, avec ses propres règles ; la liste des
conversations dit laquelle attend. L'agent peut aussi poser une vraie question à
choix, avec ses options et un champ libre.

On écrit pendant qu'un tour travaille : le message se met en file et part dans
le tour en cours dès qu'il a fini le précédent. Et l'on peut regarder une
conversation depuis plusieurs écrans — un second onglet, ou VS Code — sans la
déclencher. Le passage de main vers VS Code fonctionne dans les deux sens.

Un projet de code est un dépôt git dès sa création. La publication sur GitHub
existe côté service — `POST /v1/projects/{slug}/git/publish` —, projet par
projet et privée par défaut : ouvrir un projet est un geste de travail, le
publier en est un autre. Elle demande un jeton dans
`~/work/.secrets/github_token` et un `ATELIER_GITHUB_OWNER` ; sans eux le dépôt
reste local, et la route dit qu'elle ne peut rien faire. **L'interface ne
l'expose pas encore** : il n'y a pas de bouton, seulement l'API.

La suite de tests couvre les endroits où une régression serait silencieuse : la
garde du point d'entrée interne, ce que la sonde de vie consent à dire à un
inconnu, les autorisations et leurs règles, le journal unique, le processus
gardé (sur un faux CLI), les dépôts de projet, l'installation, et le rendu des
messages — celui-ci par un banc d'essai en JavaScript (`tests-js/`) que la
suite Python lance avec le `node` de la machine. Chaque correction est livrée
avec un test dont on a vérifié qu'il échoue sans elle.

```bash
cd atelier-src
pip install -e ".[dev]"
pytest
```

Le reste des mécanismes est validé à la main et par mesure sur le pod. Les
limites connues de chaque brique sont notées dans son document.
