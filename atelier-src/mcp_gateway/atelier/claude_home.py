"""Sync durable du store Claude Code (PVC ↔ $HOME/.claude)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings

# Sous-arbres nécessaires au resume CLI / extension VS Code
# skills/commands = overlay WikiChat (et autres) ; settings.json porte les hooks Stop
_SYNC_DIRS = ("projects", "sessions", "session-env", "skills", "commands")
_SYNC_FILES = ("settings.json",)


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


def sync_claude_home(settings: AtelierSettings) -> dict[str, str]:
    """Bidirectionnel : PVC durable ↔ $HOME/.claude.

    - Au démarrage d'un tour : PVC → HOME (restore après restart pod).
    - Après un tour : HOME → PVC (persister nouvelles sessions).

    Stratégie : pour chaque entrée, copier si source plus récente ou cible absente.
    """
    durable = durable_claude_dir(settings)
    home = home_claude_dir()
    durable.mkdir(parents=True, exist_ok=True)
    home.mkdir(parents=True, exist_ok=True)

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
