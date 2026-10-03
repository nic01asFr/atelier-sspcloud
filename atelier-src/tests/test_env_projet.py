"""`.atelier/env.json` : les variables d'un projet, par référence à des secrets.

Le cas qui l'a fait naître : un `.mcp.json` de projet qui écrit
`"Authorization": "Bearer ${VOICE_TOKEN}"` pour un serveur MCP local, et
aucune session qui ait `VOICE_TOKEN` dans son environnement — 401. Ces tests
tiennent que la valeur arrive aux tours et à VS Code, sans jamais s'écrire
dans le projet, et que les murs des secrets tiennent.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.env_projet import (
    empreinte,
    lire_references,
    variables_de_tous_les_projets,
    variables_du_projet,
)
from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.vscode_handoff import claude_extension_env, environnement_du_claude_vscode

posix = pytest.mark.skipif(os.name != "posix", reason="droits de fichiers POSIX")


@pytest.fixture()
def reglages(tmp_path: Path) -> AtelierSettings:
    settings = AtelierSettings(work_dir=tmp_path / "work")
    settings.ensure_dirs()
    return settings


def secret(settings: AtelierSettings, ref: str, valeur: str, mode: int = 0o600) -> None:
    chemin = settings.secrets_dir / ref
    chemin.write_text(valeur + "\n", encoding="utf-8")
    os.chmod(chemin, mode)


def projet(settings: AtelierSettings, slug: str, declare: object) -> Path:
    racine = settings.projects_dir / slug
    (racine / ".atelier").mkdir(parents=True)
    (racine / ".atelier" / "env.json").write_text(
        declare if isinstance(declare, str) else json.dumps(declare), encoding="utf-8"
    )
    return racine


def test_la_reference_devient_une_variable(reglages: AtelierSettings) -> None:
    secret(reglages, "voice_token", "jeton-voix")
    racine = projet(reglages, "voix", {"VOICE_TOKEN": "voice_token"})
    assert variables_du_projet(reglages.secrets_dir, racine) == {"VOICE_TOKEN": "jeton-voix"}
    # La valeur n'est écrite nulle part dans le projet.
    for fichier in racine.rglob("*"):
        if fichier.is_file():
            assert "jeton-voix" not in fichier.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "declare",
    [
        {"ATELIER_OWNER_KEY": "voice_token"},
        {"ANTHROPIC_BASE_URL": "voice_token"},
        {"CLAUDE_CODE_EFFORT_LEVEL": "voice_token"},
        {"PATH": "voice_token"},
        {"LD_PRELOAD": "voice_token"},
        {"minuscule": "voice_token"},
        {"JETON": "../atelier_owner_key"},
        {"JETON": "sous/dossier"},
        {"JETON": 12},
    ],
)
def test_les_murs_tiennent(reglages: AtelierSettings, declare: dict) -> None:
    secret(reglages, "voice_token", "x")
    racine = projet(reglages, "voix", declare)
    assert lire_references(racine) == {}
    assert variables_du_projet(reglages.secrets_dir, racine) == {}


def test_un_fichier_faux_ne_casse_rien(reglages: AtelierSettings) -> None:
    assert lire_references(projet(reglages, "a", "{pas du json")) == {}
    assert lire_references(projet(reglages, "b", ["VOICE_TOKEN"])) == {}
    assert variables_du_projet(reglages.secrets_dir, reglages.projects_dir / "absent") == {}


def test_un_secret_manquant_est_saute(reglages: AtelierSettings) -> None:
    secret(reglages, "present", "p")
    racine = projet(reglages, "voix", {"PRESENT": "present", "ABSENT": "absent"})
    assert variables_du_projet(reglages.secrets_dir, racine) == {"PRESENT": "p"}


@posix
def test_un_secret_lisible_par_d_autres_est_refuse(reglages: AtelierSettings) -> None:
    secret(reglages, "voice_token", "x", mode=0o644)
    racine = projet(reglages, "voix", {"VOICE_TOKEN": "voice_token"})
    assert variables_du_projet(reglages.secrets_dir, racine) == {}


def test_les_tours_du_projet_la_recoivent(reglages: AtelierSettings) -> None:
    secret(reglages, "voice_token", "jeton-voix")
    racine = projet(reglages, "voix", {"VOICE_TOKEN": "voice_token"})
    harnais = ClaudeHarness(reglages)
    assert harnais._env("agent", racine)["VOICE_TOKEN"] == "jeton-voix"
    # Un autre projet la reçoit aussi : le harnais charge le fichier
    # d'environnement unique, comme VS Code et le shell, qui ne savent pas
    # d'avance quel projet les attend (docs/archives/chantiers/coherence-projet.md, lot A). Même
    # environnement sur toutes les surfaces plutôt qu'un cloisonnement que
    # seul l'Atelier tenait.
    autre = reglages.projects_dir / "autre"
    autre.mkdir()
    assert harnais._env("agent", autre)["VOICE_TOKEN"] == "jeton-voix"


def test_la_valeur_du_projet_prime_sur_la_reunion(reglages: AtelierSettings) -> None:
    """Deux projets, un même nom, deux secrets : chaque tour a celui de son projet."""
    secret(reglages, "voix_a", "jeton-a")
    secret(reglages, "voix_b", "jeton-b")
    a = projet(reglages, "a", {"VOICE_TOKEN": "voix_a"})
    b = projet(reglages, "b", {"VOICE_TOKEN": "voix_b"})
    harnais = ClaudeHarness(reglages)
    assert harnais._env("agent", a)["VOICE_TOKEN"] == "jeton-a"
    assert harnais._env("agent", b)["VOICE_TOKEN"] == "jeton-b"


def test_un_secret_change_relance_le_processus(reglages: AtelierSettings) -> None:
    secret(reglages, "voice_token", "ancien")
    racine = projet(reglages, "voix", {"VOICE_TOKEN": "voice_token"})
    avant = empreinte(variables_du_projet(reglages.secrets_dir, racine))
    secret(reglages, "voice_token", "neuf")
    apres = empreinte(variables_du_projet(reglages.secrets_dir, racine))
    assert avant and apres and avant != apres
    assert "neuf" not in apres and "ancien" not in avant
    e1 = ClaudeHarness._empreinte(racine, None, "acceptEdits", "", "a", None, avant)
    e2 = ClaudeHarness._empreinte(racine, None, "acceptEdits", "", "a", None, apres)
    assert e1 != e2


def test_vs_code_recoit_celles_de_tous_les_projets(reglages: AtelierSettings) -> None:
    secret(reglages, "voice_token", "jeton-voix")
    secret(reglages, "autre", "valeur-autre")
    projet(reglages, "voix", {"VOICE_TOKEN": "voice_token"})
    projet(reglages, "zeta", {"VOICE_TOKEN": "autre", "AUTRE": "autre"})
    reunies = variables_de_tous_les_projets(reglages.secrets_dir, reglages.projects_dir)
    # Conflit de nom : le premier projet par ordre alphabétique le garde.
    assert reunies == {"VOICE_TOKEN": "jeton-voix", "AUTRE": "valeur-autre"}
    # Par l'enveloppeur, qui source le fichier unique ; jamais par les réglages.
    env = environnement_du_claude_vscode(reglages)
    assert env["VOICE_TOKEN"] == "jeton-voix"
    reglages_vscode = {e["name"] for e in claude_extension_env(reglages)}
    assert "VOICE_TOKEN" not in reglages_vscode


RESERVES = ["atelier_owner_key", "atelier_internal_secret", "atelier_lanceur_key", "llm_api_key", "claude-env.sh", "atelier_futur"]


@posix
@pytest.mark.parametrize("ref", RESERVES)
def test_un_projet_ne_peut_pas_se_faire_donner_une_cle_de_l_atelier(reglages: AtelierSettings, ref: str) -> None:
    """Relecture du 03/10 : `{"X": "atelier_owner_key"}` donnait la clé du propriétaire à l'agent."""
    secret(reglages, ref, "cle-de-l-atelier")
    racine = projet(reglages, "piege", {"X": ref, "VOICE_TOKEN": "voice_token"})
    secret(reglages, "voice_token", "jeton-voix")
    assert variables_du_projet(reglages.secrets_dir, racine) == {"VOICE_TOKEN": "jeton-voix"}


@posix
@pytest.mark.parametrize("ref", RESERVES)
def test_la_lecture_elle_meme_refuse_les_cles_de_l_atelier(reglages: AtelierSettings, ref: str) -> None:
    """Le mur est dans `lire_secret`, donc vaut aussi pour les applications."""
    from mcp_gateway.atelier.apps.secrets import SecretIllisible, lire_secret

    secret(reglages, ref, "cle-de-l-atelier")
    with pytest.raises(SecretIllisible, match="réservé"):
        lire_secret(reglages.secrets_dir, ref)
