"""Ce que reçoit l'agent d'un projet, selon la surface qui le lance.

Deux surfaces, deux chemins de chargement :

- un tour de l'Atelier : le fichier effectif (`--mcp-config … --strict-mcp-config`)
  et l'environnement du harnais ;
- VS Code et le terminal : `~/.claude.json` (portée utilisateur, et
  approbations du dossier) plus le `.mcp.json` du projet — celui-ci primant
  sur celle-là pour un même nom (mesuré, 2.1.281) — et l'environnement de
  l'extension (`claudeCode.environmentVariables`) ou du shell
  (`~/work/.secrets/claude-env.sh`).

`comparer` dit en quoi elles diffèrent. L'écart attendu est nul : mêmes
serveurs, l'Atelier présent partout, les mêmes identifiants une fois les
références développées, et aucune valeur secrète en clair dans un fichier que
lit Claude Code. Sert au test de cohérence (`tests/test_coherence_surfaces.py`)
et à la vérification réelle sur le pod (`bin/atelier-verifier-coherence`).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.config import AtelierSettings

_REFERENCE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
# Ce qui ressemble à un jeton, quel que soit le service. Large exprès : un
# faux positif se lit, un jeton manqué part dans un dépôt.
MOTIFS_DE_JETONS = (
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{16,}"),
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"xox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"(?i)\b(?:bearer|token|basic)\s+(?!\$\{)[A-Za-z0-9._~+/=-]{16,}"),
)
# En-têtes qui ne sont pas des identifiants et diffèrent à dessein : la
# conversation (`${ATELIER_SESSION}` résolu d'un côté, repli « poste » de
# l'autre, voir `navigateur`).
_ENTETES_PROPRES_A_LA_SURFACE = frozenset({"x-atelier-conversation"})


def _json(chemin: Path) -> dict[str, Any]:
    try:
        charge = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return charge if isinstance(charge, dict) else {}


def developper(texte: str, env: dict[str, str]) -> str:
    """Comme Claude Code : `${VAR}` et `${VAR:-repli}` pris dans l'environnement."""

    def remplacer(m: re.Match[str]) -> str:
        nom, repli = m.group(1), m.group(2)
        if env.get(nom):
            return env[nom]
        return repli if repli is not None else ""

    return _REFERENCE.sub(remplacer, texte)


def references(serveurs: dict[str, Any]) -> set[str]:
    """Les variables que des déclarations demandent (hors ATELIER_SESSION et consorts)."""
    trouvees: set[str] = set()
    for cfg in serveurs.values():
        texte = json.dumps(cfg, ensure_ascii=False)
        for m in _REFERENCE.finditer(texte):
            if m.group(2) is None:
                trouvees.add(m.group(1))
    return trouvees


def surface_atelier(
    settings: AtelierSettings, cwd: Path, session_id: str, *, kind: str = "code"
) -> dict[str, Any]:
    """Ce que reçoit un tour de l'Atelier : fichier effectif et environnement du harnais."""
    from mcp_gateway.atelier.harness import ClaudeHarness
    from mcp_gateway.atelier.mcp_sync import lier_le_projet, materialize_session_mcp

    lier_le_projet(settings, cwd, kind=kind)  # type: ignore[arg-type]
    chemin = materialize_session_mcp(settings, session_id, kind=kind, cwd=cwd)  # type: ignore[arg-type]
    serveurs = _json(chemin).get("mcpServers") or {}
    env = ClaudeHarness(settings)._env("", cwd, session_id)
    return {"serveurs": serveurs, "env": env, "fichiers": [chemin]}


def surface_vscode(settings: AtelierSettings, cwd: Path) -> dict[str, Any]:
    """Ce que reçoit l'extension VS Code (ou le terminal) ouverte sur le dossier."""
    from mcp_gateway.atelier.env_secrets import chemin_du_fichier, lire_le_fichier
    from mcp_gateway.atelier.vscode_handoff import claude_extension_env

    maison = Path.home() / ".claude.json"
    donnees = _json(maison)
    utilisateur = donnees.get("mcpServers") or {}
    entree = (donnees.get("projects") or {}).get(str(cwd)) or {}
    approuves = set(entree.get("enabledMcpjsonServers") or [])
    desactives = set(entree.get("disabledMcpServers") or [])
    projet = _json(cwd / ".mcp.json").get("mcpServers") or {}
    serveurs: dict[str, Any] = dict(utilisateur)
    for nom, cfg in projet.items():
        if nom in approuves:
            serveurs[nom] = cfg  # le projet prime sur la portée utilisateur
    for nom in desactives:
        serveurs.pop(nom, None)
    env_vscode = {e["name"]: e["value"] for e in claude_extension_env(settings)}
    env_terminal = lire_le_fichier(chemin_du_fichier(settings))
    return {
        "serveurs": serveurs,
        "env": env_vscode,
        "env_terminal": env_terminal,
        "fichiers": [maison, cwd / ".mcp.json"],
    }


def _identifiants(cfg: dict[str, Any], env: dict[str, str]) -> dict[str, str]:
    """Adresse et en-têtes d'identification, références développées."""
    sortie = {"url": developper(str(cfg.get("url") or ""), env).split("?", 1)[0]}
    for cle, valeur in (cfg.get("headers") or {}).items():
        if str(cle).lower() in _ENTETES_PROPRES_A_LA_SURFACE:
            continue
        sortie["header:" + str(cle).lower()] = developper(str(valeur), env)
    for cle, valeur in (cfg.get("env") or {}).items():
        sortie["env:" + str(cle)] = developper(str(valeur), env)
    if cfg.get("command"):
        sortie["command"] = developper(str(cfg["command"]), env)
    return sortie


def fichiers_a_inspecter(settings: AtelierSettings, cwd: Path) -> list[Path]:
    """Les fichiers de configuration MCP que lit Claude Code, sur toutes les surfaces."""
    candidats = [
        Path.home() / ".claude.json",
        settings.work_dir / ".claude.json",
        settings.mcp_config_path,
        settings.work_dir / ".claude" / "mcp-config.json",
        cwd / ".mcp.json",
    ]
    if settings.mcp_effective_dir.is_dir():
        candidats += sorted(settings.mcp_effective_dir.glob("*.json"))
    return [c for c in candidats if c.is_file()]


def secrets_en_clair(fichiers: list[Path], valeurs: dict[str, str]) -> list[str]:
    """Où une valeur secrète, ou ce qui y ressemble, apparaît en clair."""
    trouves: list[str] = []
    for chemin in fichiers:
        try:
            texte = chemin.read_text(encoding="utf-8")
        except OSError:
            continue
        for nom, valeur in valeurs.items():
            if len(valeur) >= 8 and valeur in texte:
                trouves.append(f"{chemin} : valeur de {nom}")
        for motif in MOTIFS_DE_JETONS:
            for m in motif.finditer(texte):
                trouves.append(f"{chemin} : motif de jeton « {m.group(0)[:6]}… »")
    return trouves


def comparer(
    settings: AtelierSettings,
    cwd: Path,
    atelier: dict[str, Any],
    vscode: dict[str, Any],
) -> list[str]:
    """Les écarts entre les surfaces. Vide = cohérent."""
    from mcp_gateway.atelier.env_secrets import variables_secretes

    ecarts: list[str] = []
    noms_a, noms_v = set(atelier["serveurs"]), set(vscode["serveurs"])
    if noms_a != noms_v:
        ecarts.append(
            f"serveurs différents : Atelier seul {sorted(noms_a - noms_v)}, VS Code seul {sorted(noms_v - noms_a)}"
        )
    for nom, surface in (("Atelier", atelier), ("VS Code", vscode)):
        if "atelier" not in surface["serveurs"]:
            ecarts.append(f"{nom} : le serveur `atelier` manque")
    for serveur in sorted(noms_a & noms_v):
        a = _identifiants(atelier["serveurs"][serveur], atelier["env"])
        v = _identifiants(vscode["serveurs"][serveur], vscode["env"])
        t = _identifiants(vscode["serveurs"][serveur], vscode["env_terminal"])
        if a != v:
            differents = sorted(k for k in set(a) | set(v) if a.get(k) != v.get(k))
            ecarts.append(f"{serveur} : Atelier et VS Code diffèrent sur {differents}")
        if v != t:
            differents = sorted(k for k in set(v) | set(t) if v.get(k) != t.get(k))
            ecarts.append(f"{serveur} : VS Code et terminal diffèrent sur {differents}")
    for nom, surface, env in (
        ("Atelier", atelier, atelier["env"]),
        ("VS Code", vscode, vscode["env"]),
        ("terminal", vscode, vscode["env_terminal"]),
    ):
        manquantes = sorted(v for v in references(surface["serveurs"]) if not env.get(v))
        if manquantes:
            ecarts.append(f"{nom} : variables non fournies {manquantes}")
    valeurs = variables_secretes(settings)
    ecarts += secrets_en_clair(fichiers_a_inspecter(settings, cwd), valeurs)
    return ecarts
