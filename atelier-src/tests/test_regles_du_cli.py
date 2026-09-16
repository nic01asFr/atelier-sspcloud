"""« Toujours » doit tenir, et c'est le CLI qui doit l'appliquer.

Mesuré le 14 septembre 2026 sur le pod : pour `./x.sh 2>&1 | tail -5`, le CLI
suggère `ruleContent: "./x.sh"` — sans `:*` — avec
`decision_reason_type: subcommandResults`. Il a découpé la ligne sur le tube,
jugé `tail -5` sûr, ôté la redirection, et ne demande que pour `./x.sh`.

Notre registre comparait la commande entière par égalité : la règle retenue
ne couvrait ni la commande d'origine ni `./x.sh 2>&1 | tail -20`. Une douzaine
de demandes évitables dans une seule séance.

Trois remèdes, dans l'ordre où ils jouent : le CLI reçoit ses suggestions avec
l'autorisation (`updatedPermissions`) et cesse de demander dans le tour ; au
tour suivant, un processus neuf reçoit les règles du fil par `--settings`, dans
sa syntaxe ; et notre couverture de secours découpe comme lui.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.decisions import (
    Demande,
    Regle,
    RegistreDesDecisions,
    permissions_a_retenir,
    reglages_cli,
    regles_suggerees,
    reponse_autorisee,
    sans_redirections,
    segments_de_la_commande,
)
from mcp_gateway.atelier.harness import ClaudeHarness

from test_canal_decision import _cle


def _bash(commande: str, session_id: str = "s1") -> Demande:
    return Demande(
        request_id="r", session_id=session_id, outil="Bash", arguments={"command": commande}
    )


def _mesuree() -> Demande:
    """La demande telle que le CLI l'a envoyée, champ pour champ."""
    return Demande(
        request_id="r",
        session_id="s1",
        outil="Bash",
        arguments={"command": "./x.sh 2>&1 | tail -5"},
        raison_type="subcommandResults",
        suggestions=[
            {
                "type": "addRules",
                "rules": [{"toolName": "Bash", "ruleContent": "./x.sh"}],
                "behavior": "allow",
                "destination": "localSettings",
            }
        ],
    )


def test_on_decoupe_une_ligne_comme_le_cli() -> None:
    assert segments_de_la_commande("./x.sh 2>&1 | tail -5") == ["./x.sh", "tail -5"]
    assert segments_de_la_commande("a && b || c ; d") == ["a", "b", "c", "d"]
    assert sans_redirections("./x.sh > out.txt") == "./x.sh"
    assert sans_redirections("./x.sh >> out.txt 2>&1") == "./x.sh"
    assert sans_redirections("./x.sh 2>/dev/null") == "./x.sh"
    assert sans_redirections("cat < entree") == "cat"


def test_la_regle_suggeree_couvre_la_commande_d_origine() -> None:
    """Le défaut mesuré : `./x.sh` ne couvrait pas `./x.sh 2>&1`."""
    regle = Regle("s1", "commande", "./x.sh", outil="Bash")
    assert regle.couvre(_bash("./x.sh"))
    assert regle.couvre(_bash("./x.sh 2>&1"))
    assert regle.couvre(_bash("./x.sh > sortie.txt"))
    # Exacte reste exacte : un argument de plus est une autre commande.
    assert not regle.couvre(_bash("./x.sh --force"))
    assert not regle.couvre(_bash("./y.sh"))


def test_le_prefixe_du_cli_est_un_prefixe() -> None:
    regle = Regle("s1", "commande", "git status:*")
    assert regle.couvre(_bash("git status"))
    assert regle.couvre(_bash("git status --porcelain"))
    assert not regle.couvre(_bash("git statusx"))
    assert not regle.couvre(_bash("git stash"))


def test_une_regle_ne_couvre_pas_un_autre_outil() -> None:
    regle = Regle("s1", "commande", "./x.sh", outil="Bash")
    autre = Demande(
        request_id="r", session_id="s1", outil="Write", arguments={"command": "./x.sh"}
    )
    assert not regle.couvre(autre)


def test_les_regles_se_cumulent_sur_une_ligne(tmp_path) -> None:
    """`a | b` est couverte quand `a` et `b` le sont, par deux règles."""
    registre = RegistreDesDecisions(tmp_path / "d")
    registre.retenir(Regle("s1", "commande", "./x.sh", outil="Bash"))
    assert registre.regle_qui_couvre(_bash("./x.sh 2>&1 | tail -5")) is None, (
        "tail n'est pas accordé : on ne devine pas la liste des commandes sûres du CLI"
    )
    registre.retenir(Regle("s1", "commande", "tail:*", outil="Bash"))
    couvre = registre.regle_qui_couvre(_bash("./x.sh 2>&1 | tail -5"))
    assert couvre is not None and couvre.valeur == "./x.sh"
    assert registre.regle_qui_couvre(_bash("./x.sh | rm -rf /")) is None


def test_toutes_les_commandes_suggerees_sont_retenues() -> None:
    demande = Demande(
        request_id="r",
        session_id="s1",
        outil="Bash",
        arguments={"command": "make && ./deploy.sh"},
        suggestions=[
            {
                "type": "addRules",
                "rules": [
                    {"toolName": "Bash", "ruleContent": "make"},
                    {"toolName": "Bash", "ruleContent": "./deploy.sh"},
                ],
            }
        ],
    )
    regles = regles_suggerees(demande)
    assert [(r.portee, r.valeur, r.outil) for r in regles] == [
        ("commande", "make", "Bash"),
        ("commande", "./deploy.sh", "Bash"),
    ]


def test_les_regles_reviennent_au_cli_dans_sa_syntaxe() -> None:
    regles = [
        Regle("s1", "commande", "./x.sh", outil="Bash"),
        Regle("s1", "commande", "git status:*"),
        Regle("s1", "outil", "Write"),
        Regle("s1", "repertoire", "/home/onyxia/travail"),
    ]
    assert reglages_cli(regles) == {
        "permissions": {
            "allow": ["Bash(./x.sh)", "Bash(git status:*)", "Write"],
            "additionalDirectories": ["/home/onyxia/travail"],
        }
    }
    assert reglages_cli([]) == {}


def test_le_tour_suivant_recoit_les_regles_du_fil(tmp_path) -> None:
    """Un processus par tour : ce qu'il a retenu meurt avec lui, on le lui redonne."""
    harnais = ClaudeHarness(AtelierSettings(work_dir=tmp_path / "work"))
    assert harnais._arguments_des_regles("s1") == []
    harnais.decisions.retenir(Regle("s1", "commande", "./x.sh", outil="Bash"))
    drapeau, valeur = harnais._arguments_des_regles("s1")
    assert drapeau == "--settings"
    assert json.loads(valeur) == {"permissions": {"allow": ["Bash(./x.sh)"]}}
    assert harnais._arguments_des_regles("s2") == [], "rien ne fuit d'un fil à l'autre"


def test_l_autorisation_rend_au_cli_ses_suggestions() -> None:
    """Le CLI applique ce qu'on lui rend, sur-le-champ, pour ce processus."""
    permissions = permissions_a_retenir(_mesuree())
    assert len(permissions) == 1
    assert permissions[0]["destination"] == "session", (
        "on n'écrit pas dans les réglages du dossier, que d'autres fils partagent"
    )
    assert permissions[0]["rules"] == [{"toolName": "Bash", "ruleContent": "./x.sh"}]
    assert reponse_autorisee({}, permissions)["updatedPermissions"] == permissions
    assert "updatedPermissions" not in reponse_autorisee({}), (
        "une fois n'est pas toujours : rien n'est rendu sans qu'on l'ait choisi"
    )


def test_toujours_par_la_route_rend_et_retient(atelier: TestClient) -> None:
    registre = atelier.app.state.harness.decisions
    demande = _mesuree()
    demande.request_id = "tj2"
    demande.session_id = "s20"
    registre.poser(demande)
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    r = atelier.post(
        "/v1/decisions/tj2", headers=entete, json={"decision": "allow", "portee": "toujours"}
    )
    assert r.status_code == 200
    assert [x["valeur"] for x in r.json()["regles"]] == ["./x.sh"]
    rendue = registre.reponse("tj2")
    assert rendue is not None and rendue["updatedPermissions"][0]["destination"] == "session"
    assert [x.pour_le_cli() for x in registre.regles("s20")] == ["Bash(./x.sh)"]
    registre.clore("tj2")
    registre.oublier_les_regles("s20")


def test_une_seule_fois_ne_rend_rien_au_cli(atelier: TestClient) -> None:
    registre = atelier.app.state.harness.decisions
    demande = _mesuree()
    demande.request_id = "uf2"
    demande.session_id = "s21"
    registre.poser(demande)
    entete = {"Authorization": f"Bearer {_cle(atelier)}"}

    atelier.post("/v1/decisions/uf2", headers=entete, json={"decision": "allow"})
    rendue = registre.reponse("uf2")
    assert rendue is not None and "updatedPermissions" not in rendue
    assert registre.regles("s21") == []
    registre.clore("uf2")
