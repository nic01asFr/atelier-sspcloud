"""La migration d'un projet d'avant vers la structure type (`docs/structure-projet.md`).

`atelier_projet_structurer` (engageante) pose ce qui manque, **sans rien
écraser** :

- `.atelier/projet.json` (titre, description ; slug = nom du dossier) ;
- `ETAT.md`, dans une version « reprise » : il dit que l'état d'avant reste à
  y rassembler, au lieu de prétendre que le projet s'ouvre ;
- `docs/cahier-des-charges.md`, `docs/decisions/NNNN-structure-type.md`,
  `README.md` s'il n'y en a aucun (même écrit `readme.md`) ;
- `.gitignore` : la ligne ancienne qui ignorait `.atelier/` entier devient
  `.atelier/*` plus les exceptions `projet.json` et `env.json` (git ne
  ré-inclut rien sous un dossier exclu), et les lignes de l'Atelier qui
  manquent sont ajoutées ;
- `CLAUDE.md` : gardé, avec l'import `@.atelier/contexte.md` en première
  ligne. La section que l'Atelier y tenait (`<!-- atelier:contexte -->`) en
  sort : elle vit désormais dans `.atelier/contexte.md`, régénéré à chaque
  tour (D7). Un `CLAUDE.md` non suivi par git le devient (D1).

Tout ce qui est touché part dans **un seul commit**, qui ne contient rien
d'autre (le travail en cours n'est pas emporté). L'état d'avant est gardé dans
`.atelier/avant-structure/<id>/` (ignoré par git) : l'inverse,
`atelier_projet_destructurer`, le remet tel quel, et refuse si un fichier
posé a été modifié depuis.

`a_blanc=true` rend le plan sans rien écrire (classe `lecture`) : c'est aussi
ce que montre l'aperçu avant « Oui ».
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

from mcp_gateway.atelier import git_repos
from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.catalogue import Catalogue
from mcp_gateway.atelier.commandes.creations import booleen, texte
from mcp_gateway.atelier.commandes.journal import maintenant
from mcp_gateway.atelier.commandes.modele import (
    ENGAGEANTE,
    LECTURE,
    REVERSIBLE,
    Commande,
    Contexte,
    Effet,
    Refus,
)

log = logging.getLogger("atelier.commandes")

NOM = "atelier_projet_structurer"
INVERSE = "atelier_projet_destructurer"
SAUVEGARDES = PurePosixPath(".atelier/avant-structure")
IMPORT_DU_CONTEXTE = "@.atelier/contexte.md"
DEBUT_CONTEXTE = "<!-- atelier:contexte -->"
FIN_CONTEXTE = "<!-- /atelier:contexte -->"
MESSAGE = "Poser la structure type"
MESSAGE_INVERSE = "Défaire la structure type"
# Une ligne qui ignore `.atelier/` entier : git n'y ré-inclurait rien.
_ANCIENNES_LIGNES_ATELIER = frozenset({".atelier/", ".atelier", "/.atelier/", "/.atelier", ".atelier/**"})
_LIGNES_ATELIER_DU_DOSSIER = (".atelier/*", "!.atelier/projet.json", "!.atelier/env.json")
_DECISION = re.compile(r"^(\d{4})-.*\.md$")
_LIGNES_DE_DIFF = 120


def _empreinte(donnees: bytes) -> str:
    return hashlib.sha256(donnees).hexdigest()


def _existe_sans_casse(racine: Path, relatif: str) -> str | None:
    """Le chemin présent, quelle que soit sa casse (`readme.md` pour `README.md`)."""
    courant = racine
    trouve: list[str] = []
    for partie in PurePosixPath(relatif).parts:
        if not courant.is_dir():
            return None
        candidat = next((e.name for e in courant.iterdir() if e.name.lower() == partie.lower()), None)
        if candidat is None:
            return None
        trouve.append(candidat)
        courant = courant / candidat
    return "/".join(trouve)


def gitignore_migre(texte_actuel: str | None) -> tuple[str, list[str], list[str]]:
    """Le `.gitignore` complété : (contenu, lignes remplacées, lignes ajoutées)."""
    if texte_actuel is None:
        return git_repos.GITIGNORE, [], list(git_repos.LIGNES_DE_L_ATELIER)
    lignes = texte_actuel.splitlines()
    presentes = {l.strip() for l in lignes}
    sortie: list[str] = []
    remplacees: list[str] = []
    for ligne in lignes:
        if ligne.strip() in _ANCIENNES_LIGNES_ATELIER:
            remplacees.append(ligne.strip())
            for nouvelle in _LIGNES_ATELIER_DU_DOSSIER:
                if nouvelle not in presentes:
                    sortie.append(nouvelle)
                    presentes.add(nouvelle)
            continue
        sortie.append(ligne)
    manquantes = [l for l in git_repos.LIGNES_DE_L_ATELIER if l not in presentes]
    contenu = "\n".join(sortie) + ("\n" if sortie else "")
    if manquantes:
        contenu += "# Déposé par l'Atelier, à ne pas versionner.\n" + "\n".join(manquantes) + "\n"
    return contenu, remplacees, manquantes


def claude_md_migre(texte_actuel: str) -> str | None:
    """`CLAUDE.md` avec l'import du contexte en tête, sans la section générée ; None s'il l'a déjà."""
    if texte_actuel.lstrip().startswith(IMPORT_DU_CONTEXTE):
        return None
    corps = texte_actuel
    if DEBUT_CONTEXTE in corps and FIN_CONTEXTE in corps:
        avant, _, reste = corps.partition(DEBUT_CONTEXTE)
        _, _, apres = reste.partition(FIN_CONTEXTE)
        corps = avant.rstrip("\n") + ("\n\n" if avant.strip() else "") + apres.lstrip("\n")
    corps = corps.lstrip("\n")
    return IMPORT_DU_CONTEXTE + "\n\n" + corps if corps else IMPORT_DU_CONTEXTE + "\n"


def _etat_repris(titre: str, jour: str, sources: list[str]) -> str:
    ailleurs = ", ".join(f"`{s}`" for s in sources) or "les fichiers du projet"
    return "\n".join(
        [
            f"# État — {titre}",
            "",
            "Lot courant : reprise dans la structure type.",
            f"Dernière vérification : {jour}, structure posée par l'Atelier sur le projet existant.",
            f"Prochaine étape : rassembler ici l'état tenu jusqu'ici dans {ailleurs}, puis l'y retirer.",
            "",
            f"## {structure.RUBRIQUE_A_DECIDER}",
            "",
            "- rien",
            "",
            f"## {structure.RUBRIQUE_DEMANDE}",
            "",
            "- rien",
            "",
            "## Fait et vérifié",
            "",
            f"- {jour} : structure type posée ; aucun fichier existant n'a été remplacé.",
            "",
            "## Non vérifié",
            "",
            f"- l'état d'avant n'est pas encore repris ici (voir {ailleurs}).",
            "",
            "## Écarts",
            "",
            "- rien",
            "",
        ]
    )


def _decision_reprise(numero: str, jour: str, par: str) -> str:
    return "\n".join(
        [
            "# Suivre la structure type de l'Atelier",
            "",
            "- Statut : acceptée",
            f"- Date : {jour}",
            "",
            "## Contexte",
            "",
            f"Projet existant, repris dans la structure type par {par} (décision {numero}).",
            "Son état était tenu à plusieurs endroits, et sa consigne mêlait règles et journal.",
            "",
            "## Décision",
            "",
            "L'état vit dans `ETAT.md` seul ; la déclaration machine dans `.atelier/projet.json` ;"
            " les décisions ici, une par fichier ; le contexte généré par l'Atelier dans"
            " `.atelier/contexte.md`, importé par `CLAUDE.md`.",
            "",
            "## Conséquences",
            "",
            "Rien d'existant n'a été déplacé ni réécrit. Rassembler l'état et alléger `CLAUDE.md`"
            " (100 lignes au plus, sans état ni adresse) sont les étapes suivantes.",
            "",
        ]
    )


@dataclass
class Operation:
    chemin: str
    action: str  # creer | modifier | garder
    contenu: str | None = None
    avant: str | None = None
    raison: str = ""


@dataclass
class Plan:
    slug: str
    titre: str
    operations: list[Operation] = field(default_factory=list)
    remarques: list[str] = field(default_factory=list)
    depot: bool = False
    suivis: set[str] = field(default_factory=set)

    @property
    def a_ecrire(self) -> list[Operation]:
        return [o for o in self.operations if o.action in ("creer", "modifier")]

    def resume(self) -> dict[str, Any]:
        creer = [
            {"chemin": o.chemin, "lignes": (o.contenu or "").count("\n")} for o in self.operations if o.action == "creer"
        ]
        modifier = []
        for o in self.operations:
            if o.action != "modifier":
                continue
            diff = list(
                difflib.unified_diff(
                    (o.avant or "").splitlines(),
                    (o.contenu or "").splitlines(),
                    fromfile=f"a/{o.chemin}",
                    tofile=f"b/{o.chemin}",
                    lineterm="",
                    n=1,
                )
            )
            if len(diff) > _LIGNES_DE_DIFF:
                diff = diff[:_LIGNES_DE_DIFF] + [f"… ({len(diff) - _LIGNES_DE_DIFF} lignes de plus)"]
            modifier.append({"chemin": o.chemin, "raison": o.raison, "diff": diff})
        suivre = sorted(o.chemin for o in self.a_ecrire if o.chemin not in self.suivis) if self.depot else []
        return {
            "projet": self.slug,
            "titre": self.titre,
            "creer": creer,
            "modifier": modifier,
            "garder": [{"chemin": o.chemin, "raison": o.raison} for o in self.operations if o.action == "garder"],
            "suivre_par_git": suivre,
            "commit": f"« {MESSAGE} », avec ces seuls fichiers" if self.depot and self.a_ecrire else "aucun",
            "remarques": self.remarques,
            "rien_a_faire": not self.a_ecrire,
        }


def _suivis(racine: Path) -> set[str]:
    if not (racine / ".git").is_dir():
        return set()
    try:
        sortie = git_repos._git(racine, "ls-files", "-z", verifier=False)  # noqa: SLF001
    except (OSError, subprocess.SubprocessError):
        return set()
    return {p for p in sortie.split("\0") if p}


def planifier(
    racine: Path, slug: str, *, titre: str, description: str, par: str, jour: str
) -> Plan:
    """Ce que la migration écrirait, sans rien écrire."""
    racine = Path(racine)
    plan = Plan(slug=slug, titre=titre, depot=(racine / ".git").is_dir())
    plan.suivis = _suivis(racine)
    if not plan.depot:
        plan.remarques.append("pas de dépôt git : les fichiers seront posés, rien ne sera commité")

    def lire(relatif: str) -> str | None:
        chemin = racine / relatif
        return chemin.read_bytes().decode("utf-8") if chemin.is_file() else None

    # projet.json
    projet_json = PurePosixPath(*structure.CHEMIN.parts).as_posix()
    try:
        declaree = structure.lire(racine)
    except structure.ErreurProjetJson as exc:
        raise Refus(f"{exc} : corrigez-le avant de migrer") from None
    if declaree is not None:
        plan.operations.append(Operation(projet_json, "garder", raison="déjà là, valide"))
        titre = declaree.titre
        plan.titre = titre
        fiche = declaree
    else:
        fiche = structure.ProjetJson(slug=slug, titre=titre, description=description)
        plan.operations.append(
            Operation(projet_json, "creer", contenu=json.dumps(fiche.en_json(), ensure_ascii=False, indent=2) + "\n")
        )

    # .gitignore
    ancien = lire(".gitignore")
    nouveau, remplacees, ajoutees = gitignore_migre(ancien)
    if ancien is None:
        plan.operations.append(Operation(".gitignore", "creer", contenu=nouveau))
    elif nouveau != ancien:
        raisons = []
        if remplacees:
            raisons.append(f"« {', '.join(remplacees)} » ignorait .atelier/ entier : remplacé par .atelier/* et ses exceptions")
        if ajoutees:
            raisons.append(f"ajoutées : {', '.join(ajoutees)}")
        plan.operations.append(Operation(".gitignore", "modifier", contenu=nouveau, avant=ancien, raison=" ; ".join(raisons)))
    else:
        plan.operations.append(Operation(".gitignore", "garder", raison="déjà complet"))

    # CLAUDE.md
    present = _existe_sans_casse(racine, "CLAUDE.md")
    gabarit = structure.fichiers_du_gabarit(fiche, description)
    if present is None:
        plan.operations.append(Operation("CLAUDE.md", "creer", contenu=gabarit["CLAUDE.md"]))
    else:
        texte_claude = lire(present) or ""
        migre = claude_md_migre(texte_claude)
        if migre is None:
            plan.operations.append(Operation(present, "garder", raison="importe déjà le contexte"))
        else:
            raisons = ["import du contexte en première ligne"]
            if DEBUT_CONTEXTE in texte_claude:
                raisons.append("section générée retirée : elle vit dans .atelier/contexte.md")
            plan.operations.append(Operation(present, "modifier", contenu=migre, avant=texte_claude, raison=" ; ".join(raisons)))
            lignes = migre.count("\n")
            if lignes > 100:
                plan.remarques.append(
                    f"CLAUDE.md garde {lignes} lignes (cible : 100 au plus, sans état ni adresse) : "
                    "à alléger par un agent du projet, pas par la migration"
                )
        if plan.depot and present not in plan.suivis:
            plan.remarques.append(f"{present} n'était pas suivi par git : il le sera (D1)")

    # ETAT.md, README.md, cahier des charges
    sources = [p for p in ("CLAUDE.md", "README.md") if _existe_sans_casse(racine, p)]
    sources = [_existe_sans_casse(racine, p) or p for p in sources]
    for relatif, contenu in (
        (fiche.fichiers.etat, _etat_repris(titre, jour, sources)),
        ("README.md", gabarit["README.md"]),
        (fiche.fichiers.cahier, gabarit["docs/cahier-des-charges.md"]),
    ):
        existant = _existe_sans_casse(racine, relatif)
        if existant is not None:
            plan.operations.append(Operation(existant, "garder", raison="déjà là, jamais écrasé"))
        else:
            plan.operations.append(Operation(relatif, "creer", contenu=contenu))

    # docs/decisions/
    dossier = racine / fiche.fichiers.decisions
    numeros = [int(m.group(1)) for e in (dossier.iterdir() if dossier.is_dir() else []) if (m := _DECISION.match(e.name))]
    deja = [e.name for e in (dossier.iterdir() if dossier.is_dir() else []) if "structure-type" in e.name]
    if deja:
        plan.operations.append(Operation(f"{fiche.fichiers.decisions}/{deja[0]}", "garder", raison="décision déjà prise"))
    else:
        numero = f"{(max(numeros) + 1) if numeros else 1:04d}"
        plan.operations.append(
            Operation(
                f"{fiche.fichiers.decisions}/{numero}-structure-type.md",
                "creer",
                contenu=_decision_reprise(numero, jour, par),
            )
        )

    readme = _existe_sans_casse(racine, "README.md")
    if readme and readme != "README.md":
        plan.remarques.append(f"{readme} tient lieu de README.md : aucun second fichier n'est posé")
    if ancien is not None and remplacees:
        plan.remarques.append(".atelier/projet.json sera suivi par git ; le reste de .atelier/ reste ignoré")
    return plan


def _dossiers_a_creer(racine: Path, chemins: list[str]) -> list[str]:
    dossiers: set[str] = set()
    for c in chemins:
        parent = PurePosixPath(c).parent
        while str(parent) not in ("", "."):
            if not (racine / parent).exists():
                dossiers.add(parent.as_posix())
            parent = parent.parent
    return sorted(dossiers, key=lambda d: d.count("/"), reverse=True)


def appliquer(settings: Any, racine: Path, plan: Plan, *, par: str) -> dict[str, Any]:
    """Écrit le plan, garde l'état d'avant, commite. Rend la preuve."""
    racine = Path(racine)
    ident = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    sauvegarde = racine / SAUVEGARDES / ident
    ecrits = plan.a_ecrire
    manifeste: dict[str, Any] = {
        "id": ident,
        "le": maintenant(),
        "par": par,
        "titre": plan.titre,
        "crees": {},
        "modifies": {},
        "suivis_avant": sorted(o.chemin for o in ecrits if o.chemin in plan.suivis),
        "dossiers_crees": _dossiers_a_creer(racine, [o.chemin for o in ecrits if o.action == "creer"]),
        "commit": "",
    }
    (sauvegarde / "fichiers").mkdir(parents=True, exist_ok=True)
    for n, o in enumerate(ecrits):
        donnees = (o.contenu or "").encode("utf-8")
        chemin = racine / o.chemin
        if o.action == "modifier":
            copie = f"fichiers/{n:02d}"
            (sauvegarde / copie).write_bytes(chemin.read_bytes())
            manifeste["modifies"][o.chemin] = {"copie": copie, "apres": _empreinte(donnees)}
        else:
            if chemin.exists():
                raise Refus(f"{o.chemin} est apparu entre l'aperçu et l'écriture : rien n'est fait")
            manifeste["crees"][o.chemin] = _empreinte(donnees)
    for o in ecrits:
        chemin = racine / o.chemin
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_bytes((o.contenu or "").encode("utf-8"))
    commit = ""
    if plan.depot and ecrits:
        corps = f"{MESSAGE}\n\nAtelier-Commande: {NOM}\nPar: {par}"
        try:
            commit = git_repos.enregistrer_fichiers(settings, racine, [o.chemin for o in ecrits], corps)
        except (git_repos.ErreurDepot, OSError, subprocess.SubprocessError) as exc:
            log.warning("structure de %s non commitée : %s", plan.slug, exc)
            manifeste["commit_erreur"] = str(exc)[:300]
    manifeste["commit"] = commit
    (sauvegarde / "manifeste.json").write_text(json.dumps(manifeste, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"sauvegarde": ident, "commit": commit, "ecrits": [o.chemin for o in ecrits]}


def lire_le_manifeste(racine: Path, ident: str) -> dict[str, Any]:
    if not re.match(r"^[0-9]{8}-[0-9]{6}-[0-9]{6}$", ident or ""):
        raise Refus("sauvegarde : l'identifiant rendu par la migration")
    chemin = Path(racine) / SAUVEGARDES / ident / "manifeste.json"
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refus(f"sauvegarde introuvable : {ident}") from None


def defaire(settings: Any, racine: Path, ident: str) -> dict[str, Any]:
    """Remet le projet tel qu'avant la migration `ident`. Refuse si l'on a touché depuis."""
    racine = Path(racine)
    manifeste = lire_le_manifeste(racine, ident)
    sauvegarde = racine / SAUVEGARDES / ident
    touches: list[str] = []
    for chemin, empreinte in manifeste["crees"].items():
        f = racine / chemin
        if f.is_file() and _empreinte(f.read_bytes()) != empreinte:
            touches.append(chemin)
    for chemin, info in manifeste["modifies"].items():
        f = racine / chemin
        if not f.is_file() or _empreinte(f.read_bytes()) != info["apres"]:
            touches.append(chemin)
    if touches:
        raise Refus(
            f"modifiés depuis la migration : {', '.join(sorted(touches))}. Rien n'est défait ; "
            "remettez-les d'abord, ou défaites à la main."
        )
    depot = (racine / ".git").is_dir()
    if depot and git_repos._git(racine, "diff", "--cached", "--name-only", verifier=False):  # noqa: SLF001
        raise Refus("des changements sont déjà indexés dans le dépôt : commitez-les ou retirez-les d'abord")
    for chemin, info in manifeste["modifies"].items():
        (racine / chemin).write_bytes((sauvegarde / info["copie"]).read_bytes())
    for chemin in manifeste["crees"]:
        (racine / chemin).unlink(missing_ok=True)
    for dossier in manifeste["dossiers_crees"]:
        d = racine / dossier
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    commit = ""
    if depot:
        suivis_avant = set(manifeste["suivis_avant"])
        suivis = _suivis(racine)
        for chemin in [*manifeste["modifies"], *manifeste["crees"]]:
            if chemin in suivis_avant:
                git_repos._git(racine, "add", "--", chemin)  # noqa: SLF001
            elif chemin in suivis:
                git_repos._git(racine, "rm", "--cached", "--quiet", "--", chemin)  # noqa: SLF001
        if git_repos._git(racine, "diff", "--cached", "--name-only", verifier=False):  # noqa: SLF001
            git_repos._identite(settings, racine)  # noqa: SLF001
            git_repos._git(  # noqa: SLF001
                racine, "commit", "-m", f"{MESSAGE_INVERSE}\n\nAtelier-Commande: {INVERSE}", "--no-verify"
            )
            commit = git_repos._git(racine, "rev-parse", "HEAD", verifier=False)  # noqa: SLF001
    shutil.rmtree(sauvegarde, ignore_errors=True)
    return {
        "commit": commit,
        "restaures": sorted(manifeste["modifies"]),
        "retires": sorted(manifeste["crees"]),
        "titre": manifeste.get("titre") or "",
    }


def inscrire_la_migration(app: Any, catalogue: Catalogue) -> None:
    settings = app.state.settings

    def projet_existant(args: dict[str, Any]) -> tuple[str, Path]:
        slug = texte(args, "projet", requis=True, maximum=60) or ""
        if slug == settings.assistant_slug:
            raise Refus("le dossier de l'Assistant n'est pas un dépôt de projet (S6)")
        chemin = settings.projects_dir / slug
        if structure.slugifier(slug) != slug or not chemin.is_dir():
            raise Refus(f"projet inconnu : {slug}")
        return slug, chemin

    def titre_de(slug: str) -> str:
        projets = getattr(app.state, "projects", None)
        if projets is not None:
            try:
                for p in projets.list_projects(include_archived=True):
                    if p.slug == slug and (p.title or "").strip():
                        return p.title.strip()
            except Exception:  # noqa: BLE001 — le titre n'est qu'un défaut
                pass
        return slug

    def le_plan(ctx: Contexte, args: dict[str, Any]) -> tuple[str, Path, Plan]:
        slug, chemin = projet_existant(args)
        titre = texte(args, "titre", maximum=120) or titre_de(slug)
        description = texte(args, "description", maximum=500) or ""
        jour = datetime.now(timezone.utc).date().isoformat()
        return slug, chemin, planifier(chemin, slug, titre=titre, description=description, par=ctx.acteur, jour=jour)

    def apercu(ctx: Contexte, args: dict[str, Any]) -> dict[str, Any]:
        return le_plan(ctx, args)[2].resume()

    def structurer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        a_blanc = booleen(args, "a_blanc")
        slug, chemin, plan = le_plan(ctx, args)
        resume = plan.resume()
        if a_blanc:
            return Effet(charge={"a_blanc": True, **resume})
        if not plan.a_ecrire:
            return Effet(
                charge={"projet": slug, "rien_a_faire": True},
                objet_id=slug,
                titre="Structure déjà en place",
                resume="rien à poser",
                voir=f"/?slug={slug}",
                preuve={"structure": structure.verifier_la_structure(chemin)},
            )
        fait = appliquer(settings, chemin, plan, par=ctx.acteur)
        try:
            from mcp_gateway.atelier.project_context import ecrire_contexte

            ecrire_contexte(chemin, slug, settings)
        except Exception as exc:  # noqa: BLE001 — le contexte se régénère au prochain tour
            log.info("contexte de %s non écrit : %s", slug, exc)
        suivi = ""
        if plan.depot:
            suivi = git_repos._git(  # noqa: SLF001
                chemin, "ls-files", "--", structure.CHEMIN.as_posix(), verifier=False
            )
        return Effet(
            charge={"projet": slug, "sauvegarde": fait["sauvegarde"], "ecrits": fait["ecrits"]},
            objet_id=slug,
            titre="Structure type posée",
            resume=f"{len(fait['ecrits'])} fichiers posés ou complétés, aucun remplacé",
            voir=f"/?slug={slug}",
            preuve={
                "commit": fait["commit"],
                "fichiers": fait["ecrits"],
                "structure": structure.verifier_la_structure(chemin),
                "projet_json_suivi": bool(suivi),
                "contexte": (chemin / ".atelier" / "contexte.md").is_file(),
            },
            avant=None,
            apres={"ecrits": fait["ecrits"], "sauvegarde": fait["sauvegarde"]},
            inverse_arguments={"projet": slug, "sauvegarde": fait["sauvegarde"]},
        )

    catalogue.ajouter(
        Commande(
            nom=NOM,
            description=(
                "Migre un projet existant vers la structure type, sans rien écraser : projet.json, "
                "ETAT.md, docs/decisions/, cahier des charges, .gitignore complété, CLAUDE.md gardé "
                "avec l'import du contexte. a_blanc=true rend le plan sans rien écrire. Un seul "
                "commit ; Annuler remet l'état d'avant."
            ),
            objet="projet",
            classe=ENGAGEANTE,
            inverse=INVERSE,
            regles=[
                "ne remplace jamais un fichier présent (casse ignorée : readme.md vaut README.md)",
                ".gitignore : .atelier/ entier devient .atelier/* avec projet.json et env.json suivis",
                "CLAUDE.md gardé : import @.atelier/contexte.md en tête, section générée retirée",
                "un seul commit, avec les seuls fichiers touchés",
                "état d'avant gardé dans .atelier/avant-structure/<id>/ (ignoré par git)",
                "a_blanc : le plan, rien d'écrit",
            ],
            executer=structurer,
            apercu=apercu,
            allegement=lambda args: LECTURE if args.get("a_blanc") is True else ENGAGEANTE,
            schema={
                "type": "object",
                "properties": {
                    "projet": {"type": "string", "description": "Slug du projet."},
                    "titre": {"type": "string", "description": "Défaut : le titre affiché du projet."},
                    "description": {"type": "string", "description": "Une phrase : à quoi sert le projet."},
                    "a_blanc": {"type": "boolean", "description": "Rend le plan sans rien écrire."},
                },
                "required": ["projet"],
            },
        )
    )

    def destructurer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        slug, chemin = projet_existant(args)
        ident = texte(args, "sauvegarde", requis=True, maximum=40) or ""
        try:
            fait = defaire(settings, chemin, ident)
        except (git_repos.ErreurDepot, OSError, subprocess.SubprocessError) as exc:
            raise Refus(f"défaire la structure : {exc}") from None
        return Effet(
            charge={"projet": slug, **fait},
            objet_id=slug,
            titre="Structure type défaite",
            resume=f"{len(fait['retires'])} fichiers retirés, {len(fait['restaures'])} remis comme avant",
            voir=f"/?slug={slug}",
            preuve={"commit": fait["commit"], "restaures": fait["restaures"], "retires": fait["retires"]},
            avant={"sauvegarde": ident},
            apres=None,
            inverse_arguments={"projet": slug, **({"titre": fait["titre"]} if fait["titre"] else {})},
        )

    catalogue.ajouter(
        Commande(
            nom=INVERSE,
            description=(
                "Défait une migration vers la structure type : retire ce qu'elle a posé et remet "
                "ce qu'elle a complété. Refuse si l'un de ces fichiers a changé depuis."
            ),
            objet="projet",
            classe=REVERSIBLE,
            inverse=NOM,
            regles=[
                "refuse si un fichier posé ou complété a changé depuis la migration",
                "un fichier non suivi avant la migration redevient non suivi",
                "un commit qui ne contient que ces fichiers",
            ],
            executer=destructurer,
            schema={
                "type": "object",
                "properties": {
                    "projet": {"type": "string"},
                    "sauvegarde": {"type": "string", "description": "Identifiant rendu par la migration."},
                },
                "required": ["projet", "sauvegarde"],
            },
        )
    )


__all__ = [
    "INVERSE",
    "NOM",
    "Plan",
    "appliquer",
    "claude_md_migre",
    "defaire",
    "gitignore_migre",
    "inscrire_la_migration",
    "planifier",
]
