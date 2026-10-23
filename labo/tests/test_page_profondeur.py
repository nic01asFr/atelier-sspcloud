"""L'interface « profondeur » dans un vrai navigateur : juger au clavier, classement, panoramas, traitements. Sauté sans Chromium."""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from laboratoire.api import creer_app
from laboratoire.profondeur.panoramax import construire_jeu, rechercher
from laboratoire.projet import Racine
from test_profondeur_essai import config, fausse_api, item

playwright = pytest.importorskip("playwright.sync_api")


def _chromium() -> str | None:
    for candidat in sorted(Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")):
        return str(candidat)
    return None


@pytest.fixture()
def serveur(racine: Racine):
    if _chromium() is None:
        pytest.skip("pas de Chromium")
    ouvrir = fausse_api([item(i, f"s{i}") for i in range(1, 5)])
    construire_jeu(racine, "jeu-test", rechercher("https://api.test", "5,45,6,46", ouvrir=ouvrir), n=4, ouvrir=ouvrir, journal=lambda s: None)
    (racine.chemin / "valideurs.json").write_text(json.dumps({"Mathieu": {"jeton": "tm", "role": "relecteur"}, "Julie": "tj"}), encoding="utf-8")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = creer_app(racine, jeton="adm", demarrer_travailleur=True, tache="profondeur")
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    fil = threading.Thread(target=srv.run, daemon=True)
    fil.start()
    fin = time.monotonic() + 10
    while not srv.started and time.monotonic() < fin:
        time.sleep(0.05)
    import urllib.request

    ids = []
    for m in ("plan", "contraste"):
        r = urllib.request.Request(f"http://127.0.0.1:{port}/api/essais", data=json.dumps(config(m, panoramas_max=4)).encode(), headers={"Authorization": "Bearer adm", "Content-Type": "application/json"})
        ids.append(json.loads(urllib.request.urlopen(r).read())["id"])
    fin = time.monotonic() + 120
    while time.monotonic() < fin:
        etats = [json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/essais/{i}", headers={"Authorization": "Bearer adm"})).read())["essai"]["etat"] for i in ids]
        if all(e == "termine" for e in etats):
            break
        time.sleep(0.3)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    fil.join(timeout=10)


def _page(p, serveur: str, jeton: str, erreurs: list[str]):
    navigateur = p.chromium.launch(executable_path=_chromium())
    contexte = navigateur.new_context()
    contexte.add_cookies([{"name": "labo_jeton", "value": jeton, "url": serveur}])
    page = contexte.new_page()
    page.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: erreurs.append(str(e)))
    page.on("response", lambda r: erreurs.append(f"{r.status} {r.url}") if r.status >= 400 else None)
    return navigateur, page


def test_une_personne_juge_au_clavier_sans_jamais_voir_les_modeles(serveur: str) -> None:
    erreurs: list[str] = []
    with playwright.sync_playwright() as p:
        navigateur, page = _page(p, serveur, "tj", erreurs)
        page.goto(f"{serveur}/")
        page.wait_for_selector("h1:has-text('Juger')")
        assert page.locator("nav.onglets a").count() == 1  # un valideur n'a que cet écran
        page.wait_for_selector(".trio img")
        page.wait_for_function("[...document.querySelectorAll('.trio img')].every(i => i.complete && i.naturalWidth > 0)")
        texte = page.inner_text("main")
        assert "plan" not in texte.lower().split("touches")[0] or "plan " not in texte  # aucun nom de modèle avant d'avoir voté
        assert "contraste" not in texte.lower()
        premiere = page.get_attribute("#vue-source", "src")
        page.keyboard.press("ArrowLeft")
        page.wait_for_function("(s) => document.querySelector('#vue-source') && document.querySelector('#vue-source').getAttribute('src') !== s", arg=premiere)
        assert "Gauche préférée" in page.inner_text("main")
        page.keyboard.press("z")
        page.wait_for_selector("text=Dernier vote annulé")
        navigateur.close()
    assert erreurs == []


def test_un_relecteur_lit_le_classement_les_panoramas_et_les_traitements(serveur: str) -> None:
    erreurs: list[str] = []
    with playwright.sync_playwright() as p:
        navigateur, page = _page(p, serveur, "tm", erreurs)
        page.goto(f"{serveur}/#/classement")
        page.wait_for_selector("h2:has-text('Ce que les personnes ont jugé')")
        texte = page.inner_text("main")
        assert "plan" in texte and "contraste" in texte and "Accord entre modèles" in texte and "fragile" in texte
        page.goto(f"{serveur}/#/panoramas")
        page.wait_for_selector(".galerie button")
        page.click(".galerie button >> nth=0")
        page.wait_for_selector(".grille-profondeur img")
        assert page.locator(".grille-profondeur figure").count() == 3  # la scène + deux modèles
        page.goto(f"{serveur}/#/traitements")
        page.wait_for_selector("h2:has-text('Historique')")
        assert "CC-BY-NC" in page.inner_text("main")
        navigateur.close()
    assert erreurs == []
