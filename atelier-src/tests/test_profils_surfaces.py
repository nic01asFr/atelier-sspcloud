"""Un profil par type d'acteur, le même sur toutes les surfaces (docs/vision/profils-acces.md).

L'app (fichier effectif d'un tour), VS Code et le terminal (le `.mcp.json` du
dossier, approuvé dans `~/.claude.json`) lisent ce que calcule une seule
fonction, `configuration_du_profil`. Ces tests passent par les vraies
fonctions d'écriture et relisent les fichiers produits.
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.mcp_sync import (
    ENTETE_PROFIL,
    SELECTION,
    SERVICE_ATELIER,
    configuration_du_profil,
    lier_le_projet,
    lier_tous_les_projets,
    materialize_mcp_config,
    materialize_session_mcp,
    noter_les_sondes,
    project_binding_state,
    resoudre_les_variables,
    write_project_binding,
)
from mcp_gateway.db import connect

ONYXIA = {"type": "http", "url": "https://onyxia.exemple/mcp", "headers": {"Authorization": "Bearer jeton-onyxia-0123456789"}}
WIKICHAT = {"type": "sse", "url": "http://127.0.0.1:3777/sse?agent=atelier"}


def _pool(reglages: AtelierSettings, **serveurs: dict) -> None:
    conn = connect(reglages.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        for nom, cfg in serveurs.items():
            store.upsert(nom, cfg)
    finally:
        conn.close()


def _lire(chemin: Path) -> dict:
    return json.loads(chemin.read_text(encoding="utf-8"))["mcpServers"]


def _approuves(dossier: Path) -> list[str]:
    donnees = json.loads((Path.home() / ".claude.json").read_text(encoding="utf-8"))
    return donnees["projects"][str(dossier)]["enabledMcpjsonServers"]


def _pool_complet(reglages: AtelierSettings) -> None:
    _pool(
        reglages,
        Onyxia=ONYXIA,
        wikichat=WIKICHAT,
        qgis={"type": "http", "url": "http://qgis/mcp", "headers": {"Authorization": "Bearer jeton-qgis-1234567890"}},
        n8n={"type": "http", "url": "http://n8n/mcp", "headers": {"Authorization": "Bearer jeton-n8n-1234567890"}},
    )


def test_code_la_meme_configuration_pour_les_trois_surfaces(reglages: AtelierSettings) -> None:
    _pool_complet(reglages)
    projet = reglages.projects_dir / "lecteur"
    lier_le_projet(reglages, projet)
    vscode_et_terminal = _lire(projet / ".mcp.json")
    app = _lire(materialize_session_mcp(reglages, "conv-1", kind="code", cwd=projet))

    # Mêmes serveurs partout, approuvés pour VS Code et le terminal.
    assert set(app) == set(vscode_et_terminal) == set(_approuves(projet))
    # Mêmes déclarations : l'app ne fait que résoudre la conversation.
    for nom, cfg in vscode_et_terminal.items():
        assert app[nom] == resoudre_les_variables(cfg, session="conv-1", agent=""), nom
    # Et c'est bien la fonction du profil qui les écrit.
    assert vscode_et_terminal == configuration_du_profil(reglages, profil="code", cwd=projet)


def test_code_porte_son_profil_vers_atelier_et_wikichat(reglages: AtelierSettings) -> None:
    """Contrats a et b."""
    _pool_complet(reglages)
    projet = reglages.projects_dir / "lecteur"
    lier_le_projet(reglages, projet)
    serveurs = _lire(projet / ".mcp.json")
    assert serveurs[SERVICE_ATELIER]["headers"][ENTETE_PROFIL] == "code"
    assert "X-Atelier-Conversation" in serveurs[SERVICE_ATELIER]["headers"]
    env = serveurs["wikichat"]["env"]
    assert env["WIKICHAT_PROFIL"] == "code" and env["WIKICHAT_PROJET"] == "lecteur"
    app = _lire(materialize_session_mcp(reglages, "conv-9", kind="code", cwd=projet))
    assert app[SERVICE_ATELIER]["headers"]["X-Atelier-Conversation"] == "conv-9"
    assert app[SERVICE_ATELIER]["headers"][ENTETE_PROFIL] == "code"


def test_code_sans_onyxia_ni_porte_deguisee_vers_les_meta_outils(reglages: AtelierSettings) -> None:
    """G3 : plus d'Onyxia imposé ; et aucune entrée vers `/mcp` sans l'en-tête de profil.

    Même choisi dans le projet, Onyxia ne vient que de `onyxia_pour_projet`,
    qui (bouchon) ne donne rien à un agent code.
    """
    _pool_complet(reglages)
    _pool(reglages, passerelle={"type": "http", "url": f"http://localhost:{reglages.port}/mcp"})
    projet = reglages.projects_dir / "choisit-tout"
    write_project_binding(reglages, projet, ["Onyxia", "qgis", "passerelle", "Onyxia_nic01asfr"])
    for serveurs in (
        _lire(projet / ".mcp.json"),
        _lire(materialize_session_mcp(reglages, "c", kind="code", cwd=projet)),
    ):
        assert "Onyxia" not in serveurs
        assert "passerelle" not in serveurs and "Onyxia_nic01asfr" not in serveurs
        portes = [n for n, c in serveurs.items() if f":{reglages.port}/mcp" in str(c.get("url", ""))]
        assert portes == [SERVICE_ATELIER]
    # Le choix de la personne, lui, est gardé.
    choix = json.loads((projet / SELECTION).read_text(encoding="utf-8"))["mcpServers"]
    assert choix["Onyxia"] == {"enabled": True}


def test_le_module_de_l_equipe_o_fait_foi_des_qu_il_existe(
    reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contrat c : `onyxia_pour_projet(settings, slug, profil) -> dict | None`."""
    appels: list[tuple[str, str]] = []

    def onyxia_pour_projet(settings: AtelierSettings, slug: str, profil: str) -> dict | None:
        appels.append((slug, profil))
        return {"type": "http", "url": f"https://onyxia.exemple/pod/{slug}"} if slug == "deploye" else None

    module = types.ModuleType("mcp_gateway.atelier.onyxia_projet")
    module.onyxia_pour_projet = onyxia_pour_projet  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp_gateway.atelier.onyxia_projet", module)
    _pool_complet(reglages)
    deploye = reglages.projects_dir / "deploye"
    autre = reglages.projects_dir / "autre"
    lier_le_projet(reglages, deploye)
    lier_le_projet(reglages, autre)
    assert _lire(deploye / ".mcp.json")["Onyxia"]["url"] == "https://onyxia.exemple/pod/deploye"
    assert "Onyxia" not in _lire(autre / ".mcp.json")
    assert ("deploye", "code") in appels and ("autre", "code") in appels


def test_assistant_converti_au_format_claude_code(reglages: AtelierSettings) -> None:
    """M3 : l'ancien « binding » de l'Assistant devient une vraie déclaration, relié au démarrage."""
    _pool_complet(reglages)
    racine = reglages.assistant_root
    racine.mkdir(parents=True, exist_ok=True)
    (racine / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"wikichat": {"enabled": True}, "qgis": {"enabled": False}}}),
        encoding="utf-8",
    )
    session = reglages.assistant_sessions_dir / "s1"
    session.mkdir(parents=True)
    (session / ".mcp.json").write_text(json.dumps({"mcpServers": {"filesystem": {"enabled": False}}}), encoding="utf-8")

    lier_tous_les_projets(reglages)

    for dossier in (racine, session):
        serveurs = _lire(dossier / ".mcp.json")
        assert all(set(c) - {"enabled"} for c in serveurs.values()), dossier
        assert serveurs[SERVICE_ATELIER]["headers"][ENTETE_PROFIL] == "assistant"
        assert serveurs["wikichat"]["env"]["WIKICHAT_PROFIL"] == "assistant"
        # Onyxia au complet pour l'Assistant (bouchon : l'entrée du pool, en référence).
        assert serveurs["Onyxia"]["url"] == ONYXIA["url"]
        assert "jeton-onyxia" not in (dossier / ".mcp.json").read_text(encoding="utf-8")
        # Les autres outils passent par la passerelle : qgis n'est pas en natif.
        assert "qgis" not in serveurs
        assert set(_approuves(dossier)) == set(serveurs)
    # Le choix d'avant est rangé hors du `.mcp.json`.
    assert json.loads((racine / SELECTION).read_text(encoding="utf-8"))["mcpServers"]["qgis"] == {"enabled": False}
    # Et le tour de l'Atelier reçoit la même chose.
    app = _lire(materialize_session_mcp(reglages, "a1", kind="assistant", cwd=session))
    assert set(app) == set(_lire(session / ".mcp.json"))


def test_un_connecteur_refuse_en_authentification_n_est_plus_distribue(reglages: AtelierSettings) -> None:
    """M5 : n8n en 401 disparaît de toutes les surfaces, est signalé, et revient après une sonde réussie."""
    _pool_complet(reglages)
    projet = reglages.projects_dir / "p"
    write_project_binding(reglages, projet, ["qgis", "n8n"])
    assert "n8n" in _lire(projet / ".mcp.json")

    assert noter_les_sondes(reglages, {"registry:n8n": "error: HTTP 401 Unauthorized", "registry:qgis": "connected"})
    assert "n8n" not in _lire(projet / ".mcp.json")
    assert "n8n" not in _lire(materialize_session_mcp(reglages, "c", kind="code", cwd=projet))
    assert "n8n" not in _approuves(projet)
    etat = {e["id"]: e for e in project_binding_state(reglages, projet)}
    assert etat["n8n"]["echec_authentification"] == 401 and etat["n8n"]["distribue"] is False
    assert etat["n8n"]["active"] is True  # toujours choisi
    # Rien du message d'erreur n'est gardé.
    assert "Unauthorized" not in (reglages.mcp_dir / "sondes-authentification.json").read_text(encoding="utf-8")

    assert not noter_les_sondes(reglages, {"registry:n8n": "error: HTTP 401 Unauthorized"})
    assert noter_les_sondes(reglages, {"registry:n8n": "connected"})
    assert "n8n" in _lire(projet / ".mcp.json")


def test_l_ancien_chrome_devtools_quitte_les_portees_de_projet(reglages: AtelierSettings) -> None:
    """M4 : le serveur de l'ancien service part de `~/.claude.json` à la matérialisation."""
    maison = Path.home() / ".claude.json"
    maison.write_text(
        json.dumps(
            {
                "userID": "moi",
                "projects": {
                    "/w/projets/nouveau-projet": {
                        "mcpServers": {"chrome-devtools": {"type": "http", "url": "http://127.0.0.1:3000/mcp"}},
                        "hasTrustDialogAccepted": True,
                    },
                    "/w/projets/garde": {"mcpServers": {"a-moi": {"type": "http", "url": "http://x/mcp"}}},
                },
            }
        ),
        encoding="utf-8",
    )
    materialize_mcp_config(reglages)
    donnees = json.loads(maison.read_text(encoding="utf-8"))
    assert "mcpServers" not in donnees["projects"]["/w/projets/nouveau-projet"]
    assert donnees["projects"]["/w/projets/nouveau-projet"]["hasTrustDialogAccepted"] is True
    assert donnees["projects"]["/w/projets/garde"]["mcpServers"] == {"a-moi": {"type": "http", "url": "http://x/mcp"}}
    assert donnees["userID"] == "moi"
