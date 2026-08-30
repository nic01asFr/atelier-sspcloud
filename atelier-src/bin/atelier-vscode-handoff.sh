#!/usr/bin/env bash
# Reprend dans VS Code la conversation qu'on lisait dans l'Atelier.
#
# VS Code s'ouvre sur un dossier, pas sur une conversation : sans ce relais,
# passer de l'Atelier à l'éditeur perd le fil, et il faut le retrouver à la
# main dans la liste des sessions.
#
# On a d'abord essayé de piloter l'interface — ouvrir la barre latérale de
# l'extension, y sélectionner la session. Aucune de ces voies ne fonctionne
# en mode web : `code-server --open-url` s'adresse à une instance de bureau,
# et ni `?payload=`, ni `?command=` n'exécutent de commande. Seul `openFile`
# passe, ce qui ne suffit pas.
#
# On reprend donc la conversation là où c'est possible : dans un terminal.
# C'est la même session, reprise, et elle s'affiche d'emblée.
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
  echo "Atelier : aucune conversation à reprendre ici."
  exit 0
fi

echo "Atelier — reprise de la conversation ${SESSION}"
echo "Ctrl+C pour rendre la main ; la barre latérale Claude Code garde la liste."
echo

# `exec` : ce terminal devient la conversation. Sans lui, le shell resterait
# entre l'utilisateur et Claude, et Ctrl+C fermerait le mauvais processus.
exec "${WORK}/bin/claude" --resume "$SESSION"
