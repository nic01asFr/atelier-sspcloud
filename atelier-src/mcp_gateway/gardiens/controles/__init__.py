"""Les contrôles internes : des fonctions `(contexte, controle) -> {etat, constats}`.

Un contrôle n'agit jamais : il lit, puis rend un JSON. Les gestes sont ailleurs
(`gestes.py`), et seul l'exécuteur les appelle.
"""

from __future__ import annotations

from typing import Any, Callable

from mcp_gateway.gardiens.controles import automates, sante, securite

REGISTRE: dict[str, Callable[..., dict[str, Any]]] = {
    "entretien.automates": automates.inventaire,
    "sante.service": sante.service,
    "sante.creations": sante.creations,
    "sante.ci": sante.ci_main,
    "sante.image": sante.image_main,
    "sante.disque": sante.disque,
    "securite.ecoutes": securite.ecoutes,
    "securite.secrets": securite.secrets_en_clair,
    "securite.droits": securite.droits,
    "securite.bypass": securite.bypass,
}
