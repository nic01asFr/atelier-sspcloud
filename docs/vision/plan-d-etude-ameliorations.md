# Plan d'étude des pistes d'amélioration

*Écrit le 30/10/2026, après une relecture statique du dépôt (code, chart, CI, docs). Rien n'a été
exécuté : l'installation des dépendances et le lancement de la suite de tests ont été refusés dans
l'environnement de revue. Les constats sont donc des **lectures** ; ceux dont le chiffre ou le
comportement doit encore être mesuré sont marqués « à mesurer ».*

Chaque piste a la même forme : ce qu'on a constaté, la **question** qui reste ouverte, la
**méthode** pour y répondre, la **mesure** qui tranche, et le **livrable**. L'effort est
indicatif : S (≤ ½ jour), M (1–2 jours), L (plus). Les numéros D-xx renvoient au
[registre des défauts](registre-des-defauts.md), les Lots à
[l'état des lieux](etat-des-lieux-et-roles.md).

## 0. Ce que cette branche corrige déjà

| Point | Changement | Reste à faire |
|---|---|---|
| `is_internal_request` | `ipaddress` : loopback, `10/8`, `172.16/12`, `192.168/16` ; plus tout `172.*` | lancer `tests/test_adresse_interne.py` (écrit, non exécuté) |
| Lecture des secrets | `deny` sur `Read(//…/secrets/**)` dans `refuser_les_outils_simules`, donc sur chaque tour, VS Code, terminal, wikichat et la cohérence | lancer les tests ; mesurer l'effet sur un pod (§1.2) |
| wikichat non épinglé | `WIKICHAT_REF` = SHA `818e940…` ; récupération du commit par `git fetch` | construire l'image ; la fumée de la CI vérifie `server.mjs` |
| `securityContext` | `security.containerSecurityContext` (valeurs), par défaut sans élévation de privilèges ni capabilities | essai sur un pod Onyxia (§2.2) |

Ce que ces correctifs **ne ferment pas** : le `deny Read` n'arrête pas un `cat` passé par Bash
(le garde-fou Bash est le travail du Lot 4, §1.3) ; `drop: ALL` et `allowPrivilegeEscalation:
false` peuvent gêner un outil de l'image qui s'appuie sur `sudo` ou `setuid` : aucun usage n'a été
trouvé dans le code, mais l'image Onyxia de base n'a pas été inspectée.

## 1. Sécurité et fiabilité

### 1.1 Lots 2–3 de la feuille de route (rôles, `dontAsk`, plafonds)
- **Constat.** Pas de `roles.py`, de plancher managé, de `--max-budget-usd` ni de `dontAsk` dans le
  code. Le Lot 1 n'existe qu'en contrôle quotidien (`coherence.py`).
- **Question.** Où le mode de permission est-il recalculé aujourd'hui, et combien de sites
  divergent ? Un agent non supervisé peut-il encore attendre une réponse qui ne vient pas (D-01) ?
- **Méthode.** `grep` des sites qui écrivent `permission-mode` / `--settings` (harness,
  lancements, vscode_handoff, coherence) ; tableau « surface × rôle × mode obtenu » ; un lancement
  réel par rôle sur un pod, avec la sortie `system/init`.
- **Mesure.** Nombre de sites ; écart entre mode attendu et mode observé ; durée de blocage d'un
  agent sans réponse.
- **Livrable.** Tableau dans l'état des lieux, puis spec de `roles.py` (une table, un lecteur).
  *Effort L.*

### 1.2 Clé propriétaire lisible par les agents
- **Constat.** `ATELIER_OWNER_KEY` est dans l'environnement et dans `secrets/` ; `SECURITY.md` le
  reconnaît. Le `deny Read` ajouté couvre l'outil `Read`.
- **Question.** Quels chemins restent ouverts : `Bash(cat)`, `Grep`, `Glob` ? `/proc/self/environ` ?
  Le `deny` est-il bien honoré en mode `bypassPermissions` sur la version du CLI installée ?
- **Méthode.** Sur un pod, par conversation : demander à l'agent de lire le fichier par chaque
  outil ; consigner ce qui passe. Vérifier la syntaxe `//chemin` dans la documentation du CLI.
- **Mesure.** Tableau outil → bloqué / passe.
- **Livrable.** Section de `SECURITY.md` mise à jour, avec les chemins qui restent ouverts. *Effort S.*

### 1.3 Lot 4 : jeton court par conversation
- **Question.** Peut-on remplacer la clé unique par un jeton lié à la conversation, à durée
  courte, sans casser les hooks, `headersHelper` et les agents lancés ?
- **Méthode.** Inventaire des consommateurs de la clé (grep `ATELIER_OWNER_KEY`, `Authorization`) ;
  schéma de jeton (HMAC du secret interne + id de conversation + expiration) ; maquette sur un
  endpoint.
- **Mesure.** Nombre de consommateurs à migrer ; ce qu'un jeton volé permet (périmètre, durée).
- **Livrable.** Note de conception (à part, c'est le plus délicat). *Effort L.*

### 1.4 Identifiants des connecteurs en clair dans `gateway.db`
- **Question.** Quel gain réel d'un chiffrement au repos, sachant que l'attaquant qui exécute du
  code sur le pod lit aussi la clé ? Où vit la clé de dérivation ?
- **Méthode.** Lister les colonnes concernées ; modèle de menace (sauvegarde du volume, copie,
  accès pod) ; essai de chiffrement avec clé dérivée de la clé owner et rotation.
- **Mesure.** Cas de menace couverts / non couverts ; coût d'une rotation de clé owner.
- **Livrable.** Décision écrite dans `docs/vision/decisions.md`. *Effort M.*

## 2. Chaîne de build et déploiement

### 2.1 Reproductibilité de l'image
- **Constat.** `image.tag: latest` + `pullPolicy: Always` ; dépendances Python en `>=` sans verrou ;
  base Onyxia sans digest. wikichat est désormais épinglé (§0).
- **Question.** Qu'est-ce qui a changé entre deux builds à une semaine d'écart ?
- **Méthode.** Deux builds du même commit à une semaine d'écart, `pip freeze` et `docker history`
  comparés ; lister ce qui dérive.
- **Mesure.** Nombre de paquets qui changent de version ; changements de la base.
- **Livrable.** `requirements.lock` (uv ou pip-compile), digest de base, tag semver publié à côté de
  `latest`, procédure de retour arrière. *Effort M.*

### 2.2 `securityContext` du conteneur
- **Question.** Quels outils échouent sous `drop: ALL` / `allowPrivilegeEscalation: false`, puis
  sous `seccompProfile: RuntimeDefault` et `runAsNonRoot` (avec un `runAsUser` numérique) ?
- **Méthode.** Un pod d'essai par réglage ; démarrer code-server, Chrome (capture d'écran),
  wikichat, un `git push`, une installation `pip`.
- **Mesure.** Tableau réglage × outil → ok / échec + message.
- **Livrable.** Valeurs par défaut durcies au maximum que le tableau permet. *Effort M.*

### 2.3 NetworkPolicy
- **Constat.** Ingress limité à 4 `ipBlock /32` codés en dur ; aucune règle d'egress.
- **Question.** D'où viennent réellement les connexions entrantes (ingress controller) et vers où
  sortent les agents (passerelle LLM, GitHub, PyPI, npm, connecteurs) ?
- **Méthode.** Journal des connexions d'un pod pendant une journée ; liste des destinations ;
  essai d'un egress en liste blanche sur un pod d'essai.
- **Mesure.** Destinations observées ; ce qu'un egress strict casse.
- **Livrable.** Sélecteur de l'ingress controller au lieu des `/32` ; egress documenté, activable. *Effort M.*

### 2.4 Dépendances et image : veille automatique
- **Question.** Quel est le bruit d'un Dependabot sur ce dépôt (Python, npm, Actions, Docker) ?
- **Méthode.** Activer `dependabot.yml` sur un seul écosystème pour une semaine ; ajouter
  `pip-audit` et Trivy en mode informatif dans la CI.
- **Mesure.** Nombre de PR et de vulnérabilités ; temps de revue.
- **Livrable.** Configuration retenue, seuils qui font échouer la CI. *Effort S–M.*

## 3. Qualité du code et CI

### 3.1 Linter et vérificateur de types
- **Constat.** Pas de ruff ni de mypy dans `pyproject.toml`.
- **Question.** Combien de violations avec un jeu de règles raisonnable (`S`, `ASYNC`, `BLE`,
  `B`, `UP`) ?
- **Méthode.** `ruff check --statistics` sans rien corriger ; `mypy --ignore-missing-imports` sur
  deux ou trois modules.
- **Mesure.** Violations par règle ; part corrigeable automatiquement.
- **Livrable.** Configuration dans `pyproject.toml`, base de référence figée (`--add-noqa` ou
  fichier de base) pour que la CI n'échoue que sur le nouveau. *Effort M.*

### 3.2 Versions de Python testées
- **Constat.** Une seule version en CI (3.13) ; `requires-python >= 3.10`.
- **Question.** Le code tourne-t-il vraiment sous 3.10 à 3.12 ? L'image est en 3.13.
- **Méthode.** Matrice CI 3.10–3.13 sur une branche d'essai.
- **Mesure.** Échecs par version.
- **Livrable.** Matrice, ou relèvement de `requires-python`. *Effort S.*

### 3.3 Fichiers monolithiques
- **Constat (vérifié).** `api.py` 3 063 lignes, `sessions.py` 1 983, `lancements.py` 1 673,
  `harness.py` 1 642.
- **Question.** Où sont les coutures : combien de routes par famille dans `build_app`, quelles
  dépendances partagées ?
- **Méthode.** Compter les routes par préfixe ; cartographier les fermetures partagées dans
  `build_app` ; essayer un découpage en `APIRouter` pour une seule famille.
- **Mesure.** Routes par famille ; lignes déplacées sans changer un test.
- **Livrable.** Plan de découpage par routeur, puis un premier routeur extrait. *Effort M–L.*

### 3.4 `except Exception`
- **Constat (vérifié).** 156 occurrences hors tests.
- **Question.** Lesquelles masquent une erreur sur un chemin de sécurité, de journal ou de
  persistance ?
- **Méthode.** Classer chaque occurrence : journalise / relance / avale en silence ; priorité aux
  silencieuses dans `auth`, `gardiens`, `persistence`, `coherence`.
- **Mesure.** Nombre d'occurrences silencieuses par module.
- **Livrable.** Liste classée ; corrections par lots. *Effort M.*

### 3.5 Appels bloquants
- **Question.** Quels `subprocess.run` / `time.sleep` s'exécutent dans la boucle d'événements, et
  lesquels dans un thread ?
- **Méthode.** Pour chaque appel bloquant, remonter jusqu'à la route ou la tâche ; distinguer
  `def` (exécuté dans le pool de threads par FastAPI) de `async def` ; mesurer la latence d'une
  route légère pendant un appel bloquant.
- **Mesure.** Appels bloquants sous `async def` ; latence p95 d'une route pendant l'appel.
- **Livrable.** Liste des seuls appels à déplacer (`asyncio.to_thread`). *Effort M.*

## 4. Coût et performance des agents

### 4.1 Contexte de 35–38 k jetons et cache de préfixe (D-41)
- **Question.** La passerelle SSPCloud accepte-t-elle le cache de préfixe ? Quel est le préfixe
  réellement stable d'un tour à l'autre ?
- **Méthode.** Deux requêtes successives au préfixe identique ; lire `cache_read_input_tokens` ;
  diffs de la requête entre deux tours pour trouver ce qui change en tête.
- **Mesure.** `cache_read_input_tokens` ; jetons du premier tour par composante (système, outils,
  consignes, mémoire).
- **Livrable.** Tableau de répartition du contexte ; réordonnancement si le cache est supporté. *Effort M.*

### 4.2 Skills et commandes plutôt que `CLAUDE.md` gonflé
- **Question.** Combien de jetons le kit (`/reprendre`, `/verifier`…) retire-t-il du premier tour ?
- **Méthode.** Mesurer le contexte avec et sans une consigne déplacée en skill (chargée à la demande).
- **Mesure.** Jetons du premier tour ; taux de déclenchement du skill.
- **Livrable.** Premier skill migré, mesure avant/après. *Effort M.*

### 4.3 Estimation caractères/jetons de la compaction
- **Question.** De combien l'estimation du relais s'écarte-t-elle du compte réel ?
- **Méthode.** Comparer l'estimation à `usage.input_tokens` sur un échantillon de tours.
- **Mesure.** Écart relatif moyen et maximal, par langue (français, code).
- **Livrable.** Coefficient calibré. *Effort S.*

## 5. Structure du dépôt

### 5.1 Laboratoire ML dans le dépôt de l'Atelier
- **Question.** Quels fichiers de `labo/` sont importés par l'Atelier, et l'inverse ?
- **Méthode.** Graphe d'imports entre `labo/` et `atelier-src/` ; workflows partagés.
- **Mesure.** Nombre d'arêtes entre les deux.
- **Livrable.** Si zéro ou peu : plan de séparation. *Effort S (étude).*

### 5.2 Poids de `docs/` (≈ 12 Mo)
- **Question.** Quelles images pèsent, lesquelles sont encore référencées ?
- **Méthode.** `du` par dossier, `grep` des références ; test de compression (WebP/PNG optimisé).
- **Mesure.** Mo récupérables sans changer le rendu.
- **Livrable.** Liste des fichiers à compresser ou à déplacer vers les releases/Pages. *Effort S.*

### 5.3 Release taguée
- **Constat.** « 0.3.0 non publiée » dans le `CHANGELOG`.
- **Question.** Qu'est-ce qui reste avant de publier : le registre des défauts, le Lot 1 ?
- **Livrable.** Critères de publication écrits ; tag `v0.3.0` et image semver (liée à §2.1). *Effort S.*

## 6. Ordre proposé

1. Lancer les tests de cette branche et corriger ce qu'ils révèlent (§0).
2. Études rapides qui débloquent des décisions : §1.2, §2.2, §3.2, §4.3, §5.2.
3. Mesures qui orientent le coût : §4.1, §3.1, §3.4.
4. Chantiers : §1.1 (Lots 1–2), §2.1, §3.3.
5. Conception à part : §1.3 (Lot 4), §1.4.
