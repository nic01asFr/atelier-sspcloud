"""Contrat wikichat, côté Atelier (wikichat `atelier-coherence`, hooks-et-dialogue.md §8).

(a) L'entrée wikichat des fichiers que lit Claude Code est le pont stdio
    `wikichat-mcp-stdio.mjs`, qui reçoit `CLAUDE_CODE_SESSION_ID` : plus de
    `?agent=atelier`.
(b) `atelier` n'est plus écrit comme nom d'agent : ni dans ces fichiers, ni
    dans l'entrée du pool dont se sert la passerelle.
(c) La formule du nom reste `<slug>-<session_id[:6]>`.
(d) Les hooks `wikichat-hook.mjs` de `~/.claude/settings.json` survivent à
    toute réécriture de ce fichier par l'Atelier.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from mcp_gateway.atelier.claude_home import sync_claude_home as synchroniser
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.gateway_tools import nature_service
from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.mcp_sync import (
    lier_le_projet,
    materialize_mcp_config,
    materialize_session_mcp,
)
from mcp_gateway.atelier.sessions import SessionRecord, SessionStore
from mcp_gateway.atelier.vscode_handoff import (
    prepare_vscode_handoff,
    write_claude_settings_env,
)
from mcp_gateway.atelier.wikichat_ensure import ensure_wikichat_mcp_connector
from mcp_gateway.atelier.wikichat_mcp import (
    NOM_PASSERELLE,
    PONT,
    declaration_wikichat,
    renommer_la_passerelle,
    url_de_la_passerelle,
)
from mcp_gateway.db import connect

ANCIENNE = "http://127.0.0.1:3777/sse?agent=atelier"


def _pool(reglages: AtelierSettings, **serveurs: dict) -> None:
    conn = connect(reglages.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        for nom, cfg in serveurs.items():
            store.upsert(nom, cfg)
    finally:
        conn.close()


def _pool_lu(reglages: AtelierSettings) -> dict:
    conn = connect(reglages.gateway_db_path)
    try:
        return IntegratedMcpStore(conn).list_servers()
    finally:
        conn.close()


def _mcp(chemin: Path) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))["mcpServers"]


def _installer(reglages: AtelierSettings) -> Path:
    _pool(reglages, wikichat={"type": "sse", "url": ANCIENNE})
    reglages.owner_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.owner_key_path.write_text("cle-proprietaire-0123456789", encoding="utf-8")
    projet = reglages.projects_dir / "lecteur-grist"
    projet.mkdir(parents=True)
    return projet


# --- (a) le pont stdio ------------------------------------------------------


def test_la_declaration_est_le_pont_stdio_avec_le_node_de_l_atelier(reglages: AtelierSettings) -> None:
    decl = declaration_wikichat(reglages)
    assert decl["type"] == "stdio"
    assert decl["command"] == str(reglages.work_dir / "bin" / "node")
    assert decl["args"] == [str(reglages.work_dir / "wikichat" / "src" / "scripts" / PONT)]
    # Ni nom, ni jeton : l'identité vient de l'environnement du client.
    assert "env" not in decl and "url" not in decl and "headers" not in decl


def test_la_source_de_wikichat_se_regle(tmp_path: Path) -> None:
    reglages = AtelierSettings(work_dir=tmp_path / "work", wikichat_src=str(tmp_path / "wc"))
    assert declaration_wikichat(reglages)["args"] == [str(tmp_path / "wc" / "scripts" / PONT)]


def test_un_wikichat_distant_recoit_son_adresse(tmp_path: Path) -> None:
    reglages = AtelierSettings(work_dir=tmp_path / "work", wikichat_url="http://wikichat.ns:4000/sse")
    assert declaration_wikichat(reglages)["env"] == {"WIKICHAT_HOST": "wikichat.ns", "WIKICHAT_PORT": "4000"}


def test_toutes_les_surfaces_recoivent_le_pont(reglages: AtelierSettings) -> None:
    projet = _installer(reglages)
    materialize_mcp_config(reglages)
    lier_le_projet(reglages, projet)
    effectif = materialize_session_mcp(
        reglages, "conv-1", kind="code", cwd=projet, agent_name="lecteur-grist-conv-1"
    )
    attendu = declaration_wikichat(reglages)
    for chemin in (
        effectif,  # tour de l'Atelier
        projet / ".mcp.json",  # VS Code et terminal
        reglages.mcp_config_path,  # claude-mcp.json
        reglages.work_dir / ".claude" / "mcp-config.json",
    ):
        assert _mcp(chemin)["wikichat"] == attendu, chemin
    # La portée utilisateur ne porte que l'Atelier, et aucune identité wikichat.
    for maison in (Path.home() / ".claude.json", reglages.work_dir / ".claude.json"):
        texte = maison.read_text(encoding="utf-8")
        assert "agent=" not in texte and "wikichat" not in _mcp(maison)


def test_le_tour_donne_son_nom_au_pont_par_l_environnement(reglages: AtelierSettings) -> None:
    """Dans nos tours, le pont hérite de WIKICHAT_AGENT ; ailleurs, il n'a que la conversation."""
    projet = _installer(reglages)
    env = ClaudeHarness(reglages)._env("lecteur-grist-a1b2c3", projet, "a1b2c3d4")
    assert env["WIKICHAT_AGENT"] == "lecteur-grist-a1b2c3"


def test_le_pont_reste_le_coordinateur_pour_l_ecran(reglages: AtelierSettings) -> None:
    nature = nature_service(declaration_wikichat(reglages), reglages.wikichat_url, nom="wikichat")
    assert nature["system"] is True


# --- (b) plus de nom `atelier` ----------------------------------------------


def test_aucun_fichier_ecrit_ne_porte_le_nom_atelier(reglages: AtelierSettings) -> None:
    projet = _installer(reglages)
    ancien = {"mcpServers": {"wikichat": {"type": "sse", "url": ANCIENNE}}}
    (projet / ".mcp.json").write_text(json.dumps(ancien), encoding="utf-8")
    materialize_mcp_config(reglages)
    materialize_session_mcp(reglages, "conv-2", kind="code", cwd=projet, agent_name="lecteur-grist-conv-2")
    fichiers = [
        projet / ".mcp.json",
        reglages.mcp_config_path,
        reglages.work_dir / ".claude" / "mcp-config.json",
        Path.home() / ".claude.json",
        *reglages.mcp_effective_dir.glob("*.json"),
    ]
    for chemin in fichiers:
        assert "agent=atelier" not in chemin.read_text(encoding="utf-8"), chemin


def test_la_passerelle_quitte_le_nom_atelier_au_demarrage(reglages: AtelierSettings) -> None:
    _pool(
        reglages,
        wikichat={"type": "sse", "url": ANCIENNE, "enabled": False},
        tiers={"type": "http", "url": "https://ailleurs/mcp?agent=atelier"},
    )
    assert renommer_la_passerelle(reglages) == ["wikichat"]
    lu = _pool_lu(reglages)
    assert lu["wikichat"]["url"] == f"http://127.0.0.1:3777/sse?agent={NOM_PASSERELLE}"
    assert lu["wikichat"]["enabled"] is False, "l'état choisi reste"
    assert lu["tiers"]["url"] == "https://ailleurs/mcp?agent=atelier", "un tiers n'est pas wikichat"
    assert renommer_la_passerelle(reglages) == [], "idempotent"


def test_l_adresse_de_la_passerelle(reglages: AtelierSettings) -> None:
    assert url_de_la_passerelle("http://h/sse") == f"http://h/sse?agent={NOM_PASSERELLE}"
    assert url_de_la_passerelle("http://h/sse?x=1&agent=atelier") == f"http://h/sse?agent={NOM_PASSERELLE}&x=1"
    assert url_de_la_passerelle("http://h/sse?agent=") == f"http://h/sse?agent={NOM_PASSERELLE}"
    assert url_de_la_passerelle("http://h/sse?agent=pilote") == "http://h/sse?agent=pilote"


def test_le_connecteur_cree_par_l_atelier_porte_le_nom_de_la_passerelle(reglages: AtelierSettings) -> None:
    ensure_wikichat_mcp_connector(reglages)
    url = _pool_lu(reglages)["wikichat"]["url"]
    assert url.endswith(f"?agent={NOM_PASSERELLE}")


# --- (c) la formule du nom --------------------------------------------------


class _Harnais:
    pass


def test_la_formule_du_nom_est_gardee(reglages: AtelierSettings) -> None:
    store = SessionStore(reglages, _Harnais())  # type: ignore[arg-type]
    rec = SessionRecord(session_id="72b08c4e-1111-2222-3333-444455556666", slug="lecteur-grist", model="m")
    assert store._nom_wikichat(rec) == "lecteur-grist-72b08c"


def test_sans_slug_le_nom_n_est_jamais_atelier(reglages: AtelierSettings) -> None:
    store = SessionStore(reglages, _Harnais())  # type: ignore[arg-type]
    rec = SessionRecord(session_id="a1b2c3d4", slug="", model="m")
    nom = store._nom_wikichat(rec)
    assert nom == f"{reglages.default_slug}-a1b2c3"
    assert not nom.startswith("atelier")


# --- (d) les hooks wikichat survivent : un seul fichier de réglages ---------

HOOK = 'node "/home/onyxia/work/wikichat/src/scripts/wikichat-hook.mjs" '
FIGER = "/home/onyxia/work/bin/atelier-figer-le-travail.sh"
ANCIEN_HOOK = 'node "/home/onyxia/work/wikichat/src/scripts/wikichat-mailbox-hook.mjs"'


def _hooks_wikichat() -> dict:
    """Ce que pose `overlay-installer.mjs` (hooksVoulus, guetteur compris)."""
    return {
        "SessionStart": [{"type": "command", "command": HOOK + "session-start", "timeout": 10}],
        "UserPromptSubmit": [{"type": "command", "command": HOOK + "prompt", "timeout": 5}],
        "Stop": [
            {"type": "command", "command": HOOK + "stop", "timeout": 10},
            {"type": "command", "command": HOOK + "guetter", "asyncRewake": True, "timeout": 1800},
        ],
        "SessionEnd": [{"type": "command", "command": HOOK + "session-end"}],
    }


def _wikichat_ecrit(chemin: Path) -> None:
    """Comme `ensureHooks` de wikichat : lit (à travers un lien), retire ses
    entrées (ancien hook compris), repose les siennes, puis écrit un fichier
    temporaire et le renomme par-dessus, ce qui remplace un lien par un fichier."""
    reglages = json.loads(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}
    hooks = reglages.get("hooks") if isinstance(reglages.get("hooks"), dict) else {}
    voulus = _hooks_wikichat()
    for evenement in set(hooks) | set(voulus):
        gardes = []
        for groupe in hooks.get(evenement, []):
            autres = [h for h in groupe.get("hooks", []) if "wikichat" not in h.get("command", "")]
            if autres:
                gardes.append({**groupe, "hooks": autres})
        if evenement in voulus:
            gardes.append({"matcher": "", "hooks": voulus[evenement]})
        hooks[evenement] = gardes
    reglages["hooks"] = hooks
    temporaire = chemin.with_name(chemin.name + ".wikichat-tmp")
    temporaire.write_text(json.dumps(reglages, indent=2), encoding="utf-8")
    os.replace(temporaire, chemin)


def _init_ecrit(reglages: AtelierSettings) -> Path:
    """Le settings.json que pose `atelier-init.sh` sur le volume (ancien hook compris)."""
    durable = reglages.work_dir / ".claude" / "settings.json"
    durable.parent.mkdir(parents=True, exist_ok=True)
    durable.write_text(
        json.dumps(
            {
                "model": "qwen3-6-35b-moe",
                "hooks": {
                    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": ANCIEN_HOOK}]}],
                    "SessionEnd": [{"matcher": "", "hooks": [{"type": "command", "command": FIGER}]}],
                },
                "env": {"ANTHROPIC_MODEL": "qwen3-6-35b-moe"},
            }
        ),
        encoding="utf-8",
    )
    return durable


def _cle_llm(reglages: AtelierSettings) -> None:
    reglages.llm_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.llm_key_path.write_text("factice", encoding="utf-8")


def _vieillir(chemin: Path, age_s: float) -> None:
    instant = time.time() - age_s
    os.utime(chemin, (instant, instant))


def _commandes(chemin: Path) -> list[str]:
    hooks = json.loads(chemin.read_text(encoding="utf-8")).get("hooks") or {}
    return [h["command"] for groupes in hooks.values() for g in groupes for h in g["hooks"]]


def _lien_possible(tmp_path: Path) -> bool:
    try:
        (tmp_path / "sonde-lien").symlink_to(tmp_path)
    except OSError:
        return False
    return True


def _verifier(reglages: AtelierSettings, tmp_path: Path) -> None:
    maison = Path.home() / ".claude" / "settings.json"
    durable = reglages.work_dir / ".claude" / "settings.json"
    for chemin in (maison, durable):
        lu = json.loads(chemin.read_text(encoding="utf-8"))
        commandes = _commandes(chemin)
        assert "WebSearch" in lu["permissions"]["deny"], chemin
        for evenement in ("session-start", "prompt", "stop", "guetter", "session-end"):
            assert HOOK + evenement in commandes, (chemin, evenement)
        assert FIGER in commandes, chemin
        assert ANCIEN_HOOK not in commandes, "l'ancien hook ne revient pas à côté du nouveau"
        assert lu["apiKeyHelper"].startswith("cat "), chemin
        assert lu["model"] == "qwen3-6-35b-moe"
    if _lien_possible(tmp_path):
        assert maison.is_symlink() and maison.resolve() == durable.resolve()
    else:
        assert maison.read_bytes() == durable.read_bytes()


def test_refus_websearch_hooks_wikichat_et_vscode_coexistent(
    reglages: AtelierSettings, tmp_path: Path
) -> None:
    """L'ordre du pod : l'init pose le volume, wikichat démarre et écrit ses hooks
    par renommage dans ~/.claude, l'Atelier démarre (réglages, refus de
    WebSearch), une conversation part dans VS Code, un tour synchronise ; puis
    wikichat redémarre et réécrit, et un tour synchronise encore."""
    _cle_llm(reglages)
    durable = _init_ecrit(reglages)
    _vieillir(durable, 120)
    maison = Path.home() / ".claude" / "settings.json"
    maison.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(durable, maison)  # une ancienne init recopiait le volume dans ~/.claude
    _wikichat_ecrit(maison)
    _vieillir(maison, 60)
    write_claude_settings_env(reglages)  # démarrage de l'Atelier
    prepare_vscode_handoff(reglages, "p", "conv-vscode", reglages.projects_dir / "p")
    synchroniser(reglages)  # début d'un tour
    _verifier(reglages, tmp_path)
    # wikichat redémarre : il lit à travers le lien, puis le remplace par un fichier.
    _wikichat_ecrit(maison)
    synchroniser(reglages)
    write_claude_settings_env(reglages)
    _verifier(reglages, tmp_path)


def test_la_reecriture_des_reglages_garde_les_hooks(reglages: AtelierSettings, tmp_path: Path) -> None:
    _cle_llm(reglages)
    _init_ecrit(reglages)
    maison = Path.home() / ".claude" / "settings.json"
    maison.parent.mkdir(parents=True, exist_ok=True)
    maison.write_text("{}", encoding="utf-8")
    _wikichat_ecrit(maison)
    write_claude_settings_env(reglages)
    write_claude_settings_env(reglages)
    _verifier(reglages, tmp_path)


def test_une_copie_durable_plus_recente_garde_les_hooks_de_la_maison(
    reglages: AtelierSettings, tmp_path: Path
) -> None:
    """Le volume réécrit après wikichat : ses hooks ne sont pas perdus pour autant."""
    _cle_llm(reglages)
    durable = _init_ecrit(reglages)
    maison = Path.home() / ".claude" / "settings.json"
    maison.parent.mkdir(parents=True, exist_ok=True)
    maison.write_text("{}", encoding="utf-8")
    _wikichat_ecrit(maison)
    _vieillir(maison, 60)
    durable.write_text(durable.read_text(encoding="utf-8"), encoding="utf-8")  # plus récent
    write_claude_settings_env(reglages)
    commandes = _commandes(durable)
    assert HOOK + "stop" in commandes and FIGER in commandes


def test_un_fichier_illisible_n_est_jamais_ecrase(reglages: AtelierSettings) -> None:
    from mcp_gateway.atelier.claude_home import unifier_les_reglages

    _init_ecrit(reglages)
    maison = Path.home() / ".claude" / "settings.json"
    maison.parent.mkdir(parents=True, exist_ok=True)
    maison.write_text("{pas du json", encoding="utf-8")
    unifier_les_reglages(reglages)
    assert maison.read_text(encoding="utf-8") == "{pas du json"
    assert not maison.is_symlink()


def test_la_fusion_des_reglages() -> None:
    from mcp_gateway.atelier.claude_home import fusionner_les_reglages

    ancien = {
        "model": "a",
        "effortLevel": "low",
        "env": {"A": "1", "B": "ancien"},
        "permissions": {"deny": ["WebSearch"], "allow": ["Bash(ls:*)"]},
        "hooks": {
            "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": ANCIEN_HOOK}]}],
            "SessionEnd": [{"matcher": "", "hooks": [{"type": "command", "command": FIGER}]}],
        },
    }
    recent = {
        "model": "b",
        "env": {"B": "recent"},
        "permissions": {"deny": ["Bash(rm:*)"]},
        "hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": HOOK + "stop"}]}]},
    }
    fusion = fusionner_les_reglages(recent, ancien)
    assert fusion["model"] == "b" and fusion["effortLevel"] == "low"
    assert fusion["env"] == {"A": "1", "B": "recent"}
    assert fusion["permissions"] == {"deny": ["Bash(rm:*)", "WebSearch"], "allow": ["Bash(ls:*)"]}
    commandes = [h["command"] for g in fusion["hooks"].values() for x in g for h in x["hooks"]]
    assert HOOK + "stop" in commandes and FIGER in commandes
    assert ANCIEN_HOOK not in commandes
