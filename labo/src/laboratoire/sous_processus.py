"""Le programme d'un essai : entraîner, puis mesurer. Il tourne dans son propre processus, sous la surveillance de l'exécuteur.

    python -m laboratoire.sous_processus <dossier de l'essai> <dossier de la variante>

Il n'écrit que des fichiers dans le dossier de l'essai (jamais dans la base : un seul processus l'écrit, le service). Sa sortie va au journal.
- `resultats.json` : la validation (visible tout de suite) ;
- `test_scelle.json` : le test, **scellé** : il n'entre dans le registre que lorsque la personne l'ouvre, et l'ouverture est comptée ;
- `erreurs.json` : les images de validation mal classées.
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from laboratoire import evaluation
from laboratoire.adaptateurs import adaptateur as obtenir_adaptateur
from laboratoire.adaptateurs.base import ContexteEssai
from laboratoire.modeles import ConfigEssai
from laboratoire.variante import Variante


def ecrire_json(chemin: Path, donnees: Any) -> None:
    """Écriture atomique : un lecteur ne voit jamais un fichier à moitié écrit."""
    temporaire = chemin.with_name(chemin.name + ".tmp")
    temporaire.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporaire, chemin)


def mesurer(ctx: ContexteEssai, adapt: Any, jeu: str) -> tuple[dict[str, Any], list[dict[str, str]]]:
    classes = ctx.variante.classes()
    predictions = adapt.predire(ctx, jeu)
    if not predictions:
        raise RuntimeError(f"le jeu « {jeu} » est vide : rien à mesurer")
    vrais = [p.echantillon.classe for p in predictions]
    predits = [p.predit for p in predictions]
    groupes = [p.echantillon.groupe for p in predictions]
    rapport = evaluation.rapport(classes, vrais, predits)
    triviales = evaluation.reponses_triviales(classes, vrais)
    mesure = {
        "jeu": jeu,
        "rapport": rapport,
        "triviales": triviales,
        "gain_sur_trivial": evaluation.gain_sur_trivial(rapport, triviales),
        "intervalle_rappel_moyen": evaluation.intervalle_par_groupes(
            classes, vrais, predits, groupes, tirages=500, graine=ctx.config.graine
        ),
    }
    erreurs = [
        {"fichier": str(p.echantillon.fichier.relative_to(ctx.variante.dossier)), "vrai": p.echantillon.classe,
         "predit": p.predit, "groupe": p.echantillon.groupe}
        for p in predictions
        if p.echantillon.classe != p.predit
    ]
    return mesure, erreurs


def executer(dossier_essai: Path, dossier_variante: Path) -> None:
    config = ConfigEssai.model_validate_json((dossier_essai / "config.json").read_text(encoding="utf-8"))
    adapt = obtenir_adaptateur(config.methode.famille)
    adapt.valider(config.methode)
    ctx = ContexteEssai(config=config, variante=Variante(dossier_variante), dossier=dossier_essai)
    print(f"[essai] {config.methode.famille}/{config.methode.modele} imgsz={config.methode.imgsz} jeu={config.jeu} graine={config.graine}", flush=True)
    print(f"[essai] effectifs : {json.dumps(ctx.variante.effectifs(), ensure_ascii=False)}", flush=True)
    adapt.entrainer(ctx)
    print("[essai] entraînement terminé ; mesure sur la validation", flush=True)
    val, erreurs = mesurer(ctx, adapt, "val")
    ecrire_json(dossier_essai / "erreurs.json", erreurs)
    ecrire_json(dossier_essai / "resultats.json", {"empreinte": config.empreinte(), **val})
    r = val["rapport"]
    print(f"[essai] validation : rappel moyen {r['rappel_moyen']} · exactitude {r['exactitude']} · non fiables {r['classes_non_fiables']}", flush=True)
    if ctx.variante.echantillons("test"):
        test, erreurs_test = mesurer(ctx, adapt, "test")
        ecrire_json(dossier_essai / "test_scelle.json", {"empreinte": config.empreinte(), **test, "erreurs": erreurs_test})
        print("[essai] test mesuré et scellé (il s'ouvre depuis le laboratoire, et l'ouverture est comptée)", flush=True)
    print("[essai] terminé", flush=True)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage : python -m laboratoire.sous_processus <dossier essai> <dossier variante>", file=sys.stderr)
        return 2
    try:
        executer(Path(argv[1]), Path(argv[2]))
    except BaseException:  # noqa: BLE001 - le journal doit tout dire, même une interruption
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
