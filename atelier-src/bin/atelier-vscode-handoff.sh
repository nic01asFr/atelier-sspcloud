#!/usr/bin/env bash
# Désigne la conversation que VS Code doit rouvrir.
#
# VS Code s'ouvre sur un dossier, pas sur une conversation. L'extension
# Claude Code sait rouvrir « la dernière » du dossier : ce script fait donc
# de celle qu'on lisait dans l'Atelier la plus récente, et s'arrête là.
#
# Il n'ouvre rien lui-même — c'est le travail de l'extension
# `atelier-ouvre-claude`, qui s'exécute dans VS Code et n'a besoin d'aucun
# détour. Les tentatives depuis le pod ont toutes échoué : `--open-url` a
# disparu de code-server, et ni `?command=` ni `?payload=` n'exécutent de
# commande en mode web.
#
# Lancé par une tâche « folderOpen » que l'Atelier écrit dans le projet au
# moment du passage de relais (voir vscode_handoff.py).
set -uo pipefail

SESSION="${1:-${ATELIER_SESSION:-}}"
SLUG="${2:-${ATELIER_SLUG:-default}}"
WORK="${HOME}/work"

# shellcheck source=/dev/null
. "${WORK}/bin/claude-env.sh" 2>/dev/null || true

resolve_claude_bin() {
  if [ -x "${WORK}/bin/claude" ]; then
    return 0
  fi
  local ext
  ext="$(ls -d "${HOME}/.local/share/code-server/extensions/anthropic.claude-code-"* 2>/dev/null | tail -1)"
  if [ -n "$ext" ] && [ -x "${ext}/resources/native-binary/claude" ]; then
    ln -sf "${ext}/resources/native-binary/claude" "${WORK}/bin/claude"
    return 0
  fi
  return 1
}

cd "${WORK}/projects/${SLUG}" 2>/dev/null || cd "${WORK}" || exit 0

if [ -z "$SESSION" ] || ! resolve_claude_bin; then
  exit 0
fi

# Faire de cette conversation la plus récente du dossier, sans l'afficher
# ici : c'est elle que la vue reprendra. Un tour sans conséquence, dont on
# ne lit qu'un octet — le terminal n'a pas à devenir la conversation, c'est
# le travail de l'extension.
(
  "${WORK}/bin/claude" --resume "$SESSION" -p "Continue la session Atelier."     --permission-mode bypassPermissions --output-format text 2>/dev/null     | head -c 1 >/dev/null
) || true

