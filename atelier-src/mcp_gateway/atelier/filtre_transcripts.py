"""Le filtre des transcripts (T10) : aucun secret connu ne sort du texte d'une conversation.

Un agent peut afficher un secret dans sa conversation (un `cat` de trop, une
variable d'environnement recopiée). Avant ce filtre, `atelier_transcript` et
`atelier_suivre` rendaient ce texte tel quel : le secret atteignait
l'Assistant, puis sa mémoire. Tout ce qui **rend** ou **capitalise** le texte
d'une conversation passe désormais par ici, avant de rendre quoi que ce soit.

Ce qui est retiré :

- les valeurs connues : celles de `~/work/.secrets/claude-env.sh`, et celles
  des fichiers d'une ligne de `~/work/.secrets/` (clé du propriétaire, clé du
  lanceur, jeton GitHub, clé du modèle, secrets des applications). Chacune
  devient son empreinte, `<secret:0123456789ab>`, comme dans le journal des
  gardiens : on peut dire « le même secret revient » sans jamais le montrer ;
- les motifs de jetons du gardien Sécurité (`ghp_…`, `github_pat_…`, `sk-…`,
  `Bearer …`), devenus « <jeton masqué> ».

C'est le filtre du journal unique (`commandes/journal.py`, `FiltreDesSecrets`)
réutilisé : même liste de valeurs, même longueur minimale, les plus longues
d'abord. Deux différences, voulues pour un transcript :

- rien n'est coupé : le journal tronque à 600 caractères, un transcript doit
  rester entier ;
- les clés ne sont jamais masquées par leur nom : une charge d'outil de
  l'Atelier qui a un champ `secrets` (des références, pas des valeurs) doit
  rester lisible. Seules les valeurs le sont.

Une valeur est aussi cherchée sous sa forme échappée JSON (`\\"`, `\\\\`) : le
transcript rendu à l'interface est fait de lignes JSON.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable

from mcp_gateway.atelier.commandes.journal import FiltreDesSecrets
from mcp_gateway.gardiens.journal import LONGUEUR_MIN_SECRET, MOTIFS_DE_JETONS, empreinte_de_valeur

JETON_MASQUE = "<jeton masqué>"
# Un fichier de secrets au-delà n'est pas une valeur d'une ligne (une clé PEM,
# un fichier de configuration) : les motifs s'en chargent.
TAILLE_MAX_FICHIER = 4096
# Relire le dossier des secrets au plus toutes les N secondes : un
# `atelier_suivre` toutes les secondes ne doit pas refaire un parcours disque.
RELECTURE_S = 5.0


def marque(valeur: str) -> str:
    return f"<secret:{empreinte_de_valeur(valeur)}>"


def _formes(valeur: str) -> list[str]:
    """La valeur telle quelle, puis telle qu'elle s'écrit dans une chaîne JSON."""
    formes = [valeur]
    for ascii_seul in (False, True):
        echappee = json.dumps(valeur, ensure_ascii=ascii_seul)[1:-1]
        if echappee not in formes:
            formes.append(echappee)
    return formes


class FiltreDesTranscripts(FiltreDesSecrets):
    """`FiltreDesSecrets`, sans coupe ni masque par nom, avec les motifs de jetons."""

    def texte(self, texte: str) -> str:
        return self._texte(texte, self._connues())

    def _texte(self, texte: str, connues: list[str]) -> str:
        if not texte:
            return texte
        for secret in connues:
            for forme in _formes(secret):
                if forme in texte:
                    texte = texte.replace(forme, marque(secret))
        for motif in MOTIFS_DE_JETONS:
            texte = motif.sub(JETON_MASQUE, texte)
        return texte

    def nettoyer(self, valeur: Any) -> Any:
        return self._recursif(valeur, self._connues())

    def _recursif(self, valeur: Any, connues: list[str]) -> Any:
        if isinstance(valeur, str):
            return self._texte(valeur, connues)
        if isinstance(valeur, dict):
            return {k: self._recursif(v, connues) for k, v in valeur.items()}
        if isinstance(valeur, list):
            return [self._recursif(v, connues) for v in valeur]
        if isinstance(valeur, tuple):
            return tuple(self._recursif(v, connues) for v in valeur)
        return valeur


def valeurs_du_dossier(dossier: Path) -> list[str]:
    """Les valeurs de `claude-env.sh`, puis celles des fichiers d'une ligne du dossier.

    Même règle que le gardien Sécurité (`controles/securite.valeurs_connues`) :
    un fichier de plus de 4 Ko, ou de plusieurs lignes, n'est pas une valeur.
    """
    from mcp_gateway.atelier.env_secrets import NOM_DU_FICHIER, lire_le_fichier

    dossier = Path(dossier)
    valeurs: list[str] = []
    try:
        valeurs.extend(lire_le_fichier(dossier / NOM_DU_FICHIER).values())
    except OSError:
        pass
    if dossier.is_dir():
        for chemin in sorted(dossier.rglob("*")):
            try:
                if not chemin.is_file() or chemin.name == NOM_DU_FICHIER or chemin.suffix == ".tmp":
                    continue
                if chemin.stat().st_size > TAILLE_MAX_FICHIER:
                    continue
                texte = chemin.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                continue
            if texte and "\n" not in texte:
                valeurs.append(texte)
    return [v for v in valeurs if isinstance(v, str) and len(v) >= LONGUEUR_MIN_SECRET]


def lecteur_du_dossier(dossier: Path, relecture_s: float = RELECTURE_S) -> Callable[[], list[str]]:
    """Les valeurs du dossier, relues au plus toutes les `relecture_s` secondes.

    Un secret ajouté ou renouvelé est filtré au plus tard quelques secondes
    après ; les valeurs ne quittent jamais la mémoire du processus.
    """
    cache: dict[str, Any] = {"quand": 0.0, "valeurs": []}
    verrou = threading.Lock()

    def lire() -> list[str]:
        with verrou:
            maintenant = time.monotonic()
            if maintenant - cache["quand"] >= relecture_s:
                cache["valeurs"] = valeurs_du_dossier(dossier)
                cache["quand"] = maintenant
            return list(cache["valeurs"])

    return lire


_FILTRES: dict[str, FiltreDesTranscripts] = {}
_VERROU = threading.Lock()


def filtre_pour(settings: Any) -> FiltreDesTranscripts:
    """Le filtre du dossier des secrets de ces réglages, partagé par le processus."""
    dossier = Path(getattr(settings, "secrets_dir"))
    cle = str(dossier)
    with _VERROU:
        filtre = _FILTRES.get(cle)
        if filtre is None:
            filtre = FiltreDesTranscripts(lecteur_du_dossier(dossier))
            _FILTRES[cle] = filtre
        return filtre


def filtre_de_valeurs(valeurs: Iterable[str]) -> FiltreDesTranscripts:
    """Un filtre sur une liste fixe (tests, outils hors service)."""
    liste = list(valeurs)
    return FiltreDesTranscripts(lambda: liste)


__all__ = [
    "FiltreDesTranscripts",
    "JETON_MASQUE",
    "filtre_de_valeurs",
    "filtre_pour",
    "lecteur_du_dossier",
    "marque",
    "valeurs_du_dossier",
]
