# STT & TTS Atelier

Ce projet donne une voix aux agents de l'Atelier : transcrire ce que dit la
personne (STT), dire à voix haute ce que répond l'agent (TTS), à terme pendant
une visioconférence ou un flux en direct. Tout tourne sur SSP Cloud, avec des
modèles auto-hébergés : aucun service vocal externe (ni OpenAI, ni edge-tts de
Microsoft, ni autre cloud).

## Ce qui existe (mis à jour le 24/09/2026, après les points 1 à 6)

- `voice_service.py` : FastAPI sur `127.0.0.1:18920`, CPU seul, lancé par
  `start.sh` (PID dans `.voice-service.pid`) et laissé tournant.
  STT faster-whisper `small` int8 (faisceau 1) ; TTS Kokoro-82M v1.0
  (kokoro-onnx), voix `ff_siwis`, français par défaut.
  Routes `/health` (public, `{"status":"ok"}` seul), `POST /tts`, `POST /stt`,
  WebSocket `/audio/stream/{session_id}` (STT seul, tranches de 3 s), et `/mcp`
  servi par le SDK MCP Python (`mcp_voix.py`) avec `dire` et `ecouter`.
  **C'est la seule base.** Le README du projet décrit l'existant.
- Jeton partagé dans `~/work/.secrets/voice_token` (600, créé par `start.sh`),
  exigé partout sauf `/health` ; limites de taille dans `securite.py`.
- `install.sh`, `scripts/telecharger_modeles.py` (empreintes SHA-256),
  `requirements.txt`, `requirements-dev.txt`, `pytest.ini` ; 66 tests
  (unitaires sans service, intégration sur `VOICE_URL`, scripts).
- `bench/` : 12 phrases de référence, WER et latence avant/après (résultats
  dans le README : WER 32,1 % -> 2,8 %, « piéton » 1/2 -> 2/2).
- `.mcp.json` du projet : ignoré par git ; la déclaration `voice` porte
  `"Authorization": "Bearer ${VOICE_TOKEN}"` (référence, pas la valeur).
  `VOICE_TOKEN` arrive dans les sessions par `.atelier/env.json`
  (`{"VOICE_TOKEN": "voice_token"}`, commité par `git add -f` : le dossier
  `.atelier/` est ignoré) : l'Atelier lit `~/work/.secrets/voice_token` à
  chaque tour et le pose dans l'environnement du CLI et de VS Code. Ne
  l'écris jamais en clair dans le projet.
- `artifacts/voix/artefact.json` : le service comme **artefact serveur** de
  l'Atelier (`.venv/bin/uvicorn voice_service:app --port {port}`, depuis la
  racine du projet, santé `/health`, `http` et `ws`, démarrage 180 s, arrêt
  après 30 min d'inactivité). Adresse :
  `https://<hôte des applications>/nouveau-projet-2/voix/`. C'est une seconde
  instance, sur un port attribué par l'Atelier ; celle de `start.sh` (port
  18920) reste celle que vise le `.mcp.json` des sessions. Le jeton est lu
  par le service dans `VOICE_TOKEN_FILE` (défaut `~/work/.secrets/voice_token`).
- `atelier-src/mcp_gateway/atelier/voice/` sur le pod : pipeline jamais branché,
  qui ne compile pas (`SyntaxError`) et appelle edge-tts. **Abandonné.** Ne le
  reprends pas, ne le corrige pas, ne t'en inspire pas.
- `VOICE-AGENT-ARCHITECTURE.md` s'ouvre sur « Proposition. Implémenté : voir
  README. » : rien de sa cible (WebRTC, StreamCore, GPU, Helm, JWT) n'existe.

## Défauts à corriger, dans cet ordre

Tous corrigés le 24/09/2026, un commit par point, chacun avec des tests qui
échouaient avant (hachages du dépôt du projet).

1. **[Corrigé, `dc13e80`] Sécurité** : `/mcp`, `/tts`, `/stt` et le WebSocket sont sans
   authentification ; tout agent du pod peut les appeler. Aucune limite de
   taille (texte, base64, upload, tampon audio qui grossit sans fin). Les
   messages d'exception partent au client.
2. **[Corrigé, `deccffc`] Voix** : `FR_VOICE = "am_fenrir"` est une voix anglaise américaine. La
   voix française Kokoro est `ff_siwis`. La langue par défaut est le français.
3. **[Corrigé, `a12cd48`] Boucle d'événements** : l'inférence (Whisper, Kokoro) tourne en synchrone
   dans des `async def` et bloque tous les clients. Passe-la dans un exécuteur.
4. **[Corrigé, `d77c60c`] Session WebSocket** : le timeout ne se déclenche jamais (`last_activity`
   remis à zéro avant le test), `self.is_processing` n'existe pas, la
   déconnexion normale est comptée en erreur, import circulaire inutile de
   `voice_service` dans `audio/session.py`.
5. **[Corrigé, `0cc330a`] MCP** : un seul état de session global ; `meta` au lieu de `_meta` ;
   `list_changed` au lieu de `listChanged` ; erreurs JSON-RPC renvoyées en
   HTTP 4xx/5xx. L'audio rendu par `dire` doit être un contenu
   `{"type": "audio", "data": …, "mimeType": "audio/wav"}`. Préfère le SDK MCP
   Python au protocole écrit à la main.
6. **[Corrigé, `82d2453`] Reproductibilité** : `start.sh` appelle un `install.sh` absent et dépend
   de `fuser` (absent du pod) ; `stop.sh` fait un `pkill -f` large. Un script
   versionné télécharge les modèles ; `requirements.txt` et un
   `requirements-dev.txt` déclarent tout (pytest, pytest-asyncio, httpx,
   websockets) ; les tests lisent `VOICE_URL`.

Chaque point est un commit, avec un test qui échouait avant.

## Visio et streaming : pas encore

Rien de WebRTC, LiveKit ou Jitsi n'existe. Le service est exposable comme
artefact serveur (ci-dessus, et le socle) : HTTP et WebSocket derrière la
connexion de l'Atelier, rien d'autre. N'ouvre pas de port, n'installe pas de
serveur média, ne lance pas de Helm : pour la visio, écris le besoin
(protocole, débit, latence visée, qui se connecte) et arrête-toi.

## Mesures

La qualité se mesure, elle ne s'affirme pas : pour tout changement de modèle ou
de réglage, un petit jeu de phrases françaises de référence (dont « piéton »,
transcrit « piétan » avec l'ancienne voix, juste avec `ff_siwis`), le taux
d'erreur par mot et la latence, avant et après (`bench/mesurer.py`).
