# Atelier

Un hub qui fait travailler Claude Code sur un pod SSPCloud : conversations de
projet, agents, connecteurs MCP, et une face VS Code intégrée. Tout tourne sur le
pod `proj-claude-code` d'Onyxia ; ce dépôt en porte le code et la documentation.

Interface : `https://user-nic01asfr-proj-claude-code.user.lab.sspcloud.fr/`

---

## Ce que ça contient

| Chemin | Rôle |
|--------|------|
| `atelier-src/mcp_gateway/atelier/` | le service : API FastAPI, registre de sessions, harnais `claude`, passerelle MCP |
| `atelier-src/mcp_gateway/atelier/web/` | l'interface, JavaScript sans cadre applicatif |
| `atelier-src/vscode-extension/` | la petite extension qui ouvre Claude Code sur la bonne conversation |
| `wikichat-atelier/` | le pilote wikichat déployé avec le service |
| `deploy-patches/deploy_agent_ui.py` | le déploiement vers le pod |
| `docs/` | cadrage, plans, mécanismes |

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

## Déploiement

Le service tourne sur le pod, pas en local. Le déploiement passe par le MCP
Onyxia :

```
python deploy-patches/deploy_agent_ui.py
```

Le script copie les fichiers listés en tête (`FILES`, `HORS_ARBRE`), puis
contrôle à l'arrivée que quelques marqueurs des derniers correctifs sont bien
présents. Les modules Python demandent un redémarrage du service pour prendre
effet ; les fichiers de l'interface, non.

La clé propriétaire (`atelier_owner_key`) ne transite jamais par le dépôt ni par
les fichiers de projet : elle vit dans `~/work/.secrets/` sur le pod, et n'est
transmise au processus `claude` que par son environnement.

---

## Documentation

| Document | Contenu |
|----------|---------|
| [`docs/atelier-mcp-unified.md`](docs/atelier-mcp-unified.md) | le registre MCP unifié : vision, trois niveaux de configuration, état et phasage |
| [`docs/atelier-mcp-implementation-plan.md`](docs/atelier-mcp-implementation-plan.md) | le détail opérationnel du phasage |
| [`docs/atelier-wikichat-alignment.md`](docs/atelier-wikichat-alignment.md) | l'articulation avec wikichat |
| [`docs/atelier-vscode-passage-de-main.md`](docs/atelier-vscode-passage-de-main.md) | comment une conversation s'ouvre dans VS Code, et pourquoi c'est indirect |
| [`docs/superpowers/specs/`](docs/superpowers/specs/) | le design du shell unifié |
| [`docs/superpowers/plans/`](docs/superpowers/plans/) | le plan d'implémentation correspondant |

---

## État

Le shell unifié, les conversations de projet, les agents, les connecteurs et les
compositions sont en service. Le passage de main vers VS Code fonctionne dans les
deux sens : une conversation de l'Atelier s'ouvre dans l'extension Claude Code,
et une conversation ouverte depuis l'extension remonte comme session du projet.

Il n'y a pas de tests automatisés : les mécanismes sont validés à la main et par
mesure sur le pod. Les limites connues de chaque brique sont notées dans son
document.
