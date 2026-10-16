# La passerelle de l'Atelier : configuration, usage, état réel

Relevé du 16/10/2026 : code (`mcp_gateway/`, `mcp/gateway.py`, `catalog.yaml`, `config.py`, `bundles.py`, `profiles.py`, `compositions/`, `upstream/pool.py`) et base `gateway.db` du pod, lue en lecture seule. Les valeurs secrètes ne sont pas reproduites ici.

## 1. Ce que c'est

Un moteur MCP **embarqué dans le processus de l'Atelier** (même application, port 8787). Il fait deux métiers que l'on confond souvent :

| Métier | Ce qu'il sert | Qui s'en sert |
|---|---|---|
| **La porte `/mcp` de l'Atelier** | les outils `atelier_*` (le catalogue de commandes : classes, aperçu, jeton, journal) | tous les agents, par un profil (`code` : 11 outils, `assistant` : 43 + 7) |
| **L'agrégateur du pool** | chercher et appeler les outils des connecteurs (`gateway_find_tools`, `gateway_call_tool`), lancer des compositions (`gateway_run_composition`, `composition_*`) | l'Assistant et les clients distants |

## 2. Comment elle se configure

| Couche | Où | Contenu aujourd'hui |
|---|---|---|
| Environnement `GATEWAY_*` | `mcp_gateway/config.py` (pydantic) | base (`db_path`), catalogue (`catalog_path`), `host_url`, `owner_lock`, `owner_key`, jetons amont hérités (`bearer_compute`, `_qgis`, `_llm`, `_ceremadoc`), `upstream_probe_on_startup`, `mcp_default_bundle`, `gitlab_catalog_*`, `grist_sync_enabled` |
| Catalogue | `mcp/catalog.yaml` | **un seul bundle**, `tout`, en mode `discover` : l'agent ne voit que les méta-outils (7) et les compositions promues ; `enforce_envelope: false` ; aucun serveur déclaré |
| Pool des connecteurs | `gateway.db` : `server_enabled` (15 lignes), table du registre, `sidecars` (12 lignes) | 12 connecteurs avec outils en cache : QGIS 57, wikichat 53, GitHub 46, Blender 45, Grist 35, Onyxia 24, Chrome 24, n8n 24, filesystem 14, LLM 12, data.gouv 10, GitLab 9 — soit **353 outils** |
| Profils de passerelle | `profiles.py` : org (issus des bundles), perso (`user_profiles`) | 0 profil perso |
| Compositions | `compositions` + `composition_runs` | 3 (2 en production : `memo_branche_preferee`, `relancer_la_veille` ; 1 temporaire), **12 exécutions dont 8 en échec** |
| Accès distant | OAuth (`oauth_clients`, `oauth_tokens`) | 6 clients enregistrés (Claude × 4, Codex × 2), 4 jetons, validité d'environ 90 jours, portée `mcp` |
| Identifiants amont | table `server_credentials` | **vide** : les secrets sont dans la configuration inline de chaque connecteur |
| Notifications | clés VAPID dans `gateway_meta` | présentes |
| Trace | `audit_log`, `tool_pins` | 27 événements, **le dernier date du 30/08** ; `tool_pins` : 0 ligne, donc aucun usage compté |

## 3. Comment elle est utilisée (mesuré)

- **Le journal unique** (2 057 événements depuis septembre) ne contient aucun appel de pool par `gateway_call_tool` : les seules mentions de `gateway_*` sont celles du contrôle de cohérence. Les commandes `atelier_*` y sont (par exemple 170 `atelier_lancer_agent`).
- **Les agents de projet n'ont pas les méta-outils** (profil `code`) et joignent les connecteurs **directement** : le pool de la passerelle n'est pas leur chemin. Seuls l'Assistant et les clients distants peuvent passer par `find_tools` / `call_tool`.
- **Clients distants** : 12 des 27 agents lancés l'ont été par un `client-distant`. D'après le code, un client OAuth, qui n'a pas de conversation, reçoit la même surface que l'appel mesuré sans conversation avec la clé du propriétaire (57 outils, `lancer_agent` et `agent_creer` compris) ; les commandes engageantes demandent un aperçu et un jeton. Non mesuré avec un vrai jeton OAuth.
- **Compositions** : activité du 29 au 30/08 uniquement.
- **Sondes** : `n8n` répond 401 depuis le 26/09, `github` depuis le 07/10. Aucune alerte de santé ne le dit à la personne.

## 4. Constats

1. **La moitié « agrégateur » est quasi dormante.** Pas d'usage compté, pas de trace, compositions inactives depuis six semaines (8 exécutions sur 12 en échec), alors que la moitié « porte de l'Atelier » est le cœur du système.
2. **Le pool est déclaré deux fois** (registre et `sidecars`, même 12 services) et porte des restes : des drapeaux `server_enabled` sans outils pour `atelier`, `webtools` et `GitLab` (en double de `gitlab`).
3. **Le catalogue ne correspond plus à ses textes.** Les méta-outils décrivent des profils « lecture, etude_territoire, terrain, ops, createur, tout » ; le catalogue n'en contient qu'un. Un agent qui appelle `gateway_list_bundles` ou `gateway_use_bundle` reçoit une description qui promet ce qui n'existe pas.
4. **De la configuration héritée du produit autonome** (`GATEWAY_BEARER_*`, `gitlab_catalog_*`, `grist_sync_*`, une clé de propriétaire propre à la passerelle) que l'Atelier n'emploie pas.
5. **Aucun rôle sur les clients distants.** Un jeton OAuth donne la surface « sans conversation » ; il n'y a ni profil par client, ni révocation visible, ni durée courte.
6. **Les identifiants amont ne passent pas par le magasin prévu.** `server_credentials` est vide ; les secrets sont inline dans la configuration des connecteurs, d'où ils sont copiés dans `claude-env.sh` pour tous les agents (voir [`distribution-des-acces.md`](distribution-des-acces.md) §7).
7. **Les appels du pool ne sont pas tracés.** Ni le journal unique, ni `audit_log`, ni `tool_pins` ne les reçoivent : impossible de dire quel outil sert, ni de décider quoi garder.
8. **La recherche d'outil reste fragile** : la mesure du 25/09 donnait 6 réussites sur 9 pour « chercher puis appeler », dont deux échecs dangereux (réponse de mémoire avec détail inventé, appel sous un nom non déclaré) (`architecture-transverse.md` §1.5).

## 5. Ce qu'elle devrait être

1. **Une seule mission pour la partie pool : la médiation.** Les services à jeton puissant passent par un mandataire de la passerelle (patron d'Onyxia) au lieu d'être joints en direct : c'est le seul endroit où l'on peut borner, classer, tracer.
2. **Une surface par acteur, lue dans la matrice** ([`acteurs-et-acces.md`](acteurs-et-acces.md) §8), appliquée à `tools/list` comme à l'appel, y compris pour les **clients OAuth** (profil par client, durée courte, révocation visible dans l'Atelier).
3. **Un registre unique** : retirer `sidecars` en double et les drapeaux orphelins ; mettre les secrets dans `server_credentials` ou dans les secrets du pod, jamais inline.
4. **Un catalogue qui dit vrai** : soit des profils réels, soit retirer `gateway_list_bundles` / `gateway_use_bundle` du profil de l'Assistant.
5. **Tracer tout appel d'outil** dans le journal unique (acteur, origine, durée, résultat), et compter l'usage : c'est la donnée qui permet d'élaguer.
6. **Alerter sur les connecteurs refusés** (401 depuis N jours) dans l'Atelier, pas seulement les retirer en silence.
7. **Nettoyer le produit autonome** : jetons `GATEWAY_BEARER_*`, clé de propriétaire de la passerelle, synchronisation GitLab/Grist, après vérification qu'aucun usage ne subsiste.
8. **Compositions** : elles restent distinctes de n8n et doivent fonctionner parfaitement pour les agents (voir §6 : ce n'est pas le cas aujourd'hui).

## 6. Épreuve réelle des compositions (16/10/2026)

Les compositions et n8n sont deux choses distinctes. Une **composition** est une chaîne d'appels d'outils MCP, synchrone, lancée par un agent ou une personne, qui s'exécute dans la passerelle et devient un outil (`composition_*`) quand la personne l'active. Un **workflow n8n** est une automatisation externe, déclenchée par des événements ou des horaires, qui tient ses propres identifiants ([`n8n.md`](n8n.md)). Elles se complètent : une composition peut appeler un outil n8n, un workflow n8n peut appeler un outil de la passerelle.

Essai fait dans le pod, par la vraie porte `/mcp`, en tant qu'Assistant, avec des compositions temporaires supprimées ensuite (les essais ont ajouté 15 lignes à `audit_log`).

### Ce qui marche

| Essai | Résultat |
|---|---|
| Enregistrer un enchaînement (`gateway_save_composition`), le lancer, lire son statut | oui, 0,1 à 0,3 s ; entrées déduites des `${input.x}` |
| Étape locale (`atelier_artefacts`, `atelier_projets`) | oui |
| Étape d'approbation : suspendre, puis reprendre par `gateway_resume_composition` | oui, l'étape suivante s'exécute après la reprise |
| Historique des exécutions, suppression (les exécutions partent avec elle) | oui |
| Profil `code` : voir ou appeler `composition_*` et `gateway_run_composition` | refusé, avec un message clair (voulu) |
| Garde de profil dans une étape | l'étape s'exécute sous le profil de l'appelant (corrigé précédemment) |

### Ce qui ne marche pas (mesuré)

1. **Les entrées ne sont pas vérifiées.** Une entrée requise absente ne bloque rien : l'étape part avec une valeur vide. Essai : `atelier_artefacts` lancé sans `projet` a rendu **`completed`** avec la liste de tous les projets, alors que l'entrée était requise. Un nombre à la place d'une chaîne produit une `AttributeError` de l'outil. C'est la cause des échecs du 30/08 (entrées mal nommées passées par un agent, erreurs remontées par l'amont). Le code ne valide `input_schema` nulle part au moment du lancement (`service.execute`).
2. **Les appels du pool par la passerelle échouent pour la plupart des connecteurs.** Un outil de lecture par connecteur, appelé par `gateway_call_tool` :

   | Connecteur | Résultat | Cause |
   |---|---|---|
   | chrome-devtools, wikichat | ok | — |
   | LLM | répond, mais `health` dit `ok: false, api_key_source: missing` | clé du service LLM absente |
   | QGIS, Blender | **400 Bad Request** | **session conservée par le pool et périmée** : avec une session neuve, les deux services répondent 200 et rendent de vraies données. `_streamable_call` n'a pas de réouverture (celle de `call_tool` ne couvre que le mode SSE) |
   | data.gouv | « All connection attempts failed » | le pod ne se connecte pas à `mcp.data.gouv.fr` (`curl` : code 7) alors que le pool l'affiche « connected » |
   | filesystem, GitLab, n8n | non exposés | ponts `stdio-local`, que la passerelle ne lance pas |
   | GitHub | non exposé | 401 depuis le 07/10 |
   | Onyxia | non exposé | volontaire : l'Assistant passe par `/mcp/onyxia` |

   Une composition dont une étape vise QGIS, Blender, data.gouv ou n8n échoue donc, quel que soit son contenu. Le statut « connected » du pool ne dit rien de l'état réel.
3. **Les compositions enregistrées par un agent ne peuvent pas devenir des outils.** `gateway_save_composition` demande un « nom lisible, en langage courant » et le range tel quel ; la promotion exige un identifiant `^[a-zA-Z][a-zA-Z0-9_]*$` et répond **400** (« Nom : identifiant alphanumérique »). Le chemin de l'écran, lui, convertit le nom (`_slug_composition`) ; celui de l'agent non.
4. **Les deux compositions en production ne sont pas des workflows** : un seul appel chacune (`wikichat__remember`, `wikichat__fire_trigger`), avec l'identifiant d'un déclencheur écrit en dur pour la seconde.
5. **Les agents de projet n'y ont pas accès.** Le profil `code` ne reçoit ni `composition_*` ni les méta-outils. « Pour les agents » veut dire aujourd'hui : l'Assistant et les clients distants.
6. **Peu de moteur.** Types d'étapes : `tool`, `elicit`, `approval`, `wait_until`. Ni condition, ni boucle, ni reprise sur erreur (sauf `optional`), ni délai par étape actif (`timeout_seconds` est à `null`), entrées toutes en chaîne.
7. **Aucun test.** Aucun fichier de `tests/` n'importe le moteur (`compositions/executor.py`, `service.py`).
8. **Aucune trace utile.** Pas de ligne dans le journal unique, `tool_pins` à zéro ; `audit_log` ne reçoit que les créations et lancements.

### Pour qu'elles fonctionnent « parfaitement pour les agents »

| # | Correctif | Effet |
|---|---|---|
| C1 | **Valider les entrées au lancement** (requises, type, valeurs permises) et refuser avec un message qui nomme l'entrée | fin des succès à vide, et de l'erreur d'un agent qui devine les noms |
| C2 | **Rouvrir la session d'un amont HTTP** sur 400 / 404 / fermeture, rejouer une fois ; sonde périodique et état réel (pas « connected » pour toujours) | QGIS et Blender redeviennent appelables ; alerte si un amont reste injoignable |
| C3 | **Normaliser le nom** à l'enregistrement par un agent (titre lisible conservé à part) | une composition sauvée peut être activée |
| C4 | **Exposer aux agents de projet** les compositions déclarées pour leur projet (famille `composition_*` bornée), comme pour n8n | un agent de projet rejoue ses enchaînements |
| C5 | **Étapes utiles** : condition, reprise sur erreur, délai par étape, entrées typées, résultat nommé | de vrais enchaînements |
| C6 | **Vérifier avant d'annoncer** : lancement à blanc (outils joignables, entrées satisfaites) avant d'activer | on ne promeut pas ce qui échouera |
| C7 | **Tests de bout en bout** avec un faux amont : lancement, suspension, reprise, entrée absente, amont tombé, session périmée | le comportement tient |
| C8 | **Tracer chaque lancement et chaque étape** dans le journal unique (acteur, origine, durée, résultat) | on sait ce qui sert |
