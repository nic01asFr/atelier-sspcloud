"""Servir les artefacts d'un projet — les livrables qu'un agent y dépose.

Un agent qui produit un résultat destiné à être vu — un rapport, une page,
un tableau — n'a nulle part où le montrer : sur ce pod, un port local n'est
jamais exposé. Un agent a passé cent soixante-quatorze tours à chercher une
URL publique pour son serveur maison, sans en trouver. La réponse est
ailleurs : il dépose ses livrables dans un dossier `artifacts/` de son projet,
et l'Atelier les sert derrière sa propre porte, comme il sert déjà VS Code.

Le contenu vient d'un agent, pas de nous. Servi tel quel sur la porte de
l'Atelier, un HTML déposé là tournerait avec le cookie de qui le regarde et
pourrait appeler l'API en son nom. On le rend donc inerte — voir `CSP_SANDBOX`
et `CSP_CORPUS` : tout ce qui sort d'ici est servi en bac à sable, sans
exception, corpus compris.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import mimetypes
import os
import re
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

# Le dossier, dans le projet, où un agent dépose ce qu'il veut montrer.
NOM_DOSSIER = "artifacts"

# Un dossier qui porte ce fichier est un « corpus » : un site à plusieurs
# pièces — feuille de style partagée, pages qui se lient entre elles — et non
# une page autonome. Il est servi en bac à sable comme le reste, mais ses
# sous-ressources relatives se chargent (voir `CSP_CORPUS` et les jetons).
MARQUEUR_CORPUS = ".corpus"

# Le contenu est produit par un agent. `sandbox` sans `allow-same-origin` met
# le document dans une origine opaque : son script ne lit plus le cookie ni le
# stockage de l'Atelier, et ses requêtes partent comme d'un autre site — le
# cookie `SameSite=Lax` n'y est pas joint (mesuré dans Chrome). `allow-scripts`
# laisse vivre une page autonome — mais jamais avec `allow-same-origin`, sinon
# le bac à sable ne servirait plus à rien. Un artefact ordinaire se veut donc
# autonome, tout en lui : c'est aussi ce qu'est un artefact chez Claude.
# `allow-downloads` : une page qui produit un fichier (un export, le lecteur
# Grist qui enregistre) doit pouvoir le donner ; sans lui, le clic ne fait rien.
# `worker-src blob:` : une carte MapLibre dessine ses couches dans un worker
# créé depuis un `blob:` du code de la page. Un tel worker hérite de cette CSP —
# ni réseau ni cookie — et n'exécute que ce que la page contenait déjà.
CSP_SANDBOX = (
    "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads; "
    "default-src 'none'; img-src data: blob:; media-src data: blob:; "
    "style-src 'unsafe-inline'; script-src 'unsafe-inline'; font-src data:; "
    "worker-src blob:; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
)

# La CSP d'un corpus : le même bac à sable, et des sous-ressources en plus.
#
# Un corpus était servi hors bac à sable, dans l'origine de l'Atelier, pour
# que sa feuille de style partagée se charge. Son script lisait alors tout ce
# que l'interface gardait dans le navigateur — la clé propriétaire comprise —
# et pouvait ouvrir l'interface dans un cadre pour agir en son nom.
#
# Mesuré dans Chrome : un document en origine opaque résout `'self'` sur
# l'origine de son adresse. La feuille de style, le script et les images
# relatifs se chargent donc ; ce qui ne suit pas, c'est le cookie, qu'aucune
# de ces requêtes ne porte. D'où le jeton dans l'adresse (voir `signer_jeton`).
# `connect-src 'self'` laisse la page écrire chez elle par ce jeton ; vers le
# reste de l'API elle n'arrive qu'en inconnue, sans cookie ni clé.
CSP_CORPUS = (
    "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads; "
    "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
    "media-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; font-src 'self' data:; "
    "worker-src 'self' blob:; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'self'"
)

# Ce qu'un corpus peut écrire d'un seul geste. Une note, une page, un index :
# on est loin du compte. Au-delà, ce n'est plus un artefact qu'on édite.
POIDS_MAX_ECRITURE = 5 * 1024 * 1024

# La forme d'un slug de projet. L'Atelier en crée en minuscules, chiffres,
# tirets et soulignés (`projects.create`) ; il liste aussi les dossiers clonés
# tels quels, d'où les majuscules et le point admis — jamais en tête, pour
# qu'un slug ne soit jamais `.` ni `..`.
FORME_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

# Le segment qui, en tête de chemin, porte un jeton de lecture.
PREFIXE_JETON = "@"

# La vie d'un jeton. Court : il circule dans une adresse. Une navigation qui le
# trouve périmé en reçoit un neuf si le cookie de session l'accompagne.
DUREE_JETON = 60 * 60

# Ce qui exécute du script si on l'ouvre : c'est là que le bac à sable compte.
TYPES_ACTIFS = ("text/html", "image/svg+xml")

# Ce qu'on ne montre pas dans l'index : les serveurs bricolés d'hier, les
# restes de dépendances. L'agent expose du contenu, pas de la plomberie.
CACHES = {"server.mjs", "server.js", "node_modules", ".git", "__pycache__", "artefact.json"}

# Le manifeste d'un artefact serveur : jamais servi, jamais écrasable par une
# page (voir `apps.manifeste`).
MANIFESTE = "artefact.json"

# Deux écritures concurrentes sur le même fichier : l'une doit voir l'autre.
# Le test `If-Match` et le remplacement se font donc d'un seul tenant.
_VERROU_ECRITURE = threading.Lock()


class Refus(ValueError):
    """Une écriture refusée — et le statut HTTP qui la dit."""

    def __init__(self, message: str, statut: int = 400) -> None:
        super().__init__(message)
        self.statut = statut


class Conflit(Exception):
    """Le fichier a changé depuis que la page l'a lu (`If-Match`)."""


# ── Le slug ────────────────────────────────────────────────────────────


def slug_valide(slug: str) -> bool:
    """Un slug qui a la forme de ceux de l'Atelier — rien d'autre ne passe.

    Le slug devient un chemin sur disque. `%2E%2E` dans l'adresse arrive ici
    décodé, selon l'ingress : sans ce contrôle il désignait le dossier parent
    de tous les projets.
    """
    return bool(FORME_SLUG.match(slug or ""))


# ── Le jeton de lecture ────────────────────────────────────────────────
#
# Un document en bac à sable charge ses sous-ressources sans cookie : la
# feuille de style d'un corpus revenait en 401. Le jeton remplace le cookie,
# mais pour un seul corpus : signé, daté, limité au préfixe du dossier. Il se
# place en tête du chemin (`/v1/artifacts/<slug>/@<jeton>/<corpus>/…`), de
# sorte que toute adresse relative écrite dans le corpus le reprend d'elle-même.


def _b64(octets: bytes) -> str:
    return base64.urlsafe_b64encode(octets).rstrip(b"=").decode("ascii")


def _deb64(texte: str) -> bytes:
    return base64.urlsafe_b64decode(texte + "=" * (-len(texte) % 4))


def secret_des_jetons(cle_proprietaire: str) -> bytes:
    """La clé qui signe les jetons, tirée de la clé propriétaire.

    Tirée et non choisie au hasard : elle survit à un redémarrage, et tombe
    avec la clé quand celle-ci est renouvelée — un jeton qui a fui avec elle
    ne vaut plus rien.
    """
    return hmac.new(
        cle_proprietaire.encode("utf-8"), b"atelier/artefacts/jeton", hashlib.sha256
    ).digest()


def _mac(secret: bytes, charge: bytes) -> bytes:
    return hmac.new(secret, charge, hashlib.sha256).digest()[:18]


def signer_jeton(
    secret: bytes, slug: str, racine: str, *, duree: int = DUREE_JETON, maintenant: float | None = None
) -> str:
    """Un jeton qui ouvre `racine` (chemin sous `artifacts/`) et rien d'autre."""
    expire = int((maintenant if maintenant is not None else time.time()) + duree)
    charge = f"{slug}\n{racine.strip('/')}\n{expire}".encode("utf-8")
    return f"{_b64(charge)}.{_b64(_mac(secret, charge))}"


@dataclass
class Jeton:
    slug: str
    racine: str  # chemin du corpus sous `artifacts/`, sans barre ; "" = tout
    expire: int

    def perime(self, maintenant: float | None = None) -> bool:
        return (maintenant if maintenant is not None else time.time()) >= self.expire

    def couvre(self, rel: str) -> bool:
        """Le chemin est-il sous la racine du jeton ?"""
        rel = rel.strip("/")
        if not self.racine:
            return True
        return rel == self.racine or rel.startswith(self.racine + "/")


def lire_jeton(secret: bytes, jeton: str, slug: str) -> Jeton | None:
    """Le jeton s'il est authentique et émis pour ce slug — sinon rien.

    Un jeton périmé est rendu quand même : c'est à l'appelant de décider s'il
    peut le renouveler (navigation avec cookie) ou non.
    """
    try:
        charge_b64, mac_b64 = jeton.split(".", 1)
        charge = _deb64(charge_b64)
        mac = _deb64(mac_b64)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(mac, _mac(secret, charge)):
        return None
    try:
        slug_j, racine, expire = charge.decode("utf-8").split("\n")
        expire_i = int(expire)
    except (UnicodeDecodeError, ValueError):
        return None
    if slug_j != slug:
        return None
    return Jeton(slug_j, racine, expire_i)


# ── Les chemins ────────────────────────────────────────────────────────


def dossier_des_artefacts(cwd: Path) -> Path:
    """Là où un projet garde ce qu'il montre."""
    return Path(cwd) / NOM_DOSSIER


def segments_suspects(rel: str) -> bool:
    """Le chemin porte-t-il un segment qu'aucune adresse honnête n'envoie ?

    `..`, `.`, un nom caché, une barre inverse ou un deux-points (lecteur ou
    flux alterné sous Windows). Le mur de `_sous` tiendrait de toute façon ;
    ceci refuse plus tôt, et refuse aussi les fichiers cachés que le mur, lui,
    laisserait lire (`.git/config`, `.corpus`).
    """
    for seg in rel.strip("/").split("/"):
        if not seg:
            continue
        if seg.startswith(".") or "\\" in seg or ":" in seg or "\x00" in seg or seg == MANIFESTE:
            return True
    return False


def _sous(base: Path, rel: str) -> Path | None:
    """Le chemin visé, s'il reste bien sous la base — sinon rien.

    Un artefact ne donne pas le droit de lire tout le disque : `../../secrets`
    dans une URL doit se heurter à un mur, pas remonter l'arborescence.
    """
    base = base.resolve()
    try:
        vise = (base / rel).resolve()
    except (OSError, ValueError):
        return None
    if vise == base or base in vise.parents:
        return vise
    return None


def _relatif(base: Path, chemin: Path) -> str:
    return chemin.relative_to(base.resolve()).as_posix().strip(".")


def racine_du_corpus(base: Path, cible: Path) -> Path | None:
    """Le dossier corpus le plus haut qui contient la cible, s'il y en a un.

    Le plus haut, et non le plus proche : un corpus est un site, et ses pages
    se lient d'un sous-dossier à l'autre. Un jeton émis pour un sous-corpus
    ne couvrirait pas le retour à l'accueil. La cible peut ne pas exister
    encore (écriture d'une page neuve) : on part de son premier ancêtre réel.
    """
    base = base.resolve()
    dossier = cible if cible.is_dir() else cible.parent
    while not dossier.exists() and dossier != base and base in dossier.parents:
        dossier = dossier.parent
    trouve: Path | None = None
    while True:
        if (dossier / MARQUEUR_CORPUS).is_file():
            trouve = dossier
        if dossier == base or base not in dossier.parents:
            return trouve
        dossier = dossier.parent


def est_sous_corpus(base: Path, cible: Path) -> bool:
    """La cible relève-t-elle d'un dossier marqué comme corpus ?"""
    return racine_du_corpus(base, cible) is not None


def racine_relative(base: Path, cible: Path) -> str | None:
    """Le chemin du corpus sous `artifacts/`, tel que le jeton le porte."""
    racine = racine_du_corpus(base, cible)
    return None if racine is None else _relatif(base, racine)


# ── L'empreinte ────────────────────────────────────────────────────────


def etag_des_octets(contenu: bytes) -> str:
    return '"' + hashlib.sha256(contenu).hexdigest()[:32] + '"'


def etag_du_fichier(chemin: Path) -> str:
    h = hashlib.sha256()
    with chemin.open("rb") as f:
        for bloc in iter(lambda: f.read(1 << 16), b""):
            h.update(bloc)
    return '"' + h.hexdigest()[:32] + '"'


def _correspond(condition: str, actuel: str | None) -> bool:
    """`If-Match` : `*`, ou l'une des empreintes fortes de la liste."""
    condition = condition.strip()
    if condition == "*":
        return actuel is not None
    if actuel is None:
        return False
    return any(c.strip() == actuel for c in condition.split(","))


# ── L'écriture ─────────────────────────────────────────────────────────


def _remplacer(provisoire: str, cible: Path) -> None:
    """`os.replace`, qui sous Windows échoue un instant sur un fichier juste
    remplacé (l'antivirus ou l'indexeur le tient encore). Sous Linux, où tourne
    le pod, le premier essai passe toujours."""
    for essai in range(20):
        try:
            os.replace(provisoire, cible)
            return
        except PermissionError:
            if os.name != "nt" or essai == 19:
                raise
            time.sleep(0.01 * (essai + 1))


def ecrire(
    base: Path,
    rel: str,
    contenu: bytes,
    *,
    racine: str | None = None,
    si_correspond: str | None = None,
    si_absent: bool = False,
    edition: bool = False,
) -> tuple[Path, str]:
    """Écrit un fichier d'un corpus, et rend son chemin et sa nouvelle empreinte.

    Les murs, dans l'ordre :
    - rien hors d'un corpus : l'écriture sert à une page qui s'édite elle-même,
      pas à déposer n'importe où sous `artifacts/`. `racine` (le corpus du
      jeton) borne encore davantage ;
    - aucun nom qui commence par un point — `.corpus` compris : écrire ce
      marqueur ferait d'un autre dossier un corpus ;
    - aucun lien symbolique sur le chemin, qui mènerait ailleurs ;
    - le dossier `artifacts/` doit exister : sans quoi on créait un *fichier*
      de ce nom à la racine du projet.

    Lève `Refus` (avec son statut) ou `Conflit` quand `If-Match` ne tient plus.
    """
    if len(contenu) > POIDS_MAX_ECRITURE:
        raise Refus(
            f"contenu trop gros ({len(contenu)} octets, plafond {POIDS_MAX_ECRITURE})", 413
        )
    rel = rel.strip("/")
    if not rel:
        raise Refus("chemin vide")
    segments = rel.split("/")
    for seg in segments:
        if seg in ("", ".", ".."):
            raise Refus("chemin invalide")
        if "\\" in seg or ":" in seg or "\x00" in seg:
            raise Refus("caractère interdit dans le chemin")
        if seg.startswith("."):
            raise Refus("un nom qui commence par un point ne s'écrit pas", 403)
        if seg == MANIFESTE:
            raise Refus("le manifeste d'un artefact ne s'écrit pas depuis une page", 403)

    if base.is_symlink() or not base.is_dir():
        raise Refus("ce projet n'a pas de dossier artifacts/", 404)
    base_r = base.resolve()

    # Le chemin, composant par composant : rien de symbolique, rien qui soit
    # un fichier là où l'on attend un dossier.
    courant = base_r
    for seg in segments[:-1]:
        courant = courant / seg
        if courant.is_symlink():
            raise Refus("lien symbolique sur le chemin", 403)
        if courant.exists() and not courant.is_dir():
            raise Refus("un fichier occupe la place d'un dossier")
    cible = courant / segments[-1]
    if cible.is_symlink():
        raise Refus("lien symbolique sur le chemin", 403)
    if cible.is_dir():
        raise Refus("ce chemin désigne un dossier")
    if _sous(base_r, rel) != cible:
        raise Refus("chemin hors de l'artefact", 403)

    corpus = base_r / racine if racine else racine_du_corpus(base_r, cible)
    if racine == "":
        corpus = base_r
    # `edition` : l'appelant a lu dans le manifeste de l'artefact que ses
    # pages écrivent ; sinon, l'ancien marqueur `.corpus` en tient lieu.
    permis = corpus is not None and (
        (edition and racine is not None and corpus.is_dir()) or (corpus / MARQUEUR_CORPUS).is_file()
    )
    if not permis:
        raise Refus("on n'écrit que dans un artefact en édition", 403)
    if corpus not in cible.parents:
        raise Refus("chemin hors du corpus", 403)

    cible.parent.mkdir(parents=True, exist_ok=True)
    # Écriture d'un seul geste, sous un nom provisoire propre à cet appel : une
    # page à moitié écrite serait servie telle quelle au premier lecteur venu,
    # et deux écritures simultanées se marchaient sur le même `.en-cours`. Le
    # point en tête le cache de l'index s'il reste orphelin.
    descr, provisoire = tempfile.mkstemp(
        dir=str(cible.parent), prefix=f".{cible.name}.", suffix=".en-cours"
    )
    try:
        with os.fdopen(descr, "wb") as f:
            f.write(contenu)
        with _VERROU_ECRITURE:
            actuel = etag_du_fichier(cible) if cible.is_file() else None
            if si_absent and actuel is not None:
                raise Conflit("le fichier existe déjà")
            if si_correspond is not None and not _correspond(si_correspond, actuel):
                raise Conflit("le fichier a changé depuis sa lecture")
            _remplacer(provisoire, cible)
    finally:
        if os.path.exists(provisoire):
            os.unlink(provisoire)
    return cible, etag_des_octets(contenu)


# ── L'index et le rendu ────────────────────────────────────────────────


@dataclass
class Entree:
    """Une ligne de l'index : un fichier ou un sous-dossier."""

    nom: str
    chemin: str  # relatif au dossier des artefacts
    est_dossier: bool
    taille: int


def _humain(taille: int) -> str:
    if taille < 1024:
        return f"{taille} o"
    if taille < 1024 * 1024:
        return f"{taille / 1024:.1f} ko"
    return f"{taille / (1024 * 1024):.1f} Mo"


def _joli_nom(nom: str) -> str:
    tronc = nom.rsplit(".", 1)[0] if "." in nom else nom
    return tronc.replace("_", " ").replace("-", " ").strip() or nom


def lister(base: Path, rel: str = "") -> list[Entree] | None:
    """Le contenu d'un dossier d'artefacts, trié dossiers puis fichiers.

    Rend `None` si le chemin ne désigne pas un dossier existant sous la base.
    Les noms cachés — marqueur, provisoires d'écriture — ne se listent pas.
    """
    cible = _sous(base, rel) if rel else base.resolve()
    if cible is None or not cible.is_dir():
        return None
    entrees: list[Entree] = []
    for enfant in sorted(cible.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if (
            enfant.name in CACHES
            or enfant.name.startswith(".")
            or enfant.name.endswith(".en-cours")
        ):
            continue
        rel_enfant = f"{rel}/{enfant.name}".strip("/")
        try:
            taille = enfant.stat().st_size if enfant.is_file() else 0
        except OSError:
            taille = 0
        entrees.append(Entree(enfant.name, rel_enfant, enfant.is_dir(), taille))
    return entrees


def type_du_fichier(chemin: Path) -> str:
    type_devine, _ = mimetypes.guess_type(chemin.name)
    if type_devine:
        return type_devine
    if chemin.suffix.lower() in (".md", ".markdown"):
        return "text/markdown"
    return "application/octet-stream"


def decoder(octets: bytes) -> tuple[str, str | None]:
    """Le texte et son jeu de caractères, s'il se reconnaît.

    UTF-8 d'abord, qui ne se trompe pas par accident. Sinon on ne devine pas :
    le jeu reste inconnu (`None`) et c'est le lecteur qui tranche — le
    navigateur lit `<meta charset>`. Relire de force en UTF-8 remplaçait les
    accents d'un fichier latin-1 par des losanges.
    """
    try:
        return octets.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return octets.decode("latin-1"), None


def _page(titre: str, corps: str) -> str:
    """Une page autonome : tout le style à l'intérieur, rien à charger.

    L'origine opaque du bac à sable interdit de tirer une feuille de style
    d'ailleurs ; la page doit donc se suffire. Elle suit aussi le thème de qui
    la lit, clair ou sombre, comme le reste de l'Atelier.
    """
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(titre)}</title>
<style>
  :root {{ color-scheme: light dark; --fond:#fff; --encre:#1a1a1a; --doux:#666;
    --trait:#e2e2e2; --lien:#0b66c3; --code:#f5f5f5; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --fond:#1a1a1a; --encre:#e8e8e8;
    --doux:#9aa; --trait:#333; --lien:#5aa9ff; --code:#242424; }} }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--fond); color:var(--encre);
    font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  main {{ max-width:820px; margin:0 auto; padding:40px 24px 96px; }}
  a {{ color:var(--lien); }}
  h1,h2,h3 {{ line-height:1.25; }}
  h1 {{ font-size:1.7rem; margin:0 0 1.2rem; }}
  pre {{ background:var(--code); padding:14px 16px; border-radius:8px;
    overflow:auto; font-size:.86em; }}
  code {{ background:var(--code); padding:.15em .4em; border-radius:4px;
    font-size:.88em; }}
  pre code {{ background:none; padding:0; }}
  table {{ border-collapse:collapse; width:100%; margin:1rem 0; }}
  th,td {{ border:1px solid var(--trait); padding:8px 12px; text-align:left; }}
  img {{ max-width:100%; height:auto; }}
  blockquote {{ margin:1rem 0; padding:.2rem 1rem; border-left:3px solid var(--trait);
    color:var(--doux); }}
  .liste {{ list-style:none; padding:0; margin:0; }}
  .liste li {{ border-bottom:1px solid var(--trait); }}
  .liste a {{ display:flex; justify-content:space-between; gap:1rem;
    padding:12px 4px; text-decoration:none; }}
  .liste a:hover {{ background:var(--code); }}
  .nom {{ color:var(--encre); }}
  .taille {{ color:var(--doux); font-variant-numeric:tabular-nums; }}
  .vide {{ color:var(--doux); }}
  .fil {{ color:var(--doux); font-size:.9em; margin:0 0 1.5rem; }}
  .fil a {{ color:var(--doux); }}
</style></head><body><main>{corps}</main></body></html>"""


def page_absente(slug: str) -> str:
    """Ce qu'on rend quand rien n'est là. Sans lien : l'adresse n'est pas sûre."""
    return _page(slug, f"<h1>{html.escape(slug)}</h1><p class=\"vide\">Rien à montrer ici.</p>")


def page_index(slug: str, rel: str, entrees: list[Entree]) -> str:
    """La page qui liste un dossier d'artefacts.

    Les liens sont relatifs : un dossier est toujours servi avec sa barre
    finale (on y redirige), donc `nom` et `../` se résolvent juste — et
    gardent le jeton en tête de chemin quand il y en a un. Chaque nom est
    encodé comme un segment d'adresse, pas échappé comme du HTML : un `#` ou
    un `?` dans un nom de fichier coupait le lien.
    """
    rel = rel.strip("/")
    titre = slug if not rel else rel.rsplit("/", 1)[-1]
    fil = ""
    if rel:
        morceaux = rel.split("/")
        n = len(morceaux)
        liens = [f'<a href="{"../" * n}">{html.escape(slug)}</a>']
        for i, m in enumerate(morceaux[:-1]):
            liens.append(f'<a href="{"../" * (n - 1 - i)}">{html.escape(m)}</a>')
        liens.append(html.escape(morceaux[-1]))
        fil = '<p class="fil">' + " / ".join(liens) + "</p>"
    if not entrees:
        corps = f"<h1>{html.escape(titre)}</h1>{fil}<p class=\"vide\">Rien à montrer ici pour le moment.</p>"
        return _page(titre, corps)
    lignes = []
    for e in entrees:
        url = quote(e.nom, safe="") + ("/" if e.est_dossier else "")
        etiquette = html.escape(e.nom + ("/" if e.est_dossier else ""))
        droite = "dossier" if e.est_dossier else _humain(e.taille)
        lignes.append(
            f'<li><a href="{html.escape(url)}"><span class="nom">{etiquette}</span>'
            f'<span class="taille">{droite}</span></a></li>'
        )
    corps = (
        f"<h1>{html.escape(titre)}</h1>{fil}"
        f'<ul class="liste">{"".join(lignes)}</ul>'
    )
    return _page(titre, corps)


def rendre_markdown(texte: str, titre: str) -> str:
    """Le Markdown en page autonome. mistune s'il est là, sinon le texte brut.

    On ne fait pas dépendre le service d'une bibliothèque de rendu : sans elle,
    l'artefact reste lisible tel qu'écrit plutôt que de renvoyer une erreur.
    """
    try:
        import mistune  # type: ignore

        corps = mistune.html(texte)
    except Exception:  # noqa: BLE001 — pas de mistune, ou un Markdown qui le fâche
        corps = f"<pre>{html.escape(texte)}</pre>"
    return _page(titre, corps)
