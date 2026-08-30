"""Matérialise le registre intégré vers la config Claude Code."""

from __future__ import annotations

import json
import logging
from pathlib import Path
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
            if name in pool_enabled:
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
) -> Path:
    """Merge binding + overlay → `effective/<session_id>.json`."""
    binding_merged = compute_binding_merged(settings, kind=kind, cwd=cwd)
    merged = apply_mcp_overlay(binding_merged, mcp_overlay)
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
