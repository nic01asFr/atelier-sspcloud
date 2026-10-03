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
    """Contrat c : `onyxia_pour_projet(settings, slug, profil, *, pool=None) -> dict | None`, nom `Onyxia`."""
    appels: list[tuple[str, str, bool]] = []

    def onyxia_pour_projet(
        settings: AtelierSettings, slug: str, profil: str, *, pool: dict | None = None
    ) -> dict | None:
        appels.append((slug, profil, pool is not None and "Onyxia" in pool))
        if slug != "deploye":
            return None
        return {
            "type": "http",
            "url": f"http://127.0.0.1:{settings.port}/mcp/onyxia/projet/{slug}",
            "headers": {"Authorization": "Bearer ${ATELIER_MCP_KEY}"},
        }

    module = types.ModuleType("mcp_gateway.atelier.onyxia_projet")
    module.onyxia_pour_projet = onyxia_pour_projet  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp_gateway.atelier.onyxia_projet", module)
    _pool_complet(reglages)
    deploye = reglages.projects_dir / "deploye"
    autre = reglages.projects_dir / "autre"
    lier_le_projet(reglages, deploye)
    lier_le_projet(reglages, autre)
    assert _lire(deploye / ".mcp.json")["Onyxia"]["url"] == f"http://127.0.0.1:{reglages.port}/mcp/onyxia/projet/deploye"
    assert "Onyxia" not in _lire(autre / ".mcp.json")
    # Le pool lui est passé, Onyxia compris.
    assert ("deploye", "code", True) in appels and ("autre", "code", True) in appels


def test_la_liste_des_services_du_projet_dit_ce_que_l_agent_recoit_d_onyxia(
    reglages: AtelierSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Constat du 03/10 : « Services du projet » cochait Onyxia, l'agent n'avait aucun outil Onyxia.

    `active` est le choix ; `distribue` est ce que l'agent reçoit. Onyxia ne vient que
    d'un déploiement déclaré : sans lui, la ligne le dit au lieu de promettre.
    """

    def onyxia_pour_projet(settings, slug, profil, *, pool=None):  # noqa: ANN001
        return {"type": "http", "url": "http://x/mcp/onyxia"} if slug == "deploye" else None

    module = types.ModuleType("mcp_gateway.atelier.onyxia_projet")
    module.onyxia_pour_projet = onyxia_pour_projet  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "mcp_gateway.atelier.onyxia_projet", module)
    _pool_complet(reglages)
    for slug in ("deploye", "autre"):
        write_project_binding(reglages, reglages.projects_dir / slug, ["Onyxia", "qgis"])

    sans = {e["id"]: e for e in project_binding_state(reglages, reglages.projects_dir / "autre")}
    assert sans["Onyxia"]["active"] is True, "le choix est gardé"
    assert sans["Onyxia"]["distribue"] is False and sans["Onyxia"]["par_deploiement"] is True
    assert "déploiement" in sans["Onyxia"]["raison"] and "Assistant" in sans["Onyxia"]["raison"]
    assert "distribue" not in sans["qgis"], "un autre service n'est pas concerné"

    avec = {e["id"]: e for e in project_binding_state(reglages, reglages.projects_dir / "deploye")}
    assert avec["Onyxia"]["distribue"] is True and avec["Onyxia"]["par_deploiement"] is True


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
        # Onyxia au complet pour l'Assistant, par le mandataire de la passerelle.
        assert serveurs["Onyxia"]["url"] == f"http://127.0.0.1:{reglages.port}/mcp/onyxia"
        assert serveurs["Onyxia"]["headers"]["Authorization"] == "Bearer ${ATELIER_MCP_KEY}"
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


def test_aucune_surface_ne_joint_plus_onyxia_en_direct(reglages: AtelierSettings) -> None:
    """Contrat de l'équipe O : Onyxia passe par le mandataire `/mcp/onyxia`, jamais en direct.

    Ni les `.mcp.json` (projet et Assistant), ni le fichier effectif d'un tour,
    ni `claude-mcp.json`, ni `~/.claude.json` (racine et portées de projet)
    ne portent plus l'adresse du service Onyxia.
    """
    _pool_complet(reglages)
    maison = Path.home() / ".claude.json"
    projet = reglages.projects_dir / "p"
    maison.write_text(
        json.dumps({"projects": {str(projet): {"mcpServers": {"Onyxia": ONYXIA, "autre": {"type": "http", "url": ONYXIA["url"]}}}}}),
        encoding="utf-8",
    )
    reglages.assistant_root.mkdir(parents=True, exist_ok=True)
    (projet / ".mcp.json").parent.mkdir(parents=True, exist_ok=True)
    (projet / ".mcp.json").write_text(json.dumps({"mcpServers": {"Onyxia": ONYXIA}}), encoding="utf-8")
    materialize_mcp_config(reglages)
    fichiers = [
        projet / ".mcp.json",
        reglages.assistant_root / ".mcp.json",
        materialize_session_mcp(reglages, "c", kind="code", cwd=projet),
        materialize_session_mcp(reglages, "a", kind="assistant", cwd=reglages.assistant_root),
        reglages.mcp_config_path,
        reglages.work_dir / ".claude" / "mcp-config.json",
        reglages.work_dir / ".claude.json",
        maison,
    ]
    for fichier in fichiers:
        assert ONYXIA["url"] not in fichier.read_text(encoding="utf-8"), fichier
    # L'Assistant garde Onyxia, par le mandataire.
    assert _lire(reglages.assistant_root / ".mcp.json")["Onyxia"]["url"].endswith("/mcp/onyxia")


# --- En-têtes de l'entrée `atelier`, par surface et par profil ----------------


def _entetes_par_surface(reglages: AtelierSettings, dossier: Path, kind: str) -> dict[str, dict]:
    lier_le_projet(reglages, dossier, kind=kind)
    effectif = _lire(materialize_session_mcp(reglages, "conv-e", kind=kind, cwd=dossier))
    return {
        "app": effectif[SERVICE_ATELIER],
        "vscode-terminal": _lire(dossier / ".mcp.json")[SERVICE_ATELIER],
    }


def test_en_tetes_du_profil_code_sur_chaque_surface(reglages: AtelierSettings) -> None:
    """Profil `code`, conversation, projet : ce que le serveur `atelier` filtre (équipe A)."""
    _pool_complet(reglages)
    projet = reglages.projects_dir / "lecteur-grist"
    surfaces = _entetes_par_surface(reglages, projet, "code")
    for surface, entree in surfaces.items():
        entetes = entree["headers"]
        assert entetes["X-Atelier-Profil"] == "code", surface
        assert entetes["X-Atelier-Projet"] == "lecteur-grist", surface
        assert "X-Atelier-Dossier" not in entetes, surface
        assert entetes["Authorization"] == "Bearer ${ATELIER_MCP_KEY}", surface
        assert entree["headersHelper"].endswith("atelier-entetes-mcp'") or entree["headersHelper"].endswith("atelier-entetes-mcp"), surface
    assert surfaces["app"]["headers"]["X-Atelier-Conversation"] == "conv-e"
    # Hors de l'Atelier : la référence, que le helper complète par l'identifiant de la conversation.
    assert surfaces["vscode-terminal"]["headers"]["X-Atelier-Conversation"] == "${ATELIER_SESSION:-poste}"


def test_en_tetes_du_profil_assistant_sur_chaque_surface(reglages: AtelierSettings) -> None:
    _pool_complet(reglages)
    surfaces = _entetes_par_surface(reglages, reglages.assistant_root, "assistant")
    for surface, entree in surfaces.items():
        assert entree["headers"]["X-Atelier-Profil"] == "assistant", surface
        assert "X-Atelier-Projet" not in entree["headers"], surface
        assert entree["headers"]["X-Atelier-Dossier"] == reglages.assistant_root.as_posix(), surface
    assert surfaces["app"]["headers"]["X-Atelier-Conversation"] == "conv-e"


def test_le_fichier_du_pool_et_la_portee_utilisateur_portent_le_profil_code(reglages: AtelierSettings) -> None:
    _pool_complet(reglages)
    materialize_mcp_config(reglages)
    for fichier in (reglages.mcp_config_path, Path.home() / ".claude.json"):
        entetes = _lire(fichier)[SERVICE_ATELIER]["headers"]
        assert entetes["X-Atelier-Profil"] == "code", fichier
        assert "X-Atelier-Projet" not in entetes, fichier
    assert (reglages.work_dir / "bin" / "atelier-entetes-mcp").is_file()


def test_la_forme_imbriquee_ne_se_developperait_pas() -> None:
    """Pourquoi un helper : l'expression de Claude Code (2.1.282) ne connaît pas l'imbrication.

    Même expression que dans le binaire : un seul passage, repli sans `}`.
    """
    import re

    motif = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*(?::-[^}]*)?)\}")

    def developper(texte: str, env: dict) -> str:
        def remplacer(m: re.Match[str]) -> str:
            nom, _, repli = m.group(1).partition(":-")
            return env.get(nom) or repli

        return motif.sub(remplacer, texte)

    assert developper("${ATELIER_SESSION:-${CLAUDE_CODE_SESSION_ID}}", {"CLAUDE_CODE_SESSION_ID": "abc"}) == "${CLAUDE_CODE_SESSION_ID}"


def _aide(tmp_path: Path, env_sup: dict) -> str:
    import os
    import shutil
    import subprocess

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("pas de bash")
    script = Path(__file__).resolve().parents[1] / "bin" / "atelier-entetes-mcp"
    env = {k: v for k, v in os.environ.items() if k not in ("ATELIER_SESSION", "CLAUDE_CONFIG_DIR")}
    env.update(env_sup)
    fini = subprocess.run([bash, str(script).replace("\\", "/")], capture_output=True, text=True, env=env, timeout=20)
    assert fini.returncode == 0 and fini.stderr == ""
    return fini.stdout.strip()


def test_l_aide_aux_en_tetes_donne_la_conversation_de_l_atelier(tmp_path: Path) -> None:
    assert json.loads(_aide(tmp_path, {"ATELIER_SESSION": "conv-42"})) == {"X-Atelier-Conversation": "conv-42"}
    assert json.loads(_aide(tmp_path, {"ATELIER_SESSION": "a b\"c"})) == {}


@pytest.mark.skipif(sys.platform == "win32", reason="/proc et PPID du pod")
def test_l_aide_aux_en_tetes_retrouve_la_conversation_du_claude_parent(tmp_path: Path) -> None:
    import os

    config = tmp_path / "config"
    (config / "sessions").mkdir(parents=True)
    (config / "sessions" / f"{os.getpid()}.json").write_text(
        json.dumps({"pid": os.getpid(), "sessionId": "4629a2a3-6fa8-43dd-999a-a6487bead4ed"}), encoding="utf-8"
    )
    sortie = _aide(tmp_path, {"CLAUDE_CONFIG_DIR": str(config)})
    assert json.loads(sortie) == {"X-Atelier-Conversation": "4629a2a3-6fa8-43dd-999a-a6487bead4ed"}
    vide = tmp_path / "vide"
    vide.mkdir()
    assert json.loads(_aide(tmp_path, {"CLAUDE_CONFIG_DIR": str(vide)})) == {}


# --- Correctifs du 26/09 (vérificateur réel sur le pod) -----------------------


def test_n8n_derriere_mcp_remote_est_sonde_et_retire(reglages: AtelierSettings, monkeypatch) -> None:
    """Le pool ne sonde pas les stdio : n8n (`mcp-remote` + jeton) restait distribué en 401."""
    import httpx

    _pool(
        reglages,
        n8n={"command": "npx", "args": ["-y", "mcp-remote", "https://n8n.exemple/mcp", "--header", "Authorization: Bearer jeton-n8n-1234567890"]},
        qgis={"type": "http", "url": "http://qgis/mcp"},
    )
    vus: list[dict] = []

    class Reponse:
        status_code = 401

    def post(url, json=None, headers=None, timeout=None):  # noqa: A002
        vus.append({"url": url, "auth": (headers or {}).get("Authorization", "")})
        return Reponse()

    monkeypatch.setattr(httpx, "post", post)
    projet = reglages.projects_dir / "p"
    lier_le_projet(reglages, projet)
    assert "n8n" in _lire(projet / ".mcp.json")
    # Le pool dit « stdio-local » : ce n'est pas une réussite, la sonde du pont décide.
    assert noter_les_sondes(reglages, {"registry:n8n": "stdio-local", "registry:qgis": "connected"})
    assert vus == [{"url": "https://n8n.exemple/mcp", "auth": "Bearer jeton-n8n-1234567890"}]
    assert "n8n" not in _lire(projet / ".mcp.json")
    reglages_locaux = json.loads((projet / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert "n8n" not in reglages_locaux["enabledMcpjsonServers"]


def test_l_approbation_du_dossier_est_exactement_son_mcp_json(reglages: AtelierSettings) -> None:
    """Une ancienne liste (Onyxia, n8n…) dans `.claude/settings.local.json` est remplacée."""
    _pool_complet(reglages)
    projet = reglages.projects_dir / "p"
    (projet / ".claude").mkdir(parents=True)
    (projet / ".claude" / "settings.local.json").write_text(
        json.dumps({"permissions": {"allow": ["Bash(ls:*)"]}, "enabledMcpjsonServers": ["Onyxia", "n8n", "fantome"],
                    "disabledMcpjsonServers": ["qgis", "autre"]}),
        encoding="utf-8",
    )
    lier_le_projet(reglages, projet)
    locaux = json.loads((projet / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert locaux["enabledMcpjsonServers"] == sorted(_lire(projet / ".mcp.json")) == sorted(_approuves(projet))
    assert locaux["disabledMcpjsonServers"] == ["autre"]
    assert locaux["permissions"]["allow"] == ["Bash(ls:*)"]


def test_le_choix_du_fil_vaut_pour_le_dossier_sur_toutes_les_surfaces(reglages: AtelierSettings) -> None:
    """Le « + » d'une conversation règle le choix du projet : app et VS Code restent égaux."""
    from mcp_gateway.atelier.harness import FakeHarness
    from mcp_gateway.atelier.sessions import SessionStore

    _pool_complet(reglages)
    store = SessionStore(reglages, FakeHarness())
    rec = store.create(slug="p")
    projet = Path(rec.cwd)
    lier_le_projet(reglages, projet)
    assert "qgis" in _lire(projet / ".mcp.json")
    store.patch_mcp_overlay(rec.session_id, {"qgis": False})
    app = _lire(materialize_session_mcp(reglages, rec.session_id, kind="code", cwd=projet, mcp_overlay={"n8n": False}))
    vscode = _lire(projet / ".mcp.json")
    assert "qgis" not in vscode and "qgis" not in app
    # Une ancienne désactivation propre à la conversation n'a plus d'effet : même ensemble partout.
    assert set(app) == set(vscode)
    assert (store.get(rec.session_id).mcp_overlay or {}) == {}


def test_le_reste_au_nom_de_l_assistant_ne_recoit_pas_le_profil_code(reglages: AtelierSettings) -> None:
    """Essais du 26/09 : `~/work/projects/wikichat-memory` recevait un `.mcp.json` de profil `code`.

    Son projet annoncé (`X-Atelier-Projet: wikichat-memory`) est le slug de
    l'Assistant : un agent `code` ouvert là (VS Code, terminal) aurait eu le
    projet de l'Assistant pour « son projet ». Le dossier de l'Assistant, lui,
    reçoit toujours le profil `assistant`.
    """
    _pool_complet(reglages)
    reste = reglages.projects_dir / reglages.assistant_slug
    reste.mkdir(parents=True)
    reglages.assistant_root.mkdir(parents=True, exist_ok=True)

    lier_tous_les_projets(reglages)

    assert not (reste / ".mcp.json").exists(), "le reste n'est pas relié comme un projet"
    serveurs = _lire(reglages.assistant_root / ".mcp.json")
    assert serveurs[SERVICE_ATELIER]["headers"][ENTETE_PROFIL] == "assistant"


def test_un_agent_code_ne_peut_pas_annoncer_le_slug_de_l_assistant(reglages: AtelierSettings) -> None:
    from mcp_gateway.atelier.commandes.profils import projet_annonce_valide

    (reglages.projects_dir / reglages.assistant_slug).mkdir(parents=True)
    (reglages.projects_dir / "vrai-projet").mkdir(parents=True)
    store = types.SimpleNamespace(settings=reglages)
    assert projet_annonce_valide(store, "vrai-projet") == "vrai-projet"
    assert projet_annonce_valide(store, reglages.assistant_slug) == ""


def test_onyxia_de_l_assistant_suit_la_case_du_dossier(reglages: AtelierSettings) -> None:
    """La case Onyxia du « + » vaut pour l'Assistant : par défaut présent, décoché absent."""
    from mcp_gateway.atelier.mcp_sync import _ecrire_la_selection, compute_binding_merged

    _pool_complet(reglages)
    dossier = reglages.assistant_root / "sessions" / "conv-onyxia"
    dossier.mkdir(parents=True)
    assert "Onyxia" in compute_binding_merged(reglages, kind="assistant", cwd=dossier)

    _ecrire_la_selection(dossier, {"Onyxia": False, "wikichat": True})
    assert "Onyxia" not in compute_binding_merged(reglages, kind="assistant", cwd=dossier)

    _ecrire_la_selection(dossier, {"Onyxia": True, "wikichat": True})
    assert "Onyxia" in compute_binding_merged(reglages, kind="assistant", cwd=dossier)
