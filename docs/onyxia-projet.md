# Onyxia, lié au déploiement d'un projet

Lot « profils », équipe O, 26/09/2026. Ce document applique la section « Onyxia : lié au
déploiement d'un projet » de `docs/vision/profils-acces.md` et corrige l'écart G3 de
`docs/archives/chantiers/coherence-outils-audit.md`.

## 1. Le serveur Onyxia

### D'où il vient

- **Entrée du pool** : `Onyxia` dans `~/work/mcp/gateway.db` (table `sidecars`), préfixe
  `onyxia`, transport `streamable-http`, adresse
  `https://user-<idep>-passerelle-mcp.user.lab.sspcloud.fr/mcp`. Le jeton est dans les
  en-têtes de la déclaration ; il n'est reproduit nulle part ici.
- **Pod** : `passerelle-mcp-dev-jupyter-python-0`, un service Jupyter du namespace
  `user-<idep>`, exposé par l'ingress Onyxia. Le compte de service du pod de l'Atelier ne
  peut pas lire ses pods (`kubectl get pods` refusé) : son lancement exact n'est pas vérifié.
- **Code** : `sspcloud-mcp` 0.2.0 (`/health` le confirme), dépôt
  `github.com/nic01asFr/sspcloud-mcp` (avec un miroir GitLab). Le transport
  HTTP est `sspcloud_mcp/server_http.py` (bibliothèque standard, `ThreadingHTTPServer`) ; les
  outils sont dans `sspcloud_mcp/tools.py`.
- **Côté Atelier** : la passerelle s'y connecte une fois au démarrage (`upstream/pool.py`) et
  sert ses 24 outils sous `onyxia__*`. `mcp_sync.assurer_onyxia_natif` l'imposait en plus en
  natif à tout projet de code ; l'équipe S le retire.

### Ses outils

| Famille | Outils | Ce qui désigne la cible |
|---|---|---|
| Sessions | `session_start`, `session_status`, `session_stop` (`uninstall` supprime le pod) | `session_id`, `attach_pod`, `launch_chart` |
| Pod de projet | `project_bind`, `project_start` (lance un pod helm) | `pod`, `project` |
| Travail dans le pod | `exec`, `job_poll`, `read_file`, `write_file`, `list_files`, `push_repo`, `pull_artifact` | `session_id` |
| GPU | `gpu_status`, `gpu_switch` (préempte par défaut), `gpu_release` | `project`, `session_id` |
| Services | `service_scaffold`, `service_provision`, `service_deploy`, `service_status`, `service_stop`, `service_warm` | `yaml_path` |
| Exposition | `expose_public`, `unexpose_public` | `session_id`, `pod`, `name` |
| Inventaire | `list_pods` | `namespace` |

- **Les sessions sont globales** au serveur : tout client peut appeler `exec` sur n'importe quel
  `session_id`. Le serveur **ne sait pas filtrer par pod**.
- **`project_bind(pod, project)`** fait bien ce qu'on en attend : il appelle
  `session_start(attach_pod=pod)`, ouvre la session `proj-<project>` sur ce pod, avec le
  dossier `…/projects/<project>`. Un pod absent ou arrêté est refusé (`POD_UNREACHABLE`).

## 2. G3 : pourquoi le serveur « ne répond pas » à `initialized`

### Cause

Il répond, en 47 ms, mais **sans délimiter son corps vide**. Dans `server_http.py`,
`_send(202)` n'écrit `Content-Length` que si le corps est non vide. En HTTP/1.1 avec
connexion persistante, une réponse 202 sans `Content-Length` ni `Transfer-Encoding` se lit
jusqu'à la fermeture de la connexion, que le serveur ne ferme pas. L'ingress la relaie en
`Transfer-Encoding: chunked` et n'envoie jamais le dernier bloc. Le client de Claude Code lit
le corps, et attend donc jusqu'à son délai de 30 s.

Un second défaut est apparu pendant la mesure : un refus 401 est rendu **sans lire le corps de
la requête**. Ce corps reste dans la connexion que l'ingress réutilise, et la requête suivante
arrive tronquée (`400 Bad request syntax ('{"jsonrpc"…}POST /mcp HTTP/1.1')`).

### Mesures

Toutes les mesures utilisent un client MCP minimal (initialize, puis la notification, puis
`tools/list`) ; le jeton est resté en mémoire.

| Où | `initialize` | `notifications/initialized` | `tools/list` |
|---|---|---|---|
| Serveur déployé, en direct depuis le pod de l'Atelier | 200 en 0,044 s | **202 en 0,047 s, sans `Content-Length`, `chunked`, corps jamais terminé** | 200 en 0,046 s |
| Copie locale non corrigée (client httpx, délai 10 s) | 200 en 0,008 s | **ReadTimeout à 10,0 s** | 200 en 0,019 s |
| Copie locale corrigée (§2, correctif serveur) | 200 en 0,007 s | 202 en 0,003 s, `Content-Length: 0` | 200 en 0,002 s |
| Mandataire de l'Atelier devant la copie **non** corrigée | 200 en 0,018 s | 202 en 0,003 s, `Content-Length: 0` | 200 en 0,001 s (24 outils) |

Le mandataire se connecte une fois à Onyxia, au démarrage de la passerelle ; cette connexion
coûte 8 s (délai de lecture de `_notify_initialized` dans `upstream/client.py`), jamais un tour.

### Correction

**Côté serveur**, dans `sspcloud_mcp/server_http.py`, à porter dans son dépôt puis à redéployer
dans le pod `passerelle-mcp`. Ce correctif n'est ni commité ni déployé :

```diff
@@ def _send(self, code, body=b"", ctype="application/json", extra=None):
         if body:
             self.send_header("Content-Type", ctype)
-            self.send_header("Content-Length", str(len(body)))
+        # Toujours délimiter le corps, même vide.
+        self.send_header("Content-Length", str(len(body)))
@@ def do_POST(self):
+        # Lire le corps avant tout refus : laissé dans la socket, il serait pris
+        # pour le début de la requête suivante sur une connexion réutilisée.
+        raw = self._read_body()
         if not self._authorized():
             self._unauthorized()
             return
         try:
-            raw = self._read_body()
             msg = json.loads(raw)
```

**Côté Atelier**, sans attendre le serveur : aucun agent ne joint plus Onyxia en direct. Les
agents passent par deux points d'entrée de la passerelle (`mcp_gateway/atelier/onyxia_projet.py`).
Ils répondent eux-mêmes à `initialize`, à la notification (202, `Content-Length: 0`) et à
`tools/list`, depuis la liste que le pool tient déjà. Seul `tools/call` joint Onyxia, par le
pool.

## 3. La liaison projet-pod

### Le bloc `deploiement`

Dans `.atelier/projet.json` (schéma strict de `commandes/structure.py`, classe `Deploiement`) :

```json
"deploiement": {
  "pod": "proj-carte-jupyter-python-0",
  "namespace": "user-jdupont",
  "gpu": true,
  "commande": "uvicorn app:app --port 8000",
  "port": 8000
}
```

- `pod` **ou** `service` (chemin d'un `<nom>.service.yml`), exactement l'un des deux ;
- `namespace` facultatif (défaut : celui du serveur Onyxia) ; `gpu` vaut faux par défaut ;
  `commande` et `port` sont facultatifs et sont annoncés à l'agent dans les consignes du
  serveur ;
- un champ inconnu, un nom de pod invalide, un port hors de 1-65535 : refusés.

### La commande `atelier_projet_deployer_declarer`

- **Classe `engageante`** : un premier appel rend un aperçu (avant, après, ce que les agents
  recevront) et un jeton ; rien n'est écrit avant l'accord.
- **Pour un pod**, elle appelle `project_bind` d'Onyxia (session `proj-<slug>`) :
  - si Onyxia refuse le pod, la commande est refusée ;
  - si Onyxia est injoignable, la déclaration est écrite, et la session sera attachée au
    premier appel d'un agent.
- Elle n'écrit que `projet.json`, commité seul. `retirer: true` enlève la liaison, et
  « Annuler » remet l'état d'avant.
- Elle est inscrite par une ligne dans `commandes/__init__.py` (`enregistrer`). Cette même
  inscription branche les points d'entrée Onyxia.

## 4. Ce que chaque profil reçoit

Contrat avec l'équipe S : `onyxia_pour_projet(settings, slug, profil, *, pool=None)` rend
l'entrée `mcpServers`, ou `None`. Le porteur est le même que celui du serveur `atelier` :
`Authorization: Bearer ${ATELIER_MCP_KEY}`, résolu par l'environnement de l'agent.

| Profil | Entrée | Outils |
|---|---|---|
| `code`, projet sans `deploiement` | `None` | aucun |
| `code`, `deploiement.pod` | `http://127.0.0.1:<port>/mcp/onyxia/projet/<slug>` | `exec`, `job_poll`, `read_file`, `write_file`, `list_files`, `session_status`, `project_bind` ; `session_id` imposé à `proj-<slug>`, `project_bind` imposé à son pod |
| `code`, `deploiement.service` | idem | `service_status`, `service_deploy`, `service_stop`, `service_warm`, `service_provision` ; `yaml_path` imposé |
| `code`, `gpu: true` | idem | en plus : `gpu_switch` (projet imposé, **sans préemption**), `gpu_release` (projet imposé), `gpu_status` |
| `assistant` | `http://127.0.0.1:<port>/mcp/onyxia` | les 24 outils ; `expose_public` et `unexpose_public` en classe `reservee` |
| tous, si le pool n'a pas `Onyxia` (`pool` fourni) | `None` | aucun |

Règles du filtre (`filtrer_appel`) :

- **Un argument imposé** absent est rempli ; présent avec la même valeur, il passe ; présent
  avec **une autre valeur, l'appel est refusé**. Rien n'est réécrit en silence.
- **Un argument non prévu** (`attach_pod`, `namespace` non déclaré, `preempt: true`…) est
  refusé.
- **Tout outil hors borne** est refusé, et il est absent de `tools/list`. Les arguments
  imposés sont retirés des schémas montrés à l'agent.
- **`expose_public` et `unexpose_public` sont refusés à tout modèle**, dans les deux profils,
  avec l'invitation à passer par « À valider ».
- **Avant un outil de session**, le mandataire vérifie que `proj-<slug>` vise bien le pod du
  projet, ou un pod GPU `proj-<slug>-gpu-…`. Il l'attache par `project_bind` si elle n'existe
  pas, et refuse si elle est partie ailleurs. Cette vérification est gardée 60 s.
- La fiche est relue à chaque appel : une déclaration ou un retrait vaut dès l'appel suivant.

## 5. Ce qui est vérifié, et ce qui ne l'est pas

**Vérifié :**

- la cause de G3 sur le serveur déployé (mesure directe, lecture seule), puis la reproduction
  et le correctif sur une copie locale ;
- le mandataire, en local, devant la copie non corrigée, avec le vrai client amont de la
  passerelle : poignée de main immédiate, `session_status` qui passe, `expose_public` refusé ;
- les tests : `tests/test_deploiement_schema.py`, `tests/test_onyxia_projet.py` et
  `tests/test_deploiement_projet.py`, ainsi que toute la suite `pytest`.

**Non vérifié :**

- **le correctif serveur, déployé** : il faut le porter dans `sspcloud_mcp`, reconstruire,
  relancer `passerelle-mcp`, puis refaire la mesure directe (202 avec `Content-Length: 0`) ;
- **les points d'entrée dans le pod** : rien n'a été modifié ni relancé sur le pod. Après
  fusion et relance de l'Atelier, refaire la poignée de main sur
  `http://127.0.0.1:8787/mcp/onyxia/projet/<slug>` et mesurer l'`init` d'un tour d'agent code
  (attendu : environ 0,7 s, contre 30,3 s) ;
- **la liaison réelle** `project_bind` d'un vrai projet, et le passage d'une session sur son pod
  GPU ;
- **la consommation par S** : l'écriture de l'entrée dans `.mcp.json` et dans la config de
  surface, et son nom de serveur (`Onyxia` recommandé, pour garder `mcp__Onyxia__*`).

## 6. Limites connues

- **La clé ouvre les deux portes.** `ATELIER_MCP_KEY` est la clé du propriétaire. Un agent code
  qui la lit peut appeler `/mcp/onyxia` (complet) à la main, comme il peut déjà appeler `/mcp`.
  Le filtre borne ce que l'agent **reçoit**, pas ce qu'il pourrait forger. La fermer demande
  des capacités courtes par projet (décision « trousseau », hors de ces vagues).
- **`exec` donne un shell dans le pod du projet.** Ce que le compte de service de ce pod peut
  faire (kubectl, S3) reste possible. La borne est le pod, pas ses droits.
- **Les sessions d'Onyxia sont globales.** L'Assistant peut rattacher `proj-<slug>` ailleurs ; le
  mandataire le détecte et refuse, mais ne le répare pas seul.
- **Le 401 sans lecture du corps** désynchronise les connexions que l'ingress réutilise, tant
  que le correctif serveur n'est pas déployé.

## 7. À trancher par le mainteneur, au regard des usages

1. **Porter le correctif dans `sspcloud_mcp`** (ses dépôts GitLab et GitHub) et redéployer
   `passerelle-mcp` : qui, et quand ?
2. **L'Assistant garde-t-il Onyxia au complet ?** `project_start`, `session_stop(uninstall)`,
   `gpu_switch(preempt)` et `service_deploy` d'un autre service engagent le quota ou suppriment
   un pod. Faut-il les passer en `engageante`, avec un aperçu et un jeton, plutôt qu'en accès
   libre ?
3. **La préemption du GPU.** Un agent code ne préempte pas le GPU d'un autre projet. Cela
   convient-il, ou faut-il une file d'attente, ou une demande dans « À valider » ?
4. **Le pod et le service ensemble.** Un projet qui développe dans un pod et publie un service
   doit aujourd'hui choisir l'un des deux. Faut-il permettre les deux dans un même bloc ?
5. **`push_repo` et `pull_artifact`**, refusés au profil code, lisent et écrivent sur la machine
   du serveur Onyxia. Faut-il les ouvrir, bornés au dossier du projet ?
6. **Démarrer et arrêter le service d'un pod.** Faut-il deux outils dédiés qui lancent et
   arrêtent `deploiement.commande` en tâche de fond ? Aujourd'hui l'agent le fait par `exec`,
   guidé par les consignes du serveur.
7. **Le nom de la session** : `proj-<slug>` reprend la convention d'Onyxia, mais le pod de
   l'Atelier utilise déjà `proj-claude-code`. Faut-il un préfixe propre à l'Atelier ?
