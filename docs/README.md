# Documentation de l'Atelier

Par où commencer, selon ce que vous venez faire. Le code fait foi : quand un
document le contredit, c'est le document qui a tort, et
[`fonctionnalites.md`](fonctionnalites.md) est le guide tenu à jour contre lui.

## Pour utiliser

| Document | Contenu |
|---|---|
| [`fonctionnalites.md`](fonctionnalites.md) | **le guide de référence** : chaque fonctionnalité, à quoi elle sert, comment s'en servir (la personne et un agent), ce qu'elle ne fait pas, son code et son statut |
| [`structure-projet.md`](structure-projet.md) | la structure type d'un projet (`CLAUDE.md`, `ETAT.md`, `.atelier/projet.json`) et la migration d'un projet ancien |

## Pour installer et exploiter

| Document | Contenu |
|---|---|
| [`installer.md`](installer.md) | installer l'Atelier sur son pod SSPCloud : catalogue Onyxia, terminal, Helm, chemin de secours ; réglages par variables d'environnement |
| [`../SECURITY.md`](../SECURITY.md) | le modèle de sécurité : ce qui est exposé, ce qui protège, où vivent les secrets, ce qui reste ouvert, comment signaler une faille |
| [`../charts/atelier/values.yaml`](../charts/atelier/values.yaml) | les valeurs du chart, commentées |

## Pour contribuer

| Document | Contenu |
|---|---|
| [`../CONTRIBUTING.md`](../CONTRIBUTING.md) | lancer la suite, conventions, comment proposer un changement |
| [`ui/guide-interface.md`](ui/guide-interface.md) | les règles de l'interface : jetons, thèmes, composants, fil, accessibilité |
| [`ui/audit.md`](ui/audit.md) | l'audit de l'interface du 26/09 et ses corrections, captures [`ui/avant/`](ui/avant/) et [`ui/apres/`](ui/apres/) |
| [`atelier-applications.md`](atelier-applications.md) | les créations : hôte des applications, supervision, mandataire, codes de passage |
| [`navigateur-atelier.md`](navigateur-atelier.md) | le navigateur des agents, l'écran en direct, « Prendre la main » |
| [`atelier-vscode-passage-de-main.md`](atelier-vscode-passage-de-main.md) | comment une conversation s'ouvre dans VS Code, et pourquoi c'est indirect |
| [`onyxia-projet.md`](onyxia-projet.md) | Onyxia lié au déploiement d'un projet, et le mandataire qui borne ses outils |
| [`atelier-mcp-distant.md`](atelier-mcp-distant.md) | l'Atelier comme connecteur MCP d'un client distant : décisions D1 à D10, lots livrés |
| [`consignes/`](consignes/README.md) | les consignes des agents : le socle commun (dans le code) et des exemples de consignes de projet |

## Conception et vision

| Document | Contenu |
|---|---|
| [`vision/cadre.md`](vision/cadre.md) | les principes de la réflexion |
| [`vision/synthese.md`](vision/synthese.md) | la vision d'ensemble |
| [`vision/architecture-transverse.md`](vision/architecture-transverse.md) | les structures communes, le catalogue des briques, les tensions |
| [`vision/assistant-synthese.md`](vision/assistant-synthese.md), [`vision/assistant-role.md`](vision/assistant-role.md) | l'Assistant : cible et expérience |
| [`vision/panneau.md`](vision/panneau.md) | le panneau et les bureaux relayés |
| [`vision/gardiens.md`](vision/gardiens.md) | les gardiens et les réparateurs |
| [`vision/ecosysteme.md`](vision/ecosysteme.md), [`atelier-hebergement.md`](atelier-hebergement.md) | familles de projets, brouillon, installation et partage (non construits) |
| [`vision/voix.md`](vision/voix.md) | l'étude de la voix (STT et TTS) |

## Décisions

| Document | Contenu |
|---|---|
| [`vision/decisions.md`](vision/decisions.md) | le registre des décisions : ce qui est tranché, ce qui attend |
| [`vision/profils-acces.md`](vision/profils-acces.md) | le contrat des profils d'accès : qui reçoit quels outils |
| [`vision/outils-profils-et-auto-evolution.md`](vision/outils-profils-et-auto-evolution.md) | audit des outils, hooks, wikichat, Onyxia et compositions ; cadre cible (profils nommés, supervision, l'Atelier qui s'améliore lui-même) et ordre de réalisation |
| [`vision/kit-atelier.md`](vision/kit-atelier.md) | le kit commun de l'Atelier : commandes `/verifier`, `/reprendre`…, hooks `PostToolUse` et garde d'édition, sous-agents ; mesures sur le CLI en headless et ordre de réalisation |
| [`vision/etat-des-lieux-et-roles.md`](vision/etat-des-lieux-et-roles.md) | l'état des lieux du 11/10 (ce qui marche, ce qui ne tient pas, vérifié sur le code et le pod) et le plan pour que chaque rôle d'agent reçoive, par les mécanismes natifs de Claude Code, ce qu'il lui faut : un rôle = une définition compilée, preuve à chaque tour, plancher dans l'image, jeton par conversation, kit |
| [`vision/registre-des-defauts.md`](vision/registre-des-defauts.md) | le registre des défauts du 11/10 (≈ 50 défauts classés, avec preuve, zone de code et statut vérifié/rapporté), la synthèse des causes, et le principe de correction : le natif de Claude Code d'abord, puis le harnais de l'Atelier (hooks, indices, contexte), en une seule chaîne par rôle |
| [`vision/attendre-sans-refuser.md`](vision/attendre-sans-refuser.md) | la conception « attendre sans refuser » : veille et reprise d'un tour en attente d'une réponse, notifications PWA avec réponse depuis la notification, cadre des rôles (d'office / à demander / interdit), projets d'essai |
| [`vision/harnais-et-serveur-mcp.md`](vision/harnais-et-serveur-mcp.md) | l'Atelier à la fois harnais installé et serveur MCP, tout par les primitives de Claude Code : réglages gérés, hooks (http, mcp_tool), skills, sous-agents, plugin, prompts / ressources / élicitation MCP, jeton par conversation, modèles, environnements auto-hébergés ; essais à faire sur le pod et ordre proposé |
| [`vision/cadrage-des-agents.md`](vision/cadrage-des-agents.md) | cadrer les agents : espaces (dossier, dépôt, projet, session) et harnais par défaut selon le type d'agent, guides d'intention (publier, application, navigateur, mémoire, pod), grille application locale ou pod, contrat de requête et de réponse entre agents, périmètre (surfaces, plan de contrôle), connexions, lots de mise en œuvre |
| [`vision/organisation-cible.md`](vision/organisation-cible.md) | l'organisation cible du pod et de ses volumes (plan de contrôle et plan d'exécution séparés, état et projets sur deux volumes sauvegardés, budget global de capacité, déploiement qui ne détruit rien), l'état mesuré du 11/10, et les étapes pour y arriver avec preuve et retour arrière |
| [`vision/gpu-arbitrage.md`](vision/gpu-arbitrage.md) | protocole commun pour le GPU partagé du namespace : bail, priorités, préemption coopérative, compensation des échecs ; à proposer à la Passerelle et aux autres services |

## Historique

| Document | Contenu |
|---|---|
| [`../CHANGELOG.md`](../CHANGELOG.md) | les étapes du projet, vague par vague |
| [`archives/`](archives/README.md) | les traces de travail rangées : cadrages, plans, journaux de chantier, premières captures |
