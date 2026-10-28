"""L'accord entre annotateurs : kappa, matrice, accord par classe, rappel moyen humain ; la file d'échantillonnage ; la route."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from laboratoire.api import creer_app
from laboratoire.donnees.brut import ImageBrute
from laboratoire.projet import Racine
from laboratoire.validation.accord import comparer, kappa_cohen, rapport_accord
from laboratoire.validation.files import file_d_images
from laboratoire.validation.journal import Journal


def test_kappa_vaut_un_en_cas_d_accord_parfait_zero_au_hasard_et_se_corrige_du_hasard() -> None:
    parfait = [("a", "a")] * 5 + [("b", "b")] * 5
    assert kappa_cohen(parfait)["kappa"] == pytest.approx(1.0)
    # Deux annotateurs indépendants, à 50/50 chacun : l'accord brut est de 0,5 mais le kappa est nul.
    hasard = [("a", "a"), ("a", "b"), ("b", "a"), ("b", "b")] * 5
    k = kappa_cohen(hasard)
    assert k["accord"] == pytest.approx(0.5) and k["kappa"] == pytest.approx(0.0)
    # Exemple classique : 90 % d'accord brut mais classe très rare → le kappa dit que c'est bien moins bon que 90 %.
    desequilibre = [("0", "0")] * 88 + [("0", "1")] * 5 + [("1", "0")] * 5 + [("1", "1")] * 2
    d = kappa_cohen(desequilibre)
    assert d["accord"] == pytest.approx(0.90) and d["kappa"] < 0.35


def test_kappa_est_vide_ou_indefini_quand_il_n_y_a_rien_a_mesurer() -> None:
    assert kappa_cohen([]) == {"n": 0, "accord": None, "kappa": None}
    assert kappa_cohen([("a", "a")] * 4)["kappa"] is None  # une seule classe : le hasard explique tout


def test_le_rappel_moyen_humain_se_lit_comme_celui_d_un_modele() -> None:
    # La référence répond 0 (10 fois), 1 (4 fois), 2+ (6 fois) ; l'autre annotateur retrouve 10/10, 1/4 et 3/6 des classes.
    paires = [("0", "0")] * 10 + [("1", "1")] + [("1", "0")] * 3 + [("2+", "2+")] * 3 + [("2+", "1")] * 3
    c = comparer(paires, ("0", "1", "2+"))
    assert c["confusion"] == [[10, 0, 0], [3, 1, 0], [0, 3, 3]]
    assert c["par_classe"]["0"]["accord"] == pytest.approx(1.0) and c["par_classe"]["1"]["accord"] == pytest.approx(0.25)
    assert c["rappel_moyen_humain"] == pytest.approx((1.0 + 0.25 + 0.5) / 3)
    assert c["par_classe"]["1"]["fiable"] is False  # 4 images : trop peu pour s'y fier


def _l(image, valideur, nombre, forme="aucune", douteuse=False, ancien_nombre=0, ancienne_forme="aucune"):
    return dict(image=image, validateur=valideur, nombre=nombre, forme=forme, douteuse=douteuse, ancien_nombre=ancien_nombre, ancienne_forme=ancienne_forme)


def test_le_rapport_compare_l_origine_au_valideur_et_les_valideurs_entre_eux() -> None:
    lignes = [
        _l("a", "Alice", 0, ancien_nombre=0), _l("a", "Bob", 0, ancien_nombre=0),
        _l("b", "Alice", 1, ancien_nombre=1), _l("b", "Bob", 2, ancien_nombre=1),  # Alice confirme l'origine, Bob non
        _l("c", "Alice", 5, ancien_nombre=3),  # 5 et 3 sont tous deux « 2 et plus » : accord
        _l("d", "Alice", None, forme=None, douteuse=True, ancien_nombre=1),  # douteuse : hors accord, comptée à part
    ]
    r = rapport_accord(lignes)
    n = r["nombre"]
    assert r["douteuses"] == 1 and r["images"] == 4 and r["valideurs"] == ["Alice", "Bob"]
    assert n["origine_contre_valideur"]["Alice"]["accord"] == pytest.approx(1.0) and n["origine_contre_valideur"]["Alice"]["n"] == 3
    assert n["origine_contre_valideur"]["Bob"]["accord"] == pytest.approx(0.5)
    entre = n["valideur_contre_valideur"]["Alice | Bob"]
    assert entre["n"] == 2 and entre["accord"] == pytest.approx(0.5)  # a : accord ; b : désaccord
    assert r["forme"]["classes"] == ["aucune", "bataille", "longitudinal"]


def test_deux_valideurs_sans_image_commune_n_ont_pas_d_accord_a_mesurer() -> None:
    r = rapport_accord([_l("a", "Alice", 1), _l("b", "Bob", 1)])
    assert r["nombre"]["valideur_contre_valideur"] == {}


def test_le_journal_rend_les_decisions_en_vigueur_sans_les_annulees(tmp_path: Path) -> None:
    j = Journal(tmp_path / "v.db")
    base = dict(valideur="Alice", forme="aucune", douteuse=False, fichier="accord", ancien_nombre=0, ancienne_forme="aucune")
    premiere = j.enregistrer(image="a", validateur="Alice", nombre=1, **{k: v for k, v in base.items() if k != "valideur"})
    j.enregistrer(image="b", validateur="Alice", nombre=0, **{k: v for k, v in base.items() if k != "valideur"})
    j.annuler(premiere, "Alice")
    assert [d["image"] for d in j.en_vigueur()] == ["b"]


def _images() -> list[ImageBrute]:
    out = []
    for plate, largeur in ((False, 768), (True, 2048)):
        for n, quantite in ((0, 60), (1, 30), (2, 40), (3, 10)):
            for k in range(quantite):
                out.append(ImageBrute(f"V/{'p' if plate else 'r'}{n}/x/droite/{n}/{k:03d}.jpeg", "V", f"V/{plate}{n}/x", "droite", n, None, largeur, 100))
    return out


def test_la_file_accord_est_equilibree_par_classe_et_par_type_et_la_meme_pour_tous() -> None:
    imgs = _images()
    f = file_d_images("accord", imgs)
    index = {i.chemin: i for i in imgs}
    assert len(f) == len(set(f))
    for classe in (lambda n: n == 0, lambda n: n == 1, lambda n: n >= 2):
        for plate in (False, True):
            assert sum(1 for c in f if classe(index[c].n) and index[c].plate == plate) == 25
    assert len(f) == 150
    assert f == file_d_images("accord", list(reversed(imgs)))  # ne dépend pas de l'ordre du scan
    assert [index[c].n for c in f[:12]] != sorted(index[c].n for c in f[:12]) or len({index[c].n for c in f[:12]}) > 1  # mêlée


def test_la_file_accord_prend_tout_quand_une_classe_est_rare() -> None:
    imgs = [i for i in _images() if not (i.n == 1 and i.plate)] + [
        ImageBrute(f"V/rare/x/droite/1/{k}.jpeg", "V", "V/rare/x", "droite", 1, None, 2048, 100) for k in range(7)
    ]
    f = file_d_images("accord", imgs)
    assert sum(1 for c in f if "/rare/" in c) == 7


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


def test_la_route_accord_mesure_l_accord_apres_deux_valideurs_a_l_aveugle(client: TestClient) -> None:
    assert client.get("/api/validation/files").json()[-1]["nom"] == "accord"
    items = client.get("/api/validation/file", params={"type": "accord", "validateur": "Alice", "limite": 6}).json()["items"]
    assert len(items) == 6
    for k, i in enumerate(items):
        # Alice redit l'étiquette d'origine ; Bob la contredit une fois sur deux.
        origine = i["ancien"]["nombre"]
        client.post("/api/validation/decisions", json={"image": i["image"], "validateur": "Alice", "nombre": origine, "fichier": "accord"})
        client.post("/api/validation/decisions", json={"image": i["image"], "validateur": "Bob", "nombre": origine if k % 2 else origine + 1, "fichier": "accord"})
    r = client.get("/api/validation/accord").json()
    assert r["images"] == 6 and r["valideurs"] == ["Alice", "Bob"]
    assert r["nombre"]["origine_contre_valideur"]["Alice"]["accord"] == pytest.approx(1.0)
    assert "Alice | Bob" in r["nombre"]["valideur_contre_valideur"]
