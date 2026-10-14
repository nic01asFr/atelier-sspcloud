# n8n dans l'Atelier : les automatisations d'un projet

Statut : **proposition** (14/10/2026). Rien n'est posé sur le pod ; ce qui est dit « mesuré » l'a été en lecture seule le même jour.

## Ce que l'on veut

n8n est le lieu où l'on construit les automatisations de Nicolas (webhooks, planifications, connecteurs d'API). L'Atelier doit le traiter comme il traite Onyxia : **un service que l'agent d'un projet opère, borné à ce projet, sans consigne à lui donner**, avec une fenêtre pertinente dans le panneau, et l'Assistant qui voit l'ensemble.

Deux sens, qui se tiennent :

- **n8n appelle l'Atelier et la passerelle** : un workflow peut utiliser les outils de la passerelle, lancer un agent, déposer une question dans « À valider ».
- **L'Atelier opère n8n** : il range les workflows par projet (étiquettes), expose à chaque projet ses outils, et montre le bon écran.

## Mesuré sur le pod

| Fait | Conséquence |
|---|---|
| n8n 2.38.6 embarque les nœuds **MCP Client**, **MCP Client Tool**, **MCP Trigger** et un module `mcp` d'instance | n8n sait appeler la passerelle et l'Atelier **sans nœud sur mesure** ; il peut aussi se publier comme serveur MCP |
| Aucune fonction « enterprise » (ni projets, ni droits fins, ni SSO) | **Les étiquettes sont le seul rangement par projet** ; la frontière d'isolation est le mandataire de l'Atelier, pas n8n |
| `N8N_UNVERIFIED_PACKAGES_ENABLED=false` | un paquet communautaire maison (`n8n-nodes-atelier`) est refusé tant qu'on ne l'ouvre pas : décision de sécurité, pas un détail |
| Pas de `N8N_PATH` ; l'éditeur envoie `X-Frame-Options: SAMEORIGIN` | pas de vue dans le panneau (voir `panneau.md`, J-d) |
| Le connecteur `n8n` du pool est un pont `mcp-remote` à jeton dans `args`, et répond **401** (adresse publique comme `http://n8n:3000/mcp`) | aucun agent n'a d'outil n8n aujourd'hui ; défaut M5 de l'audit du 25/09, jamais réglé |

## Architecture

```
 Assistant ─┐                          ┌─ n8n :5678  éditeur + API (clé de service, côté serveur)
 agent projet ─ /mcp/n8n/projet/<slug> ─ mandataire Atelier ─┤  n8n-mcp :3000 (outils de construction)
 (borné)    ┘   /mcp/n8n  (Assistant)  │                     └─ webhooks / MCP Trigger (outils exposés)
                                        ▲
 panneau (vue « editeur ») ── hôte des applications ── relais /_services/n8n/editeur/ ──┘
 workflows ── nœuds MCP Client ──► passerelle /mcp   et   Atelier /mcp
```

### 1. Les étiquettes comme appartenance

Convention, posée par l'Atelier seul (un agent ne crée ni ne retire ces étiquettes) :

| Étiquette | Sens |
|---|---|
| `projet:<slug>` | le workflow appartient à ce projet |
| `outil` | le workflow est exposé comme outil aux agents de son projet |
| `brouillon` | créé par un agent, jamais activé ; seule une personne l'active |
| `commun` | visible de tous les projets (lecture et appel, pas de modification) |

Un workflow sans `projet:…` n'appartient à personne : seuls Nicolas et l'Assistant le voient. Le projet déclare ce qu'il possède dans `.atelier/projet.json` (bloc `automatisations`, sur le modèle de `deploiement` d'Onyxia), par une commande engageante avec aperçu et « Annuler ».

### 2. Un mandataire, deux profils (même moule que `onyxia_projet.py`)

- `/mcp/n8n/projet/<slug>` — l'agent d'un projet. Outils de construction bornés : liste et lecture des workflows **de son étiquette**, création (l'étiquette `projet:<slug>` et `brouillon` sont imposées), modification et test de ses workflows, lecture de leurs exécutions. Jamais d'activation, de suppression, ni de lecture des identifiants. Sur tout appel portant un identifiant de workflow, le mandataire lit d'abord ses étiquettes et refuse si `projet:<slug>` n'y est pas.
- `/mcp/n8n` — l'Assistant. Tout voir, ranger (poser ou changer l'étiquette d'un projet), lire les échecs récents. Activer, désactiver et supprimer sont des **commandes engageantes**.
- La clé de l'API n8n et le jeton de `n8n-mcp` restent dans le mandataire. Les agents n'en voient jamais la valeur (même règle que le jeton des bureaux).

### 3. Les outils spécifiques d'un projet

Les workflows `outil` d'un projet sont publiés comme outils MCP de **ce projet seulement**, par le même mandataire :

- le nom, la description et les paramètres viennent du workflow (nœud de déclenchement + note d'en-tête, convention fixée dans le guide du projet) ;
- l'appel passe par le webhook ou le MCP Trigger du workflow, avec un secret de service que l'agent ne voit pas ;
- l'outil est de classe **lecture** si le workflow est marqué ainsi, **engageante** sinon (aperçu, jeton, « Annuler » quand c'est possible) — l'Atelier classe déjà ses commandes de cette façon.

On n'emploie pas l'accès MCP d'instance de n8n pour cela : il ne connaît pas les projets. Il reste utile à Nicolas pour un client externe.

### 4. n8n qui appelle l'Atelier et la passerelle

Sans nœud sur mesure : le nœud **MCP Client** de n8n pointe sur `/mcp` de la passerelle (tous les connecteurs, dont QGIS, Blender, data.gouv) et sur l'Atelier. Un workflow peut ainsi :

- appeler un outil de la passerelle ;
- **déposer une demande dans « À valider »** et attendre la réponse (nœud *Wait* + rappel), pour que l'humain reste dans la boucle ;
- lancer un agent, sous les plafonds, budgets et la porte dormante (J-b, J-c) ;
- poser une alerte dans le fil d'un projet.

Un paquet `n8n-nodes-atelier` (identifiants typés, actions nommées en français) viendrait **plus tard, et seulement si** l'usage montre que MCP Client ne suffit pas : il suppose d'ouvrir les paquets non vérifiés.

### 5. La fenêtre pertinente dans le panneau

Une vue `application` sur `/_services/n8n/editeur/` (J-d), qui s'ouvre **à la bonne page** selon le contexte :

| Quand | Page |
|---|---|
| l'agent vient de créer ou modifier un workflow | `workflow/<id>` |
| la personne ouvre « Automatisations » d'un projet | la liste filtrée sur `projet:<slug>` |
| un workflow a échoué | ses exécutions (`workflow/<id>/executions`) |
| l'Assistant fait le point | la liste complète, ou les échecs récents |

`atelier_montrer` accepte une cible n8n (workflow, liste, exécutions) ; l'adresse est construite par l'Atelier, jamais par l'agent. Prérequis : `N8N_PATH`, et une connexion à l'éditeur (n8n n'a pas de SSO ; connexion unique dans la vue, le cookie reste côté hôte des applications).

### 6. L'Assistant

Il gère sans entrer dans un projet : « quelles automatisations tournent, lesquelles échouent, à quel projet appartient celle-ci », rangement par étiquette, activation et arrêt (engageants), et ouverture de la vue. Le contexte d'un projet (`project_context.py`) dit à son agent, en quelques lignes, ce qu'il possède, comment l'étiquette fonctionne, et que l'activation passe par la personne.

## Sécurité

- Étiquettes imposées et vérifiées **côté serveur** ; jamais acceptées de l'agent.
- Jamais d'identifiants n8n lus par un agent ; l'exécution d'un workflow utilise ceux que n8n détient.
- Un workflow créé par un agent naît **inactif** (`brouillon`).
- Le jeton quitte `args` : en-tête du pool ou secret du pod, sondé comme les autres connecteurs.
- Les webhooks de n8n déclenchés de l'extérieur sont exposés par l'Ingress de n8n ; après `N8N_PATH` leur adresse change et le portail Grist doit suivre.

## Étapes

1. **Réparer** : jeton lu dans le Deployment, entrée HTTP directe avec `headers` + secret, rotation. *(sans effet visible pour les utilisateurs)*
2. **Voir** : `N8N_PATH`, vue `editeur`, connexion unique ; vérifier le WebSocket `push`. *(déplace l'adresse publique)*
3. **Ranger et borner** : étiquettes, mandataire `n8n_projet.py`, bloc `automatisations`, contexte du projet, commandes de l'Assistant.
4. **Publier des outils** : workflows `outil` → outils d'un projet.
5. **Boucler** : n8n → Atelier par MCP Client (« À valider », lancement d'agent).
6. **Ouvrir à la bonne page** : cibles de `atelier_montrer`.

## Questions pour Nicolas

- `N8N_PATH` déplace l'adresse publique de n8n et celle de ses webhooks : maintenant, ou après l'étape 1 ?
- Ouvrir les paquets non vérifiés pour un jour avoir des nœuds maison, ou rester sur MCP Client ?
- Les workflows `commun` : lecture seule pour tous les projets, ou rien de partagé au départ ?
