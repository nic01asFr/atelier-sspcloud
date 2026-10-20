"""Le registre des essais : SQLite sur le volume, source unique de ce que l'interface affiche.

- **Transitions d'état strictes** (`modeles.TRANSITIONS`) : un essai terminé ne redevient jamais « en cours ».
- **Rien ne s'écrase** : chaque essai a son identifiant (`E0001`…), sa configuration, son empreinte.
- **Les événements** (démarrage, arrêt, erreur, consultation du test) sont gardés avec leur heure : c'est la mémoire de ce qui s'est passé.
- **Reprise** : au démarrage du service, les essais « en cours » dont le processus n'existe plus passent à « interrompu »
  (le pod a été coupé, le service redémarré) au lieu de rester « en cours » pour toujours.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from laboratoire.modeles import ConfigEssai, TRANSITIONS

# Chaque entrée fait passer la base de la version i à i+1 ; `PRAGMA user_version` dit où l'on en est.
MIGRATIONS: list[str] = [
    """
    CREATE TABLE essais (
        id TEXT PRIMARY KEY,
        cree_le REAL NOT NULL,
        etat TEXT NOT NULL,
        config_json TEXT NOT NULL,
        empreinte TEXT NOT NULL,
        jeu TEXT NOT NULL,
        famille TEXT NOT NULL,
        modele TEXT NOT NULL,
        imgsz INTEGER NOT NULL,
        graine INTEGER NOT NULL,
        pli INTEGER,
        note TEXT NOT NULL DEFAULT '',
        debut REAL,
        fin REAL,
        pid INTEGER,
        code_sortie INTEGER,
        erreur TEXT,
        rappel_moyen_val REAL,
        rappel_moyen_test REAL,
        exactitude_val REAL,
        exactitude_test REAL,
        consultations_test INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX essais_etat ON essais(etat);
    CREATE INDEX essais_jeu ON essais(jeu);
    CREATE TABLE evenements (
        n INTEGER PRIMARY KEY AUTOINCREMENT,
        essai TEXT NOT NULL REFERENCES essais(id),
        ts REAL NOT NULL,
        genre TEXT NOT NULL,
        texte TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX evenements_essai ON evenements(essai, n);
    """,
]

COLONNES_MODIFIABLES = frozenset(
    {"debut", "fin", "pid", "code_sortie", "erreur", "note"}
)


class TransitionRefusee(Exception):
    """L'essai ne peut pas passer de cet état à celui-là."""


class EssaiInconnu(KeyError):
    pass


class Registre:
    def __init__(self, chemin: Path | str, horloge: Callable[[], float] = time.time) -> None:
        self.chemin = Path(chemin)
        self.chemin.parent.mkdir(parents=True, exist_ok=True)
        self._horloge = horloge
        self._verrou = threading.RLock()
        self._conn = sqlite3.connect(self.chemin, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._migrer()

    # -- base ------------------------------------------------------------

    def _migrer(self) -> None:
        with self._verrou:
            version = self._conn.execute("PRAGMA user_version").fetchone()[0]
            if version > len(MIGRATIONS):
                raise RuntimeError(
                    f"la base est en version {version}, ce laboratoire en connaît {len(MIGRATIONS)} : "
                    "elle vient d'une version plus récente"
                )
            for i in range(version, len(MIGRATIONS)):
                self._conn.executescript("BEGIN;" + MIGRATIONS[i] + f"PRAGMA user_version={i + 1};COMMIT;")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._verrou:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            else:
                self._conn.execute("COMMIT")

    def fermer(self) -> None:
        with self._verrou:
            self._conn.close()

    # -- essais ----------------------------------------------------------

    def creer_essai(self, config: ConfigEssai) -> str:
        """Met un essai en file. Rend son identifiant, `E0001`…"""
        with self._transaction() as c:
            dernier = c.execute("SELECT COALESCE(MAX(CAST(SUBSTR(id, 2) AS INTEGER)), 0) FROM essais").fetchone()[0]
            ident = f"E{dernier + 1:04d}"
            m = config.methode
            c.execute(
                "INSERT INTO essais (id, cree_le, etat, config_json, empreinte, jeu, famille, modele, imgsz, graine, pli, note)"
                " VALUES (?, ?, 'en_file', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ident, self._horloge(), config.model_dump_json(), config.empreinte(), config.jeu, m.famille, m.modele,
                 m.imgsz, config.graine, config.pli, config.note),
            )
            c.execute(
                "INSERT INTO evenements (essai, ts, genre, texte) VALUES (?, ?, 'cree', ?)",
                (ident, self._horloge(), f"jeu {config.jeu}, {m.famille}/{m.modele}, imgsz {m.imgsz}"),
            )
        return ident

    def essai(self, ident: str) -> dict[str, Any]:
        with self._verrou:
            ligne = self._conn.execute("SELECT * FROM essais WHERE id = ?", (ident,)).fetchone()
        if ligne is None:
            raise EssaiInconnu(ident)
        return self._vers_dict(ligne)

    @staticmethod
    def _vers_dict(ligne: sqlite3.Row) -> dict[str, Any]:
        d = dict(ligne)
        d["config"] = json.loads(d.pop("config_json"))
        return d

    def lister(self, etat: str | None = None, jeu: str | None = None, limite: int = 500) -> list[dict[str, Any]]:
        requete, args = "SELECT * FROM essais", []
        conditions = []
        if etat:
            conditions.append("etat = ?")
            args.append(etat)
        if jeu:
            conditions.append("jeu = ?")
            args.append(jeu)
        if conditions:
            requete += " WHERE " + " AND ".join(conditions)
        requete += " ORDER BY id DESC LIMIT ?"
        args.append(int(limite))
        with self._verrou:
            return [self._vers_dict(r) for r in self._conn.execute(requete, args).fetchall()]

    def changer_etat(self, ident: str, nouvel: str, **champs: Any) -> dict[str, Any]:
        """Fait passer l'essai à `nouvel` si la transition est permise ; `champs` : pid, code_sortie, erreur, debut, fin…"""
        inconnus = set(champs) - COLONNES_MODIFIABLES
        if inconnus:
            raise ValueError(f"colonnes non modifiables : {sorted(inconnus)}")
        with self._transaction() as c:
            ligne = c.execute("SELECT etat FROM essais WHERE id = ?", (ident,)).fetchone()
            if ligne is None:
                raise EssaiInconnu(ident)
            if nouvel not in TRANSITIONS.get(ligne["etat"], frozenset()):
                raise TransitionRefusee(f"{ident} : « {ligne['etat']} » → « {nouvel} » n'est pas permis")
            affectations = ["etat = ?"] + [f"{k} = ?" for k in champs]
            c.execute(f"UPDATE essais SET {', '.join(affectations)} WHERE id = ?", [nouvel, *champs.values(), ident])
            c.execute(
                "INSERT INTO evenements (essai, ts, genre, texte) VALUES (?, ?, ?, ?)",
                (ident, self._horloge(), nouvel, str(champs.get("erreur") or "")),
            )
        return self.essai(ident)

    def enregistrer_resultats(self, ident: str, jeu_evalue: str, rapport: dict[str, Any]) -> None:
        """Retient le rappel moyen et l'exactitude d'un essai sur `val` ou `test` (le détail complet vit dans resultats.json)."""
        if jeu_evalue not in ("val", "test"):
            raise ValueError("jeu_evalue : « val » ou « test »")
        with self._transaction() as c:
            if c.execute("SELECT 1 FROM essais WHERE id = ?", (ident,)).fetchone() is None:
                raise EssaiInconnu(ident)
            c.execute(
                f"UPDATE essais SET rappel_moyen_{jeu_evalue} = ?, exactitude_{jeu_evalue} = ? WHERE id = ?",
                (rapport.get("rappel_moyen"), rapport.get("exactitude"), ident),
            )

    def consulter_test(self, ident: str) -> int:
        """Compte une ouverture du jeu de test pour cet essai. Le test ne sert pas à choisir : on garde la trace de chaque consultation."""
        with self._transaction() as c:
            if c.execute("SELECT 1 FROM essais WHERE id = ?", (ident,)).fetchone() is None:
                raise EssaiInconnu(ident)
            c.execute("UPDATE essais SET consultations_test = consultations_test + 1 WHERE id = ?", (ident,))
            c.execute(
                "INSERT INTO evenements (essai, ts, genre, texte) VALUES (?, ?, 'test_consulte', '')",
                (ident, self._horloge()),
            )
            return c.execute("SELECT consultations_test FROM essais WHERE id = ?", (ident,)).fetchone()[0]

    def noter(self, ident: str, genre: str, texte: str = "") -> None:
        with self._transaction() as c:
            if c.execute("SELECT 1 FROM essais WHERE id = ?", (ident,)).fetchone() is None:
                raise EssaiInconnu(ident)
            c.execute("INSERT INTO evenements (essai, ts, genre, texte) VALUES (?, ?, ?, ?)", (ident, self._horloge(), genre, texte))

    def evenements(self, ident: str, depuis: int = 0) -> list[dict[str, Any]]:
        with self._verrou:
            lignes = self._conn.execute(
                "SELECT n, ts, genre, texte FROM evenements WHERE essai = ? AND n > ? ORDER BY n", (ident, depuis)
            ).fetchall()
        return [dict(r) for r in lignes]

    # -- file et reprise -------------------------------------------------

    def prochain_en_file(self) -> dict[str, Any] | None:
        with self._verrou:
            ligne = self._conn.execute("SELECT * FROM essais WHERE etat = 'en_file' ORDER BY id LIMIT 1").fetchone()
        return self._vers_dict(ligne) if ligne else None

    def en_cours(self) -> list[dict[str, Any]]:
        return self.lister(etat="en_cours")

    def reprendre_apres_arret(self, processus_vivant: Callable[[int], bool]) -> list[str]:
        """Au démarrage : les essais « en cours » dont le processus n'existe plus passent à « interrompu ».

        Sans cela, un pod coupé en plein entraînement laisserait l'essai « en cours » pour toujours, et la file bloquée derrière lui.
        """
        interrompus = []
        for e in self.en_cours():
            pid = e.get("pid")
            if pid is None or not processus_vivant(int(pid)):
                self.changer_etat(
                    e["id"], "interrompu", fin=self._horloge(), erreur="le processus n'existe plus (service ou pod redémarré)"
                )
                interrompus.append(e["id"])
        return interrompus
