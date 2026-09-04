"""La clé propriétaire peut être renouvelée sans se connecter au pod.

Elle ouvre tout : le harnais lance `claude` en `bypassPermissions`, donc qui
la détient exécute ce qu'il veut. Or elle a fui — dans un journal, dans une
URL, dans le transcript d'un agent. Il fallait alors se connecter au pod et
éditer un fichier, ce que personne ne fait à chaud.

Ce que ces tests tiennent : que la nouvelle clé remplace vraiment l'ancienne,
que l'ancienne ne vaille plus rien, et que les sessions de navigation ouvertes
avec elle tombent avec elle.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def _cle(atelier: TestClient) -> str:
    return atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def test_la_cle_change_et_la_nouvelle_est_rendue(atelier: TestClient) -> None:
    avant = _cle(atelier)
    r = atelier.post("/v1/auth/rotate", headers={"Authorization": f"Bearer {avant}"})
    assert r.status_code == 200
    neuve = r.json()["owner_key"]
    assert neuve and neuve != avant
    # Rendue, et posée sur le disque : les deux doivent concorder.
    assert _cle(atelier) == neuve


def test_l_ancienne_cle_ne_vaut_plus_rien(atelier: TestClient) -> None:
    ancienne = _cle(atelier)
    atelier.post("/v1/auth/rotate", headers={"Authorization": f"Bearer {ancienne}"})
    r = atelier.get("/v1/sessions", headers={"Authorization": f"Bearer {ancienne}"})
    assert r.status_code == 401


def test_la_nouvelle_cle_ouvre(atelier: TestClient) -> None:
    ancienne = _cle(atelier)
    neuve = atelier.post(
        "/v1/auth/rotate", headers={"Authorization": f"Bearer {ancienne}"}
    ).json()["owner_key"]
    r = atelier.get("/v1/sessions", headers={"Authorization": f"Bearer {neuve}"})
    assert r.status_code == 200


def test_les_sessions_ouvertes_tombent_avec_elle(atelier: TestClient) -> None:
    """Sinon renouveler ne changerait rien pour qui détient l'ancienne."""
    ancienne = _cle(atelier)
    assert (
        atelier.post(
            "/v1/auth/cookie", headers={"Authorization": f"Bearer {ancienne}"}
        ).status_code
        == 200
    )
    # Le cookie seul suffit avant la rotation.
    assert atelier.get("/v1/sessions/x/events?message=a").status_code == 404

    atelier.post("/v1/auth/rotate", headers={"Authorization": f"Bearer {ancienne}"})
    assert atelier.get("/v1/sessions/x/events?message=a").status_code == 401


def test_sans_la_cle_on_ne_fait_pas_tourner(atelier: TestClient) -> None:
    avant = _cle(atelier)
    assert atelier.post("/v1/auth/rotate").status_code == 401
    assert atelier.post(
        "/v1/auth/rotate", headers={"Authorization": "Bearer pas-la-bonne"}
    ).status_code == 401
    assert _cle(atelier) == avant


def test_le_fichier_reste_lisible_par_son_seul_proprietaire(atelier: TestClient) -> None:
    import os
    import stat as st

    chemin = atelier.app.state.settings.owner_key_path
    atelier.post("/v1/auth/rotate", headers={"Authorization": f"Bearer {_cle(atelier)}"})
    if os.name == "nt":
        return  # les droits POSIX n'ont pas cours ici
    mode = st.S_IMODE(chemin.stat().st_mode)
    assert mode == 0o600
