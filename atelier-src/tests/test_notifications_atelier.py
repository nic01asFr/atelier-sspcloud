"""Les notifications de l'Atelier : quoi prévenir, comment, et répondre depuis la notification.

Ce que ces tests tiennent, et qu'un essai à la main ne tiendrait pas :
- une notification ne part que si un appareil est inscrit, que la catégorie est
  voulue, et une seule fois par question (la pose puis la veille portent la même) ;
- le jeton de décision ne permet de répondre qu'à **sa** question, une fois
  signé, et tombe avec la clé du propriétaire ;
- prévenir ne fait jamais échouer ce qu'on annonce ;
- les fichiers de la PWA sont servis comme un navigateur l'exige.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.decisions import Demande
from mcp_gateway.atelier.push import (
    CATEGORIES,
    Notifieur,
    assainir,
    ecrire_les_preferences,
    en_heures_calmes,
    jeton_de_decision,
    lire_le_jeton,
    lire_les_preferences,
    preferences_par_defaut,
)

CLE = "a" * 64


# -- les préférences ------------------------------------------------------


def test_par_defaut_on_previent_de_ce_qui_attend_la_personne(reglages: AtelierSettings) -> None:
    prefs = lire_les_preferences(reglages)
    assert prefs["categories"]["decision"] is True
    assert prefs["categories"]["question"] is True
    assert prefs["categories"]["bloque"] is True
    assert prefs["categories"]["fini"] is False, "un agent qui finit n'est pas une urgence"
    assert prefs["calme"]["actif"] is False
    assert set(prefs["categories"]) == set(CATEGORIES)


def test_un_fichier_abime_ne_prive_pas_des_notifications(reglages: AtelierSettings) -> None:
    chemin = reglages.work_dir / ".atelier" / "notifications.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("{pas du json", encoding="utf-8")
    assert lire_les_preferences(reglages) == preferences_par_defaut()


def test_les_valeurs_invalides_sont_ignorees_pas_refusees() -> None:
    prefs = assainir(
        {
            "categories": {"decision": "oui", "inconnue": True, "fini": True},
            "calme": {"actif": True, "de": "25:99", "a": "06:30"},
            "fuseau": "Mars/Olympus",
            "detail": "peut-être",
        }
    )
    assert prefs["categories"]["decision"] is True, "ni booléen ni valide : on garde le défaut"
    assert "inconnue" not in prefs["categories"]
    assert prefs["categories"]["fini"] is True
    assert prefs["calme"] == {"actif": True, "de": "22:00", "a": "06:30"}
    assert prefs["fuseau"] == "Europe/Paris"
    assert prefs["detail"] is True


def test_ecrire_applique_un_changement_partiel(reglages: AtelierSettings) -> None:
    ecrire_les_preferences(reglages, {"categories": {"fini": True}})
    ecrire_les_preferences(reglages, {"calme": {"actif": True, "de": "23:00"}})
    prefs = lire_les_preferences(reglages)
    assert prefs["categories"]["fini"] is True and prefs["categories"]["decision"] is True
    assert prefs["calme"] == {"actif": True, "de": "23:00", "a": "07:00"}


@pytest.mark.parametrize(
    "heure, attendu",
    [("23:30", True), ("03:00", True), ("06:59", True), ("07:00", False), ("12:00", False), ("21:59", False)],
)
def test_les_heures_calmes_passent_minuit(heure: str, attendu: bool) -> None:
    prefs = assainir({"calme": {"actif": True, "de": "22:00", "a": "07:00"}})
    h, m = (int(x) for x in heure.split(":"))
    assert en_heures_calmes(prefs, datetime(2026, 10, 11, h, m)) is attendu


def test_sans_heures_calmes_on_ne_se_tait_jamais() -> None:
    assert en_heures_calmes(preferences_par_defaut(), datetime(2026, 10, 11, 3, 0)) is False


# -- le jeton de décision -------------------------------------------------


def test_le_jeton_ne_permet_de_repondre_qu_a_sa_question() -> None:
    jeton = jeton_de_decision(CLE, "req-1")
    assert lire_le_jeton(CLE, jeton) == "req-1"
    assert lire_le_jeton(CLE, jeton.replace("req-1", "req-2", 1)) is None, "autre question : refusé"


def test_un_jeton_trafique_ou_perime_est_refuse() -> None:
    jeton = jeton_de_decision(CLE, "req-1")
    corps, _, signature = jeton.rpartition(".")
    assert lire_le_jeton(CLE, f"{corps}.{'0' * len(signature)}") is None
    perime = jeton_de_decision(CLE, "req-1", expire=int(time.time()) - 5)
    assert lire_le_jeton(CLE, perime) is None
    for faux in ("", "abc", "a.b", None, 12):
        assert lire_le_jeton(CLE, faux) is None  # type: ignore[arg-type]


def test_renouveler_la_cle_du_proprietaire_invalide_les_jetons() -> None:
    jeton = jeton_de_decision(CLE, "req-1")
    assert lire_le_jeton("b" * 64, jeton) is None


def test_un_identifiant_avec_des_points_se_relit() -> None:
    assert lire_le_jeton(CLE, jeton_de_decision(CLE, "dem.1.x")) == "dem.1.x"


# -- le notifieur ---------------------------------------------------------


class Boite:
    """Ce qu'un appareil recevrait."""

    def __init__(self, atteints: int = 1) -> None:
        self.recu: list[dict[str, Any]] = []
        self.atteints = atteints

    def __call__(self, titre: str, corps: str, **charge: Any) -> int:
        self.recu.append({"titre": titre, "corps": corps, **charge})
        return self.atteints


def _fiche(titre: str = "atlas-grist", slug: str = "atlas-grist", kind: str = "code") -> SimpleNamespace:
    return SimpleNamespace(title=titre, slug=slug, kind=kind)


class _Magasin:
    def __init__(self, fiche: SimpleNamespace | None) -> None:
        self.fiche = fiche

    def get(self, _session_id: str) -> SimpleNamespace | None:
        return self.fiche


def _notifieur(atelier: TestClient, reglages: AtelierSettings, boite: Boite, appareil: bool = True,
               fiche: SimpleNamespace | None = None) -> Notifieur:
    from mcp_gateway.notifications import enregistrer_abonnement

    db = atelier.app.state.db
    db.execute("DELETE FROM push_subscriptions")
    db.commit()
    if appareil:
        enregistrer_abonnement(db, {"endpoint": "https://push.example/abc", "keys": {"p256dh": "k", "auth": "a"}}, "Pixel · Chrome")
    return Notifieur(db, reglages, CLE, store=_Magasin(fiche or _fiche()), envoyer=boite)


def _demande(**kw: Any) -> Demande:
    base = dict(
        request_id="r1", session_id="s1", outil="Bash",
        arguments={"command": "pip install torch"}, description="pip install torch",
    )
    base.update(kw)
    return Demande(**base)


def test_sans_appareil_rien_ne_part(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    _notifieur(atelier, reglages, boite, appareil=False).avis("attendue", _demande())
    assert boite.recu == []


def test_une_demande_d_accord_arrive_avec_ses_deux_boutons(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    _notifieur(atelier, reglages, boite).avis("attendue", _demande())

    (n,) = boite.recu
    assert n["titre"] == "atlas-grist a besoin de votre accord"
    assert n["corps"] == "Bash — pip install torch"
    assert n["actions"] == ["allow", "deny"]
    assert n["url"] == "/?slug=atlas-grist&session=s1", "la notification ouvre la bonne conversation"
    assert n["tag"] == "decision-r1"
    assert n["silencieux"] is False
    assert lire_le_jeton(CLE, n["decision"]["jeton"]) == "r1", "le jeton ne vaut que pour cette question"
    assert n["decision"]["genre"] == "autorisation"


def test_une_question_n_a_pas_de_boutons_on_ouvre_pour_repondre(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    question = _demande(
        outil="AskUserQuestion", genre="question",
        arguments={"questions": [{"header": "Pod", "question": "Quel pod utiliser ?", "options": []}]},
    )
    _notifieur(atelier, reglages, boite).avis("attendue", question)
    (n,) = boite.recu
    assert n["titre"] == "atlas-grist vous pose une question"
    assert n["corps"] == "Quel pod utiliser ?"
    assert n["actions"] == [], "on ne répond pas à une question à l'aveugle"


def test_la_pose_puis_la_veille_ne_font_qu_une_notification(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    n = _notifieur(atelier, reglages, boite)
    n.avis("attendue", _demande())
    n.avis("veille", _demande())
    assert len(boite.recu) == 1
    n.avis("veille", _demande(request_id="r2"))
    assert len(boite.recu) == 2, "une autre question, une autre notification"


def test_un_tour_que_personne_ne_regardait_prevenu_a_la_veille(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    _notifieur(atelier, reglages, boite).avis("veille", _demande())
    assert len(boite.recu) == 1


def test_une_categorie_coupee_ne_previent_pas(atelier: TestClient, reglages: AtelierSettings) -> None:
    ecrire_les_preferences(reglages, {"categories": {"decision": False}})
    boite = Boite()
    _notifieur(atelier, reglages, boite).avis("attendue", _demande())
    assert boite.recu == []


def test_sans_detail_l_ecran_verrouille_ne_montre_pas_la_commande(atelier: TestClient, reglages: AtelierSettings) -> None:
    ecrire_les_preferences(reglages, {"detail": False})
    boite = Boite()
    _notifieur(atelier, reglages, boite).avis("attendue", _demande())
    assert "pip install" not in boite.recu[0]["corps"]
    assert "Ouvrez l’Atelier" in boite.recu[0]["corps"]


def test_en_heures_calmes_la_notification_part_sans_bruit(
    atelier: TestClient, reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    ecrire_les_preferences(reglages, {"calme": {"actif": True, "de": "00:00", "a": "23:59"}})
    boite = Boite()
    _notifieur(atelier, reglages, boite).avis("attendue", _demande())
    assert boite.recu[0]["silencieux"] is True, "elle reste lisible, elle ne sonne pas"


def test_la_commande_longue_est_abregee(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    _notifieur(atelier, reglages, boite).avis(
        "attendue", _demande(arguments={"command": "echo " + "x" * 600})
    )
    assert len(boite.recu[0]["corps"]) <= 160


def test_un_envoi_qui_echoue_ne_fait_pas_echouer_l_avis(atelier: TestClient, reglages: AtelierSettings) -> None:
    def casse(titre: str, corps: str, **charge: Any) -> int:
        raise RuntimeError("service de poussée injoignable")

    n = _notifieur(atelier, reglages, Boite())
    n._envoyer = casse
    n.avis("attendue", _demande())  # ne lève pas


def test_la_notification_se_referme_quand_la_question_est_tranchee(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    _notifieur(atelier, reglages, boite).decision_prise("r1", True)
    (n,) = boite.recu
    assert n["tag"] == "decision-r1", "même tag : elle remplace la demande"
    assert n["resolue"] is True and n["silencieux"] is True


def _lancement(etat: str, **kw: Any) -> SimpleNamespace:
    return SimpleNamespace(id="lc-1", etat=etat, nom="Sentinel", projet="alpha", conversation="s1", erreur="", texte="", **kw)


def test_un_agent_fini_ne_previent_que_si_on_le_veut(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    n = _notifieur(atelier, reglages, boite)
    n.lancement(_lancement("fini"))
    assert boite.recu == [], "coupé par défaut"
    ecrire_les_preferences(reglages, {"categories": {"fini": True}})
    n.lancement(_lancement("fini"))
    assert [x["titre"] for x in boite.recu] == ["Sentinel a terminé son travail"]


def test_un_agent_bloque_previent_par_defaut(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    n = _notifieur(atelier, reglages, boite)
    n.lancement(_lancement("echec", ) if False else SimpleNamespace(
        id="lc-2", etat="echec", nom="Sentinel", projet="alpha", conversation="s1",
        erreur="code 1", texte=""))
    (x,) = boite.recu
    assert x["titre"] == "Sentinel s’est arrêté sans finir" and x["corps"] == "code 1"


def test_un_agent_qui_dort_n_est_pas_annonce_comme_termine(atelier: TestClient, reglages: AtelierSettings) -> None:
    """C'est sa question qui prévient, pas son état."""
    boite = Boite()
    _notifieur(atelier, reglages, boite).lancement(_lancement("en_attente"))
    assert boite.recu == []


def test_l_essai_dit_honnetement_ce_qui_s_est_passe(atelier: TestClient, reglages: AtelierSettings) -> None:
    sans = _notifieur(atelier, reglages, Boite(), appareil=False).essai()
    assert sans["ok"] is False and sans["appareils"] == 0 and "Aucun appareil" in sans["message"] or not sans["disponible"]
    atteint = _notifieur(atelier, reglages, Boite(atteints=1)).essai()
    if atteint["disponible"]:
        assert atteint["ok"] and "Reçu sur 1 appareil" in atteint["message"]
    perdu = _notifieur(atelier, reglages, Boite(atteints=0)).essai()
    if perdu["disponible"]:
        assert not perdu["ok"] and "Rien n’a pu être envoyé" in perdu["message"]


ALERTE_ANCIENNE = {"empreinte": "sante.atelier:ne-repond-pas", "niveau": "alerte", "resume": "atelier ne répond pas"}
ALERTE_NOUVELLE = {"empreinte": "securite.droits:cle", "niveau": "alerte", "resume": "une clé est lisible par d'autres"}
A_SURVEILLER = {"empreinte": "entretien.x", "niveau": "surveiller", "resume": "à surveiller"}


def _surveiller(n: Notifieur, lectures: list[Any], duree: float = 0.4) -> None:
    import asyncio

    suite = iter(lectures)
    derniere: list[Any] = [lectures[-1]]

    async def lire() -> Any:
        try:
            derniere[0] = next(suite)
        except StopIteration:
            pass
        return derniere[0]

    async def courir() -> None:
        try:
            await asyncio.wait_for(n.surveiller_les_alertes(lire, 0.01), duree)
        except asyncio.TimeoutError:
            pass

    asyncio.run(courir())


def test_une_alerte_grave_nouvelle_previent_une_seule_fois(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    n = _notifieur(atelier, reglages, boite)
    _surveiller(n, [[ALERTE_ANCIENNE], [ALERTE_ANCIENNE, ALERTE_NOUVELLE], [ALERTE_ANCIENNE, ALERTE_NOUVELLE]])
    (x,) = boite.recu
    assert x["titre"] == "Alerte de surveillance" and "clé est lisible" in x["corps"]
    assert x["url"] == "/?view=agent", "la notification ouvre là où se lisent les alertes"


def test_ce_qui_etait_deja_ouvert_au_demarrage_ne_fait_pas_sonner(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    _surveiller(_notifieur(atelier, reglages, boite), [[ALERTE_ANCIENNE]])
    assert boite.recu == []


def test_seules_les_alertes_graves_previennent(atelier: TestClient, reglages: AtelierSettings) -> None:
    boite = Boite()
    _surveiller(_notifieur(atelier, reglages, boite), [[], [A_SURVEILLER]])
    assert boite.recu == []


def test_une_alerte_qui_clignote_ne_sonne_pas_dix_fois(atelier: TestClient, reglages: AtelierSettings) -> None:
    """Registre D-24 : ouverte, résolue, rouverte — une seule notification."""
    boite = Boite()
    _surveiller(
        _notifieur(atelier, reglages, boite),
        [[], [ALERTE_NOUVELLE], [], [ALERTE_NOUVELLE], [], [ALERTE_NOUVELLE]],
    )
    assert len(boite.recu) == 1


def test_des_gardiens_injoignables_ne_cassent_pas_la_surveillance(atelier: TestClient, reglages: AtelierSettings) -> None:
    import asyncio

    boite = Boite()
    n = _notifieur(atelier, reglages, boite)
    appels = {"n": 0}

    async def lire() -> Any:
        appels["n"] += 1
        if appels["n"] < 3:
            raise ConnectionError("gardiens arrêtés")
        return [ALERTE_NOUVELLE] if appels["n"] > 4 else []

    async def courir() -> None:
        try:
            await asyncio.wait_for(n.surveiller_les_alertes(lire, 0.01), 0.4)
        except asyncio.TimeoutError:
            pass

    asyncio.run(courir())
    assert appels["n"] > 4 and len(boite.recu) == 1


# -- l'envoi réel, avec pywebpush ----------------------------------------


def test_la_charge_porte_les_champs_de_l_atelier(atelier: TestClient, reglages: AtelierSettings,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pywebpush")
    import pywebpush

    from mcp_gateway.notifications import enregistrer_abonnement, prevenir

    envoyes: list[dict[str, Any]] = []

    def faux_webpush(**kw: Any) -> None:
        envoyes.append({"sub": kw["subscription_info"], "data": json.loads(kw["data"]), "vapid": kw["vapid_claims"]})

    monkeypatch.setattr(pywebpush, "webpush", faux_webpush)
    db = atelier.app.state.db
    db.execute("DELETE FROM push_subscriptions")
    enregistrer_abonnement(db, {"endpoint": "https://push.example/x", "keys": {"p256dh": "k", "auth": "a"}}, "Pixel")
    atteints = prevenir(
        db, "T", "C", url="/?session=s", tag="decision-r1",
        extra={"actions": ["allow", "deny"], "decision": {"id": "r1", "jeton": "j"}, "titre": "ÉCRASÉ"},
    )
    assert atteints == 1
    (e,) = envoyes
    assert e["data"]["actions"] == ["allow", "deny"] and e["data"]["decision"]["id"] == "r1"
    assert e["data"]["titre"] == "T", "l'extra n'écrase pas les champs de base"
    assert e["sub"]["endpoint"] == "https://push.example/x"


# -- les routes -----------------------------------------------------------


def _entete(atelier: TestClient) -> dict[str, str]:
    cle = atelier.app.state.settings.owner_key_path.read_text(encoding="utf-8").strip()
    return {"Authorization": f"Bearer {cle}"}


ABONNEMENT = {"endpoint": "https://push.example/appareil-1", "keys": {"p256dh": "BPk", "auth": "sec"}}


def test_les_routes_de_la_personne_ne_sont_pas_publiques(atelier: TestClient) -> None:
    for methode, chemin in (("get", "/v1/push/etat"), ("post", "/v1/push/abonnements"),
                            ("put", "/v1/push/preferences"), ("post", "/v1/push/essai")):
        assert getattr(atelier, methode)(chemin).status_code == 401, chemin


def test_l_etat_donne_de_quoi_dessiner_l_ecran(atelier: TestClient) -> None:
    r = atelier.get("/v1/push/etat", headers=_entete(atelier))
    assert r.status_code == 200
    corps = r.json()
    assert {"disponible", "cle_publique", "appareils", "preferences", "categories"} <= set(corps)
    assert [c["id"] for c in corps["categories"]] == list(CATEGORIES)
    assert all(c["libelle"] for c in corps["categories"]), "des libellés en français, pas des identifiants"


def test_s_inscrire_puis_se_retirer(atelier: TestClient) -> None:
    h = _entete(atelier)
    atelier.app.state.db.execute("DELETE FROM push_subscriptions")
    assert atelier.post("/v1/push/abonnements", headers=h, json={"endpoint": "x"}).status_code == 400, "clés manquantes"
    r = atelier.post("/v1/push/abonnements", headers=h, json={"abonnement": ABONNEMENT, "appareil": "Pixel · Chrome"})
    assert r.status_code == 201
    # Idempotent : se réinscrire ne double rien.
    atelier.post("/v1/push/abonnements", headers=h, json={"abonnement": ABONNEMENT, "appareil": "Pixel · Chrome"})
    appareils = atelier.get("/v1/push/etat", headers=h).json()["appareils"]
    assert [a["appareil"] for a in appareils] == ["Pixel · Chrome"]
    assert "endpoint" not in appareils[0], "l'adresse de remise ne sort pas du service"

    assert atelier.request("DELETE", "/v1/push/abonnements", headers=h, json={"id": appareils[0]["id"]}).json()["oublie"]
    assert atelier.get("/v1/push/etat", headers=h).json()["appareils"] == []


def test_regler_enregistre_et_rend_les_preferences(atelier: TestClient, reglages: AtelierSettings) -> None:
    h = _entete(atelier)
    r = atelier.put("/v1/push/preferences", headers=h, json={"categories": {"fini": True}, "calme": {"actif": True}})
    assert r.status_code == 200
    assert r.json()["preferences"]["categories"]["fini"] is True
    assert lire_les_preferences(atelier.app.state.settings)["calme"]["actif"] is True
    assert atelier.put("/v1/push/preferences", headers=h, json=["pas", "un", "objet"]).status_code == 400


def test_l_essai_sans_appareil_le_dit(atelier: TestClient) -> None:
    atelier.app.state.db.execute("DELETE FROM push_subscriptions")
    r = atelier.post("/v1/push/essai", headers=_entete(atelier)).json()
    assert r["ok"] is False and r["atteints"] == 0 and r["message"]


# -- répondre depuis la notification -------------------------------------


def _conversation_en_veille(atelier: TestClient) -> tuple[str, Demande]:
    r = atelier.post("/v1/sessions", headers=_entete(atelier), json={"slug": "essai-notif"})
    sid = r.json()["session_id"]
    demande = Demande(request_id="rn1", session_id=sid, outil="Bash",
                      arguments={"command": "pip install torch"}, description="pip install torch")
    atelier.app.state.harness.decisions.deposer_en_veille(demande)
    return sid, demande


def _jeton(atelier: TestClient, request_id: str) -> str:
    return jeton_de_decision(atelier.app.state.auth.owner_key, request_id)


def test_le_bouton_autoriser_relance_l_agent_sans_cookie_ni_cle(atelier: TestClient) -> None:
    sid, demande = _conversation_en_veille(atelier)
    harnais = atelier.app.state.harness

    r = atelier.post(
        "/v1/decisions/rn1/notification",
        json={"jeton": _jeton(atelier, "rn1"), "decision": "allow"},
    )

    assert r.status_code == 200, r.text
    assert r.json()["reprise"] is True
    fin = time.monotonic() + 10
    while not harnais.appels and time.monotonic() < fin:
        time.sleep(0.05)
    assert harnais.appels and harnais.appels[-1]["message"].startswith("[Atelier]")
    assert "pip install torch" in harnais.appels[-1]["message"]


def test_un_jeton_d_une_autre_question_n_ouvre_rien(atelier: TestClient) -> None:
    _conversation_en_veille(atelier)
    r = atelier.post(
        "/v1/decisions/rn1/notification",
        json={"jeton": _jeton(atelier, "autre"), "decision": "allow"},
    )
    assert r.status_code == 403
    assert atelier.app.state.harness.decisions.demande_tracee("rn1") is not None, "la question reste posée"


def test_sans_jeton_ou_avec_un_faux_c_est_refuse(atelier: TestClient) -> None:
    _conversation_en_veille(atelier)
    for jeton in ("", "n'importe quoi", "rn1.9999999999.0000"):
        r = atelier.post("/v1/decisions/rn1/notification", json={"jeton": jeton, "decision": "allow"})
        assert r.status_code == 403, jeton


def test_le_jeton_ne_donne_qu_deux_gestes(atelier: TestClient) -> None:
    _conversation_en_veille(atelier)
    r = atelier.post(
        "/v1/decisions/rn1/notification",
        json={"jeton": _jeton(atelier, "rn1"), "decision": "toujours"},
    )
    assert r.status_code == 400, "« toujours » exige l'écran : une règle durable ne se donne pas d'un doigt"


def test_refuser_depuis_la_notification_relance_avec_un_refus(atelier: TestClient) -> None:
    _, _ = _conversation_en_veille(atelier)
    harnais = atelier.app.state.harness
    r = atelier.post(
        "/v1/decisions/rn1/notification",
        json={"jeton": _jeton(atelier, "rn1"), "decision": "deny"},
    )
    assert r.status_code == 200
    fin = time.monotonic() + 10
    while not harnais.appels and time.monotonic() < fin:
        time.sleep(0.05)
    assert "refusé" in harnais.appels[-1]["message"] and "Ne relance pas" in harnais.appels[-1]["message"]


# -- les fichiers de la PWA ---------------------------------------------


def test_le_service_worker_est_servi_a_la_racine_avec_sa_portee(atelier: TestClient) -> None:
    r = atelier.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    assert r.headers["service-worker-allowed"] == "/"
    assert "no-cache" in r.headers["cache-control"], "un service worker périmé ne se corrige jamais"
    assert "notificationclick" in r.text and "/notification" in r.text


def test_le_manifeste_est_valide_et_ses_icones_existent(atelier: TestClient) -> None:
    r = atelier.get("/manifest.webmanifest")
    assert r.status_code == 200 and "manifest+json" in r.headers["content-type"]
    m = r.json()
    assert m["display"] == "standalone" and m["start_url"] == "/" and m["lang"] == "fr"
    tailles = {i["sizes"] for i in m["icons"]}
    assert {"192x192", "512x512"} <= tailles
    assert any(i["purpose"] == "maskable" for i in m["icons"])
    for icone in m["icons"]:
        png = atelier.get(icone["src"])
        assert png.status_code == 200 and png.headers["content-type"] == "image/png", icone["src"]
        assert png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_la_page_annonce_le_manifeste_et_l_icone(atelier: TestClient) -> None:
    html = atelier.get("/").text
    assert 'rel="manifest" href="/manifest.webmanifest"' in html
    assert "apple-touch-icon" in html and 'name="theme-color"' in html


def test_la_page_a_la_cloche_des_notifications(atelier: TestClient) -> None:
    html = atelier.get("/").text
    assert 'id="btn-notifs"' in html and 'id="notifs"' in html and 'aria-label="Notifications"' in html


# -- les agents lancés ---------------------------------------------------


def test_un_lancement_qui_finit_previent_le_notifieur(reglages: AtelierSettings) -> None:
    from mcp_gateway.atelier.api import build_app
    from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle

    (reglages.projects_dir / "alpha").mkdir(parents=True, exist_ok=True)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:
        vus: list[str] = []
        client.app.state.lancements.avis = lambda l: vus.append(l.etat)
        r = client.post(
            "/v1/lancements",
            headers={ENTETE_CLE: lire_la_cle(client.app.state.settings)},
            json={"projet": "alpha", "message": "Fais-le.", "origine": "wikichat:trigger:essai",
                  "plafonds": {"duree_s": 60}},
        )
        assert r.status_code == 202, r.text
        client.app.state.lancements.attendre(r.json()["lancement"]["id"], 10)
        assert vus == ["fini"]


def test_un_avis_de_lancement_qui_echoue_ne_change_pas_son_sort(reglages: AtelierSettings) -> None:
    from mcp_gateway.atelier.api import build_app
    from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle

    (reglages.projects_dir / "alpha").mkdir(parents=True, exist_ok=True)
    with TestClient(build_app(settings=reglages, use_fake=True), base_url="https://testserver") as client:
        def casse(_l: Any) -> None:
            raise RuntimeError("push en panne")

        client.app.state.lancements.avis = casse
        r = client.post(
            "/v1/lancements",
            headers={ENTETE_CLE: lire_la_cle(client.app.state.settings)},
            json={"projet": "alpha", "message": "Fais-le.", "origine": "wikichat:trigger:essai",
                  "plafonds": {"duree_s": 60}},
        )
        identifiant = r.json()["lancement"]["id"]
        client.app.state.lancements.attendre(identifiant, 10)
        assert client.app.state.lancements.lire(identifiant).etat == "fini"
