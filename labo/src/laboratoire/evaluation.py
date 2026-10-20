"""Mesurer honnêtement.

Trois règles, apprises le 19/10 sur deux entraînements « réussis » qui ne valaient rien :

1. **Le rappel par classe, et sa moyenne**, sont la mesure. L'exactitude seule récompense la réponse « toujours la classe la plus
   fréquente » : avec 141 images sur 159 d'une classe, elle donne 0,887 sans rien avoir appris.
2. **Un chiffre est toujours lu contre une réponse triviale** (toujours la classe majoritaire, au hasard).
3. **Un chiffre dit sa fiabilité** : une classe de moins de `SEUIL_FIABLE` images est marquée non fiable, et un intervalle est donné
   par rééchantillonnage **de groupes** (les collections), pas d'images : des images voisines d'une même rue ne sont pas indépendantes.

Fonctions pures, sans dépendance : elles se testent sans GPU, et l'adaptateur de modèle ne fait que leur fournir des paires
(classe vraie, classe prédite).
"""

from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from typing import Any

# Au-dessous, le rappel d'une classe ne dit presque rien : un seul exemple de plus déplace le chiffre de 5 points ou plus.
SEUIL_FIABLE = 20


def matrice_de_confusion(classes: Sequence[str], vrais: Sequence[str], predits: Sequence[str]) -> list[list[int]]:
    """Lignes : classe vraie ; colonnes : classe prédite. Une classe hors liste est une erreur de l'appelant, pas un silence."""
    if len(vrais) != len(predits):
        raise ValueError(f"{len(vrais)} classes vraies pour {len(predits)} prédictions")
    indice = {c: i for i, c in enumerate(classes)}
    matrice = [[0] * len(classes) for _ in classes]
    for v, p in zip(vrais, predits):
        if v not in indice:
            raise ValueError(f"classe vraie inconnue : {v!r} (classes : {list(classes)})")
        if p not in indice:
            raise ValueError(f"classe prédite inconnue : {p!r} (classes : {list(classes)})")
        matrice[indice[v]][indice[p]] += 1
    return matrice


def _rapport_depuis_matrice(classes: Sequence[str], matrice: list[list[int]], seuil_fiable: int) -> dict[str, Any]:
    total = sum(sum(ligne) for ligne in matrice)
    bons = sum(matrice[i][i] for i in range(len(classes)))
    par_classe: dict[str, dict[str, Any]] = {}
    rappels: list[float] = []
    f1s: list[float] = []
    for i, classe in enumerate(classes):
        n = sum(matrice[i])
        predits_ici = sum(matrice[j][i] for j in range(len(classes)))
        vp = matrice[i][i]
        rappel = vp / n if n else None
        precision = vp / predits_ici if predits_ici else None
        if rappel is not None and precision is not None and (rappel + precision) > 0:
            f1 = 2 * rappel * precision / (rappel + precision)
        else:
            f1 = 0.0 if n else None
        par_classe[classe] = {
            "n": n,
            "rappel": rappel,
            "precision": precision,
            "f1": f1,
            "fiable": n >= seuil_fiable,
        }
        if rappel is not None:
            rappels.append(rappel)
        if f1 is not None:
            f1s.append(f1)
    return {
        "total": total,
        "exactitude": bons / total if total else None,
        # Rappel moyen = exactitude équilibrée : chaque classe pèse pareil, quel que soit son effectif.
        "rappel_moyen": sum(rappels) / len(rappels) if rappels else None,
        "f1_moyen": sum(f1s) / len(f1s) if f1s else None,
        "par_classe": par_classe,
        "classes_non_fiables": [c for c, v in par_classe.items() if v["n"] and not v["fiable"]],
        "confusion": matrice,
        "classes": list(classes),
    }


def rapport(
    classes: Sequence[str], vrais: Sequence[str], predits: Sequence[str], seuil_fiable: int = SEUIL_FIABLE
) -> dict[str, Any]:
    """Tout ce qu'on lit sur un jeu : exactitude, rappel/précision/F1 par classe, rappel moyen, fiabilité, matrice."""
    return _rapport_depuis_matrice(classes, matrice_de_confusion(classes, vrais, predits), seuil_fiable)


def reponses_triviales(classes: Sequence[str], vrais: Sequence[str]) -> dict[str, dict[str, float | str | None]]:
    """Ce qu'obtiendrait un « modèle » qui n'a rien appris, sur les mêmes images.

    - `majoritaire` : répond toujours la classe la plus fréquente du jeu ;
    - `hasard` : répond au hasard, uniformément parmi les classes.
    Un résultat se lit en gain sur ces deux lignes.
    """
    presentes = [c for c in classes if c in set(vrais)]
    if not vrais or not presentes:
        return {"majoritaire": {"classe": None, "exactitude": None, "rappel_moyen": None},
                "hasard": {"exactitude": None, "rappel_moyen": None}}
    comptes = {c: sum(1 for v in vrais if v == c) for c in presentes}
    majeure = max(presentes, key=lambda c: (comptes[c], c))
    return {
        "majoritaire": {
            "classe": majeure,
            "exactitude": comptes[majeure] / len(vrais),
            # Rappel de 1 sur la classe répondue, 0 sur les autres : moyenne = 1 / (nombre de classes présentes).
            "rappel_moyen": 1 / len(presentes),
        },
        "hasard": {"exactitude": 1 / len(classes), "rappel_moyen": 1 / len(classes)},
    }


def gain_sur_trivial(rapport_: dict[str, Any], triviales: dict[str, Any]) -> dict[str, float | None]:
    """Écart du rappel moyen à chaque réponse triviale (positif : le modèle a appris quelque chose)."""
    rm = rapport_.get("rappel_moyen")
    sortie: dict[str, float | None] = {}
    for nom, ligne in triviales.items():
        base = ligne.get("rappel_moyen")
        sortie[nom] = None if rm is None or base is None else rm - base
    return sortie


def intervalle_par_groupes(
    classes: Sequence[str],
    vrais: Sequence[str],
    predits: Sequence[str],
    groupes: Sequence[str],
    mesure: Callable[[dict[str, Any]], float | None] = lambda r: r["rappel_moyen"],
    tirages: int = 1000,
    graine: int = 0,
    niveau: float = 0.95,
) -> dict[str, Any]:
    """Intervalle de confiance d'une mesure, par rééchantillonnage **des groupes** (collections) avec remise.

    Rééchantillonner des images serait optimiste : deux images d'une même rue se ressemblent. On tire des collections entières, comme le
    ferait un nouveau jeu de rues. Déterministe pour une graine donnée. Avec moins de deux groupes, aucun intervalle n'a de sens : `None`.
    """
    if not (len(vrais) == len(predits) == len(groupes)):
        raise ValueError("vrais, predits et groupes doivent avoir la même longueur")
    par_groupe: dict[str, list[int]] = {}
    for i, g in enumerate(groupes):
        par_groupe.setdefault(g, []).append(i)
    noms = sorted(par_groupe)
    point = mesure(rapport(classes, vrais, predits))
    if len(noms) < 2:
        return {"estimation": point, "bas": None, "haut": None, "groupes": len(noms), "tirages": 0, "niveau": niveau}
    hasard = random.Random(graine)
    valeurs: list[float] = []
    for _ in range(tirages):
        indices: list[int] = []
        for g in (hasard.choice(noms) for _ in noms):
            indices.extend(par_groupe[g])
        m = mesure(rapport(classes, [vrais[i] for i in indices], [predits[i] for i in indices]))
        if m is not None:
            valeurs.append(m)
    if not valeurs:
        return {"estimation": point, "bas": None, "haut": None, "groupes": len(noms), "tirages": 0, "niveau": niveau}
    valeurs.sort()
    alpha = (1 - niveau) / 2
    bas = valeurs[int(alpha * (len(valeurs) - 1))]
    haut = valeurs[int((1 - alpha) * (len(valeurs) - 1))]
    return {"estimation": point, "bas": bas, "haut": haut, "groupes": len(noms), "tirages": len(valeurs), "niveau": niveau}


def comparaison_appariee(
    scores_a: Sequence[float], scores_b: Sequence[float], tirages: int = 2000, graine: int = 0, niveau: float = 0.95
) -> dict[str, Any]:
    """A est-il meilleur que B, ou est-ce du bruit ? Les scores sont appariés (mêmes plis, mêmes graines).

    On regarde la différence A − B pli par pli et l'on rééchantillonne ces différences. Si l'intervalle exclut 0, la différence est réelle ;
    sinon on ne conclut pas. Avec moins de trois paires, on ne conclut jamais.
    """
    if len(scores_a) != len(scores_b):
        raise ValueError("deux séries appariées doivent avoir la même longueur")
    n = len(scores_a)
    differences = [a - b for a, b in zip(scores_a, scores_b)]
    if n == 0:
        return {"paires": 0, "difference": None, "bas": None, "haut": None, "verdict": "aucune donnée"}
    moyenne = sum(differences) / n
    if n < 3:
        return {"paires": n, "difference": moyenne, "bas": None, "haut": None, "verdict": "trop peu de paires pour conclure"}
    hasard = random.Random(graine)
    moyennes = sorted(sum(hasard.choice(differences) for _ in range(n)) / n for _ in range(tirages))
    alpha = (1 - niveau) / 2
    bas = moyennes[int(alpha * (tirages - 1))]
    haut = moyennes[int((1 - alpha) * (tirages - 1))]
    if bas > 0:
        verdict = "A meilleur que B"
    elif haut < 0:
        verdict = "B meilleur que A"
    else:
        verdict = "différence non établie (dans le bruit)"
    return {"paires": n, "difference": moyenne, "bas": bas, "haut": haut, "verdict": verdict}
