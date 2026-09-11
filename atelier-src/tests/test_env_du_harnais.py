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
