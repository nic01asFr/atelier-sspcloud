"""La sonde de vie reste ouverte, mais ne raconte rien à un inconnu.

Elle rendait le nom des connecteurs branchés et le chemin absolu de la base
à qui les demandait depuis Internet. Rien de secret, rien d'utile non plus
au visiteur : de la reconnaissance offerte.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

ATTENDU_ANONYME = {"status", "service", "version"}


def test_repond_a_qui_ne_s_est_pas_authentifie(atelier: TestClient) -> None:
    """Une sonde Kubernetes n'a pas d'identifiant : la porte reste ouverte."""
    r = atelier.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_ne_dit_rien_de_plus_a_un_inconnu(atelier: TestClient) -> None:
    for chemin in ("/health", "/v1/health"):
        r = atelier.get(chemin)
        assert r.status_code == 200
        assert set(r.json()) == ATTENDU_ANONYME, chemin


def test_une_cle_fausse_ne_donne_pas_le_detail(atelier: TestClient) -> None:
    r = atelier.get("/health", headers={"Authorization": "Bearer pas-la-bonne-cle"})
    assert r.status_code == 200
    assert set(r.json()) == ATTENDU_ANONYME


def test_le_proprietaire_obtient_le_detail(
    atelier: TestClient, cle_du_proprietaire: str
) -> None:
    """La garde joue dans les deux sens : elle retient, elle ne mure pas."""
    r = atelier.get("/health", headers={"Authorization": f"Bearer {cle_du_proprietaire}"})
    assert r.status_code == 200
    assert set(r.json()) > ATTENDU_ANONYME
