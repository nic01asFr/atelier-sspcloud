# Lecteur Grist, mode application — conception

Version 1, 24/09/2026. **À valider par Nicolas.** Lots 0 à 5 réalisés le
25/09/2026 (voir « État », en fin de document) ; L6 à L8 sont une
proposition, non implémentée.
Sources : grist-core 1.7.3 (Apache-2.0 ; attention, le clone local est le fork
nic01asFr, le moteur à reprendre est celui de gristlabs), grist-static,
`docs/consignes/lecteur-grist.md`, `docs/atelier-applications.md`.
« Estimé » = à mesurer au lot 0.

## 0. Décisions proposées

| Question | Proposition |
|---|---|
| Forme | Serveur **Python** léger (Starlette + uvicorn) + le lecteur HTML actuel comme client, qui passe en « mode serveur » quand il est servi par l'application. |
| Formules | **Moteur de données Python d'origine de grist-core** (`sandbox/grist`, figé sur une version gristlabs), en sous-processus CPython natif, protocole marshal déjà utilisé par Grist. Pas de traduction JS, pas de Pyodide côté serveur. |
| Stockage | Le `.grist` (SQLite, WAL) est la base de l'application ; un seul écrivain (file d'actions, comme `ActiveDoc`). |
| ACL | Appliquées **côté serveur**, portage fidèle de `PredicateFormula.ts` et `PermissionInfo.ts` ; tout ce qu'on ne sait pas évaluer est refusé. |
| Identité | `aucune` (127.0.0.1 seulement), `motdepasse`, `jetons`, `oidc`, `entete` (Atelier, oauth2-proxy), `anonyme`. Rôles (`user.Access`) dans la config. |
| Widgets | Récupérés et mis en cache par le serveur (plus de CORS), servis sous `/widgets/<clé>/…` en origine opaque ; protocole grain-rpc inchangé côté client. |
| Config | `application.json` ; copie portable (sans secret) dans `_gristsys_PluginData` du `.grist`. |
| API | Sous-ensemble **compatible REST Grist** (`/api/docs/{docId}/…`) + `/api/app`, `/api/evenements` (SSE), `/api/admin/…`. |

## 1. Forme du produit

**Pourquoi Python** : le moteur de formules est du Python (~22 000 lignes,
230 fonctions de tableur) et les formules des documents sont du Python
arbitraire ; seul un interpréteur Python les calcule fidèlement. grist-core
complet comme moteur est écarté comme voie principale (image > 1 Go, modèle
org/espace surdimensionné, l'application redeviendrait « une instance Grist »)
mais gardé comme **référence de test** en CI.

Commandes (paquet `lecteur_grist`, dossier `serveur/` du projet) :

```
lecteur-grist init  <doc.grist> <dossier> [--titre T] [--purger-historique] [--recuperer-widgets]
lecteur-grist serve <dossier> [--hote 127.0.0.1] [--port 8080] [--auth aucune|motdepasse|jetons|oidc|entete]
lecteur-grist widgets recuperer <dossier> [--section N] [--tout]
lecteur-grist acl verifier <dossier>
lecteur-grist utilisateurs ajouter|retirer|role <dossier> <email> [--role owners|editors|viewers]
lecteur-grist jetons creer|revoquer <dossier> <nom> [--role viewers]
lecteur-grist sauvegarder|restaurer <dossier> [<id>]
lecteur-grist exporter <dossier> <sortie.grist> [--purger-historique]
lecteur-grist verifier <dossier>
```

`serve` refuse `--auth aucune` hors 127.0.0.1/::1, et `--auth entete` sans
écoute locale. `init` **copie** le `.grist` (application décorrélée de
l'original), vérifie intégrité et `schemaVersion`, charge le moteur une fois,
produit les rapports ACL et widgets.

Dossier d'application :

```
<dossier>/
  application.json        config non secrète
  document.grist          base vivante (WAL)
  journal.sqlite          actions appliquées (qui, quand, undo)
  widgets/<clé>/          copies des widgets + meta.json ; widgets/_api/grist-plugin-api.js
  sauvegardes/            <horodatage>.grist + .json
  secrets/                0700 : clé de session, utilisateurs (scrypt), jetons (sha256)
  .gitignore              données, sauvegardes, secrets hors git
```

Trois déploiements :

- **localhost** : `lecteur-grist serve ./mon-app --port 8080`, sans auth, la
  personne est propriétaire.
- **Artefact serveur de l'Atelier** : le dossier d'application est
  `artifacts/<nom>/` ; manifeste `artefact.json` (commande `python -m
  lecteur_grist serve artifacts/<nom> --hote 127.0.0.1 --port {port} --auth
  entete --entete-utilisateur X-Atelier-Utilisateur`, `sante: /_sante`,
  protocoles `http`, `sse`). Adresses relatives, battement SSE 20 s, écriture
  des widgets par grain-rpc (l'anti-CSRF de l'Atelier refuse `Origin: null`),
  démarrage à froid après inactivité (estimé 1–5 s).
- **Serveur public** : image OCI `python:3.12-slim`, `VOLUME /data`, `--auth
  oidc` ; chart SSPCloud à **1 réplique** (SQLite + moteur en mémoire), PVC,
  Ingress TLS, NetworkPolicy de sortie limitée ; sous-domaine séparé pour les
  widgets.

## 2. Données et persistance

- **Chargement** (reproduit d'`ActiveDoc`) : WAL, `trusted_schema=OFF`,
  `integrity_check` ; document plus récent que le moteur → lecture seule ; plus
  ancien → sauvegarde puis migrations ; chargement des tables dans le moteur
  (marshal) ; `Calculate`.
- **Écriture** : file unique. Contrôle préalable (schéma, règles d'accès,
  actions internes interdites au client) → moteur `apply_user_actions` →
  contrôle ACL des actions **directes** (comme `canApplyBundle`) → refus = défaire
  par `ApplyUndoActions` et 403 → transaction SQLite (portage de
  `DocStorage._process_*`, ~400 lignes) → journal → SSE d'invalidation (chaque
  client relit via l'API filtrée) → réponse `{actionNum, retValues}`. Échec de
  transaction : redémarrage du moteur, rien de commité.
- **Concurrence** : écritures sérialisées, dernier écrivain gagne par cellule
  (comme Grist), lectures parallèles (WAL), verrou de dossier, pas de
  multi-réplique.
- **Sauvegardes** : `VACUUM INTO`, horaires (48) et quotidiennes (14), avant
  migration/restauration, à la demande ; restauration à chaud.
- **Export `.grist`** : réservé à qui a `FullCopies` ; option de purge de
  `_gristsys_ActionHistory` (qui contient d'anciennes valeurs). Toute
  modification de l'écriture se vérifie par réouverture dans un vrai Grist.

## 3. Formules

**Traduire le moteur en JavaScript ?** Non : les formules des documents sont du
Python arbitraire ; traduire le moteur obligerait à écrire un interpréteur
Python en JS, ce que fait Pyodide avec le vrai CPython. Une traduction partielle
des formules simples produirait des écarts **silencieux** (`None + 1`, division,
arrondis, dates) : rejetée. En mode navigateur, les colonnes formule dont une
entrée a changé sont signalées « valeurs figées ».

**Pyodide** : grist-core l'utilise déjà côté Node (`sandbox/pyodide/`,
`GRIST_SANDBOX_FLAVOR=pyodide`) ; grist-static le fait tourner dans le
navigateur (Web Worker, moteur empaqueté en roue). Poids : ~15,5 Mo bruts
(~8 Mo gzip) ; démarrage estimé 3–8 s.

| Option | Fidélité | Coût | Choix |
|---|---|---|---|
| Valeurs stockées figées (actuel) | exacte à l'ouverture | nul | mode navigateur |
| Moteur CPython côté serveur | celle de Grist | moyen | **recommandé** |
| Pyodide dans le navigateur | celle de Grist | +21 Mo (fichier ~23 Mo), CSP | plus tard, variante optionnelle `lecteur-grist-formules.html` |
| Traduction JS | faible, divergences silencieuses | élevé | rejeté |

Sous la CSP des artefacts de l'Atelier, Pyodide est impossible sans
`'wasm-unsafe-eval'` : on ne le demande pas ; l'artefact serveur calcule côté
serveur.

Sécurité : une formule est du code exécuté sur le serveur. Sous-processus à
environnement vide, `RLIMIT_AS`, `nice`, réseau coupé (`unshare -n`) si le
cluster le permet ; formules modifiables par les propriétaires seuls ; `init`
signale les imports sensibles.

## 4. Widgets côté serveur

Récupération par le serveur (réutilise `outils/embarquer_widgets.py` : refus des
adresses privées, plafonds), rangée en **miroir par chemin** (le widget reste
« à son adresse », CDN réécrits sous `/widgets/<clé>/_ext/…`) ou en copie
autonome. Service : miroir > copie du document > relais direct si autorisé >
« non disponible ». CSP `sandbox` sans `allow-same-origin` (origine opaque) ;
`--port-widgets`/sous-domaine pour une vraie origine distincte. Accès réseau
d'un widget à l'exécution : liste blanche par section, jamais accordée
automatiquement. `getAccessToken` : jeton HMAC 15 min, lecture seule pour un
widget `read table`.

## 5. Authentification et ACL

`_grist_ACLRules` porte `aclFormulaParsed` (arbre déjà analysé) : **toutes** les
formules d'ACL sont évaluables fidèlement (portage de `compilePredicateFormula`,
~150 lignes). Appliqué en v1 : combinaison par `rulePos` et ressources
colonne/table/`*:*`/défaut ; lecture (tables et colonnes absentes, lignes
filtrées, cellules censurées, métadonnées filtrées) ; écriture C/U/D par
colonne avec `rec`/`newRec` ; `S`, `FullCopies`, `SchemaEdit` ; attributs
utilisateur. Non pris en charge en v1 : liens de partage (`LinkKey`), partages,
« voir comme », mémos, modification des règles dans l'application.

Règle par défaut : une règle non évaluable refuse ce qu'elle accorderait ;
`serve` multi-utilisateur **refuse de démarrer** s'il en existe (sauf option
explicite) ; un utilisateur sans rôle n'a **aucun** accès.

Derrière l'Atelier : identité par `X-Atelier-Utilisateur` (propriétaire seul
en v1), traduite en e-mail par `identites` ; domaine de confiance = l'utilisateur
Unix du pod. Public : OIDC Keycloak SSPCloud (client à demander aux
administrateurs) ou oauth2-proxy en mode `entete`.

## 6. Configuration

`application.json` fait foi (titre, pages visibles et ordre, sections en lecture
seule, widgets et leur réseau, apparence, édition, recalcul, auth, rôles,
sauvegardes) ; copié sans secret dans `_gristsys_PluginData` à l'export, relu
par `init`. Modifiable par les `owners` (`PUT /api/admin/config` avec `If-Match`,
ou CLI) ; `auth` et `roles` par la CLI seule en v1. Masquer une page n'est pas
une ACL.

## 7. API HTTP (relative au préfixe)

- `GET /_sante` ; `GET /` (lecteur) ; `GET /api/app` (bascule le lecteur en mode
  serveur).
- Compatibles Grist : `GET /api/docs/{docId}/tables`, `…/columns`, `…/data`,
  `…/records` ; `POST …/apply` ; `POST|PATCH|PUT …/records` ; `…/sql` ;
  pièces jointes ; `…/download`.
- Propres : `GET /api/evenements` (SSE), `POST /api/jeton`, `GET /widgets/…`,
  `/api/admin/*` (config, sauvegardes, widgets, rapport ACL, journal),
  connexion/déconnexion/retour OIDC.

## 8. Lots

- **L0 — Mesures (2–3 j)** : moteur gristlabs en sous-processus sur CRESO et
  documents d'essai, temps et mémoire ; réouverture dans un vrai Grist en CI.
- **L1 — Serveur en lecture seule** : `init`, `serve`, routes GET, lecteur en
  mode serveur ; parité serveur/navigateur.
- **L2 — Écriture avec formules** : moteur, stockage, file, journal, SSE,
  sauvegardes, export ; **test de parité contre `gristlabs/grist`** cellule par
  cellule.
- **L3 — Widgets côté serveur** (en parallèle de L2) : miroir, service, CSP,
  jetons ; calendrier gristlabs compris.
- **L4 — Identité et ACL** : **test différentiel contre Grist** par
  utilisateur ; règles non évaluables qui bloquent `serve`.
- **L5 — Artefact serveur Atelier**.
- **L6 — Configuration**.
- **L7 — Public** : image, chart, OIDC, anonyme, revue de sécurité.
- **L8 (optionnel)** : variante HTML avec Pyodide ; `REQUEST()` sur liste
  blanche.

Ordre : L0 → L1 → L2 → L4 → L7, L3 et L5 après L1/L2. **Rien n'est exposé à
plusieurs utilisateurs avant L4.**

## 9. Risques

Version du moteur contre version des documents ; portage du stockage
(`ModifyColumn`) ; subtilités ACL ; formules = code arbitraire sur le serveur ;
historique d'actions dans les exports ; pièces jointes externes (Grist ≥ 1.4) ;
Atelier mono-utilisateur ; client OIDC SSPCloud à obtenir ; licences des widgets
redistribués ; une seule réplique.

## 10. État (25/09/2026)

Projet `projet-sans-nom-5` (pod), dossier `serveur/`, paquet `lecteur_grist`.
Détail des mesures : `serveur/MESURES.md` ; usage : readme du projet.

### Fait et vérifié

- **L0** : moteur de **gristlabs**/grist-core **v1.7.19** (`sandbox/grist`,
  sans retouche, tests retirés, LICENSE/NOTICE/`RETOUCHES.md`), `.venv`
  Python 3.11 (uv) ; client sous-processus `PIPE_MODE=minimal` ; chargement
  dans l'ordre d'ActiveDoc, migrations comprises ; portage de
  `DocStorage._process_*` (y compris `ModifyColumn`). Mesuré sur 6 documents
  réels (Saint Martin ×2, CRM, 🟢CRM 111 Mo, Charts v4, Grist Tasks) et 2
  fixtures migrées.

  | | petit doc | CRM (22 k lignes, 55 formules) | 🟢CRM (111 Mo, 85 k lignes) |
  |---|---|---|---|
  | démarrage du moteur | 0,7–0,8 s | 0,7 s | 0,9 s |
  | chargement + Calculate | 0,15–0,4 s | 3,6 s (Calculate 3,0) | 7,4 s (Calculate 4,2) |
  | mémoire chargé / pic | 73–76 / 91 Mo | 191 / 217 Mo | 363 / 493 Mo |
  | action courante (médiane) | 1,5–3 ms | 4,6 ms | 4,7 ms |
  | `RenameColumn` | 0,5 s | 1,1 s | 1,4 s |
  | fidélité après Calculate | 0 écart | 190 écarts (date du jour), **les mêmes dans Grist** | 144 (idem) |

  Écriture : 25 actions par document (formule dépendante, lookup, colonne
  déclenchée, AddOrUpdate, renommage, undo…), écrites par `stockage.py`,
  rouvertes dans un moteur neuf (0 recalcul, 0 écart) **et dans un vrai
  Grist**.
- **Réouverture dans Grist** : grist-core 1.7.19 **construit depuis les
  sources** avec Node 22 (sur le pod en 2,5 min ; sur le poste Windows, où
  sont les documents réels, lancé en `unsandboxed`), import par
  `POST /api/docs` et comparaison cellule par cellule
  (`serveur/outils/verifier_dans_grist.py`) : « Saint Martin_local_test »
  (enregistré par le lecteur) et 5 documents écrits par le moteur s'ouvrent,
  mêmes tables, 0 écart ; copies `_lecteur_hors_ligne` conservées.
- **L1** : `lecteur-grist init|serve|verifier` ; dossier d'application
  (`application.json`, `document.grist`, `widgets/`, `sauvegardes/`,
  `secrets/` 0700, `.gitignore`) ; `init` refuse un document sans
  `schemaVersion`, migre un document ancien après sauvegarde, charge le
  moteur une fois ; `serve` (Starlette/uvicorn) : `/_sante`, `/`, `/api/app`,
  `GET /api/docs/{docId}/tables|columns|data|records` (`filter`, `sort`,
  `limit`, `hidden`), `/api/evenements` (SSE, battement 20 s), préfixe
  (`X-Forwarded-Prefix`), refus de `--auth aucune` hors 127.0.0.1/::1.
  Lecteur : `SourceServeur` implémente `Donnees` sur l'API (réplique sql.js
  rangée comme DocStorage), activée quand `api/app` répond ; mode fichier
  inchangé.
  Vérifié : 14 tests (`serveur/tests`, Windows et pod) ; routes comparées à
  grist-core sur Saint Martin et Charts v4 (**0 écart** sur tables, colonnes,
  données, métadonnées) et CRM (seuls écarts : date du jour, table cachée par
  une règle d'accès) ; Chrome sans tête (`outils/verifier_serveur.py`) sur
  Saint Martin ×2, Charts v4, CRM : tables lues par le lecteur et données des
  widgets identiques en mode fichier et serveur, mêmes pages et widgets
  (Builder, Coder prêts ; Atlas affiché en ligne), SSE connecté, même
  résultat derrière un relais à préfixe ; dans le pod, même parité sur le
  document d'essai des tests et 4 fixtures de grist-core en schéma 46 (dont
  `TypeEncoding`). Mode fichier intact : `outils/verifier_artefact.py`,
  32 étapes sur 32 (`file://` et CSP de l'Atelier), dans le pod, après
  `outils/publier.sh`. Commits locaux (pas de push) : 12 commits, du moteur
  recopié (`6d48fea`) à `04d5d75`, arbres identiques entre le poste et le
  pod.
- **L2** : écriture par le moteur, chargé par `serve`.
  - `serve` prend un **verrou de dossier** (`.verrou`, un seul serveur), passe
    le document en WAL (`synchronous=FULL`), le charge dans le moteur et
    **range ce que `Calculate` change à l'ouverture** comme action système
    (comme ActiveDoc : seulement si elle stocke quelque chose).
  - **File d'écriture unique** : le moteur applique, puis une transaction
    SQLite range les actions stockées (`stockage.py`) et l'historique ; si
    la transaction échoue ou si le moteur meurt pendant l'action, **rien
    n'est écrit**, le moteur est relancé et rechargé depuis le fichier.
  - Routes **au format de l'API REST de Grist** : `POST /api/docs/{id}/apply`
    (réponse `actionNum`, `actionHash`, `retValues`, `isModification`),
    `POST|PATCH|PUT …/records`, `…/records/delete`, `POST …/data` ; analyse
    et erreurs reprises de `TableOperationsImpl`/`DocApi` (400 `Invalid
    payload`, 404 table ou colonne absente, 500 `[Sandbox] …` pour
    `/apply`, 403 pour les actions que Grist refuse faute de contrôle).
  - **`_gristsys_ActionHistory` tenu comme Grist** (`ActionHistoryImpl`) :
    même corps marshalé et même `actionHash` (vérifié octet pour octet sur
    390 lignes d'historique écrites par Grist), élagage identique.
    `journal.sqlite` : qui, quand, origine, actions, de quoi défaire.
  - **SSE** : événement `actions` {actionNum, tables} ;
    `/api/modifications?depuis=N` pour rattraper. Lecteur en mode serveur :
    `appliquerActions` passe par `/apply`, puis la page relit les tables
    touchées ; les modifications des autres clients arrivent par le flux.
  - **Sauvegardes** par `VACUUM INTO` : toutes les heures si le document a
    changé, avant migration, à la demande (`lecteur-grist sauvegarder`) ;
    rétention 48 dernières + une par jour sur 14 jours ; `restaurer`
    (serveur arrêté, sauvegarde de l'état courant avant). `GET …/download`
    (`nohistory=true` purge l'historique) et `lecteur-grist exporter
    [--purger-historique]`.
  - Vérifié :
    - **parité contre grist-core 1.7.19** (`serveur/outils/parite_grist.py`) :
      même suite de 33 à 36 requêtes jouée contre Grist et contre `serve`,
      réponses comparées, puis **toutes les tables** (utilisateur et 24
      `_grist_*`) cellule par cellule avec `comparer_avec_grist.py`,
      l'historique action par action, et notre `/download` **rouvert dans
      Grist**. Poste : Saint Martin, Charts v4, CRM, Grist Tasks (migré), un
      document d'essai : 0 écart (hors table `Artefacts` de CRM, cachée par
      une règle d'accès : L4). Pod : 12 documents (fixtures de grist-core,
      dont 5 en stockage 7 et 8, migrés) : 0 écart, historique identique
      (30 actions sur 30) partout, réouverture sans écart ;
    - tests (`serveur/tests`, 27, poste et pod) : **deux clients** qui
      écrivent en même temps (40 actions, rien de perdu, `actionNum`
      continus), **moteur tué au milieu d'une action** (500, rien d'écrit,
      moteur relancé, écriture suivante normale), transaction refusée,
      verrou, SSE, historique, sauvegardes, rétention, restauration,
      migration de stockage ;
    - **Chrome** (`outils/verifier_ecriture_navigateur.py`, poste sur Saint
      Martin, pod sur le document d'essai) : le widget Markdown de
      gristlabs, chargé à son adresse, écrit par ses propres boutons ; un
      widget du Builder d'Étude ajoute une ligne ; un deuxième onglet voit
      la modification par SSE ; elle est là après rechargement, puis après
      arrêt et relance du serveur ;
    - lecture inchangée : fichier contre serveur (`verifier_serveur.py`)
      identiques, sauf les formules « date du jour », que le serveur tient à
      jour ; mode fichier : `verifier_artefact.py` 32/32 dans le pod.
  - Temps (poste) : démarrage de `serve` 1,6 s (Saint Martin, 10 Mo), 5,0 s
    (CRM), 7,8 s (🟢CRM, 111 Mo) ; `POST /apply` d'une cellule 31 ms en
    médiane (écriture durable) ; `/download` 0,2 à 0,9 s.
  - Commits locaux (pas de push) : 12 commits, de `eee185d` à
    `16315c4`, arbres identiques entre le poste et le pod.
- **L4** : identité et règles d'accès, en localhost.
  - **Règles** : portage de `compilePredicateFormula` sur `aclFormulaParsed`
    (sémantique de JavaScript : `===`, `+`, `<`, `in` sur les textes,
    `undefined` distinct de `null`, `.lower()`/`.upper()`),
    `ACLRuleCollection` (ressources colonne, table, `*:*`, `*SPECIAL` :
    `FullCopies`, `AccessRules`, `DocCopies`, `SchemaEdit` ; règles par
    défaut ; colonnes d'aide ; attributs utilisateur, `COLLATE NOCASE` pour
    `Email`), `PermissionInfo`/`evaluateRule` (dont `allowSome`/`denySome`,
    mémos). `acces.py` porte `GranularAccess` pour l'API : lecture filtrée
    (table refusée 403 et absente de `/tables`, colonnes retirées, lignes
    filtrées, cellules `['C']`, métadonnées censurées comme `CensorshipInfo`
    — tableId, colId, libellés, formules et options vidés ; commentaires
    censurés ; ordre des lignes du DocData de Grist tenu), écriture contrôlée
    (`checkUserActions` avant le moteur ; `canApplyBundle` après, chaque
    DocAction directe avec `rec` = état avant, `newRec` = état en fin de
    lot ; refus = `ApplyUndoActions` dans le moteur, puis 403 « Blocked by …
    access rules » avec mémos, comme Grist). `/download` et `/sql` réservés
    à `canCopyEverything` (le propriétaire télécharge toujours) ; SSE et
    `/api/modifications` : l'avis reste, limité aux tables lisibles ; la
    relecture passe par l'API filtrée. Règle non évaluable : elle refuse ce
    qu'elle accorderait, et `serve` multi-utilisateur refuse de démarrer
    (sauf `--accepter-refus`) ; compte sans rôle : aucun accès.
  - **Identité** : `--auth motdepasse` (scrypt, cookie de session HMAC
    `HttpOnly`/`SameSite=Lax`/`Secure` hors localhost, invalidé quand le
    mot de passe ou le rôle change ; `Origin`/`Sec-Fetch-Site` exigés sur
    les méthodes modifiantes ; 5 échecs par compte et 10 par adresse sur
    5 min), `jetons` (Bearer, rangé haché, rôle au plus celui du compte,
    révocable), `entete` (écoute locale seulement, pour L5). `roles` dans
    `application.json` ; commandes `lecteur-grist acl verifier`,
    `utilisateurs lister|ajouter|role|motdepasse|retirer`,
    `jetons lister|creer|revoquer`. Lecteur : page `/connexion`, compte
    affiché, déconnexion, pages et sections des tables cachées omises,
    cellules censurées « masqué », téléchargement proposé s'il est permis.
  - Vérifié :
    - **test différentiel contre grist-core** (`serveur/outils/acl_differentiel.py`,
      Grist en `GRIST_FORWARD_AUTH_HEADER`, `serve --auth entete` sur le même
      en-tête) : propriétaire, éditeurs, lecteur, comptes à attributs,
      compte sans rôle ; `/tables`, `/data`, `/columns`, `/records`,
      12 tables `_grist_*`, `/download`, `/sql`, puis les écritures (code,
      message, mémos), puis l'état complet. Scénarios tirés de
      `test/server/lib/GranularAccess.ts` (lignes, colonnes, `newRec`,
      cellules censurées, verrous, attributs, `FullCopies`, `AccessRules`,
      `DocCopies`, `-S`, `DuplicateTable`, `ApplyUndoActions`, `EvalCode`,
      règles qui échouent), fixtures à règles (`SelectionSummary`,
      `Memos-v34`, `Grist Basics`, `SummaryTableFormula`) et CRM (règles
      réelles par périmètre, table `Artefacts` cachée) : **0 écart**
      (5,8 millions de cellules comparées pour CRM ; 40 écritures dont 24
      refusées, mêmes verdicts). Poste et pod (sans CRM), mêmes résultats ;
    - règles non évaluables (arbre non compilable ; fixture `BadRules`) :
      Grist rend 500 partout, `serve` refuse de démarrer, `--accepter-refus`
      sert en refusant ;
    - Chrome, deux comptes par mot de passe (`outils/verifier_acces_navigateur.py`,
      Saint Martin sur le poste, document d'essai dans le pod) : l'éditeur ne
      voit pas la table cachée (réplique, pages, `/tables`), lit et écrit
      403 ; son écriture permise arrive chez le propriétaire ; déconnexion ;
    - `serveur/tests` (34, poste et pod) ; parité d'écriture L2 et test
      Chrome L2 rejoués sans changement.
  - Coût : `/data` d'une table de 2,7 Mo filtrée par règle de ligne +25 %
    (CRM, 419 → 524 ms).
  - Commits locaux (pas de push) : 7 commits, de `e1f3a57` à `1b7548e`,
    arbres identiques entre le poste et le pod.
- **L3** : widgets servis par le serveur.
  - `lecteur-grist widgets recuperer` (hors requête) range sous
    `widgets/<clé>/` un **miroir par chemin** (page, scripts, modules ES et
    carte d'import, CSS et `@import`/`url()`, images, polices ; CDN sous
    `_ext/<hôte>/…` ; références réécrites en relatif ;
    `grist-plugin-api.js` remplacé par `/widgets/_api/grist-plugin-api.js`)
    et une **copie autonome** (`outils/embarqueur-widgets.js` dans Node).
    Réseau par le `Recuperateur` d'`outils/embarquer_widgets.py` (refus des
    adresses privées après résolution, plafonds) ; une adresse à jeton n'est
    jamais récupérée. `widgets lister|autoriser|relais`.
  - Service (`/api/widgets`, par section lisible) : miroir > copie
    autonome > copie du document > relais direct si autorisé > « non
    disponible » (données brutes). `/widgets/*` sans identification (code
    public du widget), CSP `sandbox` sans `allow-same-origin`, réseau =
    serveur + **liste blanche de la section** (`widgets.sections.<id>.reseau`),
    jamais accordée d'office : les origines citées par le code et par les
    paramètres d'adresse sont **proposées** au propriétaire (bandeau,
    `widgets lister`). `--port-widgets` : vraie origine distincte
    (`allow-same-origin` sur cette origine, qui n'est pas celle du lecteur).
  - `getAccessToken` : `POST /api/jeton` → jeton HMAC de 15 min au nom de
    l'utilisateur, accepté en `?auth=` sur `/api/docs/*` seulement (CORS
    ouvert pour ces appels, pré-vol `OPTIONS`), soumis à ses règles
    d'accès ; lecture seule pour un widget « read table » ; rôle jamais
    au-dessus de celui du compte ; un jeton de widget n'en émet pas d'autre.
  - Lecteur : en mode serveur, les widgets externes viennent du serveur ; le
    mode fichier est inchangé (`verifier_artefact.py` 32/32 dans le pod).
  - Vérifié (Chrome 153, poste) : Builder, markdown, calendrier gristlabs
    (uicdn.toast.com recopié : il tourne, ce qui échouait en mode fichier
    hors ligne), carte (marqueurs ; tuiles d'OpenStreetMap accordées par la
    liste blanche : affichées avec `--port-widgets`), Atlas de Saint Martin
    avec sa scène (`--port-widgets`, scène, data.geopf.fr et
    tiles.openfreemap.org accordés). Sonde dans un widget « read table » :
    cookies, `localStorage` et `parent.document` inaccessibles, API sans
    jeton illisible, jeton en lecture seule (écriture 403 « No write
    access »), jeton altéré 401. `serveur/tests` 41 (poste et pod).
  - Commits : `ef2df53` à `6a2c98a` (6), arbres identiques poste et pod.
- **L5** : artefact serveur de l'Atelier, `artifacts/application/` du projet.
  - `artefact.json` au format du manifeste déployé (`type: service`,
    `commande` avec `{port}`, `repertoire: ../../serveur`, python du venv du
    projet, `chemin: retire`, `sante: /_sante`, `protocoles: [http, sse]`,
    `inactivite_min: 30`) ; créé par `atelier-app creer … serveur`, démarré
    par `atelier-app demarrer`. Dossier d'application
    `artifacts/application/dossier/` (ignoré par git), document d'essai
    écrit par le moteur dans le pod (`fabriquer_essai_widgets.py --moteur`).
  - Identité : `--auth entete --entete-utilisateur X-Atelier-Utilisateur` ;
    `apps/proxy.py` pose la valeur littérale `proprietaire` (et
    `X-Atelier-Acces: proprietaire`) ; `init` écrit `identites:
    {"proprietaire": <compte propriétaire>}`.
  - Vérifié par l'adresse publique (passage par code depuis le pod, ni clé
    ni cookie ni code affichés) : page, `api/app` en `owners` avec le
    préfixe ; widgets servis en copie autonome, les quatre appellent
    `grist.ready` dans Chrome sans tête (cookie posé par DevTools) ;
    écriture 200, autre `Origin` 403 (relais) ; SSE à travers l'Ingress
    (bonjour, actions, battements toutes les 20 s, flux tenu 88 s ; ligne
    écrite ailleurs visible dans la page en 0,3 s) ; arrêt pour inactivité
    (`inactivite_min` 1 le temps de l'essai : arrêt à 80 s) puis navigation
    → 503 « Démarrage… » → `api/app` 200 en 1,1 s.
  - Commits : `6407182`, `0117ba9`, arbres identiques poste et pod.

### Écarts à la conception

- **Stockage** : la conception prévoyait de refuser à `init` les documents
  qui demandent une migration de stockage. Les migrations 8 et 9 de
  DocStorage (un index, une colonne) ont été portées : les documents en
  stockage 7 et 8 sont migrés après sauvegarde, comme Grist le fait ;
  avant 7, `init` refuse (« ouvrir dans Grist puis réexporter »).
- **parseStrings partiel** : seules les chaînes numériques simples envoyées
  dans une colonne Numeric/Int sont lues comme Grist (point décimal, sauf
  langues où il sépare les milliers) ; le moteur convertit le reste comme il
  sait. Dates et nombres localisés : non.
- **Tables de règles** (`_grist_ACLRules`, `_grist_ACLResources`) :
  montrées seulement à qui a la permission `AccessRules` ; Grist les envoie
  aussi à qui peut tout lire (écart voulu, compté à part dans le test
  différentiel).
- **Règle non évaluable** : Grist bascule le document entier sur les règles
  d'urgence et refuse de le servir ; ici la règle seule refuse ce qu'elle
  accorderait, et `serve` multi-utilisateur ne démarre pas sans
  `--accepter-refus` (ressource en double, règle après la règle par défaut :
  règles d'urgence, comme Grist).
- **Non pris en charge en v1** (refusé plutôt qu'approché) : modifier les
  règles depuis l'application (même le propriétaire : 403 ; un non-
  propriétaire reçoit l'erreur de Grist) ; partages et formulaires publiés
  (`_grist_Shares` ignoré, `ShareRef` toujours nul), liens (`user.LinkKey`
  toujours vide), « voir comme » ; commentaires (`_grist_Cells`) et
  identifiants de pièces jointes écrits par un non-propriétaire quand il y a
  des règles ; `user.UserID`, `UserRef`, `SessionID`, `Name` propres à ce
  serveur (une règle qui s'en sert ne se comportera pas comme dans Grist) ;
  masque de permissions des jetons (le rôle du jeton en tient lieu).
- Restauration **serveur arrêté** seulement ; pas de pièces jointes
  (`_gristsys_Files` non servi) ; `REQUEST()` refusé.
- Lecteur : la réplique est construite à l'ouverture depuis `/data`, puis
  relue par table après chaque modification (pas de lecture paresseuse). Une
  colonne Bool rangée en blobs marshal par le fichier (CRM `Agents.actif`) se
  lit `true` en mode fichier, `1` en mode serveur (même valeur pour Grist).
- `sort` : tri simple (sans options `:naturalSort`, etc.).
- `--auth` : `oidc` n'existe pas encore (L7) ; `aucune` et `entete`
  n'écoutent que sur 127.0.0.1/::1.
- **Widgets (L3)** : la copie autonome s'intercale entre le miroir et la
  copie du document ; **derrière l'Atelier elle passe avant le miroir** : le
  cookie de session des applications (`__Host-atelier_apps`, `Lax`) ne part
  pas des requêtes d'une page d'origine opaque, qui ne pourrait pas charger
  ses ressources à travers le relais. Le serveur le détecte par
  `X-Atelier-Acces`. Réglage `widgets.forme` (`auto`, `autonome`, `miroir`).
- **getAccessToken** : Grist le refuse à un widget « read table » ; ici il
  l'obtient **en lecture seule** (demande du lot). Derrière l'Atelier, un
  widget qui appelle lui-même l'API avec son jeton reçoit 401 du relais
  (pas de cookie depuis une origine opaque) : ce qui passe par grain-rpc
  fonctionne, l'appel direct non.
- **Tuiles qui exigent un `Referer`** (OpenStreetMap) : jamais depuis une
  origine opaque ; elles demandent `--port-widgets`, qui n'a pas d'équivalent
  derrière l'Atelier (un seul hôte des applications). Les serveurs de tuiles
  sans cette exigence (OpenFreeMap, IGN) passent par la liste blanche.
- Propositions de réseau : heuristiques (adresses citées par le code, moins
  une liste d'hôtes de documentation) ; bruyantes pour les grosses
  bibliothèques (Atlas : 40 origines proposées). Rien n'est accordé d'office.
- Pas de `init --recuperer-widgets`, ni `widgets recuperer --tout` (la
  commande prend tout par défaut, `--section` restreint) ; pas de
  `/api/admin/*` (L6).
- **L5** : la conception mettait le dossier d'application à la racine de
  `artifacts/<nom>/` et la commande `python -m lecteur_grist serve
  artifacts/<nom>` ; déployé : dossier `artifacts/<nom>/dossier/` (le
  dossier de l'artefact porte `artefact.json` et `.auteur`, écrits par
  l'Atelier), `repertoire: ../../serveur` et `../.venv/bin/python` (le
  paquet n'est pas installé dans le venv) ; `--entete-utilisateur` est un
  synonyme de `--entete`. Démarrage à froid mesuré : 1,1 s (estimé 1–5 s).
- **L'exemple CRESO embarqué n'a pas été remplacé** : c'est un sous-ensemble
  SQLite fait à la main (ni `schemaVersion`, ni `_grist_Pages`), que le
  moteur ne sait migrer depuis aucune version supposée (1 à 40). En
  produire un vrai export demande de reconstruire le document dans Grist à
  partir de ses données : ni facile ni sûrement fidèle ; laissé en l'état.

### Non vérifié

- Le lecteur servi par l'Atelier dans un navigateur ouvert par la personne
  (le parcours a été fait par Chrome sans tête dans le pod, cookie
  d'applications posé par DevTools, et par requêtes ; pas par l'interface
  de l'Atelier et son bouton « Ouvrir »).
- Atlas de Saint Martin dans l'artefact (le document n'est pas dans le
  pod) ; widgets servis par un sous-domaine réel (`--port-widgets` : en
  localhost seulement).
- Écriture sur 🟢CRM (111 Mo) dans Chrome ; charge soutenue (au-delà de deux
  clients et 40 actions) ; long fonctionnement (rétention sur plusieurs
  jours : testée avec des dates simulées).
- Pièces jointes, `REQUEST()`, documents `onDemand`, stockage avant 7.
- Règles avec partages (`_grist_Shares`), `user.LinkKey`, `user.UserID` ;
  cellules de commentaires censurées sur un document qui en a (aucune
  fixture ni document réel n'en avait) ; règles changées par un renommage
  dans le même lot (couvert par le code, pas par le test différentiel).
- Connexion par mot de passe derrière HTTPS (cookie `Secure`) : seulement en
  localhost ici.

### Recommandation pour la suite

L3 et L5 tiennent : l'application tourne derrière l'Atelier, propriétaire
seul, widgets compris. **L7** (public, OIDC, revue de sécurité) attend les
décisions de Nicolas : client OIDC SSPCloud, image et chart, et pour les
widgets un **sous-domaine distinct** (seule façon d'offrir une vraie origine
aux widgets, donc les tuiles à `Referer` et `getAccessToken` en appel
direct). Décisions qui reviennent à l'Atelier, relevées ici : un hôte des
widgets à côté de l'hôte des applications, ou l'acceptation d'une requête
porteuse d'un jeton de widget sans cookie sur `/api/docs/*`. À traiter au
passage : parseStrings complet, pièces jointes, commentaires sous règles.
