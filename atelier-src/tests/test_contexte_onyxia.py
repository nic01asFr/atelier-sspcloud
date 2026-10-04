"""Ce que le contexte d'un agent code dit d'Onyxia : ce qu'il a vraiment.

Relecture du 03/10 : le contexte promettait « exécuter, lire, état, démarrer et
arrêter son service, GPU » dès qu'un pod ou un service était déclaré, alors que
chaque outil dépend de ce qui est déclaré ; une fiche cassée se lisait comme
« aucun déploiement » ; et la façon de déclarer était dite de deux manières.
"""

from __future__ import annotations

import json
from pathlib import Path

from mcp_gateway.atelier.mcp_sync import _etat_onyxia_du_projet
from mcp_gateway.atelier.onyxia_projet import POUR_DECLARER, situation_du_deploiement
from mcp_gateway.atelier.project_context import bloc_contexte

POD = "proj-carte-jupyter-python-0"


def _projet(racine: Path, deploiement: dict | None, brut: str | None = None) -> Path:
    dossier = racine / "carte"
    (dossier / ".atelier").mkdir(parents=True)
    fiche = dossier / ".atelier" / "projet.json"
    if brut is not None:
        fiche.write_text(brut, encoding="utf-8")
    else:
        donnees: dict = {"slug": "carte", "titre": "carte"}
        if deploiement is not None:
            donnees["deploiement"] = deploiement
        fiche.write_text(json.dumps(donnees), encoding="utf-8")
    return dossier


def _ligne_onyxia(dossier: Path, **kw) -> str:
    bloc = bloc_contexte("carte", dossier, **kw)
    return next(ligne for ligne in bloc.splitlines() if ligne.startswith("- Onyxia"))


def test_sans_deploiement_aucun_outil_et_la_phrase_commune(tmp_path: Path) -> None:
    ligne = _ligne_onyxia(_projet(tmp_path, None))
    assert "aucun outil" in ligne and POUR_DECLARER in ligne


def test_un_pod_seul_ne_promet_ni_service_ni_gpu(tmp_path: Path) -> None:
    ligne = _ligne_onyxia(_projet(tmp_path, {"pod": POD}))
    assert POD in ligne and "exécuter" in ligne
    assert "service" not in ligne.replace("pod", "") and "GPU" not in ligne


def test_un_service_avec_gpu_promet_ce_qu_il_a(tmp_path: Path) -> None:
    ligne = _ligne_onyxia(_projet(tmp_path, {"service": "carte.service.yml", "gpu": True}))
    assert "carte.service.yml" in ligne and "GPU" in ligne
    assert "exécuter du code" not in ligne  # pas de pod : pas d'exec


def test_une_fiche_cassee_n_est_pas_une_absence(tmp_path: Path) -> None:
    ligne = _ligne_onyxia(_projet(tmp_path, None, brut='{"slug": "carte", "titre": "c", "deploiement": {"pod": "x", "oups": 1}}'))
    assert "invalide" in ligne and "aucun déploiement n'est déclaré" not in ligne


def test_onyxia_absent_du_pool_n_est_pas_promis(tmp_path: Path) -> None:
    ligne = _ligne_onyxia(_projet(tmp_path, {"pod": POD}), pool_a_onyxia=False)
    assert "aucun outil" in ligne and "pas connecté" in ligne


def test_la_liste_des_services_dit_la_meme_chose(tmp_path: Path, reglages) -> None:
    from mcp_gateway.atelier.mcp_sync import _pool_enabled  # noqa: F401 — le pool vient des réglages

    racine = reglages.projects_dir
    dossier = _projet(racine, None, brut='{"slug": "carte", "titre": "c", "deploiement": {"pod": "x", "oups": 1}}')
    etat = _etat_onyxia_du_projet(reglages, dossier, {"Onyxia": {}})
    assert etat["distribue"] is False and "invalide" in etat["raison"]

    dossier2 = _projet(tmp_path / "autre", None)
    etat = _etat_onyxia_du_projet(reglages, dossier2, {"Onyxia": {}})
    assert POUR_DECLARER in etat["raison"]


def test_situation_du_deploiement_rend_la_borne(tmp_path: Path) -> None:
    borne, raison = situation_du_deploiement(_projet(tmp_path, {"pod": POD, "gpu": True}), "carte")
    assert borne is not None and borne.pod == POD and borne.gpu and "borné" in raison
