"""Accorder une fois doit suffire.

Sans mémoire, le mode `manual` est invivable : mesuré sur le pod, dix-sept
questions pour un seul tour — Bash, Read, Write, Skill. C'est ce palier, et lui
seul, qui rend le mode proposable.

Les portées ne sont pas inventées : ce sont celles que le CLI suggère dans
chaque demande — `addRules` pour une commande, `addDirectories` pour un
répertoire. L'outil seul est le cas de repli, le plus large, celui qu'on
comprend d'un coup d'œil.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.decisions import (
    Demande,
    Regle,
    RegistreDesDecisions,
    regle_suggeree,
)
from mcp_gateway.atelier.harness import ClaudeHarness

from test_canal_decision import _FauxProcessus, _cle


def _ecriture(chemin: str, session_id: str = "s1", request_id: str = "r1") -> Demande:
    return Demande(
        request_id=request_id,
        session_id=session_id,
        outil="Write",
        arguments={"file_path": chemin},
    )


def test_une_regle_sur_un_repertoire_couvre_ce_qui_est_dedans() -> None:
    regle = Regle("s1", "repertoire", "/home/onyxia/travail")
    assert regle.couvre(_ecriture("/home/onyxia/travail/a.txt"))
    assert regle.couvre(_ecriture("/home/onyxia/travail/sous/b.txt"))
    assert regle.couvre(_ecriture("/home/onyxia/travail"))
    # Le voisin qui commence pareil n'est pas dedans : « travail-bis » n'est pas
    # « travail ». Sans cette nuance, accorder un dossier en accorderait
    # d'autres, sans que personne l'ait voulu.
    assert not regle.couvre(_ecriture("/home/onyxia/travail-bis/c.txt"))
    assert not regle.couvre(_ecriture("/home/onyxia/ailleurs.txt"))


def test_une_regle_ne_traverse_pas_les_conversations() -> None:
    """Ce qu'on accorde dans un fil ne s'accorde pas dans un autre."""
    regle = Regle("s1", "outil", "Write")
    assert regle.couvre(_ecriture("/a", session_id="s1"))
    assert not regle.couvre(_ecriture("/a", session_id="s2"))


def test_une_regle_sur_une_commande_est_exacte() -> None:
    """Une commande voisine n'est pas la commande accordée."""
    regle = Regle("s1", "commande", "git status")
    exacte = Demande(
        request_id="r", session_id="s1", outil="Bash", arguments={"command": "git status"}
    )
    proche = Demande(
        request_id="r",
        session_id="s1",
        outil="Bash",
        arguments={"command": "git status --porcelain"},
    )
    assert regle.couvre(exacte)
    assert not regle.couvre(proche)


def test_la_regle_suggeree_prend_la_plus_etroite() -> None:
    """Élargir plus que demandé serait accorder plus qu'on ne nous demande."""
    avec_tout = Demande(
        request_id="r",
        session_id="s1",
        outil="Bash",
        arguments={"command": "echo bonjour"},
        suggestions=[
            {"type": "addDirectories", "directories": ["/home/onyxia"]},
            {
                "type": "addRules",
                "rules": [{"toolName": "Bash", "ruleContent": "echo bonjour"}],
            },
        ],
    )
    assert regle_suggeree(avec_tout).portee == "commande"

    avec_dossier = Demande(
        request_id="r",
        session_id="s1",
        outil="Write",
        suggestions=[{"type": "addDirectories", "directories": ["/home/onyxia"]}],
    )
    assert regle_suggeree(avec_dossier).portee == "repertoire"

    # Faute de suggestion, l'outil : large, mais c'est ce que l'utilisateur
    # voit et comprend — « Write, dans ce fil, ne me demande plus ».
    nu = Demande(request_id="r", session_id="s1", outil="Read")
    assert regle_suggeree(nu).portee == "outil"
    assert regle_suggeree(nu).valeur == "Read"


def test_une_regle_retenue_survit_au_redemarrage(tmp_path) -> None:
    """Sinon la question reviendrait à chaque relance, et le mode avec elle."""
    dossier = tmp_path / "decisions"
    RegistreDesDecisions(dossier).retenir(Regle("s1", "repertoire", "/home/onyxia"))

    apres = RegistreDesDecisions(dossier)
    assert [r.valeur for r in apres.regles("s1")] == ["/home/onyxia"]
    assert apres.regle_qui_couvre(_ecriture("/home/onyxia/x.txt")) is not None
    assert apres.regle_qui_couvre(_ecriture("/ailleurs/x.txt")) is None


def test_retenir_deux_fois_la_meme_regle_ne_la_double_pas(tmp_path) -> None:
    registre = RegistreDesDecisions(tmp_path / "decisions")
    registre.retenir(Regle("s1", "outil", "Write"))
    registre.retenir(Regle("s1", "outil", "Write"))
    assert len(registre.regles("s1")) == 1


def test_on_peut_reprendre_ce_qu_on_a_accorde(tmp_path) -> None:
    """Une autorisation qu'on ne peut pas retirer n'est plus une décision."""
    dossier = tmp_path / "decisions"
    registre = RegistreDesDecisions(dossier)
    registre.retenir(Regle("s1", "outil", "Write"))

    assert registre.oublier_les_regles("s1") == 1
    assert registre.regles("s1") == []
    assert RegistreDesDecisions(dossier).regles("s1") == []


def test_une_regle_dispense_de_poser_la_question(tmp_path) -> None:
    """Le cœur du palier : rien ne remonte, le tour ne s'arrête pas."""
    harnais = ClaudeHarness(AtelierSettings(work_dir=tmp_path / "work"))
    harnais.decisions.retenir(Regle("s1", "outil", "Write"))
    proc = _FauxProcessus()
    causes: list[str] = []

    attendu = harnais._attendre_la_decision(
        _ecriture("/a.txt"), proc, lambda ev: causes.append(ev.cause) or ev, True
    )

    assert attendu == 0.0, "on n'a pas attendu"
    assert harnais.decisions.en_attente() == [], "la question n'aurait pas dû être posée"
    assert causes == ["regle:outil"]
    assert json.loads(proc.recu[0])["response"]["response"]["behavior"] == "allow"


def test_une_regle_vaut_meme_pour_un_tour_sans_interlocuteur(tmp_path) -> None:
    """Ce que l'utilisateur a accordé, il l'a accordé — l'agent en profite aussi."""
    harnais = ClaudeHarness(AtelierSettings(work_dir=tmp_path / "work"))
    harnais.decisions.retenir(Regle("s1", "outil", "Write"))
    proc = _FauxProcessus()

    harnais._attendre_la_decision(_ecriture("/a.txt"), proc, lambda ev: ev, False)
    assert json.loads(proc.recu[0])["response"]["response"]["behavior"] == "allow"


def test_repondre_toujours_retient_la_regle_du_cli(atelier: TestClient) -> None:
    registre = atelier.app.state.harness.decisions
    registre.poser(
        Demande(
            request_id="tj",
            session_id="s7",
            outil="Write",
            arguments={"file_path": "/home/onyxia/x.txt"},
            suggestions=[{"type": "addDirectories", "directories": ["/home/onyxia"]}],
        )
    )
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/tj",
        headers=entete,
        json={"decision": "allow", "portee": "toujours"},
    )
    assert r.status_code == 200
    assert r.json()["regle"]["portee"] == "repertoire"
    assert [x.valeur for x in registre.regles("s7")] == ["/home/onyxia"]
    registre.clore("tj")
    registre.oublier_les_regles("s7")


def test_une_seule_fois_ne_retient_rien(atelier: TestClient) -> None:
    """Le défaut n'engage pas l'avenir : c'est « toujours » qui est un choix."""
    registre = atelier.app.state.harness.decisions
    registre.poser(Demande(request_id="uf", session_id="s8", outil="Write"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post("/v1/decisions/uf", headers=entete, json={"decision": "allow"})
    assert r.json()["regle"] is None
    assert registre.regles("s8") == []
    registre.clore("uf")


def test_un_refus_ne_retient_jamais_rien(atelier: TestClient) -> None:
    """« Toujours » n'a de sens que pour accorder ; on ne fige pas un refus."""
    registre = atelier.app.state.harness.decisions
    registre.poser(Demande(request_id="rf", session_id="s10", outil="Write"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/rf",
        headers=entete,
        json={"decision": "deny", "portee": "toujours"},
    )
    assert r.json()["regle"] is None
    assert registre.regles("s10") == []
    registre.clore("rf")


def test_les_regles_se_listent_et_s_oublient(atelier: TestClient) -> None:
    registre = atelier.app.state.harness.decisions
    registre.retenir(Regle("s9", "outil", "Bash"))
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    lues = atelier.get("/v1/sessions/s9/regles", headers=entete).json()
    assert [r["valeur"] for r in lues["regles"]] == ["Bash"]

    assert atelier.delete("/v1/sessions/s9/regles", headers=entete).json()["oubliees"] == 1
    assert atelier.get("/v1/sessions/s9/regles", headers=entete).json()["regles"] == []


def test_les_regles_ne_sont_pas_publiques(atelier: TestClient) -> None:
    """Poser une règle, c'est accorder d'avance : même porte que le reste."""
    assert atelier.get("/v1/sessions/s9/regles").status_code == 401
    assert atelier.delete("/v1/sessions/s9/regles").status_code == 401


def test_supprimer_une_conversation_efface_ce_qu_on_lui_avait_accorde(
    atelier: TestClient,
) -> None:
    """Une règle sans fil n'autorise plus rien — mais elle traînerait.

    Et un identifiant réutilisé la retrouverait : une autorisation donnée à une
    conversation disparue reviendrait à une autre.
    """
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}
    sid = atelier.post(
        "/v1/sessions", headers=entete, json={"slug": "essai", "title": "Ephemere"}
    ).json()["session_id"]
    registre = atelier.app.state.harness.decisions
    registre.retenir(Regle(sid, "outil", "Write"))
    assert registre.regles(sid)

    atelier.delete(f"/v1/sessions/{sid}", headers=entete)
    assert registre.regles(sid) == []
