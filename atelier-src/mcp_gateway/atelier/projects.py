"""Registre projets Atelier (assistant + code) — scan PVC."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from mcp_gateway.atelier.config import AtelierSettings

WorkspaceKind = Literal["assistant", "code"]

_SKIP_DIRS = frozenset({".git", ".wikichat", ".claude", ".vscode", "node_modules"})

# Un agent travaille dans un dossier à lui, sous la même racine que les
# projets. Ce n'en est pas un pour autant : on n'y ouvre pas de conversation,
# et le voir dans la liste de Code laisse croire à un travail en cours. Le
# marqueur est un fichier, donc visible et réversible — l'effacer suffit à
# faire réapparaître le dossier.
MARQUEUR_AGENT = ".atelier-agent"


@dataclass
class ProjectRecord:
    slug: str
    kind: WorkspaceKind
    title: str
    path: str
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Ce que l'Atelier depose lui-meme dans un projet : reglages VS Code, consigne
# de conversation, declaration de connecteurs. Rien que l'utilisateur ait ecrit.
NOS_TRACES = frozenset({".vscode", ".atelier", ".mcp.json", ".claude", "CLAUDE.md"})


def _effacer_arbre(chemin: Path) -> None:
    """Efface un fichier ou un dossier depose par l'Atelier."""
    if chemin.is_dir():
        for enfant in chemin.iterdir():
            _effacer_arbre(enfant)
        chemin.rmdir()
        return
    chemin.unlink(missing_ok=True)


class ProjectStore:
    def __init__(self, settings: AtelierSettings) -> None:
        self.settings = settings
        settings.ensure_dirs()

    def _meta_path(self) -> Path:
        return self.settings.projects_dir / ".atelier-projects.json"

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_meta(self) -> dict[str, Any]:
        p = self._meta_path()
        if not p.is_file():
            return {"projects": {}}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"projects": {}}

    def _save_meta(self, data: dict[str, Any]) -> None:
        self._meta_path().write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    def _title_for_slug(self, slug: str, meta: dict[str, Any]) -> str:
        entry = meta.get("projects", {}).get(slug, {})
        t = str(entry.get("title") or "").strip()
        if t:
            return t
        if slug == self.settings.assistant_slug:
            return "Mémoire Wikichat"
        return slug.replace("-", " ").replace("_", " ")

    def list_projects(self, *, include_archived: bool = False) -> list[ProjectRecord]:
        meta = self._load_meta()
        seen: set[str] = set()
        out: list[ProjectRecord] = []

        assistant_path = self.settings.work_dir / self.settings.assistant_slug
        if assistant_path.is_dir() or self.settings.assistant_slug:
            slug = self.settings.assistant_slug
            seen.add(slug)
            entry = meta.get("projects", {}).get(slug, {})
            out.append(
                ProjectRecord(
                    slug=slug,
                    kind="assistant",
                    title=self._title_for_slug(slug, meta),
                    path=str(assistant_path),
                    created_at=str(entry.get("created_at") or ""),
                    updated_at=str(entry.get("updated_at") or ""),
                )
            )

        projects_root = self.settings.projects_dir
        if projects_root.is_dir():
            for child in sorted(projects_root.iterdir()):
                if not child.is_dir() or child.name.startswith("."):
                    continue
                if child.name in _SKIP_DIRS:
                    continue
                if (child / MARQUEUR_AGENT).is_file():
                    continue
                slug = child.name
                if slug in seen:
                    continue
                seen.add(slug)
                entry = meta.get("projects", {}).get(slug, {})
                if entry.get("archived") and not include_archived:
                    continue
                out.append(
                    ProjectRecord(
                        slug=slug,
                        kind="code",
                        title=self._title_for_slug(slug, meta),
                        path=str(child),
                        created_at=str(entry.get("created_at") or ""),
                        updated_at=str(entry.get("updated_at") or ""),
                    )
                )

        out.sort(key=lambda p: (0 if p.kind == "assistant" else 1, p.title.lower()))
        return out

    def create(
        self,
        slug: str,
        *,
        kind: WorkspaceKind | None = None,
        title: str | None = None,
    ) -> ProjectRecord:
        slug = slug.strip().lower()
        if not slug or not slug.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid slug")
        resolved_kind = kind or (
            "assistant" if slug == self.settings.assistant_slug else "code"
        )
        if resolved_kind == "assistant" and slug != self.settings.assistant_slug:
            raise ValueError("assistant kind requires assistant slug")

        if resolved_kind == "assistant":
            path = self.settings.work_dir / self.settings.assistant_slug
        else:
            path = self.settings.projects_dir / slug
        path.mkdir(parents=True, exist_ok=True)

        meta = self._load_meta()
        projects = meta.setdefault("projects", {})
        now = self._now()
        entry = projects.get(slug, {})
        if not entry.get("created_at"):
            entry["created_at"] = now
        entry["updated_at"] = now
        entry["kind"] = resolved_kind
        if title:
            entry["title"] = title.strip()
        projects[slug] = entry
        self._save_meta(meta)

        return ProjectRecord(
            slug=slug,
            kind=resolved_kind,
            title=self._title_for_slug(slug, meta),
            path=str(path),
            created_at=str(entry.get("created_at") or ""),
            updated_at=str(entry.get("updated_at") or ""),
        )

    def patch(
        self,
        slug: str,
        *,
        title: str | None = None,
        archived: bool | None = None,
    ) -> ProjectRecord:
        meta = self._load_meta()
        projects = meta.setdefault("projects", {})
        if slug not in projects and not (self.settings.projects_dir / slug).is_dir():
            if slug != self.settings.assistant_slug:
                raise KeyError(slug)
        entry = projects.setdefault(slug, {"created_at": self._now()})
        if title is not None:
            t = title.strip()
            if not t:
                raise ValueError("title cannot be empty")
            entry["title"] = t
        if archived is not None:
            entry["archived"] = bool(archived)
        entry["updated_at"] = self._now()
        projects[slug] = entry
        self._save_meta(meta)
        kind: WorkspaceKind = (
            "assistant" if slug == self.settings.assistant_slug else "code"
        )
        if entry.get("kind") in ("assistant", "code"):
            kind = entry["kind"]
        path = (
            self.settings.work_dir / self.settings.assistant_slug
            if kind == "assistant"
            else self.settings.projects_dir / slug
        )
        return ProjectRecord(
            slug=slug,
            kind=kind,
            title=self._title_for_slug(slug, meta),
            path=str(path),
            created_at=str(entry.get("created_at") or ""),
            updated_at=str(entry.get("updated_at") or ""),
        )

    def marquer_dossier_agent(self, chemin: Path, agent: str = "") -> bool:
        """Signale qu'un dossier sert de plan de travail à un agent.

        Retourne False si le dossier n'est pas sous la racine des projets :
        un agent peut très bien travailler ailleurs, il n'y a alors rien à
        marquer.
        """
        try:
            chemin = chemin.resolve()
            racine = self.settings.projects_dir.resolve()
            chemin.relative_to(racine)
        except (OSError, ValueError):
            return False
        if chemin == racine or not chemin.is_dir():
            return False
        lignes = [
            f"Dossier de travail de l'agent {agent}.",
            "Tenu par l'Atelier : ce dossier n'apparaît pas dans la liste des "
            "projets de Code.",
            "",
        ]
        (chemin / MARQUEUR_AGENT).write_text(
            "\n".join(lignes), encoding="utf-8"
        )
        return True

    def is_empty(self, slug: str) -> bool:
        """Vrai si le dossier du projet ne contient rien."""
        path = self.settings.projects_dir / slug
        if not path.is_dir():
            return True
        return not any(path.iterdir())

    def delete(self, slug: str) -> None:
        """
        Supprime un projet vide : son dossier et son entree de meta.

        Refuse dès que le dossier contient quoi que ce soit — on ne detruit
        jamais de travail. L'absence de conversation rattachee est verifiee
        par l'appelant, qui seul connait le magasin de sessions.
        """
        if slug == self.settings.assistant_slug:
            raise ValueError("le projet assistant ne peut pas être supprimé")
        path = self.settings.projects_dir / slug
        if path.is_dir():
            reste = [p for p in path.iterdir() if p.name not in NOS_TRACES]
            if reste:
                raise ValueError("le dossier du projet n'est pas vide")
            # Ce que l'Atelier y a depose lui-meme ne compte pas comme du
            # travail : sans cela, un projet ouvert une fois dans VS Code
            # devenait indestructible.
            for p in path.iterdir():
                _effacer_arbre(p)
            path.rmdir()
        meta = self._load_meta()
        meta.setdefault("projects", {}).pop(slug, None)
        self._save_meta(meta)
