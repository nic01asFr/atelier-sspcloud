"""GitHub depuis l'Atelier : connecter un compte, voir ses dépôts, en ouvrir un comme projet.

Sans réseau : GitHub (l'API) est simulé, et le « distant » est un vrai dépôt git local — on clone
pour de bon, ce qui permet de vérifier ce qui compte : le jeton n'est ni dans une adresse, ni sur
une ligne de commande, ni dans une réponse, ni au journal ; le `.gitignore` du dépôt n'est pas touché.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import git_repos, github_compte
from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.commandes.profils import OUTILS_DU_PROFIL_CODE, outil_permis
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.github_compte import ErreurGithub
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

JETON = "github_pat_" + "A1b2C3d4E5f6G7h8" * 3  # fictif
ORIGINE = "http://testserver"


class _Github:
    """L'API de GitHub : des réponses par route, et le journal de ce qui a été demandé."""

    def __init__(self) -> None:
        self.reponses: dict[str, Any] = {}
        self.appels: list[tuple[str, str]] = []

    def __call__(self, jeton: str, route: str) -> Any:
        self.appels.append((route, jeton))
        reponse = self.reponses.get(route)
        if isinstance(reponse, Exception):
            raise reponse
        if reponse is None:
            raise ErreurGithub("Introuvable, ou le jeton n'y a pas accès.")
        return reponse


@pytest.fixture()
def github(monkeypatch: pytest.MonkeyPatch) -> _Github:
    faux = _Github()
    monkeypatch.setattr(github_compte, "_get", faux)
    github_compte._cache.update(t=0.0, cle="", liste=[])
    return faux


def _depot(nom: str, **plus: Any) -> dict[str, Any]:
    proprietaire, court = nom.split("/")
    return {
        "full_name": nom,
        "name": court,
        "private": False,
        "description": "",
        "default_branch": "main",
        "pushed_at": "2026-10-10T10:00:00Z",
        "archived": False,
        "permissions": {"push": True},
        "size": 120,
        **plus,
    }


ROUTE_PAGE_1 = "/user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator,organization_member&page=1"


@pytest.fixture()
def distant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Un vrai dépôt git, `octo/projet`, qui joue GitHub pour le clonage."""
    source = tmp_path / "source"
    source.mkdir()
    git = ["git", "-C", str(source), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run(["git", "init", "-q", "-b", "main", str(source)], check=True)
    (source / "README.md").write_text("# Projet\n", encoding="utf-8")
    (source / ".gitignore").write_text("*.log\n", encoding="utf-8")
    subprocess.run([*git, "add", "-A"], check=True)
    subprocess.run([*git, "commit", "-q", "-m", "premier"], check=True)
    nu = tmp_path / "distants" / "octo" / "projet.git"
    nu.parent.mkdir(parents=True)
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(nu)], check=True)
    monkeypatch.setattr(github_compte, "ADRESSE_DES_DEPOTS", f"{tmp_path / 'distants'}/")
    return nu


# ── Les noms de dépôt ───────────────────────────────────────────────────


@pytest.mark.parametrize("nom", ["octo/projet", "octo-cat/mon.depot_2", "O/a", "nic01asFr/atelier-sspcloud"])
def test_un_nom_de_depot_valide_est_accepte(nom: str) -> None:
    proprietaire, court = github_compte.valider_le_nom(nom)
    assert f"{proprietaire}/{court}" == nom


@pytest.mark.parametrize(
    "nom",
    [
        "",
        "projet",
        "a/b/c",
        "octo/..",
        "octo/.",
        "octo/-option",
        "--upload-pack=x/projet",
        "-octo/projet",
        "octo/projet.git",
        "octo/pro jet",
        "octo/projet;rm -rf",
        "../octo/projet",
        "https://github.com/octo/projet",
        "octo/" + "x" * 101,
    ],
)
def test_un_nom_de_depot_qui_pourrait_viser_ailleurs_est_refuse(nom: str) -> None:
    with pytest.raises(ErreurGithub):
        github_compte.valider_le_nom(nom)


# ── Le compte ───────────────────────────────────────────────────────────


def test_connecter_verifie_puis_garde_le_jeton_en_0600_sans_le_rendre(reglages: AtelierSettings, github: _Github) -> None:
    github.reponses["/user"] = {"login": "octo", "name": "Octo Cat"}
    rendu = github_compte.connecter(reglages, f"  {JETON}\n")
    assert rendu["connecte"] and rendu["login"] == "octo" and rendu["type"] == "fine-grained"
    assert JETON not in json.dumps(rendu) and "avertissement" not in rendu
    assert reglages.github_token_path.read_text(encoding="utf-8") == JETON
    assert stat.S_IMODE(reglages.github_token_path.stat().st_mode) == 0o600
    assert JETON not in (reglages.secrets_dir / "github.json").read_text(encoding="utf-8")
    assert github.appels == [("/user", JETON)]
    # Le propriétaire des dépôts se déduit du compte, sans réglage à la main.
    assert git_repos.proprietaire(reglages) == "octo"
    assert git_repos.publication_possible(reglages)


def test_un_jeton_refuse_par_github_n_est_pas_garde(reglages: AtelierSettings, github: _Github) -> None:
    github.reponses["/user"] = ErreurGithub("GitHub refuse ce jeton : il est invalide, expiré ou révoqué.")
    with pytest.raises(ErreurGithub, match="invalide, expiré ou révoqué"):
        github_compte.connecter(reglages, JETON)
    assert not reglages.github_token_path.exists() and not (reglages.secrets_dir / "github.json").exists()
    assert github_compte.etat(reglages)["connecte"] is False


@pytest.mark.parametrize("jeton", ["", "court", "a b c d e f g h i j k l m n o p q r", "é" * 30, JETON + "\nautre", "x" * 300])
def test_un_jeton_mal_forme_est_refuse_sans_appeler_github(reglages: AtelierSettings, github: _Github, jeton: str) -> None:
    with pytest.raises(ErreurGithub, match="Ce n'est pas un jeton GitHub"):
        github_compte.connecter(reglages, jeton)
    assert github.appels == [] and not reglages.github_token_path.exists()


def test_un_jeton_classique_est_accepte_avec_un_avertissement(reglages: AtelierSettings, github: _Github) -> None:
    github.reponses["/user"] = {"login": "octo"}
    rendu = github_compte.connecter(reglages, "ghp_" + "Z9y8X7w6V5u4T3s2R1q0" * 2)
    assert rendu["type"] == "classique" and "fine-grained" in rendu["avertissement"]


def test_deconnecter_retire_le_jeton_et_le_compte(reglages: AtelierSettings, github: _Github) -> None:
    github.reponses["/user"] = {"login": "octo"}
    github_compte.connecter(reglages, JETON)
    rendu = github_compte.deconnecter(reglages)
    assert rendu["connecte"] is False and rendu["login"] == ""
    assert not reglages.github_token_path.exists() and not (reglages.secrets_dir / "github.json").exists()
    assert github_compte.deconnecter(reglages)["connecte"] is False, "rejouable"


def test_l_etat_ne_rend_jamais_le_jeton_meme_pose_a_la_main(reglages: AtelierSettings) -> None:
    reglages.github_token_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.github_token_path.write_text(JETON, encoding="utf-8")
    etat = github_compte.etat(reglages)
    assert etat["connecte"] is True and etat["login"] == "" and JETON not in json.dumps(etat)


# ── Les dépôts ──────────────────────────────────────────────────────────


def _connecte(reglages: AtelierSettings, github: _Github) -> None:
    github.reponses["/user"] = {"login": "octo"}
    github_compte.connecter(reglages, JETON)
    github.appels.clear()


def test_sans_compte_lister_dit_quoi_faire(reglages: AtelierSettings, github: _Github) -> None:
    with pytest.raises(ErreurGithub, match="collez un jeton dans Réglages"):
        github_compte.depots(reglages)


def test_les_depots_se_filtrent_et_disent_ceux_deja_ouverts(reglages: AtelierSettings, github: _Github) -> None:
    _connecte(reglages, github)
    github.reponses[ROUTE_PAGE_1] = [
        _depot("octo/projet", description="Cartes des sentiers", private=True),
        _depot("octo/autre", archived=True, permissions={"push": False}),
        _depot("asso/carto", description="Une carte"),
    ]
    registre = reglages.work_dir / ".atelier-etat" / "depots.json"
    registre.parent.mkdir(parents=True, exist_ok=True)
    registre.write_text(json.dumps({"mon-projet": {"depot": "octo/projet"}}), encoding="utf-8")

    tout = github_compte.depots(reglages)
    assert [d["nom"] for d in tout["depots"]] == ["octo/projet", "octo/autre", "asso/carto"]
    assert tout["depots"][0]["projet"] == "mon-projet" and tout["depots"][1]["projet"] == ""
    assert tout["depots"][0]["prive"] is True and tout["depots"][1]["archive"] is True
    assert tout["depots"][1]["ecriture"] is False and tout["tronque"] is False
    assert [d["nom"] for d in github_compte.depots(reglages, "carte")["depots"]] == ["octo/projet", "asso/carto"]
    assert len(github.appels) == 1, "le filtre et la relecture utilisent le cache de 60 s"
    github_compte.depots(reglages, actualiser=True)
    assert len(github.appels) == 2


def test_une_liste_qui_touche_le_plafond_le_dit(reglages: AtelierSettings, github: _Github) -> None:
    _connecte(reglages, github)
    pages = [f"/user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator,organization_member&page={p}" for p in (1, 2, 3)]
    for p, route in enumerate(pages):
        github.reponses[route] = [_depot(f"octo/d{p}-{i}") for i in range(100)]
    rendu = github_compte.depots(reglages)
    assert rendu["total"] == 300 and rendu["tronque"] is True


# ── Ouvrir un dépôt comme projet ────────────────────────────────────────


def test_cloner_ouvre_le_depot_sans_secret_et_sans_toucher_son_gitignore(
    reglages: AtelierSettings, github: _Github, distant: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _connecte(reglages, github)
    github.reponses["/repos/octo/projet"] = _depot("octo/projet", private=True)
    lancees: list[tuple[list[str], dict[str, str]]] = []
    vrai_run = subprocess.run

    def espion(commande: Any, *a: Any, **k: Any) -> Any:
        if list(commande[:2]) == ["git", "clone"]:
            lancees.append((list(commande), dict(k.get("env") or {})))
        return vrai_run(commande, *a, **k)

    monkeypatch.setattr(subprocess, "run", espion)
    rendu = github_compte.cloner(reglages, "octo/projet")
    assert rendu["slug"] == "projet" and rendu["depot"] == "octo/projet" and rendu["prive"] is True
    dossier = reglages.projects_dir / "projet"
    assert (dossier / "README.md").is_file()

    # Le jeton n'est ni sur la ligne de commande ni dans une variable d'environnement : git le lit par GIT_ASKPASS.
    (commande, env), = lancees
    assert JETON not in " ".join(commande) and "--" in commande
    assert all(JETON not in valeur for valeur in env.values())
    assert env["GIT_ASKPASS"].endswith("atelier-git-askpass.sh") and env["GIT_TERMINAL_PROMPT"] == "0"
    assert env["ATELIER_GIT_TOKEN_FILE"] == str(reglages.github_token_path)

    # L'origine du dépôt est nue ; les fichiers de l'Atelier vont dans .git/info/exclude.
    origine = git_repos._git(dossier, "remote", "get-url", "origin")
    assert "@" not in origine and JETON not in origine and origine.endswith("octo/projet.git")
    assert ".mcp.json" in (dossier / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert git_repos.est_un_clone(dossier)
    assert json.loads((dossier / ".git" / "atelier-clone.json").read_text(encoding="utf-8"))["depot"] == "octo/projet"

    # Rappeler la protection de l'Atelier (à chaque tour) ne crée ni ne modifie rien de suivi.
    assert (dossier / ".gitignore").read_text(encoding="utf-8") == "*.log\n"
    assert git_repos.completer_le_gitignore(dossier) == []
    (dossier / ".mcp.json").write_text("{}", encoding="utf-8")
    assert git_repos._git(dossier, "status", "--porcelain") == "", "un fichier de l'Atelier n'apparaît pas comme modifié"
    assert (dossier / ".gitignore").read_text(encoding="utf-8") == "*.log\n"

    registre = json.loads((reglages.work_dir / ".atelier-etat" / "depots.json").read_text(encoding="utf-8"))
    assert registre["projet"]["depot"] == "octo/projet" and registre["projet"]["branche"] == "main"
    assert stat.S_IMODE((reglages.work_dir / ".atelier-etat" / "depots.json").stat().st_mode) == 0o600


def test_un_second_clone_du_meme_depot_prend_un_autre_nom(reglages: AtelierSettings, github: _Github, distant: Path) -> None:
    _connecte(reglages, github)
    github.reponses["/repos/octo/projet"] = _depot("octo/projet")
    assert github_compte.cloner(reglages, "octo/projet")["slug"] == "projet"
    assert github_compte.cloner(reglages, "octo/projet")["slug"] == "projet-2"


def test_un_depot_trop_gros_ou_inaccessible_n_est_pas_clone(reglages: AtelierSettings, github: _Github, distant: Path) -> None:
    _connecte(reglages, github)
    github.reponses["/repos/octo/projet"] = _depot("octo/projet", size=github_compte.TAILLE_MAX_KO + 1)
    with pytest.raises(ErreurGithub, match="trop gros"):
        github_compte.cloner(reglages, "octo/projet")
    with pytest.raises(ErreurGithub, match="Introuvable"):
        github_compte.cloner(reglages, "octo/secret")
    github.reponses["/repos/octo/autre"] = _depot("octo/AUTRE-NOM")
    with pytest.raises(ErreurGithub, match="n'a pas rendu ce dépôt"):
        github_compte.cloner(reglages, "octo/autre")
    assert not (reglages.projects_dir / "projet").exists() and not (reglages.projects_dir / "autre").exists()


def test_un_clone_qui_echoue_ne_laisse_rien_derriere_lui(reglages: AtelierSettings, github: _Github, distant: Path) -> None:
    _connecte(reglages, github)
    github.reponses["/repos/octo/absent"] = _depot("octo/absent")  # GitHub le connaît, le « distant » non
    with pytest.raises(ErreurGithub, match="Le clonage a échoué"):
        github_compte.cloner(reglages, "octo/absent")
    assert not (reglages.projects_dir / "absent").exists()
    assert not (reglages.work_dir / ".atelier-etat" / "depots.json").exists()


# ── Les routes de l'interface ───────────────────────────────────────────


@pytest.fixture()
def client(reglages: AtelierSettings, github: _Github) -> TestClient:
    return TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE)


def _cle(client: TestClient) -> dict[str, str]:
    return {"Authorization": f"Bearer {client.app.state.auth.owner_key}"}


def _personne(client: TestClient) -> dict[str, str]:
    sid = client.app.state.auth.ouvrir_session()
    return {"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": ORIGINE}


def test_la_cle_lit_l_etat_mais_ne_connecte_ni_ne_deconnecte_ni_ne_liste(client: TestClient, reglages: AtelierSettings) -> None:
    assert client.get("/v1/github", headers=_cle(client)).json()["connecte"] is False
    for r in (
        client.put("/v1/github", json={"jeton": JETON}, headers=_cle(client)),
        client.delete("/v1/github", headers=_cle(client)),
        client.get("/v1/github/depots", headers=_cle(client)),
    ):
        assert r.status_code == 403 and "Réservé à la personne" in r.json()["detail"]
    assert not reglages.github_token_path.exists()


def test_la_personne_connecte_liste_puis_deconnecte_sans_que_le_jeton_sorte(
    client: TestClient, reglages: AtelierSettings, github: _Github
) -> None:
    h = _personne(client)
    github.reponses["/user"] = {"login": "octo", "name": "Octo"}
    github.reponses[ROUTE_PAGE_1] = [_depot("octo/projet", private=True)]
    p = client.put("/v1/github", json={"jeton": JETON}, headers=h)
    assert p.status_code == 200 and p.json()["login"] == "octo" and JETON not in p.text
    assert client.get("/v1/github", headers=_cle(client)).json()["connecte"] is True
    liste = client.get("/v1/github/depots?q=proj", headers=h)
    assert liste.status_code == 200 and liste.json()["depots"][0]["nom"] == "octo/projet" and JETON not in liste.text
    d = client.delete("/v1/github", headers=h)
    assert d.status_code == 200 and d.json()["connecte"] is False and not reglages.github_token_path.exists()
    # Au journal : qu'un compte a été connecté, jamais le jeton.
    lignes = client.app.state.journal_unique.lire(commande="github_connecter")
    assert lignes and lignes[0]["resultat"] == "fait" and lignes[0]["acteur"] == "personne"
    assert JETON not in json.dumps(client.app.state.journal_unique.lire())


def test_un_refus_de_github_se_lit_et_est_au_journal_sans_le_jeton(client: TestClient, github: _Github) -> None:
    github.reponses["/user"] = ErreurGithub("GitHub refuse ce jeton : il est invalide, expiré ou révoqué.")
    r = client.put("/v1/github", json={"jeton": JETON}, headers=_personne(client))
    assert r.status_code == 400 and "invalide, expiré ou révoqué" in r.json()["detail"] and JETON not in r.text
    lignes = client.app.state.journal_unique.lire(commande="github_connecter")
    assert lignes[0]["resultat"] == "refus" and JETON not in json.dumps(lignes)


# ── Les commandes de l'Assistant ────────────────────────────────────────


def test_la_personne_ouvre_un_depot_comme_projet_par_la_commande(
    client: TestClient, reglages: AtelierSettings, github: _Github, distant: Path
) -> None:
    h = _personne(client)
    github.reponses["/user"] = {"login": "octo"}
    client.put("/v1/github", json={"jeton": JETON}, headers=h)
    github.reponses["/repos/octo/projet"] = _depot("octo/projet", private=True)
    r = client.post(
        "/v1/commandes/atelier_projet_depuis_github", headers=h, json={"arguments": {"depot": "octo/projet", "titre": "Mes sentiers"}}
    )
    assert r.status_code == 200, r.text
    resultat = r.json()["resultat"]
    assert resultat["projet"] == "projet" and resultat["depot"] == "octo/projet" and JETON not in r.text
    assert (reglages.projects_dir / "projet" / "README.md").is_file()
    projets = {p["slug"]: p for p in client.get("/v1/projects", headers=_cle(client)).json()["projects"]}
    assert projets["projet"]["title"] == "Mes sentiers"
    # Le dépôt n'a pas été restructuré : rien ajouté à ce qu'il suit.
    assert git_repos._git(reglages.projects_dir / "projet", "status", "--porcelain") == ""
    # Une demande invalide est refusée avec la raison, sans rien cloner.
    refus = client.post("/v1/commandes/atelier_projet_depuis_github", headers=h, json={"arguments": {"depot": "../x/y"}})
    assert refus.status_code in (403, 422) and "proprietaire/depot" in refus.text


def test_la_commande_de_lecture_liste_les_depots(client: TestClient, github: _Github) -> None:
    h = _personne(client)
    github.reponses["/user"] = {"login": "octo"}
    client.put("/v1/github", json={"jeton": JETON}, headers=h)
    github.reponses[ROUTE_PAGE_1] = [_depot("octo/projet"), _depot("asso/carto")]
    r = client.post("/v1/commandes/atelier_github_depots", headers=h, json={"arguments": {"recherche": "carto"}})
    assert r.status_code == 200 and [d["nom"] for d in r.json()["resultat"]["depots"]] == ["asso/carto"]


def test_ces_commandes_sont_a_l_assistant_pas_aux_agents_de_projet() -> None:
    for nom in ("atelier_github_depots", "atelier_projet_depuis_github"):
        assert outil_permis(nom, "assistant") and not outil_permis(nom, "code")
        assert nom not in OUTILS_DU_PROFIL_CODE
