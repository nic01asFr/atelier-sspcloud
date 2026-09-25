"""La passerelle lance elle-même les serveurs stdio qu'on lui confie.

Le navigateur de l'Atelier est un serveur stdio ; la passerelle en lance une
instance pour ses clients (`gateway_call_tool`, compositions). Ces tests
parlent à un vrai processus : un petit serveur MCP en Python, lancé et
refermé comme le serait `atelier-chrome`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from mcp_gateway.upstream.stdio_client import ClientStdio

SERVEUR = r'''
import json, os, sys
journal = os.environ.get("JOURNAL")
def ecrire(m):
    sys.stdout.write(json.dumps(m) + "\n"); sys.stdout.flush()
if journal:
    open(journal, "a").write(f"lance {os.getpid()} {os.environ.get('PORTEE', '')}\n")
for ligne in sys.stdin:
    m = json.loads(ligne)
    if "id" not in m:
        continue
    if m["method"] == "initialize":
        ecrire({"jsonrpc": "2.0", "id": m["id"], "result": {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "faux", "version": "1"}}})
    elif m["method"] == "tools/list":
        ecrire({"jsonrpc": "2.0", "id": m["id"], "result": {"tools": [{"name": "echo", "inputSchema": {"type": "object"}}, {"name": "gros", "inputSchema": {"type": "object"}}]}})
    elif m["method"] == "tools/call":
        nom = m["params"]["name"]
        if nom == "echo":
            # Une question du serveur au client avant de répondre : le client
            # doit y répondre sans se mélanger.
            ecrire({"jsonrpc": "2.0", "id": "q1", "method": "ping"})
            reponse = json.loads(sys.stdin.readline())
            assert reponse.get("id") == "q1" and "result" in reponse
            texte = json.dumps(m["params"]["arguments"])
        elif nom == "gros":
            texte = "x" * 300_000
        else:
            ecrire({"jsonrpc": "2.0", "id": m["id"], "error": {"code": -32602, "message": "inconnu"}})
            continue
        ecrire({"jsonrpc": "2.0", "id": m["id"], "result": {"content": [{"type": "text", "text": texte}]}})
if journal:
    open(journal, "a").write(f"fin {os.getpid()}\n")
'''


@pytest.fixture()
def serveur(tmp_path: Path) -> tuple[Path, Path]:
    script = tmp_path / "faux_serveur.py"
    script.write_text(SERVEUR, encoding="utf-8")
    return script, tmp_path / "journal.txt"


def _client(serveur: tuple[Path, Path], **options: float) -> ClientStdio:
    script, journal = serveur
    return ClientStdio(
        "registry:faux",
        sys.executable,
        [str(script)],
        {"JOURNAL": str(journal), "PORTEE": "passerelle"},
        **options,
    )


def _lignes(journal: Path) -> list[str]:
    return journal.read_text(encoding="utf-8").splitlines() if journal.exists() else []


def test_le_sondage_lit_les_outils_et_referme(serveur: tuple[Path, Path]) -> None:
    async def scenario() -> None:
        client = _client(serveur)
        assert await client.connect() is True
        assert [t["name"] for t in client.tools] == ["echo", "gros"]
        assert client.error is None and not client.vivant
        # L'environnement propre à l'instance est bien passé.
        assert _lignes(serveur[1])[0].endswith("passerelle")

    asyncio.run(scenario())
    assert [ligne.split()[0] for ligne in _lignes(serveur[1])] == ["lance", "fin"]


def test_un_appel_relance_le_serveur_puis_il_s_endort(serveur: tuple[Path, Path]) -> None:
    async def scenario() -> None:
        client = _client(serveur, inactivite_s=0.3)
        await client.connect()
        resultat = await client.call_tool("echo", {"a": 1})
        assert json.loads(resultat["content"][0]["text"]) == {"a": 1}
        assert client.vivant
        # Une ligne bien plus longue que la limite par défaut d'asyncio.
        gros = await client.call_tool("gros", {})
        assert len(gros["content"][0]["text"]) == 300_000
        await asyncio.sleep(1.0)
        assert not client.vivant, "inactif, le serveur (et son Chrome) est refermé"
        # Et il revient au besoin.
        assert (await client.call_tool("echo", {"b": 2}))["content"]
        await client.close()
        assert not client.vivant

    asyncio.run(scenario())
    lancements = [ligne for ligne in _lignes(serveur[1]) if ligne.startswith("lance")]
    assert len(lancements) == 3  # sondage, premier appel, réveil


def test_une_erreur_du_serveur_remonte(serveur: tuple[Path, Path]) -> None:
    from mcp_gateway.upstream.client import UpstreamError

    async def scenario() -> None:
        client = _client(serveur)
        with pytest.raises(UpstreamError, match="inconnu"):
            await client.call_tool("absent", {})
        await client.close()

    asyncio.run(scenario())


def test_une_commande_introuvable_est_un_etat_pas_une_panne(tmp_path: Path) -> None:
    async def scenario() -> None:
        client = ClientStdio("registry:x", str(tmp_path / "nulle-part"))
        assert await client.connect() is False
        assert "introuvable" in (client.error or "")

    asyncio.run(scenario())


def test_le_pool_lance_les_serveurs_confies_et_eux_seuls(
    serveur: tuple[Path, Path], tmp_path: Path
) -> None:
    from mcp_gateway.catalog import load_catalog
    from mcp_gateway.db import connect
    from mcp_gateway.registry import import_registry
    from mcp_gateway.upstream import UpstreamPool

    script, journal = serveur
    catalogue = tmp_path / "catalog.yaml"
    catalogue.write_text("servers: {}\nbundles: {}\n", encoding="utf-8")
    conn = connect(tmp_path / "gateway.db")
    commande = {"command": sys.executable, "args": [str(script)], "env": {"JOURNAL": str(journal)}}
    import_registry(conn, {"mcpServers": {"confie": commande, "autre": dict(commande)}})

    async def scenario() -> None:
        pool = UpstreamPool(load_catalog(catalogue), conn, stdio_lances={"confie": {"PORTEE": "passerelle"}})
        etat = await pool.startup()
        assert etat["registry:confie"] == "connected"
        assert etat["registry:autre"] == "stdio-local"
        resultat = await pool.call("confie__echo", {"z": 3})
        assert json.loads(resultat["content"][0]["text"]) == {"z": 3}
        assert pool.status()["registry:confie"]["transport"] == "stdio"
        await pool.shutdown()

    try:
        asyncio.run(scenario())
    finally:
        conn.close()
    lancements = [ligne for ligne in _lignes(journal) if ligne.startswith("lance")]
    assert len(lancements) == 2 and all(ligne.endswith("passerelle") for ligne in lancements)
    assert len([ligne for ligne in _lignes(journal) if ligne.startswith("fin")]) == 2
