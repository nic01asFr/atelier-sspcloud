# Transcripts YouTube

Ce projet récupère le transcript d'une vidéo YouTube et le rend lisible,
cherchable, exportable (SRT) et traduisible. Il doit devenir un service que la
personne ouvre depuis l'Atelier, derrière sa connexion.

## Ce qui existe (au 24/09/2026, après la remise en forme)

Commité sur `main` (pas de remote, rien de poussé). Le `README.md` du projet
décrit l'usage ; ce qui suit est ce qu'un agent doit savoir avant d'y toucher.

- `backend.py` : FastAPI, `create_app(source, translator)` pour l'injection en
  test. Page à `/`, API sous `api/` (`transcript`, `langs`, `srt`, `search`,
  `translate`, `translate/langs`), `GET /health` sans appel réseau. Écoute sur
  `HOST`/`PORT` (défaut `127.0.0.1:18765`) ou sur `UNIX_SOCKET`. Préfixe d'URL
  pris dans `X-Forwarded-Prefix`, à défaut `ROOT_PATH` ; `<préfixe>` est
  redirigé vers `<préfixe>/`. Pas de CORS. CSP `connect-src 'self'`.
- `frontend/index.html` : le seul front, servi par le backend, appels relatifs
  (`api/...`), aucun HTML construit à partir du texte du transcript.
- `artifacts/youtube-transcript/artefact.json` : le service comme **artefact
  serveur** de l'Atelier (`python3 backend.py` depuis la racine du projet,
  santé `/health`, HTTP seul). Adresse :
  `https://<hôte des applications>/projet-sans-nom-4/youtube-transcript/`.
  L'ancienne page statique qui disait « non exposé » est retirée.
- `start.sh` / `stop.sh` : fichier `service.pid`, journal `service.log` ;
  `start.sh` refuse un port déjà occupé, `stop.sh` ne tue que ce PID et
  vérifie qu'il s'agit bien de `backend.py`.
- `requirements.txt` (service) et `requirements-dev.txt` (+ pytest, httpx).
  La dépendance Node `youtube-transcript` (inutilisée) est retirée.
- `tests/` : 54 tests pytest, réseau interdit par fixture ; réponses de
  YouTube enregistrées dans `tests/fixtures/` par `tests/record_fixtures.py`.

Un ancien `uvicorn backend:app --host 0.0.0.0 --port 18765`, lancé à la main
le 21/09 avec l'ancien code, a été arrêté le 24/09. Ne relance pas le service
autrement que par `start.sh`.

## Montrer le service

C'est un **artefact serveur** (voir le socle) : l'Atelier le lance d'après
`artifacts/youtube-transcript/artefact.json`, lui attribue `PORT`, et le sert
sous `/projet-sans-nom-4/youtube-transcript/` sur l'hôte des applications,
préfixe transmis par `X-Forwarded-Prefix`.

- Pour le démarrer : `atelier_artefact_demarrer(nom="youtube-transcript")` (le
  projet est celui de ta conversation), puis `atelier_artefact_journal` s'il
  échoue, et `atelier_montrer(nom="youtube-transcript")` quand il répond.
  Ne lance pas `backend.py` en présentant `127.0.0.1:18765` comme une
  adresse à ouvrir ; ne passe pas par `/vscode/proxy/` (fermé).
- Ne rajoute pas de CORS : la page et l'API sont servies par la même origine.
- Garde le service exposable : routes sous préfixe, chemins relatifs dans la
  page, `/health` sans réseau, écoute sur `127.0.0.1`.
- Il faut un hôte des applications configuré sur le pod
  (`ATELIER_APPS_PUBLIC_URL`) pour l'ouvrir depuis le navigateur.

## Règles propres au projet

- **Traduction** : par la passerelle LLM du SSPCloud (`/v1/messages`, modèle
  `TRANSLATE_MODEL`, défaut `gemma4-26b-moe`, rapide et sans raisonnement
  visible). La clé vient de `ANTHROPIC_API_KEY` ou du fichier
  `LLM_API_KEY_FILE` (défaut `~/work/.secrets/llm_api_key`, celui que
  l'Atelier donne à ses agents) ; jamais écrite dans le code ni dans un log.
  Langue cible dans une liste fermée, transcript plafonné à 30 000 caractères
  et envoyé par lots. `googletrans` est retiré, ne le remets pas.
- Les erreurs de YouTube (transcript désactivé, vidéo indisponible,
  limitation de débit) sont rendues avec un message clair et un code HTTP juste,
  jamais avec le texte brut de l'exception.
  Codes : 400 entrée invalide, 404 vidéo ou sous-titres absents, 413 plafond,
  422 vidéo non lisible, 502 YouTube ou passerelle en erreur, 503 limitation
  (`Retry-After`) ou traduction non configurée, 504 YouTube trop lent.
- Validation de l'identifiant de vidéo (11 caractères `[A-Za-z0-9_-]`) avant
  tout appel ; plafonds sur l'URL, la recherche, le transcript rendu et le
  transcript traduit.
- Tests : les appels à YouTube sont enregistrés une fois (fixtures) ; la CI ne
  dépend pas du réseau. Les tests couvrent l'adaptateur autour de
  `youtube-transcript-api`, pas l'analyse des pages YouTube par la
  bibliothèque : celle-ci ne se vérifie qu'en réel.
