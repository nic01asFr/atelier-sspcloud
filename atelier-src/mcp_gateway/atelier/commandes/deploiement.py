"""`atelier_projet_deployer_declarer` : lier un projet à son pod ou à son service.

La commande écrit le bloc `deploiement` de `.atelier/projet.json`
(`structure.Deploiement`), et c'est lui qui décide de ce qu'Onyxia donne aux
agents code du projet (`onyxia_projet`, `docs/onyxia-projet.md`). Elle est
`engageante` : elle ouvre à des agents l'exécution dans un pod, donc elle
passe par un aperçu et l'accord de la personne.

Pour un pod, elle réutilise `project_bind` d'Onyxia, qui attache la session
`proj-<slug>` à ce pod : un pod absent ou arrêté est refusé tout de suite. Si
Onyxia est injoignable, la déclaration est écrite quand même, et la session
sera attachée au premier appel d'un agent.

`inscrire_le_deploiement(app, catalogue)` est la ligne que `commandes`
appelle : elle ajoute la commande et branche les points d'entrée Onyxia de la
passerelle (`/mcp/onyxia`, `/mcp/onyxia/projet/<slug>`).
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from mcp_gateway.atelier import git_repos, onyxia_projet
from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.catalogue import Catalogue
from mcp_gateway.atelier.commandes.modele import ENGAGEANTE, Commande, Contexte, Effet, Refus

log = logging.getLogger("atelier.commandes")

NOM = "atelier_projet_deployer_declarer"
_CHAMPS = ("pod", "service", "namespace", "gpu", "commande", "port")


def inscrire_le_deploiement(app: Any, catalogue: Catalogue) -> None:
    settings = app.state.settings
    mandataire = onyxia_projet.monter(app)

    def racine(slug: str) -> Path:
        return settings.projects_dir / slug

    def projet_existant(args: dict[str, Any]) -> str:
        slug = args.get("projet")
        if not isinstance(slug, str) or not slug.strip():
            raise Refus("projet requis")
        slug = slug.strip()
        if slug == settings.assistant_slug:
            raise Refus("le dossier de l'Assistant n'est pas un projet qui se déploie")
        if structure.slugifier(slug) != slug or not racine(slug).is_dir():
            raise Refus(f"projet inconnu : {slug}")
        return slug

    def fiche(slug: str) -> structure.ProjetJson:
        try:
            declaration = structure.lire(racine(slug))
        except structure.ErreurProjetJson as exc:
            raise Refus(f"{exc} : corrigez-le avant de déclarer un déploiement") from None
        if declaration is not None:
            return declaration
        # Un projet d'avant la structure : sa fiche naît ici, avec son titre.
        projets = getattr(app.state, "projects", None)
        titre = slug
        if projets is not None:
            titre = next(
                (p.title for p in projets.list_projects(include_archived=True) if p.slug == slug), slug
            ) or slug
        return structure.ProjetJson(slug=slug, titre=titre)

    def voulu(args: dict[str, Any]) -> structure.Deploiement | None:
        retirer = args.get("retirer", False)
        if not isinstance(retirer, bool):
            raise Refus("retirer : vrai ou faux")
        champs = {k: args[k] for k in _CHAMPS if args.get(k) is not None}
        if retirer:
            if champs:
                raise Refus("retirer ne se combine pas avec pod, service ou leurs réglages")
            return None
        try:
            return structure.Deploiement(**champs)
        except Exception as exc:  # noqa: BLE001 — la validation dit pourquoi
            raise Refus(f"déploiement invalide : {exc}") from None

    def en_json(deploiement: structure.Deploiement | None) -> dict[str, Any] | None:
        return deploiement.model_dump(mode="json", exclude_none=True) if deploiement else None

    def ce_que_recoivent_les_agents(deploiement: structure.Deploiement | None) -> str:
        if deploiement is None:
            return "les agents code du projet ne reçoivent plus Onyxia"
        cible = f"le pod {deploiement.pod}" if deploiement.pod else f"le service {deploiement.service}"
        gpu = ", et le GPU du projet" if deploiement.gpu else ""
        return f"les agents code du projet reçoivent Onyxia borné à {cible}{gpu}"

    def apercu(ctx: Contexte, args: dict[str, Any]) -> dict[str, Any]:
        slug = projet_existant(args)
        apres = voulu(args)
        return {
            "projet": slug,
            "avant": en_json(fiche(slug).deploiement),
            "apres": en_json(apres),
            "effet": ce_que_recoivent_les_agents(apres),
            "fichier": structure.CHEMIN.as_posix(),
        }

    async def declarer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        slug = projet_existant(args)
        nouveau = voulu(args)
        declaration = fiche(slug)
        avant = en_json(declaration.deploiement)
        apres = en_json(nouveau)

        liaison: dict[str, Any] = {}
        if nouveau is not None and nouveau.pod is not None:
            borne = onyxia_projet.borne_du_projet(slug, nouveau)
            try:
                lien = await mandataire.lier(borne)
                liaison = {"session": borne.session, "pod": lien.get("pod", nouveau.pod)}
            except onyxia_projet.RefusOnyxia as exc:
                raise Refus(str(exc)) from None
            except Exception as exc:  # noqa: BLE001 — Onyxia absent : liée au premier appel
                log.warning("onyxia injoignable pour %s : %s", slug, exc)
                liaison = {"session": borne.session, "a_faire": f"Onyxia injoignable ({type(exc).__name__})"}
        elif nouveau is None:
            mandataire.oublier_la_session(slug)

        commit = ""
        if avant != apres:
            donnees = declaration.en_json()
            if apres is None:
                donnees.pop("deploiement", None)
            else:
                donnees["deploiement"] = apres
            try:
                nouvelle = structure.valider(donnees)
            except structure.ErreurProjetJson as exc:
                raise Refus(str(exc)) from None
            chemin = racine(slug)
            structure.ecrire(chemin, nouvelle)
            try:
                commit = git_repos.enregistrer_fichiers(
                    settings,
                    chemin,
                    [structure.CHEMIN.as_posix()],
                    "Retirer le déploiement du projet" if apres is None else "Déclarer le déploiement du projet",
                )
            except (git_repos.ErreurDepot, OSError, subprocess.SubprocessError) as exc:
                log.warning("fiche de %s non commitée : %s", slug, exc)

        if avant is None:
            inverse: dict[str, Any] | None = {"projet": slug, "retirer": True} if apres is not None else None
        else:
            inverse = {"projet": slug, **avant} if avant != apres else None
        return Effet(
            charge={"projet": slug, "deploiement": apres, "avant": avant, "liaison": liaison},
            objet_id=slug,
            titre="Déploiement déclaré" if apres else "Déploiement retiré",
            resume=ce_que_recoivent_les_agents(nouveau),
            voir=f"/?slug={slug}",
            preuve={"commit": commit, "fichier": structure.CHEMIN.as_posix(), **liaison},
            avant=avant,
            apres=apres,
            inverse_arguments=inverse,
        )

    catalogue.ajouter(
        Commande(
            nom=NOM,
            description=(
                "Lie un projet à son pod Onyxia (ou à son service) : écrit le bloc deploiement de "
                ".atelier/projet.json. Les agents code du projet reçoivent alors Onyxia borné à ce "
                "pod : exécuter, lire, état, son service, son GPU. retirer=true enlève la liaison."
            ),
            objet="projet",
            classe=ENGAGEANTE,
            inverse=NOM,
            regles=[
                "un pod ou un service, exactement",
                "un pod est attaché par project_bind d'Onyxia (session proj-<slug>) ; refusé s'il est absent",
                "ne touche que projet.json, commité seul",
                "expose_public reste réservé à la personne",
            ],
            executer=declarer,
            apercu=apercu,
            schema={
                "type": "object",
                "properties": {
                    "projet": {"type": "string", "description": "Slug du projet."},
                    "pod": {"type": "string", "description": "Pod Onyxia existant (list_pods)."},
                    "service": {"type": "string", "description": "Chemin d'un <nom>.service.yml."},
                    "namespace": {"type": "string", "description": "Facultatif ; défaut : celui d'Onyxia."},
                    "gpu": {"type": "boolean", "description": "Le projet a besoin du GPU."},
                    "commande": {"type": "string", "description": "Commande de démarrage du service."},
                    "port": {"type": "integer", "description": "Port du service dans le pod."},
                    "retirer": {"type": "boolean", "description": "Enlève la liaison."},
                },
                "required": ["projet"],
            },
        )
    )


__all__ = ["NOM", "inscrire_le_deploiement"]
