#!/usr/bin/env bash
# install.sh — Déploie l'Atelier dans VOTRE namespace SSPCloud, sans passer
# par le catalogue Onyxia.
#
# Chart  : https://nic01asfr.github.io/atelier-sspcloud (dépôt Helm sur GitHub Pages)
# Image  : ghcr.io/nic01asfr/atelier (tirée par le pod)
#
# Depuis un terminal d'un service Onyxia (Jupyter, VS Code) lancé avec
#   Kubernetes > accès depuis le service : oui
#   Kubernetes > rôle                   : edit
#
#   curl -fsSL https://nic01asfr.github.io/atelier-sspcloud/install.sh | bash
#
# Variables facultatives :
#   RELEASE              nom de la release (défaut : atelier)
#   ATELIER_LLM_API_KEY  clé de https://llm.lab.sspcloud.fr ; sinon celle
#                        d'une installation précédente est reprise
#   ATELIER_MODELE       modèle par défaut
#   ATELIER_OWNER_KEY    clé owner imposée ; sinon le chart la tire au sort
#                        une fois et la garde d'une mise à jour à l'autre
#   VERSION              version du chart (défaut : la dernière)
#   IMAGE_TAG            étiquette de l'image (défaut : latest)
set -euo pipefail

RELEASE="${RELEASE:-atelier}"
REPO_NAME="atelier"
HELM_REPO="https://nic01asfr.github.io/atelier-sspcloud"
GIT_REPO="https://github.com/nic01asFr/atelier-sspcloud.git"
REF="${REF:-main}"

SA_NS_FILE="/var/run/secrets/kubernetes.io/serviceaccount/namespace"
NS="${NAMESPACE:-${KUBERNETES_NAMESPACE:-}}"
if [[ -z "$NS" && -f "$SA_NS_FILE" ]]; then
  NS=$(cat "$SA_NS_FILE")
fi
USERNAME="${ONYXIA_USER:-${NS#user-}}"
if [[ -z "$NS" || -z "$USERNAME" ]]; then
  echo "ERREUR : impossible de détecter le namespace SSPCloud."
  echo "Lancez ce script depuis un terminal d'un service Onyxia."
  exit 1
fi

K8S_DOMAIN="${K8S_DOMAIN:-${ONYXIA_DOMAIN:-user.lab.sspcloud.fr}}"
HOST="user-${USERNAME}-${RELEASE}.${K8S_DOMAIN}"

if [[ -t 1 ]]; then
  GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RED=$'\033[31m'; CYAN=$'\033[36m'; RESET=$'\033[0m'
else
  GREEN=""; YELLOW=""; RED=""; CYAN=""; RESET=""
fi
log()  { echo "${CYAN}[--]${RESET} $*"; }
ok()   { echo "${GREEN}[OK]${RESET} $*"; }
warn() { echo "${YELLOW}[!!]${RESET} $*"; }
die()  { echo "${RED}[KO]${RESET} $*" >&2; exit 1; }

log "Vérification des prérequis..."
command -v kubectl >/dev/null || die "kubectl introuvable."
command -v helm    >/dev/null || die "helm introuvable."

if ! kubectl auth can-i create statefulsets -n "$NS" >/dev/null 2>&1; then
  die "Droits Kubernetes insuffisants dans $NS.

  Relancez le service terminal avec :
    Kubernetes > Enable access from within the service : oui
    Kubernetes > Kubernetes role                       : edit

  (Le rôle par défaut 'view' ne permet pas de créer le StatefulSet.)"
fi

# Le Secret du chart est réécrit à chaque mise à jour à partir des valeurs :
# une clé de modèle absente de l'environnement est reprise de l'installation
# précédente plutôt qu'effacée.
FULLNAME="$RELEASE"
[[ "$RELEASE" == *atelier* ]] || FULLNAME="${RELEASE}-atelier"
SECRET_NAME="${FULLNAME}-secrets"
lire_secret() {
  kubectl get secret "$SECRET_NAME" -n "$NS" -o jsonpath="{.data.$1}" 2>/dev/null \
    | base64 -d 2>/dev/null || true
}
LLM_KEY="${ATELIER_LLM_API_KEY:-$(lire_secret ATELIER_LLM_API_KEY)}"
if [[ -n "$LLM_KEY" ]]; then
  ok "Clé de modèle : fournie"
else
  warn "Aucune clé de modèle : les conversations ne répondront pas.
     Créez-en une sur https://llm.lab.sspcloud.fr puis relancez avec
     ATELIER_LLM_API_KEY=... bash install.sh"
fi

export HELM_CONFIG_HOME="${HELM_CONFIG_HOME:-/tmp/atelier-helm/config}"
export HELM_CACHE_HOME="${HELM_CACHE_HOME:-/tmp/atelier-helm/cache}"
export HELM_DATA_HOME="${HELM_DATA_HOME:-/tmp/atelier-helm/data}"
mkdir -p "$HELM_CONFIG_HOME" "$HELM_CACHE_HOME" "$HELM_DATA_HOME"

echo ""
echo "+==============================================================+"
echo "|  Installation de l'Atelier — $USERNAME"
echo "|  Namespace : $NS"
echo "|  URL       : https://$HOST/"
echo "+==============================================================+"
echo ""

CHART_REF=""
log "[1/3] Dépôt Helm : $HELM_REPO"
if helm repo add "$REPO_NAME" "$HELM_REPO" --force-update >/dev/null 2>&1 \
   && helm repo update "$REPO_NAME" >/dev/null 2>&1; then
  CHART_REF="$REPO_NAME/atelier"
  ok "Dépôt Helm joint"
else
  warn "Dépôt Helm injoignable : repli sur le chart cloné depuis GitHub."
  command -v git >/dev/null || die "git introuvable, et le dépôt Helm ne répond pas."
  TMP=$(mktemp -d)
  git clone --depth 1 --branch "$REF" "$GIT_REPO" "$TMP/src" >/dev/null
  CHART_REF="$TMP/src/charts/atelier"
  ok "Chart local : $CHART_REF"
fi

log "[2/3] Déploiement Helm..."
ARGS=(
  --namespace "$NS"
  --set "ingress.hostname=$HOST"
  --set "oidc.username=$USERNAME"
  --set "image.tag=${IMAGE_TAG:-latest}"
  --set-string "llm.apiKey=$LLM_KEY"
)
[[ -n "${ATELIER_MODELE:-}" ]]      && ARGS+=(--set-string "llm.model=$ATELIER_MODELE")
[[ -n "${ATELIER_OWNER_KEY:-}" ]]   && ARGS+=(--set-string "security.ownerKey=$ATELIER_OWNER_KEY")
# Identité git du service terminal, telle qu'Onyxia l'expose.
[[ -n "${GIT_USER_NAME:-}" ]]       && ARGS+=(--set-string "git.name=$GIT_USER_NAME")
[[ -n "${GIT_USER_MAIL:-${GIT_USER_EMAIL:-}}" ]] \
  && ARGS+=(--set-string "git.email=${GIT_USER_MAIL:-${GIT_USER_EMAIL:-}}")
[[ -n "${GIT_PERSONAL_ACCESS_TOKEN:-}" ]] \
  && ARGS+=(--set-string "git.token=$GIT_PERSONAL_ACCESS_TOKEN")
[[ -n "${VERSION:-}" ]]             && ARGS+=(--version "$VERSION")

helm upgrade --install "$RELEASE" "$CHART_REF" "${ARGS[@]}" --wait --timeout 10m
ok "Release $RELEASE à jour"

log "[3/3] Notes d'installation"
echo ""
helm get notes "$RELEASE" -n "$NS" 2>/dev/null | sed '1d' || true
echo ""
OWNER_KEY=$(lire_secret ATELIER_OWNER_KEY)
echo "+==============================================================+"
echo "|  Accès"
echo "+==============================================================+"
echo "|  Atelier   : https://$HOST/"
echo "|  Clé owner : ${OWNER_KEY:-(voir le Secret $SECRET_NAME)}"
echo "+==============================================================+"
echo ""
echo "Désinstaller : helm uninstall $RELEASE -n $NS"
echo "  (le volume ~/work et le Secret $SECRET_NAME sont conservés)"
