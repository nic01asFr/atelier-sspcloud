"""Retrouver le passé et tenir la mémoire de la personne : les commandes de la mémoire.

La capitalisation vit dans wikichat (fiches de conversation, index, mémoire de
la personne) ; ces commandes en sont la porte, par le catalogue (§1.8) :

| Commande | Classe | Profil | Rôle |
|---|---|---|---|
| `atelier_rappel(requete, projet?)` | lecture | assistant ; code pour **son** projet | les fiches proches, en environ 450 jetons |
| `atelier_fiche(id)` | lecture | assistant ; code pour **son** projet | une fiche, 2 500 caractères au plus |
| `atelier_memoire` | lecture | assistant | ce qui est retenu : profil, préférences, faits |
| `atelier_memoire_proposer` | reversible | assistant | une proposition dans « À valider » (source `memoire`) |
| `atelier_memoire_retenir` | reservee | la personne | exécutée à l'acceptation d'une proposition |
| `atelier_memoire_corriger` | reservee | la personne | « Corriger » dans « Ma mémoire » |
| `atelier_memoire_oublier` | reservee | la personne | « Oublier » dans « Ma mémoire » |

A-7 : les faits extraits par le code sont enregistrés d'office (par wikichat) ;
préférences et interprétations proposées par un modèle passent par « À
valider ». Un modèle ne retient donc jamais rien lui-même : `retenir` est
réservée, et n'est même pas exposée en MCP.

En profil `code`, le projet vient de la conversation (`profils.cadrer_les_arguments`) :
`atelier_rappel` ne cherche que dans les fiches de ce projet, `atelier_fiche`
refuse une fiche d'un autre projet.
"""

from __future__ import annotations

import json
import math
from typing import Any

from mcp_gateway.atelier.commandes.catalogue import Catalogue
from mcp_gateway.atelier.commandes.modele import (
    LECTURE,
    RESERVEE,
    REVERSIBLE,
    Commande,
    Contexte,
    Effet,
    Refus,
)

RAPPEL = "atelier_rappel"
FICHE = "atelier_fiche"
MEMOIRE = "atelier_memoire"
PROPOSER = "atelier_memoire_proposer"
RETENIR = "atelier_memoire_retenir"
CORRIGER = "atelier_memoire_corriger"
OUBLIER = "atelier_memoire_oublier"

# Estimation des jetons : caractères / 3,4, comme le relais et la carte.
CARACTERES_PAR_UNITE = 3.4
BUDGET_RAPPEL_UNITES = 450
BUDGET_RAPPEL_CAR = int(BUDGET_RAPPEL_UNITES * CARACTERES_PAR_UNITE)
BUDGET_FICHE_CAR = 2500
RAPPEL_LIMITE = 5
TYPES_RETENUS = ("profil", "preference", "interpretation", "fait")


def unites(charge: Any) -> int:
    return math.ceil(len(json.dumps(charge, ensure_ascii=False)) / CARACTERES_PAR_UNITE)


def _texte(args: dict[str, Any], nom: str, *, requis: bool = False, maximum: int = 300) -> str:
    valeur = args.get(nom)
    if valeur is None or valeur == "":
        if requis:
            raise Refus(f"{nom} requis")
        return ""
    if not isinstance(valeur, str):
        raise Refus(f"{nom} : un texte")
    valeur = " ".join(valeur.split())
    if len(valeur) > maximum:
        raise Refus(f"{nom} : {maximum} caractères au plus")
    return valeur


def _date_courte(iso: str) -> str:
    iso = str(iso or "")
    return f"{iso[8:10]}/{iso[5:7]}" if len(iso) >= 10 else "?"


def _couper(texte: str, n: int) -> str:
    texte = " ".join(str(texte or "").split())
    return texte if len(texte) <= n else texte[: max(0, n - 1)].rstrip() + "…"


def mettre_en_forme_le_rappel(requete: str, projet: str, resultats: list[dict[str, Any]], total: int) -> dict[str, Any]:
    """Les fiches trouvées, en lignes courtes, sous le budget (≈ 450 jetons).

    Une ligne : identifiant court (8 caractères, accepté par `atelier_fiche`),
    date, projet, titre, résumé d'une ligne. Le résumé raccourcit d'abord ;
    au-delà, les dernières lignes tombent.
    """
    def ligne(r: dict[str, Any], n_resume: int) -> str:
        tete = f"{str(r.get('id') or '')[:8]} · {_date_courte(r.get('fin') or r.get('debut'))} · {r.get('projet') or '?'}"
        titre = _couper(r.get("titre") or "", 70)
        resume = _couper(r.get("resume") or "", n_resume) if n_resume else ""
        return f"{tete} · {titre}" + (f" — {resume}" if resume else "")

    base = {
        "requete": requete,
        **({"projet": projet} if projet else {}),
        "fiches": [],
        "trouvees": total,
        "suite": "atelier_fiche(id) pour le détail d'une fiche",
    }
    if not resultats:
        base["suite"] = "aucune fiche : reformuler, ou élargir (sans projet)"
        return base
    def tient(charge: dict[str, Any]) -> bool:
        return len(json.dumps(charge, ensure_ascii=False)) <= BUDGET_RAPPEL_CAR

    for n_resume in (180, 120, 70, 0):
        charge = {**base, "fiches": [ligne(r, n_resume) for r in resultats]}
        if tient(charge):
            return charge
    for garder in range(len(resultats) - 1, 0, -1):
        charge = {**base, "fiches": [ligne(r, 0) for r in resultats[:garder]]}
        if tient(charge):
            return charge
    return {**base, "requete": _couper(requete, 80), "fiches": [ligne(resultats[0], 0)[:200]]}


def _refus_wikichat(statut: int, charge: Any) -> Refus:
    detail = charge.get("erreur") or charge.get("error") if isinstance(charge, dict) else None
    return Refus(f"wikichat : {detail or f'HTTP {statut}'}")


def inscrire_la_memoire(app: Any, catalogue: Catalogue) -> None:
    """Les commandes et les routes internes de la mémoire ; la ligne que `commandes.enregistrer` appelle."""
    from mcp_gateway.atelier.commandes import profils
    from mcp_gateway.atelier.memoire import (
        WikichatAbsent,
        construire_le_routeur,
        deposer_une_proposition,
        wikichat_de,
    )

    async def demander(methode: str, chemin: str, **kw: Any) -> tuple[int, Any]:
        try:
            return await wikichat_de(app).demander(methode, chemin, **kw)
        except WikichatAbsent as exc:
            raise Refus(f"wikichat ne répond pas ({exc}) : la mémoire est indisponible") from None

    def projet_permis(args: dict[str, Any]) -> str:
        """Le projet demandé ; en profil `code`, celui de la conversation (déjà cadré)."""
        projet = _texte(args, "projet", maximum=100)
        if profils.est_restreint() and not projet:
            raise Refus("profil code : le projet de la conversation est requis")
        return projet

    # ── atelier_rappel ──────────────────────────────────────────────────

    async def rappel(ctx: Contexte, args: dict[str, Any]) -> Effet:
        requete = _texte(args, "requete", requis=True, maximum=300)
        projet = projet_permis(args)
        depuis = _texte(args, "depuis", maximum=40)
        limite = args.get("limite", RAPPEL_LIMITE)
        if not isinstance(limite, int) or isinstance(limite, bool) or not 1 <= limite <= RAPPEL_LIMITE:
            raise Refus(f"limite : entre 1 et {RAPPEL_LIMITE}")
        statut, charge = await demander(
            "GET", "/api/memoire/rappel", params={"q": requete, "projet": projet, "depuis": depuis, "limite": limite}
        )
        if statut != 200 or not isinstance(charge, dict):
            raise _refus_wikichat(statut, charge)
        resultats = [r for r in charge.get("resultats") or [] if isinstance(r, dict)]
        if projet:
            # La borne tient même si wikichat se trompait : jamais une fiche d'ailleurs.
            resultats = [r for r in resultats if r.get("projet") == projet]
        sortie = mettre_en_forme_le_rappel(requete, projet, resultats[:limite], int(charge.get("total") or len(resultats)))
        return Effet(charge=sortie, objet_id=projet or "tout")

    catalogue.ajouter(
        Commande(
            nom=RAPPEL,
            description=(
                "Retrouver une conversation passée sans la relire : les fiches les plus proches "
                "de la requête (date, projet, titre, résumé d'une ligne), environ 450 jetons au plus. "
                "Puis atelier_fiche(id) pour le détail d'une fiche. projet=<slug> pour ne chercher "
                "que dans un projet."
            ),
            objet="memoire",
            classe=LECTURE,
            regles=[
                "lecture seule",
                "au plus 5 fiches, environ 450 jetons (caractères / 3,4)",
                "profil code : les fiches de son projet seulement",
                "fiches écrites par le code (faits) et par la routine de nuit (sens), jamais le transcript",
            ],
            executer=rappel,
            schema={
                "type": "object",
                "properties": {
                    "requete": {"type": "string", "description": "Ce qu'on cherche, en mots-clés."},
                    "projet": {"type": "string", "description": "Slug du projet, pour borner la recherche."},
                    "depuis": {"type": "string", "description": "Date ISO : seulement les conversations d'après."},
                    "limite": {"type": "integer", "description": "1 à 5 (défaut 5)."},
                },
                "required": ["requete"],
            },
        )
    )

    # ── atelier_fiche ───────────────────────────────────────────────────

    async def fiche(ctx: Contexte, args: dict[str, Any]) -> Effet:
        ident = _texte(args, "id", requis=True, maximum=200)
        if len(ident) < 8:
            raise Refus("id : 8 caractères au moins (l'identifiant court que rend atelier_rappel)")
        projet = projet_permis(args)
        statut, charge = await demander("GET", f"/api/memoire/fiches/{ident}", params={"projet": projet})
        if statut == 404:
            raise Refus(f"fiche introuvable : {ident}" + (f" dans le projet {projet}" if projet else ""))
        if statut != 200 or not isinstance(charge, dict):
            raise _refus_wikichat(statut, charge)
        if projet and charge.get("projet") != projet:
            raise Refus(f"fiche introuvable : {ident} dans le projet {projet}")
        texte = str(charge.get("texte") or "")
        coupe = len(texte) > BUDGET_FICHE_CAR
        if coupe:
            texte = texte[: BUDGET_FICHE_CAR - 20].rstrip() + "\n… (fiche coupée)"
        sortie = {
            "id": charge.get("id"),
            "projet": charge.get("projet"),
            "genre": charge.get("genre"),
            "fiche": texte,
            **({"coupee": True} if coupe else {}),
        }
        return Effet(charge=sortie, objet_id=str(charge.get("id") or ident))

    catalogue.ajouter(
        Commande(
            nom=FICHE,
            description=(
                "La fiche d'une conversation passée : faits extraits par le code (dates, projet, "
                "créations, fichiers touchés, agents lancés, erreurs), premiers messages de la "
                "personne, et le résumé de la routine de nuit s'il existe. id : l'identifiant "
                "(ou ses 8 premiers caractères) rendu par atelier_rappel."
            ),
            objet="memoire",
            classe=LECTURE,
            regles=["lecture seule", "2 500 caractères au plus", "profil code : une fiche de son projet seulement"],
            executer=fiche,
            schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "Identifiant de la conversation (8 caractères suffisent)."},
                    "projet": {"type": "string"},
                },
                "required": ["id"],
            },
        )
    )

    # ── atelier_memoire (lire) ──────────────────────────────────────────

    async def lire_la_memoire(ctx: Contexte, args: dict[str, Any]) -> Effet:
        statut, charge = await demander("GET", "/api/memoire/personne")
        if statut != 200 or not isinstance(charge, dict):
            raise _refus_wikichat(statut, charge)
        file = getattr(app.state, "a_valider", None)
        en_attente = []
        if file is not None:
            en_attente = [
                {"id": p.id, "titre": p.titre, "type": (p.detail or {}).get("type"),
                 "texte": (p.detail or {}).get("texte"), "creee_le": p.creee_le}
                for p in file.lister(source="memoire")
            ]
        return Effet(charge={**charge, "propositions_en_attente": en_attente}, objet_id="personne")

    catalogue.ajouter(
        Commande(
            nom=MEMOIRE,
            description=(
                "Ce que l'Atelier retient de la personne : profil, préférences et interprétations "
                "validés par elle, faits extraits par le code, et les propositions encore à valider."
            ),
            objet="memoire",
            classe=LECTURE,
            regles=["lecture seule", "rien n'y entre sans validation, sauf les faits extraits par le code"],
            executer=lire_la_memoire,
            schema={"type": "object", "properties": {}},
        )
    )

    # ── atelier_memoire_proposer ────────────────────────────────────────

    async def proposer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        from mcp_gateway.atelier.outils_conversation import CONVERSATION_APPELANTE

        type_ = _texte(args, "type", requis=True, maximum=40)
        texte = _texte(args, "texte", requis=True, maximum=300)
        raison = _texte(args, "raison", maximum=300)
        file = getattr(app.state, "a_valider", None)
        if file is None:
            raise Refus("la file « À valider » n'est pas montée")
        conversation = CONVERSATION_APPELANTE.get() or ""
        try:
            p = deposer_une_proposition(
                file, app.state.settings, type_=type_, texte=texte, acteur=ctx.acteur,
                conversation=conversation, raison=raison,
            )
        except ValueError as exc:
            raise Refus(str(exc)) from None
        return Effet(
            charge={"proposition": p.id, "statut": p.statut, "titre": p.titre},
            objet_id=p.id,
            titre="Proposé à la mémoire",
            resume=f"{p.titre} — attend l'accord de la personne dans « À valider »",
            voir="/?view=a-valider",
            apres={"proposition": p.id},
            inverse_arguments={"id": p.id, "motif": "retiré par son auteur"},
        )

    catalogue.ajouter(
        Commande(
            nom=PROPOSER,
            description=(
                "Proposer de retenir une préférence, un trait du profil ou une interprétation sur la "
                "personne. La proposition va dans « À valider » : rien n'est retenu sans son accord. "
                "Trois au plus par conversation ; les doublons sont ignorés."
            ),
            objet="memoire",
            classe=REVERSIBLE,
            inverse="atelier_a_valider_refuser",
            regles=[
                "ne retient rien : dépose une proposition (source memoire)",
                "3 par conversation au plus, doublons ignorés",
                "texte filtré des secrets",
            ],
            executer=proposer,
            schema={
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["preference", "profil", "interpretation"]},
                    "texte": {"type": "string", "description": "Une phrase courte (300 caractères au plus)."},
                    "raison": {"type": "string", "description": "D'où vient la proposition."},
                },
                "required": ["type", "texte"],
            },
        )
    )

    # ── Les trois gestes de la personne ─────────────────────────────────

    def element(charge: Any) -> dict[str, Any]:
        el = charge.get("element") if isinstance(charge, dict) else None
        if not isinstance(el, dict):
            raise Refus("wikichat : réponse sans élément")
        return el

    async def retenir(ctx: Contexte, args: dict[str, Any]) -> Effet:
        type_ = _texte(args, "type", requis=True, maximum=40)
        if type_ not in TYPES_RETENUS:
            raise Refus(f"type : {', '.join(TYPES_RETENUS)}")
        texte = _texte(args, "texte", requis=True, maximum=300)
        source = dict(args.get("source")) if isinstance(args.get("source"), dict) else {}
        # Une proposition porte sa provenance à plat (conversation, projet, fiche).
        for cle in ("conversation", "projet", "fiche"):
            if isinstance(args.get(cle), str) and args[cle]:
                source.setdefault(cle, args[cle][:200])
        statut, charge = await demander(
            "POST", "/api/memoire/personne", corps={"type": type_, "texte": texte, "source": source, "par": ctx.acteur}
        )
        if statut not in (200, 201):
            raise _refus_wikichat(statut, charge)
        el = element(charge)
        return Effet(
            charge={"element": el},
            objet_id=str(el.get("id") or ""),
            titre="Retenu",
            resume=f"{type_} : {texte[:120]}",
            voir="/?view=memoire",
            apres=el,
            inverse_arguments={"id": el.get("id")},
        )

    async def corriger(ctx: Contexte, args: dict[str, Any]) -> Effet:
        ident = _texte(args, "id", requis=True, maximum=80)
        texte = _texte(args, "texte", requis=True, maximum=300)
        statut, charge = await demander("PATCH", f"/api/memoire/personne/{ident}", corps={"texte": texte, "par": ctx.acteur})
        if statut != 200:
            raise _refus_wikichat(statut, charge)
        el = element(charge)
        avant = charge.get("avant") if isinstance(charge, dict) else None
        return Effet(
            charge={"element": el},
            objet_id=ident,
            titre="Corrigé",
            resume=texte[:120],
            voir="/?view=memoire",
            avant={"texte": avant},
            apres={"texte": texte},
            inverse_arguments={"id": ident, "texte": avant} if avant else None,
        )

    async def oublier(ctx: Contexte, args: dict[str, Any]) -> Effet:
        ident = _texte(args, "id", requis=True, maximum=80)
        statut, charge = await demander("DELETE", f"/api/memoire/personne/{ident}", params={"par": ctx.acteur})
        if statut != 200:
            raise _refus_wikichat(statut, charge)
        el = element(charge)
        return Effet(
            charge={"oublie": el.get("id")},
            objet_id=ident,
            titre="Oublié",
            resume=str(el.get("texte") or "")[:120],
            voir="/?view=memoire",
            avant=el,
            inverse_arguments={"type": el.get("type"), "texte": el.get("texte"), "source": el.get("source") or {}},
        )

    schema_texte = {"type": "string", "description": "300 caractères au plus."}
    for nom, description, executer, inverse, schema in (
        (RETENIR, "Retenir un élément de la mémoire de la personne (exécutée quand elle accepte une proposition).",
         retenir, OUBLIER,
         {"type": "object", "properties": {"type": {"type": "string", "enum": list(TYPES_RETENUS)},
                                           "texte": schema_texte, "source": {"type": "object"},
                                           "conversation": {"type": "string"}, "projet": {"type": "string"},
                                           "fiche": {"type": "string"}},
          "required": ["type", "texte"]}),
        (CORRIGER, "Corriger le texte d'un élément retenu (« Corriger » dans « Ma mémoire »).",
         corriger, CORRIGER,
         {"type": "object", "properties": {"id": {"type": "string"}, "texte": schema_texte}, "required": ["id", "texte"]}),
        (OUBLIER, "Oublier un élément retenu (« Oublier » dans « Ma mémoire »). Un fait oublié n'est plus réenregistré.",
         oublier, RETENIR,
         {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"]}),
    ):
        catalogue.ajouter(
            Commande(
                nom=nom,
                description=description,
                objet="memoire",
                classe=RESERVEE,
                inverse=inverse,
                regles=["réservée à la personne : un modèle ne retient, ne corrige ni n'oublie jamais seul (A-7)"],
                executer=executer,
                schema=schema,
                exposee_mcp=False,
            )
        )

    app.include_router(construire_le_routeur(app))
    # Résumé direct et vecteurs (décisions du 26/09) : des routes, pas des commandes.
    from mcp_gateway.atelier.memoire_modele import enregistrer_la_memoire_modele

    enregistrer_la_memoire_modele(app)


__all__ = [
    "BUDGET_FICHE_CAR",
    "BUDGET_RAPPEL_CAR",
    "BUDGET_RAPPEL_UNITES",
    "inscrire_la_memoire",
    "mettre_en_forme_le_rappel",
    "unites",
]
