"""Sync durable du store Claude Code (PVC ↔ $HOME/.claude)."""

from __future__ import annotations

import shutil
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings

# Sous-arbres nécessaires au resume CLI / extension VS Code
# skills/commands = overlay WikiChat (et autres) ; settings.json porte les hooks Stop
_SYNC_DIRS = ("projects", "sessions", "session-env", "skills", "commands")
_SYNC_FILES = ("settings.json",)


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
