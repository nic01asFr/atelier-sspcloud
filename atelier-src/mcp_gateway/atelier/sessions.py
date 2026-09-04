"""Registre de sessions Atelier — métadonnées PVC, pas le process."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import (
    AtelierEvent,
    Harness,
    TurnResult,
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
    return False


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
        os.replace(provisoire, path)

    def get(self, session_id: str) -> SessionRecord | None:
        path = self._path(session_id)
        if not path.is_file():
            return None
        return SessionRecord.from_dict(json.loads(path.read_text(encoding="utf-8")))

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
            out.append(rec)
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
        model = model if model is not None else self.settings.default_model
        resolved_kind = kind or _kind_for_slug(self.settings, slug)
        cwd = _cwd_for_new_session(self.settings, slug, resolved_kind, sid)
        cwd.mkdir(parents=True, exist_ok=True)
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
        self.save(rec)
        return rec

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
        """Le premier mot de quelqu'un, qui vaut mieux qu'un identifiant."""
        try:
            with source.open(encoding="utf-8", errors="replace") as f:
                tete = f.read(65536)
        except OSError:
            return ""
        for ligne in tete.split("\n"):
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
                    b.get("text", "") for b in contenu if isinstance(b, dict) and b.get("type") == "text"
                )
            else:
                continue
            texte = " ".join(texte.split())
            if texte:
                return texte[:60]
        return ""

    def adopter_conversations_claude(self) -> list[str]:
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
                rec.state = "ready"
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

    def sync_claude_titles(self) -> dict[str, Any]:
        """Aligne title depuis ~/.claude/sessions (extension / CLI Claude Code)."""
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

            changed = False
            # Une conversation qui a déjà tourné a son identité fixée : c'est
            # sous celle-là que le CLI la connaît. La réécrire d'après ce que
            # l'IDE affiche ferait reprendre un fil qui n'existe pas de notre
            # côté, et le fil entier deviendrait injoignable. Le titre, lui,
            # continue de suivre.
            if claude_sid and claude_sid != rec.claude_session_id and rec.turns <= 0:
                rec.claude_session_id = claude_sid
                changed = True

            should_update_title = (
                name != rec.title
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
        slug = (rec.slug or "atelier").strip() or "atelier"
        return f"{slug}-{rec.session_id[:6]}"

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

    def _compacter_si_besoin(self, rec: SessionRecord, claude_cli_id: str) -> bool:
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
        """
        seuil = self.settings.compaction_seuil_jetons
        if seuil <= 0:
            return False
        poids = self.poids_de_la_conversation(rec)
        if poids < seuil:
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
    ) -> TurnResult:
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        if rec.state == "archived":
            raise ValueError("session is archived")
        if rec.kind == "assistant":
            _normalize_assistant_cwd(self.settings, rec)
            self.save(rec)
        cwd = Path(rec.cwd)
        # Ce que la conversation ne peut pas deviner — son projet, la portée
        # de ses notes — est déposé dans le dossier, là où Claude Code le lit
        # de lui-même. Écrit avant le tour : un projet renommé se corrige au
        # tour suivant, sans intervention.
        from mcp_gateway.atelier.project_context import ecrire_contexte

        ecrire_contexte(cwd, rec.slug)
        from mcp_gateway.atelier.session_attachments import enrich_message_with_attachments

        full_message = enrich_message_with_attachments(cwd, message, attachment_ids)
        if rec.turns == 0 and not rec.claude_session_id:
            self.sync_claude_titles()
            rec = self.get(session_id) or rec
        resume = self._should_resume_claude(rec)
        # Au premier tour, la conversation s'ouvre sous notre propre
        # identifiant : c'est celui-là qu'il faudra reprendre ensuite.
        if resume:
            claude_cli_id = self._claude_cli_id(rec)
        else:
            claude_cli_id = rec.session_id
            rec.claude_session_id = rec.session_id
        # Avant d'envoyer : la conversation tient-elle encore dans la fenêtre ?
        if resume:
            self._compacter_si_besoin(rec, claude_cli_id)
        rec.state = "running"
        self.save(rec)
        mcp_config_path: Path | None = None
        try:
            from mcp_gateway.atelier.mcp_sync import materialize_session_mcp

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
                timeout_s=self.settings.turn_timeout_s,
                mcp_config_path=mcp_config_path,
                agent_name=self._nom_wikichat(rec),
                on_event=on_event,
            )
        except Exception as exc:  # noqa: BLE001 — surface cause to API
            rec.state = "failed"
            rec.cause = str(exc)
            self.save(rec)
            raise

        rec.turns += 1
        rec.last_text = result.text
        if any(e.kind == "erreur" and e.cause == "timeout_mural" for e in result.events):
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
        binding, _ = session_mcp_layers(self.settings, rec)
        binding_names = set(binding.keys())
        new_overlay = dict(rec.mcp_overlay or {})
        for name, active in overlay.items():
            if not isinstance(name, str) or name not in binding_names:
                continue
            if active:
                new_overlay.pop(name, None)
            else:
                new_overlay[name] = False
        rec.mcp_overlay = new_overlay
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

    def transcript_text(self, session_id: str) -> str:
        rec = self.get(session_id)
        if not rec:
            raise KeyError(session_id)
        path = Path(rec.transcript_path)
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
