"""L'écran en direct du navigateur d'une conversation (P5, décisions J-f2 et U1).

Chaque conversation a son `chrome-devtools-mcp`, lancé par
`~/work/bin/atelier-chrome`, et son Chrome, que le serveur pilote par un tube.
Le lanceur fait ouvrir à ce Chrome, en plus, un port de débogage sur
127.0.0.1 ; le filtre `atelier-chrome-onglets.mjs` publie l'association
conversation -> port dans `<racine>/ecrans/<conversation>.json` (0600), avec
la page que l'agent a sélectionnée et le nombre de ses actions en attente
(`docs/navigateur-atelier.md`, « Écran en direct »).

Ce module est l'autre bout :

- il **se rattache en CDP** au Chrome d'une conversation
  (`ws://127.0.0.1:<port>/devtools/browser/<id>`, jamais une autre adresse),
  suit la page sélectionnée par l'agent (`Target.*`) et en diffuse le
  **screencast** (`Page.startScreencast`, JPEG, cadence bornée par
  l'acquittement des images) ;
- il ne tourne **que si quelqu'un regarde** : au départ du dernier
  spectateur, la connexion CDP se ferme et le screencast avec elle ;
- il porte **« Prendre la main »** : clics, molette, clavier et adresse,
  envoyés par `Input.dispatch*` et `Page.navigate`, seulement pendant que la
  personne a la main. Pendant ce temps, le filtre retient les actions de
  l'agent (fichier `<racine>/main/<conversation>.json`) ; « Rendre la main »
  les libère avec une note qui dit ce qui a changé, ou relance l'agent par un
  message quand aucun de ses tours n'est en cours.

Le flux passe par l'hôte des applications (`/_ecran/<conversation>/flux`, en
portée `conversation:<id>`, voir `apps.passage`). Il ne relaie pas le
protocole DevTools : la page ne reçoit que des images JPEG et un état (adresse,
titre, main), et n'envoie que des gestes validés ici. Ni le port, ni le chemin
du point d'entrée, ni aucune commande CDP ne passent du côté du navigateur de
la personne : relayer le protocole brut lui aurait donné tout le navigateur de
l'agent (scripts, cookies de tous les sites).

Limite connue (U1) : tout processus du pod, sous le même compte, peut piloter
ce Chrome par son port, comme il peut déjà lire `~/work`.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import secrets
import stat
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

import websockets
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState
from websockets.asyncio.client import connect

from mcp_gateway.atelier.apps.passage import conversation_valide
from mcp_gateway.atelier.navigateur import racine_des_navigateurs

log = logging.getLogger("atelier.ecran")

VERSION_FICHE = 1
_CHEMIN_CDP = re.compile(r"^/devtools/browser/[A-Za-z0-9-]{1,80}$")

# Le screencast : une image acquittée au plus toutes les 1/CADENCE s. Chrome
# n'envoie l'image suivante qu'après l'acquittement de la précédente : retarder
# l'acquittement règle la cadence sans rien perdre d'autre que des images.
CADENCE_IPS = 8.0
QUALITE_JPEG = 60
LARGEUR_MAX = 1280
HAUTEUR_MAX = 800
# Relire la fiche du filtre (page sélectionnée, attente) à ce rythme.
RELECTURE_S = 0.5
# Réessayer de joindre un Chrome absent ou reparti.
REESSAI_S = 1.0
CDP_DELAI_S = 10.0
TAILLE_MAX_CDP = 32 * 2**20
# La personne qui quitte l'écran sans rendre la main la rend au bout de ce délai.
MAIN_ABANDON_S = 300.0
# Un message de la page au-delà de cette taille n'est pas lu.
MESSAGE_MAX = 8192

BOUTONS = {"gauche": "left", "milieu": "middle", "droit": "right", "aucun": "none"}
SOURIS = {"presse": "mousePressed", "relache": "mouseReleased", "bouge": "mouseMoved", "molette": "mouseWheel"}


class EcranIndisponible(RuntimeError):
    """Aucun navigateur ouvert pour cette conversation."""


class ErreurCdp(RuntimeError):
    """Chrome a répondu par une erreur."""


# ── Fichiers partagés avec le filtre ────────────────────────────────────────


@dataclass(frozen=True)
class Fiche:
    """Ce que le filtre publie d'un navigateur. Le port ne sort jamais d'ici."""

    cle: str
    port: int
    chemin: str
    pid: int
    page: dict[str, Any] | None
    attente: int

    @property
    def adresse_cdp(self) -> str:
        return f"ws://127.0.0.1:{self.port}{self.chemin}"


def _fichier_a_soi(chemin: Path) -> bool:
    """Un fichier ordinaire, à ce compte, que personne d'autre ne lit (sous Unix)."""
    try:
        st = chemin.lstat()
    except OSError:
        return False
    if not stat.S_ISREG(st.st_mode):
        return False
    if os.name == "posix":
        if st.st_uid != os.getuid() or st.st_mode & 0o077:
            return False
    return True


def _vivant(pid: int) -> bool:
    """Le processus existe et appartient à ce compte. Sans objet hors Unix."""
    if os.name != "posix":
        # `os.kill(pid, 0)` y terminerait le processus : on ne vérifie pas.
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False
    return True


def lire_fiche(racine: Path, cle: str) -> Fiche | None:
    """La fiche d'écran d'une conversation, si elle est sûre et vivante."""
    if not conversation_valide(cle):
        return None
    chemin = racine / "ecrans" / f"{cle}.json"
    if not _fichier_a_soi(chemin):
        return None
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(brut, dict) or brut.get("version") != VERSION_FICHE or brut.get("conversation") != cle:
        return None
    port, chemin_cdp, pid = brut.get("port"), brut.get("chemin"), brut.get("pid")
    if not isinstance(port, int) or not 0 < port < 65536:
        return None
    if not isinstance(chemin_cdp, str) or not _CHEMIN_CDP.match(chemin_cdp):
        return None
    if not isinstance(pid, int) or pid <= 0 or not _vivant(pid):
        return None
    page = brut.get("page")
    if isinstance(page, dict):
        page = {"url": str(page.get("url") or "")[:2000], "titre": str(page.get("titre") or "")[:300]}
    else:
        page = None
    attente = brut.get("attente")
    return Fiche(cle, port, chemin_cdp, pid, page, attente if isinstance(attente, int) and attente > 0 else 0)


def _ecrire_json(chemin: Path, donnees: dict[str, Any]) -> None:
    """Écrit d'un coup, en 0600, dans un dossier en 0700."""
    chemin.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    provisoire = chemin.with_name(f".{chemin.name}.{secrets.token_hex(4)}.tmp")
    fd = os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (json.dumps(donnees, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    os.replace(provisoire, chemin)


def lire_main(racine: Path, cle: str) -> dict[str, Any] | None:
    if not conversation_valide(cle):
        return None
    chemin = racine / "main" / f"{cle}.json"
    if not _fichier_a_soi(chemin):
        return None
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return brut if isinstance(brut, dict) else None


# ── Choix de la page, phrases, gestes ───────────────────────────────────────


def choisir_la_page(
    pages: dict[str, dict[str, Any]], voulue: dict[str, Any] | None, actuelle: str | None
) -> str | None:
    """La page à montrer : celle que l'agent a sélectionnée, reconnue à son adresse.

    Le filtre ne connaît que l'adresse de la page sélectionnée (le numéro du
    serveur MCP n'est pas l'identifiant de Chrome). Parmi les pages de cette
    adresse, on garde celle qu'on suit déjà, sinon la plus récemment vue
    changer. Une adresse que plus aucune page ne porte (l'agent a cliqué un
    lien : l'adresse a changé sans nouvelle liste) garde la page suivie.
    """
    url = (voulue or {}).get("url") or ""
    if url:
        memes = [i for i, p in pages.items() if p.get("url") == url]
        if actuelle in memes:
            return actuelle
        if memes:
            return max(memes, key=lambda i: pages[i].get("vu", 0.0))
    if actuelle in pages:
        return actuelle
    if not pages:
        return None
    return max(pages, key=lambda i: pages[i].get("vu", 0.0))


def _duree(secondes: float) -> str:
    s = max(0, int(round(secondes)))
    if s < 60:
        return f"{s} s"
    m, s = divmod(s, 60)
    return f"{m} min {s:02d} s" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _page_dite(page: dict[str, Any] | None) -> str:
    if not page or not page.get("url"):
        return "aucune page"
    titre = (page.get("titre") or "").strip()
    url = str(page["url"])
    # Une adresse `data:` peut porter toute la page : on n'en dit que le début.
    if len(url) > 200:
        url = url[:200] + "…"
    return f"« {titre} » ({url})" if titre else url


def phrase_de_reprise(
    avant: dict[str, Any] | None,
    apres: dict[str, Any] | None,
    duree_s: float,
    *,
    pour: str = "note",
    abandon: bool = False,
) -> str:
    """Ce que l'agent apprend quand la main lui revient.

    `pour` : `note` (ajoutée au résultat de son prochain outil du navigateur,
    à la troisième personne) ou `message` (le message qui le relance, écrit
    au nom de la personne).
    """
    change = (avant or {}).get("url") != (apres or {}).get("url")
    if pour == "message":
        debut = (
            "J'ai pris la main sur ton navigateur pendant " + _duree(duree_s)
            + (", puis j'ai quitté l'écran : l'Atelier te la rend." if abandon else ", et je te la rends.")
        )
        suite = f" La page affichée est maintenant {_page_dite(apres)}."
        if change:
            suite += f" C'était {_page_dite(avant)} quand j'ai pris la main."
        return (
            debut + suite
            + " Ce que j'ai fait n'est pas dans ton historique : regarde la page (take_snapshot) avant"
            " d'agir, ne refais pas ce que j'ai déjà fait (connexion, formulaire), puis reprends ta tâche."
        )
    debut = (
        "Note de l'Atelier : la personne a pris la main sur ton navigateur pendant " + _duree(duree_s)
        + (", puis a quitté l'écran ; la main t'est rendue." if abandon else ", puis te l'a rendue.")
    )
    suite = f" La page affichée est maintenant {_page_dite(apres)}."
    if change:
        suite += f" C'était {_page_dite(avant)} quand elle a pris la main."
    return (
        debut + suite
        + " Ce qu'elle a fait n'est pas dans ton historique : regarde la page (take_snapshot) avant"
        " d'agir, et ne refais pas ce qu'elle a déjà fait (connexion, formulaire)."
    )


def _nombre(valeur: Any, bas: float, haut: float) -> float | None:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return None
    v = float(valeur)
    if v != v or v < bas or v > haut:  # NaN compris
        return None
    return v


def _entier(valeur: Any, bas: int, haut: int, defaut: int) -> int:
    if isinstance(valeur, bool) or not isinstance(valeur, int):
        return defaut
    return valeur if bas <= valeur <= haut else defaut


def _court(valeur: Any, longueur: int) -> str | None:
    if not isinstance(valeur, str) or len(valeur) > longueur:
        return None
    return valeur


def commande_d_entree(message: dict[str, Any], taille: tuple[float, float]) -> tuple[str, dict[str, Any]] | None:
    """Le geste de la page traduit en commande CDP, ou None s'il n'est pas valide.

    Les coordonnées arrivent en fraction de l'image (0 à 1) : la page ne
    connaît pas la taille du navigateur, et n'a pas à la connaître.
    """
    genre = message.get("type")
    largeur, hauteur = taille
    if genre == "souris":
        action = SOURIS.get(str(message.get("action")))
        x = _nombre(message.get("x"), 0.0, 1.0)
        y = _nombre(message.get("y"), 0.0, 1.0)
        if action is None or x is None or y is None:
            return None
        params: dict[str, Any] = {
            "type": action,
            "x": round(x * largeur, 1),
            "y": round(y * hauteur, 1),
            "modifiers": _entier(message.get("mod"), 0, 15, 0),
        }
        if action in ("mousePressed", "mouseReleased"):
            params["button"] = BOUTONS.get(str(message.get("bouton")), "left")
            params["clickCount"] = _entier(message.get("clics"), 1, 3, 1)
        elif action == "mouseWheel":
            dx = _nombre(message.get("dx", 0), -5000, 5000)
            dy = _nombre(message.get("dy", 0), -5000, 5000)
            if dx is None or dy is None:
                return None
            params["deltaX"], params["deltaY"] = dx, dy
        return "Input.dispatchMouseEvent", params
    if genre == "clavier":
        action = message.get("action")
        cle = _court(message.get("key"), 32)
        code = _court(message.get("code", ""), 32)
        texte = _court(message.get("texte", ""), 4)
        if action not in ("bas", "haut") or cle is None or code is None or texte is None:
            return None
        params = {
            "key": cle,
            "code": code,
            "modifiers": _entier(message.get("mod"), 0, 15, 0),
            "windowsVirtualKeyCode": _entier(message.get("touche"), 0, 255, 0),
        }
        if action == "haut":
            params["type"] = "keyUp"
        elif texte:
            params["type"] = "keyDown"
            params["text"] = texte
        else:
            params["type"] = "rawKeyDown"
        return "Input.dispatchKeyEvent", params
    if genre == "texte":
        texte = _court(message.get("texte"), 2000)
        if not texte:
            return None
        return "Input.insertText", {"text": texte}
    if genre == "aller":
        url = _court(message.get("url"), 2000)
        if not url:
            return None
        morceaux = urlsplit(url.strip())
        if morceaux.scheme not in ("http", "https") or not morceaux.netloc:
            return None
        return "Page.navigate", {"url": url.strip()}
    return None


# ── Un spectateur, un écran ─────────────────────────────────────────────────


class _Spectateur:
    """Une page qui regarde : ses messages en attente, et la dernière image seulement."""

    def __init__(self) -> None:
        self.textes: deque[str] = deque(maxlen=64)
        self.image: bytes | None = None
        self.reveil = asyncio.Event()

    def texte(self, objet: dict[str, Any]) -> None:
        self.textes.append(json.dumps(objet, ensure_ascii=False))
        self.reveil.set()

    def nouvelle_image(self, octets: bytes) -> None:
        # Une page lente ne reçoit pas un retard d'images : la dernière seule.
        self.image = octets
        self.reveil.set()


class _Cdp:
    """Un client DevTools minimal : appels numérotés et signaux."""

    def __init__(self, ws: Any, au_signal: Callable[[dict[str, Any]], None]) -> None:
        self.ws = ws
        self.au_signal = au_signal
        self.suivant = 0
        self.attentes: dict[int, asyncio.Future[dict[str, Any]]] = {}

    async def lire(self) -> None:
        try:
            async for brut in self.ws:
                try:
                    message = json.loads(brut)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                ident = message.get("id")
                if isinstance(ident, int):
                    attente = self.attentes.pop(ident, None)
                    if attente is not None and not attente.done():
                        attente.set_result(message)
                elif "method" in message:
                    try:
                        self.au_signal(message)
                    except Exception:  # noqa: BLE001 — un signal mal formé ne coupe pas l'écran
                        log.debug("signal CDP ignoré", exc_info=True)
        except websockets.ConnectionClosed:
            pass
        finally:
            for attente in self.attentes.values():
                if not attente.done():
                    attente.set_exception(ConnectionError("Chrome est parti"))
            self.attentes.clear()

    async def appeler(self, methode: str, params: dict[str, Any] | None = None, session: str | None = None) -> dict[str, Any]:
        self.suivant += 1
        ident = self.suivant
        attente: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self.attentes[ident] = attente
        message: dict[str, Any] = {"id": ident, "method": methode, "params": params or {}}
        if session:
            message["sessionId"] = session
        await self.ws.send(json.dumps(message))
        try:
            reponse = await asyncio.wait_for(attente, CDP_DELAI_S)
        finally:
            self.attentes.pop(ident, None)
        if "error" in reponse:
            erreur = reponse.get("error") or {}
            raise ErreurCdp(str(erreur.get("message") or erreur)[:200])
        return reponse.get("result") or {}


class _Ecran:
    """Le Chrome d'une conversation, tel que ses spectateurs le voient."""

    def __init__(self, parent: Ecrans, conversation: str) -> None:
        self.parent = parent
        self.conversation = conversation
        self.boucle_ev = asyncio.get_running_loop()
        self.spectateurs: set[_Spectateur] = set()
        self.tache: asyncio.Task[None] | None = None
        self.cdp: _Cdp | None = None
        self.pages: dict[str, dict[str, Any]] = {}
        self.cible: str | None = None
        self.session: str | None = None
        self.taille: tuple[float, float] = (1280.0, 720.0)
        self.prochain_acquittement = 0.0
        self.derniere_image: bytes | None = None
        self.changement = asyncio.Event()
        # Les acquittements en attente : gardés, sans quoi la boucle pourrait
        # les ramasser avant qu'ils ne partent.
        self.acquittements: set[asyncio.Task[None]] = set()
        self.etat: dict[str, Any] = {"type": "etat", "disponible": False, "raison": "connexion au navigateur…"}

    # -- spectateurs --

    def ajouter(self, spectateur: _Spectateur) -> None:
        self.spectateurs.add(spectateur)
        spectateur.texte(self.etat)
        if self.derniere_image is not None:
            spectateur.nouvelle_image(self.derniere_image)
        if self.tache is None or self.tache.done():
            self.tache = asyncio.create_task(self.boucle(), name=f"ecran-{self.conversation}")

    def retirer(self, spectateur: _Spectateur) -> None:
        self.spectateurs.discard(spectateur)
        self.changement.set()

    def diffuser(self, objet: dict[str, Any]) -> None:
        for s in self.spectateurs:
            s.texte(objet)

    def publier_etat(self, **changements: Any) -> None:
        neuf = dict(self.etat, **changements)
        neuf.update(self.parent.etat_de_la_main(self.conversation))
        if neuf != self.etat:
            self.etat = neuf
            self.diffuser(neuf)

    # -- la boucle --

    async def _patienter(self, secondes: float) -> None:
        self.changement.clear()
        try:
            await asyncio.wait_for(self.changement.wait(), secondes)
        except asyncio.TimeoutError:
            pass

    async def boucle(self) -> None:
        try:
            while self.spectateurs:
                fiche = self.parent.fiche(self.conversation)
                if fiche is None:
                    self.publier_etat(disponible=False, raison="Le navigateur de l'agent n'est pas ouvert.",
                                      url="", titre="")
                    await self._patienter(REESSAI_S)
                    continue
                try:
                    async with connect(
                        fiche.adresse_cdp,
                        max_size=TAILLE_MAX_CDP,
                        open_timeout=5,
                        ping_interval=None,
                        compression=None,
                        proxy=None,
                    ) as ws:
                        await self._suivre(ws, fiche)
                except (OSError, websockets.WebSocketException, asyncio.TimeoutError, ErreurCdp, ConnectionError) as exc:
                    log.info("écran %s : navigateur injoignable (%s)", self.conversation, type(exc).__name__)
                    self.publier_etat(disponible=False, raison="Le navigateur de l'agent ne répond pas.")
                    await self._patienter(REESSAI_S)
        finally:
            self.cdp = None
            self.cible = None
            self.session = None
            self.parent._ecran_fini(self)

    async def _suivre(self, ws: Any, fiche: Fiche) -> None:
        cdp = _Cdp(ws, self._signal)
        lecteur = asyncio.create_task(cdp.lire())
        self.cdp = cdp
        self.pages = {}
        self.cible = None
        self.session = None
        try:
            await cdp.appeler("Target.setDiscoverTargets", {"discover": True})
            infos = await cdp.appeler("Target.getTargets")
            for info in infos.get("targetInfos") or []:
                self._noter_la_page(info)
            while self.spectateurs and not lecteur.done():
                neuve = self.parent.fiche(self.conversation)
                if neuve is None or (neuve.port, neuve.chemin) != (fiche.port, fiche.chemin):
                    return  # Chrome parti ou relancé : on se rattache au nouveau
                fiche = neuve
                voulue = choisir_la_page(self.pages, fiche.page, self.cible)
                if voulue != self.cible or (voulue is not None and self.session is None):
                    await self._montrer(cdp, voulue)
                if self.cible is not None:
                    # Chrome ne signale pas toujours un changement de titre
                    # (mesuré : une page `data:` garde son adresse pour titre) :
                    # on relit la page suivie à chaque tour de boucle.
                    try:
                        info = await cdp.appeler("Target.getTargetInfo", {"targetId": self.cible})
                        self._noter_la_page(info.get("targetInfo") or {}, vue=False)
                    except ErreurCdp:
                        pass
                page = self.pages.get(self.cible or "", {})
                self.publier_etat(
                    disponible=self.cible is not None,
                    raison="" if self.cible else "Aucune page ouverte.",
                    url=page.get("url", ""),
                    titre=page.get("titre", ""),
                    attente=fiche.attente,
                )
                self.parent._page_vue(self.conversation, page)
                await self._patienter(RELECTURE_S)
            if self.session:
                try:
                    await cdp.appeler("Page.stopScreencast", session=self.session)
                except (ErreurCdp, ConnectionError, asyncio.TimeoutError, websockets.ConnectionClosed):
                    pass
        finally:
            lecteur.cancel()
            self.cdp = None

    async def _montrer(self, cdp: _Cdp, cible: str | None) -> None:
        if self.session:
            ancienne = self.session
            self.session = None
            for methode, params in (("Page.stopScreencast", {}), ("Target.detachFromTarget", {"sessionId": ancienne})):
                try:
                    await cdp.appeler(methode, params, session=ancienne if methode.startswith("Page.") else None)
                except (ErreurCdp, asyncio.TimeoutError):
                    pass
        self.cible = cible
        if cible is None:
            return
        try:
            attache = await cdp.appeler("Target.attachToTarget", {"targetId": cible, "flatten": True})
            session = str(attache.get("sessionId") or "")
            if not session:
                return
            self.session = session
            await cdp.appeler(
                "Page.startScreencast",
                {"format": "jpeg", "quality": QUALITE_JPEG, "maxWidth": LARGEUR_MAX, "maxHeight": HAUTEUR_MAX,
                 "everyNthFrame": 1},
                session=session,
            )
        except ErreurCdp as exc:
            # La page a disparu entre-temps : on en choisira une autre.
            log.info("écran %s : page %s non suivie (%s)", self.conversation, cible, exc)
            self.pages.pop(cible, None)
            self.cible = None
            self.session = None

    def _noter_la_page(self, info: dict[str, Any], *, vue: bool = True) -> None:
        """Une page de Chrome ; `vue` : elle vient de changer (elle passe devant les autres)."""
        if not isinstance(info, dict) or info.get("type") != "page":
            return
        ident = str(info.get("targetId") or "")
        if not ident:
            return
        avant = self.pages.get(ident) or {}
        url = str(info.get("url") or "")[:2000]
        self.pages[ident] = {
            "url": url,
            "titre": str(info.get("title") or "")[:300],
            "vu": time.monotonic() if vue or avant.get("url") != url else avant.get("vu", 0.0),
        }

    def _signal(self, message: dict[str, Any]) -> None:
        methode = message.get("method")
        params = message.get("params") or {}
        if methode == "Page.screencastFrame":
            if message.get("sessionId") != self.session or not self.session:
                return
            meta = params.get("metadata") or {}
            largeur = _nombre(meta.get("deviceWidth"), 1, 100000)
            hauteur = _nombre(meta.get("deviceHeight"), 1, 100000)
            if largeur and hauteur:
                self.taille = (largeur, hauteur)
            try:
                octets = base64.b64decode(params.get("data") or "", validate=True)
            except ValueError:
                return
            self.derniere_image = octets
            for s in self.spectateurs:
                s.nouvelle_image(octets)
            maintenant = time.monotonic()
            delai = max(0.0, self.prochain_acquittement - maintenant)
            self.prochain_acquittement = maintenant + delai + 1.0 / self.parent.cadence
            tache = asyncio.create_task(self._acquitter(self.session, params.get("sessionId"), delai))
            self.acquittements.add(tache)
            tache.add_done_callback(self.acquittements.discard)
        elif methode in ("Target.targetCreated", "Target.targetInfoChanged"):
            self._noter_la_page(params.get("targetInfo") or {})
            self.changement.set()
        elif methode == "Target.targetDestroyed":
            ident = params.get("targetId")
            self.pages.pop(ident, None)
            if ident == self.cible:
                self.cible = None
                self.session = None
            self.changement.set()
        elif methode == "Target.detachedFromTarget" and params.get("sessionId") == self.session:
            self.session = None
            self.cible = None
            self.changement.set()

    async def _acquitter(self, session: str | None, image: Any, delai: float) -> None:
        if delai:
            await asyncio.sleep(delai)
        cdp = self.cdp
        if cdp is None or session is None or session != self.session:
            return
        try:
            await cdp.appeler("Page.screencastFrameAck", {"sessionId": image}, session=session)
        except (ErreurCdp, ConnectionError, asyncio.TimeoutError, websockets.ConnectionClosed):
            pass

    # -- gestes de la personne --

    async def agir(self, message: dict[str, Any]) -> str:
        """Un geste, s'il est permis ; sinon la raison du refus."""
        if not self.parent.etat_de_la_main(self.conversation).get("main"):
            return "Prenez la main pour agir sur la page."
        commande = commande_d_entree(message, self.taille)
        if commande is None:
            return "geste illisible"
        cdp, session = self.cdp, self.session
        if cdp is None or session is None:
            return "Aucune page à piloter."
        methode, params = commande
        try:
            await cdp.appeler(methode, params, session=session)
        except (ErreurCdp, ConnectionError, asyncio.TimeoutError, websockets.ConnectionClosed) as exc:
            return f"geste non transmis ({type(exc).__name__})"
        return ""


# ── Le registre des écrans ──────────────────────────────────────────────────


class Ecrans:
    """Les écrans des conversations, et la main de la personne.

    Réglé à l'enregistrement des routes (`navigateur_routes`) :

    - `connue(id)` : la conversation existe dans l'Atelier ;
    - `alias(id)` : les autres noms sous lesquels son navigateur a pu être
      publié (l'identifiant du CLI, pour une conversation reprise dans
      VS Code) ;
    - `tour_en_cours(id)` : un tour de l'Atelier travaille ;
    - `relancer(id, message)` : envoie un message à la conversation (dans un
      fil), rend False si ce n'est pas possible.
    """

    def __init__(
        self,
        racine: Path | Callable[[], Path] | None = None,
        *,
        cadence: float | None = None,
        horloge: Callable[[], float] = time.time,
    ) -> None:
        self._racine = racine
        self.cadence = cadence or _cadence_reglee()
        self.horloge = horloge
        self.connue: Callable[[str], bool] = lambda _id: True
        self.alias: Callable[[str], list[str]] = lambda _id: []
        self.tour_en_cours: Callable[[str], bool] = lambda _id: False
        self.relancer: Callable[[str, str], bool] | None = None
        self._ecrans: dict[str, _Ecran] = {}
        self._pages: dict[str, dict[str, Any]] = {}
        self._abandons: dict[str, asyncio.TimerHandle] = {}
        self._verrou = threading.Lock()

    @property
    def racine(self) -> Path:
        if self._racine is None:
            return racine_des_navigateurs()
        return self._racine() if callable(self._racine) else self._racine

    # -- fiches --

    def cles(self, conversation: str) -> list[str]:
        vues: list[str] = []
        for cle in [conversation, *self.alias(conversation)]:
            if cle and conversation_valide(cle) and cle not in vues:
                vues.append(cle)
        return vues

    def fiche(self, conversation: str) -> Fiche | None:
        for cle in self.cles(conversation):
            trouvee = lire_fiche(self.racine, cle)
            if trouvee is not None:
                return trouvee
        return None

    def _cle_de_la_main(self, conversation: str) -> str:
        fiche = self.fiche(conversation)
        return fiche.cle if fiche is not None else conversation

    def _page_vue(self, conversation: str, page: dict[str, Any]) -> None:
        if page:
            self._pages[conversation] = {"url": page.get("url", ""), "titre": page.get("titre", "")}

    def page_courante(self, conversation: str) -> dict[str, Any] | None:
        if conversation in self._pages:
            return dict(self._pages[conversation])
        fiche = self.fiche(conversation)
        return dict(fiche.page) if fiche is not None and fiche.page else None

    def etat_de_la_main(self, conversation: str) -> dict[str, Any]:
        main = lire_main(self.racine, self._cle_de_la_main(conversation)) or {}
        return {"main": main.get("prise") is True}

    def etat(self, conversation: str) -> dict[str, Any]:
        """Ce que l'interface en sait : ni port, ni chemin, ni processus."""
        fiche = self.fiche(conversation)
        page = self.page_courante(conversation) or {}
        return {
            "conversation": conversation,
            "disponible": fiche is not None,
            "url": page.get("url", ""),
            "titre": page.get("titre", ""),
            "attente": fiche.attente if fiche else 0,
            "regarde": bool(self._ecrans.get(conversation) and self._ecrans[conversation].spectateurs),
            **self.etat_de_la_main(conversation),
        }

    # -- la main --

    def prendre_la_main(self, conversation: str, par: str = "personne") -> dict[str, Any]:
        fiche = self.fiche(conversation)
        if fiche is None:
            raise EcranIndisponible("Le navigateur de l'agent n'est pas ouvert.")
        chemin = self.racine / "main" / f"{fiche.cle}.json"
        deja = lire_main(self.racine, fiche.cle) or {}
        if deja.get("prise") is not True:
            _ecrire_json(
                chemin,
                {
                    "prise": True,
                    "depuis": int(self.horloge() * 1000),
                    "par": par[:60],
                    "avant": self.page_courante(conversation),
                },
            )
            log.info("écran %s : la personne prend la main", conversation)
        self._notifier(conversation)
        return self.etat(conversation)

    def rendre_la_main(self, conversation: str, *, abandon: bool = False) -> dict[str, Any]:
        """Rend la main à l'agent : ses actions retenues repartent, il apprend ce qui a changé.

        - des actions attendent, ou un tour travaille : la note part avec le
          prochain résultat d'outil du navigateur (le filtre l'y ajoute) ;
        - rien ne travaille : l'agent est relancé par un message, s'il est une
          conversation de l'Atelier ; sinon la note attend son prochain outil.
        """
        cle = self._cle_de_la_main(conversation)
        main = lire_main(self.racine, cle)
        if not main or main.get("prise") is not True:
            return {**self.etat(conversation), "reprise": "rien"}
        depuis = main.get("depuis")
        duree = self.horloge() - (depuis / 1000 if isinstance(depuis, (int, float)) else self.horloge())
        avant = main.get("avant") if isinstance(main.get("avant"), dict) else None
        apres = self.page_courante(conversation)
        fiche = self.fiche(conversation)
        chemin = self.racine / "main" / f"{cle}.json"
        reprise = "note"
        attente = fiche.attente if fiche is not None else 0
        if not attente and not self.tour_en_cours(conversation) and self.relancer is not None:
            message = phrase_de_reprise(avant, apres, duree, pour="message", abandon=abandon)
            try:
                chemin.unlink()
            except OSError:
                pass
            if self.relancer(conversation, message):
                reprise = "relance"
        if reprise == "note":
            _ecrire_json(
                chemin,
                {
                    "prise": False,
                    "depuis": int(self.horloge() * 1000),
                    "note": phrase_de_reprise(avant, apres, duree, pour="note", abandon=abandon),
                },
            )
        log.info("écran %s : main rendue (%s%s)", conversation, reprise, ", abandon" if abandon else "")
        self._notifier(conversation)
        return {**self.etat(conversation), "reprise": reprise}

    def _notifier(self, conversation: str) -> None:
        ecran = self._ecrans.get(conversation)
        if ecran is None:
            return
        try:
            ecran.boucle_ev.call_soon_threadsafe(ecran.publier_etat)
        except RuntimeError:
            pass  # boucle fermée

    def _programmer_l_abandon(self, conversation: str) -> None:
        if not self.etat_de_la_main(conversation).get("main"):
            return
        boucle = asyncio.get_running_loop()

        def abandonner() -> None:
            self._abandons.pop(conversation, None)
            ecran = self._ecrans.get(conversation)
            if ecran is not None and ecran.spectateurs:
                return
            # Écrire et relancer hors de la boucle : `relancer` peut attendre.
            boucle.run_in_executor(None, lambda: self.rendre_la_main(conversation, abandon=True))

        self._annuler_l_abandon(conversation)
        self._abandons[conversation] = boucle.call_later(MAIN_ABANDON_S, abandonner)

    def _annuler_l_abandon(self, conversation: str) -> None:
        minuterie = self._abandons.pop(conversation, None)
        if minuterie is not None:
            minuterie.cancel()

    def _ecran_fini(self, ecran: _Ecran) -> None:
        if self._ecrans.get(ecran.conversation) is ecran and not ecran.spectateurs:
            del self._ecrans[ecran.conversation]

    # -- le WebSocket de la page --

    async def servir(self, websocket: WebSocket, conversation: str) -> None:
        """Le flux d'une page qui regarde (déjà autorisée par l'hôte)."""
        await websocket.accept()
        ecran = self._ecrans.get(conversation)
        if ecran is None or ecran.boucle_ev is not asyncio.get_running_loop():
            ecran = _Ecran(self, conversation)
            self._ecrans[conversation] = ecran
        spectateur = _Spectateur()
        self._annuler_l_abandon(conversation)
        ecran.ajouter(spectateur)
        ecran.publier_etat()
        envoi = asyncio.create_task(self._envoyer(websocket, spectateur))
        try:
            while True:
                recu = await websocket.receive()
                if recu["type"] == "websocket.disconnect":
                    break
                texte = recu.get("text")
                if not isinstance(texte, str) or len(texte) > MESSAGE_MAX:
                    continue
                try:
                    message = json.loads(texte)
                except ValueError:
                    continue
                if isinstance(message, dict):
                    await self._recu(ecran, spectateur, conversation, message)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            envoi.cancel()
            ecran.retirer(spectateur)
            if not ecran.spectateurs:
                self._programmer_l_abandon(conversation)
                # Le dernier spectateur parti : on laisse la boucle fermer la
                # connexion à Chrome (et le screencast avec elle) avant de rendre.
                if ecran.tache is not None and not ecran.tache.done():
                    try:
                        await asyncio.wait_for(asyncio.shield(ecran.tache), 3)
                    except (asyncio.TimeoutError, Exception):  # noqa: BLE001
                        pass
            if websocket.application_state == WebSocketState.CONNECTED:
                try:
                    await websocket.close()
                except Exception:  # noqa: BLE001 — déjà fermé
                    pass

    async def _recu(self, ecran: _Ecran, spectateur: _Spectateur, conversation: str, message: dict[str, Any]) -> None:
        if message.get("type") == "main":
            try:
                if message.get("prendre") is True:
                    await asyncio.to_thread(self.prendre_la_main, conversation)
                elif message.get("prendre") is False:
                    await asyncio.to_thread(self.rendre_la_main, conversation)
            except EcranIndisponible as exc:
                spectateur.texte({"type": "refus", "raison": str(exc)})
            ecran.publier_etat()
            return
        refus = await ecran.agir(message)
        if refus:
            spectateur.texte({"type": "refus", "raison": refus})

    async def _envoyer(self, websocket: WebSocket, spectateur: _Spectateur) -> None:
        try:
            while True:
                await spectateur.reveil.wait()
                spectateur.reveil.clear()
                while spectateur.textes:
                    await websocket.send_text(spectateur.textes.popleft())
                image, spectateur.image = spectateur.image, None
                if image is not None:
                    await websocket.send_bytes(image)
        except (WebSocketDisconnect, RuntimeError, OSError):
            pass


def _cadence_reglee() -> float:
    try:
        valeur = float(os.environ.get("ATELIER_ECRAN_IPS") or CADENCE_IPS)
    except ValueError:
        return CADENCE_IPS
    return min(30.0, max(1.0, valeur))


__all__ = [
    "Ecrans",
    "EcranIndisponible",
    "Fiche",
    "choisir_la_page",
    "commande_d_entree",
    "lire_fiche",
    "lire_main",
    "phrase_de_reprise",
]
