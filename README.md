# Atelier

[![Helm chart](https://img.shields.io/badge/dynamic/yaml?url=https%3A%2F%2Fnic01asfr.github.io%2Fatelier-sspcloud%2Findex.yaml&query=%24.entries.atelier%5B0%5D.version&label=Helm%20chart&logo=helm)](https://nic01asfr.github.io/atelier-sspcloud/index.yaml) [![Licence Apache 2.0](https://img.shields.io/badge/licence-Apache%202.0-blue)](LICENSE) [![Vitrine FR](https://img.shields.io/badge/vitrine-FR-0063cb)](https://nic01asfr.github.io/atelier-sspcloud/) [![Showcase EN](https://img.shields.io/badge/showcase-EN-0063cb)](https://nic01asfr.github.io/atelier-sspcloud/en/)

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

Le reste de `deploy-patches/` n'est pas suivi : ce sont des fichiers de travail
d'anciennes sessions de déploiement.

---

## Ce qu'on y fait

Le guide de référence, fonctionnalité par fonctionnalité (à quoi elle sert,
comment s'en servir pour la personne et pour un agent, ce qu'elle ne fait
pas, où est le code) : **[`docs/fonctionnalites.md`](docs/fonctionnalites.md)**.
En résumé :

- **Projets et conversations** : un projet est un dépôt git sous
  `~/work/projects/` ; une conversation y fait travailler un agent Claude
  Code, la même dans l'interface, dans VS Code et au terminal, avec les
  mêmes outils et le même mode de travail (Plan, Demande, Édite, Sans
  garde-fou).
- **L'Assistant** : la porte d'entrée. Il lit la carte de l'Atelier, règle
  ses objets par les commandes (cartes d'action avec « Annuler »), et confie
  le travail dans les projets à des agents code.
- **Commandes, « À valider », journal** : un seul catalogue de commandes,
  chacune avec sa classe (lecture, réversible, engageante, réservée) et son
  inverse ; une seule file de ce qui attend l'accord de la personne ; un seul
  journal de qui a fait quoi.
- **Créations et panneau** : ce qu'un agent fabrique (pages ou applications)
  est servi par l'hôte des applications, derrière la connexion de l'Atelier,
  et s'ouvre dans le panneau à côté du fil ; les bureaux du namespace (QGIS,
  Blender, n8n) y sont relayés.
- **Navigateur de l'agent** : un Chrome par conversation, que la personne
  regarde en direct et dont elle peut prendre la main.
- **Connecteurs** : un pool de serveurs MCP, choisis projet par projet, secrets
  par référence ; l'Atelier se branche aussi comme connecteur dans claude.ai.
- **wikichat** : coordination entre agents, connaissance, cartographie des
  projets, agents planifiés ; leurs lancements passent par l'Atelier.
- **Mémoire** : fiches de chaque conversation, retrouvées par
  `atelier_rappel` ; « Ma mémoire » pour ce que l'Atelier retient de la
  personne, qui n'y entre qu'avec son accord.
- **Gardiens** : contrôles de santé et de sécurité en code, sans modèle, dans
  la vue Agents ; réparations proposées sur une branche, fusionnées par la
  personne.
- **Profils d'accès** : un agent code ne reçoit que les outils de son projet
  (et Onyxia seulement pour le pod que son projet déclare) ; l'Assistant
  reçoit tout, par ses méta-outils.

Les vues de l'interface (Code, Assistant, Connecteurs, Agents, À valider,
Journal, Ma mémoire) sont en cours de reprise : leurs noms peuvent changer.
Ce que les agents doivent savoir tient dans le socle de leurs consignes,
[`atelier-src/mcp_gateway/atelier/consignes/socle.md`](atelier-src/mcp_gateway/atelier/consignes/socle.md).

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
| [`docs/fonctionnalites.md`](docs/fonctionnalites.md) | **le guide de référence** : chaque fonctionnalité, ses usages, son code, sa doc |
| [`docs/installer.md`](docs/installer.md) | installer l'Atelier sur son propre pod SSPCloud |
| [`docs/consignes/`](docs/consignes/README.md) | les consignes des agents : le socle commun et celles de projets précis |
| [`docs/vision/`](docs/vision/) | la vision, l'architecture transverse, les décisions, le plan par vagues et son suivi |
| [`docs/structure-projet.md`](docs/structure-projet.md) | la structure type d'un projet et sa migration |
| [`docs/atelier-applications.md`](docs/atelier-applications.md) | les créations : hôte des applications, supervision, mandataire |
| [`docs/navigateur-atelier.md`](docs/navigateur-atelier.md) | le navigateur des agents, l'écran en direct, « Prendre la main » |
| [`docs/onyxia-projet.md`](docs/onyxia-projet.md) | Onyxia lié au déploiement d'un projet |
| [`docs/atelier-mcp-unified.md`](docs/atelier-mcp-unified.md) | le registre MCP unifié : vision, trois niveaux de configuration, état et phasage |
| [`docs/atelier-mcp-implementation-plan.md`](docs/atelier-mcp-implementation-plan.md) | le détail opérationnel du phasage |
| [`docs/atelier-mcp-distant.md`](docs/atelier-mcp-distant.md) | l'Atelier comme connecteur MCP d'un client distant |
| [`docs/atelier-wikichat-alignment.md`](docs/atelier-wikichat-alignment.md) | l'articulation avec wikichat |
| [`docs/atelier-vscode-passage-de-main.md`](docs/atelier-vscode-passage-de-main.md) | comment une conversation s'ouvre dans VS Code, et pourquoi c'est indirect |
| [`docs/coherence-projet.md`](docs/coherence-projet.md) | la cohérence entre surfaces et les déploiements |
| [`docs/archives/`](docs/archives/README.md) | traces de travail rangées : premier shell, premières captures |

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

Les vagues 1 et 2 de la vision sont déployées et vérifiées sur le pod
(commandes, journal, « À valider », gardiens, vue Agents, carte, bureaux
relayés, cohérence des surfaces sans écart) ; la vague 3 (Assistant,
navigateur en direct, mémoire) est intégrée et en essai. Le suivi est dans
[`docs/vision/plan-implementation.md`](docs/vision/plan-implementation.md)
§5, le détail par fonctionnalité dans
[`docs/fonctionnalites.md`](docs/fonctionnalites.md).

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
