"""Défauts du déploiement : adresses publiques à la relance, paquet du vérificateur."""

from __future__ import annotations

import os
import shutil
import subprocess
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path

import pytest

from mcp_gateway.atelier.config import AtelierSettings

BIN = Path(__file__).resolve().parent.parent / "bin"


# ── Les adresses publiques survivent à une relance ──────────────────────


def test_l_atelier_note_ses_adresses_et_n_efface_pas_la_bonne(tmp_path: Path) -> None:
    from mcp_gateway.atelier.commandes import fichier_des_adresses, noter_les_adresses

    reglages = AtelierSettings(work_dir=tmp_path / "work", public_url="https://atelier.exemple.fr")
    noter_les_adresses(reglages)
    fichier = fichier_des_adresses(reglages.work_dir)
    assert "ATELIER_PUBLIC_URL='https://atelier.exemple.fr'" in fichier.read_text(encoding="utf-8")
    # Relancé sans l'adresse : la bonne reste notée.
    noter_les_adresses(AtelierSettings(work_dir=tmp_path / "work"))
    assert "https://atelier.exemple.fr" in fichier.read_text(encoding="utf-8")


def test_le_service_note_ses_adresses_au_montage(reglages: AtelierSettings) -> None:
    from mcp_gateway.atelier.api import build_app
    from mcp_gateway.atelier.commandes import fichier_des_adresses

    reglages.apps_public_url = "https://apps.exemple.fr"
    build_app(settings=reglages, use_fake=True)
    assert "ATELIER_APPS_PUBLIC_URL='https://apps.exemple.fr'" in fichier_des_adresses(
        reglages.work_dir
    ).read_text(encoding="utf-8")


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh absent")
def test_relancer_reprend_les_adresses_sans_les_afficher(tmp_path: Path) -> None:
    travail = tmp_path / "work"
    (travail / ".atelier-etat").mkdir(parents=True)
    (travail / ".atelier-etat" / "adresses.env").write_text(
        "# note\nATELIER_PUBLIC_URL='https://secret-de-forme.exemple.fr'\n", encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if not k.startswith("ATELIER_")}
    env.update({"ATELIER_WORK": str(travail), "ATELIER_PORT": "1"})
    # Le script s'arrête de lui-même avant de lancer quoi que ce soit : il n'y
    # a pas d'`atelier-src` dans ce dossier de travail.
    sortie = subprocess.run(
        ["sh", str(BIN / "atelier-relancer")], env=env, capture_output=True, text=True, timeout=60
    )
    assert "ATELIER_PUBLIC_URL(fichier)" in sortie.stdout
    assert "secret-de-forme" not in sortie.stdout + sortie.stderr

    env["ATELIER_PUBLIC_URL"] = "https://choisie.exemple.fr"
    sortie = subprocess.run(
        ["sh", str(BIN / "atelier-relancer")], env=env, capture_output=True, text=True, timeout=60
    )
    assert "ATELIER_PUBLIC_URL" not in sortie.stdout, "ce que l'appelant exporte l'emporte"


# ── atelier-verifier-coherence trouve son paquet ────────────────────────


def _verificateur():
    chargeur = SourceFileLoader("atelier_verifier_coherence", str(BIN / "atelier-verifier-coherence"))
    module = module_from_spec(spec_from_loader(chargeur.name, chargeur))
    chargeur.exec_module(module)
    return module


def test_le_verificateur_trouve_le_paquet_une_fois_installe(tmp_path: Path) -> None:
    module = _verificateur()
    travail = tmp_path / "work"
    (travail / "atelier-src" / "mcp_gateway" / "atelier").mkdir(parents=True)
    (travail / "atelier-src" / "mcp_gateway" / "atelier" / "__init__.py").write_text("", encoding="utf-8")
    installe = travail / "bin" / "atelier-verifier-coherence"
    installe.parent.mkdir(parents=True)
    installe.write_text("", encoding="utf-8")
    trouve = module.trouver_la_source(installe, {"ATELIER_WORK": str(travail)}, tmp_path / "maison")
    assert trouve == travail / "atelier-src"


def test_le_verificateur_trouve_le_paquet_depuis_le_depot() -> None:
    module = _verificateur()
    trouve = module.trouver_la_source(BIN / "atelier-verifier-coherence", {}, Path("/nulle-part"))
    assert trouve == BIN.parent.resolve()
