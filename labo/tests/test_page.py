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


def test_creer_une_variante_depuis_la_page_puis_parcourir_ses_images(serveur: str, racine: Racine) -> None:
    from PIL import Image

    for g in range(12):
        for n in (0, 1, 2):
            for k in range(6):
                f = racine.brut / f"V/g{g}/x/droite/{n}/i{k}.jpeg"
                f.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (36, 24), (n * 80, 90, 90)).save(f)
    erreurs: list[str] = []
    with playwright.sync_playwright() as p:
        navigateur = p.chromium.launch(executable_path=_chromium())
        page = navigateur.new_page()
        page.on("console", lambda m: erreurs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: erreurs.append(str(e)))
        page.goto(f"{serveur}/#/donnees")
        page.wait_for_selector(".tuile:has-text('images brutes')")
        assert "216" in page.inner_text(".tuiles")
        page.click("text=Nouvelle variante >> nth=0")
        page.wait_for_selector("text=Contrôles")
        page.wait_for_selector("text=Identité")
        bouton = page.locator("button:has-text('Construire la variante')")
        page.wait_for_function("!document.querySelector('button.principal[type=button]').disabled")
        assert "aucun problème" in page.inner_text("main") or "à savoir" in page.inner_text("main")
        page.fill("#nom", "essai")
        page.select_option("#preparation", "masque")
        page.wait_for_function("document.body.innerText.includes('essai-')")
        bouton.click()
        page.wait_for_selector("h2:has-text('Images')", timeout=30000)
        page.wait_for_selector(".galerie img")
        page.wait_for_function("[...document.images].every(i => i.complete && i.naturalWidth > 0)")
        assert page.locator(".galerie figure").count() > 0
        page.select_option("#f-classe", "1")
        page.wait_for_function("[...document.querySelectorAll('.galerie figcaption')].every(f => f.textContent.startsWith('classe 1'))")
        navigateur.close()
    assert erreurs == []


def test_connexion_depuis_un_navigateur_avec_le_jeton(racine: Racine) -> None:
    """Accès depuis internet : sans cookie, l'écran de connexion ; avec le bon jeton, la page ; avec un faux, un refus."""
    if _chromium() is None:
        pytest.skip("pas de Chromium")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    import laboratoire.api as api

    api.PAUSE_APRES_ECHEC_S = 0
    srv = uvicorn.Server(uvicorn.Config(creer_app(racine, jeton="le-bon-jeton", demarrer_travailleur=False), host="127.0.0.1", port=port, log_level="error"))
    fil = threading.Thread(target=srv.run, daemon=True)
    fil.start()
    fin = time.monotonic() + 10
    while not srv.started and time.monotonic() < fin:
        time.sleep(0.05)
    erreurs: list[str] = []
    try:
        with playwright.sync_playwright() as p:
            navigateur = p.chromium.launch(executable_path=_chromium())
            page = navigateur.new_page()
            page.on("pageerror", lambda e: erreurs.append(str(e)))
            page.goto(f"http://127.0.0.1:{port}/")
            page.fill("#jeton", "faux")
            page.click("button[type=submit]")
            page.wait_for_selector("text=Jeton refusé")
            page.fill("#jeton", "le-bon-jeton")
            page.click("button[type=submit]")
            page.wait_for_selector("nav.onglets")
            page.wait_for_selector("#pod .pastille")  # les appels de l'API passent avec le cookie
            navigateur.close()
    finally:
        srv.should_exit = True
        fil.join(timeout=10)
    assert erreurs == []


def test_valider_au_clavier_nombre_forme_annulation_et_aveugle(racine: Racine) -> None:
    """(photos plates) Le parcours complet d'un valideur : nom, une image, touches 0 / 2+B / D / Z, étiquette d'origine cachée par défaut."""
    from PIL import Image

    if _chromium() is None:
        pytest.skip("pas de Chromium")
    for g in range(2):
        for n in (0, 1, 2):
            for k in range(4):
                f = racine.brut / f"V/g{g}/x/droite/{n}/{k + 1:03d}.jpeg"
                f.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (1600, 100), (n * 90, 60, 60)).save(f)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = creer_app(racine, demarrer_travailleur=False)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    fil = threading.Thread(target=srv.run, daemon=True)
    fil.start()
    fin = time.monotonic() + 10
    while not srv.started and time.monotonic() < fin:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    erreurs: list[str] = []

    try:
        with playwright.sync_playwright() as p:
            navigateur = p.chromium.launch(executable_path=_chromium())
            page = navigateur.new_page()
            page.on("pageerror", lambda e: erreurs.append(str(e)))
            page.goto(f"{base}/#/valider")
            page.fill("#nom-valideur", "Alice")
            page.click("button[type=submit]")
            page.wait_for_selector("#image-courante")
            assert page.locator("#ancien").count() == 0  # à l'aveugle par défaut : l'étiquette d'origine est cachée
            # La zone à qualifier est dite et montrée : l'autre moitié de la photo est assombrie (une voiture de l'autre côté ne compte pas).
            assert "On qualifie uniquement le côté DROITE de la rue" in page.inner_text("figcaption")
            assert page.locator(".zone-hors.droite").count() == 1 and page.locator(".zone-concernee.droite").count() == 1
            boite = page.locator(".zone-concernee").bounding_box()
            image = page.locator("#image-courante").bounding_box()
            assert abs(boite["x"] - (image["x"] + image["width"] / 2)) < 2 and abs(boite["width"] - image["width"] / 2) < 2  # la moitié droite
            premiere = page.get_attribute("#image-courante", "src")
            page.keyboard.press("0")  # aucune place : validé tout de suite
            page.wait_for_function("(avant) => document.querySelector('#image-courante').getAttribute('src') !== avant", arg=premiere)
            deuxieme = page.get_attribute("#image-courante", "src")
            page.keyboard.press("2")
            page.keyboard.press("b")  # 2 places en bataille : validé
            page.wait_for_function("(avant) => document.querySelector('#image-courante').getAttribute('src') !== avant", arg=deuxieme)
            troisieme = page.get_attribute("#image-courante", "src")
            page.keyboard.press("d")
            page.wait_for_function("(avant) => document.querySelector('#image-courante').getAttribute('src') !== avant", arg=troisieme)
            page.keyboard.press("z")  # annule la douteuse : on revoit la troisième
            page.wait_for_function("(avant) => document.querySelector('#image-courante').getAttribute('src') === avant", arg=troisieme)
            page.keyboard.press("v")  # montrer l'étiquette d'origine
            page.wait_for_selector("#ancien")
            page.click("#bascule-aveugle")
            page.wait_for_selector("#ancien", state="detached")
            navigateur.close()
        import json
        import urllib.request

        stats = json.loads(urllib.request.urlopen(f"{base}/api/validation/stats").read())
        assert stats["decisions"] == 2 and stats["par_valideur"] == {"Alice": 2} and stats["douteuses"] == 0  # 0 et 2+B ; la douteuse est annulée
        export = urllib.request.urlopen(f"{base}/api/validation/export").read().decode().splitlines()
        assert len(export) == 3 and any(l.endswith(",0,aucune,0") for l in export) and any(l.endswith(",2,bataille,0") for l in export)
    finally:
        srv.should_exit = True
        fil.join(timeout=10)
    assert erreurs == []
