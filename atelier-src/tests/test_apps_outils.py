"""Les outils MCP `atelier_artefact*` : montrer ce qu'on produit sans chercher de port.

Un agent n'a ni port à ouvrir ni adresse à deviner : il crée un artefact —
un dossier et une adresse —, y dépose des fichiers ou y déclare un serveur,
puis le démarre, le vérifie, lit son journal et l'arrête par ces outils. Ce
sont les mêmes gestes que le panneau de l'interface, sur le même service ;
et deux conversations ne se marchent pas dessus.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from mcp_gateway.atelier.apps.service import ServiceApps
from mcp_gateway.atelier.apps.superviseur import Superviseur
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.outils_conversation import CONVERSATION_APPELANTE, OutilsAtelier

APP = Path(__file__).with_name("app_factice.py")
# `app_factice` sert aussi sur socket Unix : elle ne se lance que sous Linux.
linux = pytest.mark.skipif(sys.platform != "linux", reason="app_factice : Linux")


@pytest.fixture()
def service(tmp_path: Path) -> ServiceApps:
    settings = AtelierSettings(
        work_dir=tmp_path / "work", apps_public_url="https://apps.test", apps_ports="22400-22420"
    )
    settings.ensure_dirs()
    art = settings.projects_dir / "demo" / "artifacts"
    (art / "voix").mkdir(parents=True)
    (art / "voix" / "artefact.json").write_text(
        json.dumps(
            {
                "version": 1,
                "commande": [sys.executable, str(APP), "--port", "{port}"],
                "sante": "/health",
                "demarrage_s": 15,
            }
        ),
        encoding="utf-8",
    )
    (art / "voix" / ".auteur").write_text("conv-voix\n", encoding="utf-8")
    (art / "casse").mkdir()
    (art / "casse" / "artefact.json").write_text(
        '{"version": 1, "commande": "python -m http.server"}', encoding="utf-8"
    )
    (art / "rapport").mkdir()
    return ServiceApps(settings, Superviseur(settings, pas_demarrage_s=0.1, delai_sigkill_s=2))


def appeler(outils: OutilsAtelier, outil: str, **arguments):
    reponse = asyncio.run(outils.appeler(outil, arguments))
    assert reponse is not None, outil
    return json.loads(reponse["content"][0]["text"]), bool(reponse["isError"])


def test_les_outils_ne_sont_annonces_qu_avec_le_service(service: ServiceApps) -> None:
    sans = OutilsAtelier(store=None, projects=None, harness=None)
    assert not any(n.startswith("atelier_artefact") for n in sans.noms)
    avec = OutilsAtelier(store=None, projects=None, harness=None, apps=service)
    assert {
        "atelier_artefacts",
        "atelier_artefact_creer",
        "atelier_artefact_demarrer",
        "atelier_artefact_arreter",
        "atelier_artefact_journal",
        "atelier_artefact_verifier",
    } <= avec.noms


def test_lister_et_verifier(service: ServiceApps) -> None:
    outils = OutilsAtelier(store=None, projects=None, harness=None, apps=service)
    vu, erreur = appeler(outils, "atelier_artefacts", projet="demo")
    assert not erreur
    fiches = {f["nom"]: f for f in vu["artefacts"]}
    assert fiches["voix"]["url"] == "https://apps.test/demo/voix/"
    assert fiches["voix"]["mode"] == "serveur" and fiches["voix"]["auteur"] == "conv-voix"
    assert fiches["rapport"]["mode"] == "autonome"
    assert fiches["casse"]["etat"] == "invalide"
    vu, erreur = appeler(outils, "atelier_artefact_verifier", projet="demo")
    assert not erreur
    assert vu["serveurs"] == ["voix"] and vu["autonomes"] == ["rapport"]
    assert "commande" in vu["erreurs"]["casse"]


def test_creer_refuse_un_nom_pris(service: ServiceApps) -> None:
    outils = OutilsAtelier(store=None, projects=None, harness=None, apps=service)
    vu, erreur = appeler(outils, "atelier_artefact_creer", projet="demo", nom="carte", mode="serveur", auteur="conv-a")
    assert not erreur, vu
    assert vu["mode"] == "serveur" and vu["auteur"] == "conv-a" and "artefact.json" in vu["suite"]
    vu, erreur = appeler(outils, "atelier_artefact_creer", projet="demo", nom="carte", auteur="conv-b")
    assert erreur and "existe déjà" in vu["erreur"]
    vu, erreur = appeler(outils, "atelier_artefact_creer", projet="demo", nom="Pas_Un_Nom")
    assert erreur


def test_l_auteur_vient_de_la_session_mcp(service: ServiceApps) -> None:
    outils = OutilsAtelier(store=None, projects=None, harness=None, apps=service)

    async def creer() -> dict:
        jeton = CONVERSATION_APPELANTE.set("conv-en-tete")
        try:
            r = await outils.appeler("atelier_artefact_creer", {"projet": "demo", "nom": "note"})
        finally:
            CONVERSATION_APPELANTE.reset(jeton)
        return json.loads(r["content"][0]["text"])

    assert asyncio.run(creer())["auteur"] == "conv-en-tete"


def test_on_n_agit_pas_sur_l_artefact_d_une_autre_conversation(service: ServiceApps) -> None:
    outils = OutilsAtelier(store=None, projects=None, harness=None, apps=service)
    vu, erreur = appeler(outils, "atelier_artefact_arreter", projet="demo", nom="voix", auteur="conv-autre")
    assert erreur and "conv-voix" in vu["erreur"] and "forcer" in vu["erreur"]
    vu, erreur = appeler(outils, "atelier_artefact_demarrer", projet="demo", nom="voix", auteur="conv-autre")
    assert erreur
    vu, erreur = appeler(outils, "atelier_artefact_arreter", projet="demo", nom="voix", auteur="conv-autre", forcer=True)
    assert not erreur


def test_les_erreurs_reviennent_lisibles(service: ServiceApps) -> None:
    outils = OutilsAtelier(store=None, projects=None, harness=None, apps=service)
    vu, erreur = appeler(outils, "atelier_artefact_demarrer", projet="inconnu", nom="voix")
    assert erreur and "inconnu" in vu["erreur"]
    vu, erreur = appeler(outils, "atelier_artefact_demarrer", projet="demo", nom="casse")
    assert erreur and "commande" in vu["erreur"]
    vu, erreur = appeler(outils, "atelier_artefact_journal", projet="demo")
    assert erreur


@linux
def test_demarrer_verifier_lire_arreter(service: ServiceApps) -> None:
    outils = OutilsAtelier(store=None, projects=None, harness=None, apps=service)

    async def scenario() -> None:
        async def appel(outil: str, **arguments):
            r = await outils.appeler(outil, {**arguments, "auteur": "conv-voix"})
            return json.loads(r["content"][0]["text"]), r["isError"]

        vu, erreur = await appel("atelier_artefact_demarrer", projet="demo", nom="voix")
        assert not erreur and vu["etat"] == "pret", vu
        vu, _ = await appel("atelier_artefact_verifier", projet="demo", nom="voix")
        assert vu["artefact"]["sonde"] == {"chemin": "/health", "statut": 200}
        vu, _ = await appel("atelier_artefact_journal", projet="demo", nom="voix", lignes=50)
        assert "prête" in vu["journal"]
        vu, _ = await appel("atelier_artefact_arreter", projet="demo", nom="voix")
        assert vu["etat"] == "arrete"
        await service.superviseur.fermer()

    asyncio.run(scenario())
