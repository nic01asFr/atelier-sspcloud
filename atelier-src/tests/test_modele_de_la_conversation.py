"""Le modèle d'une conversation se change comme `/model` dans Claude Code.

Il se pose sur la conversation, vaut pour les tours à venir, et le processus
gardé repart avec `--model` (il fait partie de son empreinte).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.sessions import modele_valide


def _entete(atelier: TestClient) -> dict[str, str]:
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def _creer(atelier: TestClient, **corps) -> str:
    return atelier.post("/v1/sessions", headers=_entete(atelier), json={"slug": "essai", "title": "M", **corps}).json()["session_id"]


def test_le_modele_se_pose_sur_une_conversation_et_se_relit(atelier: TestClient) -> None:
    sid = _creer(atelier)
    r = atelier.patch(f"/v1/sessions/{sid}", headers=_entete(atelier), json={"model": "claude-albert-gpt-oss-120b"})
    assert r.status_code == 200 and r.json()["model"] == "claude-albert-gpt-oss-120b"
    assert atelier.get(f"/v1/sessions/{sid}", headers=_entete(atelier)).json()["model"] == "claude-albert-gpt-oss-120b"


def test_un_modele_vide_rend_la_conversation_au_defaut(atelier: TestClient) -> None:
    sid = _creer(atelier, model="qwen3-8-27b")
    r = atelier.patch(f"/v1/sessions/{sid}", headers=_entete(atelier), json={"model": ""})
    assert r.status_code == 200 and r.json()["model"] == ""


def test_changer_le_modele_ne_touche_pas_au_reste(atelier: TestClient) -> None:
    sid = _creer(atelier)
    atelier.patch(f"/v1/sessions/{sid}", headers=_entete(atelier), json={"permission_mode": "plan", "title": "Nom"})
    apres = atelier.patch(f"/v1/sessions/{sid}", headers=_entete(atelier), json={"model": "sonnet"}).json()
    assert apres["permission_mode"] == "plan" and apres["title"] == "Nom" and apres["model"] == "sonnet"


def test_un_modele_de_forme_invalide_est_refuse(atelier: TestClient) -> None:
    sid = _creer(atelier)
    for mauvais in ("a b", "x;rm -rf", "--model", "é" * 3, "m" * 200):
        r = atelier.patch(f"/v1/sessions/{sid}", headers=_entete(atelier), json={"model": mauvais})
        assert r.status_code == 400, mauvais


@pytest.mark.parametrize("valeur", ["qwen3-6-35b-moe", "claude-albert-gpt-oss-120b", "albert/gpt-oss-120b", "opus", "sonnet[1m]", "claude-ssp-qwen3-vl"])
def test_les_formes_usuelles_passent(valeur: str) -> None:
    assert modele_valide(valeur) == valeur


def test_le_modele_fait_partie_de_l_empreinte_du_processus(tmp_path) -> None:
    """Changer de modèle éteint le processus gardé : le suivant part avec le bon `--model`."""
    a = ClaudeHarness._empreinte(tmp_path, "qwen3-6-35b-moe", "default", "", "", None)
    b = ClaudeHarness._empreinte(tmp_path, "claude-albert-gpt-oss-120b", "default", "", "", None)
    assert a != b
