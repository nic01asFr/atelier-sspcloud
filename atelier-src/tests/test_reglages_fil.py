"""Les réglages d'affichage du fil : retenus par personne, côté service.

« Montrer le raisonnement de l'agent » et « Montrer les actions et leurs
résultats bruts » sont décochés par défaut. Cochés, ils valent sur tous les
appareils de la personne : ils vivent dans les réglages d'interface du service
(`ui.json`), et non dans le navigateur. Décochés, ils s'effacent — l'absence
vaut le défaut.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _cle(client: TestClient) -> dict[str, str]:
    cle = client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()  # type: ignore[attr-defined]
    return {"Authorization": f"Bearer {cle}"}


def test_les_reglages_du_fil_sont_absents_par_defaut(atelier: TestClient) -> None:
    ui = atelier.get("/v1/meta", headers=_cle(atelier)).json()["ui"]
    assert "fil_raisonnement" not in ui
    assert "fil_actions" not in ui


def test_un_reglage_coche_se_retient_et_decoche_s_efface(atelier: TestClient) -> None:
    r = atelier.put("/v1/meta", headers=_cle(atelier), json={"fil_raisonnement": True})
    assert r.status_code == 200
    assert r.json()["ui"]["fil_raisonnement"] is True
    assert "fil_actions" not in r.json()["ui"], "un réglage non envoyé ne bouge pas"

    relu = atelier.get("/v1/meta", headers=_cle(atelier)).json()["ui"]
    assert relu["fil_raisonnement"] is True

    r = atelier.put("/v1/meta", headers=_cle(atelier), json={"fil_raisonnement": False, "fil_actions": True})
    ui = r.json()["ui"]
    assert "fil_raisonnement" not in ui, "décoché, le réglage s'efface : l'absence vaut le défaut"
    assert ui["fil_actions"] is True


def test_les_reglages_du_fil_ne_touchent_pas_aux_autres(atelier: TestClient) -> None:
    atelier.put("/v1/meta", headers=_cle(atelier), json={"langue": "fr"})
    atelier.put("/v1/meta", headers=_cle(atelier), json={"fil_actions": True})
    ui = atelier.get("/v1/meta", headers=_cle(atelier)).json()["ui"]
    assert ui["langue"] == "fr"
    assert ui["fil_actions"] is True
