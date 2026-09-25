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

Les `args` d'un serveur stdio aussi : un pont comme `mcp-remote` reçoit son
jeton en argument (`--header "Authorization: Bearer …"`), et le jeton de n8n
restait ainsi en clair dans chaque `.mcp.json`. Ce qui précède la valeur
(`Authorization: Bearer `, `--token=`) reste écrit en toutes lettres ; seule la
valeur devient `${ATELIER_MCP_…}`.
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


# Les options qui introduisent un en-tête HTTP en argument (`mcp-remote`,
# `supergateway`, `curl`…). Sensibles à la casse : `-h` est souvent l'aide.
_OPTIONS_EN_TETE = frozenset({"--header", "--headers", "-H"})
_EN_TETE = re.compile(r"^([A-Za-z0-9_-]+)(\s*:\s*)(\S.*)$")
_OPTION_VALEUR = re.compile(r"^(--?[A-Za-z][A-Za-z0-9_.-]*=)(.+)$")
_OPTION = re.compile(r"^--?[A-Za-z][A-Za-z0-9_.-]*$")
_PORTEUR = re.compile(r"\b(Bearer|Token|Basic)(\s+)(\S+)", re.IGNORECASE)
_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")
# En dessous, une « valeur connue » retrouvée dans un argument serait un
# hasard plus qu'un secret.
_LONGUEUR_MINIMALE = 8


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


def _nom_d_option(option: str) -> str:
    return option.lstrip("-").rstrip("=")


def _reserver(variables: dict[str, str], voulu: str, secours: str, valeur: str) -> str:
    """Le nom qui portera `valeur` : le parlant, sauf s'il porte déjà autre chose."""
    for nom in (voulu, secours):
        if variables.get(nom, valeur) == valeur:
            variables[nom] = valeur
            return nom
    suffixe = 2
    while variables.get(f"{secours}_{suffixe}", valeur) != valeur:
        suffixe += 1
    variables[f"{secours}_{suffixe}"] = valeur
    return f"{secours}_{suffixe}"


def _argument_en_reference(
    service: str,
    index: int,
    argument: str,
    precedent: str | None,
    variables: dict[str, str],
) -> str:
    """L'argument, sa valeur secrète remplacée par sa référence ; tel quel sinon.

    `variables` reçoit la variable créée, et sert aussi de valeurs connues :
    un secret des en-têtes ou de l'environnement du même serveur, recopié
    dans un argument, y devient la même référence.
    """
    secours = nom_de_variable(service, f"ARG_{index}")

    def remplacer(prefixe: str, valeur: str, voulu: str) -> str:
        m = _SCHEMA.match(valeur)
        if m:
            prefixe, valeur = f"{prefixe}{m.group(1)} ", m.group(2).strip()
        nom = _reserver(variables, voulu, secours, valeur)
        return f"{prefixe}${{{nom}}}"

    # `--header "Authorization: Bearer …"`, `--header=Authorization:…`
    texte, avant = argument, ""
    if argument.startswith("--header="):
        avant, texte = "--header=", argument[len("--header=") :]
    if avant or precedent in _OPTIONS_EN_TETE:
        m = _EN_TETE.match(texte)
        if m and est_un_nom_secret(m.group(1)):
            return remplacer(
                f"{avant}{m.group(1)}{m.group(2)}",
                m.group(3).strip(),
                nom_de_variable(service, m.group(1)),
            )
        if m:
            # Un en-tête qui n'a rien de secret (`Accept: …`) : tel quel.
            return argument
    # `--token=…`, `--api-key=…`
    m = _OPTION_VALEUR.match(argument)
    if m and est_un_nom_secret(_nom_d_option(m.group(1))):
        return remplacer(
            m.group(1),
            m.group(2),
            nom_de_variable(service, f"ARG_{_nom_d_option(m.group(1))}"),
        )
    # `--token …`, `--api-key …`
    if (
        precedent is not None
        and precedent not in _OPTIONS_EN_TETE
        and _OPTION.match(precedent)
        and est_un_nom_secret(_nom_d_option(precedent))
        and not argument.startswith("-")
    ):
        return remplacer(
            "", argument, nom_de_variable(service, f"ARG_{_nom_d_option(precedent)}")
        )
    # `Bearer …` n'importe où dans l'argument
    m = _PORTEUR.search(argument)
    if m:
        nom = _reserver(variables, secours, secours, m.group(3))
        return f"{argument[: m.start(3)]}${{{nom}}}{argument[m.end(3) :]}"
    # En dernier ressort : une valeur secrète déjà connue de ce serveur.
    return _valeurs_connues_en_references(argument, variables)


def _valeurs_connues_en_references(argument: str, valeurs: dict[str, str]) -> str:
    for nom, valeur in sorted(valeurs.items(), key=lambda kv: -len(kv[1])):
        if len(valeur) >= _LONGUEUR_MINIMALE and valeur in argument:
            argument = argument.replace(valeur, f"${{{nom}}}")
    return argument


def _args_en_references(service: str, args: list[Any], variables: dict[str, str]) -> list[Any]:
    sortie: list[Any] = []
    for index, argument in enumerate(args):
        precedent = args[index - 1] if index and isinstance(args[index - 1], str) else None
        if not isinstance(argument, str) or not argument.strip() or est_une_reference(argument):
            sortie.append(argument)
            continue
        sortie.append(_argument_en_reference(service, index, argument, precedent, variables))
    return sortie


def en_references(
    service: str, config: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """La déclaration sans ses secrets, et les variables qui les portent.

    Ne touche qu'aux en-têtes et à l'environnement dont le nom annonce un
    secret, et aux arguments qui en portent un (`_argument_en_reference`),
    s'ils ne sont pas déjà des références. Le reste passe tel quel.
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
    args = config.get("args")
    if isinstance(args, list):
        sortie["args"] = _args_en_references(service, args, variables)
    return sortie, variables


def en_references_fournies(
    service: str, config: dict[str, Any], valeurs: dict[str, str]
) -> dict[str, Any]:
    """La déclaration où chaque secret en clair que l'on fournit devient sa référence.

    Seulement si la variable porte exactement la même valeur : un projet qui
    déclare son propre jeton pour un service du pool garde le sien (et le
    test de cohérence le signale), plutôt que de recevoir en silence celui du
    pool.
    """
    references, variables = en_references(service, config)
    sortie = dict(config)
    for champ in ("headers", "env"):
        bloc = config.get(champ)
        if not isinstance(bloc, dict) or not variables:
            continue
        nouveau = dict(bloc)
        for cle, valeur in bloc.items():
            ref = (references.get(champ) or {}).get(cle)
            if ref == valeur or not isinstance(ref, str):
                continue
            variable = nom_de_variable(service, str(cle), dans_env=champ == "env")
            if variables.get(variable) is not None and valeurs.get(variable) == variables[variable]:
                nouveau[cle] = ref
        sortie[champ] = nouveau
    args = config.get("args")
    if isinstance(args, list):
        sortie["args"] = _args_fournis(service, args, references.get("args"), variables, valeurs)
    return sortie


def _args_fournis(
    service: str,
    args: list[Any],
    references: Any,
    variables: dict[str, str],
    valeurs: dict[str, str],
) -> list[Any]:
    """Les arguments dont chaque secret a sa valeur dans `valeurs`, en références."""
    sortie = list(args)
    if isinstance(references, list) and len(references) == len(args):
        for index, (argument, ref) in enumerate(zip(args, references)):
            if ref == argument or not isinstance(ref, str):
                continue
            noms = set(_REFERENCE.findall(ref))
            if noms and all(
                variables.get(n) is not None and valeurs.get(n) == variables[n] for n in noms
            ):
                sortie[index] = ref
    # Une valeur fournie pour ce service, retrouvée telle quelle dans un
    # argument, quelle que soit sa forme : c'est sa référence qui doit y être.
    prefixe = f"{PREFIXE}{_majuscules(service)}_"
    connues = {n: v for n, v in valeurs.items() if n.startswith(prefixe)}
    return [
        _valeurs_connues_en_references(a, connues) if isinstance(a, str) else a for a in sortie
    ]


def secrets_en_clair(config: dict[str, Any]) -> list[str]:
    """Les en-têtes, variables et arguments d'une déclaration qui portent un secret en clair.

    Un argument est désigné par sa position : `args[4]`.
    """
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
    args = config.get("args")
    if isinstance(args, list):
        _, variables = en_references("_", {k: v for k, v in config.items() if k != "args"})
        for index, (avant, apres) in enumerate(zip(args, _args_en_references("_", args, variables))):
            if avant != apres:
                trouves.append(f"args[{index}]")
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
