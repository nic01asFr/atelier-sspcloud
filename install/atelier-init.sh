#!/usr/bin/env bash
# Installe — ou remet en route — l'Atelier sur un pod SSPCloud.
#
# Deux façons de s'en servir, un seul script :
#
#   - sur un service Jupyter du catalogue officiel, comme init personnel
#     Onyxia (rejoué à chaque démarrage) ou à la main : il télécharge node,
#     code-server et l'extension Claude Code, clone les dépôts, installe,
#     démarre ;
#   - comme point d'entrée de l'image `atelier` (chart du catalogue) : tout
#     est déjà dans l'image, sous /opt/atelier ; il ne reste que les secrets,
#     les réglages et le démarrage, au premier plan.
#
# Idempotent : il ne refait que ce qui manque. Tout ce qui doit durer vit sur
# le volume persistant (~/work) ; $HOME est jetable et se regarnit ici.
#
# Réglages, tous par l'environnement :
#   ATELIER_LLM_API_KEY      clé de la passerelle de modèles, reprise dans
#                            ~/work/.secrets/llm_api_key si le fichier manque
#   ATELIER_OWNER_KEY        clé owner de l'Atelier ; tirée au sort sinon
#   ATELIER_GITHUB_TOKEN     jeton GitHub pour publier les projets (facultatif)
#   GIT_USER_NAME, GIT_USER_EMAIL   identité git de la machine (facultatif)
#   ATELIER_WORK             volume de travail (défaut : $HOME/work)
#   ATELIER_DEPOT            dépôt git de l'Atelier ; vide = source déjà là (ATELIER_SRC)
#   ATELIER_BRANCHE          branche à suivre (défaut : main)
#   WIKICHAT_DEPOT           dépôt git de wikichat ; vide = déjà là (WIKICHAT_SRC) ou absent
#   ATELIER_SANS_WIKICHAT    1 pour s'en passer tout à fait
#   ANTHROPIC_BASE_URL       passerelle de modèles
#   ATELIER_MODELE           modèle principal ; ATELIER_MODELE_OPUS : créneau opus ;
#                            ATELIER_MODELES_DE_REPLI : replis (le dernier sert aussi haiku)
#   CODE_SERVER_VERSION, NODE_VERSION : versions épinglées
#   ATELIER_NODE_DIR, ATELIER_CODE_SERVER_DIR, ATELIER_EXTENSIONS : outils déjà posés
#   ATELIER_AVANT_PLAN       1 pour tenir l'Atelier au premier plan (conteneur)
set -euo pipefail

WORK="${ATELIER_WORK:-$HOME/work}"
DEPOT_ATELIER="${ATELIER_DEPOT-https://github.com/nic01asFr/atelier-sspcloud.git}"
BRANCHE_ATELIER="${ATELIER_BRANCHE:-main}"
DEPOT_WIKICHAT="${WIKICHAT_DEPOT-https://github.com/nic01asFr/wikichat.git}"
SANS_WIKICHAT="${ATELIER_SANS_WIKICHAT:-0}"
VERSION_CODE_SERVER="${CODE_SERVER_VERSION:-4.135.0}"
VERSION_NODE="${NODE_VERSION:-22.23.2}"
VERSION_CHROME_MCP="${CHROME_MCP_VERSION:-1.10.1}"
PASSERELLE_LLM="${ANTHROPIC_BASE_URL:-https://llm.lab.sspcloud.fr/api}"
MODELE="${ATELIER_MODELE:-qwen3-6-35b-moe}"
# gemma4-26b-moe n'est plus ni au créneau opus ni parmi les replis : mesuré le
# 25/09/2026, il échoue dès le premier tour de Claude Code (« 'None' has no
# attribute 'split' »). Le créneau opus prend le modèle principal, le seul
# qui tienne des tours longs ; qwen3-8-27b reste le repli et le créneau haiku.
MODELE_OPUS="${ATELIER_MODELE_OPUS:-qwen3-6-35b-moe}"
MODELES_DE_REPLI="${ATELIER_MODELES_DE_REPLI:-qwen3-8-27b}"
PORT_ATELIER="${ATELIER_PORT:-8787}"
PORT_CODE_SERVER=8080
PORT_WIKICHAT=3777
PORT_RELAIS_LLM="${ATELIER_RELAIS_LLM_PORT:-8790}"
# Le relais LLM (mcp_gateway.atelier.relais_llm) : toutes les surfaces parlent
# au modèle par lui, pour que la compaction native de Claude Code fonctionne.
RELAIS_LLM="http://127.0.0.1:$PORT_RELAIS_LLM"

OUTILS="$WORK/.tools"
BIN="$WORK/bin"
SECRETS="$WORK/.secrets"
JOURNAUX="$WORK/logs"
DEPOTS="$WORK/repos"
CLONE_ATELIER="$DEPOTS/atelier-sspcloud"
SRC_ATELIER="$WORK/atelier-src"
SOURCE_ATELIER="${ATELIER_SRC:-$CLONE_ATELIER/atelier-src}"
SRC_WIKICHAT="${WIKICHAT_SRC:-$WORK/wikichat/src}"
DOSSIER_NODE="${ATELIER_NODE_DIR:-$OUTILS/node-v$VERSION_NODE-linux-x64}"
DOSSIER_CODE_SERVER="${ATELIER_CODE_SERVER_DIR:-$OUTILS/code-server-$VERSION_CODE_SERVER-linux-amd64}"
EXTENSIONS="${ATELIER_EXTENSIONS:-$HOME/.local/share/code-server/extensions}"
CACHE_EXTENSIONS="$WORK/.code-server-extensions"

dire() { printf '[atelier-init] %s\n' "$*"; }
avertir() { printf '[atelier-init] ATTENTION : %s\n' "$*" >&2; }

# --- dossiers -------------------------------------------------------------

mkdir -p "$OUTILS" "$BIN" "$JOURNAUX" "$DEPOTS" "$WORK/.claude" "$EXTENSIONS" "$CACHE_EXTENSIONS"
mkdir -p "$SECRETS" && chmod 700 "$SECRETS"
export PATH="$BIN:$DOSSIER_NODE/bin:$PATH"

# --- node et npm ----------------------------------------------------------
# L'image Jupyter n'en a pas. Une version épinglée, dans le volume : wikichat
# et les serveurs MCP en JavaScript en ont besoin.

if [ ! -x "$DOSSIER_NODE/bin/node" ]; then
  dire "node $VERSION_NODE"
  archive="node-v$VERSION_NODE-linux-x64.tar.xz"
  curl -fsSL "https://nodejs.org/dist/v$VERSION_NODE/$archive" -o "$OUTILS/$archive"
  tar -xJf "$OUTILS/$archive" -C "$OUTILS"
  rm -f "$OUTILS/$archive"
fi
ln -sfn "$DOSSIER_NODE/bin/node" "$BIN/node"
ln -sfn "$DOSSIER_NODE/bin/npm" "$BIN/npm"
ln -sfn "$DOSSIER_NODE/bin/npx" "$BIN/npx"

# --- navigateur -----------------------------------------------------------
# Le serveur MCP du navigateur (chrome-devtools-mcp, Apache-2.0), épinglé, dans
# le volume — l'image l'embarque déjà sous /opt/atelier/outils. Chaque agent le
# lance par ~/work/bin/atelier-chrome (voir docs/navigateur-atelier.md). Chrome
# vient du volume (installé ci-dessous), de l'image, ou du système ; sans lui,
# le navigateur reste déclaré mais indisponible, et l'écran des connecteurs le dit.

paquet_navigateur=node_modules/chrome-devtools-mcp/package.json
if [ ! -f "${ATELIER_OUTILS:-/opt/atelier/outils}/chrome-devtools-mcp/$paquet_navigateur" ]   && [ ! -f "$OUTILS/chrome-devtools-mcp/$paquet_navigateur" ]; then
  dire "chrome-devtools-mcp $VERSION_CHROME_MCP"
  mkdir -p "$OUTILS/chrome-devtools-mcp"
  npm install --prefix "$OUTILS/chrome-devtools-mcp" --no-audit --no-fund --save-exact     "chrome-devtools-mcp@$VERSION_CHROME_MCP" >/dev/null 2>&1     || avertir "chrome-devtools-mcp ne s'est pas installé : pas de navigateur pour les agents"
fi

# Chrome lui-même, sur le volume. Un pod du catalogue Jupyter ne tourne pas sur
# l'image de l'Atelier : un Chrome posé dans le système (/usr/bin/google-chrome)
# disparaît à son redémarrage. On installe donc, une fois, un Chrome sans écran
# dans ~/work/.tools, par `@puppeteer/browsers` (épinglé) et le Node ci-dessus
# (il exige Node 22.12+). atelier-chrome le prend avant celui du système.
#   ATELIER_CHROME_NAVIGATEUR  chrome-headless-shell (défaut, ~100 Mo, sans
#                              interface) | chrome (Chrome for Testing complet)
#   ATELIER_CHROME_CANAL       stable (défaut) | beta | un numéro de version
#   ATELIER_CHROME_VOLUME=0    ne rien installer (Chrome fourni autrement)
# Sur l'image de l'Atelier, Chrome est dans l'image : rien à faire.
VERSION_PUPPETEER_BROWSERS="${PUPPETEER_BROWSERS_VERSION:-3.2.3}"
NAVIGATEUR_CHROME="${ATELIER_CHROME_NAVIGATEUR:-chrome-headless-shell}"
CANAL_CHROME="${ATELIER_CHROME_CANAL:-stable}"
chrome_du_volume() {
  local c
  case "$NAVIGATEUR_CHROME" in
    chrome) set -- "$OUTILS"/chrome/linux*/chrome-linux64/chrome ;;
    *) set -- "$OUTILS"/chrome-headless-shell/linux*/chrome-headless-shell-linux64/chrome-headless-shell ;;
  esac
  for c in "$@"; do
    [ -x "$c" ] && { echo "$c"; return 0; }
  done
  return 1
}
if [ "${ATELIER_CHROME_VOLUME:-1}" = "0" ] || [ -n "${ATELIER_CHROME_BIN:-}" ]; then
  :
elif [ -f "${ATELIER_OUTILS:-/opt/atelier/outils}/chrome-devtools-mcp/$paquet_navigateur" ] \
  && command -v google-chrome >/dev/null 2>&1; then
  :
elif ! chrome_du_volume >/dev/null; then
  dire "Chrome sans écran ($NAVIGATEUR_CHROME@$CANAL_CHROME) dans $OUTILS"
  (cd "$OUTILS" && "$DOSSIER_NODE/bin/npx" --yes "@puppeteer/browsers@$VERSION_PUPPETEER_BROWSERS" \
      install "$NAVIGATEUR_CHROME@$CANAL_CHROME" --path "$OUTILS" >> "$JOURNAUX/chrome-install.log" 2>&1) \
    || avertir "Chrome ne s'est pas installé dans $OUTILS (voir $JOURNAUX/chrome-install.log) : les agents n'auront un navigateur que si le système en a un"
fi
if chrome_volume="$(chrome_du_volume)"; then
  # Le binaire ne suffit pas : il lui faut des bibliothèques du système
  # (nss, gbm…), que l'image Jupyter n'a pas forcément. On le dit ici plutôt
  # qu'au premier outil de navigation d'un agent.
  manquantes="$(ldd "$chrome_volume" 2>/dev/null | awk '/not found/ {print $1}' | sort -u | tr '\n' ' ' || true)"
  if [ -n "$manquantes" ]; then
    avertir "Chrome du volume ($chrome_volume) : bibliothèques système absentes : $manquantes(docs/navigateur-atelier.md, « Chrome durable »)"
  else
    dire "Chrome du volume : $chrome_volume"
  fi
fi

# --- code-server et l'extension Claude Code -------------------------------
# Le binaire `claude` est celui que l'extension embarque : on n'installe pas
# le CLI à part, on le prend là où VS Code le prend.

if [ ! -x "$DOSSIER_CODE_SERVER/bin/code-server" ]; then
  dire "code-server $VERSION_CODE_SERVER"
  archive="code-server-$VERSION_CODE_SERVER-linux-amd64.tar.gz"
  curl -fsSL "https://github.com/coder/code-server/releases/download/v$VERSION_CODE_SERVER/$archive" \
    -o "$OUTILS/$archive"
  tar -xzf "$OUTILS/$archive" -C "$OUTILS"
  rm -f "$OUTILS/$archive"
fi
CODE_SERVER="$DOSSIER_CODE_SERVER/bin/code-server"
[ -w "$EXTENSIONS" ] && echo "{}" > "$EXTENSIONS/.obsolete"
if ! "$CODE_SERVER" --extensions-dir "$EXTENSIONS" --list-extensions 2>/dev/null | grep -qi '^anthropic\.claude-code$'; then
  # Le cache sur le volume évite de retélécharger l'extension à chaque pod.
  if compgen -G "$CACHE_EXTENSIONS/anthropic.claude-code-*" > /dev/null; then
    cp -a "$CACHE_EXTENSIONS"/anthropic.claude-code-* "$EXTENSIONS"/ 2>/dev/null || true
  fi
  if ! "$CODE_SERVER" --extensions-dir "$EXTENSIONS" --list-extensions 2>/dev/null | grep -qi '^anthropic\.claude-code$'; then
    dire "extension Claude Code"
    "$CODE_SERVER" --extensions-dir "$EXTENSIONS" --install-extension anthropic.claude-code --force >/dev/null 2>&1 \
      || avertir "l'extension Claude Code ne s'est pas installée (open-vsx injoignable ?)"
    cp -a "$EXTENSIONS"/anthropic.claude-code-* "$CACHE_EXTENSIONS"/ 2>/dev/null || true
  fi
fi
extension="$(ls -d "$EXTENSIONS"/anthropic.claude-code-* 2>/dev/null | sort -V | tail -1 || true)"
if [ -n "$extension" ] && [ -x "$extension/resources/native-binary/claude" ]; then
  ln -sfn "$extension/resources/native-binary/claude" "$BIN/claude"
else
  avertir "aucun binaire claude : l'Atelier démarrera mais aucun tour ne pourra tourner"
fi

# --- l'Atelier ------------------------------------------------------------
# Cloné et suivi quand on lui donne un dépôt ; pris tel quel quand l'image
# l'embarque déjà (ATELIER_DEPOT vide).

if [ -n "$DEPOT_ATELIER" ]; then
  if [ -d "$CLONE_ATELIER/.git" ]; then
    dire "Atelier : mise à jour ($BRANCHE_ATELIER)"
    git -C "$CLONE_ATELIER" fetch -q origin "$BRANCHE_ATELIER" \
      && git -C "$CLONE_ATELIER" merge -q --ff-only "origin/$BRANCHE_ATELIER" \
      || avertir "le dépôt de l'Atelier n'a pas pu être mis à jour ; on garde la version présente"
  else
    dire "Atelier : clone de $DEPOT_ATELIER"
    git clone -q --branch "$BRANCHE_ATELIER" "$DEPOT_ATELIER" "$CLONE_ATELIER"
  fi
  SOURCE_ATELIER="$CLONE_ATELIER/atelier-src"
fi
if [ ! -d "$SOURCE_ATELIER" ]; then
  avertir "source de l'Atelier introuvable : $SOURCE_ATELIER"
  exit 1
fi
# ~/work/atelier-src est l'adresse que les scripts connaissent. Un pod où le
# code a été posé à la main l'a comme vrai dossier : on n'y touche pas.
if [ ! -e "$SRC_ATELIER" ] || [ -L "$SRC_ATELIER" ]; then
  ln -sfn "$SOURCE_ATELIER" "$SRC_ATELIER"
else
  avertir "$SRC_ATELIER est un dossier posé à la main, pas le clone : la source suivie est $SOURCE_ATELIER"
fi
if [ -n "$DEPOT_ATELIER" ] || ! python3 -c "import mcp_gateway.atelier" 2>/dev/null; then
  dire "paquet Python"
  python3 -m pip install -q -e "$SOURCE_ATELIER" 2>&1 | tail -1 || avertir "pip install a échoué"
fi
for script in atelier-relancer atelier-figer-le-travail.sh atelier-app atelier-verifier-coherence atelier-chrome atelier-claude-vscode atelier-bashrc; do
  if [ -f "$SOURCE_ATELIER/bin/$script" ]; then
    cp -f "$SOURCE_ATELIER/bin/$script" "$BIN/$script" && chmod +x "$BIN/$script"
  fi
done

# --- wikichat -------------------------------------------------------------
# Optionnel : sans lui, les onglets Assistant et Agents restent vides, le
# reste de l'Atelier fonctionne.

if [ "$SANS_WIKICHAT" = "1" ]; then
  DEPOT_WIKICHAT=""
  SRC_WIKICHAT=""
fi
if [ -n "$DEPOT_WIKICHAT" ]; then
  if [ -d "$SRC_WIKICHAT/.git" ]; then
    dire "wikichat : mise à jour"
    git -C "$SRC_WIKICHAT" pull -q --ff-only || avertir "wikichat n'a pas pu être mis à jour"
  else
    dire "wikichat : clone"
    mkdir -p "$(dirname "$SRC_WIKICHAT")"
    git clone -q "$DEPOT_WIKICHAT" "$SRC_WIKICHAT"
  fi
  if [ ! -d "$SRC_WIKICHAT/node_modules" ] || [ "$SRC_WIKICHAT/package-lock.json" -nt "$SRC_WIKICHAT/node_modules" ]; then
    dire "wikichat : dépendances"
    (cd "$SRC_WIKICHAT" && "$BIN/npm" ci --omit=dev --no-audit --no-fund >/dev/null 2>&1) \
      || avertir "npm ci a échoué dans $SRC_WIKICHAT"
  fi
fi
AVEC_WIKICHAT=0
[ -n "$SRC_WIKICHAT" ] && [ -f "$SRC_WIKICHAT/server.mjs" ] && AVEC_WIKICHAT=1

# --- secrets --------------------------------------------------------------
# Rien de tout cela ne passe par un fichier du dépôt. Ce qui vient de
# l'environnement (Vault, chart) s'écrit une fois sur le volume ; le reste se
# tire au sort et y reste.

poser_secret() {
  local nom="$1" valeur="${2:-}"
  if [ ! -s "$SECRETS/$nom" ] && [ -n "$valeur" ]; then
    printf '%s' "$valeur" > "$SECRETS/$nom"
    dire "$nom posé depuis l'environnement"
  fi
}
poser_secret llm_api_key "${ATELIER_LLM_API_KEY:-}"
poser_secret atelier_owner_key "${ATELIER_OWNER_KEY:-}"
poser_secret github_token "${ATELIER_GITHUB_TOKEN:-}"
if [ ! -s "$SECRETS/llm_api_key" ]; then
  avertir "pas de clé LLM : créez-en une sur ${PASSERELLE_LLM%/api} et écrivez-la dans $SECRETS/llm_api_key"
fi
for secret in atelier_owner_key atelier_internal_secret; do
  if [ ! -s "$SECRETS/$secret" ]; then
    openssl rand -hex 24 > "$SECRETS/$secret"
    dire "$secret tiré au sort"
  fi
done
chmod 600 "$SECRETS"/* 2>/dev/null || true

# Le fichier d'environnement unique : les valeurs des références ${ATELIER_MCP_…}
# que portent les fichiers MCP. L'Atelier le régénère (env_secrets.py) ; le
# shell le charge, pour qu'un `claude` lancé au terminal ait les mêmes
# connecteurs que dans l'Atelier et VS Code.
#
# La ligne va en TÊTE de ~/.bashrc, avant la garde non interactive (audit G1) :
# ajoutée à la fin, elle n'était jamais lue par `bash -lc`, `ssh hote cmd` ni un
# agent qui relance `claude`. `atelier-bashrc` déplace aussi une ligne déjà mal
# placée ; un second passage ne change rien.
ENV_SECRETS="$SECRETS/claude-env.sh"
if [ -f "$HOME/.bashrc" ] || [ -w "$HOME" ]; then
  if [ -f "$SOURCE_ATELIER/bin/atelier-bashrc" ]; then
    etat_bashrc="$(sh "$SOURCE_ATELIER/bin/atelier-bashrc" "$HOME/.bashrc" "$ENV_SECRETS" 2>/dev/null || echo "échec")"
    case "$etat_bashrc" in
      posé) dire "~/.bashrc charge $ENV_SECRETS avant sa garde non interactive" ;;
      inchangé) ;;
      *) avertir "~/.bashrc n'a pas pu être mis à jour : un shell non interactif n'aura pas les secrets" ;;
    esac
  else
    avertir "atelier-bashrc absent de $SOURCE_ATELIER/bin : ~/.bashrc non mis à jour"
  fi
fi

# L'identité git de la machine, si on nous la donne et qu'elle n'y est pas :
# c'est elle qui signe les commits des projets, pas l'Atelier.
if [ -n "${GIT_USER_EMAIL:-}" ] && [ -z "$(git config --global user.email 2>/dev/null)" ]; then
  git config --global user.email "$GIT_USER_EMAIL"
  [ -n "${GIT_USER_NAME:-}" ] && git config --global user.name "$GIT_USER_NAME"
  dire "identité git posée : ${GIT_USER_NAME:-} <$GIT_USER_EMAIL>"
fi

# --- réglages du CLI ------------------------------------------------------
# Écrits une fois sur le volume, recopiés dans $HOME à chaque démarrage.
# On ne réécrit pas un fichier existant : il peut porter des choix faits
# depuis (crochets, modèles).

if [ ! -s "$WORK/.claude/settings.json" ]; then
  dire "réglages du CLI"
  replis="$(printf '%s' "$MODELES_DE_REPLI" | tr ',' '\n' | sed 's/^ *//;s/ *$//' | grep -v '^$' | sed 's/.*/"&"/' | paste -sd, -)"
  crochets='{}'
  if [ "$AVEC_WIKICHAT" = "1" ]; then
    crochets="{\"Stop\":[{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$BIN/node \\\"$SRC_WIKICHAT/scripts/wikichat-mailbox-hook.mjs\\\"\"}]}],\"SessionEnd\":[{\"matcher\":\"\",\"hooks\":[{\"type\":\"command\",\"command\":\"$BIN/atelier-figer-le-travail.sh\"}]}]}"
  fi
  # La fenêtre est la vraie (131 072 pour les modèles servis) : le relais
  # LLM rend au CLI le décompte que la passerelle met à zéro, et la
  # compaction native part d'elle-même. Un fichier déjà là garde ses
  # anciennes valeurs jusqu'au démarrage de l'Atelier, qui les corrige
  # (write_claude_settings_env).
  cat > "$WORK/.claude/settings.json" <<EOF
{
  "model": "$MODELE",
  "autoCompactEnabled": true,
  "fallbackModel": [$replis],
  "hooks": $crochets,
  "apiKeyHelper": "cat $SECRETS/llm_api_key",
  "effortLevel": "medium",
  "env": {
    "ANTHROPIC_BASE_URL": "$RELAIS_LLM",
    "ANTHROPIC_MODEL": "$MODELE",
    "ANTHROPIC_DEFAULT_MODEL": "$MODELE",
    "ANTHROPIC_DEFAULT_SONNET_MODEL": "$MODELE",
    "ANTHROPIC_DEFAULT_OPUS_MODEL": "$MODELE_OPUS",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL": "${MODELES_DE_REPLI##*,}",
    "CLAUDE_CODE_MAX_CONTEXT_TOKENS": "131072",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "8192",
    "CLAUDE_CODE_EFFORT_LEVEL": "medium",
    "CLAUDE_CODE_DISABLE_1M_CONTEXT": "1",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"
  }
}
EOF
fi
mkdir -p "$HOME/.claude"
# Un seul fichier : ~/.claude/settings.json est un lien vers celui du volume.
# L'Atelier, wikichat (ses hooks) et Claude Code y écrivent ; deux copies
# recopiées l'une sur l'autre effaçaient les entrées d'un auteur. Un vrai
# fichier déjà là (init rejouée sur un pod en marche, ou lien remplacé par un
# auteur qui écrit par renommage) est laissé : l'Atelier le fusionne dans celui
# du volume puis repose le lien (claude_home.unifier_les_reglages).
if [ ! -e "$HOME/.claude/settings.json" ] || [ -L "$HOME/.claude/settings.json" ]; then
  ln -sfn "$WORK/.claude/settings.json" "$HOME/.claude/settings.json"
fi

cat > "$BIN/claude-env.sh" <<EOF
# Source : . $BIN/claude-env.sh
WORK="\${CLAUDE_WORK:-$WORK}"
export ANTHROPIC_BASE_URL="\${ANTHROPIC_BASE_URL:-$RELAIS_LLM}"
if [ -z "\${ANTHROPIC_API_KEY:-}" ] && [ -f "\$WORK/.secrets/llm_api_key" ]; then
  export ANTHROPIC_API_KEY="\$(cat "\$WORK/.secrets/llm_api_key")"
fi
export PATH="\$WORK/bin:\${PATH}"
if [ -f "\$WORK/.claude/settings.json" ]; then
  mkdir -p "\$HOME/.claude"
  if [ ! -e "\$HOME/.claude/settings.json" ] || [ -L "\$HOME/.claude/settings.json" ]; then
    ln -sfn "\$WORK/.claude/settings.json" "\$HOME/.claude/settings.json" 2>/dev/null || true
  fi
fi
export ANTHROPIC_MODEL="\${ANTHROPIC_MODEL:-$MODELE}"
EOF

# --- démarrage ------------------------------------------------------------

demarrer_relais_llm() {
  # Avant code-server et wikichat : leurs `claude` parlent au modèle par lui.
  # Processus à part, pour survivre aux redémarrages de l'Atelier.
  if curl -fsS -o /dev/null "$RELAIS_LLM/_relais/sante" 2>/dev/null; then
    dire "relais LLM déjà en route"
    return
  fi
  (cd "$SRC_ATELIER" && ATELIER_WORK="$WORK" ATELIER_ANTHROPIC_BASE_URL="$PASSERELLE_LLM" \
      ATELIER_RELAIS_LLM_PORT="$PORT_RELAIS_LLM" \
      setsid nohup python3 -m mcp_gateway.atelier.relais_llm \
      >> "$JOURNAUX/relais-llm.log" 2>&1 < /dev/null &)
  dire "relais LLM lancé ($RELAIS_LLM)"
}

demarrer_gardiens() {
  # L'exécuteur des gardiens (mcp_gateway.gardiens) : contrôles de santé et de
  # sécurité, sans modèle. Processus à part : un gardien ne vit pas dans ce
  # qu'il garde. ATELIER_GARDIENS=0 le coupe (docs/vision/gardiens.md).
  [ "${ATELIER_GARDIENS:-1}" = "0" ] && { dire "gardiens coupés (ATELIER_GARDIENS=0)"; return 0; }
  curl -fsS -o /dev/null "http://127.0.0.1:${ATELIER_GARDIENS_PORT:-8791}/sante" 2>/dev/null && { dire "gardiens déjà en route"; return 0; }
  (cd "$SRC_ATELIER" && ATELIER_WORK="$WORK" setsid nohup nice -n 10 python3 -m mcp_gateway.gardiens \
      >> "$JOURNAUX/gardiens.log" 2>&1 < /dev/null &)
  dire "gardiens lancés"
}

demarrer_code_server() {
  local config="$WORK/.config-code-server"
  mkdir -p "$config" "$JOURNAUX/code-server"
  # Loopback et sans mot de passe : c'est l'Atelier qui le sert, derrière sa
  # propre porte (/vscode), et lui seul l'atteint.
  # disable-proxy : sans lui, /vscode/proxy/<port>/ menait, derrière la porte
  # de l'Atelier, à n'importe quel service en boucle locale du pod. L'Atelier
  # refuse aussi ces chemins ; ceci ferme la route à la source. Une instance
  # déjà lancée ne le prend qu'à son redémarrage.
  printf 'bind-addr: 127.0.0.1:%s\nauth: none\ncert: false\ndisable-proxy: true\n' "$PORT_CODE_SERVER" > "$config/config.yaml"
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT_CODE_SERVER/" 2>/dev/null; then
    dire "code-server déjà en route"
    return
  fi
  nohup "$CODE_SERVER" --config "$config/config.yaml" --extensions-dir "$EXTENSIONS" "$WORK" \
    >> "$JOURNAUX/code-server/code-server.log" 2>&1 < /dev/null &
  dire "code-server lancé"
}

demarrer_wikichat() {
  [ "$AVEC_WIKICHAT" = "1" ] || return 0
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT_WIKICHAT/api/health" 2>/dev/null; then
    dire "wikichat déjà en route"
    return
  fi
  if [ ! -s "$SECRETS/llm_api_key" ]; then
    avertir "wikichat non lancé : il lui faut la clé LLM"
    return
  fi
  # wikichat hérite du fichier d'environnement unique : les `claude` qu'il
  # lance y trouvent les valeurs des références. Il doit aussi le relire à
  # chaque lancement (docs/coherence-projet.md) : un jeton renouvelé après son
  # démarrage ne serait pas dans son environnement.
  (cd "$SRC_WIKICHAT" && { [ -r "$ENV_SECRETS" ] && . "$ENV_SECRETS"; true; } && nohup env PORT="$PORT_WIKICHAT" \
      ANTHROPIC_API_KEY="$(cat "$SECRETS/llm_api_key")" \
      ANTHROPIC_BASE_URL="$RELAIS_LLM" \
      WIKICHAT_ALLOWED_HOSTS=127.0.0.1,localhost \
      "$BIN/node" server.mjs >> "$JOURNAUX/wikichat.log" 2>&1 < /dev/null &)
  dire "wikichat lancé"
}

environnement_atelier() {
  export ATELIER_WORK="$WORK"
  export ATELIER_VSCODE_INTERNAL_URL="http://127.0.0.1:$PORT_CODE_SERVER"
  export ATELIER_VSCODE_UPSTREAM_AUTH="atelier"
  # Le pont stdio de wikichat que déclarent les agents (wikichat_mcp.py).
  [ -n "$SRC_WIKICHAT" ] && export ATELIER_WIKICHAT_SRC="$SRC_WIKICHAT"
  return 0
}

demarrer_atelier() {
  if curl -fsS -o /dev/null "http://127.0.0.1:$PORT_ATELIER/v1/health" 2>/dev/null; then
    dire "Atelier déjà en route"
    return
  fi
  environnement_atelier
  (cd "$SRC_ATELIER" && setsid nohup python3 -m mcp_gateway.atelier.app --host 0.0.0.0 --port "$PORT_ATELIER" \
      >> "$JOURNAUX/atelier-uvicorn.log" 2>&1 < /dev/null &)
  dire "Atelier lancé"
}

etat() { curl -s -o /dev/null -w '%{http_code}' -m 5 "$1" 2>/dev/null || true; }
bilan() {
  dire "claude : $("$BIN/claude" --version 2>/dev/null | head -1 || echo 'absent')"
  dire "clé owner (pour ouvrir l'Atelier) : cat $SECRETS/atelier_owner_key"
  dire "adresse : ${ATELIER_PUBLIC_URL:-le port $PORT_ATELIER de ce service, tel qu'Onyxia l'expose}"
}

demarrer_relais_llm
demarrer_code_server
demarrer_wikichat
demarrer_gardiens

if [ "${ATELIER_AVANT_PLAN:-0}" = "1" ]; then
  # Dans un conteneur, l'Atelier est le processus principal : s'il tombe,
  # le pod redémarre, et avec lui code-server et wikichat.
  sleep 3
  dire "code-server : $(etat "http://127.0.0.1:$PORT_CODE_SERVER/")   wikichat : $(etat "http://127.0.0.1:$PORT_WIKICHAT/api/health")   Atelier : au premier plan"
  bilan
  environnement_atelier
  cd "$SRC_ATELIER"
  exec python3 -m mcp_gateway.atelier.app --host 0.0.0.0 --port "$PORT_ATELIER"
fi

demarrer_atelier
sleep 5
dire "relais LLM : $(etat "$RELAIS_LLM/_relais/sante")   code-server : $(etat "http://127.0.0.1:$PORT_CODE_SERVER/")   wikichat : $(etat "http://127.0.0.1:$PORT_WIKICHAT/api/health")   Atelier : $(etat "http://127.0.0.1:$PORT_ATELIER/v1/health")"
bilan
