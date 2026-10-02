"""Le panneau : ce qui s'affiche à droite d'une conversation, en onglets.

Une vue du panneau montre une création d'un projet (une page ou une
application servie par l'hôte des applications). Elle est décrite par un
petit descripteur, le même pour l'interface et pour l'agent :

    {"id": "v_3f9a1c2e", "genre": "creation", "projet": "lecteur-grist",
     "nom": "carte", "chemin": "", "titre": "Carte des parcelles",
     "epingle": "conversation", "par": "agent", "le": "2026-09-25T…"}

Où elle vit (décision J-e) :

- **épinglée à la conversation** : dans le fichier du panneau de cette
  conversation, `<work>/panneau/<conversation>.json`. À côté de la fiche et
  non dedans : un tour en cours tient sa fiche en mémoire et la réécrit en
  finissant ; une vue montrée pendant le tour y serait perdue ;
- **épinglée au projet** : dans `.atelier/projet.json`, clé `vues_epinglees`.
  Elle apparaît alors dans toutes les conversations du projet. Seule cette
  clé est lue ou écrite ici ; le reste du fichier appartient à la structure
  de projet.

« Montrer » (outil `atelier_montrer`) épingle à la conversation et prévient
les onglets ouverts sur elle : le panneau s'ouvre seul (décision J-f).

Ce module porte aussi la lecture des fils wikichat d'une conversation
(`GET /v1/sessions/{id}/fils`), relayée depuis `127.0.0.1:3777/api/fils`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("atelier.panneau")

EPINGLES = ("conversation", "projet")
MAX_VUES = 12
_CHEMIN_INTERDIT = re.compile(r"[\x00-\x1f\x7f\\]")
_ID = re.compile(r"^v_[0-9a-f]{8,16}$")


class VueInvalide(ValueError):
    """Un descripteur qu'on ne peut pas afficher."""


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def chemin_valide(chemin: str) -> str:
    """Un chemin relatif sous la création, sans remontée ni caractère de contrôle."""
    brut = (chemin or "").strip()
    if _CHEMIN_INTERDIT.search(brut) or brut.startswith("//") or "://" in brut:
        raise VueInvalide(f"chemin refusé : {chemin!r}")
    sans_requete = brut.split("?", 1)[0].split("#", 1)[0]
    if any(seg in ("..", ".") for seg in sans_requete.split("/")):
        raise VueInvalide(f"chemin refusé : {chemin!r}")
    return brut.lstrip("/")


def identifiant(projet: str, nom: str, chemin: str) -> str:
    """Le même objet montré deux fois garde son onglet."""
    return "v_" + hashlib.sha1(f"{projet}\n{nom}\n{chemin}".encode()).hexdigest()[:10]


def descripteur(
    projet: str, nom: str, *, chemin: str = "", titre: str = "", epingle: str = "conversation", par: str = "personne"
) -> dict[str, Any]:
    """Le descripteur d'une vue de création, validé."""
    from mcp_gateway.atelier.apps.manifeste import nom_valide
    from mcp_gateway.atelier.artifacts import slug_valide

    if not slug_valide(projet):
        raise VueInvalide(f"projet invalide : {projet!r}")
    if not nom_valide(nom):
        raise VueInvalide(f"nom de création invalide : {nom!r}")
    if epingle not in EPINGLES:
        raise VueInvalide(f"épingle inconnue : {epingle!r}")
    chemin = chemin_valide(chemin)
    return {
        "id": identifiant(projet, nom, chemin),
        "genre": "creation",
        "projet": projet,
        "nom": nom,
        "chemin": chemin,
        "titre": (titre or "").strip()[:120] or nom,
        "epingle": epingle,
        "par": "agent" if par == "agent" else "personne",
        "le": _maintenant(),
    }


def _ecrire_json(chemin: Path, donnees: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".en-cours")
    provisoire.write_text(json.dumps(donnees, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(provisoire, chemin)


def _lire_json(chemin: Path) -> Any:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class Panneau:
    """Les vues des conversations et des projets, et qui prévenir."""

    def __init__(
        self,
        *,
        dossier: Path,
        store: Any,
        dossier_projet: Callable[[str], Path | None],
        publier: Callable[[str, dict[str, Any], str], None] | None = None,
    ) -> None:
        self.dossier = dossier
        self.store = store
        self.dossier_projet = dossier_projet
        self.publier = publier
        self._verrou = threading.Lock()

    # ── Lecture ──────────────────────────────────────────────────────

    def _fichier(self, session_id: str) -> Path:
        if not re.match(r"^[A-Za-z0-9._-]{1,128}$", session_id or ""):
            raise VueInvalide("conversation invalide")
        return self.dossier / f"{session_id}.json"

    def _projet_json(self, projet: str) -> Path | None:
        racine = self.dossier_projet(projet)
        return racine / ".atelier" / "projet.json" if racine else None

    def vues_de_la_conversation(self, session_id: str) -> list[dict[str, Any]]:
        donnees = _lire_json(self._fichier(session_id))
        vues = donnees.get("vues") if isinstance(donnees, dict) else None
        return [v for v in vues or [] if isinstance(v, dict) and _ID.match(str(v.get("id") or ""))]

    def vues_du_projet(self, projet: str) -> list[dict[str, Any]]:
        chemin = self._projet_json(projet)
        donnees = _lire_json(chemin) if chemin else None
        brutes = donnees.get("vues_epinglees") if isinstance(donnees, dict) else None
        vues = []
        for v in brutes or []:
            if not isinstance(v, dict) or v.get("connecteur"):
                continue  # les vues de connecteur viendront avec les bureaux (P4)
            # Forme du schéma de `projet.json` : {artefact, vue, titre} ; on lit
            # aussi l'ancienne forme {nom, chemin, titre} écrite avant l'intégration.
            nom = str(v.get("artefact") or v.get("nom") or "")
            if "artefact" in v:
                chemin = "" if str(v.get("vue") or "/") == "/" else str(v.get("vue"))
            else:
                chemin = str(v.get("chemin") or "")
            try:
                vues.append(
                    descripteur(projet, nom, chemin=chemin, titre=str(v.get("titre") or ""), epingle="projet")
                )
            except VueInvalide:
                continue
        return vues

    def vues(self, session_id: str) -> list[dict[str, Any]]:
        """Ce que le panneau de cette conversation montre : projet d'abord, puis elle."""
        rec = self.store.get(session_id)
        if rec is None:
            raise KeyError(session_id)
        du_projet = self.vues_du_projet(rec.slug)
        vus = {v["id"] for v in du_projet}
        return du_projet + [v for v in self.vues_de_la_conversation(session_id) if v["id"] not in vus]

    # ── Écriture ─────────────────────────────────────────────────────

    def _ecrire_conversation(self, session_id: str, vues: list[dict[str, Any]]) -> None:
        _ecrire_json(self._fichier(session_id), {"vues": vues[-MAX_VUES:]})

    def _ecrire_projet(self, projet: str, vues: list[dict[str, Any]]) -> None:
        chemin = self._projet_json(projet)
        if chemin is None:
            raise VueInvalide(f"projet inconnu : {projet}")
        from mcp_gateway.atelier.commandes.structure import ErreurProjetJson, valider

        donnees = _lire_json(chemin)
        if not isinstance(donnees, dict):
            # Pas encore de projet.json : le minimum que son schéma exige.
            donnees = {"version": 1, "slug": projet, "titre": projet}
        donnees["vues_epinglees"] = [
            {"artefact": v["nom"], "vue": v["chemin"] or "/", "titre": v["titre"]} for v in vues[-MAX_VUES:]
        ]
        try:
            valider(donnees)
        except ErreurProjetJson as exc:
            # On n'écrit jamais un projet.json que le reste de l'Atelier refuserait.
            raise VueInvalide(str(exc)) from None
        _ecrire_json(chemin, donnees)

    def enregistrer(self, session_id: str, vue: dict[str, Any], *, tout_projet: bool = False) -> dict[str, Any]:
        """Épingle une vue, à la conversation ou au projet ; la retire de l'autre.

        Une conversation ne montre que les créations de son projet. Seule
        l'Assistant, qui n'a pas de projet à lui et orchestre ceux des autres,
        passe `tout_projet` : montrer n'écrit rien dans le projet montré, et la
        vue reste épinglée à sa conversation.
        """
        rec = self.store.get(session_id)
        if rec is None:
            raise KeyError(session_id)
        propre = descripteur(
            str(vue.get("projet") or rec.slug), str(vue.get("nom") or ""),
            chemin=str(vue.get("chemin") or ""), titre=str(vue.get("titre") or ""),
            epingle=str(vue.get("epingle") or "conversation"), par=str(vue.get("par") or "personne"),
        )
        if propre["projet"] != rec.slug:
            if not tout_projet:
                raise VueInvalide("une conversation ne montre que les créations de son projet")
            propre["epingle"] = "conversation"
        with self._verrou:
            conv = [v for v in self.vues_de_la_conversation(session_id) if v["id"] != propre["id"]]
            projet = [v for v in self.vues_du_projet(rec.slug) if v["id"] != propre["id"]]
            if propre["epingle"] == "projet":
                projet.append(propre)
                self._ecrire_projet(rec.slug, projet)
                self._ecrire_conversation(session_id, conv)
            else:
                conv.append(propre)
                self._ecrire_conversation(session_id, conv)
                if len(projet) != len(self.vues_du_projet(rec.slug)):
                    self._ecrire_projet(rec.slug, projet)
        return propre

    def retirer(self, session_id: str, vue_id: str) -> bool:
        """Ferme un onglet : il ne revient plus, ni ici ni dans le projet."""
        rec = self.store.get(session_id)
        if rec is None:
            raise KeyError(session_id)
        with self._verrou:
            conv = self.vues_de_la_conversation(session_id)
            projet = self.vues_du_projet(rec.slug)
            reste_conv = [v for v in conv if v["id"] != vue_id]
            reste_projet = [v for v in projet if v["id"] != vue_id]
            if len(reste_conv) != len(conv):
                self._ecrire_conversation(session_id, reste_conv)
            if len(reste_projet) != len(projet):
                self._ecrire_projet(rec.slug, reste_projet)
            return len(reste_conv) != len(conv) or len(reste_projet) != len(projet)

    def montrer(
        self, session_id: str, *, projet: str, nom: str, chemin: str = "", titre: str = "", tout_projet: bool = False
    ) -> dict[str, Any]:
        """Ce que fait l'agent : épingler à la conversation, et ouvrir le panneau."""
        vue = self.enregistrer(
            session_id,
            {"projet": projet, "nom": nom, "chemin": chemin, "titre": titre, "epingle": "conversation", "par": "agent"},
            tout_projet=tout_projet,
        )
        if self.publier is not None:
            try:
                self.publier(session_id, vue, "panneau_montrer")
            except Exception:  # noqa: BLE001 — prévenir ne doit pas faire échouer l'outil
                log.exception("panneau : prévenir les onglets de %s", session_id)
        return vue


# ── Routes ─────────────────────────────────────────────────────────────


def enregistrer_panneau(
    app: Any,
    router: Any,
    *,
    settings: Any,
    store: Any,
    projects: Any,
    service_apps: Any,
    diffusion: Any,
    require_owner: Callable[..., Any],
) -> Panneau:
    """Crée le panneau, le confie au service des applications, pose ses routes."""
    from fastapi import Body, Depends, HTTPException

    from mcp_gateway.atelier.events import AtelierEvent

    def dossier_projet(slug: str) -> Path | None:
        for p in projects.list_projects(include_archived=True):
            if p.slug == slug:
                return Path(p.path)
        return None

    def publier(session_id: str, vue: dict[str, Any], cause: str) -> None:
        diffusion.publier(
            session_id,
            AtelierEvent(
                kind="systeme", session_id=session_id, cause=cause, text=json.dumps(vue, ensure_ascii=False)
            ),
        )

    panneau = Panneau(
        dossier=Path(settings.work_dir) / "panneau",
        store=store,
        dossier_projet=dossier_projet,
        publier=publier,
    )
    # Les outils `atelier_montrer` et `atelier_navigateur_ouvrir` le trouvent là.
    service_apps.panneau = panneau
    app.state.panneau = panneau

    def _erreur(exc: Exception) -> HTTPException:
        if isinstance(exc, KeyError):
            return HTTPException(404, "conversation inconnue")
        return HTTPException(400, str(exc))

    @router.get("/panneau/{session_id}")
    def panneau_vues(session_id: str, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        try:
            vues = panneau.vues(session_id)
        except (KeyError, VueInvalide) as exc:
            raise _erreur(exc) from None
        return {"vues": vues, "hote": service_apps.origine or None}

    @router.put("/panneau/{session_id}/vues")
    def panneau_enregistrer(
        session_id: str, vue: dict[str, Any] = Body(...), _owner: str = Depends(require_owner)
    ) -> dict[str, Any]:
        from mcp_gateway.atelier.commandes.profils import est_de_l_assistant

        # Dans une conversation de l'Assistant, la personne choisit dans les
        # créations de tous les projets ; ailleurs, dans celles de son projet.
        rec = store.get(session_id)
        tout_projet = rec is not None and est_de_l_assistant(store, rec)
        try:
            return panneau.enregistrer(session_id, vue, tout_projet=tout_projet)
        except (KeyError, VueInvalide) as exc:
            raise _erreur(exc) from None

    @router.delete("/panneau/{session_id}/vues/{vue_id}")
    def panneau_retirer(session_id: str, vue_id: str, _owner: str = Depends(require_owner)) -> dict[str, Any]:
        try:
            return {"retiree": panneau.retirer(session_id, vue_id)}
        except (KeyError, VueInvalide) as exc:
            raise _erreur(exc) from None

    @router.get("/sessions/{session_id}/fils")
    async def fils_wikichat(
        session_id: str, statut: str = "ouvert", _owner: str = Depends(require_owner)
    ) -> dict[str, Any]:
        rec = store.get(session_id)
        if rec is None:
            raise HTTPException(404, "conversation inconnue")
        candidats = [c for c in dict.fromkeys([rec.claude_session_id, rec.session_id]) if c]
        return await lire_fils(settings, candidats, statut)

    return panneau


async def lire_fils(settings: Any, sessions: list[str], statut: str = "ouvert") -> dict[str, Any]:
    """Les fils wikichat d'une conversation (contrat : hooks-et-dialogue.md §8).

    wikichat connaît une conversation par l'identifiant de Claude ; on essaie
    celui-là, puis celui de l'Atelier. Injoignable, il ne casse rien : la liste
    est vide et le dit.
    """
    import httpx

    from mcp_gateway.atelier.wikichat_pilote_proxy import wikichat_http_origin

    statut = statut if statut in ("ouvert", "clos", "tous") else "ouvert"
    base = wikichat_http_origin(settings)
    try:
        async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
            for sid in sessions:
                r = await client.get(f"{base}/api/fils", params={"session": sid, "statut": statut})
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                donnees = r.json()
                fils = donnees.get("fils") if isinstance(donnees, dict) else None
                return {"agent": donnees.get("agent"), "fils": fils if isinstance(fils, list) else []}
    except (httpx.HTTPError, ValueError) as exc:
        log.info("fils wikichat injoignables : %s", exc)
        return {"agent": None, "fils": [], "indisponible": True}
    return {"agent": None, "fils": [], "inconnue": True}


__all__ = ["Panneau", "VueInvalide", "descripteur", "enregistrer_panneau", "lire_fils"]
