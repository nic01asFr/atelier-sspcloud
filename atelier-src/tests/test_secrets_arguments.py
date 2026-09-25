"""Les secrets portés par les `args` d'un serveur stdio deviennent des références.

Constaté après déploiement (25/09) : le connecteur `n8n`, un pont stdio
(`mcp-remote`), porte son jeton dans `args[4]` (`--header` puis
`Authorization: Bearer …`). La conversion ne traitait que `headers` et `env` :
le jeton restait en clair dans tous les `.mcp.json` de projets. Claude Code
développe `${VAR}` dans `args` comme dans le reste de la déclaration.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.env_secrets import chemin_du_fichier, lire_le_fichier
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.mcp_secrets import en_references, en_references_fournies, secrets_en_clair
from mcp_gateway.atelier.mcp_sync import (
    lier_le_projet,
    materialize_mcp_config,
    materialize_session_mcp,
    write_project_binding,
)
from mcp_gateway.db import connect

JETON = "jeton-n8n-0123456789abcdef"
VARIABLE = "ATELIER_MCP_N8N_AUTHORIZATION"


def _n8n(entete: str = f"Authorization: Bearer {JETON}") -> dict:
    return {
        "type": "stdio",
        "command": "npx",
        "args": ["-y", "mcp-remote", "https://n8n.exemple/mcp", "--header", entete],
    }


def _pool(reglages: AtelierSettings, config: dict) -> None:
    conn = connect(reglages.gateway_db_path)
    try:
        IntegratedMcpStore(conn).upsert("n8n", config)
    finally:
        conn.close()


@pytest.mark.parametrize(
    ("args", "attendu", "variable"),
    [
        (["--header", f"Authorization: Bearer {JETON}"], "Authorization: Bearer ${%s}", VARIABLE),
        (["--header", f"Authorization:Bearer {JETON}"], "Authorization:Bearer ${%s}", VARIABLE),
        (["-H", f"Authorization: {JETON}"], "Authorization: ${%s}", VARIABLE),
        (["--header", f"X-Api-Key: {JETON}"], "X-Api-Key: ${%s}", "ATELIER_MCP_N8N_X_API_KEY"),
        ([f"--header=Authorization: Bearer {JETON}"], "--header=Authorization: Bearer ${%s}", VARIABLE),
        ([f"--token={JETON}"], "--token=${%s}", "ATELIER_MCP_N8N_ARG_TOKEN"),
        (["--api-key", JETON], "${%s}", "ATELIER_MCP_N8N_ARG_API_KEY"),
        ([f"Bearer {JETON}"], "Bearer ${%s}", "ATELIER_MCP_N8N_ARG_2"),
    ],
)
def test_chaque_forme_d_argument_devient_une_reference(args, attendu, variable) -> None:
    config = {"command": "npx", "args": ["mcp-remote", "https://n8n.exemple/mcp", *args]}
    sortie, variables = en_references("n8n", config)
    assert JETON not in json.dumps(sortie)
    assert sortie["args"][-1] == attendu % variable
    assert variables == {variable: JETON}
    assert secrets_en_clair(config) == [f"args[{len(config['args']) - 1}]"]
    assert secrets_en_clair(sortie) == []


def test_un_argument_sans_secret_passe_tel_quel() -> None:
    config = {
        "command": "npx",
        "args": ["mcp-remote", "https://n8n.exemple/mcp", "--header", "Accept: application/json", "--debug"],
    }
    sortie, variables = en_references("n8n", config)
    assert sortie == config and variables == {}


def test_une_valeur_connue_du_serveur_est_retrouvee_dans_un_argument() -> None:
    """En dernier ressort : le secret de `env`, recopié dans une adresse."""
    config = {
        "command": "npx",
        "args": ["mcp-remote", f"https://n8n.exemple/mcp/{JETON}/sse"],
        "env": {"N8N_API_KEY": JETON},
    }
    sortie, variables = en_references("n8n", config)
    assert sortie["args"][1] == "https://n8n.exemple/mcp/${ATELIER_MCP_N8N_ENV_N8N_API_KEY}/sse"
    assert variables == {"ATELIER_MCP_N8N_ENV_N8N_API_KEY": JETON}


def test_un_jeton_different_n_est_pas_remplace_par_celui_fourni() -> None:
    config = _n8n("Authorization: Bearer autre-jeton-du-projet")
    sortie = en_references_fournies("n8n", config, {VARIABLE: JETON})
    assert sortie["args"] == config["args"]


def test_aucune_valeur_en_clair_dans_les_trois_sorties(reglages: AtelierSettings, tmp_path: Path) -> None:
    _pool(reglages, _n8n())
    projet = reglages.projects_dir / "projet"
    projet.mkdir(parents=True)
    materialize_mcp_config(reglages)  # portée utilisateur, pont, liaison des projets
    effectif = materialize_session_mcp(reglages, "conv-n8n", kind="code", cwd=projet)
    lier_le_projet(reglages, projet)

    for chemin in (
        effectif,
        projet / ".mcp.json",
        Path.home() / ".claude.json",
        reglages.work_dir / ".claude.json",
        reglages.mcp_config_path,
    ):
        assert JETON not in chemin.read_text(encoding="utf-8"), chemin
    reference = f"Authorization: Bearer ${{{VARIABLE}}}"
    assert json.loads(effectif.read_text(encoding="utf-8"))["mcpServers"]["n8n"]["args"][4] == reference
    projet_json = json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))
    assert projet_json["mcpServers"]["n8n"]["args"][4] == reference
    assert lire_le_fichier(chemin_du_fichier(reglages))[VARIABLE] == JETON


@pytest.mark.parametrize(
    "entete", [f"Authorization: Bearer {JETON}", f"Authorization:Bearer {JETON}"]
)
def test_un_mcp_json_existant_est_migre_a_la_liaison(reglages: AtelierSettings, tmp_path: Path, entete) -> None:
    """La forme écrite dans le projet peut différer de celle du pool : la valeur suffit."""
    _pool(reglages, _n8n())
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"n8n": _n8n(entete)}}), encoding="utf-8"
    )
    write_project_binding(reglages, projet, ["n8n"])
    texte = (projet / ".mcp.json").read_text(encoding="utf-8")
    assert JETON not in texte
    assert json.loads(texte)["mcpServers"]["n8n"]["args"][4] == entete.replace(JETON, f"${{{VARIABLE}}}")


def test_un_argument_secret_inconnu_du_pool_est_conserve_et_signale(
    reglages: AtelierSettings, tmp_path: Path, caplog
) -> None:
    _pool(reglages, _n8n())
    projet = tmp_path / "projet"
    projet.mkdir()
    tiers = {
        "command": "npx",
        "args": ["mcp-remote", "https://tiers.exemple/mcp", "--header", "X-Api-Key: cle-du-tiers-0123"],
    }
    (projet / ".mcp.json").write_text(json.dumps({"mcpServers": {"tiers": tiers}}), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="atelier.mcp_sync"):
        write_project_binding(reglages, projet, ["tiers", "n8n"])
    serveurs = json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert serveurs["tiers"]["args"] == tiers["args"]
    assert "tiers.args[3]" in caplog.text
    assert "cle-du-tiers" not in caplog.text, "on signale l'argument, jamais sa valeur"
