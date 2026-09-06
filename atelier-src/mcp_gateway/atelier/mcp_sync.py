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

log = logging.getLogger("atelier.mcp_sync")

WorkspaceKind = Literal["assistant", "code"]

# La passerelle de l'Atelier, telle qu'un projet la désigne.
SERVICE_ATELIER = "atelier"


def _load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("invalid mcp json %s: %s", path, exc)
        return None
    return loaded if isinstance(loaded, dict) else None


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
    out = dict(merged)
    if mcp_overlay:
        for name, active in mcp_overlay.items():
            if not isinstance(name, str):
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
        binding = _load_json_object(cwd / ".mcp.json")
        return merge_session_mcp_servers(pool, binding)
    global_binding = _load_json_object(settings.assistant_root / ".mcp.json")
    session_binding = _load_json_object(cwd / ".mcp.json")
    return merge_assistant_bindings(pool, global_binding, session_binding)


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
    return merged


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

    return merged


def declaration_atelier(settings: AtelierSettings) -> dict[str, Any]:
    """Comment un agent joint la passerelle de l'Atelier.

    Elle n'est pas dans le pool : l'y mettre ferait sonder l'Atelier par
    lui-même au démarrage. Elle est proposée directement au binding d'un
    projet, comme un service que la maison fournit.

    La clé passe par l'environnement du processus agent, jamais par ce
    fichier — il vit dans le dossier du projet.
    """
    return {
        "type": "http",
        "url": f"http://127.0.0.1:{settings.port}/mcp",
        "headers": {"Authorization": "Bearer ${ATELIER_MCP_KEY}"},
    }


# Les variables qu'un connecteur peut demander dans son adresse. Le fichier
# effectif est reconstruit à chaque tour, et l'Atelier connaît alors la
# conversation : il peut donc les résoudre, ce que le client ne saurait pas faire.
#
# C'est volontairement une demande, pas un cadeau. Ajouter l'identité de la
# conversation à l'adresse de tous les connecteurs l'enverrait à des services
# tiers qui n'en ont que faire — mcp.data.gouv.fr n'a pas à savoir qui lui parle.
# Un service ne la reçoit que s'il l'a écrite dans son adresse.
#
# Le service du navigateur en a besoin : c'est par là qu'il saura quel contexte
# rendre à quelle conversation, et donc quelles pages et quels cookies. Sans
# elle, il ne peut ni retrouver un fil d'un tour à l'autre, ni les cloisonner.
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
    url = str(config.get("url") or "")
    if "${" not in url:
        return config
    valeurs = {"ATELIER_SESSION": session, "ATELIER_AGENT": agent}

    def remplacer(m: re.Match[str]) -> str:
        nom, repli = m.group(1), m.group(2)
        if nom in valeurs and valeurs[nom]:
            return quote(valeurs[nom], safe="")
        if repli is not None:
            return quote(repli, safe="")
        return m.group(0)

    resolue = _VARIABLE.sub(remplacer, url)
    if resolue == url:
        return config
    sortie = dict(config)
    sortie["url"] = resolue
    return sortie


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
    binding = _load_json_object(cwd / ".mcp.json")
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
    # La passerelle de l'Atelier n'est pas dans le pool, mais elle se propose
    # comme les autres : sans elle, un agent ne peut ni chercher un outil ni
    # lancer une composition.
    etat.insert(
        0,
        {
            "id": SERVICE_ATELIER,
            "name": "Accès aux outils",
            "id_technique": SERVICE_ATELIER,
            "active": True if herite else selection.get(SERVICE_ATELIER, False),
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
    """
    pool = _pool_enabled(settings)
    chemin = cwd / ".mcp.json"
    existant = _load_json_object(chemin) or {}
    deja = existant.get("mcpServers")
    deja = deja if isinstance(deja, dict) else {}
    # La déclaration du projet prime sur celle du pool : elle porte souvent
    # ce que le pool ignore — un jeton, un helper d'en-têtes, une variable
    # d'environnement. La reprendre du pool reviendrait à la casser.
    retenus: dict[str, Any] = {}
    for nom in actifs:
        if nom == SERVICE_ATELIER:
            # Toujours reconstruite : son adresse suit le port du service.
            retenus[nom] = declaration_atelier(settings)
        elif nom in deja and isinstance(deja[nom], dict):
            config = dict(deja[nom])
            config.pop("enabled", None)
            retenus[nom] = config
        elif nom in pool:
            retenus[nom] = pool[nom]
    existant["mcpServers"] = retenus
    _atomic_write_json(chemin, existant)
    return project_binding_state(settings, cwd)


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
        servers = store.enabled_mcp_servers()
    finally:
        conn.close()

    payload = {"mcpServers": servers}
    cfg_path = settings.mcp_config_path
    _atomic_write_json(cfg_path, payload)

    _merge_user_claude_json(settings.work_dir / ".claude.json", servers)
    home_claude = Path.home() / ".claude.json"
    try:
        _merge_user_claude_json(home_claude, servers)
    except OSError:
        pass

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
    data["mcpServers"] = servers
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


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
