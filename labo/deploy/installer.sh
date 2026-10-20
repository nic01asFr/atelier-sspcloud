#!/usr/bin/env bash
# Installe et démarre le laboratoire d'essais sur le pod d'un projet. Rejouable : ne refait que ce qui manque.
#
#   bash installer.sh <dossier-du-projet> [port]
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

PYTHONPATH="$site:$src/src" LABO_RACINE="$racine" LABO_BRUT="$brut" LABO_JETON="$(cat "$racine/.jeton")" \
  setsid python3 -m laboratoire --hote 0.0.0.0 --port "$port" > "$racine/service.log" 2>&1 < /dev/null &

for _ in $(seq 1 30); do
  if curl -fs -m 2 "http://127.0.0.1:$port/sante" >/dev/null 2>&1; then echo "démarré sur le port $port (journal : $racine/service.log)"; exit 0; fi
  sleep 1
done
echo "le service ne répond pas ; voir $racine/service.log" >&2
exit 1
