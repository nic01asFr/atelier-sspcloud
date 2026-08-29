"""Handoff VS Code : extension Claude Code + session courante."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.claude_home import sync_claude_home as sync_claude_home_store

CLAUDE_CODE_EXTENSION_ID = "anthropic.claude-code"

# Layout par défaut : Claude Code sidebar, sans Welcome ni Copilot Chat.
WORKBENCH_LAYOUT_SETTINGS: dict[str, object] = {
    "workbench.startupEditor": "none",
    "workbench.secondarySideBar.defaultVisibility": "hidden",
    "chat.disableAIFeatures": True,
    "workbench.welcomePage.walkthroughs.openOnInstall": False,
    "extensions.ignoreRecommendations": True,
}


def _read_llm_key(settings: AtelierSettings) -> str:
    path = settings.llm_key_path
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def claude_extension_env(settings: AtelierSettings) -> list[dict[str, str]]:
    env: list[dict[str, str]] = [
        {"name": "ANTHROPIC_BASE_URL", "value": settings.anthropic_base_url.strip()},
    ]
    key = _read_llm_key(settings)
    if key:
        env.append({"name": "ANTHROPIC_API_KEY", "value": key})
        # Certains gateways lisent AUTH_TOKEN plutôt que API_KEY.
        env.append({"name": "ANTHROPIC_AUTH_TOKEN", "value": key})
    model = (settings.default_model or "").strip()
    if model:
        env.append({"name": "ANTHROPIC_MODEL", "value": model})
    return env


def _merge_claude_settings_file(path: Path, settings: AtelierSettings) -> None:
    """Injecte la clé LLM dans settings.json (partagé CLI + extension VS Code)."""
    key = _read_llm_key(settings)
    if not key:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
    env = data.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    env["ANTHROPIC_BASE_URL"] = settings.anthropic_base_url.strip()
    env["ANTHROPIC_API_KEY"] = key
    env["ANTHROPIC_AUTH_TOKEN"] = key
    model = (settings.default_model or "").strip()
    if model:
        env["ANTHROPIC_MODEL"] = model
        env.setdefault("ANTHROPIC_DEFAULT_MODEL", model)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def write_claude_settings_env(settings: AtelierSettings) -> None:
    """~/.claude + PVC durable : source d'auth pour l'extension (évite le login Claude.ai)."""
    home = Path.home() / ".claude" / "settings.json"
    durable = settings.work_dir / ".claude" / "settings.json"
    _merge_claude_settings_file(home, settings)
    _merge_claude_settings_file(durable, settings)


def sync_claude_home(settings: AtelierSettings, slug: str) -> None:
    """PVC durable + projet → $HOME/.claude pour resume CLI/extension."""
    sync_claude_home_store(settings)
    project_claude = settings.projects_dir / slug / ".claude"
    home_claude = Path.home() / ".claude"
    if project_claude.is_dir():
        home_claude.mkdir(parents=True, exist_ok=True)
        settings_file = project_claude / "settings.json"
        if settings_file.is_file():
            shutil.copy2(settings_file, home_claude / "settings.json")


def write_vscode_workspace_config(settings: AtelierSettings, slug: str) -> None:
    vscode_dir = settings.projects_dir / slug / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        **WORKBENCH_LAYOUT_SETTINGS,
        "claudeCode.disableLoginPrompt": True,
        "claudeCode.preferredLocation": "sidebar",
        "claudeCode.hideOnboarding": True,
        "claudeCode.environmentVariables": claude_extension_env(settings),
        "security.workspace.trust.enabled": False,
        "task.allowAutomaticTasks": "on",
    }
    (vscode_dir / "settings.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (vscode_dir / "extensions.json").write_text(
        json.dumps({"recommendations": [CLAUDE_CODE_EXTENSION_ID]}, indent=2) + "\n",
        encoding="utf-8",
    )


def write_user_code_server_settings(settings: AtelierSettings) -> None:
    user_dir = Path.home() / ".local/share/code-server/User"
    user_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        **WORKBENCH_LAYOUT_SETTINGS,
        "claudeCode.disableLoginPrompt": True,
        "claudeCode.preferredLocation": "sidebar",
        "claudeCode.hideOnboarding": True,
        "claudeCode.environmentVariables": claude_extension_env(settings),
        "security.workspace.trust.enabled": False,
        "task.allowAutomaticTasks": "on",
    }
    (user_dir / "settings.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def write_resume_sidecar(settings: AtelierSettings, slug: str, session_id: str) -> Path:
    root = settings.projects_dir / slug / ".atelier"
    root.mkdir(parents=True, exist_ok=True)
    path = root / "OPEN_CLAUDE_SESSION.md"
    path.write_text(
        "\n".join(
            [
                "# Session Atelier",
                "",
                f"Session: `{session_id}`",
                "",
                "L'extension **Claude Code** s'ouvre dans la barre latérale.",
                "",
                f"CLI : `claude --resume {session_id}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    handoff = settings.work_dir / "bin" / "atelier-vscode-handoff.sh"
    vscode_dir = settings.projects_dir / slug / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    tasks = {
        "version": "2.0.0",
        "tasks": [
            {
                "label": "Atelier: Claude Code session",
                "type": "shell",
                "command": str(handoff),
                "args": [session_id, slug],
                "options": {
                    "env": {
                        "ATELIER_SESSION": session_id,
                        "ATELIER_SLUG": slug,
                    }
                },
                "problemMatcher": [],
                "presentation": {
                    "reveal": "silent",
                    "panel": "shared",
                    "showReuseMessage": False,
                },
                "runOptions": {"runOn": "folderOpen"},
            }
        ],
    }
    (vscode_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    return path


def prepare_vscode_handoff(settings: AtelierSettings, slug: str, session_id: str) -> None:
    slug_v = (slug or settings.default_slug).strip() or settings.default_slug
    project = settings.projects_dir / slug_v
    project.mkdir(parents=True, exist_ok=True)
    sync_claude_home(settings, slug_v)
    write_claude_settings_env(settings)
    write_vscode_workspace_config(settings, slug_v)
    write_user_code_server_settings(settings)
    write_resume_sidecar(settings, slug_v, session_id)

