"""Les pièces jointes d'un message : un chemin que l'agent lit du premier coup, et ce qu'il peut en faire.

Le 13/10, `@.atelier/uploads/…` (relatif) a été résolu par un modèle non-Claude depuis son HOME
(`/home/onyxia/.atelier/uploads/…`) : « File does not exist » deux fois avant qu'il devine le bon chemin.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mcp_gateway.atelier import session_attachments as sa


def test_la_mention_est_un_chemin_absolu_qui_existe(tmp_path: Path) -> None:
    cwd = tmp_path / "assistant" / "sessions" / "abc"
    cwd.mkdir(parents=True)
    meta = sa.save_upload(cwd, "CANBT zoom (2).png", b"\x89PNG", mime="image/png")
    message = sa.enrich_message_with_attachments(cwd, "regarde", [meta.id])
    ligne = message.splitlines()[1]
    assert ligne.startswith("@/"), "absolu : lu pareil depuis n'importe quel dossier, par n'importe quel modèle"
    assert Path(ligne[1:]).is_file()
    assert ".atelier/uploads/" in ligne and ligne.endswith("_CANBT zoom (2).png")


def test_un_message_sans_texte_porte_seulement_les_fichiers(tmp_path: Path) -> None:
    meta = sa.save_upload(tmp_path, "a.txt", b"x")
    message = sa.enrich_message_with_attachments(tmp_path, "", [meta.id])
    assert message == "@" + meta.abs_path


@pytest.mark.parametrize(
    "nom, taille, genre",
    [
        ("CANBT.html", 500_000, "texte"),
        ("notes.md", 10, "texte"),
        ("carte.GEOJSON", 10, "texte"),
        ("photo.PNG", 10, "image"),
        ("rapport.pdf", 10, "pdf"),
        ("donnees.xlsx", 10, "a_ouvrir"),
        ("dossier.zip", 10, "a_ouvrir"),
        ("base.gpkg", 10, "a_ouvrir"),
        ("machin.xyz", 10, "inconnu"),
        ("sans_extension", 10, "inconnu"),
    ],
)
def test_le_genre_dit_ce_que_l_agent_peut_en_faire(nom: str, taille: int, genre: str) -> None:
    assert sa.lisibilite(nom, taille)[0] == genre


def test_un_fichier_lisible_ne_porte_pas_de_conseil_sauf_s_il_est_gros() -> None:
    assert sa.lisibilite("a.html", 1000)[1] == ""
    assert "tranches" in sa.lisibilite("a.html", sa.GROS_TEXTE_OCTETS + 1)[1]
    assert sa.lisibilite("a.png", 10**7)[1] == ""


def test_un_fichier_que_read_ne_lit_pas_porte_une_ligne_de_conseil(tmp_path: Path) -> None:
    meta = sa.save_upload(tmp_path, "bilan 2025.xlsx", b"PK")
    message = sa.enrich_message_with_attachments(tmp_path, "analyse", [meta.id])
    note = message.splitlines()[-1]
    assert note.startswith("(pièce jointe « bilan 2025.xlsx » — ")
    assert "pandas" in note and "jamais avec Read" in note


def test_l_envoi_relu_depuis_le_disque_porte_les_memes_conseils(tmp_path: Path) -> None:
    meta = sa.save_upload(tmp_path, "archive.zip", b"PK")
    relu = sa.get_attachment(tmp_path, meta.id)
    assert relu is not None
    assert (relu.genre, relu.conseil) == (meta.genre, meta.conseil)
    assert relu.genre == "a_ouvrir" and "unzip" in relu.conseil


def test_l_upload_dit_ce_qu_il_en_sera(tmp_path: Path) -> None:
    d = sa.save_upload(tmp_path, "x.docx", b"PK").to_dict()
    assert d["genre"] == "a_ouvrir" and d["conseil"]
