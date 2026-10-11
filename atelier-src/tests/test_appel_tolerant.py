"""`gateway_call_tool` comprend les formes d'appel que les modèles se trompent à écrire."""

from __future__ import annotations

from mcp_gateway.mcp.appel_tolerant import lire_appel, rappel


def test_un_appel_juste_ne_dit_rien() -> None:
    lu = lire_appel({"name": "atelier_projets", "arguments": {"a": 1}})
    assert (lu.cible, lu.arguments, lu.erreur) == ("atelier_projets", {"a": 1}, None)
    assert rappel(lu) == ""


def test_arguments_envoyes_comme_texte_json() -> None:
    lu = lire_appel({"name": "x", "arguments": '{"query": "journal"}'})
    assert lu.erreur is None and lu.arguments == {"query": "journal"}
    assert "objet JSON" in rappel(lu)


def test_arguments_a_plat_a_cote_du_nom() -> None:
    lu = lire_appel({"name": "x", "query": "journal", "limit": 3})
    assert lu.arguments == {"query": "journal", "limit": 3}
    assert "dans `arguments`" in rappel(lu)


def test_mauvais_noms_de_champ() -> None:
    lu = lire_appel({"tool": "x", "parameters": {"q": 1}})
    assert (lu.cible, lu.arguments) == ("x", {"q": 1})
    assert "pas `tool`" in rappel(lu) and "pas `parameters`" in rappel(lu)


def test_l_appel_imbrique_dans_gateway_call_tool_est_deroule() -> None:
    lu = lire_appel({"name": "gateway_call_tool", "arguments": {"name": "x", "arguments": {"q": 1}}})
    assert (lu.cible, lu.arguments, lu.erreur) == ("x", {"q": 1}, None)
    assert "par lui-même" in rappel(lu)


def test_l_appel_recursif_sans_cible_est_refuse_avec_la_forme_attendue() -> None:
    lu = lire_appel({"name": "gateway_call_tool"})
    assert lu.erreur and "Appel récursif" in lu.erreur and '"name"' in lu.erreur


def test_le_nom_manquant_montre_un_exemple() -> None:
    lu = lire_appel({"arguments": {}})
    assert lu.erreur and "atelier_projets" in lu.erreur


def test_arguments_illisibles_sont_expliques() -> None:
    lu = lire_appel({"name": "x", "arguments": "pas du json"})
    assert lu.erreur and "objet JSON" in lu.erreur
    assert lire_appel({"name": "x", "arguments": [1, 2]}).erreur


def test_champs_en_trop_a_cote_d_arguments_remplis() -> None:
    lu = lire_appel({"name": "x", "arguments": {"a": 1}, "b": 2})
    assert lu.erreur and "b" in lu.erreur


def test_arguments_vides_ou_nuls() -> None:
    assert lire_appel({"name": "x", "arguments": None}).arguments == {}
    assert lire_appel({"name": "x"}).arguments == {}
