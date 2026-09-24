"""Le mandataire de l'hôte des applications : HTTP en flux, WebSocket, en-têtes.

Ce qui passe par ici vient d'une application écrite par un agent, et y va.
Le mandataire ne lui fait pas confiance plus qu'il ne faut :

- à l'aller, il retire ce qui n'est pas pour elle — les en-têtes de saut, le
  cookie de session de l'hôte, `Authorization`, et tout `Forwarded`,
  `X-Forwarded-*` ou `X-Atelier-*` qu'un client aurait posé pour se faire
  passer pour nous — puis ajoute les siens ;
- au retour, il lui interdit ce qui toucherait les autres : un `Set-Cookie`
  perd son `Domain`, son `Path` est ramené au préfixe de l'application, un
  nom `__Host-` est refusé (il vaudrait pour tout l'hôte) ; un `Location` qui
  vise l'amont est réécrit ; `Service-Worker-Allowed` disparaît, qui
  laisserait un service worker régner hors de son préfixe ;
- il ajoute des défauts qu'elle peut préciser mais pas omettre : `nosniff`,
  `Referrer-Policy`, et `frame-ancestors` limité à l'Atelier.

Les corps vont en flux dans les deux sens, sans rien garder en mémoire : un
envoi de fichier de deux cents mégaoctets ne coûte que ses morceaux en vol,
et un flux SSE arrive à mesure (`X-Accel-Buffering: no`).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Iterable, Sequence
from typing import Any
from urllib.parse import urlsplit

from mcp_gateway.atelier.apps.passage import COOKIE_APPS
from mcp_gateway.atelier.relais_ws import (  # noqa: F401 — réexportés pour `serveur`
    FERME_AMONT_INJOIGNABLE,
    FERME_NON_AUTHENTIFIE,
    FERME_ORIGINE_REFUSEE,
)

log = logging.getLogger("atelier.apps.proxy")

SAUT = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "proxy-connection",
        "te",
        "trailer",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

# Ce qu'un client ne choisit pas : c'est nous qui le posons, ou personne.
RETIRES_ENTREE = frozenset({"host", "authorization", "forwarded"})
PREFIXES_RETIRES_ENTREE = ("x-forwarded-", "x-atelier-")
RETIRES_SORTIE = frozenset({"service-worker-allowed"})

# Plafond d'un message WebSocket, dans chaque sens.
WS_TAILLE_MAX = 16 * 2**20
WS_PING_S = 20.0

# Codes de fermeture : ceux du relais commun, et deux propres aux applications.
FERME_NON_DECLARE = 4404
FERME_PAS_PRETE = 1013  # « réessayez plus tard »


def _connexion_listes(valeurs: Iterable[str]) -> set[str]:
    """Les en-têtes que `Connection` déclare de saut, en plus des classiques."""
    noms: set[str] = set()
    for v in valeurs:
        noms.update(t.strip().lower() for t in v.split(",") if t.strip())
    return noms


def _sans_cookie_apps(valeur: str) -> str:
    morceaux = [m.strip() for m in valeur.split(";") if m.strip()]
    return "; ".join(m for m in morceaux if m.split("=", 1)[0].strip() != COOKIE_APPS)


def entetes_vers_amont(
    bruts: Sequence[tuple[str, str]],
    *,
    prefixe: str,
    hote_public: str,
    client_ip: str,
    websocket: bool = False,
) -> list[tuple[str, str]]:
    """Les en-têtes que l'application reçoit : ceux du client, nettoyés, et les nôtres."""
    listes = _connexion_listes(v for k, v in bruts if k.lower() == "connection")
    sortie: list[tuple[str, str]] = []
    for cle, valeur in bruts:
        nom = cle.lower()
        if nom in SAUT or nom in listes or nom in RETIRES_ENTREE:
            continue
        if nom.startswith(PREFIXES_RETIRES_ENTREE):
            continue
        if websocket and (nom.startswith("sec-websocket-") or nom == "origin"):
            # La poignée de main amont est la nôtre ; l'origine du client a
            # déjà été vérifiée, l'amont reçoit la nôtre.
            continue
        if nom == "cookie":
            valeur = _sans_cookie_apps(valeur)
            if not valeur:
                continue
        sortie.append((cle, valeur))
    sortie += [
        ("X-Forwarded-Prefix", prefixe),
        ("X-Forwarded-Host", hote_public),
        ("X-Forwarded-Proto", "https"),
        ("X-Forwarded-For", client_ip),
        ("X-Atelier-Utilisateur", "proprietaire"),
        ("X-Atelier-Acces", "proprietaire"),
    ]
    return sortie


def reecrire_cookie(valeur: str, *, prefixe: str, chemin_retire: bool) -> str | None:
    """Le `Set-Cookie` tel qu'on le laisse passer, ou None s'il est refusé."""
    morceaux = [m.strip() for m in valeur.split(";")]
    if not morceaux or "=" not in morceaux[0]:
        return None
    nom = morceaux[0].split("=", 1)[0].strip()
    # `__Host-` exige `Path=/` : il vaudrait pour toutes les applications de
    # l'hôte, et le nôtre en fait partie.
    if not nom or nom.lower().startswith("__host-") or nom == COOKIE_APPS:
        return None
    attributs: list[str] = []
    chemin = "/"
    for attr in morceaux[1:]:
        if not attr:
            continue
        cle = attr.split("=", 1)[0].strip().lower()
        if cle == "domain":
            continue
        if cle == "path":
            chemin = attr.split("=", 1)[1].strip() if "=" in attr else "/"
            continue
        attributs.append(attr)
    if not chemin.startswith("/"):
        chemin = "/"
    if chemin_retire:
        chemin = prefixe + ("/" if chemin == "/" else chemin)
    elif not (chemin == prefixe or chemin.startswith(prefixe + "/")):
        chemin = prefixe + "/"
    return "; ".join([morceaux[0], f"Path={chemin}", *attributs])


def reecrire_location(
    valeur: str, *, prefixe: str, chemin_retire: bool, amont: str, origine_apps: str
) -> str:
    """Un `Location` qui vise l'amont ou la racine redevient une adresse de l'hôte."""
    if valeur.startswith("//"):
        return valeur
    if valeur.startswith("/"):
        return (prefixe + valeur) if chemin_retire else valeur
    morceaux = urlsplit(valeur)
    if morceaux.scheme in ("http", "https") and amont and morceaux.netloc == urlsplit(amont).netloc:
        chemin = morceaux.path or "/"
        if chemin_retire:
            chemin = prefixe + chemin
        suite = f"?{morceaux.query}" if morceaux.query else ""
        fragment = f"#{morceaux.fragment}" if morceaux.fragment else ""
        return f"{origine_apps}{chemin}{suite}{fragment}"
    return valeur


def entetes_vers_client(
    bruts: Sequence[tuple[str, str]],
    *,
    prefixe: str,
    chemin_retire: bool,
    amont: str,
    origine_apps: str,
    origine_atelier: str,
) -> list[tuple[bytes, bytes]]:
    listes = _connexion_listes(v for k, v in bruts if k.lower() == "connection")
    sortie: list[tuple[str, str]] = []
    vus: set[str] = set()
    for cle, valeur in bruts:
        nom = cle.lower()
        if nom in SAUT or nom in listes or nom in RETIRES_SORTIE:
            continue
        if nom == "set-cookie":
            neuf = reecrire_cookie(valeur, prefixe=prefixe, chemin_retire=chemin_retire)
            if neuf is None:
                log.info("cookie refusé pour %s : %s", prefixe, valeur.split("=", 1)[0])
                continue
            valeur = neuf
        elif nom == "location":
            valeur = reecrire_location(
                valeur, prefixe=prefixe, chemin_retire=chemin_retire, amont=amont, origine_apps=origine_apps
            )
        elif nom == "content-security-policy" and "frame-ancestors" not in valeur:
            valeur = f"{valeur.rstrip('; ')}; frame-ancestors 'self' {origine_atelier}".strip()
        vus.add(nom)
        sortie.append((cle, valeur))
    if "x-content-type-options" not in vus:
        sortie.append(("X-Content-Type-Options", "nosniff"))
    if "referrer-policy" not in vus:
        sortie.append(("Referrer-Policy", "same-origin"))
    if "content-security-policy" not in vus:
        sortie.append(("Content-Security-Policy", f"frame-ancestors 'self' {origine_atelier}".strip()))
    sortie.append(("X-Accel-Buffering", "no"))
    return [(k.lower().encode("latin-1"), v.encode("latin-1", "replace")) for k, v in sortie]


class CorpsTropGros(Exception):
    pass


async def corps_borne(flux: AsyncIterator[bytes], plafond: int) -> AsyncIterator[bytes]:
    """Le corps de la requête, morceau par morceau, arrêté au plafond."""
    total = 0
    async for morceau in flux:
        if not morceau:
            continue
        total += len(morceau)
        if total > plafond:
            raise CorpsTropGros(total)
        yield morceau


# ── Origine et site ────────────────────────────────────────────────────

METHODES_SURES = frozenset({"GET", "HEAD", "OPTIONS"})


def refus_meme_site(methode: str, entetes: Any, origine_apps: str) -> str | None:
    """Anti-CSRF entre pods : `*.user.lab.sspcloud.fr` est un seul site.

    Une méthode qui écrit est refusée si le navigateur la dit venue d'un autre
    site ou d'un voisin du même site, ou si son `Origin` n'est pas l'hôte des
    applications.
    """
    if methode.upper() in METHODES_SURES:
        return None
    site = (entetes.get("sec-fetch-site") or "").lower()
    if site in ("same-site", "cross-site"):
        return "requête d'un autre site refusée"
    origine = entetes.get("origin")
    if origine is not None and origine.rstrip("/").lower() != origine_apps:
        return "origine refusée"
    return None


# ── WebSocket ──────────────────────────────────────────────────────────
#
# Le relais lui-même est `relais_ws.relayer`, commun à `/vscode` et
# `/chrome/vnc` ; l'hôte des applications lui passe `WS_TAILLE_MAX`,
# `WS_PING_S`, le socket Unix de la cible et le compteur du superviseur.
