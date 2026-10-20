"""Empreintes : une configuration, un jeu de données, ont une identité qui ne dépend pas de l'ordre des clés.

Deux essais de même empreinte sont le même essai. C'est ce qui permet de rejouer, de comparer et de ne
jamais écraser.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonique(objet: Any) -> str:
    """JSON stable : clés triées, sans espace, accents conservés."""
    return json.dumps(objet, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def empreinte(objet: Any, longueur: int = 12) -> str:
    return hashlib.sha256(canonique(objet).encode("utf-8")).hexdigest()[:longueur]
