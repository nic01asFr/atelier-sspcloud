"""Ce que nos tours reçoivent d'environnement, sans dépendre du fichier global.

Le fichier de réglages du CLI est partagé avec VS Code et avec d'autres mains ;
deux valeurs de compaction s'y sont contredites. Nos propres processus doivent
recevoir la bonne directement.
"""

from __future__ import annotations

from mcp_gateway.atelier.harness import ClaudeHarness


def test_nos_tours_recoivent_leur_fenetre_de_compaction(reglages) -> None:
    env = ClaudeHarness(reglages)._env()
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == str(reglages.cli_fenetre_compaction)
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == str(reglages.cli_contexte_max)


def test_la_fenetre_de_nos_tours_est_sous_leur_plafond(reglages) -> None:
    """Réglée à l'envers, la compaction ne se déclencherait jamais."""
    env = ClaudeHarness(reglages)._env()
    assert int(env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"]) < int(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"])


def test_nos_tours_partent_avec_un_effort_que_le_repli_accepte(reglages) -> None:
    """Trois conversations sont mortes sur « Unexpected reasoning effort high ».

    Le CLI part en `high` par défaut ; le modèle de repli de la passerelle le
    refuse. Un lot entier de travail non commité a été perdu ainsi le 14
    septembre, en plein milieu d'une commande.
    """
    from mcp_gateway.atelier.harness import EFFORT_SUR_LA_PASSERELLE

    env = ClaudeHarness(reglages)._env()
    assert env["CLAUDE_CODE_EFFORT_LEVEL"] == EFFORT_SUR_LA_PASSERELLE
    assert EFFORT_SUR_LA_PASSERELLE in ("low", "medium", "xhigh"), "ce que le repli accepte"


def test_un_effort_choisi_pour_le_service_prime(reglages) -> None:
    reglages.effort = "low"
    assert ClaudeHarness(reglages)._env()["CLAUDE_CODE_EFFORT_LEVEL"] == "low"
