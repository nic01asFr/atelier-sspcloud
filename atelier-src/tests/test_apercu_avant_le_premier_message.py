"""Régler les connecteurs avant le premier message : l'aperçu d'une conversation qui n'existe pas.

L'aperçu rend la même liste que celle d'une conversation, calculée sur le dossier où elle
naîtra, et ne crée rien : ni dossier de conversation, ni fiche.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings


def _client(reglages: AtelierSettings) -> TestClient:
    return TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver")


def _cle(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {client.app.state.settings.owner_key_path.read_text().strip()}"}  # type: ignore[attr-defined]


def test_l_apercu_d_un_projet_rend_ses_connecteurs_sans_rien_creer(reglages: AtelierSettings) -> None:
    (reglages.projects_dir / "demo").mkdir(parents=True, exist_ok=True)
    with _client(reglages) as client:
        avant = list(reglages.projects_dir.iterdir())
        r = client.get("/v1/mcp/apercu", params={"kind": "code", "slug": "demo"}, headers=_cle(client))
        assert r.status_code == 200, r.text
        corps = r.json()
        assert corps["apercu"] is True and corps["session_id"] == "" and corps["kind"] == "code"
        assert isinstance(corps["connectors"], list)
        # Le serveur de l'Atelier est dans tout projet : il est dans la liste, comme pour une conversation.
        assert any(c["id"] == "atelier" for c in corps["connectors"]) or corps["binding"] == []
        assert client.app.state.store.list_sessions("demo") == []  # type: ignore[attr-defined]
        assert sorted(reglages.projects_dir.iterdir()) == sorted(avant), "aucun dossier créé"


def test_l_apercu_de_l_assistant_ne_cree_pas_de_dossier_de_conversation(reglages: AtelierSettings) -> None:
    with _client(reglages) as client:
        racine = reglages.assistant_root
        avant = sorted(p.name for p in racine.iterdir()) if racine.exists() else []
        r = client.get("/v1/mcp/apercu", params={"kind": "assistant"}, headers=_cle(client))
        assert r.status_code == 200, r.text
        assert r.json()["kind"] == "assistant" and r.json()["apercu"] is True
        apres = sorted(p.name for p in racine.iterdir()) if racine.exists() else []
        assert apres == avant, "pas de dossier de conversation créé"


def test_l_apercu_refuse_un_slug_ou_un_genre_invalide(reglages: AtelierSettings) -> None:
    with _client(reglages) as client:
        h = _cle(client)
        assert client.get("/v1/mcp/apercu", params={"kind": "code", "slug": "../evasion"}, headers=h).status_code == 400
        assert client.get("/v1/mcp/apercu", params={"kind": "autre"}, headers=h).status_code == 400
        assert client.get("/v1/mcp/apercu", params={"kind": "code", "slug": "demo"}).status_code in (401, 403)
