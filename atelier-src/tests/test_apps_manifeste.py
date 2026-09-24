"""L'artefact et son manifeste : ce qu'il accepte, et surtout ce qu'il refuse.

Un artefact est un dossier `artifacts/<nom>/` ; il devient un serveur quand il
porte un `artefact.json`. Un manifeste est écrit par des agents. Chaque refus
ci-dessous ferme une porte précise : un port choisi par le projet, une ligne
de shell, un dossier hors du projet, un secret en clair, un accès élargi par
une ligne de JSON.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcp_gateway.atelier.apps.manifeste import (
    ArtefactInconnu,
    Manifeste,
    ManifesteInvalide,
    charger_manifeste,
    lire_auteur,
    lire_manifeste,
    lister_artefacts,
    nom_valide,
)

EXEMPLE = {
    "version": 1,
    "titre": "STT & TTS",
    "type": "service",
    "commande": ["python", "-m", "uvicorn", "voice_service:app", "--host", "127.0.0.1", "--port", "{port}"],
    "repertoire": "../..",
    "ecoute": "port",
    "chemin": "retire",
    "sante": "/health",
    "demarrage_s": 90,
    "inactivite_min": 60,
    "protocoles": ["http", "ws", "sse"],
    "corps_max_mo": 200,
    "env": {"MODELE": "whisper-small"},
    "secrets": {"VOICE_TOKEN": "voice"},
    "acces": "proprietaire",
}


def _avec(**changes: object) -> dict:
    donnees = dict(EXEMPLE)
    for cle, valeur in changes.items():
        if valeur is None:
            donnees.pop(cle, None)
        else:
            donnees[cle] = valeur
    return donnees


def _refuse(donnees: object, motif: str) -> None:
    with pytest.raises(ManifesteInvalide) as exc:
        lire_manifeste(donnees)
    assert motif in str(exc.value), str(exc.value)


def _projet(tmp_path: Path, artefacts: dict[str, object | None]) -> Path:
    """Un projet et ses artefacts : None = dossier autonome, sinon le manifeste."""
    racine = tmp_path / "projet"
    (racine / "artifacts").mkdir(parents=True)
    for nom, contenu in artefacts.items():
        dossier = racine / "artifacts" / nom
        dossier.mkdir()
        if contenu is None:
            (dossier / "index.html").write_text("<p>ok</p>", encoding="utf-8")
            continue
        texte = contenu if isinstance(contenu, str) else json.dumps(contenu)
        (dossier / "artefact.json").write_text(texte, encoding="utf-8")
    return racine


def test_l_exemple_du_document_passe() -> None:
    m = lire_manifeste(EXEMPLE)
    assert m.service
    assert m.protocoles == ["http", "ws", "sse"]
    assert m.secrets == {"VOICE_TOKEN": "voice"}


def test_valeurs_par_defaut_minimales() -> None:
    m = lire_manifeste({"version": 1, "commande": ["python", "app.py"]})
    assert (m.repertoire, m.ecoute, m.chemin, m.acces) == (".", "port", "retire", "proprietaire")
    assert m.protocoles == ["http"]
    assert m.inactivite_min is None
    assert m.edition is False


def test_version_inconnue_refusee() -> None:
    _refuse(_avec(version=2), "version")
    _refuse(_avec(version=None), "version")


def test_commande_est_une_liste_jamais_une_ligne_de_shell() -> None:
    _refuse(_avec(commande="python -m http.server {port}"), "commande")
    _refuse(_avec(commande=[]), "programme")
    _refuse(_avec(commande=["python", 3]), "commande")


def test_aucun_champ_port() -> None:
    _refuse(_avec(port=8000), "`port` n'existe pas")


def test_champ_inconnu_refuse() -> None:
    _refuse(_avec(ports=[8000]), "ports")
    _refuse(_avec(racine="public"), "racine")


def test_types_stricts() -> None:
    _refuse(_avec(demarrage_s="90"), "demarrage_s")


def test_substitutions_connues_seulement() -> None:
    _refuse(_avec(commande=["python", "--port", "{PORT}"]), "substitution inconnue")
    _refuse(_avec(commande=["python", "--hote", "{hote}"]), "substitution inconnue")
    # Des accolades qui ne sont pas une substitution restent du texte.
    lire_manifeste(_avec(commande=["python", "-c", "print({'a': 1})", "{port}"]))


def test_socket_seulement_avec_ecoute_unix() -> None:
    _refuse(_avec(commande=["app", "--uds", "{socket}"]), "{socket}")
    _refuse(_avec(ecoute="unix"), "exige {socket}")
    _refuse(_avec(ecoute="unix", commande=["app", "--uds", "{socket}", "{port}"]), "pas de port")
    lire_manifeste(_avec(ecoute="unix", commande=["app", "--uds", "{socket}"]))


def test_substitutions_litterales() -> None:
    m = lire_manifeste(_avec(commande=["app", "--port={port}", "--racine", "{prefixe}", "{projet}/x", "{'k': 1}"]))
    argv = m.arguments(port=19001, prefixe="/demo/voix", projet=Path("/p"))
    assert argv == ["app", "--port=19001", "--racine", "/demo/voix", f"{Path('/p')}/x", "{'k': 1}"]


def test_repertoire_relatif() -> None:
    _refuse(_avec(repertoire="/etc"), "absolu")
    # Remonter est permis ; en sortir se vérifie contre le projet (plus bas).
    lire_manifeste(_avec(repertoire="../.."))


def test_repertoire_part_du_dossier_de_l_artefact(tmp_path: Path) -> None:
    racine = _projet(tmp_path, {"voix": _avec(repertoire=".", secrets=None)})
    m = charger_manifeste(racine, "voix")
    assert m.dossier_de_travail(racine, "voix") == (racine / "artifacts" / "voix").resolve()


def test_repertoire_remonte_dans_le_projet_jamais_hors(tmp_path: Path) -> None:
    racine = _projet(tmp_path, {"voix": _avec(repertoire="../..", secrets=None)})
    m = charger_manifeste(racine, "voix")
    assert m.dossier_de_travail(racine, "voix") == racine.resolve()
    racine2 = _projet(tmp_path / "autre", {"voix": _avec(repertoire="../../..", secrets=None)})
    with pytest.raises(ManifesteInvalide, match="sort du projet"):
        charger_manifeste(racine2, "voix")
    racine3 = _projet(tmp_path / "trois", {"voix": _avec(repertoire="service", secrets=None)})
    with pytest.raises(ManifesteInvalide, match="n'existe pas"):
        charger_manifeste(racine3, "voix")


@pytest.mark.skipif(os.name != "posix", reason="liens symboliques POSIX")
def test_lien_symbolique_hors_du_projet_refuse(tmp_path: Path) -> None:
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    racine = _projet(tmp_path, {"voix": _avec(repertoire="lien")})
    (racine / "artifacts" / "voix" / "lien").symlink_to(ailleurs)
    with pytest.raises(ManifesteInvalide, match="sort du projet"):
        charger_manifeste(racine, "voix")


@pytest.mark.skipif(os.name != "posix", reason="liens symboliques POSIX")
def test_dossier_d_artefact_hors_du_projet_refuse(tmp_path: Path) -> None:
    dehors = _projet(tmp_path / "dehors", {"voix": EXEMPLE})
    racine = tmp_path / "projet"
    (racine / "artifacts").mkdir(parents=True)
    (racine / "artifacts" / "voix").symlink_to(dehors / "artifacts" / "voix")
    with pytest.raises(ArtefactInconnu):
        charger_manifeste(racine, "voix")


@pytest.mark.parametrize(
    "nom",
    ["Voix", "_atelier", "_artefacts", "a/b", "..", "", "a" * 41, "voix.json", "-voix", "voix_2"],
)
def test_noms_invalides(nom: str) -> None:
    assert not nom_valide(nom)


@pytest.mark.parametrize("nom", ["voix", "stt-tts", "a", "app2", "a" * 40])
def test_noms_valides(nom: str) -> None:
    assert nom_valide(nom)


def test_nom_invalide_refuse_au_chargement(tmp_path: Path) -> None:
    racine = _projet(tmp_path, {})
    with pytest.raises(ArtefactInconnu, match="nom d'artefact invalide"):
        charger_manifeste(racine, "../../etc")


def test_protocoles() -> None:
    _refuse(_avec(protocoles=["http", "ftp"]), "protocoles")
    _refuse(_avec(protocoles=["http", "ws", "ws"]), "doublon")
    _refuse(_avec(protocoles=["ws"]), "http")
    _refuse(_avec(protocoles=[]), "vide")


def test_secrets_par_reference_seulement() -> None:
    _refuse(_avec(secrets={"TOKEN": "../llm_api_key"}), "référence de secret invalide")
    _refuse(_avec(secrets={"TOKEN": "sous/dossier"}), "référence de secret invalide")
    _refuse(_avec(secrets={"TOKEN": ".cache"}), "référence de secret invalide")
    _refuse(_avec(secrets={"TOKEN": "a..b"}), "référence de secret invalide")


def test_variables_reservees() -> None:
    _refuse(_avec(env={"ATELIER_OWNER_KEY": "x"}), "réservée")
    _refuse(_avec(secrets={"ATELIER_LLM_API_KEY": "llm"}), "réservée")
    _refuse(_avec(env={"PORT": "80"}), "posée par l'Atelier")
    _refuse(_avec(env={"PATH": "/tmp"}), "posée par l'Atelier")
    _refuse(_avec(env={"minuscule": "x"}), "nom de variable invalide")
    _refuse(_avec(env={"A": "x"}, secrets={"A": "ref"}), "à la fois")


def test_acces_proprietaire_seul() -> None:
    _refuse(_avec(acces="public"), "acces")
    _refuse(_avec(acces="lien"), "acces")


def test_sante_est_un_chemin() -> None:
    _refuse(_avec(sante="health"), "sante")
    _refuse(_avec(sante="//autre.hote/x"), "sante")
    _refuse(_avec(sante="http://autre/x"), "sante")


def test_bornes_numeriques() -> None:
    _refuse(_avec(demarrage_s=0), "demarrage_s")
    _refuse(_avec(demarrage_s=100000), "demarrage_s")
    _refuse(_avec(corps_max_mo=0), "corps_max_mo")
    _refuse(_avec(inactivite_min=0), "inactivite_min")


def test_artefact_statique_en_edition() -> None:
    m = lire_manifeste({"version": 1, "type": "statique", "edition": True})
    assert not m.service and m.edition
    _refuse({"version": 1, "type": "statique", "commande": ["x"]}, "pas de `commande`")
    _refuse({"version": 1, "commande": ["x"], "edition": True}, "réservée")
    _refuse({"version": 1, "type": "statique", "secrets": {"A": "a"}}, "ni `env`")


def test_manifeste_immuable() -> None:
    m = lire_manifeste(EXEMPLE)
    with pytest.raises(Exception):
        m.titre = "autre"  # type: ignore[misc]


def test_un_dossier_sans_manifeste_est_autonome(tmp_path: Path) -> None:
    racine = _projet(tmp_path, {"rapport": None})
    assert charger_manifeste(racine, "rapport") is None
    with pytest.raises(ArtefactInconnu):
        charger_manifeste(racine, "absent")


def test_lister_separe_valides_et_fautifs(tmp_path: Path) -> None:
    racine = _projet(
        tmp_path,
        {
            "voix": _avec(repertoire=".", secrets=None),
            "rapport": None,
            "casse": _avec(port=80),
            "illisible": "{pas du json",
        },
    )
    (racine / "artifacts" / "Pas_Un_Nom").mkdir()
    (racine / "artifacts" / "page.html").write_text("x", encoding="utf-8")
    valides, erreurs = lister_artefacts(racine)
    assert sorted(valides) == ["rapport", "voix"]
    assert valides["rapport"] is None
    assert isinstance(valides["voix"], Manifeste)
    assert set(erreurs) == {"casse", "illisible"}
    assert "port" in erreurs["casse"]


def test_lister_un_projet_sans_artefacts(tmp_path: Path) -> None:
    assert lister_artefacts(tmp_path) == ({}, {})


def test_l_auteur_se_lit(tmp_path: Path) -> None:
    racine = _projet(tmp_path, {"rapport": None})
    assert lire_auteur(racine, "rapport") == ""
    (racine / "artifacts" / "rapport" / ".auteur").write_text("conv-1\n", encoding="utf-8")
    assert lire_auteur(racine, "rapport") == "conv-1"
