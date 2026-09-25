"""Le relais LLM : ce qui manque à la passerelle pour que Claude Code compacte.

Mesuré le 25 septembre 2026 sur https://llm.lab.sspcloud.fr/api :

- en flux, `/v1/messages` rapporte `usage.input_tokens: 0` et
  `output_tokens: 0`, dans `message_start` comme dans `message_delta` (exact
  en non streamé). Le compteur de Claude Code reste à zéro, et sa compaction
  automatique ne se déclenche jamais, quel que soit le réglage de fenêtre ;
- `/v1/messages/count_tokens` répond 404 ;
- au-delà de la fenêtre (131 072 jetons pour les trois modèles), litellm
  répond 400 `ContextWindowExceededError`, que Claude Code ne reconnaît pas :
  sa compaction réactive, qui attend « prompt is too long », ne part pas.

Le relais se place entre les deux, en boucle locale. Il transmet tout tel quel
et en flux, sans tampon, et ne corrige que ces trois points : il remplit
l'usage nul par une estimation (caractères / `relais_llm_ratio`), répond
lui-même au décompte, et réécrit l'erreur de fenêtre. Mesuré avec son
prototype (essai B) : l'auto-compaction native part à ~106 000 jetons et la
conversation garde tout ce qu'elle savait.

Processus à part, pas route de l'Atelier : VS Code, le terminal et les agents
de wikichat parlent au modèle par lui (`ANTHROPIC_BASE_URL`). Servi par
l'Atelier, il tomberait à chaque `atelier-relancer`, et avec lui toutes les
conversations en cours hors de l'Atelier ; il partagerait aussi la boucle
d'événements d'un service qui a d'autres charges. Seul, il ne dépend que de
httpx et d'uvicorn, démarre en une seconde, et l'Atelier le relance s'il
manque (`assurer_le_relais`).

Ce qu'il ne fait jamais : journaliser un contenu, une clé ou un en-tête ;
écouter ailleurs qu'en 127.0.0.1. Les en-têtes d'authentification passent tels
quels : le relais n'a aucun secret à lui.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from mcp_gateway.atelier.config import AtelierSettings, fenetre_du_modele, get_settings

log = logging.getLogger("atelier.relais_llm")

HOTE = "127.0.0.1"
CHEMIN_SANTE = "/_relais/sante"

# Ce qui ne traverse pas un relais : les en-têtes de la connexion elle-même.
# `accept-encoding` aussi : on lit le flux pour le corriger, il doit arriver
# en clair.
_ECARTES_REQUETE = frozenset(
    {
        "host",
        "content-length",
        "accept-encoding",
        "connection",
        "keep-alive",
        "proxy-connection",
        "transfer-encoding",
        "te",
        "trailer",
        "upgrade",
    }
)
_ECARTES_REPONSE = frozenset(
    {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive"}
)

_DEPASSEMENT = "ContextWindowExceeded"
_MAXIMUM = re.compile(r"maximum context length is (\d+)")
_TOTAL = re.compile(r"total of at least (\d+)")
_ENTREE = re.compile(r"at least (\d+) input tokens")


# -- estimation ---------------------------------------------------------


def caracteres_de_la_requete(corps: dict[str, Any]) -> int:
    """Ce que pèse une requête : consigne, outils et messages, en caractères.

    Le JSON plutôt que le seul texte : les blocs d'outils sont du JSON, et le
    modèle les lit comme tels. Même mesure que le prototype, qui l'a comparée
    à l'usage exact d'appels non streamés.
    """
    n = 0
    systeme = corps.get("system")
    if systeme:
        n += len(json.dumps(systeme, ensure_ascii=False))
    n += len(json.dumps(corps.get("tools") or [], ensure_ascii=False))
    n += len(json.dumps(corps.get("messages") or [], ensure_ascii=False))
    return n


def estimer(caracteres: int, ratio: float) -> int:
    if caracteres <= 0:
        return 0
    return max(1, int(caracteres / (ratio if ratio > 0 else 3.4)))


def _caracteres_du_delta(delta: dict[str, Any]) -> int:
    n = 0
    for champ in ("text", "partial_json", "thinking"):
        valeur = delta.get(champ)
        if isinstance(valeur, str):
            n += len(valeur)
    return n


def _caracteres_du_contenu(contenu: Any) -> int:
    if not isinstance(contenu, list):
        return 0
    n = 0
    for bloc in contenu:
        if not isinstance(bloc, dict):
            continue
        for champ in ("text", "thinking"):
            if isinstance(bloc.get(champ), str):
                n += len(bloc[champ])
        if "input" in bloc:
            n += len(json.dumps(bloc["input"], ensure_ascii=False))
    return n


# -- l'erreur de fenêtre --------------------------------------------------


def erreur_trop_long(texte: str, fenetre: int) -> dict[str, Any] | None:
    """L'erreur de litellm dans les mots de l'API Anthropic, ou rien.

    Claude Code reconnaît « prompt is too long: N tokens > M maximum » et
    compacte alors de lui-même. N doit dépasser M : litellm compte la sortie
    demandée dans le total (122 881 d'entrée + 8 192 de sortie = 131 073),
    c'est ce total qu'on rapporte quand il est dit.
    """
    if _DEPASSEMENT not in texte:
        return None
    m = _MAXIMUM.search(texte)
    maximum = int(m.group(1)) if m else fenetre
    total = _TOTAL.search(texte)
    entree = _ENTREE.search(texte)
    n = int(total.group(1)) if total else (int(entree.group(1)) if entree else maximum + 1)
    if n <= maximum:
        n = maximum + 1
    return {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": f"prompt is too long: {n} tokens > {maximum} maximum",
        },
    }


# -- correction du flux ----------------------------------------------------


class CorrecteurDuFlux:
    """Corrige, ligne à ligne, l'usage d'un flux SSE `/v1/messages`.

    Rien n'est retenu : chaque ligne sort dès qu'elle est lue. Seules deux
    lignes changent — `message_start` et `message_delta` — et seulement quand
    l'amont y a mis zéro. Un amont qui se met un jour à compter reprend la
    main sans qu'on touche à rien.
    """

    def __init__(self, entree_estimee: int, ratio: float, fenetre: int) -> None:
        self.entree_estimee = entree_estimee
        self.ratio = ratio
        self.fenetre = fenetre
        self.entree_rapportee = entree_estimee
        self.caracteres_sortie = 0
        self.corrige = False

    def ligne(self, ligne: str) -> str:
        if not ligne.startswith("data:"):
            return ligne
        charge = ligne[5:].strip()
        if not charge.startswith("{"):
            return ligne
        try:
            ev = json.loads(charge)
        except json.JSONDecodeError:
            return ligne
        if not isinstance(ev, dict):
            return ligne
        genre = ev.get("type")
        if genre == "content_block_delta":
            delta = ev.get("delta")
            if isinstance(delta, dict):
                self.caracteres_sortie += _caracteres_du_delta(delta)
            return ligne
        if genre == "content_block_start":
            bloc = ev.get("content_block")
            if isinstance(bloc, dict):
                self.caracteres_sortie += _caracteres_du_contenu([bloc]) if bloc.get("text") else 0
            return ligne
        if genre == "message_start":
            message = ev.get("message")
            if not isinstance(message, dict):
                return ligne
            usage = dict(message.get("usage") or {})
            if not usage.get("input_tokens"):
                usage["input_tokens"] = self.entree_estimee
                self.corrige = True
            if not usage.get("output_tokens"):
                usage["output_tokens"] = 1
            self.entree_rapportee = int(usage["input_tokens"] or 0)
            message["usage"] = usage
            return "data: " + json.dumps(ev, ensure_ascii=False)
        if genre == "message_delta":
            usage = dict(ev.get("usage") or {})
            if not usage.get("input_tokens"):
                usage["input_tokens"] = self.entree_rapportee
                self.corrige = True
            if not usage.get("output_tokens"):
                usage["output_tokens"] = max(1, estimer(self.caracteres_sortie, self.ratio))
                self.corrige = True
            ev["usage"] = usage
            return "data: " + json.dumps(ev, ensure_ascii=False)
        if genre == "error":
            texte = json.dumps(ev, ensure_ascii=False)
            reecrite = erreur_trop_long(texte, self.fenetre)
            if reecrite is not None:
                return "data: " + json.dumps(reecrite, ensure_ascii=False)
        return ligne


def corriger_reponse_entiere(
    corps: dict[str, Any], entree_estimee: int, ratio: float
) -> dict[str, Any]:
    """Même correction pour une réponse non streamée (exacte en pratique)."""
    usage = dict(corps.get("usage") or {})
    if not usage.get("input_tokens"):
        usage["input_tokens"] = entree_estimee
    if not usage.get("output_tokens"):
        usage["output_tokens"] = max(1, estimer(_caracteres_du_contenu(corps.get("content")), ratio))
    corps["usage"] = usage
    return corps


# -- l'application ASGI ----------------------------------------------------

Envoyer = Callable[[dict[str, Any]], Awaitable[None]]


def _entetes_pour_l_amont(scope: dict[str, Any]) -> list[tuple[str, str]]:
    sortie: list[tuple[str, str]] = []
    for cle, valeur in scope.get("headers") or []:
        nom = cle.decode("latin-1")
        if nom.lower() in _ECARTES_REQUETE:
            continue
        sortie.append((nom, valeur.decode("latin-1")))
    sortie.append(("accept-encoding", "identity"))
    return sortie


def _entetes_pour_le_client(reponse: httpx.Response) -> list[tuple[bytes, bytes]]:
    return [
        (k.encode("latin-1"), v.encode("latin-1"))
        for k, v in reponse.headers.multi_items()
        if k.lower() not in _ECARTES_REPONSE
    ]


async def _repondre_json(send: Envoyer, statut: int, corps: dict[str, Any], entetes=()) -> None:
    donnees = json.dumps(corps, ensure_ascii=False).encode("utf-8")
    liste = [(k, v) for k, v in entetes if k.lower() not in (b"content-type", b"content-length")]
    liste += [(b"content-type", b"application/json"), (b"content-length", str(len(donnees)).encode())]
    await send({"type": "http.response.start", "status": statut, "headers": liste})
    await send({"type": "http.response.body", "body": donnees})


class RelaisLLM:
    """Application ASGI du relais. `amont` : la base de la passerelle (…/api)."""

    def __init__(
        self,
        amont: str,
        *,
        ratio: float = 3.4,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.amont = amont.rstrip("/")
        self.ratio = ratio
        self._client = client

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            # Pas d'échéance de lecture courte : un tour de raisonnement peut
            # se taire longtemps avant son premier jeton.
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(connect=30.0, read=900.0, write=120.0, pool=30.0),
                follow_redirects=False,
            )
        return self._client

    async def fermer(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Envoyer) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await self.fermer()
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            return
        corps = b""
        while True:
            message = await receive()
            corps += message.get("body", b"")
            if not message.get("more_body"):
                break
        await self.relayer(scope, corps, send)

    async def relayer(self, scope: dict[str, Any], brut: bytes, send: Envoyer) -> None:
        methode = scope.get("method", "GET")
        chemin = scope.get("path", "/")
        requete = scope.get("query_string", b"").decode("latin-1")
        debut = time.monotonic()

        if chemin == CHEMIN_SANTE:
            await _repondre_json(send, 200, {"ok": True, "amont": self.amont})
            return

        messages = methode == "POST" and chemin.rstrip("/") in ("/v1/messages", "/v1/messages/count_tokens")
        corps: dict[str, Any] = {}
        if messages:
            try:
                charge = json.loads(brut or b"{}")
                corps = charge if isinstance(charge, dict) else {}
            except (json.JSONDecodeError, UnicodeDecodeError):
                corps = {}
        entree = estimer(caracteres_de_la_requete(corps), self.ratio) if messages else 0
        modele = str(corps.get("model") or "")
        fenetre = fenetre_du_modele(modele)

        if messages and chemin.rstrip("/").endswith("/count_tokens"):
            # L'amont répond 404 ; Claude Code se rabat alors sur sa propre
            # estimation, bien plus basse. Mieux vaut la nôtre, cohérente
            # avec l'usage qu'on rapporte en flux.
            await _repondre_json(send, 200, {"input_tokens": entree})
            self._noter(methode, chemin, modele, None, 200, entree, None, debut)
            return

        url = self.amont + chemin + (f"?{requete}" if requete else "")
        try:
            demande = self.client.build_request(
                methode, url, headers=_entetes_pour_l_amont(scope), content=brut
            )
            reponse = await self.client.send(demande, stream=True)
        except httpx.HTTPError as exc:
            log.warning("amont injoignable : %s", type(exc).__name__)
            await _repondre_json(
                send,
                502,
                {"type": "error", "error": {"type": "api_error", "message": "relais LLM : passerelle injoignable"}},
            )
            return

        try:
            type_contenu = reponse.headers.get("content-type", "")
            if messages and "event-stream" in type_contenu:
                sortie = await self._flux(reponse, send, entree, fenetre)
                self._noter(methode, chemin, modele, True, reponse.status_code, entree, sortie, debut)
            elif messages:
                await self._entier(reponse, send, corps, entree, fenetre)
                self._noter(methode, chemin, modele, False, reponse.status_code, entree, None, debut)
            else:
                await self._transparent(reponse, send)
        finally:
            await reponse.aclose()

    async def _flux(
        self, reponse: httpx.Response, send: Envoyer, entree: int, fenetre: int
    ) -> int:
        correcteur = CorrecteurDuFlux(entree, self.ratio, fenetre)
        await send(
            {
                "type": "http.response.start",
                "status": reponse.status_code,
                "headers": _entetes_pour_le_client(reponse),
            }
        )
        # Ligne à ligne, envoyée dès qu'elle est lue : aucun tampon au-delà
        # d'une ligne, le texte arrive au CLI au même rythme qu'à nous.
        async for ligne in reponse.aiter_lines():
            await send(
                {
                    "type": "http.response.body",
                    "body": (correcteur.ligne(ligne) + "\n").encode("utf-8"),
                    "more_body": True,
                }
            )
        await send({"type": "http.response.body", "body": b""})
        return estimer(correcteur.caracteres_sortie, self.ratio)

    async def _entier(
        self,
        reponse: httpx.Response,
        send: Envoyer,
        corps_requete: dict[str, Any],
        entree: int,
        fenetre: int,
    ) -> None:
        donnees = await reponse.aread()
        entetes = _entetes_pour_le_client(reponse)
        if reponse.status_code >= 400:
            texte = donnees.decode("utf-8", "replace")
            reecrite = erreur_trop_long(texte, fenetre)
            if reecrite is not None:
                await _repondre_json(send, 400, reecrite, entetes)
                return
        elif reponse.status_code == 200 and not corps_requete.get("stream"):
            try:
                charge = json.loads(donnees)
            except (json.JSONDecodeError, UnicodeDecodeError):
                charge = None
            if isinstance(charge, dict) and charge.get("type") == "message":
                await _repondre_json(send, 200, corriger_reponse_entiere(charge, entree, self.ratio), entetes)
                return
        entetes = [(k, v) for k, v in entetes] + [(b"content-length", str(len(donnees)).encode())]
        await send({"type": "http.response.start", "status": reponse.status_code, "headers": entetes})
        await send({"type": "http.response.body", "body": donnees})

    async def _transparent(self, reponse: httpx.Response, send: Envoyer) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": reponse.status_code,
                "headers": _entetes_pour_le_client(reponse),
            }
        )
        async for morceau in reponse.aiter_bytes():
            await send({"type": "http.response.body", "body": morceau, "more_body": True})
        await send({"type": "http.response.body", "body": b""})

    @staticmethod
    def _noter(
        methode: str,
        chemin: str,
        modele: str,
        flux: bool | None,
        statut: int,
        entree: int,
        sortie: int | None,
        debut: float,
    ) -> None:
        # Des nombres et un nom de modèle, jamais un contenu ni un en-tête.
        log.info(
            "%s %s modele=%s flux=%s statut=%s entree~%s sortie~%s %.1fs",
            methode,
            chemin,
            modele or "-",
            "-" if flux is None else int(flux),
            statut,
            entree,
            "-" if sortie is None else sortie,
            time.monotonic() - debut,
        )


# -- côté Atelier : savoir s'il répond, le lancer s'il manque --------------


def adresse_du_relais(settings: AtelierSettings) -> str:
    return f"http://{HOTE}:{settings.relais_llm_port}"


_SONDE: dict[int, tuple[float, bool]] = {}
_SONDE_DUREE = 5.0


def relais_en_service(settings: AtelierSettings, *, delai: float = 0.3) -> bool:
    """Vrai si le relais est voulu et qu'il écoute. Sondé au plus toutes les 5 s."""
    if not settings.relais_llm:
        return False
    port = settings.relais_llm_port
    maintenant = time.monotonic()
    deja = _SONDE.get(port)
    if deja is not None and maintenant - deja[0] < _SONDE_DUREE:
        return deja[1]
    try:
        with socket.create_connection((HOTE, port), timeout=delai):
            ok = True
    except OSError:
        ok = False
    _SONDE[port] = (maintenant, ok)
    return ok


def oublier_la_sonde() -> None:
    _SONDE.clear()


def base_url_des_tours(settings: AtelierSettings) -> str:
    """L'adresse que les tours donnent au CLI : le relais s'il répond, sinon l'amont."""
    if relais_en_service(settings):
        return adresse_du_relais(settings)
    return settings.anthropic_base_url.strip()


def assurer_le_relais(settings: AtelierSettings, *, attente: float = 3.0) -> bool:
    """Lance le relais s'il ne répond pas. Vrai s'il répond au retour.

    Détaché de l'Atelier (nouvelle session) : il doit survivre à ses
    redémarrages, puisque VS Code et le terminal passent par lui.
    """
    if not settings.relais_llm:
        return False
    oublier_la_sonde()
    if relais_en_service(settings):
        return True
    journal = settings.work_dir / "logs" / "relais-llm.log"
    journal.parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, Any] = {}
    if os.name == "posix":
        options["start_new_session"] = True
    with journal.open("ab") as sortie:
        subprocess.Popen(  # noqa: S603 — notre propre module, sans shell
            [sys.executable, "-m", "mcp_gateway.atelier.relais_llm"],
            stdin=subprocess.DEVNULL,
            stdout=sortie,
            stderr=subprocess.STDOUT,
            cwd=str(Path(__file__).resolve().parents[2]),
            **options,
        )
    fin = time.monotonic() + attente
    while time.monotonic() < fin:
        oublier_la_sonde()
        if relais_en_service(settings):
            return True
        time.sleep(0.2)
    return False


def main() -> None:
    settings = get_settings()
    parser = argparse.ArgumentParser(description="Relais LLM de l'Atelier (boucle locale)")
    parser.add_argument("--port", type=int, default=settings.relais_llm_port)
    parser.add_argument("--amont", default=settings.anthropic_base_url)
    parser.add_argument("--ratio", type=float, default=settings.relais_llm_ratio)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import uvicorn

    # Boucle locale seulement, sans option pour en sortir : le relais porte
    # les clés des appelants vers la passerelle.
    uvicorn.run(
        RelaisLLM(args.amont, ratio=args.ratio),
        host=HOTE,
        port=args.port,
        log_level="warning",
        access_log=False,
    )


if __name__ == "__main__":
    main()
