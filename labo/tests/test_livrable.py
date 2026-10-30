"""Le livrable : ce qu'on télécharge depuis l'interface (un fichier ou une archive), rien de plus ; et le script qui le constitue."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from laboratoire.api import creer_app
from laboratoire.projet import Racine

sys.path.insert(0, str(Path(__file__).parent.parent / "outils"))
import constituer_livrable  # noqa: E402


def _livrable(racine: Racine) -> Path:
    d = racine.chemin / "livrable"
    d.mkdir()
    (d / "groupe_a.pt").write_bytes(b"\x00modele\x01" * 100)
    (d / "groupe_a_lots.csv").write_text("fichier,jeu\nx.jpg,train\n", encoding="utf-8")
    with (d / "synthese.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["groupe", "modele", "rappel_moyen"])
        w.writerow(["groupe_a", "yolo26n-cls", "0.5"])
    return d


@pytest.fixture()
def client(racine: Racine):
    with TestClient(creer_app(racine, demarrer_travailleur=False)) as c:
        yield c


def test_sans_livrable_l_interface_le_dit_au_lieu_d_echouer(client: TestClient) -> None:
    assert client.get("/api/livrable").json() == {"existe": False, "fichiers": [], "taille_totale": 0, "synthese": []}
    assert client.get("/api/livrable/archive").status_code == 404


def test_on_liste_et_on_telecharge_un_fichier_ou_tout_en_archive(client: TestClient, racine: Racine) -> None:
    _livrable(racine)
    r = client.get("/api/livrable").json()
    assert r["existe"] and {f["nom"] for f in r["fichiers"]} == {"groupe_a.pt", "groupe_a_lots.csv", "synthese.csv"}
    assert r["synthese"] == [{"groupe": "groupe_a", "modele": "yolo26n-cls", "rappel_moyen": "0.5"}]
    f = client.get("/api/livrable/fichier", params={"nom": "groupe_a.pt"})
    assert f.status_code == 200 and f.content == b"\x00modele\x01" * 100 and "attachment" in f.headers["content-disposition"]
    a = client.get("/api/livrable/archive")
    assert a.status_code == 200 and a.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(a.content)) as z:
        assert sorted(z.namelist()) == ["livrable/groupe_a.pt", "livrable/groupe_a_lots.csv", "livrable/synthese.csv"]
        assert z.read("livrable/groupe_a.pt") == b"\x00modele\x01" * 100


def test_le_livrable_ne_sert_que_ses_propres_fichiers(client: TestClient, racine: Racine) -> None:
    d = _livrable(racine)
    (racine.chemin / "secret.txt").write_text("secret", encoding="utf-8")
    (d / "sous").mkdir()
    (d / "sous" / "cache.txt").write_text("x", encoding="utf-8")
    (d / "lien.txt").symlink_to(racine.chemin / "secret.txt")
    (d / ".cache").write_text("x", encoding="utf-8")
    for mauvais in ("../secret.txt", "/etc/passwd", "sous/cache.txt", "lien.txt", ".cache", "groupe_a.PT", "", "inconnu"):
        assert client.get("/api/livrable/fichier", params={"nom": mauvais}).status_code in (404, 422), mauvais
    noms = {f["nom"] for f in client.get("/api/livrable").json()["fichiers"]}
    assert noms == {"groupe_a.pt", "groupe_a_lots.csv", "synthese.csv"}  # ni sous-dossier, ni lien, ni fichier caché
    with zipfile.ZipFile(io.BytesIO(client.get("/api/livrable/archive").content)) as z:
        assert "livrable/lien.txt" not in z.namelist() and "livrable/.cache" not in z.namelist()


def test_le_relecteur_telecharge_le_valideur_non(racine: Racine) -> None:
    _livrable(racine)
    (racine.chemin / "valideurs.json").write_text(json.dumps({"Mathieu": {"jeton": "tm", "role": "relecteur"}, "Julie": "tj"}), encoding="utf-8")
    with TestClient(creer_app(racine, jeton="admin", demarrer_travailleur=False)) as c:
        entete = lambda j: {"Authorization": f"Bearer {j}"}
        assert c.get("/api/livrable", headers={}).status_code == 401
        assert c.get("/api/livrable/archive", headers=entete("tm")).status_code == 200
        assert c.get("/api/livrable/fichier", params={"nom": "synthese.csv"}, headers=entete("admin")).status_code == 200
        assert c.get("/api/livrable", headers=entete("tj")).status_code == 403  # un valideur ne voit que la validation


def test_la_page_declare_l_onglet_et_le_script() -> None:
    web = Path(__file__).parent.parent / "src" / "laboratoire" / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert 'href="#/livrable"' in html and "web/livrable.js" in html
    assert 'section === "livrable"' in (web / "app.js").read_text(encoding="utf-8")


# -- le script qui constitue le livrable ---------------------------------------


def _projet_de_classification(racine: Path) -> None:
    racine.mkdir(parents=True)
    base = sqlite3.connect(racine / "labo.db")
    base.execute("CREATE TABLE essais (id TEXT PRIMARY KEY, jeu TEXT, etat TEXT, note TEXT)")
    (racine / "donnees" / "variantes" / "jeu1").mkdir(parents=True)
    (racine / "donnees" / "variantes" / "jeu1" / "manifeste.csv").write_text("fichier,jeu,classe,groupe,source\na,train,0,g,s\nb,val,1,g2,s2\nc,test,0,g3,s3\n", encoding="utf-8")
    numero = 30
    for modele, rappels in (("yolo26n-cls", (0.40, 0.42, 0.38)), ("yolo26s-cls", (0.50, 0.52, 0.48))):
        for graine, rappel in enumerate(rappels):
            ident = f"E{numero:04d}"
            numero += 1
            base.execute("INSERT INTO essais VALUES (?,?,?,?)", (ident, "jeu1", "termine", f"v2 28/10 : recadrage droite nombre · réduction 64×64 explicite · {modele} · graine {graine}"))
            dossier = racine / "essais" / ident
            (dossier / "poids").mkdir(parents=True)
            (dossier / "poids" / "last.pt").write_bytes(f"{ident}".encode())
            (dossier / "resultats.json").write_text(json.dumps({
                "jeu": "val",
                "rapport": {"total": 4, "exactitude": 0.75, "rappel_moyen": rappel, "classes": ["0", "1"], "confusion": [[2, 0], [1, 1]],
                            "par_classe": {"0": {"n": 2, "rappel": 1.0, "precision": 0.67}, "1": {"n": 2, "rappel": 0.5, "precision": 1.0}}},
                "triviales": {"majoritaire": {"exactitude": 0.5}},
            }), encoding="utf-8")
    base.execute("INSERT INTO essais VALUES ('E0099','jeu1','termine','essai libre sans le format')")
    base.commit()
    base.close()
    # Le test scellé existe mais le script ne doit jamais l'ouvrir.
    (racine / "essais" / "E0030" / "test_scelle.json").write_text("{interdit", encoding="utf-8")


def test_le_script_retient_le_meilleur_modele_livre_la_graine_zero_et_ne_lit_que_la_validation(tmp_path: Path) -> None:
    racine = tmp_path / "labo"
    _projet_de_classification(racine)
    synthese = constituer_livrable.constituer(racine, "E0030", "réduction")
    assert len(synthese) == 1
    ligne = dict(zip(constituer_livrable.COLONNES, synthese[0]))
    assert ligne["groupe"] == "panoramique_droite_nombre" and ligne["modele"] == "yolo26s-cls"  # 0,50 contre 0,40 : écart > 0,02
    assert ligne["essai_livre"] == "E0033" and (racine / "livrable" / "panoramique_droite_nombre.pt").read_bytes() == b"E0033"  # graine 0 de yolo26s
    assert ligne["train"] == 1 and ligne["val"] == 1 and ligne["test"] == 1 and ligne["hasard"] == 0.5
    mesures = json.loads((racine / "livrable" / "panoramique_droite_nombre_mesures.json").read_text(encoding="utf-8"))
    assert mesures["test"] == "scellé, non ouvert" and mesures["trois_graines"]["essais"] == ["E0033", "E0034", "E0035"]
    assert mesures["trois_graines"]["rappel_moyen_moyenne"] == pytest.approx(0.5)
    with (racine / "livrable" / "synthese.csv").open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == constituer_livrable.COLONNES


def test_le_script_ecarte_un_resultat_qui_ne_porte_pas_sur_la_validation(tmp_path: Path) -> None:
    racine = tmp_path / "labo"
    _projet_de_classification(racine)
    chemin = racine / "essais" / "E0031" / "resultats.json"
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    brut["jeu"] = "test"
    chemin.write_text(json.dumps(brut), encoding="utf-8")
    with pytest.raises(SystemExit, match="validation"):
        constituer_livrable.constituer(racine, "E0030", "réduction")


# -- le carnet d'accompagnement ------------------------------------------------


def test_le_carnet_se_rejoue_sur_un_livrable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pandas")
    matplotlib = pytest.importorskip("matplotlib")
    matplotlib.use("Agg")
    racine = tmp_path / "labo"
    _projet_de_classification(racine)
    chemin = racine / "essais" / "E0033" / "resultats.json"
    brut = json.loads(chemin.read_text(encoding="utf-8"))
    brut["rapport"]["rappel_moyen"] = 0.75  # cohérent avec la matrice [[2, 0], [1, 1]]
    chemin.write_text(json.dumps(brut), encoding="utf-8")
    constituer_livrable.constituer(racine, "E0030", "réduction")
    carnet = racine / "livrable" / "lire_le_livrable.ipynb"
    assert carnet.is_file()
    # le manifeste de la maquette n'a qu'une image par lot : le contrôle de fuite doit passer, et les sorties s'afficher
    monkeypatch.chdir(racine / "livrable")
    espace: dict = {"display": lambda *_: None}
    cellules = json.loads(carnet.read_text(encoding="utf-8"))["cells"]
    for c in cellules:
        if c["cell_type"] == "code":
            exec(compile("".join(c["source"]), "carnet", "exec"), espace)  # noqa: S102
    assert espace["controle"]["empreinte conforme"].all() and (espace["fuites"]["collections dans 2 lots"] == 0).all()
