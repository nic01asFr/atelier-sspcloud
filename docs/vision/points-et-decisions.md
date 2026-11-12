# Points abordés et décisions : la synthèse

> **État au 12/11/2026.** Ce document rassemble, en un seul endroit, **ce que Nicolas a posé** pendant la relecture de l'Atelier, **tous les points abordés**, les **constats qui comptent le plus**, et **toutes les décisions encore à prendre**, dédoublonnées et regroupées. Les détails sont dans [`cible.md`](cible.md) (la cible), [`plan-de-finition.md`](plan-de-finition.md) (les lots) et [`auto-amelioration.md`](auto-amelioration.md). Rien n'est implémenté.
>
> **Comment lire.** *Posé* : décidé ou confirmé par Nicolas. *Reco* : ma recommandation, non validée. *Vérifier* : à confirmer sur le pod ou dans le code avant de s'appuyer dessus. Les constats sur le code sont des **lectures** (une seule revérifiée par moi, § 3 point 1) ; rien n'a été exécuté sur un pod.

## 1. Ce qui est posé

| # | Principe posé par Nicolas | Où |
|---|---|---|
| P1 | **Finir et mettre au propre l'Atelier actuel** avant la boucle d'auto-amélioration : tout est en place, mais des finitions et des logiques restent loin de ce qui a été posé | plan, lots 1 à 9 |
| P2 | **Tout agent de la plateforme est une session Claude Code, localisée dans un dossier sur le disque**. C'est sa nature ; la famille se lit à l'endroit où vit le dossier ; wikichat et Onyxia sont des attributs de configuration, changeants | cible § 1.0 |
| P3 | **Tout est structuré autour des fonctionnalités de Claude Code, exploitées au maximum**. On y ajoute un **cadre local wikichat** bâti sur ce fonctionnement, et des **services de base configurables selon les cas** | cible § 1.4 |
| P4 | **wikichat** : une identité par session ; disponible par défaut pour tous les agents d'un espace, dossier ou projet ; les assistants vivent dans le dossier wikichat (mémoire par défaut) ; les projets code sont des dossiers wikichat ; le lien se fait par les `.wikichat` ; les outils Onyxia sont définis par défaut pour cadrer ce fonctionnement ; des **indications contextuelles fines, potentiellement auto-apprenantes** | cible § 1.5 |
| P5 | **Deux familles d'agents** : les agents **code** (un profil attribuable au projet, modifiable par session sans impact sur les autres ni sur les défauts) et les agents **de l'Atelier** (page Agents, profils et capacités configurables, agissant sur des projets de façon cadrée) | cible § 1.2 |
| P6 | **Onyxia : accès général possible si la personne le configure explicitement**, de façon cadrée ; **élargi pour l'Assistant** | cible § 4.3 |
| P7 | **Les secrets sont confiés sans être vus** (navigateur, connecteurs) ; **la gateway doit être entièrement configurable depuis l'Atelier** | cible § 5 ter |
| P8 | **Créer, tester et rattacher des services MCP** à l'Atelier comme on crée des projets Onyxia | cible § 4.5 |
| P9 | **Gérer la connexion, l'actualisation et la reconnexion** des connecteurs streamable | cible § 4.6 |
| P10 | **Les structures Onyxia liables à un projet** (partie code) sont à cadrer | cible § 4.4 |
| P11 | **Les agents se définissent et s'utilisent en API depuis l'extérieur** ; branchement dans **Tchap** (structure inspirée de Colaig) et d'autres services de communication (**Telegram**…) sur standard | cible § 5 quinquies |
| P12 | **Toute la page Agents n'est pas Colaig** : plusieurs types d'agents ; on s'inspire de Colaig et on prévoit **un cadre d'agent de type Colaig**, optimal pour les mêmes finalités, **adapté à l'Atelier et à Claude Code** | cible § 5 sexies |
| P13 | **Les services audio / voix** sont à définir pour l'Atelier, notamment pour les agents de l'Atelier | cible § 5 quater |
| P14 | **L'intégration GitHub** actuelle est à étudier, et ce qu'elle devrait être avec les projets de l'Atelier | cible § 5 bis |
| P15 | Le **récit d'ensemble** (quatre couches, parcours d'une demande, brouillon / production, étanchéité mécanique) est confirmé : « tu as bien capté » | cible § 1 |
| P16 | **Colaig v3 est l'agent de référence** : `nic01asFr/Colaig_v3`, branche `feat/reflexive-self-config`, à lire (fait) | cible § 5 quinquies.1 bis |

## 2. Les points abordés

| Thème | Section | Ce qui existe | Lot |
|---|---|---|---|
| Nature d'un agent, familles, couches de profil | cible § 1 | deux profils par type d'acteur ; mode de permission seul à double niveau | 3 |
| Natif de Claude Code (inventaire) | cible § 1.4 | pont de permissions, `--mcp-config` strict, hooks `PreToolUse` : oui ; managés, `Stop`, skills, plugins : non | 2, 3 |
| wikichat (identité, dossier, lien) | cible § 1.5 | identité par session, Assistant dans `wikichat-memory`, projets déclarés | 3 |
| Miroir app / VS Code / terminal | cible § 2 | trois lanceurs du même `claude`, **aucun verrou entre surfaces** | 1 bis |
| Capacités des agents (navigateur, artefacts, applications, gabarits) | cible § 3 | existe en partie ; classes incohérentes ; 3 versions de gabarit | 3, 5 |
| Gateway (structure, registre, surcharge, classes) | cible § 4.1 à 4.2 | trois sources de connecteurs ; classes seulement pour `atelier_*` | 3 bis |
| Onyxia à trois niveaux, liens d'un projet | cible § 4.3, 4.4 | mandataire borné pour l'agent code ; 24 outils pour l'Assistant | 3 bis |
| Services MCP : créer, tester, rattacher | cible § 4.5 | gabarit `service-mcp` quasi vide ; pas de `source: artefact` | 3 bis |
| Connexion et reconnexion des connecteurs | cible § 4.6 | sonde au démarrage seulement ; états mensongers | 3 bis |
| Communication externe (principe) | cible § 5 | aucune ; Web Push vers la personne seulement | 3 ter |
| GitHub | cible § 5 bis | un PAT global lisible par les agents ; ni PR ni CI dans l'interface | 3 quater |
| Secrets, navigateur sans fuite, gateway configurable | cible § 5 ter | valeurs en clair, tout dans l'environnement des agents | 2 bis |
| Voix et audio | cible § 5 quater | un service hors dépôt ; rien côté Atelier | 3 quinquies |
| API d'agents, canaux, Tchap, Telegram | cible § 5 quinquies | aucune API pour un appelant extérieur | 3 sexies |
| Types d'agents, cadre conversationnel (type Colaig) | cible § 5 sexies | agents déclarés (budget, outils) et gardiens | 3 septies |
| Auto-amélioration | `auto-amelioration.md` | capteurs, budgets, « À valider » ; pas de mesure ni d'épreuve | 10 |
| Plan de finition (lots 1 à 9) | `plan-de-finition.md` | — | 1 à 9 |

## 3. Les constats qui comptent le plus

1. **L'identité n'est pas une frontière** : la clé propriétaire est dans l'environnement de chaque agent ; `/v1/auth/cookie` l'échange contre une session lue comme « la personne » (**lu et revérifié par moi, non exécuté**). Les classes réservée et engageante ne protègent que contre un modèle docile.
2. **Aucune garde n'est hors de portée de l'agent** : pas de réglages managés, hooks dans un fichier modifiable, `garde_bash` contournable (`printenv`, `cat /proc/self/environ`).
3. **Aucun verrou entre l'interface, VS Code et le terminal** : deux fenêtres peuvent écrire dans le même transcript.
4. **Les états mentent** : « fini » veut dire « arrêté » ; « connecté · N outils » reste affiché après une panne.
5. **Un agent code pousse où il veut sur GitHub** avec un PAT unique, lisible par tous ; aucune PR ni CI dans l'interface.
6. **Aucun mécanisme de saisie par référence** dans le navigateur ; snapshots, captures, console et réseau en lecture libre.
7. **Brouillon et production n'existent pas** : modifier une création serveur modifie ce qui tourne.
8. **Colaig v3** : des entrées sans contrôle de droit (`colaig_link_conversation`, `colaig_update_workspace`, routes `/workspaces*` et `/ask`) d'après la lecture ; à vérifier par vous avant correction.

## 4. Les décisions à prendre

*Reco* = ma recommandation. Les lignes **en gras** bloquent le démarrage des lots 1 à 3.

### A. Identité, profils, agents

| # | Décision | Reco | Débloque |
|---|---|---|---|
| **A1** | **Second facteur** pour ouvrir une session « personne » : jeton à part, passkey, autre ? | une clé de session distincte de celle des agents, retirée de leur environnement | lot 1 |
| **A2** | Identité signée par conversation : **d'abord pour les agents de l'Atelier, ou pour tous** ? | pour tous (même pièce que la fermeture de la clé propriétaire) | lot 1 |
| **A3** | **Surcharge de session** : seulement restreindre les défauts du projet, ou aussi élargir jusqu'au plafond ? Capacité en lecture seule pour un agent de l'Atelier sans « À valider » ? | restreindre libre ; élargir engageant ; lecture seule réversible | lot 3 |
| A4 | **Famille « agent externe »** dans les couches de profil ? Colaig d'abord comme agent externe ? | oui, puis réexprimé comme agent natif | lot 3 septies |
| A5 | Où vit le dossier d'un agent de l'Atelier qui agit sur plusieurs projets ? | dossier propre + copie de travail sur branche par projet touché | lot 3 |
| A6 | Agent conversationnel : **une session par conversation ou par utilisateur** ? | par conversation, reprise par identifiant | lot 3 septies |
| A7 | Où vit un agent conversationnel : `agents/<id>/` ou un projet de l'Atelier ? | — | lot 3 septies |
| A8 | **Coût** d'un canal public : plafonds par défaut, message quand le budget est atteint ? | plafonds par défaut + message lisible | lot 3 septies |
| A9 | Un agent **public** (n'importe qui peut lui écrire) est-il permis, avec quelles limites ? | non en v1 | lot 3 septies |
| A10 | Les skills remplacent-ils les behaviors (déclenchement par description) ? | **vérifier** sur le CLI du pod | lot 3 septies |
| A11 | Latence d'une session démarrée par un message : accusé immédiat, session chauffée ? | accusé immédiat obligatoire | lot 3 septies |

### B. Gateway, connecteurs, services MCP

| # | Décision | Reco | Débloque |
|---|---|---|---|
| **B1** | **Registre unique** : fusionner catalogue YAML, registre SQLite et `mcp_registry.py` ? Où vivent les surcharges (base versionnée ou fichier déclaratif) ? | un registre ; surcharges déclaratives versionnées | lot 3 bis |
| B2 | Surcharge d'outil : étendre les « variantes » ou créer l'*overlay* par connecteur ? | overlay | lot 3 bis |
| B3 | Classe d'un outil amont inconnu | **engageante** par défaut | lot 3 bis |
| B4 | Classes du navigateur (lectures, actions) : à journaliser ? | oui | lot 3 bis |
| B5 | Fusionner `atelier_montrer`, `atelier_navigateur_ouvrir` et l'écran en **un descripteur de vue** ? | oui | lot 3 bis |
| B6 | Gabarits de projet : lesquels retenir ; moteur de copie ou simple copie ? | page, application, service-mcp, savoir-faire, ml-gpu ; copie simple | lot 5 |
| B7 | Un seul champ `commande` : dans `artefact.json` ou dans `deploiement` ? | `cible: local \| pod \| service` | lot 3 bis |
| B8 | Capacités d'artefact consenties dès le brouillon ? | — | lot 5 |
| B9 | **Services MCP** : où vit le bloc `mcp`, un projet peut-il en exposer plusieurs ? | dans `projet.json`, plusieurs | lot 3 bis |
| B10 | Batterie de tests de conformité : minimale ou complète ? Bac à sable pour les outils d'écriture ? | minimale d'abord ; bac à sable plus tard | lot 3 bis |
| B11 | Qui peut rattacher un service ? Un agent de l'Atelier peut-il le proposer ? | la personne rattache ; un agent propose | lot 3 bis |
| B12 | Catalogue de services partageables entre personnes ? Montée de version automatique ou toujours sous accord ? | pas en v1 ; toujours sous accord | lot 3 bis |
| B13 | **Connecteurs à OAuth sortant** (`refresh_token`) ou seulement des Bearer statiques ? | **vérifier** ce qui est réellement branché | lot 3 bis |
| B14 | État des connecteurs : table de `gateway.db` ou fichier ? | table | lot 3 bis |
| B15 | Rejeu automatique après réinitialisation de session : seulement les lectures ? | oui | lot 3 bis |
| B16 | Un connecteur refusé reste-t-il retiré des projets ou seulement signalé ? | signalé, retrait automatique journalisé | lot 3 bis |
| B17 | Fréquence de sonde ; GET SSE sur `/mcp` ou POST seul avec 404 sur session inconnue ; `refresh_token` pour les jetons de la porte (90 jours) | 1 à 5 min en bon état ; POST seul + 404 | lot 3 bis |
| B18 | D-23 : wikichat « en échec » est-il un problème de connecteur ou de service ? | **vérifier** avant de le rattacher | lot 3 bis |

### C. Onyxia

| # | Décision | Reco | Débloque |
|---|---|---|---|
| C1 | **Accès général configuré par la personne** : portée (espace de noms entier ou liste de ressources), quotas, durée par défaut, cible (agent, projet, famille) ? | octroi daté, révocable, plafonné | lot 3 bis |
| C2 | Classes des outils Onyxia de l'Assistant (`project_start`, `service_deploy`, désinstallation) | engageante | lot 3 bis |
| C3 | **GPU** : préemption par file, bail, ou demande dans « À valider » ? | demande dans « À valider » | lot 3 bis |
| C4 | Pod de développement et service publié **ensemble**, avec deux entrées nommées ? | oui | lot 3 bis |
| C5 | Ouvrir `push_repo` et `pull_artifact` bornés au dossier du projet ? | oui | lot 3 bis |
| C6 | Deux outils pour démarrer et arrêter `deploiement.commande` ? Préfixe de session propre à l'Atelier ? | oui ; oui | lot 3 bis |
| C7 | **Droits du compte de service du pod** (Kubernetes, S3) : qui les réduit, et comment ? | les réduire au projet | lot 3 bis |

### D. Secrets et navigateur

| # | Décision | Reco | Débloque |
|---|---|---|---|
| **D1** | **Chiffrement au repos** : où vit la clé maître (secret Kubernetes, KMS, Vault) ? | hors du volume | lot 2 bis |
| D2 | Navigateur : masquer au niveau du pont `chrome-devtools-mcp` ou fournir un outil maison ? Que faire d'`evaluate_script` ? | outil `remplir(uid, secret_ref)` + masquage ; `evaluate_script` encadré | lot 2 bis |
| D3 | Consentement d'un secret : par domaine, par session ou par usage ? Durée par défaut ? | par domaine, une fois | lot 2 bis |
| **D4** | **Calendrier** pour supprimer `os.environ.copy()` et la clé propriétaire de l'environnement des agents | avec le lot 1 | lot 1, 2 bis |
| D5 | Fusionner `server_credentials` et les accords du registre en un seul stockage | oui | lot 2 bis |
| D6 | TOTP / 2FA et CAPTCHA : saisie toujours humaine ? | oui | lot 2 bis |
| D7 | Portée « famille » des secrets ; héritage par rapport à D-08 (8 projets sur 16 héritent de tous les connecteurs) | héritage supprimé par défaut | lot 2 bis |
| D8 | Rétention du `.jsonl` source de Claude Code : filtrer à l'écriture ? | oui | lot 2 bis |

### E. GitHub

| # | Décision | Reco | Débloque |
|---|---|---|---|
| E1 | **GitHub App ou jeton fine-grained par dépôt** ? (clé de l'App hors de portée des agents ; GitHub peut-il appeler le pod ?) | App pour les agents de l'Atelier ; **vérifier** la faisabilité sur SSPCloud | lot 3 quater |
| E2 | Les agents code **poussent-ils eux-mêmes** (sur leur branche) ou l'Atelier pousse-t-il à leur place ? | l'Atelier pousse | lot 3 quater |
| E3 | Le jeton de la personne reste-t-il sur le pod ? Comment le rendre illisible aux agents ? | UID distinct, plus de `sudo` | lot 1 |
| E4 | L'Atelier **impose-t-il** la protection de branche à la liaison ? | impose | lot 3 quater |
| E5 | Fusion : PR GitHub seulement, ou aussi la fusion locale pour les projets sans remote ? | PR ; locale seulement sans remote | lot 3 quater |
| E6 | Dépôt GitHub **obligatoire** à la création d'un projet ? | non : `git init` local, publication différée | lot 3 quater |
| E7 | Source de vérité de la production : étiquette poussée ou worktree local ? | étiquette poussée | lot 5 |

### F. Voix et audio

| # | Décision | Reco | Débloque |
|---|---|---|---|
| F1 | Décisions V-1 à V-9 de `voix.md` (statut système, dépôt privé, chemin `/v1/voix`, ordre des lots, GPU) | à reprendre une à une | lot 3 quinquies |
| F2 | Retirer `VOICE_TOKEN` de l'environnement des agents dès la première étape ? | oui | lot 3 quinquies |
| F3 | Une capacité voix distincte pour les agents de l'Atelier (V5 ne couvre que `code`) ? | oui | lot 3 quinquies |
| F4 | Seuils de plafonds (minutes, caractères, CPU) ; qualité sur voix humaines et accents | à calibrer par la mesure ; **banc à créer** | lot 3 quinquies |
| F5 | Le point d'accès LLM de SSPCloud sert-il de la transcription (aujourd'hui écarté du catalogue) ? | **vérifier** | lot 3 quinquies |
| F6 | Lecture automatique des alertes ; mention « voix synthétique » pour tout tiers | pas de lecture automatique ; mention obligatoire | lot 3 quinquies |
| F7 | Transcription de réunion : qui consent, où est stockée la transcription ? | consentement des participants ; dans le projet | lot 3 quinquies |
| F8 | Téléphonie : fournisseur hébergé en France, ou rester sur le texte et le vocal différé ? | vocal différé | lot 3 quinquies |
| F9 | Ajouter le service voix aux écoutes déclarées des gardiens | oui, dès la première étape | lot 3 quinquies |

### G. Communication externe, API d'agents, canaux

| # | Décision | Reco | Débloque |
|---|---|---|---|
| G1 | **Envoi par un agent planifié sans personne** : attente dans « À valider », liste blanche, ou interdit en v1 ? | attente dans « À valider » ; interdit en v1 | lot 3 ter |
| G2 | Après lecture de contenu externe : bloquer les actions engageantes, ou confirmation renforcée ? | bloquer dans le même tour | lot 3 ter |
| G3 | Entrant : n8n comme relais ou webhook natif ? Qui arme un déclencheur entrant ? | webhook natif signé ; la personne arme | lot 3 sexies |
| G4 | Mail : SMTP direct ou via n8n ? Un envoi mail est-il toujours engageant, même vers soi-même ? | toujours engageant | lot 3 ter |
| G5 | **Tchap** : serveur Matrix, compte bot, chiffrement de bout en bout, vérification des appareils, hébergement du pont | **vérifier** hors dépôt | lot 3 sexies |
| G6 | Standard d'API d'agent : seulement celle de l'Atelier, ou aussi un point d'accès compatible avec les API de conversation usuelles ? | celle de l'Atelier d'abord | lot 3 sexies |
| G7 | **Appairage** d'une personne à un canal : code à usage unique saisi dans l'interface ? | oui | lot 3 sexies |
| G8 | Un message d'une personne liée peut-il lancer un agent planifié, ou seulement converser avec un agent actif ? | converser seulement | lot 3 sexies |
| G9 | Réponses d'un agent dans un salon à plusieurs : à qui s'adressent-elles ; que voit un invité du contexte ? | — | lot 3 sexies |
| G10 | Quotas par défaut (messages par minute et par jour) ; Telegram : long polling ou webhook, et **où arrive le trafic entrant** (l'Ingress n'expose que l'interface et les applications) | long polling d'abord | lot 3 sexies |
| G11 | **Colaig v3** : le projet est-il vérifié et corrigé de son côté (routes et outils MCP sans contrôle de droit) avant de s'y brancher ? | oui, avant toute liaison | lot 3 sexies |

### H. Brouillon, partage, documents, exploitation

| # | Décision | Reco | Débloque |
|---|---|---|---|
| H1 | **Partage à des tiers** dans le périmètre ou non ? | hors périmètre de la finition | lot 5 |
| H2 | **Routine de nuit de wikichat** : dans ce dépôt ou ailleurs ? Persistance du store (D-53) | **vérifier** en réel | lot 6 |
| H3 | **Laboratoire ML** : rester dans le monorepo ou se séparer ? | se séparer à terme (aucun import croisé) | lot 9 |
| H4 | **Chantiers sans code** (voix, n8n, courtier GPU, commentaires, MCP Apps, « Montrer »…) : lesquels retirer du périmètre pour que la finition soit finie ? | retirer ceux sans lien avec les lots 1 à 4 | lot 9 |
| H5 | **Lexique** : S2 contre l'écosystème ; « Code » contre « Projets » | — | lot 9 |
| H6 | Les contradictions entre documents (store de wikichat, « page Gardiens », deux ordonnanceurs…) : à purger, par qui ? | moi, lot 9 | lot 9 |

### I. Auto-amélioration

| # | Décision | Reco | Débloque |
|---|---|---|---|
| I1 | Les **trois premiers objectifs** de la constitution | fins de lancement qui disent vrai ; permission jamais sans réponse ; coût par tour | lot 10 |
| I2 | **Voie automatique** : jamais, ou après N semaines de précision démontrée ? | après, hors zones protégées | lot 10 |
| I3 | Budget quotidien de la boucle ; quel modèle pour les équipes | à calibrer à l'étape 3 | lot 10 |
| I4 | Qui juge l'échantillon aveugle, à quelle fréquence ? | la personne, 5 cartes par semaine | lot 10 |
| I5 | La boucle peut-elle amender les consignes du socle, ou seulement hooks, gabarits et contrôles ? | hooks et contrôles d'abord | lot 10 |

## 5. Ce qui est à vérifier avant de bâtir

| # | À vérifier | Pourquoi |
|---|---|---|
| V1 | Précédence des couches natives ; réglages managés en mode `-p` ; sous-agents quand le parent refuse | tout le lot 2 et le lot 3 |
| V2 | La chaîne clé → cookie → « personne » s'exécute-t-elle ? (test local d'abord) | gravité du lot 1 |
| V3 | Le store de wikichat survit-il à un redémarrage ? Filtre de profil de wikichat actif ? | D-53, lot 6 |
| V4 | `securityContext` (`drop: ALL`) et mémoire maximale du pod | lot 8 |
| V5 | GitHub App installable sur SSPCloud ; GitHub peut-il appeler le pod ? | E1 |
| V6 | Tchap : serveur Matrix, compte bot, E2E | G5 |
| V7 | Les failles lues dans Colaig v3 | G11 |
| V8 | Les skills se déclenchent-ils comme prévu sur le CLI du pod ? | A10 |

## 6. L'ordre de travail

```
 Lot 1 identité ─► Lot 1 bis miroir ─► Lot 2 garde ─► Lot 2 bis coffre de secrets ─► Lot 3 rôle unique (couches)
   ─► Lot 3 bis gateway (registre, overlay, services MCP, connecteurs, Onyxia) ─► Lot 4 états vrais ─► Lot 5 brouillon / production
   ─► Lots 3 ter à 3 septies (communication, GitHub, voix, API et canaux, types d'agents)
 en continu : Lot 6 mémoire · Lot 7 consolidation · Lot 8 pod · Lot 9 documents
 en dernier : Lot 10 auto-amélioration
```

**Les décisions à prendre en premier** (elles débloquent les lots 1 à 3) : **A1, A2, A3, B1, D1, D4, E3**, puis les vérifications **V1 et V2**.
