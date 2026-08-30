"""Registre de sessions Atelier — métadonnées PVC, pas le process."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.harness import Harness, TurnResult, new_session_id

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


def _normalize_assistant_cwd(settings: AtelierSettings, rec: SessionRecord) -> Path:
    """Sessions assistant legacy (cwd = racine mémoire) → sous-dossier session."""
    if rec.kind != "assistant":
        return Path(rec.cwd)
    root = settings.assistant_root.resolve()
    current = Path(rec.cwd).resolve()
    expected = _assistant_session_cwd(settings, rec.session_id).resolve()
    if current == root:
        expected.mkdir(parents=True, exist_ok=True)
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
        rec.updated_at = self._now()
        path = self._path(rec.session_id)
        path.write_text(
            json.dumps(rec.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

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
            rec = SessionRecord.from_dict(json.loads(p.read_text(encoding="utf-8")))
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
        if archived is not None:
            if archived:
                rec.state = "archived"
            elif rec.state == "archived":
                rec.state = "idle"
        self.save(rec)
        return rec

    def delete(self, session_id: str, *, remove_files: bool = True) -> None:
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

    def sync_claude_titles(self) -> dict[str, Any]:
        """Aligne title depuis ~/.claude/sessions (extension / CLI Claude Code)."""
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
                    else:
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

    def send(
        self,
        session_id: str,
        message: str,
        attachment_ids: list[str] | None = None,
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
