"""La page, dans un vrai navigateur : aucune erreur JavaScript, et ce qu'on doit y lire s'y lit. Sauté sans Chromium (ni Playwright)."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from conftest import faire_variante
from laboratoire.api import creer_app
from laboratoire.projet import Racine

playwright = pytest.importorskip("playwright.sync_api")


def _chromium() -> str | None:
    for base in (Path("/opt/pw-browsers"),):
        for candidat in sorted(base.glob("chromium-*/chrome-linux/chrome")):
            return str(candidat)
    return None


@pytest.fixture()
def serveur(racine: Racine):
    if _chromium() is None:
        pytest.skip("pas de Chromium")
    faire_variante(racine, "droite-nombre-v1", {
        "train": {"0": [("c1", 12), ("c2", 12)], "1": [("c1", 5)], "2": [("c1", 6), ("c2", 6)]},
        "val": {"0": [("c3", 10)], "1": [("c3", 2)], "2": [("c3", 5)]},
        "test": {"0": [("c4", 8)], "1": [("c4", 2)], "2": [("c4", 5)]},
    })
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = creer_app(racine, demarrer_travailleur=True)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    fil = threading.Thread(target=srv.run, daemon=True)
    fil.start()
    fin = time.monotonic() + 10
    while not srv.started and time.monotonic() < fin:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    fil.join(timeout=10)


def test_la_page_s_affiche_sans_erreur_et_dit_la_verite(serveur: str) -> None:
    import json
    import urllib.request

    corps = json.dumps({"jeu": "droite-nombre-v1", "methode": {"famille": "jouet", "modele": "centres", "imgsz": 8, "epochs": 1}}).encode()
    requete = urllib.request.Request(f"{serveur}/api/essais", data=corps, headers={"Content-Type": "application/json"})
    ident = json.loads(urllib.request.urlopen(requete).read())["id"]
    fin = time.monotonic() + 60
    while time.monotonic() < fin:
        if json.loads(urllib.request.urlopen(f"{serveur}/api/essais/{ident}").read())["essai"]["etat"] == "termine":
            break
        time.sleep(0.2)
    erreurs: list[str] = []
    with playwright.sync_playwright() as p:
        navigateur = p.chromium.launch(executable_path=_chromium())
        page = navigateur.new_page()
        page.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: erreurs.append(str(e)))
        page.goto(f"{serveur}/#/essais")
        page.wait_for_selector("table tbody tr a")
        assert ident in page.inner_text("table")
        assert "scellé" in page.inner_text("table")  # le test est scellé tant qu'on ne l'a pas ouvert
        page.goto(f"{serveur}/#/essais/{ident}")
        page.wait_for_selector("text=Gain sur la réponse triviale")
        texte = page.inner_text("main")
        assert "Rappel moyen (validation)" in texte and "non fiable" in texte and "Test scellé" in texte
        page.goto(f"{serveur}/#/lancer")
        page.wait_for_selector("text=Mettre en file")
        page.goto(f"{serveur}/#/donnees")
        page.wait_for_selector("h1:has-text('Données')")
        page.wait_for_selector("h2:has-text('droite-nombre-v1')")
        navigateur.close()
    assert erreurs == []


def test_un_texte_du_serveur_n_est_jamais_interprete_comme_du_html(serveur: str, racine: Racine) -> None:
    """Le nom d'une classe ou d'une collection venu du disque s'affiche tel quel, sans s'exécuter."""
    faire_variante(racine, "pieges", {
        "train": {"<img src=x onerror=window.pwn=1>": [("<b>c1", 4)], "b": [("c2", 4)]},
        "val": {"<img src=x onerror=window.pwn=1>": [("c3", 2)], "b": [("c3", 2)]},
        "test": {"<img src=x onerror=window.pwn=1>": [("c4", 2)], "b": [("c4", 2)]},
    })
    with playwright.sync_playwright() as p:
        navigateur = p.chromium.launch(executable_path=_chromium())
        page = navigateur.new_page()
        page.goto(f"{serveur}/#/donnees")
        page.wait_for_selector("h2:has-text('pieges')")
        assert page.evaluate("window.pwn") is None
        assert "<img src=x" in page.inner_text("main")
        assert page.locator("main img").count() == 0
        navigateur.close()
