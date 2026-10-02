"""Un fournisseur OpenAI (Albert) derrière le relais : traduction et routage."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from mcp_gateway.atelier.fournisseurs import Fournisseur, charger_fournisseurs, fournisseur_du_modele
from mcp_gateway.atelier.relais_llm import RelaisLLM
from mcp_gateway.atelier.traduction_openai import (
    TraducteurDeFlux,
    reponse_vers_anthropic,
    vers_openai,
)

ALBERT = Fournisseur("albert", "Albert API", "https://albert.exemple/v1", "cle-albert")


# -- requête ---------------------------------------------------------------


def test_une_conversation_avec_outils_est_traduite() -> None:
    corps = {
        "model": "albert/deepseek",
        "max_tokens": 100,
        "stop_sequences": ["FIN"],
        "system": [{"type": "text", "text": "Sois bref."}],
        "tools": [{"name": "lire", "description": "lit", "input_schema": {"type": "object", "properties": {"p": {"type": "string"}}}}],
        "tool_choice": {"type": "any"},
        "messages": [
            {"role": "user", "content": "lis a.txt"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "hm", "signature": "x"},
                    {"type": "text", "text": "je lis"},
                    {"type": "tool_use", "id": "t1", "name": "lire", "input": {"p": "a.txt"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t1", "content": [{"type": "text", "text": "contenu"}]},
                    {"type": "text", "text": "et ensuite ?"},
                ],
            },
        ],
    }
    sortie = vers_openai(corps, "deepseek")
    assert sortie["model"] == "deepseek" and sortie["max_tokens"] == 100 and sortie["stop"] == ["FIN"]
    assert sortie["tool_choice"] == "required"
    assert sortie["tools"][0]["function"]["parameters"]["properties"]["p"] == {"type": "string"}
    roles = [m["role"] for m in sortie["messages"]]
    assert roles == ["system", "user", "assistant", "tool", "user"]
    assert sortie["messages"][0]["content"] == "Sois bref."
    assistant = sortie["messages"][2]
    assert assistant["content"] == "je lis"  # le raisonnement ne repart pas
    assert assistant["tool_calls"][0]["function"] == {"name": "lire", "arguments": '{"p": "a.txt"}'}
    assert sortie["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": "contenu"}
    assert "stream" not in sortie


def test_les_outils_vides_et_le_flux() -> None:
    sortie = vers_openai({"messages": [], "tools": [], "tool_choice": {"type": "auto"}, "stream": True}, "m")
    assert "tools" not in sortie and "tool_choice" not in sortie
    assert sortie["stream"] is True and sortie["stream_options"] == {"include_usage": True}


def test_une_image_et_une_erreur_d_outil() -> None:
    corps = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "t", "content": "boum", "is_error": True},
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}},
                ],
            }
        ]
    }
    messages = vers_openai(corps, "m")["messages"]
    assert messages[0]["content"] == "Erreur : boum"
    assert messages[1]["content"][0]["image_url"]["url"] == "data:image/png;base64,AAAA"


# -- réponse entière ---------------------------------------------------------


def test_une_reponse_avec_appel_d_outil() -> None:
    donnees = {
        "id": "c1",
        "choices": [
            {
                "finish_reason": "tool_calls",
                "message": {
                    "content": "voilà",
                    "reasoning_content": "je réfléchis",
                    "tool_calls": [{"id": "t1", "function": {"name": "lire", "arguments": '{"p": "x"}'}}],
                },
            }
        ],
        "usage": {"prompt_tokens": 12, "completion_tokens": 7},
    }
    m = reponse_vers_anthropic(donnees, "albert/d")
    assert [b["type"] for b in m["content"]] == ["thinking", "text", "tool_use"]
    assert m["content"][2]["input"] == {"p": "x"} and m["stop_reason"] == "tool_use"
    assert m["usage"] == {"input_tokens": 12, "output_tokens": 7} and m["model"] == "albert/d"


def test_des_arguments_illisibles_ne_cassent_rien() -> None:
    donnees = {"choices": [{"message": {"tool_calls": [{"id": "t", "function": {"name": "n", "arguments": "{pas"}}]}}]}
    assert reponse_vers_anthropic(donnees, "m")["content"][0]["input"] == {}


# -- flux ------------------------------------------------------------------


def _rejouer(lignes: list[str]) -> list[dict[str, Any]]:
    t = TraducteurDeFlux("albert/d")
    sortie: list[dict[str, Any]] = []
    for ligne in lignes:
        sortie += t.ligne(ligne)
    return sortie + t.fin()


def _data(**kw: Any) -> str:
    return "data: " + json.dumps(kw)


def test_un_flux_de_texte() -> None:
    ev = _rejouer(
        [
            _data(choices=[{"delta": {"role": "assistant", "content": ""}}]),
            _data(choices=[{"delta": {"content": "Bon"}}]),
            _data(choices=[{"delta": {"content": "jour"}, "finish_reason": "stop"}]),
            _data(choices=[], usage={"prompt_tokens": 5, "completion_tokens": 2}),
            "data: [DONE]",
        ]
    )
    assert [e["type"] for e in ev] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert "".join(e["delta"]["text"] for e in ev if e["type"] == "content_block_delta") == "Bonjour"
    assert ev[-2]["delta"]["stop_reason"] == "end_turn"
    assert ev[-2]["usage"] == {"input_tokens": 5, "output_tokens": 2}


def test_un_flux_avec_raisonnement_puis_deux_outils() -> None:
    ev = _rejouer(
        [
            _data(choices=[{"delta": {"reasoning_content": "hm"}}]),
            _data(choices=[{"delta": {"content": "je lis"}}]),
            _data(choices=[{"delta": {"tool_calls": [{"index": 0, "id": "a", "function": {"name": "lire", "arguments": '{"p"'}}]}}]),
            _data(choices=[{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": ': "x"}'}}]}}]),
            _data(choices=[{"delta": {"tool_calls": [{"index": 1, "id": "b", "function": {"name": "ecrire", "arguments": "{}"}}]}}]),
            _data(choices=[{"delta": {}, "finish_reason": "tool_calls"}]),
        ]
    )
    debuts = [e["content_block"]["type"] for e in ev if e["type"] == "content_block_start"]
    assert debuts == ["thinking", "text", "tool_use", "tool_use"]
    json_premier = "".join(e["delta"]["partial_json"] for e in ev if e["type"] == "content_block_delta" and e["index"] == 2)
    assert json.loads(json_premier) == {"p": "x"}
    # Chaque bloc ouvert est fermé, dans l'ordre.
    assert [e["index"] for e in ev if e["type"] == "content_block_stop"] == [0, 1, 2, 3]
    assert ev[-2]["delta"]["stop_reason"] == "tool_use"


def test_un_flux_vide_ou_bruite_se_termine_proprement() -> None:
    ev = _rejouer([": keep-alive", "", "data: pas du json", "data: [DONE]"])
    assert [e["type"] for e in ev] == ["message_start", "message_delta", "message_stop"]


# -- fournisseurs ------------------------------------------------------------


def test_une_cle_suffit_pour_albert(reglages) -> None:
    assert charger_fournisseurs(reglages) == []
    reglages.secrets_dir.mkdir(parents=True, exist_ok=True)
    (reglages.secrets_dir / "albert_api_key").write_text("k\n", encoding="utf-8")
    (albert,) = charger_fournisseurs(reglages)
    assert albert.id == "albert" and albert.cle == "k" and albert.base_url.startswith("https://albert.")


def test_un_autre_fournisseur_declare_et_les_invalides_ecartes(reglages) -> None:
    d = reglages.secrets_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "fournisseurs.json").write_text(
        json.dumps(
            {
                "autre": {"nom": "Autre", "base_url": "https://autre.exemple/v1/"},
                "http": {"base_url": "http://clair.exemple/v1"},
                "Mauvais Nom": {"base_url": "https://x.exemple/v1"},
                "sanscle": {"base_url": "https://y.exemple/v1"},
            }
        ),
        encoding="utf-8",
    )
    for nom in ("autre", "http", "Mauvais Nom"):
        (d / f"{nom}_api_key").write_text("k", encoding="utf-8")
    assert [f.id for f in charger_fournisseurs(reglages)] == ["autre"]


def test_le_prefixe_designe_le_fournisseur() -> None:
    assert fournisseur_du_modele([ALBERT], "albert/deepseek") == (ALBERT, "deepseek")
    assert fournisseur_du_modele([ALBERT], "albert/") is None
    assert fournisseur_du_modele([ALBERT], "qwen3-6-35b-moe") is None


# -- le relais ---------------------------------------------------------------


def _appeler(relais: RelaisLLM, corps: dict[str, Any]) -> tuple[int, bytes, list[tuple[bytes, bytes]]]:
    envoyes: list[dict[str, Any]] = []

    async def send(m: dict[str, Any]) -> None:
        envoyes.append(m)

    scope = {"type": "http", "method": "POST", "path": "/v1/messages", "query_string": b"", "headers": [(b"x-api-key", b"cle-sspcloud")]}
    asyncio.run(relais.relayer(scope, json.dumps(corps).encode(), send))
    debut = next(m for m in envoyes if m["type"] == "http.response.start")
    return debut["status"], b"".join(m.get("body", b"") for m in envoyes if m["type"] == "http.response.body"), debut["headers"]


def _relais(reponse: httpx.Response | None = None, vus: list[httpx.Request] | None = None) -> RelaisLLM:
    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        if vus is not None:
            vus.append(requete)
        return reponse or httpx.Response(500)

    return RelaisLLM(
        "https://sspcloud.exemple/api",
        client=httpx.AsyncClient(transport=httpx.MockTransport(gestionnaire)),
        fournisseurs=lambda: [ALBERT],
    )


def test_un_modele_albert_va_chez_albert_avec_sa_cle() -> None:
    vus: list[httpx.Request] = []
    reponse = httpx.Response(200, json={"id": "c", "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}], "usage": {"prompt_tokens": 3, "completion_tokens": 1}})
    statut, corps, _ = _appeler(_relais(reponse, vus), {"model": "albert/deepseek", "max_tokens": 10, "messages": [{"role": "user", "content": "salut"}]})
    assert statut == 200
    message = json.loads(corps)
    assert message["type"] == "message" and message["content"][0]["text"] == "ok"
    (requete,) = vus
    assert str(requete.url) == "https://albert.exemple/v1/chat/completions"
    assert requete.headers["authorization"] == "Bearer cle-albert"
    assert b"cle-sspcloud" not in requete.content and "cle-sspcloud" not in str(requete.headers)
    assert json.loads(requete.content)["model"] == "deepseek"


def test_un_modele_sspcloud_ne_passe_pas_par_albert() -> None:
    vus: list[httpx.Request] = []
    reponse = httpx.Response(200, json={"type": "message", "content": [], "usage": {"input_tokens": 1, "output_tokens": 1}})
    _appeler(_relais(reponse, vus), {"model": "qwen3-6-35b-moe", "max_tokens": 5, "messages": [{"role": "user", "content": "x"}]})
    assert str(vus[0].url) == "https://sspcloud.exemple/api/v1/messages"
    assert vus[0].headers["x-api-key"] == "cle-sspcloud"


def test_le_flux_albert_sort_en_sse_anthropic() -> None:
    sse = "\n".join(
        [
            _data(choices=[{"delta": {"content": "Bon"}}]),
            "",
            _data(choices=[{"delta": {"content": "jour"}, "finish_reason": "stop"}]),
            "",
            "data: [DONE]",
            "",
        ]
    )
    reponse = httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})
    statut, corps, entetes = _appeler(_relais(reponse), {"model": "albert/d", "stream": True, "max_tokens": 5, "messages": [{"role": "user", "content": "x"}]})
    texte = corps.decode()
    assert statut == 200 and (b"content-type", b"text/event-stream") in entetes
    assert "event: message_start" in texte and "event: message_stop" in texte
    assert texte.count("text_delta") == 2
    # L'usage nul de l'amont est rempli, comme pour SSPCloud.
    delta = [json.loads(b[5:]) for b in texte.split("\n") if b.startswith("data:") and '"message_delta"' in b][0]
    assert delta["usage"]["input_tokens"] > 0 and delta["usage"]["output_tokens"] > 0


def test_une_erreur_albert_devient_une_erreur_anthropic() -> None:
    reponse = httpx.Response(401, json={"detail": "Invalid API key"})
    statut, corps, _ = _appeler(_relais(reponse), {"model": "albert/d", "max_tokens": 5, "messages": [{"role": "user", "content": "x"}]})
    erreur = json.loads(corps)
    assert statut == 401 and erreur["type"] == "error" and "Albert API" in erreur["error"]["message"]


def test_un_fournisseur_injoignable_donne_un_502() -> None:
    def coupe(requete: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("coupé")

    relais = RelaisLLM("https://s/api", client=httpx.AsyncClient(transport=httpx.MockTransport(coupe)), fournisseurs=lambda: [ALBERT])
    statut, corps, _ = _appeler(relais, {"model": "albert/d", "max_tokens": 5, "messages": []})
    assert statut == 502 and "injoignable" in json.loads(corps)["error"]["message"]


# -- modèles contraints (appels d'outils non analysés chez le fournisseur) ----

from mcp_gateway.atelier.traduction_openai import OUTIL_REPONDRE, flux_depuis_message  # noqa: E402

_OUTILS = [{"name": "lire", "description": "lit", "input_schema": {"type": "object", "properties": {}}}]


def test_un_modele_contraint_doit_toujours_appeler_un_outil() -> None:
    corps = {"system": "Sois bref.", "tools": _OUTILS, "stream": True, "messages": [{"role": "user", "content": "x"}]}
    sortie = vers_openai(corps, "m", contraint=True)
    assert sortie["tool_choice"] == "required"
    assert [o["function"]["name"] for o in sortie["tools"]] == ["lire", OUTIL_REPONDRE]
    assert OUTIL_REPONDRE in sortie["messages"][0]["content"] and sortie["messages"][0]["content"].startswith("Sois bref.")
    assert "stream" not in sortie  # la réponse entière est rejouée en flux


def test_la_contrainte_ne_touche_ni_l_absence_d_outils_ni_le_choix_de_l_appelant() -> None:
    sans = vers_openai({"messages": [], "stream": True}, "m", contraint=True)
    assert "tools" not in sans and sans["stream"] is True
    impose = vers_openai({"messages": [], "tools": _OUTILS, "tool_choice": {"type": "tool", "name": "lire"}}, "m", contraint=True)
    assert [o["function"]["name"] for o in impose["tools"]] == ["lire"]
    assert impose["tool_choice"] == {"type": "function", "function": {"name": "lire"}}


def test_repondre_redevient_du_texte_et_clot_le_tour() -> None:
    donnees = {"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"id": "t", "function": {"name": OUTIL_REPONDRE, "arguments": '{"texte": "Voilà."}'}}]}}]}
    m = reponse_vers_anthropic(donnees, "m")
    assert m["content"] == [{"type": "text", "text": "Voilà."}] and m["stop_reason"] == "end_turn"


def test_repondre_a_cote_d_un_vrai_outil_garde_le_tour_ouvert() -> None:
    appels = [
        {"id": "a", "function": {"name": OUTIL_REPONDRE, "arguments": "je lis"}},  # JSON oublié : on garde le texte
        {"id": "b", "function": {"name": "lire", "arguments": "{}"}},
    ]
    m = reponse_vers_anthropic({"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": appels}}]}, "m")
    assert [b["type"] for b in m["content"]] == ["text", "tool_use"] and m["content"][0]["text"] == "je lis"
    assert m["stop_reason"] == "tool_use"


def test_un_message_entier_se_rejoue_en_flux() -> None:
    message = reponse_vers_anthropic(
        {"choices": [{"finish_reason": "tool_calls", "message": {"content": "ok", "tool_calls": [{"id": "t", "function": {"name": "lire", "arguments": '{"p": 1}'}}]}}], "usage": {"prompt_tokens": 4, "completion_tokens": 3}},
        "m",
    )
    ev = flux_depuis_message(message)
    assert [e["type"] for e in ev if e["type"] != "content_block_delta"] == [
        "message_start", "content_block_start", "content_block_stop", "content_block_start", "content_block_stop", "message_delta", "message_stop",
    ]
    assert ev[-2]["delta"]["stop_reason"] == "tool_use" and ev[-2]["usage"]["output_tokens"] == 3
    delta_outil = [e for e in ev if e["type"] == "content_block_delta" and e["index"] == 1][0]["delta"]
    assert json.loads(delta_outil["partial_json"]) == {"p": 1}


def test_les_modeles_natifs_se_declarent(reglages) -> None:
    d = reglages.secrets_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "albert_api_key").write_text("k", encoding="utf-8")
    (albert,) = charger_fournisseurs(reglages)
    assert albert.outils_natifs == frozenset({"gpt-oss-120b"})


def test_relais_un_modele_contraint_est_appele_sans_flux_et_rejoue_en_flux() -> None:
    vus: list[httpx.Request] = []
    reponse = httpx.Response(200, json={"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"id": "t", "function": {"name": OUTIL_REPONDRE, "arguments": '{"texte": "Bonjour"}'}}]}}], "usage": {"prompt_tokens": 9, "completion_tokens": 4}})
    corps = {"model": "albert/deepseek", "stream": True, "max_tokens": 50, "tools": _OUTILS, "messages": [{"role": "user", "content": "salut"}]}
    statut, brut, entetes = _appeler(_relais(reponse, vus), corps)
    envoye = json.loads(vus[0].content)
    assert "stream" not in envoye and envoye["tool_choice"] == "required"
    assert statut == 200 and (b"content-type", b"text/event-stream") in entetes
    texte = brut.decode()
    assert '"text": "Bonjour"' in texte and "event: message_stop" in texte and '"end_turn"' in texte


def test_relais_un_modele_natif_garde_son_flux_direct() -> None:
    natif = Fournisseur("albert", "Albert API", "https://albert.exemple/v1", "cle-albert", frozenset({"gpt-oss"}))
    vus: list[httpx.Request] = []

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vus.append(requete)
        return httpx.Response(200, content=b"data: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    relais = RelaisLLM("https://s/api", client=httpx.AsyncClient(transport=httpx.MockTransport(gestionnaire)), fournisseurs=lambda: [natif])
    _appeler(relais, {"model": "albert/gpt-oss", "stream": True, "max_tokens": 5, "tools": _OUTILS, "messages": [{"role": "user", "content": "x"}]})
    envoye = json.loads(vus[0].content)
    assert envoye["stream"] is True and "tool_choice" not in envoye
    assert [o["function"]["name"] for o in envoye["tools"]] == ["lire"]


# -- le catalogue que Claude Code lit pour son sélecteur /model ---------------


def _lister(relais: RelaisLLM) -> tuple[int, dict[str, Any]]:
    envoyes: list[dict[str, Any]] = []

    async def send(m: dict[str, Any]) -> None:
        envoyes.append(m)

    scope = {"type": "http", "method": "GET", "path": "/v1/models", "query_string": b"", "headers": [(b"x-api-key", b"cle-sspcloud")]}
    asyncio.run(relais.relayer(scope, b"", send))
    debut = next(m for m in envoyes if m["type"] == "http.response.start")
    return debut["status"], json.loads(b"".join(m.get("body", b"") for m in envoyes if m["type"] == "http.response.body"))


def _relais_catalogue(vus: list[httpx.Request], panne_albert: bool = False) -> RelaisLLM:
    sspcloud = {"data": [{"id": "qwen3-6-35b-moe", "name": "qwen3-6-35b-moe"}, {"id": "gemma4-26b-moe"}, {"id": "qwen3-embedding-8b"}, {"id": "chandra-ocr-2"}]}
    albert = {"data": [{"id": "gpt-oss-120b", "type": "text-generation"}, {"id": "deepseek-v4-flash-0731", "type": "text-generation"}, {"id": "bge-m3", "type": "text-embeddings-inference"}, {"id": "lightonocr-2-1b", "type": "image-text-to-text"}]}

    def gestionnaire(requete: httpx.Request) -> httpx.Response:
        vus.append(requete)
        if "albert" in str(requete.url):
            return httpx.Response(503) if panne_albert else httpx.Response(200, json=albert)
        return httpx.Response(200, json=sspcloud)

    natif = Fournisseur("albert", "Albert API", "https://albert.exemple/v1", "cle-albert", frozenset({"gpt-oss-120b"}))
    return RelaisLLM("https://sspcloud.exemple/api", client=httpx.AsyncClient(transport=httpx.MockTransport(gestionnaire)), fournisseurs=lambda: [natif])


def test_le_catalogue_fusionne_sspcloud_et_albert_et_ecarte_le_reste() -> None:
    vus: list[httpx.Request] = []
    statut, corps = _lister(_relais_catalogue(vus))
    ids = [m["id"] for m in corps["data"]]
    assert statut == 200 and ids == ["claude-ssp-qwen3-6-35b-moe", "claude-albert-gpt-oss-120b", "claude-albert-deepseek-v4-flash-0731"]
    assert all(m["type"] == "model" and m["display_name"] for m in corps["data"])
    noms = {m["id"]: m["display_name"] for m in corps["data"]}
    assert noms["claude-albert-gpt-oss-120b"] == "Albert API · gpt-oss-120b"
    descriptions = {m["id"]: m["description"] for m in corps["data"]}
    assert "imposés" not in descriptions["claude-albert-gpt-oss-120b"] and "imposés" in descriptions["claude-albert-deepseek-v4-flash-0731"]
    assert corps["has_more"] is False and corps["last_id"] == ids[-1]


def test_le_catalogue_envoie_la_bonne_cle_a_chacun() -> None:
    vus: list[httpx.Request] = []
    _lister(_relais_catalogue(vus))
    chez_albert = next(r for r in vus if "albert" in str(r.url))
    chez_sspcloud = next(r for r in vus if "sspcloud" in str(r.url))
    assert chez_albert.headers["authorization"] == "Bearer cle-albert" and "cle-sspcloud" not in str(chez_albert.headers)
    assert chez_sspcloud.headers["x-api-key"] == "cle-sspcloud" and "cle-albert" not in str(chez_sspcloud.headers)


def test_un_fournisseur_en_panne_n_efface_pas_les_modeles_sspcloud() -> None:
    statut, corps = _lister(_relais_catalogue([], panne_albert=True))
    assert statut == 200 and [m["id"] for m in corps["data"]] == ["claude-ssp-qwen3-6-35b-moe"]


def test_le_catalogue_est_garde_cinq_minutes() -> None:
    vus: list[httpx.Request] = []
    relais = _relais_catalogue(vus)
    _lister(relais)
    n = len(vus)
    _lister(relais)
    assert len(vus) == n


def test_les_identifiants_publics_font_l_aller_retour() -> None:
    from mcp_gateway.atelier.fournisseurs import identifiant_sspcloud, modele_sspcloud_nu

    assert ALBERT.identifiant_public("gpt-oss-120b") == "claude-albert-gpt-oss-120b"
    assert fournisseur_du_modele([ALBERT], "claude-albert-gpt-oss-120b") == (ALBERT, "gpt-oss-120b")
    assert fournisseur_du_modele([ALBERT], "claude-albert-") is None
    assert fournisseur_du_modele([ALBERT], "claude-ssp-qwen") is None
    assert modele_sspcloud_nu(identifiant_sspcloud("qwen3-6-35b-moe")) == "qwen3-6-35b-moe"
    assert modele_sspcloud_nu("qwen3-6-35b-moe") == "qwen3-6-35b-moe"  # un nom nu reste valable


def test_ssp_n_est_pas_un_identifiant_de_fournisseur(reglages) -> None:
    d = reglages.secrets_dir
    d.mkdir(parents=True, exist_ok=True)
    (d / "fournisseurs.json").write_text(json.dumps({"ssp": {"base_url": "https://x.exemple/v1"}}), encoding="utf-8")
    (d / "ssp_api_key").write_text("k", encoding="utf-8")
    assert charger_fournisseurs(reglages) == []


def test_relais_le_modele_public_albert_est_route_comme_le_prefixe() -> None:
    vus: list[httpx.Request] = []
    reponse = httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})
    statut, _, _ = _appeler(_relais(reponse, vus), {"model": "claude-albert-deepseek", "max_tokens": 5, "messages": [{"role": "user", "content": "x"}]})
    assert statut == 200 and json.loads(vus[0].content)["model"] == "deepseek"


def test_relais_le_modele_public_sspcloud_part_sous_son_nom_nu() -> None:
    vus: list[httpx.Request] = []
    reponse = httpx.Response(200, json={"type": "message", "content": [], "usage": {"input_tokens": 1, "output_tokens": 1}})
    _appeler(_relais(reponse, vus), {"model": "claude-ssp-qwen3-6-35b-moe", "max_tokens": 5, "messages": [{"role": "user", "content": "x"}]})
    assert str(vus[0].url) == "https://sspcloud.exemple/api/v1/messages"
    assert json.loads(vus[0].content)["model"] == "qwen3-6-35b-moe"
