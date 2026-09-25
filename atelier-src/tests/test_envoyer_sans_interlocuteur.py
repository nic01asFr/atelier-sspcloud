"""Un tour lancé par un automate ne reste plus figé sur une autorisation.

Trouvé par l'agent wikichat (prérequis du lot D) : `atelier_envoyer` jouait
toujours le tour avec `peut_attendre=True` et n'acceptait aucun mode. Un tour
lancé par wikichat — personne pour répondre — attendait donc indéfiniment.
Désormais : `peut_attendre` vaut faux par défaut quand l'appel vient de la clé
du propriétaire (agents, wikichat), et un `mode` peut être demandé, sans que
l'appelant puisse s'accorder seul le bypass.
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_gateway.atelier.outils_conversation import APPEL_INTERACTIF, OutilsAtelier


class _Magasin:
    def __init__(self, permission_mode: str = "", cwd: str = "") -> None:
        self.settings = SimpleNamespace(default_slug="default", permission_mode="acceptEdits")
        self.fiche = SimpleNamespace(
            session_id="conv", state="idle", slug="p", permission_mode=permission_mode, cwd=cwd
        )
        self.vus: dict[str, Any] = {}
        self.parti = threading.Event()

    def get(self, session_id: str):
        return self.fiche if session_id == "conv" else None

    def send(self, session_id, message, on_event=None, **kw):
        self.vus.update(kw)
        self.parti.set()
        return SimpleNamespace(text="ok", events=[])


def _envoyer(magasin: _Magasin, interactif: bool = True, **args: Any) -> dict:
    outils = OutilsAtelier(store=magasin, projects=None, harness=None)

    async def appel() -> dict:
        jeton = APPEL_INTERACTIF.set(interactif)
        try:
            return await outils.appeler(
                "atelier_envoyer", {"conversation": "conv", "message": "va", **args}
            )
        finally:
            APPEL_INTERACTIF.reset(jeton)

    resultat = asyncio.run(appel())
    charge = json.loads(resultat["content"][0]["text"])
    if not resultat.get("isError"):
        assert magasin.parti.wait(timeout=5)
    return {"charge": charge, "erreur": bool(resultat.get("isError"))}


def test_un_automate_ne_fait_pas_attendre_par_defaut() -> None:
    magasin = _Magasin()
    r = _envoyer(magasin, interactif=False)
    assert magasin.vus["peut_attendre"] is False
    assert r["charge"]["peut_attendre"] is False
    # Et pas de bypass implicite pour autant : le mode du service.
    assert magasin.vus["mode"] == "acceptEdits"


def test_un_client_ou_quelqu_un_lit_attend_comme_avant() -> None:
    magasin = _Magasin()
    _envoyer(magasin, interactif=True)
    assert magasin.vus["peut_attendre"] is True


def test_l_appelant_peut_le_dire_lui_meme() -> None:
    magasin = _Magasin()
    _envoyer(magasin, interactif=False, peut_attendre=True)
    assert magasin.vus["peut_attendre"] is True


@pytest.mark.parametrize(("demande", "attendu"), [("plan", "plan"), ("default", "manual"), ("acceptEdits", "acceptEdits")])
def test_un_mode_demande_est_applique(demande: str, attendu: str) -> None:
    magasin = _Magasin()
    _envoyer(magasin, mode=demande)
    assert magasin.vus["mode"] == attendu


def test_le_bypass_ne_s_accorde_pas_par_l_appelant() -> None:
    magasin = _Magasin(permission_mode="acceptEdits")
    r = _envoyer(magasin, interactif=False, mode="bypassPermissions")
    assert r["erreur"] and "bypassPermissions refusé" in r["charge"]["erreur"]
    assert not magasin.vus, "aucun tour ne part"


def test_le_bypass_deja_accorde_par_la_conversation_passe() -> None:
    magasin = _Magasin(permission_mode="bypassPermissions")
    _envoyer(magasin, interactif=False, mode="bypassPermissions")
    assert magasin.vus["mode"] == "bypassPermissions"


def test_le_bypass_deja_accorde_par_le_projet_passe(tmp_path: Path) -> None:
    (tmp_path / ".claude").mkdir()
    (tmp_path / ".claude" / "settings.local.json").write_text(
        json.dumps({"permissions": {"defaultMode": "bypassPermissions"}}), encoding="utf-8"
    )
    magasin = _Magasin(cwd=str(tmp_path))
    _envoyer(magasin, interactif=False, mode="bypassPermissions")
    assert magasin.vus["mode"] == "bypassPermissions"


def test_un_service_en_bypass_ne_le_donne_pas_a_un_automate() -> None:
    magasin = _Magasin()
    magasin.settings.permission_mode = "bypassPermissions"
    _envoyer(magasin, interactif=False)
    assert magasin.vus["mode"] == "acceptEdits"


def test_un_mode_inconnu_est_refuse() -> None:
    r = _envoyer(_Magasin(), mode="yolo")
    assert r["erreur"] and "mode inconnu" in r["charge"]["erreur"]


def _porte(atelier):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from mcp_gateway.atelier.auth import OwnerAuth
    from mcp_gateway.atelier.mcp_endpoint import register_mcp_endpoint

    vus: list[bool] = []

    class Passerelle:
        async def handle_jsonrpc(self, body, session):
            vus.append(APPEL_INTERACTIF.get())
            return {"jsonrpc": "2.0", "id": body.get("id"), "result": {}}

    app = FastAPI()
    app.state.db = atelier.app.state.db
    app.state.mcp = Passerelle()
    register_mcp_endpoint(app, OwnerAuth(atelier.app.state.settings))
    return TestClient(app, base_url="https://testserver"), vus


def test_la_porte_mcp_distingue_la_cle_du_proprietaire(atelier, cle_du_proprietaire: str) -> None:
    """Clé du propriétaire (agents, wikichat) : automate. Jeton OAuth : quelqu'un lit."""
    from mcp_gateway.auth import issue_token

    porte, vus = _porte(atelier)
    corps = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
    r = porte.post("/mcp", json=corps, headers={"Authorization": f"Bearer {cle_du_proprietaire}"})
    assert r.status_code == 200
    jeton = issue_token(atelier.app.state.db, client_id="essai", label="essai")
    r = porte.post("/mcp", json=corps, headers={"Authorization": f"Bearer {jeton}"})
    assert r.status_code == 200
    assert vus == [False, True]
    assert APPEL_INTERACTIF.get() is True, "le contexte est rendu après l'appel"
