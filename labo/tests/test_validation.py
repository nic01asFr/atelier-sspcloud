"""La validation humaine : un journal qu'on n'altère pas, des files déterministes, des routes qui ne sortent pas du brut."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from laboratoire.api import creer_app
from laboratoire.donnees.brut import ImageBrute
from laboratoire.donnees.recette import Recette, etiqueter
from laboratoire.projet import Racine
from laboratoire.validation.files import file_d_images, voisins
from laboratoire.validation.journal import Decision, DecisionRefusee, Journal, nom_valide


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "validation.db")


def _d(journal: Journal, image="V/g0/x/droite/1/001.jpeg", valideur="Alice", nombre=1, forme="aucune", **kw) -> int:
    base = dict(image=image, validateur=valideur, nombre=nombre, forme=forme, douteuse=False, fichier="audit_classe_1", ancien_nombre=0, ancienne_forme="aucune")
    base.update(kw)
    return journal.enregistrer(**base)


def test_le_journal_ne_se_modifie_ni_ne_se_vide_meme_a_la_main(journal: Journal, tmp_path: Path) -> None:
    ident = _d(journal)
    direct = sqlite3.connect(tmp_path / "validation.db")
    with pytest.raises(sqlite3.DatabaseError, match="ne se modifie pas"):
        direct.execute("UPDATE decisions SET nombre=9 WHERE id=?", (ident,))
    with pytest.raises(sqlite3.DatabaseError, match="ne se vide pas"):
        direct.execute("DELETE FROM decisions")
    assert journal.tout()[0]["nombre"] == 1


def test_annuler_ajoute_une_ligne_et_remet_l_image_a_faire(journal: Journal) -> None:
    ident = _d(journal)
    assert journal.deja_faites("Alice", "audit_classe_1") == {"V/g0/x/droite/1/001.jpeg"}
    journal.annuler(ident, "Alice")
    assert journal.deja_faites("Alice", "audit_classe_1") == set() and journal.retenues() == {}
    assert len(journal.tout()) == 2  # la décision et son annulation : l'historique est entier
    with pytest.raises(DecisionRefusee, match="déjà annulée"):
        journal.annuler(ident, "Alice")


def test_on_n_annule_que_ses_propres_decisions(journal: Journal) -> None:
    ident = _d(journal)
    with pytest.raises(DecisionRefusee, match="propres"):
        journal.annuler(ident, "Bob")
    with pytest.raises(DecisionRefusee, match="inconnue"):
        journal.annuler(999, "Alice")


def test_les_valeurs_invalides_sont_refusees(journal: Journal) -> None:
    for mauvais in (dict(nombre=-1), dict(nombre=31), dict(nombre=True), dict(nombre=None), dict(forme="zigzag"), dict(note="a\nb")):
        with pytest.raises(DecisionRefusee):
            _d(journal, **mauvais)
    with pytest.raises(DecisionRefusee, match="douteuse"):
        _d(journal, douteuse=True)  # une image douteuse n'a ni nombre ni forme
    _d(journal, nombre=None, forme=None, douteuse=True)
    for nom in ("", "x" * 41, "a/b", "a\nb", "<script>"):
        with pytest.raises(DecisionRefusee):
            nom_valide(nom)
    assert nom_valide("Marie-Claire D.") == "Marie-Claire D."


def test_la_decision_retenue_suppose_l_accord_les_desaccords_attendent_un_arbitre(journal: Journal) -> None:
    _d(journal, valideur="Alice", nombre=2)
    assert journal.retenues() == {"V/g0/x/droite/1/001.jpeg": Decision(2, "aucune", False)}  # un seul valideur : sa décision
    _d(journal, valideur="Bob", nombre=2)
    assert len(journal.retenues()) == 1 and not journal.desaccords()
    _d(journal, valideur="Claire", nombre=1)
    assert journal.retenues() == {} and list(journal.desaccords()) == ["V/g0/x/droite/1/001.jpeg"]
    # Alice change d'avis : sa dernière décision en vigueur remplace la précédente.
    _d(journal, valideur="Alice", nombre=1)
    _d(journal, valideur="Bob", nombre=1)
    assert journal.retenues()["V/g0/x/droite/1/001.jpeg"].nombre == 1


def test_les_statistiques_disent_si_l_etiquette_d_origine_tenait(journal: Journal) -> None:
    _d(journal, image="a", nombre=1, ancien_nombre=1)
    _d(journal, image="b", nombre=2, ancien_nombre=1)
    _d(journal, image="c", nombre=1, ancien_nombre=0)
    _d(journal, image="d", nombre=None, forme=None, douteuse=True, ancien_nombre=1)
    s = journal.statistiques("audit_classe_1")
    assert s["decisions"] == 4 and s["douteuses"] == 1 and s["par_valideur"] == {"Alice": 4}
    assert s["ancien_vers_nouveau"] == {"0→1": 1, "1→1": 1, "1→2": 1}
    assert s["part_confirmee"] == pytest.approx(1 / 3)


def _images() -> list[ImageBrute]:
    out = []
    for g in range(3):
        for rang, n in enumerate((0, 0, 1, 2, 3)):
            for k in range(8):
                out.append(ImageBrute(f"V/g{g}/x/droite/{n}/{g}{rang}{k:02d}.jpeg", "V", f"V/g{g}/x", "droite", n, None, 36, 24))
    return out


def test_l_audit_prend_toutes_les_images_un_et_un_tirage_stable_des_autres() -> None:
    imgs = _images()
    f = file_d_images("audit_classe_1", imgs)
    un = {i.chemin for i in imgs if i.n == 1}
    assert un <= set(f) and len(f) == len(set(f))
    assert len([c for c in f if c not in un]) == 40 + 20  # 40 « 0 » (sur 48), 20 « 2 et plus » (sur 48)
    assert f == file_d_images("audit_classe_1", list(reversed(imgs)))  # ne dépend pas de l'ordre du scan
    assert f != file_d_images("audit_classe_1", imgs, graine=12)
    with pytest.raises(ValueError, match="inconnue"):
        file_d_images("nimporte", imgs)


def test_les_voisins_suivent_la_sequence_de_la_meme_collection() -> None:
    imgs = [ImageBrute(f"V/g0/x/droite/{n}/{k:03d}.jpeg", "V", "V/g0/x", "droite", n, None, 1, 1) for n, k in ((0, 2), (1, 5), (0, 3), (2, 9))]
    imgs.append(ImageBrute("V/g1/x/droite/0/004.jpeg", "V", "V/g1/x", "droite", 0, None, 1, 1))
    assert voisins(imgs, "V/g0/x/droite/0/003.jpeg") == ("V/g0/x/droite/0/002.jpeg", "V/g0/x/droite/1/005.jpeg")
    assert voisins(imgs, "V/g0/x/droite/0/002.jpeg")[0] is None  # début de séquence
    assert voisins(imgs, "V/g1/x/droite/0/004.jpeg") == (None, None)  # une autre collection ne se mélange pas
    assert voisins(imgs, "inconnue") == (None, None)


def test_une_decision_humaine_l_emporte_sur_l_etiquette_d_origine_dans_une_variante() -> None:
    imgs = _images()
    cible = next(i for i in imgs if i.n == 1)
    douteuse = next(i for i in imgs if i.n == 2)
    et, ecartes = etiqueter(imgs, Recette(cote="droite", tache="nombre"), None, {cible.chemin: Decision(0, "aucune", False), douteuse.chemin: Decision(None, None, True)})
    par = {e.image.chemin: e.classe for e in et}
    assert par[cible.chemin] == "0" and douteuse.chemin not in par and ecartes["étiquette douteuse écartée"] == 1
    # La forme validée s'ajoute à une image qui n'en avait pas ; « aucune » l'écarte de la tâche forme.
    et, _ = etiqueter(imgs, Recette(cote="droite", tache="forme"), None, {cible.chemin: Decision(1, "bataille", False)})
    assert [e.classe for e in et] == ["bataille"]
    # Sans validation pour la recette qui n'applique pas les corrections.
    et2, _ = etiqueter(imgs, Recette(cote="droite", tache="nombre", corrections=False), None, None)
    assert {e.classe for e in et2} == {"0", "1", "2"}


# -- l'API ------------------------------------------------------------------


@pytest.fixture()
def client(racine: Racine):
    for g in range(2):
        for n in (0, 1, 2):
            for k in range(5):
                f = racine.brut / f"V/g{g}/x/droite/{n}/{k + 1:03d}.jpeg"
                f.parent.mkdir(parents=True, exist_ok=True)
                Image.new("RGB", (60, 40), (n * 90, 60, 60)).save(f)
    with TestClient(creer_app(racine, demarrer_travailleur=False)) as c:
        yield c


def test_la_file_ne_remontre_pas_ce_que_ce_valideur_a_deja_fait(client: TestClient) -> None:
    f = client.get("/api/validation/file", params={"validateur": "Alice", "limite": 3}).json()
    assert f["file"] == "audit_classe_1" and f["total"] == 30  # 10 « 0 », 10 « 1 », 10 « 2 et plus » dans cette petite collection
    premier = f["items"][0]
    assert {"image", "cote", "ancien", "avant", "apres"} <= set(premier)
    r = client.post("/api/validation/decisions", json={"image": premier["image"], "validateur": "Alice", "nombre": 1, "forme": "aucune", "fichier": "audit_classe_1"})
    assert r.status_code == 201
    apres = client.get("/api/validation/file", params={"validateur": "Alice", "limite": 20}).json()
    assert premier["image"] not in [i["image"] for i in apres["items"]] and apres["faites"] == 1
    bob = client.get("/api/validation/file", params={"validateur": "Bob", "limite": 20}).json()
    assert premier["image"] in [i["image"] for i in bob["items"]] and bob["faites"] == 0  # chacun sa progression


def test_decider_refuse_l_image_inconnue_le_nombre_absurde_et_les_champs_en_trop(client: TestClient) -> None:
    ok = {"validateur": "Alice", "nombre": 1, "fichier": "audit_classe_1"}
    assert client.post("/api/validation/decisions", json={**ok, "image": "../../etc/passwd"}).status_code == 404
    image = client.get("/api/validation/file", params={"validateur": "Alice"}).json()["items"][0]["image"]
    assert client.post("/api/validation/decisions", json={**ok, "image": image, "nombre": 99}).status_code == 422
    assert client.post("/api/validation/decisions", json={**ok, "image": image, "pirate": 1}).status_code == 422
    assert client.post("/api/validation/decisions", json={**ok, "image": image, "fichier": "autre"}).status_code == 422
    assert client.post("/api/validation/decisions", json={**ok, "image": image, "validateur": "<b>"}).status_code == 422


def test_annuler_puis_derniere_et_stats_et_export(client: TestClient) -> None:
    items = client.get("/api/validation/file", params={"validateur": "Alice", "limite": 2}).json()["items"]
    ids = [client.post("/api/validation/decisions", json={"image": i["image"], "validateur": "Alice", "nombre": 2, "forme": "bataille", "fichier": "audit_classe_1"}).json()["id"] for i in items]
    assert client.get("/api/validation/derniere", params={"validateur": "Alice"}).json()["decision"]["id"] == ids[-1]
    assert client.post(f"/api/validation/decisions/{ids[-1]}/annuler", json={"validateur": "Bob"}).status_code == 422
    assert client.post(f"/api/validation/decisions/{ids[-1]}/annuler", json={"validateur": "Alice"}).status_code == 201
    assert client.get("/api/validation/derniere", params={"validateur": "Alice"}).json()["decision"]["id"] == ids[0]
    assert client.get("/api/validation/stats").json()["decisions"] == 1
    csv = client.get("/api/validation/export").text.splitlines()
    assert csv[0] == "chemin,nombre,forme,douteuse" and csv[1].endswith(",2,bataille,0") and len(csv) == 2


def test_l_image_du_brut_ne_sort_pas_du_brut_et_se_rogne(client: TestClient, racine: Racine) -> None:
    image = client.get("/api/validation/file", params={"validateur": "Alice"}).json()["items"][0]["image"]
    entiere = client.get("/api/brut/image", params={"chemin": image})
    rognee = client.get("/api/brut/image", params={"chemin": image, "rognage": True})
    assert entiere.status_code == 200 and entiere.headers["content-type"] == "image/jpeg"
    from io import BytesIO

    assert Image.open(BytesIO(entiere.content)).size == (60, 40) and Image.open(BytesIO(rognee.content)).size == (30, 40)  # la moitié du côté étudié
    (racine.chemin / "secret.jpeg").write_bytes(b"x")
    for mauvais in ("../../secret.jpeg", "/etc/passwd", "V/../../secret.jpeg", "inconnue.jpeg"):
        assert client.get("/api/brut/image", params={"chemin": mauvais}).status_code == 404


def test_une_decision_change_l_identite_de_la_variante(client: TestClient) -> None:
    recette = {"cote": "droite", "tache": "nombre", "reequilibrage": {"actif": False}}
    avant = client.post("/api/variantes/apercu", json=recette).json()["id"]
    image = client.get("/api/validation/file", params={"validateur": "Alice"}).json()["items"][0]["image"]
    client.post("/api/validation/decisions", json={"image": image, "validateur": "Alice", "nombre": 2, "fichier": "audit_classe_1"})
    apres = client.post("/api/variantes/apercu", json=recette).json()["id"]
    assert avant != apres and apres.startswith(avant)  # une variante déjà construite n'est pas réutilisée à tort
    sans = client.post("/api/variantes/apercu", json={**recette, "corrections": False}).json()["id"]
    assert "-c" not in sans


def test_les_routes_de_validation_exigent_le_jeton(racine: Racine) -> None:
    with TestClient(creer_app(racine, jeton="s", demarrer_travailleur=False)) as c:
        assert c.get("/api/validation/files").status_code == 401
        assert c.get("/api/brut/image", params={"chemin": "x"}).status_code == 401
        assert c.get("/api/validation/files", headers={"Authorization": "Bearer s"}).status_code == 200
