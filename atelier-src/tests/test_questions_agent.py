"""L'agent peut poser une question, et recevoir la réponse.

Mesuré sur le pod : le modèle appelle `AskUserQuestion` avec une charge
complète — question, intitulé, options et leurs descriptions, choix multiple ou
non — et cet appel arrive par le canal des autorisations, comme une demande de
permission.

Mais autoriser l'outil ne rend rien : le CLI, faute d'écran, conclut aussitôt
« The user did not answer the questions ». C'est le message d'un refus qui lui
revient comme résultat, mot pour mot — vérifié de bout en bout, le modèle l'a
lu et a poursuivi. Le mot « refus » n'est donc qu'un véhicule ; ces tests
tiennent ce que ce véhicule transporte.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mcp_gateway.atelier.decisions import (
    Demande,
    Regle,
    regle_suggeree,
    reponse_aux_questions,
)

from test_canal_decision import _cle

# Relevé sur le pod, pas inventé : c'est la charge exacte que le modèle envoie.
APPEL_REEL = {
    "subtype": "can_use_tool",
    "tool_name": "AskUserQuestion",
    "input": {
        "questions": [
            {
                "question": "Quelle couleur préfères-tu ?",
                "header": "Couleur",
                "options": [
                    {"label": "Rouge", "description": "La couleur du feu"},
                    {"label": "Vert", "description": "La couleur de la nature"},
                    {"label": "Bleu", "description": "La couleur du ciel"},
                ],
                "multiSelect": False,
            }
        ]
    },
    "tool_use_id": "call_qcm",
}


def _question(request_id: str = "q1", session_id: str = "s1") -> Demande:
    return Demande.depuis_control_request(request_id, session_id, APPEL_REEL)


def test_une_question_se_reconnait_a_son_outil() -> None:
    demande = _question()
    assert demande.genre == "question"
    assert demande.questions[0]["header"] == "Couleur"
    assert [o["label"] for o in demande.questions[0]["options"]] == [
        "Rouge",
        "Vert",
        "Bleu",
    ]


def test_une_autorisation_ordinaire_reste_une_autorisation() -> None:
    demande = Demande.depuis_control_request(
        "r", "s1", {"subtype": "can_use_tool", "tool_name": "Write", "input": {}}
    )
    assert demande.genre == "autorisation"
    assert demande.questions == []


def test_la_reponse_nomme_la_question_a_laquelle_elle_repond() -> None:
    """Un modèle qui en pose trois doit savoir laquelle on lui rend."""
    rendu = reponse_aux_questions(_question(), [["Bleu"]])
    assert "Couleur : Bleu" in rendu["message"]
    # Le canal n'a qu'un champ qui revienne au modèle : celui d'un refus.
    assert rendu["behavior"] == "deny"


def test_un_choix_multiple_rend_toutes_les_reponses() -> None:
    appel = json.loads(json.dumps(APPEL_REEL))
    appel["input"]["questions"][0]["multiSelect"] = True
    demande = Demande.depuis_control_request("q", "s1", appel)
    rendu = reponse_aux_questions(demande, [["Rouge", "Bleu"]])
    assert "Couleur : Rouge, Bleu" in rendu["message"]


def test_plusieurs_questions_se_repondent_ensemble() -> None:
    appel = json.loads(json.dumps(APPEL_REEL))
    appel["input"]["questions"].append(
        {"question": "Et la taille ?", "header": "Taille", "options": [], "multiSelect": False}
    )
    demande = Demande.depuis_control_request("q", "s1", appel)
    message = reponse_aux_questions(demande, [["Bleu"], ["Grande"]])["message"]
    assert "Couleur : Bleu" in message
    assert "Taille : Grande" in message


def test_une_reponse_libre_passe_comme_une_autre() -> None:
    """Aucune liste ne prévoit tout ; le texte libre voyage pareil."""
    rendu = reponse_aux_questions(_question(), [["Turquoise"]])
    assert "Couleur : Turquoise" in rendu["message"]


def test_ne_rien_choisir_se_dit_franchement() -> None:
    rendu = reponse_aux_questions(_question(), [[]])
    assert "pas répondu" in rendu["message"]


def test_une_question_ne_s_accorde_jamais_d_avance() -> None:
    """« Ne plus me demander » n'a pas de sens quand on demande un avis.

    Et une règle qui couvrirait une question l'autoriserait sans rien répondre
    — le modèle recevrait « the user did not answer », en boucle.
    """
    assert regle_suggeree(_question()) is None
    assert Regle("s1", "outil", "AskUserQuestion").couvre(_question()) is False


def test_la_route_rend_la_reponse_au_tour(atelier: TestClient) -> None:
    registre = atelier.app.state.harness.decisions
    signal = registre.poser(_question("qr", "s12"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/qr",
        headers=entete,
        json={"decision": "deny", "reponses": [["Bleu"]]},
    )
    assert r.status_code == 200
    assert signal.is_set()
    assert "Couleur : Bleu" in registre.reponse("qr")["message"]
    # Répondre à une question ne retient jamais de règle.
    assert r.json()["regle"] is None
    assert registre.regles("s12") == []
    registre.clore("qr")


def test_repondre_a_une_question_sans_rien_choisir(atelier: TestClient) -> None:
    """Le tour doit repartir quand même : mieux vaut un « rien » qu'un blocage."""
    registre = atelier.app.state.harness.decisions
    signal = registre.poser(_question("qv", "s13"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post("/v1/decisions/qv", headers=entete, json={"decision": "deny"})
    assert r.status_code == 200
    assert signal.is_set()
    assert "pas répondu" in registre.reponse("qv")["message"]
    registre.clore("qv")
