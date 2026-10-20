"""Construire une variante : images préparées, manifeste lisible par les essais, contrôles qui démasquent les pièges."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from laboratoire.donnees.brut import ImageBrute
from laboratoire.donnees.construction import ConstructionRefusee, construire, nom_sur, preparer
from laboratoire.donnees.controles import Ligne, controler
from laboratoire.donnees.recette import Recette, planifier
from laboratoire.variante import Variante


def _brut(tmp_path: Path, collections: int = 12, par_classe: int = 6) -> tuple[Path, list[ImageBrute]]:
    brut = tmp_path / "brut"
    images = []
    for g in range(collections):
        for n in (0, 1, 2):
            for k in range(par_classe):
                rel = f"V/g{g}/x/droite/{n}/img{k}.jpeg"
                (brut / rel).parent.mkdir(parents=True, exist_ok=True)
                im = Image.new("RGB", (36, 24), (10, 10, 10))
                im.paste((250, 250, 250), (18, 0, 36, 24))  # moitié droite claire
                im.save(brut / rel)
                images.append(ImageBrute(rel, "V", f"V/g{g}/x", "droite", n, None, 36, 24))
    return brut, images


def test_rognage_garde_la_moitie_du_cote_et_masque_noircit_l_autre() -> None:
    im = Image.new("RGB", (40, 20), (255, 255, 255))
    im.paste((0, 0, 255), (0, 0, 20, 20))
    assert preparer(im, "droite", "rognage").size == (20, 20)
    assert preparer(im, "droite", "rognage").getpixel((5, 5)) == (255, 255, 255)
    assert preparer(im, "gauche", "rognage").getpixel((5, 5)) == (0, 0, 255)
    masque = preparer(im, "droite", "masque")
    assert masque.size == (40, 20) and masque.getpixel((5, 5)) == (0, 0, 0) and masque.getpixel((30, 5)) == (255, 255, 255)
    assert preparer(im, "droite", "aucune").size == (40, 20)


def test_construction_ecrit_un_manifeste_que_les_essais_savent_lire(tmp_path: Path) -> None:
    brut, images = _brut(tmp_path)
    recette = Recette(cote="droite", tache="nombre", reequilibrage={"actif": False})
    plan = planifier(images, recette)
    avancement = []
    resultat = construire(brut, plan, recette, tmp_path / "v", progression=lambda a, b: avancement.append((a, b)))
    v = Variante(tmp_path / "v")
    assert v.classes() == ["0", "1", "2"]
    assert sum(sum(c.values()) for c in v.effectifs().values()) == len(images)
    assert all(e.fichier.is_file() for j in ("train", "val", "test") for e in v.echantillons(j))
    assert avancement[-1] == (len(images), len(images))
    assert json.loads((tmp_path / "v" / "recette.json").read_text())["cote"] == "droite"
    assert (tmp_path / "v" / "controles.json").is_file() and resultat["effectifs"]["train"]
    # La préparation a bien eu lieu : rognage → moitié droite, donc 18×24 et claire.
    une = v.echantillons("train")[0].fichier
    with Image.open(une) as im:
        assert im.size == (18, 24) and im.getpixel((3, 3))[0] > 200
    # Aucune collection dans deux jeux.
    assert not (v.groupes("train") & v.groupes("val")) and not (v.groupes("train") & v.groupes("test"))


def test_les_copies_de_reequilibrage_ont_leur_propre_fichier_et_restent_dans_train(tmp_path: Path) -> None:
    brut, images = _brut(tmp_path)
    images = [i for i in images if not (i.n == 1 and not i.chemin.endswith(("img0.jpeg", "img1.jpeg")))]  # classe « 1 » rare
    recette = Recette(cote="droite", tache="nombre", reequilibrage={"actif": True, "rapport": 1.0})
    plan = planifier(images, recette)
    construire(brut, plan, recette, tmp_path / "v")
    v = Variante(tmp_path / "v")
    copies = [e for e in v.echantillons("train") if "__dup" in e.fichier.name]
    assert copies and all(e.jeu == "train" for e in copies)
    assert not [e for j in ("val", "test") for e in v.echantillons(j) if "__dup" in e.fichier.name]
    assert len({e.fichier for e in v.echantillons("train")}) == len(v.echantillons("train"))  # pas deux lignes sur un même fichier


def test_une_construction_n_ecrase_pas_et_ne_laisse_rien_a_moitie(tmp_path: Path) -> None:
    brut, images = _brut(tmp_path)
    recette = Recette(cote="droite", tache="nombre")
    plan = planifier(images, recette)
    construire(brut, plan, recette, tmp_path / "v")
    with pytest.raises(ConstructionRefusee, match="existe déjà"):
        construire(brut, plan, recette, tmp_path / "v")
    (brut / images[0].chemin).unlink()  # une image disparaît en cours de route
    with pytest.raises(FileNotFoundError):
        construire(brut, plan, recette, tmp_path / "w")
    assert not (tmp_path / "w").exists() and not (tmp_path / "w.encours").exists()


def test_aucune_image_retenue_est_refuse(tmp_path: Path) -> None:
    brut, images = _brut(tmp_path)
    plan = planifier(images, Recette(cote="gauche", tache="nombre"))
    with pytest.raises(ConstructionRefusee):
        construire(brut, plan, Recette(cote="gauche", tache="nombre"), tmp_path / "v")


def test_nom_sur() -> None:
    assert nom_sur("Ville/a b") == "Ville_a_b"
    assert "/" not in nom_sur("../../x") and nom_sur("///") == "x"


def _l(jeu, classe, groupe, source=None, copie=False) -> Ligne:
    return Ligne(jeu, classe, groupe, source or f"{groupe}/{classe}/{jeu}", copie)


def _codes(constats) -> set[str]:
    return {c["code"] for c in constats}


def test_une_fuite_de_collection_est_bloquante() -> None:
    lignes = [_l("train", "0", "g1", "a"), _l("val", "0", "g1", "b"), _l("test", "0", "g2", "c")]
    constats = controler(lignes)
    assert "fuite_groupe" in _codes(constats)
    assert next(c for c in constats if c["code"] == "fuite_groupe")["gravite"] == "bloquant"


def test_une_meme_image_dans_deux_jeux_est_une_fuite() -> None:
    lignes = [_l("train", "0", "g1", "a"), _l("val", "0", "g2", "a"), _l("test", "0", "g3", "c")]
    assert "fuite_image" in _codes(controler(lignes))


def test_classes_absentes_rares_et_jeu_vide() -> None:
    lignes = [_l("train", "0", "g1", "a"), _l("train", "1", "g1", "b"), _l("val", "0", "g2", "c")]
    c = controler(lignes)
    assert {"jeu_vide", "classe_absente", "classe_rare"} <= _codes(c)
    assert next(x for x in c if x["code"] == "jeu_vide")["jeu"] == "test"
    absente = next(x for x in c if x["code"] == "classe_absente" and x["jeu"] == "val")
    assert absente["classes"] == ["1"] and absente["gravite"] == "avertissement"
    # Une classe absente du train, elle, est bloquante.
    c2 = controler([_l("train", "0", "g1", "a"), _l("val", "1", "g2", "b"), _l("test", "1", "g3", "c")], ["0", "1"])
    assert any(x["code"] == "classe_absente" and x["jeu"] == "train" and x["gravite"] == "bloquant" for x in c2)


def test_les_copies_ne_sont_pas_des_doublons_mais_un_vrai_doublon_l_est() -> None:
    base = [_l("val", "0", "g2", "v"), _l("test", "0", "g3", "t")]
    assert "doublon" not in _codes(controler(base + [_l("train", "0", "g1", "a"), _l("train", "0", "g1", "a", copie=True)]))
    assert "doublon" in _codes(controler(base + [_l("train", "0", "g1", "a"), _l("train", "0", "g1", "a")]))
    assert "copie_hors_train" in _codes(controler(base + [_l("val", "0", "g2", "v", copie=True)]))


def test_desequilibre_ignore_les_copies() -> None:
    lignes = [_l("train", "0", "g1", f"a{i}") for i in range(50)] + [_l("train", "1", "g1", "b")] + [_l("train", "1", "g1", "b", copie=True)] * 40
    assert "desequilibre" in _codes(controler(lignes))
