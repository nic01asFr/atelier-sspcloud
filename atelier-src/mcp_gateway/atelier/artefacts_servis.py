"""Servir et écrire les artefacts d'un projet, sous une adresse donnée.

Le même service tient à deux adresses. Sur l'hôte des applications,
`/<slug>/<nom>/…` : c'est là que tout contenu d'agent doit vivre, hors de
l'origine de l'Atelier (docs/atelier-applications.md, lot 4). Sur
l'Atelier même, `/v1/artifacts/<slug>/…` : le palier de secours d'une
installation sans second hôte, et, quand ce second hôte existe, une simple
porte qui y renvoie.

Rien ne change de ce qui fait la sûreté d'un artefact d'une adresse à
l'autre : bac à sable sans `allow-same-origin`, lecture sous jeton, écriture
bornée à l'artefact du jeton. Seuls diffèrent le préfixe des adresses, et ce
qu'une page a le droit de joindre (`connect-src`).

Un artefact est un dossier `artifacts/<nom>/` (voir `apps.manifeste`) : ses
pages se relient entre elles, chargent leurs feuilles de style et leurs
scripts relatifs, sous un jeton borné à ce dossier. Elles n'écrivent chez
elles que si l'artefact le déclare (`"edition": true`), ou si le dossier
porte encore l'ancien marqueur `.corpus`. Un artefact **serveur** (son
`artefact.json` est un service) n'est jamais servi comme des fichiers : son
code et sa configuration resteraient lisibles.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import quote

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from mcp_gateway.atelier import artifacts as art
from mcp_gateway.atelier.apps.manifeste import (
    ArtefactInconnu,
    Manifeste,
    ManifesteInvalide,
    charger_manifeste,
    nom_valide,
)

ENTETES_ARTEFACT = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    # Le jeton vit dans l'adresse : elle ne doit pas partir en `Referer`
    # vers un lien externe que la page propose.
    "Referrer-Policy": "no-referrer",
}


class ServeurArtefacts:
    """Les artefacts de tous les projets, sous `prefixe(slug)`.

    `prefixe` rend le début d'adresse d'un projet, barre finale comprise
    (`/v1/artifacts/<slug>/` ou `/<slug>/`). `connect_src`, s'il est donné,
    remplace le `connect-src 'self'` des pages sous jeton : sur l'hôte des
    applications, une page n'écrit que sous le préfixe de son projet.
    """

    def __init__(
        self,
        projects_dir: Path,
        secret: Callable[[], bytes],
        prefixe: Callable[[str], str],
        *,
        connect_src: Callable[[str], str] | None = None,
    ) -> None:
        self.projects_dir = projects_dir
        self.secret = secret
        self.prefixe = prefixe
        self.connect_src = connect_src

    # ── Les artefacts ────────────────────────────────────────────────

    def _manifeste(self, slug: str, nom: str) -> Manifeste | None:
        """Le manifeste d'un dossier d'artefact ; `ManifesteInvalide` s'il est faux."""
        try:
            return charger_manifeste(self.projects_dir / slug, nom)
        except ArtefactInconnu:
            return None

    def est_service(self, slug: str, nom: str) -> bool:
        """Vrai si ce dossier ne doit pas être servi comme des fichiers.

        Un manifeste illisible compte comme un service : dans le doute, on ne
        montre pas le contenu d'un dossier qui voulait être un processus.
        """
        if not nom_valide(nom):
            return False
        try:
            m = self._manifeste(slug, nom)
        except ManifesteInvalide:
            return True
        return m is not None and m.service

    def edition_permise(self, slug: str, racine: str) -> bool:
        if not racine or not nom_valide(racine):
            return False
        try:
            m = self._manifeste(slug, racine)
        except ManifesteInvalide:
            return False
        return m is not None and not m.service and m.edition

    @staticmethod
    def racine_de(base: Path, cible: Path, rel: str) -> str | None:
        """Le dossier que couvre un jeton de lecture : l'artefact, en tête du chemin.

        L'ancien marqueur `.corpus` à la racine d'`artifacts/` couvre encore
        tout le dossier ; ailleurs, c'est le premier segment, s'il est un
        dossier. Un fichier posé à la racine n'a pas de jeton : page autonome.
        """
        ancien = art.racine_relative(base, cible)
        if ancien == "":
            return ""
        tete = rel.strip("/").split("/", 1)[0]
        if tete and (base.resolve() / tete).is_dir():
            return tete
        return ancien

    # ── Adresses et en-têtes ─────────────────────────────────────────

    def csp_corpus(self, slug: str) -> str:
        if self.connect_src is None:
            return art.CSP_CORPUS
        return art.CSP_CORPUS.replace("connect-src 'self'", f"connect-src {self.connect_src(slug)}")

    def entetes(self, csp: str, jeton: bool) -> dict[str, str]:
        h = {"Content-Security-Policy": csp, **ENTETES_ARTEFACT}
        if jeton:
            # La page d'un corpus parle depuis une origine opaque : `Origin:
            # null`. Le jeton fait foi, pas l'origine ; on la laisse donc lire
            # la réponse et son empreinte.
            h["Access-Control-Allow-Origin"] = "null"
            h["Access-Control-Expose-Headers"] = "ETag"
        return h

    def refus(self, statut: int, detail: str, jeton: bool) -> JSONResponse:
        """Un refus lisible par la page qui écrit, même en origine opaque."""
        return JSONResponse(
            {"detail": detail}, status_code=statut, headers=self.entetes(art.CSP_SANDBOX, jeton)
        )

    def base(self, slug: str) -> Path:
        """Le dossier `artifacts/` d'un projet existant — sinon 404.

        Le slug devient un chemin : il doit avoir la forme d'un slug de
        l'Atelier, et le projet exister. Sans cela, `%2E%2E` désignait le
        parent des projets et un PUT vers un slug inventé créait l'arborescence.
        """
        if not art.slug_valide(slug):
            raise HTTPException(404, "projet inconnu")
        projet = self.projects_dir / slug
        if projet.is_symlink() or not projet.is_dir():
            raise HTTPException(404, "projet inconnu")
        return art.dossier_des_artefacts(projet)

    def url(self, slug: str, rel: str, jeton: str | None, dossier: bool) -> str:
        """L'adresse d'un artefact, chaque segment encodé — jamais brut."""
        chemin = self.prefixe(quote(slug, safe=""))
        if jeton:
            chemin += f"{art.PREFIXE_JETON}{jeton}/"
        rel = rel.strip("/")
        if rel:
            chemin += quote(rel, safe="/") + ("/" if dossier else "")
        return chemin

    @staticmethod
    def separer_jeton(chemin: str) -> tuple[str | None, str]:
        tete, _, reste = chemin.partition("/")
        if tete.startswith(art.PREFIXE_JETON):
            return tete[len(art.PREFIXE_JETON):], reste
        return None, chemin

    @staticmethod
    def redirection(url: str, statut: int) -> RedirectResponse:
        return RedirectResponse(url, status_code=statut, headers=dict(ENTETES_ARTEFACT))

    def lire_jeton(self, slug: str, brut: str) -> art.Jeton | None:
        if not art.slug_valide(slug):
            return None
        return art.lire_jeton(self.secret(), brut, slug)

    # ── Lecture ──────────────────────────────────────────────────────

    def servir(
        self,
        request: Request,
        slug: str,
        chemin: str,
        jeton: art.Jeton | None = None,
        brut: str | None = None,
    ) -> Response:
        """Rend un dossier d'artefacts ou l'un de ses fichiers.

        Sans jeton, seul un fichier posé à la racine d'`artifacts/` est servi ;
        ce qui relève d'un dossier d'artefact renvoie vers son adresse à jeton.
        Avec jeton, rien hors de l'artefact qu'il couvre.
        """
        base = self.base(slug)
        rel = chemin.strip("/")
        csp = self.csp_corpus(slug) if jeton is not None else art.CSP_SANDBOX

        def entetes() -> dict[str, str]:
            return self.entetes(csp, jeton is not None)

        def absent() -> Response:
            return Response(
                art.page_absente(slug),
                status_code=404,
                media_type="text/html; charset=utf-8",
                headers=entetes(),
            )

        if art.segments_suspects(rel):
            return absent()
        tete = rel.split("/", 1)[0]
        if tete and self.est_service(slug, tete):
            return Response(
                art.page_absente(slug),
                status_code=409,
                media_type="text/html; charset=utf-8",
                headers=entetes(),
            )
        if jeton is not None and not jeton.couvre(rel):
            return self.refus(403, "hors du corpus de ce jeton", True)
        cible = art._sous(base, rel) if rel else base.resolve()
        if cible is None:
            return absent()

        # Un artefact lu sans jeton : on lui en donne un, et on y renvoie. Les
        # adresses relatives de ses pages hériteront du segment qui le porte.
        if jeton is None and cible.exists():
            racine = self.racine_de(base, cible, rel)
            if racine is not None:
                neuf = art.signer_jeton(self.secret(), slug, racine)
                return self.redirection(self.url(slug, rel, neuf, cible.is_dir() or not rel), 302)

        # Un dossier : la racine, ou un sous-dossier. Servi sans sa barre
        # finale, ses liens relatifs se résolvaient un cran trop haut.
        if cible.is_dir() or not rel:
            if not request.url.path.endswith("/"):
                return self.redirection(self.url(slug, rel, brut, True), 308)
            # Un dossier qui porte sa page d'accueil la montre, corpus ou non :
            # c'est ce qu'un agent attend en y déposant un site.
            if (cible / "index.html").is_file():
                cible = cible / "index.html"
            else:
                entrees = art.lister(base, rel) or []
                # Notre propre page, pas celle d'un agent : autonome, donc le
                # bac à sable strict lui suffit, corpus ou non.
                return Response(
                    art.page_index(slug, rel, entrees),
                    media_type="text/html; charset=utf-8",
                    headers=self.entetes(art.CSP_SANDBOX, jeton is not None),
                )

        if not cible.is_file():
            return absent()

        h = entetes()
        h["ETag"] = art.etag_du_fichier(cible)
        type_mime = art.type_du_fichier(cible)
        # Hors corpus, le Markdown se rend en page autonome. Dans un corpus,
        # tout est servi tel quel : c'est lui qui gère son rendu et ses liens.
        if jeton is None and type_mime == "text/markdown":
            texte, _ = art.decoder(cible.read_bytes())
            return Response(
                art.rendre_markdown(texte, art._joli_nom(cible.name)),
                media_type="text/html; charset=utf-8",
                headers=h,
            )
        type_servi = "text/plain" if type_mime == "text/markdown" else type_mime
        if type_servi.startswith("text/") or type_servi in (
            "application/javascript",
            "application/json",
            "image/svg+xml",
        ):
            # Les octets tels quels. Le jeu de caractères n'est annoncé que
            # s'il se reconnaît ; sinon le navigateur lit celui du document.
            octets = cible.read_bytes()
            _, jeu = art.decoder(octets)
            h["Content-Type"] = f"{type_servi}; charset={jeu}" if jeu else type_servi
            return Response(octets, headers=h)
        return FileResponse(cible, media_type=type_mime, headers=h)

    @staticmethod
    def preflight(par_jeton: bool) -> Response:
        """La requête préalable d'une page de corpus qui veut écrire chez elle."""
        if not par_jeton:
            return Response(status_code=204)
        return Response(
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "null",
                "Access-Control-Allow-Methods": "GET, PUT",
                "Access-Control-Allow-Headers": "Content-Type, If-Match, If-None-Match",
                "Access-Control-Max-Age": "600",
            },
        )

    # ── Écriture ─────────────────────────────────────────────────────

    async def ecrire(
        self,
        request: Request,
        slug: str,
        chemin: str,
        *,
        sans_jeton: Callable[[], None],
        if_match: str | None,
        if_none_match: str | None,
    ) -> Response:
        """Écrit un fichier d'un corpus — à l'adresse même où on le lit.

        Depuis la page, c'est le jeton du chemin qui autorise, et il borne
        l'écriture à son corpus. Sans jeton, `sans_jeton` décide (la clé au
        porteur sur l'Atelier) et lève si l'appel n'a pas le droit. Les murs
        sont dans `art.ecrire` ; `If-Match` évite d'écraser une version
        qu'on n'a pas vue.
        """
        import logging

        brut, rel = self.separer_jeton(chemin)
        par_jeton = brut is not None
        racine: str | None = None
        if par_jeton:
            jeton = self.lire_jeton(slug, brut or "")
            if jeton is None or jeton.perime():
                return self.refus(401, "jeton invalide ou périmé", True)
            if not jeton.couvre(rel):
                return self.refus(403, "hors du corpus de ce jeton", True)
            racine = jeton.racine
        else:
            sans_jeton()
        tete = rel.strip("/").split("/", 1)[0]
        if tete and self.est_service(slug, tete):
            return self.refus(409, "un artefact serveur ne s'écrit pas par cette voie", par_jeton)
        edition = self.edition_permise(slug, racine if racine is not None else tete)
        if racine is None and edition:
            racine = tete
        try:
            base = self.base(slug)
        except HTTPException as exc:
            return self.refus(exc.status_code, str(exc.detail), par_jeton)
        annonce = request.headers.get("content-length")
        if annonce and annonce.isdigit() and int(annonce) > art.POIDS_MAX_ECRITURE:
            return self.refus(
                413,
                f"contenu trop gros ({annonce} octets, plafond {art.POIDS_MAX_ECRITURE})",
                par_jeton,
            )
        contenu = await request.body()
        try:
            cible, etag = art.ecrire(
                base,
                rel,
                contenu,
                racine=racine,
                si_correspond=if_match,
                si_absent=(if_none_match or "").strip() == "*",
                edition=edition,
            )
        except art.Conflit as exc:
            return self.refus(412, str(exc), par_jeton)
        except art.Refus as exc:
            # Un refus se lit : la page qui écrit doit pouvoir le montrer à qui
            # l'a demandé, plutôt que d'afficher « échec ».
            return self.refus(exc.statut, str(exc), par_jeton)
        except OSError as exc:
            return self.refus(500, f"écriture impossible : {exc}", par_jeton)
        logging.getLogger("atelier.artefacts").info(
            "artefact écrit : %s/%s (%d octets)", slug, rel, len(contenu)
        )
        h = self.entetes(art.CSP_SANDBOX, par_jeton)
        h["ETag"] = etag
        return JSONResponse(
            {"chemin": rel, "octets": len(contenu), "ecrit": cible.name, "etag": etag},
            headers=h,
        )
