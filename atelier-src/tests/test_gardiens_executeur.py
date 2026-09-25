"""L'exécuteur : déclaration, rythme, une alerte par empreinte, homme mort, gestes, journal, API."""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

import pytest

from mcp_gateway.gardiens import gestes
from mcp_gateway.gardiens.api import servir_en_arriere_plan
from mcp_gateway.gardiens.controles import REGISTRE
from mcp_gateway.gardiens.controles.commun import Contexte, ReponseHttp
from mcp_gateway.gardiens.declaration import Cron, Declaration, DeclarationInvalide, lire
from mcp_gateway.gardiens.executeur import HOMME_MORT, Executeur
from mcp_gateway.gardiens.journal import MOTIFS_DE_JETONS, Filtre, Journal

SECRET = "valeur-secrete-du-pool-987654321"


class Horloge:
    def __init__(self, t: float = 1_790_000_000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def ecrire_declaration(dossier: Path, controles: list[dict], reglages: dict | None = None) -> Path:
    chemin = dossier / "gardiens.json"
    chemin.write_text(json.dumps({"reglages": reglages or {}, "controles": controles}), encoding="utf-8")
    return chemin


def sonde(ident: str, service: str = "wikichat", **extra) -> dict:
    return {
        "id": ident,
        "gardien": "sante",
        "portee": "pod",
        "quand": {"toutes_les_min": 1},
        "commande": ["interne", "sante.service"],
        "delai_s": 5,
        "params": {"service": service},
        **extra,
    }


@pytest.fixture()
def ctx(tmp_path: Path) -> Contexte:
    work = tmp_path / "work"
    (work / ".secrets").mkdir(parents=True)
    return Contexte(work=work, home=tmp_path / "home", env={}, ecoutes=lambda: [], processus=lambda: [])


def executeur(tmp_path: Path, ctx: Contexte, controles: list[dict], horloge: Horloge | None = None, **options) -> Executeur:
    decl = lire(ecrire_declaration(tmp_path, controles, options.pop("reglages", None)))
    ctx.reglages = decl.reglages
    journal = Journal(tmp_path / "etat" / "journal", options.pop("filtre", None))
    return Executeur(decl, ctx, journal, tmp_path / "etat", horloge=horloge or Horloge(), **options)


def lignes_du_journal(tmp_path: Path) -> list[dict]:
    lignes = []
    for f in sorted((tmp_path / "etat" / "journal").glob("*.jsonl")):
        lignes += [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()]
    return lignes


# --- déclaration --------------------------------------------------------------


def test_la_declaration_du_paquet_est_valide_et_ne_nomme_que_des_controles_existants() -> None:
    decl = lire()
    assert {c.gardien for c in decl.controles} == {"sante", "securite", "entretien"}
    assert all(c.interne in REGISTRE for c in decl.controles)
    gestes_nommes = {c.geste for c in decl.controles if c.geste}
    assert gestes_nommes == set(gestes.GESTES)


@pytest.mark.parametrize(
    "defaut",
    [
        {"geste": "supprimer_le_projet", "si_constat": "geste"},
        {"gardien": "inconnu"},
        {"quand": {"tous_les_jours": 1}},
        {"delai_s": 0},
        {"si_constat": "geste"},
    ],
)
def test_une_declaration_hors_contrat_est_refusee(tmp_path: Path, defaut: dict) -> None:
    with pytest.raises(DeclarationInvalide):
        lire(ecrire_declaration(tmp_path, [{**sonde("x"), **defaut}]))


def test_cron() -> None:
    depart = datetime(2026, 9, 25, 10, 7, tzinfo=timezone.utc).timestamp()
    assert Cron("*/30 * * * *").suivante(depart) == datetime(2026, 9, 25, 10, 30, tzinfo=timezone.utc).timestamp()
    assert Cron("0 3 * * 0").suivante(depart) == datetime(2026, 9, 27, 3, 0, tzinfo=timezone.utc).timestamp()
    assert Cron("15 7 1 * *").suivante(depart) == datetime(2026, 10, 1, 7, 15, tzinfo=timezone.utc).timestamp()


# --- alertes et journal ---------------------------------------------------------


def test_une_alerte_par_empreinte_un_compteur_et_une_ligne_par_execution(tmp_path: Path, ctx: Contexte) -> None:
    etat = {"up": False}
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(200 if etat["up"] else 0, "", "refus")
    ex = executeur(tmp_path, ctx, [sonde("sante.wikichat")])
    c = ex.controles["sante.wikichat"]
    for _ in range(3):
        ex.passer(c)
    ouvertes = ex.alertes_ouvertes()
    assert len(ouvertes) == 1 and ouvertes[0]["compte"] == 3
    etat["up"] = True
    ex.passer(c)
    assert ex.alertes_ouvertes() == []
    lignes = lignes_du_journal(tmp_path)
    assert [l["etat"] for l in lignes] == ["alerte", "alerte", "alerte", "ok"]
    assert lignes[0]["alertes"]["nouvelles"] == ["sante.wikichat:ne-repond-pas"]
    assert lignes[1]["alertes"]["nouvelles"] == []
    assert lignes[3]["alertes"]["resolues"] == ["sante.wikichat:ne-repond-pas"]
    assert all(l["cout"]["jetons"] == 0 for l in lignes)
    # Ajout seul : les lignes déjà écrites restent telles quelles.
    avant = (tmp_path / "etat" / "journal").glob("*.jsonl").__next__().read_text(encoding="utf-8")
    ex.passer(c)
    apres = (tmp_path / "etat" / "journal").glob("*.jsonl").__next__().read_text(encoding="utf-8")
    assert apres.startswith(avant) and len(apres) > len(avant)


def test_le_journal_ne_porte_aucun_secret(tmp_path: Path, ctx: Contexte) -> None:
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(0, "", f"refus avec {SECRET} et ghp_{'b' * 36}")
    ex = executeur(tmp_path, ctx, [sonde("sante.wikichat")], filtre=Filtre([SECRET]))
    ex.passer(ex.controles["sante.wikichat"])
    texte = "".join(f.read_text(encoding="utf-8") for f in (tmp_path / "etat" / "journal").glob("*.jsonl"))
    assert SECRET not in texte and "ghp_" not in texte
    assert "<secret:" in texte and "<jeton masqué>" in texte


def test_les_motifs_du_journal_sont_ceux_de_la_coherence() -> None:
    from mcp_gateway.atelier.coherence import MOTIFS_DE_JETONS as MOTIFS_COHERENCE

    assert [m.pattern for m in MOTIFS_DE_JETONS] == [m.pattern for m in MOTIFS_COHERENCE]


def test_un_controle_bloque_ou_casse_devient_un_constat_sans_bloquer(tmp_path: Path, ctx: Contexte, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(REGISTRE, "essai.lent", lambda ctx, c: time.sleep(5))
    monkeypatch.setitem(REGISTRE, "essai.casse", lambda ctx, c: 1 / 0)
    ex = executeur(tmp_path, ctx, [
        {**sonde("lent"), "commande": ["interne", "essai.lent"], "delai_s": 0.3},
        {**sonde("casse"), "commande": ["interne", "essai.casse"]},
    ])
    debut = time.monotonic()
    lent = ex.passer(ex.controles["lent"])
    assert time.monotonic() - debut < 3
    assert lent["constats"][0]["empreinte"] == "lent:delai"
    casse = ex.passer(ex.controles["casse"])
    assert casse["constats"][0]["empreinte"] == "casse:erreur"
    assert "ZeroDivisionError" in casse["constats"][0]["preuve"]


def test_un_controle_externe_rend_son_json(tmp_path: Path, ctx: Contexte) -> None:
    script = tmp_path / "controle.py"
    script.write_text(
        "import json; print(json.dumps({'etat': 'attention', 'constats': [{'empreinte': 'ext:1', 'objet': 'o', 'resume': 'r', 'preuve': 'p', 'niveau': 'attention'}]}))"
    )
    ex = executeur(tmp_path, ctx, [{**sonde("ext"), "commande": [sys.executable, "controle.py"]}])
    ligne = ex.passer(ex.controles["ext"])
    assert ligne["etat"] == "attention" and ligne["constats"][0]["empreinte"] == "ext:1"


# --- homme mort -----------------------------------------------------------------


def test_homme_mort_au_redemarrage_et_en_cours_de_route(tmp_path: Path, ctx: Contexte) -> None:
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(200, "")
    horloge = Horloge()
    ex = executeur(tmp_path, ctx, [sonde("sante.wikichat")], horloge)
    ex.passer(ex.controles["sante.wikichat"])
    assert ex.alertes_ouvertes() == []
    # L'exécuteur s'arrête une heure : au redémarrage, le contrôle est en retard.
    horloge.t += 3600
    ex2 = executeur(tmp_path, ctx, [sonde("sante.wikichat")], horloge)
    assert [a["empreinte"] for a in ex2.alertes_ouvertes()] == [f"{HOMME_MORT}:sante.wikichat"]
    # Il retourne : l'alerte se ferme.
    ex2.passer(ex2.controles["sante.wikichat"])
    assert ex2.alertes_ouvertes() == []
    # Plus rien ne le fait tourner (boucle bloquée) : le veilleur le voit.
    horloge.t += 60 + ex2.tolerance(ex2.controles["sante.wikichat"]) + 1
    assert ex2.verifier_homme_mort() == ["sante.wikichat"]
    assert ex2.verifier_homme_mort() == ["sante.wikichat"]
    assert len(ex2.alertes_ouvertes()) == 1  # une seule alerte, pas une par passage
    assert any(l["controle"] == HOMME_MORT for l in lignes_du_journal(tmp_path))


# --- gestes ---------------------------------------------------------------------


def faux_script(tmp_path: Path, drapeau: Path) -> list[str]:
    """Un « script officiel » factice : il note son passage et relève le service."""
    script = tmp_path / "relancer.py"
    script.write_text(f"from pathlib import Path\nPath({str(drapeau)!r}).write_text('relancé')\nprint('relance : 200')\n")
    return [sys.executable, str(script)]


def service_factice(drapeau: Path):
    return lambda url, entetes=None, delai=5.0: ReponseHttp(200 if drapeau.exists() else 0, "", "refus")


def test_relance_par_le_script_officiel_apres_deux_echecs_avec_avant_et_apres(tmp_path: Path, ctx: Contexte) -> None:
    drapeau = tmp_path / "wikichat-en-route"
    ctx.http = service_factice(drapeau)
    horloge = Horloge()
    ex = executeur(
        tmp_path, ctx, [sonde("sante.wikichat", si_constat="geste", geste="relancer_wikichat")], horloge,
        reglages={"scripts": {"wikichat": {"argv": faux_script(tmp_path, drapeau), "delai_s": 30}}},
        permettre_gestes=True, attente_apres_geste_s=5,
    )
    c = ex.controles["sante.wikichat"]
    premiere = ex.passer(c)
    assert "action" not in premiere and not drapeau.exists()
    horloge.t += 60
    seconde = ex.passer(c)
    assert drapeau.read_text() == "relancé"
    action = seconde["action"]
    assert action["nom"] == "relancer_wikichat"
    assert action["avant"]["etat"] == "alerte"
    assert action["apres"]["etat"] == "ok"
    assert action["script"]["code"] == 0 and "relance : 200" in action["script"]["sortie"]
    assert ex.etats["sante.wikichat"].echecs_consecutifs == 0
    assert lignes_du_journal(tmp_path)[-1]["action"]["apres"]["etat"] == "ok"


def test_aucun_geste_quand_ils_sont_interdits(tmp_path: Path, ctx: Contexte) -> None:
    drapeau = tmp_path / "en-route"
    ctx.http = service_factice(drapeau)
    ctx.env = {"ATELIER_GARDIENS_GESTES": "0"}
    ex = executeur(
        tmp_path, ctx, [sonde("sante.wikichat", si_constat="geste", geste="relancer_wikichat")],
        reglages={"scripts": {"wikichat": {"argv": faux_script(tmp_path, drapeau)}}},
    )
    c = ex.controles["sante.wikichat"]
    ex.passer(c)
    ligne = ex.passer(c)
    assert ligne["action"]["refuse"] == "ATELIER_GARDIENS_GESTES=0"
    assert not drapeau.exists()


def test_l_atelier_n_est_relance_qu_apres_cinq_minutes_de_silence(tmp_path: Path, ctx: Contexte) -> None:
    drapeau = tmp_path / "atelier-en-route"
    ctx.http = service_factice(drapeau)
    horloge = Horloge()
    ex = executeur(
        tmp_path, ctx, [sonde("sante.atelier", "atelier", si_constat="geste", geste="relancer_atelier")], horloge,
        reglages={"scripts": {"atelier": {"argv": faux_script(tmp_path, drapeau)}}},
        permettre_gestes=True, attente_apres_geste_s=5,
    )
    c = ex.controles["sante.atelier"]
    for _ in range(4):  # quatre échecs en trois minutes : pas encore
        assert "action" not in ex.passer(c)
        horloge.t += 60
    assert not drapeau.exists()
    horloge.t += 120
    assert ex.passer(c)["action"]["apres"]["etat"] == "ok"
    assert drapeau.exists()


def test_pas_plus_de_trois_relances_dans_l_heure(tmp_path: Path, ctx: Contexte) -> None:
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(0, "", "refus")  # ne revient jamais
    horloge = Horloge()
    ex = executeur(
        tmp_path, ctx, [sonde("sante.wikichat", si_constat="geste", geste="relancer_wikichat")], horloge,
        reglages={"scripts": {"wikichat": {"argv": faux_script(tmp_path, tmp_path / "d")}}},
        permettre_gestes=True, attente_apres_geste_s=0,
    )
    c = ex.controles["sante.wikichat"]
    actions = []
    for _ in range(6):
        ligne = ex.passer(c)
        actions.append(ligne.get("action"))
        horloge.t += 60
    lances = [a for a in actions if a and "script" in a]
    refuses = [a for a in actions if a and "refuse" in a]
    assert len(lances) == 3 and len(refuses) == 2


def test_un_geste_hors_de_la_liste_fermee_n_existe_pas() -> None:
    assert set(gestes.GESTES) == {"relancer_atelier", "relancer_wikichat", "relancer_relais"}
    assert gestes.GESTES["relancer_atelier"].silence_min_s == 300


# --- API ------------------------------------------------------------------------


def lire_api(port: int, chemin: str, methode: str = "GET") -> tuple[int, dict]:
    try:
        with urlopen(Request(f"http://127.0.0.1:{port}{chemin}", method=methode), timeout=5) as r:
            return r.status, json.loads(r.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_api_de_lecture(tmp_path: Path, ctx: Contexte) -> None:
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(0, "", "refus")
    ctx.wikichat_dir = tmp_path / "wk"
    ex = executeur(tmp_path, ctx, [
        sonde("sante.wikichat"),
        {"id": "entretien.automates", "gardien": "entretien", "portee": "pod", "quand": {"cron": "*/15 * * * *"}, "commande": ["interne", "entretien.automates"]},
    ])
    ex.tout_une_fois()
    srv, _ = servir_en_arriere_plan(ex, 0)
    port = srv.server_address[1]
    try:
        assert srv.server_address[0] == "127.0.0.1"
        statut, sante = lire_api(port, "/sante")
        assert statut == 200 and sante["ok"] and sante["controles"] == 2
        _, etat = lire_api(port, "/etat")
        assert {c["id"] for c in etat["controles"]} == {"sante.wikichat", "entretien.automates"}
        assert etat["alertes_ouvertes"][0]["empreinte"] == "sante.wikichat:ne-repond-pas"
        _, echeances = lire_api(port, "/echeances")
        assert [e["id"] for e in echeances["echeances"]] == ["sante.wikichat", "entretien.automates"]
        _, resultats = lire_api(port, "/resultats?controle=sante.wikichat&n=5")
        assert resultats["lignes"][-1]["controle"] == "sante.wikichat"
        _, automates = lire_api(port, "/automates")
        assert any(a["id"] == "gardiens.sante.wikichat" for a in automates["automates"])
        assert lire_api(port, "/resultats/inconnu")[0] == 404
        assert lire_api(port, "/etat", "POST")[0] == 405
    finally:
        srv.shutdown()
        srv.server_close()


def test_declaration_vide_a_blanc_n_ecrit_rien(tmp_path: Path, ctx: Contexte) -> None:
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(0, "", "refus")
    decl = lire(ecrire_declaration(tmp_path, [sonde("sante.wikichat", si_constat="geste", geste="relancer_wikichat")]))
    ex = Executeur(decl, ctx, Journal(None), tmp_path / "etat", a_blanc=True)
    ex.tout_une_fois()
    lignes = ex.tout_une_fois()
    assert lignes[0]["action"]["refuse"] == "exécution à blanc"
    assert not (tmp_path / "etat").exists()
    assert isinstance(decl, Declaration)


# --- intégration vague 1 : journal unique et mode image -------------------------


def test_alertes_et_gestes_vont_au_journal_unique(tmp_path: Path, ctx: Contexte) -> None:
    from mcp_gateway.atelier.commandes.journal import Evenement, Journal as JournalUnique

    unique = JournalUnique(tmp_path / "unique")
    publies: list[dict] = []

    def publier(e: dict) -> None:
        publies.append(e)
        unique.ecrire(Evenement(acteur="gardiens", **e))

    etat = {"up": False}
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(200 if etat["up"] else 0, "", "refus")
    ex = executeur(tmp_path, ctx, [sonde("sante.wikichat")], publier=publier)
    c = ex.controles["sante.wikichat"]
    for _ in range(3):
        ex.passer(c)
    etat["up"] = True
    ex.passer(c)
    # Une ouverture, une fermeture : pas une ligne par exécution.
    assert [e["resultat"] for e in publies] == ["alerte", "resolue"]
    lignes = unique.lire()
    assert [l["source"] for l in lignes] == ["controle", "controle"]
    assert all(l["acteur"] == "gardiens" for l in lignes)


def test_rien_au_journal_unique_a_blanc(tmp_path: Path, ctx: Contexte) -> None:
    publies: list[dict] = []
    ctx.http = lambda url, entetes=None, delai=5.0: ReponseHttp(0, "", "refus")
    decl = lire(ecrire_declaration(tmp_path, [sonde("sante.wikichat")]))
    ex = Executeur(decl, ctx, Journal(None), None, a_blanc=True, publier=publies.append)
    ex.tout_une_fois()
    assert publies == []


def test_l_atelier_n_est_jamais_relance_en_mode_image(tmp_path: Path, ctx: Contexte) -> None:
    drapeau = tmp_path / "atelier-en-route"
    ctx.http = service_factice(drapeau)
    ctx.env = {"ATELIER_AVANT_PLAN": "1"}
    horloge = Horloge()
    ex = executeur(
        tmp_path, ctx, [sonde("sante.atelier", "atelier", si_constat="geste", geste="relancer_atelier")], horloge,
        reglages={"scripts": {"atelier": {"argv": faux_script(tmp_path, drapeau)}}},
        permettre_gestes=True, attente_apres_geste_s=5,
    )
    c = ex.controles["sante.atelier"]
    action = None
    for _ in range(8):
        ligne = ex.passer(c)
        action = ligne.get("action") or action
        horloge.t += 60
    assert action is not None and "ATELIER_AVANT_PLAN" in action["refuse"]
    assert not drapeau.exists()
