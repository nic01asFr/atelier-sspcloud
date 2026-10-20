"""Découper en train / val / test **par groupe** (collection) et **en gardant les classes rares dans chaque jeu**.

Deux défauts du découpage du 19/10, corrigés ici :
- découper image par image fait fuiter : deux images d'une même rue, presque identiques, se retrouvent de part et d'autre ;
- découper par collection à l'aveugle (par un hachage du nom) a laissé 4 images de la classe rare en validation et 6 en test.

On répartit des collections entières, de façon déterministe pour une graine, en minimisant l'écart entre la part de chaque classe dans chaque
jeu et la proportion visée : c'est un glouton « groupes stratifiés ». Les collections qui portent une grande part d'une classe rare passent en
premier, là où le choix compte le plus.
"""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence

JEUX = ("train", "val", "test")


def decouper_par_groupes(
    comptes: Mapping[str, Mapping[str, int]],
    proportions: Sequence[float] = (0.7, 0.15, 0.15),
    graine: int = 0,
) -> dict[str, str]:
    """`comptes[groupe][classe]` = nombre d'images ; rend `groupe → jeu`.

    Aucun groupe n'est coupé en deux : c'est la garantie anti-fuite. Avec au moins trois groupes, chaque jeu reçoit au moins un groupe.
    """
    if len(proportions) != 3 or any(p <= 0 for p in proportions) or abs(sum(proportions) - 1) > 1e-6:
        raise ValueError("trois proportions strictement positives, de somme 1")
    # Triés d'abord : le résultat ne dépend ni de l'ordre du disque ni de celui du dictionnaire, seulement de la graine.
    groupes = sorted(g for g in comptes if sum(comptes[g].values()) > 0)
    if not groupes:
        return {}
    classes = sorted({c for g in groupes for c in comptes[g]})
    total = {c: sum(comptes[g].get(c, 0) for g in groupes) for c in classes}
    hasard = random.Random(graine)
    hasard.shuffle(groupes)  # l'égalité de priorité se tranche par la graine, pas par l'ordre du disque

    def priorite(g: str) -> float:
        return max((comptes[g].get(c, 0) / total[c] for c in classes if total[c]), default=0.0)

    groupes.sort(key=priorite, reverse=True)  # tri stable : le mélange départage les égalités
    courant = {j: {c: 0 for c in classes} for j in JEUX}
    affectation: dict[str, str] = {}
    for g in groupes:
        meilleur, meilleur_cout = JEUX[0], float("inf")
        for j, p in zip(JEUX, proportions):
            # Ce qu'on **gagne** à mettre ce groupe ici (variation de l'écart à la proportion visée), pas l'écart lui-même :
            # sinon un jeu déjà proche de sa cible serait toujours préféré à un jeu encore vide.
            cout = sum(
                ((courant[j][c] + comptes[g].get(c, 0)) / total[c] - p) ** 2 - (courant[j][c] / total[c] - p) ** 2
                for c in classes
                if total[c]
            )
            if cout < meilleur_cout - 1e-12:
                meilleur, meilleur_cout = j, cout
        affectation[g] = meilleur
        for c in classes:
            courant[meilleur][c] += comptes[g].get(c, 0)
    _reparer_la_presence(comptes, classes, affectation)
    # Un jeu vide n'a aucun sens : avec assez de groupes, on prend le plus petit du jeu le plus fourni.
    if len(groupes) >= 3:
        for vide in (j for j in JEUX if j not in set(affectation.values())):
            donneur = max(JEUX, key=lambda j: sum(1 for v in affectation.values() if v == j))
            candidat = min((g for g, j in affectation.items() if j == donneur), key=lambda g: sum(comptes[g].values()))
            affectation[candidat] = vide
    return affectation


def _reparer_la_presence(comptes: Mapping[str, Mapping[str, int]], classes: Sequence[str], affectation: dict[str, str]) -> None:
    """Une classe présente dans au moins trois collections doit l'être dans chacun des trois jeux.

    Le glouton minimise un écart moyen ; il peut laisser une classe rare sans aucune image dans un jeu, et l'on mesurerait alors un rappel
    sur rien. Pour chaque (jeu, classe) vide, on déplace vers ce jeu la collection **la plus petite** qui porte la classe, prise dans le jeu qui
    en a le plus et qui garde ainsi au moins une collection porteuse. On traite les classes les plus rares d'abord.
    """
    portent = {c: [g for g in affectation if comptes[g].get(c, 0) > 0] for c in classes}
    for classe in sorted(classes, key=lambda c: (len(portent[c]), c)):
        if len(portent[classe]) < 3:
            continue
        for jeu in JEUX:
            if any(affectation[g] == jeu for g in portent[classe]):
                continue
            donneurs = {j: [g for g in portent[classe] if affectation[g] == j] for j in JEUX if j != jeu}
            donneur = max((j for j in donneurs if len(donneurs[j]) >= 2), key=lambda j: sum(comptes[g].get(classe, 0) for g in donneurs[j]), default=None)
            if donneur is None:
                continue
            candidat = min(donneurs[donneur], key=lambda g: (sum(comptes[g].values()), g))
            affectation[candidat] = jeu
