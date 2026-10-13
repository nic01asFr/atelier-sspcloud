"""Pièces jointes composer — stockage sous cwd session (.atelier/uploads)."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_SEND = 8
# Au-delà, l'outil Read de l'agent refuse le fichier entier : il faut le lire par tranches.
GROS_TEXTE_OCTETS = 200_000

# Ce que l'agent lit tel quel avec son outil Read (le reste passe par Bash).
EXT_TEXTE = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".geojson", ".xml",
    ".html", ".htm", ".css", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".vue", ".svelte", ".py", ".r", ".sql",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".log", ".sh", ".bash", ".tex", ".bib", ".svg", ".ipynb",
    ".java", ".c", ".h", ".cpp", ".hpp", ".go", ".rs", ".rb", ".php", ".qml", ".gpx", ".kml", ".srt", ".vtt",
}
EXT_IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
EXT_PDF = {".pdf"}
# Lisibles, mais pas par Read : un geste de plus, que l'agent n'a pas à deviner.
CONSEILS = {
    (".zip", ".jar"): "archive : la lister avec `unzip -l`, l'extraire dans un dossier du projet avec `unzip`, puis lire ce qu'elle contient",
    (".tar", ".gz", ".tgz", ".bz2", ".xz"): "archive : l'extraire dans un dossier du projet avec `tar -xf`, puis lire ce qu'elle contient",
    (".7z", ".rar"): "archive : l'extraire avec `7z x` (ou `unrar x`) dans un dossier du projet, puis lire ce qu'elle contient",
    (".docx", ".odt"): "document Word : extraire le texte avec python (`python-docx`) ou `unzip -p fichier word/document.xml`",
    (".xlsx", ".xlsm", ".ods"): "classeur : le lire avec python (`pandas.read_excel` ou `openpyxl`), jamais avec Read",
    (".pptx", ".odp"): "présentation : en extraire le texte avec python (`python-pptx`)",
    (".xls", ".doc", ".ppt"): "ancien format Office : le lire avec python (`xlrd` pour .xls) ou demander à la personne un export récent (.xlsx, .docx, .pptx)",
    (".parquet", ".feather", ".arrow"): "table binaire : la lire avec python (`pandas.read_parquet` / `pyarrow`)",
    (".sqlite", ".sqlite3", ".db", ".gpkg"): "base SQLite : l'interroger avec `sqlite3` ou python, sans la charger entière",
    (".shp", ".dbf", ".shx", ".geotiff", ".tif", ".tiff"): "donnée géographique : la lire avec python (`geopandas` / `rasterio`) ou `ogrinfo`",
    (".mp3", ".wav", ".m4a", ".ogg", ".flac"): "audio : Read ne l'écoute pas ; demander une transcription à la personne, sauf si le projet a un outil de reconnaissance vocale",
    (".mp4", ".mov", ".webm", ".mkv", ".avi"): "vidéo : en extraire des images avec `ffmpeg`, puis lire les images",
    (".heic", ".bmp", ".avif"): "image dans un format que Read n'affiche pas : la convertir en PNG (python `PIL`, ou `convert` s'il est installé) puis la lire",
}
_CONSEIL_PAR_EXT = {ext: texte for exts, texte in CONSEILS.items() for ext in exts}


def lisibilite(nom: str, taille: int) -> tuple[str, str]:
    """(genre, conseil) d'un fichier joint : ce que l'agent peut en faire, et le geste s'il n'est pas direct.

    Genres : `texte`, `image`, `pdf` (lus tels quels avec Read), `a_ouvrir` (Office, archive, base… : par Bash),
    `inconnu` (extension qu'on ne sait pas dire : l'agent regarde le début avec `file` / `head -c`).
    """
    ext = Path(nom).suffix.lower()
    if ext in EXT_TEXTE:
        if taille > GROS_TEXTE_OCTETS:
            return "texte", (
                f"gros fichier ({taille // 1024} Ko) : le lire par tranches (Read avec offset et limit) "
                "ou y chercher avec Grep, pas d'un bloc"
            )
        return "texte", ""
    if ext in EXT_IMAGE:
        return "image", ""
    if ext in EXT_PDF:
        return "pdf", "PDF : Read le lit par tranches de 20 pages au plus (paramètre pages)"
    if ext in _CONSEIL_PAR_EXT:
        return "a_ouvrir", _CONSEIL_PAR_EXT[ext]
    return "inconnu", "type de fichier inconnu : regarder le début avec `file` puis `head -c 2000` avant de choisir comment le lire"


@dataclass
class AttachmentMeta:
    id: str
    name: str
    rel_path: str
    abs_path: str
    size: int
    mime: str = ""
    genre: str = ""
    conseil: str = ""

    def __post_init__(self) -> None:
        if not self.genre:
            self.genre, self.conseil = lisibilite(self.name, self.size)

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
    """Mention `@fichier` de Claude Code, avec le chemin ABSOLU.

    Le 13/10, `@.atelier/uploads/…` (relatif) a été lu par un modèle non-Claude depuis son HOME
    (`$HOME/.atelier/uploads/…`) : « File does not exist », deux lectures perdues avant qu'il devine le
    bon chemin. Un chemin absolu se lit pareil depuis n'importe quel dossier, pour n'importe quel modèle.
    """
    return "@" + meta.abs_path.replace("\\", "/").lstrip("@")


def _note_de_lecture(meta: AttachmentMeta) -> str:
    """Une ligne qui dit à l'agent comment lire ce fichier, quand ce n'est pas un simple Read."""
    if not meta.conseil:
        return ""
    return f"(pièce jointe « {meta.name} » — {meta.conseil})"


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
    notes: list[str] = []
    for aid in ids:
        meta = get_attachment(cwd, aid)
        if not meta:
            continue
        refs.append(_claude_file_reference(meta))
        note = _note_de_lecture(meta)
        if note:
            notes.append(note)
    if not refs:
        return message
    head = message.strip()
    lignes = refs + notes
    if head:
        return head + "\n" + "\n".join(lignes)
    return "\n".join(lignes)
