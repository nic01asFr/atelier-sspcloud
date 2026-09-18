"""Exposer les artefacts d'un projet, sans exposer le reste.

Un agent qui produit un livrable à montrer — un rapport, une page — n'avait
nulle part où le poser : sur ce pod, un port local n'est jamais public. Un
agent a passé cent soixante-quatorze tours à chercher une URL, en vain. Il
dépose désormais dans `artifacts/`, et l'Atelier sert ce dossier derrière sa
porte. Le contenu venant d'un agent, chaque réponse est rendue inerte.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import artifacts as art
from mcp_gateway.atelier.config import AtelierSettings


# ── le module ──────────────────────────────────────────────────────────

def test_un_chemin_ne_remonte_pas_hors_du_dossier(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    base.mkdir()
    (tmp_path / "secret.txt").write_text("clé", encoding="utf-8")
    assert art._sous(base, "../secret.txt") is None
    assert art._sous(base, "sous/../../secret.txt") is None
    assert art._sous(base, "page.html") == (base / "page.html").resolve()


def test_l_index_cache_la_plomberie_et_les_fichiers_points(tmp_path: Path) -> None:
    base = tmp_path / "artifacts"
    (base / "node_modules").mkdir(parents=True)
    base.joinpath("server.mjs").write_text("x", encoding="utf-8")
    base.joinpath(".secret").write_text("x", encoding="utf-8")
    base.joinpath("rapport.md").write_text("# Titre", encoding="utf-8")
    (base / "detail").mkdir()
    noms = [e.nom for e in art.lister(base) or []]
    assert noms == ["detail", "rapport.md"]  # dossiers d'abord, plomberie masquée


def test_un_dossier_absent_ne_se_liste_pas(tmp_path: Path) -> None:
    assert art.lister(tmp_path / "artifacts") is None


def test_le_markdown_se_rend_en_page_autonome(tmp_path: Path) -> None:
    page = art.rendre_markdown("# Bonjour\n\ntexte", "Rapport")
    assert "<!DOCTYPE html>" in page
    assert "Bonjour" in page
    # Autonome : le style est dedans (aucune feuille externe à charger depuis
    # une origine opaque, où « rien » ne se référencerait plus).
    assert "<style>" in page
    assert "<link" not in page


def test_la_csp_est_un_bac_a_sable_sans_meme_origine() -> None:
    # `allow-same-origin` rendrait le bac à sable inutile : il ne doit pas y être.
    assert "sandbox" in art.CSP_SANDBOX
    assert "allow-scripts" in art.CSP_SANDBOX
    assert "allow-same-origin" not in art.CSP_SANDBOX


# ── les routes ─────────────────────────────────────────────────────────

def _depose(reglages: AtelierSettings, slug: str) -> Path:
    base = reglages.projects_dir / slug / "artifacts"
    base.mkdir(parents=True, exist_ok=True)
    base.joinpath("rapport.md").write_text("# Résultat\n\nAlpha beta.", encoding="utf-8")
    base.joinpath("page.html").write_text(
        "<!doctype html><h1>Autonome</h1>", encoding="utf-8"
    )
    (reglages.projects_dir / slug / "secret.txt").write_text("clé", encoding="utf-8")
    return base


def test_l_index_liste_les_artefacts(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get(
        "/v1/artifacts/recherche",
        headers={"Authorization": f"Bearer {cle_du_proprietaire}"},
    )
    assert r.status_code == 200
    assert "rapport.md" in r.text and "page.html" in r.text
    assert "sandbox" in r.headers["content-security-policy"]


def test_un_markdown_arrive_rendu(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get(
        "/v1/artifacts/recherche/rapport.md",
        headers={"Authorization": f"Bearer {cle_du_proprietaire}"},
    )
    assert r.status_code == 200
    assert "<h1>Résultat</h1>" in r.text
    assert "sandbox" in r.headers["content-security-policy"]


def test_un_html_est_servi_en_bac_a_sable(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get(
        "/v1/artifacts/recherche/page.html",
        headers={"Authorization": f"Bearer {cle_du_proprietaire}"},
    )
    assert r.status_code == 200
    assert "Autonome" in r.text
    assert "allow-same-origin" not in r.headers["content-security-policy"]


def test_on_ne_remonte_pas_hors_des_artefacts(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    _depose(reglages, "recherche")
    r = atelier.get(
        "/v1/artifacts/recherche/..%2Fsecret.txt",
        headers={"Authorization": f"Bearer {cle_du_proprietaire}"},
    )
    assert "clé" not in r.text
    assert r.status_code in (404, 400)


def test_un_projet_sans_artefacts_le_dit_sans_casser(
    atelier: TestClient, reglages: AtelierSettings, cle_du_proprietaire: str
) -> None:
    (reglages.projects_dir / "vide").mkdir(parents=True, exist_ok=True)
    r = atelier.get(
        "/v1/artifacts/vide",
        headers={"Authorization": f"Bearer {cle_du_proprietaire}"},
    )
    assert r.status_code == 200
    assert "Rien à montrer" in r.text


def test_sans_la_porte_rien_ne_sort(atelier: TestClient, reglages: AtelierSettings) -> None:
    _depose(reglages, "recherche")
    r = atelier.get("/v1/artifacts/recherche")
    assert r.status_code == 401
