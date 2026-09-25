"""Client MCP d'un serveur stdio que la passerelle lance elle-même.

La passerelle relaie d'ordinaire du HTTP : un serveur stdio est lancé par le
client final depuis son `.mcp.json`, et le pool le marque `stdio-local` sans
s'y connecter. Quelques serveurs doivent pourtant servir aussi les clients de
la passerelle (`gateway_find_tools` / `gateway_call_tool`, compositions) — le
navigateur de l'Atelier d'abord. Pour ceux-là, et pour eux seuls (le pool en
tient la liste), ce client lance le serveur.

Deux temps, pour ne rien garder d'ouvert sans usage :

- `connect()` sonde : lance le serveur, lit ses outils, le referme. Le pool en
  garde la liste (et son cache) ; le service paraît en ligne.
- `call_tool()` relance le serveur au premier appel et le garde tant qu'on s'en
  sert. Après `inactivite_s` sans appel, il est refermé — pour le navigateur,
  c'est aussi fermer son Chrome.

Même interface que `UpstreamClient` pour ce que le pool en lit : `tools`,
`error`, `url`, `_mode`, `connect()`, `call_tool()`, `close()`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

from mcp_gateway.upstream.client import UpstreamError

logger = logging.getLogger("mcp_gateway.upstream.stdio")

PROTOCOL_VERSION = "2025-06-18"
# Une ligne JSON-RPC peut être grosse : l'arbre d'accessibilité d'une page
# encyclopédique dépasse le mégaoctet. La limite par défaut d'asyncio (64 Kio)
# ferait échouer la lecture.
LIMITE_LIGNE = 64 * 1024 * 1024


class ClientStdio:
    """Un serveur MCP stdio lancé à la demande, refermé après inactivité."""

    def __init__(
        self,
        server_id: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        *,
        inactivite_s: float = 600.0,
        delai_demarrage: float = 30.0,
        delai_appel: float = 180.0,
    ) -> None:
        self.server_id = server_id
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.url = f"stdio://{command}"
        self.transport = "stdio"
        self._mode = "stdio"
        self.tools: list[dict[str, Any]] = []
        self.error: str | None = None
        self.inactivite_s = inactivite_s
        self.delai_demarrage = delai_demarrage
        self.delai_appel = delai_appel
        self._proc: asyncio.subprocess.Process | None = None
        self._lecteur: asyncio.Task[None] | None = None
        self._attentes: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._id = 0
        self._verrou = asyncio.Lock()
        self._en_cours = 0
        self._veille: asyncio.TimerHandle | None = None

    # -- cycle de vie -------------------------------------------------------

    @property
    def vivant(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def connect(self) -> bool:
        """Sonde le serveur : ses outils, puis on le referme."""
        try:
            async with self._verrou:
                await self._demarrer()
                reponse = await self._requete("tools/list", {}, self.delai_demarrage)
                outils = (reponse or {}).get("tools") or []
                self.tools = [t for t in outils if isinstance(t, dict) and t.get("name")]
                self.error = None
            return True
        except Exception as exc:  # noqa: BLE001 — le pool en fait un état, pas une panne
            self.error = str(exc) or type(exc).__name__
            logger.warning("stdio %s : sondage impossible (%s)", self.server_id, self.error)
            return False
        finally:
            await self._arreter()

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with self._verrou:
            if not self.vivant:
                try:
                    await self._demarrer()
                except BaseException:
                    # Un serveur lancé mais pas initialisé ne doit pas passer
                    # pour vivant à l'appel suivant.
                    await self._arreter()
                    raise
        self._en_cours += 1
        self._desarmer_veille()
        try:
            return await self._requete(
                "tools/call", {"name": tool_name, "arguments": arguments}, self.delai_appel
            )
        finally:
            self._en_cours -= 1
            self._armer_veille()

    async def close(self) -> None:
        self._desarmer_veille()
        await self._arreter()

    async def _demarrer(self) -> None:
        from mcp_gateway.atelier.stdio_probe import resoudre_commande

        binaire = resoudre_commande(self.command)
        if not binaire:
            raise UpstreamError(f"« {self.command} » introuvable sur la machine")
        self._proc = await asyncio.create_subprocess_exec(
            binaire,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, **self.env},
            limit=LIMITE_LIGNE,
        )
        self._lecteur = asyncio.create_task(self._lire(self._proc))
        reponse = await self._requete(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "atelier-passerelle", "version": "1.0"},
            },
            self.delai_demarrage,
        )
        if not isinstance(reponse, dict):
            raise UpstreamError("pas de réponse à l'initialisation")
        await self._envoyer({"jsonrpc": "2.0", "method": "notifications/initialized"})

    async def _arreter(self) -> None:
        proc, self._proc = self._proc, None
        lecteur, self._lecteur = self._lecteur, None
        if proc is not None and proc.returncode is None:
            # L'entrée fermée suffit d'ordinaire : le serveur sort, et son
            # Chrome avec lui (mesuré). La force ensuite.
            try:
                if proc.stdin and not proc.stdin.is_closing():
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass
            for signal_suivant in ("terminate", "kill"):
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                    break
                except asyncio.TimeoutError:
                    try:
                        getattr(proc, signal_suivant)()
                    except ProcessLookupError:
                        break
        if lecteur is not None:
            lecteur.cancel()
            try:
                await lecteur
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self._echouer_les_attentes("serveur arrêté")

    # -- veille d'inactivité ------------------------------------------------

    def _desarmer_veille(self) -> None:
        if self._veille is not None:
            self._veille.cancel()
            self._veille = None

    def _armer_veille(self) -> None:
        self._desarmer_veille()
        if self.inactivite_s <= 0 or self._en_cours > 0:
            return
        boucle = asyncio.get_running_loop()
        self._veille = boucle.call_later(
            self.inactivite_s, lambda: asyncio.ensure_future(self._s_endormir())
        )

    async def _s_endormir(self) -> None:
        self._veille = None
        if self._en_cours > 0:
            return
        async with self._verrou:
            if self._en_cours == 0 and self.vivant:
                logger.info("stdio %s : inactif, refermé", self.server_id)
                await self._arreter()

    # -- JSON-RPC -----------------------------------------------------------

    async def _envoyer(self, message: dict[str, Any]) -> None:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.returncode is not None:
            raise UpstreamError(f"{self.server_id} : serveur arrêté")
        proc.stdin.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        await proc.stdin.drain()

    async def _requete(self, methode: str, params: dict[str, Any], delai: float) -> dict[str, Any]:
        self._id += 1
        ident = self._id
        attente: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._attentes[ident] = attente
        try:
            await self._envoyer({"jsonrpc": "2.0", "id": ident, "method": methode, "params": params})
            message = await asyncio.wait_for(attente, timeout=delai)
        except asyncio.TimeoutError as exc:
            raise UpstreamError(f"{self.server_id} : pas de réponse à {methode} en {delai:.0f} s") from exc
        finally:
            self._attentes.pop(ident, None)
        if message.get("error"):
            raise UpstreamError(str(message["error"]))
        resultat = message.get("result")
        return resultat if isinstance(resultat, dict) else {}

    async def _lire(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        try:
            while True:
                ligne = await proc.stdout.readline()
                if not ligne:
                    break
                try:
                    message = json.loads(ligne.decode("utf-8", "replace"))
                except json.JSONDecodeError:
                    continue
                if not isinstance(message, dict):
                    continue
                if "method" in message and "id" in message:
                    await self._repondre_au_serveur(message)
                    continue
                attente = self._attentes.get(message.get("id"))  # type: ignore[arg-type]
                if attente is not None and not attente.done():
                    attente.set_result(message)
        except (asyncio.CancelledError, ValueError):
            pass
        finally:
            self._echouer_les_attentes("le serveur s'est arrêté")

    async def _repondre_au_serveur(self, requete: dict[str, Any]) -> None:
        """Les rares questions qu'un serveur pose à son client."""
        methode = requete.get("method")
        if methode == "ping":
            reponse: dict[str, Any] = {"jsonrpc": "2.0", "id": requete["id"], "result": {}}
        elif methode == "roots/list":
            reponse = {"jsonrpc": "2.0", "id": requete["id"], "result": {"roots": []}}
        else:
            reponse = {
                "jsonrpc": "2.0",
                "id": requete["id"],
                "error": {"code": -32601, "message": f"méthode non prise en charge : {methode}"},
            }
        try:
            await self._envoyer(reponse)
        except UpstreamError:
            pass

    def _echouer_les_attentes(self, raison: str) -> None:
        for attente in list(self._attentes.values()):
            if not attente.done():
                attente.set_exception(UpstreamError(f"{self.server_id} : {raison}"))
