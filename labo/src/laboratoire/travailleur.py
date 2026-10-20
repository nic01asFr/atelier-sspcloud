"""Le travailleur : prend la file, un essai à la fois, et tient le pod éveillé tant qu'un essai tourne.

`tick()` fait un pas et se teste sans fil d'exécution ; `demarrer()` le fait tourner en arrière-plan.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from laboratoire.executeur import Executeur, processus_vivant
from laboratoire.registre import Registre

log = logging.getLogger("laboratoire.travailleur")


class Travailleur:
    def __init__(
        self,
        registre: Registre,
        executeur: Executeur,
        parallelisme: int = 1,
        battement: Callable[[], None] | None = None,
        intervalle_battement: float = 120.0,
        horloge: Callable[[], float] = time.monotonic,
    ) -> None:
        self.registre, self.executeur, self.parallelisme = registre, executeur, max(1, parallelisme)
        self._battement, self._intervalle, self._horloge = battement, intervalle_battement, horloge
        self._dernier_battement = float("-inf")
        self._arret = threading.Event()
        self._fil: threading.Thread | None = None

    def tick(self) -> None:
        self.executeur.verifier()
        while len(self.registre.en_cours()) < self.parallelisme:
            suivant = self.registre.prochain_en_file()
            if suivant is None:
                break
            self.executeur.lancer(suivant)
        self._battre()

    def _battre(self) -> None:
        """Tant qu'un essai tourne, le GPU travaille un instant : le serveur ne coupe pas un pod qui travaille (D-81)."""
        if self._battement is None or not self.registre.en_cours():
            return
        if self._horloge() - self._dernier_battement < self._intervalle:
            return
        self._dernier_battement = self._horloge()
        try:
            self._battement()
        except Exception:  # noqa: BLE001 - un battement raté ne doit jamais arrêter un essai
            log.warning("battement raté", exc_info=True)

    def demarrer(self, pause: float = 2.0) -> None:
        interrompus = self.registre.reprendre_apres_arret(processus_vivant)
        if interrompus:
            log.warning("essais interrompus par un arrêt : %s", interrompus)

        def boucle() -> None:
            while not self._arret.is_set():
                try:
                    self.tick()
                except Exception:  # noqa: BLE001 - la boucle ne meurt pas sur un essai défaillant
                    log.exception("pas du travailleur en échec")
                self._arret.wait(pause)

        self._fil = threading.Thread(target=boucle, name="laboratoire-travailleur", daemon=True)
        self._fil.start()

    def arreter(self) -> None:
        self._arret.set()
        if self._fil:
            self._fil.join(timeout=5)
