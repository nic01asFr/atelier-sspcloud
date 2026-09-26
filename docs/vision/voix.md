# La voix dans l'Atelier : STT et TTS

Étude et conception du 26/09/2026, équipe « voix » (vague 4, jalon A7). **Proposition, non
implémentée**, sauf mention « existe ». Elle répond à la demande de Nicolas : « voir pour ce qui
est éventuellement du service TTS et STT à intégrer ensuite à l'Atelier de manière appropriée ».

Sources :

- `docs/consignes/stt-tts-atelier.md` : l'état du service au 24/09 ;
- `assistant-role.md` §3.9, `assistant-harness.md` §4.9, `assistant-synthese.md`, `decisions.md`
  (A-8), `mesures-vague1.md` §3 : ce que l'oral doit tenir ;
- `architecture-transverse.md` §0, §1.4, §1.6, §5 et T4, T11, T20 ;
- `profils-acces.md`, `panneau.md` ;
- le code : `apps/manifeste.py`, `apps/superviseur.py`, `apps/serveur.py`, `apps/proxy.py`,
  `apps/bureaux.py`, `apps/passage.py`, `relais_ws.py`, `ecran.py`, `env_projet.py`,
  `commandes/journal.py`, `web/js/views/code-chat.js`, `assistant.js`, `panneau.js` ;
- le pod, en lecture et par des mesures bornées (§1).

Marques : **[M]** mesuré sur le pod le 26/09 ; **[L]** lu dans le code ; **[S]** supposé ou
calculé, à vérifier.

## 0. En bref

1. **La voix devient une brique système de l'Atelier**, pas le projet d'un agent : un projet
   système `atelier-voix` (dépôt versionné), lancé et surveillé par le superviseur des créations
   avec un statut « système », gardé par les gardiens, mis à jour par proposition. Pas de
   connecteur `voix` dans le pool.
2. **Le son passe par l'origine de l'Atelier** (`/v1/voix/…`), avec la session de la personne,
   la garde d'`Origin` et le relais WebSocket commun ; le jeton du service est posé côté serveur.
   L'hôte des applications n'est pas le bon chemin pour le micro de l'interface (T24).
3. **Dans l'ordre** : dictée dans le composeur, puis lecture à voix haute d'une réponse, puis
   conversation continue avec l'Assistant (VAD, interruption). Les outils vocaux des agents et
   les créations qui parlent viennent après, la visio beaucoup plus tard.
4. **Sur CPU, avec les modèles actuels** : STT d'environ 1,1 s par énoncé, TTS de 0,4 à 0,8 s
   par phrase [M]. Pas de GPU pour l'instant. Le goulet est la concurrence : deux transcriptions
   et une synthèse simultanées prennent chacune plus de 2 s [M].
5. **Sept lots** (V0 à V6, §7), dont trois suffisent à la première valeur : V0 (statut
   système), V1 (routes de l'Atelier), V2 (dictée).

## 1. Ce qui existe, mesuré le 26/09

### 1.1 Le service

| Élément | État |
|---|---|
| Code | `~/work/projects/nouveau-projet-2` : `voice_service.py` (FastAPI), `mcp_voix.py` (SDK MCP), `securite.py`, `inference.py`, `audio/session.py`, `audio/buffer.py`, `bench/`, 66 tests. Dernier commit `4f4e559` [M] |
| Versionnement | **aucun remote git** : le code n'existe que sur le volume du pod [M]. Pas de `.atelier/projet.json` [M] |
| Instance en service | lancée à la main par `start.sh`, PID 3888701, en service depuis 1 j 19 h, `127.0.0.1:18920`, `nice 0`, hors superviseur [M]. Recensée comme écoute non déclarée par les gardiens (T20) |
| Instance « création serveur » | `artifacts/voix/artefact.json` déclaré, **pas lancée** (`~/work/.atelier-etat/apps.json` vide) [M] |
| Modèles | faster-whisper `small` int8 (464 Mo sur disque), Kokoro-82M v1.0 onnx, voix `ff_siwis` (675 Mo) ; `.venv` 507 Mo [M]. Tout est local ; aucun appel sortant [L] |
| Jeton | `~/work/.secrets/voice_token`, 0600 [M] ; exigé partout sauf `/health` [M : 401 sans jeton]. En WebSocket, accepté aussi en sous-protocole `bearer.<jeton>` [L] |
| Routes | `GET /health`, `POST /tts` (texte → WAV), `POST /stt` (WAV → texte), `WS /audio/stream/{id}` (PCM 16 bits 16 kHz, tranches fixes de 3 s, STT seul), `/mcp` (`dire`, `ecouter`) [L] |
| Limites | texte 2 000 caractères, audio 8 Mio et 120 s, WAV seulement, 8 sessions WS, 2 fils d'inférence partagés par STT et TTS [L] |
| Journal | `voice-service.log` dans le dossier du projet, 0644, sans rotation (163 Ko) ; **aucune transcription n'y est écrite**, seulement les requêtes et les métriques de session [M] |
| Consommateurs | le `.mcp.json` de `nouveau-projet-2` (`voice` sur `127.0.0.1:18920/mcp`, jeton par `${VOICE_TOKEN}`, que l'Atelier pose par `.atelier/env.json`) [M]. Aucune autre surface |
| Détection de parole | aucune dans le service ; mais **Silero VAD v6 est déjà livré** avec faster-whisper (`faster_whisper/assets/silero_vad_v6.onnx`, `get_speech_timestamps`) [M] |

### 1.2 Mesures

Phrases synthétisées par le service puis transcrites, deux essais chacune, service chaud, par
HTTP avec jeton, depuis le pod (script jetable `/tmp/mesure-voix-v4/`) [M] :

| Phrase | Audio | TTS | STT | Transcription |
|---|---|---|---|---|
| « Qu'est-ce qui attend ma validation ? » (36 car.) | 1,58 s | 0,54 ; 0,43 s | 1,21 ; 1,06 s | exacte |
| « D'accord, je regarde. » (21 car.) | 1,39 s | 0,47 ; 0,40 s | 1,07 ; 1,01 s | exacte |
| « Le lecteur Grist a fini son lot trois, les tests sont verts. » (60 car.) | 3,41 s | 0,78 ; 0,66 s | 1,12 ; 1,06 s | « griste », « 3 » |

- **Le STT coûte environ 1,1 s quelle que soit la longueur** de l'énoncé (1,4 à 3,4 s d'audio).
  Whisper traite toujours une fenêtre de 30 s : c'est un coût fixe, pas un débit [S, cohérent
  avec la mesure]. Raccourcir l'énoncé ne fait donc rien gagner ; changer de modèle ou de
  matériel, oui.
- **Le TTS suit la longueur** : environ 0,2 s par seconde d'audio produite, plus 0,1 à 0,2 s.
- **Concurrence** : deux transcriptions et une synthèse lancées ensemble finissent en 2,13 ;
  2,36 et 2,56 s [M]. Avec deux fils d'inférence partagés, la synthèse attend derrière les
  transcriptions : dans une conversation, la première phrase de l'Assistant serait retardée par
  n'importe quelle dictée d'un autre onglet.
- **Démarrage à froid** : chargement de Kokoro 2 s, de Whisper 1 s (journal du 24/09) [M] ;
  plus l'import de Python et la première inférence, non mesurés [S : 5 à 8 s au total].
- **Mémoire** : 2,18 Go résidents avec les deux modèles chargés, 142 fils [M].
- **Machine** : 128 processeurs visibles, aucun plafond de CPU ni de mémoire posé sur le groupe
  du pod (`cpu.max` et `memory.max` à `max`), charge moyenne de 21 [M]. Pas de GPU sur ce pod ;
  quota GPU du namespace : 1, libre au moment de la mesure [M].
- **Format** : Kokoro rend du WAV mono 16 bits à 24 kHz, soit environ 47 Ko par seconde [M].
  Un micro en PCM 16 bits à 16 kHz fait 32 Ko par seconde [calculé].

### 1.3 Ce que ces faits changent

| Fait | Conséquence |
|---|---|
| Le mandataire de l'hôte des applications retire `Authorization` à l'aller (`proxy.RETIRES_ENTREE`) et ne pose aucun jeton pour une création [L] | L'instance « création serveur » répondrait 401 à tout ce qui n'est pas `/health`, sauf à mettre le jeton dans la page. **Déclarée, elle est inutilisable** depuis le navigateur (T24) |
| Le superviseur redémarre une création au-delà de 1,5 Gio résidents (`plafond_memoire_octets`), et la met `en_echec` après cinq redémarrages en dix minutes [L] | Avec 2,18 Go mesurés, l'instance « création serveur » **tournerait en boucle** dès que les deux modèles seraient chargés (T25) |
| Le superviseur lance toute création en `nice 10` et au plus quatre à la fois (`apps_max`) [L] | La voix, sensible à la latence, passerait derrière les agents ; elle prendrait une des quatre places des créations de la personne |
| `dire` rend un WAV en base64 dans le résultat d'outil [L] | Environ 100 Ko de texte par phrase dans le contexte d'un modèle qui n'entend pas l'audio [S] (T26) |
| Le cadre du panneau porte `allow="clipboard-write; fullscreen"` [L] | Aucune création affichée dans le panneau n'a le micro. C'est voulu, et cela reste vrai (§3.6) |
| L'Ingress de l'Atelier (chart) : `proxy-body-size: "0"`, délais de 3 600 s [L, chart ; non vérifié sur le pod actuel] | Un WebSocket de conversation et un envoi de quelques mégaoctets passent. Un essai réel depuis l'extérieur reste à faire (V1) |

## 2. Statut du service dans l'Atelier (question 1)

### 2.1 Les options

| | A. Projet d'agent qui déclare une création serveur (état actuel) | B. Brique système de l'Atelier |
|---|---|---|
| Qui la démarre | le superviseur, sur la première requête vers son adresse ; ou `start.sh` à la main (aujourd'hui) | le superviseur, à la demande de l'interface ou d'un outil, par un nom fixe connu de l'Atelier |
| Qui l'utilise | le navigateur, par l'hôte des applications, sans jeton possible (§1.3) | l'interface, par `/v1/voix/…` ; les agents, par des outils `atelier_*` ; plus tard les créations, par capacité |
| Qui la change | n'importe quel agent du projet `nouveau-projet-2`, sur `main`, sans revue | un agent code du projet système, sur branche, fusion par « À valider » |
| Garde | aucune, hors « écoute non déclarée » (T20) | santé et sécurité par les gardiens, comme une création servie |
| Limites | celles d'une création (1,5 Gio, `nice 10`, une des quatre places) : incompatibles (§1.3) | propres, déclarées |
| Coût d'écriture | nul, mais ne marche pas | quelques ajouts au superviseur et au manifeste, une route, un nom de configuration |

### 2.2 Recommandation : B, en réutilisant le superviseur

Le principe du §0 du transverse tranche : la brique existe (le service, le superviseur, le
relais WS, le code de passage, le journal), il faut la **structurer et la rendre disponible**,
pas en écrire une autre.

- **Projet système `atelier-voix`**, quatrième ligne du §2 du transverse, à côté de
  `wikichat-memory`, `atelier-gardiens` et `atelier`. C'est le dépôt actuel de
  `nouveau-projet-2`, renommé, avec un `projet.json` (`systeme: true`), un `ETAT.md`, et **un
  remote** (dépôt privé : décision V-2). Son dossier reste sur le volume, avec son `.venv` et ses
  modèles (1,6 Go) : ils n'entrent pas dans l'image de l'Atelier.
- **Lancé par le superviseur existant**, désigné par un réglage de l'Atelier
  (`ATELIER_VOIX = "atelier-voix/voix"`, une ligne dans `config.py`). Ce qui le distingue d'une
  création ordinaire tient en trois règles :
  - il ne compte pas dans `apps_max` ;
  - il tourne en `nice 0` ;
  - son plafond de mémoire vient de son manifeste (`memoire_max_mo`, nouveau champ borné à
    4 096, que toute création peut aussi déclarer).
- **Démarrage à la demande, arrêt après 30 min d'inactivité** (le défaut du manifeste actuel).
  Le démarrage à froid est court (§1.2) ; tenir 2,2 Go en permanence pour une fonction qu'on
  n'utilise pas toute la journée n'est pas justifié. L'interface **préchauffe** la voix quand la
  personne ouvre une conversation vocale ou appuie sur le micro (§3.4).
- **Santé et sécurité par les gardiens**, sans code nouveau : la voix est une création servie
  (G1), son port est attribué par le superviseur (G2), son jeton est un fichier 0600 contrôlé par
  empreinte (G2). L'instance de `start.sh` disparaît au déploiement de V0, et avec elle l'écoute
  non déclarée de T20.
- **Mise à jour** : un agent code du projet `atelier-voix` travaille sur une branche ; la
  personne fusionne par « À valider » ; l'Atelier redémarre la création système (geste existant
  « redémarrer » d'une création). Tout changement de modèle ou de réglage passe par
  `bench/mesurer.py` (WER et latence avant/après), comme l'exige la consigne.
- **Pas de connecteur `voix` dans le pool.** Le pool distribue des outils aux modèles ; le
  premier consommateur de la voix est l'interface, pas un modèle. Un connecteur remettrait le
  jeton dans l'environnement de chaque session (le mécanisme `.atelier/env.json` qu'on retire)
  et ferait entrer de l'audio dans les contextes (T26). Les agents passent par le serveur
  `atelier` (§4.2).

## 3. Chemin du son (question 3)

### 3.1 Principe

**Navigateur de la personne → origine de l'Atelier (`/v1/voix/…`) → service voix sur la
boucle locale.** Même garde que `/vscode` : session de la personne, `Origin` exactement égale
à l'adresse publique de l'Atelier (`relais_ws.refus_websocket`), et le jeton du service posé
côté serveur, jamais dans la page. C'est le relais commun (`relais_ws.relayer`) et le
compteur de connexions du superviseur, tels qu'ils existent.

Pourquoi pas l'hôte des applications, comme l'écrivaient `assistant-harness.md` §4.9 et le
transverse §1.6 : le micro et le composeur vivent dans la page de l'Atelier, pas dans un cadre du
panneau ; l'hôte des applications refuse une `Origin` qui n'est pas la sienne ; son mandataire
retire `Authorization` et ne pose aucun jeton pour une création ; et le cadre du panneau n'a pas
le micro. L'hôte des applications sert à **montrer** des vues ; la voix est une capacité de
l'interface elle-même, comme l'écran du navigateur est servi par `ecran.py` plutôt que relayé
brut. Le principe du §1.6 tient : **un seul relais WS, une seule garde, pas de port nu** ; seule
l'origine change (T24).

### 3.2 Routes proposées (module `mcp_gateway/atelier/voix.py`)

| Route | Entrée | Sortie | Usage |
|---|---|---|---|
| `GET /v1/voix/etat` | — | `{etat: absente\|arretee\|demarrage\|prete\|en_echec, depuis}` | l'interface sait si le micro est utilisable ; `absente` quand `ATELIER_VOIX` n'est pas réglé |
| `POST /v1/voix/preparer` | — | l'état | préchauffage (démarre la création système sans attendre) |
| `POST /v1/voix/transcrire` | WAV PCM 16 bits mono 16 kHz, 60 s au plus | `{texte, duree_audio_s, secondes}` | dictée |
| `POST /v1/voix/dire` | `{texte}` (600 caractères au plus) | WAV | lecture d'une phrase |
| `WS /v1/voix/conversation/{session_id}` | trames PCM 16 bits 16 kHz de 20 à 40 ms ; messages JSON de contrôle | événements JSON et trames audio (§3.5) | conversation continue (V4) |

- Le texte transcrit passe par `filtre_transcripts.py` (T10) avant d'être rendu : une valeur
  connue de `claude-env.sh` dite à voix haute n'entre ni dans le composeur, ni dans la
  conversation.
- Les erreurs sont en mots (« la voix se prépare », « le micro n'a rien entendu ») et suivent le
  lexique S2 : ni « service », ni « jeton », ni « STT » à l'écran.

### 3.3 Format et tranches

- **Capture** : `getUserMedia({audio: {echoCancellation: true, noiseSuppression: true,
  autoGainControl: true, channelCount: 1}})`, puis un `AudioWorklet` qui rééchantillonne à
  16 kHz et convertit en PCM 16 bits. Pas de `MediaRecorder` : il produit du WebM/Opus, que le
  service refuse (WAV seulement) et qu'il faudrait décoder. 32 Ko/s passent sans peine.
- **Dictée** : l'audio est gardé dans la page le temps de l'appui, emballé en WAV (en-tête de
  44 octets), puis envoyé en un `POST`. Plafond de 60 s côté page (1,9 Mo).
- **Conversation** : trames de 20 à 40 ms envoyées au fil de l'eau sur le WebSocket.
- **Sortie** : WAV 24 kHz, décodé par `AudioContext.decodeAudioData` et joué par Web Audio,
  ce qui permet de couper net.
- **Interdit** : l'API Web Speech du navigateur (`SpeechRecognition`, et les voix réseau de
  `speechSynthesis`). Dans Chrome, la reconnaissance part chez Google. Aucune donnée hors
  SSPCloud (§4).

### 3.4 Latence visée

Budget par étape, dans les cibles de `decisions.md` A-8 :

| Étape | Dictée | Conversation (V4) |
|---|---|---|
| Fin de parole détectée | relâcher le bouton : 0 s | VAD Silero, silence de 0,5 s : environ 0,5 s [S] |
| Envoi | un `POST` de 50 à 200 Ko : moins de 0,2 s [S] | déjà envoyé au fil de l'eau |
| STT | environ 1,1 s [M] | environ 1,1 s [M] |
| Texte → premier jeton de l'Assistant | — | environ 0,7 s [M, harness] |
| Première phrase | — | 0,2 à 0,4 s [M, harness] |
| TTS de la première phrase | — | 0,4 à 0,8 s [M] |
| **Total** | **texte dans le composeur en 1,3 à 1,5 s** [S] | **premier mot en 2,9 à 3,5 s sans outil** [S, somme de mesures] |

- L'**accusé** (« je regarde ») est un son préenregistré, joué quand le premier événement du
  tour est un outil : moins de 2 s après la fin de parole [S]. Les accusés sont synthétisés une
  fois par Kokoro et servis comme fichiers statiques de l'interface.
- **Démarrage à froid** : la première utilisation après 30 min d'inactivité paie 5 à 8 s [S].
  D'où le préchauffage à l'ouverture d'une conversation vocale et à l'appui sur le micro ;
  l'interface dit « la voix se prépare » plutôt que d'échouer.
- **Concurrence** (§1.2) : V0 sépare les fils d'inférence, un pour le STT et un pour le TTS,
  pour qu'une phrase à dire n'attende jamais une transcription. Une seule conversation vocale
  à la fois (§6).

### 3.5 Conversation continue et interruption

Le service garde son WebSocket, dont le découpage change : **la VAD Silero déjà livrée avec
faster-whisper remplace les tranches fixes de 3 s** (`audio/buffer.py`). C'est la brique
existante qu'on branche, pas une dépendance de plus.

Protocole `voice.v2` entre l'Atelier et le service (le navigateur ne parle qu'à l'Atelier) :

- client → service : trames PCM ; `{"type": "fin"}` pour forcer la fin d'un énoncé ;
- service → client : `parole_debut`, `parole_fin`, `transcription` (`{texte, secondes}`).

L'Atelier tient le pont, dans `voix.py`, sans modèle :

1. sur `transcription`, il envoie le texte à la conversation de l'Assistant par la route
   existante (`POST /v1/sessions/{id}/messages`), avec un champ nouveau `canal: "voix"` ;
2. il lit les `text_delta` du tour, que le harnais diffuse déjà (`events.py`, `kind=texte`) ;
3. il les coupe en phrases (`. ? ! :` et saut de ligne ; première phrase coupée à la virgule
   au-delà de 60 caractères ; ni Markdown ni code dits : `assistant-harness.md` §4.9), les
   synthétise dans l'ordre, la suivante pendant que la précédente est jouée, et envoie l'audio
   au navigateur sur le même WebSocket ;
4. **interruption** : sur `parole_debut` pendant que l'Assistant parle, la page coupe le son
   aussitôt (localement, sans attendre le serveur), l'Atelier abandonne les phrases restantes et
   appelle la route d'interruption existante (`POST /v1/sessions/{id}/interrupt`). Ce qui est
   écrit reste écrit ; une délégation lancée continue ; l'énoncé suivant part avec la mention
   « (interrompu après : « … ») » (harness §4.9).

Risque : **l'écho**. Le haut-parleur de la personne peut déclencher la VAD pendant que
l'Assistant parle. L'annulation d'écho du navigateur (`echoCancellation`) couvre le son joué par
la page dans la plupart des cas [S, à mesurer en V4] ; sinon, seuil de VAD relevé pendant la
lecture, et le casque conseillé. Repli toujours disponible : appuyer pour parler.

### 3.6 Derrière l'Ingress SSPCloud

- **HTTPS** : `getUserMedia` exige un contexte sûr ; l'Atelier est servi en `https` [L].
- **WebSocket** : le relais passe déjà l'Ingress pour `/vscode`, l'écran du navigateur et les
  bureaux noVNC (bureau QGIS vérifié en réel le 26/09, `plan-implementation.md` §5).
- **Délais** : `proxy-read-timeout` de 3 600 s dans le chart [L]. L'Atelier envoie un ping
  toutes les 20 s sur le WebSocket de conversation, qu'un Ingress plus strict ne le coupe pas.
- **Taille** : `proxy-body-size: "0"` dans le chart [L] ; la dictée plafonnée à 60 s reste de
  toute façon sous 2 Mo.
- **Pas d'UDP** : un Ingress ne relaie que HTTP. C'est ce qui écarte WebRTC aujourd'hui (§5).
- **Micro dans le panneau** : non. Le cadre garde `allow="clipboard-write; fullscreen"`. Le
  micro reste une capacité de la page de l'Atelier.

## 4. Sécurité et portée (question 4)

### 4.1 Le jeton

- Un seul jeton, `voice_token`, déplacé dans `~/work/.secrets/apps/voix` (0600) pour suivre la
  règle des créations (`manifeste.secrets` : références vers `~/work/.secrets/apps/`). Le
  manifeste déclare `"secrets": {"VOICE_TOKEN": "voix"}` ; le service lit `VOICE_TOKEN` s'il
  est posé, sinon `VOICE_TOKEN_FILE` (petit ajout à `securite.py`).
- L'Atelier lit la même référence pour poser `Authorization` vers le service, comme `bureaux`
  pose le jeton d'une vue (`jeton.depuis = secret:<réf>`). Le jeton ne quitte jamais le
  serveur : ni page, ni `.mcp.json`, ni environnement d'un CLI.
- `.atelier/env.json` (`VOICE_TOKEN`) et l'entrée `voice` des `.mcp.json` disparaissent ; le
  mécanisme `env_projet.py` reste, pour les autres projets qui en ont besoin.
- Rotation : l'Atelier réécrit le fichier et redémarre la création système. Aucun client à
  prévenir, puisque l'Atelier est le seul client.

### 4.2 Qui peut appeler quoi

| Acteur | Accès | Canal | Garde |
|---|---|---|---|
| Personne | dictée, lecture, conversation | `/v1/voix/…` | session de l'Atelier, `Origin` |
| Assistant | **aucun outil vocal** : la voix est un canal, tenu par le pont (§3.5), pas un outil du modèle | — | — |
| Agent code | `atelier_voix_transcrire(chemin)` et `atelier_voix_synthetiser(texte, chemin)` : un fichier audio **de son projet** vers du texte, un texte vers un WAV écrit **dans son projet** | serveur `atelier`, profil `code`, famille `voix` | bornés au projet de la conversation, comme `atelier_creation_*` ; plafonds (§6) |
| Agent lancé | rien par défaut ; la famille `voix` si sa mission la déclare | serveur `atelier` | liste fermée |
| Gardien | `/health` seulement | boucle locale | — |
| Application (création) | plus tard : capacité `voix:dire` (lot V6) | jeton de capacité (`atelier-hebergement.md` §4) | accordée par la personne |
| Autre processus du pod | la boucle locale est joignable, mais tout exige le jeton | — | limite connue, comme pour le Chrome d'une conversation (U1) |

`dire` et `ecouter` quittent la surface des agents (T26) : un résultat d'outil qui porte du son
n'a pas d'usage pour un modèle qui ne l'entend pas, et coûte environ 100 Ko par phrase. Le
serveur MCP du service peut rester, joignable par la seule boucle locale sous jeton, pour les
tests d'intégration du projet système.

### 4.3 Données

- **Aucun audio conservé**, nulle part (A-8) : ni par le service, ni par l'Atelier, ni dans la
  page au-delà de l'énoncé en cours. Aucun test ne pose de fichier audio hors d'un dossier
  jetable.
- **Aucune donnée hors SSPCloud** : modèles locaux ; `HF_HUB_OFFLINE=1` dans le manifeste, pour
  que faster-whisper ne tente jamais de joindre Hugging Face ; API Web Speech du navigateur
  interdite (§3.3).
- **Transcriptions** : elles deviennent des messages de la conversation, qui est leur seul
  enregistrement. Elles sont filtrées (T10) avant d'y entrer, puis capitalisées comme toute
  conversation, avec le même filtre.
- **Journal unique** (`commandes/journal.py`) : une ligne par conversation vocale ouverte et
  fermée (source `capacite` : acteur, conversation, durée totale d'audio, nombre d'énoncés,
  latences médianes), une ligne par refus, et les appels des outils `atelier_voix_*` comme toute
  commande. **Jamais le texte** transcrit ou dit. Pas de ligne par dictée : ce serait du bruit.
- **Journal du service** : celui du superviseur (tournant, 5 Mo) remplace `voice-service.log` ;
  il ne contient déjà aucun texte [M].
- **Accords** : aucun à la voix seule (A-8). Une commande engageante reçue à l'oral montre son
  aperçu à l'écran et attend un clic. Le pont n'envoie jamais un « oui » dit à voix haute comme
  réponse à une carte.

## 5. Visio et flux (question 5)

**Réaliste maintenant, et déjà couvert** : ce que `assistant-role.md` appelle « Visio » n'est pas
une visioconférence. C'est une conversation vocale (§3.5) pendant laquelle le panneau montre la
vue dont parle l'Assistant, qui est déjà diffusée : écran du navigateur en JPEG (`ecran.py`),
bureaux noVNC, créations. Aucune caméra, aucun serveur média. Le lot A5 d'`assistant-role.md`
(onglet Visio, sous-titres sur la vignette, désignation d'une zone) se construit sur V4 et sur le
panneau, sans rien d'autre.

**Plus tard, sous condition** :

- **Plusieurs personnes dans la même conversation vocale** (Nicolas et une collègue) : le même
  WebSocket, un par participant, et un mélange côté Atelier. Suppose d'abord des invités
  (`passerelle-auth`).
- **Visioconférence avec image** (WebRTC, LiveKit, Jitsi) : il faut de l'UDP, ou un TURN en TLS
  sur le port 443 avec un passage direct, qu'un Ingress HTTP n'offre pas. Il faudrait un service
  Onyxia dédié avec un réseau que le namespace ne donne pas aujourd'hui [S, à confirmer avec
  l'équipe SSPCloud]. Un service externe (webconf de l'État, par exemple) ferait sortir le son de
  SSPCloud : exclu par la consigne.

**À ne pas faire maintenant** : ouvrir un port, installer un serveur média ou un TURN, lancer un
chart Helm, reprendre `VOICE-AGENT-ARCHITECTURE.md` ou le pipeline abandonné
`atelier-src/mcp_gateway/atelier/voice/` du pod. Le besoin est écrit ici : protocole WebRTC,
débit de 50 à 100 kbit/s par flux audio Opus, latence visée sous 300 ms de bout en bout pour le
son, participants humains authentifiés par l'Atelier.

## 6. Coût et limites (question 6)

- **CPU seul, et ça suffit pour une personne** : 1,1 s de STT et 0,4 à 0,8 s de TTS [M]. Le pod
  n'a pas de plafond de CPU posé, mais partage la machine (charge 21 sur 128) [M] : une
  inférence de voix entre en concurrence avec les agents, d'où `nice 0` pour elle seule.
- **Mémoire** : 2,2 Go tant que la voix est chaude [M], rendus après 30 min d'inactivité.
  Plafond déclaré : `memoire_max_mo: 3072`.
- **Concurrence** : un fil STT, un fil TTS ; une seule conversation vocale à la fois (la
  seconde reçoit « la voix est déjà utilisée dans un autre onglet ») ; dictées en file. Outils
  des agents : 10 min d'audio transcrit et 20 000 caractères synthétisés par conversation et
  par jour [S : ordre de grandeur à régler], pour qu'un agent ne tienne pas le CPU de la voix.
- **Modèles, par la mesure seulement** (`bench/mesurer.py`, plus un jeu de voix humaines à
  constituer, puisque le banc actuel n'entend que la voix de synthèse) :
  - STT `base` ou `tiny` : moins de temps fixe, plus d'erreurs [S] ;
  - Kokoro int8 : moins de mémoire [S] ;
  - transcription partielle pendant la parole : sans intérêt tant que le coût est fixe.
- **GPU** : pas maintenant. Le seul GPU du namespace est partagé par six projets, un pod GPU
  démarre en minutes, et le gain (environ 1 s de STT) ne vaut pas une dépendance au quota. Le
  lien projet ↔ pod GPU (`docs/onyxia-projet.md`) permettrait plus tard un projet `atelier-voix`
  déployé sur un pod GPU, avec `large-v3-turbo`, si la qualité sur voix humaine l'exige. La
  route `/v1/voix/…` ne changerait pas : seul l'amont changerait.
- **À vérifier** : le point d'accès LLM de SSPCloud sert-il un modèle de transcription ? S'il le
  fait, c'est une option dans SSPCloud, sans GPU à nous.

## 7. Découpage en lots (question 7)

Chaque lot suit les règles communes (`plan-implementation.md` §1) : worktree et branche,
périmètre de fichiers, tests qui échouent avant, documentation du thème dans le même commit,
rapport « vérifié » et « non vérifié ». Le pod reste en lecture seule pour les équipes ; le
coordinateur déploie.

**Accroches pour l'équipe de l'interface (refine en parallèle).** Ce document ne propose aucun
écran. Les lots V2 à V4 posent seulement :

- un emplacement de bouton dans le composeur, `#btn-composer-micro`, à côté de
  `#btn-composer-attach`, avec un attribut `data-etat` (`indisponible`, `pret`, `ecoute`,
  `transcription`, `erreur`) que le refine habille comme il veut ;
- une action de message « Écouter » (et « Arrêter ») dans `renderMessageActions` ;
- un indicateur d'état vocal pour la conversation de l'Assistant (`data-voix` sur le fil) ;
- un module `web/js/services/voix.js` sans DOM, qui émet des événements (`etat`, `niveau`,
  `texte`, `parole`, `lecture`) : le refine s'y abonne ;
- deux réglages dans `ui_settings` : « Voix activée », « Lire les réponses de l'Assistant ».

Libellés au lexique S2 : « Dicter », « Écouter », « Parler avec l'Assistant », « La voix se
prépare ».

### V0 : la voix devient une brique système

- **Contenu** : projet système `atelier-voix` (déplacement du dépôt de `nouveau-projet-2`,
  `projet.json` avec `systeme: true`, `ETAT.md`, remote privé) ; manifeste : `memoire_max_mo`,
  `secrets`, `env` (`HF_HUB_OFFLINE=1`, `VOICE_INFER_WORKERS` retiré au profit de deux
  exécuteurs) ; superviseur : plafond de mémoire par manifeste, statut système (hors
  `apps_max`, `nice 0`) pour la création nommée par `ATELIER_VOIX` ; service : un exécuteur STT
  et un exécuteur TTS, `VOICE_TOKEN` lu dans l'environnement ; retrait de `start.sh` de l'usage
  courant (gardé pour les essais locaux).
- **Fichiers** : Atelier `apps/manifeste.py`, `apps/superviseur.py`, une ligne dans
  `config.py`, `docs/atelier-applications.md` (champ `memoire_max_mo`) ; projet `atelier-voix` :
  `securite.py`, `inference.py`, `artifacts/voix/artefact.json`, `README.md`.
- **Tests** : manifeste (`memoire_max_mo` borné, refusé hors bornes, strict) ; superviseur
  (plafond lu du manifeste, avec l'horloge injectable ; une création système ne compte pas dans
  `apps_max` ; `nice` 0 pour elle seule) ; service (`VOICE_TOKEN` en variable ; une synthèse
  n'attend pas une transcription en cours, avec des doublures lentes).
- **Fini** : sur une copie jetable, la création système démarre, tient 2,2 Go sans redémarrer,
  répond à `/health` ; suite complète verte des deux côtés.
- **Déploiement** (coordinateur, go de Nicolas) : déplacer le dépôt, déplacer le jeton dans
  `~/work/.secrets/apps/voix`, arrêter l'instance `start.sh` (PID dans `.voice-service.pid`,
  jamais `pkill -f`).
- **Dépend de** : décisions V-1, V-2.

### V1 : les routes de la voix dans l'Atelier

- **Contenu** : module `voix.py` : `etat`, `preparer`, `transcrire`, `dire` (§3.2) ; jeton posé
  côté serveur ; démarrage à la demande par le superviseur ; filtre T10 sur le texte ; journal
  unique (§4.3) ; plafonds.
- **Fichiers** : `mcp_gateway/atelier/voix.py` (nouveau), une ligne dans `api.py`.
- **Tests** : 401 sans session ; refus d'une `Origin` étrangère (4403 en WebSocket) ; le jeton n'apparaît
  dans aucune réponse ni aucun en-tête rendu ; démarrage à la demande (superviseur factice) ;
  « la voix se prépare » pendant le démarrage ; un secret connu dit à voix haute sort caviardé ;
  la ligne de journal ne contient aucun texte ; 413 au-delà de 60 s d'audio ; service factice sur
  la boucle locale, sans modèle.
- **Fini** : sur le pod, `POST /v1/voix/transcrire` depuis l'extérieur (Ingress) rend le texte
  en moins de 1,6 s pour un énoncé de 2 s, mesuré.
- **Dépend de** : V0.

### V2 : dicter dans le composeur (Code et Assistant)

- **Contenu** : `services/voix.js` (capture, `AudioWorklet` à 16 kHz, PCM 16 bits, WAV) ;
  appuyer pour parler (bouton ou raccourci), relâcher pour transcrire ; le texte s'insère au
  curseur, **n'est jamais envoyé seul** ; préchauffage à l'appui ; erreurs en mots (micro refusé,
  rien entendu, voix indisponible).
- **Fichiers** : `web/js/services/voix.js`, `web/js/services/voix-worklet.js` (nouveaux) ; une
  accroche dans `views/code-chat.js` (`renderComposer`) ; `index.html` (emplacement du bouton).
- **Tests** (`node --test`) : conversion flottant → PCM 16 bits, rééchantillonnage, en-tête WAV
  octet par octet, machine d'états du bouton, insertion au curseur ; API simulée.
- **Fini** : dans Chrome, sur le pod, une phrase dictée apparaît dans le composeur de Code et
  de l'Assistant en moins de 2 s après le relâchement, mesuré ; rien n'est envoyé sans clic.
- **Dépend de** : V1. Parallélisable avec V3.

### V3 : écouter une réponse

- **Contenu** : action « Écouter » sur un message ; découpage en phrases (fonction pure,
  partagée avec V4) ; synthèse de la phrase suivante pendant la lecture ; « Arrêter » ; réglage
  « Lire les réponses de l'Assistant » (lecture au fil du tour, même découpage sur les
  `text_delta` reçus par la page).
- **Fichiers** : `services/voix.js`, `views/code-chat.js` (`renderMessageActions`),
  `ui_settings.py` (deux réglages).
- **Tests** : découpage (ponctuation, virgule au-delà de 60 caractères, blocs de code et
  Markdown écartés, nombres et abréviations) ; file de lecture et arrêt net.
- **Fini** : la première phrase d'une réponse se fait entendre moins de 1 s après le clic,
  mesuré.
- **Dépend de** : V1.

### V4 : parler avec l'Assistant, mains libres

- **Contenu** : service : protocole `voice.v2` avec la VAD Silero (§3.5) à la place de
  `audio/buffer.py` ; Atelier : WebSocket `/v1/voix/conversation/{session_id}`, pont (envoi
  avec `canal: "voix"`, découpage, synthèse en file, interruption), accusés préenregistrés ;
  interface : mode conversation, coupure locale du son sur `parole_debut`.
- **Fichiers** : projet `atelier-voix` : `audio/session.py`, `audio/vad.py` (nouveau),
  `voice_service.py` ; Atelier : `voix.py`, `api.py` (champ `canal` du message, une ligne),
  `web/js/services/voix.js`.
- **Tests** : VAD sur des fichiers de référence (début et fin détectés, silence ignoré) ; pont
  avec un harnais simulé (ordre des phrases, abandon à l'interruption, route d'interruption
  appelée une fois) ; une seule conversation vocale à la fois ; ping toutes les 20 s.
- **Fini** : **premier mot en moins de 3,5 s sans outil**, et accusé en moins de 2 s avec un
  outil, mesurés de bout en bout sur le pod, cinq essais (A-8) ; interruption qui coupe le son
  en moins de 300 ms ; écho mesuré avec et sans casque.
- **Dépend de** : V3 ; équipe Assistant (processus persistant du harnais, hook
  `UserPromptSubmit` pour la mention d'interruption, remplacement du hook `Stop` de 45 s :
  `assistant-harness.md` H6).

### V5 : les outils vocaux des agents

- **Contenu** : famille `voix` du serveur `atelier`, profil `code` : `atelier_voix_transcrire`
  et `atelier_voix_synthetiser`, bornés au projet, classe `reversible`, plafonds ; retrait de
  `voice` des `.mcp.json` et de `.atelier/env.json` ; ni port 18920 ni `VOICE_TOKEN` nulle part.
- **Fichiers** : `outils_conversation.py` (ou le module des outils de création du profil
  `code`), `commandes/` (définitions). L'entrée `voice` n'est pas un connecteur du pool : c'est
  une déclaration propre au `.mcp.json` du projet, que `mcp_sync._binding_du_dossier` conserve
  [L, M] ; elle se retire dans le projet système, avec `.atelier/env.json`.
- **Tests** : un chemin hors du projet est refusé ; aucun contenu audio dans le résultat d'outil
  (un chemin et une durée seulement) ; plafonds ; le vérificateur de cohérence voit la même
  famille sur les trois surfaces.
- **Fini** : un agent code transcrit un enregistrement de son projet ; le vérificateur ne voit
  plus `voice` dans aucun `.mcp.json`.
- **Dépend de** : V1 ; décision V-4.

### V6 : plus tard

- Créations qui parlent : capacité `voix:dire` par jeton de capacité, quand il existera.
- Onglet Visio d'`assistant-role.md` (A5) sur V4 et le panneau.
- Choix de modèles (§6) sur un banc de voix humaines.

### Ordre et parallélisme

```
V0 ──> V1 ──┬──> V2 (dictée)
            ├──> V3 (écouter) ──> V4 (mains libres, avec l'équipe Assistant)
            └──> V5 (agents)
```

Une équipe pour V0 et V1 (Atelier et projet système) ; une pour V2 et V3 (interface, sur les
accroches ci-dessus) ; V4 avec l'équipe Assistant ; V5 avec l'équipe des profils.

## 8. Décisions à soumettre à Nicolas

| # | Question | Recommandation |
|---|---|---|
| V-1 | Statut de la voix | brique système : projet système `atelier-voix`, lancé par le superviseur avec un statut système ; pas de connecteur dans le pool |
| V-2 | Où vit son code | un dépôt privé dédié (aujourd'hui **aucun remote** : le code n'existe que sur le volume du pod) ; pas dans l'image de l'Atelier, pour ne pas y ajouter 1,6 Go de modèles et de dépendances |
| V-3 | Chemin du son | l'origine de l'Atelier (`/v1/voix/…`), pas l'hôte des applications ; révise `assistant-harness.md` §4.9 et le transverse §1.6 (T24) |
| V-4 | Outils vocaux des agents | retirer `dire` et `ecouter` des agents ; famille `voix` sur fichiers du projet pour le profil `code` ; aucun outil vocal pour l'Assistant, dont la voix est un canal |
| V-5 | Ordre | dictée, puis écouter, puis mains libres, puis outils des agents |
| V-6 | Ressources | `nice 0`, hors des quatre places de créations, 3 Go de plafond, arrêt après 30 min, une conversation vocale à la fois |
| V-7 | API Web Speech du navigateur | interdite (le son partirait chez Google) ; règle à ajouter au socle |
| V-8 | GPU | non pour l'instant ; revoir après un banc sur voix humaines |
| V-9 | Visio | rien de WebRTC ; « Visio » veut dire voix et panneau ; visioconférence à plusieurs hors de portée tant que le namespace n'a pas d'UDP |

## 9. Évaluation

| Critère | Verdict | Sur quoi |
|---|---|---|
| **Désirable** | oui | la dictée sert tout de suite, dans Code comme dans l'Assistant ; la conversation mains libres est la promesse de l'Assistant (« on lui parle ») |
| **Faisable** | oui, par lots | service, superviseur, relais WS, garde d'`Origin`, filtre T10, journal, flux des `text_delta`, route d'interruption et VAD Silero existent [L, M] ; il manque le statut système, une route, un module d'interface et le pont |
| **Viable** | oui | CPU seul, 2,2 Go seulement quand la voix sert, aucun service externe, aucun serveur média |
| **Cohérent** | oui, avec une révision | mêmes briques et mêmes règles (§0, §1.4, §1.6 du transverse) ; seule l'origine du chemin du son change (T24) |
