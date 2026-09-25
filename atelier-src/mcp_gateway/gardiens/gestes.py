"""La liste fermée des gestes qu'un gardien fait seul (gardiens.md §3.3).

Vague 1 : relancer un service tombé **par son script officiel**, rien d'autre.

- `relancer_atelier` : `~/work/bin/atelier-relancer`, qui ne tue que le
  processus qui tient le port (par l'inode de sa socket, jamais par motif) ;
- `relancer_wikichat` : `~/work/bin/start_wikichat.sh` ;
- `relancer_relais` : `python -m mcp_gateway.atelier.relais_llm`, détaché,
  comme `install/atelier-init.sh` et `relais_llm.assurer_le_relais`.

Un geste n'existe que s'il est dans `GESTES` : une déclaration qui en nomme un
autre est refusée au chargement. Les scripts se règlent dans
`reglages.scripts.<service>` de la déclaration (les tests y mettent un faux
script) ; `{work}`, `{python}` et `{atelier_src}` y sont remplacés.

Les conditions (deux échecs de suite, cinq minutes de silence pour l'Atelier,
interrupteur `ATELIER_GARDIENS_GESTES=0`, plafond de relances) sont tenues par
l'exécuteur, pas ici.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp_gateway.gardiens.controles.commun import Contexte


@dataclass(frozen=True)
class Geste:
    service: str
    echecs_avant: int = 2
    silence_min_s: float = 0.0


GESTES: dict[str, Geste] = {
    "relancer_atelier": Geste("atelier", echecs_avant=2, silence_min_s=300.0),
    "relancer_wikichat": Geste("wikichat", echecs_avant=2),
    "relancer_relais": Geste("relais", echecs_avant=2),
}

SCRIPTS_PAR_DEFAUT: dict[str, dict[str, Any]] = {
    "atelier": {"argv": ["{work}/bin/atelier-relancer"], "delai_s": 90},
    "wikichat": {"argv": ["{work}/bin/start_wikichat.sh"], "delai_s": 90},
    "relais": {
        "argv": ["{python}", "-m", "mcp_gateway.atelier.relais_llm"],
        "detache": True,
        "cwd": "{atelier_src}",
        "journal": "{work}/logs/relais-llm.log",
    },
}


def _remplir(texte: str, ctx: Contexte) -> str:
    return (
        texte.replace("{work}", str(ctx.work))
        .replace("{python}", sys.executable)
        .replace("{atelier_src}", str(ctx.atelier_src))
    )


def script_de(service: str, ctx: Contexte) -> dict[str, Any]:
    brut = {**SCRIPTS_PAR_DEFAUT.get(service, {}), **(ctx.reglages.get("scripts", {}).get(service) or {})}
    return {
        "argv": [_remplir(a, ctx) for a in brut.get("argv", [])],
        "detache": bool(brut.get("detache", False)),
        "cwd": _remplir(brut["cwd"], ctx) if brut.get("cwd") else None,
        "journal": _remplir(brut["journal"], ctx) if brut.get("journal") else None,
        "delai_s": float(brut.get("delai_s", 90)),
    }


def executer(nom: str, ctx: Contexte) -> dict[str, Any]:
    """Lance le script officiel du geste. Rend ce qui s'est passé, sans secret."""
    geste = GESTES[nom]
    s = script_de(geste.service, ctx)
    debut = time.monotonic()
    compte_rendu: dict[str, Any] = {"script": " ".join(s["argv"])}
    programme = s["argv"][0] if s["argv"] else ""
    if not programme or not (Path(programme).exists() or shutil.which(programme)):
        compte_rendu.update(code=127, sortie="script absent")
        return compte_rendu
    options: dict[str, Any] = {}
    if os.name == "posix":
        options["start_new_session"] = True
    try:
        if s["detache"]:
            journal = Path(s["journal"]) if s["journal"] else None
            if journal is not None:
                journal.parent.mkdir(parents=True, exist_ok=True)
            sortie = journal.open("ab") if journal is not None else subprocess.DEVNULL
            try:
                subprocess.Popen(  # noqa: S603 — script officiel, sans shell
                    s["argv"], stdin=subprocess.DEVNULL, stdout=sortie, stderr=subprocess.STDOUT, cwd=s["cwd"], **options
                )
            finally:
                if journal is not None:
                    sortie.close()
            compte_rendu.update(code=None, sortie="lancé en arrière-plan")
        else:
            fini = subprocess.run(  # noqa: S603
                s["argv"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=s["delai_s"],
                cwd=s["cwd"],
                **options,
            )
            texte = ((fini.stdout or "") + (fini.stderr or "")).strip()
            compte_rendu.update(code=fini.returncode, sortie=texte[-400:])
    except subprocess.TimeoutExpired:
        compte_rendu.update(code=124, sortie=f"délai de {s['delai_s']:.0f} s dépassé")
    except OSError as exc:
        compte_rendu.update(code=126, sortie=str(exc)[:200])
    compte_rendu["secondes"] = round(time.monotonic() - debut, 1)
    return compte_rendu
