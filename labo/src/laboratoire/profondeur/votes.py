"""Le journal des votes par paires : une ligne par jugement, **jamais modifiée ni supprimée** (même principe que la validation des images).

Une personne voit, pour une même vue, deux cartes de profondeur sans savoir de quels modèles elles viennent (ni de quel côté est chacun : le côté est
tiré au hasard) et dit laquelle rend le mieux le relief de la scène, ou « égal », ou « je ne peux pas juger ». Annuler, c'est ajouter une ligne qui
pointe la ligne annulée.
"""

from __future__ import annotations

import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

CHOIX = ("gauche", "droite", "egal", "indecidable")
_NOM = re.compile(r"^[\w .'’-]{1,40}$", re.UNICODE)

MIGRATIONS = [
    """
    CREATE TABLE votes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        jeu TEXT NOT NULL,
        panorama TEXT NOT NULL,
        vue TEXT NOT NULL,
        modele_gauche TEXT NOT NULL,
        modele_droite TEXT NOT NULL,
        essai_gauche TEXT NOT NULL,
        essai_droite TEXT NOT NULL,
        choix TEXT NOT NULL,
        votant TEXT NOT NULL,
        duree_ms INTEGER,
        note TEXT NOT NULL DEFAULT '',
        annule_id INTEGER REFERENCES votes(id),
        cree_le REAL NOT NULL
    );
    CREATE INDEX votes_jeu ON votes(jeu, panorama, vue);
    CREATE INDEX votes_votant ON votes(votant, jeu);
    CREATE TRIGGER votes_sans_modification BEFORE UPDATE ON votes
        BEGIN SELECT RAISE(ABORT, 'le journal des votes ne se modifie pas : on ajoute une ligne'); END;
    CREATE TRIGGER votes_sans_suppression BEFORE DELETE ON votes
        BEGIN SELECT RAISE(ABORT, 'le journal des votes ne se vide pas'); END;
    """,
]


class VoteRefuse(ValueError):
    pass


class Votes:
    def __init__(self, chemin: Path, horloge=time.time) -> None:
        chemin = Path(chemin)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.RLock()
        self._horloge = horloge
        self._c = sqlite3.connect(chemin, check_same_thread=False, isolation_level=None)
        self._c.row_factory = sqlite3.Row
        self._c.execute("PRAGMA journal_mode=WAL")
        with self._verrou:
            version = self._c.execute("PRAGMA user_version").fetchone()[0]
            for i in range(version, len(MIGRATIONS)):
                self._c.executescript("BEGIN;" + MIGRATIONS[i] + f"PRAGMA user_version={i + 1};COMMIT;")

    def fermer(self) -> None:
        with self._verrou:
            self._c.close()

    def voter(
        self, *, jeu: str, panorama: str, vue: str, modele_gauche: str, modele_droite: str, essai_gauche: str, essai_droite: str,
        choix: str, votant: str, duree_ms: int | None = None, note: str = "",
    ) -> int:
        if choix not in CHOIX:
            raise VoteRefuse(f"choix refusé : {choix!r} (attendu : {', '.join(CHOIX)})")
        votant = (votant or "").strip()
        if not _NOM.match(votant):
            raise VoteRefuse("nom du votant refusé (1 à 40 caractères)")
        if len(note) > 1000:
            raise VoteRefuse("la note dépasse 1000 caractères")
        with self._verrou:
            cur = self._c.execute(
                "INSERT INTO votes (jeu, panorama, vue, modele_gauche, modele_droite, essai_gauche, essai_droite, choix, votant, duree_ms, note, cree_le)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (jeu, panorama, vue, modele_gauche, modele_droite, essai_gauche, essai_droite, choix, votant, duree_ms, note, self._horloge()),
            )
            return int(cur.lastrowid)

    def annuler(self, vote_id: int, votant: str) -> int:
        """Ajoute une ligne qui annule `vote_id` ; seul son auteur peut l'annuler, et une seule fois."""
        with self._verrou:
            v = self._c.execute("SELECT * FROM votes WHERE id = ?", (vote_id,)).fetchone()
            if v is None or v["annule_id"] is not None:
                raise VoteRefuse("ce vote n'existe pas ou est lui-même une annulation")
            if v["votant"] != votant:
                raise VoteRefuse("on n'annule que ses propres votes")
            if self._c.execute("SELECT 1 FROM votes WHERE annule_id = ?", (vote_id,)).fetchone():
                raise VoteRefuse("ce vote est déjà annulé")
            cur = self._c.execute(
                "INSERT INTO votes (jeu, panorama, vue, modele_gauche, modele_droite, essai_gauche, essai_droite, choix, votant, note, annule_id, cree_le)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (v["jeu"], v["panorama"], v["vue"], v["modele_gauche"], v["modele_droite"], v["essai_gauche"], v["essai_droite"], v["choix"], votant, "annulation", vote_id, self._horloge()),
            )
            return int(cur.lastrowid)

    def valides(self, jeu: str | None = None) -> list[dict[str, Any]]:
        """Les votes en vigueur : ni les annulations, ni les votes annulés."""
        requete = (
            "SELECT * FROM votes v WHERE v.annule_id IS NULL AND NOT EXISTS (SELECT 1 FROM votes a WHERE a.annule_id = v.id)"
            + (" AND v.jeu = ?" if jeu else "") + " ORDER BY v.id"
        )
        with self._verrou:
            return [dict(r) for r in self._c.execute(requete, (jeu,) if jeu else ()).fetchall()]

    def dernier(self, votant: str, jeu: str) -> dict[str, Any] | None:
        v = [x for x in self.valides(jeu) if x["votant"] == votant]
        return v[-1] if v else None
