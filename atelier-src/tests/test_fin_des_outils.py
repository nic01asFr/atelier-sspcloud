"""Un outil qui rend son résultat doit cesser d'être « en cours ».

Le CLI annonce les résultats d'outils dans des enregistrements de type
« user ». Tant que cette forme n'était pas lue, aucun « outil_fin » n'était
émis : à l'écran, les outils restaient en cours jusqu'au rechargement de la
page, alors que le tour était fini depuis longtemps.
"""

from __future__ import annotations

import json

from mcp_gateway.atelier.events import parse_stream_json_line

SESSION = "session-de-test"


def _ligne(contenu: object) -> str:
    return json.dumps({"type": "user", "message": {"content": contenu}})


def test_un_resultat_d_outil_ferme_l_outil() -> None:
    ligne = _ligne(
        [{"type": "tool_result", "tool_use_id": "outil-42", "content": "trois fichiers"}]
    )
    evenements = parse_stream_json_line(SESSION, ligne)
    assert [e.kind for e in evenements] == ["outil_fin"]
    assert evenements[0].tool_id == "outil-42"
    assert "trois fichiers" in evenements[0].text


def test_le_resultat_peut_arriver_en_blocs() -> None:
    """Le CLI écrit tantôt une chaîne, tantôt une liste de blocs."""
    ligne = _ligne(
        [
            {
                "type": "tool_result",
                "tool_use_id": "outil-7",
                "content": [{"type": "text", "text": "deuxième forme"}],
            }
        ]
    )
    evenements = parse_stream_json_line(SESSION, ligne)
    assert [e.kind for e in evenements] == ["outil_fin"]
    assert "deuxième forme" in evenements[0].text


def test_plusieurs_resultats_dans_un_meme_message() -> None:
    ligne = _ligne(
        [
            {"type": "tool_result", "tool_use_id": "a", "content": "un"},
            {"type": "tool_result", "tool_use_id": "b", "content": "deux"},
        ]
    )
    evenements = parse_stream_json_line(SESSION, ligne)
    assert [e.tool_id for e in evenements] == ["a", "b"]


def test_un_message_ordinaire_n_emet_rien() -> None:
    """La prise de parole de quelqu'un n'est pas la fin d'un outil."""
    assert parse_stream_json_line(SESSION, _ligne("bonjour")) == []
    assert parse_stream_json_line(SESSION, _ligne([{"type": "text", "text": "bonjour"}])) == []


def test_un_tour_coupe_au_plafond_est_dit() -> None:
    """Sortie 0, `result` d'apparence normale : ça se lisait comme une fin."""
    ligne = json.dumps({"type": "result", "subtype": "error_max_turns", "result": ""})
    evenements = parse_stream_json_line(SESSION, ligne)
    assert [e.kind for e in evenements] == ["erreur"]
    assert "plafond de tours" in evenements[0].cause


def test_un_tour_qui_aboutit_reste_une_fin() -> None:
    ligne = json.dumps({"type": "result", "subtype": "success", "result": "voila"})
    assert [e.kind for e in parse_stream_json_line(SESSION, ligne)] == ["texte", "fin"]
