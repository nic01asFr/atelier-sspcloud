"""Les files : quelles images faire valider, et dans quel ordre. Une file est une liste de chemins du brut, déterministe pour une graine."""

from __future__ import annotations

import random
import re
from collections import defaultdict

from laboratoire.donnees.brut import ImageBrute

FILES = {
    "audit_classe_1": "Audit de la classe « 1 » : toutes les images « 1 place » et un tirage de « 0 » et de « 2 et plus »",
    "tirage_au_hasard": "Tirage au hasard dans tout le brut (contrôle et étalonnage)",
}


def _melangees(chemins: list[str], graine: int) -> list[str]:
    ordre = sorted(chemins)  # d'abord un ordre stable, puis la graine : le résultat ne dépend pas de l'ordre du scan
    random.Random(graine).shuffle(ordre)
    return ordre


def file_d_images(nom: str, images: list[ImageBrute], graine: int = 11) -> list[str]:
    if nom == "audit_classe_1":
        un = [i.chemin for i in images if i.n == 1]
        zero = _melangees([i.chemin for i in images if i.n == 0], graine)[:40]
        plus = _melangees([i.chemin for i in images if i.n is not None and i.n >= 2], graine + 1)[:20]
        return _melangees(un + zero + plus, graine + 2)
    if nom == "tirage_au_hasard":
        return _melangees([i.chemin for i in images], graine)[:200]
    raise ValueError(f"file inconnue : {nom!r} (connues : {', '.join(FILES)})")


_CHIFFRES = re.compile(r"^(\d+)")


def _cle_de_sequence(chemin: str) -> tuple[int, str]:
    nom = chemin.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    m = _CHIFFRES.match(nom)
    return (int(m.group(1)) if m else 10**9, nom)


def voisins(images: list[ImageBrute], chemin: str) -> tuple[str | None, str | None]:
    """L'image précédente et la suivante de la même collection et du même côté, dans l'ordre de la séquence (le numéro dans le nom)."""
    cible = next((i for i in images if i.chemin == chemin), None)
    if cible is None:
        return None, None
    meme = sorted((i.chemin for i in images if i.groupe == cible.groupe and i.cote == cible.cote), key=_cle_de_sequence)
    k = meme.index(chemin)
    return (meme[k - 1] if k > 0 else None, meme[k + 1] if k + 1 < len(meme) else None)
