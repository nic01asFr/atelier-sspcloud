"""Le navigateur de l'Atelier : une déclaration stdio, la même partout.

Le navigateur est `chrome-devtools-mcp` lancé par `~/work/bin/atelier-chrome`
dans le processus de chaque client (docs/navigateur-atelier.md). Il ne porte
ni adresse, ni jeton, ni en-tête : le processus est la conversation. Il se
reconnaît à son identifiant seul, s'installe une fois dans le pool, migre
l'ancienne déclaration HTTP, et n'a plus de bureau à relayer.

Le lanceur lui-même est éprouvé dans test_lanceur_chrome.py, le client stdio
de la passerelle dans test_client_stdio.py.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mcp_gateway.atelier.api import build_app
from mcp_gateway.atelier.chrome_ensure import TRACE_PROPOSE, ensure_chrome_mcp_connector
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_tools import GROUPE_NAVIGATEUR, nature_service
from mcp_gateway.atelier.mcp_sync import (
    SERVICE_CHROME,
    declaration_chrome,
    integrer_le_navigateur,
    lier_le_projet,
    materialize_session_mcp,
    pour_le_home,
)
from mcp_gateway.atelier.navigateur import (
    ENV_PASSERELLE,
    declaration_du_pool,
    lanceur_chrome,
    refuser_les_outils_simules,
    regles_de_lecture_du_navigateur,
    stdio_de_la_passerelle,
)
from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME

ORIGINE = "https://testserver"
ANCIEN_JETON = "jeton-du-service-navigateur-0123456789abcdef"


def _reglages(tmp_path: Path, **options: object) -> AtelierSettings:
    s = AtelierSettings(work_dir=tmp_path / "work", public_url=ORIGINE, **options)
    s.ensure_dirs()
    return s


def _pool(s: AtelierSettings) -> dict:
    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.db import connect

    conn = connect(s.gateway_db_path)
    try:
        return IntegratedMcpStore(conn).list_servers()
    finally:
        conn.close()


def _pool_faire(s: AtelierSettings, action: str, config: dict | None = None) -> None:
    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.db import connect

    conn = connect(s.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        if action == "desactiver":
            store.set_enabled(SERVICE_CHROME, False)
        elif action == "supprimer":
            store.delete(SERVICE_CHROME)
        elif action == "poser":
            store.upsert(SERVICE_CHROME, config or {})
    finally:
        conn.close()


# --- la déclaration -----------------------------------------------------------


def test_la_declaration_est_le_lanceur_stdio_sans_secret(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    d = declaration_chrome(s)
    assert d == {"type": "stdio", "command": str(s.work_dir / "bin" / "atelier-chrome"), "args": []}
    # Le pool porte la même : l'écran des connecteurs montre ce que l'agent reçoit.
    assert declaration_du_pool(s) == d


def test_la_meme_declaration_sur_toutes_les_surfaces(tmp_path: Path) -> None:
    """Fichier effectif d'un tour, `.mcp.json` du projet (VS Code, terminal,
    wikichat) et configuration du HOME : un seul et même lanceur."""
    s = _reglages(tmp_path)
    ensure_chrome_mcp_connector(s)
    projet = s.projects_dir / "p"
    lier_le_projet(s, projet)
    dans_le_projet = json.loads((projet / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]
    effectif = json.loads(
        materialize_session_mcp(s, "conv-1", kind="code", cwd=projet).read_text(encoding="utf-8")
    )["mcpServers"]
    home = json.loads(s.mcp_config_path.read_text(encoding="utf-8"))["mcpServers"]
    attendu = declaration_chrome(s)
    assert dans_le_projet[SERVICE_CHROME] == attendu
    assert effectif[SERVICE_CHROME] == attendu
    assert home[SERVICE_CHROME] == attendu


def test_un_connecteur_tiers_qui_parle_de_chrome_n_est_pas_reecrit(tmp_path: Path) -> None:
    tiers = {
        "mon-chrome": {"type": "http", "url": "http://127.0.0.1:9222/chrome-devtools/mcp"},
        "chrome-perso": {"type": "stdio", "command": "npx", "args": ["chrome-devtools-mcp@latest"]},
        SERVICE_CHROME: {"type": "http", "url": "https://ancien-ingress/mcp?session=x"},
    }
    s = _reglages(tmp_path)
    sortie = integrer_le_navigateur(tiers, s)
    assert sortie["mon-chrome"] == tiers["mon-chrome"]
    assert sortie["chrome-perso"] == tiers["chrome-perso"]
    assert sortie[SERVICE_CHROME] == declaration_chrome(s)
    for nom in ("mon-chrome", "chrome-perso"):
        nature = nature_service(tiers[nom], "http://127.0.0.1:3777/sse", nom=nom)
        assert nature["group"] != GROUPE_NAVIGATEUR


def test_c_est_du_socle_pas_un_connecteur_detachable(tmp_path: Path) -> None:
    nature = nature_service(
        declaration_chrome(_reglages(tmp_path)), "http://127.0.0.1:3777/sse", nom=SERVICE_CHROME
    )
    assert nature["system"] is True
    assert nature["group"] == GROUPE_NAVIGATEUR


def test_eteint_rien_n_est_declare_ni_lance(tmp_path: Path) -> None:
    s = _reglages(tmp_path, navigateur=False)
    assert ensure_chrome_mcp_connector(s) is None
    entree = {SERVICE_CHROME: {"type": "http", "url": "http://ailleurs/mcp"}}
    assert integrer_le_navigateur(entree, s) == entree
    assert stdio_de_la_passerelle(s) == {}


def test_la_passerelle_lance_sa_propre_instance(tmp_path: Path) -> None:
    assert stdio_de_la_passerelle(_reglages(tmp_path)) == {SERVICE_CHROME: ENV_PASSERELLE}
    assert ENV_PASSERELLE == {"ATELIER_CHROME_PORTEE": "passerelle"}


def test_le_home_porte_la_declaration_telle_quelle(tmp_path: Path) -> None:
    d = declaration_chrome(_reglages(tmp_path))
    assert pour_le_home({SERVICE_CHROME: d})[SERVICE_CHROME] == d


# --- le connecteur, dans le pool ----------------------------------------------


def test_ensure_cree_puis_respecte_une_desactivation(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    assert ensure_chrome_mcp_connector(s) is not None
    assert _pool(s)[SERVICE_CHROME]["enabled"] is True
    _pool_faire(s, "desactiver")
    ensure_chrome_mcp_connector(s)
    assert _pool(s)[SERVICE_CHROME]["enabled"] is False


def test_ensure_ne_recree_pas_un_connecteur_supprime(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    ensure_chrome_mcp_connector(s)
    _pool_faire(s, "supprimer")
    assert ensure_chrome_mcp_connector(s) is None
    assert SERVICE_CHROME not in _pool(s)
    (s.mcp_dir / TRACE_PROPOSE).unlink()
    assert ensure_chrome_mcp_connector(s) is not None


def test_l_ancienne_declaration_http_est_migree_sans_son_jeton(tmp_path: Path) -> None:
    """Le pool du pod portait le service distant, son jeton et son en-tête."""
    s = _reglages(tmp_path)
    _pool_faire(
        s,
        "poser",
        {
            "type": "http",
            "url": "http://chrome-devtools-mcp:3100/mcp",
            "headers": {
                "X-Atelier-Conversation": "atelier-passerelle",
                "Authorization": f"Bearer {ANCIEN_JETON}",
            },
            "enabled": False,
        },
    )
    ensure_chrome_mcp_connector(s)
    assert _pool(s)[SERVICE_CHROME]["enabled"] is False, "le choix de la personne reste"
    from mcp_gateway.atelier.env_secrets import chemin_du_fichier

    home = json.loads(s.mcp_config_path.read_text(encoding="utf-8"))["mcpServers"]
    assert SERVICE_CHROME not in home, "désactivé, il n'est déclaré nulle part"
    for chemin in (s.mcp_config_path, chemin_du_fichier(s)):
        if chemin.exists():
            texte = chemin.read_text(encoding="utf-8")
            assert ANCIEN_JETON not in texte
            assert "CHROME_DEVTOOLS_MCP_AUTHORIZATION" not in texte
    # Réactivé, c'est le lanceur qui est déclaré.
    from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
    from mcp_gateway.atelier.mcp_sync import materialize_mcp_config
    from mcp_gateway.db import connect

    conn = connect(s.gateway_db_path)
    try:
        IntegratedMcpStore(conn).set_enabled(SERVICE_CHROME, True)
    finally:
        conn.close()
    materialize_mcp_config(s)
    home = json.loads(s.mcp_config_path.read_text(encoding="utf-8"))["mcpServers"]
    assert home[SERVICE_CHROME] == declaration_chrome(s)


# --- WebSearch ----------------------------------------------------------------


def test_websearch_est_refuse_sans_toucher_au_reste(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    # Les lectures du navigateur sont autorisées d'office en même temps (J-f3).
    lectures = regles_de_lecture_du_navigateur()
    assert refuser_les_outils_simules({}, s) == {"permissions": {"deny": ["WebSearch"], "allow": lectures}}
    perso = {"permissions": {"deny": ["Bash(rm:*)"], "allow": ["Read"]}, "model": "m"}
    sortie = refuser_les_outils_simules(perso, s)
    assert sortie["permissions"] == {"deny": ["Bash(rm:*)", "WebSearch"], "allow": ["Read", *lectures]}
    assert sortie["model"] == "m"
    assert refuser_les_outils_simules(sortie, s) == sortie, "idempotent"


def test_websearch_natif_retire_seulement_notre_refus(tmp_path: Path) -> None:
    s = _reglages(tmp_path, websearch_natif=True, navigateur=False)
    reglages = {"permissions": {"deny": ["WebSearch", "Bash(rm:*)"]}}
    assert refuser_les_outils_simules(reglages, s) == {"permissions": {"deny": ["Bash(rm:*)"]}}
    assert refuser_les_outils_simules({"permissions": {"deny": ["WebSearch"]}}, s) == {}


def test_chaque_tour_refuse_websearch(tmp_path: Path) -> None:
    from mcp_gateway.atelier.harness import ClaudeHarness

    arguments = ClaudeHarness(_reglages(tmp_path))._arguments_de_reglages("conv-1", None)  # noqa: SLF001
    reglages = json.loads(arguments[arguments.index("--settings") + 1])
    assert "WebSearch" in reglages["permissions"]["deny"]


# --- l'état, dans l'interface -------------------------------------------------


def _cookie(client: TestClient) -> dict[str, str]:
    sid = client.app.state.auth.ouvrir_session()  # type: ignore[attr-defined]
    return {"Cookie": f"{COOKIE_NAME}={sid}"}


def test_health_sans_lanceur_le_dit_et_le_bureau_a_disparu(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    with TestClient(build_app(settings=s, use_fake=True), base_url=ORIGINE) as client:
        r = client.get("/chrome/health", headers=_cookie(client))
        assert r.status_code == 200
        etat = r.json()
        assert etat["configure"] is True and etat["mode"] == "stdio"
        assert etat["pret"] is False and "lanceur absent" in etat["raison"]
        assert etat["bureau"] is False
        for route in ("/chrome/view", "/chrome/novnc/core/rfb.js"):
            assert client.get(route, headers=_cookie(client)).status_code == 404


def test_health_eteint(tmp_path: Path) -> None:
    s = _reglages(tmp_path, navigateur=False)
    with TestClient(build_app(settings=s, use_fake=True), base_url=ORIGINE) as client:
        etat = client.get("/chrome/health", headers=_cookie(client)).json()
        assert etat["configure"] is False and etat["pret"] is False


@pytest.mark.skipif(os.name == "nt", reason="lanceur shell : pod Linux")
def test_health_demande_au_lanceur_ce_qu_il_trouve(tmp_path: Path) -> None:
    s = _reglages(tmp_path)
    lanceur = lanceur_chrome(s)
    lanceur.parent.mkdir(parents=True, exist_ok=True)
    lanceur.write_text(
        '#!/bin/sh\n[ "$ATELIER_CHROME_VERIFIER" = 1 ] || exit 3\n'
        'printf "node=/n\\nserveur=/s.js\\nchrome=/c\\n"\n',
        encoding="utf-8",
    )
    lanceur.chmod(lanceur.stat().st_mode | stat.S_IEXEC)
    from mcp_gateway.atelier import navigateur

    navigateur._VERIFICATION.update(etat=None, quand=0.0, lanceur="")  # noqa: SLF001
    etat = navigateur.etat_local(s)
    assert etat["pret"] is True and etat["chrome"] == "/c" and etat["serveur"] == "/s.js"
