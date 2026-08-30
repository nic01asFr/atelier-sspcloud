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
        # C'est l'extension qui doit s'ouvrir sur la conversation, pas un
        # terminal : ce réglage lui demande de prendre le premier plan au
        # démarrage. Il valait « false » par défaut, ce qui laissait la vue
        # fermée et obligeait à la chercher dans la barre d'activité.
        "claudeCode.focusView": True,
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
        "claudeCode.focusView": True,
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
                "label": "Atelier — conversation",
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
                # Le terminal devient la conversation : le montrer est tout
                # l'intérêt. Un panneau à lui évite qu'un autre travail
                # vienne s'y mêler.
                "presentation": {
                    "reveal": "always",
                    "panel": "dedicated",
                    "focus": True,
                    "showReuseMessage": False,
                    "clear": True,
                },
                "runOptions": {"runOn": "folderOpen"},
            }
        ],
    }
    (vscode_dir / "tasks.json").write_text(json.dumps(tasks, indent=2) + "\n", encoding="utf-8")
    return path


def _serveurs_declares(settings: AtelierSettings, slug: str) -> list[str]:
    """Serveurs MCP que le projet déclare, tels quels."""
    chemin = settings.projects_dir / slug / ".mcp.json"
    if not chemin.is_file():
        return []
    try:
        data = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    serveurs = data.get("mcpServers") if isinstance(data, dict) else None
    return sorted(serveurs) if isinstance(serveurs, dict) else []


def ensure_claude_onboarding(settings: AtelierSettings, slug: str) -> None:
    """Épargne à l'utilisateur les questions de première ouverture.

    Reprendre une conversation dans un terminal butait sur l'assistant de
    démarrage du CLI — choisir un thème avant d'entrer. Le harnais ne le
    voyait pas : en mode non interactif, ces questions ne se posent pas.

    Le même fichier porte la confiance accordée au dossier, sans laquelle
    le helper d'en-têtes de wikichat n'est pas exécuté et la conversation
    perd son identité. Les deux se règlent ici, une fois.

    On complète sans écraser : ce que quelqu'un a déjà choisi reste.
    """
    path = Path.home() / ".claude.json"
    data: dict[str, object] = {}
    if path.is_file():
        try:
            charge = json.loads(path.read_text(encoding="utf-8"))
            data = charge if isinstance(charge, dict) else {}
        except json.JSONDecodeError:
            data = {}

    data.setdefault("hasCompletedOnboarding", True)
    data.setdefault("theme", "dark")

    # La clé du modèle vient de l'Atelier : la faire approuver à l'ouverture
    # n'ajoute aucune garantie, et bloque la reprise. Claude Code retient la
    # réponse par le suffixe de la clé, jamais la clé entière.
    cle = _read_llm_key(settings)
    if cle:
        reponses = data.setdefault("customApiKeyResponses", {})
        if isinstance(reponses, dict):
            approuvees = reponses.setdefault("approved", [])
            if isinstance(approuvees, list):
                suffixe = cle[-20:]
                if suffixe not in approuvees:
                    approuvees.append(suffixe)

    projets = data.setdefault("projects", {})
    if isinstance(projets, dict):
        dossier = str(settings.projects_dir / slug)
        projet = projets.setdefault(dossier, {})
        if isinstance(projet, dict):
            projet.setdefault("hasTrustDialogAccepted", True)
            projet.setdefault("hasCompletedProjectOnboarding", True)
            # Les serveurs du dossier ont été choisis dans l'Atelier : les
            # faire réapprouver un par un à l'ouverture ne demande rien de
            # plus à personne, et bloque la reprise de la conversation.
            declares = _serveurs_declares(settings, slug)
            if declares:
                deja = projet.get("enabledMcpjsonServers")
                deja = deja if isinstance(deja, list) else []
                projet["enabledMcpjsonServers"] = sorted(set(deja) | set(declares))

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def prepare_vscode_handoff(settings: AtelierSettings, slug: str, session_id: str) -> None:
    slug_v = (slug or settings.default_slug).strip() or settings.default_slug
    project = settings.projects_dir / slug_v
    project.mkdir(parents=True, exist_ok=True)
    sync_claude_home(settings, slug_v)
    write_claude_settings_env(settings)
    write_vscode_workspace_config(settings, slug_v)
    write_user_code_server_settings(settings)
    ensure_claude_onboarding(settings, slug_v)
    write_resume_sidecar(settings, slug_v, session_id)

