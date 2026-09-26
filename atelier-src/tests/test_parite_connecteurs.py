"""VS Code et l'Atelier doivent donner la même boîte à outils.

Mesuré le 6 septembre : la conversation `83f88a57`, ouverte dans VS Code,
y voyait dix connecteurs quand l'Atelier ne lui en donnait que quatre —
`datagouv`, `github`, `gitlab`, `llm`, `n8n` et `qgis` en trop. Le même agent,
sur le même fil, n'avait pas les mêmes outils selon la fenêtre par laquelle on
l'ouvrait, et aucun des deux écrans ne le disait.

L'écart venait de la portée utilisateur, qui portait tout le pool. Elle ne
porte plus que l'Atelier ; chaque projet a dans son `.mcp.json` ce que l'agent
y reçoit (voir `test_selection_connecteurs.py`). Restent ici les règles de
transport et d'Onyxia natif.
"""

from __future__ import annotations

import json
from pathlib import Path



def test_un_connecteur_sans_transport_est_ecarte_en_silence() -> None:
    """Le CLI refuse une adresse sans `type`, et ne le dit qu'en diagnostic.

    Relevé sur le pod : « [github] Skipped — MCP server "github" has a "url"
    but no "type" ». Deux connecteurs du pool étaient dans ce cas. Ils
    s'affichaient actifs dans l'Atelier et n'offraient aucun outil — c'est la
    panne que Nicolas décrivait par « ajouté avec sa clé, aucun outil listé ».
    """
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert _avec_son_transport({"url": "https://x/mcp"})["type"] == "http"


def test_une_adresse_en_sse_annonce_son_transport() -> None:
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert _avec_son_transport({"url": "http://127.0.0.1:3777/sse"})["type"] == "sse"
    # La requête ne doit pas masquer la terminaison : wikichat porte `?agent=`.
    assert _avec_son_transport({"url": "http://x/sse?agent=moi"})["type"] == "sse"


def test_un_transport_declare_n_est_jamais_reecrit() -> None:
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert _avec_son_transport({"url": "http://x/sse", "type": "http"})["type"] == "http"


def test_un_connecteur_en_commande_n_a_pas_de_transport() -> None:
    from mcp_gateway.atelier.gateway_mcp import _avec_son_transport

    assert "type" not in _avec_son_transport({"command": "node", "args": ["s.js"]})


def test_le_fichier_utilisateur_du_cli_n_est_lisible_que_par_son_proprietaire(tmp_path: Path) -> None:
    """Il porte les adresses des connecteurs, et parfois leurs jetons en clair.

    Mesuré sur le pod : `~/.claude.json` en 644, avec le jeton n8n dedans,
    affiché par `claude mcp list`. Sur Windows, les droits POSIX n'ont pas de
    sens ; on ne vérifie que là où ils en ont un.
    """
    import os
    import stat

    from mcp_gateway.atelier.mcp_sync import _merge_user_claude_json

    chemin = tmp_path / ".claude.json"
    _merge_user_claude_json(chemin, {"x": {"type": "http", "url": "http://x"}})
    assert chemin.is_file()
    if os.name == "posix":
        assert stat.S_IMODE(chemin.stat().st_mode) == 0o600


# ── Onyxia natif pour les agents Code, alias déguisé hors jeu ───────────
#
# Les agents Code voyaient mcp__Onyxia__* dans leur boîte à outils. Ce n'est
# pas un passage par gateway_find_tools : ces méta-outils n'étaient pas
# enregistrés quand cet accès existait déjà. On ne recopie pas Onyxia dans
# ~/.claude.json : VS Code le sert alors à tous les dossiers, Failed au GET.


def test_l_agent_code_a_onyxia_en_natif() -> None:
    """Le harnais ouvre Onyxia comme les autres MCP du binding."""
    from mcp_gateway.atelier.mcp_sync import merge_session_mcp_servers

    pool = {
        "Onyxia": {"type": "http", "url": "https://passerelle/mcp"},
        "wikichat": {"type": "sse", "url": "http://127.0.0.1:3777/sse"},
    }
    binding = {
        "mcpServers": {
            "atelier": {"type": "http", "url": "http://127.0.0.1:8787/mcp"},
            "Onyxia": {"type": "http", "url": "https://passerelle/mcp"},
            "wikichat": {"type": "sse", "url": "http://127.0.0.1:3777/sse"},
        }
    }
    merged = merge_session_mcp_servers(pool, binding)
    assert merged["Onyxia"]["url"] == "https://passerelle/mcp"
    assert "atelier" in merged
    assert "wikichat" in merged


def test_un_alias_onyxia_n_est_pas_le_service_onyxia() -> None:
    """Onyxia_nic01asfr pointait vers Atelier /mcp : un doublon, pas Onyxia."""
    from mcp_gateway.atelier.mcp_sync import merge_session_mcp_servers

    pool = {"wikichat": {"type": "sse", "url": "http://x/sse"}}
    binding = {
        "mcpServers": {
            "Onyxia_nic01asfr": {
                "type": "http",
                "url": "https://atelier.example/mcp",
            },
            "wikichat": {"type": "sse", "url": "http://x/sse"},
        }
    }
    merged = merge_session_mcp_servers(pool, binding)
    assert "Onyxia_nic01asfr" not in merged
    assert "wikichat" in merged


def test_sans_binding_l_heritage_du_pool_emporte_onyxia() -> None:
    """Pas de `.mcp.json` : l'agent Code héritait le pool, Onyxia compris."""
    from mcp_gateway.atelier.mcp_sync import merge_session_mcp_servers

    pool = {
        "Onyxia": {"type": "http", "url": "https://passerelle/mcp"},
        "filesystem": {"command": "node"},
    }
    merged = merge_session_mcp_servers(pool, None)
    assert "Onyxia" in merged
    assert "filesystem" in merged


def test_un_fichier_de_configuration_ecarte_l_alias_et_onyxia_direct(tmp_path: Path) -> None:
    """Un fichier qui porte le pool (le pont `claude-mcp.json`) n'a ni l'alias ni Onyxia direct.

    Plus personne ne joint Onyxia en direct : il passe par le mandataire de la
    passerelle, que distribue le profil (contrat de l'équipe O).
    """
    from mcp_gateway.atelier.mcp_sync import _merge_user_claude_json

    chemin = tmp_path / ".claude.json"
    _merge_user_claude_json(
        chemin,
        {
            "Onyxia": {"type": "http", "url": "https://passerelle/mcp"},
            "Onyxia_nic01asfr": {"type": "http", "url": "https://atelier.example/mcp"},
            "wikichat": {"type": "sse", "url": "http://x/sse"},
        },
    )
    data = json.loads(chemin.read_text(encoding="utf-8"))
    assert "Onyxia" not in data["mcpServers"]
    assert "Onyxia_nic01asfr" not in data["mcpServers"]
    assert "wikichat" in data["mcpServers"]


