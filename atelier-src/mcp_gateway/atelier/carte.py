"""La carte de l'Atelier : un seul graphe, calculé par du code (transverse §1.3).

Deux couches, un seul point de lecture :

- **la couche projets et connaissance** vient de wikichat, par
  `GET /api/cartographie` (contrat : `docs/cartographie-contrat.md` de
  wikichat) : projets, instantanés, santé, `ETAT.md`, relations, proximités,
  connecteurs partagés ;
- **la couche opérationnelle** est celle de l'Atelier, lue là où elle vit déjà,
  sans double saisie :
  - les projets (`ProjectStore`), leur `.atelier/projet.json` et les
    connecteurs choisis (`.atelier/connecteurs-choisis.json`, sinon le pool) ;
  - les créations et leur état au superviseur (`ServiceApps.lister_tout`) ;
  - les conversations et les tours en cours (fiches et harnais) ;
  - la file « À valider » (commande `atelier_a_valider`, pilote compris) ;
  - les tâches automatiques et les alertes ouvertes, lues à l'API des
    gardiens (`127.0.0.1:8791`, routes `/automates` et `/alertes`).

L'assemblage joint les nœuds par le slug, remplit le champ `atelier` des nœuds
wikichat qui sont des projets de l'Atelier, et ajoute les liens que seul
l'Atelier connaît (`sert`, `travaille_sur`, `utilise`, et les `meme_connecteur`
qui manquent). Si wikichat ne répond pas, la carte reste servie, bâtie sur la
seule couche de l'Atelier, et `sources.wikichat` le dit.

Trois formes : complète (le graphe), synthétique (un texte borné pour le
contexte de l'Assistant, moins de 2 400 unités de modèle estimées à
3,4 caractères chacune) et projet (un projet et son voisinage).

Le calcul est gardé en cache un court délai, et invalidé par le crochet
`apres_commande` du catalogue : une création ou une modification faite par une
commande s'y reflète au calcul suivant.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable

log = logging.getLogger("atelier.carte")

VERSION = 1

FORME_SYNTHETIQUE = "synthetique"
FORME_COMPLETE = "complete"
FORME_PROJET = "projet"
FORMES = (FORME_SYNTHETIQUE, FORME_COMPLETE, FORME_PROJET)

# Le budget de la forme synthétique : 2 400 unités de modèle au plus, estimées
# à 3,4 caractères chacune (`assistant-contexte.md` §3.3). On vise un peu en
# dessous, pour que l'estimation n'effleure jamais le plafond.
CARACTERES_PAR_UNITE = 3.4
PLAFOND_UNITES = 2400
BUDGET_SYNTHETIQUE = 8000

# Un projet est actif s'il a bougé depuis ce délai, ou s'il a une conversation
# en cours, une création en marche, une alerte ou une proposition.
ACTIF_JOURS = 14

DELAI_CACHE_S = 20.0
DELAI_HTTP_S = 5.0

PORT_GARDIENS = 8791
PROJETS_SYSTEME = frozenset({"atelier", "atelier-gardiens"})

# Les états d'une création serveur qui occupent une place (superviseur).
CREATION_EN_MARCHE = frozenset({"demarrage", "pret", "redemarrage"})
CREATION_EN_ECHEC = frozenset({"en_echec", "invalide"})

# Un connecteur présent partout relierait chaque projet à tous les autres : il
# ne crée pas de lien (même règle que wikichat, contrat §4.3).
CONNECTEURS_COMMUNS = frozenset({"wikichat", "atelier"})

TEXTE_COURT = 120


# ── Petits outils ────────────────────────────────────────────────────────


def maintenant_iso(instant: float | None = None) -> str:
    quand = datetime.fromtimestamp(instant if instant is not None else time.time(), tz=timezone.utc)
    return quand.isoformat(timespec="seconds")


def instant(texte: Any) -> float | None:
    """Un horodatage ISO 8601 en secondes ; None s'il est absent ou illisible."""
    if not isinstance(texte, str) or not texte.strip():
        return None
    brut = texte.strip().replace("Z", "+00:00")
    try:
        quand = datetime.fromisoformat(brut)
    except ValueError:
        return None
    if quand.tzinfo is None:
        quand = quand.replace(tzinfo=timezone.utc)
    return quand.timestamp()


def age(secondes: float) -> str:
    if secondes < 3600:
        return "< 1 h"
    if secondes < 86400:
        return f"{int(secondes // 3600)} h"
    if secondes < 14 * 86400:
        return f"{int(secondes // 86400)} j"
    return f"{int(secondes // (7 * 86400))} sem."


def unites_estimees(texte: str) -> int:
    """Estimation de la taille pour le modèle : caractères / 3,4, arrondi au-dessus."""
    return int(-(-len(texte) // CARACTERES_PAR_UNITE))


def _court(valeur: Any, maximum: int = TEXTE_COURT) -> str | None:
    if valeur is None:
        return None
    texte = " ".join(str(valeur).split())
    return texte if len(texte) <= maximum else texte[: maximum - 1] + "…"


def adresse_des_gardiens() -> str:
    """L'API de lecture des gardiens, en boucle locale (`ATELIER_GARDIENS_PORT`)."""
    brut = os.environ.get("ATELIER_GARDIENS_URL", "").strip().rstrip("/")
    if brut:
        return brut
    port = os.environ.get("ATELIER_GARDIENS_PORT", "").strip() or str(PORT_GARDIENS)
    return f"http://127.0.0.1:{port}"


class Absent(Exception):
    """La source ne répond pas (refus de connexion, délai) : ce n'est pas une erreur de sa part."""


async def lire_json(url: str, delai_s: float = DELAI_HTTP_S) -> Any:
    """GET en JSON. `Absent` si personne ne répond, `ValueError` si la réponse est mauvaise."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=delai_s) as client:
            reponse = await client.get(url)
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise Absent(type(exc).__name__) from None
    except httpx.TransportError as exc:
        raise Absent(type(exc).__name__) from None
    if reponse.status_code != 200:
        raise ValueError(f"HTTP {reponse.status_code}")
    try:
        return reponse.json()
    except ValueError:
        raise ValueError("réponse non JSON") from None


# ── La couche de l'Atelier : lecteurs ────────────────────────────────────


def connecteurs_choisis(chemin: Path) -> dict[str, Any]:
    """Ce que le projet a choisi dans le pool ; `herite_du_pool` s'il n'a rien choisi."""
    from mcp_gateway.atelier import mcp_sync

    if mcp_sync.herite_du_pool(chemin):
        return {"herite_du_pool": True, "choisis": []}
    binding = mcp_sync._binding_du_dossier(chemin)
    if binding is None:
        return {"herite_du_pool": True, "choisis": []}
    selection = mcp_sync._binding_selection(binding)
    return {
        "herite_du_pool": False,
        "choisis": sorted(n for n, actif in selection.items() if actif and n != mcp_sync.SERVICE_ATELIER),
    }


def structure_du_projet(chemin: Path) -> dict[str, Any]:
    """Ce que `.atelier/projet.json` déclare, sans jamais lever."""
    from mcp_gateway.atelier.commandes import structure

    try:
        declaration = structure.lire(chemin)
    except structure.ErreurProjetJson:
        return {"projet_json": "invalide", "gabarit": None, "deploiement": None, "vues_epinglees": 0,
                "description": None}
    if declaration is None:
        return {"projet_json": "absent", "gabarit": None, "deploiement": None, "vues_epinglees": 0,
                "description": None}
    deploiement = None
    if declaration.deploiement is not None:
        d = declaration.deploiement
        deploiement = {"pod": d.pod, "service": d.service, "gpu": d.gpu}
    return {
        "projet_json": "valide",
        "gabarit": declaration.gabarit.nom if declaration.gabarit else None,
        "deploiement": deploiement,
        "vues_epinglees": len(declaration.vues_epinglees),
        "description": declaration.description or None,
    }


def lire_projets(projects: Any) -> list[dict[str, Any]]:
    """Les projets de l'Atelier, rangés compris, avec leur fiche et leurs connecteurs."""
    sortie: list[dict[str, Any]] = []
    for p in projects.list_projects(include_archived=True):
        chemin = Path(p.path)
        sortie.append(
            {
                "slug": p.slug,
                "titre": p.title,
                "kind": p.kind,
                "range": bool(p.archived),
                "chemin": str(chemin),
                "cree_le": p.created_at or None,
                "maj": p.updated_at or None,
                "structure": structure_du_projet(chemin),
                "connecteurs": connecteurs_choisis(chemin),
            }
        )
    return sortie


def lire_pool(settings: Any) -> list[str]:
    """Les noms des connecteurs activés du pool. Rien d'autre : leurs réglages portent des secrets."""
    from mcp_gateway.atelier.mcp_sync import SERVICE_ATELIER, _pool_enabled

    return sorted(n for n in _pool_enabled(settings) if n != SERVICE_ATELIER)


def lire_creations(apps: Any) -> list[dict[str, Any]]:
    if apps is None:
        return []
    return [
        {
            "projet": f.get("slug"),
            "nom": f.get("nom"),
            "titre": f.get("titre") or f.get("nom"),
            "mode": f.get("mode"),
            "etat": f.get("etat"),
        }
        for f in apps.lister_tout()
    ]


def lire_conversations(store: Any, harness: Any = None) -> list[dict[str, Any]]:
    """Les conversations non rangées ; `en_cours` quand un tour tourne."""
    sortie: list[dict[str, Any]] = []
    for rec in store.list_sessions(include_archived=False):
        en_cours = rec.state == "running"
        if harness is not None:
            try:
                en_cours = en_cours or bool(harness.tour_en_cours(rec.session_id))
            except Exception:  # noqa: BLE001 — l'état de la fiche suffit
                pass
        sortie.append(
            {
                "id": rec.session_id,
                "projet": rec.slug,
                "kind": rec.kind,
                "titre": rec.title or None,
                "etat": rec.state,
                "en_cours": en_cours,
                "maj": rec.updated_at or rec.created_at or None,
                "tours": rec.turns,
            }
        )
    return sortie


# ── Sources et couche ────────────────────────────────────────────────────


@dataclass
class Sources:
    """D'où la carte lit. Chaque lecteur est remplaçable (tests, mesure hors service)."""

    projets: Callable[[], list[dict[str, Any]]]
    pool: Callable[[], list[str]]
    creations: Callable[[], list[dict[str, Any]]]
    conversations: Callable[[], list[dict[str, Any]]]
    # Asynchrones : elles passent par HTTP ou par le catalogue.
    wikichat: Callable[[], Awaitable[Any]] | None = None
    gardiens_alertes: Callable[[], Awaitable[Any]] | None = None
    gardiens_automates: Callable[[], Awaitable[Any]] | None = None
    a_valider: Callable[[], Awaitable[Any]] | None = None
    # Retire les secrets connus d'une valeur (le filtre du journal unique).
    filtre: Callable[[Any], Any] | None = None
    assistant: str = ""
    systeme: frozenset[str] = PROJETS_SYSTEME


def sources_http(wikichat_origine: str, gardiens_origine: str | None = None) -> dict[str, Callable[[], Awaitable[Any]]]:
    """Les lecteurs HTTP réels : wikichat (`/api/cartographie`) et les gardiens."""
    gardiens = (gardiens_origine or adresse_des_gardiens()).rstrip("/")
    origine = wikichat_origine.rstrip("/")

    async def wikichat() -> Any:
        return await lire_json(f"{origine}/api/cartographie")

    async def alertes() -> Any:
        return await lire_json(f"{gardiens}/alertes")

    async def automates() -> Any:
        return await lire_json(f"{gardiens}/automates")

    return {"wikichat": wikichat, "gardiens_alertes": alertes, "gardiens_automates": automates}


@dataclass
class Couche:
    """Ce que l'Atelier sait, lu en une fois ; `etats` dit ce qui a manqué."""

    projets: list[dict[str, Any]] = field(default_factory=list)
    pool: list[str] = field(default_factory=list)
    creations: list[dict[str, Any]] = field(default_factory=list)
    conversations: list[dict[str, Any]] = field(default_factory=list)
    automates: list[dict[str, Any]] | None = None
    alertes: list[dict[str, Any]] | None = None
    a_valider: list[dict[str, Any]] | None = None
    etats: dict[str, dict[str, Any]] = field(default_factory=dict)


def _etat_ok(**extra: Any) -> dict[str, Any]:
    return {"etat": "ok", **extra}


def _etat_de(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, Absent):
        return {"etat": "absent", "detail": f"ne répond pas ({exc})"}
    return {"etat": "erreur", "detail": _court(f"{type(exc).__name__}: {exc}", 200)}


def contrat_wikichat_valide(graphe: Any) -> None:
    """Lève `ValueError` si la réponse ne suit pas le contrat `version: 1`."""
    if not isinstance(graphe, dict):
        raise ValueError("cartographie : un objet attendu")
    if graphe.get("version") != 1:
        raise ValueError(f"cartographie : version {graphe.get('version')!r} inconnue (1 attendue)")
    if not isinstance(graphe.get("noeuds"), list) or not isinstance(graphe.get("aretes"), list):
        raise ValueError("cartographie : noeuds et aretes attendus")


# ── Assemblage ───────────────────────────────────────────────────────────

_CHAMPS_NOEUD_WIKICHAT: dict[str, Any] = {
    "nom": None, "titre": None, "description": None, "chemin": None, "origine": ["atelier"],
    "statut": "atelier", "cycle_de_vie": None, "but": None, "axes": [], "pile": [], "github": None,
    "instantane": None, "sante": None, "etat": None, "decisions": 0, "cloture": None,
    "connecteurs": None, "atelier": None,
}


def _noeud_projet_neuf(projet: dict[str, Any]) -> dict[str, Any]:
    """Un projet que wikichat ne donne pas : les champs de son contrat, vides."""
    noeud: dict[str, Any] = {"id": projet["slug"], "type": "projet"}
    for cle, defaut in _CHAMPS_NOEUD_WIKICHAT.items():
        noeud[cle] = list(defaut) if isinstance(defaut, list) else defaut
    noeud["nom"] = projet["slug"]
    noeud["chemin"] = projet.get("chemin")
    noeud["description"] = (projet.get("structure") or {}).get("description")
    return noeud


def _arete_projets(a: dict[str, Any]) -> bool:
    return a.get("type") in ("relation", "proximite", "meme_connecteur")


def _vise(alerte: dict[str, Any], projets: set[str], automates: set[str]) -> str | None:
    """L'objet de la carte qu'une alerte vise, quand on sait le dire."""
    objet = str(alerte.get("objet") or "")
    if f"automate:{objet}" in automates:
        return f"automate:{objet}"
    texte = f"{objet} {alerte.get('preuve') or ''}"
    trouve = re.search(r"/projects/([a-z0-9][a-z0-9._-]*)", texte)
    if trouve and trouve.group(1) in projets:
        return trouve.group(1)
    tete = objet.split("/", 1)[0]
    if tete in projets:
        return tete
    return None


def assembler(
    couche: Couche,
    wikichat: dict[str, Any] | None,
    *,
    maintenant_s: float | None = None,
    assistant: str = "",
    systeme: Iterable[str] = PROJETS_SYSTEME,
) -> dict[str, Any]:
    """La carte complète : la couche wikichat (si elle est là) et celle de l'Atelier."""
    maintenant_s = maintenant_s if maintenant_s is not None else time.time()
    systeme = set(systeme) | ({assistant} if assistant else set())
    seuil_actif = maintenant_s - ACTIF_JOURS * 86400

    # 1. Les projets : wikichat d'abord, dans son ordre ; l'Atelier joint par le slug.
    noeuds_projets: dict[str, dict[str, Any]] = {}
    if wikichat:
        for brut in wikichat.get("noeuds") or []:
            if not isinstance(brut, dict) or not brut.get("id"):
                continue
            noeud = dict(brut)
            noeud["type"] = "projet"
            noeud.setdefault("atelier", None)
            noeuds_projets[str(noeud["id"])] = noeud
    aretes: list[dict[str, Any]] = [dict(a) for a in (wikichat or {}).get("aretes") or [] if isinstance(a, dict)]
    ids_aretes = {a.get("id") for a in aretes}

    slugs_atelier = {p["slug"] for p in couche.projets}
    par_slug = {p["slug"]: p for p in couche.projets}
    for projet in couche.projets:
        if projet["slug"] not in noeuds_projets:
            noeuds_projets[projet["slug"]] = _noeud_projet_neuf(projet)

    # 2. Créations, conversations, connecteurs, automates : leurs nœuds et leurs liens.
    noeuds: list[dict[str, Any]] = []
    par_projet_creations: dict[str, list[dict[str, Any]]] = {}
    for c in couche.creations:
        ident = f"creation:{c['projet']}/{c['nom']}"
        noeuds.append({**c, "id": ident, "type": "creation"})
        par_projet_creations.setdefault(str(c["projet"]), []).append(c)
        if c["projet"] in noeuds_projets:
            aretes.append({"id": f"sert:{c['projet']}/{c['nom']}", "type": "sert", "de": ident,
                           "vers": c["projet"], "oriente": True, "source": "artifacts"})

    par_projet_conversations: dict[str, list[dict[str, Any]]] = {}
    for conv in couche.conversations:
        ident = f"conversation:{conv['id']}"
        noeuds.append({**{k: v for k, v in conv.items() if k != "id"}, "id": ident, "type": "conversation",
                       "session_id": conv["id"]})
        par_projet_conversations.setdefault(str(conv["projet"]), []).append(conv)
        if conv["projet"] in noeuds_projets:
            aretes.append({"id": f"travaille_sur:{conv['id']}", "type": "travaille_sur", "de": ident,
                           "vers": conv["projet"], "oriente": True, "source": "fiches"})

    pool = set(couche.pool)
    effectifs: dict[str, set[str]] = {}
    for projet in couche.projets:
        choix = projet.get("connecteurs") or {}
        noms = set(pool) if choix.get("herite_du_pool") else set(choix.get("choisis") or [])
        effectifs[projet["slug"]] = noms
    connus = sorted(pool.union(*effectifs.values()))
    for nom in connus:
        utilisateurs = sorted(s for s, n in effectifs.items() if nom in n)
        noeuds.append({"id": f"connecteur:{nom}", "type": "connecteur", "nom": nom, "au_pool": nom in pool,
                       "projets": len(utilisateurs)})
        for slug in utilisateurs:
            herite = bool((par_slug[slug].get("connecteurs") or {}).get("herite_du_pool"))
            aretes.append({"id": f"utilise:{slug}>{nom}", "type": "utilise", "de": slug,
                           "vers": f"connecteur:{nom}", "oriente": True,
                           "source": "pool" if herite else "connecteurs-choisis"})

    # Connecteurs partagés : seulement ceux que les deux projets ont CHOISIS
    # (`connecteurs.choisis`). Hériter du pool n'est pas un choix : tous les
    # projets qui en héritent partagent le pool entier (blender, github,
    # gitlab, llm, qgis sur le pod), et la carte se couvrait de liens qui ne
    # disaient rien (181 arêtes au 26/09). wikichat lit `.mcp.json`, où
    # l'héritage ne se distingue pas d'un choix : ses liens entre deux projets
    # de l'Atelier sont donc recalculés ici, et retirés s'il ne reste rien.
    communs = set(CONNECTEURS_COMMUNS) | set(((wikichat or {}).get("limites") or {}).get("connecteurs_communs") or [])
    actifs_pour_liens = {
        s: set((par_slug[s].get("connecteurs") or {}).get("choisis") or [])
        for s in effectifs
        if not (par_slug[s].get("connecteurs") or {}).get("herite_du_pool") and not par_slug[s].get("range")
    }
    actifs_pour_liens = {s: n for s, n in actifs_pour_liens.items() if n}
    if len(actifs_pour_liens) > 4:
        compte: dict[str, int] = {}
        for noms in actifs_pour_liens.values():
            for n in noms:
                compte[n] = compte.get(n, 0) + 1
        communs |= {n for n, k in compte.items() if k > len(actifs_pour_liens) / 2}
    def _partages(a: str, b: str) -> list[str]:
        return sorted((actifs_pour_liens.get(a, set()) & actifs_pour_liens.get(b, set())) - communs)

    # Un lien de wikichat dont un bout est un projet de l'Atelier ne garde que
    # ce que ce projet a choisi ; entre deux projets de l'Atelier, il est
    # recalculé. Un dossier que l'Atelier ne connaît pas garde son `.mcp.json`.
    gardees: list[dict[str, Any]] = []
    for arete in aretes:
        bouts = [str(arete.get("de")), str(arete.get("vers"))]
        du_nous = [b for b in bouts if b in slugs_atelier]
        if arete.get("type") != "meme_connecteur" or not du_nous:
            gardees.append(arete)
            continue
        if len(du_nous) == 2:
            partages = _partages(*bouts)
        else:
            partages = sorted(
                set(arete.get("connecteurs") or []) & actifs_pour_liens.get(du_nous[0], set()) - communs
            )
        if not partages:
            ids_aretes.discard(arete.get("id"))
            continue
        arete["connecteurs"] = partages
        gardees.append(arete)
    aretes[:] = gardees
    slugs_tries = sorted(actifs_pour_liens)
    for i, a in enumerate(slugs_tries):
        for b in slugs_tries[i + 1:]:
            partages = _partages(a, b)
            ident = f"meme_connecteur:{a}~{b}"
            if partages and ident not in ids_aretes:
                aretes.append({"id": ident, "type": "meme_connecteur", "de": a, "vers": b, "oriente": False,
                               "connecteurs": partages, "source": "atelier"})
                ids_aretes.add(ident)

    automates_ids: set[str] = set()
    for au in couche.automates or []:
        ident = f"automate:{au.get('id')}"
        automates_ids.add(ident)
        noeuds.append(
            {
                "id": ident,
                "type": "automate",
                "genre": au.get("genre"),
                "etat": au.get("etat"),
                "titre": _court(au.get("titre"), 80),
                "proprietaire": au.get("proprietaire"),
                "budget": bool(au.get("budget")),
                "plafond_par_jour": au.get("plafond_par_jour"),
                "lancements": au.get("lancements"),
                "derniere": au.get("derniere"),
                "prochaine": au.get("prochaine"),
            }
        )

    # 3. État : alertes ouvertes et propositions en attente, rattachées à leur objet.
    alertes: list[dict[str, Any]] = []
    for al in couche.alertes or []:
        if not isinstance(al, dict):
            continue
        alertes.append(
            {
                "empreinte": al.get("empreinte"),
                "gardien": al.get("gardien"),
                "controle": al.get("controle"),
                "niveau": al.get("niveau"),
                "objet": _court(al.get("objet"), 80),
                "resume": _court(al.get("resume"), 160),
                "depuis": al.get("depuis"),
                "compte": al.get("compte"),
                "vise": _vise(al, slugs_atelier, automates_ids),
            }
        )
    a_valider = [
        {
            "id": p.get("id"),
            "source": p.get("source"),
            "titre": _court(p.get("titre"), 120),
            "projet": p.get("projet") or None,
            "creee_le": p.get("creee_le") or None,
        }
        for p in couche.a_valider or []
        if isinstance(p, dict)
    ]

    # 4. Le champ `atelier` de chaque projet de l'Atelier.
    for projet in couche.projets:
        slug = projet["slug"]
        noeud = noeuds_projets[slug]
        creations = par_projet_creations.get(slug, [])
        conversations = par_projet_conversations.get(slug, [])
        instants = [instant(c.get("maj")) for c in conversations]
        instants.append(instant(projet.get("maj")))
        instants.append(instant(projet.get("cree_le")))
        inst = noeud.get("instantane") or {}
        instants.append(instant(((inst.get("dernier_commit") or {}).get("date"))))
        instants.append(instant((noeud.get("etat") or {}).get("modifie")))
        derniere = max((t for t in instants if t is not None), default=None)
        en_cours = sum(1 for c in conversations if c.get("en_cours"))
        en_marche = sum(1 for c in creations if c.get("etat") in CREATION_EN_MARCHE)
        n_alertes = sum(1 for a in alertes if a["vise"] == slug)
        n_a_valider = sum(1 for p in a_valider if p["projet"] == slug)
        actif = not projet.get("range") and (
            (derniere is not None and derniere >= seuil_actif) or en_cours > 0 or en_marche > 0
            or n_alertes > 0 or n_a_valider > 0
        )
        noeud["atelier"] = {
            "type": projet.get("kind"),
            "titre": projet.get("titre"),
            "systeme": slug in systeme,
            "range": bool(projet.get("range")),
            **{k: v for k, v in (projet.get("structure") or {}).items() if k != "description"},
            "connecteurs": projet.get("connecteurs") or {"herite_du_pool": True, "choisis": []},
            "creations": {
                "total": len(creations),
                "en_marche": en_marche,
                "en_echec": sum(1 for c in creations if c.get("etat") in CREATION_EN_ECHEC),
            },
            "conversations": {"total": len(conversations), "en_cours": en_cours,
                              "derniere": max((c.get("maj") or "" for c in conversations), default="") or None},
            "a_valider": n_a_valider,
            "alertes": n_alertes,
            "derniere_activite": maintenant_iso(derniere) if derniere is not None else None,
            "actif": actif,
        }

    projets_atelier = [noeuds_projets[p["slug"]] for p in couche.projets]
    non_ranges = [n for n in projets_atelier if not n["atelier"]["range"]]
    par_etat_automates: dict[str, int] = {}
    for au in couche.automates or []:
        par_etat_automates[str(au.get("etat"))] = par_etat_automates.get(str(au.get("etat")), 0) + 1
    par_niveau: dict[str, int] = {}
    for a in alertes:
        par_niveau[str(a["niveau"])] = par_niveau.get(str(a["niveau"]), 0) + 1

    resume = {
        "projets": len(non_ranges),
        "projets_actifs": sum(1 for n in non_ranges if n["atelier"]["actif"]),
        "projets_ranges": len(projets_atelier) - len(non_ranges),
        "hors_atelier": len([i for i in noeuds_projets if i not in slugs_atelier]),
        "connecteurs": len(pool),
        "creations": len(couche.creations),
        "creations_en_marche": sum(1 for c in couche.creations if c.get("etat") in CREATION_EN_MARCHE),
        "conversations": len(couche.conversations),
        "conversations_en_cours": sum(1 for c in couche.conversations if c.get("en_cours")),
        "automates": par_etat_automates if couche.automates is not None else None,
        "alertes": par_niveau if couche.alertes is not None else None,
        "a_valider": len(a_valider) if couche.a_valider is not None else None,
    }

    return {
        "version": VERSION,
        "calcule_le": maintenant_iso(maintenant_s),
        "sources": dict(couche.etats),
        "resume": resume,
        "noeuds": list(noeuds_projets.values()) + noeuds,
        "aretes": aretes,
        "groupes": list((wikichat or {}).get("groupes") or []),
        "alertes": alertes,
        "a_valider": a_valider,
        "limites": dict((wikichat or {}).get("limites") or {}),
    }


# ── Formes ───────────────────────────────────────────────────────────────


def _projets(carte: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in carte["noeuds"] if n.get("type") == "projet"]


def _voisins(carte: dict[str, Any], slug: str) -> list[tuple[str, str, float]]:
    """Les projets liés à `slug` : (autre, type, poids), du lien le plus fort au plus faible."""
    ordre = {"relation": 0, "proximite": 1, "meme_connecteur": 2}
    sortie = []
    for a in carte["aretes"]:
        if not _arete_projets(a) or slug not in (a.get("de"), a.get("vers")):
            continue
        autre = a["vers"] if a["de"] == slug else a["de"]
        poids = float(a.get("poids") or 0.0)
        sortie.append((ordre.get(a["type"], 9), -poids, autre, a["type"], a))
    sortie.sort(key=lambda x: (x[0], x[1], x[2]))
    vus: set[str] = set()
    uniques: list[tuple[str, str, float]] = []
    for _, poids, autre, genre, _a in sortie:
        if autre in vus:
            continue
        vus.add(autre)
        uniques.append((autre, genre, -poids))
    return uniques


_LIBELLES_LIENS = {"relation": "relation", "proximite": "proche", "meme_connecteur": "connecteur"}


def _date_courte(texte: str) -> str:
    t = instant(texte)
    if t is None:
        return "?"
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%d/%m %H:%M")


def _ligne_projet(n: dict[str, Any], carte: dict[str, Any], maintenant_s: float, *, wikichat: bool = True) -> str:
    at = n["atelier"]
    slug = n["id"]
    titre = n.get("titre") or at.get("titre")
    morceaux = [f"- {slug}"]
    if titre and titre.strip().lower() != slug.replace("-", " ").lower() and titre != slug:
        morceaux[0] += f" « {_court(titre, 40)} »"
    if at.get("systeme"):
        morceaux[0] += " [système]"
    derniere = instant(at.get("derniere_activite"))
    morceaux.append(age(maintenant_s - derniere) if derniere else "jamais")
    conv = at["conversations"]
    if conv["total"]:
        morceaux.append(f"{conv['total']} conv." + (f" ({conv['en_cours']} en cours)" if conv["en_cours"] else ""))
    cr = at["creations"]
    if cr["total"]:
        detail = []
        if cr["en_marche"]:
            detail.append(f"{cr['en_marche']} en marche")
        if cr["en_echec"]:
            detail.append(f"{cr['en_echec']} en échec")
        pluriel = "s" if cr["total"] > 1 else ""
        morceaux.append(f"{cr['total']} création{pluriel}" + (f" ({', '.join(detail)})" if detail else ""))
    choix = at["connecteurs"]
    if choix.get("herite_du_pool"):
        morceaux.append("connecteurs : tous")
    elif choix.get("choisis"):
        noms = choix["choisis"]
        morceaux.append("connecteurs : " + ", ".join(noms[:4]) + (f" +{len(noms) - 4}" if len(noms) > 4 else ""))
    else:
        morceaux.append("aucun connecteur")
    etat = n.get("etat")
    if etat:
        morceaux.append(f"ETAT.md : {etat.get('a_decider', 0)} à décider")
    elif wikichat and not at.get("systeme"):
        # Sans wikichat, on ne sait pas : on ne dit rien plutôt que le faux.
        morceaux.append("sans ETAT.md")
    if at.get("deploiement"):
        d = at["deploiement"]
        morceaux.append(f"déployé sur {d.get('pod') or d.get('service')}")
    if at["alertes"]:
        morceaux.append(f"{at['alertes']} alerte" + ("s" if at["alertes"] > 1 else ""))
    if at["a_valider"]:
        morceaux.append(f"{at['a_valider']} à valider")
    sante = n.get("sante")
    if sante and isinstance(sante.get("score"), (int, float)) and sante["score"] < 50:
        morceaux.append(f"santé {sante['score']}")
    # Dans la vue courte, une proximité vers un dossier qui n'est pas un projet de
    # l'Atelier (dossier parent, dossier de travail) n'aide pas ; une relation
    # déclarée, si.
    projets_atelier = {m["id"] for m in _projets(carte) if m.get("atelier")}
    voisins = [v for v in _voisins(carte, slug) if v[1] == "relation" or v[0] in projets_atelier]
    if voisins:
        noms = [f"{autre} ({_LIBELLES_LIENS.get(g, g)})" if g == "relation" else autre for autre, g, _ in voisins[:3]]
        morceaux.append("liens : " + ", ".join(noms) + (f" +{len(voisins) - 3}" if len(voisins) > 3 else ""))
    return " | ".join(morceaux)


def _liste(noms: list[str], maximum: int) -> str:
    if len(noms) <= maximum:
        return ", ".join(noms)
    return ", ".join(noms[:maximum]) + f"… (+{len(noms) - maximum})"


def vue_synthetique(
    carte: dict[str, Any], *, budget: int = BUDGET_SYNTHETIQUE, maintenant_s: float | None = None
) -> str:
    """Le texte que l'Assistant garde en contexte : une ligne par projet actif, le reste en décompte.

    Au-delà du budget, les projets actifs les moins récents se replient en
    dormants, puis les listes de noms raccourcissent ; le texte ne dépasse
    jamais `budget` caractères.
    """
    maintenant_s = maintenant_s if maintenant_s is not None else time.time()
    r = carte["resume"]
    sources = carte.get("sources") or {}
    projets = [n for n in _projets(carte) if n.get("atelier")]
    non_ranges = [n for n in projets if not n["atelier"]["range"]]
    actifs = sorted(
        (n for n in non_ranges if n["atelier"]["actif"]),
        key=lambda n: instant(n["atelier"].get("derniere_activite")) or 0.0,
        reverse=True,
    )
    dormants_de_base = sorted(n["id"] for n in non_ranges if not n["atelier"]["actif"])
    hors = sorted(n["id"] for n in _projets(carte) if not n.get("atelier"))

    tete = [
        f"Atelier — {r['projets']} projets ({r['projets_actifs']} actif{'s' if r['projets_actifs'] > 1 else ''} "
        f"sur {ACTIF_JOURS} j"
        + (f", {r['projets_ranges']} rangés" if r["projets_ranges"] else "")
        + f"), {r['connecteurs']} connecteurs, {r['creations']} créations ({r['creations_en_marche']} en marche), "
        f"{r['conversations']} conversations ({r['conversations_en_cours']} en cours)."
    ]
    etat_lignes = []
    if r["automates"] is None:
        etat_lignes.append("Tâches automatiques : inconnues (gardiens absents).")
    else:
        a = r["automates"]
        etat_lignes.append(
            f"Tâches automatiques : {a.get('actif', 0)} actives, {a.get('sans_declaration', 0)} sans budget "
            f"ni déclaration, {a.get('coupe', 0)} coupées."
        )
    alertes_txt = (
        "inconnues (gardiens absents)" if r["alertes"] is None
        else f"{r['alertes'].get('alerte', 0)} graves, {r['alertes'].get('attention', 0)} à surveiller"
    )
    valider_txt = "inconnu" if r["a_valider"] is None else str(r["a_valider"])
    etat_lignes.append(f"Alertes : {alertes_txt}. À valider : {valider_txt}.")
    wk = sources.get("wikichat") or {}
    couche = (
        "à jour" if wk.get("etat") == "ok"
        else "absente, wikichat ne répond pas : ni liens entre projets, ni ETAT.md, ni santé"
        if wk.get("etat") == "absent"
        else f"en erreur ({wk.get('detail') or '?'})"
    )
    etat_lignes.append(f"Carte du {_date_courte(carte['calcule_le'])} UTC. Couche projets (wikichat) : {couche}.")

    lignes_actifs = [_ligne_projet(n, carte, maintenant_s, wikichat=wk.get("etat") == "ok") for n in actifs]

    def queue(max_noms: int, replies: list[str]) -> list[str]:
        sortie: list[str] = []
        dormants = sorted(dormants_de_base + replies)
        if dormants:
            sortie.append(
                f"Dormants ({len(dormants)}) : {_liste(dormants, max_noms)}. "
                "Détail d'un projet : atelier_carte avec forme=projet."
            )
        if hors:
            sortie.append(f"Autres dossiers connus de wikichat ({len(hors)}) : {_liste(hors, min(max_noms, 8))}.")
        sans = [n for n in carte["noeuds"] if n.get("type") == "automate" and n.get("etat") == "sans_declaration"
                and n.get("genre") in ("trigger", "routine")]
        if sans:
            noms = [str(n["id"]).rsplit(".", 1)[-1] for n in sans]
            sortie.append(f"Tâches wikichat sans budget : {_liste(noms, max_noms)}.")
        graves = [a for a in carte["alertes"] if a.get("niveau") == "alerte"]
        for a in graves[:5]:
            sortie.append(f"Alerte [{a.get('gardien')}] {a.get('objet')} : {a.get('resume')}")
        if len(graves) > 5:
            sortie.append(f"… et {len(graves) - 5} autres alertes graves.")
        autres = [a for a in carte["alertes"] if a.get("niveau") != "alerte"]
        if autres:
            par_gardien: dict[str, int] = {}
            for a in autres:
                par_gardien[str(a.get("gardien"))] = par_gardien.get(str(a.get("gardien")), 0) + 1
            detail = ", ".join(f"{g} {k}" for g, k in sorted(par_gardien.items(), key=lambda x: -x[1]))
            sortie.append(f"À surveiller ({len(autres)}) : {detail}.")
        propositions = carte["a_valider"]
        if propositions:
            titres = [_court(p.get("titre"), 60) or "?" for p in propositions]
            sortie.append(f"À valider ({len(propositions)}) : " + " ; ".join(titres[: min(5, max_noms)])
                          + (" ; …" if len(titres) > min(5, max_noms) else ""))
        return sortie

    def rendre(n_actifs: int, max_noms: int) -> str:
        replies = [n["id"] for n in actifs[n_actifs:]]
        corps = list(tete) + etat_lignes
        if n_actifs:
            corps.append("Projets actifs :")
            corps += lignes_actifs[:n_actifs]
        corps += queue(max_noms, replies)
        return "\n".join(corps)

    for max_noms in (40, 12, 4):
        for n_actifs in range(len(actifs), -1, -1):
            texte = rendre(n_actifs, max_noms)
            if len(texte) <= budget:
                return texte
    texte = rendre(0, 2)
    return texte if len(texte) <= budget else texte[: budget - 10] + "\n(coupé)"


def vue_projet(carte: dict[str, Any], slug: str, *, conversations_max: int = 5, liens_max: int = 12) -> dict[str, Any]:
    """Un projet et son voisinage, borné. `KeyError` s'il n'est pas sur la carte."""
    noeud = next((n for n in _projets(carte) if n["id"] == slug), None)
    if noeud is None:
        raise KeyError(slug)
    creations = [n for n in carte["noeuds"] if n.get("type") == "creation" and n.get("projet") == slug]
    conversations = sorted(
        (n for n in carte["noeuds"] if n.get("type") == "conversation" and n.get("projet") == slug),
        key=lambda n: n.get("maj") or "",
        reverse=True,
    )
    liens = []
    for autre, genre, poids in _voisins(carte, slug)[:liens_max]:
        lien: dict[str, Any] = {"projet": autre, "type": genre}
        if poids:
            lien["poids"] = poids
        for a in carte["aretes"]:
            if a.get("type") == genre and {a.get("de"), a.get("vers")} == {slug, autre}:
                if genre == "relation":
                    lien["sous_type"] = a.get("sous_type")
                    lien["sens"] = "vers" if a.get("de") == slug else "depuis"
                if genre == "meme_connecteur":
                    lien["connecteurs"] = a.get("connecteurs")
                break
        liens.append(lien)
    noeud_court = {k: v for k, v in noeud.items() if k not in ("connecteurs",)}
    return {
        "forme": FORME_PROJET,
        "projet": slug,
        "calcule_le": carte["calcule_le"],
        "sources": carte.get("sources"),
        "noeud": noeud_court,
        "creations": [{k: c.get(k) for k in ("nom", "titre", "mode", "etat")} for c in creations],
        "conversations": [
            {k: c.get(k) for k in ("session_id", "titre", "etat", "en_cours", "maj")} for c in conversations[:conversations_max]
        ],
        "conversations_non_montrees": max(0, len(conversations) - conversations_max),
        "liens": liens,
        "alertes": [a for a in carte["alertes"] if a.get("vise") == slug],
        "a_valider": [p for p in carte["a_valider"] if p.get("projet") == slug],
    }


# ── Le calcul, gardé un court délai ──────────────────────────────────────


class Carte:
    """Calcule la carte à la demande, la garde `delai_s`, l'oublie à chaque commande qui agit."""

    def __init__(
        self,
        sources: Sources,
        *,
        delai_s: float = DELAI_CACHE_S,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sources = sources
        self.delai_s = delai_s
        self.horloge = horloge
        self.calculs = 0
        self.derniere_invalidation: str = ""
        self._generation = 0
        self._cache: dict[str, Any] | None = None
        self._cache_instant = 0.0
        self._cache_generation = -1
        self._verrous: dict[int, asyncio.Lock] = {}

    def invalider(self, raison: str = "") -> None:
        """La prochaine lecture recalcule. Appelé par le crochet `apres_commande`."""
        self._generation += 1
        self.derniere_invalidation = raison

    def _verrou(self) -> asyncio.Lock:
        # Un verrou par boucle : la suite de tests en crée plusieurs.
        boucle = id(asyncio.get_running_loop())
        verrou = self._verrous.get(boucle)
        if verrou is None:
            self._verrous = {boucle: asyncio.Lock()}
            verrou = self._verrous[boucle]
        return verrou

    def _frais(self) -> bool:
        return (
            self._cache is not None
            and self._cache_generation == self._generation
            and self.horloge() - self._cache_instant < self.delai_s
        )

    async def obtenir(self, *, rafraichir: bool = False) -> dict[str, Any]:
        if not rafraichir and self._frais():
            return self._cache  # type: ignore[return-value]
        async with self._verrou():
            if not rafraichir and self._frais():
                return self._cache  # type: ignore[return-value]
            generation = self._generation
            carte = await self.calculer()
            self._cache = carte
            self._cache_instant = self.horloge()
            self._cache_generation = generation
            self.calculs += 1
            return carte

    def _couche_locale(self) -> Couche:
        couche = Couche()
        s = self.sources
        notes: dict[str, str] = {}
        for nom, lecteur in (("projets", s.projets), ("pool", s.pool), ("creations", s.creations),
                             ("conversations", s.conversations)):
            try:
                setattr(couche, nom, list(lecteur()))
            except Exception as exc:  # noqa: BLE001 — une source en panne n'emporte pas la carte
                log.warning("carte : %s illisibles : %s", nom, exc)
                notes[nom] = _court(f"{type(exc).__name__}: {exc}", 200) or ""
        couche.etats["atelier"] = _etat_ok(notes=notes) if not notes else {"etat": "partiel", "notes": notes}
        return couche

    async def calculer(self) -> dict[str, Any]:
        debut = time.monotonic()
        s = self.sources
        couche = await asyncio.to_thread(self._couche_locale)

        async def rien() -> Any:
            raise Absent("non branché")

        resultats = await asyncio.gather(
            (s.wikichat or rien)(),
            (s.gardiens_alertes or rien)(),
            (s.gardiens_automates or rien)(),
            (s.a_valider or rien)(),
            return_exceptions=True,
        )
        wikichat, alertes, automates, a_valider = resultats
        filtre = s.filtre or (lambda v: v)

        graphe: dict[str, Any] | None = None
        if isinstance(wikichat, BaseException):
            couche.etats["wikichat"] = _etat_de(wikichat)
        else:
            try:
                contrat_wikichat_valide(wikichat)
                graphe = filtre(wikichat)
                couche.etats["wikichat"] = _etat_ok(calcule_le=wikichat.get("calcule_le"),
                                                    noeuds=len(wikichat["noeuds"]),
                                                    aretes=len(wikichat["aretes"]))
            except ValueError as exc:
                couche.etats["wikichat"] = _etat_de(exc)

        gardiens: dict[str, Any] = {}
        if isinstance(alertes, BaseException):
            gardiens = _etat_de(alertes)
        elif isinstance(alertes, dict) and isinstance(alertes.get("alertes"), list):
            couche.alertes = [a for a in filtre(alertes["alertes"]) if isinstance(a, dict) and a.get("ouverte", True)]
        else:
            gardiens = {"etat": "erreur", "detail": "alertes : forme inattendue"}
        if isinstance(automates, BaseException):
            gardiens = gardiens or _etat_de(automates)
        elif isinstance(automates, dict) and isinstance(automates.get("automates"), list):
            couche.automates = [a for a in filtre(automates["automates"]) if isinstance(a, dict)]
        else:
            gardiens = gardiens or {"etat": "erreur", "detail": "automates : forme inattendue"}
        couche.etats["gardiens"] = gardiens or _etat_ok()

        if isinstance(a_valider, BaseException):
            couche.etats["a_valider"] = _etat_de(a_valider)
        else:
            charge = a_valider if isinstance(a_valider, dict) else {}
            couche.a_valider = [p for p in filtre(charge.get("propositions") or []) if isinstance(p, dict)]
            couche.etats["a_valider"] = _etat_ok(**({"note": charge["note"]} if charge.get("note") else {}))

        couche.conversations = filtre(couche.conversations)
        carte = assembler(couche, graphe, assistant=s.assistant, systeme=s.systeme)
        carte["duree_s"] = round(time.monotonic() - debut, 3)
        return carte

    async def forme(
        self, forme: str = FORME_SYNTHETIQUE, *, projet: str = "", rafraichir: bool = False
    ) -> dict[str, Any]:
        """La carte sous la forme demandée. `ValueError` si la forme ou le projet est inconnu."""
        if forme not in FORMES:
            raise ValueError(f"forme inconnue : {forme} ({', '.join(FORMES)})")
        if forme == FORME_PROJET and not projet:
            raise ValueError("forme projet : le slug du projet est requis (projet)")
        carte = await self.obtenir(rafraichir=rafraichir)
        if forme == FORME_COMPLETE:
            return {"forme": FORME_COMPLETE, **carte}
        if forme == FORME_PROJET:
            try:
                return vue_projet(carte, projet)
            except KeyError:
                raise ValueError(f"projet absent de la carte : {projet}") from None
        texte = vue_synthetique(carte)
        return {
            "forme": FORME_SYNTHETIQUE,
            "calcule_le": carte["calcule_le"],
            "sources": carte["sources"],
            "texte": texte,
            "taille": {"caracteres": len(texte), "unites_estimees": unites_estimees(texte),
                       "plafond_unites": PLAFOND_UNITES},
        }


__all__ = [
    "Absent",
    "BUDGET_SYNTHETIQUE",
    "Carte",
    "Couche",
    "FORMES",
    "FORME_COMPLETE",
    "FORME_PROJET",
    "FORME_SYNTHETIQUE",
    "PLAFOND_UNITES",
    "Sources",
    "adresse_des_gardiens",
    "assembler",
    "connecteurs_choisis",
    "contrat_wikichat_valide",
    "lire_conversations",
    "lire_creations",
    "lire_json",
    "lire_pool",
    "lire_projets",
    "sources_http",
    "unites_estimees",
    "vue_projet",
    "vue_synthetique",
]
