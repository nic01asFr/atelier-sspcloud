"""Le journal des décisions humaines : une ligne par décision, **jamais modifiée ni supprimée**.

Annuler, c'est ajouter une ligne d'annulation qui pointe la décision annulée ; l'historique reste entier. Des déclencheurs SQL refusent
toute modification et toute suppression, même par une requête à la main.

Ce qu'on valide, pour une image : le **nombre de places de stationnement perçues** (de ce côté de la rue) et la **forme** du stationnement
(`aucune`, `bataille`, `longitudinal`) — ou bien « douteuse » (image inexploitable).
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

FORMES = ("aucune", "bataille", "longitudinal")
NOMBRE_MAX = 30
_NOM = re.compile(r"^[\w .'’-]{1,40}$", re.UNICODE)

MIGRATIONS = [
    """
    CREATE TABLE decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image TEXT NOT NULL,
        validateur TEXT NOT NULL,
        nombre INTEGER,
        forme TEXT,
        douteuse INTEGER NOT NULL DEFAULT 0,
        ancien_nombre INTEGER,
        ancienne_forme TEXT,
        fichier TEXT NOT NULL,
        modele TEXT,
        aveugle INTEGER NOT NULL DEFAULT 1,
        duree_ms INTEGER,
        note TEXT NOT NULL DEFAULT '',
        annule_id INTEGER REFERENCES decisions(id),
        cree_le REAL NOT NULL
    );
    CREATE INDEX decisions_image ON decisions(image);
    CREATE INDEX decisions_validateur ON decisions(validateur, fichier);
    CREATE TRIGGER decisions_sans_modification BEFORE UPDATE ON decisions
        BEGIN SELECT RAISE(ABORT, 'le journal des décisions ne se modifie pas : on ajoute une ligne'); END;
    CREATE TRIGGER decisions_sans_suppression BEFORE DELETE ON decisions
        BEGIN SELECT RAISE(ABORT, 'le journal des décisions ne se vide pas'); END;
    """,
]


class DecisionRefusee(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    nombre: int | None
    forme: str | None
    douteuse: bool

    def comme_dict(self) -> dict[str, Any]:
        return {"nombre": self.nombre, "forme": self.forme, "douteuse": self.douteuse}


def nom_valide(nom: str) -> str:
    nom = (nom or "").strip()
    if not _NOM.match(nom):
        raise DecisionRefusee("nom de valideur refusé (1 à 40 caractères : lettres, chiffres, espace, point, tiret)")
    return nom


class Journal:
    def __init__(self, chemin: Path) -> None:
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.RLock()
        self._c = sqlite3.connect(chemin, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        self._c.execute("PRAGMA busy_timeout=5000")
        version = self._c.execute("PRAGMA user_version").fetchone()[0]
        for n, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self._c.executescript("BEGIN;" + script + f"PRAGMA user_version={n};COMMIT;")

    def fermer(self) -> None:
        with self._verrou:
            self._c.close()

    # -- écrire -------------------------------------------------------------

    def enregistrer(
        self, *, image: str, validateur: str, nombre: int | None, forme: str | None, douteuse: bool, fichier: str,
        ancien_nombre: int | None, ancienne_forme: str | None, aveugle: bool = True, modele: str | None = None,
        duree_ms: int | None = None, note: str = "",
    ) -> int:
        validateur = nom_valide(validateur)
        if douteuse:
            if nombre is not None or forme is not None:
                raise DecisionRefusee("une image douteuse n'a ni nombre ni forme")
        else:
            if nombre is None or isinstance(nombre, bool) or not isinstance(nombre, int) or not 0 <= nombre <= NOMBRE_MAX:
                raise DecisionRefusee(f"le nombre de places est un entier de 0 à {NOMBRE_MAX}")
            forme = forme or "aucune"
            if forme not in FORMES:
                raise DecisionRefusee(f"forme inconnue : {forme!r} (attendu : {', '.join(FORMES)})")
        if len(note) > 500 or "\n" in note:
            raise DecisionRefusee("note : 500 caractères, sur une ligne")
        if duree_ms is not None and not 0 <= duree_ms <= 3_600_000:
            duree_ms = None
        with self._verrou:
            cur = self._c.execute(
                "INSERT INTO decisions(image,validateur,nombre,forme,douteuse,ancien_nombre,ancienne_forme,fichier,modele,aveugle,duree_ms,note,cree_le)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (image, validateur, nombre, forme, int(douteuse), ancien_nombre, ancienne_forme, fichier, modele, int(aveugle), duree_ms, note, time.time()),
            )
            return int(cur.lastrowid)

    def annuler(self, decision_id: int, validateur: str) -> int:
        """Ajoute une ligne d'annulation. Seul l'auteur annule sa propre décision, une seule fois."""
        validateur = nom_valide(validateur)
        with self._verrou:
            d = self._c.execute("SELECT * FROM decisions WHERE id=?", (decision_id,)).fetchone()
            if d is None:
                raise DecisionRefusee(f"décision inconnue : {decision_id}")
            if d["annule_id"] is not None:
                raise DecisionRefusee("une annulation ne s'annule pas : refaites la décision")
            if d["validateur"] != validateur:
                raise DecisionRefusee("on n'annule que ses propres décisions")
            if self._c.execute("SELECT 1 FROM decisions WHERE annule_id=?", (decision_id,)).fetchone():
                raise DecisionRefusee("décision déjà annulée")
            cur = self._c.execute(
                "INSERT INTO decisions(image,validateur,douteuse,fichier,aveugle,note,annule_id,cree_le) VALUES (?,?,0,?,?,'',?,?)",
                (d["image"], validateur, d["fichier"], d["aveugle"], decision_id, time.time()),
            )
            return int(cur.lastrowid)

    # -- lire ---------------------------------------------------------------

    def _valides(self) -> list[sqlite3.Row]:
        """Les décisions en vigueur : ni annulées, ni lignes d'annulation."""
        return self._c.execute(
            "SELECT * FROM decisions d WHERE d.annule_id IS NULL AND NOT EXISTS (SELECT 1 FROM decisions a WHERE a.annule_id=d.id) ORDER BY d.id"
        ).fetchall()

    def en_vigueur(self) -> list[dict[str, Any]]:
        """Les décisions en vigueur (ni annulées, ni annulations), pour mesurer l'accord entre annotateurs."""
        with self._verrou:
            return [dict(r) for r in self._valides()]

    def deja_faites(self, validateur: str, fichier: str) -> set[str]:
        with self._verrou:
            return {r["image"] for r in self._valides() if r["validateur"] == validateur and r["fichier"] == fichier}

    def derniere(self, validateur: str) -> dict[str, Any] | None:
        with self._verrou:
            mes = [r for r in self._valides() if r["validateur"] == validateur]
            return dict(mes[-1]) if mes else None

    def _par_image(self) -> dict[str, dict[str, Decision]]:
        """image → valideur → sa dernière décision en vigueur."""
        sortie: dict[str, dict[str, Decision]] = defaultdict(dict)
        for r in self._valides():
            sortie[r["image"]][r["validateur"]] = Decision(r["nombre"], r["forme"], bool(r["douteuse"]))
        return sortie

    def retenues(self) -> dict[str, Decision]:
        """Pour chaque image, la décision sur laquelle les valideurs s'accordent. Un désaccord n'est pas retenu (il attend un arbitre)."""
        with self._verrou:
            retenues: dict[str, Decision] = {}
            for image, par in self._par_image().items():
                valeurs = set(par.values())
                if len(valeurs) == 1:
                    retenues[image] = next(iter(valeurs))
            return retenues

    def desaccords(self) -> dict[str, dict[str, dict[str, Any]]]:
        with self._verrou:
            return {
                image: {v: d.comme_dict() for v, d in par.items()}
                for image, par in self._par_image().items() if len(set(par.values())) > 1
            }

    def statistiques(self, fichier: str | None = None) -> dict[str, Any]:
        with self._verrou:
            lignes = [r for r in self._valides() if fichier is None or r["fichier"] == fichier]
            par_valideur: dict[str, int] = defaultdict(int)
            corrections: dict[str, int] = defaultdict(int)  # « ancien → nouveau » : l'étiquette d'origine tenait-elle ?
            douteuses = 0
            for r in lignes:
                par_valideur[r["validateur"]] += 1
                if r["douteuse"]:
                    douteuses += 1
                    continue
                if r["ancien_nombre"] is not None:
                    cle = f"{r['ancien_nombre']}→{r['nombre']}"
                    corrections[cle] += 1
            confirmees = sum(n for c, n in corrections.items() if c.split("→")[0] == c.split("→")[1])
            avec_ancien = sum(corrections.values())
            return {
                "decisions": len(lignes),
                "images": len({r["image"] for r in lignes}),
                "par_valideur": dict(sorted(par_valideur.items())),
                "douteuses": douteuses,
                "ancien_vers_nouveau": dict(sorted(corrections.items())),
                "part_confirmee": (confirmees / avec_ancien) if avec_ancien else None,
                "desaccords": len(self.desaccords()),
            }

    def tout(self) -> list[dict[str, Any]]:
        """Tout le journal, annulations comprises (pour l'export et l'audit)."""
        with self._verrou:
            return [dict(r) for r in self._c.execute("SELECT * FROM decisions ORDER BY id")]
