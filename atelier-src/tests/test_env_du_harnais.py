"""Ce que nos tours reçoivent d'environnement, sans dépendre du fichier global.

Le fichier de réglages du CLI est partagé avec VS Code et avec d'autres mains ;
son `env` l'emporte même sur l'environnement du processus (mesuré, 2.1.281).
Ce que nos tours doivent imposer passe donc aussi par `--settings`, qui, lui,
l'emporte sur le fichier (mesuré aussi).
"""

from __future__ import annotations

import json

import pytest

from mcp_gateway.atelier import relais_llm
from mcp_gateway.atelier.config import FENETRES_DES_MODELES, OBSOLETES
from mcp_gateway.atelier.harness import ClaudeHarness


def test_nos_tours_recoivent_la_fenetre_du_modele(reglages) -> None:
    env = ClaudeHarness(reglages)._env(model="qwen3-8-27b")
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == str(FENETRES_DES_MODELES["qwen3-8-27b"])
    assert env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "8192"


def test_les_anciens_reglages_herites_sont_retires(reglages, monkeypatch) -> None:
    for ancien in OBSOLETES:
        monkeypatch.setenv(ancien, "30000")
    env = ClaudeHarness(reglages)._env()
    for ancien in OBSOLETES:
        assert ancien not in env


def test_avec_le_relais_nos_tours_passent_par_lui(reglages, monkeypatch) -> None:
    monkeypatch.setattr(relais_llm, "relais_en_service", lambda s, **k: True)
    h = ClaudeHarness(reglages)
    assert h._env()["ANTHROPIC_BASE_URL"] == f"http://127.0.0.1:{reglages.relais_llm_port}"


def test_sans_relais_nos_tours_vont_a_la_passerelle(reglages) -> None:
    """Le relais absent (port sans personne) : repli sur la passerelle."""
    assert ClaudeHarness(reglages)._env()["ANTHROPIC_BASE_URL"] == reglages.anthropic_base_url


def test_l_environnement_impose_passe_aussi_par_settings(reglages, monkeypatch) -> None:
    monkeypatch.setattr(relais_llm, "relais_en_service", lambda s, **k: True)
    drapeau, valeur = ClaudeHarness(reglages)._arguments_de_reglages("s1", "qwen3-6-35b-moe")
    assert drapeau == "--settings"
    env = json.loads(valeur)["env"]
    assert env["ANTHROPIC_BASE_URL"].startswith("http://127.0.0.1:")
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "131072"


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


@pytest.mark.parametrize("modele", [None, "", "modele-inconnu"])
def test_un_modele_inconnu_recoit_la_fenetre_par_defaut(reglages, modele) -> None:
    assert ClaudeHarness(reglages)._env(model=modele)["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "131072"
