"""L'accord entre annotateurs : à quel point des humains s'entendent sur la même image. C'est ce qui borne ce qu'un modèle peut apprendre.

Deux comparaisons, sur les décisions en vigueur du journal :
- **origine contre valideur** : l'étiquette d'origine (celle du jeu de données) contre ce que dit un valideur qui ne la voyait pas ;
- **valideur contre valideur** : deux personnes sur les mêmes images, sans voir la réponse de l'autre.

Pour chaque comparaison on rend l'**accord brut**, le **kappa de Cohen** (accord corrigé de celui qu'on aurait au hasard), la **matrice de
confusion**, l'accord **par classe** et le **rappel moyen humain** : le rappel moyen de l'un des deux en prenant l'autre pour référence. C'est la
même mesure que le rappel moyen d'un modèle : un modèle ne peut guère le dépasser, puisque ses étiquettes de référence sont celles d'un humain.

Les images « douteuses » n'entrent pas dans les accords (on les compte à part). Le nombre de places est plafonné à « 2 et plus », comme dans
les recettes.

Attention : un échantillon tiré par étiquette d'origine (file `accord`) rend l'accord **par classe** fiable, pas l'accord brut ni le kappa globaux
(ils dépendent de la part de chaque classe dans l'échantillon, pas dans le jeu). Pour comparer à un modèle, on lit le rappel moyen humain.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from typing import Any

from laboratoire.evaluation import SEUIL_FIABLE

CLASSES_NOMBRE = ("0", "1", "2+")
CLASSES_FORME = ("aucune", "bataille", "longitudinal")
PLAFOND_NOMBRE = 2


def classe_nombre(n: int) -> str:
    return "2+" if n >= PLAFOND_NOMBRE else str(n)


def kappa_cohen(paires: Sequence[tuple[str, str]]) -> dict[str, Any]:
    """Accord brut et kappa de Cohen de paires (étiquette de A, étiquette de B). Kappa `None` si le hasard suffit à tout expliquer."""
    n = len(paires)
    if n == 0:
        return {"n": 0, "accord": None, "kappa": None}
    accord = sum(1 for a, b in paires if a == b) / n
    classes = sorted({c for p in paires for c in p})
    attendu = sum((sum(1 for a, _ in paires if a == c) / n) * (sum(1 for _, b in paires if b == c) / n) for c in classes)
    kappa = None if attendu >= 1 - 1e-12 else (accord - attendu) / (1 - attendu)
    return {"n": n, "accord": accord, "kappa": kappa}


def comparer(paires: Sequence[tuple[str, str]], classes: Sequence[str]) -> dict[str, Any]:
    """Compare deux jeux d'étiquettes. `paires` : (référence, autre). La référence est en lignes de la matrice."""
    paires = [(a, b) for a, b in paires if a in classes and b in classes]
    indice = {c: i for i, c in enumerate(classes)}
    matrice = [[0] * len(classes) for _ in classes]
    for a, b in paires:
        matrice[indice[a]][indice[b]] += 1
    par_classe: dict[str, dict[str, Any]] = {}
    rappels: list[float] = []
    for c in classes:
        n_c = sum(matrice[indice[c]])
        if not n_c:
            continue
        r = matrice[indice[c]][indice[c]] / n_c
        par_classe[c] = {"n": n_c, "accord": r, "fiable": n_c >= SEUIL_FIABLE}
        rappels.append(r)
    return {
        **kappa_cohen(paires),
        "classes": list(classes),
        "confusion": matrice,
        "par_classe": par_classe,
        "rappel_moyen_humain": sum(rappels) / len(rappels) if rappels else None,
    }


def _etiquettes(ligne: dict[str, Any], tache: str, ancien: bool = False) -> str | None:
    """L'étiquette d'une ligne du journal pour la tâche, ou `None` si elle n'en porte pas (douteuse, ou pas d'ancienne étiquette)."""
    if ancien:
        if tache == "nombre":
            return None if ligne["ancien_nombre"] is None else classe_nombre(ligne["ancien_nombre"])
        return ligne["ancienne_forme"]
    if ligne["douteuse"]:
        return None
    if tache == "nombre":
        return None if ligne["nombre"] is None else classe_nombre(ligne["nombre"])
    return ligne["forme"]


def rapport_accord(lignes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """`lignes` : les décisions en vigueur du journal (dicts). Rend, par tâche, les deux comparaisons et le compte des douteuses."""
    sortie: dict[str, Any] = {}
    par_image: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    for ligne in lignes:
        par_image[ligne["image"]][ligne["validateur"]] = ligne
    valideurs = sorted({v for par in par_image.values() for v in par})
    for tache, classes in (("nombre", CLASSES_NOMBRE), ("forme", CLASSES_FORME)):
        origine: dict[str, list[tuple[str, str]]] = {v: [] for v in valideurs}
        entre: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for par in par_image.values():
            for v, l in par.items():
                a, b = _etiquettes(l, tache, ancien=True), _etiquettes(l, tache)
                if a is not None and b is not None:
                    origine[v].append((a, b))
            noms = sorted(par)
            for i, v in enumerate(noms):
                for w in noms[i + 1:]:
                    a, b = _etiquettes(par[v], tache), _etiquettes(par[w], tache)
                    if a is not None and b is not None:
                        entre.setdefault((v, w), []).append((a, b))
        sortie[tache] = {
            "classes": list(classes),
            "origine_contre_valideur": {v: comparer(p, classes) for v, p in origine.items() if p},
            "valideur_contre_valideur": {f"{v} | {w}": comparer(p, classes) for (v, w), p in sorted(entre.items())},
        }
    sortie["douteuses"] = sum(1 for l in lignes if l["douteuse"])
    sortie["images"] = len(par_image)
    sortie["valideurs"] = valideurs
    return sortie
