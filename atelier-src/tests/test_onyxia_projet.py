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
    assert ox.filtrer_appel("code", borne, "gpu_switch", {}) == {
        "project": "carte", "session_id": "proj-carte", "preempt": False,
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
    assert "pas le pod du projet" in _charge(resultat)["refus"]
    assert faux.envoyes("exec") == []


def test_le_mandataire_admet_le_pod_gpu_du_projet() -> None:
    faux = FauxOnyxia({"proj-carte": "proj-carte-gpu-jupyter-pytorch-gpu-0"})
    resultat = _appel(_mandataire(faux), "code", _borne(gpu=True), "exec", {"code": "1"})
    assert not resultat["isError"], resultat


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


def test_gpu_switch_sans_pod_n_impose_pas_de_session() -> None:
    """Projet en `service` + `gpu` : il n'y a pas de session `proj-<slug>` à imposer."""
    borne = ox.borne_du_projet("carte", structure.Deploiement(service="carte.service.yml", gpu=True))
    envoye = ox.filtrer_appel("code", borne, "gpu_switch", {})
    assert "session_id" not in envoye and envoye["preempt"] is False and envoye["project"] == "carte"


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
        super().__init__({"proj-carte": "proj-carte-gpu-jupyter-pytorch-gpu-0"})
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
