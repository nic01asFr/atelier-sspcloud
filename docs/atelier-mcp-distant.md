# Atelier MCP distant — cadrage de chantier

L'Atelier se branche comme connecteur MCP dans un client distant (Claude), sous la seule
clé de son propriétaire, et lui donne ses propres verbes : projets, conversations, agents.

**Statut** : **L0 et L1 faits, déployés et mesurés sur le pod le 20 septembre 2026.**
L2 (portées) et L3 (agents publiés) cadrés, non commencés. Décisions D1–D10 arrêtées le même jour.

**Documents liés** : [`atelier-mcp-unified.md`](./atelier-mcp-unified.md) (le pool, les trois
niveaux — sens entrant), [`atelier-mcp-implementation-plan.md`](./atelier-mcp-implementation-plan.md)
(décision D10 : pas de second service).

---

## 1. De quoi il s'agit, et de quoi il ne s'agit pas

Les documents existants décrivent le sens **entrant** : l'Atelier consomme des serveurs MCP,
les range dans un pool, les sert à ses agents. Ce chantier ouvre le sens **sortant** :
l'Atelier est lui-même un serveur MCP, pour un client qui n'est pas sur le pod.

La porte existe déjà — [`atelier/mcp_endpoint.py`](../atelier-src/mcp_gateway/atelier/mcp_endpoint.py)
branche `/mcp` sur la passerelle intégrée — mais ce qui en sort est le **pool**
(`gateway_find_tools`, `gateway_call_tool`, compositions, profils), pas l'Atelier. Les verbes
de l'Atelier n'existent aujourd'hui qu'en REST sous `/v1`, et la porte n'accepte que la clé
au porteur.

Ce chantier ne crée donc ni service, ni port, ni protocole : il monte un routeur déjà écrit,
et ajoute une famille d'outils au-dessus de handlers déjà écrits.

---

## 2. Décisions arrêtées

| ID | Décision | Pourquoi |
|----|----------|----------|
| D1 | Même processus, même port, même ingress — la porte reste `/mcp` sur `:8787` | Prolonge D10 du plan M1 : pas de second déploiement |
| D2 | L'authentification passe par le flux OAuth de [`oauth.py`](../atelier-src/mcp_gateway/oauth.py), monté sur l'app Atelier | Un client humain ne doit **jamais** porter d'en-tête `Authorization` dans sa configuration : le CLI coupe alors son propre flux, et le secret atterrit dans un fichier que l'agent lit |
| D3 | La clé tapée sur la page de consentement est la **clé API de l'Atelier** (`atelier_owner_key`) | C'est celle qui garde déjà tout le reste du service. Il n'y en a jamais eu deux : `build_gateway_settings` passe déjà cette clé-là à la passerelle, qui se contentait d'en garder une copie dans `gateway_meta` que personne ne lisait. Copie supprimée |
| D4 | `/register` reste ouvert ; la porte est le consentement, pas l'enregistrement | Claude appelle `/register` sans information d'identité ; le fermer coûte le « je colle l'URL et ça marche » |
| D5 | Renouveler la clé révoque les jetons qu'elle a accordés | Une clé se renouvelle parce qu'elle a fui ; laisser vivre ce qu'elle a consenti ne change rien pour qui la détient |
| D6 | Les portées existantes (`owner`, `mcp`) se raffinent en lecture / conduite / administration | La colonne `scope` et `portee_du_porteur` sont déjà là : enrichissement, pas mécanisme neuf |
| D7 | Les outils `atelier_*` appellent les handlers en direct, jamais par HTTP sur soi-même | Le pilote se paie déjà un proxy HTTP interne ; on ne l'imite pas |
| D8 | Un tour long s'expose en deux temps : démarrer, puis suivre | Un appel d'outil qui bloque le temps d'un tour ne tient pas ; le couple existe déjà pour les compositions |
| D9 | Publier un agent = le promouvoir, comme une composition | `promote` / `demote` fait déjà ce geste, et les consignes d'`initialize` annoncent déjà ce qui est en production |
| D10 | `POST /agent/{id}/decide` **n'est pas** exposé en MCP | C'est le geste qui rend le pilote sûr ; l'exposer à l'agent qui a déclenché la proposition le referme sur lui-même |

---

## 3. Lots

### L0 — Le connecteur se branche

Le parcours visé : coller l'URL de l'Atelier comme connecteur, une page s'ouvre, taper la clé
de l'Atelier, c'est branché. Ce que le client voit alors, ce sont les outils du pool — L0 ne
touche pas à la liste d'outils.

**IN** — fait le 20 septembre 2026

- [x] Routeur OAuth monté sur `build_app` — il n'était inclus que dans `main.py`, le service autonome qu'on ne lance pas
- [x] `_owner_key` lit `app.state.owner_key` ; l'Atelier y pose la clé de son fichier. Il ne s'agissait pas d'arbitrer entre deux clés — il n'y en a qu'une — mais d'empêcher le flux d'aller la chercher dans des réglages que l'Atelier n'a pas : l'écran tombait avant de s'afficher
- [x] 401 `WWW-Authenticate` avec `resource_metadata` sur `/mcp`, et le jeton OAuth accepté à cette porte (`validate_credential`) en plus de la clé
- [x] Adresse publique : le réglage `ATELIER_PUBLIC_URL` d'abord (le chart le pose déjà), sinon **ce que l'ingress a écrit devant**. Ce second chemin n'était pas prévu et s'est imposé : deux hôtes mènent au même processus sur ce pod, et une adresse figée en aurait fait mentir un
- [x] Rotation de la clé : purge `oauth_tokens` en plus de `oauth_sessions`, et `app.state.owner_key` remis à jour — sans quoi l'ancienne clé aurait continué de consentir (D5)
- [x] `app.state.gateway_owner_key` retirée : la clé de l'Atelier n'est plus recopiée dans `gateway_meta`, où rien ne la lisait
- [x] Onglet Connecteurs : section « Clients distants » — qui s'est enregistré, qui a été accordé, qui détient un jeton, et un bouton pour débrancher. Plafond de 50 et ménage des clients jamais reconnus sur `/register`

**OUT** : tout outil `atelier_*`, toute portée nouvelle, tout agent publié.

**Tenu par la suite** : `tests/test_connecteur_distant.py` (25 cas) et
`tests/js/clients-distants.suite.mjs` (12 vérifications). Cinq mutations essayées, cinq
mordues : rotation qui ne révoque plus, clé non rafraîchie, adresse publique ignorée, ménage
qui emporte un client branché, en-tête `WWW-Authenticate` retiré. Suite complète : 330 verts.

**Critères d'acceptation** — mesurés sur le pod le 20 septembre 2026, service relancé sur le
code déployé :

1. ✅ `/mcp` sans jeton → 401 portant `resource_metadata` pointant l'hôte public ; `/.well-known/oauth-protected-resource` → 200 annonçant `https://user-nic01asfr-atelier.user.lab.sspcloud.fr`
2. ✅ `/register` d'un client inconnu → 201, puis `/authorize` → page de consentement avec champ clé, **aucune redirection, aucun code**
3. ✅ Clé invalide → 401 ; clé de l'Atelier → 302 vers la destination déclarée, avec code
4. ⚠️ Second branchement : **tenu par la suite, pas mesurable en loopback**. Le cookie de session est posé `Secure` ; un client en clair ne le renvoie jamais (0 cookie retenu côté client, 58 sessions ouvertes côté base). Se verra au premier branchement réel, dans le navigateur
5. ✅ `redirect_uri` non déclarée → 400, **sans redirection**
6. ⚠️ Rotation → **tenu par la suite, pas joué sur le pod** : la mesurer, c'est renouveler la vraie clé de Nicolas et couper ses sessions en cours. À jouer par lui quand il le voudra
7. ✅ Un seul processus sur `:8787` avant et après, 76 Mo, aucune erreur au journal, les 22 conversations toujours là

**Bout en bout, joué sur le pod** : enregistrement → consentement sous la clé → échange du code
(PKCE S256) → `initialize` sur `/mcp` (serveur `atelier`, consignes reçues) → `tools/list`
(9 outils) → `/v1/sessions` avec ce jeton **401** → client listé, puis révoqué → son jeton ne
vaut plus rien. Le client de recette a été retiré : la table est revenue à zéro.

**Vu au passage, pas corrigé** : `oauth_sessions` ne fait l'objet d'aucun ménage (58 lignes,
dont des expirées). Sans conséquence, hors périmètre de ce lot, mais de la même famille que le
plafond posé sur les clients.

### L1 — Les verbes de l'Atelier — **fait, déployé, mesuré le 20 septembre 2026**

Le périmètre a été resserré en cours de route, et par une mesure : wikichat, qui est dans le
pool, donne **déjà** de quoi piloter des agents — voir les agents planifiés et leur cadence,
en définir un (`register_trigger` + `spawn_session`), réveiller un agent hors ligne, lui parler.
Redonner cela sous un autre nom aurait fait deux vérités à tenir. Ce que l'Atelier est le seul
à savoir faire, c'est **conduire une conversation** : c'est cela, et cela seul, qu'il expose.

**Fait** — huit outils dans [`outils_conversation.py`](../atelier-src/mcp_gateway/atelier/outils_conversation.py),
branchés sur les magasins du service, jamais sur une copie :

| Outil | Ce qu'il fait |
|-------|---------------|
| `atelier_projets`, `atelier_conversations` | voir |
| `atelier_ouvrir` | ouvrir un fil dans un projet |
| `atelier_envoyer` / `atelier_suivre` | envoyer un tour, puis le suivre (D8) |
| `atelier_interrompre`, `atelier_transcript` | arrêter, relire |
| `atelier_decider` | répondre à une autorisation que le tour attend |

Branchement : `McpGateway` accepte des `outils_locaux`, dispatchés **avant** la résolution de
profil — ils n'appartiennent à aucun profil et seraient refusés comme hors périmètre.

**Ce que la mesure sur le pod a changé, et qu'aucun test local n'aurait trouvé**

- **Le flux arrivait en miettes.** Un « prêt. » de six caractères remontait en plus de soixante blocs — « pr », « êt », « . » — entrelacés de marqueurs répétés, chacun coûtant un aller-retour. Corrigé en reprenant la règle que le service tient déjà (`retenir_le_texte`) : les fragments et le raisonnement ne remontent pas, les blocs complets sont fondus à la lecture, la même phrase n'est suivie qu'une fois, et `suivre` laisse au tour un court repos pour finir sa phrase. Résultat mesuré : **cinq blocs** au lieu de soixante.
- **Le projet par défaut du pod est rangé.** Quatre conversations de recette y ont été ouvertes et ont disparu de la vue sans que rien ne le signale. `atelier_ouvrir` refuse désormais un projet rangé en disant lesquels sont visibles : ce lot ne vaut que si l'humain peut regarder.

**Et pour l'Assistant et les agents du pod** — rien à écrire : **le chemin existait déjà.**
L'Atelier se propose lui-même comme connecteur au binding d'un projet (`declaration_atelier`,
`SERVICE_ATELIER` dans [`mcp_sync.py`](../atelier-src/mcp_gateway/atelier/mcp_sync.py)), et sa
clé passe par **l'environnement du processus agent** (`${ATELIER_MCP_KEY}`), jamais par un
fichier du dossier de projet. J'avais commencé par déclarer une entrée de registre concurrente,
avec un jeton écrit dans le fichier : un doublon dans la liste des connecteurs, et le secret à
l'endroit précis que leur dessin évite. Retiré, entrée supprimée, jeton révoqué. La leçon est
celle qui était déjà notée sur ce projet : **vérifier l'existant avant de construire.**

Activer les verbes pour un projet est donc un geste de niveau 2, dans l'onglet Connecteurs :
`atelier` → actif. Fait sur `nouveau-projet-4`, mesuré ensuite.

**OUT** : administration du pool, agents publiés (L3), portées (L2). `POST /agent/{id}/decide`
reste hors MCP (D10) : `atelier_decider` répond aux autorisations d'une **conversation**, pas
aux propositions du pilote.

**Tenu par la suite** : 32 cas dans `tests/test_outils_conversation.py`. Quatre mutations
essayées, quatre mordues (dispatch après le profil, envoi bloquant, autorisations masquées,
curseur compté sur les blocs fondus). Suite complète : **362 verts**.

**Mesuré sur le pod, service relancé sur le code déployé** : 17 outils annoncés dont les 8
verbes ; `envoyer` rend la main en **0,00 s** ; le tour part, produit son texte, finit ;
la conversation apparaît dans `/v1/sessions` — donc dans l'interface — avec son titre, son
projet et son tour ; `atelier_transcript` relit le fil ; un projet inconnu comme un projet
rangé sont refusés en disant où aller. Les six conversations de recette ont été supprimées.

**Validation du 20 septembre, en conditions réelles**

- **La boucle d'autorisation, de bout en bout.** Un tour demande (`printf ok > /tmp/…`), `atelier_suivre` le montre avec la commande et sa raison, `atelier_decider` répond `allow` → `tour_repris: true`, le tour reprend, redemande pour la commande suivante, est débloqué à nouveau, et finit en rendant le bon résultat.
- **Un agent de l'Atelier se sert des verbes de l'Atelier.** Dans une conversation du pod, l'agent a appelé `mcp__atelier__atelier_conversations` ; l'appel a demandé une autorisation, accordée **à distance** par le conducteur ; l'outil a rendu les conversations, l'agent a rendu leurs titres. C'est la boucle complète : un agent au travail, conduit et autorisé depuis l'extérieur.

**Deux défauts trouvés par cette validation, et seulement par elle**

1. **Le tour partait sans interlocuteur.** `envoyer` appelait `store.send` sans `peut_attendre`, donc le service choisissait le mode « sans demande » : aucune autorisation n'était jamais demandée, et `atelier_decider` ne pouvait pas servir. Corrigé — la contrepartie est à celui qui conduit : un tour qui attend n'avance plus, à lui de répondre ou d'interrompre.
2. **La même phrase revenait d'un `suivre` à l'autre.** La déduplication ne valait que pour un appel ; elle est désormais portée par le tour.

**Pas encore mesuré** : un tour long de plusieurs dizaines de minutes.

**Vu au passage, corrigé sur le pod** : `~/work/bin/start-atelier-stack.sh` lançait le service
sans `setsid`. Il restait donc dans la session du noyau Jupyter qui l'avait démarré — un noyau
qui redémarre l'emportait, sans une ligne d'erreur. Mesuré en le provoquant sans le vouloir :
502 depuis Internet, service arrêté proprement. Le script d'installation du dépôt, lui, faisait
déjà bien (`install/atelier-init.sh`). Copie de l'ancien lanceur gardée à côté. Le lanceur de
wikichat a la même fragilité, non corrigée.

### L2 — Les portées

**IN** : lecture / conduite / administration adossées à `scope` ; la clé maître garde tout.
La portée s'affiche au consentement : ce qu'on accorde se lit avant de l'accorder.

### L3 — Les agents publiés

**IN** : publier un agent du pilote le fait apparaître comme outil. Un agent publié porte une
description qui tienne devant un modèle qui ne connaît pas le pod, et un schéma d'entrée —
c'est là qu'est le travail, pas dans le transport. Aujourd'hui un agent n'est qu'un trigger
cron plus un `name`, un `role` et un `initial_task` en texte libre.

**Réserve à tenir dans le texte des outils** : les agents du pilote sont des *proposeurs*.
Le contrat injecté leur interdit toute écriture externe ; ils déposent dans la file
d'approbation. Un appel ne rend donc pas un résultat mais une proposition, et l'outil doit le
dire — sinon le client conclura qu'une chose est faite alors qu'elle attend.

---

## 4. Risques

- **L'ingress sert `/` en public.** Le verrou est le consentement derrière la clé — mesuré le 20 septembre, pas supposé : clé invalide 401, clé de l'Atelier 302.
- **Réentrance.** Un client distant qui pilote un agent qui pilote des agents : décider tôt qui tient le journal et qui répond des autorisations, sinon les demandes de décision remontent dans une conversation que personne ne regarde. Ouvert, pour L1.
- ~~**Deux magasins de clés.**~~ Il n'y en avait qu'un : la copie dans `gateway_meta` est supprimée (D3).
- **Non mesuré** : ce que le client distant envoie exactement au consentement (paramètre `resource`, RFC 8707), et le comportement des champs OAuth avancés si l'enregistrement dynamique venait à être fermé.

---

## 5. Hors périmètre

Autorité OAuth mutualisée, délégation par agent, coffre Vault : c'est le trousseau
(`trousseau-sspcloud`), pas ce chantier. Ce qui est décidé ici reste local au pod et à un seul
propriétaire, et doit pouvoir être remplacé par le trousseau sans réécrire les outils.
