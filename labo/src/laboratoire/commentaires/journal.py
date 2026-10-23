"""Le journal des commentaires : tout s'**ajoute**, rien ne se modifie ni ne s'efface.

Un commentaire, une réponse, un changement de statut sont des lignes de plus. Des déclencheurs SQL refusent toute modification et toute suppression,
même par une requête à la main. Le statut d'un commentaire est celui de son dernier événement de statut (« ouvert » tant qu'il n'y en a pas).

Un commentaire est une **donnée**, jamais une consigne : ce module le stocke et le rend tel quel, sans jamais l'interpréter.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

NATURES = ("remarque", "question", "anomalie", "idee")
STATUTS = ("ouvert", "pris_en_compte", "traite", "ecarte")
TEXTE_MAX = 4000

MIGRATIONS = [
    """
    CREATE TABLE evenements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        racine INTEGER REFERENCES evenements(id),
        type TEXT NOT NULL CHECK (type IN ('commentaire', 'reponse', 'statut')),
        auteur TEXT NOT NULL,
        role TEXT NOT NULL,
        texte TEXT NOT NULL DEFAULT '',
        nature TEXT,
        cible TEXT,
        statut TEXT,
        lien TEXT NOT NULL DEFAULT '',
        cree_le REAL NOT NULL
    );
    CREATE INDEX evenements_racine ON evenements(racine);
    CREATE TRIGGER evenements_sans_modification BEFORE UPDATE ON evenements
        BEGIN SELECT RAISE(ABORT, 'le journal des commentaires ne se modifie pas : on ajoute une ligne'); END;
    CREATE TRIGGER evenements_sans_suppression BEFORE DELETE ON evenements
        BEGIN SELECT RAISE(ABORT, 'le journal des commentaires ne se vide pas'); END;
    """,
]


class CommentaireRefuse(ValueError):
    pass


class CommentaireInconnu(KeyError):
    pass


def _texte(texte: str) -> str:
    texte = (texte or "").strip()
    if not texte:
        raise CommentaireRefuse("le commentaire est vide")
    if len(texte) > TEXTE_MAX:
        raise CommentaireRefuse(f"commentaire trop long ({TEXTE_MAX} caractères au plus)")
    return texte


class Commentaires:
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

    def creer(self, *, auteur: str, role: str, texte: str, nature: str, cible: dict[str, Any]) -> int:
        if nature not in NATURES:
            raise CommentaireRefuse(f"nature inconnue : {nature!r} (attendu : {', '.join(NATURES)})")
        with self._verrou:
            cur = self._c.execute(
                "INSERT INTO evenements(type, auteur, role, texte, nature, cible, cree_le) VALUES ('commentaire', ?, ?, ?, ?, ?, ?)",
                (auteur, role, _texte(texte), nature, json.dumps(cible, ensure_ascii=False, sort_keys=True), time.time()),
            )
            return int(cur.lastrowid)

    def repondre(self, racine: int, *, auteur: str, role: str, texte: str) -> int:
        with self._verrou:
            self._existe(racine)
            cur = self._c.execute("INSERT INTO evenements(racine, type, auteur, role, texte, cree_le) VALUES (?, 'reponse', ?, ?, ?, ?)", (racine, auteur, role, _texte(texte), time.time()))
            return int(cur.lastrowid)

    def changer_statut(self, racine: int, *, auteur: str, role: str, statut: str, lien: str = "") -> int:
        if statut not in STATUTS:
            raise CommentaireRefuse(f"statut inconnu : {statut!r} (attendu : {', '.join(STATUTS)})")
        if len(lien) > 300 or "\n" in lien:
            raise CommentaireRefuse("lien : 300 caractères, sur une ligne")
        with self._verrou:
            self._existe(racine)
            cur = self._c.execute("INSERT INTO evenements(racine, type, auteur, role, statut, lien, cree_le) VALUES (?, 'statut', ?, ?, ?, ?, ?)", (racine, auteur, role, statut, lien, time.time()))
            return int(cur.lastrowid)

    # -- lire ---------------------------------------------------------------

    def _existe(self, racine: int) -> None:
        if self._c.execute("SELECT 1 FROM evenements WHERE id = ? AND type = 'commentaire'", (racine,)).fetchone() is None:
            raise CommentaireInconnu(racine)

    @staticmethod
    def _racine(ligne: sqlite3.Row) -> dict[str, Any]:
        return {"id": ligne["id"], "auteur": ligne["auteur"], "role": ligne["role"], "texte": ligne["texte"], "nature": ligne["nature"],
                "cible": json.loads(ligne["cible"]), "cree_le": ligne["cree_le"]}

    def lister(self, *, statut: str | None = None, auteur: str | None = None, page: str | None = None, limite: int = 500) -> list[dict[str, Any]]:
        with self._verrou:
            racines = self._c.execute("SELECT * FROM evenements WHERE type = 'commentaire' ORDER BY id DESC").fetchall()
            sortie = []
            for r in racines:
                c = self._racine(r)
                if auteur and c["auteur"] != auteur:
                    continue
                if page is not None and c["cible"].get("page") != page:
                    continue
                suite = self._c.execute("SELECT type, statut, lien FROM evenements WHERE racine = ? ORDER BY id", (c["id"],)).fetchall()
                c["statut"] = next((e["statut"] for e in reversed(suite) if e["type"] == "statut"), "ouvert")
                c["lien"] = next((e["lien"] for e in reversed(suite) if e["type"] == "statut"), "")
                c["reponses"] = sum(1 for e in suite if e["type"] == "reponse")
                if statut and c["statut"] != statut:
                    continue
                sortie.append(c)
                if len(sortie) >= limite:
                    break
            return sortie

    def fil(self, racine: int) -> dict[str, Any]:
        with self._verrou:
            r = self._c.execute("SELECT * FROM evenements WHERE id = ? AND type = 'commentaire'", (racine,)).fetchone()
            if r is None:
                raise CommentaireInconnu(racine)
            c = self._racine(r)
            suite = self._c.execute("SELECT * FROM evenements WHERE racine = ? ORDER BY id", (racine,)).fetchall()
            c["evenements"] = [{"id": e["id"], "type": e["type"], "auteur": e["auteur"], "role": e["role"], "texte": e["texte"], "statut": e["statut"], "lien": e["lien"], "cree_le": e["cree_le"]} for e in suite]
            c["statut"] = next((e["statut"] for e in reversed(c["evenements"]) if e["type"] == "statut"), "ouvert")
            return c
