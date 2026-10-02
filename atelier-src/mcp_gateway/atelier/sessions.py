"""Registre de sessions Atelier — métadonnées PVC, pas le process."""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, Request

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import (
    AtelierEvent,
    Harness,
    TurnResult,
    effort_valide,
    mode_permission_valide,
    new_session_id,
)
from mcp_gateway.atelier.projects import ProjectStore
from mcp_gateway.atelier.vscode_handoff import (
    PROGRAMMATIQUE,
    dossier_transcripts_claude,
    marque_origine,
    nommer_pour_l_extension,
    rendre_visible_a_l_extension,
)
from mcp_gateway.atelier.journal import (
    a_absorber,
    fondre,
    histoire_unifiee,
    paroles_humaines,
    uuids_connus,
)

log = logging.getLogger("atelier.sessions")

SessionState = Literal[
    "idle",
    "running",
    "done",
    "failed",
    "timeout",
    "interrupted",
    "created",
    "archived",
]

WorkspaceKind = Literal["assistant", "code"]


def _kind_for_slug(settings: AtelierSettings, slug: str) -> WorkspaceKind:
    if slug == settings.assistant_slug:
        return "assistant"
    return "code"


def _project_cwd(settings: AtelierSettings, slug: str) -> Path:
    if slug == settings.assistant_slug:
        return settings.assistant_root
    return settings.projects_dir / slug


def _assistant_session_cwd(settings: AtelierSettings, session_id: str) -> Path:
    return settings.assistant_sessions_dir / session_id


def _cwd_for_new_session(
    settings: AtelierSettings,
    slug: str,
    kind: WorkspaceKind,
    session_id: str,
) -> Path:
    if kind == "assistant":
        return _assistant_session_cwd(settings, session_id)
    return _project_cwd(settings, slug)


def _deplacer_transcript_claude(ancien: Path, nouveau: Path, cli_id: str) -> bool:
    """Emmene l'historique quand la conversation change de dossier.

    Claude Code range ses transcripts par repertoire de travail : deplacer une
    conversation sans deplacer son journal revient a la perdre — au tour
    suivant le CLI ne la trouve plus la ou il la cherche et en ouvre une
    neuve, les echanges precedents devenant injoignables.
    """
    source = dossier_transcripts_claude(ancien) / f"{cli_id}.jsonl"
    if not source.is_file():
        return False
    cible = dossier_transcripts_claude(nouveau) / f"{cli_id}.jsonl"
    if cible.exists():
        return False
    cible.parent.mkdir(parents=True, exist_ok=True)
    os.replace(source, cible)
    log.info("transcript %s suivi de %s vers %s", cli_id[:8], ancien, nouveau)
    return True


def _normalize_assistant_cwd(settings: AtelierSettings, rec: SessionRecord) -> Path:
    """Sessions assistant legacy (cwd = racine mémoire) → sous-dossier session."""
    if rec.kind != "assistant":
        return Path(rec.cwd)
    root = settings.assistant_root.resolve()
    current = Path(rec.cwd).resolve()
    expected = _assistant_session_cwd(settings, rec.session_id).resolve()
    if current == root:
        expected.mkdir(parents=True, exist_ok=True)
        _deplacer_transcript_claude(
            current, expected, (rec.claude_session_id or rec.session_id).strip()
        )
        rec.cwd = str(expected)
        if not rec.overlay_path:
            rec.overlay_path = str(expected)
    return Path(rec.cwd)


# Les prises de parole que le CLI se rédige à lui-même sous le rôle « user ».
# Aucune ne dit de quoi parle la conversation, et deux fils repris après
# compaction portaient ainsi le même titre — celui d'un préambule.
PREAMBULES_SYNTHETIQUES = (
    "This session is being continued",
    "Caveat: The messages below were generated",
    "<system-reminder>",
    "<command-name>",
    "<local-command-stdout>",
)

# Ce qu'on dit à un tour qu'on a dû arrêter en route, une fois la conversation
# résumée. Écrit du point de vue de qui reprend : il ne se souvient plus du
# détail, seulement du résumé qu'on vient de lui faire.
MESSAGE_DE_REPRISE = (
    "Ton tour précédent a été arrêté : la conversation devenait trop lourde "
    "pour le modèle, et elle vient d'être résumée. Reprends où tu en étais, "
    "à partir de ce résumé. Si tu ne sais plus où tu en étais, dis-le et "
    "attends plutôt que de recommencer."
)

# Au-delà, on renonce : un transcript de plusieurs milliers de lignes dont
# aucune n'est de quelqu'un n'aura pas de titre plus bas non plus.
LIGNES_CHERCHEES_POUR_LE_TITRE = 500


def titre_utilisable(texte: str) -> bool:
    """Un titre doit dire de quoi l'on parle, pas d'où l'on vient.

    Ni un préambule du CLI, ni du balisage : un premier message qui colle une
    page HTML donnait pour titre « <!DOCTYPE html> <html lang=… » (lot H).
    """
    debut = (texte or "").strip()
    if not debut or debut.startswith(PREAMBULES_SYNTHETIQUES):
        return False
    return not _BALISE.match(debut)


_BALISE = re.compile(r"^\s*(<[!?/a-zA-Z]|```|\{\s*\"|\[\s*\{)")
_BALISES = re.compile(r"<[^>]{0,400}>")
_BLOC_DE_CODE = re.compile(r"```.*?(```|$)", re.S)


def titre_lisible(texte: str, taille: int = 60) -> str:
    """Ce qu'un premier message dit en mots : sans balises, ni code, ni JSON.

    Rend une chaîne vide quand il ne reste rien de lisible : mieux vaut alors
    le titre par défaut qu'un morceau de code.
    """
    brut = _BLOC_DE_CODE.sub(" ", texte or "")
    brut = re.sub(r"<(script|style)\b.*?(</\1>|$)", " ", brut, flags=re.S | re.I)
    brut = _BALISES.sub(" ", brut)
    mots = " ".join(brut.split())
    if not mots or mots.startswith(("{", "[")) or not re.search(r"[A-Za-zÀ-ÿ]{3}", mots):
        return ""
    return mots[:taille].strip()


def _default_title(slug: str, session_id: str) -> str:
    short = session_id[:8]
    if slug:
        return f"{slug}-{short}"
    return short


def _is_auto_title(title: str, slug: str, session_id: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    if t == _default_title(slug, session_id):
        return True
    if re.match(r"^[a-f0-9]{8}$", t):
        return True
    return _est_un_nom_derive(t, slug)


def _est_un_nom_derive(nom: str, slug: str) -> bool:
    """Le nom que le CLI se donne en attendant d'en avoir un.

    Il prend le dossier et deux caractères au hasard, « nouveau-projet-6d » :
    rien de ce dont on parle. Une conversation dont le premier tour n'a pas
    abouti le gardait pour titre, et la liste en alignait trois pareils.
    """
    return bool(slug) and re.fullmatch(re.escape(slug) + r"-[0-9a-f]{2}", nom) is not None


def _est_un_tour(message: dict[str, Any]) -> bool:
    """Vrai si ce message vient de quelqu'un, et non d'un outil.

    Les retours d'outils voyagent dans des enregistrements « user ».
    Les compter comme des tours ferait annoncer trente-deux echanges la
    ou il y en a eu deux.
    """
    contenu = message.get("content")
    if isinstance(contenu, str):
        return bool(contenu.strip())
    if not isinstance(contenu, list):
        return False
    return any(
        isinstance(b, dict)
        and b.get("type") != "tool_result"
        and str(b.get("text") or "").strip()
        for b in contenu
    )


def _claude_name_rank(data: dict[str, Any]) -> int:
    src = str(data.get("nameSource") or "")
    if src in ("user", "custom", "prompt"):
        return 3
    if src == "derived":
        return 1
    return 2


# La règle d'absorption en vigueur. On a d'abord repris ce qui portait un autre
# point d'entrée que le nôtre, ce qui laissait dehors les entrées de nos propres
# tours que le harnais ne consigne pas. Le `uuid` les attrape toutes ; changer de
# règle demande d'incrémenter ce nombre, faute de quoi les conversations déjà
# marquées garderaient le trou de l'ancienne.
CRITERE_ABSORPTION = 1

# L'adoption des conversations nées dans VS Code se fait à la lecture de la
# liste. Deux lectures simultanées — l'interface en lance plusieurs d'affilée,
# et chaque onglet relit toutes les quinze secondes — voyaient le même
# transcript sans fiche et en créaient chacune une : deux fiches pour un même
# fil CLI (lot H). Une seule adoption à la fois, pour tout le processus.
_VERROU_ADOPTION = threading.RLock()


# Ce que dit `entrypoint` dans `<config>/sessions/<pid>.json` (relevé en 2.1.282).
SURFACES_DES_ENTREES = {"claude-vscode": "vscode", "cli": "terminal", "sdk-cli": "atelier", "sdk-ts": "atelier"}


def dossiers_de_config_claude(settings: AtelierSettings) -> list[Path]:
    """Où Claude Code tient ses fichiers de processus : `CLAUDE_CONFIG_DIR`, `~/.claude`, le volume."""
    from mcp_gateway.atelier.claude_home import durable_claude_dir, home_claude_dir

    candidats = []
    if os.environ.get("CLAUDE_CONFIG_DIR"):
        candidats.append(Path(os.environ["CLAUDE_CONFIG_DIR"]))
    candidats += [home_claude_dir(), durable_claude_dir(settings)]
    vus: list[Path] = []
    for c in candidats:
        try:
            r = c.resolve()
        except OSError:
            continue
        if r not in vus:
            vus.append(r)
    return vus


def pid_vivant(pid: int) -> bool:
    """Le processus existe-t-il ? Sans jamais lui envoyer de signal.

    Sous Windows, `os.kill(pid, 0)` enverrait CTRL_C_EVENT : on demande l'état
    au système à la place.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            import ctypes

            noyau = ctypes.windll.kernel32  # type: ignore[attr-defined]
            poignee = noyau.OpenProcess(0x1000, False, int(pid))
            if not poignee:
                return False
            try:
                code = ctypes.c_ulong()
                noyau.GetExitCodeProcess(poignee, ctypes.byref(code))
                return code.value == 259
            finally:
                noyau.CloseHandle(poignee)
        except (OSError, AttributeError):
            return False
    return Path(f"/proc/{pid}").exists()


def mode_de_la_ligne_de_commande(argv: list[str]) -> str | None:
    """Le mode que la ligne de commande d'un `claude` lui a donné, s'il le dit."""
    for a, b in zip(argv, argv[1:]):
        if a == "--permission-mode":
            return b
    for a in argv:
        if a.startswith("--permission-mode="):
            return a.split("=", 1)[1]
        if a == "--dangerously-skip-permissions":
            return "bypassPermissions"
    return None


def _ligne_de_commande(pid: int) -> list[str]:
    try:
        brut = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode("utf-8", "replace") for a in brut.split(b"\0") if a]


def processus_cli_de(
    dossiers: list[Path],
    cli_id: str,
    *,
    vivant: Callable[[int], bool] = pid_vivant,
    ligne_de_commande: Callable[[int], list[str]] = _ligne_de_commande,
) -> list[dict[str, Any]]:
    """Les processus `claude` vivants dont `sessions/<pid>.json` nomme cette conversation."""
    sortie: list[dict[str, Any]] = []
    if not cli_id:
        return sortie
    vus: set[int] = set()
    for dossier in dossiers:
        repertoire = dossier / "sessions"
        if not repertoire.is_dir():
            continue
        for fichier in repertoire.glob("*.json"):
            try:
                donnees = json.loads(fichier.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(donnees, dict) or donnees.get("sessionId") != cli_id:
                continue
            try:
                pid = int(donnees.get("pid") or fichier.stem)
            except (TypeError, ValueError):
                continue
            if pid in vus or not vivant(pid):
                continue
            vus.add(pid)
            entree = str(donnees.get("entrypoint") or "")
            sortie.append(
                {
                    "pid": pid,
                    "surface": SURFACES_DES_ENTREES.get(entree, entree or "inconnue"),
                    "entrypoint": entree,
                    "statut": donnees.get("status"),
                    "depuis": donnees.get("startedAt"),
                    "version": donnees.get("version"),
                    "mode_au_lancement": mode_de_la_ligne_de_commande(ligne_de_commande(pid)),
                }
            )
    return sortie


def enregistrer_les_routes_des_processus(app: Any) -> None:
    """`GET /v1/sessions/{id}/processus` : la ligne que `api.py` appelle."""
    from mcp_gateway.atelier.auth import ENTETE_INTERFACE
    from mcp_gateway.atelier.vscode_bridge import COOKIE_NAME
    from mcp_gateway.auth import bearer_from_header

    router = APIRouter(prefix="/v1")

    def proprietaire(request: Request) -> str:
        return app.state.auth.check_api(
            bearer_from_header(request.headers.get("authorization")),
            request.cookies.get(COOKIE_NAME),
            request.headers.get(ENTETE_INTERFACE) == "1",
        )

    @router.get("/sessions/{session_id}/processus")
    def processus(session_id: str, _qui: str = Depends(proprietaire)) -> dict[str, Any]:
        try:
            return app.state.store.processus_de_la_conversation(session_id)
        except KeyError:
            raise HTTPException(404, "session not found") from None

    app.include_router(router)


_SLUG_DE_PROJET = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")


def slug_de_projet_valide(slug: str, settings: AtelierSettings) -> str:
    """Le nom d'un dossier de `projects/`, rien d'autre.

    La création de projet impose déjà cette forme ; celle de conversation ne
    la vérifiait pas : `../evasion` donnait un dossier de travail hors de
    `projects/`, `A B` ou une faute de frappe, un projet de plus dans la liste.
    """
    if slug == settings.assistant_slug or _SLUG_DE_PROJET.match(slug or ""):
        return slug
    raise ValueError(f"slug de projet invalide : {str(slug)[:40]!r} (minuscules, chiffres, - et _)")


_MODELE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:\-\[\]]{0,119}$")


def modele_valide(valeur: str) -> str:
    """Un identifiant de modèle ou un alias (`sonnet`, `opus`…), ou vide (= le défaut).

    Même liberté que `--model` : on ne vérifie que la forme, c'est le CLI et
    la passerelle qui savent ce qu'ils servent.
    """
    texte = (valeur or "").strip()
    if not texte:
        return ""
    if not _MODELE.match(texte):
        raise ValueError(f"modèle invalide : {texte[:40]!r}")
    return texte


@dataclass
class SessionRecord:
    session_id: str
    slug: str
    model: str
    state: SessionState = "created"
    cwd: str = ""
    transcript_path: str = ""
    log_path: str = ""
    created_at: str = ""
    updated_at: str = ""
    last_text: str = ""
    cause: str = ""
    turns: int = 0
    kind: WorkspaceKind = "code"
    title: str = ""
    overlay_path: str = ""
    claude_session_id: str = ""
    # "user" quand le titre a ete saisi a la main : la synchronisation avec
    # le nom declare cote Claude/wikichat ne doit alors plus l'ecraser.
    title_source: str = ""
    mcp_overlay: dict[str, Any] = field(default_factory=dict)
    # Comment cette conversation travaille. Vide = le réglage du service.
    # Un mode ne vaut que pour les tours à venir : ce qui est déjà écrit
    # l'a été sous l'ancien.
    permission_mode: str = ""
    effort: str = ""
    # Jusqu'où l'on a déjà recopié le registre du CLI dans le nôtre. Une
    # conversation menée dans VS Code s'écrit là-bas ; sans cette marque, on
    # la relirait en entier à chaque fois, ou on la recopierait deux fois.
    octets_absorbes: int = 0
    # Sous quel critère cette marque a été posée. Quand la règle d'absorption
    # change, la marque d'avant ne vaut plus : elle a pu dépasser des entrées
    # que l'ancienne règle écartait et que la nouvelle reprendrait. On rebalaie
    # une fois, plutôt que de les perdre en silence.
    critere_absorption: int = 0
    # Un agent lancé (lot D) : qui l'a demandé (`wikichat:trigger:…`,
    # `gardien:<contrôle>`, `conversation:<id>`). Vide pour une conversation
    # ouverte par la personne. La vue Agents le lit pour montrer les agents
    # spécifiques à côté des autres.
    lance_par: str = ""
    # Le nom sous lequel cet agent parle à wikichat quand ce n'est pas celui
    # que l'Atelier dérive (`<slug>-<id6>`) : un agent nommé de wikichat
    # (« Librarian ») garde son nom en passant par l'Atelier, et son courrier
    # le trouve.
    nom_wikichat: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SessionRecord:
        fields = cls.__dataclass_fields__
        clean: dict[str, Any] = {}
        for k in fields:
            if k not in data:
                continue
            v = data[k]
            if k == "kind" and v not in ("assistant", "code"):
                continue
            if k == "mcp_overlay" and not isinstance(v, dict):
                continue
            if k == "state" and v == "archived":
                clean[k] = v
                continue
            # L'adoption écrivait « ready », qu'aucun écran ne savait lire : la
            # liste affichait le mot anglais à côté de « au repos ». Ce que
            # cela voulait dire, c'est au repos.
            if k == "state" and v == "ready":
                clean[k] = "idle"
                continue
            clean[k] = v
        rec = cls(**{k: clean[k] for k in clean if k in fields})
        if not rec.title:
            rec.title = _default_title(rec.slug, rec.session_id)
        if not rec.kind:
            rec.kind = "code"
        return rec


class SessionStore:
    def __init__(self, settings: AtelierSettings, harness: Harness) -> None:
        self.settings = settings
        self.harness = harness
        settings.ensure_dirs()

    def _path(self, session_id: str) -> Path:
        return self.settings.sessions_dir / f"{session_id}.json"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def save(self, rec: SessionRecord) -> None:
        """Ecrit la fiche d'un seul geste.

        Deux onglets suffisent a croiser une ecriture et une lecture : ecrire
        en place laisserait voir un fichier a moitie ecrit, et la liste des
        conversations tomberait dessus.
        """
        rec.updated_at = self._now()
        path = self._path(rec.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        provisoire = path.with_name(path.name + ".en-cours")
        provisoire.write_text(
            json.dumps(rec.to_dict(), ensure_ascii=False, indent=2) + chr(10),
            encoding="utf-8",
        )
        # Sous Windows, remplacer un fichier qu'un lecteur tient encore ouvert
        # échoue — là où Linux l'accepte. Depuis qu'un tour peut être conduit
        # d'un côté pendant qu'on le suit de l'autre, les deux se croisent : le
        # tour mourait alors d'un refus d'accès, pour une lecture qui durait un
        # millième de seconde. On réessaie brièvement plutôt que de perdre le
        # tour ; au-delà, l'erreur remonte, car elle ne vient plus de là.
        for essai in range(10):
            try:
                os.replace(provisoire, path)
                return
            except PermissionError:
                if essai == 9:
                    raise
                time.sleep(0.02)

    def get(self, session_id: str) -> SessionRecord | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        return self._avec_son_mode(SessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))

    def _avec_son_mode(self, rec: SessionRecord) -> SessionRecord:
        """Le mode de la conversation, lu à l'endroit unique que partagent les surfaces.

        Le magasin de l'extension VS Code (`modes_permission`), sous
        l'identifiant du CLI : un choix fait dans VS Code se lit ici, et
        inversement. La fiche n'en garde qu'une copie de lecture, pour les
        gardiens qui la lisent sans passer par nous.
        """
        from mcp_gateway.atelier.modes_permission import mode_de_la_conversation

        rec.permission_mode = mode_de_la_conversation(self._claude_cli_id(rec))
        return rec

    def list_sessions(
        self,
        slug: str | None = None,
        *,
        include_archived: bool = False,
    ) -> list[SessionRecord]:
        out: list[SessionRecord] = []
        for p in sorted(self.settings.sessions_dir.glob("*.json")):
            # Une fiche illisible — écriture interrompue, fichier étranger —
            # ne doit pas emporter la liste entière avec elle.
            try:
                rec = SessionRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError, TypeError, ValueError):
                log.warning("fiche de session illisible, ignorée : %s", p.name)
                continue
            if slug is not None and rec.slug != slug:
                continue
            if not include_archived and rec.state == "archived":
                continue
            out.append(self._avec_son_mode(rec))
        out.sort(key=lambda r: r.updated_at or r.created_at, reverse=True)
        return out

    def create(
        self,
        slug: str | None = None,
        model: str | None = None,
        title: str | None = None,
        kind: WorkspaceKind | None = None,
    ) -> SessionRecord:
        sid = new_session_id()
        slug = (slug or self.settings.default_slug).strip() or self.settings.default_slug
        if kind == "assistant":
            # Une conversation de l'Assistant n'a qu'un « projet » : le sien. Un
            # autre nom ne ferait que mentir sur l'endroit où elle travaille.
            slug = self.settings.assistant_slug
        slug_de_projet_valide(slug, self.settings)
        model = model if model is not None else self.settings.default_model
        resolved_kind = kind or _kind_for_slug(self.settings, slug)
        cwd = _cwd_for_new_session(self.settings, slug, resolved_kind, sid)
        cwd.mkdir(parents=True, exist_ok=True)
        if resolved_kind == "assistant":
            from mcp_gateway.atelier.assistant import preparer_la_session

            preparer_la_session(self.settings, cwd)
        overlay_path = str(cwd) if resolved_kind == "assistant" else ""
        tdir = self.settings.transcripts_dir / slug
        tdir.mkdir(parents=True, exist_ok=True)
        transcript = tdir / f"{sid}.jsonl"
        log = self.settings.logs_dir / f"{sid}.log"
        session_title = (title or "").strip() or _default_title(slug, sid)
        rec = SessionRecord(
            session_id=sid,
            slug=slug,
            model=model or "",
            state="created",
            cwd=str(cwd),
            transcript_path=str(transcript),
            log_path=str(log),
            created_at=self._now(),
            updated_at=self._now(),
            kind=resolved_kind,
            title=session_title,
            overlay_path=overlay_path,
        )
        self.save(rec)
        return rec

    def patch(
        self,
        session_id: str,
        *,
        title: str | None = None,
        archived: bool | None = None,
        permission_mode: str | None = None,
        effort: str | None = None,
        model: str | None = None,
    ) -> SessionRecord:
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        if title is not None:
            t = title.strip()
            if not t:
                raise ValueError("title cannot be empty")
            rec.title = t
            rec.title_source = "user"
            # Le nom qu'on donne ici doit être celui qu'on lit dans VS Code :
            # une conversation ne peut pas porter deux noms selon la fenêtre.
            if rec.cwd:
                nommer_pour_l_extension(Path(rec.cwd), self._claude_cli_id(rec), t)
        if archived is not None:
            if archived:
                rec.state = "archived"
            elif rec.state == "archived":
                rec.state = "idle"
        # Le choix de la conversation va à l'endroit unique que lisent l'app,
        # VS Code et le terminal (`modes_permission`). Une chaîne vide rend la
        # conversation au défaut du projet, puis du service ; un mode inconnu
        # vaut celui du service, comme avant.
        if permission_mode is not None:
            from mcp_gateway.atelier.modes_permission import ecrire_mode_de_la_conversation

            demande = permission_mode.strip()
            rec.permission_mode = ecrire_mode_de_la_conversation(
                self.settings,
                self._claude_cli_id(rec),
                mode_permission_valide(demande) if demande else "",
            )
        if effort is not None:
            rec.effort = effort_valide(effort)
        if model is not None:
            # Comme `/model` dans Claude Code : le modèle de la conversation
            # change pour les tours à venir (il est dans l'empreinte du processus
            # gardé, qui repart avec `--model` et reprend la conversation).
            rec.model = modele_valide(model)
        self.save(rec)
        if permission_mode is not None:
            # Le processus gardé de cette conversation ne garde pas l'ancien
            # mode (constaté le 26/09 : un bypass qui survivait au retour au
            # défaut du projet). Celui de VS Code, l'Atelier ne le pilote pas :
            # `processus_de_la_conversation` dit s'il est ouvert.
            from mcp_gateway.atelier.modes_permission import mode_resolu

            try:
                nouveau, _source = mode_resolu(self.settings, rec.cwd, self._claude_cli_id(rec))
                self.harness.changer_de_mode(session_id, nouveau)
            except (OSError, ValueError) as exc:
                log.warning("mode de %s non transmis au processus : %s", session_id, exc)
        return rec

    def defaut_du_projet_change(self, slug: str) -> dict[str, str]:
        """Le défaut d'un projet a changé : prévenir les processus de ses conversations qui le suivent.

        Une conversation qui a son propre choix de mode le garde ; les autres
        suivent le projet, et leur processus gardé ne doit pas garder l'ancien
        défaut. Rend `{conversation: aucun|eteint|envoye}`.
        """
        from mcp_gateway.atelier.modes_permission import mode_de_la_conversation, mode_resolu

        faits: dict[str, str] = {}
        for rec in self.list_sessions(slug):
            cli_id = self._claude_cli_id(rec)
            if mode_de_la_conversation(cli_id):
                continue
            try:
                nouveau, _source = mode_resolu(self.settings, rec.cwd, cli_id)
                faits[rec.session_id] = self.harness.changer_de_mode(rec.session_id, nouveau)
            except (OSError, ValueError) as exc:
                log.warning("mode de %s non transmis au processus : %s", rec.session_id, exc)
        return faits

    def processus_de_la_conversation(self, session_id: str) -> dict[str, Any]:
        """Les processus `claude` vivants de cette conversation, et ce que vaut un changement de mode.

        Lus dans `<config>/sessions/<pid>.json`, que Claude Code tient pour
        chaque processus (`sessionId`, `entrypoint`, `status`) : VS Code
        (`claude-vscode`), le terminal (`cli`), les tours de l'Atelier. Le mode
        au lancement vient de la ligne de commande (`/proc`, Linux seulement).

        L'Atelier ne pilote que ses propres processus. Celui de VS Code garde
        son mode jusqu'à ce que l'onglet se ferme : l'interface doit dire
        « s'applique à la prochaine ouverture dans VS Code ».
        """
        rec = self.get(session_id)
        if rec is None:
            raise KeyError(session_id)
        from mcp_gateway.atelier.modes_permission import mode_resolu

        cli_id = self._claude_cli_id(rec)
        choisi, source = mode_resolu(self.settings, rec.cwd, cli_id)
        processus = processus_cli_de(dossiers_de_config_claude(self.settings), cli_id)
        gardes = getattr(self.harness, "processus_vivants", None)
        atelier = self.harness.tour_en_cours(session_id) or (
            callable(gardes) and session_id in gardes()
        )
        if atelier and not any(p["surface"] == "atelier" for p in processus):
            processus.append({"pid": None, "surface": "atelier", "statut": "garde", "mode_au_lancement": None})
        vscode = [p for p in processus if p["surface"] == "vscode"]
        sortie: dict[str, Any] = {
            "conversation": session_id,
            "cli_id": cli_id,
            "mode_choisi": choisi,
            "source_du_mode": source,
            "processus": processus,
            "vscode_vivant": bool(vscode),
        }
        if vscode:
            sortie["note"] = (
                "Un onglet VS Code de cette conversation est ouvert : un changement de mode "
                "s'applique à la prochaine ouverture dans VS Code."
            )
            differents = [p for p in vscode if p.get("mode_au_lancement") and p["mode_au_lancement"] != choisi]
            if differents:
                sortie["ecart"] = {"vivant": differents[0]["mode_au_lancement"], "choisi": choisi}
        return sortie

    def delete(self, session_id: str, *, remove_files: bool = True) -> None:
        rec_avant = self.get(session_id)
        if rec_avant is not None:
            self._refuser_adoption(self._claude_cli_id(rec_avant))
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        path = self._path(session_id)
        if path.is_file():
            path.unlink()
        # Ce qu'on avait accordé à cette conversation disparaît avec elle : une
        # règle sans fil auquel se rattacher n'autorise plus rien, mais elle
        # traînerait sur le disque, et un identifiant réutilisé la retrouverait.
        self.harness.decisions.oublier_les_regles(session_id)
        self.harness.decisions.abandonner(session_id)
        self.harness.decisions.oublier_les_questions(session_id)
        self.harness.messages.vider(session_id)
        # La configuration MCP effective est refaite à chaque tour ; celle
        # d'une conversation supprimée ne sert plus à rien et restait pourtant
        # là. Soixante et une traînaient pour quatorze conversations.
        try:
            (self.settings.mcp_effective_dir / f"{session_id}.json").unlink(missing_ok=True)
        except OSError:
            pass
        if remove_files:
            for fp in (rec.transcript_path, rec.log_path):
                p = Path(fp)
                if p.is_file():
                    p.unlink()

    def _journal_refus(self) -> Path:
        # Hors du dossier des fiches : celui-ci est lu au lance-pierre, tout
        # « .json » qui s'y trouve est pris pour une conversation.
        return self.settings.work_dir / ".atelier" / "adoptions-refusees.json"

    def _refuser_adoption(self, identifiant: str) -> None:
        """Retient qu'on ne veut plus de cette conversation.

        Supprimer une fiche n'efface pas le transcript que Claude Code garde
        de son cote. Sans cette trace, la passe d'alignement le retrouverait
        orphelin et l'adopterait a nouveau dans la seconde : la conversation
        reviendrait sous un autre identifiant, aussitot supprimee, aussitot
        revenue.
        """
        if not identifiant:
            return
        chemin = self._journal_refus()
        refuses = self._adoptions_refusees()
        refuses.add(identifiant)
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(sorted(refuses), indent=2) + chr(10), encoding="utf-8")

    def _adoptions_refusees(self) -> set[str]:
        try:
            data = json.loads(self._journal_refus().read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return set()
        return {str(x) for x in data} if isinstance(data, list) else set()

    def _ids_revendiques(self) -> set[str]:
        """Tous les identifiants qu'une fiche reclame, ou qu'on a ecartes."""
        pris: set[str] = self._adoptions_refusees()
        for rec in self.list_sessions(include_archived=True):
            pris.add(rec.session_id)
            if rec.claude_session_id:
                pris.add(rec.claude_session_id)
        return pris

    def _convertir_transcript_claude(self, source: Path) -> tuple[list[str], int]:
        """Recopie une conversation de Claude Code au format que l'Atelier lit.

        Les deux journaux disent la meme chose autrement : meme enregistrements
        `user` et `assistant`, meme objet `message`. Claude y ajoute de quoi
        reconstituer un arbre — parents, repertoire, branche git — dont
        l'affichage n'a pas l'usage, et nomme la session `sessionId` la ou le
        flux du CLI ecrit `session_id`.

        On ne garde donc que ce qui se lit, et on rend les lignes avec le
        nombre de tours — sans rien écrire, pour pouvoir renoncer avant
        d'avoir créé quoi que ce soit.
        """
        tours = 0
        lignes: list[str] = []
        try:
            brut = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return [], 0
        for ligne in brut.split("\n"):
            ligne = ligne.strip()
            if not ligne.startswith("{"):
                continue
            try:
                enr = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if enr.get("type") not in ("user", "assistant") or enr.get("isSidechain"):
                continue
            message = enr.get("message")
            if not isinstance(message, dict):
                continue
            if enr["type"] == "user" and not enr.get("isMeta") and _est_un_tour(message):
                tours += 1
            lignes.append(
                json.dumps(
                    {
                        "type": enr["type"],
                        "message": message,
                        "session_id": enr.get("sessionId") or "",
                        "uuid": enr.get("uuid") or "",
                        "timestamp": enr.get("timestamp") or "",
                        "parent_tool_use_id": None,
                    },
                    ensure_ascii=False,
                )
            )
        return lignes, tours

    def _titre_depuis_claude(self, source: Path) -> str:
        """Le premier mot de quelqu'un, qui vaut mieux qu'un identifiant.

        Le premier n'est pas toujours de quelqu'un. Une conversation reprise
        après compaction commence par un résumé que le CLI se rédige à
        lui-même, sous le rôle « user » : deux conversations du pod s'appelaient
        ainsi « This session is being continued from a previous… », ce qui ne
        dit rien et les rendait indiscernables l'une de l'autre. On saute ces
        prises de parole-là et l'on continue à chercher la vraie.

        Et l'on parcourt le fichier ligne à ligne : ce résumé pèse parfois plus
        que les 64 ko qu'on lisait d'un coup, si bien que le vrai premier
        message tombait hors de portée et qu'il ne restait plus de titre du
        tout.
        """
        try:
            with source.open(encoding="utf-8", errors="replace") as f:
                for numero, ligne in enumerate(f):
                    if numero > LIGNES_CHERCHEES_POUR_LE_TITRE:
                        break
                    ligne = ligne.strip()
                    if not ligne.startswith("{") or '"type":"user"' not in ligne:
                        continue
                    try:
                        enr = json.loads(ligne)
                    except json.JSONDecodeError:
                        continue
                    if enr.get("isMeta") or enr.get("isSidechain"):
                        continue
                    contenu = (enr.get("message") or {}).get("content")
                    if isinstance(contenu, str):
                        texte = contenu
                    elif isinstance(contenu, list):
                        texte = " ".join(
                            b.get("text", "")
                            for b in contenu
                            if isinstance(b, dict) and b.get("type") == "text"
                        )
                    else:
                        continue
                    texte = " ".join(texte.split())
                    if texte and not texte.startswith(PREAMBULES_SYNTHETIQUES):
                        lisible = titre_lisible(texte)
                        if lisible:
                            return lisible
        except OSError:
            return ""
        return ""

    def adopter_conversations_claude(self) -> list[str]:
        with _VERROU_ADOPTION:
            return self._adopter_conversations_claude()

    def _adopter_conversations_claude(self) -> list[str]:
        """Fait entrer dans l'Atelier les conversations nees dans VS Code.

        L'alignement etait a sens unique : ce que l'Atelier connaissait,
        l'extension pouvait le rouvrir, mais une discussion ouverte depuis
        l'extension restait invisible cote Code. Les deux listes doivent
        montrer la meme chose.

        On adopte exactement ce que l'extension elle-meme accepte de montrer :
        un transcript pose dans le dossier d'un projet connu, que reclame
        aucune fiche, et qui n'est pas marque comme programmatique. Ce dernier
        point ecarte de lui-meme les restes d'essais du harnais, qui portent
        cette marque et que personne ne veut voir remonter.
        """
        pris = self._ids_revendiques()
        adoptees: list[str] = []
        projets = ProjectStore(self.settings)
        # Y compris les projets archives : une conversation ouverte dans
        # VS Code sur l'un d'eux doit remonter tout de suite, plutot que
        # d'arriver en bloc le jour ou on le desarchive.
        for projet in projets.list_projects(include_archived=True):
            if projet.kind == "assistant":
                continue
            cwd = Path(projet.path)
            dossier = dossier_transcripts_claude(cwd)
            if not dossier.is_dir():
                continue
            for source in sorted(dossier.glob("*.jsonl")):
                sid = source.stem
                if sid in pris:
                    continue
                try:
                    with source.open(encoding="utf-8", errors="replace") as f:
                        tete = f.read(65536)
                except OSError:
                    continue
                marque = marque_origine(tete)
                if not marque or marque in PROGRAMMATIQUE:
                    continue
                if '"isSidechain":true' in tete.split(chr(10))[0]:
                    continue
                # Juger avant de créer : une conversation ouverte dans
                # l'extension et laissée vide reviendrait sinon à chaque
                # passage, le temps d'une fiche aussitôt détruite.
                reprises, tours = self._convertir_transcript_claude(source)
                if tours <= 0:
                    continue
                rec = self.create(slug=projet.slug, title=self._titre_depuis_claude(source))
                rec.claude_session_id = sid
                rec.cwd = str(cwd)
                rec.turns = tours
                journal = Path(rec.transcript_path)
                journal.parent.mkdir(parents=True, exist_ok=True)
                journal.write_text(chr(10).join(reprises) + chr(10), encoding="utf-8")
                rec.state = "idle"
                rec.updated_at = self._now()
                self.save(rec)
                pris.add(sid)
                adoptees.append(rec.session_id)
        return adoptees

    def _tours_de_lutilisateur(self, enregistrements: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Les prises de parole de quelqu'un, dans l'ordre.

        Même règle que le comptage des tours, pour que l'interface et le
        serveur désignent le même message quand ils parlent du n-ième.
        """
        return [
            enr
            for enr in enregistrements
            if enr.get("type") == "user"
            and not enr.get("isMeta")
            and not enr.get("isSidechain")
            and _est_un_tour(enr.get("message") or {})
        ]

    def forker(self, session_id: str, rang: int, *, titre: str = "") -> SessionRecord:
        """Ouvre une conversation qui reprend celle-ci jusqu'avant le n-ième message.

        Une session Claude ne se rembobine pas. Pour corriger une question déjà
        posée, on repart donc d'avant elle : le transcript est recopié jusqu'au
        message qui la précède, sous une nouvelle identité, et la suite s'écrit
        à partir de là. L'originale reste intacte.

        Le fork hérite de tout ce qui fait la conversation — même dossier de
        travail, même projet, mêmes connecteurs : ce sont des propriétés du
        dossier, pas de la session.

        On remonte la chaîne `parentUuid`, qui est complète et porte aussi les
        pièces jointes. Les enregistrements annexes — file d'attente, dernier
        prompt, titre — n'appartiennent pas à cette chaîne et se reconstruisent
        d'eux-mêmes : les recopier ferait référence à une session qui n'est
        plus la bonne.
        """
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        source = dossier_transcripts_claude(Path(rec.cwd)) / f"{self._claude_cli_id(rec)}.jsonl"
        try:
            brut = source.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ValueError(f"transcript introuvable : {exc}") from exc

        enregistrements: list[dict[str, Any]] = []
        for ligne in brut.split(chr(10)):
            ligne = ligne.strip()
            if not ligne.startswith("{"):
                continue
            try:
                enregistrements.append(json.loads(ligne))
            except json.JSONDecodeError:
                continue

        tours = self._tours_de_lutilisateur(enregistrements)
        if rang < 0 or rang >= len(tours):
            raise ValueError(f"message {rang} introuvable ({len(tours)} tours)")

        par_uuid = {e["uuid"]: e for e in enregistrements if e.get("uuid")}
        depart = par_uuid.get(str(tours[rang].get("parentUuid") or ""))
        gardes: set[str] = set()
        courant = depart
        while courant is not None:
            uid = str(courant.get("uuid") or "")
            if not uid or uid in gardes:
                break
            gardes.add(uid)
            courant = par_uuid.get(str(courant.get("parentUuid") or ""))

        nouvel_id = new_session_id()
        lignes = []
        for enr in enregistrements:
            if str(enr.get("uuid") or "") not in gardes:
                continue
            copie = dict(enr)
            # L'enregistrement dit de quelle session il vient : sans cela le
            # fork porterait l'identité de son aîné.
            copie["sessionId"] = nouvel_id
            lignes.append(json.dumps(copie, ensure_ascii=False))

        destination = dossier_transcripts_claude(Path(rec.cwd)) / f"{nouvel_id}.jsonl"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            (chr(10).join(lignes) + chr(10)) if lignes else "", encoding="utf-8"
        )

        nom = (titre or "").strip() or f"{rec.title} (reprise)"
        fork = self.create(slug=rec.slug, model=rec.model or None, title=nom, kind=rec.kind)
        fork.claude_session_id = nouvel_id
        fork.cwd = rec.cwd
        fork.mcp_overlay = dict(rec.mcp_overlay or {})
        fork.title_source = "user"
        reprises, tours_repris = self._convertir_transcript_claude(destination)
        journal = Path(fork.transcript_path)
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text(
            (chr(10).join(reprises) + chr(10)) if reprises else "", encoding="utf-8"
        )
        fork.turns = tours_repris
        fork.state = "idle" if reprises else "created"
        self.save(fork)
        log.info(
            "conversation %s forkée au message %d -> %s (%d enregistrements)",
            session_id[:8],
            rang,
            fork.session_id[:8],
            len(lignes),
        )
        return fork

    def _titrer_au_premier_message(self, rec: SessionRecord, message: str) -> None:
        """Le premier message titre la conversation dès l'envoi, pas à la fin du tour.

        Le titre se retrouvait jusque-là dans le transcript, après le tour
        (`sync_claude_titles`). Pendant tout le premier tour, une conversation
        de l'Assistant s'affichait donc « wikichat-memory-a5827138 » (essais du
        26/09) ; en Code, le projet portait déjà le nom tiré du message et le
        défaut se voyait moins. Même règle que le transcript (`titre_lisible`,
        `titre_utilisable`), pour les deux, et seulement sur un titre par
        défaut : un titre choisi n'est jamais remplacé.
        """
        if rec.turns > 0 or rec.title_source == "user":
            return
        if not _is_auto_title(rec.title, rec.slug, rec.session_id):
            return
        lisible = titre_lisible(" ".join((message or "").split()))
        if not lisible or not titre_utilisable(lisible) or lisible == rec.title:
            return
        rec.title = lisible
        self.save(rec)

    def _titre_du_transcript_claude(self, rec: SessionRecord) -> str:
        """Le titre qu'aurait eu cette fiche si on l'avait su dès l'adoption."""
        if not rec.cwd:
            return ""
        source = dossier_transcripts_claude(Path(rec.cwd)) / (
            self._claude_cli_id(rec) + ".jsonl"
        )
        if not source.is_file():
            return ""
        return self._titre_depuis_claude(source)

    def sync_claude_titles(self) -> dict[str, Any]:
        """Aligne title depuis ~/.claude/sessions (extension / CLI Claude Code)."""
        with _VERROU_ADOPTION:
            return self._sync_claude_titles()

    def _sync_claude_titles(self) -> dict[str, Any]:
        # D'abord faire entrer ce qui manque : une conversation ouverte dans
        # VS Code n'a pas de fiche, et sans fiche rien ne l'aligne.
        self.adopter_conversations_claude()
        updated: list[str] = []
        claude_by_id: dict[str, dict[str, Any]] = {}
        claude_by_cwd: dict[str, list[dict[str, Any]]] = {}
        claude_dirs = [
            Path.home() / ".claude" / "sessions",
            self.settings.work_dir / ".claude" / "sessions",
        ]
        for d in claude_dirs:
            if not d.is_dir():
                continue
            for p in d.glob("*.json"):
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                sid = str(data.get("sessionId") or "")
                name = str(data.get("name") or "").strip()
                cwd = str(data.get("cwd") or "").rstrip("/")
                if sid:
                    claude_by_id[sid] = data
                if cwd and name:
                    claude_by_cwd.setdefault(cwd, []).append(data)

        assigned_claude: set[str] = set()
        records = sorted(
            self.list_sessions(include_archived=True),
            key=lambda r: r.created_at or r.updated_at or "",
        )

        for rec in records:
            # Réparer avant d'aligner : deux conversations du pod portaient le
            # préambule d'une reprise en guise de titre, posé par une version
            # de ce code qui prenait la première prise de parole sans regarder
            # de qui elle venait. Elles ne se seraient jamais renommées seules.
            if rec.title and (
                not titre_utilisable(rec.title)
                or _is_auto_title(rec.title, rec.slug, rec.session_id)
            ):
                retrouve = self._titre_du_transcript_claude(rec)
                if retrouve and retrouve != rec.title:
                    rec.title = retrouve
                    self.save(rec)
                    updated.append(rec.session_id)

            # Les deux listes doivent montrer la même chose : ce que l'Atelier
            # connaît, l'extension doit pouvoir le rouvrir. Elle écarte les
            # conversations marquées « sdk-cli », marque que le CLI pose à
            # chaque tour de l'Atelier — on la corrige ici, une fois par
            # conversation. Les transcripts qu'aucune fiche ne réclame restent
            # masqués, et c'est bien : ce sont des restes, pas des
            # conversations.
            if rec.cwd:
                rendre_visible_a_l_extension(Path(rec.cwd), self._claude_cli_id(rec))

            data = claude_by_id.get(rec.session_id)
            if not data and rec.claude_session_id:
                data = claude_by_id.get(rec.claude_session_id)

            cwd_key = str(rec.cwd).rstrip("/")
            if not data and cwd_key:
                pool = [
                    d
                    for d in claude_by_cwd.get(cwd_key, [])
                    if str(d.get("sessionId") or "") not in assigned_claude
                ]
                if pool:
                    auto = _default_title(rec.slug, rec.session_id)
                    by_name = [
                        d
                        for d in pool
                        if str(d.get("name") or "").strip() in (rec.title, auto)
                    ]
                    if len(by_name) == 1:
                        data = by_name[0]
                    elif len(pool) == 1:
                        data = pool[0]
                    elif rec.turns > 0:
                        # Rapprochement au juge : acceptable pour reprendre un
                        # titre, jamais pour decider de quelle conversation il
                        # s'agit. Une fiche qui n'a pas encore parle n'a pas
                        # d'identite a defendre — lui en preter une reviendrait
                        # a ouvrir la conversation de quelqu'un d'autre.
                        data = max(
                            pool,
                            key=lambda d: (
                                _claude_name_rank(d),
                                d.get("startedAt") or 0,
                            ),
                        )

            if not data:
                continue

            claude_sid = str(data.get("sessionId") or "")
            if claude_sid:
                assigned_claude.add(claude_sid)

            name = str(data.get("name") or "").strip()
            if not name or re.match(r"^[a-f0-9]{8}$", name):
                continue
            # L'IDE reprend parfois le même préambule que nous : le refuser
            # ici aussi, sinon il réécrirait par la bande le titre qu'on vient
            # de retrouver.
            if not titre_utilisable(name):
                continue

            changed = False
            # Une conversation qui a déjà tourné a son identité fixée : c'est
            # sous celle-là que le CLI la connaît. La réécrire d'après ce que
            # l'IDE affiche ferait reprendre un fil qui n'existe pas de notre
            # côté, et le fil entier deviendrait injoignable. Le titre, lui,
            # continue de suivre.
            if claude_sid and claude_sid != rec.claude_session_id and rec.turns <= 0:
                rec.claude_session_id = claude_sid
                changed = True

            # Un nom provisoire ne vaut pas mieux que le premier message qu'on
            # vient peut-être de retrouver : le prendre l'effacerait.
            should_update_title = (
                name != rec.title
                and str(data.get("nameSource") or "") != "derived"
                and rec.title_source != "user"
                and (
                    _is_auto_title(rec.title, rec.slug, rec.session_id)
                    or _claude_name_rank(data) >= 2
                )
            )
            if should_update_title:
                rec.title = name
                changed = True

            if changed:
                self.save(rec)
                updated.append(rec.session_id)

        return {"updated": updated, "count": len(updated)}

    def _nom_wikichat(self, rec: SessionRecord) -> str:
        """Nom sous lequel une conversation se présente au coordinateur.

        Le projet en préfixe pour qu'on sache d'où vient le message, un
        fragment de l'identifiant pour distinguer deux fils ouverts sur le
        même dossier. La mémoire du projet, elle, ne dépend pas de ce nom :
        le coordinateur rattache une session à son canal-projet d'après son
        dossier de travail.
        """
        if (rec.nom_wikichat or "").strip():
            return rec.nom_wikichat.strip()
        # Jamais `atelier` : wikichat tient ce nom pour générique. Sans slug,
        # celui du projet par défaut, là où la conversation travaille alors.
        slug = (rec.slug or "").strip() or self.settings.default_slug
        return f"{slug}-{rec.session_id[:6]}"

    def _mode_du_tour(self, rec: SessionRecord, claude_cli_id: str) -> str:
        from mcp_gateway.atelier.modes_permission import mode_resolu, rafraichir_la_conversation

        mode, _source = mode_resolu(self.settings, rec.cwd, claude_cli_id)
        # Un choix qu'on applique reste en vie : l'extension l'oublierait après 30 jours.
        rafraichir_la_conversation(claude_cli_id)
        return mode

    def identifiant_claude(self, rec: SessionRecord) -> str:
        """L'identifiant sous lequel Claude Code connaît cette conversation.

        Public, parce que la porte VS Code en a besoin : elle reçoit
        l'identifiant Atelier et doit confier celui du CLI.
        """
        return self._claude_cli_id(rec)

    def _claude_cli_id(self, rec: SessionRecord) -> str:
        """ID passé à `claude --resume` / `--session-id` (peut ≠ session_id Atelier)."""
        return (rec.claude_session_id or rec.session_id).strip()

    def _transcript_has_claude_cli(self, rec: SessionRecord) -> bool:
        path = Path(rec.transcript_path)
        if not path.is_file():
            return False
        try:
            sample = path.read_text(encoding="utf-8", errors="replace")[:12000]
        except OSError:
            return False
        return '"type":"stream_event"' in sample or '"subtype":"init"' in sample

    def _should_resume_claude(self, rec: SessionRecord) -> bool:
        """Reprendre suppose qu'une conversation existe déjà côté CLI.

        L'identifiant peut venir de l'IDE plutôt que de nous : on l'adopte
        pour aligner les titres, mais il ne prouve pas qu'une conversation
        soit reprenable ici — le CLI de l'Atelier ne lit pas forcément le
        même dossier de configuration que l'extension. Sans tour déjà joué,
        on ouvre donc plutôt que de reprendre : un `--resume` sur un
        identifiant inconnu échoue et emporte le fil entier.
        """
        if rec.turns <= 0:
            return False
        return bool(rec.claude_session_id) or self._transcript_has_claude_cli(rec)

    def poids_de_la_conversation(self, rec: SessionRecord) -> int:
        """Une estimation de ce que pèse la conversation, en jetons.

        Grossière à dessein : on compte les caractères des tours et on divise.
        La précision n'importe pas — on cherche à savoir si l'on approche d'un
        plafond, pas à facturer.
        """
        source = dossier_transcripts_claude(Path(rec.cwd)) / f"{self._claude_cli_id(rec)}.jsonl"
        try:
            brut = source.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0
        lignes = [l.strip() for l in brut.split(chr(10)) if l.strip().startswith("{")]
        # Après une compaction, le CLI ne rejoue que ce qui suit la frontière —
        # tout compter reviendrait à mesurer une histoire qui n'est plus
        # envoyée, et à compacter une conversation déjà légère.
        depart = 0
        for i, ligne in enumerate(lignes):
            if "compact_boundary" in ligne:
                depart = i
        caracteres = 0
        for ligne in lignes[depart:]:
            try:
                enr = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if enr.get("type") not in ("user", "assistant"):
                continue
            contenu = (enr.get("message") or {}).get("content")
            if isinstance(contenu, str):
                caracteres += len(contenu)
            elif isinstance(contenu, list):
                for bloc in contenu:
                    if isinstance(bloc, dict):
                        caracteres += len(json.dumps(bloc, ensure_ascii=False))
        # Trois, et non quatre : les blocs d'outils sont du JSON, plus dense en
        # jetons que de la prose. Mieux vaut compacter un peu tôt que trop tard
        # — une conversation qui a franchi la fenêtre ne peut plus l'être du
        # tout, la compaction elle-même n'y tenant plus.
        return caracteres // 3

    def _compacter_si_besoin(
        self, rec: SessionRecord, claude_cli_id: str, force: bool = False
    ) -> bool:
        """Fait résumer la conversation avant qu'elle ne dépasse la fenêtre.

        Claude Code sait compacter tout seul, et l'Atelier l'a longtemps cru
        acquis : `autoCompactEnabled` est vrai, la fenêtre est réglée. Mais la
        bascule automatique se décide sur les jetons consommés, que la
        passerelle de modèles rapporte **à zéro** — mesuré : `input_tokens: 0`
        sur chaque tour, et `preTokens: 1` dans les métadonnées d'une
        compaction sur une conversation de 76 000 jetons. Le compteur ne monte
        jamais, le seuil n'est jamais franchi, et la conversation grossit
        jusqu'à ce que le modèle refuse.

        La compaction manuelle, elle, fonctionne en mode `-p` : on l'envoie
        comme un tour. C'est donc à l'Atelier de décider quand, puisqu'il est
        le seul à pouvoir mesurer.

        Ce n'est plus qu'un repli. Le relais LLM rend au CLI son décompte, et
        sa compaction native reprend la main (`relais_llm`) ; tant que le
        relais répond, l'Atelier ne compacte pas de lui-même — il doublerait
        le travail, et couperait un résumé que le CLI sait mieux placer.
        """
        from mcp_gateway.atelier.relais_llm import relais_en_service

        if not force and relais_en_service(self.settings):
            return False
        seuil = self.settings.compaction_seuil_jetons
        if seuil <= 0 and not force:
            return False
        poids = self.poids_de_la_conversation(rec)
        if poids < seuil and not force:
            return False
        log.info(
            "conversation %s à ~%d jetons (seuil %d) — compaction demandée",
            rec.session_id[:8],
            poids,
            seuil,
        )
        try:
            self.harness.run_turn(
                rec.session_id,
                "/compact",
                cwd=Path(rec.cwd),
                model=rec.model or None,
                resume=True,
                claude_session_id=claude_cli_id,
                transcript_path=Path(rec.transcript_path),
                log_path=Path(rec.log_path),
                timeout_s=self.settings.turn_timeout_s,
                # La compaction n'édite rien et doit aboutir : un mode qui
                # restreint les outils n'a pas à l'empêcher.
                permission_mode="bypassPermissions",
                effort=rec.effort or self.settings.effort,
                agent_name=self._nom_wikichat(rec),
            )
        except Exception as exc:  # noqa: BLE001 — un échec ne doit pas bloquer le tour
            log.warning("compaction de %s échouée : %s", rec.session_id[:8], exc)
            return False
        return True

    def send(
        self,
        session_id: str,
        message: str,
        attachment_ids: list[str] | None = None,
        on_event: Callable[[AtelierEvent], None] | None = None,
        peut_attendre: bool = False,
        reprises: int = 0,
        mode: str = "",
        delai_s: int | None = None,
        regles: dict[str, list[str]] | None = None,
        env_tour: dict[str, str] | None = None,
    ) -> TurnResult:
        """Joue un tour.

        `delai_s`, `regles` et `env_tour` sont ceux d'un agent lancé (lot D,
        `lancements`) : sa durée plafonnée (jamais au-delà de celle du
        service), les règles de permission imposées à son fil (`allow`,
        `deny`), et l'environnement de sa copie de travail (les gardes git
        d'une réparation).

        `peut_attendre` dit si une question d'autorisation peut rester en
        suspens. Vrai seulement quand le tour part par le flux d'événements :
        là, l'interface sait montrer la question et l'utilisateur peut y
        répondre. Sur la route bloquante — celle qu'empruntent les agents et
        les scripts — personne ne verrait rien, et attendre figerait le tour
        pour toujours. On y refuse donc d'office, ce que le CLI faisait déjà
        avant que ce canal existe.
        """
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        if rec.state == "archived":
            raise ValueError("session is archived")
        if rec.state == "running" and not self.harness.tour_en_cours(session_id):
            # La fiche dit « en cours », mais plus rien ne tourne : un service
            # redémarré, un processus tué. Sans cette reprise, le message
            # partirait dans une file que personne ne viderait jamais — la
            # parole avalée en silence, ce qui est pire que refusée.
            rec.state = "failed" if rec.cause else "idle"
            self.save(rec)
        if rec.state == "running":
            # Un tour travaille vraiment. On ne refuse pas et on n'en lance pas
            # un second — deux processus sur le même identifiant de session se
            # marcheraient dessus. Le message attend, et partira dans le tour
            # en cours dès qu'il aura fini le précédent : c'est le CLI qui
            # tient cette file, il suffit de lui écrire au bon moment.
            identifiant = self.harness.messages.deposer(session_id, message)
            return TurnResult(
                session_id=session_id,
                exit_code=0,
                events=[
                    AtelierEvent(
                        kind="systeme",
                        session_id=session_id,
                        cause="message_en_file",
                        tool_id=identifiant,
                        text=message,
                    )
                ],
            )
        if rec.kind == "assistant":
            _normalize_assistant_cwd(self.settings, rec)
            self.save(rec)
        cwd = Path(rec.cwd)
        # Ce que la conversation ne peut pas deviner — son projet, la portée
        # de ses notes — est déposé dans le dossier, là où Claude Code le lit
        # de lui-même. Écrit avant le tour : un projet renommé se corrige au
        # tour suivant, sans intervention.
        from mcp_gateway.atelier.project_context import ecrire_contexte

        ecrire_contexte(cwd, rec.slug, self.settings)
        from mcp_gateway.atelier.session_attachments import enrich_message_with_attachments

        full_message = enrich_message_with_attachments(cwd, message, attachment_ids)
        if rec.turns == 0 and not rec.claude_session_id:
            self.sync_claude_titles()
            rec = self.get(session_id) or rec
        self._titrer_au_premier_message(rec, message)
        resume = self._should_resume_claude(rec)
        # Au premier tour, la conversation s'ouvre sous notre propre
        # identifiant : c'est celui-là qu'il faudra reprendre ensuite.
        if resume:
            claude_cli_id = self._claude_cli_id(rec)
        else:
            claude_cli_id = rec.session_id
            rec.claude_session_id = rec.session_id
        # Avant d'envoyer : si le relais manque, l'Atelier fait résumer une
        # conversation qui approche de la fenêtre. On ne déclare plus jamais
        # une conversation perdue : avec le relais, une conversation trop
        # lourde reçoit « prompt is too long » et le CLI la compacte de
        # lui-même ; sans lui, la compaction forcée reste possible.
        if resume:
            self._compacter_si_besoin(rec, claude_cli_id)
        rec.state = "running"
        self.save(rec)
        mcp_config_path: Path | None = None
        try:
            from mcp_gateway.atelier.mcp_sync import lier_le_projet, materialize_session_mcp

            # Le `.mcp.json` du dossier dit la même chose que le fichier
            # effectif : la conversation reprise dans VS Code ou au terminal
            # aura les mêmes connecteurs.
            lier_le_projet(self.settings, Path(rec.cwd), kind=rec.kind)
            mcp_config_path = materialize_session_mcp(
                self.settings,
                session_id,
                kind=rec.kind,
                cwd=Path(rec.cwd),
                mcp_overlay=rec.mcp_overlay or None,
                agent_name=self._nom_wikichat(rec),
            )
        except OSError as exc:
            rec.cause = f"mcp_materialize: {exc}"
        try:
            result = self.harness.run_turn(
                session_id,
                full_message,
                cwd=Path(rec.cwd),
                model=rec.model or None,
                resume=resume,
                claude_session_id=claude_cli_id,
                transcript_path=Path(rec.transcript_path),
                log_path=Path(rec.log_path),
                timeout_s=(
                    min(int(delai_s), self.settings.turn_timeout_s)
                    if delai_s and delai_s > 0
                    else self.settings.turn_timeout_s
                ),
                mcp_config_path=mcp_config_path,
                # La même règle que VS Code et le terminal : le choix de la
                # conversation, sinon le défaut du projet, sinon celui du
                # service (`modes_permission.mode_resolu`). Plus de bypass
                # implicite pour un tour sans interlocuteur.
                #
                # `mode` : celui qu'un appelant demande pour ce seul tour
                # (atelier_envoyer), déjà vérifié par lui — jamais un bypass que
                # ni la conversation ni le projet n'accordaient.
                permission_mode=mode or self._mode_du_tour(rec, claude_cli_id),
                peut_attendre=peut_attendre,
                effort=rec.effort or self.settings.effort,
                agent_name=self._nom_wikichat(rec),
                poids_initial=self.poids_de_la_conversation(rec) if resume else 0,
                on_event=on_event,
                # Seulement quand il y en a : un harnais écrit avant le lot D
                # (ceux des tests) ne connaît pas ces arguments.
                **({"regles_imposees": regles} if regles else {}),
                **({"env_en_plus": env_tour} if env_tour else {}),
            )
        except Exception as exc:  # noqa: BLE001 — surface cause to API
            rec.state = "failed"
            rec.cause = str(exc)
            self.save(rec)
            raise

        # Le tour a été arrêté parce que la conversation devenait trop lourde :
        # on la fait résumer, puis on la fait reprendre là où elle en était.
        # Une seule fois — si le tour repris pèse encore trop, c'est qu'il n'y
        # a plus rien à gagner à recommencer, et la personne doit le savoir.
        plafond_atteint = any(
            e.kind == "erreur" and e.cause == "contexte_plafond" for e in result.events
        )
        if plafond_atteint and reprises < self.settings.contexte_reprises_max:
            rec.turns += 1
            rec.state = "idle"
            rec.cause = ""
            self.save(rec)
            if on_event is not None:
                on_event(
                    AtelierEvent(
                        kind="systeme",
                        session_id=session_id,
                        cause="contexte_compacte",
                        text=MESSAGE_DE_REPRISE,
                    )
                )
            if not self._compacter_si_besoin(rec, claude_cli_id, force=True):
                # Le résumé n'a pas abouti : reprendre ne ferait que buter au
                # même endroit, une fois de plus.
                rec.state = "timeout"
                rec.cause = "contexte_plafond"
                self.save(rec)
                return result
            return self.send(
                session_id,
                MESSAGE_DE_REPRISE,
                on_event=on_event,
                peut_attendre=peut_attendre,
                reprises=reprises + 1,
                mode=mode,
                delai_s=delai_s,
                regles=regles,
                env_tour=env_tour,
            )

        # Un tour peut traiter plusieurs messages depuis qu'on écrit pendant
        # qu'il travaille : celui qu'on lui a donné, puis ceux qui attendaient.
        # Compter les appels au harnais revenait à en oublier — deux messages
        # échangés, un seul affiché dans la liste.
        rec.turns += 1 + sum(
            1 for e in result.events if e.kind == "systeme" and e.cause == "message_suivant"
        )
        rec.last_text = result.text
        # Arrêté à la main pendant qu'il travaillait : l'interruption a déjà
        # écrit « interrupted » sur la fiche, puis le processus tué rend un code
        # non nul et une erreur. Juger sur ces seuls signes affichait « en
        # erreur » une conversation qu'on venait d'arrêter soi-même.
        sur_disque = self.get(session_id)
        if sur_disque is not None and sur_disque.state == "interrupted":
            rec.state = "interrupted"
            rec.cause = "interrupted"
        elif plafond_atteint:
            rec.state = "timeout"
            rec.cause = "contexte_plafond"
        elif any(e.kind == "erreur" and e.cause == "timeout_mural" for e in result.events):
            rec.state = "timeout"
            rec.cause = "timeout_mural"
        elif result.exit_code != 0 and any(e.kind == "erreur" for e in result.events):
            rec.state = "failed"
            rec.cause = next(e.cause for e in result.events if e.kind == "erreur")
        else:
            rec.state = "idle"
            rec.cause = ""
        self.save(rec)
        self.sync_claude_titles()
        return result

    def patch_mcp_overlay(
        self,
        session_id: str,
        overlay: dict[str, bool],
    ) -> SessionRecord:
        from mcp_gateway.atelier.session_mcp import session_mcp_layers

        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        if rec.kind == "assistant":
            _normalize_assistant_cwd(self.settings, rec)
        # Le « + » du fil règle le choix du DOSSIER, pas de la seule
        # conversation : VS Code et le terminal lisent un `.mcp.json` par
        # dossier, sans rien savoir de la conversation. Une sélection propre
        # à la conversation ne pouvait donc valoir que dans l'app — c'est
        # l'écart mesuré le 26/09 (qgis dans l'app seule). Pour un projet, le
        # choix vaut pour toutes ses conversations ; une conversation de
        # l'Assistant a son propre dossier, donc son propre choix.
        from mcp_gateway.atelier.mcp_sync import (
            SERVICE_ATELIER,
            _ecrire_la_selection,
            lier_le_projet,
            write_project_binding,
        )

        binding, _ = session_mcp_layers(self.settings, rec)
        actifs = {n for n in binding if n != SERVICE_ATELIER}
        for name, active in overlay.items():
            if not isinstance(name, str) or name == SERVICE_ATELIER:
                continue
            if active:
                actifs.add(name)
            else:
                actifs.discard(name)
        cwd = Path(rec.cwd)
        if rec.kind == "assistant":
            connus = actifs | {n for n in overlay if isinstance(n, str)}
            _ecrire_la_selection(cwd, {n: n in actifs for n in connus if n != SERVICE_ATELIER})
            lier_le_projet(self.settings, cwd, kind="assistant")
        else:
            write_project_binding(self.settings, cwd, sorted(actifs))
        rec.mcp_overlay = {}
        self.save(rec)
        return rec

    def get_mcp_state(
        self,
        rec: SessionRecord,
        upstream: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        from mcp_gateway.atelier.session_mcp import build_session_mcp_payload

        return build_session_mcp_payload(self.settings, rec, upstream)

    def interrupt(self, session_id: str) -> SessionRecord:
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        self.harness.interrupt(session_id)
        rec.state = "interrupted"
        rec.cause = "interrupted"
        self.save(rec)
        return rec

    def registres_de(self, rec: SessionRecord) -> list[Path]:
        """Les endroits où cette conversation s'est écrite.

        Le nôtre d'abord : sa graphie est celle que l'affichage sait lire, et
        c'est elle qui gagne quand un même geste figure des deux côtés.
        """
        registres = [Path(rec.transcript_path)]
        if rec.cwd:
            cli = dossier_transcripts_claude(Path(rec.cwd)) / (
                self._claude_cli_id(rec) + ".jsonl"
            )
            registres.append(cli)
        return registres

    def reconcilier_les_etats(self) -> list[str]:
        """Rend leur vérité aux fiches qui se disent « en cours » sans processus.

        Un service redémarré laisse cet état derrière lui, et rien ne le
        corrigeait avant l'envoi d'un message. Entre-temps la conversation
        s'affichait en cours, l'absorption du journal la tenait pour occupée
        et l'ignorait, et un message posté partait en file au lieu de jouer.
        Deux fiches réparées à la main le 7 septembre ; on le fait ici, à
        chaque démarrage.
        """
        reparees: list[str] = []
        for rec in self.list_sessions(include_archived=True):
            if rec.state != "running" or self.harness.tour_en_cours(rec.session_id):
                continue
            rec.state = "failed" if rec.cause else "idle"
            self.save(rec)
            reparees.append(rec.session_id)
        return reparees

    def absorber_le_cli(self, rec: SessionRecord) -> int:
        """Recopie dans notre journal ce que l'autre fenêtre a écrit.

        Une conversation menée dans VS Code s'écrit dans le registre du CLI ;
        la nôtre n'en savait rien. On les fondait à la lecture, ce qui montrait
        la bonne histoire mais n'en gardait qu'une moitié : le jour où ce
        registre est réécrit ou purgé, ce qui n'était que là disparaît.

        On ne recopie que ce qui vient d'ailleurs — le CLI estampille ses
        entrées, les nôtres portent `sdk-cli` et sont déjà chez nous.

        Deux gardes. On n'écrit pas pendant qu'un tour écrit : deux plumes sur
        le même fichier couperaient une ligne en deux. Et on repart de l'octet
        où l'on s'était arrêté, pour ne rien recopier deux fois — un doublon ne
        se retire plus d'un journal qui ne fait qu'ajouter.

        Renvoie le nombre d'entrées reprises.
        """
        if self.harness.tour_en_cours(rec.session_id):
            return 0
        if not rec.cwd:
            return 0
        source = dossier_transcripts_claude(Path(rec.cwd)) / (
            self._claude_cli_id(rec) + ".jsonl"
        )
        journal = Path(rec.transcript_path)
        if rec.critere_absorption < CRITERE_ABSORPTION:
            rec.octets_absorbes = 0
            rec.critere_absorption = CRITERE_ABSORPTION
        # On ne relit notre cahier que s'il y a matière : c'est le seul coût
        # notable ici, et il ne se paie pas quand rien n'a bougé ailleurs.
        candidates, position = a_absorber(source, rec.octets_absorbes)
        entrees = (
            a_absorber(source, rec.octets_absorbes, uuids_connus(journal))[0]
            if candidates
            else []
        )
        if position == rec.octets_absorbes and not entrees:
            return 0
        if entrees:
            journal.parent.mkdir(parents=True, exist_ok=True)
            from mcp_gateway.atelier.events import sans_substituts

            with journal.open("a", encoding="utf-8") as f:
                for e in entrees:
                    # Un demi-emoji lu dans le transcript du CLI ne s'écrit pas
                    # en UTF-8 : il faisait échouer l'absorption entière.
                    f.write(json.dumps(sans_substituts(e), ensure_ascii=False) + "\n")
        rec.octets_absorbes = position
        # Le compteur affiché doit dire ce que le fil montre. Il ne comptait
        # que les tours menés d'ici : une conversation travaillée dans VS Code
        # s'annonçait « 2 tour(s) » avec deux cent soixante-sept entrées.
        vues = paroles_humaines(fondre([journal]))
        if vues > rec.turns:
            rec.turns = vues
        self.save(rec)
        return len(entrees)

    def transcript_text(self, session_id: str) -> str:
        """La conversation entière, d'où qu'elle ait été menée.

        Elle s'écrit à deux endroits — notre journal, et le transcript du CLI
        que VS Code alimente — et ni l'un ni l'autre n'est complet. Les rendre
        séparément revenait à montrer deux histoires partielles selon la
        fenêtre par laquelle on regardait.
        """
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        # Absorber d'abord : la lecture fondue reste le filet, mais ce qui a
        # été écrit ailleurs doit d'abord entrer dans notre cahier.
        self.absorber_le_cli(rec)
        return histoire_unifiee(self.registres_de(rec))
