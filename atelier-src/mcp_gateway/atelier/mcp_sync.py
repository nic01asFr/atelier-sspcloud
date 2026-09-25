"""Matérialise le registre intégré vers la config Claude Code."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import quote
from typing import Any, Literal

from mcp_gateway.db import connect
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.mcp_secrets import (
    en_references,
    en_references_fournies,
    est_une_reference,
    secrets_en_clair,
)

log = logging.getLogger("atelier.mcp_sync")

WorkspaceKind = Literal["assistant", "code"]

# La passerelle de l'Atelier, telle qu'un projet la désigne.
SERVICE_ATELIER = "atelier"
# Le navigateur de l'Atelier (stdio, un processus par client) et l'en-tête de
# conversation de la passerelle vivent dans `navigateur` ; réexportés ici pour
# les appelants existants.
from mcp_gateway.atelier.navigateur import (  # noqa: E402
    CONVERSATION_HORS_ATELIER,
    ENTETE_CONVERSATION,
    SERVICE_CHROME,
    declaration_chrome,
    est_le_navigateur,
    navigateur_configure,
)


def est_alias_onyxia_deguise(nom: str) -> bool:
    """Onyxia_nic01asfr n'est pas le service Onyxia : c'est Atelier `/mcp`.

    Le vrai connecteur s'appelle `Onyxia`. Les agents Code l'ouvrent en
    natif (`mcp__Onyxia__*`) — pas via `gateway_find_tools`, qui n'existait
    pas encore quand cet accès tenait déjà.
    """
    cle = nom.lower()
    return cle.startswith("onyxia") and cle != "onyxia"


def est_amont_de_la_gateway(nom: str) -> bool:
    """Compat : l'alias déguisé seulement, plus le service Onyxia lui-même."""
    return est_alias_onyxia_deguise(nom)


def sans_amonts_gateway(servers: dict[str, Any]) -> dict[str, Any]:
    """Hors les portes Atelier mal nommées Onyxia_*."""
    return {
        nom: cfg for nom, cfg in servers.items() if not est_alias_onyxia_deguise(nom)
    }


def pour_le_home(servers: dict[str, Any]) -> dict[str, Any]:
    """Le HOME porte Onyxia : les projets sans `.mcp.json` en héritent.

    On n'écarte que l'alias déguisé (`Onyxia_nic01asfr`), qui n'est pas
    le service Onyxia — c'est la porte `/mcp` de l'Atelier.

    Le navigateur n'y demande rien de plus : c'est un serveur stdio, dont
    chaque client lance son propre processus — le cloisonnement est là.
    """
    propre = sans_amonts_gateway(servers)
    sortie: dict[str, Any] = {}
    for nom, cfg in propre.items():
        if isinstance(cfg, dict):
            # Jamais un secret en clair dans ce fichier : les déclarations du
            # pool deviennent leurs références `${ATELIER_MCP_…}`, dont
            # `~/work/.secrets/claude-env.sh` porte les valeurs (env_secrets).
            sortie[nom], _ = en_references(nom, cfg)
        else:
            sortie[nom] = cfg
    return sortie


def assurer_onyxia_natif(
    merged: dict[str, dict[str, Any]],
    pool: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Un agent Code a Onyxia en MCP natif dès que le pool l'a.

    La case Connecteurs d'un projet pouvait l'oublier ; les tools directs
    n'en dépendaient pas.
    """
    if "Onyxia" in pool and "Onyxia" not in merged:
        merged = dict(merged)
        merged["Onyxia"] = pool["Onyxia"]
    return sans_amonts_gateway(merged)


def _load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("invalid mcp json %s: %s", path, exc)
        return None
    return loaded if isinstance(loaded, dict) else None


# Un projet qui n'a jamais choisi ses connecteurs hérite du pool entier. Son
# `.mcp.json` est désormais écrit quand même (VS Code et le terminal ne lisent
# que lui) ; cette marque dit qu'il reflète le pool et doit le suivre.
MARQUE_HERITAGE = Path(".atelier") / "connecteurs-herites"


def herite_du_pool(cwd: Path) -> bool:
    """Vrai si le projet n'a pas choisi ses connecteurs lui-même."""
    return (cwd / MARQUE_HERITAGE).is_file() or not (cwd / ".mcp.json").is_file()


def _binding_du_dossier(cwd: Path) -> dict[str, Any] | None:
    """Le choix du projet, ou None s'il hérite du pool."""
    if (cwd / MARQUE_HERITAGE).is_file():
        return None
    return _load_json_object(cwd / ".mcp.json")


def _binding_selection(binding: dict[str, Any]) -> dict[str, bool]:
    """Nom serveur → activé dans le binding (défaut true si absent)."""
    servers = binding.get("mcpServers")
    if not isinstance(servers, dict):
        return {}
    out: dict[str, bool] = {}
    for name, raw in servers.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(raw, dict):
            out[name] = True
            continue
        out[name] = bool(raw.get("enabled", True))
    return out


def apply_mcp_overlay(
    merged: dict[str, dict[str, Any]],
    mcp_overlay: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Les désactivations propres à une conversation — jamais celle de l'Atelier.

    Le serveur de l'Atelier est présent sur toutes les surfaces ; une
    conversation qui s'en priverait n'aurait plus ses outils `atelier_*` ici
    et les aurait dans VS Code.
    """
    out = dict(merged)
    if mcp_overlay:
        for name, active in mcp_overlay.items():
            if not isinstance(name, str) or name == SERVICE_ATELIER:
                continue
            if active is False and name in out:
                del out[name]
    return out


def compute_binding_merged(
    settings: AtelierSettings,
    *,
    kind: WorkspaceKind,
    cwd: Path,
) -> dict[str, dict[str, Any]]:
    """Niveau 2 seul — pool ∩ bindings fichier, sans overlay conversation."""
    pool = _pool_enabled(settings)
    if kind == "code":
        binding = _binding_du_dossier(cwd)
        merged = assurer_onyxia_natif(merge_session_mcp_servers(pool, binding), pool)
        return integrer_l_atelier(assurer_l_atelier(integrer_le_navigateur(merged, settings), settings))
    global_binding = _load_json_object(settings.assistant_root / ".mcp.json")
    session_binding = _binding_du_dossier(cwd)
    return integrer_l_atelier(
        assurer_l_atelier(
            integrer_le_navigateur(
                merge_assistant_bindings(pool, global_binding, session_binding),
                settings,
            ),
            settings,
        )
    )


def assurer_l_atelier(servers: dict[str, Any], settings: AtelierSettings) -> dict[str, Any]:
    """Le serveur de l'Atelier (`atelier_*`) est dans tout projet, sur toute surface.

    Il n'était là que si le `.mcp.json` du projet l'avait coché : mesuré le
    25 septembre, aucune des quatre surfaces n'avait les outils de l'Atelier
    pour le Lecteur Grist. Il n'est plus un choix du projet.
    """
    if SERVICE_ATELIER in servers:
        return servers
    return {SERVICE_ATELIER: declaration_atelier(settings), **servers}


def portee_utilisateur(settings: AtelierSettings) -> dict[str, Any]:
    """Ce que `~/.claude.json` déclare pour tous les dossiers : l'Atelier seul.

    Ce qui vaut pour un projet vit dans son `.mcp.json` (liaison du projet) :
    la portée utilisateur ne porte que ce qui est commun à tous, sans quoi
    VS Code et le terminal verraient des connecteurs que le projet n'a pas.
    """
    return {SERVICE_ATELIER: declaration_atelier(settings)}


def merge_assistant_bindings(
    pool_enabled: dict[str, dict[str, Any]],
    global_binding: dict[str, Any] | None,
    session_binding: dict[str, Any] | None,
    *,
    mcp_overlay: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge pool ∩ binding global ; session = sélection explicite ou désactivations."""
    merged = merge_session_mcp_servers(pool_enabled, global_binding)
    if session_binding is not None:
        selection = _binding_selection(session_binding)
        positives = {name for name, enabled in selection.items() if enabled}
        negatives = {name for name, enabled in selection.items() if not enabled}
        if positives:
            merged = {name: merged[name] for name in positives if name in merged}
        else:
            for name in negatives:
                merged.pop(name, None)
    if mcp_overlay:
        for name, active in mcp_overlay.items():
            if not isinstance(name, str):
                continue
            if active is False and name in merged:
                del merged[name]
    return sans_amonts_gateway(merged)


def _assistant_binding_paths(settings: AtelierSettings, session_cwd: Path) -> tuple[Path, Path]:
    global_path = settings.assistant_root / ".mcp.json"
    session_path = session_cwd / ".mcp.json"
    return global_path, session_path


def merge_session_mcp_servers(
    pool_enabled: dict[str, dict[str, Any]],
    binding: dict[str, Any] | None,
    *,
    mcp_overlay: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Intersection pool enabled ∩ binding projet ; overlay = toggles conversation (M5)."""
    if binding is None:
        merged = dict(pool_enabled)
    else:
        merged: dict[str, dict[str, Any]] = {}
        declarations = binding.get("mcpServers")
        declarations = declarations if isinstance(declarations, dict) else {}
        for name, enabled in _binding_selection(binding).items():
            if not enabled:
                continue
            if isinstance(declarations.get(name), dict) and declarations[name]:
                # Le projet a sa propre déclaration : elle prime. Elle porte
                # ce que le pool ignore — l'identité de la session dans
                # l'adresse, un helper d'en-têtes — et le pool, lui, ne sert
                # ici qu'à dire ce qui est autorisé. Les confondre faisait
                # parler toutes les conversations sous un même nom.
                config = dict(declarations[name])
                config.pop("enabled", None)
                merged[name] = config
            elif name in pool_enabled:
                merged[name] = pool_enabled[name]
            elif name == SERVICE_ATELIER and isinstance(declarations.get(name), dict):
                # L'Atelier ne figure pas dans son propre pool : sa
                # déclaration fait foi, sinon il serait filtré comme un
                # serveur inconnu et le projet perdrait ce qu'il a choisi.
                merged[name] = declarations[name]
            else:
                log.debug("binding server %s absent du pool enabled — ignoré", name)

    if mcp_overlay:
        for name, active in mcp_overlay.items():
            if not isinstance(name, str):
                continue
            if active is False and name in merged:
                del merged[name]

    return sans_amonts_gateway(merged)


def declaration_atelier(settings: AtelierSettings) -> dict[str, Any]:
    """Comment un agent joint la passerelle de l'Atelier.

    Elle n'est pas dans le pool : l'y mettre ferait sonder l'Atelier par
    lui-même au démarrage. Elle est proposée directement au binding d'un
    projet, comme un service que la maison fournit.

    La clé passe par l'environnement du processus agent, jamais par ce
    fichier — il vit dans le dossier du projet.

    La conversation aussi, par référence : `X-Atelier-Conversation` dit aux
    outils `atelier_artefact_*` qui les appelle, sans que l'agent ait à le
    répéter en argument. Le fichier effectif d'un tour la résout
    (`resoudre_les_variables`), et un client hors conversation — VS Code, qui
    lit le `.mcp.json` du projet — tombe sur le repli « poste ».
    """
    return {
        "type": "http",
        "url": f"http://127.0.0.1:{settings.port}/mcp",
        "headers": {
            "Authorization": "Bearer ${ATELIER_MCP_KEY}",
            ENTETE_CONVERSATION: _CONVERSATION_PAR_REFERENCE,
        },
    }


_CONVERSATION_PAR_REFERENCE = "${ATELIER_SESSION:-" + CONVERSATION_HORS_ATELIER + "}"


def integrer_l_atelier(servers: dict[str, Any]) -> dict[str, Any]:
    """La déclaration de l'Atelier porte l'en-tête de conversation, même ancienne.

    Un `.mcp.json` de projet écrit avant l'en-tête ne le porte pas, et le
    binding y prime sur tout : sans ce complément, ses conversations
    appelleraient les outils d'artefact sans auteur jusqu'à ce qu'on
    réenregistre ses connecteurs. On n'ajoute que l'en-tête manquant ; le
    reste de la déclaration reste tel que le projet l'a écrit.
    """
    cfg = servers.get(SERVICE_ATELIER)
    if not isinstance(cfg, dict):
        return servers
    entetes = cfg.get("headers")
    entetes = dict(entetes) if isinstance(entetes, dict) else {}
    if any(str(k).lower() == ENTETE_CONVERSATION.lower() for k in entetes):
        return servers
    entetes[ENTETE_CONVERSATION] = _CONVERSATION_PAR_REFERENCE
    sortie = dict(servers)
    sortie[SERVICE_ATELIER] = {**cfg, "headers": entetes}
    return sortie


def integrer_le_navigateur(
    servers: dict[str, Any],
    settings: AtelierSettings,
) -> dict[str, Any]:
    """Remplace la déclaration du navigateur de l'Atelier par celle du lanceur.

    Seule l'entrée `SERVICE_CHROME` est touchée, et seulement si le
    navigateur n'est pas éteint : un connecteur tiers qui parle de Chrome
    reste tel que la personne l'a écrit. Une ancienne déclaration HTTP (le
    service distant, son jeton, son en-tête) devient celle du lanceur stdio.
    """
    if not navigateur_configure(settings):
        return dict(servers)
    sortie: dict[str, Any] = {}
    for nom, cfg in servers.items():
        if est_le_navigateur(nom):
            sortie[nom] = declaration_chrome(settings)
        else:
            sortie[nom] = cfg
    return sortie


# Les variables qu'un connecteur peut demander dans son adresse. Le fichier
# effectif est reconstruit à chaque tour, et l'Atelier connaît alors la
# conversation : il peut donc les résoudre, ce que le client ne saurait pas faire.
#
# C'est volontairement une demande, pas un cadeau. Ajouter l'identité de la
# conversation à l'adresse de tous les connecteurs l'enverrait à des services
# tiers qui n'en ont que faire — mcp.data.gouv.fr n'a pas à savoir qui lui parle.
# Un service ne la reçoit que s'il l'a écrite dans son adresse.
#
# La passerelle de l'Atelier en a besoin : c'est par là que ses outils
# `atelier_*` savent quelle conversation les appelle.
VARIABLES_CONNUES = ("ATELIER_SESSION", "ATELIER_AGENT")

_VARIABLE = re.compile(r"\$\{([A-Z_]+)(?::-([^}]*))?\}")


def resoudre_les_variables(config: dict[str, Any], *, session: str, agent: str) -> dict[str, Any]:
    """Remplit dans l'adresse les variables que l'Atelier sait renseigner.

    La syntaxe est celle du shell, `${NOM}` ou `${NOM:-repli}`, parce que c'est
    déjà celle du fichier de projet et qu'un connecteur écrit à la main s'y lit
    sans mode d'emploi.

    Une variable qu'on ne connaît pas est laissée telle quelle plutôt qu'effacée :
    une adresse visiblement fautive se répare, une adresse silencieusement vidée
    de son identité donne un service qui mélange deux conversations sans le dire.
    """
    valeurs = {"ATELIER_SESSION": session, "ATELIER_AGENT": agent}

    def remplaceur(encoder: bool) -> Any:
        def remplacer(m: re.Match[str]) -> str:
            nom, repli = m.group(1), m.group(2)
            if nom in valeurs and valeurs[nom]:
                return quote(valeurs[nom], safe="") if encoder else valeurs[nom]
            # Dans un en-tête, une variable qu'on ne fournit pas (le jeton
            # d'un connecteur, `${ATELIER_MCP_…}`) reste au client, repli
            # compris : c'est lui qui la développe depuis son environnement.
            if not encoder and nom not in VARIABLES_CONNUES:
                return m.group(0)
            if repli is not None:
                return quote(repli, safe="") if encoder else repli
            return m.group(0)

        return remplacer

    sortie = dict(config)
    change = False
    url = str(config.get("url") or "")
    if "${" in url:
        resolue = _VARIABLE.sub(remplaceur(True), url)
        if resolue != url:
            sortie["url"] = resolue
            change = True
    # Les en-têtes aussi : c'est par là que la passerelle de l'Atelier reçoit la
    # conversation. Pas d'encodage d'URL dans un en-tête.
    entetes = config.get("headers")
    if isinstance(entetes, dict) and any("${" in str(v) for v in entetes.values()):
        nouveaux = {
            k: _VARIABLE.sub(remplaceur(False), v) if isinstance(v, str) else v
            for k, v in entetes.items()
        }
        if nouveaux != entetes:
            sortie["headers"] = nouveaux
            change = True
    return sortie if change else config


def _avec_identite(config: dict[str, Any], nom: str, wikichat_url: str) -> dict[str, Any]:
    """Inscrit l'identité de la session dans l'adresse du coordinateur.

    Le fichier de projet porte `?agent=${WIKICHAT_AGENT:-}`, à charge pour le
    client d'y substituer la variable. On ne s'y fie pas : le fichier
    effectif est reconstruit à chaque tour et nous connaissons alors le nom.
    L'écrire résolu enlève une dépendance à un détail d'implémentation, et
    un agent qui se présente sans nom perd sa mémoire et son courrier.
    """
    if not nom:
        return config
    url = str(config.get("url") or "")
    if not url or not _est_le_coordinateur(url, wikichat_url):
        return config
    base, _, requete = url.partition("?")
    garde = [
        p
        for p in requete.split("&")
        if p and not p.startswith("agent=")
    ]
    garde.insert(0, f"agent={quote(nom, safe='')}")
    sortie = dict(config)
    sortie["url"] = base + "?" + "&".join(garde)
    return sortie


# La même machine s'écrit de plusieurs façons. Comparer les adresses sans le
# savoir fait manquer une correspondance pourtant évidente : le binding d'un
# projet dit « localhost », la configuration du service dit « 127.0.0.1 ».
_HOTES_LOCAUX = {"localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0"}


def _hote_normalise(url: str) -> str:
    autorite = url.split("://", 1)[-1].split("/", 1)[0]
    hote, _, port = autorite.rpartition(":")
    if not hote:
        hote, port = autorite, ""
    if hote.lower() in _HOTES_LOCAUX:
        hote = "local"
    return f"{hote.lower()}:{port}"


def _est_le_coordinateur(url: str, wikichat_url: str) -> bool:
    if not wikichat_url or not url:
        return False
    return _hote_normalise(url) == _hote_normalise(wikichat_url)


def project_binding_state(
    settings: AtelierSettings,
    cwd: Path,
) -> list[dict[str, Any]]:
    """Ce que le pool propose au projet, et ce que le projet en retient.

    Sans fichier de binding, un projet hérite du pool entier : c'est
    l'absence de choix, pas un choix vide. On l'expose tel quel plutôt que
    d'écrire un fichier que personne n'a demandé.
    """
    pool = _pool_enabled(settings)
    binding = _binding_du_dossier(cwd)
    selection = _binding_selection(binding) if binding is not None else {}
    herite = binding is None
    from mcp_gateway.atelier.gateway_tools import nature_service

    etat: list[dict[str, Any]] = []
    for name in sorted(pool.keys()):
        nature = nature_service(pool[name], settings.wikichat_url, nom=name)
        etat.append(
            {
                "id": name,
                "name": nature["group"] if nature["system"] else name,
                "id_technique": name,
                "active": True if herite else selection.get(name, False),
                "group": nature["group"],
                "system": nature["system"],
                "scope": nature["scope"],
            }
        )
    # La passerelle de l'Atelier n'est pas dans le pool. Elle est dans tout
    # projet, sans case à cocher ; ce qu'on affiche est ce que l'agent reçoit
    # — lu au même endroit que le fichier effectif, pas supposé.
    try:
        presente = SERVICE_ATELIER in compute_binding_merged(settings, kind="code", cwd=cwd)
    except OSError:
        presente = False
    etat.insert(
        0,
        {
            "id": SERVICE_ATELIER,
            "name": "Accès aux outils",
            "id_technique": SERVICE_ATELIER,
            "active": presente,
            "fixe": True,
            "group": "Accès aux outils",
            "system": True,
            "scope": [],
        },
    )
    return etat


def write_project_binding(
    settings: AtelierSettings,
    cwd: Path,
    actifs: list[str],
) -> list[dict[str, Any]]:
    """Fixe les services d'un projet, en conservant leur déclaration du pool.

    On recopie la config plutôt qu'un simple nom : le fichier reste lisible
    par Claude Code seul, sans l'Atelier pour l'interpréter.

    Mais jamais ses secrets : le fichier vit dans le dossier du projet, qui
    se commite et se pousse — un jeton de la passerelle est parti ainsi sur
    GitHub. Chaque en-tête secret devient une référence `${ATELIER_MCP_…}`
    que Claude Code développe, et dont l'Atelier fournit la valeur à
    l'environnement des sessions qu'il lance (voir `mcp_secrets`).
    """
    pool = _pool_enabled(settings)
    chemin = cwd / ".mcp.json"
    existant = _load_json_object(chemin) or {}
    deja = existant.get("mcpServers")
    deja = deja if isinstance(deja, dict) else {}
    # La déclaration du projet prime sur celle du pool : elle porte souvent
    # ce que le pool ignore — un helper d'en-têtes, une variable
    # d'environnement. La reprendre du pool reviendrait à la casser. Ses
    # secrets en clair, eux, sont migrés quand le pool les connaît.
    retenus: dict[str, Any] = {}
    # L'Atelier n'est pas un choix : il est dans tout projet.
    actifs = [SERVICE_ATELIER, *[n for n in actifs if n != SERVICE_ATELIER]]
    for nom in actifs:
        if est_alias_onyxia_deguise(nom):
            # Porte Atelier collée sous un nom Onyxia_* : pas le service.
            continue
        if nom == SERVICE_ATELIER:
            # Toujours reconstruite : son adresse suit le port du service.
            retenus[nom] = declaration_atelier(settings)
        elif est_le_navigateur(nom) and navigateur_configure(settings):
            # Le lanceur stdio, le même sur toutes les surfaces.
            retenus[nom] = declaration_chrome(settings)
        elif nom in deja and isinstance(deja[nom], dict):
            config = dict(deja[nom])
            config.pop("enabled", None)
            retenus[nom] = _migrer_les_secrets(nom, config, pool.get(nom), chemin)
        elif nom in pool:
            retenus[nom], _ = en_references(nom, pool[nom])
    existant["mcpServers"] = retenus
    _atomic_write_json(chemin, existant)
    _proteger_du_depot(cwd)
    # Un choix explicite : le projet cesse de suivre le pool.
    (cwd / MARQUE_HERITAGE).unlink(missing_ok=True)
    approuver_les_serveurs_du_projet(cwd, sorted(retenus))
    return project_binding_state(settings, cwd)


def lier_le_projet(
    settings: AtelierSettings,
    cwd: Path,
    *,
    kind: WorkspaceKind = "code",
) -> list[str]:
    """Écrit dans le `.mcp.json` du dossier ce que l'agent y recevra, partout.

    Le fichier effectif d'un tour de l'Atelier se calcule (pool, choix du
    projet, Onyxia natif, navigateur, Atelier) ; VS Code et le terminal, eux,
    ne lisent que `~/.claude.json` et ce `.mcp.json`. On y écrit donc le même
    ensemble — en références, jamais en clair — et on l'approuve dans
    `~/.claude.json` (`enabledMcpjsonServers`). Plus de `disabledMcpServers`
    figé par la dernière ouverture dans VS Code : la sélection vit ici.

    Un projet qui hérite du pool garde sa marque et suit le pool à chaque
    liaison. Rend les noms des serveurs du projet.
    """
    cwd.mkdir(parents=True, exist_ok=True)
    herite = herite_du_pool(cwd)
    merged = compute_binding_merged(settings, kind=kind, cwd=cwd)
    pool = _pool_enabled(settings)
    chemin = cwd / ".mcp.json"
    existant = _load_json_object(chemin) or {}
    deja = existant.get("mcpServers")
    deja = deja if isinstance(deja, dict) else {}
    ecrits: dict[str, Any] = {}
    for nom, cfg in merged.items():
        if not isinstance(cfg, dict):
            continue
        if nom == SERVICE_ATELIER:
            ecrits[nom] = declaration_atelier(settings)
        elif est_le_navigateur(nom) and navigateur_configure(settings):
            ecrits[nom] = declaration_chrome(settings)
        elif not herite and isinstance(deja.get(nom), dict):
            config = dict(deja[nom])
            config.pop("enabled", None)
            ecrits[nom] = _migrer_les_secrets(nom, config, pool.get(nom), chemin)
        else:
            ecrits[nom], _ = en_references(nom, cfg)
    if ecrits != deja or "mcpServers" not in existant:
        existant["mcpServers"] = ecrits
        _atomic_write_json(chemin, existant)
        _proteger_du_depot(cwd)
    if herite:
        marque = cwd / MARQUE_HERITAGE
        marque.parent.mkdir(parents=True, exist_ok=True)
        if not marque.is_file():
            marque.write_text(
                "Ce projet hérite des connecteurs du pool : l'Atelier réécrit .mcp.json"
                " quand le pool change. Choisir ses connecteurs dans l'Atelier retire"
                " cette marque.\n",
                encoding="utf-8",
            )
    approuver_les_serveurs_du_projet(cwd, sorted(ecrits))
    return sorted(ecrits)


def lier_tous_les_projets(settings: AtelierSettings) -> int:
    """Relie chaque dossier de projet (démarrage, pool modifié). Rend le nombre relié."""
    racine = settings.projects_dir
    if not racine.is_dir():
        return 0
    n = 0
    for dossier in sorted(racine.iterdir()):
        if not dossier.is_dir() or dossier.is_symlink() or dossier.name.startswith("."):
            continue
        try:
            lier_le_projet(settings, dossier)
            n += 1
        except OSError as exc:
            log.warning("liaison de %s impossible : %s", dossier.name, exc)
    return n


def approuver_les_serveurs_du_projet(dossier: Path, noms: list[str]) -> bool:
    """Approuve dans `~/.claude.json` les serveurs du `.mcp.json` du dossier.

    Sans approbation, Claude Code demande à l'ouverture (ou ignore en `-p`)
    les serveurs d'un `.mcp.json`. On retire aussi de `disabledMcpServers` —
    que l'Atelier y figeait à chaque ouverture dans VS Code — les serveurs que
    le projet a choisis : ils doivent être actifs partout.

    Un fichier illisible n'est pas écrasé : il porte l'identité de la machine
    et l'historique des projets. Rend vrai si le fichier a changé.
    """
    chemin = Path.home() / ".claude.json"
    data: dict[str, Any] = {}
    if chemin.is_file():
        try:
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if not isinstance(charge, dict):
            return False
        data = charge
    projets = data.setdefault("projects", {})
    if not isinstance(projets, dict):
        return False
    entree = projets.setdefault(str(dossier), {})
    if not isinstance(entree, dict):
        return False
    avant = json.dumps(entree, sort_keys=True)
    entree["enabledMcpjsonServers"] = sorted(set(noms))
    for cle in ("disabledMcpServers", "disabledMcpjsonServers"):
        liste = entree.get(cle)
        if isinstance(liste, list):
            reste = [n for n in liste if n not in noms]
            if reste:
                entree[cle] = reste
            else:
                entree.pop(cle, None)
    if json.dumps(entree, sort_keys=True) == avant:
        return False
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(chemin)
    try:
        chemin.chmod(0o600)
    except OSError:
        pass
    return True


def _migrer_les_secrets(
    nom: str,
    config: dict[str, Any],
    du_pool: dict[str, Any] | None,
    chemin: Path,
) -> dict[str, Any]:
    """Remplace par leur référence les secrets en clair qu'on sait fournir.

    Un en-tête que le pool déclare pour ce service a sa variable : l'Atelier
    la remplit, la valeur en clair peut partir. Un en-tête que le pool ne
    connaît pas a été écrit par la personne, pour un service que nous ne
    servons pas : l'écraser le casserait, et nous n'aurions rien à mettre
    dans la variable. On le laisse, et on le dit.
    """
    references: dict[str, Any] = {}
    if isinstance(du_pool, dict):
        references, _ = en_references(nom, du_pool)
    sortie = dict(config)
    for champ in ("headers", "env"):
        bloc = config.get(champ)
        if not isinstance(bloc, dict):
            continue
        connus = references.get(champ) if isinstance(references.get(champ), dict) else {}
        # La casse d'un en-tête HTTP ne compte pas : `authorization` écrit à
        # la main désigne bien l'`Authorization` du pool.
        par_nom = {str(k).lower(): v for k, v in connus.items()}
        nouveau = dict(bloc)
        for cle in secrets_en_clair({champ: bloc}):
            nom_cle = cle.split(".", 1)[1]
            reference = par_nom.get(nom_cle.lower())
            if est_une_reference(reference):
                nouveau[nom_cle] = reference
            else:
                log.warning(
                    "secret en clair laissé dans %s : %s.%s (inconnu du pool,"
                    " écrit hors de l'Atelier)",
                    chemin,
                    nom,
                    cle,
                )
        sortie[champ] = nouveau
    # Les arguments (`--header "Authorization: Bearer …"` d'un pont stdio) :
    # un secret dont le pool fournit la même valeur devient sa référence ;
    # un autre reste, et se signale comme un en-tête inconnu.
    args = config.get("args")
    if isinstance(args, list):
        _, valeurs = en_references(nom, du_pool) if isinstance(du_pool, dict) else ({}, {})
        sortie["args"] = en_references_fournies(nom, {"args": args}, valeurs)["args"]
        for cle in secrets_en_clair({"args": sortie["args"]}):
            log.warning(
                "secret en clair laissé dans %s : %s.%s (inconnu du pool,"
                " écrit hors de l'Atelier)",
                chemin,
                nom,
                cle,
            )
    return sortie


def _proteger_du_depot(cwd: Path) -> None:
    """Garde `.mcp.json` hors du dépôt, en plus de n'y rien mettre de secret.

    Le .gitignore est complété, pas réécrit. Un fichier déjà suivi le reste :
    le dé-suivre réécrirait l'histoire de la personne sans qu'elle l'ait
    demandé. On le signale, ici et dans l'état du dépôt.
    """
    if not (cwd / ".git").is_dir():
        return
    from mcp_gateway.atelier import git_repos

    try:
        git_repos.completer_le_gitignore(cwd)
        if git_repos.mcp_json_suivi(cwd):
            log.warning(
                "%s/.mcp.json est suivi par git : le .gitignore ne l'en retire pas."
                " Ses secrets sont désormais des références, mais les versions"
                " déjà commitées peuvent en porter — `git rm --cached .mcp.json`"
                " et une rotation des jetons si elles sont parties.",
                cwd,
            )
    except OSError as exc:
        log.warning("protection de .mcp.json impossible dans %s : %s", cwd, exc)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _pool_enabled(settings: AtelierSettings) -> dict[str, dict[str, Any]]:
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        return store.enabled_mcp_servers()
    finally:
        conn.close()


def materialize_session_mcp(
    settings: AtelierSettings,
    session_id: str,
    *,
    kind: WorkspaceKind,
    cwd: Path,
    mcp_overlay: dict[str, Any] | None = None,
    agent_name: str = "",
) -> Path:
    """Merge binding + overlay → `effective/<session_id>.json`."""
    binding_merged = compute_binding_merged(settings, kind=kind, cwd=cwd)
    merged = apply_mcp_overlay(binding_merged, mcp_overlay)
    if agent_name:
        merged = {
            nom: _avec_identite(cfg, agent_name, settings.wikichat_url)
            for nom, cfg in merged.items()
        }
    # Puis les variables que le connecteur a demandées lui-même. Après l'identité
    # du coordinateur, pour qu'un service qui écrirait les deux obtienne les deux.
    merged = {
        nom: resoudre_les_variables(cfg, session=session_id, agent=agent_name)
        for nom, cfg in merged.items()
    }
    # Le fichier effectif ne porte plus de secret en clair : chaque valeur
    # que l'environnement du tour fournit devient sa référence, que le CLI
    # développe (mesuré sur le pod pour `--mcp-config`). Les valeurs viennent
    # du fichier d'environnement unique, régénéré ici au besoin.
    from mcp_gateway.atelier.env_secrets import ecrire_le_fichier

    valeurs = ecrire_le_fichier(settings)
    merged = {
        nom: en_references_fournies(nom, cfg, valeurs) if isinstance(cfg, dict) else cfg
        for nom, cfg in merged.items()
    }
    cfg_path = settings.mcp_effective_dir / f"{session_id}.json"
    _atomic_write_json(cfg_path, {"mcpServers": merged})
    log.info(
        "session mcp %s kind=%s cwd=%s binding=%s effective=%s",
        session_id,
        kind,
        cwd,
        sorted(binding_merged),
        sorted(merged),
    )
    return cfg_path


def materialize_mcp_config(settings: AtelierSettings) -> Path:
    """Écrit `claude-mcp.json` depuis gateway.db (enabled registry) + sync `.claude`."""
    settings.mcp_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        servers = integrer_le_navigateur(sans_amonts_gateway(store.enabled_mcp_servers()), settings)
    finally:
        conn.close()

    payload = {"mcpServers": pour_le_home(servers)}
    cfg_path = settings.mcp_config_path
    _atomic_write_json(cfg_path, payload)

    # La portée utilisateur ne porte que l'Atelier : le reste appartient au
    # `.mcp.json` de chaque projet (liaison), pour que VS Code et le terminal
    # voient les mêmes connecteurs que le tour de l'Atelier.
    commun = portee_utilisateur(settings)
    _merge_user_claude_json(settings.work_dir / ".claude.json", commun)
    home_claude = Path.home() / ".claude.json"
    try:
        _merge_user_claude_json(home_claude, commun)
    except OSError:
        pass

    # Le pool a pu changer : les valeurs des références aussi, et les
    # projets qui en héritent.
    from mcp_gateway.atelier.env_secrets import ecrire_le_fichier

    ecrire_le_fichier(settings)
    lier_tous_les_projets(settings)

    durable_dir = settings.work_dir / ".claude"
    durable_dir.mkdir(parents=True, exist_ok=True)
    (durable_dir / "mcp-config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if settings.mcp_registry_path.is_file():
        log.warning(
            "registry.json legacy encore présent — source canonique = %s",
            settings.gateway_db_path,
        )

    return cfg_path


def _merge_user_claude_json(path: Path, servers: dict[str, dict[str, Any]]) -> None:
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
    data["mcpServers"] = pour_le_home(servers)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    # Ce fichier portait les jetons des connecteurs en clair — celui de n8n y
    # était, en 644, affiché par `claude mcp list`. Il n'y a plus que des
    # références (`pour_le_home`) ; le 600 reste, pour les adresses et pour
    # ce que d'autres mains y écriraient.
    try:
        path.chmod(0o600)
    except OSError:
        pass


def sync_summary(settings: AtelierSettings) -> dict[str, Any]:
    path = materialize_mcp_config(settings)
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        all_servers = store.list_servers(mask=True)
    finally:
        conn.close()
    enabled = [n for n, e in all_servers.items() if e.get("enabled", True)]
    return {
        "mcp_config": str(path),
        "gateway_db": str(settings.gateway_db_path),
        "total": len(all_servers),
        "enabled": enabled,
        "disabled": [n for n in all_servers if n not in enabled],
    }
