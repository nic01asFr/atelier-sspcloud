"""Chaque contrôle des gardiens, sur un pod imaginaire (fixtures), sans réseau ni /proc réel."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from mcp_gateway.gardiens.controles import automates, sante, securite
from mcp_gateway.gardiens.controles.commun import Contexte, Ecoute, Processus, ReponseHttp, ecoutes_du_texte
from mcp_gateway.gardiens.declaration import Controle
from mcp_gateway.gardiens.journal import empreinte_de_valeur

SECRET = "s3cr3t-valeur-du-pool-0123456789"
JETON_GH = "ghp_" + "A" * 36


def controle(ident: str, **params) -> Controle:
    return Controle(id=ident, gardien="sante", portee="pod", quand={"toutes_les_min": 1}, commande=["interne", "x"], params=params)


@pytest.fixture()
def ctx(tmp_path: Path) -> Contexte:
    work = tmp_path / "work"
    home = tmp_path / "home"
    (work / ".secrets").mkdir(parents=True)
    home.mkdir()
    return Contexte(
        work=work,
        home=home,
        code_server_dir=home / "code-server",
        http=lambda url, entetes=None, delai=5.0: ReponseHttp(0, "", "ConnectionRefusedError"),
        commande=lambda argv, delai=20.0, cwd=None: (127, ""),
        ecoutes=lambda: [],
        processus=lambda: [],
        env={},
    )


# --- santé ------------------------------------------------------------------


def test_service_qui_repond_est_ok_et_celui_qui_ne_repond_pas_est_une_alerte(ctx: Contexte) -> None:
    vus = []

    def http(url, entetes=None, delai=5.0):
        vus.append(url)
        return ReponseHttp(200, "{}") if url.endswith("/api/health") else ReponseHttp(0, "", "refus")

    ctx.http = http
    ctx.port_wikichat = 3999
    assert sante.service(ctx, controle("sante.wikichat", service="wikichat"))["etat"] == "ok"
    assert vus[-1] == "http://127.0.0.1:3999/api/health"
    res = sante.service(ctx, controle("sante.atelier", service="atelier"))
    assert res["etat"] == "alerte"
    assert res["constats"][0]["empreinte"] == "sante.atelier:ne-repond-pas"
    assert "refus" in res["constats"][0]["preuve"]


def test_creations_en_echec_lues_au_superviseur_avec_la_cle_sans_la_rendre(ctx: Contexte) -> None:
    (ctx.secrets_dir / "atelier_owner_key").write_text("cle-owner-tres-secrete\n")
    recu = {}

    def http(url, entetes=None, delai=5.0):
        recu.update(url=url, entetes=entetes)
        return ReponseHttp(200, json.dumps({"artefacts": [
            {"slug": "p", "nom": "a", "etat": "en_echec", "raison": "5 redémarrages en 10 min"},
            {"slug": "p", "nom": "b", "etat": "pret"},
            {"slug": "q", "nom": "c", "etat": "invalide", "erreur": "commande manquante"},
        ]}))

    ctx.http = http
    res = sante.creations(ctx, controle("sante.creations"))
    assert recu["url"].endswith("/v1/apps")
    assert recu["entetes"]["Authorization"] == "Bearer cle-owner-tres-secrete"
    assert res["etat"] == "alerte"
    assert [c["objet"] for c in res["constats"]] == ["p/a", "q/c"]
    assert "cle-owner" not in json.dumps(res)


def test_ci_rouge_sur_main_par_gh(ctx: Contexte) -> None:
    runs = {"workflow_runs": [
        {"id": 2, "name": "Image", "status": "completed", "conclusion": "failure", "head_sha": "abcdef1234", "created_at": "2026-09-16T21:47:00Z"},
        {"id": 1, "name": "Image", "status": "completed", "conclusion": "success", "head_sha": "0123456", "created_at": "2026-09-15T10:00:00Z"},
        {"id": 3, "name": "Image", "status": "in_progress", "conclusion": None, "head_sha": "fff", "created_at": "2026-09-17T10:00:00Z"},
    ]}
    ctx.commande = lambda argv, delai=20.0, cwd=None: (0, json.dumps(runs)) if argv[:2] == ["gh", "api"] else (127, "")
    res = sante.ci_main(ctx, controle("sante.ci-main", depots=["o/d"]))
    assert res["etat"] == "alerte"
    assert res["constats"][0]["empreinte"] == "sante.ci-main:rouge:o/d"
    assert "abcdef1" in res["constats"][0]["preuve"]


def test_ci_inaccessible_sans_jeton_est_une_attention_et_le_jeton_ne_sort_pas(ctx: Contexte) -> None:
    (ctx.secrets_dir / "github_token").write_text(JETON_GH)
    vus = {}

    def http(url, entetes=None, delai=5.0):
        vus.update(entetes or {})
        return ReponseHttp(404, '{"message": "Not Found"}')

    ctx.http = http
    res = sante.ci_main(ctx, controle("sante.ci-main", depots=["o/prive"]))
    assert vus["Authorization"] == f"Bearer {JETON_GH}"
    assert res["etat"] == "attention"
    assert JETON_GH not in json.dumps(res)


def test_image_comparee_a_main(ctx: Contexte, tmp_path: Path) -> None:
    version = tmp_path / "VERSION"
    version.write_text("1111111aaaa")
    ctx.commande = lambda argv, delai=20.0, cwd=None: (0, json.dumps({"sha": "2222222bbbb"}))
    res = sante.image_main(ctx, controle("sante.image-main", depot="o/d", fichiers_version=[str(version)]))
    assert [c["empreinte"] for c in res["constats"]] == ["sante.image-main:ecart"]
    version.write_text("2222222bbbb")
    assert sante.image_main(ctx, controle("sante.image-main", depot="o/d", fichiers_version=[str(version)]))["etat"] == "ok"
    res = sante.image_main(ctx, controle("sante.image-main", depot="o/d", fichiers_version=[str(tmp_path / "absent")]))
    assert [c["empreinte"] for c in res["constats"]] == ["sante.image-main:inconnu"]


def test_disque_seuils(ctx: Contexte) -> None:
    ctx.disque = lambda p: (100, 40)
    assert sante.disque(ctx, controle("sante.disque"))["etat"] == "ok"
    ctx.disque = lambda p: (100, 10)
    assert sante.disque(ctx, controle("sante.disque"))["etat"] == "attention"
    ctx.disque = lambda p: (100, 2)
    assert sante.disque(ctx, controle("sante.disque"))["etat"] == "alerte"


# --- sécurité ---------------------------------------------------------------

TCP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 00000000:223B 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 111 1
   1: 0100007F:0ED1 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 222 1
   2: 0100007F:1F90 0100007F:D431 01 00000000:00000000 00:00000000 00000000  1000        0 333 1
   3: 00000000:1F40 00000000:0000 0A 00000000:00000000 00:00000000 00000000  1000        0 444 1
"""
TCP6 = """  sl  local_address                         remote_address                        st
   0: 00000000000000000000000000000000:1F41 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000  1000 0 555 1
   1: 00000000000000000000000001000000:0BB9 00000000000000000000000000000000:0000 0A 00000000:00000000 00:00000000 00000000  1000 0 666 1
"""


def test_lecture_de_proc_net_tcp() -> None:
    assert ecoutes_du_texte(TCP, False) == [("0.0.0.0", 8763, "111"), ("127.0.0.1", 3793, "222"), ("0.0.0.0", 8000, "444")]
    assert ecoutes_du_texte(TCP6, True) == [("::", 8001, "555"), ("::1", 3001, "666")]


def test_ecoute_hors_declaration_sur_toutes_les_interfaces(ctx: Contexte) -> None:
    ctx.reglages = {"ecoutes_declarees": [{"port": 8787}, {"port": 8788}]}
    ctx.ecoutes = lambda: [
        Ecoute("0.0.0.0", 8787, 10, "python3 -m mcp_gateway.atelier.app"),
        Ecoute("127.0.0.1", 3777, 11, "node server.mjs"),
        Ecoute("0.0.0.0", 8000, 12, "python -m ipykernel_launcher"),
        Ecoute("::", 9000, None, ""),
    ]
    res = securite.ecoutes(ctx, controle("securite.ecoutes"))
    assert res["etat"] == "alerte"
    assert [c["empreinte"] for c in res["constats"]] == ["securite.ecoutes:8000", "securite.ecoutes:9000"]
    assert "pid 12" in res["constats"][0]["preuve"]


def _pod_avec_secret_en_clair(ctx: Contexte) -> None:
    (ctx.secrets_dir / "claude-env.sh").write_text(f"export ATELIER_MCP_N8N='{SECRET}'\n")
    (ctx.secrets_dir / "voice_token").write_text("jeton-voix-de-test-42\n")
    (ctx.home / ".claude.json").write_text(json.dumps({"mcpServers": {"n8n": {"args": ["--token", SECRET]}}}))
    projet = ctx.work / "projects" / "p"
    projet.mkdir(parents=True)
    (projet / ".mcp.json").write_text(json.dumps({"mcpServers": {"x": {"headers": {"Authorization": "Bearer ${ATELIER_MCP_KEY}"}}}}))
    (projet / ".git").mkdir()
    (projet / "notes.md").write_text(f"remote avec jeton : https://{JETON_GH}@github.com/o/d\n")
    (projet / "doc.md").write_text("Authorization: Bearer abcdefghijklmnopqrstuvwxyz (exemple de doc)\n")


def test_secrets_en_clair_par_empreinte_sans_jamais_la_valeur(ctx: Contexte) -> None:
    _pod_avec_secret_en_clair(ctx)
    projet = ctx.work / "projects" / "p"
    ctx.commande = lambda argv, delai=20.0, cwd=None: (0, "notes.md\0doc.md\0") if "ls-files" in argv else (127, "")
    res = securite.secrets_en_clair(ctx, controle("securite.secrets-en-clair"))
    texte = json.dumps(res)
    assert SECRET not in texte and JETON_GH not in texte and "jeton-voix" not in texte
    par_objet = {(c["objet"], c["resume"]) for c in res["constats"]}
    assert (str(ctx.home / ".claude.json"), "valeur de ATELIER_MCP_N8N en clair") in par_objet
    assert (str(projet / "notes.md"), "motif de jeton (github)") in par_objet
    # Le motif générique « Bearer … » ne vaut que pour les fichiers de configuration.
    assert not any(c["objet"].endswith("doc.md") for c in res["constats"])
    # La référence ${…} du .mcp.json n'est pas un secret.
    assert not any(c["objet"].endswith(".mcp.json") for c in res["constats"])
    emp = empreinte_de_valeur(SECRET)
    assert f"securite.secrets-en-clair:{emp}:{ctx.home / '.claude.json'}" in {c["empreinte"] for c in res["constats"]}
    assert res["donnees"]["valeurs_connues"] == 2


def test_aurait_vu_le_jeton_n8n_dans_args(ctx: Contexte) -> None:
    """Mutation S4 : sans la valeur en clair, plus de constat."""
    _pod_avec_secret_en_clair(ctx)
    (ctx.home / ".claude.json").write_text(json.dumps({"mcpServers": {"n8n": {"args": ["--token", "${ATELIER_MCP_N8N}"]}}}))
    res = securite.secrets_en_clair(ctx, controle("securite.secrets-en-clair", depots_suivis=False))
    assert res["etat"] == "ok"


@pytest.mark.skipif(os.name != "posix", reason="droits POSIX")
def test_droits_des_fichiers_de_secrets(ctx: Contexte) -> None:
    bon = ctx.secrets_dir / "llm_api_key"
    mauvais = ctx.secrets_dir / "github_token"
    bon.write_text("x")
    mauvais.write_text("y")
    ctx.secrets_dir.chmod(0o700)
    bon.chmod(0o600)
    mauvais.chmod(0o644)
    res = securite.droits(ctx, controle("securite.droits"))
    assert [c["objet"] for c in res["constats"]] == [str(mauvais)]
    mauvais.chmod(0o600)
    assert securite.droits(ctx, controle("securite.droits"))["etat"] == "ok"
    assert stat.S_IMODE(bon.stat().st_mode) == 0o600


def test_bypass_sans_fiche_est_une_alerte_avec_le_lanceur(ctx: Contexte) -> None:
    ctx.sessions_dir.mkdir(parents=True)
    (ctx.sessions_dir / "a.json").write_text(json.dumps({"session_id": "a", "claude_session_id": "sid-atelier", "permission_mode": "bypassPermissions"}))
    ctx.processus = lambda: [
        Processus(1, ["node", "server.mjs"], "/w/wikichat"),
        Processus(2, ["/x/native-binary/claude", "-p", "--permission-mode", "bypassPermissions", "--resume", "sid-atelier"], "/w/p", 1),
        Processus(3, ["/x/native-binary/claude", "-p", "--permission-mode", "bypassPermissions", "--resume", "sid-sauvage"], "/w/q", 1),
        Processus(4, ["/x/native-binary/claude", "-p", "--permission-mode", "acceptEdits"], "/w/r", 1),
    ]
    res = securite.bypass(ctx, controle("securite.bypass"))
    assert [c["empreinte"] for c in res["constats"]] == ["securite.bypass:sid-sauvage"]
    assert "node server.mjs" in res["constats"][0]["preuve"]
    assert res["donnees"]["claude_en_bypass"] == 2


# --- G0 -----------------------------------------------------------------------


def test_inventaire_des_automates(ctx: Contexte) -> None:
    ctx.wikichat_dir.mkdir(parents=True)
    (ctx.wikichat_dir / "triggers.json").write_text(json.dumps({
        "r1": {"id": "r1", "type": "cron", "enabled": True, "max_per_day": 48, "fire_count": 42, "config": {"schedule": "*/30 * * * *"}, "action": {"type": "spawn_session"}},
        "r2": {"id": "r2", "type": "cron", "enabled": False, "config": {"schedule": "0 4 * * *"}},
        "r3": {"id": "r3", "type": "cron", "enabled": True, "config": {"schedule": "0 8 * * *", "tz": "Europe/Paris"}, "budget": {"passes_par_jour": 1}},
        "m": {"id": "m", "type": "mention", "enabled": True},
    }))
    (ctx.wikichat_dir / "routines.json").write_text(json.dumps({"paradox": {"id": "paradox", "enabled": True, "steps": [{}, {}]}}))
    (ctx.wikichat_dir / "routine-runs.jsonl").write_text(
        json.dumps({"routineId": "paradox", "startedAt": "2026-09-25T10:00:00Z"}) + "\n"
        + json.dumps({"routineId": "paradox", "startedAt": "2026-09-01T10:00:00Z"}) + "\n"
    )
    (ctx.work / ".atelier-etat").mkdir()
    (ctx.work / ".atelier-etat" / "apps.json").write_text(json.dumps({"version": 1, "apps": {"p/a": {"pid": 9, "port": 41000}}}))
    ctx.maintenant = lambda: 1790000000.0  # 2026-09-21
    ctx.reglages = {"demons_connus": [{"id": "atelier", "ports": [8787]}, {"id": "wikichat", "ports": [3777]}]}
    ctx.ecoutes = lambda: [
        Ecoute("0.0.0.0", 8787, 5, "atelier"),
        Ecoute("127.0.0.1", 41000, 9, "creation"),
        Ecoute("127.0.0.1", 9999, 7, "python3 -m http.server 9999"),
        Ecoute("127.0.0.1", 45000, 8, "python -m ipykernel_launcher -f x"),
    ]
    ctx.etat_executeur = lambda: [{"id": "sante.atelier", "gardien": "sante", "quand": {"toutes_les_min": 1}, "derniere": None, "prochaine": None}]
    res = automates.inventaire(ctx, Controle("entretien.automates", "entretien", "pod", {"toutes_les_min": 15}, ["interne", "x"]))
    par_id = {a["id"]: a for a in res["donnees"]["automates"]}
    cles = {"id", "genre", "proprietaire", "source", "quand", "budget", "derniere", "prochaine", "cout_semaine", "etat"}
    assert all(cles <= set(a) for a in par_id.values())
    assert par_id["wikichat.trigger.r1"]["etat"] == "sans_declaration"
    assert par_id["wikichat.trigger.r1"]["prochaine"] is not None
    assert par_id["wikichat.trigger.r2"]["etat"] == "coupe"
    assert par_id["wikichat.trigger.r3"]["etat"] == "actif"
    assert par_id["wikichat.routine.paradox"]["etat"] == "sans_declaration"
    assert par_id["wikichat.routine.paradox"]["cout_semaine"]["passes"] == 1
    assert par_id["gardiens.sante.atelier"]["genre"] == "controle"
    assert par_id["creation.p/a"]["etat"] == "actif"
    assert par_id["demon.atelier"]["etat"] == "actif"
    assert par_id["demon.wikichat"]["etat"] == "absent"
    assert par_id["demon.port-9999"]["etat"] == "sans_declaration"
    assert "demon.port-45000" not in par_id and "demon.port-41000" not in par_id
    constats = {c["objet"] for c in res["constats"]}
    assert constats == {"wikichat.trigger.r1", "wikichat.trigger.m", "wikichat.routine.paradox", "demon.port-9999"}
    assert res["etat"] == "attention"
