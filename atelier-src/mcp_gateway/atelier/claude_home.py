"""Sync durable du store Claude Code (PVC ↔ $HOME/.claude)."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings

log = logging.getLogger("atelier.claude_home")

# Sous-arbres nécessaires au resume CLI / extension VS Code
# skills/commands = overlay WikiChat (et autres).
_SYNC_DIRS = ("projects", "sessions", "session-env", "skills", "commands")
# `settings.json` n'est plus recopié d'un côté à l'autre : c'est un seul fichier
# (`unifier_les_reglages`).
_SYNC_FILES: tuple[str, ...] = ()
REGLAGES = "settings.json"


def donnees_code_server() -> Path:
    """Le dossier de données de code-server : réglages et extensions.

    Celui du pod par défaut ; `ATELIER_CODE_SERVER_DATA` le déplace, pour une
    image qui l'a mis ailleurs ou pour un test.
    """
    return Path(os.environ.get("ATELIER_CODE_SERVER_DATA") or Path.home() / ".local/share/code-server")


def dossier_des_extensions() -> Path:
    """Où l'extension Claude Code est installée."""
    return Path(os.environ.get("ATELIER_EXTENSIONS") or donnees_code_server() / "extensions")


def _version(dossier: Path) -> tuple[int, ...]:
    """`anthropic.claude-code-2.1.273-linux-x64` donne (2, 1, 273)."""
    nom = dossier.name.removeprefix("anthropic.claude-code-")
    chiffres: list[int] = []
    for morceau in nom.split("-")[0].split("."):
        if not morceau.isdigit():
            return ()
        chiffres.append(int(morceau))
    return tuple(chiffres)


def binaire_claude_le_plus_recent() -> Path | None:
    """Le binaire `claude` de la version d'extension la plus récente installée.

    C'est celui que VS Code lance : l'extension se met à jour seule et prend
    toujours la dernière. Le lien `~/work/bin/claude`, posé une fois à la main,
    était resté sur la 2.1.248 quand VS Code tournait en 2.1.273 — deux jeux
    d'outils et d'agents différents pour une même conversation. On choisit
    comme VS Code choisit. Trier les noms comme du texte classerait 2.1.99
    après 2.1.273 : on compare les numéros.
    """
    candidats = [
        (_version(d), d / "resources/native-binary/claude")
        for d in dossier_des_extensions().glob("anthropic.claude-code-*")
    ]
    valides = [(v, b) for v, b in candidats if v and b.is_file() and os.access(b, os.X_OK)]
    if not valides:
        return None
    return max(valides)[1]


def aligner_le_lien_claude(settings: AtelierSettings) -> Path | None:
    """Fait pointer `~/work/bin/claude` sur le binaire que VS Code utilise.

    wikichat et le terminal passent par ce lien ; l'aligner les met sur la même
    version que l'extension. Un vrai fichier à cet endroit n'est pas un lien
    qu'on aurait posé : on n'y touche pas.
    """
    cible = binaire_claude_le_plus_recent()
    lien = settings.claude_bin
    if cible is None or (lien.exists() and not lien.is_symlink()):
        return None
    if lien.is_symlink() and lien.resolve() == cible.resolve():
        return cible
    lien.parent.mkdir(parents=True, exist_ok=True)
    temporaire = lien.with_name(lien.name + ".nouveau")
    temporaire.unlink(missing_ok=True)
    temporaire.symlink_to(cible)
    temporaire.replace(lien)
    return cible


def durable_claude_dir(settings: AtelierSettings) -> Path:
    return settings.work_dir / ".claude"


def home_claude_dir() -> Path:
    return Path.home() / ".claude"


# --- ~/.claude/settings.json : un seul fichier ------------------------------
#
# Trois auteurs y écrivent : l'Atelier (`vscode_handoff.write_claude_settings_env`,
# refus de WebSearch compris), wikichat (ses hooks, à son démarrage, dans
# `$HOME/.claude/settings.json`) et Claude Code lui-même. Chacun fusionne ses
# propres entrées ; mais tant que `~/.claude` et `~/work/.claude` en avaient
# chacun une copie, recopiées l'une sur l'autre en entier (la plus récente
# gagnant), le miroir effaçait les entrées de l'autre auteur.
#
# Désormais le fichier physique est celui du volume, `~/work/.claude/settings.json`,
# et `~/.claude/settings.json` est un lien vers lui. Un auteur qui écrit par
# renommage atomique remplace le lien par un fichier : c'est le cas de wikichat
# (`overlay-installer.mjs` : `writeFileSync(tmp)` puis `renameSync`). Ce fichier
# a été écrit à partir de ce qu'il lisait à travers le lien : on le fusionne dans
# celui du volume, sans rien perdre, et l'on repose le lien. Là où un lien ne
# peut pas être créé (Windows sans privilège), les deux fichiers reçoivent le
# même contenu fusionné.


def _famille(commande: str) -> str:
    """L'auteur d'un hook : wikichat remplace les siens d'un bloc (ancien hook compris)."""
    return "wikichat" if "wikichat" in commande else commande


def _commandes(hooks: Any) -> set[str]:
    trouvees: set[str] = set()
    if not isinstance(hooks, dict):
        return trouvees
    for groupes in hooks.values():
        for groupe in groupes if isinstance(groupes, list) else []:
            for h in (groupe.get("hooks") if isinstance(groupe, dict) else None) or []:
                if isinstance(h, dict) and isinstance(h.get("command"), str):
                    trouvees.add(h["command"])
    return trouvees


def fusionner_les_reglages(recent: dict[str, Any], ancien: dict[str, Any]) -> dict[str, Any]:
    """Les réglages de `recent`, complétés de ce que seul `ancien` porte.

    - clés de premier niveau et `env` : le plus récent l'emporte, rien ne se perd ;
    - `permissions.allow|deny|ask|additionalDirectories` : réunion des listes ;
    - `hooks` : ceux du plus récent, plus ceux de l'ancien dont la commande n'y
      est pas — sauf si le plus récent porte déjà des hooks du même auteur
      (wikichat remplace tous les siens à la fois : l'ancien
      `wikichat-mailbox-hook.mjs` ne doit pas revenir à côté de
      `wikichat-hook.mjs`).
    """
    sortie: dict[str, Any] = {**ancien, **recent}
    env_a, env_r = ancien.get("env"), recent.get("env")
    if isinstance(env_a, dict) and isinstance(env_r, dict):
        sortie["env"] = {**env_a, **env_r}
    perm_a, perm_r = ancien.get("permissions"), recent.get("permissions")
    if isinstance(perm_a, dict) and isinstance(perm_r, dict):
        permissions = {**perm_a, **perm_r}
        for cle in ("allow", "deny", "ask", "additionalDirectories"):
            liste_a, liste_r = perm_a.get(cle), perm_r.get(cle)
            if isinstance(liste_a, list) and isinstance(liste_r, list):
                permissions[cle] = liste_r + [x for x in liste_a if x not in liste_r]
        sortie["permissions"] = permissions
    hooks_a, hooks_r = ancien.get("hooks"), recent.get("hooks")
    if isinstance(hooks_a, dict) and isinstance(hooks_r, dict):
        presentes = _commandes(hooks_r)
        # L'ancien hook ne compte pas comme présence de wikichat : un fichier
        # qui n'a que lui cède la place aux hooks actuels de l'autre.
        familles = {_famille(c) for c in presentes if _ANCIEN_HOOK_WIKICHAT not in c}
        hooks = {ev: list(g) if isinstance(g, list) else g for ev, g in hooks_r.items()}
        for evenement, groupes in hooks_a.items():
            if not isinstance(groupes, list):
                continue
            ajouts = []
            for groupe in groupes:
                if not isinstance(groupe, dict) or not isinstance(groupe.get("hooks"), list):
                    continue
                gardes = [
                    h
                    for h in groupe["hooks"]
                    if isinstance(h, dict)
                    and isinstance(h.get("command"), str)
                    and h["command"] not in presentes
                    and _famille(h["command"]) not in familles
                ]
                if gardes:
                    ajouts.append({**groupe, "hooks": gardes})
            if ajouts:
                deja = hooks.get(evenement)
                hooks[evenement] = (deja if isinstance(deja, list) else []) + ajouts
        sortie["hooks"] = _sans_ancien_hook(hooks)
    return sortie


# Le hook `Stop` d'avant `wikichat-hook.mjs`. wikichat le retire lui-même en
# posant les nouveaux ; une fusion ne doit pas le faire revenir à côté d'eux
# (il délègue au nouveau : le `Stop` tournerait deux fois).
_ANCIEN_HOOK_WIKICHAT = "wikichat-mailbox-hook"
_HOOK_WIKICHAT = "wikichat-hook.mjs"


def _sans_ancien_hook(hooks: dict[str, Any]) -> dict[str, Any]:
    if not any(_HOOK_WIKICHAT in c for c in _commandes(hooks)):
        return hooks
    sortie: dict[str, Any] = {}
    for evenement, groupes in hooks.items():
        if not isinstance(groupes, list):
            sortie[evenement] = groupes
            continue
        gardes = []
        for groupe in groupes:
            if isinstance(groupe, dict) and isinstance(groupe.get("hooks"), list):
                restants = [
                    h
                    for h in groupe["hooks"]
                    if not (isinstance(h, dict) and _ANCIEN_HOOK_WIKICHAT in str(h.get("command", "")))
                ]
                if restants:
                    gardes.append({**groupe, "hooks": restants})
            else:
                gardes.append(groupe)
        if gardes:
            sortie[evenement] = gardes
    return sortie


def _lire_reglages(chemin: Path) -> dict[str, Any] | None:
    """Le contenu, `{}` pour un fichier vide, None s'il est illisible (on n'y touche pas)."""
    try:
        brut = chemin.read_text(encoding="utf-8")
    except OSError:
        return None
    if not brut.strip():
        return {}
    try:
        lu = json.loads(brut)
    except json.JSONDecodeError:
        return None
    return lu if isinstance(lu, dict) else None


def _ecrire_reglages(chemin: Path, donnees: dict[str, Any]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_name(chemin.name + ".atelier-tmp")
    temporaire.write_text(json.dumps(donnees, indent=2) + "\n", encoding="utf-8")
    temporaire.replace(chemin)


def reglages_durables(settings: AtelierSettings) -> Path:
    return durable_claude_dir(settings) / REGLAGES


def unifier_les_reglages(settings: AtelierSettings) -> Path:
    """Fait de `~/.claude/settings.json` un lien vers celui du volume. Rend le fichier physique.

    Un vrai fichier trouvé à la place du lien (premier passage, ou lien remplacé
    par un auteur qui écrit par renommage) est d'abord fusionné dans celui du
    volume (`fusionner_les_reglages`, le plus récent l'emportant). Un fichier
    illisible n'est jamais écrasé : on le laisse, et l'on s'arrête là.
    """
    durable = reglages_durables(settings)
    maison = home_claude_dir() / REGLAGES
    durable.parent.mkdir(parents=True, exist_ok=True)
    maison.parent.mkdir(parents=True, exist_ok=True)
    if maison.is_symlink():
        try:
            if maison.resolve() == durable.resolve():
                return durable
        except OSError:
            pass
    if maison.exists():
        de_la_maison = _lire_reglages(maison)
        if de_la_maison is None:
            log.warning("%s illisible : ni fusionné ni remplacé", maison)
            return durable
        du_volume = _lire_reglages(durable) if durable.exists() else {}
        if du_volume is None:
            log.warning("%s illisible : ni fusionné ni remplacé", durable)
            return durable
        if not durable.exists():
            fusion = de_la_maison
        elif maison.stat().st_mtime >= durable.stat().st_mtime:
            fusion = fusionner_les_reglages(de_la_maison, du_volume)
        else:
            fusion = fusionner_les_reglages(du_volume, de_la_maison)
        if fusion != du_volume or not durable.exists():
            _ecrire_reglages(durable, fusion)
    if not durable.exists():
        return durable
    try:
        if maison.is_symlink() or maison.exists():
            maison.unlink()
        maison.symlink_to(durable)
    except OSError:
        # Pas de lien possible ici : la même chose des deux côtés.
        shutil.copy2(durable, maison)
    return durable


def sync_claude_home(settings: AtelierSettings) -> dict[str, str]:
    """Bidirectionnel : PVC durable ↔ $HOME/.claude.

    - Au démarrage d'un tour : PVC → HOME (restore après restart pod).
    - Après un tour : HOME → PVC (persister nouvelles sessions).

    Stratégie : pour chaque entrée, copier si source plus récente ou cible absente.

    Seuls `~/work/.claude` et `~/.claude` se répondent : aucun réglage de
    projet (`<projet>/.claude/`) n'entre dans cette synchronisation.
    """
    durable = durable_claude_dir(settings)
    home = home_claude_dir()
    durable.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)

    # 0) Les réglages : un seul fichier, jamais recopié en entier.
    unifier_les_reglages(settings)

    # 1) PVC → HOME (restore)
    _mirror_tree(durable, home, prefer="src")
    # 2) HOME → PVC (capture sessions créées par claude)
    _mirror_tree(home, durable, prefer="src")

    return {
        "durable": str(durable),
        "home": str(home),
        "projects": str(home / "projects"),
    }


def _mirror_tree(src_root: Path, dst_root: Path, *, prefer: str) -> None:
    for name in _SYNC_FILES:
        _sync_file(src_root / name, dst_root / name)
    for name in _SYNC_DIRS:
        src = src_root / name
        dst = dst_root / name
        if not src.is_dir():
            continue
        dst.mkdir(parents=True, exist_ok=True)
        _sync_dir_recursive(src, dst)


def _sync_file(src: Path, dst: Path) -> None:
    if not src.is_file():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.is_file() or src.stat().st_mtime >= dst.stat().st_mtime:
        shutil.copy2(src, dst)


def _sync_dir_recursive(src: Path, dst: Path) -> None:
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        target = dst / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # Strictement plus recent : a date egale les deux copies disent la
        # meme chose, et le test large refaisait tout l'arbre a chaque tour,
        # deux fois.
        if not target.is_file() or path.stat().st_mtime > target.stat().st_mtime:
            shutil.copy2(path, target)
