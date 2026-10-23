"""Lancer le service : `python -m laboratoire --racine ~/work/projects/<projet>/labo`.

Hors boucle locale, le service **refuse de démarrer sans jeton** (`LABO_JETON`) : il n'a pas d'authentification propre, il la reçoit du relais
de l'Atelier. Sans cela, n'importe quel pod du namespace pourrait lancer et arrêter des essais.
"""

from __future__ import annotations

import argparse
import functools
import ipaddress
import os
import sys
from pathlib import Path

import uvicorn

from laboratoire.api import creer_app
from laboratoire.battement import battre
from laboratoire.projet import Racine


def est_boucle_locale(hote: str) -> bool:
    if hote == "localhost":
        return True
    try:
        return ipaddress.ip_address(hote).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="laboratoire", description=__doc__)
    p.add_argument("--racine", default=os.environ.get("LABO_RACINE"), help="dossier du laboratoire du projet (sur le volume)")
    p.add_argument("--hote", default="127.0.0.1")
    p.add_argument("--port", type=int, default=7860)
    p.add_argument("--maitre", action="store_true", help="pod CPU : ne lance aucun essai, un travailleur GPU (laboratoire.travailleur_gpu) prend la file")
    p.add_argument("--sans-battement", action="store_true", help="ne pas faire travailler le GPU pendant un essai")
    args = p.parse_args(argv)
    if not args.racine:
        print("il faut --racine ou LABO_RACINE", file=sys.stderr)
        return 2
    jeton = os.environ.get("LABO_JETON") or None
    if not est_boucle_locale(args.hote) and not jeton:
        print(f"refus : écouter sur {args.hote} sans jeton (LABO_JETON) ouvrirait le laboratoire à tout le namespace", file=sys.stderr)
        return 2
    brut = os.environ.get("LABO_BRUT")
    app = creer_app(
        Racine(Path(args.racine), Path(brut) if brut else None), jeton=jeton, maitre=args.maitre,
        battement=None if (args.sans_battement or args.maitre) else battre,
        battement_humain=None if (args.sans_battement or args.maitre) else functools.partial(battre, 10.0),
    )
    uvicorn.run(app, host=args.hote, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
