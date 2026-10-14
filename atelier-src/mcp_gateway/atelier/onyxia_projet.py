"""Onyxia pour un projet : ce qu'un agent en reçoit, selon son profil (`docs/onyxia-projet.md`).

Le serveur Onyxia (`sspcloud-mcp`, pod `passerelle-mcp` du namespace) ne sait
pas filtrer par pod : ses sessions sont globales, et chaque outil prend un
`session_id`, un `pod`, un `project` ou un `yaml_path` en argument. Le filtre
se fait donc ici, dans la passerelle de l'Atelier, qui tient déjà une
connexion à Onyxia (`app.state.pool`, préfixe `onyxia`) :

- profil `code` : un point d'entrée par projet, `/mcp/onyxia/projet/<slug>`,
  qui n'expose que les outils bornés au déploiement déclaré dans
  `.atelier/projet.json`. Les arguments qui désignent le pod (session, pod,
  projet, namespace, fichier de service) sont imposés : absents, ils sont
  remplis ; présents avec une autre valeur, l'appel est refusé. Tout autre
  outil est refusé ;
- profil `assistant` : `/mcp/onyxia`, tous les outils, sauf ceux de classe
  `reservee` (`expose_public`, `unexpose_public`), refusés à un modèle comme
  toute commande réservée de l'Atelier.

Ces deux points d'entrée répondent eux-mêmes à `initialize`, à
`notifications/initialized` (202, corps vide et délimité) et à `tools/list`
(depuis la liste que le pool a déjà) : le démarrage d'un tour n'attend plus
jamais le serveur Onyxia (écart G3 de `docs/archives/chantiers/coherence-outils-audit.md`).

Contrat avec la configuration par surface (`mcp_sync`) :
`onyxia_pour_projet(settings, slug, profil)` rend l'entrée `mcpServers`
qu'un agent de ce profil reçoit pour ce projet, ou None.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from mcp_gateway.atelier.commandes import structure
from mcp_gateway.auth import bearer_from_header, validate_credential

log = logging.getLogger("atelier.onyxia_projet")

Profil = Literal["code", "assistant"]
PROFILS = ("code", "assistant")

# Le serveur Onyxia tel que le pool de la passerelle le connaît.
SERVEUR_DU_POOL = "Onyxia"
PREFIXE_DU_POOL = "onyxia"

CHEMIN_COMPLET = "/mcp/onyxia"
CHEMIN_PROJET = "/mcp/onyxia/projet"

# Refusés à tout modèle, quel que soit le profil (socle : `reservee`).
OUTILS_RESERVES = frozenset({"expose_public", "unexpose_public"})

VERSIONS_DU_PROTOCOLE = ("2025-06-18", "2025-03-26", "2024-11-05")
NOM_DU_SERVEUR = "onyxia-atelier"

# Une session vérifiée (bien attachée au pod du projet) n'est pas revérifiée
# avant ce délai : un `session_status` par appel doublerait chaque aller-retour.
SESSION_VERIFIEE_S = 60.0

# Le plafond d'un `exec` synchrone, tel qu'Onyxia le dit dans sa description
# (mise à jour du 11/10) : au-delà, `background=true` et `job_poll`.
PLAFOND_EXEC_SYNCHRONE_S = 40

# Un pod dont le pont d'exécution n'est pas démarré ne répond à rien : chaque appel attend la coupure de la
# passerelle (60 s) puis « The operation timed out ». Constaté le 12/10 sur `proj-mobscidata` (pod de deux
# minutes, `~/work` vide) : cinq `exec` de suite, cinq minutes perdues, et l'agent a conclu « noyau mort ».
# Une attente de cette longueur, sur une commande courte, n'est pas le plafond d'exec : c'est un pod muet.
OUTILS_D_EXECUTION = frozenset({"exec", "read_file", "write_file", "list_files", "job_poll"})
SILENCE_DU_POD_S = 50.0  # une réponse qui met au moins ce temps à échouer est une absence de réponse
SILENCES_MEMORISES_S = 300.0
POD_MUET_APRES = 2  # silences d'affilée au bout desquels on cesse de faire attendre l'agent
POD_MUET_PAUSE_S = 120.0  # puis un nouvel essai est permis


class RefusOnyxia(Exception):
    """L'appel ne part pas vers Onyxia ; le message dit pourquoi à l'agent."""


# ── La borne d'un projet ────────────────────────────────────────────────


def session_du_projet(slug: str) -> str:
    """La session Onyxia d'un projet : celle que `project_bind(project=slug)` nomme."""
    return f"proj-{slug}"


# Kubernetes borne le nom d'un pod (et son label de révision) à 63 caractères : le statefulset
# `proj-<nom>-gpu-jupyter-pytorch-gpu` n'admet que 23 caractères pour <nom>. Au-delà, le courtier GPU
# (`sspcloud_mcp/gpu_broker.py`, D-72) donne au projet un nom court et stable : ses 14 premiers caractères,
# puis les 8 premiers de l'empreinte SHA-1 du slug. Cette règle est la sienne, recopiée : si elle change là-bas,
# elle change ici (`tests/test_onyxia_projet.py` en fige un exemple).
NOM_GPU_MAX = 23


def nom_gpu_du_projet(slug: str) -> str:
    """Le nom qu'un projet porte dans ses pods GPU : le slug, ou son nom court s'il est trop long."""
    if len(slug) <= NOM_GPU_MAX:
        return slug
    return f"{slug[: NOM_GPU_MAX - 9].rstrip('-')}-{hashlib.sha1(slug.encode()).hexdigest()[:8]}"


def prefixe_des_pods_gpu(slug: str) -> str:
    """Les pods GPU d'un projet (`gpu_broker` : release `proj-<nom>-gpu`)."""
    return f"proj-{nom_gpu_du_projet(slug)}-gpu-"


# Le chart GPU du courtier : le pod du projet s'appelle `<prefixe>jupyter-pytorch-gpu-0`.
GPU_CHART = "jupyter-pytorch-gpu"


def session_gpu_du_projet(slug: str) -> str:
    """La session Onyxia du pod GPU d'un projet. Deux pods, deux sessions : celle du pod CPU ne bouge pas."""
    return f"proj-{slug}-gpu"


def pod_gpu_du_projet(slug: str) -> str:
    return f"{prefixe_des_pods_gpu(slug)}{GPU_CHART}-0"


@dataclass(frozen=True)
class Borne:
    """Ce qu'un agent code du projet peut viser, et rien d'autre."""

    slug: str
    session: str
    pod: str | None
    service: str | None
    namespace: str | None
    gpu: bool
    commande: str | None = None
    port: int | None = None

    def pod_admis(self, pod: str) -> bool:
        if self.pod is not None and pod == self.pod:
            return True
        return self.gpu and pod.startswith(prefixe_des_pods_gpu(self.slug))

    # Un projet avec GPU a un pod CPU et un pod GPU : deux cibles, chacune sa session Onyxia.
    @property
    def cibles(self) -> tuple[str, ...]:
        return tuple(c for c, present in (("cpu", self.pod is not None), ("gpu", self.gpu)) if present)

    @property
    def cible_par_defaut(self) -> str:
        return "cpu" if self.pod is not None else "gpu"

    def session_de(self, cible: str) -> str:
        return self.session if cible == "cpu" else session_gpu_du_projet(self.slug)

    def pod_de(self, cible: str) -> str:
        return (self.pod or "") if cible == "cpu" else pod_gpu_du_projet(self.slug)


def borne_du_projet(slug: str, deploiement: structure.Deploiement) -> Borne:
    return Borne(
        slug=slug,
        session=session_du_projet(slug),
        pod=deploiement.pod,
        service=deploiement.service,
        namespace=deploiement.namespace,
        gpu=deploiement.gpu,
        commande=deploiement.commande,
        port=deploiement.port,
    )


# Une valeur imposée à None veut dire : l'argument doit être absent (le
# serveur prendra son défaut, qui est le namespace du pod Onyxia).
_ABSENT = None


@dataclass(frozen=True)
class Regle:
    """Un outil admis : les arguments que l'agent choisit, ceux qu'on impose."""

    libres: frozenset[str] = frozenset()
    imposes: dict[str, Any] = field(default_factory=dict)
    # La session dépend de la cible choisie (`cpu` ou `gpu`) : `session_id` n'est pas figé ici mais résolu.
    par_cible: bool = False


def regles_code(borne: Borne) -> dict[str, Regle]:
    """Les outils d'un agent code, bornés à ce déploiement."""
    ns = {"namespace": borne.namespace}
    regles: dict[str, Regle] = {}
    if borne.cibles:
        # Exécuter, lire, écrire, dans le pod CPU du projet et/ou dans son pod GPU : `cible` choisit.
        def par_cible(libres: frozenset[str]) -> Regle:
            return Regle(libres, {}, par_cible=True)

        regles.update(
            {
                "exec": par_cible(frozenset({"code", "lang", "timeout", "background"})),
                "job_poll": par_cible(frozenset({"job_id"})),
                "read_file": par_cible(frozenset({"path", "max_bytes"})),
                "write_file": par_cible(frozenset({"path", "content"})),
                "list_files": par_cible(frozenset({"path", "depth"})),
                # État d'une session.
                "session_status": par_cible(frozenset()),
            }
        )
    if borne.pod is not None:
        # (Ré)attachement de la session du pod CPU à son pod. Celle du GPU s'attache seule, ou par gpu_switch.
        regles["project_bind"] = Regle(
            frozenset(), {"session_id": borne.session, "pod": borne.pod, "project": borne.slug, **ns}
        )
    if borne.service is not None:
        yaml = {"yaml_path": borne.service}
        regles.update(
            {
                # Son service : état, déploiement, arrêt, préchauffage.
                "service_status": Regle(frozenset(), yaml),
                "service_deploy": Regle(frozenset(), yaml),
                "service_stop": Regle(frozenset(), yaml),
                "service_warm": Regle(frozenset(), yaml),
                "service_provision": Regle(frozenset({"packages", "models", "subdirs"}), yaml),
            }
        )
    if borne.gpu:
        regles.update(
            {
                # Son GPU : basculer le slot vers le pod GPU du projet, sans préempter celui d'un autre projet, et
                # le rendre. La session attachée est celle du GPU (`proj-<projet>-gpu`), jamais celle du pod CPU : les
                # deux pods se travaillent dans le même tour, par `cible`.
                "gpu_switch": Regle(
                    frozenset({"idle_minutes"}),
                    {"project": borne.slug, "session_id": session_gpu_du_projet(borne.slug), "preempt": False, **ns},
                ),
                "gpu_release": Regle(frozenset(), {"project": borne.slug, **ns}),
                # Sans argument : l'état du slot (qui le tient, charge, VRAM). `nvidia-smi` du pod : un `exec`
                # sur la cible `gpu`.
                "gpu_status": Regle(frozenset(), {**ns}),
            }
        )
    return regles


# ── Le filtre ───────────────────────────────────────────────────────────


def filtrer_appel(
    profil: Profil, borne: Borne | None, outil: str, arguments: dict[str, Any] | None
) -> dict[str, Any]:
    """Les arguments à envoyer à Onyxia, ou `RefusOnyxia`.

    Rien n'est réécrit en silence : un argument qui vise autre chose que le
    déploiement du projet est refusé, pas remplacé.
    """
    arguments = dict(arguments or {})
    if outil in OUTILS_RESERVES:
        raise RefusOnyxia(
            f"{outil} est réservé : seule la personne le fait, dans l'Atelier. "
            "Proposez-le dans « À valider »."
        )
    if profil == "assistant":
        if outil == "gpu_switch":
            # Un modèle demande le GPU ; en prendre un à un autre qui le tient est
            # un geste de la personne (docs/vision/gpu-arbitrage.md §2, principe 5).
            if arguments.get("preempt"):
                raise RefusOnyxia(
                    "préempter le GPU d'un autre est un geste de la personne : "
                    "demandez-lui de libérer le GPU, puis rappelez gpu_switch sans preempt."
                )
            arguments["preempt"] = False
        return arguments
    if profil != "code":
        raise RefusOnyxia(f"profil inconnu : {profil}")
    if borne is None:
        raise RefusOnyxia("ce projet n'a pas de déploiement déclaré : pas d'Onyxia pour ses agents")
    regle = regles_code(borne).get(outil)
    if regle is None:
        raise RefusOnyxia(
            f"{outil} n'est pas ouvert aux agents du projet {borne.slug} : seuls les outils "
            "bornés à son déploiement le sont"
        )
    cible = arguments.pop("cible", None)
    imposes = regle.imposes
    if regle.par_cible:
        cible = cible if cible is not None else borne.cible_par_defaut
        if cible not in borne.cibles:
            raise RefusOnyxia(
                f"{outil} : cible={cible!r} n'existe pas pour le projet {borne.slug} "
                f"(cibles : {', '.join(borne.cibles)})"
                + (" — le projet n'a pas de GPU déclaré" if cible == "gpu" else " — le projet n'a pas de pod CPU déclaré")
            )
        imposes = {**imposes, "session_id": borne.session_de(cible)}
    elif cible is not None:
        raise RefusOnyxia(f"{outil} : argument 'cible' non admis")
    sortie: dict[str, Any] = {}
    for cle, valeur in arguments.items():
        if cle in imposes:
            voulu = imposes[cle]
            if voulu is _ABSENT or valeur != voulu:
                raise RefusOnyxia(
                    f"{outil} : {cle}={valeur!r} vise autre chose que le déploiement du projet "
                    f"{borne.slug}" + (f" ({cle} y vaut {voulu!r})" if voulu is not _ABSENT else "")
                )
            continue
        if cle not in regle.libres:
            raise RefusOnyxia(f"{outil} : argument {cle!r} non admis pour un agent de projet")
        sortie[cle] = valeur
    for cle, voulu in imposes.items():
        if voulu is not _ABSENT:
            sortie[cle] = voulu
    return sortie


def outils_visibles(
    profil: Profil, borne: Borne | None, outils_amont: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Ce que `tools/list` montre : les outils admis, sans les arguments imposés."""
    sortie: list[dict[str, Any]] = []
    regles = regles_code(borne) if (profil == "code" and borne is not None) else None
    for outil in outils_amont:
        nom = outil.get("name") if isinstance(outil, dict) else None
        if not isinstance(nom, str):
            continue
        if profil == "code":
            if regles is None or nom not in regles:
                continue
            copie = copy.deepcopy(outil)
            schema = copie.get("inputSchema") or {"type": "object", "properties": {}}
            imposes = set(regles[nom].imposes) | ({"session_id"} if regles[nom].par_cible else set())
            proprietes = schema.get("properties") or {}
            schema["properties"] = {
                k: v for k, v in proprietes.items() if k in regles[nom].libres
            }
            if regles[nom].par_cible and len(borne.cibles) > 1:  # type: ignore[union-attr]
                schema["properties"]["cible"] = {
                    "type": "string",
                    "enum": list(borne.cibles),  # type: ignore[union-attr]
                    "description": (
                        f"Quel pod : « cpu » ({borne.pod}, défaut) ou « gpu » (le pod GPU du projet, "  # type: ignore[union-attr]
                        "lancé par gpu_switch)."
                    ),
                }
            schema["required"] = [r for r in schema.get("required") or [] if r not in imposes]
            copie["inputSchema"] = schema
            cible = (
                " + ".join(f"{c}: {borne.pod_de(c)}" for c in borne.cibles)  # type: ignore[union-attr]
                if regles[nom].par_cible
                else (borne.pod or borne.service)  # type: ignore[union-attr]
            )
            copie["description"] = f"[projet {borne.slug}, {cible}] " + str(copie.get("description") or "")  # type: ignore[union-attr]
            sortie.append(copie)
            continue
        copie = copy.deepcopy(outil)
        if nom in OUTILS_RESERVES:
            copie["description"] = (
                "[réservé : seule la personne le fait, dans l'Atelier] "
                + str(copie.get("description") or "")
            )
            copie.setdefault("_meta", {})["atelier/commande"] = {"classe": "reservee"}
        sortie.append(copie)
    return sortie


# ── L'entrée mcpServers (contrat avec mcp_sync) ─────────────────────────


def lire_le_deploiement(settings: Any, slug: str) -> structure.Deploiement | None:
    """Le déploiement déclaré par le projet ; None s'il n'y en a pas ou si sa fiche est invalide."""
    if not isinstance(slug, str) or not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        return None
    try:
        projet = structure.lire(settings.projects_dir / slug)
    except structure.ErreurProjetJson as exc:
        log.warning("projet %s : fiche invalide, pas d'Onyxia (%s)", slug, exc)
        return None
    return projet.deploiement if projet is not None else None


# Une seule phrase pour dire comment s'ouvre Onyxia à un projet : la liste des
# services, le contexte de l'agent et l'Assistant la reprennent telle quelle.
POUR_DECLARER = "demandez à l'Assistant de relier le projet à son pod ou à son service Onyxia"


def situation_du_deploiement(
    racine: Path, slug: str, *, pool_a_onyxia: bool = True
) -> tuple[Borne | None, str]:
    """Ce qu'Onyxia donne à ce projet, et pourquoi : (borne, raison en une phrase).

    Une fiche cassée n'est pas une absence de déclaration : on le dit, au lieu
    de laisser croire que rien n'a été déclaré.
    """
    if not isinstance(slug, str) or not slug or "/" in slug or "\\" in slug or slug.startswith("."):
        return None, f"aucun déploiement n'est déclaré : {POUR_DECLARER}"
    try:
        projet = structure.lire(Path(racine))
    except structure.ErreurProjetJson as exc:
        return None, f"la fiche du projet (.atelier/projet.json) est invalide, donc Onyxia n'est pas ouvert : {exc}"
    deploiement = projet.deploiement if projet is not None else None
    if deploiement is None:
        return None, f"aucun déploiement n'est déclaré : {POUR_DECLARER}"
    if not pool_a_onyxia:
        return None, "Onyxia n'est pas connecté à l'Atelier"
    return borne_du_projet(slug, deploiement), "borné au déploiement du projet"


def _entree(settings: Any, chemin: str) -> dict[str, Any]:
    # Même porteur que la déclaration de l'Atelier : la clé passe par
    # l'environnement du processus agent, jamais par le fichier.
    return {
        "type": "http",
        "url": f"http://127.0.0.1:{settings.port}{chemin}",
        "headers": {"Authorization": "Bearer ${ATELIER_MCP_KEY}"},
    }


def onyxia_pour_projet(
    settings: Any,
    slug: str,
    profil: str,
    *,
    pool: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """L'entrée `mcpServers` qu'un agent de ce profil reçoit pour ce projet, ou None.

    - `code` : None si le projet n'a pas de `deploiement` ; sinon le point
      d'entrée borné à ce déploiement ;
    - `assistant` : le point d'entrée complet (`expose_public` réservé).

    Dans les deux cas l'agent passe par la passerelle, jamais directement par
    le serveur Onyxia : c'est elle qui répond à `initialized` (G3).
    `pool`, si l'appelant l'a déjà, évite de promettre Onyxia quand le pool ne
    l'a pas.
    """
    if pool is not None and SERVEUR_DU_POOL not in pool:
        return None
    if profil == "assistant":
        return _entree(settings, CHEMIN_COMPLET)
    if profil != "code":
        return None
    if lire_le_deploiement(settings, slug) is None:
        return None
    return _entree(settings, f"{CHEMIN_PROJET}/{slug}")


# ── Le mandataire MCP ───────────────────────────────────────────────────

AppelerAmont = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
OutilsAmont = Callable[[], list[dict[str, Any]]]


def _erreur_de(resultat: dict[str, Any]) -> dict[str, Any] | None:
    """L'erreur structurée d'un résultat d'outil Onyxia (`{"error": {code, …}}`)."""
    if not isinstance(resultat, dict) or not resultat.get("isError"):
        return None
    for bloc in resultat.get("content") or []:
        if isinstance(bloc, dict) and bloc.get("type") == "text":
            try:
                charge = json.loads(bloc.get("text") or "")
            except ValueError:
                return {"code": "", "message": bloc.get("text")}
            if isinstance(charge, dict) and isinstance(charge.get("error"), dict):
                return charge["error"]
    return {"code": ""}


def _charge_de(resultat: dict[str, Any]) -> Any:
    blocs = resultat.get("content") if isinstance(resultat, dict) else None
    for bloc in blocs or []:
        if isinstance(bloc, dict) and bloc.get("type") == "text":
            try:
                return json.loads(bloc.get("text") or "")
            except ValueError:
                return None
    return None


def _refus_mcp(motif: str) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps({"refus": motif}, ensure_ascii=False)}],
        "isError": True,
    }


class MandataireOnyxia:
    """Sert Onyxia en MCP à un profil, sans jamais faire attendre l'initialisation.

    `appeler(outil, arguments)` joint le serveur Onyxia (le pool de la
    passerelle en service) ; `outils_amont()` rend sa liste d'outils déjà
    connue. Les deux sont injectés : les tests s'en passent de serveur.
    """

    def __init__(
        self,
        appeler: AppelerAmont,
        outils_amont: OutilsAmont,
        journal: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._appeler = appeler
        self._outils_amont = outils_amont
        self._journal = journal
        self._sessions_verifiees: dict[tuple[str, str], float] = {}
        self._silences: dict[str, list[float]] = {}  # session -> instants des appels restés sans réponse
        self._noyaux: dict[str, Any] = {}  # session -> kernel_alive, tel que session_status l'a dit

    # Le protocole ---------------------------------------------------------

    async def traiter(self, message: Any, profil: Profil, borne: Borne | None) -> Any:
        """Un message JSON-RPC (ou un lot) ; None pour une notification seule."""
        if isinstance(message, list):
            reponses = [await self._un(m, profil, borne) for m in message]
            reponses = [r for r in reponses if r is not None]
            return reponses or None
        return await self._un(message, profil, borne)

    async def _un(self, message: Any, profil: Profil, borne: Borne | None) -> dict[str, Any] | None:
        if not isinstance(message, dict):
            return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "requête invalide"}}
        methode = message.get("method")
        ident = message.get("id")
        if ident is None:
            # Une notification (dont `notifications/initialized`) : rien à
            # rendre, et surtout rien à attendre.
            return None
        params = message.get("params") or {}
        if methode == "initialize":
            voulue = params.get("protocolVersion") if isinstance(params, dict) else None
            version = voulue if voulue in VERSIONS_DU_PROTOCOLE else VERSIONS_DU_PROTOCOLE[1]
            return self._ok(
                ident,
                {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": NOM_DU_SERVEUR, "version": "1"},
                    "instructions": self._instructions(profil, borne),
                },
            )
        if methode == "ping":
            return self._ok(ident, {})
        if methode == "tools/list":
            return self._ok(ident, {"tools": outils_visibles(profil, borne, self._liste_amont())})
        if methode == "tools/call":
            nom = params.get("name") if isinstance(params, dict) else None
            arguments = params.get("arguments") if isinstance(params, dict) else None
            if not isinstance(nom, str) or (arguments is not None and not isinstance(arguments, dict)):
                return self._erreur(ident, -32602, "tools/call : name et arguments attendus")
            return self._ok(ident, await self.appeler_outil(profil, borne, nom, arguments or {}))
        if methode in ("resources/list", "prompts/list"):
            cle = "resources" if methode == "resources/list" else "prompts"
            return self._ok(ident, {cle: []})
        return self._erreur(ident, -32601, f"méthode inconnue : {methode}")

    # Les outils -----------------------------------------------------------

    async def appeler_outil(
        self, profil: Profil, borne: Borne | None, nom: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        cible = self._cible_visee(borne, arguments)
        suivi = profil == "code" and borne is not None and cible is not None and nom in OUTILS_D_EXECUTION
        if suivi:
            muet = self._pod_muet(borne, cible)  # type: ignore[arg-type]
            if muet:
                return _refus_mcp(muet)
        debut = time.monotonic()
        resultat = await self._appeler_filtre(profil, borne, nom, arguments)
        if suivi and nom == "exec" and (arguments.get("lang") or "python") == "bash":
            resultat = await self._rejouer_apres_dossier(profil, borne, arguments, resultat)  # type: ignore[arg-type]
        duree = time.monotonic() - debut
        if suivi:
            resultat = self._noter_le_silence(borne, nom, duree, resultat, cible)  # type: ignore[arg-type]
        if nom == "exec" and not arguments.get("background"):
            resultat = self._dire_le_plafond_de_exec(arguments, resultat, duree)
        if nom.startswith("gpu_"):
            self._noter(profil, borne, nom, arguments, resultat)
            if nom == "gpu_switch" and resultat.get("isError") and borne is not None and borne.gpu:
                # On ne relâche PAS de soi-même : sans connaître l'état réel du GPU,
                # relâcher pourrait faire perdre au projet un GPU qu'il tient et le
                # modèle chargé dessus. Le nettoyage des demandes sans suite est
                # celui du courtier (docs/vision/gpu-arbitrage.md §7) ; l'agent, lui,
                # sait quoi faire.
                resultat = {
                    **resultat,
                    "content": [
                        *(resultat.get("content") or []),
                        {
                            "type": "text",
                            "text": (
                                "gpu_switch n'a pas abouti. Rien n'a été relâché automatiquement : "
                                "si le pod GPU du projet reste à 0/1, appelez gpu_status puis gpu_release."
                            ),
                        },
                    ],
                }
        return resultat

    @staticmethod
    def _cible_visee(borne: Borne | None, arguments: dict[str, Any]) -> str | None:
        """La cible (`cpu` ou `gpu`) d'un appel d'agent ; None sans borne, ou si l'argument n'est pas une cible du projet."""
        if borne is None or not borne.cibles:
            return None
        cible = arguments.get("cible")
        cible = borne.cible_par_defaut if cible is None else cible
        return cible if cible in borne.cibles else None

    async def _rejouer_apres_dossier(
        self, profil: Profil, borne: Borne, arguments: dict[str, Any], resultat: dict[str, Any]
    ) -> dict[str, Any]:
        """Un `exec` bash s'ouvre dans le dossier du projet ; un pod neuf ne l'a pas : on le crée, on rejoue.

        Le serveur Onyxia lance la commande avec `cwd = …/projects/<projet>`. Dans le pod d'un projet (volume vide,
        code resté dans l'Atelier) ce dossier n'existe pas : `[Errno 2] No such file or directory: '…/projects/<projet>'`,
        pour toute commande, même `echo`. L'agent y voyait un pod cassé alors que le pod allait bien (14/10,
        `gaussian-splatting-capture-render`). Le chemin vient de l'erreur elle-même, et n'est créé que s'il est bien le
        dossier de CE projet. Un seul rejeu : si l'échec persiste, l'agent le lit tel quel.
        """
        texte = " ".join(
            str(b.get("text") or "")
            for b in (resultat.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "text"
        )
        m = re.search(r"No such file or directory: ['\\\"]+(/[^'\\\"]+)", texte)
        if m is None or not m.group(1).rstrip("/").endswith(f"/projects/{borne.slug}"):
            return resultat
        dossier = m.group(1).rstrip("/")
        creation = await self._appeler(
            "exec",
            {
                "session_id": borne.session_de(self._cible_visee(borne, arguments) or borne.cible_par_defaut),
                "lang": "python",
                "code": f"import os\nos.makedirs({dossier!r}, exist_ok=True)\nprint('ok')",
            },
        )
        if creation.get("isError") or "ok" not in json.dumps(creation):
            return resultat
        log.info("onyxia : dossier %s créé dans le pod de %s, commande rejouée", dossier, borne.slug)
        return await self._appeler_filtre(profil, borne, "exec", arguments)

    @staticmethod
    def _dire_le_plafond_de_exec(
        arguments: dict[str, Any], resultat: dict[str, Any], duree: float | None = None
    ) -> dict[str, Any]:
        """Un `exec` synchrone est plafonné par Onyxia (mise à jour du 11/10).

        Le `timeout` au-delà du plafond est ignoré sans bruit : l'agent croit
        avoir laissé 5 minutes à sa commande, elle est coupée à 40 s, et il en
        conclut que le pod est lent ou en panne. L'indice vient avec le
        résultat, au moment où il sert — l'agent n'a rien à retenir.
        """
        texte = " ".join(
            str(b.get("text") or "")
            for b in (resultat.get("content") or [])
            if isinstance(b, dict) and b.get("type") == "text"
        ).lower()
        demande = arguments.get("timeout")
        trop_long = isinstance(demande, (int, float)) and demande > PLAFOND_EXEC_SYNCHRONE_S
        coupe = resultat.get("isError") and ("timeout" in texte or "timed out" in texte or "délai" in texte)
        if coupe and duree is not None and duree >= SILENCE_DU_POD_S:
            coupe = False  # une commande coupée au plafond dure ~40 s ; plus long, c'est le pod qui ne répond pas
        if not (trop_long or coupe):
            return resultat
        return {
            **resultat,
            "content": [
                *(resultat.get("content") or []),
                {
                    "type": "text",
                    "text": (
                        f"Onyxia plafonne un `exec` synchrone à {PLAFOND_EXEC_SYNCHRONE_S} s : un "
                        "`timeout` au-delà est ignoré. Pour une tâche plus longue, relancez avec "
                        "`background=true`, puis suivez-la avec `job_poll`."
                    ),
                },
            ],
        }

    @staticmethod
    def _est_un_delai(resultat: dict[str, Any]) -> bool:
        if not isinstance(resultat, dict) or not resultat.get("isError"):
            return False
        texte = " ".join(
            str(b.get("text") or "") for b in (resultat.get("content") or []) if isinstance(b, dict)
        ).lower()
        return "timed out" in texte or "timeout" in texte or "délai" in texte

    def _noter_le_silence(
        self, borne: Borne, nom: str, duree: float, resultat: dict[str, Any], cible: str = "cpu"
    ) -> dict[str, Any]:
        """Un appel resté sans réponse est dit comme tel ; un appel qui répond efface la mémoire des silences."""
        cle = borne.session_de(cible)
        pod = borne.pod_de(cible)
        if not (self._est_un_delai(resultat) and duree >= SILENCE_DU_POD_S):
            if not (isinstance(resultat, dict) and resultat.get("isError")):
                self._silences.pop(cle, None)
            return resultat
        maintenant = time.monotonic()
        vus = [t for t in self._silences.get(cle, []) if maintenant - t < SILENCES_MEMORISES_S]
        vus.append(maintenant)
        self._silences[cle] = vus
        noyau = self._noyaux.get(cle)
        etat = f" (session_status : kernel_alive={str(bool(noyau)).lower()})" if noyau is not None else ""
        reste = (
            f"C'est le {len(vus)}e appel de suite sans réponse : n'insiste pas, " if len(vus) > 1 else "N'insiste pas : "
        )
        return {
            **resultat,
            "content": [
                *(resultat.get("content") or []),
                {
                    "type": "text",
                    "text": (
                        f"Le pod {pod} n'a pas répondu à `{nom}` en {duree:.0f} s{etat}. Ce n'est pas le plafond "
                        "d'exec (la commande était courte) : le pod ou son pont d'exécution (~/work/.pont) ne répond pas. "
                        f"{reste}dis-le à la personne en une phrase — « le pod {pod} ne répond pas, son pont "
                        "d'exécution n'est pas démarré » — et avance sur ce qui ne demande pas le pod (les fichiers du projet). "
                        "Ne propose pas de « redémarrer le noyau » : il n'a pas démarré."
                    ),
                },
            ],
        }

    def _pod_muet(self, borne: Borne, cible: str = "cpu") -> str:
        """Le refus immédiat d'un appel au pod, s'il vient de rester sans réponse plusieurs fois d'affilée."""
        maintenant = time.monotonic()
        pod = borne.pod_de(cible)
        vus = [t for t in self._silences.get(borne.session_de(cible), []) if maintenant - t < SILENCES_MEMORISES_S]
        if len(vus) < POD_MUET_APRES or maintenant - vus[-1] >= POD_MUET_PAUSE_S:
            return ""
        restant = int(POD_MUET_PAUSE_S - (maintenant - vus[-1]))
        return (
            f"Le pod {pod} n'a pas répondu à vos {len(vus)} derniers appels (le dernier il y a "
            f"{int(maintenant - vus[-1])} s) : inutile de réessayer maintenant, ce serait attendre {int(SILENCE_DU_POD_S)} s "
            "de plus pour rien. Son pont d'exécution n'est probablement pas démarré. Dites-le à la personne, et avancez "
            f"sur ce qui ne demande pas le pod. Un nouvel essai est permis dans {restant} s."
        )

    async def sonder(self, borne: Borne, delai_s: float = 12.0) -> dict[str, Any]:
        """Le pod répond-il à une commande triviale ? « muet » plutôt que de laisser le premier agent attendre 60 s."""
        if borne.pod is None:
            return {"etat": "sans_pod"}
        try:
            envoyes = filtrer_appel("code", borne, "exec", {"code": "echo ok", "lang": "bash", "timeout": 10})
            resultat = await asyncio.wait_for(self._appeler("exec", envoyes), delai_s)
        except asyncio.TimeoutError:
            return {"etat": "muet", "detail": f"pas de réponse en {delai_s:.0f} s"}
        except RefusOnyxia as exc:
            return {"etat": "refuse", "detail": str(exc)}
        except Exception as exc:  # noqa: BLE001
            return {"etat": "injoignable", "detail": type(exc).__name__}
        if self._est_un_delai(resultat):
            return {"etat": "muet", "detail": "délai dépassé"}
        if isinstance(resultat, dict) and resultat.get("isError"):
            erreur = _erreur_de(resultat) or {}
            return {"etat": "erreur", "detail": str(erreur.get("message") or erreur.get("code") or "erreur")[:200]}
        self._silences.pop(borne.session, None)
        return {"etat": "pret"}

    def _noter(
        self, profil: Profil, borne: Borne | None, outil: str, arguments: dict[str, Any], resultat: dict[str, Any]
    ) -> None:
        """Une ligne par appel GPU : qui, quoi, et ce qu'Onyxia a répondu."""
        if self._journal is None:
            return
        erreur = bool(resultat.get("isError"))
        texte = ""
        for bloc in resultat.get("content") or []:
            if isinstance(bloc, dict) and bloc.get("type") == "text":
                texte = str(bloc.get("text") or "")
                break
        entree = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "profil": profil,
            "projet": borne.slug if borne is not None else "",
            "outil": outil,
            "arguments": arguments,
            "ok": not erreur,
            "resultat": texte[:500],
        }
        try:
            self._journal(entree)
        except Exception:  # noqa: BLE001 — le journal ne doit jamais faire échouer l'appel
            log.warning("journal GPU non écrit", exc_info=True)

    async def _appeler_filtre(
        self, profil: Profil, borne: Borne | None, nom: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            envoyes = filtrer_appel(profil, borne, nom, arguments)
            if profil == "code" and borne is not None:
                regle = regles_code(borne).get(nom, Regle())
                # Les outils de session (exécuter, lire…) : la session visée existe et vise le bon pod. gpu_switch
                # l'attache lui-même ; project_bind est le geste qui répare celle du pod CPU.
                if (regle.par_cible or "session_id" in regle.imposes) and "session_id" in envoyes:
                    await self._assurer_la_session(borne, nom, envoyes["session_id"])
        except RefusOnyxia as exc:
            log.info("onyxia refusé (%s, %s) : %s", profil, nom, exc)
            return _refus_mcp(str(exc))
        try:
            resultat = await self._appeler(nom, envoyes)
        except Exception as exc:  # noqa: BLE001 — l'agent doit voir la panne, pas un 500
            return _refus_mcp(f"Onyxia injoignable : {type(exc).__name__}: {exc}")
        if profil == "code" and borne is not None and borne.gpu and nom in ("gpu_switch", "gpu_release"):
            # Le pod GPU vient d'être lancé, déplacé ou rendu : la vérification gardée de sa session ne vaut plus.
            self._sessions_verifiees.pop((borne.slug, session_gpu_du_projet(borne.slug)), None)
            self._silences.pop(session_gpu_du_projet(borne.slug), None)
        return resultat

    async def _assurer_la_session(self, borne: Borne, outil: str, session: str | None = None) -> None:
        """La session visée existe et vise son pod ; sinon on l'attache, ou on refuse.

        Un projet a une session par pod : `proj-<slug>` (pod CPU) et `proj-<slug>-gpu` (pod GPU). Les sessions
        d'Onyxia sont globales : une autre conversation a pu en rattacher une ailleurs. On ne suit pas une session
        qui a quitté le pod du projet.
        """
        session = session or borne.session
        if outil in ("project_bind", "gpu_switch"):
            return
        cible = "gpu" if session == session_gpu_du_projet(borne.slug) and borne.gpu else "cpu"
        if cible == "cpu" and borne.pod is None:
            return
        cle = (borne.slug, session)
        if time.monotonic() - self._sessions_verifiees.get(cle, -1e9) < SESSION_VERIFIEE_S:
            return
        etat = await self._appeler("session_status", {"session_id": session})
        erreur = _erreur_de(etat)
        if erreur is not None:
            if erreur.get("code") != "NO_SESSION":
                raise RefusOnyxia(f"session du projet illisible : {erreur}")
            lien = await self._appeler("project_bind", self._arguments_de_liaison(borne, cible))
            erreur = _erreur_de(lien)
            if erreur is not None:
                if cible == "gpu":
                    raise RefusOnyxia(
                        f"le pod GPU du projet ({borne.pod_de('gpu')}) n'est pas joignable : lancez-le avec "
                        f"gpu_switch (sans préemption), puis recommencez. Onyxia dit : {erreur}"
                    )
                raise RefusOnyxia(f"session du projet non attachée à {borne.pod} : {erreur}")
            etat = lien
        charge = _charge_de(etat)
        if isinstance(charge, dict) and "kernel_alive" in charge:
            self._noyaux[session] = charge.get("kernel_alive")
        pod = charge.get("pod") if isinstance(charge, dict) else None
        if cible == "cpu":
            admis = isinstance(pod, str) and pod == borne.pod
            attendu = borne.pod
        else:
            admis = isinstance(pod, str) and pod.startswith(prefixe_des_pods_gpu(borne.slug))
            attendu = borne.pod_de("gpu")
        if not admis:
            raise RefusOnyxia(
                f"la session {session} vise {pod!r}, pas le pod {cible.upper()} du projet ({attendu}) : "
                + ("rattachez-la par project_bind" if cible == "cpu" else "relancez gpu_switch")
            )
        self._sessions_verifiees[cle] = time.monotonic()

    @staticmethod
    def _arguments_de_liaison(borne: Borne, cible: str) -> dict[str, Any]:
        """Les arguments de `project_bind` pour la session d'une cible. Le pod CPU passe par le filtre ; le GPU est calculé."""
        if cible == "cpu":
            return filtrer_appel("code", borne, "project_bind", {})
        arguments = {"session_id": session_gpu_du_projet(borne.slug), "pod": borne.pod_de("gpu"), "project": borne.slug}
        if borne.namespace:
            arguments["namespace"] = borne.namespace
        return arguments

    async def lier(self, borne: Borne) -> dict[str, Any]:
        """Attache la session du projet à son pod, par `project_bind` d'Onyxia.

        `project_bind(pod, project)` ouvre une session nommée `proj-<projet>`
        sur ce pod (`session_start(attach_pod=…)`, dossier
        `…/projects/<projet>`). Rend ce qu'Onyxia en dit ; `RefusOnyxia` si
        Onyxia refuse (pod absent, non Running) ; laisse passer une panne de
        transport, que l'appelant distingue.
        """
        self.oublier_la_session(borne.slug)
        resultat = await self._appeler("project_bind", filtrer_appel("code", borne, "project_bind", {}))
        erreur = _erreur_de(resultat)
        if erreur is not None:
            raise RefusOnyxia(f"Onyxia n'attache pas {borne.pod} : {erreur.get('message') or erreur}")
        charge = _charge_de(resultat)
        return charge if isinstance(charge, dict) else {}

    def oublier_la_session(self, slug: str) -> None:
        self._sessions_verifiees = {k: v for k, v in self._sessions_verifiees.items() if k[0] != slug}

    # Utilitaires ----------------------------------------------------------

    def _liste_amont(self) -> list[dict[str, Any]]:
        try:
            return list(self._outils_amont() or [])
        except Exception:  # noqa: BLE001
            log.exception("liste des outils Onyxia")
            return []

    @staticmethod
    def _instructions(profil: Profil, borne: Borne | None) -> str:
        if profil == "assistant":
            return (
                "Onyxia au complet, par la passerelle de l'Atelier. expose_public et "
                "unexpose_public sont réservés à la personne."
            )
        if borne is None:
            return "Ce projet n'a pas de déploiement déclaré : aucun outil Onyxia."
        lignes = [f"Onyxia borné au déploiement du projet {borne.slug}."]
        if borne.pod:
            lignes.append(f"Pod : {borne.pod} ; session imposée : {borne.session}.")
        if borne.pod and borne.gpu:
            lignes.append(
                f"Deux pods : « cpu » ({borne.pod}) et « gpu » ({borne.pod_de('gpu')}, lancé par gpu_switch) ; "
                "exec, read_file, write_file, list_files, job_poll et session_status prennent `cible` (défaut « cpu »)."
            )
        elif borne.gpu and not borne.pod:
            lignes.append(f"Pod GPU : {borne.pod_de('gpu')} (lancé par gpu_switch) ; les outils d'exécution y vont par défaut.")
        if borne.service:
            lignes.append(f"Service : {borne.service}.")
        if borne.commande:
            lignes.append(f"Commande de démarrage : {borne.commande}.")
        if borne.port:
            lignes.append(f"Port : {borne.port}.")
        if borne.gpu:
            lignes.append("GPU : gpu_switch lance ou réveille le pod GPU du projet, sans préempter ; gpu_status dit qui tient le slot.")
        return " ".join(lignes)

    @staticmethod
    def _ok(ident: Any, resultat: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "result": resultat}

    @staticmethod
    def _erreur(ident: Any, code: int, message: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}


# ── Les routes ──────────────────────────────────────────────────────────


def _mandataire_du_pool(app: Any) -> MandataireOnyxia:
    async def appeler(outil: str, arguments: dict[str, Any]) -> dict[str, Any]:
        pool = getattr(app.state, "pool", None)
        if pool is None:
            raise RuntimeError("passerelle sans pool")
        return await pool.call(f"{PREFIXE_DU_POOL}__{outil}", arguments)

    def outils_amont() -> list[dict[str, Any]]:
        pool = getattr(app.state, "pool", None)
        if pool is None:
            return []
        client, _ = pool.resolve_tool(f"{PREFIXE_DU_POOL}__exec")
        return list(getattr(client, "tools", None) or [])

    def journal(entree: dict[str, Any]) -> None:
        # Un fichier d'événements, une ligne JSON par appel : qui tenait le GPU,
        # quand, et pourquoi il a été refusé. Hors des fiches de conversation.
        reglages = getattr(app.state, "settings", None)
        if reglages is None:
            return
        chemin = Path(reglages.work_dir) / "logs" / "gpu.jsonl"
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entree, ensure_ascii=False) + "\n")

    return MandataireOnyxia(appeler, outils_amont, journal=journal)


def monter(app: Any) -> MandataireOnyxia:
    """Branche `/mcp/onyxia` (assistant) et `/mcp/onyxia/projet/<slug>` (code).

    Même porteur que `/mcp` : la clé du propriétaire ou un jeton OAuth.
    """
    mandataire: MandataireOnyxia = getattr(app.state, "onyxia_mandataire", None) or _mandataire_du_pool(app)
    app.state.onyxia_mandataire = mandataire

    def autoriser(request: Request) -> None:
        jeton = bearer_from_header(request.headers.get("Authorization")) or ""
        cle = getattr(getattr(request.app.state, "auth", None), "owner_key", "") or ""
        if jeton and validate_credential(request.app.state.db, jeton, cle):
            return
        raise HTTPException(status_code=401, detail="unauthorized")

    async def servir(request: Request, profil: Profil, borne: Borne | None) -> Response:
        # Le corps est lu avant tout refus : laissé dans la connexion, il
        # serait pris pour la requête suivante (défaut mesuré sur Onyxia).
        brut = await request.body()
        autoriser(request)
        try:
            message = json.loads(brut or b"null")
        except ValueError:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "JSON invalide"}},
                status_code=400,
            )
        reponse = await mandataire.traiter(message, profil, borne)
        entetes: dict[str, str] = {}
        if not request.headers.get("Mcp-Session-Id") and _ouvre(message):
            entetes["Mcp-Session-Id"] = uuid4().hex
        if reponse is None:
            # 202, corps vide et délimité (Content-Length: 0).
            return Response(status_code=202, headers=entetes)
        return JSONResponse(reponse, headers=entetes)

    @app.post(CHEMIN_COMPLET)
    async def onyxia_complet(request: Request) -> Response:
        return await servir(request, "assistant", None)

    @app.post(CHEMIN_PROJET + "/{slug}")
    async def onyxia_du_projet(slug: str, request: Request) -> Response:
        deploiement = lire_le_deploiement(request.app.state.settings, slug)
        borne = borne_du_projet(slug, deploiement) if deploiement is not None else None
        return await servir(request, "code", borne)

    @app.get(CHEMIN_COMPLET)
    @app.get(CHEMIN_PROJET + "/{slug}")
    async def onyxia_sans_flux(request: Request) -> Response:
        # Pas de flux serveur vers client : le transport le permet (405).
        return Response(status_code=405, headers={"Allow": "POST"})

    return mandataire


def _ouvre(message: Any) -> bool:
    if isinstance(message, dict):
        return message.get("method") == "initialize"
    if isinstance(message, list):
        return any(isinstance(m, dict) and m.get("method") == "initialize" for m in message)
    return False


__all__ = [
    "Borne",
    "CHEMIN_COMPLET",
    "CHEMIN_PROJET",
    "MandataireOnyxia",
    "OUTILS_RESERVES",
    "PROFILS",
    "RefusOnyxia",
    "Regle",
    "borne_du_projet",
    "filtrer_appel",
    "lire_le_deploiement",
    "monter",
    "onyxia_pour_projet",
    "outils_visibles",
    "regles_code",
    "session_du_projet",
]
