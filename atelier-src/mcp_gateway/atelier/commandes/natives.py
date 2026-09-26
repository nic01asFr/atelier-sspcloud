"""Les commandes écrites dans le catalogue : projets, conversations, « À valider », annuler.

Chacune applique ses règles elle-même : ce n'est pas au modèle de se souvenir
qu'un projet a un `ETAT.md` ou qu'une proposition ne s'accepte pas seule.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from mcp_gateway.atelier import git_repos
from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.a_valider import (
    ACCEPTEE,
    EN_ATTENTE,
    PREFIXE_PILOTE,
    REFUSEE,
    ErreurAValider,
    FileAValider,
    decomposer_id_pilote,
    propositions_du_pilote,
)
from mcp_gateway.atelier.commandes.catalogue import FAIT, Catalogue
from mcp_gateway.atelier.commandes.journal import maintenant
from mcp_gateway.atelier.commandes.modele import (
    ENGAGEANTE,
    LECTURE,
    RESERVEE,
    REVERSIBLE,
    Commande,
    Contexte,
    Effet,
    Refus,
)

log = logging.getLogger("atelier.commandes")

PiloteLire = Callable[[], Awaitable[Any]]
PiloteDecider = Callable[[str, str, str, "dict[str, Any] | None"], Awaitable[Any]]


@dataclass
class Services:
    settings: Any
    projects: Any
    sessions: Any
    file: FileAValider
    # Absents quand wikichat ne tourne pas (harnais factice) : la file ne
    # montre alors que ses propres propositions.
    pilote_lire: PiloteLire | None = None
    pilote_decider: PiloteDecider | None = None


def _texte(args: dict[str, Any], cle: str, *, requis: bool = False, maximum: int = 500) -> str | None:
    valeur = args.get(cle)
    if valeur is None:
        if requis:
            raise Refus(f"{cle} requis")
        return None
    if not isinstance(valeur, str):
        raise Refus(f"{cle} doit être un texte")
    valeur = valeur.strip()
    if requis and not valeur:
        raise Refus(f"{cle} requis")
    if len(valeur) > maximum:
        raise Refus(f"{cle} : {maximum} caractères au plus")
    return valeur


def _liste_de_noms(args: dict[str, Any], cle: str) -> list[str] | None:
    valeur = args.get(cle)
    if valeur is None:
        return None
    if not isinstance(valeur, list) or not all(isinstance(v, str) and v.strip() for v in valeur):
        raise Refus(f"{cle} : une liste de noms")
    return [v.strip() for v in valeur]


def _lien_projet(slug: str) -> str:
    return f"/?slug={slug}"


def inscrire_les_natives(catalogue: Catalogue, s: Services) -> None:
    settings = s.settings

    def racine(slug: str) -> Path:
        return settings.projects_dir / slug

    def projet_existant(args: dict[str, Any]) -> str:
        slug = _texte(args, "projet", requis=True, maximum=60) or ""
        if slug == settings.assistant_slug:
            raise Refus("le dossier de l'Assistant n'est pas un projet qu'on modifie par commande")
        if not racine(slug).is_dir():
            raise Refus(f"projet inconnu : {slug}")
        return slug

    def pool() -> dict[str, Any]:
        from mcp_gateway.atelier.mcp_sync import _pool_enabled

        return _pool_enabled(settings)

    def connecteurs_valides(noms: list[str]) -> list[str]:
        try:
            connus = set(pool())
        except Exception as exc:  # noqa: BLE001
            raise Refus(f"catalogue des connecteurs illisible : {exc}") from None
        inconnus = [n for n in noms if n not in connus and n != "atelier"]
        if inconnus:
            raise Refus(
                f"connecteurs absents du catalogue : {', '.join(inconnus)}. "
                f"Disponibles : {', '.join(sorted(connus)) or 'aucun'}"
            )
        return [n for n in noms if n != "atelier"]

    def connecteurs_du_projet(chemin: Path) -> list[str]:
        try:
            brut = json.loads((chemin / ".mcp.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        serveurs = brut.get("mcpServers") if isinstance(brut, dict) else None
        return sorted(n for n in (serveurs or {}) if n != "atelier")

    def lier(chemin: Path, connecteurs: list[str] | None) -> dict[str, Any]:
        from mcp_gateway.atelier import mcp_sync

        try:
            if connecteurs is None:
                noms = mcp_sync.lier_le_projet(settings, chemin)
            else:
                mcp_sync.write_project_binding(settings, chemin, connecteurs)
                noms = connecteurs_du_projet(chemin) + ["atelier"]
        except Exception as exc:  # noqa: BLE001 — le projet existe, la liaison se refera au tour suivant
            log.warning("liaison de %s : %s", chemin.name, exc)
            return {"erreur": f"{type(exc).__name__}: {exc}"}
        return {"connecteurs": sorted(noms)}

    # ── Projets ─────────────────────────────────────────────────────────

    def projet_creer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        titre = _texte(args, "titre", requis=True, maximum=120) or ""
        objectif = _texte(args, "objectif", maximum=500) or ""
        gabarit = _texte(args, "gabarit", maximum=40) or "vide"
        if gabarit not in structure.GABARITS:
            raise Refus(f"gabarit inconnu : {gabarit} ({', '.join(structure.GABARITS)})")
        connecteurs = _liste_de_noms(args, "connecteurs")
        if connecteurs is not None:
            connecteurs = connecteurs_valides(connecteurs)
        voulu = _texte(args, "slug", maximum=40)
        if voulu:
            slug = voulu
            if structure.slugifier(slug) != slug:
                raise Refus("slug : minuscules, chiffres et tirets")
            if racine(slug).exists():
                raise Refus(f"slug déjà pris : {slug}")
        else:
            base = structure.slugifier(titre) or "projet"
            slug, n = base, 2
            while racine(slug).exists() or slug == settings.assistant_slug:
                suffixe = f"-{n}"
                slug = base[: 40 - len(suffixe)] + suffixe
                n += 1
        if slug == settings.assistant_slug:
            raise Refus("ce slug est celui de l'Assistant")

        declaration = structure.ProjetJson(
            slug=slug,
            titre=titre,
            description=objectif,
            gabarit=structure.GabaritDuProjet(nom=gabarit),  # type: ignore[arg-type]
            creation=structure.Creation(par=ctx.acteur, le=maintenant()),
        )
        chemin = racine(slug)
        ecrits = structure.poser_le_gabarit(chemin, declaration, objectif)
        try:
            git_repos.initialiser(
                settings,
                chemin,
                message=(
                    "Ouvrir le projet"
                    + chr(10) * 2
                    + "Atelier-Commande: atelier_projet_creer"
                    + chr(10)
                    + f"Par: {ctx.acteur}"
                ),
            )
        except (git_repos.ErreurDepot, OSError, subprocess.SubprocessError) as exc:
            raise Refus(f"dépôt non créé : {exc}") from None
        s.projects.create(slug, kind="code", title=titre)
        liaison = lier(chemin, connecteurs)
        commit = git_repos.dernier_commit(chemin)
        return Effet(
            charge={"projet": slug, "titre": titre, "dossier": str(chemin), "gabarit": gabarit},
            objet_id=slug,
            titre="Projet créé",
            resume=f"« {titre} » ({slug}), structure type « {gabarit} »",
            voir=_lien_projet(slug),
            preuve={
                "commit": commit,
                "fichiers": ecrits,
                "structure": structure.verifier_la_structure(chemin),
                **liaison,
            },
            avant=None,
            apres={"projet": slug, "titre": titre},
            inverse_arguments={"projet": slug},
        )

    catalogue.ajouter(
        Commande(
            nom="atelier_projet_creer",
            description=(
                "Crée un projet cadré : dossier, dépôt git sur main avec son commit d'ouverture, "
                ".atelier/projet.json, ETAT.md (À décider, Demandé à l'Atelier), CLAUDE.md qui "
                "importe le contexte, docs/decisions/, .gitignore, .mcp.json en références. "
                "Rend une carte avec Annuler (range le projet, ne le supprime pas)."
            ),
            objet="projet",
            classe=REVERSIBLE,
            inverse="atelier_projet_ranger",
            regles=[
                "slug unique, dérivé du titre",
                "dépôt git sur main avec un commit d'ouverture",
                "projet.json valide au schéma strict",
                "ETAT.md avec « À décider » et « Demandé à l'Atelier »",
                "CLAUDE.md sans état ni adresse, qui importe @.atelier/contexte.md",
                ".mcp.json en références seulement",
                "trace de qui l'a créé (projet.json.creation)",
            ],
            executer=projet_creer,
            schema={
                "type": "object",
                "properties": {
                    "titre": {"type": "string", "description": "Le nom affiché."},
                    "objectif": {"type": "string", "description": "Une phrase : à quoi sert le projet."},
                    "gabarit": {"type": "string", "enum": list(structure.GABARITS)},
                    "connecteurs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Connecteurs du catalogue. Absent : le projet suit le pool.",
                    },
                    "slug": {"type": "string", "description": "Facultatif ; dérivé du titre sinon."},
                },
                "required": ["titre"],
            },
        )
    )

    def projet_modifier(ctx: Contexte, args: dict[str, Any]) -> Effet:
        slug = projet_existant(args)
        titre = _texte(args, "titre", maximum=120)
        description = _texte(args, "description", maximum=500)
        if description is None:
            description = _texte(args, "objectif", maximum=500)
        connecteurs = _liste_de_noms(args, "connecteurs")
        if titre is None and description is None and connecteurs is None:
            raise Refus("rien à modifier : titre, description ou connecteurs")
        if titre is not None and not titre:
            raise Refus("titre vide")
        chemin = racine(slug)
        try:
            declaration = structure.lire(chemin)
        except structure.ErreurProjetJson as exc:
            raise Refus(f"{exc} : corrigez-le avant de le modifier par commande") from None
        if declaration is None:
            # Un projet d'avant la structure : sa fiche naît ici, avec le titre
            # qu'il affichait déjà.
            actuel = next((p.title for p in s.projects.list_projects(include_archived=True) if p.slug == slug), slug)
            declaration = structure.ProjetJson(slug=slug, titre=actuel or slug)
        avant: dict[str, Any] = {}
        apres: dict[str, Any] = {}
        donnees = declaration.en_json()
        if titre is not None and titre != declaration.titre:
            avant["titre"], apres["titre"] = declaration.titre, titre
            donnees["titre"] = titre
        if description is not None and description != declaration.description:
            avant["description"], apres["description"] = declaration.description, description
            donnees["description"] = description
        liaison: dict[str, Any] = {}
        if connecteurs is not None:
            connecteurs = connecteurs_valides(connecteurs)
            anciens = connecteurs_du_projet(chemin)
            if sorted(connecteurs) != anciens:
                avant["connecteurs"], apres["connecteurs"] = anciens, sorted(connecteurs)
                liaison = lier(chemin, connecteurs)
                if "erreur" in liaison:
                    raise Refus(f"connecteurs non écrits : {liaison['erreur']}")
        commit = ""
        if "titre" in apres or "description" in apres:
            try:
                nouvelle = structure.valider(donnees)
            except structure.ErreurProjetJson as exc:
                raise Refus(str(exc)) from None
            structure.ecrire(chemin, nouvelle)
            try:
                commit = git_repos.enregistrer_fichiers(
                    settings, chemin, [structure.CHEMIN.as_posix()], "Modifier la fiche du projet"
                )
            except (git_repos.ErreurDepot, OSError, subprocess.SubprocessError) as exc:
                log.warning("fiche de %s non commitée : %s", slug, exc)
            if "titre" in apres:
                s.projects.patch(slug, title=apres["titre"])
        return Effet(
            charge={"projet": slug, "modifie": sorted(apres), "avant": avant, "apres": apres},
            objet_id=slug,
            titre="Projet modifié" if apres else "Projet inchangé",
            resume=", ".join(sorted(apres)) or "déjà ainsi",
            voir=_lien_projet(slug),
            preuve={"commit": commit, **liaison},
            avant=avant,
            apres=apres,
            inverse_arguments=({"projet": slug, **avant} if avant else None),
        )

    catalogue.ajouter(
        Commande(
            nom="atelier_projet_modifier",
            description=(
                "Change le titre, la description ou les connecteurs d'un projet. Ne touche que "
                ".atelier/projet.json (commité seul) et .mcp.json. Annuler remet les valeurs d'avant."
            ),
            objet="projet",
            classe=REVERSIBLE,
            inverse="atelier_projet_modifier",
            regles=[
                "ne touche que projet.json et .mcp.json",
                "projet.json reste valide au schéma strict",
                "le commit ne contient que projet.json",
            ],
            executer=projet_modifier,
            schema={
                "type": "object",
                "properties": {
                    "projet": {"type": "string", "description": "Slug du projet."},
                    "titre": {"type": "string"},
                    "description": {"type": "string"},
                    "connecteurs": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["projet"],
            },
        )
    )

    def bascule_projet(range: bool) -> Callable[[Contexte, dict[str, Any]], Effet]:
        def executer(ctx: Contexte, args: dict[str, Any]) -> Effet:
            slug = projet_existant(args)
            s.projects.patch(slug, archived=range)
            return Effet(
                charge={"projet": slug, "range": range},
                objet_id=slug,
                titre="Projet rangé" if range else "Projet ressorti",
                resume="rien n'est supprimé : le dossier et son dépôt restent" if range else "de nouveau affiché",
                voir=_lien_projet(slug),
                preuve={"range": range},
                avant={"range": not range},
                apres={"range": range},
                inverse_arguments={"projet": slug},
            )

        return executer

    schema_projet = {
        "type": "object",
        "properties": {"projet": {"type": "string", "description": "Slug du projet."}},
        "required": ["projet"],
    }
    catalogue.ajouter(
        Commande(
            nom="atelier_projet_ranger",
            description="Range un projet : il ne s'affiche plus par défaut. Rien n'est supprimé.",
            objet="projet",
            classe=REVERSIBLE,
            inverse="atelier_projet_ressortir",
            regles=["archive, ne supprime jamais"],
            executer=bascule_projet(True),
            schema=schema_projet,
        )
    )
    catalogue.ajouter(
        Commande(
            nom="atelier_projet_ressortir",
            description="Ressort un projet rangé.",
            objet="projet",
            classe=REVERSIBLE,
            inverse="atelier_projet_ranger",
            executer=bascule_projet(False),
            schema=schema_projet,
        )
    )

    def projet_publier(ctx: Contexte, args: dict[str, Any]) -> Effet:
        slug = projet_existant(args)
        prive = args.get("prive", True)
        if not isinstance(prive, bool):
            raise Refus("prive : vrai ou faux")
        try:
            etat = git_repos.publier(settings, racine(slug), slug, prive=prive)
        except git_repos.ErreurDepot as exc:
            raise Refus(str(exc)) from None
        return Effet(
            charge={"projet": slug, "depot": etat.to_dict()},
            objet_id=slug,
            titre="Projet publié",
            resume=etat.distant,
            voir=etat.distant,
            preuve={"distant": etat.distant, "branche": etat.branche},
        )

    catalogue.ajouter(
        Commande(
            nom="atelier_projet_publier",
            description="Publie le dépôt d'un projet sur GitHub (privé par défaut).",
            objet="projet",
            classe=RESERVEE,
            regles=["refusé si un fichier sensible est dans l'histoire", "privé par défaut"],
            executer=projet_publier,
            schema={
                "type": "object",
                "properties": {"projet": {"type": "string"}, "prive": {"type": "boolean"}},
                "required": ["projet"],
            },
            exposee_mcp=False,
        )
    )

    # ── Conversations ───────────────────────────────────────────────────

    def bascule_conversation(range: bool) -> Callable[[Contexte, dict[str, Any]], Effet]:
        def executer(ctx: Contexte, args: dict[str, Any]) -> Effet:
            ident = _texte(args, "conversation", requis=True, maximum=200) or ""
            try:
                rec = s.sessions.patch(ident, archived=range)
            except KeyError:
                raise Refus(f"conversation inconnue : {ident}") from None
            return Effet(
                charge={"conversation": ident, "etat": rec.state},
                objet_id=ident,
                titre="Conversation rangée" if range else "Conversation ressortie",
                resume=rec.title or ident,
                voir=f"/?slug={rec.slug}&session={ident}",
                preuve={"etat": rec.state},
                apres={"etat": rec.state},
                inverse_arguments={"conversation": ident},
            )

        return executer

    schema_conv = {
        "type": "object",
        "properties": {"conversation": {"type": "string"}},
        "required": ["conversation"],
    }
    catalogue.ajouter(
        Commande(
            nom="atelier_conversation_ranger",
            description="Range une conversation : elle ne s'affiche plus par défaut. Rien n'est effacé.",
            objet="conversation",
            classe=REVERSIBLE,
            inverse="atelier_conversation_ressortir",
            regles=["archive, n'efface jamais le fil"],
            executer=bascule_conversation(True),
            schema=schema_conv,
        )
    )
    catalogue.ajouter(
        Commande(
            nom="atelier_conversation_ressortir",
            description="Ressort une conversation rangée.",
            objet="conversation",
            classe=REVERSIBLE,
            inverse="atelier_conversation_ranger",
            executer=bascule_conversation(False),
            schema=schema_conv,
        )
    )

    # ── « À valider » ───────────────────────────────────────────────────

    async def a_valider(ctx: Contexte, args: dict[str, Any]) -> Effet:
        statut = _texte(args, "statut", maximum=20) or EN_ATTENTE
        if statut not in (EN_ATTENTE, ACCEPTEE, REFUSEE, "tout"):
            raise Refus("statut : en_attente, acceptee, refusee ou tout")
        projet = _texte(args, "projet", maximum=60) or ""
        source = _texte(args, "source", maximum=20) or ""
        locales = [
            p.to_dict()
            for p in s.file.lister(statut="" if statut == "tout" else statut, projet=projet, source=source)
        ]
        pilote: list[dict[str, Any]] = []
        note = ""
        if statut in (EN_ATTENTE, "tout") and not projet and source in ("", "pilote") and s.pilote_lire:
            try:
                pilote = propositions_du_pilote(await s.pilote_lire())
            except Exception as exc:  # noqa: BLE001 — wikichat absent : la file reste lisible
                note = f"propositions du pilote wikichat indisponibles : {type(exc).__name__}"
        if source == "pilote":
            locales = []
        charge: dict[str, Any] = {"propositions": locales + pilote, "nombre": len(locales) + len(pilote)}
        if note:
            charge["note"] = note
        return Effet(charge=charge)

    catalogue.ajouter(
        Commande(
            nom="atelier_a_valider",
            description=(
                "La file « À valider » : propositions des gardiens, des agents, des créations, "
                "mémoire proposée, et actions proposées par les agents du pilote wikichat."
            ),
            objet="validation",
            classe=LECTURE,
            executer=a_valider,
            schema={
                "type": "object",
                "properties": {
                    "statut": {"type": "string", "enum": [EN_ATTENTE, ACCEPTEE, REFUSEE, "tout"]},
                    "projet": {"type": "string"},
                    "source": {"type": "string"},
                },
            },
        )
    )

    async def accepter(ctx: Contexte, args: dict[str, Any]) -> Effet:
        ident = _texte(args, "id", requis=True, maximum=300) or ""
        motif = _texte(args, "motif", maximum=500) or ""
        if ident.startswith(PREFIXE_PILOTE):
            if s.pilote_decider is None:
                raise Refus("le pilote wikichat n'est pas joignable ici")
            agent, action = decomposer_id_pilote(ident)
            complete = args.get("complete")
            if complete is not None and not isinstance(complete, dict):
                raise Refus("complete : un objet {chemin: valeur}")
            retour = await s.pilote_decider(agent, action, "approve", complete)
            return Effet(
                charge={"id": ident, "statut": ACCEPTEE, "pilote": retour},
                objet_id=ident,
                titre="Proposition acceptée",
                resume="l'agent l'appliquera à son prochain passage",
                preuve={"pilote": retour},
                apres={"statut": ACCEPTEE},
            )
        p = s.file.lire(ident)
        if p is None:
            raise Refus(f"proposition inconnue : {ident}")
        if p.statut != EN_ATTENTE:
            raise Refus(f"déjà tranchée : {p.statut}")
        resultat: Any = None
        if p.action:
            reponse = await catalogue.executer(
                str(p.action.get("commande")), dict(p.action.get("arguments") or {}), ctx
            )
            if reponse.statut != FAIT:
                raise Refus(f"l'action proposée n'a pas abouti ({reponse.statut}) : {reponse.charge}")
            resultat = {"action": reponse.action, "carte": (reponse.charge or {}).get("carte")}
        try:
            p = s.file.trancher(ident, ACCEPTEE, par=ctx.acteur, motif=motif, resultat=resultat)
        except ErreurAValider as exc:
            raise Refus(str(exc)) from None
        return Effet(
            charge={"id": ident, "statut": p.statut, "resultat": resultat},
            objet_id=ident,
            titre="Proposition acceptée",
            resume=p.titre,
            preuve={"action_executee": resultat},
            avant={"statut": EN_ATTENTE},
            apres={"statut": ACCEPTEE},
        )

    schema_decision = {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Identifiant de la proposition."},
            "motif": {"type": "string"},
        },
        "required": ["id"],
    }
    catalogue.ajouter(
        Commande(
            nom="atelier_a_valider_accepter",
            description=(
                "Accepte une proposition et exécute l'action qu'elle porte. Réservée à la "
                "personne : un modèle n'accepte jamais seul (A-5)."
            ),
            objet="validation",
            classe=RESERVEE,
            regles=[
                "jamais par un modèle",
                "l'action proposée passe par le catalogue, avec son propre journal et son annulation",
                "une proposition du pilote wikichat est approuvée chez le pilote",
            ],
            executer=accepter,
            schema={
                **schema_decision,
                "properties": {
                    **schema_decision["properties"],
                    "complete": {"type": "object", "description": "Pilote : valeurs saisies pour needs."},
                },
            },
            exposee_mcp=False,
        )
    )

    async def refuser(ctx: Contexte, args: dict[str, Any]) -> Effet:
        ident = _texte(args, "id", requis=True, maximum=300) or ""
        motif = _texte(args, "motif", maximum=500) or ""
        if ident.startswith(PREFIXE_PILOTE):
            if s.pilote_decider is None:
                raise Refus("le pilote wikichat n'est pas joignable ici")
            agent, action = decomposer_id_pilote(ident)
            retour = await s.pilote_decider(agent, action, "reject", None)
            return Effet(
                charge={"id": ident, "statut": REFUSEE, "pilote": retour},
                objet_id=ident,
                titre="Proposition refusée",
                resume=motif,
                preuve={"pilote": retour},
                apres={"statut": REFUSEE},
            )
        try:
            p = s.file.trancher(ident, REFUSEE, par=ctx.acteur, motif=motif)
        except ErreurAValider as exc:
            raise Refus(str(exc)) from None
        return Effet(
            charge={"id": ident, "statut": p.statut},
            objet_id=ident,
            titre="Proposition refusée",
            resume=f"{p.titre}" + (f" — {motif}" if motif else ""),
            preuve={"statut": p.statut},
            avant={"statut": EN_ATTENTE},
            apres={"statut": REFUSEE},
            inverse_arguments={"id": ident},
        )

    catalogue.ajouter(
        Commande(
            nom="atelier_a_valider_refuser",
            description="Refuse une proposition de la file « À valider », avec un motif.",
            objet="validation",
            classe=REVERSIBLE,
            inverse="atelier_a_valider_rouvrir",
            regles=["rien n'est exécuté", "se rouvre (sauf une proposition du pilote)"],
            executer=refuser,
            schema=schema_decision,
        )
    )

    def rouvrir(ctx: Contexte, args: dict[str, Any]) -> Effet:
        ident = _texte(args, "id", requis=True, maximum=300) or ""
        try:
            p = s.file.rouvrir(ident, par=ctx.acteur)
        except ErreurAValider as exc:
            raise Refus(str(exc)) from None
        return Effet(
            charge={"id": ident, "statut": p.statut},
            objet_id=ident,
            titre="Proposition rouverte",
            resume=p.titre,
            avant={"statut": REFUSEE},
            apres={"statut": EN_ATTENTE},
            inverse_arguments={"id": ident},
        )

    catalogue.ajouter(
        Commande(
            nom="atelier_a_valider_rouvrir",
            description="Remet en attente une proposition refusée.",
            objet="validation",
            classe=REVERSIBLE,
            inverse="atelier_a_valider_refuser",
            executer=rouvrir,
            schema={"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]},
        )
    )

    # ── Journal et annulation ───────────────────────────────────────────

    def journal(ctx: Contexte, args: dict[str, Any]) -> Effet:
        limite = args.get("limite", 50)
        if not isinstance(limite, int) or isinstance(limite, bool):
            raise Refus("limite : un entier")
        evenements = catalogue.journal.lire(
            depuis=_texte(args, "depuis", maximum=40) or "",
            source=_texte(args, "source", maximum=20) or "",
            acteur=_texte(args, "acteur", maximum=250) or "",
            objet_type=_texte(args, "objet_type", maximum=40) or "",
            objet_id=_texte(args, "objet", maximum=250) or "",
            commande=_texte(args, "commande", maximum=80) or "",
            limite=max(1, min(limite, 200)),
        )
        return Effet(charge={"evenements": evenements, "nombre": len(evenements)})

    catalogue.ajouter(
        Commande(
            nom="atelier_journal",
            description=(
                "Le journal de l'Atelier, le plus récent d'abord : qui a fait quoi, avec quel "
                "résultat. Filtres : depuis (ISO), source, acteur, objet_type, objet, commande."
            ),
            objet="journal",
            classe=LECTURE,
            executer=journal,
            schema={
                "type": "object",
                "properties": {
                    "depuis": {"type": "string"},
                    "source": {"type": "string"},
                    "acteur": {"type": "string"},
                    "objet_type": {"type": "string"},
                    "objet": {"type": "string"},
                    "commande": {"type": "string"},
                    "limite": {"type": "integer", "description": "Défaut 50, au plus 200."},
                },
            },
        )
    )

    async def annuler(ctx: Contexte, args: dict[str, Any]) -> Effet:
        ident = _texte(args, "action", requis=True, maximum=60) or ""
        evenement = catalogue.journal.trouver(ident)
        if evenement is None or evenement.get("source") != "commande":
            raise Refus(f"action inconnue : {ident}")
        if evenement.get("resultat") != FAIT:
            raise Refus("cette action n'a rien fait : rien à annuler")
        inverse = (evenement.get("action") or {}).get("inverse")
        if not isinstance(inverse, dict) or not inverse.get("commande"):
            raise Refus("cette action ne s'annule pas (aucune inverse)")
        deja = catalogue.journal.lire(commande="atelier_annuler", limite=1000)
        if any(
            e.get("resultat") == FAIT and ((e.get("action") or {}).get("arguments") or {}).get("action") == ident
            for e in deja
        ):
            raise Refus("déjà annulée")
        arguments = dict(inverse.get("arguments") or {})
        commande_inverse = catalogue.commande(str(inverse["commande"]))
        ctx_inverse = ctx
        consentement = False
        if (
            commande_inverse is not None
            and commande_inverse.classe_pour(arguments) == ENGAGEANTE
            and (ctx.est_la_personne or ctx.acteur == evenement.get("acteur"))
        ):
            # Défaire son propre geste : le « Oui » donné à l'action (ou la
            # personne elle-même) vaut pour son inverse. Même acteur, et le
            # journal de l'inverse dit par où elle est passée. Une inverse
            # réservée reste refusée à un modèle : la classe est revérifiée.
            ctx_inverse = Contexte(
                acteur=ctx.acteur, origine=ctx.origine, via=f"atelier_annuler:{ident}", confirme=True
            )
            consentement = True
        reponse = await catalogue.executer(str(inverse["commande"]), arguments, ctx_inverse)
        if reponse.statut != FAIT:
            raise Refus(f"l'inverse n'a pas abouti ({reponse.statut}) : {reponse.charge}")
        return Effet(
            charge={"annule": ident, "par": inverse["commande"], "resultat": reponse.charge},
            objet_id=ident,
            titre="Action annulée",
            resume=f"{(evenement.get('action') or {}).get('commande')} défait par {inverse['commande']}",
            preuve={"action_inverse": reponse.action, "consentement_de_l_action": consentement},
        )

    catalogue.ajouter(
        Commande(
            nom="atelier_annuler",
            description=(
                "Annule une action faite par une commande : applique son inverse. `action` est "
                "l'identifiant rendu dans la carte (carte.action)."
            ),
            objet="action",
            classe=REVERSIBLE,
            regles=[
                "l'inverse passe par le catalogue, avec sa propre classe et son journal",
                "une inverse engageante s'applique sans nouvel accord quand son auteur (ou la personne) "
                "annule : via atelier_annuler:<action> au journal",
                "une inverse réservée reste refusée à un modèle",
                "une action ne s'annule qu'une fois",
            ],
            executer=annuler,
            schema={"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]},
        )
    )


__all__ = ["Services", "inscrire_les_natives"]
