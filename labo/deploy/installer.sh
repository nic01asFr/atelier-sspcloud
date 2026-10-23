#!/usr/bin/env bash
# Installe et démarre le laboratoire d'essais sur le pod d'un projet. Rejouable : ne refait que ce qui manque.
#
#   bash installer.sh <dossier-du-projet> [port]
#
# LABO_ROLE choisit ce que fait ce pod :
#   autonome (défaut)  le laboratoire et les essais sur le même pod (GPU) ;
#   maitre             pod CPU toujours allumé : file, essais, données, validation, commentaires ; ne lance aucun essai ;
#   gpu                pod GPU à la demande : prend les essais du maître (LABO_MAITRE=http://<ip-du-pod-cpu>:7860) et les entraîne.
#                      Le jeton du travailleur est lu dans <projet>/labo/.jeton_travailleur (à y déposer, mode 600).
#
# - les dépendances vont dans <projet>/.site (seul ~/work survit à l'arrêt du pod) ;
# - le code du laboratoire est lu dans LABO_SRC (dossier `labo/` du dépôt, par défaut <projet>/laboratoire-src) ;
# - les données du laboratoire vivent dans <projet>/labo, le brut est lu dans LABO_BRUT (par défaut <projet>/brut) ;
# - le jeton est créé une fois dans <projet>/labo/.jeton (mode 600) et jamais affiché.
set -euo pipefail

projet="$(cd "${1:?usage : installer.sh <dossier-du-projet> [port]}" && pwd)"
port="${2:-7860}"
src="${LABO_SRC:-$projet/laboratoire-src}"
brut="${LABO_BRUT:-$projet/brut}"
racine="$projet/labo"
site="$projet/.site"

[ -f "$src/pyproject.toml" ] || { echo "code du laboratoire introuvable : $src" >&2; exit 2; }
mkdir -p "$racine" "$site"

if ! PYTHONPATH="$site" python3 -c "import fastapi, uvicorn, pydantic, numpy, PIL" 2>/dev/null; then
  python3 -m pip install --quiet --target "$site" fastapi uvicorn pydantic numpy pillow
fi

umask 077
[ -s "$racine/.jeton" ] || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$racine/.jeton"

if curl -fs -m 3 "http://127.0.0.1:$port/sante" >/dev/null 2>&1; then
  echo "déjà démarré sur le port $port"
  exit 0
fi

role="${LABO_ROLE:-autonome}"
if [ "$role" = "gpu" ]; then
  [ -n "${LABO_MAITRE:-}" ] || { echo "LABO_MAITRE manque (adresse du laboratoire sur le pod CPU)" >&2; exit 2; }
  [ -s "$racine/.jeton_travailleur" ] || { echo "jeton du travailleur absent : $racine/.jeton_travailleur" >&2; exit 2; }
  if pgrep -f "[l]aboratoire.travailleur_gpu" >/dev/null; then echo "travailleur déjà démarré"; exit 0; fi
  PYTHONPATH="$site:$src/src" LABO_RACINE="$projet/gpu" LABO_MAITRE="$LABO_MAITRE" LABO_JETON_TRAVAILLEUR="$(cat "$racine/.jeton_travailleur")" \
    setsid python3 -m laboratoire.travailleur_gpu > "$racine/travailleur.log" 2>&1 < /dev/null &
  sleep 3
  pgrep -f "[l]aboratoire.travailleur_gpu" >/dev/null && { echo "travailleur démarré (journal : $racine/travailleur.log)"; exit 0; }
  echo "le travailleur ne démarre pas ; voir $racine/travailleur.log" >&2
  exit 1
fi

options=""
if [ "$role" = "maitre" ]; then
  options="--maitre"
  # le jeton du travailleur GPU : créé une fois, inscrit dans valideurs.json (relu à chaque requête, pas de redémarrage)
  [ -s "$racine/.jeton_travailleur" ] || python3 -c "import secrets; print(secrets.token_urlsafe(32))" > "$racine/.jeton_travailleur"
  python3 - "$racine" <<'PY'
import json, pathlib, sys
racine = pathlib.Path(sys.argv[1])
chemin = racine / "valideurs.json"
try:
    porteurs = json.loads(chemin.read_text(encoding="utf-8"))
except (OSError, ValueError):
    porteurs = {}
porteurs["gpu"] = {"jeton": (racine / ".jeton_travailleur").read_text(encoding="utf-8").strip(), "role": "travailleur"}
chemin.write_text(json.dumps(porteurs, indent=2), encoding="utf-8")
chemin.chmod(0o600)
PY
fi

PYTHONPATH="$site:$src/src" LABO_RACINE="$racine" LABO_BRUT="$brut" LABO_JETON="$(cat "$racine/.jeton")" \
  setsid python3 -m laboratoire --hote 0.0.0.0 --port "$port" $options > "$racine/service.log" 2>&1 < /dev/null &

for _ in $(seq 1 30); do
  if curl -fs -m 2 "http://127.0.0.1:$port/sante" >/dev/null 2>&1; then echo "démarré sur le port $port (journal : $racine/service.log)"; exit 0; fi
  sleep 1
done
echo "le service ne répond pas ; voir $racine/service.log" >&2
exit 1
