"""Recherche d'outils dans le périmètre du profil actif.

Charger tous les outils dans le contexte coûte cher — mesuré : ~13 900 tokens
pour le profil `tout`. Cette recherche permet de n'exposer en permanence que les
méta-outils, le reste étant retrouvé à la demande.

Le classement est lexical : normalisation des accents, nom pondéré plus fort que
la description. Éprouvé sur le catalogue réel, il place le bon outil en tête sans
recourir à des embeddings. L'usage constaté et les épinglages départagent ensuite.

Cette recherche ne décide jamais de ce qui est *permis* : elle opère sur les
outils déjà filtrés par le profil, qui reste le plafond de sécurité.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

NAME_WEIGHT = 3
DESCRIPTION_WEIGHT = 1
USAGE_BONUS_MAX = 2
PIN_BONUS = 2
DEFAULT_LIMIT = 10
MIN_TERM_LENGTH = 3


DIGEST_DESCRIPTION_LENGTH = 110

# Indices qu'un échec vient des arguments et non du métier : dans ce cas, rendre
# le schéma permet à l'assistant de corriger sans repartir en recherche.
ARGUMENT_ERROR_HINTS = (
    "required", "requis", "invalid", "invalide", "missing", "manquant",
    "argument", "parameter", "paramètre", "schema", "schéma", "validation",
    "unexpected keyword", "got an unexpected", "type error", "typeerror",
)


def looks_like_argument_error(text: str | None) -> bool:
    """Vrai si le message d'erreur évoque un problème d'arguments.

    Volontairement heuristique : joindre le schéma à toute erreur noierait les
    messages métier légitimes (« No study zone set ») sous du bruit.
    """
    lowered = normalize(text)
    return any(hint in lowered for hint in ARGUMENT_ERROR_HINTS)


def suggest_names(candidates: list[str], wanted: str, limit: int = 5) -> list[str]:
    """Noms les plus proches — un outil introuvable est souvent mal orthographié."""
    import difflib

    wanted_n = normalize(wanted)
    close = difflib.get_close_matches(wanted_n, [normalize(c) for c in candidates],
                                      n=limit, cutoff=0.6)
    by_norm = {normalize(c): c for c in candidates}
    out = [by_norm[c] for c in close if c in by_norm]
    if out:
        return out
    # Repli : un fragment commun suffit souvent (« export » -> qgis__export_pdf).
    fragment = wanted_n.split("__")[-1]
    return [c for c in candidates if fragment and fragment in normalize(c)][:limit]


def tool_digest(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Vue allégée pour un inventaire : de quoi choisir, pas de quoi appeler.

    Les schémas d'appel sont le gros du poids ; on ne les joint qu'aux résultats
    d'une recherche, quand l'assistant s'apprête effectivement à exécuter.
    """
    out: list[dict[str, Any]] = []
    for tool in tools:
        description = " ".join(str(tool.get("description") or "").split())
        if len(description) > DIGEST_DESCRIPTION_LENGTH:
            description = description[: DIGEST_DESCRIPTION_LENGTH - 1].rstrip() + "…"
        item = {"name": str(tool.get("name") or ""), "description": description}
        kind = str(tool.get("kind") or "")
        if kind:
            item["kind"] = kind
        out.append(item)
    return out


def normalize(text: str | None) -> str:
    """Minuscules sans accents — « étude » et « etude » doivent se rejoindre."""
    decomposed = unicodedata.normalize("NFD", (text or "").lower())
    return "".join(c for c in decomposed if unicodedata.category(c) != "Mn")


def split_terms(query: str | None) -> list[str]:
    """Termes significatifs de la requête, mots outils écartés par leur longueur."""
    return [w for w in re.split(r"\W+", normalize(query)) if len(w) >= MIN_TERM_LENGTH]


def lexical_score(tool: dict[str, Any], terms: list[str]) -> int:
    if not terms:
        return 0
    name = normalize(str(tool.get("name") or ""))
    description = normalize(str(tool.get("description") or ""))
    score = 0
    for term in terms:
        if term in name:
            score += NAME_WEIGHT
        if term in description:
            score += DESCRIPTION_WEIGHT
    return score


def _server_of(tool: dict[str, Any]) -> str:
    """Préfixe du serveur d'origine : `qgis__export_pdf` → `qgis`."""
    explicit = tool.get("server") or tool.get("source")
    if explicit:
        return str(explicit)
    name = str(tool.get("name") or "")
    return name.split("__", 1)[0] if "__" in name else ""


def _correspond_au_serveur(tool: dict[str, Any], server: str) -> bool:
    """Le filtre `server` accepte le préfixe d'outil *ou* la clé de pool.

    Les outils du registre portent `source=registry:chrome-devtools-mcp` alors
    que le nom s'écrit `chrome-devtools-mcp__raise_window`. Exiger l'égalité
    stricte faisait rater le navigateur dès qu'on cherchait par son nom de
    service — celui que décrit le schéma de `gateway_find_tools`.
    """
    voulu = str(server or "").strip()
    if not voulu:
        return True
    origin = _server_of(tool)
    nom = str(tool.get("name") or "")
    prefixe = nom.split("__", 1)[0] if "__" in nom else ""
    if voulu in {origin, prefixe}:
        return True
    if origin.endswith(f":{voulu}") or voulu.endswith(f":{origin}"):
        return True
    return False


def _usage_bonus(name: str, usage: dict[str, int] | None) -> float:
    """Léger avantage aux outils réellement utilisés, plafonné pour ne pas
    écraser la pertinence lexicale."""
    if not usage:
        return 0.0
    count = usage.get(name, 0)
    if count <= 0:
        return 0.0
    top = max(usage.values()) or 1
    return USAGE_BONUS_MAX * (count / top)


def search_tools(
    tools: list[dict[str, Any]],
    *,
    query: str = "",
    kind: str = "",
    server: str = "",
    limit: int = DEFAULT_LIMIT,
    usage: dict[str, int] | None = None,
    pins: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Outils correspondants, les plus pertinents d'abord.

    `limit <= 0` rend tout le périmètre filtré : c'est l'inventaire, que
    tronquer laisserait croire incomplet. L'appelant décide (cf. `_find_tools`).
    """
    terms = split_terms(query)
    pins = pins or set()
    candidates = []

    for tool in tools:
        if kind and str(tool.get("kind") or "") != kind:
            continue
        if server and not _correspond_au_serveur(tool, server):
            continue
        score = lexical_score(tool, terms)
        if terms and score == 0:
            continue
        name = str(tool.get("name") or "")
        ranking = score + _usage_bonus(name, usage) + (PIN_BONUS if name in pins else 0)
        candidates.append((ranking, name, tool))

    # Le nom départage à score égal : l'ordre doit être stable d'un appel à l'autre.
    candidates.sort(key=lambda item: (-item[0], item[1]))
    if limit <= 0:
        return [tool for _, _, tool in candidates]
    return [tool for _, _, tool in candidates[:limit]]
