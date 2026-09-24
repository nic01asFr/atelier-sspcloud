"""Le sondage stdio ne doit pas planter sur un import oublié."""

from __future__ import annotations


def test_resoudre_commande_sans_path_ne_leve_pas_nameerror(monkeypatch) -> None:
    """`npx` absent du PATH tombait sur `Path.home()` alors que Path n'était pas importé."""
    from mcp_gateway.atelier.stdio_probe import resoudre_commande

    monkeypatch.setattr("mcp_gateway.atelier.stdio_probe.shutil.which", lambda _: None)
    assert resoudre_commande("npx-absent") == ""
