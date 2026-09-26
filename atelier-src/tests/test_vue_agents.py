"""La vue Agents : les gardiens comme agents spécifiques, et toutes les tâches automatiques.

Couvre, de bout en bout et contre un vrai exécuteur servi en boucle locale :

- l'exécuteur se laisse couper, réactiver et lancer à chaud ; une coupure
  survit au redémarrage et n'est pas un homme mort ;
- `POST /pilotage` n'est ouvert qu'à qui porte le jeton, jamais à un
  navigateur (`Origin`), jamais sous un autre nom d'hôte ;
- l'Atelier assemble un agent par gardien (contrôles, alertes, constats,
  échéance, gestes du journal unique) et une seule liste d'automates ;
- couper un gardien et activer une tâche automatique sont réservés à la
  personne (J-b2) ; chaque geste va au journal unique, avec son acteur.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Iterator
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.automates import LecteurGardiens, assembler_les_gardiens, liste_des_automates
from mcp_gateway.atelier.commandes.journal import Evenement, Journal
from mcp_gateway.gardiens.api import creer_le_jeton, servir_en_arriere_plan
from mcp_gateway.gardiens.controles.commun import Contexte, ReponseHttp
from mcp_gateway.gardiens.declaration import lire
from mcp_gateway.gardiens.executeur import HOMME_MORT, Executeur
from mcp_gateway.gardiens.journal import Journal as JournalGardiens

INTERFACE = {"X-Atelier-Interface": "1", "Sec-Fetch-Site": "same-origin"}


class Horloge:
    def __init__(self, t: float = 1_790_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _sonde(ident: str, service: str = "wikichat", gardien: str = "sante") -> dict[str, Any]:
    return {
        "id": ident,
        "gardien": gardien,
        "portee": "pod",
        "quand": {"toutes_les_min": 1},
        "commande": ["interne", "sante.service"],
        "delai_s": 5,
        "params": {"service": service},
    }


CONTROLES = [
    _sonde("sante.wikichat"),
    _sonde("sante.relais", "relais"),
    {"id": "securite.bypass", "gardien": "securite", "portee": "pod", "quand": {"toutes_les_min": 5},
     "commande": ["interne", "securite.bypass"], "delai_s": 5},
    {"id": "entretien.automates", "gardien": "entretien", "portee": "pod", "quand": {"toutes_les_min": 15},
     "commande": ["interne", "entretien.automates"], "delai_s": 5},
]


def _contexte(tmp_path: Path) -> Contexte:
    work = tmp_path / "work"
    (work / ".secrets").mkdir(parents=True, exist_ok=True)
    ctx = Contexte(work=work, home=tmp_path / "home", env={}, ecoutes=lambda: [], processus=lambda: [])
    # Rien ne répond : les sondes de santé lèvent une alerte, sans réseau.
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(0, "", "refus")
    ctx.wikichat_dir = tmp_path / "wikichat"
    ctx.wikichat_dir.mkdir(exist_ok=True)
    (ctx.wikichat_dir / "triggers.json").write_text(json.dumps({"triggers": [
        {"id": "cron-routine-4h", "type": "cron", "enabled": True, "config": {"schedule": "0 */4 * * *"},
         "description": "Recherche paradoxes", "max_per_day": 6, "fire_count": 27,
         "last_fired": "2026-09-25T20:00:00Z", "action": {"type": "run_routine"}},
        {"id": "veille-coupee", "type": "cron", "enabled": False, "config": {"schedule": "0 8 * * *"},
         "description": "Veille coupée", "budget": {"jetons_par_jour": 1000}},
    ]}), encoding="utf-8")
    (ctx.wikichat_dir / "routines.json").write_text(json.dumps({"routines": [
        {"id": "paradox-research", "description": "Paradoxes", "steps": [{}, {}], "enabled": True},
    ]}), encoding="utf-8")
    return ctx


def _executeur(tmp_path: Path, horloge: Horloge | None = None, controles: list[dict] | None = None) -> Executeur:
    ctx = _contexte(tmp_path)
    chemin = tmp_path / "gardiens.json"
    chemin.write_text(json.dumps({"reglages": {}, "controles": controles or CONTROLES}), encoding="utf-8")
    decl = lire(chemin)
    ctx.reglages = decl.reglages
    etat = tmp_path / "work" / ".atelier-etat" / "gardiens"
    return Executeur(decl, ctx, JournalGardiens(etat / "journal"), etat, horloge=horloge or Horloge())


def _poster(port: int, corps: Any, entetes: dict[str, str] | None = None) -> tuple[int, Any]:
    requete = Request(
        f"http://127.0.0.1:{port}/pilotage",
        data=json.dumps(corps).encode(),
        method="POST",
        headers={"Content-Type": "application/json", **(entetes or {})},
    )
    try:
        with urlopen(requete, timeout=5) as r:
            return r.status, json.loads(r.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


# ── L'exécuteur, piloté à chaud ────────────────────────────────────────────


def test_couper_un_gardien_arrete_ses_controles_et_survit_au_redemarrage(tmp_path: Path) -> None:
    horloge = Horloge()
    ex = _executeur(tmp_path, horloge)
    horloge.t += 120
    assert {c.id for c in ex.echeances()} == {c["id"] for c in CONTROLES}

    assert sorted(ex.couper(gardien="sante", par="personne")) == ["sante.relais", "sante.wikichat"]
    assert {c.id for c in ex.echeances()} == {"securite.bypass", "entretien.automates"}
    etat = {c["id"]: c for c in ex.etat_des_controles()}
    assert etat["sante.wikichat"]["actif"] is False and etat["sante.wikichat"]["actif_declare"] is True
    assert etat["sante.wikichat"]["coupe"]["par"] == "personne"
    assert etat["sante.wikichat"]["prochaine"] is None

    # Longtemps après : un contrôle coupé n'est pas un homme mort.
    horloge.t += 3600
    assert "sante.wikichat" not in ex.verifier_homme_mort()

    # Redémarrage : la coupure tient.
    repris = _executeur(tmp_path, horloge)
    assert "sante.wikichat" in repris.coupes
    assert "sante.wikichat" not in {c.id for c in repris.echeances()}

    # Réactiver le fait repartir tout de suite.
    assert sorted(repris.reactiver(gardien="sante")) == ["sante.relais", "sante.wikichat"]
    assert {"sante.wikichat", "sante.relais"} <= {c.id for c in repris.echeances()}
    assert repris.reactiver(gardien="sante") == [], "réactiver deux fois ne fait rien la seconde"


def test_couper_ferme_l_homme_mort_du_controle(tmp_path: Path) -> None:
    horloge = Horloge()
    ex = _executeur(tmp_path, horloge)
    horloge.t += 3600
    assert "sante.wikichat" in ex.verifier_homme_mort()
    assert any(a["controle"] == HOMME_MORT and a["objet"] == "sante.wikichat" for a in ex.alertes_ouvertes())
    ex.couper(controle="sante.wikichat")
    assert not any(a["controle"] == HOMME_MORT and a["objet"] == "sante.wikichat" for a in ex.alertes_ouvertes())


def test_lancer_maintenant_avance_l_echeance_sans_executer_dans_l_appel(tmp_path: Path) -> None:
    horloge = Horloge()
    ex = _executeur(tmp_path, horloge)
    ex.tout_une_fois()
    assert ex.echeances() == []
    assert ex.lancer_maintenant(gardien="securite") == ["securite.bypass"]
    assert [c.id for c in ex.echeances()] == ["securite.bypass"]
    ex.couper(controle="sante.relais")
    assert ex.lancer_maintenant(controle="sante.relais") == [], "un contrôle coupé ne se lance pas"
    with pytest.raises(KeyError):
        ex.lancer_maintenant(controle="inconnu")


def test_un_controle_declare_inactif_ne_se_reactive_pas_d_ici(tmp_path: Path) -> None:
    ex = _executeur(tmp_path, controles=[{**_sonde("sante.wikichat"), "actif": False}])
    assert ex.couper(controle="sante.wikichat") == []
    assert ex.reactiver(controle="sante.wikichat") == []
    assert ex.etat_des_controles()[0]["actif"] is False


# ── Le pilotage par l'API locale ───────────────────────────────────────────


@pytest.fixture()
def executeur_servi(tmp_path: Path) -> Iterator[tuple[Executeur, int, str]]:
    ex = _executeur(tmp_path)
    ex.tout_une_fois()
    jeton = creer_le_jeton(ex.dossier_etat)
    srv, _ = servir_en_arriere_plan(ex, 0, jeton)
    try:
        yield ex, srv.server_address[1], jeton
    finally:
        srv.shutdown()
        srv.server_close()


def test_le_pilotage_demande_le_jeton_et_refuse_un_navigateur(executeur_servi: tuple[Executeur, int, str]) -> None:
    ex, port, jeton = executeur_servi
    porteur = {"Authorization": f"Bearer {jeton}"}
    corps = {"action": "couper", "gardien": "securite", "par": "personne"}

    assert _poster(port, corps)[0] == 401
    assert _poster(port, corps, {"Authorization": "Bearer faux"})[0] == 401
    assert _poster(port, corps, {**porteur, "Origin": "https://voisin.example"})[0] == 403
    assert _poster(port, corps, {**porteur, "Host": "piege.example"})[0] == 403
    assert "securite.bypass" not in ex.coupes, "aucun refus n'a rien coupé"

    statut, reponse = _poster(port, corps, porteur)
    assert statut == 200 and reponse["controles"] == ["securite.bypass"]
    assert "securite.bypass" in ex.coupes
    assert _poster(port, {"action": "detruire", "gardien": "securite"}, porteur)[0] == 400
    assert _poster(port, {"action": "lancer", "gardien": "inconnu"}, porteur)[0] == 404


def test_sans_jeton_le_pilotage_est_ferme_et_la_lecture_reste(tmp_path: Path) -> None:
    ex = _executeur(tmp_path)
    srv, _ = servir_en_arriere_plan(ex, 0)
    port = srv.server_address[1]
    try:
        assert _poster(port, {"action": "lancer", "gardien": "sante"}, {"Authorization": "Bearer x"})[0] == 503
        with urlopen(f"http://127.0.0.1:{port}/sante", timeout=5) as r:
            assert r.status == 200
        requete = Request(f"http://127.0.0.1:{port}/etat", data=b"{}", method="POST")
        with pytest.raises(HTTPError) as exc:
            urlopen(requete, timeout=5)
        assert exc.value.code == 405, "les autres POST restent refusés"
    finally:
        srv.shutdown()
        srv.server_close()


# ── L'Atelier : un agent par gardien, une seule liste d'automates ─────────


def test_un_agent_par_gardien_avec_alertes_constats_et_gestes(tmp_path: Path) -> None:
    ex = _executeur(tmp_path)
    ex.tout_une_fois()
    journal = Journal(tmp_path / "journal-unique")
    journal.ecrire(Evenement(
        source="geste", acteur="gardiens", objet={"type": "pod", "id": "relancer_wikichat"},
        action={"commande": "relancer_wikichat", "origine": "sante", "avant": {"etat": "alerte"},
                "apres": {"etat": "ok"}},
        resultat="fait",
    ))
    from mcp_gateway.atelier.automates import _gestes_des_gardiens

    gardiens = assembler_les_gardiens(
        {"controles": ex.etat_des_controles(), "alertes_ouvertes": ex.alertes_ouvertes()},
        ex.journal.recentes(500),
        _gestes_des_gardiens(journal),
    )
    par_id = {g["id"]: g for g in gardiens}
    assert [g["id"] for g in gardiens] == ["sante", "securite", "entretien"], "l'ordre des gardiens"
    sante = par_id["sante"]
    assert sante["etat"] == "alerte"
    assert {a["empreinte"] for a in sante["alertes"]} >= {"sante.wikichat:ne-repond-pas"}
    assert any(c["controle"] == "sante.wikichat" for c in sante["constats"])
    assert sante["prochaine"] and sante["derniere"]
    assert sante["gestes"][0]["nom"] == "relancer_wikichat"
    assert par_id["securite"]["gestes"] == [], "un geste ne va qu'à son gardien"
    assert sante["actions"] == {"lancer": True, "couper": True, "reactiver": False}

    ex.couper(gardien="sante")
    sante = {g["id"]: g for g in assembler_les_gardiens(
        {"controles": ex.etat_des_controles(), "alertes_ouvertes": []}, [], [])}["sante"]
    assert sante["etat"] == "coupe"
    assert sante["actions"] == {"lancer": False, "couper": False, "reactiver": True}


def test_la_liste_des_automates_reunit_gardiens_triggers_routines(tmp_path: Path, executeur_servi) -> None:  # noqa: ANN001
    ex, port, _ = executeur_servi
    lecteur = LecteurGardiens(f"http://127.0.0.1:{port}", ex.dossier_etat)
    pilote = {
        "agents": [{"id": "veille-depots", "name": "Veille dépôts", "enabled": True, "lastFired": None,
                    "next": "demain 8h", "cron": "0 8 * * *", "trigger": {"cap": "24"}}],
        "system_agents": [{"id": "evt-wake-any", "name": "Réveil sur mention", "enabled": False, "type": "event"}],
    }
    liste = asyncio.run(liste_des_automates(lecteur, None, None, pilote))
    par_id = {a["id"]: a for a in liste["automates"]}
    assert liste["sources"] == {"gardiens": True, "inventaire": True, "pilote": True}
    assert {"gardien.sante", "gardien.securite", "gardien.entretien"} <= set(par_id)
    assert par_id["gardien.sante"]["plafond"] == {"jetons": 0}

    routine = par_id["trigger.cron-routine-4h"]
    assert routine["plafond"]["par_jour"] == 6 and routine["derniere"] == "2026-09-25T20:00:00Z"
    assert routine["prochaine"], "la prochaine exécution d'un cron est calculée"
    assert routine["etat"] == "sans_declaration", "actif sans budget : l'inventaire le dit"
    assert routine["gestes"] == ["lancer", "couper"]

    assert par_id["trigger.veille-coupee"]["etat"] == "coupe"
    assert par_id["trigger.veille-coupee"]["gestes"] == ["activer"]
    assert par_id["trigger.veille-depots"]["plafond"]["par_jour"] == 24
    assert par_id["trigger.veille-depots"]["prochaine_texte"] == "demain 8h"
    assert par_id["trigger.evt-wake-any"]["etat"] == "coupe"
    assert par_id["routine.paradox-research"]["genre"] == "routine"


def test_gardiens_absents_la_vue_le_dit_sans_casser(tmp_path: Path) -> None:
    lecteur = LecteurGardiens("http://127.0.0.1:9", tmp_path, delai=0.5)
    liste = asyncio.run(liste_des_automates(lecteur, None, None, None, "pilote absent"))
    assert liste["automates"] == []
    assert liste["sources"]["gardiens"] is False
    assert any("ne répondent pas" in n for n in liste["notes"]) and "pilote absent" in liste["notes"]


# ── Les routes de l'Atelier et les droits de chacun ───────────────────────


@pytest.fixture()
def atelier_et_gardiens(atelier: TestClient, executeur_servi) -> Iterator[tuple[TestClient, Executeur]]:  # noqa: ANN001
    ex, port, _ = executeur_servi
    atelier.app.state.lecteur_gardiens = LecteurGardiens(f"http://127.0.0.1:{port}", ex.dossier_etat)
    yield atelier, ex


def _cle(atelier: TestClient) -> dict[str, str]:
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def _ouvrir_la_session(atelier: TestClient) -> None:
    assert atelier.post("/v1/auth/cookie", headers=_cle(atelier)).status_code == 200


def _gestes_au_journal(atelier: TestClient) -> list[dict[str, Any]]:
    return atelier.get("/v1/journal?source=automate", headers=_cle(atelier)).json()["evenements"]


def test_les_routes_lisent_les_gardiens(atelier_et_gardiens) -> None:  # noqa: ANN001
    atelier, _ = atelier_et_gardiens
    assert atelier.get("/v1/gardiens").status_code == 401
    vue = atelier.get("/v1/gardiens", headers=_cle(atelier)).json()
    assert vue["joignable"] and [g["id"] for g in vue["gardiens"]] == ["sante", "securite", "entretien"]
    liste = atelier.get("/v1/automates", headers=_cle(atelier)).json()
    assert any(a["id"] == "gardien.sante" for a in liste["automates"])
    assert any("mode factice" in n for n in liste["notes"])


def test_couper_un_gardien_est_reserve_a_la_personne(atelier_et_gardiens) -> None:  # noqa: ANN001
    atelier, ex = atelier_et_gardiens
    corps = {"id": "gardien.securite", "geste": "couper"}
    r = atelier.post("/v1/automates/action", json=corps, headers=_cle(atelier))
    assert r.status_code == 403 and "réservé à la personne" in r.json()["detail"]
    assert "securite.bypass" not in ex.coupes

    _ouvrir_la_session(atelier)
    r = atelier.post("/v1/automates/action", json=corps, headers=INTERFACE)
    assert r.status_code == 200 and r.json()["controles"] == ["securite.bypass"]
    assert "securite.bypass" in ex.coupes
    vue = atelier.get("/v1/gardiens", headers=INTERFACE).json()
    assert {g["id"]: g for g in vue["gardiens"]}["securite"]["etat"] == "coupe"

    # Un agent (la clé) peut remettre le filet, et lancer un contrôle.
    r = atelier.post("/v1/automates/action", json={"id": "gardien.securite", "geste": "reactiver"}, headers=_cle(atelier))
    assert r.status_code == 200 and "securite.bypass" not in ex.coupes
    r = atelier.post("/v1/automates/action", json={"id": "controle.sante.relais", "geste": "lancer"}, headers=_cle(atelier))
    assert r.status_code == 200 and r.json()["controles"] == ["sante.relais"]

    gestes = _gestes_au_journal(atelier)
    resume = [(e["acteur"], e["action"]["commande"], e["resultat"]) for e in reversed(gestes)]
    assert resume == [
        ("cle-proprietaire", "automate_couper", "refus"),
        ("personne", "automate_couper", "fait"),
        ("cle-proprietaire", "automate_reactiver", "fait"),
        ("cle-proprietaire", "automate_lancer", "fait"),
    ]


def test_activer_une_tache_automatique_est_reserve_a_la_personne(atelier_et_gardiens) -> None:  # noqa: ANN001
    atelier, _ = atelier_et_gardiens
    r = atelier.post("/v1/automates/action", json={"id": "trigger.cron-routine-4h", "geste": "activer"}, headers=_cle(atelier))
    assert r.status_code == 403 and "réservé à la personne" in r.json()["detail"]
    # La personne passe la règle ; c'est le pilote, absent en mode factice, qui manque.
    _ouvrir_la_session(atelier)
    r = atelier.post("/v1/automates/action", json={"id": "trigger.cron-routine-4h", "geste": "activer"}, headers=INTERFACE)
    assert r.status_code == 503
    assert atelier.post("/v1/automates/action", json={"id": "trigger.x", "geste": "detruire"}, headers=INTERFACE).status_code == 422
    assert atelier.post("/v1/automates/action", json={"id": "sansgenre", "geste": "lancer"}, headers=INTERFACE).status_code == 422


def test_executeur_arrete_la_vue_et_le_pilotage_le_disent(atelier: TestClient, tmp_path: Path) -> None:
    atelier.app.state.lecteur_gardiens = LecteurGardiens("http://127.0.0.1:9", tmp_path, delai=0.5)
    _ouvrir_la_session(atelier)
    r = atelier.post("/v1/automates/action", json={"id": "gardien.sante", "geste": "lancer"}, headers=INTERFACE)
    assert r.status_code == 503
    assert atelier.get("/v1/gardiens", headers=INTERFACE).json()["joignable"] is False
