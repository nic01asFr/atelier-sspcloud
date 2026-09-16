"""Un projet de l'Atelier est un dépôt, et le reste.

Ce que ces tests tiennent : qu'un projet naisse versionné, qu'on puisse le
rappeler sans dégât, que le premier commit existe même sur un projet vide —
sans quoi la branche n'existe pas et la veille ne trouve rien — et que rien
de ce qui touche à GitHub ne parte sans jeton.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier import git_repos
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.projects import ProjectStore

besoin_de_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git absent de la machine"
)


def _journal(chemin: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(chemin), "log", "--format=%s %an <%ae>"],
        capture_output=True,
        text=True,
    ).stdout


@besoin_de_git
def test_un_projet_naît_versionné(reglages: AtelierSettings) -> None:
    projet = ProjectStore(reglages).create("essai-depot", kind="code")
    etat = git_repos.etat(Path(projet.path))
    assert etat.depot
    assert etat.branche == "main"
    # Un dépôt sans commit n'a pas de branche : `rev-parse HEAD` échoue et la
    # veille ne lit rien. Le premier commit doit exister, projet vide ou non.
    assert etat.commits == 1


@besoin_de_git
def test_l_identité_des_commits_est_celle_des_réglages(
    reglages: AtelierSettings, tmp_path: Path, monkeypatch
) -> None:
    """Locale au dépôt : on ne réécrit pas la machine pour un projet.

    Et seulement faute d'identité globale — sur une machine qui en porte une,
    c'est elle qui signe (voir test_liste_et_depots). On lit donc un fichier
    global vide, pour ne pas dépendre du poste où le test tourne.
    """
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig-vide"))
    (tmp_path / "gitconfig-vide").write_text("", encoding="utf-8")
    projet = ProjectStore(reglages).create("essai-identite", kind="code")
    assert f"{reglages.git_user_name} <{reglages.git_user_email}>" in _journal(
        Path(projet.path)
    )


@besoin_de_git
def test_initialiser_deux_fois_ne_casse_rien(reglages: AtelierSettings) -> None:
    """Idempotente : c'est ce qui permet de rattraper les projets anciens."""
    chemin = reglages.projects_dir / "essai-idempotent"
    premier = git_repos.initialiser(reglages, chemin)
    second = git_repos.initialiser(reglages, chemin)
    assert (second.commits, second.branche) == (premier.commits, premier.branche)


@besoin_de_git
def test_enregistrer_ne_commite_que_s_il_y_a_de_quoi(
    reglages: AtelierSettings,
) -> None:
    chemin = reglages.projects_dir / "essai-commit"
    depart = git_repos.initialiser(reglages, chemin).commits
    assert git_repos.enregistrer(reglages, chemin, "rien").commits == depart

    (chemin / "note.md").write_text("du travail", encoding="utf-8")
    apres = git_repos.enregistrer(reglages, chemin, "Ajouter une note")
    assert apres.commits == depart + 1
    assert apres.en_attente == 0


@besoin_de_git
def test_l_état_de_la_machine_reste_hors_de_l_histoire(
    reglages: AtelierSettings,
) -> None:
    chemin = reglages.projects_dir / "essai-gitignore"
    git_repos.initialiser(reglages, chemin)
    (chemin / ".atelier").mkdir(exist_ok=True)
    (chemin / ".atelier" / "session.md").write_text("état", encoding="utf-8")
    (chemin / "CLAUDE.md").write_text("consigne", encoding="utf-8")

    git_repos.enregistrer(reglages, chemin, "Ajouter la consigne")
    suivis = subprocess.run(
        ["git", "-C", str(chemin), "ls-files"], capture_output=True, text=True
    ).stdout
    assert "CLAUDE.md" in suivis
    assert ".atelier" not in suivis


def test_l_état_d_un_dossier_sans_dépôt_ne_lève_pas(tmp_path: Path) -> None:
    etat = git_repos.etat(tmp_path)
    assert not etat.depot
    assert etat.to_dict()["commits"] == 0


def test_pas_de_publication_sans_jeton(reglages: AtelierSettings) -> None:
    assert not git_repos.publication_possible(reglages)
    with pytest.raises(git_repos.ErreurDepot):
        git_repos.publier(reglages, reglages.projects_dir / "x", "x")


def test_l_url_du_distant_ne_rend_jamais_ce_qui_precede_l_arobase() -> None:
    """Une URL posée à la main ailleurs peut porter un jeton. Pas dans l'API."""
    assert (
        git_repos._url_sans_secret("https://jeton@github.com/a/b.git")
        == "https://github.com/a/b.git"
    )


@besoin_de_git
def test_la_route_dit_l_état_sans_rien_promettre(atelier: TestClient) -> None:
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    entete = {"Authorization": f"Bearer {cle}"}
    atelier.post("/v1/projects", headers=entete, json={"slug": "essai-route"})

    r = atelier.get("/v1/projects/essai-route/git", headers=entete)
    assert r.status_code == 200
    corps = r.json()
    assert corps["repo"] is True
    assert corps["branch"] == "main"
    # Sans jeton ni propriétaire, l'interface ne doit pas proposer de publier.
    assert corps["can_publish"] is False


@besoin_de_git
def test_un_env_n_est_pas_versionne(reglages: AtelierSettings) -> None:
    """On en a trouvé un qui disait « ne pas committer » sur sa 1re ligne."""
    chemin = reglages.projects_dir / "essai-env"
    chemin.mkdir(parents=True)
    (chemin / ".env.sspcloud").write_text("export CLE=sk-secret", encoding="utf-8")
    (chemin / ".env.example").write_text("export CLE=", encoding="utf-8")
    (chemin / "main.py").write_text("print(1)", encoding="utf-8")

    git_repos.initialiser(reglages, chemin)
    suivis = subprocess.run(
        ["git", "-C", str(chemin), "ls-files"], capture_output=True, text=True
    ).stdout
    assert "main.py" in suivis
    assert ".env.sspcloud" not in suivis
    # Un modèle est fait pour être lu : il n'a rien à cacher.
    assert ".env.example" in suivis


@besoin_de_git
def test_rien_ne_part_si_un_secret_est_deja_suivi(reglages: AtelierSettings) -> None:
    """Le .gitignore ne rattrape pas ce qui était suivi avant lui."""
    chemin = reglages.projects_dir / "essai-deja-suivi"
    git_repos.initialiser(reglages, chemin)
    (chemin / ".env").write_text("CLE=sk-secret", encoding="utf-8")
    subprocess.run(["git", "-C", str(chemin), "add", "-f", ".env"], check=True)
    subprocess.run(
        ["git", "-C", str(chemin), "commit", "-m", "avant la regle", "--no-verify"],
        check=True,
        capture_output=True,
    )

    assert git_repos.fichiers_sensibles_suivis(chemin) == [".env"]
    reglages.github_owner = "quelqu-un"
    reglages.github_token_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.github_token_path.write_text("jeton-factice", encoding="utf-8")
    with pytest.raises(git_repos.ErreurDepot, match="publication refusée"):
        git_repos.publier(reglages, chemin, "essai")


@besoin_de_git
def test_un_secret_retire_du_suivi_bloque_encore(reglages: AtelierSettings) -> None:
    """Le retirer ne le retire pas du passé, et c'est le passé que push emporte."""
    chemin = reglages.projects_dir / "essai-histoire"
    git_repos.initialiser(reglages, chemin)
    (chemin / ".env").write_text("CLE=sk-secret", encoding="utf-8")
    for args in (["add", "-f", ".env"], ["commit", "-m", "avant", "--no-verify"]):
        subprocess.run(["git", "-C", str(chemin), *args], check=True, capture_output=True)
    for args in (["rm", "--cached", "-q", ".env"], ["commit", "-m", "retire", "--no-verify"]):
        subprocess.run(["git", "-C", str(chemin), *args], check=True, capture_output=True)

    assert git_repos.fichiers_sensibles_suivis(chemin) == []
    assert git_repos.fichiers_sensibles_dans_l_histoire(chemin) == [".env"]

    reglages.github_owner = "quelqu-un"
    reglages.github_token_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.github_token_path.write_text("jeton-factice", encoding="utf-8")
    with pytest.raises(git_repos.ErreurDepot, match="publication refusée"):
        git_repos.publier(reglages, chemin, "essai")
