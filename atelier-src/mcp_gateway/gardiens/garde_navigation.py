"""Hook `PreToolUse` du socle : le navigateur d'un agent n'ouvre que des pages web.

Mesuré sur le pod le 12/10 : le Chrome d'un agent lit `file:///etc/hostname` et
atteint wikichat sur `127.0.0.1:3777`. Il contourne ainsi `garde_bash`, qui
refuse `.secrets` dans une commande mais ne voit pas une page `file:///…/.secrets/`.
Trois choses sont refusées, avec de quoi faire à la place :

1. **Un schéma qui n'est pas du web** : `file:`, `chrome:`, `devtools:`,
   `javascript:`, `blob:`… Seuls `http`, `https` et `about:blank` passent
   (`view-source:` n'est jugé que sur l'adresse qu'il enveloppe).
2. **Une adresse du pod ou de son réseau interne** : `localhost`, `127.0.0.1`,
   `0.0.0.0`, `[::1]`, les réseaux privés et link-local (dont l'adresse des
   métadonnées du cloud), les noms internes (`*.svc`, `*.cluster.local`,
   `*.internal`, un nom sans point comme `wikichat`), et leurs écritures
   détournées — entier (`2130706433`), hexadécimal, octal, `%`-encodée, `\\`.
3. **`/vscode/proxy/<port>`** (et `/proxy/<port>`, `/absproxy/<port>`) : code-server
   relaie n'importe quel port du pod, même depuis l'adresse publique.

Ce qui vaut pour `new_page` et `navigate_page`, et pour `WebFetch` (le CLI
l'exécute depuis le pod : même chemin vers l'intérieur). `evaluate_script` est
relu en meilleur effort : une adresse refusée écrite en toutes lettres dans le
script l'est aussi. Ce n'est pas une frontière étanche (un script peut
composer l'adresse), c'est un garde-fou contre l'erreur et le raccourci ; la
frontière physique est l'objet de `docs/vision/organisation-cible.md` (E5).

Pas de porte de sortie : ni variable d'environnement ni réglage de projet ne le
désactive, un agent les écrirait lui-même. Une création se teste par
`atelier_navigateur_ouvrir`, un service par un artefact serveur.

Même forme que `garde_bash` : l'appel d'outil arrive en JSON sur l'entrée, un
refus sort en code 2 avec la raison sur la sortie d'erreur, le reste en 0. Il
n'importe que la bibliothèque standard.
"""

from __future__ import annotations

import ipaddress
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from mcp_gateway.gardiens.garde_bash import commande_du_hook, poser_un_hook, reglages_par_defaut

MODULE = "mcp_gateway.gardiens.garde_navigation"
# Un `matcher` de Claude Code est une expression régulière sur le nom de l'outil.
MATCHER = r"mcp__chrome-devtools(?:-mcp)?__(?:navigate_page|new_page|evaluate_script)|WebFetch"

A_FAIRE = (
    "Pour montrer ou tester ce que tu as écrit : atelier_artefact_creer(nom), tes fichiers dans "
    "artifacts/<nom>/, puis atelier_navigateur_ouvrir(chemin=\"<nom>/\") te rend une adresse sûre. "
    "Un service (processus) se déclare comme artefact serveur : atelier_artefact_creer(nom, mode=\"serveur\")."
)
RAISON_SCHEMA = (
    "Refusé par le socle de l'Atelier : {quoi} n'est pas une page web. Le navigateur de l'agent n'ouvre "
    "que http et https : file:// lirait les fichiers du pod, clés comprises ; chrome:// et devtools:// "
    "ouvrent les entrailles du navigateur. " + A_FAIRE
)
RAISON_INTERNE = (
    "Refusé par le socle de l'Atelier : {quoi} est une adresse du pod ou de son réseau interne (l'Atelier, "
    "wikichat, code-server et le relais LLM y écoutent). Un agent n'y va pas par son navigateur. " + A_FAIRE
)
RAISON_PROXY = (
    "Refusé par le socle de l'Atelier : {quoi} traverse code-server vers un port quelconque du pod. " + A_FAIRE
)

SCHEMAS_WEB = {"http", "https"}
_PROXY = re.compile(r"^/(?:vscode/)?(?:abs)?proxy/\d+", re.IGNORECASE)
_SUFFIXES_INTERNES = (".localhost", ".local", ".internal", ".svc", ".cluster.local", ".lan", ".home.arpa", ".intranet")
_POINTS = str.maketrans({"。": ".", "｡": ".", "．": "."})
_ADRESSE_EN_CLAIR = re.compile(r"""[A-Za-z][A-Za-z0-9+.\-]*:(?://|/)[^\s'"`)<>\\]+|file:[^\s'"`)<>]+""")


def _ipv4_whatwg(hote: str) -> ipaddress.IPv4Address | None:
    """Lit l'hôte comme le fait Chrome : `2130706433`, `0x7f.1`, `0177.0.0.1` valent 127.0.0.1."""
    parties = hote.split(".")
    if parties and parties[-1] == "":
        parties = parties[:-1]
    if not parties or len(parties) > 4:
        return None
    valeurs: list[int] = []
    for p in parties:
        if p == "":
            return None
        try:
            if p.lower().startswith("0x"):
                valeurs.append(int(p[2:] or "0", 16))
            elif len(p) > 1 and p.startswith("0"):
                valeurs.append(int(p, 8))
            else:
                valeurs.append(int(p, 10))
        except ValueError:
            return None
    if any(v < 0 for v in valeurs) or any(v > 255 for v in valeurs[:-1]):
        return None
    reste = 4 - (len(valeurs) - 1)
    if valeurs[-1] >= 256**reste:
        return None
    nombre = valeurs[-1]
    for i, v in enumerate(valeurs[:-1]):
        nombre += v * 256 ** (3 - i)
    return ipaddress.IPv4Address(nombre)


def _adresse_interne(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(
        ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_unspecified
        or ip.is_reserved or ip.is_multicast
        or (isinstance(ip, ipaddress.IPv4Address) and ip in ipaddress.ip_network("100.64.0.0/10"))
    )


def _hote_interne(hote: str) -> bool:
    hote = unicodedata.normalize("NFKC", unquote(hote)).translate(_POINTS).strip().lower().rstrip(".")
    if not hote:
        return True
    if hote.startswith("[") and hote.endswith("]"):
        hote = hote[1:-1]
    try:
        return _adresse_interne(ipaddress.ip_address(hote))
    except ValueError:
        pass
    ipv4 = _ipv4_whatwg(hote)
    if ipv4 is not None:
        return _adresse_interne(ipv4)
    if hote == "localhost" or hote.endswith(_SUFFIXES_INTERNES):
        return True
    # Un nom sans point (`wikichat`, `kubernetes`, `atelier`) ne désigne que le réseau interne.
    return "." not in hote


def raison_de_refus_url(url: str) -> str | None:
    """La raison du refus, ou None si l'adresse peut être ouverte."""
    brut = unicodedata.normalize("NFKC", str(url or "")).strip()
    # Chrome retire tabulations et retours à la ligne et lit `\` comme `/`.
    brut = re.sub(r"[\t\r\n]", "", brut).replace("\\", "/")
    if not brut:
        return None
    if brut.lower() == "about:blank":
        return None
    schema = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", brut)
    if schema is None:
        brut = "http://" + brut.lstrip("/")  # `localhost:3000/x` : Chrome le lit comme une adresse web
        schema = re.match(r"^([A-Za-z][A-Za-z0-9+.\-]*):", brut)
    nom = schema.group(1).lower()
    if nom == "view-source":
        return raison_de_refus_url(brut[len("view-source:"):])
    if nom not in SCHEMAS_WEB:
        return RAISON_SCHEMA.format(quoi=f"« {nom}: »")
    if not re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://", brut):
        # `http:localhost` : la forme sans `//` se lit comme une adresse web.
        brut = re.sub(r"^([A-Za-z]+):/*", r"\1://", brut, count=1)
    try:
        coupe = urlsplit(brut)
        hote = coupe.hostname or ""
    except ValueError:
        return RAISON_INTERNE.format(quoi="cette adresse illisible")
    if _hote_interne(hote):
        return RAISON_INTERNE.format(quoi=f"« {hote or brut[:60]} »")
    if _PROXY.match(unquote(coupe.path or "")):
        return RAISON_PROXY.format(quoi=f"« {coupe.path[:40]} »")
    return None


def raison_de_refus_script(code: str) -> str | None:
    """Une adresse refusée écrite en toutes lettres dans un script évalué dans la page."""
    for trouve in _ADRESSE_EN_CLAIR.findall(code or ""):
        raison = raison_de_refus_url(trouve)
        if raison:
            return raison
    return None


def raison_de_refus(nom_outil: str, entree: dict[str, Any]) -> str | None:
    """La raison du refus pour cet appel d'outil, ou None s'il passe."""
    fin = nom_outil.rsplit("__", 1)[-1]
    if nom_outil == "WebFetch" or fin in ("navigate_page", "new_page"):
        url = entree.get("url")
        return raison_de_refus_url(url) if isinstance(url, str) else None
    if fin == "evaluate_script" and nom_outil.startswith("mcp__"):
        for cle in ("function", "script", "expression"):
            texte = entree.get(cle)
            if isinstance(texte, str):
                raison = raison_de_refus_script(texte)
                if raison:
                    return raison
    return None


def main_hook(entree: str) -> int:
    try:
        appel = json.loads(entree or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(appel, dict):
        return 0
    nom = appel.get("tool_name")
    donnees = appel.get("tool_input")
    if not isinstance(nom, str) or not isinstance(donnees, dict):
        return 0
    if nom != "WebFetch" and not re.match(r"^mcp__chrome-devtools(?:-mcp)?__", nom):
        return 0
    raison = raison_de_refus(nom, donnees)
    if raison is None:
        return 0
    sys.stderr.write(raison + "\n")
    return 2


def commande_du_hook_navigation(python: str | None = None) -> str:
    return commande_du_hook(python, module=MODULE)


def poser(chemin: Path, python: str | None = None) -> str:
    """Pose le hook dans le fichier de réglages (voir `garde_bash.poser_un_hook`)."""
    return poser_un_hook(chemin, module=MODULE, matcher=MATCHER, python=python)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--poser"]:
        chemin = Path(argv[1]) if len(argv) > 1 else reglages_par_defaut()
        print(f"hook de navigation : {poser(chemin)} ({chemin})")
        return 0
    if argv[:1] == ["--verifier"]:
        raison = raison_de_refus_url(" ".join(argv[1:]))
        print(raison or "accepté")
        return 2 if raison else 0
    return main_hook(sys.stdin.read())


if __name__ == "__main__":
    sys.exit(main())
