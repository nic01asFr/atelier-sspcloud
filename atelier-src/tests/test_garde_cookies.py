"""Ce que le cookie de session autorise, et d'où.

`sspcloud.fr` n'est pas dans la liste des suffixes publics : le service d'un
autre utilisateur sous `*.user.lab.sspcloud.fr` est « même site » que
l'Atelier, et `SameSite=Lax` le laissait joindre notre cookie à un POST. Seule
l'origine exacte départage désormais l'interface d'un voisin.

L'interface, de son côté, ne garde plus la clé : elle l'échange une fois
contre ce cookie, puis parle à l'API par lui et par l'en-tête
`X-Atelier-Interface`, qu'aucune autre origine ne peut poser.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_gateway.atelier.vscode_bridge import COOKIE_ANCIEN, COOKIE_NAME

INTERFACE = {"X-Atelier-Interface": "1", "Sec-Fetch-Site": "same-origin"}


def _cle(atelier: TestClient) -> str:
    return atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()


def _ouvrir(atelier: TestClient) -> str:
    r = atelier.post("/v1/auth/cookie", headers={"Authorization": f"Bearer {_cle(atelier)}"})
    assert r.status_code == 200
    return r.headers["set-cookie"]


def test_le_cookie_est_un_cookie_host(atelier: TestClient) -> None:
    """`__Host-` : Secure, Path=/, sans Domain — un voisin ne peut le poser."""
    entete = _ouvrir(atelier)
    assert entete.startswith(f"{COOKIE_NAME}=")
    assert COOKIE_NAME.startswith("__Host-")
    bas = entete.lower()
    assert "secure" in bas and "httponly" in bas and "path=/" in bas
    assert "samesite=lax" in bas
    assert "domain=" not in bas


def test_un_post_d_un_voisin_avec_le_cookie_est_refuse(atelier: TestClient) -> None:
    _ouvrir(atelier)
    r = atelier.post("/pilote/api/x", headers={"Sec-Fetch-Site": "same-site"})
    assert r.status_code == 403
    r = atelier.post(
        "/pilote/api/x", headers={"Origin": "https://voisin.user.lab.sspcloud.fr"}
    )
    assert r.status_code == 403


def test_le_meme_post_depuis_l_atelier_passe_la_garde(atelier: TestClient) -> None:
    """503 : le pilote n'existe pas en mode factice — mais la garde est passée."""
    _ouvrir(atelier)
    r = atelier.post("/pilote/api/x", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.status_code == 503
    r = atelier.post("/pilote/api/x", headers={"Origin": "https://testserver"})
    assert r.status_code == 503


def test_la_cle_au_porteur_n_a_pas_besoin_d_origine(atelier: TestClient) -> None:
    """Un client hors navigateur (CLI, MCP) n'envoie ni Origin ni Sec-Fetch."""
    _ouvrir(atelier)  # même avec un cookie présent
    r = atelier.post(
        "/pilote/api/x", headers={"Authorization": f"Bearer {_cle(atelier)}"}
    )
    assert r.status_code == 503


def test_un_get_qui_lance_un_tour_ne_vient_que_de_l_atelier(atelier: TestClient) -> None:
    """`?message=` lance un tour : un lien posé ailleurs ne doit pas le faire."""
    _ouvrir(atelier)
    chemin = "/v1/sessions/inexistante/events?message=rm"
    assert atelier.get(chemin, headers={"Sec-Fetch-Site": "same-site"}).status_code == 403
    assert atelier.get(chemin, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert atelier.get(chemin).status_code == 403  # sans Sec-Fetch non plus
    assert atelier.get(chemin, headers={"Sec-Fetch-Site": "same-origin"}).status_code == 404


def test_l_api_veut_le_cookie_et_l_en_tete_de_l_interface(atelier: TestClient) -> None:
    """Le cookie seul — celui d'un formulaire ou d'une image — ne suffit pas."""
    _ouvrir(atelier)
    assert atelier.get("/v1/meta").status_code == 401
    assert atelier.get("/v1/meta", headers=INTERFACE).status_code == 200


def test_une_cle_fausse_ne_retombe_pas_sur_le_cookie(atelier: TestClient) -> None:
    _ouvrir(atelier)
    r = atelier.get("/v1/meta", headers={**INTERFACE, "Authorization": "Bearer faux"})
    assert r.status_code == 401


def test_la_session_ne_s_ouvre_qu_avec_la_cle(atelier: TestClient) -> None:
    """Une session n'en ouvre pas une autre : l'échange se fait contre la clé."""
    _ouvrir(atelier)
    assert atelier.post("/v1/auth/cookie", headers=INTERFACE).status_code == 401


def test_l_ancien_cookie_est_lu_une_fois_puis_remplace(atelier: TestClient) -> None:
    sid = _ouvrir(atelier).split(";", 1)[0].split("=", 1)[1]
    atelier.cookies.clear()
    r = atelier.get("/v1/meta", headers={**INTERFACE, "Cookie": f"{COOKIE_ANCIEN}={sid}"})
    assert r.status_code == 200
    poses = r.headers.get_list("set-cookie")
    assert any(p.startswith(f"{COOKIE_NAME}={sid}") and "Secure" in p for p in poses)
    assert any(p.startswith(f"{COOKIE_ANCIEN}=") and "Max-Age=0" in p for p in poses)


def test_se_deconnecter_efface_le_cookie_host(atelier: TestClient) -> None:
    _ouvrir(atelier)
    r = atelier.delete("/v1/auth/cookie", headers={"Sec-Fetch-Site": "same-origin"})
    assert r.json()["session_fermee"] == "oui"
    efface = [p for p in r.headers.get_list("set-cookie") if p.startswith(COOKIE_NAME)]
    # Sans `Secure`, le navigateur ignorerait l'effacement d'un cookie `__Host-`.
    assert efface and "secure" in efface[0].lower()


def test_la_csp_protege_l_interface_et_autorise_le_widget_atlas(atelier: TestClient) -> None:
    r = atelier.get("/")
    if r.status_code == 200:
        csp = r.headers["content-security-policy"]
        assert "frame-src 'self' https://nic01asfr.github.io" in csp
        assert "frame-ancestors 'self'" in csp
