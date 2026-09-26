# L'Assistant de l'Atelier — cadre de la réflexion

Document de cadrage du 25/09/2026, commun aux équipes de réflexion sur l'Assistant.
**Réflexion, rien n'est implémenté.** L'implémentation viendra quand la vision d'ensemble
(`synthese.md`) sera validée.

## L'idée (Nicolas)

L'Assistant est le **chef d'orchestre** de l'Atelier de la personne. Il a une vue globale et
précise de tout son Atelier, et il est à son service complet.

- **Où il vit** : dans le dépôt mémoire wikichat (`wikichat-memory`), comme le prévoit
  `docs/atelier-wikichat-alignment.md`. Il a un harness adapté à son rôle.
- **Ses outils** : il n'a pas tous les outils de l'Atelier, contrairement aux agents code. Il a
  **ses outils dédiés** du serveur MCP `atelier`.
- **Son contexte** : en toutes circonstances, il dispose d'un contexte de l'Atelier à la fois
  **détaillé et synthétique**. Ce contexte lui vient de wikichat et des mécanismes de l'Atelier.
- **Son public** : il sert une personne « grand public » (voir `relecture-grand-public.md`).
- **Sa contrainte** : les modèles opérés sur SSPCloud (`qwen3-*`, fenêtre de 131 072 jetons,
  pas d'API Anthropic). Son harness doit être optimisé pour eux.
- **La boucle vertueuse** : par son fonctionnement, l'Assistant alimente lui-même son harness
  (mémoire, résumés, consignes, contexte) de manière optimale.

### Précision de Nicolas (25/09) : la porte d'entrée principale

L'Assistant est **la porte d'entrée principale de l'Atelier** pour la personne, « comme un Jarvis
complet », appuyé sur tout son Atelier. Il doit :

- **comprendre l'ensemble** de l'Atelier et les liens entre ses éléments : projets, agents,
  applications, services, connecteurs ;
- **manipuler, éditer et créer** en passant par les commandes de l'Atelier. Son harness les
  **assemble dynamiquement** selon la demande, pour qu'il traite toute demande de manière fiable
  et appropriée ;
- **créer des projets déjà cadrés** selon les spécifications de l'Atelier (structure type,
  `projet.json`, consignes, gabarits). L'outil lui facilite la configuration : c'est l'outil qui
  applique les règles, pas le modèle qui s'en souvient ;
- **créer des agents**, dédiés à un projet, liés à plusieurs, ou indépendants ;
- **servir d'assistant principal** : c'est lui qu'on sollicite d'abord, et il mobilise le reste.

« Jarvis » est une illustration, pas une spécification. Elle désigne un assistant complet qui :

- comprend les besoins de la personne ;
- réutilise et capitalise les informations et les conversations, et les exploite ;
- mène des tâches avec autonomie.

Ces capacités ne viennent pas de l'Assistant seul : **c'est l'Atelier au complet qui les lui
donne**. Mémoire et coordination viennent de wikichat, le reste des éléments suivants :

- les gardiens ;
- les agents code ;
- les tâches automatiques ;
- le panneau ;
- les connecteurs et les applications.

L'Assistant en est l'interface.

**La voix.** L'Assistant est aussi la porte d'entrée du service vocal en construction dans
l'Atelier. Ce service STT/TTS doit permettre de converser en visio avec un agent. Ici, cet agent
est l'Assistant, et la conversation doit être fluide et naturelle. Ce qui existe est décrit dans
`docs/consignes/stt-tts-atelier.md` ; l'audit du 24/09 le résume ainsi :

- seule base existante : `voice_service.py` du projet `nouveau-projet-2`, qui écoute sur
  127.0.0.1:18920, sans authentification ;
- l'ancien module `voice/` ne compile pas.

La voix impose ses propres contraintes :

- latence de la première parole ;
- réponses courtes, pensées pour l'oral ;
- tours de parole et interruption ;
- continuité entre la voix et l'écrit ;
- transcriptions capitalisées comme les autres conversations.

**Voix et vues diffusées : un même modèle.** La visio avec l'Assistant rejoint les services et
fenêtres diffusés du panneau (`panneau.md`) : bureaux Blender et QGIS, navigateur de l'agent, n8n
et applications. On doit donc envisager un seul modèle :

- La visio est elle-même une vue du panneau.
- Pendant la conversation, l'Assistant ouvre, montre et commente des vues diffusées, comme un
  partage d'écran dans les deux sens : la personne montre, l'Assistant montre.
- Le même chemin sert partout : l'hôte des applications, les relais WS, et `atelier_montrer`.
- Le même contrat de vue s'applique, celui de MCP Apps.
- Le son et l'image sont des flux de plus dans ce modèle, pas un système à part.

## Ce qui existe déjà (à lire)

- `docs/atelier-wikichat-alignment.md` :
  - Assistant (`kind=assistant`) et agent code (`kind=code`) ;
  - slug canonique `wikichat-memory` ;
  - sessions dans `assistant/sessions/<uuid>/` ;
  - binding MCP de niveau 2 ;
  - synchronisation `~/.wikichat` ↔ dépôt jamais activée.
- `docs/archives/shell-unifie-2026-08/specs/2026-08-29-atelier-shell-unifie-design.md` : l'interface à vues
  Code / Assistant / Connecteurs / Agent.
- `docs/coherence-projet.md` : une seule source par sujet ; les lots A à H (B : `SessionStart`
  et `contexte.md` ; C : une identité par conversation ; D : lancements par l'Atelier) ; la
  compaction native par le relais LLM.
- wikichat, branche `atelier-coherence` (dans son propre worktree) : hooks `SessionStart`,
  `UserPromptSubmit` et `Stop`, briefing plafonné, fils de dialogue, suivi de projet lu dans
  les fichiers (`docs/hooks-et-dialogue.md`).
- Vision : `synthese.md`, `panneau.md`, `ecosysteme.md`, `gardiens.md`,
  `coherence-croisee.md`, `relecture-grand-public.md`.
- Mesures connues sur les modèles SSPCloud :
  - `usage` vide en streaming, corrigé par le relais LLM ;
  - `count_tokens` absent ;
  - WebSearch simulé, désormais refusé ;
  - un bloc de thinking long, d'où `MAX_THINKING_TOKENS=0` ;
  - `gemma4` cassé ;
  - 24 outils Chrome = environ 5 700 jetons par appel ;
  - pas de tool search avec un `ANTHROPIC_BASE_URL` personnalisé.
- Code de l'Atelier : `atelier-src/mcp_gateway/atelier/` (outils `atelier_*`, harness,
  `mcp_sync.py`, `coherence.py`, relais LLM).

## Principes

Ce sont ceux du `cadre.md` : simple d'abord, natif et standard, un seul modèle pour plusieurs
usages, construire sur l'existant, sûr par construction, sobre. Trois principes s'y ajoutent :

1. **Mesurer avant d'affirmer** : ce que supportent réellement les modèles opérés (nombre
   d'outils, longueur de contexte utile, suivi de consignes, délégation) se mesure. Toute
   affirmation non mesurée est marquée comme hypothèse.
2. **L'Assistant agit par les commandes de l'Atelier** : il crée, configure et modifie les objets
   de l'Atelier (projets, agents, connecteurs, applications, tâches automatiques) par des outils
   qui appliquent les règles. Le travail long de code dans un dépôt, il le confie à un agent code,
   le suit et en rend compte. Il ne remplace pas les gardiens (le code qui vérifie). Où passe la
   frontière entre ce qu'il fait lui-même et ce qu'il confie : c'est une question à instruire.
3. **Le contexte se prépare hors du modèle** : ce que l'Assistant doit savoir, du code et
   wikichat le calculent et le résument. Le modèle ne le recalcule pas à chaque tour.

## Format de rendu

Chaque équipe rend un document `docs/vision/assistant-<theme>.md`, au format du `cadre.md` :

1. le problème ;
2. l'existant ;
3. la proposition ;
4. les parcours ;
5. les étapes ;
6. les risques et questions ;
7. l'évaluation.

Plus de 450 lignes, c'est trop. Chaque document distingue ce qui est **mesuré** de ce qui est
**supposé**.
