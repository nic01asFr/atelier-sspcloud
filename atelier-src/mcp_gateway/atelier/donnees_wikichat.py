"""Le store de wikichat vit sur le volume, pas dans la couche éphémère du conteneur (D-53).

wikichat range ses données dans `~/.wikichat` (déclencheurs, agents, mémoire,
sessions, liaisons d'identité). Dans le conteneur, `~` n'est pas sur le volume :
chaque redémarrage du pod les perdait. Ici, `~/.wikichat` devient un lien vers
un dossier du volume.

La migration ne détruit rien : elle copie, vérifie la copie, met l'ancien
dossier de côté (il n'est jamais supprimé), puis pose le lien ; au moindre
échec, l'ancien dossier est remis en place. À lancer AVANT wikichat — il ne
doit pas écrire dans le dossier qu'on déplace :

    python3 -m mcp_gateway.atelier.donnees_wikichat <~/.wikichat> <dossier durable>
"""

from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

DEJA_LIE = "deja_lie"
LIE = "lie"
MIGRE = "migre"
AILLEURS = "lien_ailleurs"
CONFLIT = "conflit"
REFUSE = "refuse"


def _inventaire(racine: Path) -> dict[str, int]:
    """Chemin relatif → taille, pour comparer une copie à son original."""
    inventaire: dict[str, int] = {}
    for chemin in sorted(racine.rglob("*")):
        relatif = chemin.relative_to(racine).as_posix()
        if chemin.is_symlink():
            inventaire[relatif] = -1
        elif chemin.is_file():
            inventaire[relatif] = chemin.stat().st_size
        else:
            inventaire[relatif] = -2
    return inventaire


def _vide(dossier: Path) -> bool:
    return not any(dossier.iterdir())


def _poser_le_lien(home_link: Path, durable: Path) -> None:
    home_link.symlink_to(durable, target_is_directory=True)


def lier_le_store(home_link: Path, durable: Path) -> tuple[str, str]:
    """Rend `home_link` lien vers `durable`, en gardant ce qui s'y trouvait.

    Rend (état, détail). Ne lève pas pour un cas attendu : l'init doit
    pouvoir démarrer wikichat quoi qu'il arrive ici.
    """
    if home_link.is_symlink():
        try:
            if home_link.resolve() == durable.resolve():
                return DEJA_LIE, str(durable)
        except OSError:
            pass
        return AILLEURS, f"{home_link} est déjà un lien vers {home_link.resolve()} : laissé tel quel"

    if not home_link.exists():
        durable.mkdir(parents=True, exist_ok=True)
        _poser_le_lien(home_link, durable)
        return LIE, str(durable)

    if not home_link.is_dir():
        return REFUSE, f"{home_link} n'est pas un dossier"

    if durable.exists() and not durable.is_dir():
        return REFUSE, f"{durable} n'est pas un dossier"
    if durable.is_dir() and not _vide(durable):
        if _vide(home_link):
            home_link.rmdir()
            _poser_le_lien(home_link, durable)
            return LIE, str(durable)
        # Deux jeux de données : on ne fusionne pas, une personne décide.
        return CONFLIT, (
            f"{home_link} et {durable} contiennent chacun des données : "
            "rien n'a été déplacé, il faut choisir lequel garder"
        )

    # Le cas à migrer : un vrai dossier à la place du lien.
    copie = durable.with_name(durable.name + ".copie-en-cours")
    if copie.exists():
        shutil.rmtree(copie)
    durable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(home_link, copie, symlinks=True)
    if _inventaire(copie) != _inventaire(home_link):
        shutil.rmtree(copie, ignore_errors=True)
        return REFUSE, "la copie ne correspond pas à l'original : rien n'a été déplacé"

    if durable.is_dir():
        durable.rmdir()  # vide, on vient de le vérifier
    copie.rename(durable)

    garde = home_link.with_name(f"{home_link.name}.avant-migration")
    if garde.exists():
        garde = home_link.with_name(f"{home_link.name}.avant-migration-{time.strftime('%Y%m%d-%H%M%S')}")
    home_link.rename(garde)
    try:
        _poser_le_lien(home_link, durable)
    except OSError as exc:
        garde.rename(home_link)
        return REFUSE, f"le lien n'a pas pu être posé ({exc}) : l'ancien dossier est remis en place"
    return MIGRE, f"{durable} ; l'ancien dossier est gardé dans {garde}"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage : donnees_wikichat <~/.wikichat> <dossier durable>", file=sys.stderr)
        return 2
    try:
        etat, detail = lier_le_store(Path(argv[0]).expanduser(), Path(argv[1]).expanduser())
    except OSError as exc:
        print(f"refuse: {exc}")
        return 1
    print(f"{etat}: {detail}")
    return 0 if etat in (DEJA_LIE, LIE, MIGRE) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
