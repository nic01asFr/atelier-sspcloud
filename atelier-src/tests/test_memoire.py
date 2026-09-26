"""La mémoire côté Atelier : filtre des transcripts (T10), transcript fourni à wikichat,
propositions par « À valider », rappel sous budget, profil `code` borné à son projet.

wikichat est un faux serveur HTTP qui suit le contrat de ses routes `/api/memoire/*`
(`docs/atelier-coherence.md` §14 de wikichat) : l'Atelier l'appelle par le même
chemin qu'en service.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.commandes.rappel import BUDGET_RAPPEL_CAR, BUDGET_RAPPEL_UNITES, unites
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.filtre_transcripts import JETON_MASQUE, filtre_de_valeurs, marque
from mcp_gateway.atelier.memoire import evenements_de

ATELIER = "https://testserver"
SECRET_ENV = "valeur-tres-secrete-du-pod-0123456789"
SECRET_FICHIER = "cle-du-fichier-secret-abcdefghijkl"
JETON_GITHUB = "ghp_" + "A" * 36


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FauxWikichat:
    """Les routes mémoire de wikichat, en mémoire ; note chaque appel."""

    def __init__(self) -> None:
        self.appels: list[dict[str, Any]] = []
        self.rappel: dict[str, Any] = {"resultats": [], "total": 0}
        self.fiches: dict[str, dict[str, Any]] = {}
        self.elements: list[dict[str, Any]] = []
        faux = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def _repondre(self, statut: int, corps: Any) -> None:
                donnees = json.dumps(corps).encode("utf-8")
                self.send_response(statut)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(donnees)))
                self.end_headers()
                self.wfile.write(donnees)

            def _traiter(self, methode: str) -> None:
                u = urlsplit(self.path)
                params = {k: v[0] for k, v in parse_qs(u.query).items()}
                longueur = int(self.headers.get("Content-Length") or 0)
                corps = json.loads(self.rfile.read(longueur) or b"null") if longueur else None
                faux.appels.append({"methode": methode, "chemin": u.path, "params": params, "corps": corps,
                                    "cle": self.headers.get("X-Atelier-Lanceur")})
                if u.path == "/api/memoire/rappel":
                    return self._repondre(200, faux.rappel)
                if u.path.startswith("/api/memoire/fiches/"):
                    ident = u.path.rsplit("/", 1)[1]
                    f = next((x for k, x in faux.fiches.items() if k.startswith(ident)), None)
                    if f is None or (params.get("projet") and f["projet"] != params["projet"]):
                        return self._repondre(404, {"erreur": "introuvable"})
                    return self._repondre(200, f)
                if u.path == "/api/memoire/personne" and methode == "GET":
                    return self._repondre(200, {"elements": faux.elements})
                if u.path == "/api/memoire/personne" and methode == "POST":
                    el = {"id": f"m-{len(faux.elements) + 1}", **(corps or {})}
                    faux.elements.append(el)
                    return self._repondre(201, {"element": el})
                if u.path.startswith("/api/memoire/personne/"):
                    ident = u.path.rsplit("/", 1)[1]
                    el = next((x for x in faux.elements if x["id"] == ident), None)
                    if el is None:
                        return self._repondre(404, {"erreur": "inconnu"})
                    if methode == "DELETE":
                        faux.elements.remove(el)
                        return self._repondre(200, {"element": el})
                    avant = el["texte"]
                    el["texte"] = corps["texte"]
                    return self._repondre(200, {"element": el, "avant": avant})
                return self._repondre(404, {"erreur": "route inconnue"})

            def do_GET(self) -> None:  # noqa: N802
                self._traiter("GET")

            def do_POST(self) -> None:  # noqa: N802
                self._traiter("POST")

            def do_PATCH(self) -> None:  # noqa: N802
                self._traiter("PATCH")

            def do_DELETE(self) -> None:  # noqa: N802
                self._traiter("DELETE")

            def log_message(self, *args: Any) -> None:
                return

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.port = self.serveur.server_address[1]
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self) -> None:
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture()
def wikichat() -> Iterator[FauxWikichat]:
    faux = FauxWikichat()
    try:
        yield faux
    finally:
        faux.fermer()


def _secrets(settings: AtelierSettings) -> None:
    """Un `claude-env.sh` et un fichier de secret, comme sur le pod."""
    settings.secrets_dir.mkdir(parents=True, exist_ok=True)
    (settings.secrets_dir / "claude-env.sh").write_text(
        f"export ATELIER_MCP_N8N_TOKEN='{SECRET_ENV}'\n", encoding="utf-8"
    )
    (settings.secrets_dir / "github_token").write_text(SECRET_FICHIER + "\n", encoding="utf-8")


@pytest.fixture()
def atelier(tmp_path: Path, wikichat: FauxWikichat) -> Iterator[TestClient]:
    settings = AtelierSettings(work_dir=tmp_path / "work", public_url=ATELIER,
                               wikichat_url=f"http://127.0.0.1:{wikichat.port}/sse")
    settings.relais_llm_port = _port_libre()
    _secrets(settings)
    with TestClient(build_app(settings=settings, use_fake=True), base_url=ATELIER) as client:
        yield client


def porteur(client: TestClient) -> dict[str, str]:
    cle = client.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


def lanceur(client: TestClient) -> dict[str, str]:
    from mcp_gateway.atelier.lancements import assurer_la_cle

    return {"X-Atelier-Lanceur": assurer_la_cle(client.app.state.settings)}


def personne(client: TestClient) -> dict[str, str]:
    """La session de l'interface : la personne."""
    from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

    sid = client.app.state.auth.ouvrir_session()
    return {"Cookie": f"{COOKIE_NAME}={sid}", "X-Atelier-Interface": "1", "Origin": ATELIER}


def commande(client: TestClient, nom: str, entetes: dict[str, str] | None = None, **arguments: Any) -> Any:
    return client.post(f"/v1/commandes/{nom}", json={"arguments": arguments}, headers=entetes or porteur(client))


def lignes_du_transcript(secret_dans_outil: bool = True) -> list[dict[str, Any]]:
    """Un transcript fixe : une demande, un outil qui affiche un secret, une erreur, une fin."""
    return [
        {"type": "user", "uuid": "u1", "timestamp": "2026-09-25T14:00:00Z", "entrypoint": "sdk-cli",
         "message": {"role": "user", "content": f"Crée le projet marchés publics. Au passage le jeton est {SECRET_ENV}"}},
        {"type": "assistant", "uuid": "a1", "timestamp": "2026-09-25T14:00:05Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Je crée le projet."},
             {"type": "tool_use", "id": "t1", "name": "mcp__atelier__atelier_projet_creer",
              "input": {"titre": "Marchés publics", "slug": "marches-publics", "description": "x" * 900}},
             {"type": "tool_use", "id": "t2", "name": "Bash",
              "input": {"command": f"echo {SECRET_FICHIER} && git commit -m 'Ouvrir le projet'" if secret_dans_outil else "ls"}},
         ]}},
        {"type": "user", "uuid": "u2", "timestamp": "2026-09-25T14:00:09Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": "contenu long du résultat, jamais rendu " * 50},
             {"type": "tool_result", "tool_use_id": "t2", "is_error": True, "content": f"échec : {JETON_GITHUB}"},
         ]}},
        {"type": "assistant", "uuid": "a2", "timestamp": "2026-09-25T14:00:20Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": f"Fait. Voici la clé : {SECRET_ENV}"}]}},
        {"type": "result", "timestamp": "2026-09-25T14:00:21Z", "subtype": "success", "is_error": False,
         "usage": {"input_tokens": 1000, "cache_read_input_tokens": 20000, "output_tokens": 300}},
    ]


def conversation(client: TestClient, slug: str = "alpha", *, lignes: list[dict[str, Any]] | None = None) -> str:
    store = client.app.state.store
    rec = store.create(slug=slug, title=f"Conversation de {slug}")
    Path(rec.transcript_path).write_text(
        "\n".join(json.dumps(l, ensure_ascii=False) for l in (lignes or lignes_du_transcript())) + "\n",
        encoding="utf-8",
    )
    return rec.session_id


def sans_secret(texte: str) -> None:
    for valeur in (SECRET_ENV, SECRET_FICHIER, JETON_GITHUB):
        assert valeur not in texte, f"valeur connue retrouvée : {valeur[:6]}…"


# ── T10 : le filtre ──────────────────────────────────────────────────────────


def test_filtre_valeur_connue_forme_echappee_et_motif() -> None:
    f = filtre_de_valeurs([SECRET_ENV, 'avec"guillemet\\et-barre-longue'])
    brut = json.dumps({"t": f"a {SECRET_ENV} b", "u": 'x avec"guillemet\\et-barre-longue y', "g": f"jeton {JETON_GITHUB}"})
    propre = f.texte(brut)
    assert SECRET_ENV not in propre and JETON_GITHUB not in propre and "guillemet" not in propre
    assert marque(SECRET_ENV) in propre and JETON_MASQUE in propre
    # Le JSON reste lisible : une marque ne casse pas une chaîne.
    json.loads(propre)
    # Rien n'est coupé : un transcript reste entier (le journal, lui, coupe à 600).
    long = "a" * 5000
    assert f.texte(long) == long
    # Les clés ne sont pas masquées par leur nom : une référence reste lisible.
    assert f.nettoyer({"secrets": {"TOKEN": "ref-apps-grist"}}) == {"secrets": {"TOKEN": "ref-apps-grist"}}


def test_atelier_transcript_ne_rend_jamais_une_valeur_connue(atelier: TestClient) -> None:
    sid = conversation(atelier)
    r = commande(atelier, "atelier_transcript", conversation=sid, derniers=40000)
    assert r.status_code == 200, r.text
    texte = json.dumps(r.json(), ensure_ascii=False)
    sans_secret(texte)
    assert "<secret:" in texte


def test_route_du_transcript_de_l_interface_filtree_et_lisible(atelier: TestClient) -> None:
    sid = conversation(atelier)
    r = atelier.get(f"/v1/sessions/{sid}/transcript", headers=porteur(atelier))
    assert r.status_code == 200
    transcript = r.json()["transcript"]
    sans_secret(transcript)
    for ligne in transcript.splitlines():
        json.loads(ligne)


def test_atelier_suivre_filtre_les_blocs(atelier: TestClient) -> None:
    from mcp_gateway.atelier.outils_conversation import _Suivi

    sid = conversation(atelier)
    outils = atelier.app.state.commandes.outils
    outils._suivis[sid] = _Suivi(blocs=[{"genre": "texte", "texte": f"voici {SECRET_ENV}"}], fini=True,
                                 texte=f"fin {SECRET_FICHIER}")
    r = commande(atelier, "atelier_suivre", conversation=sid)
    assert r.status_code == 200, r.text
    sans_secret(json.dumps(r.json(), ensure_ascii=False))


def test_atelier_conversations_filtre_le_dernier_texte(atelier: TestClient) -> None:
    sid = conversation(atelier)
    store = atelier.app.state.store
    rec = store.get(sid)
    rec.last_text = f"réponse avec {SECRET_ENV}"
    store.save(rec)
    r = commande(atelier, "atelier_conversations", projet="alpha")
    assert r.status_code == 200
    sans_secret(json.dumps(r.json(), ensure_ascii=False))


# ── Le transcript fourni à wikichat ──────────────────────────────────────────


def test_extraction_lit_un_transcript_fixe_reduit_et_filtre(atelier: TestClient) -> None:
    sid = conversation(atelier)
    r = atelier.get(f"/v1/memoire/conversations/{sid}")
    assert r.status_code == 401, "sans clé, rien"
    r = atelier.get(f"/v1/memoire/conversations/{sid}", headers=lanceur(atelier))
    assert r.status_code == 200, r.text
    corps = r.json()
    texte = json.dumps(corps, ensure_ascii=False)
    sans_secret(texte)
    assert "jamais rendu" not in texte, "le contenu d'un résultat d'outil ne sort pas"
    roles = [e["role"] for e in corps["evenements"]]
    assert roles == ["personne", "modele", "outil", "outil", "resultat", "resultat", "modele", "fin"]
    creer = corps["evenements"][2]
    assert creer["outil"] == "mcp__atelier__atelier_projet_creer"
    assert creer["entree"]["slug"] == "marches-publics"
    assert len(creer["entree"]["description"]) <= 301, "une entrée d'outil est abrégée"
    erreur = corps["evenements"][5]
    assert erreur["erreur"] is True and JETON_MASQUE in erreur["texte"]
    assert corps["evenements"][4].get("texte") is None, "un résultat réussi ne rend aucun texte"
    assert corps["evenements"][-1]["jetons"] == {"entree": 21000, "sortie": 300}
    meta = corps["conversation"]
    assert meta["projet"] == "alpha" and meta["genre"] == "code" and meta["empreinte"]
    assert corps["evenements"][0]["surface"] == "sdk-cli"


def test_liste_des_conversations_repos_et_empreinte(atelier: TestClient) -> None:
    sid = conversation(atelier)
    r = atelier.get("/v1/memoire/conversations?repos_min=0", headers=lanceur(atelier))
    assert r.status_code == 200
    conv = next(c for c in r.json()["conversations"] if c["id"] == sid)
    # « created » : une conversation qui n'a pas encore joué n'est pas au repos.
    assert conv["au_repos"] is False
    store = atelier.app.state.store
    rec = store.get(sid)
    rec.state = "idle"
    store.save(rec)
    avant = conv["empreinte"]
    with open(rec.transcript_path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "user", "uuid": "u9", "timestamp": "2026-09-25T15:00:00Z",
                            "message": {"content": "encore une chose"}}) + "\n")
    conv = next(c for c in atelier.get("/v1/memoire/conversations?repos_min=0", headers=lanceur(atelier)).json()["conversations"] if c["id"] == sid)
    assert conv["au_repos"] is True
    assert conv["empreinte"] != avant, "une conversation qui grandit change d'empreinte"
    # Les lancements de la routine de nuit ne se fichent pas eux-mêmes.
    rec.lance_par = "wikichat:memoire:nuit"
    store.save(rec)
    ids = [c["id"] for c in atelier.get("/v1/memoire/conversations?repos_min=0", headers=lanceur(atelier)).json()["conversations"]]
    assert sid not in ids


def test_meme_en_tete_que_le_lanceur() -> None:
    from mcp_gateway.atelier import lancements, memoire

    assert memoire.ENTETE_CLE == lancements.ENTETE_CLE


def test_evenements_chemins_relatifs() -> None:
    entrees = [{"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "t", "name": "Edit", "input": {"file_path": "/w/projects/a/src/x.py", "old_string": "s"}}]}}]
    evs, tronque = evenements_de(entrees, "/w/projects/a")
    assert evs[0]["entree"] == {"file_path": "src/x.py"} and tronque is False


# ── Propositions : « À valider », jamais d'office ────────────────────────────


def test_proposition_de_memoire_passe_par_a_valider(atelier: TestClient, wikichat: FauxWikichat) -> None:
    corps = {"type": "preference", "texte": "Pas de notification la nuit", "conversation": "c-1", "projet": "alpha"}
    r = atelier.post("/v1/memoire/propositions", json=corps, headers=lanceur(atelier))
    assert r.status_code == 200, r.text
    p = r.json()["proposition"]
    assert p["source"] == "memoire" and p["statut"] == "en_attente"
    assert p["action"]["commande"] == "atelier_memoire_retenir"
    assert not [a for a in wikichat.appels if a["methode"] == "POST"], "rien n'est retenu avant l'accord"
    # Le même texte n'est pas dupliqué ; au plus trois par conversation.
    atelier.post("/v1/memoire/propositions", json=corps, headers=lanceur(atelier))
    for i in range(2):
        r = atelier.post("/v1/memoire/propositions", json={**corps, "texte": f"autre préférence {i}"}, headers=lanceur(atelier))
        assert r.status_code == 200
    r = atelier.post("/v1/memoire/propositions", json={**corps, "texte": "une de trop"}, headers=lanceur(atelier))
    assert r.status_code == 422
    en_attente = atelier.app.state.a_valider.lister(source="memoire")
    assert len(en_attente) == 3
    # Un modèle (clé du propriétaire) ne peut ni accepter, ni retenir lui-même.
    r = atelier.post(f"/v1/a-valider/{p['id']}/decision", json={"decision": "accepter"}, headers=porteur(atelier))
    assert r.status_code == 403
    r = commande(atelier, "atelier_memoire_retenir", type="preference", texte="retenu par un modèle")
    assert r.status_code == 403
    assert not [a for a in wikichat.appels if a["methode"] == "POST"]
    # La personne accepte : la commande réservée écrit chez wikichat, avec la clé.
    r = atelier.post(f"/v1/a-valider/{p['id']}/decision", json={"decision": "accepter"}, headers=personne(atelier))
    assert r.status_code == 200, r.text
    ecrits = [a for a in wikichat.appels if a["methode"] == "POST" and a["chemin"] == "/api/memoire/personne"]
    assert len(ecrits) == 1 and ecrits[0]["corps"]["texte"] == "Pas de notification la nuit"
    assert ecrits[0]["corps"]["source"] == {"conversation": "c-1", "projet": "alpha"}, "la provenance suit"
    assert all(isinstance(v, str) for v in p["action"]["arguments"].values()), "des arguments à plat, lisibles dans « À valider »"
    assert ecrits[0]["cle"], "wikichat reçoit la clé du lanceur"


def test_proposition_filtre_les_secrets(atelier: TestClient) -> None:
    r = atelier.post("/v1/memoire/propositions", headers=lanceur(atelier),
                     json={"type": "profil", "texte": f"Sa clé est {SECRET_ENV}", "conversation": "c-2"})
    assert r.status_code == 200
    sans_secret(json.dumps(r.json(), ensure_ascii=False))


def test_corriger_et_oublier_reserves_a_la_personne(atelier: TestClient, wikichat: FauxWikichat) -> None:
    wikichat.elements.append({"id": "m-1", "type": "preference", "texte": "Réponses courtes"})
    assert commande(atelier, "atelier_memoire_oublier", id="m-1").status_code == 403
    r = commande(atelier, "atelier_memoire_corriger", personne(atelier), id="m-1", texte="Réponses très courtes")
    assert r.status_code == 200, r.text
    assert wikichat.elements[0]["texte"] == "Réponses très courtes"
    r = commande(atelier, "atelier_memoire_oublier", personne(atelier), id="m-1")
    assert r.status_code == 200 and not wikichat.elements
    # Ni retenir, ni corriger, ni oublier ne sont des outils MCP.
    noms = {c["nom"]: c for c in atelier.get("/v1/commandes", headers=porteur(atelier)).json()["commandes"]}
    for nom in ("atelier_memoire_retenir", "atelier_memoire_corriger", "atelier_memoire_oublier"):
        assert noms[nom]["classe"] == "reservee" and noms[nom]["exposee_mcp"] is False


# ── Rappel : sous budget ─────────────────────────────────────────────────────


def _resultats(n: int, projet: str = "alpha") -> list[dict[str, Any]]:
    return [
        {"id": f"{i:08d}-aaaa-bbbb-cccc-dddddddddddd", "projet": projet, "genre": "code",
         "debut": "2026-09-20T10:00:00Z", "fin": "2026-09-20T11:00:00Z",
         "titre": "Widget de carte pour le lecteur Grist " * 4, "resume": "On a choisi Leaflet plutôt que MapLibre. " * 20}
        for i in range(n)
    ]


def test_rappel_sous_budget(atelier: TestClient, wikichat: FauxWikichat) -> None:
    wikichat.rappel = {"resultats": _resultats(5), "total": 12}
    r = commande(atelier, "atelier_rappel", requete="widget de carte " * 18)
    assert r.status_code == 200, r.text
    charge = r.json()["resultat"]
    assert len(json.dumps(charge, ensure_ascii=False)) <= BUDGET_RAPPEL_CAR
    assert unites(charge) <= BUDGET_RAPPEL_UNITES
    assert charge["fiches"] and charge["trouvees"] == 12
    assert charge["fiches"][0].startswith("00000000 · 20/09 · alpha")


def test_fiche_bornee_et_id_court(atelier: TestClient, wikichat: FauxWikichat) -> None:
    wikichat.fiches["12345678-aaaa"] = {"id": "12345678-aaaa", "projet": "alpha", "genre": "code", "texte": "# Fiche\n" + "x" * 9000}
    r = commande(atelier, "atelier_fiche", id="12345678")
    assert r.status_code == 200, r.text
    assert len(r.json()["resultat"]["fiche"]) <= 2500 and r.json()["resultat"]["coupee"] is True


# ── Profil code : son projet seulement ───────────────────────────────────────


def test_profil_code_limite_a_son_projet(atelier: TestClient, wikichat: FauxWikichat) -> None:
    sid = conversation(atelier, "alpha")
    code = {**porteur(atelier), "X-Atelier-Conversation": sid}
    wikichat.rappel = {"resultats": _resultats(2, "alpha") + _resultats(1, "beta"), "total": 3}
    # Un autre projet : refusé, sans appel à wikichat.
    avant = len(wikichat.appels)
    r = commande(atelier, "atelier_rappel", code, requete="widget", projet="beta")
    assert r.status_code == 403
    assert len(wikichat.appels) == avant
    # Sans projet : celui de la conversation, et rien d'un autre projet ne revient.
    r = commande(atelier, "atelier_rappel", code, requete="widget")
    assert r.status_code == 200, r.text
    assert wikichat.appels[-1]["params"]["projet"] == "alpha"
    assert all(" · alpha · " in l for l in r.json()["resultat"]["fiches"])
    # Une fiche d'un autre projet : introuvable.
    wikichat.fiches["beta0001-x"] = {"id": "beta0001-x", "projet": "beta", "genre": "code", "texte": "secret de beta"}
    r = commande(atelier, "atelier_fiche", code, id="beta0001")
    assert r.status_code == 403
    assert "secret de beta" not in r.text
    # Les autres commandes de la mémoire ne sont pas du profil code.
    for nom, args in (("atelier_memoire", {}), ("atelier_memoire_proposer", {"type": "profil", "texte": "x y z"})):
        assert commande(atelier, nom, code, **args).status_code == 403
    noms = {c["nom"] for c in atelier.get("/v1/commandes", headers=code).json()["commandes"]}
    assert {"atelier_rappel", "atelier_fiche"} <= noms
    assert "atelier_memoire_proposer" not in noms


def test_proposer_depuis_une_conversation(atelier: TestClient) -> None:
    """L'Assistant (sans profil restreint) propose ; la conversation compte ses propositions."""
    r = commande(atelier, "atelier_memoire_proposer", type="preference", texte="Répondre en français")
    assert r.status_code == 200, r.text
    assert r.json()["statut"] == "fait"
    p = atelier.app.state.a_valider.lister(source="memoire")[0]
    assert p.action["commande"] == "atelier_memoire_retenir"
