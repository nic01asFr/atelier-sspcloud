"""L'agent se dit sous le nom que la personne a donné au projet.

Cas relevé : un projet créé sans titre (dossier `projet-sans-nom-2`) puis
renommé « BigStarter » s'affichait ainsi dans l'Atelier, mais l'agent répondait
« Je suis prêt à vous aider sur le projet projet-sans-nom-2 » : son contexte
(`CLAUDE.md`, régénéré par l'Atelier) ne portait que le nom du dossier.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from mcp_gateway.atelier.project_context import bloc_contexte, ecrire_contexte
from mcp_gateway.atelier.projects import ProjectStore


def _entete(atelier: TestClient) -> dict[str, str]:
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def test_un_titre_choisi_remplace_le_nom_du_dossier(tmp_path) -> None:
    texte = bloc_contexte("projet-sans-nom-2", tmp_path / "projet-sans-nom-2", titre="BigStarter")
    assert "projet **BigStarter**" in texte
    assert "identifiant `projet-sans-nom-2`" in texte  # le dossier reste dit, à part
    assert "conversations de **BigStarter**" in texte
    assert "projet **projet-sans-nom-2**" not in texte


def test_sans_titre_ou_titre_identique_le_dossier_se_dit_seul(tmp_path) -> None:
    for titre in ("", "  ", "demo"):
        texte = bloc_contexte("demo", tmp_path / "demo", titre=titre)
        assert "projet **demo**" in texte and "identifiant" not in texte


def test_le_titre_de_repli_n_est_pas_un_titre_choisi(reglages) -> None:
    store = ProjectStore(reglages)
    store.create("projet-sans-nom-2", kind="code")
    assert store.titre_choisi("projet-sans-nom-2") == ""  # la liste dirait « projet sans nom 2 » : ce n'est pas un choix
    store.patch("projet-sans-nom-2", title="BigStarter")
    assert store.titre_choisi("projet-sans-nom-2") == "BigStarter"
    assert store.titre_choisi(reglages.assistant_slug) == ""


def test_le_contexte_ecrit_porte_le_titre(reglages) -> None:
    store = ProjectStore(reglages)
    store.create("projet-sans-nom-2", kind="code")
    store.patch("projet-sans-nom-2", title="BigStarter")
    dossier = reglages.projects_dir / "projet-sans-nom-2"
    ecrire_contexte(dossier, "projet-sans-nom-2", reglages)
    assert "projet **BigStarter**" in (dossier / "CLAUDE.md").read_text(encoding="utf-8")


def test_renommer_par_l_api_met_a_jour_le_contexte_tout_de_suite(atelier: TestClient, reglages) -> None:
    h = _entete(atelier)
    assert atelier.post("/v1/projects", headers=h, json={"slug": "projet-sans-nom-2", "kind": "code"}).status_code == 200
    ecrire_contexte(reglages.projects_dir / "projet-sans-nom-2", "projet-sans-nom-2", reglages)
    fichier = reglages.projects_dir / "projet-sans-nom-2" / "CLAUDE.md"
    assert "projet **projet-sans-nom-2**" in fichier.read_text(encoding="utf-8")
    r = atelier.patch("/v1/projects/projet-sans-nom-2", headers=h, json={"title": "BigStarter"})
    assert r.status_code == 200
    assert "projet **BigStarter**" in fichier.read_text(encoding="utf-8")


def test_le_contexte_d_une_ancienne_installation_est_reecrit_a_l_identique_ensuite(reglages) -> None:
    """Rien n'est réécrit quand le contenu est déjà le bon (le dossier est souvent sous git)."""
    store = ProjectStore(reglages)
    store.create("demo", kind="code")
    store.patch("demo", title="Vitrine")
    dossier = reglages.projects_dir / "demo"
    assert ecrire_contexte(dossier, "demo", reglages) is True
    assert ecrire_contexte(dossier, "demo", reglages) is False


def test_le_contexte_demande_de_dire_ce_qu_on_fait_entre_les_actions(tmp_path) -> None:
    """Constat du 02/10 : un agent (deepseek via Albert) enchaînait 22 outils sans un mot ;
    la personne ne voyait que des étapes, sans savoir ce qu'il pensait."""
    texte = bloc_contexte("demo", tmp_path / "demo", titre="Démo")
    assert "Te faire suivre" in texte and "dis en une phrase ce que tu fais" in texte
