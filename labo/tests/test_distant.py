"""Le laboratoire (CPU) et le travailleur (GPU) : un vrai service, un vrai travailleur, un vrai entraînement (le jouet), sans GPU."""

from __future__ import annotations

import io
import json
import socket
import tarfile
import threading
import time
import urllib.error
from pathlib import Path

import pytest
import uvicorn
from fastapi.testclient import TestClient

from conftest import faire_variante
from laboratoire.api import creer_app
from laboratoire.distant import extraire_sur
from laboratoire.projet import Racine
from laboratoire.travailleur_gpu import Maitre, Travailleur

CONFIG = {"jeu": "v1", "methode": {"famille": "jouet", "modele": "centres", "imgsz": 8, "epochs": 1}}
ADMIN, GPU = "jeton-admin", "jeton-gpu"


@pytest.fixture()
def maitre(racine: Racine):
    """Un laboratoire en mode maître, sur un vrai port, avec le jeton d'un travailleur."""
    faire_variante(racine)
    (racine.chemin / "valideurs.json").write_text(json.dumps({"gpu": {"jeton": GPU, "role": "travailleur"}}), encoding="utf-8")
    app = creer_app(racine, jeton=ADMIN, maitre=True, demarrer_travailleur=True)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    serveur = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    fil = threading.Thread(target=serveur.run, daemon=True)
    fil.start()
    while not serveur.started:
        time.sleep(0.02)
    yield app, f"http://127.0.0.1:{port}"
    serveur.should_exit = True
    fil.join(timeout=10)


def _admin(app) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {ADMIN}"})


def _travailleur(url: str, tmp_path: Path, **kw) -> Travailleur:
    return Travailleur(Maitre(url, GPU, "gpu-test"), Racine(tmp_path / "gpu"), pause=lambda s: time.sleep(0.01), **kw)


def test_un_essai_va_du_laboratoire_au_travailleur_et_revient(maitre, tmp_path: Path) -> None:
    app, url = maitre
    with _admin(app) as admin:
        ident = admin.post("/api/essais", json=CONFIG).json()["id"]
        # le laboratoire ne lance rien lui-même
        time.sleep(0.5)
        assert admin.get(f"/api/essais/{ident}").json()["essai"]["etat"] == "en_file"
        assert admin.get("/api/pod").json()["travailleur"]["connecte"] is False

        assert _travailleur(url, tmp_path).un_pas() is True

        detail = admin.get(f"/api/essais/{ident}").json()
        assert detail["essai"]["etat"] == "termine"
        assert detail["essai"]["travailleur"] == "gpu-test"
        assert detail["resultats"]["rapport"]["rappel_moyen"] == 1.0
        assert detail["essai"]["rappel_moyen_val"] == 1.0
        assert detail["metriques"]
        assert "journal.log" not in {p.name for p in (app.state.racine.dossier_essai(ident)).glob("*.tar")}
        assert admin.get(f"/api/essais/{ident}/journal").json()["texte"].strip()
        assert admin.get("/api/pod").json()["travailleur"]["connecte"] is True
        # le test scellé est arrivé avec le reste et s'ouvre comme d'habitude
        assert admin.post(f"/api/essais/{ident}/ouvrir-test", json={"confirmer": True}).status_code == 200


def test_le_jeu_de_donnees_n_est_telecharge_qu_une_fois(maitre, tmp_path: Path) -> None:
    app, url = maitre
    with _admin(app) as admin:
        admin.post("/api/essais", json=CONFIG)
        admin.post("/api/essais", json=CONFIG)
        t = _travailleur(url, tmp_path)
        appels = []
        original = t.maitre.telecharger_variante
        t.maitre.telecharger_variante = lambda *a, **k: (appels.append(1), original(*a, **k))[1]
        assert t.un_pas() and t.un_pas()
        assert t.un_pas() is False
        assert len(appels) == 1


def test_la_personne_arrete_un_essai_distant(maitre, tmp_path: Path) -> None:
    app, url = maitre
    with _admin(app) as admin:
        ident = admin.post("/api/essais", json=CONFIG).json()["id"]
        essai = app.state.registre.prendre_pour("gpu-test")  # confié, mais le travailleur est silencieux depuis peu : l'arrêt est demandé
        assert essai["id"] == ident
        assert admin.post(f"/api/essais/{ident}/arreter").json()["arret_demande"] == 1
        assert Maitre(url, GPU, "gpu-test").signe(ident, None) == {"arreter": True}


def test_un_travailleur_silencieux_est_tenu_pour_perdu(maitre) -> None:
    app, url = maitre
    with _admin(app) as admin:
        ident = admin.post("/api/essais", json=CONFIG).json()["id"]
        app.state.registre.prendre_pour("gpu-test")
        with app.state.registre._transaction() as c:
            c.execute("UPDATE essais SET dernier_signe = ? WHERE id = ?", (time.time() - 3600, ident))
        app.state.executeur.verifier()
        e = admin.get(f"/api/essais/{ident}").json()["essai"]
        assert e["etat"] == "interrompu" and "n'a plus donné signe" in e["erreur"]
        # un travailleur qui revient après l'interruption n'écrase rien
        with pytest.raises(urllib.error.HTTPError) as exc:
            Maitre(url, GPU, "gpu-test").signe(ident, None)
        assert exc.value.code == 409


def test_les_jetons_ne_servent_qu_a_leur_role(maitre) -> None:
    app, url = maitre
    with TestClient(app) as c:
        gpu = {"Authorization": f"Bearer {GPU}"}
        assert c.get("/api/essais", headers=gpu).status_code == 403  # un travailleur ne lit pas le laboratoire
        assert c.post("/api/travail/prendre", json={"travailleur": "x"}).status_code == 401
        (app.state.racine.chemin / "valideurs.json").write_text(
            json.dumps({"gpu": {"jeton": GPU, "role": "travailleur"}, "mathieu": {"jeton": "m", "role": "relecteur"}}), encoding="utf-8"
        )
        assert c.post("/api/travail/prendre", json={"travailleur": "x"}, headers={"Authorization": "Bearer m"}).status_code == 403


def test_une_archive_qui_sort_du_dossier_est_refusee(tmp_path: Path) -> None:
    for nom in ("../evasion.txt", "/etc/evasion.txt"):
        tampon = io.BytesIO()
        with tarfile.open(fileobj=tampon, mode="w") as t:
            info = tarfile.TarInfo(nom)
            info.size = 2
            t.addfile(info, io.BytesIO(b"ok"))
        archive = tmp_path / "a.tar"
        archive.write_bytes(tampon.getvalue())
        with pytest.raises(ValueError):
            extraire_sur(archive, tmp_path / "dest")
    lien = io.BytesIO()
    with tarfile.open(fileobj=lien, mode="w") as t:
        info = tarfile.TarInfo("lien")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        t.addfile(info)
    archive.write_bytes(lien.getvalue())
    with pytest.raises(ValueError):
        extraire_sur(archive, tmp_path / "dest")
    assert not (tmp_path / "evasion.txt").exists()


def test_un_reseau_coupe_ne_perd_pas_l_essai(maitre, tmp_path: Path) -> None:
    app, url = maitre
    with _admin(app) as admin:
        ident = admin.post("/api/essais", json=CONFIG).json()["id"]
        t = _travailleur(url, tmp_path)
        original = t.maitre.terminer
        t.maitre.terminer = lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("coupé"))
        assert t.un_pas()
        assert admin.get(f"/api/essais/{ident}").json()["essai"]["etat"] == "en_cours"
        assert (tmp_path / "gpu" / "essais" / ident / "fin.json").is_file()
        t.maitre.terminer = original  # le réseau revient : l'essai part à la reprise du contact
        t.reprendre()
        assert admin.get(f"/api/essais/{ident}").json()["essai"]["etat"] == "termine"
