"""Une conversation n'a qu'une histoire, même si elle s'écrit à deux endroits.

L'Atelier tient son journal ; le CLI lancé par VS Code tient le sien. Aucun des
deux ne lit l'autre, et — mesuré le 6 septembre — aucun n'est complet : sur une
conversation, quatre messages tapés dans VS Code manquaient à l'Atelier ; sur
une autre, les deux premiers tours n'existaient que chez nous. Ouvrir le même
fil des deux côtés montrait donc deux histoires partielles, chacune persuadée
d'être entière.

On ne choisit pas un registre contre l'autre : on les fond. Les deux portent
`uuid` et `timestamp`, ce qui rend la chose possible sans deviner.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.events import sans_substituts

# Ce qu'un lecteur doit voir. Les autres types — événements de flux, opérations
# de file — appartiennent à la mécanique, pas à la conversation.
TYPES_MONTRES = ("user", "assistant", "result")

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# Le même geste s'écrit de deux façons : `/compact` chez nous,
# `<command-name>/compact</command-name>` chez le CLI. Sans cette équivalence,
# la fusion afficherait deux fois chaque commande.
_COMMANDE = re.compile(r"<command-name>\s*([^<]*?)\s*</command-name>")


def texte_dune_entree(entree: dict[str, Any]) -> str:
    """Ce qui a été dit, quelle que soit la forme du contenu."""
    contenu = (entree.get("message") or {}).get("content")
    if isinstance(contenu, str):
        return contenu
    if not isinstance(contenu, list):
        return ""
    morceaux = [
        b.get("text", "")
        for b in contenu
        if isinstance(b, dict) and b.get("type") == "text"
    ]
    return " ".join(m for m in morceaux if m)


def normaliser(texte: str) -> str:
    """Ramène deux graphies d'un même message à une seule."""
    sans_couleur = _ANSI.sub("", texte or "")
    sans_balise = _COMMANDE.sub(r"\1", sans_couleur)
    return " ".join(sans_balise.split())


# Ce que le CLI glisse dans le fil sans que personne l'ait dit. Fondre les deux
# registres les a fait remonter : ils s'affichaient comme des messages de
# l'utilisateur, ce qu'ils ne sont pas.
#
# On n'écarte que le machinal. `[Request interrupted by user for tool use]`
# reste : c'est un geste réellement fait par quelqu'un, et une histoire qui
# l'efface ment sur ce qui s'est passé.
MARQUEURS_MECANIQUES = (
    "<task-notification>",
    "<local-command-stdout>",
    "<system-reminder>",
    "<command-message>",
    "Caveat: The messages below were generated",
)


def est_machinal(texte: str) -> bool:
    """Une entrée que le CLI s'est écrite à lui-même, et qu'il ne faut pas lire."""
    return normaliser(texte).startswith(MARQUEURS_MECANIQUES)


def _entrees(chemin: Path) -> list[dict[str, Any]]:
    if not chemin.is_file():
        return []
    out: list[dict[str, Any]] = []
    try:
        flux = chemin.open(encoding="utf-8", errors="replace")
    except OSError:
        return []
    with flux:
        for ligne in flux:
            ligne = ligne.strip()
            if not ligne.startswith("{"):
                continue
            try:
                # Un emoji coupé en deux dans le transcrit du CLI donne un
                # substitut isolé que `json.loads` accepte mais que la réponse
                # JSON refuse ensuite d'encoder : on le retire ici.
                e = sans_substituts(json.loads(ligne))
            except json.JSONDecodeError:
                continue
            if not isinstance(e, dict) or e.get("type") not in TYPES_MONTRES:
                continue
            if e.get("type") == "user" and est_machinal(texte_dune_entree(e)):
                continue
            out.append(e)
    return out


def fondre(registres: list[Path]) -> list[dict[str, Any]]:
    """Une histoire unique, ordonnée, sans doublon.

    L'ordre des registres compte : le premier a raison sur la forme. On donne
    donc le journal de l'Atelier en tête, dont la graphie est celle que sait
    déjà lire l'affichage.

    Deux dédoublonnages, et ils ne font pas le même travail. Le `uuid` attrape
    l'entrée strictement identique, présente des deux côtés. Le texte normalisé
    attrape le même geste écrit autrement — mais seulement quand il y a du
    texte : un tour qui n'appelle que des outils n'en a pas, et les fondre sur
    un texte vide les réduirait tous à un seul.
    """
    vus_uuid: set[str] = set()
    vus_texte: set[tuple[str, str]] = set()
    retenues: list[tuple[str, int, dict[str, Any]]] = []
    rang = 0
    for chemin in registres:
        # Une entrée sans horodatage (le `result` qui clôt un tour, dans le
        # journal de l'Atelier) prend celui de l'entrée qui la précède dans son
        # registre. Sans cela elle remontait au début de l'histoire : l'affichage
        # la lisait comme la réponse du tour, puis montrait la vraie réponse une
        # seconde fois (constaté sur le pod le 26/09).
        precedent = ""
        for e in _entrees(chemin):
            if e.get("timestamp"):
                precedent = str(e.get("timestamp"))
            elif precedent:
                e = {**e, "timestamp": precedent}
            uid = str(e.get("uuid") or "")
            if uid and uid in vus_uuid:
                continue
            texte = normaliser(texte_dune_entree(e))
            cle = (str(e.get("type")), texte)
            if texte and cle in vus_texte:
                continue
            if uid:
                vus_uuid.add(uid)
            if texte:
                vus_texte.add(cle)
            retenues.append((str(e.get("timestamp") or ""), rang, e))
            rang += 1
    # Sans horodatage, l'entrée garde sa place d'arrivée plutôt que de remonter
    # en tête : mieux vaut un ordre approximatif qu'une histoire réécrite.
    dates = [h for h, _, _ in retenues if h]
    defaut = min(dates) if dates else ""
    retenues.sort(key=lambda x: (x[0] or defaut, x[1]))
    return [e for _, _, e in retenues]


def histoire_unifiee(registres: list[Path]) -> str:
    """La conversation fondue, au format de lignes que l'affichage attend."""
    lignes = [json.dumps(e, ensure_ascii=False) for e in fondre(registres)]
    return "\n".join(lignes) + ("\n" if lignes else "")


def a_absorber(
    chemin: Path, depuis: int, connus: set[str] | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Ce qui a été écrit ailleurs et qu'on n'a pas, et où l'on en est.

    Le critère est le `uuid`, pas la provenance. On avait d'abord repris les
    seules entrées estampillées d'un autre point d'entrée que le nôtre — ce qui
    marchait pour ce que VS Code tape, mais laissait dehors trente-sept entrées
    de nos propres tours, que notre harnais ne consigne pas ligne à ligne. Le
    `uuid` les attrape toutes sans jamais rien reprendre deux fois.

    Une entrée sans `uuid` n'est pas reprise : on ne saurait pas la reconnaître
    au passage suivant, et un doublon ne se retire plus d'un journal qui ne fait
    qu'ajouter.

    On repart de l'octet où l'on s'était arrêté. Si le fichier a rétréci, c'est
    qu'il a été réécrit sous nos pieds : on repart du début plutôt que de lire
    au milieu d'une ligne.
    """
    if not chemin.is_file():
        return [], depuis
    try:
        taille = chemin.stat().st_size
    except OSError:
        return [], depuis
    debut = 0 if taille < depuis else depuis
    deja = connus or set()
    retenues: list[dict[str, Any]] = []
    vus: set[str] = set()
    try:
        with chemin.open(encoding="utf-8", errors="replace") as flux:
            flux.seek(debut)
            for ligne in flux:
                ligne = ligne.strip()
                if not ligne.startswith("{"):
                    continue
                try:
                    e = json.loads(ligne)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict) or e.get("type") not in TYPES_MONTRES:
                    continue
                uid = str(e.get("uuid") or "")
                if not uid or uid in deja or uid in vus:
                    continue
                if e.get("type") == "user" and est_machinal(texte_dune_entree(e)):
                    continue
                vus.add(uid)
                retenues.append(e)
    except OSError:
        return [], depuis
    return retenues, taille


def uuids_connus(chemin: Path) -> set[str]:
    """Les entrées que notre cahier porte déjà."""
    return {
        str(e.get("uuid"))
        for e in _entrees(chemin)
        if e.get("uuid")
    }


def paroles_humaines(entrees: list[dict[str, Any]]) -> int:
    """Combien de fois quelqu'un a pris la parole.

    Ni les retours d'outils, ni le machinal : ce qu'on compte doit être ce que
    le lecteur voit, sans quoi le nombre affiché ment sur le fil.
    """
    n = 0
    for e in entrees:
        if e.get("type") != "user":
            continue
        contenu = (e.get("message") or {}).get("content")
        if isinstance(contenu, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in contenu
        ):
            continue
        if normaliser(texte_dune_entree(e)):
            n += 1
    return n
