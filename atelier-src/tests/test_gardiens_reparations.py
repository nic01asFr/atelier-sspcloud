"""G5, côté exécuteur : un constat qui persiste demande un agent réparateur à l'Atelier.

Les contrôles sont de vraies sondes (`sante.service`) contre un service qui ne
répond pas ; la demande part par une fonction d'envoi remplaçable. Le dernier
test branche l'exécuteur sur un vrai Atelier (sa route de lancement, un vrai
dépôt git) : du constat jusqu'à la proposition dans « À valider ».
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from mcp_gateway.gardiens.controles.commun import Contexte, ReponseHttp
from mcp_gateway.gardiens.declaration import DeclarationInvalide, lire
from mcp_gateway.gardiens.executeur import Executeur
from mcp_gateway.gardiens.journal import Filtre, Journal
from mcp_gateway.gardiens.reparations import Reparations, branche_de

SECRET = "valeur-secrete-du-pool-123456789"


class Horloge:
    def __init__(self, t: float = 1_790_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class Envoi:
    """La route de lancement de l'Atelier, simulée : retient les demandes."""

    def __init__(self, statut: int = 202) -> None:
        self.statut = statut
        self.demandes: list[dict[str, Any]] = []
        self.cles: list[str] = []

    def __call__(self, corps: dict[str, Any], cle: str) -> tuple[int, dict[str, Any]]:
        self.demandes.append(corps)
        self.cles.append(cle)
        if self.statut == 0:
            return 0, {"erreur": "ConnectionRefusedError"}
        n = len(self.demandes)
        return self.statut, {"statut": "fait", "lancement": {
            "id": f"lc-20260926-0000000{n}", "branche": corps["branche"], "conversation": f"conv-{n}"}}


def sonde(ident: str, service: str, proposer: dict[str, Any] | None = None) -> dict[str, Any]:
    brut: dict[str, Any] = {
        "id": ident, "gardien": "sante", "portee": "pod", "quand": {"toutes_les_min": 1},
        "commande": ["interne", "sante.service"], "delai_s": 5, "params": {"service": service},
    }
    if proposer is not None:
        brut["proposer"] = proposer
    return brut


PROPOSER = {"apres_occurrences": 2, "projet": "outil", "verification": "pytest -q", "delai_min": 20}


def _executeur(tmp_path: Path, controles: list[dict[str, Any]], env: dict[str, str] | None = None,
               envoi: Envoi | None = None, a_blanc: bool = False, par_jour: int = 3) -> tuple[Executeur, Envoi]:
    work = tmp_path / "work"
    (work / ".secrets").mkdir(parents=True, exist_ok=True)
    (work / ".secrets" / "atelier_lanceur_key").write_text("cle-du-lanceur\n", encoding="utf-8")
    ctx = Contexte(
        work=work, home=tmp_path / "home", env=env or {}, ecoutes=lambda: [], processus=lambda: [],
        # Le service ne répond pas, avec un secret dans sa réponse d'erreur.
        http=lambda *a, **k: ReponseHttp(0, "", f"ConnectionRefusedError: jeton {SECRET}"),
    )
    chemin = tmp_path / "gardiens.json"
    chemin.write_text(json.dumps({"controles": controles}), encoding="utf-8")
    decl = lire(chemin)
    journal = Journal(tmp_path / "etat" / "journal", Filtre([SECRET]))
    envoi = envoi or Envoi()
    reparations = Reparations(
        dossier_etat=tmp_path / "etat", cle=lambda: "cle-du-lanceur", poster=envoi,
        env=ctx.env, par_jour=par_jour, nettoyer=journal.filtre.nettoyer,
    )
    ex = Executeur(decl, ctx, journal, None if a_blanc else tmp_path / "etat", horloge=Horloge(),
                   a_blanc=a_blanc, reparations=reparations)
    return ex, envoi


def test_un_constat_qui_persiste_demande_un_reparateur_une_seule_fois(tmp_path: Path) -> None:
    ex, envoi = _executeur(tmp_path, [sonde("sante.wikichat", "wikichat", PROPOSER)])
    c = ex.controles["sante.wikichat"]
    ex.passer(c)
    assert envoi.demandes == [], "sous le seuil : un signalement, pas de réparation"
    ligne = ex.passer(c)
    assert len(envoi.demandes) == 1
    demande = envoi.demandes[0]
    assert envoi.cles == ["cle-du-lanceur"]
    assert demande["origine"] == "gardien:sante.wikichat"
    assert demande["projet"] == "outil"
    assert demande["branche"] == branche_de("sante", "sante.wikichat", ex.horloge())
    assert demande["branche"].startswith("gardien/sante/")
    assert demande["plafonds"] == {"duree_s": 1200, "jetons": 150000}
    assert "pytest -q" in demande["message"] and "ne pousses rien" in demande["message"]
    assert demande["reparation"]["empreinte"] and demande["reparation"]["verification"] == "pytest -q"
    # Aucune valeur secrète ne part dans le brief.
    assert SECRET not in json.dumps(demande)
    assert ligne["reparations"][0]["demandee"]["lancement"] == "lc-20260926-00000001"
    # Revu : l'alerte est servie, rien ne repart.
    for _ in range(3):
        ex.passer(c)
    assert len(envoi.demandes) == 1
    # Le registre survit à un redémarrage de l'exécuteur.
    registre = json.loads((tmp_path / "etat" / "reparations.json").read_text(encoding="utf-8"))
    assert registre[0]["controle"] == "sante.wikichat" and registre[0]["projet"] == "outil"


@pytest.mark.parametrize("env", [{"ATELIER_GARDIENS_GESTES": "0"}, {"ATELIER_GARDIENS_REPARATIONS": "0"}])
def test_les_interrupteurs_coupent_les_reparations(tmp_path: Path, env: dict[str, str]) -> None:
    ex, envoi = _executeur(tmp_path, [sonde("sante.wikichat", "wikichat", PROPOSER)], env=env)
    c = ex.controles["sante.wikichat"]
    ex.passer(c)
    ligne = ex.passer(c)
    assert envoi.demandes == []
    assert ligne["reparations"][0]["refuse"] == f"{next(iter(env))}=0"
    # Le même refus n'est pas répété à chaque passage.
    assert "reparations" not in ex.passer(c)


def test_a_blanc_aucune_reparation(tmp_path: Path) -> None:
    ex, envoi = _executeur(tmp_path, [sonde("sante.wikichat", "wikichat", PROPOSER)], a_blanc=True)
    c = ex.controles["sante.wikichat"]
    for _ in range(3):
        ex.passer(c)
    assert envoi.demandes == [] and ex.reparations is None


def test_sans_projet_declare_le_constat_reste_un_signalement(tmp_path: Path) -> None:
    proposer = {"apres_occurrences": 1}
    ex, envoi = _executeur(tmp_path, [sonde("sante.wikichat", "wikichat", proposer)])
    ligne = ex.passer(ex.controles["sante.wikichat"])
    assert envoi.demandes == [] and "signalement seul" in ligne["reparations"][0]["refuse"]


def test_trois_reparations_par_jour_au_plus(tmp_path: Path) -> None:
    proposer = {"apres_occurrences": 1, "projet": "outil"}
    controles = [sonde(f"sante.s{i}", f"s{i}", proposer) for i in range(4)]
    ex, envoi = _executeur(tmp_path, controles)
    lignes = [ex.passer(ex.controles[f"sante.s{i}"]) for i in range(4)]
    assert len(envoi.demandes) == 3
    assert "3 réparations aujourd'hui" in lignes[3]["reparations"][0]["refuse"]


def test_atelier_injoignable_on_redemande_au_passage_suivant(tmp_path: Path) -> None:
    envoi = Envoi(statut=0)
    ex, _ = _executeur(tmp_path, [sonde("sante.wikichat", "wikichat", {"apres_occurrences": 1, "projet": "outil"})], envoi=envoi)
    c = ex.controles["sante.wikichat"]
    assert "injoignable" in ex.passer(c)["reparations"][0]["echec"]
    envoi.statut = 202
    assert ex.passer(c)["reparations"][0]["demandee"]
    assert len(envoi.demandes) == 2


@pytest.mark.parametrize(
    "proposer",
    [{"projet": "outil"}, {"apres_h": -1}, {"apres_occurrences": 0}, {"apres_h": 1, "delai_min": 90}, {"apres_h": 1, "projet": "../x"}],
)
def test_un_seuil_mal_declare_est_refuse_au_chargement(tmp_path: Path, proposer: dict[str, Any]) -> None:
    chemin = tmp_path / "gardiens.json"
    chemin.write_text(json.dumps({"controles": [sonde("sante.x", "x", proposer)]}), encoding="utf-8")
    with pytest.raises(DeclarationInvalide):
        lire(chemin)


def test_la_declaration_du_paquet_reste_valide() -> None:
    decl = lire()
    ci = next(c for c in decl.controles if c.id == "sante.ci-main")
    assert ci.proposer and ci.proposer["apres_h"] == 24


# --- de bout en bout : exécuteur, route de lancement, dépôt, « À valider » ----


@pytest.mark.skipif(shutil.which("git") is None, reason="git absent")
def test_du_constat_a_la_proposition_dans_a_valider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient

    from mcp_gateway.atelier.api import build_app
    from mcp_gateway.atelier.config import AtelierSettings
    from mcp_gateway.atelier.lancements import ENTETE_CLE

    for cle in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(cle, "Essai")
    for cle in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(cle, "essai@example.invalid")

    reglages = AtelierSettings(work_dir=tmp_path / "atelier-work")
    projet = reglages.projects_dir / "outil"
    projet.mkdir(parents=True)

    def git(*args: str, cwd: Path = projet, env: dict[str, str] | None = None) -> int:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, env={**os.environ, **(env or {})}).returncode

    git("init", "-q", "-b", "main")
    (projet / "service.py").write_text("PORT = 0\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "Premier état")
    main_avant = subprocess.run(["git", "rev-parse", "main"], cwd=projet, capture_output=True, text=True).stdout.strip()

    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:

        def agent(*, cwd: Path, env: dict[str, str], **_: Any) -> None:
            (Path(cwd) / "service.py").write_text("PORT = 3777\n", encoding="utf-8")
            git("commit", "-q", "-am", "Remettre le port", cwd=Path(cwd), env=env)

        client.app.state.harness.pendant_le_tour = agent

        def poster(corps: dict[str, Any], cle: str) -> tuple[int, dict[str, Any]]:
            r = client.post("/v1/lancements", headers={ENTETE_CLE: cle}, json=corps)
            return r.status_code, r.json()

        cle_du_lanceur = (reglages.secrets_dir / "atelier_lanceur_key").read_text(encoding="utf-8").strip()
        ex, _ = _executeur(tmp_path, [sonde("sante.wikichat", "wikichat", {"apres_occurrences": 2, "projet": "outil"})])
        ex.reparations.poster = poster
        ex.reparations.cle = lambda: cle_du_lanceur
        c = ex.controles["sante.wikichat"]
        ex.passer(c)
        ligne = ex.passer(c)
        demandee = ligne["reparations"][0]["demandee"]
        lanceur = client.app.state.lancements
        fin = lanceur.attendre(demandee["lancement"], 20)
        assert fin.etat == "fini" and fin.origine == "gardien:sante.wikichat"

        (p,) = client.app.state.a_valider.lister()
        assert p.source == "gardien" and p.projet == "outil"
        assert p.action["commande"] == "atelier_reparation_fusionner"
        assert p.detail["avant"]["controle"] == "sante.wikichat"
        assert SECRET not in json.dumps(p.to_dict())
        assert subprocess.run(["git", "rev-parse", "main"], cwd=projet, capture_output=True, text=True).stdout.strip() == main_avant
        # La conversation du réparateur est une conversation de l'Atelier, visible.
        fiche = client.app.state.store.get(fin.conversation)
        assert fiche.lance_par == "gardien:sante.wikichat" and fiche.title == "Réparation : sante.wikichat"
