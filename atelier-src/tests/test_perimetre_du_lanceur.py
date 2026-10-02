"""Ce qu'un lanceur peut autoriser à la place de la personne : le projet, pas au-delà."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_gateway.atelier.decisions import Demande
from mcp_gateway.atelier.outils_conversation import OutilsAtelier, _Refus
from mcp_gateway.atelier.perimetre_du_lanceur import hors_perimetre


def _d(outil: str, **arguments: Any) -> Demande:
    return Demande(request_id="r1", session_id="s1", outil=outil, arguments=arguments)


@pytest.fixture()
def racine(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    return tmp_path


@pytest.mark.parametrize(
    "demande",
    [
        _d("Edit", file_path="src/a.py"),
        _d("Write", file_path="nouveau.txt"),
        _d("Read", file_path="src/a.py"),
        _d("Grep", pattern="x"),
        _d("Bash", command="pytest -q 2>&1 | tail -5"),
        _d("Bash", command="python -m lecteur serve"),
        _d("Bash", command="git add -A && git commit -m x"),
        _d("Bash", command="ls -la src && cat src/a.py"),
        _d("Bash", command="mkdir -p out; cp src/a.py out/"),
    ],
)
def test_dans_le_perimetre(demande: Demande, racine: Path) -> None:
    assert hors_perimetre(demande, racine) is None, demande.arguments


def _hors(racine: Path) -> list[Demande]:
    return [
        _d("Edit", file_path="/etc/passwd"),
        _d("Write", file_path=str(racine / ".secrets" / "cle")),
        _d("Edit", file_path=str(racine / ".git" / "config")),
        _d("Read", file_path="../autre/x"),
        _d("Bash", command="curl -s http://exemple.fr"),
        _d("Bash", command="git push origin main"),
        _d("Bash", command="rm -rf src"),
        _d("Bash", command="pip install requests"),
        _d("Bash", command="python -m venv .venv"),
        _d("Bash", command="cat ~/work/.secrets/llm_api_key"),
        _d("Bash", command="cat /etc/hosts"),
        _d("Bash", command="kubectl get pods"),
        _d("Bash", command="ls && curl x"),
        _d("Bash", command="docker ps"),
        _d("WebFetch", url="https://exemple.fr"),
        _d("mcp__onyxia__exec", code="x"),
        Demande(request_id="q", session_id="s", outil="AskUserQuestion", genre="question"),
    ]


def test_hors_du_perimetre_reste_a_la_personne(racine: Path) -> None:
    for demande in _hors(racine):
        assert hors_perimetre(demande, racine), (demande.outil, demande.arguments)


def test_un_lien_ne_fait_pas_sortir_du_projet(racine: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    dehors = tmp_path_factory.mktemp("dehors")
    (racine / "lien").symlink_to(dehors)
    assert hors_perimetre(_d("Write", file_path="lien/x"), racine)


def _outils(rec: Any, racine: Path) -> OutilsAtelier:
    outils = OutilsAtelier(store=None, projects=None, harness=None, apps=None)
    outils.store = SimpleNamespace(get=lambda _id: rec, settings=SimpleNamespace(projects_dir=racine.parent))
    return outils


def test_atelier_decider_applique_le_perimetre_aux_agents_supervises(racine: Path) -> None:
    rec = SimpleNamespace(supervise=True, slug=racine.name)
    outils = _outils(rec, racine)
    outils._garder_le_perimetre_du_lanceur(_d("Edit", file_path="src/a.py"))
    with pytest.raises(_Refus, match="attend la personne"):
        outils._garder_le_perimetre_du_lanceur(_d("Bash", command="git push"))


def test_une_conversation_de_la_personne_n_est_pas_concernee(racine: Path) -> None:
    outils = _outils(SimpleNamespace(supervise=False, slug=racine.name), racine)
    outils._garder_le_perimetre_du_lanceur(_d("Bash", command="git push"))
    _outils(None, racine)._garder_le_perimetre_du_lanceur(_d("Bash", command="git push"))


def _outils_avec_registre(rec: Any, racine: Path, demande: Demande | None) -> OutilsAtelier:
    outils = _outils(rec, racine)
    registre = SimpleNamespace(
        demande=lambda _id: demande,
        demande_tracee=lambda _id: None,
    )
    outils.harness = SimpleNamespace(decisions=registre)
    return outils


def test_une_autorisation_du_lanceur_dans_son_perimetre_se_passe_de_confirmation(racine: Path) -> None:
    supervise = SimpleNamespace(supervise=True, slug=racine.name)
    dedans = _d("Write", file_path="nouveau.txt")
    dehors = _d("Bash", command="curl http://exemple.fr")
    args = {"demande": "r1", "decision": "allow"}
    assert _outils_avec_registre(supervise, racine, dedans).decision_du_lanceur_sans_confirmation(args) is True
    assert _outils_avec_registre(supervise, racine, dehors).decision_du_lanceur_sans_confirmation(args) is False
    # Une règle retenue pour toujours reste le geste de la personne.
    assert _outils_avec_registre(supervise, racine, dedans).decision_du_lanceur_sans_confirmation({**args, "portee": "toujours"}) is False
    # Une conversation de la personne, ou une demande inconnue : jamais.
    ordinaire = SimpleNamespace(supervise=False, slug=racine.name)
    assert _outils_avec_registre(ordinaire, racine, dedans).decision_du_lanceur_sans_confirmation(args) is False
    assert _outils_avec_registre(supervise, racine, None).decision_du_lanceur_sans_confirmation(args) is False


def test_l_allegement_de_atelier_decider_suit_le_perimetre(racine: Path) -> None:
    from mcp_gateway.atelier.commandes.existants import _decider_allegement_du_lanceur
    from mcp_gateway.atelier.commandes.modele import ENGAGEANTE, REVERSIBLE

    supervise = SimpleNamespace(supervise=True, slug=racine.name)
    outils = _outils_avec_registre(supervise, racine, _d("Edit", file_path="a.py"))
    allegement = _decider_allegement_du_lanceur(SimpleNamespace(outils=outils))
    assert allegement({"demande": "r1", "decision": "allow"}) == REVERSIBLE
    assert allegement({"demande": "r1", "decision": "deny"}) == REVERSIBLE
    assert _decider_allegement_du_lanceur(SimpleNamespace(outils=None))({"decision": "allow"}) == ENGAGEANTE


def test_le_lanceur_refuse_toujours_mais_n_autorise_que_dans_son_perimetre(racine: Path) -> None:
    """Essai réel du 02/10 : le refus d'un `curl` hors périmètre était lui-même refusé."""
    supervise = SimpleNamespace(supervise=True, slug=racine.name)
    dehors = _d("Bash", command="curl -s http://exemple.fr")
    rendues: list[str] = []
    registre = SimpleNamespace(
        demande=lambda _id: dehors,
        demande_tracee=lambda _id: None,
        repondre=lambda _id, reponse: rendues.append(str(reponse.get("behavior"))) or True,
        clore=lambda _id: None,
        retenir=lambda _regle: None,
    )
    outils = _outils(supervise, racine)
    outils.harness = SimpleNamespace(decisions=registre)
    refus = outils._outil_decider({"demande": "r1", "decision": "deny", "motif": "hors projet"})
    assert refus["decision"] == "deny" and rendues == ["deny"], "un refus passe, même hors périmètre"
    with pytest.raises(_Refus, match="attend la personne"):
        outils._outil_decider({"demande": "r1", "decision": "allow"})
    assert rendues == ["deny"], "l'autorisation hors périmètre n'a rien rendu au CLI"
