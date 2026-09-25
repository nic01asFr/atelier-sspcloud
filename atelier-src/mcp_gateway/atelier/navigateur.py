"""Le navigateur de l'Atelier : comment chaque client le lance.

Le navigateur est un serveur MCP **stdio**, `chrome-devtools-mcp` (le serveur
officiel de l'équipe Chrome DevTools, Apache-2.0), lancé par le lanceur
`~/work/bin/atelier-chrome`. Chaque client qui le déclare — une conversation
de l'Atelier, VS Code, le terminal, un agent wikichat — lance le sien, avec un
Chrome sans écran à lui : profil jetable, aucun port ouvert, tout s'arrête
avec le client (mesures et choix : `docs/navigateur-atelier.md`).

La passerelle en lance une instance à part pour ses propres clients
(`gateway_find_tools` / `gateway_call_tool`, compositions), en portée
`passerelle` : adresses privées refusées, refermée après inactivité.

Il n'y a plus de service distant, d'adresse, de jeton ni d'en-tête de
conversation : le processus *est* la conversation. La déclaration ne porte
aucun secret, et elle est la même sur toutes les surfaces.

Le navigateur de l'Atelier se reconnaît à son identifiant, `SERVICE_CHROME`,
et à rien d'autre. Un connecteur tiers dont le nom ou l'adresse contient
« chrome » n'est pas le nôtre : on ne le réécrit pas.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings

log = logging.getLogger("atelier.navigateur")

SERVICE_CHROME = "chrome-devtools-mcp"
LANCEUR = "atelier-chrome"
# L'en-tête par lequel la passerelle de l'Atelier sait quelle conversation
# l'appelle (outils `atelier_*`). Il servait aussi au navigateur distant ; il
# reste pour l'Atelier seul.
ENTETE_CONVERSATION = "X-Atelier-Conversation"
# La conversation des clients qui lisent un fichier hors conversation (VS Code,
# HOME, `.mcp.json` d'un projet) : ils n'ont pas d'`ATELIER_SESSION` à fournir.
CONVERSATION_HORS_ATELIER = "poste"
# L'environnement de l'instance que la passerelle lance pour ses clients.
ENV_PASSERELLE = {"ATELIER_CHROME_PORTEE": "passerelle"}


def est_le_navigateur(nom: str, cfg: dict[str, Any] | None = None) -> bool:  # noqa: ARG001
    """Vrai pour le seul service déclaré par l'Atelier, reconnu à son identifiant.

    `cfg` est accepté pour la compatibilité des appelants ; il ne décide de
    rien. Reconnaître le navigateur à son adresse faisait réécrire en silence
    tout connecteur tiers dont l'URL contenait « chrome ».
    """
    return nom == SERVICE_CHROME


def lanceur_chrome(settings: AtelierSettings) -> Path:
    """Le lanceur, là où `atelier-init.sh` le pose : `~/work/bin/atelier-chrome`."""
    return settings.work_dir / "bin" / LANCEUR


def navigateur_configure(settings: AtelierSettings) -> bool:
    """Le navigateur est déclaré sauf si on l'a éteint (`ATELIER_NAVIGATEUR=0`).

    On ne vérifie pas ici que le lanceur est installé : la déclaration doit
    être la même partout, et un lanceur absent se dit à l'agent (serveur en
    échec) et dans l'interface (`etat_local`), pas par une déclaration qui
    change d'un démarrage à l'autre.
    """
    return bool(settings.navigateur)


def declaration_chrome(
    settings: AtelierSettings,
    *,
    cloisonner: bool = True,  # noqa: ARG001 — compat : le processus est la conversation
) -> dict[str, Any]:
    """Ce qu'un fichier de configuration dit du navigateur. Sans secret.

    La même pour le fichier effectif d'un tour, le `.mcp.json` d'un projet
    (VS Code, terminal, wikichat) et le pool : chaque client lance son
    processus, qui est à lui seul le cloisonnement.
    """
    return {"type": "stdio", "command": str(lanceur_chrome(settings)), "args": []}


def declaration_du_pool(settings: AtelierSettings) -> dict[str, Any]:
    """L'entrée du pool : la déclaration même que reçoivent les agents.

    La passerelle, qui lance aussi ce serveur pour ses propres clients, y
    ajoute `ENV_PASSERELLE` au lancement (`stdio_de_la_passerelle`), sans
    l'écrire ici : l'écran des connecteurs montre ce que l'agent reçoit.
    """
    return declaration_chrome(settings)


def stdio_de_la_passerelle(settings: AtelierSettings) -> dict[str, dict[str, str]]:
    """Les serveurs stdio que le pool lance lui-même, avec leur environnement."""
    if not navigateur_configure(settings):
        return {}
    return {SERVICE_CHROME: dict(ENV_PASSERELLE)}


# -- état local, pour l'interface ------------------------------------------

_VERIFICATION: dict[str, Any] = {"quand": 0.0, "lanceur": "", "etat": None}
_VERIFICATION_DUREE_S = 60.0


def _verifier_le_lanceur(lanceur: Path) -> dict[str, Any]:
    """Demande au lanceur s'il trouve node, le serveur et Chrome. N'ouvre rien."""
    try:
        sortie = subprocess.run(
            [str(lanceur)],
            env={**os.environ, "ATELIER_CHROME_VERIFIER": "1"},
            capture_output=True,
            text=True,
            timeout=10,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {"pret": False, "raison": f"lanceur non exécutable ({type(exc).__name__})"}
    if sortie.returncode != 0:
        lignes = (sortie.stderr or "").strip().splitlines()
        return {"pret": False, "raison": lignes[-1] if lignes else f"code {sortie.returncode}"}
    trouve = dict(ligne.split("=", 1) for ligne in sortie.stdout.splitlines() if "=" in ligne)
    return {"pret": True, "chrome": trouve.get("chrome", ""), "serveur": trouve.get("serveur", "")}


def racine_des_navigateurs() -> Path:
    """Le dossier où les lanceurs de ce compte rangent profils et comptage."""
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return Path(os.environ.get("TMPDIR") or "/tmp") / f"atelier-chrome-{uid}"


def navigateurs_ouverts() -> int:
    """Les Chrome que les lanceurs de ce compte ont ouverts, encore vivants."""
    try:
        fiches = list((racine_des_navigateurs() / "navigateurs").iterdir())
    except OSError:
        return 0
    n = 0
    for fiche in fiches:
        try:
            ligne = (Path("/proc") / fiche.name / "cmdline").read_bytes()
        except OSError:
            continue
        if b"chrome" in ligne:
            n += 1
    return n


def etat_local(settings: AtelierSettings) -> dict[str, Any]:
    """Ce que l'Atelier sait du navigateur, sans jamais lever.

    `bureau` reste dans la réponse, toujours faux : il n'y a plus de bureau à
    ouvrir (Chrome tourne sans écran, dans le processus de chaque agent).
    """
    if not navigateur_configure(settings):
        return {
            "configure": False,
            "pret": False,
            "bureau": False,
            "raison": "navigateur éteint (ATELIER_NAVIGATEUR=0)",
        }
    lanceur = lanceur_chrome(settings)
    if not lanceur.is_file():
        verification: dict[str, Any] = {"pret": False, "raison": f"lanceur absent : {lanceur}"}
    else:
        maintenant = time.monotonic()
        perime = maintenant - _VERIFICATION["quand"] > _VERIFICATION_DUREE_S
        if _VERIFICATION["etat"] is None or perime or _VERIFICATION["lanceur"] != str(lanceur):
            _VERIFICATION.update(
                etat=_verifier_le_lanceur(lanceur), quand=maintenant, lanceur=str(lanceur)
            )
        verification = dict(_VERIFICATION["etat"])
    try:
        plafond = int(os.environ.get("ATELIER_CHROME_MAX") or 6)
    except ValueError:
        plafond = 6
    return {
        "configure": True,
        "mode": "stdio",
        "lanceur": str(lanceur),
        "bureau": False,
        "navigateurs": navigateurs_ouverts(),
        "maxNavigateurs": plafond,
        **verification,
    }


# -- WebSearch -------------------------------------------------------------

# WebSearch est un outil serveur d'Anthropic : la passerelle LLM de SSPCloud
# l'accepte sans l'exécuter, et le modèle répond en simulant une recherche,
# sans le moindre signal d'erreur (mesuré). On le refuse donc partout : les
# réglages globaux (VS Code, terminal, wikichat) et le `--settings` de chaque
# tour. Refusé, il disparaît de la liste d'outils du modèle (mesuré sur le
# pod, CLI 2.1.281). La recherche passe par le navigateur (un moteur en HTML
# simple) ou par un connecteur de recherche du pool.
OUTILS_REFUSES = ("WebSearch",)


def refuser_les_outils_simules(reglages: dict[str, Any], settings: AtelierSettings) -> dict[str, Any]:
    """Ajoute (ou retire si `websearch_natif`) WebSearch de `permissions.deny`.

    Le reste de la liste est à la personne : on n'y touche pas.
    """
    permissions = reglages.get("permissions")
    permissions = dict(permissions) if isinstance(permissions, dict) else {}
    refus = permissions.get("deny")
    refus = [r for r in refus if isinstance(r, str)] if isinstance(refus, list) else []
    if settings.websearch_natif:
        refus = [r for r in refus if r not in OUTILS_REFUSES]
    else:
        refus += [o for o in OUTILS_REFUSES if o not in refus]
    if refus:
        permissions["deny"] = refus
    else:
        permissions.pop("deny", None)
    sortie = dict(reglages)
    if permissions:
        sortie["permissions"] = permissions
    else:
        sortie.pop("permissions", None)
    return sortie
