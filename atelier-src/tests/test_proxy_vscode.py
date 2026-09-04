"""Le proxy ne remet pas à code-server la clé de sa propre porte.

Le navigateur joint à chaque appel de `/vscode` ce qu'il joint partout : la clé
propriétaire en `Authorization`, et le cookie de session de l'Atelier. Ils
partaient tels quels vers code-server, qui n'en a aucun usage.

Et ce n'était pas qu'une question d'hygiène : `httpx` laisse un en-tête
`Cookie` explicite l'emporter sur le pot de cookies du client. Le cookie du
navigateur déplaçait donc la session que le proxy avait ouverte auprès de
code-server.
"""

from __future__ import annotations

import httpx

from mcp_gateway.atelier.vscode_proxy import NE_PAS_TRANSMETTRE, entetes_amont

ENVOI_DU_NAVIGATEUR = {
    "Authorization": "Bearer la-cle-proprietaire",
    "Cookie": "atelier_sid=une-session; autre=valeur",
    "Accept": "text/html",
    "User-Agent": "un-navigateur",
    "Host": "atelier.example",
    "Connection": "keep-alive",
}


def test_la_cle_et_le_cookie_ne_remontent_pas() -> None:
    amont = entetes_amont(ENVOI_DU_NAVIGATEUR)
    minuscules = {k.lower() for k in amont}
    assert "authorization" not in minuscules
    assert "cookie" not in minuscules


def test_ce_qui_sert_a_code_server_passe() -> None:
    """Retirer trop casserait le rendu : seuls deux en-têtes s'en vont."""
    amont = entetes_amont(ENVOI_DU_NAVIGATEUR)
    assert amont["Accept"] == "text/html"
    assert amont["User-Agent"] == "un-navigateur"


def test_les_en_tetes_saut_par_saut_partent_toujours() -> None:
    amont = entetes_amont(ENVOI_DU_NAVIGATEUR)
    minuscules = {k.lower() for k in amont}
    assert "host" not in minuscules
    assert "connection" not in minuscules


def test_la_casse_de_l_en_tete_n_y_change_rien() -> None:
    for ecriture in ("authorization", "AUTHORIZATION", "AuThOrIzAtIoN"):
        assert entetes_amont({ecriture: "Bearer x"}) == {}


def test_un_cookie_explicite_ecrase_le_pot_de_httpx() -> None:
    """La raison pour laquelle ce n'est pas qu'une question de propreté.

    Si le proxy laisse passer le `Cookie` du navigateur, sa propre session
    auprès de code-server ne part pas — l'en-tête explicite gagne.
    """
    pot = httpx.Cookies()
    pot.set("code-server-session", "celle-du-proxy", domain="127.0.0.1")
    with httpx.Client(cookies=pot) as client:
        avec = client.build_request(
            "GET", "http://127.0.0.1:8080/", headers={"Cookie": "atelier_sid=celle-du-client"}
        )
        assert "celle-du-proxy" not in (avec.headers.get("cookie") or "")

        sans = client.build_request(
            "GET", "http://127.0.0.1:8080/", headers=entetes_amont(ENVOI_DU_NAVIGATEUR)
        )
        assert "celle-du-proxy" in (sans.headers.get("cookie") or "")


def test_l_ensemble_retire_contient_bien_les_deux() -> None:
    assert {"authorization", "cookie"} <= NE_PAS_TRANSMETTRE
