"""`atelier_projet_deployer_declarer` et les points d'entrée Onyxia de la passerelle.

Onyxia est remplacé par un faux qui note ce qu'on lui envoie : la commande
réutilise `project_bind`, et le mandataire sert `initialize` et
`notifications/initialized` sans jamais l'attendre (G3).
"""

from __future__ import annotations

import asyncio
import json
import shutil
from typing import Any

import pytest

from mcp_gateway.atelier import onyxia_projet as ox
from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.catalogue import APERCU, FAIT, REFUSE
from mcp_gateway.atelier.commandes.modele import ORIGINE_MCP, Contexte

from test_onyxia_projet import OUTILS_AMONT, POD, FauxOnyxia, _texte

besoin_de_git = pytest.mark.skipif(shutil.which("git") is None, reason="git absent")

NOM = "atelier_projet_deployer_declarer"


def _executer(atelier: Any, nom: str, arguments: dict[str, Any], *, confirme: bool = True) -> Any:
    ctx = Contexte(acteur="conversation:essai", origine=ORIGINE_MCP, confirme=confirme)
    return asyncio.run(atelier.app.state.commandes.executer(nom, arguments, ctx))


def _projet(atelier: Any) -> str:
    reponse = _executer(atelier, "atelier_projet_creer", {"titre": "Carte", "gabarit": "application"})
    assert reponse.statut == FAIT, reponse.charge
    return reponse.charge["projet"]


def _brancher(atelier: Any, faux: FauxOnyxia) -> None:
    mandataire = atelier.app.state.onyxia_mandataire
    mandataire._appeler = faux.appeler  # noqa: SLF001
    mandataire._outils_amont = faux.outils  # noqa: SLF001


def _fiche(atelier: Any, slug: str) -> structure.ProjetJson:
    fiche = structure.lire(atelier.app.state.settings.projects_dir / slug)
    assert fiche is not None
    return fiche


# ── La commande ─────────────────────────────────────────────────────────


@besoin_de_git
def test_la_commande_est_engageante_et_montre_un_apercu(atelier) -> None:  # noqa: ANN001
    slug = _projet(atelier)
    commande = atelier.app.state.commandes.commande(NOM)
    assert commande is not None and commande.classe == "engageante"
    reponse = _executer(atelier, NOM, {"projet": slug, "pod": POD}, confirme=False)
    assert reponse.statut == APERCU
    assert reponse.charge["apercu"]["apres"] == {"pod": POD, "gpu": False}
    assert "borné" in reponse.charge["apercu"]["effet"]
    # Rien n'est écrit avant l'accord.
    assert _fiche(atelier, slug).deploiement is None


@besoin_de_git
def test_declarer_un_pod_reutilise_project_bind_et_ecrit_la_fiche(atelier) -> None:  # noqa: ANN001
    slug = _projet(atelier)
    faux = FauxOnyxia()
    _brancher(atelier, faux)
    reponse = _executer(atelier, NOM, {"projet": slug, "pod": POD, "gpu": True, "commande": "python app.py", "port": 8000})
    assert reponse.statut == FAIT, reponse.charge
    assert faux.envoyes("project_bind") == [{"session_id": f"proj-{slug}", "pod": POD, "project": slug}]
    deploiement = _fiche(atelier, slug).deploiement
    assert deploiement is not None and deploiement.pod == POD and deploiement.gpu and deploiement.port == 8000
    assert reponse.charge["carte"]["preuve"]["commit"]
    # Désormais, un agent code du projet reçoit Onyxia, borné.
    entree = ox.onyxia_pour_projet(atelier.app.state.settings, slug, "code")
    assert entree is not None and entree["url"].endswith(f"/mcp/onyxia/projet/{slug}")
    # Annuler retire la liaison.
    assert reponse.charge["carte"]["annuler"] is not None


@besoin_de_git
def test_annuler_sa_declaration_retire_la_liaison_sans_nouvel_accord(atelier) -> None:  # noqa: ANN001
    slug = _projet(atelier)
    _brancher(atelier, FauxOnyxia())
    reponse = _executer(atelier, NOM, {"projet": slug, "service": "carte.service.yml"})
    assert reponse.statut == FAIT, reponse.charge
    # L'inverse (la commande elle-même, engageante) s'applique : le « Oui » d'origine vaut pour elle.
    annule = _executer(atelier, "atelier_annuler", {"action": reponse.action}, confirme=False)
    assert annule.statut == FAIT, annule.charge
    assert _fiche(atelier, slug).deploiement is None


@besoin_de_git
def test_un_pod_qu_onyxia_refuse_n_est_pas_declare(atelier) -> None:  # noqa: ANN001
    slug = _projet(atelier)

    async def refus(outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return _texte({"error": {"code": "POD_UNREACHABLE", "message": "Pod non Running."}}, erreur=True)

    atelier.app.state.onyxia_mandataire._appeler = refus  # noqa: SLF001
    reponse = _executer(atelier, NOM, {"projet": slug, "pod": POD})
    assert reponse.statut == REFUSE
    assert "Running" in reponse.charge["erreur"]
    assert _fiche(atelier, slug).deploiement is None


@besoin_de_git
def test_onyxia_injoignable_la_declaration_est_ecrite_et_liee_plus_tard(atelier) -> None:  # noqa: ANN001
    slug = _projet(atelier)
    # Harnais factice : la passerelle n'a pas de pool.
    reponse = _executer(atelier, NOM, {"projet": slug, "pod": POD})
    assert reponse.statut == FAIT, reponse.charge
    assert "a_faire" in reponse.charge["liaison"]
    assert _fiche(atelier, slug).deploiement is not None


@besoin_de_git
def test_retirer_le_deploiement(atelier) -> None:  # noqa: ANN001
    slug = _projet(atelier)
    _brancher(atelier, FauxOnyxia())
    assert _executer(atelier, NOM, {"projet": slug, "service": "carte.service.yml"}).statut == FAIT
    reponse = _executer(atelier, NOM, {"projet": slug, "retirer": True})
    assert reponse.statut == FAIT, reponse.charge
    assert _fiche(atelier, slug).deploiement is None
    assert ox.onyxia_pour_projet(atelier.app.state.settings, slug, "code") is None


@besoin_de_git
@pytest.mark.parametrize(
    "arguments",
    [
        {"pod": POD, "service": "carte.service.yml"},
        {},
        {"pod": "Pas Un Pod"},
        {"retirer": True, "pod": POD},
        {"pod": POD, "port": "8000"},
    ],
)
def test_arguments_invalides_refuses(atelier, arguments: dict[str, Any]) -> None:  # noqa: ANN001
    slug = _projet(atelier)
    reponse = _executer(atelier, NOM, {"projet": slug, **arguments})
    assert reponse.statut == REFUSE, reponse.charge


@besoin_de_git
@pytest.mark.parametrize("arguments", [{"pod": POD, "service": "carte.service.yml"}, {"pod": "Pas Un Pod"}])
def test_un_apercu_aux_arguments_faux_est_un_refus(atelier, arguments: dict[str, Any]) -> None:  # noqa: ANN001
    """Sans confirmation, l'aperçu refuse lui-même, sans jeton ni exception (catalogue)."""
    slug = _projet(atelier)
    reponse = _executer(atelier, NOM, {"projet": slug, **arguments}, confirme=False)
    assert reponse.statut == REFUSE, reponse.charge
    assert "déploiement invalide" in reponse.charge["erreur"] and "confirmation" not in reponse.charge
    ligne = atelier.app.state.commandes.journal.lire(commande=NOM, limite=1)[0]
    assert ligne["resultat"] == "refus"
    assert _executer(atelier, NOM, {"projet": "inconnu", "pod": POD}, confirme=False).statut == REFUSE


def test_projet_inconnu_ou_assistant_refuse(atelier) -> None:  # noqa: ANN001
    for projet in ("inconnu", atelier.app.state.settings.assistant_slug, "../x"):
        assert _executer(atelier, NOM, {"projet": projet, "pod": POD}).statut == REFUSE


# ── Les points d'entrée HTTP ────────────────────────────────────────────


def _poser_deploiement(atelier: Any, slug: str, deploiement: dict[str, Any]) -> None:
    racine = atelier.app.state.settings.projects_dir / slug
    structure.ecrire(racine, structure.valider({"slug": slug, "titre": slug, "deploiement": deploiement}))


def _post(atelier: Any, chemin: str, corps: Any, cle: str | None, **entetes: str) -> Any:
    if cle is not None:
        entetes["Authorization"] = f"Bearer {cle}"
    return atelier.post(chemin, content=json.dumps(corps), headers={"Content-Type": "application/json", **entetes})


def test_l_initialisation_ne_touche_pas_onyxia(atelier, cle_du_proprietaire: str) -> None:  # noqa: ANN001
    _poser_deploiement(atelier, "carte", {"pod": POD})
    faux = FauxOnyxia()
    _brancher(atelier, faux)
    chemin = "/mcp/onyxia/projet/carte"
    init = _post(atelier, chemin, {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}}, cle_du_proprietaire)
    assert init.status_code == 200 and init.headers.get("mcp-session-id")
    sid = init.headers["mcp-session-id"]
    notif = _post(atelier, chemin, {"jsonrpc": "2.0", "method": "notifications/initialized"}, cle_du_proprietaire, **{"Mcp-Session-Id": sid})
    # G3 : 202, corps vide et délimité.
    assert notif.status_code == 202
    assert notif.headers.get("content-length") == "0"
    liste = _post(atelier, chemin, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, cle_du_proprietaire, **{"Mcp-Session-Id": sid})
    noms = {o["name"] for o in liste.json()["result"]["tools"]}
    assert "exec" in noms and "expose_public" not in noms and "list_pods" not in noms
    assert faux.appels == []


def test_un_appel_vers_un_autre_pod_est_refuse_par_http(atelier, cle_du_proprietaire: str) -> None:  # noqa: ANN001
    _poser_deploiement(atelier, "carte", {"pod": POD})
    faux = FauxOnyxia({"proj-carte": POD})
    _brancher(atelier, faux)
    appel = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "exec", "arguments": {"code": "1", "session_id": "proj-autre"}}}
    reponse = _post(atelier, "/mcp/onyxia/projet/carte", appel, cle_du_proprietaire).json()
    assert reponse["result"]["isError"]
    assert faux.envoyes("exec") == []
    appel["params"]["arguments"] = {"code": "1"}
    reponse = _post(atelier, "/mcp/onyxia/projet/carte", appel, cle_du_proprietaire).json()
    assert not reponse["result"]["isError"]
    assert faux.envoyes("exec") == [{"code": "1", "session_id": "proj-carte"}]


def test_projet_sans_deploiement_n_a_aucun_outil(atelier, cle_du_proprietaire: str) -> None:  # noqa: ANN001
    _brancher(atelier, FauxOnyxia())
    liste = _post(atelier, "/mcp/onyxia/projet/sans-deploiement", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, cle_du_proprietaire)
    assert liste.json()["result"]["tools"] == []


def test_le_point_d_entree_complet_sert_l_assistant(atelier, cle_du_proprietaire: str) -> None:  # noqa: ANN001
    _brancher(atelier, FauxOnyxia())
    liste = _post(atelier, "/mcp/onyxia", {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, cle_du_proprietaire).json()
    assert len(liste["result"]["tools"]) == len(OUTILS_AMONT)
    appel = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "expose_public", "arguments": {}}}
    assert _post(atelier, "/mcp/onyxia", appel, cle_du_proprietaire).json()["result"]["isError"]


@pytest.mark.parametrize("chemin", ["/mcp/onyxia", "/mcp/onyxia/projet/carte"])
def test_sans_cle_refuse(atelier, chemin: str) -> None:  # noqa: ANN001
    assert _post(atelier, chemin, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, None).status_code == 401
    assert _post(atelier, chemin, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "mauvaise").status_code == 401
