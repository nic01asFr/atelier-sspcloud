"""Le relais LLM, éprouvé contre un amont qui répond comme la passerelle.

L'amont factice rejoue ce qui a été mesuré le 25 septembre 2026 sur
https://llm.lab.sspcloud.fr/api : un flux `/v1/messages` dont l'usage vaut
zéro, un 404 sur `count_tokens`, et le 400 de litellm au-delà de la fenêtre.
Les deux serveurs sont réels (sockets, HTTP), en boucle locale.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Iterator

import httpx
import pytest
import uvicorn

from mcp_gateway.atelier import relais_llm
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.relais_llm import (
    CorrecteurDuFlux,
    RelaisLLM,
    caracteres_de_la_requete,
    erreur_trop_long,
)

# Le corps exact de l'erreur relevée sur la passerelle (tronqué comme elle).
ERREUR_LITELLM = (
    "litellm.ContextWindowExceededError: litellm.BadRequestError: "
    "ContextWindowExceededError: OpenAIException - This model's maximum context "
    "length is 131072 tokens. However, you requested 8192 output tokens and your "
    "prompt contains at least 122881 input tokens, for a total of at least 131073 "
    "tokens. Please reduce the length of the input prompt or the number of "
    "requested output tokens."
)


def _flux_mesure() -> list[dict[str, Any]]:
    """Un flux tel que la passerelle le rend : usage à zéro partout."""
    return [
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "qwen3-6-35b-moe",
                "content": [],
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "a" * 340}},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"input_tokens": 0, "output_tokens": 0},
        },
        {"type": "message_stop"},
    ]


class Amont:
    """La passerelle factice. Retient ce qu'on lui a envoyé."""

    def __init__(self) -> None:
        self.recus: list[dict[str, Any]] = []
        self.liberer = threading.Event()
        self.attendre_apres_le_debut = False
        amont = self

        class Gestionnaire(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a: Any) -> None:
                pass

            def _noter(self, corps: bytes) -> dict[str, Any]:
                try:
                    charge = json.loads(corps or b"{}")
                except json.JSONDecodeError:
                    charge = {}
                entree = {
                    "chemin": self.path,
                    "methode": self.command,
                    "entetes": {k.lower(): v for k, v in self.headers.items()},
                    "corps": charge,
                }
                amont.recus.append(entree)
                return charge

            def _json(self, statut: int, corps: Any) -> None:
                donnees = json.dumps(corps).encode()
                self.send_response(statut)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def do_GET(self) -> None:
                self._noter(b"")
                if self.path.startswith("/api/v1/models"):
                    self._json(200, {"data": [{"id": "qwen3-6-35b-moe"}]})
                else:
                    self._json(404, {"detail": {"detail": "Not Found"}})

            def do_POST(self) -> None:
                corps = self.rfile.read(int(self.headers.get("content-length", 0)))
                charge = self._noter(corps)
                if self.path.startswith("/api/v1/messages/count_tokens"):
                    self._json(404, {"detail": {"detail": "Not Found"}})
                    return
                if not self.path.startswith("/api/v1/messages"):
                    self._json(404, {"detail": "Not Found"})
                    return
                if "DEBORDE" in json.dumps(charge):
                    self._json(400, {"detail": ERREUR_LITELLM})
                    return
                if not charge.get("stream"):
                    self._json(
                        200,
                        {
                            "id": "msg_2",
                            "type": "message",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "b" * 68}],
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        },
                    )
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream; charset=utf-8")
                self.send_header("cache-control", "no-cache")
                self.send_header("connection", "close")
                self.end_headers()
                for i, ev in enumerate(_flux_mesure()):
                    self.wfile.write(f"event: {ev['type']}\ndata: {json.dumps(ev)}\n\n".encode())
                    self.wfile.flush()
                    if i == 0 and amont.attendre_apres_le_debut:
                        amont.liberer.wait(timeout=10)
                self.close_connection = True

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    @property
    def base(self) -> str:
        return f"http://127.0.0.1:{self.port}/api"

    def fermer(self) -> None:
        self.liberer.set()
        self.serveur.shutdown()


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture()
def amont() -> Iterator[Amont]:
    a = Amont()
    yield a
    a.fermer()


@pytest.fixture()
def relais(amont: Amont) -> Iterator[str]:
    port = _port_libre()
    serveur = uvicorn.Server(
        uvicorn.Config(
            RelaisLLM(amont.base, ratio=3.4), host="127.0.0.1", port=port, log_level="warning"
        )
    )
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    fin = time.monotonic() + 10
    while not serveur.started and time.monotonic() < fin:
        time.sleep(0.05)
    assert serveur.started
    yield f"http://127.0.0.1:{port}"
    serveur.should_exit = True
    fil.join(timeout=10)


def _requete(texte: str = "bonjour", stream: bool = True) -> dict[str, Any]:
    return {
        "model": "qwen3-6-35b-moe",
        "max_tokens": 8192,
        "stream": stream,
        "system": [{"type": "text", "text": "tu es un agent"}],
        "tools": [{"name": "Read", "input_schema": {"type": "object"}}],
        "messages": [{"role": "user", "content": texte}],
    }


def _evenements(texte: str) -> list[dict[str, Any]]:
    return [
        json.loads(l[5:].strip())
        for l in texte.splitlines()
        if l.startswith("data:") and l[5:].strip().startswith("{")
    ]


def test_l_usage_nul_du_flux_est_rempli(relais: str) -> None:
    corps = _requete("x" * 3400)
    attendu = int(caracteres_de_la_requete(corps) / 3.4)
    r = httpx.post(relais + "/v1/messages?beta=true", json=corps, timeout=10)
    assert r.status_code == 200
    evs = _evenements(r.text)
    debut = next(e for e in evs if e["type"] == "message_start")
    delta = next(e for e in evs if e["type"] == "message_delta")
    assert debut["message"]["usage"]["input_tokens"] == attendu
    assert delta["usage"]["input_tokens"] == attendu
    # 340 caractères de texte produits, divisés par 3,4.
    assert delta["usage"]["output_tokens"] == 100
    # Le reste du flux passe intact, dans l'ordre.
    assert [e["type"] for e in evs] == [e["type"] for e in _flux_mesure()]
    assert "event: message_start" in r.text


def test_le_flux_n_est_pas_retenu(relais: str, amont: Amont) -> None:
    """La première ligne arrive avant que l'amont ait fini : aucun tampon."""
    amont.attendre_apres_le_debut = True
    lu_avant_la_fin = False
    with httpx.stream("POST", relais + "/v1/messages", json=_requete(), timeout=15) as r:
        for ligne in r.iter_lines():
            if ligne.startswith("data:") and "message_start" in ligne:
                # L'amont est encore bloqué : s'il y avait un tampon, on ne
                # lirait rien avant la fin.
                lu_avant_la_fin = not amont.liberer.is_set()
                amont.liberer.set()
    assert lu_avant_la_fin


def test_l_erreur_de_fenetre_devient_prompt_too_long(relais: str) -> None:
    r = httpx.post(relais + "/v1/messages", json=_requete("DEBORDE"), timeout=10)
    assert r.status_code == 400
    assert r.json() == {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": "prompt is too long: 131073 tokens > 131072 maximum",
        },
    }


def test_count_tokens_repond_par_l_estimation(relais: str, amont: Amont) -> None:
    corps = _requete("y" * 680, stream=False)
    corps.pop("stream")
    r = httpx.post(relais + "/v1/messages/count_tokens?beta=true", json=corps, timeout=10)
    assert r.status_code == 200
    assert r.json() == {"input_tokens": int(caracteres_de_la_requete(corps) / 3.4)}
    assert not [x for x in amont.recus if "count_tokens" in x["chemin"]], "l'amont répond 404 : inutile d'y aller"


def test_une_reponse_non_streamee_est_completee(relais: str) -> None:
    corps = _requete("z" * 34, stream=False)
    r = httpx.post(relais + "/v1/messages", json=corps, timeout=10)
    usage = r.json()["usage"]
    assert usage["input_tokens"] == int(caracteres_de_la_requete(corps) / 3.4)
    assert usage["output_tokens"] == 20


def test_le_reste_passe_tel_quel(relais: str) -> None:
    r = httpx.get(relais + "/v1/models", timeout=10)
    assert r.status_code == 200 and r.json()["data"][0]["id"] == "qwen3-6-35b-moe"
    r = httpx.post(relais + "/v1/autre", json={}, timeout=10)
    assert r.status_code == 404


def test_l_authentification_passe_telle_quelle(relais: str, amont: Amont) -> None:
    httpx.post(
        relais + "/v1/messages",
        json=_requete(),
        headers={"x-api-key": "cle-de-l-appelant", "authorization": "Bearer cle-de-l-appelant"},
        timeout=10,
    )
    recu = [x for x in amont.recus if x["chemin"].startswith("/api/v1/messages")][-1]
    assert recu["entetes"]["x-api-key"] == "cle-de-l-appelant"
    assert recu["entetes"]["authorization"] == "Bearer cle-de-l-appelant"
    assert recu["corps"] == _requete(), "le corps part intact"


def test_le_journal_ne_porte_ni_contenu_ni_cle(relais: str, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG, logger="atelier.relais_llm")
    httpx.post(
        relais + "/v1/messages",
        json=_requete("CONTENU-CONFIDENTIEL"),
        headers={"x-api-key": "CLE-SECRETE"},
        timeout=10,
    )
    texte = "\n".join(r.getMessage() for r in caplog.records)
    assert "CONTENU-CONFIDENTIEL" not in texte
    assert "CLE-SECRETE" not in texte
    assert "/v1/messages" in texte, "le journal dit quand même ce qui est passé"


def test_un_amont_qui_compte_garde_la_main() -> None:
    """Si la passerelle se met à compter, ses chiffres priment sur les nôtres."""
    c = CorrecteurDuFlux(500, 3.4, 131072)
    debut = {"type": "message_start", "message": {"usage": {"input_tokens": 42, "output_tokens": 3}}}
    assert json.loads(c.ligne("data: " + json.dumps(debut))[5:])["message"]["usage"]["input_tokens"] == 42
    delta = {"type": "message_delta", "usage": {"output_tokens": 7}}
    usage = json.loads(c.ligne("data: " + json.dumps(delta))[5:])["usage"]
    assert usage == {"output_tokens": 7, "input_tokens": 42}


def test_l_erreur_sans_total_depasse_quand_meme_le_maximum() -> None:
    texte = "ContextWindowExceededError: maximum context length is 131072 tokens"
    message = erreur_trop_long(texte, 131072)["error"]["message"]
    assert message == "prompt is too long: 131073 tokens > 131072 maximum"
    assert erreur_trop_long("autre erreur", 131072) is None


def test_la_base_des_tours_suit_la_presence_du_relais(reglages: AtelierSettings, monkeypatch) -> None:
    monkeypatch.setattr(relais_llm, "relais_en_service", lambda s, **k: True)
    assert relais_llm.base_url_des_tours(reglages) == f"http://127.0.0.1:{reglages.relais_llm_port}"
    monkeypatch.setattr(relais_llm, "relais_en_service", lambda s, **k: False)
    assert relais_llm.base_url_des_tours(reglages) == reglages.anthropic_base_url


def test_la_sonde_trouve_un_relais_qui_ecoute(reglages: AtelierSettings, relais: str) -> None:
    reglages.relais_llm_port = int(relais.rsplit(":", 1)[1])
    relais_llm.oublier_la_sonde()
    assert relais_llm.relais_en_service(reglages)
    reglages.relais_llm = False
    assert not relais_llm.relais_en_service(reglages), "désactivé, il n'est jamais pris"
    relais_llm.oublier_la_sonde()


def test_la_sante_repond_sans_aller_a_l_amont(relais: str, amont: Amont) -> None:
    r = httpx.get(relais + relais_llm.CHEMIN_SANTE, timeout=5)
    assert r.json()["ok"] is True
    assert not amont.recus


def test_une_liste_d_outils_vide_ne_part_pas(relais: str, amont: Amont) -> None:
    """WebFetch appelle le petit modèle avec `"tools": []`, que litellm refuse
    (400 « `tools` must not be an empty array », mesuré le 25 septembre) : le
    relais retire la liste vide, et `tool_choice` avec elle."""
    corps = {**_requete(stream=False), "tools": [], "tool_choice": {"type": "auto"}}
    r = httpx.post(relais + "/v1/messages", json=corps, timeout=10)
    assert r.status_code == 200
    recu = [x for x in amont.recus if x["chemin"].startswith("/api/v1/messages")][-1]
    assert "tools" not in recu["corps"] and "tool_choice" not in recu["corps"]
    assert recu["corps"]["messages"] == corps["messages"]


def test_une_liste_d_outils_pleine_part_intacte(relais: str, amont: Amont) -> None:
    outil = {"name": "lire", "description": "", "input_schema": {"type": "object"}}
    corps = {**_requete(stream=False), "tools": [outil]}
    httpx.post(relais + "/v1/messages", json=corps, timeout=10)
    recu = [x for x in amont.recus if x["chemin"].startswith("/api/v1/messages")][-1]
    assert recu["corps"]["tools"] == [outil]
