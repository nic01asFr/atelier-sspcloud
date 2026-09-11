"""Un service qui redémarre ne doit pas hériter d'états que rien ne porte.

Deux fiches se disaient « en cours » le 7 septembre sans aucun processus
derrière : réparées à la main. Rien ne le faisait au démarrage, et jusqu'à
l'envoi d'un message la conversation s'affichait occupée, l'absorption du
journal l'ignorait, et un message posté partait en file au lieu de jouer.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app


def test_une_fiche_en_cours_sans_processus_est_reparee_au_demarrage(reglages) -> None:
    # Une fiche laissée « en cours » par un service précédent.
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as c:
        cle = reglages.owner_key_path.read_text(encoding="utf-8").strip()
        sid = c.post(
            "/v1/sessions", headers={"Authorization": f"Bearer {cle}"},
            json={"slug": "essai", "title": "Fantome"},
        ).json()["session_id"]
    fiche = reglages.sessions_dir / f"{sid}.json"
    d = json.loads(fiche.read_text(encoding="utf-8"))
    d["state"] = "running"
    fiche.write_text(json.dumps(d), encoding="utf-8")

    # Le service redémarre : aucun tour ne tourne.
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as c:
        cle = reglages.owner_key_path.read_text(encoding="utf-8").strip()
        etat = c.get(f"/v1/sessions/{sid}", headers={"Authorization": f"Bearer {cle}"}).json()["state"]
    assert etat == "idle"


def test_une_fiche_en_echec_garde_sa_cause(reglages) -> None:
    """« en cours » avec une cause d'arrêt, c'est un échec, pas un repos."""
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as c:
        cle = reglages.owner_key_path.read_text(encoding="utf-8").strip()
        sid = c.post(
            "/v1/sessions", headers={"Authorization": f"Bearer {cle}"},
            json={"slug": "essai", "title": "Echec"},
        ).json()["session_id"]
    fiche = reglages.sessions_dir / f"{sid}.json"
    d = json.loads(fiche.read_text(encoding="utf-8"))
    d["state"] = "running"; d["cause"] = "timeout_mural"
    fiche.write_text(json.dumps(d), encoding="utf-8")

    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as c:
        cle = reglages.owner_key_path.read_text(encoding="utf-8").strip()
        etat = c.get(f"/v1/sessions/{sid}", headers={"Authorization": f"Bearer {cle}"}).json()["state"]
    assert etat == "failed"
