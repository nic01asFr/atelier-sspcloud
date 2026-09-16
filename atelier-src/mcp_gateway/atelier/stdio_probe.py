"""Sondage ponctuel d'un serveur MCP lancé en local (stdio).

La passerelle relaie du HTTP et du SSE ; elle ne fait pas tourner les serveurs
stdio, qui sont démarrés par le client final depuis son `.mcp.json`. Le pool
les marque donc `stdio-local` sans jamais s'y connecter — et leurs outils
restent inconnus.

Or on a besoin de leurs noms : sans eux, on ne peut proposer qu'un service
entier, jamais « ces outils-là ». C'est ce qui empêche, par exemple, de donner
un accès en lecture seule à un serveur de fichiers.

Ce module ne change rien au pool : il lance le serveur le temps d'un
`tools/list`, met le résultat en cache, puis referme. Rien ne reste ouvert.
"""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import shutil
from typing import Any

log = logging.getLogger("mcp_gateway.atelier.stdio_probe")

PROTOCOL_VERSION = "2025-06-18"


async def _lire_reponse(
    proc: asyncio.subprocess.Process,
    attendu: int,
    timeout: float,
) -> dict[str, Any] | None:
    """Lit les lignes JSON-RPC jusqu'à la réponse portant `attendu` comme id.

    Un serveur peut intercaler des notifications (journal, progression) : on
    les ignore plutôt que de prendre la première ligne venue.
    """
    fin = asyncio.get_running_loop().time() + timeout
    while True:
        restant = fin - asyncio.get_running_loop().time()
        if restant <= 0:
            return None
        try:
            ligne = await asyncio.wait_for(proc.stdout.readline(), timeout=restant)
        except asyncio.TimeoutError:
            return None
        if not ligne:
            return None
        try:
            msg = json.loads(ligne.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("id") == attendu:
            return msg


async def probe_stdio_tools(
    command: str,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    *,
    timeout: float = 25.0,
) -> list[dict[str, Any]]:
    """Retourne les outils déclarés par un serveur MCP stdio.

    Lève RuntimeError si le serveur ne répond pas ou refuse la poignée de main.
    """
    args = list(args or [])
    environnement = {**os.environ, **(env or {})}
    binaire = resoudre_commande(command)
    if not binaire:
        raise RuntimeError(
            f"« {command} » introuvable sur la machine — ce connecteur est lancé "
            "par le client, pas par l'Atelier"
        )
    try:
        proc = await asyncio.create_subprocess_exec(
            binaire,
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env=environnement,
        )
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"lancement impossible : {exc}") from exc

    async def envoyer(payload: dict[str, Any]) -> None:
        proc.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    try:
        await envoyer(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "atelier-probe", "version": "1.0"},
                },
            }
        )
        init = await _lire_reponse(proc, 1, timeout)
        if init is None or "result" not in init:
            raise RuntimeError("pas de réponse à l'initialisation")

        await envoyer({"jsonrpc": "2.0", "method": "notifications/initialized"})
        await envoyer({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        rep = await _lire_reponse(proc, 2, timeout)
        if rep is None:
            raise RuntimeError("pas de réponse à tools/list")
        if "error" in rep:
            raise RuntimeError(str(rep["error"]))
        outils = (rep.get("result") or {}).get("tools") or []
        return [t for t in outils if isinstance(t, dict) and t.get("name")]
    finally:
        # Le serveur ne sert qu'au sondage : on le referme dans tous les cas.
        try:
            if proc.stdin and not proc.stdin.is_closing():
                proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            proc.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except (asyncio.TimeoutError, ProcessLookupError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass


def resoudre_commande(commande: str) -> str:
    """Chemin réel d'un interpréteur, même absent du PATH du service.

    Le service tourne avec un PATH minimal ; un serveur MCP déclaré avec
    `node` ou `npx` échouerait au lancement alors que le binaire existe
    ailleurs sur la machine — c'est le client final qui le trouve d'ordinaire,
    pas nous.
    """
    if not commande:
        return ""
    if os.path.isabs(commande):
        return commande if os.path.exists(commande) else ""
    trouve = shutil.which(commande)
    if trouve:
        return trouve
    # Emplacements où un runtime embarqué se cache sur ce genre de poste.
    outils = str(Path.home() / "work" / ".tools")
    motifs = [
        f"{outils}/*/lib/{commande}",
        f"{outils}/*/bin/{commande}",
        f"/usr/lib/*/bin/{commande}",
        f"/opt/*/bin/{commande}",
    ]
    for motif in motifs:
        for chemin in sorted(glob.glob(motif)):
            if os.access(chemin, os.X_OK):
                return chemin
    return ""


def commande_depuis_config(config: dict[str, Any]) -> tuple[str, list[str], dict[str, str]]:
    """Extrait (commande, arguments, environnement) d'une déclaration MCP."""
    commande = str(config.get("command") or "")
    args = config.get("args")
    env = config.get("env")
    return (
        commande,
        [str(a) for a in args] if isinstance(args, list) else [],
        {str(k): str(v) for k, v in env.items()} if isinstance(env, dict) else {},
    )
