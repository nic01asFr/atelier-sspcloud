"""Hook `PreToolUse` du socle : refuser, avant qu'elle parte, une commande qui a déjà cassé le pod.

Deux familles de refus (`docs/consignes/socle.md`, « Hooks du socle ») :

1. **Tuer par motif** : `killall <nom>`, `pkill` sur un motif non ancré,
   `kill $(pgrep …)` / `pgrep … | xargs kill`. Le 18/09, `pkill -f "server.mjs"`
   a tué wikichat : le motif attrape les processus des autres. On tue par PID,
   celui qu'on a écrit soi-même dans un fichier `.pid`.
2. **Écouter sur toutes les interfaces** : `0.0.0.0` ou `::` passé comme hôte,
   et `python -m http.server` sans `-b 127.0.0.1` (qui écoute partout par
   défaut). Tout le pod, et au-delà, peut joindre un port ouvert ainsi.

Le hook lit l'appel d'outil sur son entrée (JSON de Claude Code) et, pour un
refus, sort en code 2 avec la raison sur la sortie d'erreur : Claude Code
bloque l'appel et rend la raison à l'agent. Tout le reste sort en 0 sans rien
écrire. Il n'importe que la bibliothèque standard : il part à chaque commande.

`--poser` l'installe dans `~/work/.claude/settings.json` (le fichier physique,
dont `~/.claude/settings.json` est un lien), sans toucher aux hooks de
wikichat ni aux autres entrées.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

MODULE = "mcp_gateway.gardiens.garde_bash"

RAISON_TUER = (
    "Refusé par le socle de l'Atelier : {quoi} tue tous les processus dont le nom ou la ligne de "
    "commande correspond, y compris ceux des autres agents et des services (wikichat est mort "
    "ainsi le 18/09). Tue par PID : celui que ton script a écrit dans son fichier .pid "
    "(kill \"$(cat run.pid)\"), ou pkill avec un motif ancré des deux côtés (^...$)."
)
RAISON_ECOUTE = (
    "Refusé par le socle de l'Atelier : {quoi} écoute sur toutes les interfaces ; le port serait "
    "joignable par tout le pod, et au-delà. Écoute sur 127.0.0.1. Pour montrer un service, "
    "déclare-le comme artefact serveur : c'est l'Atelier qui le lance et le sert."
)

_SEPARATEURS = re.compile(r"\|\||&&|[;|&\n]|\$\(|`|\)")
_TOUTES_INTERFACES = re.compile(r"(?<![\w.:])(?:0\.0\.0\.0(?![\w.])|\[::\]|::(?![\w.:]))")
_OPTIONS_HOTE = re.compile(
    r"(?:--host|--bind|--bind-addr|--ip|--listen|--address|--addr|-b|-H|-l)(?:=|\s+)['\"]?(?:0\.0\.0\.0(?![\w.])|\[::\]|::(?![\w.:]))"
    r"|\b(?:HOST|BIND|LISTEN_ADDR|BIND_ADDR)=['\"]?(?:0\.0\.0\.0|::)(?![\w.:])"
    r"|(?:host|bind)\s*=\s*['\"](?:0\.0\.0\.0|::)['\"]"
    r"|bind-addr:\s*0\.0\.0\.0"
)


def _segments(commande: str) -> list[list[str]]:
    sortie = []
    for morceau in _SEPARATEURS.split(commande):
        morceau = morceau.strip()
        if not morceau:
            continue
        try:
            mots = shlex.split(morceau, posix=True)
        except ValueError:
            mots = morceau.split()
        # `sudo`, `env X=1`, `nohup` devant la vraie commande
        while mots and (mots[0] in ("sudo", "env", "nohup", "exec", "command", "timeout") or "=" in mots[0] and not mots[0].startswith("-")):
            mots = mots[1:]
            if mots and re.fullmatch(r"\d+[smh]?", mots[0]):
                mots = mots[1:]
        if mots:
            sortie.append(mots)
    return sortie


def _motif_ancre(motif: str) -> bool:
    return motif.startswith("^") and motif.endswith("$") and len(motif) > 2


def _motif_de_pkill(mots: list[str]) -> str | None:
    """Le motif d'un `pkill`/`pgrep` (dernier argument qui n'est pas une option)."""
    avec_valeur = {"-s", "-g", "-G", "-u", "-U", "-t", "-P", "--signal", "-F", "--pidfile", "--session", "--pgroup", "--group", "--euid", "--uid", "--terminal", "--parent", "--ns", "--nslist"}
    motif = None
    saute = False
    for m in mots[1:]:
        if saute:
            saute = False
            continue
        if m in avec_valeur:
            saute = True
            continue
        if m.startswith("-"):
            continue
        motif = m
    return motif


def _pidfile(mots: list[str]) -> bool:
    return any(m in ("-F", "--pidfile") or m.startswith("--pidfile=") for m in mots)


def raison_de_refus(commande: str) -> str | None:
    """La raison du refus, ou None si la commande passe."""
    segments = _segments(commande)
    tue = any(os.path.basename(s[0]) in ("kill", "xargs") and (os.path.basename(s[0]) == "kill" or "kill" in s) for s in segments)
    for mots in segments:
        nom = os.path.basename(mots[0])
        if nom == "killall":
            return RAISON_TUER.format(quoi="killall")
        if nom == "pkill" and not _pidfile(mots):
            motif = _motif_de_pkill(mots)
            if motif is None or not _motif_ancre(motif):
                quoi = "pkill -f" if ("-f" in mots or "--full" in mots or any(re.fullmatch(r"-\w*f\w*", m) for m in mots)) else "pkill"
                return RAISON_TUER.format(quoi=f"{quoi} sur un motif non ancré")
        if nom == "pgrep" and tue:
            motif = _motif_de_pkill(mots)
            if motif is None or not _motif_ancre(motif):
                return RAISON_TUER.format(quoi="kill sur la sortie de pgrep (motif non ancré)")
    if _OPTIONS_HOTE.search(commande):
        return RAISON_ECOUTE.format(quoi="cette commande")
    for mots in segments:
        texte = " ".join(mots)
        if re.search(r"(?:^|\s)-m\s+http\.server\b", texte) or re.search(r"\bhttp\.server\b", texte) and "python" in mots[0]:
            if not re.search(r"(?:-b|--bind)(?:=|\s+)(?:127\.0\.0\.1|localhost|::1)\b", texte):
                return RAISON_ECOUTE.format(quoi="python -m http.server sans -b 127.0.0.1")
        if any(os.path.basename(mots[0]).startswith(p) for p in ("uvicorn", "gunicorn", "flask", "hypercorn")) or "uvicorn" in mots[:3]:
            if _TOUTES_INTERFACES.search(texte):
                return RAISON_ECOUTE.format(quoi=os.path.basename(mots[0]))
    return None


def main_hook(entree: str) -> int:
    try:
        appel = json.loads(entree or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(appel, dict) or appel.get("tool_name") != "Bash":
        return 0
    commande = (appel.get("tool_input") or {}).get("command")
    if not isinstance(commande, str):
        return 0
    raison = raison_de_refus(commande)
    if raison is None:
        return 0
    sys.stderr.write(raison + "\n")
    return 2


# --- pose -------------------------------------------------------------------


def commande_du_hook(python: str | None = None) -> str:
    return f"{shlex.quote(python or sys.executable)} -m {MODULE}"


def poser(chemin: Path, python: str | None = None) -> str:
    """Ajoute (ou met à jour) le hook dans le fichier de réglages. Rend ce qui a été fait.

    On écrit dans le fichier **physique** (le lien est suivi), par un fichier
    provisoire renommé : le lien `~/.claude/settings.json` reste un lien. Un
    fichier absent ou illisible n'est pas créé ni écrasé : l'Atelier et
    l'installation en sont les auteurs. Les hooks des autres (wikichat) ne sont
    pas touchés ; notre commande ne contient pas « wikichat », pour que la
    fusion de `claude_home` ne la range pas dans sa famille.
    """
    physique = Path(os.path.realpath(chemin))
    try:
        brut = physique.read_text(encoding="utf-8")
        donnees = json.loads(brut) if brut.strip() else {}
    except (OSError, json.JSONDecodeError):
        return "absent ou illisible : rien posé"
    if not isinstance(donnees, dict):
        return "illisible : rien posé"
    voulu = commande_du_hook(python)
    hooks = donnees.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    groupes = hooks.get("PreToolUse")
    if not isinstance(groupes, list):
        groupes = []
    trouve = False
    change = False
    nouveaux = []
    for groupe in groupes:
        if not isinstance(groupe, dict) or not isinstance(groupe.get("hooks"), list):
            nouveaux.append(groupe)
            continue
        garde = []
        for h in groupe["hooks"]:
            if isinstance(h, dict) and MODULE in str(h.get("command", "")):
                if trouve:
                    change = True
                    continue  # un doublon : un seul suffit
                trouve = True
                if h.get("command") != voulu:
                    h = {**h, "command": voulu}
                    change = True
            garde.append(h)
        if garde:
            nouveaux.append({**groupe, "hooks": garde})
        else:
            change = True
    if not trouve:
        nouveaux.append({"matcher": "Bash", "hooks": [{"type": "command", "command": voulu, "timeout": 10}]})
        change = True
    if not change:
        return "déjà posé"
    hooks["PreToolUse"] = nouveaux
    donnees["hooks"] = hooks
    provisoire = physique.with_name(physique.name + ".gardiens-tmp")
    provisoire.write_text(json.dumps(donnees, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(provisoire, physique)
    return "posé" if not trouve else "mis à jour"


def reglages_par_defaut() -> Path:
    work = Path(os.environ.get("ATELIER_WORK") or Path.home() / "work")
    return work / ".claude" / "settings.json"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--poser"]:
        chemin = Path(argv[1]) if len(argv) > 1 else reglages_par_defaut()
        print(f"hook du socle : {poser(chemin)} ({chemin})")
        return 0
    if argv[:1] == ["--verifier"]:
        raison = raison_de_refus(" ".join(argv[1:]))
        print(raison or "accepté")
        return 2 if raison else 0
    return main_hook(sys.stdin.read())


if __name__ == "__main__":
    sys.exit(main())
