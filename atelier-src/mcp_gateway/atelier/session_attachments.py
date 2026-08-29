"""Pièces jointes composer — stockage sous cwd session (.atelier/uploads)."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_SEND = 8


@dataclass
class AttachmentMeta:
    id: str
    name: str
    rel_path: str
    abs_path: str
    size: int
    mime: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def uploads_dir(cwd: Path) -> Path:
    d = cwd / ".atelier" / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def sanitize_filename(name: str) -> str:
    base = (name or "file").replace("\\", "/").split("/")[-1].strip()
    base = re.sub(r"[^\w.\-+() ]", "_", base)
    return (base[:120] or "file")


def _attachment_path(cwd: Path, attachment_id: str, name: str) -> Path:
    safe = sanitize_filename(name)
    return uploads_dir(cwd) / f"{attachment_id}_{safe}"


def save_upload(cwd: Path, name: str, data: bytes, mime: str = "") -> AttachmentMeta:
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError(f"file too large (max {MAX_ATTACHMENT_BYTES} bytes)")
    attachment_id = str(uuid.uuid4())
    path = _attachment_path(cwd, attachment_id, name)
    path.write_bytes(data)
    rel = path.relative_to(cwd.resolve()).as_posix()
    abs_path = str(path.resolve())
    return AttachmentMeta(
        id=attachment_id,
        name=sanitize_filename(name),
        rel_path=rel,
        abs_path=abs_path,
        size=len(data),
        mime=mime or "",
    )


def get_attachment(cwd: Path, attachment_id: str) -> AttachmentMeta | None:
    root = uploads_dir(cwd)
    prefix = f"{attachment_id}_"
    for path in root.iterdir():
        if not path.is_file():
            continue
        if path.name.startswith(prefix):
            name = path.name[len(prefix):] or path.name
            rel = path.relative_to(cwd.resolve()).as_posix()
            return AttachmentMeta(
                id=attachment_id,
                name=name,
                rel_path=rel,
                abs_path=str(path.resolve()),
                size=path.stat().st_size,
            )
    return None


def delete_attachment(cwd: Path, attachment_id: str) -> bool:
    root = uploads_dir(cwd)
    prefix = f"{attachment_id}_"
    removed = False
    for path in root.iterdir():
        if path.is_file() and path.name.startswith(prefix):
            path.unlink(missing_ok=True)
            removed = True
    return removed


def _claude_file_reference(meta: AttachmentMeta) -> str:
    """Référence fichier native Claude Code (@path relatif au cwd de la session)."""
    path = meta.rel_path.replace("\\", "/")
    if not path.startswith("@"):
        path = f"@{path}"
    return path


def enrich_message_with_attachments(
    cwd: Path,
    message: str,
    attachment_ids: list[str] | None,
) -> str:
    ids = [x.strip() for x in (attachment_ids or []) if x and str(x).strip()]
    if not ids:
        return message
    if len(ids) > MAX_ATTACHMENTS_PER_SEND:
        raise ValueError(f"too many attachments (max {MAX_ATTACHMENTS_PER_SEND})")
    refs: list[str] = []
    for aid in ids:
        meta = get_attachment(cwd, aid)
        if not meta:
            continue
        refs.append(_claude_file_reference(meta))
    if not refs:
        return message
    head = message.strip()
    if head:
        return head + "\n" + "\n".join(refs)
    return "\n".join(refs)
