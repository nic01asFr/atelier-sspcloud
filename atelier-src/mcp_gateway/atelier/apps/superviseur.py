"""Le superviseur des applications : lancer, surveiller, arrêter.

L'Atelier est le seul à lancer les processus des applications, et le seul à
leur attribuer un port. Le proxy de l'hôte des applications ne connaît que ce
que ce module lui rend (`cible`) : un port qu'on n'a pas attribué n'est pas
joignable, quoi qu'écrive un manifeste ou un agent.

Ce que fait le superviseur, et pourquoi :

- Chaque application part dans sa propre session (`start_new_session`), donc
  son propre groupe de processus. L'arrêter, c'est signaler le groupe : les
  processus qu'elle a lancés à son tour (un `--reload`, des workers) partent
  avec elle au lieu de rester à tenir le port.
- Elle reçoit un environnement construit de toutes pièces, jamais une copie
  de celui du service. Celui-ci porte `ATELIER_OWNER_KEY`,
  `ATELIER_LLM_API_KEY`, `ATELIER_GITHUB_TOKEN` : une application écrite par
  un agent n'a aucune raison de les voir.
- Ses secrets viennent de `~/work/.secrets/apps/<ref>`, fichiers 0600 ; un
  fichier lisible par d'autres est refusé plutôt que lu.
- Sa sortie passe par un tube vers un journal tournant (5 Mo, deux copies) :
  une application bavarde ne remplit pas le PVC.
- Elle est sondée toutes les 0,5 s au démarrage, puis toutes les 30 s. Trois
  échecs de suite, ou la mort du processus, la font redémarrer après une
  attente qui double (1, 2, 4… s) ; au-delà de cinq redémarrages en dix
  minutes, elle passe `en_echec` et on attend un geste humain.
- Sans requête ni connexion ouverte pendant son délai d'inactivité, elle est
  arrêtée. Une WebSocket ou un flux SSE ouvert compte comme activité : le
  proxy tient le compte avec `connexion()`.
- Son état vit dans `~/work/.atelier-etat/apps.json`. Si l'Atelier meurt sans
  arrêter ses applications, le suivant retrouve les groupes orphelins et les
  tue — après avoir vérifié `/proc/<pid>/cmdline`, parce qu'un pid se
  recycle et qu'on ne tue pas un inconnu sur la foi d'un vieux fichier.
- Garde-fous du pod, qui n'a pas de zone d'échange : un plafond
  d'applications simultanées, `RLIMIT_NOFILE`, `nice 10`, et un plafond de
  mémoire résidente (1,5 Gio pour le groupe) vérifié à chaque sonde.
  `RLIMIT_RSS` n'est pas appliqué par Linux ; `RLIMIT_AS` punirait les
  runtimes qui réservent beaucoup d'adresses sans les toucher. On mesure donc.

Écrit pour Linux (le pod). Le module s'importe ailleurs, mais les primitives
POSIX qu'il emploie n'y existent pas.

L'horloge est injectable : l'inactivité et la fenêtre des redémarrages se
testent sans attendre trente minutes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterator

import httpx

from ..config import AtelierSettings
from ..artifacts import slug_valide
from .manifeste import Manifeste, nom_valide
from .secrets import SecretIllisible, lire_secret

try:  # POSIX seulement.
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]

log = logging.getLogger("atelier.apps")

# Les états qu'une application traverse.
ARRETE = "arrete"
DEMARRAGE = "demarrage"
PRET = "pret"
REDEMARRAGE = "redemarrage"
ARRET = "arret"
EN_ECHEC = "en_echec"

# SIGKILL n'existe pas hors POSIX ; là, SIGTERM termine déjà le processus.
_SIGKILL = getattr(signal, "SIGKILL", signal.SIGTERM)

# Ceux qui occupent une place sous le plafond d'applications simultanées.
_ACTIFS = frozenset({DEMARRAGE, PRET, REDEMARRAGE})


class ErreurApplication(RuntimeError):
    """Une application qu'on ne peut pas lancer, avec la raison lisible."""


class PlafondAtteint(ErreurApplication):
    """Plus de place : trop d'applications, ou plus un port libre."""


@dataclass(frozen=True)
class Cible:
    """Où joindre une application prête : un port de 127.0.0.1, ou un socket."""

    port: int | None
    socket: Path | None


@dataclass(frozen=True)
class InfoApp:
    """Ce que l'on montre d'une application : un instantané, pas l'objet vivant."""

    slug: str
    nom: str
    etat: str
    raison: str
    port: int | None
    socket: str | None
    pid: int | None
    connexions: int
    redemarrages_recents: int
    journal: str

    def en_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "nom": self.nom,
            "etat": self.etat,
            "raison": self.raison,
            "port": self.port,
            "socket": self.socket,
            "pid": self.pid,
            "connexions": self.connexions,
            "redemarrages_recents": self.redemarrages_recents,
        }


@dataclass
class _App:
    slug: str
    nom: str
    racine_projet: Path
    manifeste: Manifeste
    etat: str = ARRETE
    raison: str = ""
    port: int | None = None
    socket: Path | None = None
    argv: list[str] = field(default_factory=list)
    processus: asyncio.subprocess.Process | None = None
    pompe: asyncio.Task | None = None
    tache: asyncio.Task | None = None
    connexions: int = 0
    derniere_activite: float = 0.0
    echecs_sonde: int = 0
    redemarrages: list[float] = field(default_factory=list)
    verrou: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def cle(self) -> str:
        return f"{self.slug}/{self.nom}"

    @property
    def prefixe(self) -> str:
        return f"/{self.slug}/{self.nom}"

    @property
    def pid(self) -> int | None:
        p = self.processus
        return p.pid if p is not None and p.returncode is None else None


class _JournalTournant:
    """Un fichier de journal qui tourne à taille fixe : `x.log`, `x.log.1`…"""

    def __init__(self, chemin: Path, max_octets: int, copies: int) -> None:
        self.chemin = chemin
        self.max_octets = max_octets
        self.copies = copies
        chemin.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(chemin, "ab")  # noqa: SIM115 - tenu ouvert exprès

    def _tourner(self) -> None:
        self._f.close()
        for i in range(self.copies, 0, -1):
            source = self.chemin if i == 1 else self.chemin.with_name(f"{self.chemin.name}.{i - 1}")
            if source.exists():
                os.replace(source, self.chemin.with_name(f"{self.chemin.name}.{i}"))
        self._f = open(self.chemin, "ab")  # noqa: SIM115

    def ecrire(self, donnees: bytes) -> None:
        # Un morceau lu du tube peut dépasser ce qui reste de place : on le
        # coupe, pour que la taille promise tienne quoi qu'écrive l'application.
        while donnees:
            place = self.max_octets - self._f.tell()
            if place <= 0:
                self._tourner()
                continue
            self._f.write(donnees[:place])
            donnees = donnees[place:]
        self._f.flush()

    def note(self, texte: str) -> None:
        horodatage = time.strftime("%Y-%m-%d %H:%M:%S")
        self.ecrire(f"[atelier {horodatage}] {texte}\n".encode("utf-8"))

    def fermer(self) -> None:
        with contextlib.suppress(OSError):
            self._f.close()


def plage_de_ports(texte: str) -> range:
    """`19000-19099` (bornes comprises) ou un port seul."""
    morceaux = [m.strip() for m in texte.split("-")]
    try:
        if len(morceaux) == 1:
            debut = fin = int(morceaux[0])
        elif len(morceaux) == 2:
            debut, fin = int(morceaux[0]), int(morceaux[1])
        else:
            raise ValueError
    except ValueError:
        raise ValueError(f"plage de ports invalide : {texte!r}") from None
    if not (1024 <= debut <= fin <= 65535):
        raise ValueError(f"plage de ports invalide : {texte!r}")
    return range(debut, fin + 1)


def port_libre(port: int) -> bool:
    """Vrai si l'on peut écouter sur 127.0.0.1:port à l'instant.

    `SO_REUSEADDR` comme les serveurs qu'on lance : une connexion en
    TIME_WAIT ne rend pas un port inutilisable, un auditeur actif si.
    """
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def ligne_de_commande(pid: int) -> list[str] | None:
    """Les arguments d'un processus vivant, lus dans `/proc`."""
    try:
        brut = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    if not brut:
        return None  # zombie ou processus noyau
    return [a.decode("utf-8", "replace") for a in brut.rstrip(b"\0").split(b"\0")]


def groupe_du_processus(pid: int) -> int | None:
    """Le groupe de processus, champ 5 de `/proc/<pid>/stat`."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    champs = stat[stat.rfind(")") + 2 :].split()
    try:
        return int(champs[2])
    except (IndexError, ValueError):
        return None


def meme_commande(lue: list[str], lancee: list[str]) -> bool:
    """Vrai si `/proc` montre bien la commande qu'on a lancée.

    Un script à shebang apparaît précédé de son interpréteur, et le noyau
    remplace le nom donné à `exec` par le chemin du script : on compare donc
    la fin de la ligne, et le premier argument par son nom de base.
    """
    if not lancee or len(lue) < len(lancee):
        return False
    fin = lue[len(lue) - len(lancee) :]
    return fin[1:] == lancee[1:] and os.path.basename(fin[0]) == os.path.basename(lancee[0])


def memoire_du_groupe(pgid: int) -> int:
    """Mémoire résidente, en octets, de tous les processus du groupe."""
    page = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
    total = 0
    if not Path("/proc").is_dir():  # pragma: no cover - hors du pod
        return 0
    for entree in Path("/proc").iterdir():
        if not entree.name.isdigit():
            continue
        try:
            stat = (entree / "stat").read_text()
        except OSError:
            continue
        champs = stat[stat.rfind(")") + 2 :].split()
        try:
            if int(champs[2]) == pgid:
                total += int(champs[21]) * page
        except (IndexError, ValueError):
            continue
    return total


def _signaler_groupe(pgid: int, signal_: int) -> bool:
    try:
        if hasattr(os, "killpg"):
            os.killpg(pgid, signal_)
        else:  # pragma: no cover - hors du pod : le processus seul
            os.kill(pgid, signal_)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


class Superviseur:
    """Les applications lancées par cet Atelier, et leur surveillance."""

    def __init__(
        self,
        settings: AtelierSettings,
        *,
        horloge: Callable[[], float] = time.monotonic,
        dormir: Callable[[float], Awaitable[None]] = asyncio.sleep,
        intervalle_sonde_s: float = 30.0,
        pas_demarrage_s: float = 0.5,
        delai_sigkill_s: float = 10.0,
        attente_base_s: float = 1.0,
        redemarrages_max: int = 5,
        fenetre_redemarrages_s: float = 600.0,
        echecs_sonde_max: int = 3,
        plafond_memoire_octets: int = 3 * 2**29,  # 1,5 Gio
        fichiers_ouverts_max: int = 4096,
        gentillesse: int = 10,
        journal_max_octets: int = 5 * 2**20,
        journal_copies: int = 2,
    ) -> None:
        self.settings = settings
        self.horloge = horloge
        # L'attente avant un redémarrage, seule à dépendre de l'horloge
        # murale : injectable pour qu'un test lise la suite 1, 2, 4…
        self.dormir = dormir
        self.intervalle_sonde_s = intervalle_sonde_s
        self.pas_demarrage_s = pas_demarrage_s
        self.delai_sigkill_s = delai_sigkill_s
        self.attente_base_s = attente_base_s
        self.redemarrages_max = redemarrages_max
        self.fenetre_redemarrages_s = fenetre_redemarrages_s
        self.echecs_sonde_max = echecs_sonde_max
        self.plafond_memoire_octets = plafond_memoire_octets
        self.fichiers_ouverts_max = fichiers_ouverts_max
        self.gentillesse = gentillesse
        self.journal_max_octets = journal_max_octets
        self.journal_copies = journal_copies
        self.ports = plage_de_ports(settings.apps_ports)
        self._apps: dict[str, _App] = {}
        self._journaux: dict[str, _JournalTournant] = {}
        self._boucle: asyncio.Task | None = None

    # --- Emplacements ---------------------------------------------------

    @property
    def dossier_etat(self) -> Path:
        return self.settings.work_dir / ".atelier-etat"

    @property
    def fichier_etat(self) -> Path:
        return self.dossier_etat / "apps.json"

    @property
    def dossier_journaux(self) -> Path:
        return self.settings.work_dir / "logs" / "apps"

    @property
    def dossier_secrets(self) -> Path:
        return self.settings.secrets_dir / "apps"

    @property
    def dossier_sockets(self) -> Path:
        return self.dossier_etat / "sockets"

    def chemin_journal(self, slug: str, nom: str) -> Path:
        _verifier_nom(slug, nom)
        return self.dossier_journaux / slug / f"{nom}.log"

    # --- Consultation ----------------------------------------------------

    def _info(self, app: _App) -> InfoApp:
        return InfoApp(
            slug=app.slug,
            nom=app.nom,
            etat=app.etat,
            raison=app.raison,
            port=app.port,
            socket=str(app.socket) if app.socket else None,
            pid=app.pid,
            connexions=app.connexions,
            redemarrages_recents=len(self._redemarrages_recents(app)),
            journal=str(self.chemin_journal(app.slug, app.nom)),
        )

    def etat(self, slug: str, nom: str) -> InfoApp | None:
        app = self._apps.get(f"{slug}/{nom}")
        return self._info(app) if app else None

    def lister(self, slug: str | None = None) -> list[InfoApp]:
        return [self._info(a) for a in self._apps.values() if slug is None or a.slug == slug]

    def cible(self, slug: str, nom: str) -> Cible | None:
        """Où le proxy doit relayer, ou None si l'application n'est pas prête.

        Seul chemin par lequel le proxy apprend un port : il n'en existe pas
        d'autre que ceux qu'on a attribués.
        """
        app = self._apps.get(f"{slug}/{nom}")
        if app is None or app.etat != PRET or app.pid is None:
            return None
        return Cible(port=app.port, socket=app.socket)

    def manifeste(self, slug: str, nom: str) -> Manifeste | None:
        """Le manifeste avec lequel l'application tourne, s'il y en a une."""
        app = self._apps.get(f"{slug}/{nom}")
        return app.manifeste if app is not None else None

    def ports_attribues(self) -> set[int]:
        return {a.port for a in self._apps.values() if a.port is not None}

    def journal(self, slug: str, nom: str, lignes: int = 200) -> str:
        """Les dernières lignes du journal, copie tournée précédente comprise."""
        lignes = max(1, min(int(lignes), 5000))
        chemin = self.chemin_journal(slug, nom)
        morceaux: list[bytes] = []
        for f in (chemin.with_name(chemin.name + ".1"), chemin):
            try:
                with open(f, "rb") as flux:
                    flux.seek(0, os.SEEK_END)
                    taille = flux.tell()
                    flux.seek(max(0, taille - 2 * 2**20))
                    morceaux.append(flux.read())
            except OSError:
                continue
        texte = b"".join(morceaux).decode("utf-8", "replace")
        return "\n".join(texte.splitlines()[-lignes:])

    # --- Activité (tenue par le proxy) ------------------------------------

    def noter_activite(self, slug: str, nom: str) -> None:
        app = self._apps.get(f"{slug}/{nom}")
        if app is not None:
            app.derniere_activite = self.horloge()

    def ouvrir_connexion(self, slug: str, nom: str) -> None:
        """Une requête en cours, une WebSocket ou un flux SSE ouvert."""
        app = self._apps.get(f"{slug}/{nom}")
        if app is not None:
            app.connexions += 1
            app.derniere_activite = self.horloge()

    def fermer_connexion(self, slug: str, nom: str) -> None:
        app = self._apps.get(f"{slug}/{nom}")
        if app is not None:
            app.connexions = max(0, app.connexions - 1)
            app.derniere_activite = self.horloge()

    @contextlib.contextmanager
    def connexion(self, slug: str, nom: str) -> Iterator[None]:
        self.ouvrir_connexion(slug, nom)
        try:
            yield
        finally:
            self.fermer_connexion(slug, nom)

    # --- Démarrer / arrêter -----------------------------------------------

    async def demarrer(
        self,
        slug: str,
        nom: str,
        racine_projet: Path,
        manifeste: Manifeste,
        *,
        attendre: bool = True,
    ) -> InfoApp:
        """Démarre l'application si elle ne tourne pas.

        `attendre=False` rend la main tout de suite, en état `demarrage` : le
        proxy montre alors sa page « Démarrage… » et revient voir. Une
        application `en_echec` repart de zéro : c'est le geste humain attendu.
        """
        _verifier_nom(slug, nom)
        if manifeste.type != "service":
            raise ErreurApplication("une application statique n'a pas de processus")
        cle = f"{slug}/{nom}"
        app = self._apps.get(cle)
        if app is not None and app.etat in _ACTIFS:
            if attendre:
                await self.attendre(slug, nom)
            return self._info(app)
        if app is not None and app.tache is not None and not app.tache.done():
            await self.attendre(slug, nom)
        actifs = sum(1 for a in self._apps.values() if a.etat in _ACTIFS and a.cle != cle)
        if actifs >= self.settings.apps_max:
            raise PlafondAtteint(
                f"déjà {actifs} applications lancées (ATELIER_APPS_MAX={self.settings.apps_max})"
            )
        # Les secrets se vérifient avant tout lancement : un manquant est une
        # erreur à montrer, pas une boucle de redémarrages.
        self._lire_secrets(manifeste)
        if app is None:
            app = _App(slug=slug, nom=nom, racine_projet=racine_projet, manifeste=manifeste)
            self._apps[cle] = app
        else:
            app.racine_projet = racine_projet
            app.manifeste = manifeste
        app.etat = DEMARRAGE
        app.raison = ""
        app.redemarrages = []
        app.derniere_activite = self.horloge()
        app.tache = asyncio.create_task(self._demarrage_initial(app))
        if attendre:
            await self.attendre(slug, nom)
        return self._info(app)

    async def attendre(self, slug: str, nom: str) -> InfoApp | None:
        """Attend la fin d'une transition en cours (démarrage, redémarrage)."""
        app = self._apps.get(f"{slug}/{nom}")
        if app is None:
            return None
        while app.tache is not None and not app.tache.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(app.tache)
        return self._info(app)

    async def arreter(self, slug: str, nom: str, *, raison: str = "arrêt demandé") -> InfoApp | None:
        app = self._apps.get(f"{slug}/{nom}")
        if app is None:
            return None
        courante = asyncio.current_task()
        if app.tache is not None and not app.tache.done() and app.tache is not courante:
            app.tache.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await app.tache
        async with app.verrou:
            app.etat = ARRET
            await self._tuer(app, raison)
            app.etat = ARRETE
            app.raison = raison
            app.connexions = 0
        self._ecrire_etat()
        return self._info(app)

    async def arreter_tout(self) -> None:
        await asyncio.gather(
            *(self.arreter(a.slug, a.nom, raison="arrêt de l'Atelier") for a in list(self._apps.values())),
            return_exceptions=True,
        )

    # --- Boucle de surveillance ------------------------------------------

    def lancer(self) -> None:
        """Démarre la surveillance périodique (à appeler dans le `lifespan`)."""
        if self._boucle is None or self._boucle.done():
            self._boucle = asyncio.create_task(self._tourner())

    async def fermer(self) -> None:
        """Arrête la surveillance, puis toutes les applications."""
        if self._boucle is not None:
            self._boucle.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._boucle
            self._boucle = None
        await self.arreter_tout()
        for j in self._journaux.values():
            j.fermer()
        self._journaux.clear()

    async def _tourner(self) -> None:
        while True:
            await asyncio.sleep(self.intervalle_sonde_s)
            try:
                await self.superviser_une_fois()
            except Exception:  # la surveillance ne doit jamais mourir
                log.exception("surveillance des applications")

    async def superviser_une_fois(self) -> None:
        """Un passage : morts, inactivité, mémoire, santé."""
        for app in list(self._apps.values()):
            if app.tache is not None and not app.tache.done():
                continue  # transition en cours, elle se surveille elle-même
            if app.etat != PRET:
                continue
            processus = app.processus
            if processus is None or processus.returncode is not None:
                code = None if processus is None else processus.returncode
                self._planifier_redemarrage(app, f"processus arrêté (code {code})")
                continue
            delai_s = (app.manifeste.inactivite_min or self.settings.apps_idle_minutes) * 60
            if app.connexions == 0 and self.horloge() - app.derniere_activite >= delai_s:
                await self.arreter(app.slug, app.nom, raison="inactivité")
                continue
            memoire = memoire_du_groupe(processus.pid)
            if memoire > self.plafond_memoire_octets:
                self._planifier_redemarrage(
                    app, f"mémoire {memoire // 2**20} Mio au-delà du plafond"
                )
                continue
            if await self._sonder(app):
                app.echecs_sonde = 0
            else:
                app.echecs_sonde += 1
                if app.echecs_sonde >= self.echecs_sonde_max:
                    self._planifier_redemarrage(
                        app, f"{app.echecs_sonde} sondes de santé échouées"
                    )

    # --- Mécanique -------------------------------------------------------

    def _redemarrages_recents(self, app: _App) -> list[float]:
        maintenant = self.horloge()
        return [t for t in app.redemarrages if maintenant - t < self.fenetre_redemarrages_s]

    def _planifier_redemarrage(self, app: _App, raison: str) -> None:
        app.etat = REDEMARRAGE
        app.raison = raison
        app.tache = asyncio.create_task(self._redemarrer(app, raison))

    async def _demarrage_initial(self, app: _App) -> None:
        async with app.verrou:
            try:
                pret = await self._lancer_et_attendre(app)
            except Exception as exc:  # jamais d'application coincée en `demarrage`
                log.exception("démarrage de %s", app.cle)
                app.raison = f"erreur interne : {exc}"
                pret = False
            if not pret:
                await self._tuer(app, "échec du démarrage")
                app.etat = EN_ECHEC
                self._ecrire_etat()

    async def _redemarrer(self, app: _App, raison: str) -> None:
        async with app.verrou:
            try:
                await self._boucle_de_redemarrage(app, raison)
            except Exception as exc:
                log.exception("redémarrage de %s", app.cle)
                await self._tuer(app, "erreur interne")
                app.etat = EN_ECHEC
                app.raison = f"erreur interne : {exc}"
                self._ecrire_etat()

    async def _boucle_de_redemarrage(self, app: _App, raison: str) -> None:
        self._journal(app).note(f"redémarrage : {raison}")
        # Toujours par le groupe : le chef mort, ses descendants peuvent
        # encore tenir le port.
        await self._tuer(app, raison)
        while True:
            app.redemarrages = self._redemarrages_recents(app)
            if len(app.redemarrages) >= self.redemarrages_max:
                app.etat = EN_ECHEC
                app.raison = (
                    f"{len(app.redemarrages)} redémarrages en "
                    f"{int(self.fenetre_redemarrages_s // 60)} min ; dernier motif : {raison}"
                )
                self._journal(app).note(app.raison)
                await self._tuer(app, "en échec")
                self._ecrire_etat()
                return
            app.redemarrages.append(self.horloge())
            app.etat = REDEMARRAGE
            await self.dormir(self.attente_base_s * 2 ** (len(app.redemarrages) - 1))
            if await self._lancer_et_attendre(app):
                return
            raison = app.raison or "échec du démarrage"
            await self._tuer(app, raison)

    async def _lancer_et_attendre(self, app: _App) -> bool:
        """Lance le processus puis sonde jusqu'à `demarrage_s`. Vrai si prêt."""
        try:
            await self._lancer(app)
        except (ErreurApplication, ValueError) as exc:  # ValueError : ManifesteInvalide
            app.raison = str(exc)
            self._journal(app).note(str(exc))
            return False
        try:
            pret = await self._attendre_sante(app)
        except asyncio.CancelledError:
            await self._tuer(app, "démarrage interrompu")
            raise
        if pret:
            app.etat = PRET
            app.raison = ""
            app.echecs_sonde = 0
            app.derniere_activite = self.horloge()
            self._journal(app).note(f"prête (pid {app.pid})")
        return pret

    async def _lancer(self, app: _App) -> None:
        m = app.manifeste
        repertoire = m.dossier_de_travail(app.racine_projet, app.nom)
        if m.ecoute == "unix":
            self.dossier_sockets.mkdir(parents=True, exist_ok=True)
            app.socket = self.dossier_sockets / f"{app.slug}__{app.nom}.sock"
            with contextlib.suppress(FileNotFoundError):
                app.socket.unlink()
            app.port = None
        else:
            app.socket = None
            app.port = self._attribuer_port()
        app.argv = m.arguments(
            port=app.port, prefixe=app.prefixe, projet=app.racine_projet.resolve(), socket=app.socket
        )
        env = self._environnement(app)
        journal = self._journal(app)
        journal.note("lancement : " + " ".join(app.argv))
        try:
            app.processus = await asyncio.create_subprocess_exec(
                *app.argv,
                cwd=str(repertoire),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
                preexec_fn=self._limites(),
            )
        except (OSError, ValueError) as exc:
            app.port = None
            raise ErreurApplication(f"lancement impossible : {exc}") from None
        app.pompe = asyncio.create_task(self._pomper(app.processus, journal))
        self._ecrire_etat()

    def _limites(self) -> Callable[[], None] | None:
        """Ce que le processus s'impose avant `exec` (dans l'enfant)."""
        if resource is None:
            return None
        fichiers = self.fichiers_ouverts_max
        gentillesse = self.gentillesse

        def appliquer() -> None:
            _, dur = resource.getrlimit(resource.RLIMIT_NOFILE)
            plafond = fichiers if dur == resource.RLIM_INFINITY else min(fichiers, dur)
            resource.setrlimit(resource.RLIMIT_NOFILE, (plafond, plafond))
            if gentillesse:
                os.nice(gentillesse)

        return appliquer

    def _attribuer_port(self) -> int:
        pris = self.ports_attribues()
        for port in self.ports:
            if port not in pris and port_libre(port):
                return port
        raise PlafondAtteint(f"aucun port libre dans {self.settings.apps_ports}")

    def _lire_secrets(self, m: Manifeste) -> dict[str, str]:
        valeurs: dict[str, str] = {}
        for variable, ref in m.secrets.items():
            try:
                valeurs[variable] = lire_secret(self.dossier_secrets, ref)
            except SecretIllisible as exc:
                raise ErreurApplication(str(exc)) from None
        return valeurs

    def _environnement(self, app: _App) -> dict[str, str]:
        """L'environnement de l'application, construit variable par variable.

        Rien n'est recopié en bloc de celui du service : ce qui n'est pas
        nommé ici n'existe pas pour l'application.
        """
        chemin = os.environ.get("PATH") or os.defpath
        env = {
            "PATH": chemin,
            "HOME": os.environ.get("HOME") or str(Path.home()),
            "LANG": os.environ.get("LANG") or "C.UTF-8",
            # Sans quoi une application Python garde sa sortie en tampon, et
            # le journal reste vide quand on en a besoin.
            "PYTHONUNBUFFERED": "1",
        }
        if os.name == "nt":  # pragma: no cover - hors du pod, pour les essais locaux
            # Sans elle, Python sous Windows n'ouvre même pas une socket.
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        venv = app.racine_projet / ".venv"
        if (venv / "bin").is_dir():
            env["VIRTUAL_ENV"] = str(venv)
            env["PATH"] = f"{venv / 'bin'}{os.pathsep}{chemin}"
        env.update(app.manifeste.env)
        env.update(self._lire_secrets(app.manifeste))
        if app.port is not None:
            env["PORT"] = str(app.port)
        env["ATELIER_APP_PREFIX"] = app.prefixe
        public = self.settings.apps_public_url.rstrip("/")
        env["ATELIER_APP_URL"] = f"{public}{app.prefixe}/" if public else ""
        env["ATELIER_APP_NOM"] = app.nom
        return env

    def _journal(self, app: _App) -> _JournalTournant:
        j = self._journaux.get(app.cle)
        if j is None:
            j = _JournalTournant(
                self.chemin_journal(app.slug, app.nom), self.journal_max_octets, self.journal_copies
            )
            self._journaux[app.cle] = j
        return j

    @staticmethod
    async def _pomper(processus: asyncio.subprocess.Process, journal: _JournalTournant) -> None:
        flux = processus.stdout
        if flux is None:
            return
        while True:
            morceau = await flux.read(65536)
            if not morceau:
                return
            try:
                journal.ecrire(morceau)
            except OSError:
                log.warning("journal d'application illisible : %s", journal.chemin)

    async def _sonder(self, app: _App) -> bool:
        m = app.manifeste
        try:
            if m.sante is None:
                if app.socket is not None:
                    _, ecriture = await asyncio.wait_for(asyncio.open_unix_connection(str(app.socket)), 2)
                else:
                    _, ecriture = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", app.port), 2)
                ecriture.close()
                with contextlib.suppress(Exception):
                    await ecriture.wait_closed()
                return True
            # Une application qui garde son préfixe l'attend aussi sur sa sonde.
            chemin = (app.prefixe + m.sante) if m.chemin == "garde" else m.sante
            if app.socket is not None:
                transport = httpx.AsyncHTTPTransport(uds=str(app.socket))
                url = f"http://localhost{chemin}"
            else:
                transport = httpx.AsyncHTTPTransport()
                url = f"http://127.0.0.1:{app.port}{chemin}"
            async with httpx.AsyncClient(transport=transport, timeout=2.0, trust_env=False) as client:
                reponse = await client.get(url)
            return 200 <= reponse.status_code < 400
        except (OSError, asyncio.TimeoutError, httpx.HTTPError):
            return False

    async def _attendre_sante(self, app: _App) -> bool:
        boucle = asyncio.get_running_loop()
        echeance = boucle.time() + app.manifeste.demarrage_s
        while True:
            processus = app.processus
            if processus is None or processus.returncode is not None:
                code = None if processus is None else processus.returncode
                app.raison = f"arrêtée pendant le démarrage (code {code})"
                return False
            if await self._sonder(app):
                return True
            if boucle.time() >= echeance:
                app.raison = f"pas prête après {app.manifeste.demarrage_s} s"
                self._journal(app).note(app.raison)
                return False
            await asyncio.sleep(self.pas_demarrage_s)

    async def _tuer(self, app: _App, raison: str) -> None:
        """SIGTERM au groupe, SIGKILL s'il tient encore après le délai."""
        processus = app.processus
        if processus is not None:
            pgid = processus.pid  # chef de sa propre session
            if processus.returncode is None:
                self._journal(app).note(f"arrêt : {raison}")
                _signaler_groupe(pgid, signal.SIGTERM)
                try:
                    await asyncio.wait_for(processus.wait(), self.delai_sigkill_s)
                except asyncio.TimeoutError:
                    self._journal(app).note(f"toujours là après {self.delai_sigkill_s:g} s : SIGKILL")
                    _signaler_groupe(pgid, _SIGKILL)
                    await processus.wait()
            # Le chef parti, des descendants peuvent rester dans le groupe et
            # tenir le port ou le tube du journal.
            _signaler_groupe(pgid, _SIGKILL)
        await self._liberer(app)

    async def _liberer(self, app: _App) -> None:
        if app.pompe is not None:
            try:
                await asyncio.wait_for(app.pompe, 2)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                app.pompe.cancel()
            app.pompe = None
        processus = app.processus
        if processus is not None and processus.returncode is not None:
            app.processus = None
        app.port = None
        if app.socket is not None:
            with contextlib.suppress(OSError):
                app.socket.unlink()
            app.socket = None
        self._ecrire_etat()

    # --- État persistant et orphelins -----------------------------------

    def _ecrire_etat(self) -> None:
        vivantes = {}
        for app in self._apps.values():
            if app.pid is None:
                continue
            vivantes[app.cle] = {
                "pid": app.pid,
                "pgid": app.pid,
                "argv": app.argv,
                "port": app.port,
                "socket": str(app.socket) if app.socket else None,
                "lance_a": time.time(),
            }
        self.dossier_etat.mkdir(parents=True, exist_ok=True)
        provisoire = self.fichier_etat.with_suffix(".json.tmp")
        provisoire.write_text(json.dumps({"version": 1, "apps": vivantes}, indent=2), encoding="utf-8")
        os.replace(provisoire, self.fichier_etat)

    async def nettoyer_orphelins(self) -> list[int]:
        """Tue les groupes laissés par un Atelier précédent ; rend leurs pid.

        À appeler au démarrage, avant tout lancement. Un pid n'est signalé
        que si `/proc` montre la commande enregistrée et le groupe attendu :
        sinon il a été recyclé, et ce processus-là n'est pas à nous.
        """
        try:
            donnees = json.loads(self.fichier_etat.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        tues: list[int] = []
        for cle, entree in (donnees.get("apps") or {}).items():
            try:
                pid, pgid, argv = int(entree["pid"]), int(entree["pgid"]), list(entree["argv"])
            except (KeyError, TypeError, ValueError):
                continue
            lue = ligne_de_commande(pid)
            if lue is None or not meme_commande(lue, argv) or groupe_du_processus(pid) != pgid:
                log.info("orphelin %s (pid %s) ignoré : ce n'est plus notre processus", cle, pid)
                continue
            log.warning("orphelin %s (pid %s) : arrêt du groupe", cle, pid)
            _signaler_groupe(pgid, signal.SIGTERM)
            echeance = time.monotonic() + self.delai_sigkill_s
            while time.monotonic() < echeance and ligne_de_commande(pid) is not None:
                await asyncio.sleep(0.1)
            _signaler_groupe(pgid, _SIGKILL)
            tues.append(pid)
            sock = entree.get("socket")
            if sock:
                with contextlib.suppress(OSError):
                    Path(sock).unlink()
        self._ecrire_etat()
        return tues


def _verifier_nom(slug: str, nom: str) -> None:
    # La forme des slugs de l'Atelier : jamais `.` ni `..`, jamais de barre.
    if not slug_valide(slug) or not nom_valide(nom):
        raise ErreurApplication(f"application invalide : {slug!r}/{nom!r}")
