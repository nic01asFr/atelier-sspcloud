"""Les accords de la personne : activer un agent, accorder un secret.

Les deux commandes réservées viennent de l'équipe K (`v2-creations`). Tant que
la branche n'est pas fusionnée ici, elles sont remplacées par de fausses
commandes au même contrat (nom, classe réservée, non exposées, arguments) :
ce qu'on éprouve, c'est le chemin de l'interface — `POST /v1/commandes/<nom>`
par la session, et « Accepter » dans « À valider » — et la liste des noms de
secrets, qui ne rend jamais une valeur.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.accords import noms_des_secrets
from mcp_gateway.atelier.commandes.modele import RESERVEE, Commande, Contexte, Effet

INTERFACE = {"X-Atelier-Interface": "1", "Sec-Fetch-Site": "same-origin"}
VALEUR = "valeur-du-secret-qui-ne-doit-jamais-sortir-42"


def _cle(atelier: TestClient) -> dict[str, str]:
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def _session(atelier: TestClient) -> None:
    assert atelier.post("/v1/auth/cookie", headers=_cle(atelier)).status_code == 200


CONTRAT = {"atelier_agent_activer": ["agent"], "atelier_connecteur_accorder": ["nom", "champ", "secret"]}


@pytest.fixture()
def fausses_commandes(atelier: TestClient) -> list[tuple[str, dict[str, Any]]]:
    """`atelier_agent_activer` et `atelier_connecteur_accorder`, au contrat de K.

    Remplacées même quand la branche de K est là : on éprouve le chemin de
    l'interface, pas le Pilote ni le pool, absents en mode factice. Que les
    vraies suivent le contrat, `test_les_vraies_commandes_suivent_le_contrat`
    le vérifie.
    """
    appels: list[tuple[str, dict[str, Any]]] = []
    catalogue = atelier.app.state.commandes
    for nom, requis in CONTRAT.items():
        catalogue._natives.pop(nom, None)  # noqa: SLF001 — remplacer, pour ce test seulement

        def executer(ctx: Contexte, args: dict[str, Any], nom: str = nom) -> Effet:
            appels.append((nom, dict(args)))
            return Effet(charge={"ok": True, **args}, objet_id=str(args.get("agent") or args.get("nom")), titre=nom)

        catalogue.ajouter(
            Commande(
                nom=nom,
                description="fausse commande au contrat de l'équipe K",
                objet="agent" if "agent" in nom else "connecteur",
                classe=RESERVEE,
                executer=executer,
                schema={"type": "object", "properties": {k: {"type": "string"} for k in requis}, "required": requis},
                exposee_mcp=False,
            )
        )
    return appels


def test_activer_un_agent_par_l_interface_et_jamais_par_la_cle(atelier: TestClient, fausses_commandes) -> None:  # noqa: ANN001
    corps = {"arguments": {"agent": "veille"}}
    r = atelier.post("/v1/commandes/atelier_agent_activer", json=corps, headers=_cle(atelier))
    assert r.status_code == 403 and r.json()["statut"] == "refus"
    assert fausses_commandes == [], "la clé du propriétaire (les agents du pod) n'active rien"
    _session(atelier)
    r = atelier.post("/v1/commandes/atelier_agent_activer", json=corps, headers=INTERFACE)
    assert r.status_code == 200 and r.json()["statut"] == "fait"
    assert fausses_commandes == [("atelier_agent_activer", {"agent": "veille"})]


def test_accepter_une_proposition_qui_active_un_agent(atelier: TestClient, fausses_commandes) -> None:  # noqa: ANN001
    p = atelier.app.state.a_valider.deposer(
        "agent", "Activer la veille", acteur="conversation:x",
        action={"commande": "atelier_agent_activer", "arguments": {"agent": "veille"}},
    )
    r = atelier.post(f"/v1/a-valider/{p.id}/decision", json={"decision": "accepter"}, headers=_cle(atelier))
    assert r.status_code == 403, "accepter est réservé à la personne"
    _session(atelier)
    r = atelier.post(f"/v1/a-valider/{p.id}/decision", json={"decision": "accepter"}, headers=INTERFACE)
    assert r.status_code == 200 and r.json()["statut"] == "fait"
    assert fausses_commandes == [("atelier_agent_activer", {"agent": "veille"})], "même chemin que depuis la fiche"


def test_accorder_un_secret_par_son_nom(atelier: TestClient, fausses_commandes) -> None:  # noqa: ANN001
    _session(atelier)
    corps = {"arguments": {"nom": "grist", "champ": "headers.Authorization", "secret": "grist_api_key", "schema": "Bearer"}}
    r = atelier.post("/v1/commandes/atelier_connecteur_accorder", json=corps, headers=INTERFACE)
    assert r.status_code == 200
    assert fausses_commandes[-1][1]["secret"] == "grist_api_key"


def _secret(dossier: Path, nom: str, mode: int = 0o600) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / nom).write_text(VALEUR, encoding="utf-8")
    os.chmod(dossier / nom, mode)


def test_la_liste_des_secrets_rend_des_noms_jamais_des_valeurs(atelier: TestClient) -> None:
    dossier = atelier.app.state.settings.secrets_dir
    _secret(dossier, "grist_api_key")
    _secret(dossier, "n8n_jeton", 0o644)
    _secret(dossier, "atelier_internal_secret")
    _secret(dossier, "atelier_lanceur_key")
    _secret(dossier, "atelier_cle_de_demain")
    _secret(dossier, "claude-env.sh")
    _secret(dossier, ".cache")
    _secret(dossier / "apps", "app_cle")

    assert atelier.get("/v1/secrets/noms").status_code == 401
    r = atelier.get("/v1/secrets/noms", headers=_cle(atelier))
    assert r.status_code == 403, "les agents (la clé) ne voient pas la carte des secrets"

    _session(atelier)
    r = atelier.get("/v1/secrets/noms", headers=INTERFACE)
    assert r.status_code == 200
    assert VALEUR not in r.text
    noms = {n["nom"]: n for n in r.json()["noms"]}
    assert set(noms) == {"grist_api_key", "n8n_jeton"}, "ni ceux de l'Atelier, ni les cachés, ni les sous-dossiers"
    assert noms["grist_api_key"]["protege"] is True
    if os.name == "posix":
        assert noms["n8n_jeton"]["protege"] is False


def test_un_lien_n_est_pas_propose(tmp_path: Path) -> None:
    _secret(tmp_path, "vrai")
    try:
        (tmp_path / "lien").symlink_to(tmp_path / "vrai")
    except OSError:
        pytest.skip("liens symboliques indisponibles ici")
    assert [n["nom"] for n in noms_des_secrets(tmp_path)] == ["vrai"]


def test_les_vraies_commandes_suivent_le_contrat(atelier: TestClient) -> None:
    """Quand la branche de K est fusionnée : mêmes noms, réservées, non exposées, mêmes arguments."""
    catalogue = atelier.app.state.commandes
    presentes = {nom: catalogue.commande(nom) for nom in CONTRAT}
    if not any(presentes.values()):
        pytest.skip("commandes de l'équipe K absentes (v2-creations pas encore fusionnée)")
    for nom, requis in CONTRAT.items():
        c = presentes[nom]
        assert c is not None, nom
        assert c.classe == RESERVEE and c.exposee_mcp is False, nom
        assert set(requis) <= set(c.schema.get("properties", {})), nom
        assert set(c.schema.get("required", [])) <= set(requis), f"{nom} demande un argument que l'écran n'envoie pas"
    schema = presentes["atelier_connecteur_accorder"].schema["properties"]
    assert set(schema.get("schema", {}).get("enum", [])) == {"Bearer", "Token", "Basic"}, "les préfixes de l'écran"
