# Profils d'accès : qui reçoit quels outils

Contrat du 26/09/2026, posé avec Nicolas après l'audit `docs/coherence-outils-audit.md`. Il
précise `architecture-transverse.md` §1.1 (acteurs) et §1.5 (outils), et il fait foi pour les
équipes du lot « profils ».

## Principe

- **Un profil par type d'acteur, identique sur toutes les surfaces.** Une conversation d'agent
  code reçoit exactement la même chose dans l'app, dans VS Code et au terminal : mêmes serveurs,
  mêmes outils, mêmes refus, mêmes hooks, même mode de permission, même version du CLI.
- **Ce qu'on voit dépend du profil, pas de la surface.**
- Un profil se **filtre à la source**, par le serveur qui expose les outils, et pas seulement par
  une consigne au modèle.
- **Voir un autre projet passe par ses agents.** Un agent code travaille dans son projet. Pour
  voir ou faire agir un autre projet, il s'adresse aux agents de ce projet par wikichat
  (message, fil). L'Assistant procède de même pour explorer ou agir : il délègue plutôt que
  d'agir directement, sauf pour les commandes de l'Atelier qui sont les siennes.
  **À revoir à l'usage.**

## Profil « agent code »

| Brique | Accès | Encadrement |
|---|---|---|
| Outils natifs de Claude Code | tous (fichiers, Bash, recherche, sous-agents, WebFetch) | WebSearch refusé ; son remplacement (navigateur, WebTools) viendra plus tard. Hook du socle actif, qui refuse `pkill -f` et l'écoute sur `0.0.0.0` |
| Connecteurs du projet | ceux que la personne a choisis pour ce projet | secrets par référence ; un connecteur en échec d'authentification n'est pas distribué |
| wikichat | **limité à son projet** : état et notes de son projet, sa mémoire, sa connaissance et celle de son projet, messagerie et fils (pour s'adresser aux agents d'autres projets) | pas de vue globale des projets, pas de lancement d'agent, pas de trigger ni de routine, pas d'audit global ; filtré par le serveur wikichat selon le profil annoncé par le pont |
| Navigateur | **sa propre fenêtre Chrome isolée**, avec les onglets qu'il veut | plafond d'onglets par conversation (performance) ; plafond global de Chrome (6) |
| Atelier | **les seuls outils de son projet** : ses créations (créer, vérifier, démarrer, arrêter, journal), `atelier_montrer`, `atelier_navigateur_ouvrir` | le serveur `atelier` en profil `code` n'expose que ces outils, bornés au projet de la conversation ; ni méta-outils, ni passerelle, ni commandes globales, ni « À valider » |
| Onyxia | **seulement par le déploiement de son projet** | voir plus bas |

## Profil « Assistant »

- **Tous les outils de l'Atelier** : le serveur `atelier` au complet, en profil `assistant`, avec
  commandes globales, carte, « À valider », journal et décider.
- **Tous les autres outils**, par les deux méta-outils de la passerelle (`gateway_find_tools`,
  `gateway_call_tool`), classes d'action vérifiées par le serveur.
- **wikichat au complet.**
- **Onyxia au complet**, pour gérer l'ensemble. À étudier au regard des usages.
- Les règles de `assistant-synthese.md` §2 s'appliquent : confirmation, inverse, preuve,
  « À valider ».

## Onyxia : lié au déploiement d'un projet

Le but : relier **de façon standard un projet à un pod** (et, s'il le faut, à un accès GPU).
L'accès d'un agent code à Onyxia est alors cadré par le fait de vouloir déployer **ce** projet.

1. Le projet déclare son déploiement dans `.atelier/projet.json`, en posant un bloc
   `deploiement` : pod ou service lié, besoin de GPU, commande de démarrage. Cette déclaration
   se fait par une commande de l'Atelier, en classe `engageante`.
2. Un agent code de ce projet reçoit les outils Onyxia **bornés à ce pod** : exécuter, lire,
   état, démarrer et arrêter son service, basculer son GPU. Il ne reçoit pas les autres pods,
   `expose_public` ni le déploiement d'un autre service.
3. Un projet sans `deploiement` : pas d'Onyxia pour ses agents.
4. L'Assistant peut tout, avec les confirmations d'usage. `expose_public` reste `reservee` pour
   tout le monde (socle).
5. Correction préalable : le serveur Onyxia ne doit plus bloquer le démarrage d'un tour.
   Aujourd'hui il ne répond pas à `initialized`, et chaque tour attend 30 s (audit G3).

## Mode de permission

- **Une seule liste** : défaut, accepter les modifications, plan, **bypass**.
- **Un défaut par projet** et **un choix par conversation** qui le remplace, écrits à un seul
  endroit que lisent l'app, VS Code et le terminal.
- Choisir bypass dans l'app le met aussi dans VS Code pour cette conversation, et inversement.
- **Aucun résidu** : ni réglage machine qui impose `--allow-dangerously-skip-permissions`, ni
  `bypassPermissions` codé en dur dans un projet.

## Vérification

- **Le vérificateur de cohérence** compare, pour chaque vrai projet et chaque surface (app,
  VS Code, terminal interactif, shell non interactif), ce que Claude Code annonce au démarrage
  (`system/init`) :
  - serveurs et outils ;
  - version ;
  - mode ;
  - modèle et effort ;
  - hooks réellement exécutables depuis le projet.
- Il compare les deux profils à ce contrat.
- Les gardiens le font tourner régulièrement, sans modèle.
