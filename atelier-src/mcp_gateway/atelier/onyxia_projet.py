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
jamais le serveur Onyxia (écart G3 de `docs/coherence-outils-audit.md`).

Contrat avec la configuration par surface (`mcp_sync`) :
`onyxia_pour_projet(settings, slug, profil)` rend l'entrée `mcpServers`
qu'un agent de ce profil reçoit pour ce projet, ou None.
"""

from __future__ import annotations

import copy
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal
from uuid import uuid4

from mcp_gateway.atelier.commandes import structure

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


class RefusOnyxia(Exception):
    """L'appel ne part pas vers Onyxia ; le message dit pourquoi à l'agent."""


# ── La borne d'un projet ────────────────────────────────────────────────


def session_du_projet(slug: str) -> str:
    """La session Onyxia d'un projet : celle que `project_bind(project=slug)` nomme."""
    return f"proj-{slug}"


def prefixe_des_pods_gpu(slug: str) -> str:
    """Les pods GPU d'un projet (`gpu_broker` : release `proj-<projet>-gpu`)."""
    return f"proj-{slug}-gpu-"


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


def regles_code(borne: Borne) -> dict[str, Regle]:
    """Les outils d'un agent code, bornés à ce déploiement."""
    ns = {"namespace": borne.namespace}
    regles: dict[str, Regle] = {}
    if borne.pod is not None:
        session = {"session_id": borne.session}
        regles.update(
            {
                # Exécuter, lire, écrire, dans le pod du projet.
                "exec": Regle(frozenset({"code", "lang", "timeout", "background"}), session),
                "job_poll": Regle(frozenset({"job_id"}), session),
                "read_file": Regle(frozenset({"path", "max_bytes"}), session),
                "write_file": Regle(frozenset({"path", "content"}), session),
                "list_files": Regle(frozenset({"path", "depth"}), session),
                # État de sa session, et (ré)attachement à son pod.
                "session_status": Regle(frozenset(), session),
                "project_bind": Regle(
                    frozenset(),
                    {**session, "pod": borne.pod, "project": borne.slug, **ns},
                ),
            }
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
                # Son GPU : basculer le slot vers le pod GPU du projet, sans
                # préempter celui d'un autre projet, et le rendre.
                "gpu_switch": Regle(
                    frozenset({"idle_minutes"}),
                    {"project": borne.slug, "session_id": borne.session, "preempt": False, **ns},
                ),
                "gpu_release": Regle(frozenset(), {"project": borne.slug, **ns}),
                "gpu_status": Regle(
                    frozenset(),
                    {"session_id": borne.session} if borne.pod is not None else {**ns},
                ),
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
    sortie: dict[str, Any] = {}
    for cle, valeur in arguments.items():
        if cle in regle.imposes:
            voulu = regle.imposes[cle]
            if voulu is _ABSENT or valeur != voulu:
                raise RefusOnyxia(
                    f"{outil} : {cle}={valeur!r} vise autre chose que le déploiement du projet "
                    f"{borne.slug}" + (f" ({cle} y vaut {voulu!r})" if voulu is not _ABSENT else "")
                )
            continue
        if cle not in regle.libres:
            raise RefusOnyxia(f"{outil} : argument {cle!r} non admis pour un agent de projet")
        sortie[cle] = valeur
    for cle, voulu in regle.imposes.items():
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
            imposes = set(regles[nom].imposes)
            proprietes = schema.get("properties") or {}
            schema["properties"] = {
                k: v for k, v in proprietes.items() if k in regles[nom].libres
            }
            schema["required"] = [r for r in schema.get("required") or [] if r not in imposes]
            copie["inputSchema"] = schema
            cible = borne.pod or borne.service  # type: ignore[union-attr]
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

    def __init__(self, appeler: AppelerAmont, outils_amont: OutilsAmont) -> None:
        self._appeler = appeler
        self._outils_amont = outils_amont
        self._sessions_verifiees: dict[tuple[str, str], float] = {}

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
        try:
            envoyes = filtrer_appel(profil, borne, nom, arguments)
            if profil == "code" and borne is not None and "session_id" in regles_code(borne).get(nom, Regle()).imposes:
                await self._assurer_la_session(borne, nom)
        except RefusOnyxia as exc:
            log.info("onyxia refusé (%s, %s) : %s", profil, nom, exc)
            return _refus_mcp(str(exc))
        try:
            return await self._appeler(nom, envoyes)
        except Exception as exc:  # noqa: BLE001 — l'agent doit voir la panne, pas un 500
            return _refus_mcp(f"Onyxia injoignable : {type(exc).__name__}: {exc}")

    async def _assurer_la_session(self, borne: Borne, outil: str) -> None:
        """La session du projet existe et vise son pod ; sinon on l'attache, ou on refuse.

        Les sessions d'Onyxia sont globales : une autre conversation a pu
        rattacher `proj-<slug>` ailleurs. On ne suit pas une session qui a
        quitté le pod du projet.
        """
        if borne.pod is None or outil in ("project_bind", "gpu_switch"):
            return
        cle = (borne.slug, borne.session)
        if time.monotonic() - self._sessions_verifiees.get(cle, -1e9) < SESSION_VERIFIEE_S:
            return
        etat = await self._appeler("session_status", {"session_id": borne.session})
        erreur = _erreur_de(etat)
        if erreur is not None:
            if erreur.get("code") != "NO_SESSION":
                raise RefusOnyxia(f"session du projet illisible : {erreur}")
            lien = await self._appeler(
                "project_bind",
                filtrer_appel("code", borne, "project_bind", {}),
            )
            erreur = _erreur_de(lien)
            if erreur is not None:
                raise RefusOnyxia(f"session du projet non attachée à {borne.pod} : {erreur}")
            etat = lien
        charge = _charge_de(etat)
        pod = charge.get("pod") if isinstance(charge, dict) else None
        if not isinstance(pod, str) or not borne.pod_admis(pod):
            raise RefusOnyxia(
                f"la session {borne.session} vise {pod!r}, pas le pod du projet ({borne.pod}) : "
                "rattachez-la par project_bind"
            )
        self._sessions_verifiees[cle] = time.monotonic()

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
        if borne.service:
            lignes.append(f"Service : {borne.service}.")
        if borne.commande:
            lignes.append(f"Commande de démarrage : {borne.commande}.")
        if borne.port:
            lignes.append(f"Port : {borne.port}.")
        if borne.gpu:
            lignes.append("GPU : gpu_switch bascule le slot vers le pod GPU du projet, sans préempter.")
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

    return MandataireOnyxia(appeler, outils_amont)


def monter(app: Any) -> MandataireOnyxia:
    """Branche `/mcp/onyxia` (assistant) et `/mcp/onyxia/projet/<slug>` (code).

    Même porteur que `/mcp` : la clé du propriétaire ou un jeton OAuth.
    """
    from fastapi import HTTPException, Request, Response
    from fastapi.responses import JSONResponse

    from mcp_gateway.auth import bearer_from_header, validate_credential

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
