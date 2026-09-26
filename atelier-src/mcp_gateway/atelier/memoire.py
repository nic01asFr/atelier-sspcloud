"""La mémoire, côté Atelier : ce que l'Atelier fournit à wikichat, et ce qu'il en lit.

La capitalisation des conversations vit dans wikichat (transverse §1.6 bis,
W8), sur ses briques : mêmes fichiers que la connaissance, même recherche.
L'Atelier, lui, tient les conversations. Ce module est la frontière :

1. **Ce que l'Atelier fournit** (routes internes, clé du lanceur ou propriétaire) :

   - `GET /v1/memoire/conversations` : les conversations, avec leur état de
     repos et une empreinte qui change quand elles grandissent. wikichat sait
     ainsi quoi (re)ficher, sans relire ce qui n'a pas bougé ;
   - `GET /v1/memoire/conversations/{id}` : **le transcript filtré** (T10) et
     réduit à ce qu'une extraction par le code lit : paroles de la personne,
     textes du modèle, outils appelés (nom et quelques champs d'entrée), erreurs,
     fins de tour avec leurs jetons. Jamais le contenu d'un résultat d'outil ;
   - `POST /v1/memoire/propositions` : une préférence ou une interprétation
     proposée par un modèle (la routine de nuit) entre dans « À valider »,
     source `memoire` (A-7). Rien n'est retenu avant l'accord de la personne ;
   - `POST /v1/memoire/resumer` et `POST /v1/memoire/vecteurs` : le résumé
     d'une conversation par un appel direct du modèle, et les vecteurs des
     fiches (décisions du 26/09), dans `memoire_modele.py`. Clé du lanceur
     seulement : ni le propriétaire ni l'interface.

   La clé acceptée est celle du lanceur (`~/work/.secrets/atelier_lanceur_key`,
   en-tête `X-Atelier-Lanceur`) : c'est déjà la clé de wikichat auprès de
   l'Atelier. Le propriétaire (clé ou session de l'interface) lit aussi.

2. **Ce que l'Atelier lit chez wikichat** (`Wikichat`) : le rappel, une fiche,
   la mémoire de la personne, et les trois gestes de la personne (retenir,
   corriger, oublier), qui passent par les commandes réservées de
   `commandes/rappel.py`.

Lecture seule des conversations : le transcript se lit par `fondre`, sans
l'absorption du registre du CLI que fait `transcript_text` (qui écrit).
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("atelier.memoire")

# Au niveau du module : FastAPI résout les annotations (`Header(alias=…)`)
# dans les globales de la fonction ; importée dans `construire_le_routeur`,
# l'en-tête devenait un paramètre de requête et la clé n'était jamais lue.
# Le même que `lancements.ENTETE_CLE` (vérifié par `test_memoire`).
ENTETE_CLE = "X-Atelier-Lanceur"

# Une conversation est « au repos » après N minutes sans écriture (§3.4 de
# `assistant-contexte.md` : fin de conversation, ou 30 min d'inactivité).
REPOS_MIN = 30
# Ce que l'extraction reçoit d'une conversation, au plus. Le plus long
# transcript du pod fait 2 965 entrées (mesuré le 26/09).
EVENEMENTS_MAX = 6000
TEXTE_MAX = 4000
ENTREE_MAX = 300
ERREUR_MAX = 300
# Les champs d'entrée d'un outil que l'extraction lit ; tout le reste est tu.
CLES_D_ENTREE = (
    "file_path", "notebook_path", "path", "command", "pattern", "url", "description",
    "subagent_type", "slug", "titre", "title", "nom", "name", "projet", "project",
    "type", "content", "message", "decision", "commande",
)
# Les lancements de la routine de nuit ne se fichent pas eux-mêmes.
ORIGINE_MEMOIRE = "wikichat:memoire"
TYPES_PROPOSES = ("preference", "profil", "interpretation")
PROPOSITIONS_PAR_CONVERSATION = 3
ETATS_ACTIFS = ("running", "created")


# ── Lire une conversation, sans rien écrire ──────────────────────────────────


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _date(texte: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(texte).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def genre_de(rec: Any, settings: Any) -> str:
    """`assistant` pour une conversation de l'Assistant, `code` sinon (comme les profils)."""
    if str(getattr(rec, "kind", "") or "") == "assistant":
        return "assistant"
    cwd = str(getattr(rec, "cwd", "") or "")
    racine = getattr(settings, "assistant_root", None)
    if cwd and racine:
        try:
            Path(cwd).resolve().relative_to(Path(racine).resolve())
            return "assistant"
        except (ValueError, OSError):
            pass
    return "code"


def empreinte_de(rec: Any, registres: list[Path]) -> str:
    """Change quand la conversation grandit ; ne dit rien de son contenu."""
    parts = [str(getattr(rec, "updated_at", "") or "")]
    for r in registres:
        try:
            st = r.stat()
            parts.append(f"{r.name}:{st.st_size}")
        except OSError:
            parts.append(f"{r.name}:-")
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def meta_de(rec: Any, store: Any, *, repos_min: int = REPOS_MIN) -> dict[str, Any]:
    settings = store.settings
    registres = store.registres_de(rec)
    modifie = _date(getattr(rec, "updated_at", "") or "")
    age_min = (_maintenant() - modifie).total_seconds() / 60 if modifie else None
    etat = str(getattr(rec, "state", "") or "")
    au_repos = etat not in ETATS_ACTIFS and age_min is not None and age_min >= repos_min
    return {
        "id": rec.session_id,
        "cli_id": (getattr(rec, "claude_session_id", "") or rec.session_id).strip(),
        "projet": rec.slug,
        "genre": genre_de(rec, settings),
        "titre": getattr(rec, "title", "") or "",
        "etat": etat,
        "cree_le": getattr(rec, "created_at", "") or "",
        "modifie_le": getattr(rec, "updated_at", "") or "",
        "tours": int(getattr(rec, "turns", 0) or 0),
        "lance_par": getattr(rec, "lance_par", "") or "",
        "au_repos": bool(au_repos or etat == "archived"),
        "close": etat == "archived",
        "empreinte": empreinte_de(rec, registres),
    }


def _court(valeur: Any, n: int) -> str:
    texte = valeur if isinstance(valeur, str) else str(valeur)
    return texte if len(texte) <= n else texte[:n] + "…"


def _relatif(chemin: str, cwd: str) -> str:
    """Un chemin de fichier, relatif au dossier de la conversation quand il y est."""
    if not chemin or not cwd:
        return chemin
    try:
        return Path(chemin).resolve().relative_to(Path(cwd).resolve()).as_posix()
    except (ValueError, OSError):
        return chemin


def _entree_abregee(entree: Any, cwd: str) -> dict[str, Any]:
    if not isinstance(entree, dict):
        return {}
    sortie: dict[str, Any] = {}
    for cle in CLES_D_ENTREE:
        if cle not in entree or entree[cle] in (None, "", [], {}):
            continue
        valeur = entree[cle]
        if cle in ("file_path", "notebook_path", "path") and isinstance(valeur, str):
            valeur = _relatif(valeur, cwd)
        if isinstance(valeur, (dict, list)):
            continue
        sortie[cle] = _court(valeur, ENTREE_MAX) if isinstance(valeur, str) else valeur
    return sortie


def _texte_du_resultat(bloc: dict[str, Any]) -> str:
    contenu = bloc.get("content")
    if isinstance(contenu, str):
        return contenu
    if isinstance(contenu, list):
        return " ".join(str(b.get("text") or "") for b in contenu if isinstance(b, dict))
    return ""


def evenements_de(entrees: list[dict[str, Any]], cwd: str = "") -> tuple[list[dict[str, Any]], bool]:
    """Le transcript réduit : ce qu'une extraction par le code lit, rien de plus.

    Rend `(evenements, tronque)`. Les textes restent bruts ici : le filtre des
    secrets s'applique à la sortie (`transcript_filtre`).
    """
    from mcp_gateway.atelier.journal import texte_dune_entree

    sortie: list[dict[str, Any]] = []
    tronque = False

    def ajouter(ev: dict[str, Any]) -> None:
        nonlocal tronque
        if len(sortie) >= EVENEMENTS_MAX:
            tronque = True
            return
        sortie.append(ev)

    for e in entrees:
        quand = str(e.get("timestamp") or "")
        surface = str(e.get("entrypoint") or "")
        base = {"quand": quand, **({"surface": surface} if surface else {})}
        genre = e.get("type")
        contenu = (e.get("message") or {}).get("content")
        if genre == "user":
            if isinstance(contenu, list) and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in contenu):
                for b in contenu:
                    if not isinstance(b, dict) or b.get("type") != "tool_result":
                        continue
                    ev = {**base, "role": "resultat", "outil_id": str(b.get("tool_use_id") or "")}
                    if b.get("is_error"):
                        ev["erreur"] = True
                        ev["texte"] = _court(_texte_du_resultat(b), ERREUR_MAX)
                    ajouter(ev)
                continue
            texte = texte_dune_entree(e).strip()
            if texte:
                if len(texte) > TEXTE_MAX:
                    tronque = True
                ajouter({**base, "role": "personne", "texte": _court(texte, TEXTE_MAX)})
        elif genre == "assistant":
            if isinstance(contenu, str):
                if contenu.strip():
                    ajouter({**base, "role": "modele", "texte": _court(contenu.strip(), TEXTE_MAX)})
                continue
            for b in contenu if isinstance(contenu, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and str(b.get("text") or "").strip():
                    ajouter({**base, "role": "modele", "texte": _court(str(b["text"]).strip(), TEXTE_MAX)})
                elif b.get("type") == "tool_use":
                    ajouter({
                        **base, "role": "outil", "outil": str(b.get("name") or ""),
                        "outil_id": str(b.get("id") or ""), "entree": _entree_abregee(b.get("input"), cwd),
                    })
        elif genre == "result":
            usage = e.get("usage") if isinstance(e.get("usage"), dict) else {}
            entree_jetons = sum(int(usage.get(k) or 0) for k in (
                "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
            ev = {**base, "role": "fin", "erreur": bool(e.get("is_error")),
                  "sous_type": str(e.get("subtype") or "")}
            if usage:
                ev["jetons"] = {"entree": entree_jetons, "sortie": int(usage.get("output_tokens") or 0)}
            ajouter(ev)
    return sortie, tronque


def transcript_filtre(store: Any, rec: Any) -> dict[str, Any]:
    """La conversation, réduite et filtrée (T10) : ce que wikichat capitalise."""
    from mcp_gateway.atelier.filtre_transcripts import filtre_pour
    from mcp_gateway.atelier.journal import fondre

    registres = store.registres_de(rec)
    entrees = fondre(registres)
    evenements, tronque = evenements_de(entrees, str(getattr(rec, "cwd", "") or ""))
    corps = {
        "conversation": meta_de(rec, store),
        "evenements": evenements,
        "nombre": len(evenements),
        "tronque": tronque,
    }
    return filtre_pour(store.settings).nettoyer(corps)


# ── wikichat, vu de l'Atelier ────────────────────────────────────────────────


class WikichatAbsent(Exception):
    """wikichat ne répond pas."""


class Wikichat:
    """Les routes mémoire de wikichat (`/api/memoire/*`), avec la clé du lanceur."""

    def __init__(self, settings: Any, *, delai_s: float = 5.0) -> None:
        from mcp_gateway.atelier.wikichat_pilote_proxy import wikichat_http_origin

        self.settings = settings
        self.origine = wikichat_http_origin(settings).rstrip("/")
        self.delai_s = delai_s

    def _entetes(self) -> dict[str, str]:
        from mcp_gateway.atelier.lancements import ENTETE_CLE, lire_la_cle

        cle = lire_la_cle(self.settings)
        return {ENTETE_CLE: cle} if cle else {}

    async def demander(
        self, methode: str, chemin: str, *, params: dict[str, Any] | None = None, corps: Any = None
    ) -> tuple[int, Any]:
        import httpx

        propres = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            async with httpx.AsyncClient(timeout=self.delai_s) as client:
                reponse = await client.request(
                    methode, f"{self.origine}{chemin}", params=propres or None,
                    json=corps, headers=self._entetes(),
                )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.TransportError) as exc:
            raise WikichatAbsent(type(exc).__name__) from None
        try:
            charge = reponse.json()
        except ValueError:
            charge = {"texte": reponse.text[:500]}
        return reponse.status_code, charge


def wikichat_de(app: Any) -> Wikichat:
    """Le client, remplaçable par un test (`app.state.wikichat_memoire`)."""
    client = getattr(app.state, "wikichat_memoire", None)
    if client is None:
        client = Wikichat(app.state.settings)
        app.state.wikichat_memoire = client
    return client


# ── Propositions de mémoire ──────────────────────────────────────────────────


def normaliser_texte(texte: str) -> str:
    return " ".join(str(texte or "").split()).strip()


def empreinte_de_proposition(type_: str, texte: str) -> str:
    brut = f"memoire|{type_}|{normaliser_texte(texte).lower()}"
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


def deposer_une_proposition(
    file: Any,
    settings: Any,
    *,
    type_: str,
    texte: str,
    acteur: str,
    conversation: str = "",
    projet: str = "",
    raison: str = "",
    fiche: str = "",
) -> Any:
    """Dépose une proposition de mémoire dans « À valider ». Lève `ValueError` si elle n'est pas recevable.

    Le texte passe par le filtre des secrets ; la même proposition, encore en
    attente, n'est pas dupliquée ; au plus trois par conversation (A-7,
    `assistant-contexte.md` §3.4 : contre le bruit).
    """
    from mcp_gateway.atelier.filtre_transcripts import filtre_pour

    type_ = str(type_ or "").strip().lower()
    if type_ not in TYPES_PROPOSES:
        raise ValueError(f"type : {', '.join(TYPES_PROPOSES)}")
    filtre = filtre_pour(settings)
    texte = filtre.texte(normaliser_texte(texte))[:300]
    if len(texte) < 3:
        raise ValueError("texte vide")
    raison = filtre.texte(normaliser_texte(raison))[:300]
    cle_conversation = conversation or acteur
    if cle_conversation:
        deja = [
            p for p in file.lister(statut="", source="memoire")
            if str((p.detail or {}).get("conversation") or p.acteur) == cle_conversation
            and p.empreinte != empreinte_de_proposition(type_, texte)
        ]
        if len(deja) >= PROPOSITIONS_PAR_CONVERSATION:
            raise ValueError(
                f"déjà {len(deja)} propositions de mémoire pour cette conversation "
                f"(au plus {PROPOSITIONS_PAR_CONVERSATION})"
            )
    libelles = {"preference": "préférence", "profil": "profil", "interpretation": "interprétation"}
    source = {k: v for k, v in (("conversation", conversation), ("projet", projet), ("fiche", fiche)) if v}
    return file.deposer(
        "memoire",
        f"Retenir ({libelles[type_]}) : {texte[:120]}",
        raison or "Proposé par un modèle ; rien n'est retenu sans votre accord.",
        acteur=acteur,
        projet=projet,
        detail={"type": type_, "texte": texte, "raison": raison, **({"conversation": conversation} if conversation else {}),
                **({"fiche": fiche} if fiche else {})},
        # Arguments à plat : l'écran « À valider » les montre tels quels.
        action={"commande": "atelier_memoire_retenir", "arguments": {"type": type_, "texte": texte, **source}},
        empreinte=empreinte_de_proposition(type_, texte),
    )


# ── Les routes ───────────────────────────────────────────────────────────────


def construire_le_routeur(app: Any) -> APIRouter:
    from mcp_gateway.atelier.auth import ENTETE_INTERFACE
    from mcp_gateway.atelier.lancements import lire_la_cle
    from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
    from mcp_gateway.auth import bearer_from_header

    router = APIRouter(prefix="/v1/memoire")

    def lecteur(request: Request, cle: str | None, authorization: str | None) -> str:
        """La clé du lanceur (wikichat), ou le propriétaire (clé ou session)."""
        attendue = lire_la_cle(app.state.settings)
        if cle and attendue and secrets.compare_digest(cle.strip(), attendue):
            return "lanceur"
        return app.state.auth.check_api(
            bearer_from_header(authorization),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )

    @router.get("/conversations")
    def lister(
        request: Request,
        repos_min: int = REPOS_MIN,
        depuis: str = "",
        inclure_memoire: bool = False,
        limite: int = 500,
        cle: Annotated[str | None, Header(alias=ENTETE_CLE)] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        lecteur(request, cle, authorization)
        store = app.state.store
        sortie = []
        for rec in store.list_sessions(include_archived=True):
            if not inclure_memoire and str(getattr(rec, "lance_par", "") or "").startswith(ORIGINE_MEMOIRE):
                continue
            if depuis and str(getattr(rec, "updated_at", "") or "") < depuis:
                continue
            sortie.append(meta_de(rec, store, repos_min=max(0, repos_min)))
            if len(sortie) >= max(1, min(limite, 2000)):
                break
        return {"conversations": sortie, "nombre": len(sortie), "repos_min": repos_min}

    @router.get("/conversations/{identifiant}")
    def lire(
        request: Request,
        identifiant: str,
        cle: Annotated[str | None, Header(alias=ENTETE_CLE)] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        from mcp_gateway.atelier.commandes.profils import fiche_de_la_conversation

        lecteur(request, cle, authorization)
        rec = fiche_de_la_conversation(app.state.store, identifiant)
        if rec is None:
            raise HTTPException(404, f"conversation inconnue : {identifiant[:80]}")
        return JSONResponse(transcript_filtre(app.state.store, rec))

    @router.post("/propositions")
    async def proposer(
        request: Request,
        cle: Annotated[str | None, Header(alias=ENTETE_CLE)] = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        qui = lecteur(request, cle, authorization)
        try:
            corps = await request.json()
        except ValueError:
            raise HTTPException(422, "corps JSON attendu") from None
        if not isinstance(corps, dict):
            raise HTTPException(422, "corps JSON attendu")
        acteur = {"lanceur": f"automate:{ORIGINE_MEMOIRE}", "session": "personne"}.get(qui, "cle-proprietaire")
        try:
            p = deposer_une_proposition(
                app.state.a_valider,
                app.state.settings,
                type_=str(corps.get("type") or ""),
                texte=str(corps.get("texte") or ""),
                acteur=acteur,
                conversation=str(corps.get("conversation") or "")[:200],
                projet=str(corps.get("projet") or "")[:100],
                raison=str(corps.get("raison") or ""),
                fiche=str(corps.get("fiche") or "")[:200],
            )
        except ValueError as exc:
            return JSONResponse({"statut": "refus", "erreur": str(exc)}, status_code=422)
        return JSONResponse({"statut": "fait", "proposition": p.to_dict()})

    return router


__all__ = [
    "ORIGINE_MEMOIRE",
    "REPOS_MIN",
    "Wikichat",
    "WikichatAbsent",
    "construire_le_routeur",
    "deposer_une_proposition",
    "empreinte_de_proposition",
    "evenements_de",
    "genre_de",
    "meta_de",
    "transcript_filtre",
    "wikichat_de",
]
