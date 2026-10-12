"""Quand la personne a-t-elle écrit pour la dernière fois dans une conversation ?

Une commande engageante rend un aperçu et un jeton ; le jeton ne vaut qu'une
fois que la personne a répondu. Un modèle qui repassait son propre jeton dans
le même tour se confirmait seul (registre D-02, revu en direct le 12/10 :
même agent lancé deux fois). Ce repère dit si, depuis l'aperçu, la personne a
dit quelque chose.

Seul compte un message arrivé par la session de l'interface : la clé du
propriétaire est lue par les agents du pod, elle ne prouve pas une personne.
Le repère est un fichier par conversation, à part de la fiche : la fiche est
relue et réécrite à chaque tour, une sauvegarde concurrente effacerait le champ.
"""

from __future__ import annotations

import os
import re
import secrets
import time
from pathlib import Path

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,199}$")


class MessagesHumains:
    def __init__(self, dossier: Path) -> None:
        self.dossier = Path(dossier)

    def _chemin(self, session_id: str) -> Path | None:
        return self.dossier / session_id if _ID.match(session_id or "") else None

    def noter(self, session_id: str, quand: float | None = None) -> None:
        chemin = self._chemin(session_id)
        if chemin is None:
            return
        try:
            self.dossier.mkdir(parents=True, exist_ok=True)
            provisoire = chemin.with_name(f"{chemin.name}.{secrets.token_hex(3)}.tmp")
            provisoire.write_text(repr(quand if quand is not None else time.time()), encoding="utf-8")
            os.replace(provisoire, chemin)
        except OSError:
            # Ne pas noter ne donne rien de plus au modèle : la confirmation sera refusée.
            pass

    def dernier(self, session_id: str) -> float:
        """L'instant du dernier message de la personne, 0 si aucun."""
        chemin = self._chemin(session_id)
        if chemin is None:
            return 0.0
        try:
            return float(chemin.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 0.0
