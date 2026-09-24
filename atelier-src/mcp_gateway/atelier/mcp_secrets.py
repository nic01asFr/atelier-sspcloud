"""Les secrets des connecteurs, tenus hors des fichiers d'un projet.

Le `.mcp.json` d'un projet vit dans son dossier, et ce dossier se commite et
se pousse. L'Atelier y recopiait les déclarations du pool telles quelles,
en-têtes `Authorization` compris : un jeton de la passerelle est parti ainsi
sur GitHub.

Le fichier ne porte donc plus que des références, `${ATELIER_MCP_…}`, que
Claude Code développe lui-même dans `url`, `headers`, `env`, `command` et
`args` (documenté). Les valeurs restent là où elles sont déjà rangées — la
base du pool, `~/work/.secrets` pour la clé de l'Atelier — et l'Atelier les
remet dans l'environnement des processus qu'il lance, et dans celui que
l'extension VS Code donne à son `claude`.

Un nom de variable se déduit du service et de l'en-tête, sans état : le même
connecteur donne toujours la même variable, d'un fichier à l'autre et d'un
redémarrage à l'autre.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("atelier.mcp_secrets")

PREFIXE = "ATELIER_MCP_"

# Ce qui s'annonce comme un secret par son nom. Large exprès : un en-tête
# rangé à tort parmi les secrets devient une référence qui marche quand même
# (l'Atelier fournit sa valeur) ; un secret rangé à tort parmi le reste part
# en clair dans un dépôt.
_ENTETES_SECRETS = frozenset(
    {"authorization", "proxy-authorization", "cookie", "x-api-key", "api-key", "apikey"}
)
_MOTS_SECRETS = ("token", "secret", "key", "password", "passwd", "auth", "credential", "cookie")

# Le schéma d'authentification reste lisible dans le fichier : il ne dit rien
# du secret, et il dit à qui relit ce qu'on attend de la variable.
_SCHEMA = re.compile(r"^(Bearer|Token|Basic)\s+(\S.*)$", re.IGNORECASE)


def est_une_reference(valeur: Any) -> bool:
    """Vrai si la valeur renvoie déjà à l'environnement, au lieu de le porter."""
    return isinstance(valeur, str) and "${" in valeur


def est_un_nom_secret(nom: str) -> bool:
    cle = nom.strip().lower()
    if cle in _ENTETES_SECRETS:
        return True
    return any(mot in cle for mot in _MOTS_SECRETS)


def _majuscules(texte: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", texte.upper()).strip("_")


def nom_de_variable(service: str, cle: str, *, dans_env: bool = False) -> str:
    """La variable qui porte un secret : `ATELIER_MCP_<SERVICE>_<EN-TÊTE>`.

    Un secret d'environnement d'un serveur stdio s'écrit
    `ATELIER_MCP_<SERVICE>_ENV_<CLÉ>`, pour ne jamais croiser un en-tête du
    même nom.
    """
    milieu = "ENV_" if dans_env else ""
    return f"{PREFIXE}{_majuscules(service)}_{milieu}{_majuscules(cle)}"


def _en_reference(variable: str, valeur: str) -> tuple[str, str]:
    """Ce qui s'écrit dans le fichier, et ce que la variable doit contenir."""
    m = _SCHEMA.match(valeur.strip())
    if m:
        return f"{m.group(1)} ${{{variable}}}", m.group(2).strip()
    return f"${{{variable}}}", valeur


def en_references(
    service: str, config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """La déclaration sans ses secrets, et les variables qui les portent.

    Ne touche qu'aux en-têtes et à l'environnement dont le nom annonce un
    secret, et qui ne sont pas déjà des références. Le reste de la
    déclaration passe tel quel.
    """
    sortie = dict(config)
    variables: dict[str, str] = {}
    for champ, dans_env in (("headers", False), ("env", True)):
        bloc = config.get(champ)
        if not isinstance(bloc, dict):
            continue
        nouveau = dict(bloc)
        for cle, valeur in bloc.items():
            if not isinstance(valeur, str) or not valeur.strip():
                continue
            if est_une_reference(valeur) or not est_un_nom_secret(str(cle)):
                continue
            variable = nom_de_variable(service, str(cle), dans_env=dans_env)
            nouveau[cle], variables[variable] = _en_reference(variable, valeur)
        sortie[champ] = nouveau
    return sortie, variables


def secrets_en_clair(config: dict[str, Any]) -> list[str]:
    """Les en-têtes et variables d'une déclaration qui portent un secret en clair."""
    trouves: list[str] = []
    for champ in ("headers", "env"):
        bloc = config.get(champ)
        if not isinstance(bloc, dict):
            continue
        for cle, valeur in bloc.items():
            if (
                isinstance(valeur, str)
                and valeur.strip()
                and not est_une_reference(valeur)
                and est_un_nom_secret(str(cle))
            ):
                trouves.append(f"{champ}.{cle}")
    return trouves


def variables_des_services(pool: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Toutes les variables que les déclarations du pool demandent.

    C'est ce que l'Atelier ajoute à l'environnement d'un `claude` : de quoi
    développer chaque référence qu'il a écrite dans un `.mcp.json`. La valeur
    est lue dans le pool à chaque lancement, jamais recopiée ailleurs.
    """
    variables: dict[str, str] = {}
    for nom, config in pool.items():
        if not isinstance(config, dict):
            continue
        _, trouvees = en_references(nom, config)
        variables.update(trouvees)
    return variables


def variables_du_pool(settings: Any) -> dict[str, str]:
    """Les variables des services, lues dans la base du pool.

    Ne lève jamais : un pool illisible ne doit pas empêcher un tour de
    partir, il le prive seulement des connecteurs qui en dépendent.
    """
    from mcp_gateway.atelier.mcp_sync import _pool_enabled

    try:
        return variables_des_services(_pool_enabled(settings))
    except Exception as exc:  # noqa: BLE001 — l'environnement ne doit pas casser un tour
        log.warning("variables des connecteurs illisibles : %s", exc)
        return {}
