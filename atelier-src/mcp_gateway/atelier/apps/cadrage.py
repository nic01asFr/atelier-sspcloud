"""Qui peut encadrer ce que sert l'hôte des applications : l'Atelier, et lui seul.

Le panneau de l'Atelier montre les créations d'un projet dans une iframe, à
côté du fil. Pour que cela marche, et pour que rien d'autre ne le puisse, une
seule politique vaut pour toute réponse de l'hôte des applications :

- `Content-Security-Policy: frame-ancestors <origine de l'Atelier>`, et rien
  d'autre en fait de `frame-ancestors`. Ni `'self'` : une application du même
  hôte ne doit pas pouvoir en encadrer une autre pour la faire cliquer ; ni ce
  que l'application a déclaré de son côté.
- aucun `X-Frame-Options`. n8n rend `SAMEORIGIN`, qui interdirait l'Atelier ;
  `frame-ancestors` le remplace, et le garder ne ferait que semer le doute sur
  la règle qui s'applique.

Sans origine de l'Atelier connue (installation sans adresse publique), rien ne
peut encadrer : `frame-ancestors 'none'`.

La politique est posée à la sortie de l'application ASGI (`CadrageDesReponses`)
et non réponse par réponse : une route ajoutée demain n'y échappe pas, et le
mandataire, les fichiers des créations comme les pages d'erreur de l'hôte
passent tous par elle.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import Any
from urllib.parse import urlsplit

# Une origine telle qu'une source CSP l'accepte : schéma, hôte, port. Rien
# d'autre ne passe, pour qu'une adresse mal réglée ne glisse pas une directive.
_ORIGINE = re.compile(r"^https?://[a-z0-9.-]+(:[0-9]{1,5})?$")


def origine_normalisee(adresse: str) -> str:
    """`https://hote[:port]` tiré d'une adresse, ou vide s'il n'y en a pas de sûre."""
    brut = (adresse or "").strip()
    if not brut:
        return ""
    morceaux = urlsplit(brut)
    if not morceaux.scheme or not morceaux.netloc:
        return ""
    origine = f"{morceaux.scheme}://{morceaux.netloc}".lower()
    return origine if _ORIGINE.match(origine) else ""


def politique(origine_atelier: str) -> str:
    """La seule directive `frame-ancestors` que l'hôte des applications envoie."""
    origine = origine_normalisee(origine_atelier)
    return f"frame-ancestors {origine}" if origine else "frame-ancestors 'none'"


def sans_frame_ancestors(csp: str) -> str:
    """La CSP sans aucune directive `frame-ancestors`."""
    gardees = []
    for directive in (csp or "").split(";"):
        propre = directive.strip()
        if not propre:
            continue
        if propre.split(None, 1)[0].lower() == "frame-ancestors":
            continue
        gardees.append(propre)
    return "; ".join(gardees)


def imposer(entetes: Sequence[tuple[str, str]], origine_atelier: str) -> list[tuple[str, str]]:
    """Les en-têtes d'une réponse, avec la politique de cadrage et elle seule.

    Chaque CSP perd son `frame-ancestors` (une CSP vidée disparaît), le
    `X-Frame-Options` disparaît, et une CSP de plus porte la nôtre. Plusieurs
    CSP s'appliquent toutes : celle-ci suffit donc à fixer la règle.
    """
    sortie: list[tuple[str, str]] = []
    for cle, valeur in entetes:
        nom = cle.lower()
        if nom == "x-frame-options":
            continue
        if nom == "content-security-policy":
            reste = sans_frame_ancestors(valeur)
            if not reste:
                continue
            valeur = reste
        sortie.append((cle, valeur))
    sortie.append(("Content-Security-Policy", politique(origine_atelier)))
    return sortie


class CadrageDesReponses:
    """Middleware ASGI : toute réponse HTTP sort avec la politique de cadrage."""

    def __init__(self, app: Any, origine_atelier: Callable[[], str]) -> None:
        self.app = app
        self.origine_atelier = origine_atelier

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def envoyer(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                bruts = [
                    (k.decode("latin-1"), v.decode("latin-1")) for k, v in message.get("headers") or []
                ]
                neufs = imposer(bruts, self.origine_atelier() or "")
                message = dict(message)
                message["headers"] = [
                    (k.lower().encode("latin-1"), v.encode("latin-1", "replace")) for k, v in neufs
                ]
            await send(message)

        await self.app(scope, receive, envoyer)


__all__ = ["CadrageDesReponses", "imposer", "origine_normalisee", "politique", "sans_frame_ancestors"]
