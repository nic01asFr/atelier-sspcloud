#!/bin/sh
# Hook `SessionEnd` de Claude Code : fige le travail non commité d'un projet.
#
# Pourquoi ici, et pas dans l'Atelier. Le harnais ne voit que les tours qu'il
# lance lui-même ; une conversation poursuivie depuis l'extension VS Code lui
# échappe entièrement, et c'est un usage nominal. Un hook vit dans le CLI :
# il attrape les deux.
#
# Ce hook est un filet, pas un ouvrier. Le bon commit est celui que l'agent
# écrit lui-même, avec un message qui dit ce qu'il a fait. Celui-ci ne sert
# qu'à ne rien perdre quand personne ne l'a fait — d'où son sujet, qui
# s'annonce comme machine pour que la veille sache le distinguer.
#
# Il ne pousse jamais. Publier reste un geste délibéré.
#
# Contrat : reçoit sur son entrée standard un objet JSON portant `cwd`, et
# s'exécute dans le répertoire de travail de la session. Sort 0 quoi qu'il
# arrive : un hook qui échoue ne doit pas retenir la session.

set -u

MARQUEUR=".atelier-figer"

sortir() { exit 0; }

# Le cwd du hook est déjà celui de la session ; on ne lit l'entrée que pour
# ne pas la laisser dans le tuyau.
cat >/dev/null 2>&1 || true

[ -d .git ] || sortir

# Opt-in par projet, et versionné : le fichier se voit, se lit et se retire.
[ -f "$MARQUEUR" ] || sortir

# Rien à figer ? Rien à faire. C'est le cas de la plupart des passages.
[ -n "$(git status --porcelain 2>/dev/null)" ] || sortir

# Un secret qui n'a rien à faire dans l'histoire arrête tout : mieux vaut ne
# pas commiter que commiter ce qui ne s'efface plus.
SENSIBLES=$(git status --porcelain 2>/dev/null | awk '{print $NF}' \
  | grep -Ei '(^|/)\.env($|\.)|\.pem$|\.key$|_token$|_secret$|credentials' \
  | grep -Eiv '\.(example|sample|template|dist)$' || true)
if [ -n "$SENSIBLES" ]; then
  echo "atelier: commit non fait — fichiers sensibles en attente : $SENSIBLES" >&2
  sortir
fi

git add -A >/dev/null 2>&1 || sortir
[ -n "$(git diff --cached --name-only 2>/dev/null)" ] || sortir

QUOI=$(git diff --cached --shortstat 2>/dev/null | sed 's/^ *//')
git commit --no-verify -m "chore(atelier) : travail non figé" \
  -m "Commit automatique de fin de session — personne n'avait figé ce travail.
${QUOI}" >/dev/null 2>&1

sortir
