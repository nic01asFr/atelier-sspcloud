"""Secrets par références partout, une seule valeur : `~/work/.secrets/claude-env.sh`.

Le fichier effectif d'un tour et `~/.claude.json` portaient les jetons des
connecteurs en clair (audit du 25 septembre, Lecteur Grist). Ils ne portent
plus que des références `${ATELIER_MCP_…}` ; les valeurs sont dans un fichier
0600 que chargent le harnais, code-server, le shell et wikichat. Mesuré sur le
pod (2.1.281) : Claude Code développe ces références dans `--mcp-config`, la
portée utilisateur et le `.mcp.json` d'un projet.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import shutil
from pathlib import Path

import pytest

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.env_secrets import (
    chemin_du_fichier,
    ecrire_le_fichier,
    lire_le_fichier,
    rendu,
)
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.harness import ClaudeHarness
from mcp_gateway.atelier.mcp_sync import lier_le_projet, materialize_mcp_config, materialize_session_mcp
from mcp_gateway.atelier.vscode_handoff import environnement_du_claude_vscode
from mcp_gateway.db import connect

JETON = "jeton-onyxia-0123456789abcdef"
VARIABLE = "ATELIER_MCP_PASSERELLE_AUTHORIZATION"
CLE = "cle-proprietaire-0123456789"


def _preparer(reglages: AtelierSettings) -> None:
    conn = connect(reglages.gateway_db_path)
    try:
        IntegratedMcpStore(conn).upsert(
            "passerelle",
            {
                "type": "http",
                "url": "https://passerelle.exemple/mcp",
                "headers": {"Authorization": f"Bearer {JETON}"},
            },
        )
    finally:
        conn.close()
    reglages.owner_key_path.parent.mkdir(parents=True, exist_ok=True)
    reglages.owner_key_path.write_text(CLE, encoding="utf-8")


def test_le_fichier_porte_les_valeurs_et_se_relit(reglages: AtelierSettings) -> None:
    _preparer(reglages)
    valeurs = ecrire_le_fichier(reglages)
    chemin = chemin_du_fichier(reglages)
    assert chemin == reglages.secrets_dir / "claude-env.sh"
    assert valeurs[VARIABLE] == JETON and valeurs["ATELIER_MCP_KEY"] == CLE
    assert lire_le_fichier(chemin) == valeurs
    if os.name == "posix":
        assert stat.S_IMODE(chemin.stat().st_mode) == 0o600


def test_une_apostrophe_survit_au_shell(tmp_path: Path) -> None:
    valeurs = {"ATELIER_MCP_X": "a'b c$d\\e"}
    chemin = tmp_path / "claude-env.sh"
    chemin.write_text(rendu(valeurs), encoding="utf-8")
    assert lire_le_fichier(chemin) == valeurs
    bash = shutil.which("bash")
    if bash is None or os.name != "posix":
        pytest.skip("pas de shell POSIX ici")
    sortie = subprocess.run(
        [bash, "-c", f'. "{chemin}" && printf %s "$ATELIER_MCP_X"'],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert sortie == valeurs["ATELIER_MCP_X"]


def test_le_fichier_effectif_ne_porte_que_des_references(reglages: AtelierSettings, tmp_path: Path) -> None:
    _preparer(reglages)
    projet = tmp_path / "projet"
    projet.mkdir()
    chemin = materialize_session_mcp(reglages, "conv-1", kind="code", cwd=projet)
    texte = chemin.read_text(encoding="utf-8")
    assert JETON not in texte and CLE not in texte
    serveurs = json.loads(texte)["mcpServers"]
    assert serveurs["passerelle"]["headers"]["Authorization"] == f"Bearer ${{{VARIABLE}}}"


def test_un_jeton_propre_au_projet_suit_la_meme_regle_sur_toutes_les_surfaces(
    reglages: AtelierSettings, tmp_path: Path
) -> None:
    """Le tour de l'Atelier et le `.mcp.json` (VS Code, terminal) disent la même chose.

    Avant les profils, le tour gardait le jeton du projet quand le `.mcp.json`
    le remplaçait par la référence du pool : deux jetons pour une conversation
    selon la surface. Une seule fonction les écrit désormais : l'en-tête que
    le pool connaît devient sa référence partout, et aucun secret en clair
    ne reste dans le dossier du projet.
    """
    _preparer(reglages)
    projet = tmp_path / "projet"
    projet.mkdir()
    (projet / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "passerelle": {
                        "type": "http",
                        "url": "https://passerelle.exemple/mcp",
                        "headers": {"Authorization": "Bearer autre-jeton-du-projet"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    chemin = materialize_session_mcp(reglages, "conv-2", kind="code", cwd=projet)
    serveurs = json.loads(chemin.read_text(encoding="utf-8"))["mcpServers"]
    lier_le_projet(reglages, projet)
    du_projet = json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    assert serveurs["passerelle"] == du_projet["passerelle"]
    assert serveurs["passerelle"]["headers"]["Authorization"] == f"Bearer ${{{VARIABLE}}}"
    assert "autre-jeton-du-projet" not in (projet / ".mcp.json").read_text(encoding="utf-8")


def test_la_portee_utilisateur_ne_porte_aucun_secret(reglages: AtelierSettings) -> None:
    _preparer(reglages)
    materialize_mcp_config(reglages)
    for chemin in (
        Path.home() / ".claude.json",
        reglages.work_dir / ".claude.json",
        reglages.mcp_config_path,
        reglages.work_dir / ".claude" / "mcp-config.json",
    ):
        texte = chemin.read_text(encoding="utf-8")
        assert JETON not in texte and CLE not in texte, chemin
    pont = json.loads(reglages.mcp_config_path.read_text(encoding="utf-8"))["mcpServers"]
    assert pont["passerelle"]["headers"]["Authorization"] == f"Bearer ${{{VARIABLE}}}"


def test_harnais_vscode_et_shell_ont_les_memes_valeurs(reglages: AtelierSettings) -> None:
    _preparer(reglages)
    env = ClaudeHarness(reglages)._env()
    vscode = environnement_du_claude_vscode(reglages)
    shell = lire_le_fichier(chemin_du_fichier(reglages))
    for nom, valeur in shell.items():
        assert env[nom] == valeur
        assert vscode[nom] == valeur
    assert shell[VARIABLE] == JETON


def test_un_jeton_renouvele_suit_au_tour_suivant(reglages: AtelierSettings) -> None:
    _preparer(reglages)
    ClaudeHarness(reglages)._env()
    reglages.owner_key_path.write_text("nouvelle-cle-0123456789", encoding="utf-8")
    assert ClaudeHarness(reglages)._env()["ATELIER_MCP_KEY"] == "nouvelle-cle-0123456789"
    assert lire_le_fichier(chemin_du_fichier(reglages))["ATELIER_MCP_KEY"] == "nouvelle-cle-0123456789"


def test_l_init_fait_charger_le_fichier_par_le_shell(tmp_path: Path) -> None:
    """Le bloc de l'init, exécuté deux fois : une seule ligne dans ~/.bashrc."""
    bash = shutil.which("bash")
    if bash is None or os.name != "posix":
        pytest.skip("pas de shell POSIX ici")
    init = (Path(__file__).resolve().parents[2] / "install" / "atelier-init.sh").read_text(encoding="utf-8")
    debut = init.index('ENV_SECRETS="$SECRETS/claude-env.sh"')
    fin = init.index("fi\nfi\n", debut) + len("fi\nfi\n")
    bloc = init[debut:fin]
    maison = tmp_path / "maison"
    maison.mkdir()
    script = f'dire() {{ :; }}\nSECRETS="{tmp_path}/secrets"\n' + bloc
    for _ in range(2):
        subprocess.run([bash, "-c", script], env={"HOME": str(maison), "PATH": os.environ["PATH"]}, check=True)
    bashrc = (maison / ".bashrc").read_text(encoding="utf-8")
    assert bashrc.count(f"{tmp_path}/secrets/claude-env.sh") == 2  # test et source, sur une ligne
    assert len([l for l in bashrc.splitlines() if "claude-env.sh" in l]) == 1
