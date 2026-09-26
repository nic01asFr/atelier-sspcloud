"""Pose le socle des agents, `~/work/projects/CLAUDE.md`, depuis le code déployé.

Claude Code lit le `CLAUDE.md` du dossier parent sur toutes les surfaces :
celui de `~/work/projects/` vaut donc pour tous les agents code de tous les
projets. Son texte vit dans le paquet (`consignes/socle.md`), pour qu'il
voyage avec le code — l'image copie `atelier-src`, un pod reçoit l'extraction
de `atelier-src` — et non dans `docs/`, qui n'arrive jamais sur le pod.
Jusqu'au 26/09 il se recopiait à la main ; le socle du pod avait un jour de
retard sur le dépôt.

Qui le pose : `install/atelier-init.sh` (`python3 -m mcp_gateway.atelier.socle`)
et le démarrage de l'Atelier (donc aussi `atelier-relancer`).

Règles :

- écriture atomique (fichier provisoire dans le même dossier, puis `os.replace`) :
  un agent qui démarre au même instant lit l'ancien texte ou le nouveau,
  jamais la moitié d'un ;
- l'empreinte du texte posé est notée dans `~/work/.atelier-etat/socle.json` ;
- un fichier dont l'empreinte n'est pas celle de la dernière pose a été
  modifié à la main (ou posé avant que l'Atelier ne s'en charge) : il est
  gardé en copie datée sous `~/work/.atelier-etat/socle/`, l'événement va au
  journal unique, puis le socle du code le remplace. Rien ne disparaît en
  silence ; la personne reporte ses ajouts dans `consignes/socle.md` (ou dans
  le `CLAUDE.md` d'un projet) si elle veut les garder.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger("atelier.socle")

SOURCE = Path(__file__).with_name("consignes") / "socle.md"
ACTEUR = "atelier:socle"


def empreinte(texte: str) -> str:
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def destination(settings: Any) -> Path:
    return Path(settings.projects_dir) / "CLAUDE.md"


def dossier_d_etat(settings: Any) -> Path:
    return Path(settings.work_dir) / ".atelier-etat"


def _lire_l_etat(settings: Any) -> dict[str, Any]:
    try:
        donnees = json.loads((dossier_d_etat(settings) / "socle.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return donnees if isinstance(donnees, dict) else {}


def ecrire_atomiquement(chemin: Path, texte: str, mode: int = 0o644) -> None:
    """Écrit `texte` dans `chemin` d'un seul `rename` : jamais de fichier à moitié écrit."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    descripteur, provisoire = tempfile.mkstemp(prefix=f".{chemin.name}.", suffix=".tmp", dir=chemin.parent)
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8", newline="\n") as flux:
            flux.write(texte)
            flux.flush()
            os.fsync(flux.fileno())
        try:
            os.chmod(provisoire, mode)
        except OSError:
            pass
        os.replace(provisoire, chemin)
    except BaseException:
        try:
            os.unlink(provisoire)
        except OSError:
            pass
        raise


def _noter_la_pose(settings: Any, texte: str, quand: str) -> None:
    ecrire_atomiquement(
        dossier_d_etat(settings) / "socle.json",
        json.dumps({"empreinte": empreinte(texte), "pose_le": quand, "destination": str(destination(settings))},
                   ensure_ascii=False, indent=1) + "\n",
    )


def _journal_par_defaut(settings: Any) -> Any:
    """Le journal unique, s'il s'ouvre ; None sinon (le socle se pose quand même)."""
    try:
        from mcp_gateway.atelier.commandes.journal import (
            Journal,
            dossier_du_journal,
            secrets_du_fichier_d_environnement,
        )
        from mcp_gateway.atelier.env_secrets import chemin_du_fichier

        return Journal(
            dossier_du_journal(settings.work_dir),
            secrets=secrets_du_fichier_d_environnement(chemin_du_fichier(settings)),
        )
    except Exception as exc:  # noqa: BLE001 — sans journal, le journal technique suffit
        log.info("journal unique indisponible pour le socle : %s", exc)
        return None


def _journaliser(journal: Any, resultat: str, cible: Path, avant: dict[str, Any] | None, apres: dict[str, Any]) -> None:
    if journal is None:
        return
    try:
        from mcp_gateway.atelier.commandes.journal import Evenement

        journal.ecrire(
            Evenement(
                source="automate",
                acteur=ACTEUR,
                objet={"type": "fichier", "id": str(cible)},
                action={"commande": "socle.poser", "classe": "reversible", "avant": avant, "apres": apres},
                resultat=resultat,
                empreinte=apres.get("empreinte", "")[:16],
            )
        )
    except Exception as exc:  # noqa: BLE001 — un journal qui échoue n'empêche pas la pose
        log.warning("socle : événement non journalisé (%s)", exc)


def poser_le_socle(settings: Any, *, journal: Any = "defaut", source: Path | None = None,
                   maintenant: datetime | None = None) -> dict[str, Any]:
    """Pose le socle du code dans `projects/CLAUDE.md` si besoin. Rend ce qui a été fait.

    `resultat` : `a-jour` (rien écrit), `pose` (fichier absent), `mis-a-jour`
    (la version précédente de l'Atelier, intacte, remplacée), `remplace-modifie`
    (modifié à la main : copie datée, journal, puis remplacé), `source-absente`
    ou `erreur`.
    """
    source = source or SOURCE
    cible = destination(settings)
    quand_dt = maintenant or datetime.now(timezone.utc)
    quand = quand_dt.isoformat(timespec="seconds")
    try:
        texte = source.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("socle introuvable dans le code (%s) : %s non mis à jour", source, cible)
        return {"resultat": "source-absente", "source": str(source), "erreur": type(exc).__name__}
    neuve = empreinte(texte)
    try:
        ancien = cible.read_text(encoding="utf-8") if cible.is_file() else None
    except OSError as exc:
        return {"resultat": "erreur", "destination": str(cible), "erreur": f"{type(exc).__name__}: {exc}"}

    etat = _lire_l_etat(settings)
    if ancien == texte:
        if etat.get("empreinte") != neuve:
            try:
                _noter_la_pose(settings, texte, quand)
            except OSError:
                pass
        return {"resultat": "a-jour", "destination": str(cible), "empreinte": neuve}

    if journal == "defaut":
        journal = _journal_par_defaut(settings)
    copie: Path | None = None
    if ancien is None:
        resultat = "pose"
        avant = None
    else:
        ancienne = empreinte(ancien)
        avant = {"empreinte": ancienne[:16]}
        if etat.get("empreinte") == ancienne:
            resultat = "mis-a-jour"
        else:
            resultat = "remplace-modifie"
            copie = dossier_d_etat(settings) / "socle" / f"CLAUDE.md.{quand_dt.strftime('%Y%m%d-%H%M%S')}"
            try:
                ecrire_atomiquement(copie, ancien)
            except OSError as exc:
                # Sans copie, on n'écrase pas : c'est la seule chose qu'on s'interdit.
                log.warning("socle : copie de %s impossible (%s), fichier laissé tel quel", cible, exc)
                return {"resultat": "erreur", "destination": str(cible), "erreur": f"copie impossible : {exc}"}
            avant["copie"] = str(copie)
            avant["raison"] = ("empreinte différente de la dernière pose" if etat.get("empreinte")
                               else "aucune pose connue de l'Atelier")
    try:
        ecrire_atomiquement(cible, texte)
        _noter_la_pose(settings, texte, quand)
    except OSError as exc:
        return {"resultat": "erreur", "destination": str(cible), "erreur": f"{type(exc).__name__}: {exc}"}
    apres = {"empreinte": neuve[:16], "mots": len(texte.split())}
    _journaliser(journal, resultat, cible, avant, apres)
    if resultat == "remplace-modifie":
        log.warning("socle : %s modifié hors de l'Atelier, copie gardée dans %s, remplacé par le socle du code",
                    cible, copie)
    else:
        log.info("socle : %s (%s)", resultat, cible)
    sortie: dict[str, Any] = {"resultat": resultat, "destination": str(cible), "empreinte": neuve}
    if copie is not None:
        sortie["copie"] = str(copie)
    return sortie


def main() -> int:
    """`python3 -m mcp_gateway.atelier.socle` : une pose, le résultat en une ligne JSON."""
    from mcp_gateway.atelier.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    sortie = poser_le_socle(get_settings())
    print(json.dumps(sortie, ensure_ascii=False))
    return 0 if sortie["resultat"] not in ("erreur", "source-absente") else 1


if __name__ == "__main__":
    sys.exit(main())
