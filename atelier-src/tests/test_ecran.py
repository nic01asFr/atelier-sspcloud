"""L'écran en direct du navigateur d'une conversation (P5, J-f2) et la main de la personne.

Éprouvé avec un vrai serveur de l'hôte des applications, dans son fil, et un
faux Chrome côté DevTools (`faux_cdp.py`) qui se comporte comme Chrome : pages,
rattachement, screencast acquitté image par image. La fiche que publierait le
filtre du lanceur est écrite à la main (le filtre a ses propres tests,
`test_filtre_ecran.py`) ; l'essai contre un vrai Chrome est dans
`test_ecran_chrome_reel.py`.

Ce qui est vérifié est ce que verrait la personne et ce que verrait Chrome :
une session ouverte pour une conversation n'en ouvre aucune autre ; ni le
port ni le chemin DevTools n'arrivent au navigateur ; l'écran suit la page que
l'agent sélectionne ; rien ne tourne quand personne ne regarde ; un geste
n'arrive à Chrome que main prise ; rendre la main laisse une note, ou relance
l'agent.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import websockets
from fastapi.testclient import TestClient

from faux_cdp import CHEMIN, FauxChrome  # noqa: E402 — dossier des tests, sur sys.path
from test_bureaux import Serveur, port_libre  # noqa: E402

from mcp_gateway.atelier import ecran as module_ecran
from mcp_gateway.atelier.apps.passage import (
    COOKIE_APPS,
    Passage,
    conversation_de_portee,
    destination_valide,
    portee_conversation,
    portee_du_chemin,
    portee_valide,
    racine_de_portee,
)
from mcp_gateway.atelier.apps.serveur import construire_app_apps
from mcp_gateway.atelier.apps.service import ServiceApps
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.ecran import (
    Ecrans,
    EcranIndisponible,
    choisir_la_page,
    commande_d_entree,
    lire_fiche,
    lire_main,
    page_a_change,
    phrase_de_reprise,
)
from mcp_gateway.auth import migrate_auth_schema, open_owner_session
from mcp_gateway.db import connect

ATELIER = "https://atelier.test"


def publier(racine: Path, conversation: str, port: int, *, page: dict[str, str] | None = None,
            attente: int = 0, pid: int | None = None, **autres: Any) -> Path:
    """La fiche que publie le filtre du lanceur."""
    dossier = racine / "ecrans"
    dossier.mkdir(parents=True, exist_ok=True)
    fiche = {"version": 1, "conversation": conversation, "pid": pid or os.getpid(), "port": port,
             "chemin": CHEMIN, "page": page, "attente": attente, **autres}
    chemin = dossier / f"{conversation}.json"
    # D'un coup, comme le filtre : une fiche lue à moitié ferait croire Chrome parti.
    provisoire = dossier / f".{conversation}.tmp"
    provisoire.write_text(json.dumps(fiche), encoding="utf-8")
    if os.name == "posix":
        provisoire.chmod(0o600)
    os.replace(provisoire, chemin)
    return chemin


class Monte:
    def __init__(self, service: ServiceApps, hote: Serveur, chrome: FauxChrome, racine: Path) -> None:
        self.service = service
        self.hote = hote
        self.chrome = chrome
        self.racine = racine
        self.base = hote.base
        self.ecrans: Ecrans = service.ecrans


@pytest.fixture()
def monte(tmp_path: Path) -> Iterator[Monte]:
    chrome = FauxChrome({"T1": "https://a.test/", "T2": "https://b.test/"})
    racine = tmp_path / "racine"
    port = port_libre()
    settings = AtelierSettings(work_dir=tmp_path / "work", apps_public_url=f"http://127.0.0.1:{port}", public_url=ATELIER)
    settings.ensure_dirs()
    site = settings.projects_dir / "demo" / "artifacts" / "site"
    site.mkdir(parents=True)
    (site / "index.html").write_text("<h1>site</h1>", encoding="utf-8")
    service = ServiceApps(settings)
    ecrans = Ecrans(racine, cadence=30)
    ecrans.connue = lambda c: c in {"conv-a", "conv-b"}
    service.ecrans = ecrans
    app = construire_app_apps(service, origine_atelier=lambda: ATELIER, secret_artefacts=lambda: b"secret")
    hote = Serveur(app, port)
    publier(racine, "conv-a", chrome.port, page={"url": "https://b.test/", "titre": "B"})
    try:
        yield Monte(service, hote, chrome, racine)
    finally:
        hote.fermer()
        chrome.fermer()


def session_owner(m: Monte) -> str:
    conn = connect(m.service.settings.gateway_db_path)
    migrate_auth_schema(conn)
    try:
        return open_owner_session(conn, 3600)
    finally:
        conn.close()


def entrer(m: Monte, portee: str, destination: str) -> str:
    code = m.service.passage.emettre_code(session_owner(m), portee, destination)
    r = httpx.get(f"{m.base}/_atelier/entree", params={"code": code})
    assert r.status_code == 302, r.text
    for valeur in r.headers.get_list("set-cookie"):
        if valeur.startswith(COOKIE_APPS + "="):
            return valeur.split(";", 1)[0].split("=", 1)[1]
    raise AssertionError("pas de cookie de session posé")


def entrer_ecran(m: Monte, conversation: str = "conv-a") -> str:
    return entrer(m, portee_conversation(conversation), f"/_ecran/{conversation}/")


def client(cookie: str | None) -> httpx.Client:
    entetes = {"Cookie": f"{COOKIE_APPS}={cookie}"} if cookie else {}
    return httpx.Client(headers=entetes, timeout=30, trust_env=False, follow_redirects=False)


def flux(m: Monte, cookie: str | None, conversation: str = "conv-a", origine: str | None = "defaut") -> Any:
    entetes = [("Cookie", f"{COOKIE_APPS}={cookie}")] if cookie else []
    return websockets.connect(
        f"ws://127.0.0.1:{m.hote.port}/_ecran/{conversation}/flux",
        origin=(m.base if origine == "defaut" else origine),
        additional_headers=entetes,
        open_timeout=10,
        max_size=None,
    )


class Spectateur:
    """Ce que la page reçoit : des états et des images, gardés dans l'ordre."""

    def __init__(self, ws: Any) -> None:
        self.ws = ws
        self.textes: list[str] = []
        self.images: list[bytes] = []

    async def jusqua(self, condition: Any, delai: float = 10.0) -> None:
        fin = time.monotonic() + delai
        while not condition(self):
            reste = fin - time.monotonic()
            if reste <= 0:
                raise AssertionError(f"jamais vu ; textes : {self.textes[-5:]} ; images : {self.images[-3:]}")
            try:
                recu = await asyncio.wait_for(self.ws.recv(), reste)
            except asyncio.TimeoutError:
                continue
            if isinstance(recu, bytes):
                self.images.append(recu)
            else:
                self.textes.append(recu)

    def etats(self) -> list[dict[str, Any]]:
        return [json.loads(t) for t in self.textes if json.loads(t).get("type") == "etat"]

    def dernier_etat(self) -> dict[str, Any]:
        etats = self.etats()
        return etats[-1] if etats else {}

    def refus(self) -> list[str]:
        return [json.loads(t)["raison"] for t in self.textes if json.loads(t).get("type") == "refus"]

    async def envoyer(self, objet: dict[str, Any]) -> None:
        await self.ws.send(json.dumps(objet))


def image_de(cible: str):
    return lambda s: bool(s.images) and s.images[-1].startswith(f"JPEG:{cible}:".encode())


# ── La portée « conversation » ─────────────────────────────────────────


def test_les_portees_de_conversation() -> None:
    assert portee_conversation("conv-a") == "conversation:conv-a"
    assert conversation_de_portee("conversation:conv-a") == "conv-a"
    assert conversation_de_portee("connecteur:conv-a") is None and conversation_de_portee("demo") is None
    assert portee_valide("conversation:conv-a") and not portee_valide("conversation:../x")
    assert racine_de_portee("conversation:conv-a") == "/_ecran/conv-a"
    assert portee_du_chemin("/_ecran/conv-a/flux") == "conversation:conv-a"
    assert portee_du_chemin("/_ecran/..%2F/") is None
    assert destination_valide("/_ecran/conv-a/", "conversation:conv-a")
    assert not destination_valide("/_ecran/conv-b/", "conversation:conv-a")
    assert not destination_valide("/_ecran/conv-a/../conv-b/", "conversation:conv-a")
    assert not destination_valide("/demo/site/", "conversation:conv-a")
    for mauvais in ("", ".", "..", "-x", "a/b", "a" * 121):
        with pytest.raises(ValueError):
            portee_conversation(mauvais)


def test_un_agent_ne_recoit_jamais_l_ecran_d_une_conversation(tmp_path: Path) -> None:
    passage = Passage(tmp_path / "base.sqlite")
    with pytest.raises(ValueError):
        passage.emettre_code_agent("agent:conv-a", "conversation:conv-a", "/_ecran/conv-a/")


def test_une_session_d_ecran_n_ouvre_que_sa_conversation(monte: Monte) -> None:
    cookie = entrer_ecran(monte, "conv-a")
    with client(cookie) as c:
        r = c.get(f"{monte.base}/_ecran/conv-a/", headers={"Sec-Fetch-Mode": "navigate"})
        assert r.status_code == 200 and "Navigateur de l'agent" in r.text
        # Une autre conversation, un projet : retour à l'Atelier pour un code.
        for chemin in ("/_ecran/conv-b/", "/demo/site/", "/_ecran/conv-b/ecran.js"):
            r = c.get(f"{monte.base}{chemin}", headers={"Sec-Fetch-Mode": "navigate"})
            assert r.status_code in (302, 401), (chemin, r.status_code)
            if r.status_code == 302:
                assert r.headers["location"].startswith(f"{ATELIER}/v1/apps/entree?"), chemin
    # Une session de projet n'ouvre aucun écran.
    projet = entrer(monte, "demo", "/demo/site/")
    with client(projet) as c:
        assert c.get(f"{monte.base}/_ecran/conv-a/", headers={"Sec-Fetch-Mode": "navigate"}).status_code == 302


def test_le_flux_refuse_autre_conversation_origine_et_session(monte: Monte) -> None:
    cookie_a = entrer_ecran(monte, "conv-a")
    cookie_projet = entrer(monte, "demo", "/demo/site/")

    async def refuse(**kw: Any) -> None:
        with pytest.raises((websockets.InvalidStatus, websockets.ConnectionClosed)):
            async with flux(monte, **kw) as ws:
                await ws.recv()

    async def scenario() -> None:
        await refuse(cookie=cookie_a, conversation="conv-b")
        await refuse(cookie=cookie_a, origine=None)
        await refuse(cookie=cookie_a, origine="https://voisin.user.lab.sspcloud.fr")
        await refuse(cookie=cookie_a, origine=ATELIER)
        await refuse(cookie=None)
        await refuse(cookie=cookie_projet)

    asyncio.run(scenario())
    assert monte.chrome.connexions == 0, "aucun refus n'a touché Chrome"


# ── Ce qui passe côté navigateur ───────────────────────────────────────


def test_ni_port_ni_chemin_devtools_cote_navigateur(monte: Monte) -> None:
    cookie = entrer_ecran(monte)
    port = str(monte.chrome.port)
    with client(cookie) as c:
        for fichier in ("", "ecran.js", "ecran.css"):
            r = c.get(f"{monte.base}/_ecran/conv-a/{fichier}")
            assert r.status_code == 200, fichier
            assert port not in r.text and "/devtools/" not in r.text.lower()
        csp = " ".join(r.headers.get_list("content-security-policy"))
        assert "frame-ancestors https://atelier.test" in csp

    async def scenario() -> None:
        async with flux(monte, cookie) as ws:
            s = Spectateur(ws)
            await s.jusqua(image_de("T2"))
            await s.jusqua(lambda s: s.dernier_etat().get("url") == "https://b.test/")
            for texte in s.textes:
                assert port not in texte and "/devtools/" not in texte.lower() and CHEMIN not in texte
                assert "pid" not in json.loads(texte)

    asyncio.run(scenario())
    etat = monte.ecrans.etat("conv-a")
    assert etat["disponible"] is True and etat["url"] == "https://b.test/"
    assert port not in json.dumps(etat) and "chemin" not in etat and "port" not in etat


# ── Suivre la page de l'agent ──────────────────────────────────────────


def test_l_ecran_suit_la_page_selectionnee_par_l_agent(monte: Monte) -> None:
    cookie = entrer_ecran(monte)

    async def scenario() -> None:
        async with flux(monte, cookie) as ws:
            s = Spectateur(ws)
            await s.jusqua(image_de("T2"))
            # L'agent sélectionne l'autre onglet (select_page) : le filtre le publie.
            publier(monte.racine, "conv-a", monte.chrome.port, page={"url": "https://a.test/", "titre": "A"})
            await s.jusqua(image_de("T1"))
            await s.jusqua(lambda s: s.dernier_etat().get("url") == "https://a.test/")
            # La page suivie change d'adresse sans nouvelle liste (un lien cliqué) : on la garde.
            await asyncio.to_thread(monte.chrome.naviguer, "T1", "https://a.test/suite", "Suite")
            await s.jusqua(lambda s: s.dernier_etat().get("url") == "https://a.test/suite")
            assert s.dernier_etat().get("titre") == "Suite"
            await s.jusqua(image_de("T1"))
            # Un nouvel onglet (new_page), sélectionné : on le suit.
            await asyncio.to_thread(monte.chrome.ouvrir, "T3", "https://c.test/")
            publier(monte.racine, "conv-a", monte.chrome.port, page={"url": "https://c.test/", "titre": ""})
            await s.jusqua(image_de("T3"))

    asyncio.run(scenario())
    # Chaque changement de page a détaché la précédente.
    assert len(monte.chrome.methodes("Target.detachFromTarget")) >= 2


def test_choisir_la_page() -> None:
    pages = {"A": {"url": "https://x/", "vu": 1.0}, "B": {"url": "https://x/", "vu": 2.0}, "C": {"url": "https://y/", "vu": 3.0}}
    assert choisir_la_page(pages, {"url": "https://y/"}, "A") == "C"
    assert choisir_la_page(pages, {"url": "https://x/"}, "A") == "A", "on garde la page suivie de même adresse"
    assert choisir_la_page(pages, {"url": "https://x/"}, None) == "B", "sinon la plus récemment vue"
    assert choisir_la_page(pages, {"url": "https://z/"}, "A") == "A", "adresse inconnue : on ne bouge pas"
    assert choisir_la_page(pages, None, "disparue") == "C"
    assert choisir_la_page({}, {"url": "https://x/"}, None) is None


# ── Personne ne regarde : rien ne tourne ───────────────────────────────


def test_personne_ne_regarde_rien_ne_tourne(monte: Monte) -> None:
    cookie = entrer_ecran(monte)
    time.sleep(0.3)
    assert monte.chrome.connexions == 0, "pas de connexion à Chrome sans spectateur"

    async def regarder() -> None:
        async with flux(monte, cookie) as ws:
            await Spectateur(ws).jusqua(image_de("T2"))

    asyncio.run(regarder())
    # Le dernier spectateur parti : la connexion se ferme, le screencast s'arrête.
    monte.chrome.attendre(lambda: monte.chrome.ouvertes == 0)
    n = len(monte.chrome.methodes("Page.screencastFrameAck"))
    time.sleep(0.5)
    assert len(monte.chrome.methodes("Page.screencastFrameAck")) == n, "plus aucune image acquittée"
    assert monte.chrome.methodes("Page.stopScreencast"), "arrêt demandé proprement"


def test_la_cadence_est_bornee_par_l_acquittement(tmp_path: Path, monte: Monte) -> None:
    monte.ecrans.cadence = 5
    cookie = entrer_ecran(monte)

    async def regarder() -> None:
        async with flux(monte, cookie) as ws:
            s = Spectateur(ws)
            await s.jusqua(image_de("T2"))
            debut = len(monte.chrome.methodes("Page.screencastFrameAck"))
            await asyncio.sleep(1.2)
            fait = len(monte.chrome.methodes("Page.screencastFrameAck")) - debut
            # Le faux Chrome enverrait 50 images par seconde ; on en acquitte au plus 5.
            assert fait <= 8, fait

    asyncio.run(regarder())


def test_sans_navigateur_ouvert_la_page_le_dit(monte: Monte) -> None:
    (monte.racine / "ecrans" / "conv-a.json").unlink()
    cookie = entrer_ecran(monte)

    async def scenario() -> None:
        async with flux(monte, cookie) as ws:
            s = Spectateur(ws)
            await s.jusqua(lambda s: "pas ouvert" in (s.dernier_etat().get("raison") or ""))
            assert s.dernier_etat()["disponible"] is False
            # Le navigateur s'ouvre (premier outil de l'agent) : l'écran s'y rattache seul.
            publier(monte.racine, "conv-a", monte.chrome.port, page={"url": "https://a.test/"})
            await s.jusqua(image_de("T1"))

    asyncio.run(scenario())


# ── La main ────────────────────────────────────────────────────────────


def test_un_geste_n_arrive_a_chrome_que_main_prise(monte: Monte) -> None:
    cookie = entrer_ecran(monte)
    clic = {"type": "souris", "action": "presse", "x": 0.5, "y": 0.25, "bouton": "gauche", "clics": 1}

    async def scenario() -> None:
        async with flux(monte, cookie) as ws:
            s = Spectateur(ws)
            await s.jusqua(image_de("T2"))
            await s.envoyer(clic)
            await s.jusqua(lambda s: bool(s.refus()))
            assert "Prenez la main" in s.refus()[0]
            assert not monte.chrome.methodes("Input.dispatchMouseEvent")

            await s.envoyer({"type": "main", "prendre": True})
            await s.jusqua(lambda s: s.dernier_etat().get("main") is True)
            assert lire_main(monte.racine, "conv-a")["prise"] is True
            await s.envoyer(clic)
            await s.envoyer({"type": "clavier", "action": "bas", "key": "a", "code": "KeyA", "texte": "a"})
            await s.envoyer({"type": "texte", "texte": "bonjour"})
            await s.envoyer({"type": "aller", "url": "javascript:alert(1)"})
            await s.envoyer({"type": "aller", "url": "https://connexion.test/"})
            await asyncio.to_thread(monte.chrome.attendre, lambda: monte.chrome.methodes("Page.navigate"))
            souris = monte.chrome.methodes("Input.dispatchMouseEvent")[0]
            assert souris["params"]["x"] == 640 and souris["params"]["y"] == 180, "fraction de l'image, en pixels de la page"
            assert souris["sessionId"].startswith("S-T2-"), "sur la page affichée"
            touche = monte.chrome.methodes("Input.dispatchKeyEvent")[0]["params"]
            assert touche["type"] == "keyDown" and touche["text"] == "a"
            assert monte.chrome.methodes("Input.insertText")[0]["params"]["text"] == "bonjour"
            navigations = [r["params"]["url"] for r in monte.chrome.methodes("Page.navigate")]
            assert navigations == ["https://connexion.test/"], "javascript: n'atteint jamais Chrome"

            await s.envoyer({"type": "main", "prendre": False})
            await s.jusqua(lambda s: s.dernier_etat().get("main") is False)

    asyncio.run(scenario())
    # Aucun tour en cours, aucune relance possible ici : la note attend le prochain outil.
    main = lire_main(monte.racine, "conv-a")
    assert main["prise"] is False and "Note de l'Atelier" in main["note"]
    assert "https://b.test/" in main["note"]


def test_rendre_la_main_relance_l_agent_s_il_ne_travaille_pas(monte: Monte) -> None:
    relances: list[tuple[str, str]] = []
    monte.ecrans.relancer = lambda c, m: relances.append((c, m)) or True
    monte.ecrans.prendre_la_main("conv-a")
    time.sleep(0.01)
    rendu = monte.ecrans.rendre_la_main("conv-a")
    assert rendu["reprise"] == "relance" and rendu["main"] is False
    assert relances and relances[0][0] == "conv-a"
    assert relances[0][1].startswith("J'ai pris la main sur ton navigateur")
    assert lire_main(monte.racine, "conv-a") is None, "pas de note en double"


def test_rendre_la_main_laisse_une_note_quand_l_agent_attend_ou_travaille(monte: Monte) -> None:
    relances: list[Any] = []
    monte.ecrans.relancer = lambda c, m: relances.append(m) or True
    # Des actions de l'agent attendent dans le filtre : elles portent la note.
    publier(monte.racine, "conv-a", monte.chrome.port, page={"url": "https://b.test/"}, attente=1)
    monte.ecrans.prendre_la_main("conv-a")
    assert monte.ecrans.rendre_la_main("conv-a")["reprise"] == "note"
    # Un tour travaille : la note partira avec son prochain outil du navigateur.
    publier(monte.racine, "conv-a", monte.chrome.port, page={"url": "https://b.test/"})
    monte.ecrans.tour_en_cours = lambda c: True
    monte.ecrans.prendre_la_main("conv-a")
    assert monte.ecrans.rendre_la_main("conv-a")["reprise"] == "note"
    assert relances == []
    assert "Note de l'Atelier" in lire_main(monte.racine, "conv-a")["note"]


def test_rendre_la_main_dit_au_filtre_si_la_page_a_change(monte: Monte) -> None:
    """Essais du 26/09 : un clic retenu (uid de la page d'avant) a été joué sur la nouvelle page.

    La main rendue dit au filtre si la page a changé (adresse ou titre) ; c'est
    lui qui refuse alors les actions par `uid` (`test_filtre_ecran.py`).
    """
    monte.ecrans.tour_en_cours = lambda c: True
    publier(monte.racine, "conv-a", monte.chrome.port, page={"url": "https://b.test/", "titre": "B"}, attente=1)
    monte.ecrans.prendre_la_main("conv-a")
    monte.ecrans.rendre_la_main("conv-a")
    assert lire_main(monte.racine, "conv-a")["page_changee"] is False, "même page : rien ne change"

    monte.ecrans.prendre_la_main("conv-a")
    monte.ecrans._page_vue("conv-a", {"url": "https://c.test/", "titre": "C"})
    monte.ecrans.rendre_la_main("conv-a")
    assert lire_main(monte.racine, "conv-a")["page_changee"] is True, "autre adresse"

    monte.ecrans.prendre_la_main("conv-a")
    monte.ecrans._page_vue("conv-a", {"url": "https://c.test/", "titre": "C, connecté"})
    monte.ecrans.rendre_la_main("conv-a")
    assert lire_main(monte.racine, "conv-a")["page_changee"] is True, "même adresse, autre titre"


def test_page_a_change() -> None:
    a = {"url": "https://a.test/", "titre": "A"}
    assert page_a_change(a, dict(a)) is False
    assert page_a_change(None, None) is False
    assert page_a_change(a, None) is True and page_a_change(None, a) is True
    assert page_a_change(a, {"url": "https://a.test/", "titre": "A2"}) is True


def test_prendre_la_main_sans_navigateur_est_refuse(monte: Monte) -> None:
    (monte.racine / "ecrans" / "conv-a.json").unlink()
    with pytest.raises(EcranIndisponible):
        monte.ecrans.prendre_la_main("conv-a")
    assert lire_main(monte.racine, "conv-a") is None


def test_quitter_l_ecran_sans_rendre_la_main_la_rend(monkeypatch: pytest.MonkeyPatch, monte: Monte) -> None:
    monkeypatch.setattr(module_ecran, "MAIN_ABANDON_S", 0.3)
    cookie = entrer_ecran(monte)

    async def scenario() -> None:
        async with flux(monte, cookie) as ws:
            s = Spectateur(ws)
            await s.envoyer({"type": "main", "prendre": True})
            await s.jusqua(lambda s: s.dernier_etat().get("main") is True)

    asyncio.run(scenario())
    fin = time.monotonic() + 5
    while time.monotonic() < fin and (lire_main(monte.racine, "conv-a") or {}).get("prise") is not False:
        time.sleep(0.05)
    main = lire_main(monte.racine, "conv-a")
    assert main["prise"] is False and "quitté l'écran" in main["note"]


def test_la_phrase_de_reprise_dit_ce_qui_a_change() -> None:
    avant = {"url": "https://a.test/connexion", "titre": "Connexion"}
    apres = {"url": "https://a.test/compte", "titre": "Mon compte"}
    note = phrase_de_reprise(avant, apres, 125, pour="note")
    assert "2 min 05 s" in note and "« Mon compte » (https://a.test/compte)" in note
    assert "C'était « Connexion »" in note and "take_snapshot" in note
    message = phrase_de_reprise(avant, avant, 3, pour="message")
    assert message.startswith("J'ai pris la main") and "C'était" not in message


# ── Gestes : ce qui passe, ce qui ne passe pas ─────────────────────────


@pytest.mark.parametrize(
    "geste",
    [
        {"type": "souris", "action": "presse", "x": 1.5, "y": 0.2},
        {"type": "souris", "action": "presse", "x": float("nan"), "y": 0.2},
        {"type": "souris", "action": "vole", "x": 0.1, "y": 0.2},
        {"type": "souris", "action": "molette", "x": 0.1, "y": 0.2, "dx": 0, "dy": 10**9},
        {"type": "clavier", "action": "bas", "key": "a" * 40, "code": "KeyA"},
        {"type": "clavier", "action": "bas", "key": "a", "code": "KeyA", "texte": "abcdef"},
        {"type": "texte", "texte": ""},
        {"type": "aller", "url": "file:///etc/passwd"},
        {"type": "aller", "url": "chrome://settings"},
        {"type": "evaluer", "expression": "document.cookie"},
        {"type": "Runtime.evaluate"},
    ],
)
def test_un_geste_invalide_n_est_pas_traduit(geste: dict[str, Any]) -> None:
    assert commande_d_entree(geste, (1280, 720)) is None


def test_un_geste_valide_est_traduit() -> None:
    methode, params = commande_d_entree(
        {"type": "souris", "action": "molette", "x": 0.25, "y": 1, "dx": 0, "dy": 120, "mod": 8}, (1280, 720)
    )
    assert methode == "Input.dispatchMouseEvent"
    assert params == {"type": "mouseWheel", "x": 320.0, "y": 720.0, "modifiers": 8, "deltaX": 0.0, "deltaY": 120.0}
    methode, params = commande_d_entree({"type": "clavier", "action": "bas", "key": "Enter", "code": "Enter", "texte": "\r", "touche": 13}, (1, 1))
    assert params["type"] == "keyDown" and params["windowsVirtualKeyCode"] == 13
    _, params = commande_d_entree({"type": "clavier", "action": "bas", "key": "ArrowLeft", "code": "ArrowLeft"}, (1, 1))
    assert params["type"] == "rawKeyDown"


# ── La fiche du filtre : lue seulement si elle est sûre ────────────────


def test_une_fiche_douteuse_n_est_pas_lue(tmp_path: Path) -> None:
    racine = tmp_path / "racine"
    publier(racine, "conv-a", 9222)
    assert lire_fiche(racine, "conv-a") is not None
    for defaut in ({"version": 2}, {"port": 0}, {"port": "9222"}, {"chemin": "/json/version"},
                   {"chemin": "/devtools/browser/../x"}, {"conversation": "conv-b"}):
        chemin = publier(racine, "conv-a", 9222)
        fiche = json.loads(chemin.read_text(encoding="utf-8"))
        fiche.update(defaut)
        chemin.write_text(json.dumps(fiche), encoding="utf-8")
        assert lire_fiche(racine, "conv-a") is None, defaut
    assert lire_fiche(racine, "../conv-a") is None
    if os.name == "posix":
        chemin = publier(racine, "conv-a", 9222)
        chemin.chmod(0o644)
        assert lire_fiche(racine, "conv-a") is None, "lisible par d'autres : ignorée"
        publier(racine, "conv-a", 9222, pid=999999)
        assert lire_fiche(racine, "conv-a") is None, "filtre mort : ignorée"


def test_la_fiche_se_trouve_aussi_sous_l_identifiant_du_cli(tmp_path: Path) -> None:
    racine = tmp_path / "racine"
    ecrans = Ecrans(racine)
    ecrans.alias = lambda c: ["cli-1234"] if c == "conv-a" else []
    publier(racine, "cli-1234", 9222, page={"url": "https://x.test/"})
    assert ecrans.fiche("conv-a").cle == "cli-1234"
    ecrans.prendre_la_main("conv-a")
    assert lire_main(racine, "cli-1234")["prise"] is True, "la main suit le nom sous lequel le filtre lit"


# ── Côté Atelier : l'ouverture et l'état ───────────────────────────────


@pytest.fixture()
def atelier(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from mcp_gateway.atelier.api import build_app

    monkeypatch.setenv("ATELIER_CHROME_RACINE", str(tmp_path / "racine"))
    settings = AtelierSettings(work_dir=tmp_path / "work", apps_public_url="https://apps.test", public_url="https://testserver")
    settings.ensure_dirs()
    with TestClient(build_app(settings=settings, use_fake=True), base_url="https://testserver") as c:
        yield c


def _porteur(c: TestClient) -> dict[str, str]:
    cle = c.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def _conversation(c: TestClient) -> str:
    r = c.post("/v1/sessions", json={"slug": "demo"}, headers=_porteur(c))
    if r.status_code >= 400:
        r = c.post("/v1/sessions", json={}, headers=_porteur(c))
    assert r.status_code < 400, r.text
    return r.json()["session_id"]


def test_ouvrir_l_ecran_emet_un_code_de_la_seule_conversation(atelier: TestClient) -> None:
    conv = _conversation(atelier)
    atelier.post("/v1/auth/cookie", headers=_porteur(atelier))
    r = atelier.get(f"/v1/ecran/{conv}/ouvrir", follow_redirects=False)
    assert r.status_code == 302, r.text
    vers = urlsplit(r.headers["location"])
    assert f"{vers.scheme}://{vers.netloc}" == "https://apps.test" and vers.path == "/_atelier/entree"
    code = atelier.app.state.apps.passage.consommer_code(parse_qs(vers.query)["code"][0])
    assert code.portee == f"conversation:{conv}" and code.destination == f"/_ecran/{conv}/"
    assert atelier.get("/v1/ecran/inconnue/ouvrir", follow_redirects=False).status_code == 404
    # Le retour de l'hôte sans session n'émet un code que pour une conversation connue.
    r = atelier.get("/v1/apps/entree", params={"suite": f"/_ecran/{conv}/"}, follow_redirects=False)
    assert r.status_code == 302
    r = atelier.get("/v1/apps/entree", params={"suite": "/_ecran/inconnue/"}, follow_redirects=False)
    assert r.status_code == 404


def test_ouvrir_l_ecran_exige_la_session_du_navigateur(atelier: TestClient) -> None:
    conv = _conversation(atelier)
    assert atelier.get(f"/v1/ecran/{conv}/ouvrir", headers=_porteur(atelier), follow_redirects=False).status_code == 400
    assert atelier.get(f"/v1/ecran/{conv}/ouvrir", follow_redirects=False).status_code == 401


def test_l_etat_de_l_ecran_et_la_main_par_l_atelier(atelier: TestClient, tmp_path: Path) -> None:
    conv = _conversation(atelier)
    r = atelier.get(f"/v1/ecran/{conv}", headers=_porteur(atelier))
    assert r.status_code == 200 and r.json()["disponible"] is False
    assert atelier.post(f"/v1/ecran/{conv}/main", json={"prendre": True}, headers=_porteur(atelier)).status_code == 409
    publier(tmp_path / "racine", conv, 9222, page={"url": "https://x.test/", "titre": "X"})
    r = atelier.get(f"/v1/ecran/{conv}", headers=_porteur(atelier))
    corps = r.json()
    assert corps["disponible"] is True and corps["url"] == "https://x.test/"
    assert "9222" not in r.text and "/devtools/" not in r.text
    r = atelier.post(f"/v1/ecran/{conv}/main", json={"prendre": True}, headers=_porteur(atelier))
    assert r.status_code == 200 and r.json()["main"] is True
    r = atelier.post(f"/v1/ecran/{conv}/main", json={"prendre": False}, headers=_porteur(atelier))
    # Aucun tour ne travaille (mode factice) : l'agent est relancé par un message.
    assert r.status_code == 200 and r.json()["main"] is False and r.json()["reprise"] == "relance"
    assert atelier.get("/v1/ecran/inconnue", headers=_porteur(atelier)).status_code == 404
