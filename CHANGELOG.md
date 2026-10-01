# Journal des modifications

Ce journal suit les étapes du projet plutôt que des versions : le service est
publié en continu (image `ghcr.io/nic01asfr/atelier:latest`, tirée à chaque
démarrage du pod). Depuis la 0.3.0, le service (`/v1/health`), le paquet
Python et le chart Helm portent le même numéro, écrit à un seul endroit
(`atelier-src/mcp_gateway/atelier/__init__.py`) ; jusque-là, seul le chart en
avait un. Chaque étape renvoie au chart qui l'a accompagnée quand il y en a un. Le détail des vagues
est dans [`docs/archives/vision/plan-implementation.md`](docs/archives/vision/plan-implementation.md)
§5 ; celui de chaque fonctionnalité, dans [`docs/fonctionnalites.md`](docs/fonctionnalites.md).

Les dates sont celles de l'intégration dans le dépôt, en 2026.

## Version 0.3.0 : publication (non publiée)

- une seule version pour le service, le paquet et le chart (0.3.0) ;
- image redistribuable : le navigateur sans écran et l'extension Claude Code
  sont téléchargés depuis leur source au premier démarrage, puis gardés sur
  le volume ; seules les bibliothèques système du navigateur restent dans
  l'image ;
- retrait de `deploy-patches/`, `wikichat-atelier/` et du miroir de transition
  `helm-repo/` : le dépôt Helm n'est plus servi que par GitHub Pages ;
- fil : le raisonnement n'occupe plus une ligne quand son affichage est coupé,
  et les preuves des cartes d'action se lisent sans JSON brut ; celui-ci reste
  disponible sous « Détails techniques » ;
- panneau : la politique CSP autorise le widget Atlas servi par
  `https://nic01asfr.github.io` dans une iframe, tout en continuant d'interdire
  l'encapsulation de l'Atelier par un autre site ;
- panneau : la même politique nomme aussi l'hôte des applications dans
  `frame-src`. Sans lui, le navigateur refusait le 302 de `/v1/apps/…/ouvrir`
  et le cadre des créations et de l'écran du navigateur restait vide, alors
  que le service répondait ;
- agents et créations : l'Assistant montre la création d'un autre projet
  (`atelier_montrer(projet, nom)`) ; il n'écrit pas de fichiers, donc
  `atelier_artefact_creer` et `atelier_navigateur_ouvrir` lui sont refusés avec
  la voie à suivre (déléguer à un agent code), au lieu de laisser un dossier
  vide ; `atelier_artefact_verifier` et `atelier_montrer` rendent des
  `avertissements` pour une page autonome (index absent, fichier introuvable,
  chemin absolu, ressource externe bloquée) ; les consignes disent qu'il n'y a
  aucun bouton « Exposer ».

Préparation de la publication du dépôt :

- vitrine refaite (capacités, cas d'usage pas à pas, associations entre
  briques, captures réelles dans les deux thèmes), README en français et en
  anglais, index de la documentation ;
- traces de travail rangées sous `docs/archives/`, adresses de pod et chemins
  personnels neutralisés dans la documentation et les captures ;
- `SECURITY.md` remis d'accord avec le code, signalement privé des failles ;
- `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `.editorconfig`, vérification des
  liens de la documentation en CI ;
- `install.sh` rangé dans `install/` (l'adresse publiée ne change pas).

## Vague 4 : socle, voix, interface (26 septembre)

- **Interface reprise** : thèmes clair et sombre sur une table de jetons unique,
  fil en étapes lisibles (« Voir les étapes »), ouverture d'une conversation en
  25 ms au lieu de 4 s, navigation mobile, contrastes AA, aucun emoji
  ([`docs/ui/audit.md`](docs/ui/audit.md), [`docs/ui/guide-interface.md`](docs/ui/guide-interface.md)).
- **Socle des agents** allégé et posé par le code à chaque démarrage, avec copie
  datée d'un fichier modifié à la main.
- **Contrôle quotidien de cohérence** : le gardien Cohérence lance le
  vérificateur des surfaces une fois par jour.
- **Mémoire** : plafond de sortie du résumé relevé à 1 200 jetons.
- **Voix** : étude d'intégration ([`docs/vision/voix.md`](docs/vision/voix.md)) ;
  rien n'est encore dans l'interface.

## Vague 3 : Assistant, navigateur en direct, mémoire (26 septembre)

- **L'Assistant** : profil `assistant`, méta-outils `gateway_find_tools` et
  `gateway_call_tool`, contexte toujours présent (carte, commandes, « À
  valider »), cartes d'action construites par les commandes, délégation par
  `atelier_lancer_agent` (engageante).
- **Navigateur de l'agent en direct** : Chrome possédé par l'Atelier, écran
  dans le panneau, « Prendre la main », refus d'une action devenue obsolète.
- **Mémoire** : fiches de conversation, `atelier_rappel` et `atelier_fiche`,
  recherche par le sens, résumé direct par l'Atelier, « Ma mémoire », filtre
  des secrets dans les transcripts.

## Vague 2 : relier (26 septembre)

- Gardiens montrés comme des agents spécifiques dans la vue Agents ; toutes
  les tâches automatiques dans la même vue ; écrans « À valider » et Journal.
- Carte de l'Atelier (`GET /v1/carte`, `atelier_carte`), assemblée avec la
  cartographie de wikichat.
- Lancements d'agents par l'Atelier pour wikichat et les gardiens, avec
  plafonds ; réparateurs des gardiens sur branche.
- Commandes de création : agents, connecteurs, liens entre projets.
- Bureaux du namespace (QGIS, Blender, n8n) relayés dans le panneau.

## Lot « profils » (26 septembre)

- Profils d'accès filtrés à la source (`code`, `assistant`) ; mêmes outils sur
  toutes les surfaces (interface, VS Code, terminal) ; Onyxia lié au
  déploiement déclaré d'un projet ; vérificateur de cohérence des surfaces.

## Vague 1 : fondations (25 septembre)

- Catalogue de commandes à classes (lecture, réversible, engageante, réservée)
  et inverses ; journal unique ; file « À valider ».
- Structure type d'un projet (`projet.json`, `ETAT.md`, `CLAUDE.md`).
- Panneau à côté du fil, vues encadrables, `atelier_montrer`.
- Exécuteur des gardiens (santé, sécurité, entretien) et hook du socle qui
  refuse `pkill -f` et l'écoute sur `0.0.0.0`.
- wikichat : données sous `~/.wikichat`, cartographie publiée par API.

## Chart 0.2.0 : applications et catalogue (24 septembre)

- Hôte des applications sur un second Ingress : créations des projets servies
  en autonome ou en serveur, derrière la connexion de l'Atelier, sur une autre
  origine.
- L'Atelier comme connecteur MCP d'un client distant (OAuth, consentement par
  la clé) ; une conversation reçoit ses propres outils.
- Secrets des connecteurs gardés hors des fichiers de projet.
- Clé owner affichée là où Onyxia la copie ; dépôt Helm et vitrine publiés sur
  GitHub Pages.

## Chart 0.1.0 : entrée au catalogue Onyxia (16 septembre)

- Image `ghcr.io/nic01asfr/atelier` (node, code-server, extension Claude Code,
  wikichat), formulaire rempli depuis le profil Onyxia, volume `~/work`,
  NetworkPolicy qui ne laisse entrer que l'ingress.
- Même CLI et même mode pour une conversation, dans l'Atelier et dans VS Code.

## Août et début septembre : le service

- **Conversations** : un processus par conversation gardé entre les tours,
  messages mis en file pendant un tour, plusieurs écrans sur une même
  conversation, compaction par le relais LLM.
- **Autorisations** : le CLI demande à l'Atelier au lieu de refuser, cartes
  « Autoriser / Refuser » et questions à choix dans le fil, modes de travail
  par conversation.
- **Projets** : chaque projet est un dépôt git, publication sur GitHub par
  l'API.
- **VS Code** : la même conversation s'ouvre dans code-server, dans les deux
  sens.
- **Connecteurs** : pool MCP unifié, compositions à plusieurs étapes,
  descriptions lisibles.
- **Sécurité** : cookie de session sans la clé, clé renouvelable, clé du modèle
  hors des fichiers de réglages, point d'entrée interne gardé par un secret,
  images tierces non chargées ; licence Apache-2.0 et modèle de menace
  (31 août).
