"""Les agents planifiés ou à la demande : créer, modifier, supprimer, activer, désactiver.

**Où vit un agent.** Dans le Pilote de wikichat : un agent y est un trigger
`cron` dont l'action est `spawn_session` (`wikichat/src/pilote.mjs`). C'est
déjà ce que la vue Agents de l'Atelier crée (`POST /v1/agent`, relais de
`POST /pilote/api/agent`) et montre (`/v1/agent/overview`), et c'est wikichat
qui ordonne les automates (transverse §1.7, J-a). On ne pose donc pas un
second registre d'agents : ces commandes écrivent dans le Pilote par la même
API, et un agent créé ici apparaît dans la vue Agents comme les autres. Les
profils d'agents de l'Atelier (`/mcp/profiles/.../pilote-bindings`) ne sont
qu'un pré-remplissage d'outils dans ce formulaire ; la commande prend
directement la liste fermée d'outils.

**Règles (J-b, J-b2).**

- Un agent naît **désactivé**, avec un **budget obligatoire** : tours par
  lancement (`max_turns`), lancements par jour (`max_per_day`, 24 au plus),
  pause entre deux lancements (`cooldown_s`).
- L'activer est **réservé** à la personne (`atelier_agent_activer`, jamais
  exposée aux modèles) ; le désactiver est permis à tous.
- Une modification faite par un modèle **désactive** l'agent : la personne le
  réactive, en connaissance de la nouvelle consigne.
- Un modèle ne supprime pas un agent actif.

**À la demande.** Le Pilote ne connaît que les agents horaires. Un agent à la
demande y est un agent dont l'horaire ne tombe jamais (`0 0 31 2 *`, le 31
février) : il ne part que par « Lancer » (`/pilote/api/agent/<id>/fire`).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.catalogue import Catalogue
from mcp_gateway.atelier.commandes.creations import entier, liste_de_noms, services_de, texte
from mcp_gateway.atelier.commandes.modele import RESERVEE, REVERSIBLE, Commande, Contexte, Effet, Refus

log = logging.getLogger("atelier.commandes")

CREER = "atelier_agent_creer"
MODIFIER = "atelier_agent_modifier"
SUPPRIMER = "atelier_agent_supprimer"
ACTIVER = "atelier_agent_activer"
DESACTIVER = "atelier_agent_desactiver"

A_LA_DEMANDE = "0 0 31 2 *"
PREFIXE_ID = "agent-"
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_CHAMP_CRON = re.compile(r"^[0-9*,/\-]+$")

# Les outils intégrés qu'un agent lancé peut recevoir. WebSearch est refusé
# partout (`profils-acces.md`) ; le reste vient du pool, par nom de connecteur.
OUTILS_INTEGRES = ("Read", "Glob", "Grep", "WebFetch", "Bash", "Write", "Edit")
OUTILS_PAR_DEFAUT = ["Read", "Glob", "Grep"]
TOURS_MAX = 100
PAR_JOUR_MAX = 24
PAUSE_PAR_DEFAUT = 3600

_CHAMPS_MODIFIABLES = ("nom", "consigne", "description", "horaire", "budget", "outils", "modele")


def _jeton_mcp(nom: str) -> str:
    return "mcp__" + re.sub(r"[^\w-]", "_", nom)


def _horaire(valeur: Any) -> str:
    """Un cron à cinq champs, ou l'horaire « à la demande »."""
    if valeur is None or valeur == "" or valeur == "manuel":
        return A_LA_DEMANDE
    if not isinstance(valeur, str):
        raise Refus("horaire : un cron à cinq champs (« 0 8 * * * »), ou absent pour un agent à la demande")
    champs = valeur.split()
    if len(champs) != 5 or not all(_CHAMP_CRON.match(c) for c in champs):
        raise Refus(f"horaire invalide : {valeur!r} (cinq champs cron, « 0 8 * * * » par exemple)")
    return " ".join(champs)


def _budget(valeur: Any) -> dict[str, int]:
    if not isinstance(valeur, dict):
        raise Refus(
            "budget obligatoire : {tours: 1-100, par_jour: 1-24, pause_s: 60 et plus} "
            "(tours par lancement, lancements par jour, pause entre deux)"
        )
    inconnus = set(valeur) - {"tours", "par_jour", "pause_s"}
    if inconnus:
        raise Refus(f"budget : champs inconnus {sorted(inconnus)}")
    tours = entier(valeur, "tours", minimum=1, maximum=TOURS_MAX)
    par_jour = entier(valeur, "par_jour", minimum=1, maximum=PAR_JOUR_MAX)
    pause = entier(valeur, "pause_s", minimum=60, maximum=7 * 86400)
    if tours is None or par_jour is None:
        raise Refus("budget : tours et par_jour sont obligatoires")
    return {"tours": tours, "par_jour": par_jour, "pause_s": pause if pause is not None else PAUSE_PAR_DEFAUT}


def _valeur_de(texte_affiche: Any, motif: str) -> int | None:
    m = re.search(motif, str(texte_affiche or ""))
    return int(m.group(1)) if m else None


def definition_du_pilote(agent: dict[str, Any]) -> dict[str, Any]:
    """Un agent tel que le Pilote le montre, dans le vocabulaire des commandes.

    La forme lue est celle de `triggerToAgent` (`pilote.mjs`), la même que
    relit le formulaire d'édition de la vue Agents.
    """
    trigger = agent.get("trigger") or {}
    scope = agent.get("scope") or {}
    memoire = agent.get("memory") or {}
    mission = agent.get("mission")
    consigne = "\n".join(mission) if isinstance(mission, list) else str(mission or "")
    cron = str(agent.get("cron") or trigger.get("freq") or "")
    dossier = str(scope.get("dir") or "")
    modele = str(memoire.get("budget") or "")
    return {
        "id": str(agent.get("id") or ""),
        "nom": str(agent.get("name") or ""),
        "description": str(agent.get("desc") or ""),
        "consigne": consigne,
        "horaire": None if cron in ("", "—", A_LA_DEMANDE) else cron,
        "budget": {
            "tours": _valeur_de(memoire.get("turns"), r"--max-turns\s+(\d+)"),
            "par_jour": _valeur_de(trigger.get("cap"), r"^(\d+)"),
            "pause_s": _valeur_de(trigger.get("cooldown"), r"^(\d+)"),
        },
        "outils": [str(o) for o in scope.get("servers") or []],
        "modele": "" if modele == "—" else modele,
        "dossier": "" if dossier == "—" else dossier,
        "actif": bool(agent.get("enabled")),
    }


def inscrire_les_agents(app: Any, catalogue: Catalogue) -> None:
    settings = app.state.settings

    def pilote() -> Any:
        acces = services_de(app).pilote
        if acces is None:
            raise Refus("le Pilote de wikichat n'est pas joignable ici : aucun agent ne peut être touché")
        return acces

    async def agents_du_pilote() -> dict[str, dict[str, Any]]:
        try:
            donnees = await pilote().lire()
        except Refus:
            raise
        except Exception as exc:  # noqa: BLE001 — wikichat arrêté : on le dit
            raise Refus(f"Pilote de wikichat illisible : {type(exc).__name__}: {exc}") from None
        agents = donnees.get("agents") if isinstance(donnees, dict) else None
        systeme = donnees.get("system_agents") if isinstance(donnees, dict) else None
        tous: dict[str, dict[str, Any]] = {}
        for a in (agents or []):
            if isinstance(a, dict) and a.get("id"):
                tous[str(a["id"])] = {**a, "_pilote": True}
        for a in (systeme or []):
            if isinstance(a, dict) and a.get("id") and str(a["id"]) not in tous:
                tous[str(a["id"])] = {**a, "_pilote": False}
        return tous

    async def agent_existant(args: dict[str, Any]) -> dict[str, Any]:
        ident = texte(args, "agent", requis=True, maximum=64) or ""
        tous = await agents_du_pilote()
        agent = tous.get(ident)
        if agent is None:
            raise Refus(f"agent inconnu : {ident}")
        if not agent.get("_pilote"):
            raise Refus(
                f"{ident} est une tâche de la plateforme, pas un agent du Pilote : "
                "elle ne se modifie pas par ces commandes"
            )
        return agent

    def pool() -> set[str]:
        from mcp_gateway.atelier.mcp_sync import _pool_enabled

        try:
            return set(_pool_enabled(settings))
        except Exception as exc:  # noqa: BLE001
            raise Refus(f"catalogue des connecteurs illisible : {exc}") from None

    def outils_valides(noms: list[str] | None, deja: list[str] | None = None) -> list[str]:
        """La liste fermée d'outils, au format du Pilote (`Bash`, `mcp__<connecteur>`)."""
        if noms is None:
            return list(OUTILS_PAR_DEFAUT)
        deja = deja or []
        connus: set[str] | None = None
        jetons: list[str] = []
        for nom in noms:
            if nom in OUTILS_INTEGRES:
                jetons.append(nom)
                continue
            if nom == "WebSearch":
                raise Refus("WebSearch est refusé partout ; WebFetch lit une page dont on a l'adresse")
            if nom in deja:
                jetons.append(nom)
                continue
            if connus is None:
                connus = pool() | {"wikichat"}
            brut = nom[len("mcp__"):] if nom.startswith("mcp__") else nom
            trouve = next((c for c in connus if c == brut or _jeton_mcp(c) == _jeton_mcp(brut)), None)
            if trouve is None:
                raise Refus(
                    f"outil inconnu : {nom}. Outils intégrés : {', '.join(OUTILS_INTEGRES)} ; "
                    f"connecteurs : {', '.join(sorted(connus)) or 'aucun'}"
                )
            jetons.append(_jeton_mcp(trouve))
        if not jetons:
            raise Refus("outils : au moins un")
        return list(dict.fromkeys(jetons))

    def dossier_de(projet: str | None, ident: str) -> Path:
        if projet:
            if projet == settings.assistant_slug:
                raise Refus("le dossier de l'Assistant n'accueille pas d'agent planifié")
            chemin = settings.projects_dir / projet
            if structure.slugifier(projet) != projet or not chemin.is_dir():
                raise Refus(f"projet inconnu : {projet}")
            return chemin
        # Un agent qui n'est dédié à aucun projet travaille dans un dossier à
        # lui, hors de la racine des projets (il n'encombre pas la liste de Code).
        return settings.work_dir / "agents" / ident

    def charge_pilote(ident: str, d: dict[str, Any], actif: bool) -> dict[str, Any]:
        budget = d["budget"]
        corps: dict[str, Any] = {
            "id": ident,
            "name": d["nom"],
            "desc": d.get("description") or "",
            "dir": d["dossier"],
            "freq": d["horaire"] or A_LA_DEMANDE,
            "mission": d["consigne"],
            "tools": d["outils"],
            "max_turns": budget["tours"],
            "max_per_day": budget["par_jour"],
            "cooldown_s": budget["pause_s"],
            "enabled": actif,
        }
        if d.get("modele"):
            corps["model"] = d["modele"]
        return corps

    async def ecrire_au_pilote(corps: dict[str, Any]) -> dict[str, Any]:
        try:
            retour = await pilote().ecrire("/pilote/api/agent", corps)
        except Refus:
            raise
        except Exception as exc:  # noqa: BLE001
            raise Refus(f"le Pilote a refusé l'agent : {type(exc).__name__}: {exc}") from None
        if not isinstance(retour, dict) or not retour.get("ok"):
            raise Refus(f"le Pilote a refusé l'agent : {retour}")
        return retour

    async def relu(ident: str) -> dict[str, Any]:
        agent = (await agents_du_pilote()).get(ident)
        if agent is None:
            raise Refus(f"l'agent {ident} n'apparaît pas dans le Pilote après l'écriture")
        return agent

    def preuve_de(agent: dict[str, Any]) -> dict[str, Any]:
        d = definition_du_pilote(agent)
        return {
            "pilote": d["id"],
            "actif": d["actif"],
            "horaire": d["horaire"] or "à la demande",
            "budget": d["budget"],
            "outils": d["outils"],
        }

    def voir(ident: str) -> str:
        return f"/?vue=agents&agent={ident}"

    # ── Créer ───────────────────────────────────────────────────────────

    async def creer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        nom = texte(args, "nom", requis=True, maximum=80) or ""
        consigne = texte(args, "consigne", requis=True, maximum=20000) or ""
        description = texte(args, "description", maximum=300) or ""
        projet = texte(args, "projet", maximum=60)
        horaire = _horaire(args.get("horaire"))
        budget = _budget(args.get("budget"))
        modele = texte(args, "modele", maximum=80) or ""
        voulu = texte(args, "id", maximum=64)
        tous = await agents_du_pilote()
        if voulu:
            if not _ID.match(voulu):
                raise Refus("id : minuscules, chiffres et tirets")
            ident = voulu
            if ident in tous:
                raise Refus(f"un agent porte déjà l'identifiant {ident}")
        else:
            base = PREFIXE_ID + (structure.slugifier(nom) or "agent")
            ident, n = base[:64], 2
            while ident in tous:
                suffixe = f"-{n}"
                ident = base[: 64 - len(suffixe)] + suffixe
                n += 1
        outils = outils_valides(liste_de_noms(args, "outils"), deja=liste_de_noms(args, "outils") if voulu else None)
        dossier = dossier_de(projet, ident)
        dossier.mkdir(parents=True, exist_ok=True)
        definition = {
            "nom": nom,
            "description": description,
            "consigne": consigne,
            "horaire": None if horaire == A_LA_DEMANDE else horaire,
            "budget": budget,
            "outils": outils,
            "modele": modele,
            "dossier": str(dossier),
        }
        await ecrire_au_pilote(charge_pilote(ident, definition, actif=False))
        agent = await relu(ident)
        if agent.get("enabled"):
            # Le Pilote n'a pas retenu la naissance désactivée : on corrige
            # tout de suite, et on le dit.
            await pilote().ecrire(f"/pilote/api/agent/{ident}/toggle", {})
            agent = await relu(ident)
            if agent.get("enabled"):
                raise Refus(f"l'agent {ident} est né actif et n'a pas pu être désactivé : désactivez-le à la main")
        return Effet(
            charge={"agent": ident, "nom": nom, "actif": False, "projet": projet or None, "dossier": str(dossier)},
            objet_id=ident,
            titre="Agent créé, désactivé",
            resume=(
                f"« {nom} » ({'à la demande' if horaire == A_LA_DEMANDE else horaire}), "
                f"{budget['tours']} tours par lancement, {budget['par_jour']} lancements par jour au plus. "
                "La personne l'active dans la vue Agents."
            ),
            voir=voir(ident),
            preuve=preuve_de(agent),
            avant=None,
            apres={"agent": ident, **definition, "actif": False},
            inverse_arguments={"agent": ident},
        )

    schema_budget = {
        "type": "object",
        "description": "Obligatoire. tours : 1-100 par lancement ; par_jour : 1-24 ; pause_s : défaut 3600.",
        "properties": {
            "tours": {"type": "integer", "minimum": 1, "maximum": TOURS_MAX},
            "par_jour": {"type": "integer", "minimum": 1, "maximum": PAR_JOUR_MAX},
            "pause_s": {"type": "integer", "minimum": 60},
        },
        "required": ["tours", "par_jour"],
    }
    proprietes_agent = {
        "nom": {"type": "string", "description": "Le nom affiché dans la vue Agents."},
        "consigne": {"type": "string", "description": "Ce que l'agent fait à chaque lancement."},
        "description": {"type": "string"},
        "projet": {"type": "string", "description": "Slug du projet où il travaille ; absent : un dossier à lui."},
        "horaire": {
            "type": "string",
            "description": "Cron à cinq champs (« 0 8 * * * ») ; absent ou « manuel » : à la demande.",
        },
        "budget": schema_budget,
        "outils": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                f"Liste fermée : {', '.join(OUTILS_INTEGRES)}, ou le nom d'un connecteur du pool. "
                "Défaut : Read, Glob, Grep. Les connecteurs connus du Pilote sont réduits à la lecture."
            ),
        },
        "modele": {"type": "string", "description": "Facultatif ; défaut : celui du Pilote."},
    }
    catalogue.ajouter(
        Commande(
            nom=CREER,
            description=(
                "Crée un agent planifié (horaire cron) ou à la demande, dédié à un projet ou non, dans "
                "le Pilote de wikichat (vue Agents). Il naît désactivé : seule la personne l'active. "
                "Le budget (tours par lancement, lancements par jour) est obligatoire."
            ),
            objet="agent",
            classe=REVERSIBLE,
            inverse=SUPPRIMER,
            regles=[
                "naît désactivé (J-b) ; l'activation est réservée à la personne",
                "budget obligatoire : tours par lancement, lancements par jour (24 au plus), pause",
                "outils en liste fermée : intégrés, ou connecteurs du pool ; jamais WebSearch",
                "écrit dans le Pilote de wikichat, comme la vue Agents : pas de second registre",
                "un agent dédié travaille dans le dossier de son projet ; sinon dans ~/work/agents/<id>",
            ],
            executer=creer,
            schema={
                "type": "object",
                "properties": {
                    **proprietes_agent,
                    "id": {"type": "string", "description": "Réservé à l'annulation d'une suppression."},
                },
                "required": ["nom", "consigne", "budget"],
            },
        )
    )

    # ── Modifier ────────────────────────────────────────────────────────

    async def modifier(ctx: Contexte, args: dict[str, Any]) -> Effet:
        agent = await agent_existant(args)
        ident = str(agent["id"])
        actuelle = definition_du_pilote(agent)
        voulue = dict(actuelle)
        if "nom" in args:
            voulue["nom"] = texte(args, "nom", requis=True, maximum=80)
        if "consigne" in args:
            voulue["consigne"] = texte(args, "consigne", requis=True, maximum=20000)
        if "description" in args:
            voulue["description"] = texte(args, "description", maximum=300) or ""
        if "horaire" in args:
            h = _horaire(args.get("horaire"))
            voulue["horaire"] = None if h == A_LA_DEMANDE else h
        if "budget" in args:
            voulue["budget"] = _budget(args.get("budget"))
        if "outils" in args:
            voulue["outils"] = outils_valides(liste_de_noms(args, "outils"), deja=actuelle["outils"])
        if "modele" in args:
            voulue["modele"] = texte(args, "modele", maximum=80) or ""
        if not any(k in args for k in _CHAMPS_MODIFIABLES):
            raise Refus(f"rien à modifier : {', '.join(_CHAMPS_MODIFIABLES)}")
        budget = voulue["budget"]
        if not all(isinstance(budget.get(k), int) for k in ("tours", "par_jour", "pause_s")):
            raise Refus("cet agent n'a pas de budget lisible : passez budget en entier")
        avant = {k: actuelle[k] for k in _CHAMPS_MODIFIABLES if actuelle[k] != voulue[k]}
        apres = {k: voulue[k] for k in avant}
        # Un modèle qui change un agent actif le désactive : la personne
        # réactive en connaissance de la nouvelle définition.
        actif = actuelle["actif"] and ctx.est_la_personne
        if apres or actif != actuelle["actif"]:
            await ecrire_au_pilote(charge_pilote(ident, voulue, actif=actif))
        relu_ = await relu(ident)
        if relu_.get("enabled") and not actif:
            await pilote().ecrire(f"/pilote/api/agent/{ident}/toggle", {})
            relu_ = await relu(ident)
        desactive = actuelle["actif"] and not bool(relu_.get("enabled"))
        resume = ", ".join(sorted(apres)) or "déjà ainsi"
        if desactive:
            resume += " ; désactivé : la personne le réactive"
        inverse: dict[str, Any] | None = None
        if avant:
            inverse = {"agent": ident, **avant}
            if inverse.get("horaire") is None and "horaire" in avant:
                inverse["horaire"] = "manuel"
        return Effet(
            charge={"agent": ident, "modifie": sorted(apres), "avant": avant, "apres": apres, "desactive": desactive},
            objet_id=ident,
            titre="Agent modifié" if apres else "Agent inchangé",
            resume=resume,
            voir=voir(ident),
            preuve=preuve_de(relu_),
            avant={**avant, "actif": actuelle["actif"]},
            apres={**apres, "actif": bool(relu_.get("enabled"))},
            inverse_arguments=inverse,
        )

    catalogue.ajouter(
        Commande(
            nom=MODIFIER,
            description=(
                "Modifie un agent du Pilote : nom, consigne, description, horaire, budget, outils, modèle. "
                "Une modification par un modèle désactive l'agent ; la personne le réactive. "
                "Annuler remet les valeurs d'avant."
            ),
            objet="agent",
            classe=REVERSIBLE,
            inverse=MODIFIER,
            regles=[
                "ne touche que les champs donnés ; garde l'historique des lancements",
                "un agent modifié par un modèle est désactivé",
                "mêmes règles de budget et d'outils qu'à la création",
            ],
            executer=modifier,
            schema={
                "type": "object",
                "properties": {"agent": {"type": "string", "description": "Identifiant de l'agent."}, **proprietes_agent},
                "required": ["agent"],
            },
        )
    )

    # ── Supprimer ───────────────────────────────────────────────────────

    async def supprimer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        agent = await agent_existant(args)
        ident = str(agent["id"])
        definition = definition_du_pilote(agent)
        if definition["actif"] and not ctx.est_la_personne:
            raise Refus(
                f"{ident} est actif : un modèle ne supprime pas un agent actif. "
                f"Désactivez-le d'abord ({DESACTIVER}), ou laissez la personne le faire."
            )
        try:
            retour = await pilote().supprimer(f"/pilote/api/agent/{ident}")
        except Refus:
            raise
        except Exception as exc:  # noqa: BLE001
            raise Refus(f"suppression refusée par le Pilote : {type(exc).__name__}: {exc}") from None
        if ident in await agents_du_pilote():
            raise Refus(f"l'agent {ident} est toujours dans le Pilote : {retour}")
        # L'inverse recrée l'agent, désactivé, sous le même identifiant.
        recreer: dict[str, Any] = {
            "id": ident,
            "nom": definition["nom"],
            "consigne": definition["consigne"] or "(consigne vide)",
            "description": definition["description"],
            "horaire": definition["horaire"] or "manuel",
            "outils": definition["outils"] or list(OUTILS_PAR_DEFAUT),
        }
        budget = definition["budget"]
        if all(isinstance(budget.get(k), int) for k in ("tours", "par_jour")):
            recreer["budget"] = {k: v for k, v in budget.items() if isinstance(v, int)}
            recreer["budget"]["par_jour"] = min(recreer["budget"]["par_jour"], PAR_JOUR_MAX)
            recreer["budget"]["tours"] = min(recreer["budget"]["tours"], TOURS_MAX)
            if recreer["budget"].get("pause_s", PAUSE_PAR_DEFAUT) < 60:
                recreer["budget"]["pause_s"] = 60
        if definition["modele"]:
            recreer["modele"] = definition["modele"]
        dossier = definition["dossier"]
        try:
            projet = Path(dossier).resolve().relative_to(settings.projects_dir.resolve()).parts[0]
            recreer["projet"] = projet
        except (ValueError, OSError, IndexError):
            pass
        return Effet(
            charge={"agent": ident, "supprime": True},
            objet_id=ident,
            titre="Agent supprimé",
            resume=f"« {definition['nom']} » retiré du Pilote ; son dossier et ses propositions restent",
            voir="/?vue=agents",
            preuve={"pilote": ident, "present": False},
            avant=definition,
            apres=None,
            inverse_arguments=recreer if "budget" in recreer else None,
        )

    schema_agent = {
        "type": "object",
        "properties": {"agent": {"type": "string", "description": "Identifiant de l'agent."}},
        "required": ["agent"],
    }
    catalogue.ajouter(
        Commande(
            nom=SUPPRIMER,
            description=(
                "Retire un agent du Pilote. Son dossier, ses propositions et l'historique de ses "
                "lancements restent. Un modèle ne supprime pas un agent actif. Annuler le recrée, désactivé."
            ),
            objet="agent",
            classe=REVERSIBLE,
            inverse=CREER,
            regles=[
                "un agent actif ne se supprime que par la personne",
                "ne touche ni au dossier ni aux propositions de l'agent",
                "l'annulation recrée l'agent désactivé, sous le même identifiant",
            ],
            executer=supprimer,
            schema=schema_agent,
        )
    )

    # ── Activer, désactiver ─────────────────────────────────────────────

    def basculer(voulu: bool) -> Any:
        async def executer(ctx: Contexte, args: dict[str, Any]) -> Effet:
            agent = await agent_existant(args)
            ident = str(agent["id"])
            definition = definition_du_pilote(agent)
            if voulu:
                budget = definition["budget"]
                if not all(isinstance(budget.get(k), int) for k in ("tours", "par_jour")):
                    raise Refus(f"{ident} n'a pas de budget lisible : fixez-le ({MODIFIER}) avant de l'activer")
            change = definition["actif"] != voulu
            if change:
                try:
                    await pilote().ecrire(f"/pilote/api/agent/{ident}/toggle", {})
                except Exception as exc:  # noqa: BLE001
                    raise Refus(f"le Pilote n'a pas basculé l'agent : {type(exc).__name__}: {exc}") from None
            relu_ = await relu(ident)
            if bool(relu_.get("enabled")) != voulu:
                raise Refus(f"l'agent {ident} n'est pas {'actif' if voulu else 'désactivé'} après la bascule")
            return Effet(
                charge={"agent": ident, "actif": voulu, "change": change},
                objet_id=ident,
                titre=("Agent activé" if voulu else "Agent désactivé") if change else "Agent inchangé",
                resume=(
                    f"prochain lancement : {relu_.get('next') or '—'} ; "
                    f"{definition['budget'].get('par_jour')} lancements par jour au plus, "
                    f"{definition['budget'].get('tours')} tours chacun"
                    if voulu
                    else "il ne part plus seul ; « Lancer » reste possible"
                ),
                voir=voir(ident),
                preuve=preuve_de(relu_),
                avant={"actif": definition["actif"]},
                apres={"actif": voulu},
                inverse_arguments={"agent": ident} if change else None,
            )

        return executer

    catalogue.ajouter(
        Commande(
            nom=ACTIVER,
            description=(
                "Active un agent du Pilote : il part seul selon son horaire, dans son budget. "
                "Réservée à la personne (J-b2) : un modèle ne l'appelle jamais."
            ),
            objet="agent",
            classe=RESERVEE,
            inverse=DESACTIVER,
            regles=["jamais par un modèle", "refusée sans budget lisible", "vérifie l'état après la bascule"],
            executer=basculer(True),
            schema=schema_agent,
            exposee_mcp=False,
        )
    )
    catalogue.ajouter(
        Commande(
            nom=DESACTIVER,
            description="Désactive un agent du Pilote : il ne part plus seul. Permis à tous (J-b2).",
            objet="agent",
            classe=REVERSIBLE,
            inverse=ACTIVER,
            regles=["l'annulation (réactiver) est réservée à la personne", "vérifie l'état après la bascule"],
            executer=basculer(False),
            schema=schema_agent,
        )
    )


__all__ = [
    "A_LA_DEMANDE",
    "ACTIVER",
    "CREER",
    "DESACTIVER",
    "MODIFIER",
    "SUPPRIMER",
    "definition_du_pilote",
    "inscrire_les_agents",
]
