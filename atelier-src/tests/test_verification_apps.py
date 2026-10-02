"""Ce qu'une page autonome promet sans le tenir : les phrases rendues à l'agent.

Cas relevés en production : un dossier créé mais jamais rempli (la personne
ouvrait une page vide), une page qui référence des images que personne n'a
déposées (des 404 en silence).
"""

from __future__ import annotations

from pathlib import Path

from mcp_gateway.atelier.apps.verification import MAX_AVERTISSEMENTS, verifier_references


def _creation(tmp_path: Path, html: str | None, *autres: str) -> Path:
    dossier = tmp_path / "artifacts" / "demo"
    dossier.mkdir(parents=True)
    (dossier / ".auteur").write_text("agent\n", encoding="utf-8")
    if html is not None:
        (dossier / "index.html").write_text(html, encoding="utf-8")
    for nom in autres:
        (dossier / nom).parent.mkdir(parents=True, exist_ok=True)
        (dossier / nom).write_bytes(b"x")
    return dossier


def test_un_dossier_cree_mais_vide_est_dit_vide(tmp_path: Path) -> None:
    (phrase,) = verifier_references(_creation(tmp_path, None))
    assert "est vide" in phrase and "ne dépose rien" in phrase


def test_des_fichiers_sans_index_html_sont_signales(tmp_path: Path) -> None:
    (phrase,) = verifier_references(_creation(tmp_path, None, "notes.txt"))
    assert "pas de index.html" in phrase


def test_une_page_qui_tient_ses_promesses_ne_dit_rien(tmp_path: Path) -> None:
    html = (
        '<link rel="stylesheet" href="style.css"><img src="img/a.png">'
        '<img src="data:image/png;base64,AAAA"><a href="https://exemple.fr">lien</a>'
        '<link rel="canonical" href="https://exemple.fr/x"><script src="app.js?v=2#haut"></script>'
        '<div style="background:url(img/a.png)"></div>'
    )
    assert verifier_references(_creation(tmp_path, html, "style.css", "img/a.png", "app.js")) == []


def test_un_fichier_absent_est_nomme(tmp_path: Path) -> None:
    (phrase,) = verifier_references(_creation(tmp_path, '<img src="dav2_depth.png">'))
    assert "fichier absent : dav2_depth.png" in phrase


def test_une_ressource_externe_est_bloquee_et_le_dit(tmp_path: Path) -> None:
    html = '<script src="https://cdn.exemple.fr/lib.js"></script><img src="//img.exemple.fr/a.png">'
    phrases = verifier_references(_creation(tmp_path, html))
    assert len(phrases) == 2 and all("bloquée" in p and "réseau" in p for p in phrases)
    # Un lien <a> n'est pas une sous-ressource : il ne charge rien.
    assert verifier_references(_creation(tmp_path / "b", '<a href="https://exemple.fr">x</a>')) == []


def test_un_chemin_absolu_part_ailleurs(tmp_path: Path) -> None:
    (phrase,) = verifier_references(_creation(tmp_path, '<img src="/img/a.png">'))
    assert "chemin absolu /img/a.png" in phrase and "img/a.png" in phrase


def test_un_chemin_qui_sort_du_dossier_est_refuse_sans_le_lire(tmp_path: Path) -> None:
    dossier = _creation(tmp_path, '<img src="../../secret.png">')
    (tmp_path / "secret.png").write_bytes(b"x")  # existe, mais hors de la création
    (phrase,) = verifier_references(dossier)
    assert "sort du dossier" in phrase


def test_les_url_des_feuilles_de_style_sont_lues(tmp_path: Path) -> None:
    html = "<style>body{background:url('fond.jpg')}</style>"
    (phrase,) = verifier_references(_creation(tmp_path, html))
    assert "fichier absent : fond.jpg" in phrase


def test_la_liste_est_bornee(tmp_path: Path) -> None:
    html = "".join(f'<img src="m{i}.png">' for i in range(MAX_AVERTISSEMENTS + 5))
    phrases = verifier_references(_creation(tmp_path, html))
    assert len(phrases) == MAX_AVERTISSEMENTS + 1 and phrases[-1] == "… et 5 autres"


def test_une_page_mal_formee_ne_fait_pas_echouer(tmp_path: Path) -> None:
    assert isinstance(verifier_references(_creation(tmp_path, "<img src='a.png' <<< <div")), list)


def test_un_dossier_absent_est_dit(tmp_path: Path) -> None:
    (phrase,) = verifier_references(tmp_path / "artifacts" / "nulle-part")
    assert "n'existe pas" in phrase
