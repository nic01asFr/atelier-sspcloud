"""Le socle des agents se pose depuis le code, sans jamais écraser en silence.

`~/work/projects/CLAUDE.md` est lu par tous les agents code, sur toutes les
surfaces. Il vient de `mcp_gateway/atelier/consignes/socle.md`, posé par
l'init et par le démarrage de l'Atelier.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mcp_gateway.atelier import socle
from mcp_gateway.atelier.commandes.journal import Journal

RACINE_SRC = Path(__file__).resolve().parents[1]
INIT = RACINE_SRC.parent / "install" / "atelier-init.sh"


def _reglages(tmp_path: Path) -> SimpleNamespace:
    work = tmp_path / "work"
    return SimpleNamespace(work_dir=work, projects_dir=work / "projects")


def _source(tmp_path: Path, texte: str) -> Path:
    chemin = tmp_path / "source" / "socle.md"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(texte, encoding="utf-8")
    return chemin


def _journal(reglages: SimpleNamespace) -> Journal:
    return Journal(reglages.work_dir / ".atelier-etat" / "journal")


def test_le_socle_voyage_avec_le_paquet() -> None:
    """Il est dans l'arbre copié par l'image et l'extraction, et déclaré au paquet."""
    assert socle.SOURCE.is_file()
    assert socle.SOURCE.is_relative_to(RACINE_SRC / "mcp_gateway")
    assert "consignes/*.md" in (RACINE_SRC / "pyproject.toml").read_text(encoding="utf-8")
    assert socle.SOURCE.read_text(encoding="utf-8").startswith("# ")


def test_pose_puis_ne_reecrit_pas(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    source = _source(tmp_path, "# Socle v1\n")
    journal = _journal(reglages)

    r = socle.poser_le_socle(reglages, journal=journal, source=source)
    assert r["resultat"] == "pose"
    cible = reglages.projects_dir / "CLAUDE.md"
    assert cible.read_text(encoding="utf-8") == "# Socle v1\n"
    mtime = cible.stat().st_mtime_ns

    r = socle.poser_le_socle(reglages, journal=journal, source=source)
    assert r["resultat"] == "a-jour"
    assert cible.stat().st_mtime_ns == mtime
    evenements = journal.lire()
    assert [e["resultat"] for e in evenements] == ["pose"], "une pose, pas une ligne par démarrage"
    assert evenements[0]["acteur"] == "atelier:socle"


def test_met_a_jour_la_version_precedente_intacte(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    journal = _journal(reglages)
    socle.poser_le_socle(reglages, journal=journal, source=_source(tmp_path, "# Socle v1\n"))

    r = socle.poser_le_socle(reglages, journal=journal, source=_source(tmp_path, "# Socle v2\n"))
    assert r["resultat"] == "mis-a-jour"
    assert "copie" not in r
    assert (reglages.projects_dir / "CLAUDE.md").read_text(encoding="utf-8") == "# Socle v2\n"
    assert not (reglages.work_dir / ".atelier-etat" / "socle").exists(), "rien à sauver : c'était notre texte"


def test_un_fichier_modifie_a_la_main_est_garde_et_journalise(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    journal = _journal(reglages)
    socle.poser_le_socle(reglages, journal=journal, source=_source(tmp_path, "# Socle v1\n"))
    cible = reglages.projects_dir / "CLAUDE.md"
    cible.write_text("# Socle v1\n\nAjout de la personne.\n", encoding="utf-8")

    quand = datetime(2026, 9, 26, 14, 30, 5, tzinfo=timezone.utc)
    r = socle.poser_le_socle(reglages, journal=journal, source=_source(tmp_path, "# Socle v2\n"), maintenant=quand)
    assert r["resultat"] == "remplace-modifie"
    copie = Path(r["copie"])
    assert copie.name == "CLAUDE.md.20260926-143005"
    assert copie.read_text(encoding="utf-8") == "# Socle v1\n\nAjout de la personne.\n"
    assert cible.read_text(encoding="utf-8") == "# Socle v2\n"
    dernier = journal.lire()[0]
    assert dernier["resultat"] == "remplace-modifie"
    assert dernier["action"]["avant"]["copie"] == str(copie)
    assert dernier["action"]["avant"]["raison"] == "empreinte différente de la dernière pose"


def test_un_fichier_pose_a_la_main_avant_l_atelier_est_garde(tmp_path: Path) -> None:
    """Le cas du pod le 26/09 : un socle recopié à la main, aucune pose connue."""
    reglages = _reglages(tmp_path)
    cible = reglages.projects_dir / "CLAUDE.md"
    cible.parent.mkdir(parents=True)
    cible.write_text("# Ancien socle du 25/09\n", encoding="utf-8")
    journal = _journal(reglages)

    r = socle.poser_le_socle(reglages, journal=journal, source=_source(tmp_path, "# Socle\n"))
    assert r["resultat"] == "remplace-modifie"
    assert Path(r["copie"]).read_text(encoding="utf-8") == "# Ancien socle du 25/09\n"
    assert journal.lire()[0]["action"]["avant"]["raison"] == "aucune pose connue de l'Atelier"


def test_sans_copie_possible_rien_n_est_ecrase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    reglages = _reglages(tmp_path)
    cible = reglages.projects_dir / "CLAUDE.md"
    cible.parent.mkdir(parents=True)
    cible.write_text("# À la main\n", encoding="utf-8")
    vraie = socle.ecrire_atomiquement

    def refuser_la_copie(chemin: Path, texte: str, mode: int = 0o644) -> None:
        if chemin.parent.name == "socle":
            raise PermissionError("lecture seule")
        vraie(chemin, texte, mode)

    monkeypatch.setattr(socle, "ecrire_atomiquement", refuser_la_copie)
    r = socle.poser_le_socle(reglages, journal=None, source=_source(tmp_path, "# Socle\n"))
    assert r["resultat"] == "erreur"
    assert cible.read_text(encoding="utf-8") == "# À la main\n"


def test_ecriture_atomique_sans_reste(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cible = tmp_path / "projects" / "CLAUDE.md"
    socle.ecrire_atomiquement(cible, "un\n")

    def panne(*_a: object) -> None:
        raise OSError("disque plein")

    monkeypatch.setattr(socle.os, "replace", panne)
    with pytest.raises(OSError):
        socle.ecrire_atomiquement(cible, "deux\n")
    assert cible.read_text(encoding="utf-8") == "un\n", "l'ancien texte reste entier"
    assert [p.name for p in cible.parent.iterdir()] == ["CLAUDE.md"], "pas de fichier provisoire laissé"


def test_source_absente_ne_touche_a_rien(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    r = socle.poser_le_socle(reglages, journal=None, source=tmp_path / "absent.md")
    assert r["resultat"] == "source-absente"
    assert not (reglages.projects_dir / "CLAUDE.md").exists()


def test_la_commande_de_l_init_pose_le_socle_du_paquet(tmp_path: Path) -> None:
    """`python3 -m mcp_gateway.atelier.socle`, tel que l'init l'appelle."""
    work = tmp_path / "work"
    env = {**os.environ, "ATELIER_WORK": str(work), "HOME": str(tmp_path), "USERPROFILE": str(tmp_path)}
    fini = subprocess.run(
        [sys.executable, "-m", "mcp_gateway.atelier.socle"],
        cwd=RACINE_SRC, env=env, capture_output=True, text=True, timeout=60,
    )
    assert fini.returncode == 0, fini.stderr
    assert json.loads(fini.stdout.strip().splitlines()[-1])["resultat"] == "pose"
    assert (work / "projects" / "CLAUDE.md").read_text(encoding="utf-8") == socle.SOURCE.read_text(encoding="utf-8")
    lignes = (work / ".atelier-etat" / "journal").glob("*.jsonl")
    assert any('"atelier:socle"' in f.read_text(encoding="utf-8") for f in lignes)


@pytest.mark.skipif(os.name == "nt" or shutil.which("bash") is None, reason="bloc shell de l'init : pod Linux")
def test_le_bloc_de_l_init_pose_le_socle(tmp_path: Path) -> None:
    texte = INIT.read_text(encoding="utf-8")
    bloc = texte[texte.index("# --- socle des agents") : texte.index("# --- démarrage")]
    work = tmp_path / "work"
    script = (
        "set -euo pipefail\n"
        "dire() { printf '%s\\n' \"$*\"; }\n"
        "avertir() { printf 'ATTENTION %s\\n' \"$*\" >&2; }\n"
        f'WORK="{work}"\nSRC_ATELIER="{RACINE_SRC}"\n' + bloc
    )
    fini = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=60,
                          env={**os.environ, "HOME": str(tmp_path)})
    assert fini.returncode == 0, fini.stderr
    assert "socle des agents" in fini.stdout
    assert (work / "projects" / "CLAUDE.md").is_file()

