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
                im = Image.new("RGB", (36, 24), (n * 80, 90, 90))
                im.paste((g * 20, k * 40, 7), (0, 0, 16, 16))  # une image distincte : deux images identiques seraient une fuite (fuite_contenu)
                im.save(f)
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


def test_commenter_une_zone_sur_une_image_repondre_et_changer_le_statut(racine: Racine) -> None:
    """Mathieu (relecteur) dessine un rectangle sur l'image à valider, écrit, répond ; la personne qui administre change le statut. Rien ne se valide en tapant."""
    import json
    import urllib.request

    from PIL import Image

    if _chromium() is None:
        pytest.skip("pas de Chromium")
    for g in range(2):
        for n in (0, 1, 2):
            for k in range(4):
                f = racine.brut / f"V/g{g}/x/droite/{n}/{k + 1:03d}.jpeg"
                f.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (60, 40), (n * 90, 60, 60)).save(f)
    (racine.chemin / "valideurs.json").write_text('{"Mathieu": {"jeton": "jeton-mathieu", "role": "relecteur"}}', encoding="utf-8")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = creer_app(racine, jeton="admin", demarrer_travailleur=False)
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    fil = threading.Thread(target=srv.run, daemon=True)
    fil.start()
    fin = time.monotonic() + 10
    while not srv.started and time.monotonic() < fin:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    erreurs: list[str] = []

    def api(chemin: str, jeton: str = "admin"):
        requete = urllib.request.Request(f"{base}{chemin}", headers={"Authorization": f"Bearer {jeton}"})
        return json.loads(urllib.request.urlopen(requete).read())

    try:
        with playwright.sync_playwright() as p:
            navigateur = p.chromium.launch(executable_path=_chromium())
            contexte = navigateur.new_context(viewport={"width": 1280, "height": 900})
            contexte.add_cookies([{"name": "labo_jeton", "value": "jeton-mathieu", "url": base}])
            page = contexte.new_page()
            page.on("pageerror", lambda e: erreurs.append(str(e)))
            page.goto(f"{base}/#/valider")
            page.fill("#nom-valideur", "Mathieu")
            page.click("button[type=submit]")
            page.wait_for_selector("#image-courante")
            page.wait_for_function("() => document.querySelector('#image-courante').complete && document.querySelector('#image-courante').naturalWidth > 0")
            # 1. Le mode « commenter » : on dessine un rectangle sur l'image.
            page.click(".cm-bouton")
            page.click("text=Nouveau commentaire")
            image = page.locator("#image-courante").bounding_box()
            x0, y0 = image["x"] + image["width"] * 0.25, image["y"] + image["height"] * 0.25
            x1, y1 = image["x"] + image["width"] * 0.75, image["y"] + image["height"] * 0.75
            page.mouse.move(x0, y0)
            page.mouse.down()
            page.mouse.move(x1, y1, steps=6)
            page.mouse.up()
            page.wait_for_selector(".cm-formulaire")
            page.locator(".cm-formulaire select").select_option("anomalie")
            page.fill(".cm-formulaire textarea", "2 voitures, b : ce n'est pas une place, c'est un camion.")  # des touches de raccourci de la page
            page.click(".cm-formulaire button[type=submit]")
            page.wait_for_selector(".cm-pin")
            page.wait_for_selector(".cm-tiroir .cm-fil")
            liste = api("/api/commentaires")
            assert len(liste) == 1 and liste[0]["auteur"] == "Mathieu" and liste[0]["role"] == "relecteur" and liste[0]["nature"] == "anomalie"
            cible = liste[0]["cible"]
            assert cible["zone"]["repere"] == "image" and abs(cible["zone"]["x"] - 0.25) < 0.03 and abs(cible["zone"]["l"] - 0.5) < 0.03 and abs(cible["zone"]["h"] - 0.5) < 0.03
            assert cible["donnee"]["type"] == "image" and cible["donnee"]["id"].endswith(".jpeg") and cible["page"] == "/valider"
            assert any(e["type"] == "cible" and e["valeur"].startswith("image:") for e in cible["elements"])
            assert api("/api/validation/stats")["decisions"] == 0  # taper « 2 », « b » dans le champ n'a rien validé
            # 2. Le repère est posé sur l'image, au coin de la zone.
            zone = page.locator(".cm-zone").bounding_box()
            assert abs(zone["x"] - x0) < 3 and abs(zone["width"] - (x1 - x0)) < 3 and abs(zone["height"] - (y1 - y0)) < 3
            assert page.locator(".cm-tiroir select[aria-label='Nouveau statut']").count() == 0  # le statut n'est pas à un relecteur
            # 3. Une réponse.
            page.fill(".cm-fil textarea", "Je précise : le camion est arrêté.")
            page.click("text=Répondre")
            page.wait_for_selector(".cm-tiroir .cm-evt")
            assert api("/api/commentaires")[0]["reponses"] == 1
            # 4. Rechargé, le repère est toujours là ; Échap annule le mode.
            page.reload()
            page.wait_for_selector(".cm-pin", timeout=15000)
            page.click(".cm-bouton")
            page.click("text=Nouveau commentaire")
            page.keyboard.press("Escape")
            assert page.locator(".cm-bouton[aria-pressed='true']").count() == 0
            # 5. La personne qui administre voit le même commentaire et en change le statut.
            admin = navigateur.new_context(viewport={"width": 1280, "height": 900})
            admin.add_cookies([{"name": "labo_jeton", "value": "admin", "url": base}])
            pa = admin.new_page()
            pa.on("pageerror", lambda e: erreurs.append(str(e)))
            pa.goto(f"{base}/#/essais")
            pa.wait_for_selector(".cm-bouton")
            pa.click(".cm-bouton")
            pa.click("button:has-text('Tous (1)')")
            pa.click(".cm-item")
            pa.wait_for_selector(".cm-tiroir select[aria-label='Nouveau statut']")
            pa.locator(".cm-tiroir select[aria-label='Nouveau statut']").select_option("traite")
            pa.fill(".cm-tiroir input[aria-label='Lien de la correction']", "PR 62")
            pa.click("button:has-text('Changer')")
            pa.wait_for_selector(".cm-tiroir .cm-evt:has-text('PR 62')")
            navigateur.close()
        assert api("/api/commentaires")[0]["statut"] == "traite" and api("/api/commentaires")[0]["lien"] == "PR 62"
    finally:
        srv.should_exit = True
        fil.join(timeout=10)
    assert erreurs == []


def test_la_page_livrable_liste_les_modeles_propose_le_zip_et_telecharge_un_fichier(serveur: str, racine: Racine) -> None:
    import csv

    d = racine.chemin / "livrable"
    d.mkdir()
    for groupe in ("panoramique_droite_nombre", "non_panoramique_gauche_nombre"):
        (d / f"{groupe}.pt").write_bytes(b"modele-" + groupe.encode())
        (d / f"{groupe}_lots.csv").write_text("fichier,jeu\n", encoding="utf-8")
    colonnes = ["groupe", "modele", "essai_livre", "jeu_de_donnees", "train", "val", "test", "images_validation", "exactitude", "reponse_triviale",
                "rappel_moyen", "hasard", "rappel_moyen_3_graines", "ecart_3_graines", "poids_sha256_12"]
    with (d / "synthese.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(colonnes)
        w.writerow(["panoramique_droite_nombre", "yolo26n-cls", "E0030", "jeu1", 355, 70, 83, 70, 0.6, 0.614, 0.345, 0.33, 0.352, 0.005, "abc"])
        w.writerow(["non_panoramique_gauche_nombre", "yolo26s-cls", "E0043", "jeu2", 240, 47, 61, 47, 0.83, 0.745, 0.514, 0.33, 0.533, 0.014, "def"])
    erreurs: list[str] = []
    with playwright.sync_playwright() as p:
        navigateur = p.chromium.launch(executable_path=_chromium())
        page = navigateur.new_page(accept_downloads=True)
        page.on("pageerror", lambda e: erreurs.append(str(e)))
        page.goto(f"{serveur}/#/livrable")
        page.wait_for_selector("text=Tout télécharger")
        texte = page.inner_text("main")
        assert "panoramique droite nombre" in texte and "non panoramique gauche nombre" in texte
        assert "0,53" in texte and "0,35" in texte and "Le lot de test est scellé" in texte  # les chiffres sont lus, pas devinés
        assert page.locator("[data-nav=livrable]").get_attribute("aria-current") == "page"
        with page.expect_download() as dl:
            page.locator("table a:text-is('modèle')").first.click()
        assert dl.value.suggested_filename.endswith(".pt")
        with page.expect_download() as dl:
            page.click("text=Tout télécharger")
        assert dl.value.suggested_filename == "livrable.zip"
        navigateur.close()
    assert erreurs == []
