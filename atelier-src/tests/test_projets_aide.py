"""Un « projet » mal désigné : le refus dit quoi prendre à la place.

Constaté les 12 et 13/10 : l'Assistant passe l'identifiant de sa conversation, ou le slug de son propre
espace, reçoit « projet inconnu » et conclut qu'il n'a pas de projet. Le refus doit porter la liste des projets
qui existent, le nom proche, et — pour son espace ou un identifiant de conversation — pourquoi et que faire.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import projets_aide
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

UUID = "7c4373ee-09b0-4469-b720-41407433dfce"
ORIGINE = "https://testserver"


def _projets(reglages: AtelierSettings, *noms: str) -> None:
    for nom in noms:
        (reglages.projects_dir / nom).mkdir(parents=True, exist_ok=True)


def test_un_nom_proche_est_propose_avec_la_liste(reglages: AtelierSettings) -> None:
    _projets(reglages, "mobscidata", "pix2hdr", "atlas-grist")
    message = projets_aide.projet_inconnu(reglages, "mobscidat")
    assert message.startswith("projet inconnu : mobscidat.")
    assert "Voulais-tu dire « mobscidata » ?" in message
    assert "atlas-grist, mobscidata, pix2hdr" in message


def test_sans_nom_proche_la_liste_suffit(reglages: AtelierSettings) -> None:
    _projets(reglages, "mobscidata")
    message = projets_aide.projet_inconnu(reglages, "zzz")
    assert "Voulais-tu dire" not in message and "Ceux qui existent : mobscidata" in message


def test_l_espace_de_l_assistant_n_est_pas_un_projet_et_le_dit(reglages: AtelierSettings) -> None:
    _projets(reglages, "mobscidata", reglages.assistant_slug)
    message = projets_aide.projet_inconnu(reglages, reglages.assistant_slug)
    assert "espace de l'Assistant, pas un projet" in message and "atelier_projet_creer" in message
    assert "mobscidata" in message
    assert reglages.assistant_slug + "," not in message, "l'espace de l'Assistant ne figure pas dans la liste des projets"


def test_un_identifiant_de_conversation_est_reconnu(reglages: AtelierSettings) -> None:
    _projets(reglages, "mobscidata")
    message = projets_aide.projet_inconnu(reglages, UUID)
    assert "identifiant d'une conversation, pas un projet" in message and "mobscidata" in message


def test_la_liste_est_plafonnee_et_dit_ou_trouver_le_reste(reglages: AtelierSettings) -> None:
    _projets(reglages, *[f"p{i:02d}" for i in range(30)])
    message = projets_aide.projet_inconnu(reglages, "autre")
    assert "p00" in message and "p14" in message and "p15" not in message
    assert "30 au total" in message and "atelier_projets" in message


def test_aucun_projet_est_dit(reglages: AtelierSettings) -> None:
    assert "aucun pour l'instant" in projets_aide.projet_inconnu(reglages, "x")


def test_les_dossiers_techniques_et_les_liens_ne_sont_pas_des_projets(reglages: AtelierSettings, tmp_path: Path) -> None:
    _projets(reglages, "vrai", ".cache", "_services")
    (reglages.projects_dir / "lien").symlink_to(tmp_path)
    assert projets_aide.slugs(reglages) == ["vrai"]


# ── Par les commandes, comme le voit un agent ───────────────────────────


@pytest.fixture()
def personne(atelier: TestClient) -> dict[str, str]:
    sid = atelier.app.state.auth.ouvrir_session()
    return {"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": ORIGINE}


@pytest.mark.parametrize(
    "commande",
    ["atelier_projet_modifier", "atelier_projet_ranger", "atelier_projet_structurer", "atelier_projet_deployer_declarer"],
)
def test_les_commandes_de_projet_guident_l_assistant_qui_vise_son_espace(
    atelier: TestClient, personne: dict[str, str], commande: str
) -> None:
    slug = atelier.app.state.settings.assistant_slug
    r = atelier.post(f"/v1/commandes/{commande}", headers=personne, json={"arguments": {"projet": slug, "titre": "x"}})
    assert r.status_code in (403, 422), r.text
    assert "espace de l'Assistant" in r.text and "atelier_projet_creer" in r.text


@pytest.mark.parametrize("commande", ["atelier_projet_modifier", "atelier_projet_ranger", "atelier_projet_deployer_declarer"])
def test_les_commandes_de_projet_dissent_qu_un_identifiant_de_conversation_n_est_pas_un_projet(
    atelier: TestClient, personne: dict[str, str], commande: str
) -> None:
    r = atelier.post(f"/v1/commandes/{commande}", headers=personne, json={"arguments": {"projet": UUID, "titre": "x"}})
    assert r.status_code in (403, 422), r.text
    assert "identifiant d'une conversation" in r.text
