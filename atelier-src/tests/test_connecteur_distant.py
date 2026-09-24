"""Un client distant se branche sur l'Atelier, sous la clé du propriétaire.

Le parcours tenu ici est celui qu'on veut voir marcher depuis Claude : coller
l'URL de l'Atelier comme connecteur, une page s'ouvre, taper la clé, c'est
branché. Rien d'autre ne doit passer.

Ce que ces tests tiennent, dans l'ordre où ça casserait :

- les métadonnées annoncent l'adresse publique, pas celle que voit uvicorn ;
- s'enregistrer ne donne rien — ni code, ni jeton — sans consentement ;
- une clé invalide ne consent pas, la bonne clé consent ;
- une destination non déclarée est refusée, et sans redirection ;
- la table des clients ne grossit pas sans fin et se laisse purger ;
- renouveler la clé emporte les jetons qu'elle avait accordés.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.auth import (
    PLAFOND_CLIENTS,
    issue_token,
    lister_clients,
    purger_clients_inertes,
)

RETOUR = "https://claude.ai/api/mcp/auth_callback"


def _defi() -> tuple[str, str]:
    """Un couple PKCE : le vérifieur gardé, le défi envoyé."""
    verifieur = secrets.token_urlsafe(48)
    defi = (
        base64.urlsafe_b64encode(hashlib.sha256(verifieur.encode()).digest())
        .decode()
        .rstrip("=")
    )
    return verifieur, defi


def _cle(client: TestClient) -> str:
    return client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def _enregistrer(client: TestClient, retour: str = RETOUR) -> str:
    r = client.post(
        "/register",
        json={"client_name": "Claude", "redirect_uris": [retour]},
    )
    assert r.status_code == 201, r.text
    return r.json()["client_id"]


def _autoriser(client: TestClient, client_id: str, defi: str, retour: str = RETOUR):
    return client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": retour,
            "state": "xyz",
            "code_challenge": defi,
            "code_challenge_method": "S256",
        },
        # Ne pas suivre : la destination est celle du client distant, et la
        # suivre ici la ferait router dans l'application de test.
        follow_redirects=False,
    )


def _consentir(
    client: TestClient, client_id: str, defi: str, cle: str, retour: str = RETOUR
):
    return client.post(
        "/authorize/confirm",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": retour,
            "state": "xyz",
            "code_challenge": defi,
            "code_challenge_method": "S256",
        },
        data={"owner_key": cle},
        follow_redirects=False,
    )


def _code_de(reponse) -> str:
    assert reponse.status_code in (302, 307), reponse.text
    destination = reponse.headers["location"]
    assert destination.startswith(RETOUR)
    return destination.split("code=")[1].split("&")[0]


# ── Les métadonnées ─────────────────────────────────────────────────────────


def test_les_metadonnees_annoncent_l_adresse_publique(tmp_path: Path) -> None:
    """Derrière un ingress, l'adresse vue par uvicorn est interne.

    Un client distant qui la suit n'arrive nulle part — et le défaut ne se voit
    qu'au branchement, c'est-à-dire trop tard.
    """
    reglages = AtelierSettings(
        work_dir=tmp_path / "work", public_url="https://atelier.exemple.fr"
    )
    with TestClient(
        build_app(settings=reglages, use_fake=True), base_url="https://testserver"
    ) as client:
        meta = client.get("/.well-known/oauth-authorization-server").json()
        assert meta["issuer"] == "https://atelier.exemple.fr"
        assert meta["authorization_endpoint"].startswith("https://atelier.exemple.fr/")
        ressource = client.get("/.well-known/oauth-protected-resource").json()
        assert ressource["resource"] == "https://atelier.exemple.fr"


def test_sans_adresse_publique_on_retombe_sur_celle_vue(atelier: TestClient) -> None:
    meta = atelier.get("/.well-known/oauth-authorization-server").json()
    assert meta["issuer"] == "https://testserver"


def test_sans_reglage_on_suit_ce_que_l_ingress_a_ecrit(atelier: TestClient) -> None:
    """Deux hôtes mènent au même processus : chacun doit s'annoncer lui-même.

    Sans cela, l'adresse annoncée est celle que voit uvicorn — interne, et en
    clair — et le client distant ne retrouve pas le serveur d'autorisation.
    """
    meta = atelier.get(
        "/.well-known/oauth-authorization-server",
        headers={
            "X-Forwarded-Host": "atelier.user.lab.sspcloud.fr",
            "X-Forwarded-Proto": "https",
        },
    ).json()
    assert meta["issuer"] == "https://atelier.user.lab.sspcloud.fr"
    assert meta["token_endpoint"] == "https://atelier.user.lab.sspcloud.fr/oauth/token"


def test_le_reglage_explicite_prime_sur_l_ingress(tmp_path: Path) -> None:
    reglages = AtelierSettings(
        work_dir=tmp_path / "work", public_url="https://atelier.exemple.fr"
    )
    with TestClient(
        build_app(settings=reglages, use_fake=True), base_url="https://testserver"
    ) as client:
        meta = client.get(
            "/.well-known/oauth-authorization-server",
            headers={"X-Forwarded-Host": "ailleurs.exemple", "X-Forwarded-Proto": "http"},
        ).json()
        assert meta["issuer"] == "https://atelier.exemple.fr"


# ── S'enregistrer ne donne rien ─────────────────────────────────────────────


def test_s_enregistrer_n_ouvre_rien(atelier: TestClient) -> None:
    """La porte est le consentement, pas l'enregistrement."""
    client_id = _enregistrer(atelier)
    _, defi = _defi()
    page = _autoriser(atelier, client_id, defi)
    assert page.status_code == 200
    # Une page, pas une redirection : aucun code n'est parti.
    assert "location" not in {k.lower() for k in page.headers}
    assert "Vérifier et autoriser" in page.text


def test_une_cle_invalide_ne_consent_pas(atelier: TestClient) -> None:
    client_id = _enregistrer(atelier)
    _, defi = _defi()
    r = _consentir(atelier, client_id, defi, "pas-la-bonne")
    assert r.status_code == 401
    assert "Clé invalide" in r.text


def test_la_cle_de_l_atelier_consent(atelier: TestClient) -> None:
    """La clé tapée est celle qui garde déjà le service — pas une seconde."""
    client_id = _enregistrer(atelier)
    verifieur, defi = _defi()
    code = _code_de(_consentir(atelier, client_id, defi, _cle(atelier)))

    jeton = atelier.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": RETOUR,
            "client_id": client_id,
            "code_verifier": verifieur,
        },
    )
    assert jeton.status_code == 200, jeton.text
    assert jeton.json()["access_token"]


def test_un_client_inconnu_est_refuse_sans_rediriger(atelier: TestClient) -> None:
    """Rediriger vers une adresse non vérifiée confirmerait qu'elle marche."""
    _, defi = _defi()
    r = _autoriser(atelier, "identifiant-invente", defi)
    assert r.status_code == 400
    assert "location" not in {k.lower() for k in r.headers}


def test_une_destination_non_declaree_est_refusee(atelier: TestClient) -> None:
    client_id = _enregistrer(atelier)
    _, defi = _defi()
    r = _autoriser(atelier, client_id, defi, retour="https://ailleurs.exemple/vol")
    assert r.status_code == 400
    r = _consentir(
        atelier, client_id, defi, _cle(atelier), retour="https://ailleurs.exemple/vol"
    )
    assert r.status_code == 400


def test_sans_defi_pkce_rien_n_est_emis(atelier: TestClient) -> None:
    client_id = _enregistrer(atelier)
    r = _autoriser(atelier, client_id, defi="")
    assert r.status_code == 400


def test_le_second_branchement_ne_redemande_pas_la_cle(atelier: TestClient) -> None:
    """L'accord retenu plus le cookie de session : on ne retape pas la clé."""
    client_id = _enregistrer(atelier)
    _, defi = _defi()
    _code_de(_consentir(atelier, client_id, defi, _cle(atelier)))
    # Le client repasse (le TestClient a gardé le cookie de session).
    _, defi2 = _defi()
    r = _autoriser(atelier, client_id, defi2)
    assert r.status_code in (302, 307)
    assert "code=" in r.headers["location"]


# ── La table des clients ────────────────────────────────────────────────────


def test_les_clients_se_listent_et_se_revoquent(atelier: TestClient) -> None:
    """Sans cette liste, la seule sortie était de renouveler la clé."""
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    entete = {"Authorization": f"Bearer {cle}"}
    client_id = _enregistrer(atelier)
    _, defi = _defi()
    _code_de(_consentir(atelier, client_id, defi, cle))

    liste = atelier.get("/v1/oauth/clients", headers=entete).json()["clients"]
    inscrit = next(c for c in liste if c["client_id"] == client_id)
    assert inscrit["nom"] == "Claude"
    assert inscrit["accorde"] is True
    assert inscrit["destinations"] == [RETOUR]

    r = atelier.delete(f"/v1/oauth/clients/{client_id}", headers=entete)
    assert r.status_code == 200
    assert not atelier.get("/v1/oauth/clients", headers=entete).json()["clients"]
    # Débranché pour de bon : son accord est tombé avec lui.
    _, defi2 = _defi()
    assert _autoriser(atelier, client_id, defi2).status_code == 400


def test_la_liste_est_gardee(atelier: TestClient) -> None:
    assert atelier.get("/v1/oauth/clients").status_code == 401
    assert atelier.delete("/v1/oauth/clients/n-importe-quoi").status_code == 401


def test_la_table_des_clients_ne_grossit_pas_sans_fin(atelier: TestClient) -> None:
    """Personne ne prouve rien pour s'enregistrer : il faut donc un plafond."""
    for _ in range(PLAFOND_CLIENTS):
        r = atelier.post("/register", json={"redirect_uris": [RETOUR]})
        if r.status_code != 201:
            break
    r = atelier.post("/register", json={"redirect_uris": [RETOUR]})
    assert r.status_code == 429


def test_le_menage_epargne_ce_qui_a_servi(tmp_path: Path) -> None:
    """Un client jamais reconnu s'efface ; celui qui porte un jeton reste."""
    base = sqlite3.connect(tmp_path / "essai.db")
    base.row_factory = sqlite3.Row
    base.execute("CREATE TABLE IF NOT EXISTS gateway_meta (key TEXT PRIMARY KEY, value TEXT)")
    from mcp_gateway.auth import migrate_auth_schema

    migrate_auth_schema(base)
    base.execute(
        "INSERT INTO oauth_clients (client_id, redirect_uris, client_name, created_at)"
        " VALUES ('inerte', '[]', 'inconnu', datetime('now', '-2 days'))"
    )
    base.execute(
        "INSERT INTO oauth_clients (client_id, redirect_uris, client_name, created_at)"
        " VALUES ('utile', '[]', 'branché', datetime('now', '-2 days'))"
    )
    base.commit()
    issue_token(base, client_id="utile", label="essai")

    assert purger_clients_inertes(base) == 1
    restants = {c["client_id"] for c in lister_clients(base)}
    assert restants == {"utile"}
    base.close()


# ── La rotation emporte ce que la clé a accordé ─────────────────────────────


def test_renouveler_la_cle_revoque_les_jetons(atelier: TestClient) -> None:
    """Une clé se renouvelle parce qu'elle a fui.

    Tant qu'elle n'était pas ce qui consent, ses jetons pouvaient lui survivre.
    Depuis, les laisser vivre, c'est laisser un connecteur branché au nom d'une
    clé qui n'existe plus.
    """
    cle = _cle(atelier)
    client_id = _enregistrer(atelier)
    verifieur, defi = _defi()
    code = _code_de(_consentir(atelier, client_id, defi, cle))
    jeton = atelier.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": RETOUR,
            "client_id": client_id,
            "code_verifier": verifieur,
        },
    ).json()["access_token"]

    entete = {"Authorization": f"Bearer {cle}"}
    assert atelier.get("/v1/oauth/clients", headers=entete).json()["clients"][0]["jetons"] == 1

    neuve = atelier.post("/v1/auth/rotate", headers=entete).json()["owner_key"]
    entete_neuf = {"Authorization": f"Bearer {neuve}"}
    assert atelier.get("/v1/oauth/clients", headers=entete_neuf).json()["clients"][0]["jetons"] == 0

    from mcp_gateway.auth import portee_du_porteur

    assert portee_du_porteur(atelier.app.state.db, jeton, neuve) is None


def test_la_nouvelle_cle_est_celle_que_l_ecran_demande(atelier: TestClient) -> None:
    """Sinon l'ancienne continuerait de consentir après son renouvellement."""
    ancienne = _cle(atelier)
    neuve = atelier.post(
        "/v1/auth/rotate", headers={"Authorization": f"Bearer {ancienne}"}
    ).json()["owner_key"]
    atelier.cookies.clear()

    client_id = _enregistrer(atelier)
    _, defi = _defi()
    assert _consentir(atelier, client_id, defi, ancienne).status_code == 401
    assert _consentir(atelier, client_id, defi, neuve).status_code in (302, 307)


# ── Le jeton ne vaut que pour /mcp ──────────────────────────────────────────


def test_un_jeton_de_client_n_ouvre_pas_l_atelier(atelier: TestClient) -> None:
    """Le seul geste que ce flux prétend accorder est l'accès à `/mcp`.

    Un jeton qui ouvrirait `/v1` donnerait au client distant le pod entier :
    le harnais y lance `claude` en `bypassPermissions`.
    """
    jeton = issue_token(atelier.app.state.db, client_id="essai", label="essai")
    entete = {"Authorization": f"Bearer {jeton}"}
    assert atelier.get("/v1/sessions", headers=entete).status_code == 401
    assert atelier.get("/v1/oauth/clients", headers=entete).status_code == 401


@pytest.mark.parametrize(
    "chemin",
    [
        "/.well-known/oauth-authorization-server",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server/mcp",
        "/.well-known/oauth-protected-resource/mcp",
        "/mcp/.well-known/oauth-authorization-server",
        "/mcp/.well-known/oauth-protected-resource",
    ],
)
def test_les_metadonnees_restent_ouvertes(atelier: TestClient, chemin: str) -> None:
    """Un client MCP les lit avant d'avoir le moindre jeton."""
    assert atelier.get(chemin).status_code == 200


def test_la_ressource_protegee_du_mcp_est_la_porte(atelier: TestClient) -> None:
    """RFC 9728 : le client interpolé `/mcp` dans le well-known.

    Claude Code / Claude Desktop collent l'URL `…/mcp`. Ils demandent alors
    `/.well-known/oauth-protected-resource/mcp`, pas la racine. Sans cette
    page, le flux OAuth part ailleurs — mesuré : 404, puis `/mcp/authorize`
    404, puis GET `/authorize` sans paramètres (400).
    """
    for chemin in (
        "/.well-known/oauth-protected-resource/mcp",
        "/mcp/.well-known/oauth-protected-resource",
    ):
        ressource = atelier.get(chemin).json()
        assert ressource["resource"] == "https://testserver/mcp"
        assert ressource["authorization_servers"] == ["https://testserver"]


def test_le_serveur_d_autorisation_du_mcp_est_le_meme(atelier: TestClient) -> None:
    racine = atelier.get("/.well-known/oauth-authorization-server").json()
    for chemin in (
        "/.well-known/oauth-authorization-server/mcp",
        "/mcp/.well-known/oauth-authorization-server",
    ):
        assert atelier.get(chemin).json() == racine


def test_authorize_sous_mcp_est_la_meme_porte(atelier: TestClient) -> None:
    """Claude Code cherche `/mcp/authorize` une fois collée l'URL `…/mcp`."""
    verifieur, defi = _defi()
    client_id = _enregistrer(atelier)
    via_mcp = atelier.get(
        "/mcp/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": RETOUR,
            "state": "xyz",
            "code_challenge": defi,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    via_racine = _autoriser(atelier, client_id, defi)
    assert via_mcp.status_code == via_racine.status_code == 200
    assert "owner_key" in via_mcp.text
    _ = verifieur


def test_le_consentement_sous_mcp_accorde_aussi(atelier: TestClient) -> None:
    _verifieur, defi = _defi()
    client_id = _enregistrer(atelier)
    r = atelier.post(
        "/mcp/authorize/confirm",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": RETOUR,
            "state": "xyz",
            "code_challenge": defi,
            "code_challenge_method": "S256",
        },
        data={"owner_key": _cle(atelier)},
        follow_redirects=False,
    )
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith(RETOUR)


def test_les_alias_oauth_du_mcp_restent_publics() -> None:
    """Le verrou propriétaire ne doit pas recouvrir le flux, une fois sous `/mcp`."""
    from mcp_gateway.auth import is_public_path

    assert is_public_path("/mcp/authorize")
    assert is_public_path("/mcp/authorize/confirm")
    assert is_public_path("/mcp/.well-known/oauth-protected-resource")
    assert is_public_path("/.well-known/oauth-protected-resource/mcp")
    assert not is_public_path("/mcp")


# ── La porte /mcp ───────────────────────────────────────────────────────────
#
# Le mode factice ne monte pas la passerelle, donc pas la porte. On la monte
# seule, sur une application nue : ce qu'on vérifie est sa garde, pas ce
# qu'elle sert.


@pytest.fixture()
def porte(atelier: TestClient) -> TestClient:
    from fastapi import FastAPI

    from mcp_gateway.atelier.auth import OwnerAuth
    from mcp_gateway.atelier.mcp_endpoint import register_mcp_endpoint

    app = FastAPI()
    app.state.db = atelier.app.state.db
    app.state.host_url = "https://atelier.exemple.fr"
    app.state.mcp = None  # la passerelle n'est pas là : 503 une fois la garde passée
    register_mcp_endpoint(app, OwnerAuth(atelier.app.state.settings))
    return TestClient(app, base_url="https://testserver")


def test_la_porte_suit_aussi_l_ingress(atelier: TestClient) -> None:
    """La porte et les métadonnées doivent désigner le même serveur.

    Si l'une annonce l'hôte par lequel on est arrivé et l'autre un réglage
    figé, le client part chercher son jeton ailleurs qu'à la porte qu'il vient
    de heurter.
    """
    from fastapi import FastAPI

    from mcp_gateway.atelier.auth import OwnerAuth
    from mcp_gateway.atelier.mcp_endpoint import register_mcp_endpoint

    app = FastAPI()
    app.state.db = atelier.app.state.db
    app.state.mcp = None
    register_mcp_endpoint(app, OwnerAuth(atelier.app.state.settings))
    with TestClient(app, base_url="https://testserver") as client:
        r = client.post(
            "/mcp",
            json={"method": "initialize"},
            headers={
                "X-Forwarded-Host": "atelier.user.lab.sspcloud.fr",
                "X-Forwarded-Proto": "https",
            },
        )
    assert r.status_code == 401
    assert "https://atelier.user.lab.sspcloud.fr/.well-known/" in r.headers["www-authenticate"]


def test_sans_jeton_la_porte_dit_ou_demander(porte: TestClient) -> None:
    """Sans cet en-tête, un client MCP ne sait pas où obtenir son jeton.

    Il abandonne, et le branchement reste à faire à la main — ce qui est
    précisément ce qu'on essaie d'éviter.
    """
    r = porte.post("/mcp", json={"method": "initialize"})
    assert r.status_code == 401
    entete = r.headers["www-authenticate"]
    assert 'realm="atelier"' in entete
    assert (
        'resource_metadata="https://atelier.exemple.fr/.well-known/'
        'oauth-protected-resource/mcp"' in entete
    )


def test_un_jeton_consenti_franchit_la_porte(porte: TestClient, atelier: TestClient) -> None:
    """Le 503 est la preuve : la garde est passée, la passerelle manque."""
    jeton = issue_token(atelier.app.state.db, client_id="essai", label="essai")
    r = porte.post(
        "/mcp",
        json={"method": "initialize"},
        headers={"Authorization": f"Bearer {jeton}"},
    )
    assert r.status_code == 503


def test_la_cle_du_proprietaire_franchit_la_porte(porte: TestClient, atelier: TestClient) -> None:
    r = porte.post(
        "/mcp",
        json={"method": "initialize"},
        headers={"Authorization": f"Bearer {_cle(atelier)}"},
    )
    assert r.status_code == 503


def test_un_jeton_invente_ne_franchit_pas(porte: TestClient) -> None:
    r = porte.post(
        "/mcp",
        json={"method": "initialize"},
        headers={"Authorization": "Bearer invente"},
    )
    assert r.status_code == 401
