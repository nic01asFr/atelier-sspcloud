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

## Ce que l'Atelier doit savoir faire avant (lu dans le code, 16/10)

Ces manques ne sont pas propres à n8n : n8n les rend seulement visibles. Les combler d'abord évite d'écrire n8n « en copie » d'Onyxia.

| # | Manque | Constat | À faire |
|---|---|---|---|
| A1 | **Un mandataire de connecteur borné, générique** | `onyxia_projet.py` (1050 lignes) porte à la fois le moule (outils visibles, arguments imposés, refus, session, mutisme) et le métier d'Onyxia. `mcp_sync.py` a des cas à part (`est_onyxia`, `_est_onyxia_direct`, `onyxia_pour_projet`) dans une dizaine d'endroits | extraire le moule (`Borne`, `Regle`, `filtrer_appel`, `outils_visibles`, rejeu) ; chaque connecteur borné fournit `pour_projet(settings, slug, profil)` ; `mcp_sync` n'appelle plus que ce registre |
| A2 | **Une vue de service que l'agent peut montrer, à une page donnée** | `panneau.descripteur` ne connaît que le genre `creation` (projet + nom) ; `atelier_montrer` ne montre donc qu'une création. Les services (bureaux, éditeur) ne s'ouvrent que sur un geste, par le catalogue `/v1/bureaux` (J-f) | genre `service` (connecteur, vue, chemin validé) ; `atelier_montrer` l'accepte, y compris pour l'Assistant ; épinglage au projet. J-f vise les **flux** vivants : un éditeur n'en est pas un et peut s'ouvrir seul |
| A3 | **Un bloc de projet générique** | `projet.json` porte `deploiement` (Onyxia) avec sa commande de déclaration. Un second bloc `automatisations` copierait structure, aperçu, annulation, contexte | une famille « services du projet » : même schéma de déclaration, même commande engageante, même ligne de contexte |
| A4 | **Classer les outils d'un connecteur tiers** | la classe `lecture` / `engageante` n'existe que pour les commandes `atelier_*`. Un outil n8n qui active ou supprime n'est classé nulle part | classe dérivée des annotations MCP (`readOnlyHint`, `destructiveHint`) ou d'une table par connecteur ; le mandataire rend l'aperçu et le jeton de confirmation déjà en place |
| A5 | **Une surface d'outils stable** | un agent ne reçoit ses outils d'un connecteur qu'à son lancement (constaté pour Onyxia). Des outils qui apparaissent quand un workflow est publié ne lui parviennent pas | commencer par deux outils fixes (`n8n_outils`, `n8n_appeler`) ; les outils nommés viendront avec `tools/list_changed`, si les clients le suivent (à mesurer) |
| A6 | **Un chemin d'entrée pour les événements** | n8n doit pouvoir dire « ce workflow a échoué » ou « validez ceci ». Rien n'accepte aujourd'hui d'événement externe signé vers un fil ou « À valider » | endpoint entrant à jeton de service (un secret de l'hôte des applications), qui écrit dans `événements`, « À valider » ou `rappel` ; comptage par origine (`X-Atelier-Origine`, T18) |
| A7 | **Des garde-fous contre les boucles** | n8n peut lancer un agent, qui peut créer un workflow, qui peut lancer un agent | profondeur de lancement portée par l'en-tête d'origine ; plafonds et budgets (J-b) comptés par origine ; refus au-delà d'une profondeur |
| A8 | **Sondes et gardiens génériques** | la sonde `initialize` des ponts stdio a retiré n8n quand il répondait 401 ; aucune ne dit « jeton refusé » à la personne | sonde HTTP commune à tout connecteur ; alerte lisible dans l'Atelier ; jeton jamais en `args` (déjà couvert par `mcp_secrets`) |
| A9 | **Édition concurrente** | une personne édite dans l'éditeur pendant que l'agent modifie par l'API : le dernier enregistrement gagne (à vérifier sur 2.38.6) | l'agent travaille sur un workflow `brouillon` qu'il ne touche plus quand la vue est ouverte dessus ; la vue se recharge après une écriture de l'agent, avec le liseré « l'agent agit » |
| A10 | **Honnêteté de la documentation** | `site/vitrine.json` et `docs/fonctionnalites.md` annoncent que n8n s'ouvre dans le panneau : ce n'est pas vrai aujourd'hui | corriger les deux textes tant que la vue n'est pas posée |

Autres points à garder en tête :

- **Coût en jetons.** `n8n-mcp` expose des dizaines d'outils et la documentation de centaines de nœuds : l'agent d'un projet n'en reçoit que ce qui construit ses workflows (`outils_visibles` sait déjà filtrer).
- **Vérifier avant d'annoncer.** Comme `atelier_artefact_verifier` pour une page, un `n8n_verifier` (exécution à blanc, nœuds sans identifiants, déclencheur joignable) avant que l'agent dise « c'est prêt ».
- **Catalogue de la passerelle.** `gateway_find_tools` ne contient ni n8n ni gitlab (ponts stdio) ; un n8n en HTTP direct y entrera, ce qui change ce que voient les profils.
- **Production.** Le correctif du sous-protocole du noyau Jupyter et l'alias court du pod GPU ne sont que dans l'image de développement : à reporter avant de compter sur le chemin « agent → Onyxia » en production.
- **Tests.** Le service factice de `tests/test_bureaux.py` sert de modèle pour un faux n8n (API, étiquettes, webhook) : le prévoir dès A1.

## Étapes

0. **Socle** : A1 (moule générique), A2 (vue de service montrable), A3 (bloc générique), A4 (classes), A10 (textes). Chacune est utile sans n8n : Blender et QGIS en profitent.
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
