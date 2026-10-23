"""La section « Secrets » de Réglages : écrire, changer et retirer un secret depuis l'interface, sans que la valeur ne ressorte.

Les valeurs sont fictives. Ce qu'on éprouve : réservé à la personne, jamais la valeur (réponse, journal, erreur), fichier fermé (0600),
refus de ce qui appartient à l'Atelier, et les connecteurs qui utilisent le secret reçoivent la nouvelle valeur.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.commandes.catalogue import FAIT, contexte_interface
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.db import connect

INTERFACE = {"X-Atelier-Interface": "1", "Sec-Fetch-Site": "same-origin"}
VALEUR = "jeton-fictif-0123456789abcdef-NE-DOIT-JAMAIS-SORTIR"
AUTRE = "jeton-fictif-fedcba9876543210-NOUVELLE-VALEUR"


def _cle(atelier: TestClient) -> dict[str, str]:
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def _session(atelier: TestClient) -> None:
    assert atelier.post("/v1/auth/cookie", headers=_cle(atelier)).status_code == 200


def _fichier(atelier: TestClient, nom: str) -> Path:
    return Path(atelier.app.state.settings.secrets_dir) / nom


def _pool(atelier: TestClient) -> dict[str, Any]:
    conn = connect(atelier.app.state.settings.gateway_db_path)
    try:
        return IntegratedMcpStore(conn).list_servers(mask=False)
    finally:
        conn.close()


def test_la_personne_cree_un_secret_ferme_qui_ne_ressort_jamais(atelier: TestClient) -> None:
    corps = {"valeur": VALEUR}
    assert atelier.put("/v1/secrets/grist_cle", json=corps).status_code == 401
    r = atelier.put("/v1/secrets/grist_cle", json=corps, headers=_cle(atelier))
    assert r.status_code == 403 and VALEUR not in r.text  # la clé du propriétaire, lue par les agents du pod, n'écrit aucun secret
    assert not _fichier(atelier, "grist_cle").exists()

    _session(atelier)
    r = atelier.put("/v1/secrets/grist_cle", json={"valeur": f"  {VALEUR}\n"}, headers=INTERFACE)
    assert r.status_code == 200 and r.json()["nouveau"] is True and r.json()["protege"] is True and VALEUR not in r.text
    fichier = _fichier(atelier, "grist_cle")
    assert fichier.read_text(encoding="utf-8") == VALEUR  # espaces et fin de ligne retirés
    if os.name == "posix":
        assert stat.S_IMODE(fichier.stat().st_mode) == 0o600
    liste = atelier.get("/v1/secrets", headers=INTERFACE)
    assert liste.status_code == 200 and VALEUR not in liste.text
    ligne = next(x for x in liste.json()["secrets"] if x["nom"] == "grist_cle")
    assert ligne["protege"] is True and ligne["utilise_par"] == [] and ligne["modifie"]
    journal = json.dumps(atelier.app.state.journal_unique.lire())
    assert VALEUR not in journal and "secret_ecrire" in journal  # qu'un secret a été écrit, jamais sa valeur


@pytest.mark.parametrize(
    "nom, valeur, statut, motif",
    [
        ("atelier_owner_key", VALEUR, 403, "réservé à l'Atelier"),
        ("atelier_inconnu_de_demain", VALEUR, 403, "réservé à l'Atelier"),
        ("llm_api_key", VALEUR, 403, "réservé à l'Atelier"),
        (".cache", VALEUR, 422, "Nom refusé"),
        ("a..b", VALEUR, 422, "Nom refusé"),
        ("github_token", VALEUR, 409, "section GitHub"),
        ("cle.avant", VALEUR, 422, "sauvegarde"),
        ("grist_cle", "   ", 422, "vide"),
        ("grist_cle", "ligne1\nligne2", 422, "une seule ligne"),
        ("grist_cle", "x" * 9000, 422, "trop longue"),
    ],
)
def test_les_refus_se_disent_sans_jamais_citer_la_valeur(atelier: TestClient, nom: str, valeur: str, statut: int, motif: str) -> None:
    _session(atelier)
    r = atelier.put(f"/v1/secrets/{nom}", json={"valeur": valeur}, headers=INTERFACE)
    assert r.status_code == statut and motif in r.text and valeur not in r.text
    fichier = _fichier(atelier, nom)  # ce que l'Atelier garde pour lui existe peut-être : il n'a surtout pas été écrasé
    assert not fichier.exists() or fichier.read_text(encoding="utf-8").strip() != valeur.strip()


def test_un_chemin_ne_sort_pas_du_dossier_des_secrets(atelier: TestClient) -> None:
    _session(atelier)
    for nom in ("..%2Fescape", "sous%2Fdossier"):
        r = atelier.put(f"/v1/secrets/{nom}", json={"valeur": VALEUR}, headers=INTERFACE)
        assert r.status_code in (404, 422), r.status_code
    assert not (Path(atelier.app.state.settings.secrets_dir).parent / "escape").exists()


def test_un_lien_n_est_pas_ecrit(atelier: TestClient, tmp_path: Path) -> None:
    _session(atelier)
    dossier = Path(atelier.app.state.settings.secrets_dir)
    dossier.mkdir(parents=True, exist_ok=True)
    cible = tmp_path / "ailleurs.txt"
    cible.write_text("intact", encoding="utf-8")
    try:
        (dossier / "lien").symlink_to(cible)
    except OSError:
        pytest.skip("pas de liens symboliques ici")
    r = atelier.put("/v1/secrets/lien", json={"valeur": VALEUR}, headers=INTERFACE)
    assert r.status_code == 409 and cible.read_text(encoding="utf-8") == "intact"


def _connecteur_accorde(atelier: TestClient, nom_secret: str) -> None:
    conn = connect(atelier.app.state.settings.gateway_db_path)
    try:
        IntegratedMcpStore(conn).upsert("grist", {"type": "http", "url": "http://grist.invalid/mcp"})
    finally:
        conn.close()
    arguments = {"nom": "grist", "champ": "headers.Authorization", "secret": nom_secret, "schema": "Bearer"}
    assert asyncio.run(atelier.app.state.commandes.executer("atelier_connecteur_accorder", arguments, contexte_interface())).statut == FAIT


def test_changer_un_secret_renouvelle_les_connecteurs_qui_l_utilisent_et_protege_leur_retrait(atelier: TestClient) -> None:
    _session(atelier)
    assert atelier.put("/v1/secrets/grist_cle", json={"valeur": VALEUR}, headers=INTERFACE).status_code == 200
    _connecteur_accorde(atelier, "grist_cle")
    assert _pool(atelier)["grist"]["headers"]["Authorization"] == f"Bearer {VALEUR}"
    ligne = next(x for x in atelier.get("/v1/secrets", headers=INTERFACE).json()["secrets"] if x["nom"] == "grist_cle")
    assert ligne["utilise_par"] == ["grist"]  # on voit qui s'en sert

    r = atelier.put("/v1/secrets/grist_cle", json={"valeur": AUTRE}, headers=INTERFACE)
    assert r.status_code == 200 and r.json()["nouveau"] is False and r.json()["renouveles"] == ["grist"]
    assert VALEUR not in r.text and AUTRE not in r.text
    assert _pool(atelier)["grist"]["headers"]["Authorization"] == f"Bearer {AUTRE}"  # une seule action
    journal = json.dumps(atelier.app.state.journal_unique.lire())
    assert VALEUR not in journal and AUTRE not in journal

    refus = atelier.delete("/v1/secrets/grist_cle", headers=INTERFACE)
    assert refus.status_code == 409 and "grist" in refus.text and _fichier(atelier, "grist_cle").is_file()  # un connecteur le garde


def test_retirer_un_secret_inutilise(atelier: TestClient) -> None:
    _session(atelier)
    assert atelier.delete("/v1/secrets/absent", headers=INTERFACE).status_code == 404
    atelier.put("/v1/secrets/provisoire", json={"valeur": VALEUR}, headers=INTERFACE)
    assert atelier.delete("/v1/secrets/provisoire", headers=_cle(atelier)).status_code == 403  # pas par la clé
    assert _fichier(atelier, "provisoire").is_file()
    r = atelier.delete("/v1/secrets/provisoire", headers=INTERFACE)
    assert r.status_code == 200 and r.json()["retire"] is True and not _fichier(atelier, "provisoire").exists()
    assert VALEUR not in json.dumps(atelier.app.state.journal_unique.lire())


def test_le_detail_est_reserve_a_la_personne(atelier: TestClient) -> None:
    assert atelier.get("/v1/secrets").status_code == 401
    assert atelier.get("/v1/secrets", headers=_cle(atelier)).status_code == 403
