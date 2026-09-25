"""Le contexte de projet ne s'écrit que dans le dossier du projet (le `/tmp/CLAUDE.md` du 24/09)."""

from __future__ import annotations

from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.project_context import DEBUT, ecrire_contexte


# ── Le contexte ne s'écrit que dans le dossier du projet ────────────────


def test_le_contexte_ne_s_ecrit_jamais_dans_un_cwd_etranger(tmp_path: Path) -> None:
    reglages = AtelierSettings(work_dir=tmp_path / "work")
    faux_tmp = tmp_path / "tmp"
    faux_tmp.mkdir()
    assert ecrire_contexte(faux_tmp, "projet-sans-nom-5", reglages) is False
    assert not (faux_tmp / "CLAUDE.md").exists()
    # Un sous-dossier du projet n'est pas le projet non plus.
    sous = reglages.projects_dir / "p" / "src"
    sous.mkdir(parents=True)
    assert ecrire_contexte(sous, "p", reglages) is False
    assert not (sous / "CLAUDE.md").exists()
    # Un slug qui voudrait sortir de la racine des projets.
    assert ecrire_contexte(tmp_path, "..", reglages) is False


def test_le_contexte_s_ecrit_dans_le_projet(tmp_path: Path) -> None:
    reglages = AtelierSettings(work_dir=tmp_path / "work")
    projet = reglages.projects_dir / "p"
    projet.mkdir(parents=True)
    assert ecrire_contexte(projet, "p", reglages) is True
    assert DEBUT in (projet / "CLAUDE.md").read_text(encoding="utf-8")
    assert ecrire_contexte(projet, "p", reglages) is False, "rien à réécrire"


def test_un_projet_a_la_structure_type_recoit_contexte_md(tmp_path: Path) -> None:
    reglages = AtelierSettings(work_dir=tmp_path / "work")
    projet = reglages.projects_dir / "p"
    projet.mkdir(parents=True)
    consigne = "@.atelier/contexte.md\n\n# P\n"
    (projet / "CLAUDE.md").write_text(consigne, encoding="utf-8")
    assert ecrire_contexte(projet, "p", reglages) is True
    assert (projet / "CLAUDE.md").read_text(encoding="utf-8") == consigne, "CLAUDE.md sans état ni adresse"
    assert DEBUT in (projet / ".atelier" / "contexte.md").read_text(encoding="utf-8")


def test_le_contexte_de_l_assistant_reste_dans_son_dossier(tmp_path: Path) -> None:
    reglages = AtelierSettings(work_dir=tmp_path / "work")
    dossier = reglages.assistant_sessions_dir / "s1"
    dossier.mkdir(parents=True)
    assert ecrire_contexte(dossier, reglages.assistant_slug, reglages) is True
    assert ecrire_contexte(tmp_path, reglages.assistant_slug, reglages) is False


