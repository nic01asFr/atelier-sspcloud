"""Captures de l'instance locale de démonstration (Playwright, Chromium sans tête).

usage : DEMO_WORK=<dossier> python capturer.py <dossier de sortie> [vue ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

import os

# La clé de l'instance de démonstration, tirée au sort par elle : jamais celle d'un pod.
CLE = (Path(os.environ["DEMO_WORK"]) / ".secrets" / "atelier_owner_key").read_text(encoding="utf-8").strip()
BASE = "http://127.0.0.1:8787/"
SORTIE = Path(sys.argv[1] if len(sys.argv) > 1 else "essais")
SORTIE.mkdir(parents=True, exist_ok=True)
VUES = set(sys.argv[2:])


def lancer(largeur, hauteur, schema, mobile=False):
    p = sync_playwright().start()
    b = p.chromium.launch()
    ctx = b.new_context(viewport={"width": largeur, "height": hauteur}, color_scheme=schema,
                        device_scale_factor=2 if mobile else 1, is_mobile=mobile, has_touch=mobile,
                        locale="fr-FR", timezone_id="Europe/Paris")
    return p, b, ctx.new_page()


def connecter(page):
    page.goto(BASE)
    champ = page.locator("input[type=password]").first
    champ.wait_for(timeout=15000)
    champ.fill(CLE)
    champ.press("Enter")
    page.locator("nav").first.wait_for(timeout=15000)
    page.wait_for_timeout(1000)


def vue(page, libelle):
    page.locator("nav").get_by_text(libelle, exact=False).first.click()
    page.wait_for_timeout(2200)


def ouvrir_conversation(page, projet, titre):
    page.get_by_text(projet, exact=True).first.click()
    page.wait_for_timeout(600)
    page.get_by_text(titre, exact=False).first.click()
    page.wait_for_timeout(1800)


def prendre(page, nom):
    page.mouse.move(2, 2)
    page.wait_for_timeout(400)
    textes = [page.evaluate("() => document.body.innerText")]
    for f in page.frames[1:]:
        try:
            textes.append(f.evaluate("() => document.body.innerText"))
        except Exception:
            pass
    tout = chr(10).join(textes)
    for interdit in ("AppData", "C:\\", "Users\\", CLE[:12]):
        assert interdit not in tout, f"{nom} : {interdit!r} visible"
    page.screenshot(path=str(SORTIE / f"{nom}.png"))
    print("capture", nom)


def veut(nom):
    return not VUES or nom in VUES


def grand_ecran(schema, suffixe):
    p, b, page = lancer(1440, 900, schema)
    connecter(page)
    if veut("code"):
        ouvrir_conversation(page, "Carte des parcelles", "Carte des parcelles, 2019")
        if not page.locator("#panneau iframe").count() or not page.locator("#panneau").is_visible():
            page.get_by_role("button", name="Panneau").first.click()
        page.wait_for_timeout(1200)
        montrer = page.locator("#panneau button[title='Afficher dans le panneau, à côté du fil']")
        if montrer.count() and montrer.first.is_visible():
            montrer.first.click()
        page.wait_for_timeout(3500)
        prendre(page, f"code-creation-{suffixe}")
        page.get_by_role("button", name="Panneau").first.click()
        page.wait_for_timeout(600)
        page.locator("summary", has_text="Voir les étapes").first.click()
        page.wait_for_timeout(800)
        prendre(page, f"code-etapes-{suffixe}")
    if veut("assistant"):
        vue(page, "Assistant")
        page.get_by_text("Où en sont mes projets", exact=False).first.click()
        page.wait_for_timeout(2000)
        page.evaluate("() => { for (const e of document.querySelectorAll('*')) { if (e.scrollHeight > e.clientHeight + 40 && getComputedStyle(e).overflowY !== 'visible') e.scrollTop = e.scrollHeight; } }")
        page.wait_for_timeout(600)
        prendre(page, f"assistant-{suffixe}")
    for nom, libelle in (("a-valider", "À valider"), ("agents", "Agents"), ("journal", "Journal"),
                         ("memoire", "Ma mémoire"), ("connecteurs", "Connecteurs")):
        if veut(nom):
            vue(page, libelle)
            prendre(page, f"{nom}-{suffixe}")
    b.close()
    p.stop()


def telephone(schema, suffixe):
    if not veut("mobile"):
        return
    p, b, page = lancer(390, 844, schema, mobile=True)
    connecter(page)
    prendre(page, f"mobile-liste-{suffixe}")
    ouvrir_conversation(page, "Lecteur Grist", "Export CSV des tables")
    prendre(page, f"mobile-conversation-{suffixe}")
    b.close()
    p.stop()


if __name__ == "__main__":
    for schema, suffixe in (("dark", "sombre"), ("light", "clair")):
        grand_ecran(schema, suffixe)
        telephone(schema, suffixe)
