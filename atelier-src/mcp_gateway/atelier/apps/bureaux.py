"""Les services du namespace, relayés par l'hôte des applications (décision J-d).

Blender, QGIS et n8n tournent dans leurs propres pods du namespace. Leur
bureau (noVNC) ou leur éditeur ne sont joignables que de l'intérieur du
cluster, et parfois sous un jeton. Le panneau de l'Atelier les montre
pourtant à côté du fil : l'hôte des applications les relaie, sous
`/_services/<connecteur>/<vue>/`, comme il relaie les créations serveur.

**Déclaration.** Une entrée du pool des connecteurs porte, sous une clé
unique `atelier` qui n'est jamais écrite dans un `.mcp.json`
(`coherence-croisee.md` M3), la liste de ses vues :

    "atelier": {"vues": [
      {"nom": "bureau", "genre": "bureau", "amont": "http://blender-remote-mcp:6080",
       "vnc": "/websockify", "titre": "Bureau Blender"},
      {"nom": "canvas", "genre": "application", "amont": "http://blender-remote-mcp:8100",
       "accueil": "/canvas", "jeton": {"depuis": "entete:Authorization", "pose": "cookie:blender_token"}}
    ]}

- `genre` : `bureau` (un noVNC : l'accueil est sa page `vnc.html`, reliée à
  `vnc`) ou `application` (une page web : l'accueil est `accueil`, `/` par
  défaut) ;
- `amont` : l'adresse **interne** du service, `http://<service>:<port>`.
  Jamais une adresse de ce pod (boucle locale) : l'hôte des applications
  n'est pas une porte vers l'Atelier ;
- `vnc` : le chemin du WebSocket de websockify chez l'amont ;
- `jeton` (facultatif) : d'où vient le jeton du service et où le poser.
  `depuis` : `entete:<Nom>` (un en-tête de l'entrée du connecteur, sans son
  schéma `Bearer`) ou `secret:<réf>` (un fichier de `~/work/.secrets/apps/`).
  `pose` : `cookie:<nom>`, `entete:<Nom>` ou `requete:<nom>` ;
- `chemin` : `retire` (défaut : l'amont reçoit le chemin sans le préfixe) ou
  `garde` (un service réglé pour vivre sous ce préfixe, comme n8n avec
  `N8N_PATH`).

**Le jeton ne quitte jamais le serveur.** Le relais le pose sur la requête
vers l'amont, après avoir retiré ce que le navigateur aurait mis au même
endroit. Au retour, tout ce qui le porterait est retiré : l'en-tête qui le
contient (un `Set-Cookie` du service, par exemple) disparaît, et le corps
est lu en flux et caviardé (le jeton, encodé ou non, remplacé par rien). Un
amont qui compresse sa réponse malgré `Accept-Encoding: identity` n'est pas
relayé : on ne caviarde pas ce qu'on ne lit pas.

**Qui encadre.** La politique de l'hôte (`cadrage`) : `frame-ancestors` à
l'Atelier seul, `X-Frame-Options` retiré — sur ces réponses comme sur les
autres, qu'un amont n'envoie aucun en-tête (n8n, mesure A6) ou qu'il en
envoie un contraire.

**Qui entre.** Une session de l'hôte dont la portée couvre ce connecteur
(`connecteur:<nom>`, voir `passage`). Une session ouverte pour un projet ou
pour un autre connecteur ne l'ouvre pas.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import threading
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit

from mcp_gateway.atelier.apps.passage import (
    RACINE_SERVICES,
    nom_connecteur_valide,
    portee_connecteur,
)
from mcp_gateway.atelier.apps.secrets import SecretIllisible, lire_secret, reference_valide

log = logging.getLogger("atelier.apps.bureaux")

GENRES = ("bureau", "application")
CHEMINS = ("retire", "garde")
POSES = ("cookie", "entete", "requete")
_NOM_VUE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_NOM_JETON = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_CHEMIN = re.compile(r"^/[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*$")
# Les hôtes que l'amont ne peut pas désigner : ce pod lui-même.
_HOTES_INTERDITS = {"localhost", "localhost.localdomain", "0.0.0.0", "::", "::1", "ip6-localhost"}

# Les réponses d'un amont : la lecture du pool est gardée quelques secondes.
DUREE_CACHE_S = 5.0


class DeclarationInvalide(ValueError):
    """Une vue déclarée qu'on ne relaie pas."""


@dataclass(frozen=True)
class Jeton:
    """D'où vient le jeton d'un service, et où il est posé. Jamais sa valeur."""

    depuis: str  # "entete" | "secret"
    source: str  # nom de l'en-tête du connecteur, ou référence du secret
    pose: str  # "cookie" | "entete" | "requete"
    cle: str  # nom du cookie, de l'en-tête ou du paramètre


@dataclass(frozen=True)
class VueService:
    connecteur: str
    nom: str
    genre: str
    titre: str
    amont: str  # http(s)://hote[:port], sans chemin
    vnc: str
    accueil: str
    chemin: str
    jeton: Jeton | None

    @property
    def prefixe(self) -> str:
        return f"{RACINE_SERVICES}/{self.connecteur}/{self.nom}"

    @property
    def portee(self) -> str:
        return portee_connecteur(self.connecteur)

    @property
    def adresse_accueil(self) -> str:
        """Le chemin, sur l'hôte, où la vue s'ouvre.

        `vnc` et `accueil` se lisent toujours sous la racine de la vue ; seul
        ce que reçoit l'amont change avec `chemin` (voir `chemin_amont`).
        Pour un bureau, la page `vnc.html` de noVNC, que websockify sert à côté
        de son WebSocket, reliée à ce WebSocket par `path` (relatif à l'hôte).
        """
        if self.genre == "bureau":
            requete = urlencode(
                {
                    "autoconnect": "true",
                    "resize": "scale",
                    "reconnect": "true",
                    "path": (self.prefixe + self.vnc).lstrip("/"),
                }
            )
            return f"{self.prefixe}/vnc.html?{requete}"
        return self.prefixe + self.accueil

    def chemin_amont(self, chemin_public: str) -> str:
        """Le chemin que l'amont reçoit pour un chemin de l'hôte."""
        if self.chemin == "garde":
            return chemin_public
        return chemin_public[len(self.prefixe):] or "/"

    def fiche(self) -> dict[str, Any]:
        """Ce que l'interface en voit : ni amont, ni jeton."""
        return {
            "connecteur": self.connecteur,
            "nom": self.nom,
            "genre": self.genre,
            "titre": self.titre,
            "ouvrir": f"/v1/bureaux/{quote(self.connecteur, safe='')}/{quote(self.nom, safe='')}/ouvrir",
        }


# ── Lecture des déclarations ────────────────────────────────────────────


def _amont_valide(adresse: str, *, boucle_locale: bool = False) -> str:
    """`http(s)://hote[:port]` d'un service du namespace, ou une erreur.

    `boucle_locale` n'existe que pour les essais, où le service factice
    écoute sur 127.0.0.1 : en service, ce pod n'est jamais un amont.
    """
    brut = (adresse or "").strip().rstrip("/")
    morceaux = urlsplit(brut)
    if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
        raise DeclarationInvalide(f"amont invalide : {adresse!r} (http://service:port attendu)")
    if morceaux.username or morceaux.password or morceaux.query or morceaux.fragment:
        raise DeclarationInvalide("amont invalide : ni identifiants, ni requête, ni fragment")
    if morceaux.path not in ("", "/"):
        raise DeclarationInvalide("amont invalide : l'adresse s'arrête au port")
    hote = morceaux.hostname.lower()
    if not boucle_locale and (hote in _HOTES_INTERDITS or hote.endswith(".localhost")):
        raise DeclarationInvalide(f"amont refusé : {hote} désigne ce pod")
    try:
        ip = ipaddress.ip_address(hote)
    except ValueError:
        ip = None
    if ip is not None and (
        (ip.is_loopback and not boucle_locale) or ip.is_link_local or ip.is_unspecified or ip.is_multicast
    ):
        raise DeclarationInvalide(f"amont refusé : {hote}")
    try:
        port = morceaux.port
    except ValueError:
        raise DeclarationInvalide(f"amont invalide : port de {adresse!r}") from None
    netloc = hote if ip is None or ip.version == 4 else f"[{hote}]"
    return f"{morceaux.scheme}://{netloc}" + (f":{port}" if port else "")


def _chemin_valide(chemin: str, champ: str) -> str:
    if not _CHEMIN.match(chemin or "") or chemin.startswith("//") or "\\" in chemin:
        raise DeclarationInvalide(f"{champ} invalide : {chemin!r}")
    segments = chemin.split("?", 1)[0].split("/")
    if any(s in (".", "..") for s in segments):
        raise DeclarationInvalide(f"{champ} invalide : {chemin!r}")
    return chemin


def _jeton(brut: Any) -> Jeton | None:
    if brut is None:
        return None
    if not isinstance(brut, dict):
        raise DeclarationInvalide("jeton : un objet {depuis, pose} attendu")
    depuis, _, source = str(brut.get("depuis") or "").partition(":")
    pose, _, cle = str(brut.get("pose") or "").partition(":")
    if depuis not in ("entete", "secret") or not source:
        raise DeclarationInvalide("jeton.depuis : `entete:<Nom>` ou `secret:<référence>`")
    if depuis == "entete" and not _NOM_JETON.match(source):
        raise DeclarationInvalide(f"jeton.depuis : en-tête invalide {source!r}")
    if depuis == "secret" and not reference_valide(source):
        raise DeclarationInvalide(f"jeton.depuis : référence invalide {source!r}")
    if pose not in POSES or not _NOM_JETON.match(cle):
        raise DeclarationInvalide("jeton.pose : `cookie:<nom>`, `entete:<Nom>` ou `requete:<nom>`")
    return Jeton(depuis, source, pose, cle)


def lire_vue(connecteur: str, brut: Any, *, boucle_locale: bool = False) -> VueService:
    """Une vue déclarée, validée ; `DeclarationInvalide` sinon."""
    if not nom_connecteur_valide(connecteur):
        raise DeclarationInvalide(f"connecteur invalide : {connecteur!r}")
    if not isinstance(brut, dict):
        raise DeclarationInvalide("une vue est un objet")
    nom = str(brut.get("nom") or "")
    if not _NOM_VUE.match(nom):
        raise DeclarationInvalide(f"nom de vue invalide : {nom!r}")
    genre = str(brut.get("genre") or "")
    if genre not in GENRES:
        raise DeclarationInvalide(f"genre inconnu : {genre!r} (bureau ou application)")
    chemin = str(brut.get("chemin") or "retire")
    if chemin not in CHEMINS:
        raise DeclarationInvalide(f"chemin : retire ou garde, pas {chemin!r}")
    amont = _amont_valide(str(brut.get("amont") or ""), boucle_locale=boucle_locale)
    vnc = str(brut.get("vnc") or "")
    if genre == "bureau":
        vnc = _chemin_valide(vnc or "/websockify", "vnc")
    elif vnc:
        vnc = _chemin_valide(vnc, "vnc")
    accueil = _chemin_valide(str(brut.get("accueil") or "/"), "accueil")
    titre = str(brut.get("titre") or "").strip()[:80] or f"{connecteur} : {nom}"
    return VueService(connecteur, nom, genre, titre, amont, vnc, accueil, chemin, _jeton(brut.get("jeton")))


def vues_du_pool(
    pool: dict[str, Any], *, boucle_locale: bool = False
) -> tuple[dict[tuple[str, str], VueService], list[dict[str, str]]]:
    """Les vues des connecteurs actifs, et les déclarations refusées (sans valeur)."""
    vues: dict[tuple[str, str], VueService] = {}
    erreurs: list[dict[str, str]] = []
    for connecteur, entree in sorted(pool.items()):
        if not isinstance(entree, dict) or not entree.get("enabled", True):
            continue
        atelier = entree.get("atelier")
        brutes = atelier.get("vues") if isinstance(atelier, dict) else None
        if brutes is None:
            continue
        if not isinstance(brutes, list):
            erreurs.append({"connecteur": connecteur, "vue": "", "raison": "atelier.vues : une liste attendue"})
            continue
        for brut in brutes:
            try:
                vue = lire_vue(connecteur, brut, boucle_locale=boucle_locale)
            except DeclarationInvalide as exc:
                nom = str(brut.get("nom") or "") if isinstance(brut, dict) else ""
                erreurs.append({"connecteur": connecteur, "vue": nom[:40], "raison": str(exc)})
                continue
            if (connecteur, vue.nom) in vues:
                erreurs.append({"connecteur": connecteur, "vue": vue.nom, "raison": "vue déclarée deux fois"})
                continue
            vues[(connecteur, vue.nom)] = vue
    return vues, erreurs


# ── Le jeton, côté serveur seulement ────────────────────────────────────


def _sans_schema(valeur: str) -> str:
    schema, _, reste = valeur.strip().partition(" ")
    return reste.strip() if reste and schema.lower() in ("bearer", "token") else valeur.strip()


def poser_jeton(
    entetes: Sequence[tuple[str, str]], requete: str, jeton: Jeton, valeur: str
) -> tuple[list[tuple[str, str]], str]:
    """Les en-têtes et la requête vers l'amont, jeton posé ; ce que le client avait mis au même endroit est retiré."""
    sortie: list[tuple[str, str]] = []
    cle = jeton.cle
    for nom, v in entetes:
        bas = nom.lower()
        if jeton.pose == "entete" and bas == cle.lower():
            continue
        if jeton.pose == "cookie" and bas == "cookie":
            morceaux = [m.strip() for m in v.split(";") if m.strip()]
            morceaux = [m for m in morceaux if m.split("=", 1)[0].strip() != cle]
            if not morceaux:
                continue
            v = "; ".join(morceaux)
        sortie.append((nom, v))
    if jeton.pose == "cookie":
        cookies = [i for i, (n, _) in enumerate(sortie) if n.lower() == "cookie"]
        if cookies:
            i = cookies[0]
            sortie[i] = (sortie[i][0], f"{sortie[i][1]}; {cle}={valeur}")
        else:
            sortie.append(("Cookie", f"{cle}={valeur}"))
    elif jeton.pose == "entete":
        sortie.append((cle, f"Bearer {valeur}" if cle.lower() == "authorization" else valeur))
    if jeton.pose == "requete":
        paires = [(k, v) for k, v in parse_qsl(requete, keep_blank_values=True) if k != cle]
        paires.append((cle, valeur))
        requete = urlencode(paires)
    return sortie, requete


def motifs_du_jeton(valeur: str) -> list[bytes]:
    """Les formes sous lesquelles un jeton peut revenir de l'amont."""
    formes = {valeur, quote(valeur, safe=""), quote_plus(valeur)}
    return sorted((f.encode("utf-8") for f in formes if f), key=len, reverse=True)


def _porte(valeur: str, motifs: Sequence[bytes]) -> bool:
    brut = valeur.encode("latin-1", "replace")
    return any(m in brut for m in motifs)


def entetes_sans_jeton(entetes: Sequence[tuple[str, str]], motifs: Sequence[bytes]) -> list[tuple[str, str]]:
    """Tout en-tête de réponse qui porte le jeton disparaît ; la longueur aussi (le corps est caviardé)."""
    if not motifs:
        return list(entetes)
    return [
        (k, v)
        for k, v in entetes
        if k.lower() != "content-length" and not _porte(v, motifs)
    ]


async def caviarder(flux: AsyncIterator[bytes], motifs: Sequence[bytes]) -> AsyncIterator[bytes]:
    """Le corps en flux, sans le jeton, même coupé entre deux morceaux.

    On garde en réserve la longueur du plus long motif moins un octet : un
    motif qui commence dans ce qu'on rend finit forcément dans ce qu'on a
    déjà lu, et y a donc déjà été retiré.
    """
    if not motifs:
        async for morceau in flux:
            yield morceau
        return
    garde = max(len(m) for m in motifs) - 1
    tampon = b""

    def nettoyer(donnees: bytes) -> bytes:
        avant = None
        while avant != donnees:
            avant = donnees
            for m in motifs:
                donnees = donnees.replace(m, b"")
        return donnees

    async for morceau in flux:
        if not morceau:
            continue
        tampon = nettoyer(tampon + morceau)
        if len(tampon) > garde:
            coupe = len(tampon) - garde
            yield tampon[:coupe]
            tampon = tampon[coupe:]
    tampon = nettoyer(tampon)
    if tampon:
        yield tampon


# ── Le registre des vues ────────────────────────────────────────────────


class Bureaux:
    """Les vues déclarées dans le pool, relues au plus toutes les quelques secondes.

    `lire_pool` rend le pool tel que l'Atelier le garde : `{nom: entrée}`,
    entrées complètes (`enabled`, en-têtes en clair). Ce qui en sort vers
    l'interface (`fiches`) ne porte ni amont ni jeton.
    """

    def __init__(
        self,
        lire_pool: Callable[[], dict[str, Any]],
        dossier_secrets: Path,
        *,
        variables: Callable[[], dict[str, str]] | None = None,
        horloge: Callable[[], float] = time.monotonic,
        boucle_locale: bool = False,
    ) -> None:
        self._lire_pool = lire_pool
        self.dossier_secrets = dossier_secrets
        self._variables = variables
        self._horloge = horloge
        self._boucle_locale = boucle_locale
        self._verrou = threading.Lock()
        self._cache: tuple[float, dict[str, Any], dict[tuple[str, str], VueService], list[dict[str, str]]] | None = None

    def _etat(self) -> tuple[dict[str, Any], dict[tuple[str, str], VueService], list[dict[str, str]]]:
        maintenant = self._horloge()
        with self._verrou:
            if self._cache is not None and maintenant - self._cache[0] < DUREE_CACHE_S:
                return self._cache[1], self._cache[2], self._cache[3]
        try:
            pool = self._lire_pool() or {}
        except Exception as exc:  # noqa: BLE001 — un pool illisible ne casse pas l'hôte
            log.warning("pool illisible pour les bureaux : %s", exc)
            pool = {}
        vues, erreurs = vues_du_pool(pool, boucle_locale=self._boucle_locale)
        with self._verrou:
            self._cache = (maintenant, pool, vues, erreurs)
        return pool, vues, erreurs

    def oublier(self) -> None:
        with self._verrou:
            self._cache = None

    def vue(self, connecteur: str, nom: str) -> VueService | None:
        return self._etat()[1].get((connecteur, nom))

    def vue_du_chemin(self, chemin: str) -> VueService | None:
        """La vue sous laquelle tombe un chemin de l'hôte, s'il y en a une."""
        morceaux = chemin.split("?", 1)[0].lstrip("/").split("/")
        if len(morceaux) < 3 or "/" + morceaux[0] != RACINE_SERVICES:
            return None
        return self.vue(morceaux[1], morceaux[2])

    def lister(self) -> list[VueService]:
        return list(self._etat()[1].values())

    def fiches(self) -> dict[str, Any]:
        _, vues, erreurs = self._etat()
        return {"vues": [v.fiche() for v in vues.values()], "refusees": erreurs}

    def valeur_du_jeton(self, vue: VueService) -> str:
        """La valeur du jeton, lue à l'instant, pour la requête en cours seulement."""
        jeton = vue.jeton
        if jeton is None:
            return ""
        if jeton.depuis == "secret":
            try:
                return lire_secret(self.dossier_secrets, jeton.source)
            except SecretIllisible as exc:
                raise DeclarationInvalide(str(exc)) from None
        pool = self._etat()[0]
        entree = pool.get(vue.connecteur) or {}
        entetes = entree.get("headers") if isinstance(entree, dict) else None
        valeur = ""
        if isinstance(entetes, dict):
            for nom, v in entetes.items():
                if str(nom).lower() == jeton.source.lower() and isinstance(v, str):
                    valeur = v
                    break
        valeur = self._developper(valeur)
        valeur = _sans_schema(valeur)
        if not valeur:
            raise DeclarationInvalide(
                f"{vue.connecteur} : pas d'en-tête {jeton.source} dans l'entrée du connecteur"
            )
        return valeur

    def _developper(self, valeur: str) -> str:
        """Une référence `${VAR}` du pool, développée ; une valeur, telle quelle."""
        m = re.fullmatch(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", valeur.strip())
        if not m:
            return valeur
        variables = self._variables() if self._variables else {}
        return variables.get(m.group(1), "")


__all__ = [
    "Bureaux",
    "DeclarationInvalide",
    "Jeton",
    "VueService",
    "caviarder",
    "entetes_sans_jeton",
    "lire_vue",
    "motifs_du_jeton",
    "poser_jeton",
    "vues_du_pool",
]
