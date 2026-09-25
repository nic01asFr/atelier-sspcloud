# Décisions de la vision : registre

Ouvert le 25/09/2026. Nicolas a demandé de passer à l'implémentation une fois tout cadré. Les
questions encore ouvertes des documents de vision sont donc **adoptées par défaut selon la
recommandation qui les accompagnait**.

Chaque ligne est **révisable** : Nicolas la change ici, et l'équipe concernée suit. Une équipe qui
bute sur une décision non listée la remonte au coordinateur au lieu de trancher seule.

Statut :

- **N** : décidé par Nicolas ;
- **D** : adopté par défaut, révisable.

## Structurantes

| # | Décision | Statut | Source |
|---|---|---|---|
| S1 | L'Atelier est conçu pour les personnes qui ne codent pas comme pour Nicolas, et construit d'abord pour Nicolas | D | `synthese.md` §7 |
| S2 | Lexique d'interface de 12 mots ; les mots internes (artefact, vue, extension, famille, gabarit, composition, MCP, jeton, production) n'apparaissent jamais à l'écran | D | `synthese.md` §3 |
| S3 | Une seule file « À valider » : propositions des gardiens, des agents et des créations, mémoire proposée, décisions de l'Assistant | D | `synthese.md` §4 |
| S4 | Politique d'accord : rien en brouillon ; un geste dans le panneau vaut accord pour l'outil de ce connecteur le temps de la conversation ; un seul écran groupé à l'installation et au partage ; lecture seule par défaut | D | `synthese.md` §4 |
| S5 | Tout se base sur les briques existantes : on les structure, les organise et les expose. Deux maisons : l'Atelier pour l'état opérationnel, wikichat pour la connaissance et la coordination | N | `architecture-transverse.md` §0 |
| S6 | Le dossier de l'Assistant n'est pas un dépôt ; le dépôt GitHub `wikichat-memory` est une publication assainie | N (02/09) | `atelier-wikichat-alignment.md` §10 |

## Premiers jalons

| # | Décision | Statut | Source |
|---|---|---|---|
| J-a | L'exécuteur des gardiens est un processus à part, lancé comme le relais LLM. Il ne fait que les contrôles santé et sécurité de l'Atelier et de wikichat. wikichat ordonne tout le reste | D | `coherence-croisee.md` §5.2-a ; transverse §1.7 |
| J-b | Tâches automatiques : `max_per_day` à 24 par défaut, budget obligatoire ; un trigger créé par un agent naît désactivé | D | 5.2-b |
| J-c | La porte dormante reste pour ce qui lance un agent ; les contrôles en code n'y sont pas soumis | D | 5.2-c |
| J-d | Les services du namespace (Blender, QGIS, n8n) sont relayés par l'hôte des applications | D | 5.2-d |
| J-e | Vues épinglées : au projet dans `projet.json` (`vues_epinglees`), à la conversation dans sa fiche | D | 5.2-e |
| J-f | Le panneau s'ouvre seul pour une interface rendue par un outil et pour « Montrer », jamais pour un flux vivant | D | 5.2-f |
| J-g | `atelier-gardiens` est un projet système, avec la structure type | D | 5.3-m |
| J-h | Le navigateur d'un agent ouvre les créations de son projet par un code de passage d'agent, jamais avec le cookie de l'Atelier | D | `synthese.md` §2 (navigateur) |

## Assistant

| # | Décision | Statut | Source |
|---|---|---|---|
| A-1 | Modèle `qwen3-6-35b-moe` ; `agent` exclu ; `qwen3-8-27b` pour le fond ; `qwen3-vl` pour les captures ; `qwen3-embedding-8b` pour la recherche sémantique. L'effort `xhigh` est mesuré avant tout changement | N (orientation) + D | `assistant-synthese.md` §6.2 |
| A-2 | Outils : les méta-outils de l'Atelier (`gateway_find_tools`, `gateway_call_tool`), avec une seule porte et la classe d'action vérifiée par le serveur. Le chargement par `list_changed` reste une option, selon la mesure | N | §6.3 |
| A-3 | L'accueil devient le fil de l'Assistant, derrière un réglage pendant la transition ; « Code » devient « Projets » | D | §6.5 |
| A-4 | L'Assistant lance un agent code sans accord s'il est demandé, en brouillon et dans les plafonds, avec une carte « Arrêter » | D | §6.6 |
| A-5 | Pour les propositions : l'Assistant refuse seul, n'accepte jamais seul | D | §6.7 |
| A-6 | L'Assistant n'écrit que dans son dossier (notes de travail) ; la mémoire et les objets passent par des commandes | D | §6.8 |
| A-7 | Mémoire : les faits extraits par le code sont enregistrés d'office ; préférences et interprétations passent par « À valider ». Capitalisation nocturne plafonnée à 20 conversations de 30 000 jetons, sur `qwen3-8-27b`. Les conversations des agents code sont capitalisées en fiches de projet | D | §6.9 |
| A-8 | Voix : aucun audio conservé ; aucun accord à l'oral ; accusé en moins de 2 s, premier mot en moins de 3,5 s | D | §6.10 |

## Plus tard (non bloquant)

Ces points se trancheront avant le jalon concerné (`coherence-croisee.md` §5.3,
`relecture-grand-public.md` §5) :

- partage à des tiers après `passerelle-auth` ;
- canal de notification hors Atelier ;
- unité de dépense affichée (part du forfait) ;
- mode d'édition à la main des pages ;
- moteur des gabarits (simple copie d'abord) ;
- hooks interdits dans une extension ;
- place de marché (plugins Claude Code, sous réserve de mesure).

## En attente d'une réponse explicite de Nicolas

- Le trigger wikichat `cron-routine-4h` (routine `paradox-research`, toutes les 4 h) a été
  rattrapé au redémarrage du 25/09. Faut-il le couper comme les cinq autres ?
- Faut-il supprimer les sauvegardes `*.avant-26-09` du pod une fois l'état validé ?
- Faire tourner le jeton n8n.
