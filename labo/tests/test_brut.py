"""Lire le brut : la structure réelle, ses cas tordus, et le refus de deviner."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from laboratoire.donnees.brut import scanner


def _img(racine: Path, chemin: str, taille=(24, 16)) -> None:
    p = racine / chemin
    p.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", taille, (10, 10, 10)).save(p, "JPEG")


def _brut(tmp_path: Path) -> Path:
    b = tmp_path / "brut"
    for chemin in (
        "ECHIROLLES/14239/uuid-a/droite/0/001 x.jpeg",
        "ECHIROLLES/14239/uuid-a/droite/1/002 x.jpeg",
        "ECHIROLLES/14239/uuid-a/gauche/4/bataille/003 x.jpeg",
        "ECHIROLLES/14239/uuid-a/droite/longitudinal/004 x.jpeg",
        "FONTAINE1/uuid-b/13767/gauche/1/005 x.jpeg",  # FONTAINE1 : collection et route inversées
    ):
        _img(b, chemin)
    return b


def test_la_structure_reelle_est_lue_avec_nombre_forme_et_collection(tmp_path: Path) -> None:
    r = scanner(_brut(tmp_path))
    assert r.anomalies == []
    par_nom = {i.chemin.rsplit("/", 1)[1]: i for i in r.images}
    assert (par_nom["001 x.jpeg"].cote, par_nom["001 x.jpeg"].n, par_nom["001 x.jpeg"].forme) == ("droite", 0, None)
    deux = par_nom["003 x.jpeg"]  # N places ET une forme
    assert (deux.cote, deux.n, deux.forme) == ("gauche", 4, "bataille")
    seule = par_nom["004 x.jpeg"]  # une forme seule
    assert (seule.n, seule.forme) == (None, "longitudinal")
    assert par_nom["001 x.jpeg"].groupe == "ECHIROLLES/14239/uuid-a"
    assert par_nom["005 x.jpeg"].groupe == "FONTAINE1/uuid-b/13767"  # l'ordre inversé n'empêche pas d'identifier la collection


def test_le_resume_compte(tmp_path: Path) -> None:
    resume = scanner(_brut(tmp_path)).resume()
    assert resume["images"] == 5 and resume["collections"] == 2
    assert resume["par_cote"] == {"droite": 3, "gauche": 2}
    assert resume["par_nombre"] == {"0": 1, "1": 2, "4": 1, "—": 1}
    assert resume["par_forme"] == {"bataille": 1, "longitudinal": 1, "—": 3}
    assert resume["plates"] == 0 and resume["recadrages"] == 5


def test_une_photo_pleine_resolution_est_plate_le_reste_est_un_recadrage(tmp_path: Path) -> None:
    b = tmp_path / "brut"
    _img(b, "V/a/b/droite/0/plate.jpeg", taille=(1600, 30))
    _img(b, "V/a/b/droite/0/recadrage.jpeg", taille=(36, 24))
    r = scanner(b)
    assert {i.chemin.rsplit("/", 1)[1]: i.plate for i in r.images} == {"plate.jpeg": True, "recadrage.jpeg": False}
    assert r.resume()["plates"] == 1 and r.resume()["recadrages"] == 1


def test_ce_qui_ne_rentre_pas_est_signale_et_non_classe_au_hasard(tmp_path: Path) -> None:
    b = _brut(tmp_path)
    for chemin in (
        "ECHIROLLES/14239/uuid-a/devant/0/x.jpeg",  # côté inconnu
        "ECHIROLLES/14239/uuid-a/droite/oblique/x.jpeg",  # classe inconnue
        "ECHIROLLES/14239/uuid-a/droite/2/diagonale/x.jpeg",  # forme inconnue
        "ECHIROLLES/14239/x.jpeg",  # trop haut
        "ECHIROLLES/14239/uuid-a/droite/2/bataille/trop/profond.jpeg",
    ):
        _img(b, chemin)
    r = scanner(b)
    assert len(r.images) == 5  # les cinq bonnes images, pas une de plus
    assert len(r.anomalies) == 5
    assert any("côté inconnu" in a for a in r.anomalies) and any("forme inconnue" in a for a in r.anomalies)
    assert any("trop peu de niveaux" in a for a in r.anomalies)


def test_les_fichiers_qui_ne_sont_pas_des_images_sont_ignores(tmp_path: Path) -> None:
    b = _brut(tmp_path)
    (b / "ECHIROLLES/14239/uuid-a/classes.csv").write_text("a,b\n", encoding="utf-8")
    (b / "ECHIROLLES/14239/uuid-a/pictures.gpkg").write_bytes(b"x")
    r = scanner(b)
    assert len(r.images) == 5 and r.anomalies == []


def test_une_image_illisible_est_comptee_pas_fatale(tmp_path: Path) -> None:
    b = tmp_path / "brut"
    chemin = b / "V/a/b/droite/0/cassee.jpeg"
    chemin.parent.mkdir(parents=True)
    chemin.write_bytes(b"pas une image")
    r = scanner(b)
    assert r.images[0].largeur is None and r.resume()["taille_inconnue"] == 1


def test_un_dossier_brut_absent_est_une_anomalie(tmp_path: Path) -> None:
    r = scanner(tmp_path / "rien")
    assert r.images == [] and "introuvable" in r.anomalies[0]
