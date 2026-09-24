"""Le passage de l'Atelier à l'hôte des applications, et les règles du mandataire.

Fonctions pures et base de test : ce fichier tourne partout. Ce qu'il tient :

- un code ne sert qu'une fois, pas au-delà de soixante secondes, et ne mène
  qu'à une destination de l'hôte, sous le projet ouvert ;
- une session d'applications tombe avec la session owner qui l'a ouverte,
  sans qu'on ait à y penser ;
- les réécritures d'en-têtes du mandataire, une par une.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_gateway.atelier.apps import proxy as px
from mcp_gateway.atelier.apps.passage import (
    COOKIE_APPS,
    DUREE_CODE_S,
    Passage,
    destination_valide,
    portee_du_chemin,
    portee_valide,
)
from mcp_gateway.auth import close_owner_session, migrate_auth_schema, open_owner_session
from mcp_gateway.db import connect


class Horloge:
    def __init__(self) -> None:
        self.t = 1_000_000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture()
def base(tmp_path: Path) -> Path:
    return tmp_path / "gateway.db"


def ouvrir_owner(base: Path, duree: int = 3600) -> str:
    conn = connect(base)
    migrate_auth_schema(conn)
    try:
        return open_owner_session(conn, duree)
    finally:
        conn.close()


def fermer_owner(base: Path, sid: str) -> None:
    conn = connect(base)
    try:
        close_owner_session(conn, sid)
    finally:
        conn.close()


# ── Portées et destinations ────────────────────────────────────────────
#
# Une portée est un projet : ses artefacts sont d'un même domaine de
# confiance, et un code ouvert pour un projet ne mène pas à un autre.


@pytest.mark.parametrize("portee", ["demo", "Projet.1", "a-b_c"])
def test_portees_valides(portee: str) -> None:
    assert portee_valide(portee)


@pytest.mark.parametrize("portee", ["", "demo/voix", "..", ".cache", "/demo"])
def test_portees_invalides(portee: str) -> None:
    assert not portee_valide(portee)


def test_la_portee_se_lit_dans_le_chemin() -> None:
    assert portee_du_chemin("/demo/voix/api/x") == "demo"
    assert portee_du_chemin("/demo/@jeton/rapport/") == "demo"
    assert portee_du_chemin("/demo") == "demo"
    assert portee_du_chemin("/_atelier/entree") is None
    assert portee_du_chemin("/") is None


@pytest.mark.parametrize(
    "destination",
    ["/demo/voix/", "/demo", "/demo/voix/page?x=1#y", "/demo/page.html"],
)
def test_destinations_admises(destination: str) -> None:
    assert destination_valide(destination, "demo")


@pytest.mark.parametrize(
    "destination",
    [
        "//evil.example/demo/voix/",
        "https://evil.example/",
        "demo/voix/",
        "/autre/voix/",
        "/demox/voix/",
        "/demo/voix/\\evil",
        "/demo/voix/\r\nSet-Cookie: x",
    ],
)
def test_destinations_refusees(destination: str) -> None:
    assert not destination_valide(destination, "demo")


# ── Codes ──────────────────────────────────────────────────────────────


def test_un_code_ne_sert_qu_une_fois(base: Path) -> None:
    p = Passage(base)
    sid = ouvrir_owner(base)
    code = p.emettre_code(sid, "demo", "/demo/voix/")
    assert len(code) >= 40
    trouve = p.consommer_code(code)
    assert trouve is not None and trouve.portee == "demo" and trouve.parent_sid == sid
    assert p.consommer_code(code) is None
    assert p.consommer_code("") is None


def test_un_code_perime_apres_soixante_secondes(base: Path) -> None:
    horloge = Horloge()
    p = Passage(base, horloge=horloge)
    code = p.emettre_code(ouvrir_owner(base), "demo", "/demo/voix/")
    horloge.t += DUREE_CODE_S + 1
    assert p.consommer_code(code) is None


def test_un_code_ne_s_emet_pas_pour_n_importe_quoi(base: Path) -> None:
    p = Passage(base)
    sid = ouvrir_owner(base)
    with pytest.raises(ValueError):
        p.emettre_code("", "demo", "/demo/voix/")
    with pytest.raises(ValueError):
        p.emettre_code(sid, "demo", "//ailleurs/")
    with pytest.raises(ValueError):
        p.emettre_code(sid, "demo", "/autre/voix/")
    with pytest.raises(ValueError):
        p.emettre_code(sid, "..", "/../x/")


# ── Sessions ───────────────────────────────────────────────────────────


def test_une_session_tombe_avec_sa_session_owner(base: Path) -> None:
    p = Passage(base)
    sid = ouvrir_owner(base)
    session = p.ouvrir(p.consommer_code(p.emettre_code(sid, "demo", "/demo/voix/")))
    assert p.session(session.id).couvre("demo")
    fermer_owner(base, sid)
    assert p.session(session.id) is None


def test_une_session_owner_expiree_emporte_la_sienne(base: Path) -> None:
    p = Passage(base)
    sid = ouvrir_owner(base, duree=-1)
    session = p.ouvrir(p.consommer_code(p.emettre_code(sid, "demo", "/demo/voix/")))
    assert p.session(session.id) is None


def test_une_session_s_elargit_sans_changer_d_identifiant(base: Path) -> None:
    p = Passage(base)
    sid = ouvrir_owner(base)
    premiere = p.ouvrir(p.consommer_code(p.emettre_code(sid, "demo", "/demo/voix/")))
    seconde = p.ouvrir(p.consommer_code(p.emettre_code(sid, "autre", "/autre/")), premiere.id)
    assert seconde.id == premiere.id
    assert p.session(premiere.id).portees == {"demo", "autre"}
    # Née d'une autre session owner : une session neuve, pas un élargissement.
    autre = ouvrir_owner(base)
    troisieme = p.ouvrir(p.consommer_code(p.emettre_code(autre, "demo", "/demo/voix/")), premiere.id)
    assert troisieme.id != premiere.id


def test_une_session_expire_apres_douze_heures(base: Path) -> None:
    horloge = Horloge()
    p = Passage(base, horloge=horloge)
    sid = ouvrir_owner(base, duree=10**9)
    session = p.ouvrir(p.consommer_code(p.emettre_code(sid, "demo", "/demo/voix/")))
    horloge.t += 12 * 3600 + 1
    assert p.session(session.id) is None


def test_fermer_tout(base: Path) -> None:
    p = Passage(base)
    sid = ouvrir_owner(base)
    session = p.ouvrir(p.consommer_code(p.emettre_code(sid, "demo", "/demo/voix/")))
    code = p.emettre_code(sid, "demo", "/demo/voix/")
    p.fermer_tout()
    assert p.session(session.id) is None
    assert p.consommer_code(code) is None


# ── Réécritures du mandataire ──────────────────────────────────────────


def test_entetes_vers_amont() -> None:
    sortie = px.entetes_vers_amont(
        [
            ("Host", "apps"),
            ("Authorization", "Bearer x"),
            ("Cookie", f"a=1; {COOKIE_APPS}=secret; b=2"),
            ("X-Forwarded-For", "6.6.6.6"),
            ("x-atelier-utilisateur", "moi"),
            ("Forwarded", "for=x"),
            ("Connection", "keep-alive, X-Retire"),
            ("X-Retire", "1"),
            ("Transfer-Encoding", "chunked"),
            ("Accept", "text/html"),
        ],
        prefixe="/demo/voix",
        hote_public="apps.test",
        client_ip="10.0.0.1",
    )
    noms = [k.lower() for k, _ in sortie]
    assert "host" not in noms and "authorization" not in noms and "forwarded" not in noms
    assert "x-retire" not in noms and "transfer-encoding" not in noms and "connection" not in noms
    d = dict((k.lower(), v) for k, v in sortie)
    assert d["cookie"] == "a=1; b=2"
    assert d["x-forwarded-for"] == "10.0.0.1"
    assert d["x-forwarded-prefix"] == "/demo/voix"
    assert d["x-atelier-utilisateur"] == "proprietaire"
    assert noms.count("x-forwarded-for") == 1


def test_seul_le_cookie_de_l_hote_est_retire() -> None:
    sortie = px.entetes_vers_amont(
        [("Cookie", f"{COOKIE_APPS}=secret")], prefixe="/d/v", hote_public="h", client_ip=""
    )
    assert "cookie" not in [k.lower() for k, _ in sortie]


@pytest.mark.parametrize(
    "valeur,retire,attendu",
    [
        ("a=1; Path=/; HttpOnly", True, "a=1; Path=/demo/voix/; HttpOnly"),
        ("a=1", True, "a=1; Path=/demo/voix/"),
        ("a=1; Domain=.sspcloud.fr; Path=/x", True, "a=1; Path=/demo/voix/x"),
        ("a=1; Path=/demo/voix/api", False, "a=1; Path=/demo/voix/api"),
        ("a=1; Path=/", False, "a=1; Path=/demo/voix/"),
        ("a=1; Path=/demo/voixx", False, "a=1; Path=/demo/voix/"),
    ],
)
def test_reecrire_cookie(valeur: str, retire: bool, attendu: str) -> None:
    assert px.reecrire_cookie(valeur, prefixe="/demo/voix", chemin_retire=retire) == attendu


@pytest.mark.parametrize("valeur", ["__Host-x=1; Path=/; Secure", f"{COOKIE_APPS}=vol", "=1", "sansegal"])
def test_cookies_refuses(valeur: str) -> None:
    assert px.reecrire_cookie(valeur, prefixe="/demo/voix", chemin_retire=True) is None


def test_reecrire_location() -> None:
    kw = dict(prefixe="/demo/voix", amont="http://127.0.0.1:19001", origine_apps="https://apps.test")
    assert px.reecrire_location("/login", chemin_retire=True, **kw) == "/demo/voix/login"
    assert px.reecrire_location("/demo/voix/login", chemin_retire=False, **kw) == "/demo/voix/login"
    assert (
        px.reecrire_location("http://127.0.0.1:19001/a?b=1", chemin_retire=True, **kw)
        == "https://apps.test/demo/voix/a?b=1"
    )
    assert px.reecrire_location("https://ailleurs/x", chemin_retire=True, **kw) == "https://ailleurs/x"
    assert px.reecrire_location("//ailleurs/x", chemin_retire=True, **kw) == "//ailleurs/x"
    assert px.reecrire_location("relatif", chemin_retire=True, **kw) == "relatif"


def test_entetes_vers_client() -> None:
    sortie = px.entetes_vers_client(
        [
            ("Content-Type", "text/html"),
            ("Service-Worker-Allowed", "/"),
            ("Connection", "close"),
            ("Set-Cookie", "__Host-x=1; Path=/"),
            ("Set-Cookie", "a=1"),
            ("Referrer-Policy", "no-referrer"),
        ],
        prefixe="/demo/voix",
        chemin_retire=True,
        amont="http://127.0.0.1:1",
        origine_apps="https://apps.test",
        origine_atelier="https://atelier.test",
    )
    d: dict[str, list[str]] = {}
    for k, v in sortie:
        d.setdefault(k.decode(), []).append(v.decode())
    assert "service-worker-allowed" not in d and "connection" not in d
    assert d["set-cookie"] == ["a=1; Path=/demo/voix/"]
    assert d["referrer-policy"] == ["no-referrer"]
    assert d["x-content-type-options"] == ["nosniff"]
    assert d["content-security-policy"] == ["frame-ancestors 'self' https://atelier.test"]
    assert d["x-accel-buffering"] == ["no"]


def test_la_garde_meme_site() -> None:
    o = "https://apps.test"
    assert px.refus_meme_site("GET", {"sec-fetch-site": "cross-site"}, o) is None
    assert px.refus_meme_site("POST", {"sec-fetch-site": "same-site"}, o)
    assert px.refus_meme_site("DELETE", {"sec-fetch-site": "cross-site"}, o)
    assert px.refus_meme_site("POST", {"origin": "https://voisin.test"}, o)
    assert px.refus_meme_site("POST", {"origin": "https://apps.test", "sec-fetch-site": "same-origin"}, o) is None
    assert px.refus_meme_site("PUT", {}, o) is None
