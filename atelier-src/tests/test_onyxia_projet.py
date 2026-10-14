"""Onyxia selon le profil : `code` borné au déploiement du projet, `assistant` complet.

Le serveur Onyxia ne sait pas filtrer par pod ; le filtre est dans la
passerelle (`onyxia_projet`). On l'éprouve sans serveur : le mandataire reçoit
un faux Onyxia qui note ce qu'on lui envoie.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from mcp_gateway.atelier import onyxia_projet as ox
from mcp_gateway.atelier.commandes import structure

POD = "proj-carte-jupyter-python-0"

# Les outils tels qu'Onyxia les annonce (noms et schémas réduits à l'utile).
OUTILS_AMONT = [
    {"name": nom, "description": nom, "inputSchema": {"type": "object", "properties": props, "required": req}}
    for nom, props, req in [
        ("exec", {"session_id": {}, "code": {}, "lang": {}, "timeout": {}, "background": {}}, ["session_id", "code"]),
        ("job_poll", {"session_id": {}, "job_id": {}}, ["session_id", "job_id"]),
        ("read_file", {"session_id": {}, "path": {}, "max_bytes": {}}, ["session_id", "path"]),
        ("write_file", {"session_id": {}, "path": {}, "content": {}}, ["session_id", "path", "content"]),
        ("list_files", {"session_id": {}, "path": {}, "depth": {}}, ["session_id"]),
        ("session_status", {"session_id": {}}, []),
        ("session_start", {"attach_pod": {}}, []),
        ("session_stop", {"session_id": {}, "uninstall": {}}, ["session_id"]),
        ("list_pods", {"namespace": {}, "name_filter": {}}, []),
        ("project_bind", {"project": {}, "pod": {}, "namespace": {}, "session_id": {}}, []),
        ("project_start", {"project": {}, "gpu": {}}, ["project"]),
        ("gpu_switch", {"project": {}, "preempt": {}, "idle_minutes": {}, "session_id": {}}, ["project"]),
        ("gpu_release", {"project": {}, "namespace": {}}, []),
        ("gpu_status", {"session_id": {}, "namespace": {}}, []),
        ("service_deploy", {"yaml_path": {}}, ["yaml_path"]),
        ("service_status", {"yaml_path": {}}, ["yaml_path"]),
        ("service_stop", {"yaml_path": {}}, ["yaml_path"]),
        ("push_repo", {"session_id": {}, "source": {}}, ["session_id", "source"]),
        ("expose_public", {"session_id": {}, "port": {}}, []),
        ("unexpose_public", {"session_id": {}, "name": {}}, []),
    ]
]


def _texte(charge: Any, erreur: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(charge)}], "isError": erreur}


class FauxOnyxia:
    """Un serveur Onyxia minimal : une session globale par nom, attachée à un pod."""

    def __init__(self, sessions: dict[str, str] | None = None) -> None:
        self.sessions = dict(sessions or {})
        self.appels: list[tuple[str, dict[str, Any]]] = []

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.appels.append((outil, dict(arguments)))
        if outil == "project_bind":
            self.sessions[arguments["session_id"]] = arguments["pod"]
            return _texte({"session_id": arguments["session_id"], "pod": arguments["pod"]})
        sid = arguments.get("session_id")
        if sid is not None and sid not in self.sessions:
            return _texte({"error": {"code": "NO_SESSION", "message": sid}}, erreur=True)
        if outil == "session_status":
            return _texte({"session_id": sid, "pod": self.sessions[sid]})
        return _texte({"ok": outil})

    def outils(self) -> list[dict[str, Any]]:
        return OUTILS_AMONT

    def envoyes(self, outil: str) -> list[dict[str, Any]]:
        return [a for o, a in self.appels if o == outil]


def _borne(**kw: Any) -> ox.Borne:
    deploiement = structure.Deploiement(**({"pod": POD} | kw))
    return ox.borne_du_projet("carte", deploiement)


def _mandataire(faux: FauxOnyxia) -> ox.MandataireOnyxia:
    return ox.MandataireOnyxia(faux.appeler, faux.outils)


def _appel(m: ox.MandataireOnyxia, profil: str, borne: ox.Borne | None, outil: str, args: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(m.appeler_outil(profil, borne, outil, args))  # type: ignore[arg-type]


def _charge(resultat: dict[str, Any]) -> Any:
    return json.loads(resultat["content"][0]["text"])


# ── L'entrée mcpServers ─────────────────────────────────────────────────


def _reglages(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(projects_dir=tmp_path / "projects", port=8787)


def _poser(reglages: SimpleNamespace, slug: str, deploiement: dict[str, Any] | None) -> None:
    donnees: dict[str, Any] = {"slug": slug, "titre": slug}
    if deploiement is not None:
        donnees["deploiement"] = deploiement
    structure.ecrire(reglages.projects_dir / slug, structure.valider(donnees))


def test_code_sans_deploiement_ne_recoit_pas_onyxia(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    _poser(reglages, "carte", None)
    assert ox.onyxia_pour_projet(reglages, "carte", "code") is None
    # Ni fiche, ni projet : rien non plus.
    assert ox.onyxia_pour_projet(reglages, "inconnu", "code") is None


def test_code_avec_fiche_invalide_ne_recoit_pas_onyxia(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    chemin = reglages.projects_dir / "carte" / structure.CHEMIN
    chemin.parent.mkdir(parents=True)
    chemin.write_text(json.dumps({"slug": "carte", "titre": "c", "deploiement": {"pod": POD, "x": 1}}), encoding="utf-8")
    assert ox.onyxia_pour_projet(reglages, "carte", "code") is None


def test_code_avec_deploiement_recoit_le_point_d_entree_borne(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    _poser(reglages, "carte", {"pod": POD})
    entree = ox.onyxia_pour_projet(reglages, "carte", "code")
    assert entree == {
        "type": "http",
        "url": "http://127.0.0.1:8787/mcp/onyxia/projet/carte",
        "headers": {"Authorization": "Bearer ${ATELIER_MCP_KEY}"},
    }
    # Jamais le serveur Onyxia en direct, jamais un secret dans l'entrée.
    assert "sspcloud" not in json.dumps(entree)


def test_assistant_recoit_le_point_d_entree_complet(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    entree = ox.onyxia_pour_projet(reglages, "n-importe", "assistant")
    assert entree is not None and entree["url"] == "http://127.0.0.1:8787/mcp/onyxia"


def test_sans_onyxia_dans_le_pool_personne_ne_le_recoit(tmp_path: Path) -> None:
    reglages = _reglages(tmp_path)
    _poser(reglages, "carte", {"pod": POD})
    assert ox.onyxia_pour_projet(reglages, "carte", "code", pool={"github": {}}) is None
    assert ox.onyxia_pour_projet(reglages, "carte", "assistant", pool={}) is None
    assert ox.onyxia_pour_projet(reglages, "carte", "code", pool={"Onyxia": {}}) is not None


def test_profil_inconnu_ne_recoit_rien(tmp_path: Path) -> None:
    assert ox.onyxia_pour_projet(_reglages(tmp_path), "carte", "invite") is None


# ── Le filtre du profil code ────────────────────────────────────────────


def test_code_voit_seulement_les_outils_de_son_pod() -> None:
    noms = {o["name"] for o in ox.outils_visibles("code", _borne(), OUTILS_AMONT)}
    assert noms == {"exec", "job_poll", "read_file", "write_file", "list_files", "session_status", "project_bind"}


def test_code_avec_gpu_et_service() -> None:
    noms = {o["name"] for o in ox.outils_visibles("code", _borne(gpu=True), OUTILS_AMONT)}
    assert {"gpu_switch", "gpu_release", "gpu_status"} <= noms
    service = ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml"))
    noms = {o["name"] for o in ox.outils_visibles("code", service, OUTILS_AMONT)}
    assert noms == {"service_deploy", "service_status", "service_stop"}


def test_code_sans_deploiement_ne_voit_rien() -> None:
    assert ox.outils_visibles("code", None, OUTILS_AMONT) == []


def test_les_arguments_imposes_disparaissent_du_schema() -> None:
    exec_ = next(o for o in ox.outils_visibles("code", _borne(), OUTILS_AMONT) if o["name"] == "exec")
    assert "session_id" not in exec_["inputSchema"]["properties"]
    assert exec_["inputSchema"]["required"] == ["code"]
    assert POD in exec_["description"]
    # L'original du pool n'est pas modifié.
    assert "session_id" in OUTILS_AMONT[0]["inputSchema"]["properties"]


def test_code_la_session_du_projet_est_imposee() -> None:
    envoyes = ox.filtrer_appel("code", _borne(), "exec", {"code": "print(1)"})
    assert envoyes == {"code": "print(1)", "session_id": "proj-carte"}
    # La même valeur, donnée par l'agent, passe.
    assert ox.filtrer_appel("code", _borne(), "exec", {"code": "1", "session_id": "proj-carte"})["session_id"] == "proj-carte"


@pytest.mark.parametrize(
    ("outil", "arguments"),
    [
        ("exec", {"code": "1", "session_id": "proj-autre"}),
        ("read_file", {"path": "/x", "session_id": "proj-claude-code"}),
        ("project_bind", {"pod": "proj-autre-jupyter-python-0"}),
        ("project_bind", {"project": "autre"}),
        ("project_bind", {"namespace": "user-quelqu-un"}),
        ("exec", {"code": "1", "attach_pod": "proj-autre-jupyter-python-0"}),
        ("exec", {"code": "1", "namespace": "user-quelqu-un"}),
    ],
)
def test_code_les_arguments_visant_un_autre_pod_sont_refuses(outil: str, arguments: dict[str, Any]) -> None:
    with pytest.raises(ox.RefusOnyxia):
        ox.filtrer_appel("code", _borne(), outil, arguments)


@pytest.mark.parametrize(
    "outil",
    ["list_pods", "session_start", "session_stop", "project_start", "push_repo", "service_deploy", "gpu_switch"],
)
def test_code_les_autres_outils_sont_refuses(outil: str) -> None:
    with pytest.raises(ox.RefusOnyxia):
        ox.filtrer_appel("code", _borne(), outil, {})


def test_code_gpu_borne_au_projet_et_sans_preemption() -> None:
    borne = _borne(gpu=True)
    # La session attachée est celle du GPU, pas celle du pod CPU : les deux pods se travaillent dans le même tour.
    assert ox.filtrer_appel("code", borne, "gpu_switch", {}) == {
        "project": "carte", "session_id": "proj-carte-gpu", "preempt": False,
    }
    for arguments in ({"project": "autre"}, {"preempt": True}):
        with pytest.raises(ox.RefusOnyxia):
            ox.filtrer_appel("code", borne, "gpu_switch", arguments)
    with pytest.raises(ox.RefusOnyxia):
        ox.filtrer_appel("code", borne, "gpu_release", {"project": "autre"})


def test_code_service_borne_a_son_yaml() -> None:
    borne = ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml"))
    assert ox.filtrer_appel("code", borne, "service_stop", {}) == {"yaml_path": "carte.service.yml"}
    with pytest.raises(ox.RefusOnyxia):
        ox.filtrer_appel("code", borne, "service_deploy", {"yaml_path": "autre.service.yml"})
    with pytest.raises(ox.RefusOnyxia):
        ox.filtrer_appel("code", borne, "exec", {"code": "1"})


@pytest.mark.parametrize("profil", ["code", "assistant"])
@pytest.mark.parametrize("outil", ["expose_public", "unexpose_public"])
def test_exposer_est_toujours_refuse(profil: str, outil: str) -> None:
    with pytest.raises(ox.RefusOnyxia, match="réservé"):
        ox.filtrer_appel(profil, _borne(), outil, {"session_id": "proj-carte"})  # type: ignore[arg-type]


# ── Le profil assistant ─────────────────────────────────────────────────


def test_assistant_est_complet() -> None:
    visibles = ox.outils_visibles("assistant", None, OUTILS_AMONT)
    assert [o["name"] for o in visibles] == [o["name"] for o in OUTILS_AMONT]
    expose = next(o for o in visibles if o["name"] == "expose_public")
    assert expose["_meta"]["atelier/commande"]["classe"] == "reservee"
    # Ses arguments passent tels quels, vers n'importe quel pod.
    arguments = {"session_id": "proj-autre", "code": "1"}
    assert ox.filtrer_appel("assistant", None, "exec", arguments) == arguments
    assert ox.filtrer_appel("assistant", None, "list_pods", {}) == {}


# ── Le mandataire ───────────────────────────────────────────────────────


def test_le_mandataire_repond_a_l_initialisation_sans_onyxia() -> None:
    faux = FauxOnyxia()
    m = _mandataire(faux)
    init = asyncio.run(m.traiter({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}, "code", _borne()))
    assert init["result"]["protocolVersion"] == "2025-03-26"
    assert POD in init["result"]["instructions"]
    assert asyncio.run(m.traiter({"jsonrpc": "2.0", "method": "notifications/initialized"}, "code", _borne())) is None
    liste = asyncio.run(m.traiter({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, "code", _borne()))
    assert {o["name"] for o in liste["result"]["tools"]} >= {"exec", "read_file"}
    # Rien de tout cela n'a touché Onyxia.
    assert faux.appels == []


def test_le_mandataire_attache_la_session_du_projet_a_son_pod() -> None:
    faux = FauxOnyxia()
    m = _mandataire(faux)
    resultat = _appel(m, "code", _borne(), "exec", {"code": "print(1)"})
    assert not resultat["isError"], resultat
    assert faux.envoyes("project_bind") == [{"session_id": "proj-carte", "pod": POD, "project": "carte"}]
    assert faux.envoyes("exec") == [{"code": "print(1)", "session_id": "proj-carte"}]
    # Vérifiée une fois : l'appel suivant ne revérifie pas.
    _appel(m, "code", _borne(), "exec", {"code": "print(2)"})
    assert len(faux.envoyes("session_status")) == 1


def test_le_mandataire_refuse_une_session_partie_sur_un_autre_pod() -> None:
    faux = FauxOnyxia({"proj-carte": "proj-autre-jupyter-python-0"})
    resultat = _appel(_mandataire(faux), "code", _borne(), "exec", {"code": "1"})
    assert resultat["isError"]
    assert "pas le pod CPU du projet" in _charge(resultat)["refus"]
    assert faux.envoyes("exec") == []


def test_le_mandataire_admet_le_pod_gpu_du_projet_sur_sa_session_gpu() -> None:
    faux = FauxOnyxia({"proj-carte": POD, "proj-carte-gpu": "proj-carte-gpu-jupyter-pytorch-gpu-0"})
    resultat = _appel(_mandataire(faux), "code", _borne(gpu=True), "exec", {"code": "1", "cible": "gpu"})
    assert not resultat["isError"], resultat
    assert faux.envoyes("exec") == [{"code": "1", "session_id": "proj-carte-gpu"}]


def test_la_session_du_pod_cpu_n_est_pas_admise_sur_le_gpu() -> None:
    """Avant les deux sessions, gpu_switch déplaçait `proj-<slug>` sur le GPU : une exécution « cpu » partait au GPU."""
    faux = FauxOnyxia({"proj-carte": "proj-carte-gpu-jupyter-pytorch-gpu-0"})
    resultat = _appel(_mandataire(faux), "code", _borne(gpu=True), "exec", {"code": "1"})
    assert resultat["isError"] and "pas le pod CPU" in _charge(resultat)["refus"]
    assert faux.envoyes("exec") == []


def test_le_mandataire_rend_le_refus_a_l_agent_sans_appeler_onyxia() -> None:
    faux = FauxOnyxia({"proj-carte": POD})
    m = _mandataire(faux)
    for outil, arguments in [("exec", {"code": "1", "session_id": "proj-autre"}), ("expose_public", {}), ("list_pods", {})]:
        resultat = _appel(m, "code", _borne(), outil, arguments)
        assert resultat["isError"] and "refus" in _charge(resultat)
    assert faux.appels == []


def test_le_mandataire_assistant_passe_tout_sauf_le_reserve() -> None:
    faux = FauxOnyxia({"proj-autre": "proj-autre-jupyter-python-0"})
    m = _mandataire(faux)
    assert not _appel(m, "assistant", None, "exec", {"session_id": "proj-autre", "code": "1"})["isError"]
    assert _appel(m, "assistant", None, "expose_public", {"session_id": "proj-autre"})["isError"]
    assert [o for o, _ in faux.appels] == ["exec"]


def test_une_panne_d_onyxia_revient_a_l_agent() -> None:
    async def panne(outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("amont hors ligne")

    m = ox.MandataireOnyxia(panne, lambda: OUTILS_AMONT)
    resultat = _appel(m, "assistant", None, "list_pods", {})
    assert resultat["isError"] and "injoignable" in _charge(resultat)["refus"]


# ── Le GPU : relecture du 03/10 ─────────────────────────────────────────


def test_gpu_switch_sans_pod_cpu_attache_quand_meme_la_session_gpu() -> None:
    """Projet en `service` + `gpu` : pas de session `proj-<slug>`, mais celle du GPU existe toujours."""
    borne = ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml", gpu=True))
    envoye = ox.filtrer_appel("code", borne, "gpu_switch", {})
    assert envoye == {"project": "carte", "session_id": "proj-carte-gpu", "preempt": False}


def test_l_assistant_ne_preempte_pas_le_gpu_d_un_autre() -> None:
    """Un modèle demande ; préempter est un geste de la personne (gpu-arbitrage.md §2)."""
    with pytest.raises(ox.RefusOnyxia, match="préempter"):
        ox.filtrer_appel("assistant", None, "gpu_switch", {"project": "x", "preempt": True})
    assert ox.filtrer_appel("assistant", None, "gpu_switch", {"project": "x"})["preempt"] is False
    assert ox.filtrer_appel("assistant", None, "gpu_switch", {"project": "x", "preempt": False})["preempt"] is False
    # Les autres outils de l'Assistant ne sont pas touchés.
    assert ox.filtrer_appel("assistant", None, "exec", {"code": "1"}) == {"code": "1"}


class OnyxiaGpu(FauxOnyxia):
    """Un GPU qu'on peut déclarer pris : `gpu_switch` échoue alors, et `gpu_release` se note."""

    def __init__(self, pris: bool) -> None:
        super().__init__({"proj-carte": POD, "proj-carte-gpu": "proj-carte-gpu-jupyter-pytorch-gpu-0"})
        self.pris = pris

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if outil == "gpu_switch" and self.pris:
            self.appels.append((outil, dict(arguments)))
            return _texte({"error": {"code": "GPU_HELD", "message": "tenu par proj-depth-models"}}, erreur=True)
        return await super().appeler(outil, arguments)


def _avec_journal(faux: FauxOnyxia) -> tuple[ox.MandataireOnyxia, list[dict[str, Any]]]:
    ecrit: list[dict[str, Any]] = []
    return ox.MandataireOnyxia(faux.appeler, faux.outils, journal=ecrit.append), ecrit


def test_un_gpu_switch_refuse_ne_relache_rien_mais_dit_quoi_faire() -> None:
    """Relâcher de soi-même pourrait faire perdre un GPU légitimement tenu : l'agent décide."""
    faux = OnyxiaGpu(pris=True)
    m, _ = _avec_journal(faux)
    resultat = _appel(m, "code", _borne(gpu=True), "gpu_switch", {})
    assert resultat["isError"]
    assert faux.envoyes("gpu_release") == []
    texte = " ".join(b["text"] for b in resultat["content"])
    assert "GPU_HELD" in texte and "gpu_release" in texte


def test_un_gpu_switch_reussi_reste_tel_quel() -> None:
    faux = OnyxiaGpu(pris=False)
    m, _ = _avec_journal(faux)
    resultat = _appel(m, "code", _borne(gpu=True), "gpu_switch", {})
    assert not resultat["isError"] and len(resultat["content"]) == 1


def test_chaque_appel_gpu_laisse_une_trace() -> None:
    faux = OnyxiaGpu(pris=True)
    m, ecrit = _avec_journal(faux)
    _appel(m, "code", _borne(gpu=True), "gpu_switch", {})
    _appel(m, "code", _borne(gpu=True), "gpu_status", {})
    _appel(m, "code", _borne(gpu=True), "exec", {"code": "1"})  # pas du GPU : pas de ligne
    assert [(e["outil"], e["ok"]) for e in ecrit] == [("gpu_switch", False), ("gpu_status", True)]
    assert ecrit[0]["projet"] == "carte" and ecrit[0]["profil"] == "code"
    assert "GPU_HELD" in ecrit[0]["resultat"] and "ts" in ecrit[0]


def test_un_refus_du_filtre_est_aussi_journalise() -> None:
    m, ecrit = _avec_journal(OnyxiaGpu(pris=False))
    _appel(m, "code", _borne(gpu=True), "gpu_switch", {"preempt": True})
    assert [(e["outil"], e["ok"]) for e in ecrit] == [("gpu_switch", False)]
    assert "refus" in ecrit[0]["resultat"]


# ── Le plafond d'un exec synchrone (mise à jour d'Onyxia du 11/10) ──────


def test_un_exec_synchrone_plus_long_que_le_plafond_recoit_l_indice() -> None:
    faux = FauxOnyxia({"proj-carte": POD})
    resultat = _appel(
        _mandataire(faux), "code", _borne(), "exec", {"code": "sleep 200", "lang": "bash", "timeout": 300}
    )
    assert not resultat["isError"]
    texte = " ".join(b["text"] for b in resultat["content"])
    assert "40 s" in texte and "background=true" in texte and "job_poll" in texte


def test_un_exec_court_ou_en_arriere_plan_reste_tel_quel() -> None:
    faux = FauxOnyxia({"proj-carte": POD})
    m = _mandataire(faux)
    court = _appel(m, "code", _borne(), "exec", {"code": "ls", "timeout": 10})
    assert len(court["content"]) == 1
    fond = _appel(m, "code", _borne(), "exec", {"code": "train.py", "background": True, "timeout": 3600})
    assert len(fond["content"]) == 1, "en arrière-plan le plafond ne s'applique pas"


def test_un_exec_coupe_par_le_delai_dit_comment_faire_autrement() -> None:
    class Coupe(FauxOnyxia):
        async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if outil == "exec":
                return _texte({"error": {"code": "TIMEOUT", "message": "timed out after 40s"}}, erreur=True)
            return await super().appeler(outil, arguments)

    resultat = _appel(
        _mandataire(Coupe({"proj-carte": POD})), "code", _borne(), "exec", {"code": "make"}
    )
    assert resultat["isError"]
    assert "background=true" in " ".join(b["text"] for b in resultat["content"])


# ── Un pod muet : le pont d'exécution n'est pas démarré (constaté le 12/10 sur proj-mobscidata) ──


class PodMuet(FauxOnyxia):
    """Un pod dont le pont ne répond à rien : chaque `exec` finit par « The operation timed out »."""

    def __init__(self, sessions: dict[str, str] | None = None) -> None:
        super().__init__(sessions)
        self.execs = 0

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if outil in ox.OUTILS_D_EXECUTION:
            self.execs += 1
            return {"content": [{"type": "text", "text": "The operation timed out."}], "isError": True}
        if outil == "session_status":
            return _texte({"session_id": arguments["session_id"], "pod": POD, "kernel_alive": False})
        return await super().appeler(outil, arguments)


def _textes(resultat: dict[str, Any]) -> str:
    return " ".join(b["text"] for b in resultat["content"])


@pytest.fixture()
def silence_immediat(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sans attendre 50 s : tout délai compte comme un silence du pod."""
    monkeypatch.setattr(ox, "SILENCE_DU_POD_S", 0.0)


def test_un_pod_muet_est_dit_et_pas_le_plafond_d_exec(silence_immediat: None) -> None:
    faux = PodMuet({"proj-carte": POD})
    texte = _textes(_appel(_mandataire(faux), "code", _borne(), "exec", {"code": 'print("hello")', "lang": "python"}))
    assert "n'a pas répondu à `exec`" in texte and "kernel_alive=false" in texte
    assert "pont d'exécution" in texte and "redémarrer le noyau" in texte
    assert "plafonne" not in texte, "une commande triviale qui reste sans réponse n'est pas le plafond d'exec"


def test_apres_deux_silences_l_agent_n_attend_plus_pour_rien(silence_immediat: None) -> None:
    faux = PodMuet({"proj-carte": POD})
    m = _mandataire(faux)
    _appel(m, "code", _borne(), "exec", {"code": "echo 1"})
    deuxieme = _textes(_appel(m, "code", _borne(), "exec", {"code": "echo 2"}))
    assert "2e appel de suite" in deuxieme and faux.execs == 2
    refus = _appel(m, "code", _borne(), "read_file", {"path": "x"})
    assert refus["isError"] and faux.execs == 2, "le troisième appel ne part pas : il ne ferait qu'attendre"
    assert "inutile de réessayer" in _textes(refus) and "avancez" in _textes(refus)


def test_le_silence_est_oublie_apres_la_pause(silence_immediat: None, monkeypatch: pytest.MonkeyPatch) -> None:
    faux = PodMuet({"proj-carte": POD})
    m = _mandataire(faux)
    for _ in range(2):
        _appel(m, "code", _borne(), "exec", {"code": "echo"})
    monkeypatch.setattr(ox, "POD_MUET_PAUSE_S", 0.0)
    _appel(m, "code", _borne(), "exec", {"code": "echo"})
    assert faux.execs == 3, "après la pause un nouvel essai est permis"


def test_un_pod_qui_repond_efface_le_silence(silence_immediat: None) -> None:
    class Revient(PodMuet):
        muet = True

        async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if outil in ox.OUTILS_D_EXECUTION and not self.muet:
                return _texte({"ok": outil})
            return await super().appeler(outil, arguments)

    faux = Revient({"proj-carte": POD})
    m = _mandataire(faux)
    _appel(m, "code", _borne(), "exec", {"code": "echo"})
    faux.muet = False
    assert not _appel(m, "code", _borne(), "exec", {"code": "echo"})["isError"]
    faux.muet = True
    texte = _textes(_appel(m, "code", _borne(), "exec", {"code": "echo"}))
    assert "2e appel" not in texte and "1e" not in texte, "la série repart de zéro"


def test_les_sessions_sans_pod_ni_l_assistant_ne_sont_pas_suivis(silence_immediat: None) -> None:
    faux = PodMuet({"proj-carte": POD})
    m = _mandataire(faux)
    for _ in range(3):
        _appel(m, "assistant", None, "exec", {"session_id": "proj-carte", "code": "echo"})
    assert faux.execs == 3, "l'Assistant n'est pas borné par ce suivi"


def test_une_commande_coupee_au_plafond_garde_son_indice_habituel() -> None:
    """Coupée à ~40 s, elle dit le plafond d'exec : seul un silence de 50 s ou plus est un pod muet."""
    faux = PodMuet({"proj-carte": POD})
    texte = _textes(_appel(_mandataire(faux), "code", _borne(), "exec", {"code": "make"}))
    assert "background=true" in texte and "n'a pas répondu" not in texte


def test_sonder_dit_pret_muet_ou_refuse() -> None:
    pret = asyncio.run(_mandataire(FauxOnyxia({"proj-carte": POD})).sonder(_borne()))
    assert pret == {"etat": "pret"}

    class Lent(FauxOnyxia):
        async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
            await asyncio.sleep(1)
            return _texte({"ok": 1})

    muet = asyncio.run(_mandataire(Lent({"proj-carte": POD})).sonder(_borne(), delai_s=0.05))
    assert muet["etat"] == "muet" and "pas de réponse" in muet["detail"]
    delai = asyncio.run(_mandataire(PodMuet({"proj-carte": POD})).sonder(_borne()))
    assert delai["etat"] == "muet"
    sans_pod = asyncio.run(_mandataire(FauxOnyxia()).sonder(ox.borne_du_projet("carte", structure.Deploiement(service="a.service.yml"))))
    assert sans_pod == {"etat": "sans_pod"}


# ── Le GPU d'un projet au nom long, et le dossier du projet dans un pod neuf (14/10) ─────────────────────
# `gaussian-splatting-capture-render` (33 caractères) : le pod GPU porte un nom court que le courtier GPU
# calcule (D-72) ; sans lui, le filtre refusait la session rattachée au GPU du projet. Et son pod CPU, volume
# vide, n'avait pas le dossier du projet : tout `exec` bash y échouait, même `echo`.

LONG = "gaussian-splatting-capture-render"


def test_le_nom_gpu_court_est_celui_du_courtier() -> None:
    assert ox.nom_gpu_du_projet("carte") == "carte"
    assert ox.nom_gpu_du_projet("a" * 23) == "a" * 23
    # Figé : le pod réellement lancé le 13/10 s'appelle proj-gaussian-splat-a7bfea92-gpu-jupyter-pytorch-gpu-0.
    assert ox.nom_gpu_du_projet(LONG) == "gaussian-splat-a7bfea92"
    assert len(f"proj-{ox.nom_gpu_du_projet(LONG)}-gpu-jupyter-pytorch-gpu") + 11 <= 63
    assert ox.nom_gpu_du_projet("x" * 14 + "-" + "y" * 20).startswith("x" * 14 + "-")


def test_la_borne_admet_le_pod_gpu_au_nom_court_et_aucun_autre() -> None:
    borne = ox.borne_du_projet(LONG, structure.Deploiement(pod="proj-g-jupyter-python-0", gpu=True))
    assert borne.pod_admis("proj-gaussian-splat-a7bfea92-gpu-jupyter-pytorch-gpu-0")
    assert borne.pod_admis("proj-g-jupyter-python-0")
    assert not borne.pod_admis("proj-autre-projet-gpu-jupyter-pytorch-gpu-0")
    assert not borne.pod_admis("proj-gaussian-splat-ffffffff-gpu-jupyter-pytorch-gpu-0"), "un autre projet au même début"
    sans_gpu = ox.borne_du_projet(LONG, structure.Deploiement(pod="proj-g-jupyter-python-0"))
    assert not sans_gpu.pod_admis("proj-gaussian-splat-a7bfea92-gpu-jupyter-pytorch-gpu-0")


class SansDossier(FauxOnyxia):
    """Un pod neuf : le dossier du projet n'existe pas tant qu'un `makedirs` ne l'a pas créé."""

    def __init__(self, *, creation_ok: bool = True) -> None:
        super().__init__()
        self.cree = False
        self.creation_ok = creation_ok

    async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if outil == "exec" and arguments.get("session_id") in self.sessions:
            self.appels.append((outil, dict(arguments)))
            if arguments.get("lang") == "python" and "makedirs" in arguments["code"]:
                self.cree = self.creation_ok
                return _texte({"stdout": "ok\n"}) if self.creation_ok else _texte({"error": {"code": "X"}}, erreur=True)
            if arguments.get("lang") == "bash" and not self.cree:
                return _texte({"rc": -1, "stdout": "", "stderr": "[Errno 2] No such file or directory: '/work/projects/carte'"})
            return _texte({"rc": 0, "stdout": "bonjour\n", "stderr": ""})
        return await super().appeler(outil, arguments)


def test_un_exec_bash_dans_un_pod_neuf_cree_le_dossier_du_projet_et_se_rejoue() -> None:
    faux = SansDossier()
    resultat = _appel(_mandataire(faux), "code", _borne(), "exec", {"code": "echo bonjour", "lang": "bash"})
    assert _charge(resultat) == {"rc": 0, "stdout": "bonjour\n", "stderr": ""}
    exec_ = faux.envoyes("exec")
    assert [a["lang"] for a in exec_] == ["bash", "python", "bash"], "essai, création, rejeu"
    assert "'/work/projects/carte'" in exec_[1]["code"]
    # Une fois le dossier là, le geste suivant n'a plus rien à réparer.
    _appel(_mandataire(faux), "code", _borne(), "exec", {"code": "ls", "lang": "bash"})
    assert [a["lang"] for a in faux.envoyes("exec")][-1] == "bash" and len(faux.envoyes("exec")) == 4


def test_la_creation_du_dossier_qui_echoue_laisse_l_erreur_telle_quelle() -> None:
    faux = SansDossier(creation_ok=False)
    resultat = _appel(_mandataire(faux), "code", _borne(), "exec", {"code": "echo", "lang": "bash"})
    assert "No such file or directory" in _charge(resultat)["stderr"]
    assert [a["lang"] for a in faux.envoyes("exec")] == ["bash", "python"], "pas de rejeu sans dossier"


def test_un_autre_dossier_manquant_n_est_pas_cree() -> None:
    """Seul le dossier de CE projet est créé : un chemin quelconque cité par une erreur ne l'est jamais."""

    class AutreChemin(SansDossier):
        async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if outil == "exec" and arguments.get("lang") == "bash":
                self.appels.append((outil, dict(arguments)))
                return _texte({"rc": 1, "stdout": "", "stderr": "cat: /etc/secret: No such file or directory: '/etc/secret'"})
            return await super().appeler(outil, arguments)

    faux = AutreChemin()
    _appel(_mandataire(faux), "code", _borne(), "exec", {"code": "cat /etc/secret", "lang": "bash"})
    assert [a["lang"] for a in faux.envoyes("exec")] == ["bash"]


def test_un_exec_python_ou_en_arriere_plan_n_est_pas_rejoue_pour_un_dossier() -> None:
    faux = SansDossier()
    _appel(_mandataire(faux), "code", _borne(), "exec", {"code": "print(1)"})
    assert [a.get("lang") for a in faux.envoyes("exec")] == [None]


# ── Un projet avec GPU : un pod CPU, un pod GPU, deux sessions, une `cible` (14/10) ────────────────────────
# « Dans le cas d'un projet avec GPU, le projet peut avoir un pod CPU et un pod GPU. » Avant : une seule session
# `proj-<projet>` que gpu_switch déplaçait sur le GPU ; l'agent ne voyait qu'un pod à la fois, et le CPU disparaissait.

GPU_POD = "proj-carte-gpu-jupyter-pytorch-gpu-0"


def test_la_borne_dit_ses_cibles_et_leurs_sessions() -> None:
    deux = _borne(gpu=True)
    assert deux.cibles == ("cpu", "gpu") and deux.cible_par_defaut == "cpu"
    assert (deux.session_de("cpu"), deux.session_de("gpu")) == ("proj-carte", "proj-carte-gpu")
    assert (deux.pod_de("cpu"), deux.pod_de("gpu")) == (POD, GPU_POD)
    assert _borne().cibles == ("cpu",)
    seul = ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml", gpu=True))
    assert seul.cibles == ("gpu",) and seul.cible_par_defaut == "gpu"
    assert ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml")).cibles == ()


def test_la_cible_choisit_la_session_et_le_defaut_est_le_pod_cpu() -> None:
    borne = _borne(gpu=True)
    assert ox.filtrer_appel("code", borne, "exec", {"code": "1"})["session_id"] == "proj-carte"
    assert ox.filtrer_appel("code", borne, "exec", {"code": "1", "cible": "cpu"})["session_id"] == "proj-carte"
    envoye = ox.filtrer_appel("code", borne, "exec", {"code": "1", "cible": "gpu"})
    assert envoye == {"code": "1", "session_id": "proj-carte-gpu"}, "`cible` n'est pas envoyé à Onyxia"
    for outil, args in [("job_poll", {"job_id": "j"}), ("read_file", {"path": "/x"}), ("write_file", {"path": "/x", "content": ""}),
                        ("list_files", {}), ("session_status", {})]:
        assert ox.filtrer_appel("code", borne, outil, {**args, "cible": "gpu"})["session_id"] == "proj-carte-gpu"


def test_sans_pod_cpu_les_outils_d_execution_vont_au_gpu() -> None:
    seul = ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml", gpu=True))
    assert ox.filtrer_appel("code", seul, "exec", {"code": "1"}) == {"code": "1", "session_id": "proj-carte-gpu"}
    with pytest.raises(ox.RefusOnyxia, match="pas de pod CPU"):
        ox.filtrer_appel("code", seul, "exec", {"code": "1", "cible": "cpu"})


@pytest.mark.parametrize(
    "borne, args, motif",
    [
        (_borne(), {"cible": "gpu"}, "pas de GPU déclaré"),
        (_borne(gpu=True), {"cible": "tpu"}, "n'existe pas"),
        (_borne(gpu=True), {"cible": "gpu", "session_id": "proj-carte"}, "vise autre chose"),
        (_borne(gpu=True), {"cible": "cpu", "session_id": "proj-carte-gpu"}, "vise autre chose"),
    ],
)
def test_une_cible_hors_projet_ou_une_session_forcee_est_refusee(borne: ox.Borne, args: dict[str, Any], motif: str) -> None:
    with pytest.raises(ox.RefusOnyxia, match=motif):
        ox.filtrer_appel("code", borne, "exec", {"code": "1", **args})


def test_une_cible_inconnue_n_accuse_pas_un_pod_cpu_absent() -> None:
    with pytest.raises(ox.RefusOnyxia) as refus:
        ox.filtrer_appel("code", _borne(gpu=True), "exec", {"code": "1", "cible": "tpu"})
    assert "pas de pod CPU" not in str(refus.value) and "pas de GPU" not in str(refus.value)

def test_cible_n_est_admis_que_sur_les_outils_d_execution() -> None:
    borne = _borne(gpu=True)
    for outil in ("gpu_switch", "gpu_release", "gpu_status", "project_bind"):
        with pytest.raises(ox.RefusOnyxia, match="cible"):
            ox.filtrer_appel("code", borne, outil, {"cible": "gpu"})


def test_gpu_status_dit_le_slot_et_ne_vise_aucune_session() -> None:
    assert ox.filtrer_appel("code", _borne(gpu=True), "gpu_status", {}) == {}


def test_tools_list_montre_cible_seulement_quand_il_y_a_deux_pods() -> None:
    def schema(borne: ox.Borne, nom: str) -> dict[str, Any]:
        return next(o for o in ox.outils_visibles("code", borne, OUTILS_AMONT) if o["name"] == nom)["inputSchema"]

    exec_deux = schema(_borne(gpu=True), "exec")
    assert exec_deux["properties"]["cible"]["enum"] == ["cpu", "gpu"]
    assert "session_id" not in exec_deux["properties"] and exec_deux["required"] == ["code"]
    assert "cible" not in schema(_borne(), "exec")["properties"]
    for outil in ("gpu_switch", "project_bind"):
        assert "cible" not in schema(_borne(gpu=True), outil)["properties"]
    description = next(o for o in ox.outils_visibles("code", _borne(gpu=True), OUTILS_AMONT) if o["name"] == "exec")["description"]
    assert f"cpu: {POD}" in description and f"gpu: {GPU_POD}" in description


def test_le_mandataire_attache_la_session_gpu_au_premier_appel_et_laisse_celle_du_cpu() -> None:
    faux = FauxOnyxia()
    m = _mandataire(faux)
    resultat = _appel(m, "code", _borne(gpu=True), "exec", {"code": "nvidia-smi", "lang": "python", "cible": "gpu"})
    assert not resultat["isError"], resultat
    assert faux.envoyes("project_bind") == [{"session_id": "proj-carte-gpu", "pod": GPU_POD, "project": "carte"}]
    assert faux.sessions == {"proj-carte-gpu": GPU_POD}, "la session du pod CPU n'est pas créée pour autant"
    _appel(m, "code", _borne(gpu=True), "exec", {"code": "1"})
    assert faux.sessions == {"proj-carte-gpu": GPU_POD, "proj-carte": POD}


def test_le_mandataire_dit_de_lancer_le_gpu_quand_son_pod_n_existe_pas() -> None:
    class SansPodGpu(FauxOnyxia):
        async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if outil == "project_bind" and arguments["session_id"].endswith("-gpu"):
                self.appels.append((outil, dict(arguments)))
                return _texte({"error": {"code": "POD_UNREACHABLE", "message": GPU_POD}}, erreur=True)
            return await super().appeler(outil, arguments)

    faux = SansPodGpu()
    resultat = _appel(_mandataire(faux), "code", _borne(gpu=True), "exec", {"code": "1", "cible": "gpu"})
    assert resultat["isError"]
    refus = _charge(resultat)["refus"]
    assert "gpu_switch" in refus and GPU_POD in refus and "POD_UNREACHABLE" in refus
    assert faux.envoyes("exec") == []


def test_une_session_gpu_partie_ailleurs_est_refusee() -> None:
    faux = FauxOnyxia({"proj-carte-gpu": "proj-autre-gpu-jupyter-pytorch-gpu-0"})
    resultat = _appel(_mandataire(faux), "code", _borne(gpu=True), "exec", {"code": "1", "cible": "gpu"})
    assert resultat["isError"] and "pas le pod GPU du projet" in _charge(resultat)["refus"]
    assert faux.envoyes("exec") == []


def test_gpu_switch_et_gpu_release_font_reverifier_la_session_gpu() -> None:
    faux = FauxOnyxia({"proj-carte": POD, "proj-carte-gpu": GPU_POD})
    m = _mandataire(faux)
    borne = _borne(gpu=True)
    _appel(m, "code", borne, "exec", {"code": "1", "cible": "gpu"})
    _appel(m, "code", borne, "exec", {"code": "2", "cible": "gpu"})
    assert len(faux.envoyes("session_status")) == 1, "vérifiée une fois"
    _appel(m, "code", borne, "gpu_release", {})
    _appel(m, "code", borne, "exec", {"code": "3", "cible": "gpu"})
    assert len(faux.envoyes("session_status")) == 2, "un GPU rendu ou relancé : la session est revue"
    assert faux.envoyes("gpu_switch") == [] and faux.envoyes("gpu_release") == [{"project": "carte"}]


def test_gpu_switch_attache_la_session_gpu_sans_toucher_au_cpu() -> None:
    faux = FauxOnyxia({"proj-carte": POD})
    _appel(_mandataire(faux), "code", _borne(gpu=True), "gpu_switch", {})
    assert faux.envoyes("gpu_switch") == [{"project": "carte", "session_id": "proj-carte-gpu", "preempt": False}]
    assert faux.sessions["proj-carte"] == POD


def test_un_gpu_muet_ne_rend_pas_le_pod_cpu_muet(silence_immediat: None) -> None:
    class DeuxPodsMuets(PodMuet):
        async def appeler(self, outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
            if outil == "session_status":  # chaque session dit son vrai pod
                return _texte({"session_id": arguments["session_id"], "pod": self.sessions[arguments["session_id"]]})
            return await super().appeler(outil, arguments)

    faux = DeuxPodsMuets({"proj-carte": POD, "proj-carte-gpu": GPU_POD})
    m = _mandataire(faux)
    borne = _borne(gpu=True)
    for _ in range(2):
        _appel(m, "code", borne, "exec", {"code": "1", "cible": "gpu"})
    resultat = _appel(m, "code", borne, "exec", {"code": "1", "cible": "gpu"})
    assert GPU_POD in _textes(resultat) and "inutile de réessayer" in _textes(resultat)
    cpu = _appel(m, "code", borne, "exec", {"code": "1"})
    assert "inutile de réessayer" not in _textes(cpu), "le pod CPU a sa propre mémoire des silences"


def test_le_dossier_manquant_est_cree_sur_la_session_de_la_cible() -> None:
    faux = SansDossier()
    faux.sessions = {"proj-carte": POD, "proj-carte-gpu": GPU_POD}
    resultat = _appel(_mandataire(faux), "code", _borne(gpu=True), "exec", {"code": "echo", "lang": "bash", "cible": "gpu"})
    assert _charge(resultat)["rc"] == 0
    creation = [a for a in faux.envoyes("exec") if a["lang"] == "python"]
    assert [a["session_id"] for a in creation] == ["proj-carte-gpu"], "le dossier se crée dans le pod visé"


def test_les_instructions_parlent_des_deux_pods() -> None:
    texte = ox.MandataireOnyxia._instructions("code", _borne(gpu=True))
    assert "Deux pods" in texte and GPU_POD in texte and "cible" in texte
    assert "Deux pods" not in ox.MandataireOnyxia._instructions("code", _borne())
    seul = ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml", gpu=True))
    assert GPU_POD in ox.MandataireOnyxia._instructions("code", seul)
