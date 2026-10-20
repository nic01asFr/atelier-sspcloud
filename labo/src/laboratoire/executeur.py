"""Lancer, surveiller, arrêter les essais. Un essai = un sous-processus, son journal, ses fichiers.

L'exécuteur est le seul à écrire l'état des essais dans le registre : le sous-processus n'écrit que des fichiers.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from laboratoire.projet import Racine
from laboratoire.registre import Registre
from laboratoire.variante import VarianteInvalide, Variante

LIGNES_D_ERREUR = 12


def processus_vivant(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Un zombie répond à kill(0) : on le dit mort s'il n'est plus qu'une entrée de table.
    try:
        with open(f"/proc/{pid}/stat", encoding="utf-8") as f:
            return f.read().rsplit(")", 1)[1].split()[0] != "Z"
    except (OSError, IndexError):
        return True


class Executeur:
    def __init__(
        self,
        racine: Racine,
        registre: Registre,
        python: str = sys.executable,
        module: str = "laboratoire.sous_processus",
        horloge: Callable[[], float] = time.time,
    ) -> None:
        self.racine, self.registre, self.python, self.module, self._horloge = racine, registre, python, module, horloge
        self._processus: dict[str, subprocess.Popen[bytes]] = {}
        racine.preparer()

    # -- lancer ----------------------------------------------------------

    def lancer(self, essai: dict[str, Any]) -> None:
        ident = essai["id"]
        dossier = self.racine.dossier_essai(ident)
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / "config.json").write_text(json.dumps(essai["config"], ensure_ascii=False, indent=2), encoding="utf-8")
        variante = self.racine.dossier_variante(essai["config"]["jeu"])
        try:
            Variante(variante)  # on refuse avant de lancer : un jeu absent ou mal formé n'occupe pas la file
        except VarianteInvalide as exc:
            self.registre.changer_etat(ident, "en_cours", debut=self._horloge())
            self.registre.changer_etat(ident, "echoue", fin=self._horloge(), erreur=f"jeu de données inutilisable : {exc}")
            return
        journal = open(dossier / "journal.log", "ab")
        try:
            p = subprocess.Popen(  # noqa: S603 - notre propre module
                [self.python, "-m", self.module, str(dossier), str(variante)],
                stdout=journal, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=True,  # son propre groupe : on l'arrête avec ses enfants (les travailleurs de chargement)
                cwd=str(dossier),
            )
        finally:
            journal.close()
        self._processus[ident] = p
        self.registre.changer_etat(ident, "en_cours", debut=self._horloge(), pid=p.pid)

    # -- surveiller ------------------------------------------------------

    def verifier(self) -> list[str]:
        """Met à jour les essais dont le processus s'est arrêté. Rend les identifiants conclus."""
        conclus = []
        for essai in self.registre.en_cours():
            ident = essai["id"]
            p = self._processus.get(ident)
            if p is not None:
                code = p.poll()
                if code is None:
                    continue
                del self._processus[ident]
            elif essai.get("pid") and processus_vivant(int(essai["pid"])):
                continue
            else:
                code = None  # processus perdu (service redémarré) : on juge sur les fichiers
            self._conclure(essai, code)
            conclus.append(ident)
        return conclus

    def _conclure(self, essai: dict[str, Any], code: int | None) -> None:
        ident = essai["id"]
        dossier = self.racine.dossier_essai(ident)
        resultats = dossier / "resultats.json"
        if (code in (0, None)) and resultats.is_file():
            donnees = json.loads(resultats.read_text(encoding="utf-8"))
            self.registre.enregistrer_resultats(ident, "val", donnees["rapport"])
            self.registre.changer_etat(ident, "termine", fin=self._horloge(), code_sortie=0 if code is None else code)
        else:
            self.registre.changer_etat(ident, "echoue", fin=self._horloge(), code_sortie=code, erreur=self._fin_du_journal(dossier, code))

    @staticmethod
    def _fin_du_journal(dossier: Path, code: int | None) -> str:
        journal = dossier / "journal.log"
        queue = ""
        if journal.is_file():
            lignes = journal.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            queue = "\n".join(lignes[-LIGNES_D_ERREUR:])
        return f"code de sortie {code}\n{queue}".strip()

    # -- arrêter ---------------------------------------------------------

    def arreter(self, ident: str, delai: float = 5.0) -> dict[str, Any]:
        essai = self.registre.essai(ident)
        if essai["etat"] == "en_file":
            return self.registre.changer_etat(ident, "arrete", fin=self._horloge(), erreur="arrêté avant le départ")
        pid = essai.get("pid")
        p = self._processus.pop(ident, None)
        if pid and processus_vivant(int(pid)):
            try:
                os.killpg(int(pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
            fin = time.monotonic() + delai
            while time.monotonic() < fin and processus_vivant(int(pid)):
                if p is not None:
                    p.poll()
                time.sleep(0.05)
            if processus_vivant(int(pid)):
                try:
                    os.killpg(int(pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            if p is not None:
                p.wait()
        return self.registre.changer_etat(ident, "arrete", fin=self._horloge(), erreur="arrêté par la personne")

    # -- lire ------------------------------------------------------------

    def resultats(self, ident: str) -> dict[str, Any] | None:
        chemin = self.racine.dossier_essai(ident) / "resultats.json"
        return json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else None

    def ouvrir_test(self, ident: str) -> dict[str, Any]:
        """Ouvre le test scellé d'un essai terminé. Chaque ouverture est comptée ; il n'y a pas de lecture sans ouverture."""
        essai = self.registre.essai(ident)
        chemin = self.racine.dossier_essai(ident) / "test_scelle.json"
        if essai["etat"] != "termine" or not chemin.is_file():
            raise FileNotFoundError(f"{ident} : pas de test à ouvrir (état « {essai['etat']} »)")
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        donnees["consultations"] = self.registre.consulter_test(ident)
        self.registre.enregistrer_resultats(ident, "test", donnees["rapport"])
        return donnees

    def journal(self, ident: str, depuis: int = 0) -> tuple[str, int]:
        """Le journal à partir de l'octet `depuis` ; rend le texte et le nouvel octet (lecture incrémentale pour l'affichage en direct)."""
        chemin = self.racine.dossier_essai(ident) / "journal.log"
        if not chemin.is_file():
            return "", 0
        with chemin.open("rb") as f:
            f.seek(depuis)
            morceau = f.read()
        return morceau.decode("utf-8", errors="replace"), depuis + len(morceau)
