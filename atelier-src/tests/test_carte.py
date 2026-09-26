"""La carte de l'Atelier : assemblage, wikichat absent, profils, budget, invalidation.

Contrat : `docs/vision/architecture-transverse.md` §1.3, et pour la couche
wikichat `docs/cartographie-contrat.md` de wikichat. Les deux sources HTTP
(wikichat sur `/api/cartographie`, les gardiens sur `/alertes` et
`/automates`) sont de vrais serveurs HTTP locaux, servis par le test : la carte
les lit par le même chemin qu'en service. Tout le reste est l'Atelier de test :
ses projets, ses conversations, ses créations, sa file « À valider », son
catalogue de commandes.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.carte import (
    BUDGET_SYNTHETIQUE,
    CARACTERES_PAR_UNITE,
    PLAFOND_UNITES,
    Carte,
    Couche,
    Sources,
    assembler,
    unites_estimees,
    vue_synthetique,
)
from mcp_gateway.atelier.commandes import profils
from mcp_gateway.atelier.config import AtelierSettings

ATELIER = "https://testserver"


# ── Deux faux voisins, de vrais serveurs HTTP ─────────────────────────────


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Voisin:
    """Un serveur HTTP local qui rend, par chemin, ce qu'on lui a donné."""

    def __init__(self) -> None:
        self.reponses: dict[str, tuple[int, Any]] = {}
        self.appels: list[str] = []
        voisin = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                chemin = self.path.split("?", 1)[0]
                voisin.appels.append(chemin)
                statut, corps = voisin.reponses.get(chemin, (404, {"erreur": "inconnu"}))
                donnees = json.dumps(corps).encode("utf-8")
                self.send_response(statut)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def log_message(self, *args: Any) -> None:
                return

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.port = self.serveur.server_address[1]
        self.fil = threading.Thread(target=self.serveur.serve_forever, daemon=True)
        self.fil.start()

    def fermer(self) -> None:
        self.serveur.shutdown()
        self.serveur.server_close()


def _noeud_wikichat(ident: str, **champs: Any) -> dict[str, Any]:
    noeud: dict[str, Any] = {
        "id": ident, "nom": ident, "titre": None, "description": None, "chemin": f"/p/{ident}",
        "origine": ["registre"], "statut": "discovered", "cycle_de_vie": None, "but": None, "axes": [],
        "pile": [], "github": None, "instantane": None, "sante": None, "etat": None, "decisions": 0,
        "cloture": None, "connecteurs": None, "atelier": None,
    }
    noeud.update(champs)
    return noeud


def cartographie_du_contrat() -> dict[str, Any]:
    """L'exemple du contrat de wikichat (§5), plus un dossier qui n'est pas un projet de l'Atelier."""
    return {
        "version": 1,
        "calcule_le": "2026-09-25T20:14:03.512Z",
        "sources": {"registre": None, "clustering": "2026-09-21", "audits": None,
                    "racine_projets_atelier": "/home/onyxia/work/projects"},
        "noeuds": [
            _noeud_wikichat(
                "lecteur-grist", titre="Lecteur Grist", connecteurs=["grist", "wikichat"],
                sante={"score": 78, "le": "2026-09-25T02:00:03.100Z", "alertes": ["no LICENSE"]},
                etat={"fichier": "ETAT.md", "modifie": "2026-09-24T16:40:00.000Z",
                      "tete": ["Lot courant : L6."], "a_decider": 2},
            ),
            _noeud_wikichat("grist-appstore", connecteurs=["grist"]),
            _noeud_wikichat("onyxia"),
        ],
        "aretes": [
            {"id": "relation:lecteur-grist>grist-appstore:provides-to", "type": "relation", "de": "lecteur-grist",
             "vers": "grist-appstore", "oriente": True, "sous_type": "provides-to", "note": "widget",
             "source": "set_project_meta"},
            {"id": "meme_connecteur:grist-appstore~lecteur-grist", "type": "meme_connecteur",
             "de": "grist-appstore", "vers": "lecteur-grist", "oriente": False, "connecteurs": ["grist"],
             "source": ".mcp.json"},
        ],
        "groupes": [{"id": "clustering-1", "type": "clustering", "membres": ["grist-appstore", "lecteur-grist"]}],
        "limites": {"absents_exclus": 0, "relations_sans_cible": 0, "connecteurs_communs": ["atelier", "wikichat"]},
    }


def reponses_des_gardiens(voisin: Voisin) -> None:
    voisin.reponses["/alertes"] = (200, {"alertes": [
        {"empreinte": "securite.bypass:42", "controle": "securite.bypass", "gardien": "securite",
         "portee": "pod", "objet": "pid 42", "resume": "session claude en bypassPermissions sans fiche",
         "preuve": "cwd /home/onyxia/work/projects/lecteur-grist ; lancé par pid 1", "niveau": "alerte",
         "depuis": "2026-09-25T21:33:24Z", "vu_le": "2026-09-26T04:55:01Z", "compte": 3, "ouverte": True},
        {"empreinte": "entretien.automates:t1", "controle": "entretien.automates", "gardien": "entretien",
         "portee": "pod", "objet": "wikichat.trigger.t1", "resume": "trigger actif sans budget déclaré",
         "preuve": "", "niveau": "attention", "depuis": "2026-09-25T21:33:24Z", "compte": 1, "ouverte": True},
    ]})
    voisin.reponses["/automates"] = (200, {"controle": "entretien.automates", "lu_a": "2026-09-26T04:55:01Z",
                                           "par_etat": {"actif": 1, "sans_declaration": 1}, "automates": [
        {"id": "gardiens.sante.atelier", "genre": "controle", "proprietaire": "gardiens", "etat": "actif",
         "titre": "", "budget": None},
        {"id": "wikichat.trigger.t1", "genre": "trigger", "proprietaire": "wikichat", "etat": "sans_declaration",
         "titre": "Résume le travail des projets", "budget": None, "lancements": 48},
    ]})


# ── L'Atelier de test ──────────────────────────────────────────────────


@pytest.fixture()
def voisins(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Voisin, Voisin]]:
    wikichat, gardiens = Voisin(), Voisin()
    monkeypatch.setenv("ATELIER_GARDIENS_PORT", str(gardiens.port))
    monkeypatch.delenv("ATELIER_GARDIENS_URL", raising=False)
    try:
        yield wikichat, gardiens
    finally:
        wikichat.fermer()
        gardiens.fermer()


def _atelier(tmp_path: Path, wikichat_port: int) -> TestClient:
    settings = AtelierSettings(work_dir=tmp_path / "work", public_url=ATELIER,
                               wikichat_url=f"http://127.0.0.1:{wikichat_port}/sse")
    settings.relais_llm_port = _port_libre()
    return TestClient(build_app(settings=settings, use_fake=True), base_url=ATELIER)


@pytest.fixture()
def atelier(tmp_path: Path, voisins: tuple[Voisin, Voisin]) -> Iterator[TestClient]:
    with _atelier(tmp_path, voisins[0].port) as client:
        yield client


@pytest.fixture()
def atelier_sans_wikichat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Personne n'écoute sur ces deux ports : ni wikichat, ni les gardiens.
    monkeypatch.setenv("ATELIER_GARDIENS_PORT", str(_port_libre()))
    monkeypatch.delenv("ATELIER_GARDIENS_URL", raising=False)
    with _atelier(tmp_path, _port_libre()) as client:
        yield client


def porteur(client: TestClient) -> dict[str, str]:
    cle = client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def commande(client: TestClient, nom: str, **arguments: Any) -> dict[str, Any]:
    r = client.post(f"/v1/commandes/{nom}", json={"arguments": arguments}, headers=porteur(client))
    assert r.status_code == 200, r.text
    return r.json()


def peupler(client: TestClient) -> str:
    """Un projet cadré avec ses connecteurs choisis, une création, une conversation, une proposition."""
    commande(client, "atelier_projet_creer", titre="Lecteur Grist", slug="lecteur-grist")
    settings = client.app.state.settings
    racine = settings.projects_dir / "lecteur-grist"
    (racine / ".atelier" / "connecteurs-herites").unlink(missing_ok=True)
    (racine / ".atelier" / "connecteurs-choisis.json").write_text(
        json.dumps({"mcpServers": {"grist": {"enabled": True}, "n8n": {"enabled": False}}}), encoding="utf-8"
    )
    if not (racine / ".mcp.json").is_file():
        (racine / ".mcp.json").write_text('{"mcpServers": {}}', encoding="utf-8")
    page = racine / "artifacts" / "lecteur"
    page.mkdir(parents=True)
    (page / "index.html").write_text("<h1>lecteur</h1>", encoding="utf-8")
    r = client.post("/v1/sessions", json={"slug": "lecteur-grist", "kind": "code"}, headers=porteur(client))
    assert r.status_code == 200, r.text
    client.app.state.a_valider.deposer("gardien", "Couper le trigger t1", "sans budget", acteur="gardien:entretien",
                                       projet="lecteur-grist")
    # Le pool de ce test : l'Atelier factice n'a aucun connecteur en base.
    client.app.state.carte.sources.pool = lambda: ["grist", "n8n", "qgis"]
    client.app.state.carte.invalider("test")
    return r.json()["session_id"]


def carte_complete(client: TestClient, **entetes: str) -> dict[str, Any]:
    r = client.get("/v1/carte?forme=complete&rafraichir=true", headers={**porteur(client), **entetes})
    assert r.status_code == 200, r.text
    return r.json()


# ── Assemblage ─────────────────────────────────────────────────────────


def test_l_assemblage_joint_par_le_slug_et_remplit_le_champ_atelier(
    atelier: TestClient, voisins: tuple[Voisin, Voisin]
) -> None:
    wikichat, gardiens = voisins
    wikichat.reponses["/api/cartographie"] = (200, cartographie_du_contrat())
    reponses_des_gardiens(gardiens)
    conversation = peupler(atelier)

    carte = carte_complete(atelier)
    assert wikichat.appels == ["/api/cartographie"]
    assert carte["version"] == 1
    assert carte["sources"]["wikichat"]["etat"] == "ok"
    assert carte["sources"]["gardiens"]["etat"] == "ok"
    noeuds = {n["id"]: n for n in carte["noeuds"]}

    # Joint par le slug : un seul nœud, les champs de wikichat et ceux de l'Atelier.
    lecteur = noeuds["lecteur-grist"]
    assert [n["id"] for n in carte["noeuds"]].count("lecteur-grist") == 1
    assert lecteur["type"] == "projet"
    assert lecteur["sante"]["score"] == 78 and lecteur["etat"]["a_decider"] == 2
    at = lecteur["atelier"]
    assert at["projet_json"] == "valide" and at["gabarit"] == "vide"
    assert at["connecteurs"] == {"herite_du_pool": False, "choisis": ["grist"]}
    assert at["creations"]["total"] == 1
    assert at["conversations"]["total"] == 1
    assert at["a_valider"] == 1 and at["alertes"] == 1
    assert at["actif"] is True

    # Un nœud de wikichat qui n'est pas un projet de l'Atelier garde `atelier: null`.
    assert noeuds["grist-appstore"]["atelier"] is None
    assert noeuds["onyxia"]["atelier"] is None
    # Un projet de l'Atelier inconnu de wikichat entre avec les champs du contrat, vides.
    memoire = noeuds[atelier.app.state.settings.assistant_slug]
    assert memoire["origine"] == ["atelier"] and memoire["atelier"]["systeme"] is True

    # Les liens de wikichat restent, ceux de l'Atelier s'ajoutent.
    aretes = {a["id"]: a for a in carte["aretes"]}
    assert "relation:lecteur-grist>grist-appstore:provides-to" in aretes
    assert aretes["sert:lecteur-grist/lecteur"]["de"] == "creation:lecteur-grist/lecteur"
    assert aretes[f"travaille_sur:{conversation}"]["vers"] == "lecteur-grist"
    assert aretes["utilise:lecteur-grist>grist"]["source"] == "connecteurs-choisis"
    assert "utilise:lecteur-grist>n8n" not in aretes, "un connecteur décoché n'est pas utilisé"
    # Le lien de wikichat reste (le lecteur a choisi grist) ; aucun lien ne naît
    # de l'héritage du pool : le dossier de l'Assistant hérite de grist sans
    # l'avoir choisi, il ne partage donc rien avec le lecteur (essais du 26/09).
    partages = {a["id"]: a for a in carte["aretes"] if a["type"] == "meme_connecteur"}
    assert set(partages) == {"meme_connecteur:grist-appstore~lecteur-grist"}
    assert partages["meme_connecteur:grist-appstore~lecteur-grist"]["source"] == ".mcp.json"
    assert partages["meme_connecteur:grist-appstore~lecteur-grist"]["connecteurs"] == ["grist"]
    # Règle du contrat : toute arête relie deux nœuds de la carte.
    ids = set(noeuds)
    for a in carte["aretes"]:
        assert a["de"] in ids and a["vers"] in ids, a

    # L'alerte est rattachée au projet qu'elle vise ; la tâche sans budget à son automate.
    visees = {a["empreinte"]: a["vise"] for a in carte["alertes"]}
    assert visees == {"securite.bypass:42": "lecteur-grist", "entretien.automates:t1": "automate:wikichat.trigger.t1"}
    assert "preuve" not in carte["alertes"][0], "la preuve reste chez les gardiens"
    assert noeuds["automate:wikichat.trigger.t1"]["etat"] == "sans_declaration"
    assert [p["titre"] for p in carte["a_valider"]] == ["Couper le trigger t1"]


def test_la_vue_synthetique_et_la_vue_projet_portent_les_deux_couches(
    atelier: TestClient, voisins: tuple[Voisin, Voisin]
) -> None:
    wikichat, gardiens = voisins
    wikichat.reponses["/api/cartographie"] = (200, cartographie_du_contrat())
    reponses_des_gardiens(gardiens)
    peupler(atelier)

    r = atelier.get("/v1/carte", headers=porteur(atelier))
    assert r.status_code == 200, r.text
    synthese = r.json()
    assert synthese["forme"] == "synthetique"
    texte = synthese["texte"]
    ligne = next(l for l in texte.splitlines() if l.startswith("- lecteur-grist"))
    assert "1 conv." in ligne and "1 création |" in ligne and "connecteurs : grist" in ligne
    assert "ETAT.md : 2 à décider" in ligne and "grist-appstore (relation)" in ligne
    assert "Couche projets (wikichat) : à jour" in texte
    assert "Tâches wikichat sans budget : t1" in texte
    assert "Alerte [securite] pid 42" in texte
    assert synthese["taille"]["unites_estimees"] == unites_estimees(texte)

    r = atelier.get("/v1/carte?projet=lecteur-grist", headers=porteur(atelier))
    assert r.status_code == 200, r.text
    detail = r.json()
    assert detail["forme"] == "projet" and detail["noeud"]["atelier"]["actif"] is True
    assert detail["liens"][0] == {"projet": "grist-appstore", "type": "relation", "sous_type": "provides-to",
                                  "sens": "vers"}
    assert [c["nom"] for c in detail["creations"]] == ["lecteur"]
    assert len(detail["alertes"]) == 1 and len(detail["a_valider"]) == 1

    r = atelier.get("/v1/carte?projet=inconnu", headers=porteur(atelier))
    assert r.status_code == 422


# ── wikichat absent ou hors contrat ────────────────────────────────────


def test_sans_wikichat_la_carte_reste_servie_et_le_dit(atelier_sans_wikichat: TestClient) -> None:
    client = atelier_sans_wikichat
    peupler(client)
    carte = carte_complete(client)
    assert carte["sources"]["wikichat"]["etat"] == "absent"
    assert carte["sources"]["gardiens"]["etat"] == "absent"
    lecteur = next(n for n in carte["noeuds"] if n["id"] == "lecteur-grist")
    assert lecteur["origine"] == ["atelier"] and lecteur["statut"] == "atelier"
    assert lecteur["atelier"]["creations"]["total"] == 1
    assert carte["resume"]["alertes"] is None, "inconnu n'est pas zéro"

    texte = client.get("/v1/carte", headers=porteur(client)).json()["texte"]
    assert "absente, wikichat ne répond pas" in texte
    assert "Alertes : inconnues (gardiens absents)" in texte
    assert "sans ETAT.md" not in texte, "sans wikichat, on ne sait pas : on ne dit pas le faux"
    assert "- lecteur-grist" in texte


def test_une_couche_wikichat_hors_contrat_est_ecartee(atelier: TestClient, voisins: tuple[Voisin, Voisin]) -> None:
    wikichat, _ = voisins
    graphe = cartographie_du_contrat()
    graphe["version"] = 2
    wikichat.reponses["/api/cartographie"] = (200, graphe)
    peupler(atelier)
    carte = carte_complete(atelier)
    assert carte["sources"]["wikichat"]["etat"] == "erreur"
    assert "version" in carte["sources"]["wikichat"]["detail"]
    assert "grist-appstore" not in {n["id"] for n in carte["noeuds"]}

    wikichat.reponses["/api/cartographie"] = (500, {"error": "boom"})
    carte = carte_complete(atelier)
    assert carte["sources"]["wikichat"] == {"etat": "erreur", "detail": "ValueError: HTTP 500"}


# ── Profils ────────────────────────────────────────────────────────────


def test_un_agent_code_n_a_pas_la_carte(atelier: TestClient, voisins: tuple[Voisin, Voisin]) -> None:
    wikichat, _ = voisins
    wikichat.reponses["/api/cartographie"] = (200, cartographie_du_contrat())
    conversation = peupler(atelier)
    entetes = {**porteur(atelier), "X-Atelier-Conversation": conversation}

    r = atelier.get("/v1/carte", headers=entetes)
    assert r.status_code == 403, r.text
    assert "profil code" in r.text
    # Annoncer « assistant » n'élargit pas une conversation de code.
    r = atelier.get("/v1/carte", headers={**entetes, "X-Atelier-Profil": "assistant"})
    assert r.status_code == 403
    r = atelier.post("/v1/commandes/atelier_carte", json={"arguments": {}}, headers=entetes)
    assert r.status_code == 403
    noms = {c["nom"] for c in atelier.get("/v1/commandes", headers=entetes).json()["commandes"]}
    assert "atelier_carte" not in noms
    # Rien n'a été calculé pour lui.
    assert wikichat.appels == []

    # Par la face MCP du catalogue (celle de la porte /mcp) : ni listée, ni appelable.
    catalogue = atelier.app.state.commandes
    jeton = profils.PROFIL_APPELANT.set(profils.PROFIL_CODE)
    try:
        assert "atelier_carte" not in {d["name"] for d in catalogue.definitions()}
        reponse = asyncio.run(catalogue.appeler("atelier_carte", {}))
    finally:
        profils.PROFIL_APPELANT.reset(jeton)
    assert reponse is not None and reponse["isError"] is True


def test_l_assistant_a_la_carte(atelier: TestClient, voisins: tuple[Voisin, Voisin]) -> None:
    wikichat, _ = voisins
    wikichat.reponses["/api/cartographie"] = (200, cartographie_du_contrat())
    assistant = atelier.app.state.store.create(kind="assistant").session_id
    entetes = {**porteur(atelier), "X-Atelier-Conversation": assistant, "X-Atelier-Profil": "assistant"}
    r = atelier.get("/v1/carte", headers=entetes)
    assert r.status_code == 200, r.text
    assert r.json()["forme"] == "synthetique"
    noms = {c["nom"] for c in atelier.get("/v1/commandes", headers=entetes).json()["commandes"]}
    assert "atelier_carte" in noms
    declaration = next(c for c in atelier.get("/v1/commandes", headers=entetes).json()["commandes"]
                       if c["nom"] == "atelier_carte")
    assert declaration["classe"] == "lecture" and declaration["objet"] == "carte"
    # Et elle se trouve par l'intention.
    from mcp_gateway.tool_search import MOTS_CLES_PAR_OUTIL
    assert "quoi de neuf" in MOTS_CLES_PAR_OUTIL["atelier_carte"]


# ── Budget de la forme synthétique ─────────────────────────────────────


def _couche_realiste(n_projets: int, *, tous_actifs: bool = False) -> tuple[Couche, dict[str, Any]]:
    """Une couche à la mesure du pod (26 projets, 38 tâches, 18 alertes), en plus bavard."""
    import time

    maintenant = time.time()
    pool = ["Onyxia", "blender", "chrome", "datagouv", "filesystem", "grist", "n8n", "qgis", "voice", "webtools",
            "wikichat"]
    projets, creations, conversations, noeuds_wk, aretes_wk = [], [], [], [], []
    for i in range(n_projets):
        slug = f"projet-exemple-numero-{i:03d}"
        actif = tous_actifs or i % 3 == 0
        maj = maintenant - (3600 * (i + 1) if actif else 40 * 86400)
        date = datetime_iso(maj)
        projets.append({
            "slug": slug, "titre": f"Un titre de projet assez long pour la ligne {i}", "kind": "code",
            "range": i % 13 == 12, "chemin": f"/p/{slug}", "cree_le": date, "maj": date,
            "structure": {"projet_json": "valide", "gabarit": "application", "deploiement": None,
                          "vues_epinglees": 0, "description": None},
            "connecteurs": {"herite_du_pool": i % 2 == 0, "choisis": pool[: (i % 7) + 1]},
        })
        for k in range(i % 4):
            creations.append({"projet": slug, "nom": f"creation-{k}", "titre": "Page", "mode": "serveur",
                              "etat": "pret" if k == 0 else "arrete"})
        for k in range(i % 5):
            conversations.append({"id": f"{slug}-c{k}", "projet": slug, "kind": "code", "titre": "Travail",
                                  "etat": "idle", "en_cours": k == 0 and actif, "maj": date, "tours": 3})
        noeuds_wk.append(_noeud_wikichat(slug, etat={"fichier": "ETAT.md", "modifie": date, "tete": [],
                                                    "a_decider": i % 3}))
    for i in range(13):
        noeuds_wk.append(_noeud_wikichat(f"dossier-hors-atelier-{i}"))
    ids = [n["id"] for n in noeuds_wk]
    for i in range(len(ids)):
        for j in range(i + 1, min(i + 8, len(ids))):
            aretes_wk.append({"id": f"proximite:{ids[i]}~{ids[j]}", "type": "proximite", "de": ids[i],
                              "vers": ids[j], "oriente": False, "poids": 0.3, "dependances_communes": [],
                              "source": "clustering:2026-09-26"})
    automates = [{"id": f"wikichat.trigger.t{i}", "genre": "trigger", "etat": ("actif", "sans_declaration", "coupe")[i % 3],
                  "titre": "Une tâche automatique"} for i in range(38)]
    alertes = [{"empreinte": f"e{i}", "gardien": "entretien" if i > 1 else "securite", "controle": "c",
                "niveau": "alerte" if i < 2 else "attention", "objet": f"wikichat.trigger.t{i}",
                "resume": "écoute sur toutes les interfaces, hors de la liste déclarée", "ouverte": True}
               for i in range(18)]
    a_valider = [{"id": f"p{i}", "source": "gardien", "titre": f"Proposition numéro {i} à trancher"}
                 for i in range(5)]
    couche = Couche(projets=projets, pool=pool, creations=creations, conversations=conversations,
                    automates=automates, alertes=alertes, a_valider=a_valider,
                    etats={"atelier": {"etat": "ok"}, "wikichat": {"etat": "ok"}, "gardiens": {"etat": "ok"}})
    wikichat = {"version": 1, "noeuds": noeuds_wk, "aretes": aretes_wk, "groupes": [],
                "limites": {"connecteurs_communs": ["atelier", "wikichat"]}}
    return couche, wikichat


def _projet_de_l_atelier(slug: str, *, herite: bool, choisis: list[str] | None = None) -> dict[str, Any]:
    return {
        "slug": slug, "titre": slug, "kind": "code", "range": False, "chemin": f"/p/{slug}",
        "cree_le": None, "maj": None,
        "structure": {"projet_json": "valide", "gabarit": "vide", "deploiement": None,
                      "vues_epinglees": 0, "description": None},
        "connecteurs": {"herite_du_pool": herite, "choisis": [] if herite else list(choisis or [])},
    }


def test_un_lien_meme_connecteur_ne_compte_que_les_connecteurs_choisis() -> None:
    """Essais du 26/09 : 181 liens « même connecteur » sur le pod, presque tous nés du pool.

    Les projets qui héritent du pool partagent tous blender, github, gitlab,
    llm et qgis ; wikichat, qui lit `.mcp.json`, en faisait autant de liens,
    et l'Atelier en ajoutait. Seul un connecteur choisi par les deux projets
    fait un lien.
    """
    pool = ["blender", "github", "gitlab", "grist", "llm", "qgis"]
    projets = [
        _projet_de_l_atelier("herite-a", herite=True),
        _projet_de_l_atelier("herite-b", herite=True),
        _projet_de_l_atelier("choix-a", herite=False, choisis=["grist", "qgis", "wikichat"]),
        _projet_de_l_atelier("choix-b", herite=False, choisis=["grist", "wikichat"]),
    ]
    heritage = ["blender", "github", "gitlab", "llm", "qgis"]

    def lien(a: str, b: str, connecteurs: list[str]) -> dict[str, Any]:
        return {"id": f"meme_connecteur:{a}~{b}", "type": "meme_connecteur", "de": a, "vers": b,
                "oriente": False, "connecteurs": connecteurs, "source": ".mcp.json"}

    wikichat = {
        "version": 1,
        "noeuds": [_noeud_wikichat(p["slug"]) for p in projets] + [_noeud_wikichat("hors-atelier")],
        "aretes": [
            lien("herite-a", "herite-b", heritage),
            lien("choix-a", "herite-a", ["qgis"]),
            lien("choix-a", "choix-b", heritage + ["grist"]),
            lien("hors-atelier", "herite-a", ["qgis"]),
            lien("choix-a", "hors-atelier", ["grist", "qgis"]),
        ],
        "groupes": [],
        "limites": {"connecteurs_communs": ["atelier", "wikichat"]},
    }
    carte = assembler(Couche(projets=projets, pool=pool), wikichat)
    liens = {a["id"]: a["connecteurs"] for a in carte["aretes"] if a["type"] == "meme_connecteur"}
    assert liens == {
        "meme_connecteur:choix-a~choix-b": ["grist"],
        "meme_connecteur:choix-a~hors-atelier": ["grist", "qgis"],
    }, "ni héritage du pool, ni connecteur commun : seulement ce que les deux ont choisi"
    # Les projets qui héritent du pool l'utilisent toujours.
    utilise = {a["id"] for a in carte["aretes"] if a["type"] == "utilise"}
    assert "utilise:herite-a>qgis" in utilise and "utilise:choix-b>grist" in utilise

    # Sans wikichat, l'Atelier ne crée pas davantage de lien d'héritage.
    seule = assembler(Couche(projets=projets, pool=pool), None)
    assert {a["id"] for a in seule["aretes"] if a["type"] == "meme_connecteur"} == {
        "meme_connecteur:choix-a~choix-b"
    }


def datetime_iso(t: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(t, tz=timezone.utc).isoformat(timespec="seconds")


def test_la_forme_synthetique_tient_dans_le_budget_pour_26_projets() -> None:
    couche, wikichat = _couche_realiste(26)
    texte = vue_synthetique(assembler(couche, wikichat))
    unites = len(texte) / CARACTERES_PAR_UNITE
    assert unites < PLAFOND_UNITES, (unites, texte)
    # Et elle dit l'essentiel : chaque projet actif a sa ligne, le reste son décompte.
    actifs = [p for p in couche.projets if not p["range"] and int(p["slug"][-3:]) % 3 == 0]
    for p in actifs:
        assert f"- {p['slug']}" in texte
    assert "Dormants (" in texte and "Autres dossiers connus de wikichat (13)" in texte


def test_au_dela_du_budget_les_projets_se_replient_en_dormants() -> None:
    couche, wikichat = _couche_realiste(200, tous_actifs=True)
    texte = vue_synthetique(assembler(couche, wikichat))
    assert len(texte) <= BUDGET_SYNTHETIQUE
    assert len(texte) / CARACTERES_PAR_UNITE < PLAFOND_UNITES
    montres = sum(1 for l in texte.splitlines() if l.startswith("- projet-exemple"))
    assert 0 < montres < 185, montres
    assert "Dormants (" in texte, "ce qui ne tient pas est replié, pas perdu"
    # Les plus récents restent en ligne.
    assert "- projet-exemple-numero-000" in texte


# ── Cache et invalidation ──────────────────────────────────────────────


def test_le_cache_tient_un_court_delai_et_cede_a_l_invalidation() -> None:
    horloge = [0.0]
    lectures = []

    def projets() -> list[dict[str, Any]]:
        lectures.append(1)
        return []

    carte = Carte(Sources(projets=projets, pool=list, creations=list, conversations=list), delai_s=20,
                  horloge=lambda: horloge[0])

    async def scenario() -> None:
        await carte.obtenir()
        await carte.obtenir()
        assert carte.calculs == 1, "dans le délai, la carte est gardée"
        carte.invalider("atelier_projet_creer")
        await carte.obtenir()
        assert carte.calculs == 2, "invalidée, elle est recalculée"
        horloge[0] = 25.0
        await carte.obtenir()
        assert carte.calculs == 3, "au-delà du délai, elle est recalculée"
        await carte.obtenir(rafraichir=True)
        assert carte.calculs == 4

    asyncio.run(scenario())
    assert len(lectures) == 4


def test_une_commande_qui_agit_se_voit_a_la_lecture_suivante(
    atelier: TestClient, voisins: tuple[Voisin, Voisin]
) -> None:
    wikichat, _ = voisins
    wikichat.reponses["/api/cartographie"] = (200, cartographie_du_contrat())
    carte = atelier.app.state.carte
    carte.delai_s = 3600  # seul le crochet peut rafraîchir

    texte = atelier.get("/v1/carte", headers=porteur(atelier)).json()["texte"]
    assert "carte-neuve" not in texte
    calculs = carte.calculs

    # Une lecture ne change rien : la carte reste gardée.
    commande(atelier, "atelier_journal")
    atelier.get("/v1/carte", headers=porteur(atelier))
    assert carte.calculs == calculs

    commande(atelier, "atelier_projet_creer", titre="Carte neuve", slug="carte-neuve")
    assert carte.derniere_invalidation == "atelier_projet_creer"
    texte = atelier.get("/v1/carte", headers=porteur(atelier)).json()["texte"]
    assert "- carte-neuve" in texte, "le projet créé est sur la carte sans que personne l'ait noté"
    assert carte.calculs == calculs + 1

    # Ranger : le crochet invalide encore, le projet quitte les projets affichés.
    commande(atelier, "atelier_projet_ranger", projet="carte-neuve")
    complete = carte_complete(atelier)
    neuve = next(n for n in complete["noeuds"] if n["id"] == "carte-neuve")
    assert neuve["atelier"]["range"] is True and neuve["atelier"]["actif"] is False
