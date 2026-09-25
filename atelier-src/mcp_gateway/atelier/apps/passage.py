"""Passer de l'Atelier à l'hôte des applications sans y porter la session.

Les deux hôtes sont deux origines, et c'est voulu : le cookie de l'Atelier
(`__Host-atelier_session`) ne part jamais vers celui des applications, et
réciproquement. Il faut donc un passage. Il se fait par un code :

1. l'interface de l'Atelier (session owner) demande à ouvrir un artefact
   `{slug}/{nom}` ;
2. l'Atelier tire un code de 32 octets, gardé en mémoire soixante secondes,
   d'usage unique, lié à la session owner, à la portée (le projet) et à la
   destination ;
3. il renvoie le navigateur vers `https://apps…/_atelier/entree?code=…` ;
4. l'hôte des applications consomme le code et pose sa propre session,
   `__Host-atelier_apps`, qui ne vaut que pour les projets qu'on lui a
   ouverts.

Une session d'applications n'a pas de vie propre : elle ne vaut que tant que
la session owner qui l'a ouverte vaut. Fermer celle-ci, ou faire tourner la
clé (qui les ferme toutes), ferme les sessions d'applications qui en
dépendent — la jointure le garantit à chaque lecture, sans ménage à faire.

**Le passage d'agent** (décision J-h). Le navigateur d'un agent doit pouvoir
ouvrir les créations de son projet, pour les vérifier après les avoir
modifiées. Il n'a pas, et ne doit jamais avoir, le cookie de l'Atelier. L'outil
`atelier_navigateur_ouvrir` émet donc un code d'agent :

- lié à un acteur (`agent:<conversation>`), non à une session owner ;
- borné au seul projet de la conversation ;
- de courte durée (deux minutes pour le code, une heure pour la session) ;
- d'usage unique, comme l'autre.

Le navigateur de l'agent le consomme à `/_atelier/entree` et reçoit une
session d'applications à lui, qui ne s'élargit jamais : ni par un autre code
d'agent, ni par un code owner. Cette session ne vaut que sur l'hôte des
applications : l'Atelier ne lit pas ce cookie.
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import unquote

from mcp_gateway.atelier.artifacts import slug_valide
from mcp_gateway.db import connect

COOKIE_APPS = "__Host-atelier_apps"

DUREE_CODE_S = 60
DUREE_SESSION_S = 12 * 3600
# Le passage d'agent : un code qu'un modèle recopie dans son navigateur (le
# temps d'un appel d'outil), et une session le temps d'une vérification.
DUREE_CODE_AGENT_S = 120
DUREE_SESSION_AGENT_S = 3600
PREFIXE_AGENT = "agent:"
_ACTEUR = re.compile(r"^agent:[A-Za-z0-9._-]{1,120}$")

_CONTROLE = re.compile(r"[\x00-\x1f\x7f\\]")


def portee_valide(portee: str) -> bool:
    """Une portée est un projet : le slug de ses artefacts sur l'hôte.

    Tous les artefacts d'un même projet sont d'un même domaine de confiance
    (docs/atelier-applications.md, principe 5) ; la portée sépare les
    projets, et borne la destination d'un code.
    """
    return slug_valide(portee or "")


def portee_du_chemin(chemin: str) -> str | None:
    """La portée qu'une adresse de l'hôte des applications demande."""
    tete = chemin.lstrip("/").split("/", 1)[0]
    return tete if tete and not tete.startswith("_") and portee_valide(tete) else None


def destination_valide(destination: str, portee: str) -> bool:
    """Un chemin de cet hôte, sous la portée ouverte — jamais une autre adresse.

    Commence par une seule barre (`//ailleurs` serait un autre hôte pour le
    navigateur), ne porte ni contrôle ni barre inverse, et reste sous la
    portée : un code ouvert pour un projet ne mène pas à un autre.
    """
    if not destination.startswith("/") or destination.startswith("//"):
        return False
    if _CONTROLE.search(destination):
        return False
    chemin = destination.split("?", 1)[0].split("#", 1)[0]
    # `/demo/../autre/` commence bien par `/demo/`, mais le navigateur y lit
    # `/autre/` : aucun segment `.` ou `..`, encodé ou non.
    segments = [unquote(x) for x in chemin.split("/")]
    if any(x in (".", "..") for x in segments):
        return False
    return chemin == f"/{portee}" or chemin.startswith(f"/{portee}/")


def acteur_valide(acteur: str) -> bool:
    """`agent:<conversation>` : de quoi l'écrire au journal, rien d'autre."""
    return bool(_ACTEUR.match(acteur or ""))


@dataclass(frozen=True)
class Code:
    parent_sid: str
    portee: str
    destination: str
    expire: float
    # Vide pour un code owner ; `agent:<conversation>` pour un code d'agent.
    acteur: str = ""


@dataclass(frozen=True)
class SessionApps:
    id: str
    parent_sid: str
    portees: frozenset[str]
    expire: float
    acteur: str = ""

    @property
    def est_agent(self) -> bool:
        return bool(self.acteur)

    def couvre(self, portee: str) -> bool:
        return portee in self.portees


class Passage:
    """Les codes de passage (en mémoire) et les sessions d'applications (en base)."""

    def __init__(self, db_path: Path, *, horloge: Callable[[], float] = time.time) -> None:
        self.db_path = db_path
        self.horloge = horloge
        self._codes: dict[str, Code] = {}
        self._verrou = threading.Lock()
        conn = self._base()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_sessions (
                    id TEXT PRIMARY KEY,
                    parent_sid TEXT NOT NULL,
                    portee TEXT NOT NULL DEFAULT '[]',
                    expire REAL NOT NULL,
                    created_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            colonnes = {r[1] for r in conn.execute("PRAGMA table_info(app_sessions)").fetchall()}
            if "acteur" not in colonnes:
                conn.execute("ALTER TABLE app_sessions ADD COLUMN acteur TEXT NOT NULL DEFAULT ''")
            conn.commit()
        finally:
            conn.close()

    def _base(self) -> sqlite3.Connection:
        from mcp_gateway.auth import migrate_auth_schema

        conn = connect(self.db_path)
        migrate_auth_schema(conn)
        return conn

    # ── Codes ─────────────────────────────────────────────────────────

    def emettre_code(self, parent_sid: str, portee: str, destination: str) -> str:
        if not parent_sid:
            raise ValueError("une session owner est nécessaire")
        if not portee_valide(portee):
            raise ValueError(f"portée invalide : {portee!r}")
        if not destination_valide(destination, portee):
            raise ValueError(f"destination invalide : {destination!r}")
        code = secrets.token_urlsafe(32)
        maintenant = self.horloge()
        with self._verrou:
            for cle in [c for c, v in self._codes.items() if v.expire <= maintenant]:
                del self._codes[cle]
            self._codes[code] = Code(parent_sid, portee, destination, maintenant + DUREE_CODE_S)
        return code

    def emettre_code_agent(self, acteur: str, portee: str, destination: str) -> str:
        """Un code pour le navigateur d'un agent : un projet, deux minutes, un acteur.

        Aucune session owner n'y est liée : le code ne peut donc rien élargir
        de ce que la personne a ouvert, et la session qu'il ouvre ne dépend que
        de sa propre échéance.
        """
        if not acteur_valide(acteur):
            raise ValueError(f"acteur invalide : {acteur!r}")
        if not portee_valide(portee):
            raise ValueError(f"portée invalide : {portee!r}")
        if not destination_valide(destination, portee):
            raise ValueError(f"destination invalide : {destination!r}")
        code = secrets.token_urlsafe(32)
        maintenant = self.horloge()
        with self._verrou:
            for cle in [c for c, v in self._codes.items() if v.expire <= maintenant]:
                del self._codes[cle]
            self._codes[code] = Code("", portee, destination, maintenant + DUREE_CODE_AGENT_S, acteur)
        return code

    def consommer_code(self, code: str) -> Code | None:
        """Le code s'il est connu et frais ; il ne sert qu'une fois, même raté."""
        with self._verrou:
            trouve = self._codes.pop(code or "", None)
        if trouve is None or trouve.expire <= self.horloge():
            return None
        return trouve

    # ── Sessions ──────────────────────────────────────────────────────

    def session(self, sid: str | None) -> SessionApps | None:
        """La session d'applications, si elle vaut encore — elle et sa mère."""
        if not sid:
            return None
        maintenant = self.horloge()
        conn = self._base()
        try:
            # Une session owner vit tant que sa mère vit ; une session d'agent
            # n'a pas de mère, seulement sa propre échéance, courte.
            ligne = conn.execute(
                """
                SELECT a.id, a.parent_sid, a.portee, a.expire, a.acteur
                FROM app_sessions a LEFT JOIN oauth_sessions o ON o.sid = a.parent_sid
                WHERE a.id = ? AND a.expire > ?
                  AND ((a.acteur = '' AND o.expires_at > ?) OR a.acteur != '')
                """,
                (sid, maintenant, maintenant),
            ).fetchone()
        finally:
            conn.close()
        if ligne is None:
            return None
        try:
            portees = frozenset(str(p) for p in json.loads(ligne["portee"] or "[]"))
        except ValueError:
            portees = frozenset()
        return SessionApps(
            ligne["id"], ligne["parent_sid"], portees, float(ligne["expire"]), ligne["acteur"] or ""
        )

    def ouvrir(self, code: Code, sid_actuel: str | None = None) -> SessionApps:
        """La session que le code ouvre, ou celle qu'on a déjà, élargie.

        Un seul cookie par hôte : ouvrir une deuxième application ne doit pas
        fermer la première. Si le navigateur porte déjà une session née de la
        même session owner, on y ajoute la portée ; sinon on en ouvre une.
        """
        actuelle = self.session(sid_actuel)
        conn = self._base()
        try:
            if code.acteur:
                return self._ouvrir_agent(conn, code)
            # Une session d'agent ne s'élargit jamais, et un code owner n'en
            # fait pas une session owner : on en ouvre une neuve.
            if (
                actuelle is not None
                and not actuelle.est_agent
                and actuelle.parent_sid == code.parent_sid
            ):
                portees = sorted(actuelle.portees | {code.portee})
                conn.execute(
                    "UPDATE app_sessions SET portee = ? WHERE id = ?",
                    (json.dumps(portees), actuelle.id),
                )
                conn.commit()
                return SessionApps(actuelle.id, actuelle.parent_sid, frozenset(portees), actuelle.expire)
            sid = secrets.token_urlsafe(32)
            expire = self.horloge() + DUREE_SESSION_S
            conn.execute(
                "INSERT INTO app_sessions (id, parent_sid, portee, expire) VALUES (?, ?, ?, ?)",
                (sid, code.parent_sid, json.dumps([code.portee]), expire),
            )
            # Le ménage des sessions mortes, au passage.
            self._menage(conn)
            conn.commit()
            return SessionApps(sid, code.parent_sid, frozenset([code.portee]), expire)
        finally:
            conn.close()

    def _ouvrir_agent(self, conn: sqlite3.Connection, code: Code) -> SessionApps:
        """Une session neuve, un seul projet, une heure : jamais une session élargie."""
        sid = secrets.token_urlsafe(32)
        expire = self.horloge() + DUREE_SESSION_AGENT_S
        conn.execute(
            "INSERT INTO app_sessions (id, parent_sid, portee, expire, acteur) VALUES (?, '', ?, ?, ?)",
            (sid, json.dumps([code.portee]), expire, code.acteur),
        )
        self._menage(conn)
        conn.commit()
        return SessionApps(sid, "", frozenset([code.portee]), expire, code.acteur)

    def _menage(self, conn: sqlite3.Connection) -> None:
        """Les sessions mortes, au passage : échues, ou nées d'une session owner fermée."""
        conn.execute(
            """
            DELETE FROM app_sessions WHERE expire <= ?
               OR (acteur = '' AND parent_sid NOT IN (SELECT sid FROM oauth_sessions))
            """,
            (self.horloge(),),
        )

    def fermer_pour(self, parent_sid: str | None) -> int:
        """Ferme les sessions d'applications nées d'une session owner."""
        if not parent_sid:
            return 0
        conn = self._base()
        try:
            n = conn.execute(
                "DELETE FROM app_sessions WHERE acteur = '' AND parent_sid = ?", (parent_sid,)
            ).rowcount
            conn.commit()
            return n
        finally:
            conn.close()

    def fermer_tout(self) -> int:
        with self._verrou:
            self._codes.clear()
        conn = self._base()
        try:
            n = conn.execute("DELETE FROM app_sessions").rowcount
            conn.commit()
            return n
        finally:
            conn.close()
