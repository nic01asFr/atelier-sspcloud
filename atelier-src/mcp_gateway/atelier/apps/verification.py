"""Ce qu'une création autonome promet, et ne tient pas.

Un agent écrit `index.html`, la personne l'ouvre dans le panneau, et la page
est blanche : une image que personne n'a déposée, un script chargé depuis un
CDN, un chemin qui commence par `/`. Rien ne le dit à l'agent, qui annonce que
c'est prêt. Ce module lit la page et rend, en phrases, ce qui ne se chargera
pas — avant que la personne ne le voie.

Il ne bloque rien : ce sont des avertissements, rendus avec `atelier_montrer` et
`atelier_artefact_verifier`. La règle suit la politique de sécurité des
créations (`artifacts.CSP_SANDBOX`) : une page autonome n'a aucun accès au
réseau, ses sous-ressources sont ses fichiers ou des `data:`.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

# Ce qui ne dit rien de l'artefact : l'auteur, le manifeste.
FICHIERS_DE_SERVICE = frozenset({".auteur", "artefact.json"})

PAGE = "index.html"
MAX_AVERTISSEMENTS = 12
MAX_PAGE_OCTETS = 2 * 1024 * 1024

_URL_CSS = re.compile(r"url\(\s*['\"]?([^)'\"\s]+)", re.IGNORECASE)
_LIBRES = ("data:", "blob:", "mailto:", "tel:", "javascript:", "about:")
# `<link>` charge quelque chose seulement pour ces rôles ; les autres (canonical,
# alternate…) sont des métadonnées.
_ROLES_CHARGES = frozenset({"stylesheet", "icon", "shortcut", "preload", "modulepreload", "manifest"})


class _Lecteur(HTMLParser):
    """Les adresses que la page charge : images, scripts, styles, médias, cadres."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.adresses: list[str] = []
        self._dans_style = False

    def _ajouter(self, valeur: str | None) -> None:
        brut = (valeur or "").strip()
        if brut and brut not in self.adresses:
            self.adresses.append(brut)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): v for k, v in attrs}
        if tag in ("img", "script", "source", "video", "audio", "track", "iframe", "embed"):
            self._ajouter(a.get("src"))
            self._ajouter(a.get("poster"))
        elif tag == "link":
            roles = set((a.get("rel") or "").lower().split())
            if roles & _ROLES_CHARGES:
                self._ajouter(a.get("href"))
        elif tag == "object":
            self._ajouter(a.get("data"))
        elif tag == "style":
            self._dans_style = True
        for texte in (a.get("style"),):
            for m in _URL_CSS.finditer(texte or ""):
                self._ajouter(m.group(1))

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self._dans_style = False

    def handle_data(self, data: str) -> None:
        if self._dans_style:
            for m in _URL_CSS.finditer(data):
                self._ajouter(m.group(1))


def _lignes(avertissements: list[str]) -> list[str]:
    if len(avertissements) <= MAX_AVERTISSEMENTS:
        return avertissements
    reste = len(avertissements) - MAX_AVERTISSEMENTS
    return avertissements[:MAX_AVERTISSEMENTS] + [f"… et {reste} autres"]


def verifier_references(dossier: Path, *, nom: str = "") -> list[str]:
    """Les phrases qui disent ce que la page `index.html` de `dossier` ne chargera pas.

    Liste vide : rien à dire. Un artefact serveur n'est pas concerné (il sert
    ce qu'il veut) : l'appelant ne l'envoie pas ici.
    """
    nom = nom or dossier.name
    if not dossier.is_dir():
        return [f"le dossier artifacts/{nom}/ n'existe pas"]
    utiles = [f for f in dossier.iterdir() if f.name not in FICHIERS_DE_SERVICE]
    page = dossier / PAGE
    if not page.is_file():
        if not utiles:
            return [
                f"artifacts/{nom}/ est vide : il n'y a rien à ouvrir. Écris {PAGE} (et les fichiers "
                "qu'il charge) dans ce dossier ; créer le dossier ne dépose rien."
            ]
        return [
            f"pas de {PAGE} dans artifacts/{nom}/ : l'adresse de la création n'ouvre rien ; "
            "les autres fichiers s'ouvrent par leur nom."
        ]
    try:
        texte = page.read_bytes()[:MAX_PAGE_OCTETS].decode("utf-8", errors="replace")
    except OSError as exc:
        return [f"{PAGE} illisible : {exc.strerror or exc}"]
    lecteur = _Lecteur()
    try:
        lecteur.feed(texte)
        lecteur.close()
    except Exception:  # noqa: BLE001 — une page mal formée n'est pas une raison de refuser de répondre
        pass
    racine = dossier.resolve()
    avertissements: list[str] = []
    for adresse in lecteur.adresses:
        bas = adresse.lower()
        if bas.startswith(_LIBRES) or bas.startswith("#"):
            continue
        if bas.startswith(("http://", "https://", "//")):
            avertissements.append(
                f"ressource externe, bloquée (une création autonome n'a pas accès au réseau) : {adresse[:120]}. "
                "Dépose-la dans le dossier, ou intègre-la en data:."
            )
            continue
        chemin = unquote(urlsplit(adresse).path)
        if not chemin:
            continue
        if chemin.startswith("/"):
            avertissements.append(
                f"chemin absolu {chemin[:100]} : la création est servie sous /<projet>/{nom}/, "
                "un chemin absolu part ailleurs. Écris-le relatif "
                f"({chemin.lstrip('/')[:100]})."
            )
            continue
        cible = (dossier / chemin).resolve()
        try:
            cible.relative_to(racine)
        except ValueError:
            avertissements.append(f"{chemin[:100]} sort du dossier de la création : il ne sera pas servi")
            continue
        if not cible.exists():
            avertissements.append(f"fichier absent : {chemin[:100]} (référencé par {PAGE}, introuvable dans artifacts/{nom}/)")
    return _lignes(avertissements)
