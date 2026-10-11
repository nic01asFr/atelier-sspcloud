"""D-53 : le store de wikichat quitte la couche éphémère sans rien perdre."""

from __future__ import annotations

import os
from pathlib import Path

from mcp_gateway.atelier import donnees_wikichat as d


def _remplir(racine: Path) -> None:
    (racine / "agents").mkdir(parents=True)
    (racine / "agents" / "a.json").write_text('{"x": 1}', encoding="utf-8")
    (racine / "triggers.json").write_text("[1, 2, 3]", encoding="utf-8")
    sel = racine / "identity-salt"
    sel.write_text("secret", encoding="utf-8")
    sel.chmod(0o600)
    (racine / "vide").mkdir()


def test_un_dossier_existant_est_migre_garde_et_lie(tmp_path: Path) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "work" / "wikichat" / "donnees"
    _remplir(home)
    etat, detail = d.lier_le_store(home, durable)
    assert etat == d.MIGRE and "avant-migration" in detail
    assert home.is_symlink() and home.resolve() == durable.resolve()
    assert (home / "triggers.json").read_text() == "[1, 2, 3]"
    assert (durable / "agents" / "a.json").read_text() == '{"x": 1}'
    assert (durable / "vide").is_dir()
    assert oct((durable / "identity-salt").stat().st_mode & 0o777) == "0o600"
    # L'ancien dossier est gardé, intact.
    garde = tmp_path / ".wikichat.avant-migration"
    assert (garde / "triggers.json").read_text() == "[1, 2, 3]"


def test_la_migration_est_idempotente(tmp_path: Path) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "donnees"
    _remplir(home)
    d.lier_le_store(home, durable)
    (home / "nouveau.json").write_text("{}", encoding="utf-8")
    assert d.lier_le_store(home, durable)[0] == d.DEJA_LIE
    assert (durable / "nouveau.json").exists()


def test_sans_dossier_le_lien_est_pose(tmp_path: Path) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "donnees"
    assert d.lier_le_store(home, durable)[0] == d.LIE
    (home / "x").write_text("1")
    assert (durable / "x").read_text() == "1"


def test_deux_jeux_de_donnees_ne_sont_pas_fusionnes(tmp_path: Path) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "donnees"
    _remplir(home)
    durable.mkdir()
    (durable / "autre.json").write_text("{}")
    etat, _ = d.lier_le_store(home, durable)
    assert etat == d.CONFLIT
    assert not home.is_symlink() and (home / "triggers.json").exists()
    assert sorted(p.name for p in durable.iterdir()) == ["autre.json"]


def test_un_durable_vide_deja_cree_n_empeche_pas_la_migration(tmp_path: Path) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "donnees"
    _remplir(home)
    durable.mkdir()
    assert d.lier_le_store(home, durable)[0] == d.MIGRE
    assert (durable / "triggers.json").exists()


def test_un_lien_vers_ailleurs_n_est_pas_touche(tmp_path: Path) -> None:
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    home = tmp_path / ".wikichat"
    home.symlink_to(ailleurs, target_is_directory=True)
    assert d.lier_le_store(home, tmp_path / "donnees")[0] == d.AILLEURS
    assert home.resolve() == ailleurs.resolve()


def test_si_le_lien_echoue_l_ancien_dossier_revient(tmp_path: Path, monkeypatch) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "donnees"
    _remplir(home)

    def casse(*_a, **_k):
        raise OSError("pas de lien ici")

    monkeypatch.setattr(d, "_poser_le_lien", casse)
    etat, detail = d.lier_le_store(home, durable)
    assert etat == d.REFUSE and "remis en place" in detail
    assert home.is_dir() and not home.is_symlink() and (home / "triggers.json").exists()


def test_une_copie_qui_ne_correspond_pas_ne_deplace_rien(tmp_path: Path, monkeypatch) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "donnees"
    _remplir(home)
    vrai = d._inventaire
    appels = {"n": 0}

    def trompeur(racine: Path):
        appels["n"] += 1
        inv = vrai(racine)
        if appels["n"] == 1:
            inv["fantome"] = 1
        return inv

    monkeypatch.setattr(d, "_inventaire", trompeur)
    assert d.lier_le_store(home, durable)[0] == d.REFUSE
    assert home.is_dir() and not home.is_symlink() and not durable.exists()


def test_la_ligne_de_commande_rend_un_code_utilisable_par_l_init(tmp_path: Path, capsys) -> None:
    home, durable = tmp_path / ".wikichat", tmp_path / "donnees"
    _remplir(home)
    assert d.main([str(home), str(durable)]) == 0
    assert capsys.readouterr().out.startswith("migre:")
    assert d.main([str(home)]) == 2


def test_apres_un_redemarrage_le_lien_reprend_les_donnees_du_volume(tmp_path: Path) -> None:
    """Conteneur neuf : plus de ~/.wikichat, mais la copie posée sur le volume avant."""
    home, durable = tmp_path / ".wikichat", tmp_path / "work" / "wikichat" / "donnees"
    _remplir(durable)
    assert d.lier_le_store(home, durable)[0] == d.LIE
    assert (home / "triggers.json").read_text() == "[1, 2, 3]"
