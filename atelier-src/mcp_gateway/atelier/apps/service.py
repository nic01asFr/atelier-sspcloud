"""Les artefacts d'un Atelier : ce que voient l'API, les outils et le mandataire.

Un seul objet, pour que les trois portes — les routes `/v1/apps`, les outils
MCP `atelier_artefact*`, le mandataire de l'hôte des applications — disent la
même chose d'un artefact : son mode, son état, son adresse, son auteur.

L'auteur est la conversation qui a créé l'artefact (`artifacts/<nom>/.auteur`).
Ce n'est pas une frontière de sécurité — tous les agents du pod agissent pour
le même propriétaire — mais une règle de voisinage : deux conversations ne
démarrent ni n'arrêtent l'artefact l'une de l'autre sans le dire (`forcer`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp_gateway.atelier.apps.manifeste import (
    FICHIER_AUTEUR,
    FICHIER_MANIFESTE,
    ArtefactInconnu,
    Manifeste,
    ManifesteInvalide,
    charger_manifeste,
    dossier_artefact,
    lire_auteur,
    lister_artefacts,
    nom_valide,
)
from mcp_gateway.atelier.apps.passage import Passage
from mcp_gateway.atelier.apps.superviseur import ErreurApplication, Superviseur
from mcp_gateway.atelier.artifacts import slug_valide
from mcp_gateway.atelier.config import AtelierSettings

# Ce que `creer` pose dans un artefact serveur : un point de départ à
# compléter, qui échoue clairement tant qu'il ne l'est pas.
GABARIT_SERVICE: dict[str, Any] = {
    "version": 1,
    "titre": "",
    "type": "service",
    "commande": ["python3", "app.py", "--port", "{port}"],
    "sante": "/health",
    "protocoles": ["http"],
}


class ApplicationInconnue(LookupError):
    """Projet ou artefact qui n'existe pas (404)."""


class AutreAuteur(PermissionError):
    """L'artefact appartient à une autre conversation (409, sauf `forcer`)."""


class ServiceApps:
    def __init__(
        self,
        settings: AtelierSettings,
        superviseur: Superviseur | None = None,
        passage: Passage | None = None,
    ) -> None:
        self.settings = settings
        self.superviseur = superviseur or Superviseur(settings)
        self.passage = passage or Passage(settings.gateway_db_path)
        self._bureaux: Any = None

    # ── Les services du namespace (voir `bureaux`) ────────────────────

    @property
    def bureaux(self) -> Any:
        """Les vues que les connecteurs du pool déclarent (`atelier.vues`)."""
        if self._bureaux is None:
            from mcp_gateway.atelier.apps.bureaux import Bureaux

            settings = self.settings

            def lire_pool() -> dict[str, Any]:
                from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
                from mcp_gateway.db import connect

                conn = connect(settings.gateway_db_path)
                try:
                    return IntegratedMcpStore(conn).list_servers()
                finally:
                    conn.close()

            def variables() -> dict[str, str]:
                from mcp_gateway.atelier.env_secrets import variables_secretes

                return variables_secretes(settings)

            self._bureaux = Bureaux(lire_pool, settings.secrets_dir / "apps", variables=variables)
        return self._bureaux

    @bureaux.setter
    def bureaux(self, valeur: Any) -> None:
        self._bureaux = valeur

    # ── Le second hôte ────────────────────────────────────────────────

    @property
    def origine(self) -> str:
        """`https://<hôte des applications>`, ou vide sans second hôte."""
        brut = (self.settings.apps_public_url or "").strip().rstrip("/")
        if not brut:
            return ""
        morceaux = urlsplit(brut)
        if not morceaux.scheme or not morceaux.netloc:
            return ""
        return f"{morceaux.scheme}://{morceaux.netloc}".lower()

    @property
    def hote(self) -> str:
        return urlsplit(self.origine).netloc if self.origine else ""

    @property
    def expose(self) -> bool:
        return bool(self.origine)

    def url(self, slug: str, nom: str) -> str:
        """L'adresse de l'artefact : la même en mode autonome et en mode serveur."""
        return f"{self.origine}/{slug}/{nom}/" if self.origine else f"/v1/artifacts/{slug}/{nom}/"

    # ── Projets et manifestes ─────────────────────────────────────────

    def racine_projet(self, slug: str) -> Path:
        if not slug_valide(slug):
            raise ApplicationInconnue(f"projet inconnu : {slug}")
        racine = self.settings.projects_dir / slug
        if racine.is_symlink() or not racine.is_dir():
            raise ApplicationInconnue(f"projet inconnu : {slug}")
        return racine

    def manifeste(self, slug: str, nom: str) -> Manifeste | None:
        """Le manifeste tel qu'il est sur le disque ; None pour un artefact autonome."""
        if not nom_valide(nom):
            raise ApplicationInconnue(f"artefact inconnu : {nom}")
        try:
            return charger_manifeste(self.racine_projet(slug), nom)
        except ArtefactInconnu as exc:
            raise ApplicationInconnue(str(exc)) from None

    def auteur(self, slug: str, nom: str) -> str:
        return lire_auteur(self.racine_projet(slug), nom)

    def fiche(self, slug: str, nom: str, manifeste: Manifeste | None, erreur: str = "") -> dict[str, Any]:
        info = self.superviseur.etat(slug, nom)
        service = manifeste is not None and manifeste.service
        if erreur:
            etat = "invalide"
        elif service:
            etat = info.etat if info else "arrete"
        else:
            etat = "statique"
        fiche: dict[str, Any] = {
            "slug": slug,
            "nom": nom,
            "titre": (manifeste.titre if manifeste else "") or nom,
            "mode": "serveur" if service else ("invalide" if erreur else "autonome"),
            "edition": bool(manifeste and not manifeste.service and manifeste.edition),
            "protocoles": list(manifeste.protocoles) if service else [],
            "etat": etat,
            "raison": (info.raison if info else "") or "",
            "port": info.port if info else None,
            "pid": info.pid if info else None,
            "connexions": info.connexions if info else 0,
            "auteur": lire_auteur(self.racine_projet(slug), nom),
            "url": self.url(slug, nom),
            "ouvrir": f"/v1/apps/{slug}/{nom}/ouvrir" if (self.expose or not service) else "",
        }
        if erreur:
            fiche["erreur"] = erreur
        return fiche

    def lister(self, slug: str) -> list[dict[str, Any]]:
        racine = self.racine_projet(slug)
        valides, erreurs = lister_artefacts(racine)
        fiches = [self.fiche(slug, nom, m) for nom, m in valides.items()]
        fiches += [self.fiche(slug, nom, None, erreur) for nom, erreur in erreurs.items()]
        return sorted(fiches, key=lambda f: f["nom"])

    def lister_tout(self) -> list[dict[str, Any]]:
        fiches: list[dict[str, Any]] = []
        dossier = self.settings.projects_dir
        if not dossier.is_dir():
            return fiches
        for enfant in sorted(dossier.iterdir()):
            if enfant.is_dir() and not enfant.is_symlink() and slug_valide(enfant.name):
                if (enfant / "artifacts").is_dir():
                    fiches += self.lister(enfant.name)
        return fiches

    # ── Auteur ────────────────────────────────────────────────────────

    def verifier_auteur(self, slug: str, nom: str, auteur: str | None, forcer: bool) -> None:
        """Refuse d'agir sur l'artefact d'une autre conversation, sauf `forcer`.

        Un artefact sans `.auteur` (déposé à la main, ou d'avant) est à tous.
        """
        proprietaire = self.auteur(slug, nom)
        if not proprietaire or forcer or (auteur or "") == proprietaire:
            return
        raise AutreAuteur(
            f"l'artefact {slug}/{nom} appartient à la conversation {proprietaire} ; "
            "passez forcer=true pour agir quand même"
        )

    # ── Gestes ────────────────────────────────────────────────────────

    def creer(self, slug: str, nom: str, mode: str, auteur: str | None) -> dict[str, Any]:
        """Crée `artifacts/<nom>/` d'un seul geste, ou refuse s'il existe.

        `mkdir` est atomique : deux conversations qui créent le même nom au
        même instant, une seule réussit. L'autre apprend que le nom est pris,
        au lieu d'écrire par-dessus.
        """
        if mode not in ("autonome", "serveur"):
            raise ValueError("mode : autonome ou serveur")
        if not nom_valide(nom):
            raise ValueError(f"nom d'artefact invalide : {nom!r} (minuscules, chiffres, tirets ; 40 au plus)")
        racine = self.racine_projet(slug)
        (racine / "artifacts").mkdir(exist_ok=True)
        dossier = dossier_artefact(racine, nom)
        try:
            os.mkdir(dossier)
        except FileExistsError:
            raise FileExistsError(f"l'artefact {slug}/{nom} existe déjà ({self.auteur(slug, nom) or 'sans auteur'})") from None
        if auteur:
            (dossier / FICHIER_AUTEUR).write_text(auteur.strip()[:200] + "\n", encoding="utf-8")
        if mode == "serveur":
            gabarit = dict(GABARIT_SERVICE, titre=nom)
            (dossier / FICHIER_MANIFESTE).write_text(
                json.dumps(gabarit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
        return self.fiche(slug, nom, self._manifeste_ou_none(slug, nom))

    def _manifeste_ou_none(self, slug: str, nom: str) -> Manifeste | None:
        try:
            return self.manifeste(slug, nom)
        except ManifesteInvalide:
            return None

    async def demarrer(
        self,
        slug: str,
        nom: str,
        *,
        attendre: bool = True,
        auteur: str | None = None,
        forcer: bool = True,
    ) -> dict[str, Any]:
        manifeste = self.manifeste(slug, nom)
        self.verifier_auteur(slug, nom, auteur, forcer)
        if manifeste is None or not manifeste.service:
            return self.fiche(slug, nom, manifeste)
        await self.superviseur.demarrer(
            slug, nom, self.racine_projet(slug), manifeste, attendre=attendre
        )
        return self.fiche(slug, nom, manifeste)

    async def arreter(
        self, slug: str, nom: str, *, auteur: str | None = None, forcer: bool = True
    ) -> dict[str, Any]:
        manifeste = self.manifeste(slug, nom)
        self.verifier_auteur(slug, nom, auteur, forcer)
        await self.superviseur.arreter(slug, nom)
        return self.fiche(slug, nom, manifeste)

    def journal(self, slug: str, nom: str, lignes: int = 200) -> str:
        self.racine_projet(slug)
        if not nom_valide(nom):
            raise ApplicationInconnue(f"artefact inconnu : {nom}")
        return self.superviseur.journal(slug, nom, lignes)


__all__ = ["ApplicationInconnue", "AutreAuteur", "ErreurApplication", "ServiceApps"]
