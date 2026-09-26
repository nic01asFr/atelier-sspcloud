"""Les agents réparateurs des gardiens (G5), côté Atelier.

Un vrai dépôt git, un vrai remote (dépôt nu local), la vraie route de
lancement, la vraie file « À valider ». Le harnais factice joue l'agent : dans
la copie de travail et avec l'environnement que recevrait `claude`, il commite
sa correction, puis tente ce qu'un réparateur ne doit jamais pouvoir faire —
déplacer `main`, poser une étiquette, pousser. Rien de cela ne doit aboutir,
et la proposition doit attendre la personne.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

ORIGINE = "https://testserver"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")


@pytest.fixture(autouse=True)
def _identite_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for cle, valeur in {
        "GIT_AUTHOR_NAME": "Essai", "GIT_AUTHOR_EMAIL": "essai@example.invalid",
        "GIT_COMMITTER_NAME": "Essai", "GIT_COMMITTER_EMAIL": "essai@example.invalid",
    }.items():
        monkeypatch.setenv(cle, valeur)


def _git(dossier: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=dossier, capture_output=True, text=True,
        env={**os.environ, **(env or {})}, check=False,
    )


def _depot(reglages: AtelierSettings, slug: str = "outil") -> tuple[Path, Path]:
    """Un projet sous git, sur `main`, avec un remote `origin` (dépôt nu) à jour."""
    distant = reglages.work_dir.parent / f"{slug}-distant.git"
    _git(reglages.work_dir.parent, "init", "--bare", "-q", str(distant))
    projet = reglages.projects_dir / slug
    projet.mkdir(parents=True)
    _git(projet, "init", "-q", "-b", "main")
    (projet / "CLAUDE.md").write_text("@.atelier/contexte.md\n\n# Outil\n", encoding="utf-8")
    (projet / "calcul.py").write_text("def double(x):\n    return x + x + 1\n", encoding="utf-8")
    _git(projet, "add", "-A")
    _git(projet, "commit", "-q", "-m", "Premier état")
    _git(projet, "remote", "add", "origin", str(distant))
    assert _git(projet, "push", "-q", "origin", "main").returncode == 0
    return projet, distant


def _sha(dossier: Path, ref: str) -> str:
    return _git(dossier, "rev-parse", ref).stdout.strip()


def _personne(client: TestClient) -> dict[str, str]:
    sid = client.app.state.auth.ouvrir_session()  # type: ignore[attr-defined]
    return {"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": ORIGINE}


def _reparer(client: TestClient, **corps: Any) -> Any:
    corps.setdefault("origine", "gardien:sante.ci-main")
    corps.setdefault("projet", "outil")
    corps.setdefault("branche", "gardien/sante/2026-09-26-ci")
    corps.setdefault("plafonds", {"duree_s": 600, "jetons": 150000})
    corps.setdefault("message", "La CI de main est rouge : double(2) rend 5. Corrige, vérifie, commite, arrête-toi.")
    corps.setdefault("reparation", {
        "controle": "sante.ci-main", "empreinte": "sante.ci-main:outil",
        "resume": "CI de main rouge", "preuve": "test_double : 5 != 4", "verification": "pytest",
    })
    return client.post("/v1/lancements", headers={ENTETE_CLE: lire_la_cle(client.app.state.settings)}, json=corps)


class _AgentReparateur:
    """Ce que ferait l'agent, dans sa copie, avec l'environnement du tour."""

    def __init__(self, distant: Path) -> None:
        self.distant = distant
        self.codes: dict[str, int] = {}
        self.cwd: Path | None = None
        self.env: dict[str, str] = {}

    def __call__(self, *, cwd: Path, env: dict[str, str], **_: Any) -> None:
        self.cwd, self.env = Path(cwd), env
        (self.cwd / "calcul.py").write_text("def double(x):\n    return x + x\n", encoding="utf-8")
        self.codes["add"] = _git(self.cwd, "add", "calcul.py", env=env).returncode
        self.codes["commit"] = _git(self.cwd, "commit", "-q", "-m", "Corriger double", env=env).returncode
        # Ce qui ne doit jamais aboutir.
        self.codes["update-ref main"] = _git(self.cwd, "update-ref", "refs/heads/main", "HEAD", env=env).returncode
        self.codes["tag"] = _git(self.cwd, "tag", "v9", env=env).returncode
        self.codes["branche ailleurs"] = _git(self.cwd, "branch", "autre", env=env).returncode
        self.codes["push main"] = _git(self.cwd, "push", "origin", "HEAD:main", env=env).returncode
        self.codes["push --no-verify"] = _git(
            self.cwd, "push", "--no-verify", "origin", "HEAD:refs/heads/autre", env=env
        ).returncode
        self.codes["push par adresse"] = _git(
            self.cwd, "push", "--no-verify", str(self.distant), "HEAD:refs/heads/par-adresse", env=env
        ).returncode


def test_le_reparateur_ne_touche_pas_main_et_depose_sa_proposition(reglages: AtelierSettings) -> None:
    projet, distant = _depot(reglages)
    main_avant = _sha(projet, "main")
    distant_avant = _git(distant, "for-each-ref", "--format=%(refname) %(objectname)").stdout
    agent = _AgentReparateur(distant)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE) as client:
        client.app.state.harness.pendant_le_tour = agent
        r = _reparer(client)
        assert r.status_code == 202, r.text
        ident = r.json()["lancement"]["id"]
        client.app.state.lancements.attendre(ident, 20)
        fin = client.app.state.lancements.lire(ident)
        assert fin.etat == "fini", fin

        # L'agent a travaillé dans une copie, sur sa branche, en acceptEdits.
        assert agent.cwd is not None and agent.cwd.parent == (projet / ".atelier" / "reparations").resolve()
        appel = client.app.state.harness.appels[-1]
        assert appel["permission_mode"] == "acceptEdits"
        assert "Bash(git push:*)" in appel["regles_imposees"]["deny"]
        assert agent.codes["commit"] == 0, "l'agent doit pouvoir commiter sur sa branche"
        for geste in ("update-ref main", "tag", "branche ailleurs", "push main", "push --no-verify", "push par adresse"):
            assert agent.codes[geste] != 0, f"{geste} a abouti"

        # `main` n'a pas bougé, le remote non plus, le projet est propre.
        assert _sha(projet, "main") == main_avant
        assert _git(distant, "for-each-ref", "--format=%(refname) %(objectname)").stdout == distant_avant
        assert _git(projet, "status", "--porcelain").stdout.strip() == ""
        assert (projet / "calcul.py").read_text(encoding="utf-8").endswith("x + x + 1\n")

        # Le contexte de la copie dit la branche et l'interdit.
        contexte = (agent.cwd / ".atelier" / "contexte.md").read_text(encoding="utf-8")
        assert "gardien/sante/2026-09-26-ci" in contexte and "ne pousse rien" in contexte

        # La proposition attend dans « À valider » : avant, après, action de fusion.
        propositions = client.app.state.a_valider.lister()
        assert len(propositions) == 1
        p = propositions[0]
        assert p.source == "gardien" and p.projet == "outil"
        assert p.titre.startswith("Réparation proposée")
        assert p.action == {"commande": "atelier_reparation_fusionner", "arguments": {"lancement": ident}}
        assert p.detail["avant"]["commit"] == main_avant and p.detail["avant"]["constat"] == "CI de main rouge"
        assert len(p.detail["apres"]["commits"]) == 1 and "Corriger double" in p.detail["apres"]["commits"][0]
        assert "calcul.py" in p.detail["apres"]["ecart"]
        assert fin.proposition == p.id and fin.conclusion["base_intacte"] is True

        # Un modèle ne fusionne pas (réservée), même avec la clé du propriétaire.
        cle = client.app.state.settings.owner_key_path.read_text().strip()
        r = client.post(f"/v1/a-valider/{p.id}/decision", headers={"Authorization": f"Bearer {cle}"},
                        json={"decision": "accepter"})
        assert r.status_code == 403
        assert _sha(projet, "main") == main_avant

        # La personne accepte : fusion dans main, sans rien pousser.
        r = client.post(f"/v1/a-valider/{p.id}/decision", headers=_personne(client), json={"decision": "accepter"})
        assert r.status_code == 200, r.text
        assert _sha(projet, "main") != main_avant
        assert _sha(projet, "main^2") == _sha(projet, "gardien/sante/2026-09-26-ci")
        assert (projet / "calcul.py").read_text(encoding="utf-8").endswith("x + x\n")
        assert _git(distant, "for-each-ref", "--format=%(refname) %(objectname)").stdout == distant_avant
        assert not agent.cwd.exists(), "la copie de travail est retirée après la fusion"


def test_sans_correction_un_diagnostic_sans_action(reglages: AtelierSettings) -> None:
    _depot(reglages)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE) as client:
        ident = _reparer(client).json()["lancement"]["id"]
        client.app.state.lancements.attendre(ident, 20)
        (p,) = client.app.state.a_valider.lister()
        assert p.titre.startswith("Diagnostic sans correction") and p.action is None


def test_une_reparation_travaille_toujours_sur_une_branche_gardien(reglages: AtelierSettings) -> None:
    _depot(reglages)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE) as client:
        r = _reparer(client, branche="")
        assert r.status_code == 403 and "branche" in r.json()["erreur"]
        r = _reparer(client, branche="main")
        assert r.status_code == 403
        r = _reparer(client, branche="agent/x")
        assert r.status_code == 403
        r = _reparer(client, mode="bypassPermissions", mode_de_la_definition=True)
        assert r.status_code == 202 and r.json()["lancement"]["mode"] == "acceptEdits"
        client.app.state.lancements.attendre(r.json()["lancement"]["id"], 20)


def test_trois_reparations_par_jour_au_plus(reglages: AtelierSettings) -> None:
    _depot(reglages)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url=ORIGINE) as client:
        for i in range(3):
            r = _reparer(client, branche=f"gardien/sante/essai-{i}", origine=f"gardien:controle-{i}")
            assert r.status_code == 202, r.text
            client.app.state.lancements.attendre(r.json()["lancement"]["id"], 20)
        r = _reparer(client, branche="gardien/sante/essai-3", origine="gardien:controle-3")
        assert r.status_code == 403 and "réparations aujourd'hui" in r.json()["erreur"]
