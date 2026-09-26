"""Ce que reçoit l'agent d'un projet, selon la surface qui le lance.

Deux surfaces, deux chemins de chargement :

- un tour de l'Atelier : le fichier effectif (`--mcp-config … --strict-mcp-config`)
  et l'environnement du harnais ;
- VS Code et le terminal : `~/.claude.json` (portée utilisateur, et
  approbations du dossier) plus le `.mcp.json` du projet — celui-ci primant
  sur celle-là pour un même nom (mesuré, 2.1.281) — et l'environnement de
  l'extension (`claudeCode.environmentVariables`, sans secret, complété par
  l'enveloppeur `atelier-claude-vscode` qui source
  `~/work/.secrets/claude-env.sh`) ou du shell (le même fichier).

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

from mcp_gateway.atelier.claude_home import donnees_code_server
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
# l'autre, voir `mcp_sync.declaration_atelier`).
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
    from mcp_gateway.atelier.vscode_handoff import environnement_du_claude_vscode

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
    env_vscode = environnement_du_claude_vscode(settings)
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
        # Les réglages de code-server : l'extension n'y trouve plus de valeur
        # secrète, l'enveloppeur les charge au lancement.
        donnees_code_server() / "User" / "settings.json",
        donnees_code_server() / "Machine" / "settings.json",
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


# =============================================================================
# Vérification réelle : ce que Claude Code annonce au démarrage, par surface
# =============================================================================
#
# Contrat `docs/vision/profils-acces.md`, « Vérification ». Pour chaque vrai
# projet (et le dossier de l'Assistant) et chaque surface, on lance le vrai
# `claude -p --output-format stream-json --verbose`, hooks désactivés, sans
# transcrit, avec une copie du dossier de configuration et une adresse de
# modèle morte ; on lit `system/init` et l'on tue ce seul processus (et ses
# descendants, par PID). Puis on compare les surfaces entre elles et au profil.
#
# Aucune valeur secrète ne sort : on ne rapporte que des noms (serveurs,
# outils), des états, des versions, des modes et des codes de sortie.

import os as _os  # noqa: E402
import shlex as _shlex  # noqa: E402
import shutil as _shutil  # noqa: E402
import subprocess as _subprocess  # noqa: E402
import tempfile as _tempfile  # noqa: E402
import time as _time  # noqa: E402
from dataclasses import dataclass as _dataclass  # noqa: E402
from dataclasses import field as _field  # noqa: E402

SURFACES = ("app", "vscode", "terminal", "bash-lc")
# Le nom sous lequel les mesures se présentent à wikichat. Un seul, fixe : le
# pont se connecte vraiment (on mesure ses outils, filtrés par profil), sans
# créer une identité par lancement. Voir `--sans-wikichat`.
NOM_VERIFICATEUR = "verificateur-coherence"
MODELE_MORT = "http://127.0.0.1:9"
# Ce qu'un agent code ne doit jamais recevoir (profils-acces.md, profil « agent code »).
OUTILS_INTERDITS_CODE = (
    "mcp__atelier__gateway_",
    "mcp__atelier__composition_",
)
WIKICHAT_INTERDITS_CODE = frozenset(
    {
        "list_projects",
        "scan_projects",
        "audit_all_projects",
        "spawn_session",
        "respawn_project_agents",
        "kill_spawn",
        "register_trigger",
        "fire_trigger",
        "delete_trigger",
        "set_trigger_enabled",
        "register_routine",
        "run_routine",
        "delete_routine",
    }
)
META_OUTILS = ("mcp__atelier__gateway_find_tools", "mcp__atelier__gateway_call_tool")
# Ce que le profil « Assistant » refuse (`assistant.reglages_du_profil`).
OUTILS_REFUSES_ASSISTANT = frozenset({"Bash", "NotebookEdit", "WebSearch"})
# Outils qui n'existent que selon l'instant (un serveur encore en attente).
_OUTILS_CIRCONSTANCIELS = frozenset({"WaitForMcpServers"})
# Les variables d'une conversation ou d'une surface, jamais héritées du lanceur.
_PROPRES_A_LA_SURFACE = (
    "ATELIER_SESSION",
    "WIKICHAT_AGENT",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDECODE",
)


@_dataclass
class Dossier:
    slug: str
    chemin: Path
    profil: str


@_dataclass
class Lancement:
    surface: str
    commande: list[str]
    env: dict[str, str]
    cwd: Path
    effort: str = ""


@_dataclass
class Vu:
    surface: str
    ok: bool = False
    erreur: str = ""
    version: str = ""
    mode: str = ""
    modele: str = ""
    effort: str = ""
    serveurs: dict[str, str] = _field(default_factory=dict)
    outils: list[str] = _field(default_factory=list)
    duree_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "surface": self.surface,
            "ok": self.ok,
            "erreur": self.erreur,
            "version": self.version,
            "mode": self.mode,
            "modele": self.modele,
            "effort": self.effort,
            "serveurs": dict(sorted(self.serveurs.items())),
            "outils": sorted(self.outils),
            "duree_s": round(self.duree_s, 1),
        }


def dossiers_reels(settings: AtelierSettings) -> list[Dossier]:
    """Les vrais projets (`projects_dir/*`) et le dossier de l'Assistant."""
    dossiers: list[Dossier] = []
    if settings.projects_dir.is_dir():
        for d in sorted(settings.projects_dir.iterdir()):
            if d.is_dir() and not d.is_symlink() and not d.name.startswith("."):
                dossiers.append(Dossier(d.name, d, "code"))
    if settings.assistant_root.is_dir():
        dossiers.append(Dossier("assistant", settings.assistant_root, "assistant"))
    return dossiers


def echantillon(dossiers: list[Dossier], noms: list[str] | None, rapide: bool) -> list[Dossier]:
    """Les dossiers demandés ; `rapide` : un par profil (le plus récemment modifié)."""
    if noms:
        voulus = set(noms)
        return [d for d in dossiers if d.slug in voulus]
    if not rapide:
        return dossiers
    choisis: list[Dossier] = []
    for profil in ("code", "assistant"):
        candidats = [d for d in dossiers if d.profil == profil]
        if candidats:
            choisis.append(max(candidats, key=lambda d: d.chemin.stat().st_mtime))
    return choisis


def _descendants(pid: int) -> list[int]:
    """Les PID descendants (Linux, par /proc), des plus profonds aux plus proches."""
    sortie: list[int] = []
    try:
        enfants = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
    except OSError:
        return sortie
    for enfant in enfants:
        if enfant.isdigit():
            sortie += _descendants(int(enfant))
            sortie.append(int(enfant))
    return sortie


def _tuer(proc: Any) -> None:
    """Tue ce processus et ses descendants, par PID : jamais par motif."""
    import signal

    for pid in _descendants(proc.pid):
        try:
            _os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
        except OSError:
            pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout=10)
    except Exception:  # noqa: BLE001 — un processus récalcitrant ne bloque pas le rapport
        pass


def lire_init(lancement: Lancement, delai: float = 60.0) -> Vu:
    """Lance, lit `system/init`, tue. Rien de ce que le processus écrit n'est rapporté."""
    import queue
    import threading

    vu = Vu(lancement.surface, effort=lancement.effort)
    debut = _time.monotonic()
    try:
        proc = _subprocess.Popen(
            lancement.commande,
            cwd=str(lancement.cwd),
            env=lancement.env,
            stdin=_subprocess.PIPE,
            stdout=_subprocess.PIPE,
            stderr=_subprocess.DEVNULL,
            text=True,
        )
    except OSError as exc:
        vu.erreur = f"lancement impossible : {type(exc).__name__}"
        return vu
    lignes: queue.Queue[str] = queue.Queue()

    def lire() -> None:
        try:
            for ligne in proc.stdout:  # type: ignore[union-attr]
                lignes.put(ligne)
        except (OSError, ValueError):
            pass
        lignes.put("")

    threading.Thread(target=lire, daemon=True).start()
    try:
        message = {"type": "user", "message": {"role": "user", "content": "ok"}}
        proc.stdin.write(json.dumps(message) + "\n")  # type: ignore[union-attr]
        proc.stdin.flush()  # type: ignore[union-attr]
    except OSError:
        pass
    init: dict[str, Any] = {}
    fin = debut + delai
    while _time.monotonic() < fin:
        try:
            ligne = lignes.get(timeout=max(0.1, fin - _time.monotonic()))
        except queue.Empty:
            break
        if not ligne:
            break
        try:
            ev = json.loads(ligne)
        except ValueError:
            continue
        if isinstance(ev, dict) and ev.get("type") == "system" and ev.get("subtype") == "init":
            init = ev
            break
    vu.duree_s = _time.monotonic() - debut
    _tuer(proc)
    if not init:
        vu.erreur = "pas d'événement system/init" + (" (délai dépassé)" if _time.monotonic() >= fin else "")
        return vu
    vu.ok = True
    vu.version = str(init.get("claude_code_version") or init.get("version") or "")
    vu.mode = str(init.get("permissionMode") or "")
    vu.modele = str(init.get("model") or "")
    vu.serveurs = {
        str(s.get("name")): str(s.get("status") or "")
        for s in init.get("mcp_servers") or []
        if isinstance(s, dict) and s.get("name")
    }
    vu.outils = sorted(str(t) for t in init.get("tools") or [] if isinstance(t, str))
    return vu


def _config_temporaire(racine: Path) -> Path:
    """Une copie du dossier de configuration : le CLI y écrit, pas dans le vrai."""
    cible = racine / "config"
    cible.mkdir(parents=True, exist_ok=True)
    maison = Path.home()
    if (maison / ".claude.json").is_file():
        _shutil.copy2(maison / ".claude.json", cible / ".claude.json")
    source = maison / ".claude"
    for nom in ("settings.json", "CLAUDE.md"):
        if (source / nom).is_file():
            _shutil.copy2(source / nom, cible / nom)
    for nom in ("commands", "skills", "plugins", "agents"):
        if (source / nom).is_dir():
            _shutil.copytree(source / nom, cible / nom, symlinks=True, dirs_exist_ok=True)
    return cible


def _env_de_base() -> dict[str, str]:
    """L'environnement du lanceur, sans ce qui appartient à une conversation ni les valeurs des références.

    Les `ATELIER_MCP_*` sont retirées : chaque surface doit les obtenir par son
    propre chemin (harnais, enveloppeur, `~/.bashrc`) — c'est ce qu'on vérifie.
    """
    return {
        k: v
        for k, v in _os.environ.items()
        if k not in _PROPRES_A_LA_SURFACE and not k.startswith("ATELIER_MCP_")
    }


def _effort_des_reglages() -> str:
    """L'effort que verra le CLI hors `--settings` : `settings.json`, puis l'environnement.

    Mesuré le 25/09 : `env` de `settings.json` l'emporte sur l'environnement
    du processus. `system/init` ne le dit pas : c'est une valeur déduite.
    """
    donnees = _json(Path.home() / ".claude" / "settings.json")
    env = donnees.get("env") if isinstance(donnees.get("env"), dict) else {}
    return str(env.get("CLAUDE_CODE_EFFORT_LEVEL") or donnees.get("effortLevel") or _os.environ.get("CLAUDE_CODE_EFFORT_LEVEL") or "")


def lancements(
    settings: AtelierSettings,
    dossier: Dossier,
    config: Path,
    *,
    avec_wikichat: bool = True,
    claude: Path | None = None,
) -> list[Lancement]:
    """Les quatre lancements d'un dossier, tels que chaque surface les fait."""
    from mcp_gateway.atelier.claude_home import binaire_claude_le_plus_recent
    from mcp_gateway.atelier.config import effort_accepte_partout
    from mcp_gateway.atelier.env_projet import variables_du_projet
    from mcp_gateway.atelier.env_secrets import chemin_du_fichier, lire_le_fichier
    from mcp_gateway.atelier.harness import ClaudeHarness
    from mcp_gateway.atelier.mcp_sync import configuration_du_profil, resoudre_les_variables
    from mcp_gateway.atelier.modes_permission import CLE_BYPASS, mode_resolu
    from mcp_gateway.atelier.navigateur import refuser_les_outils_simules
    from mcp_gateway.atelier.vscode_handoff import enveloppeur_vscode

    binaire = claude or binaire_claude_le_plus_recent() or settings.claude_bin
    session = f"verif-{dossier.slug}"[:60]
    commun = [
        "-p",
        "--input-format",
        "stream-json",
        "--output-format",
        "stream-json",
        "--verbose",
        "--max-turns",
        "1",
        "--no-session-persistence",
        "--permission-prompt-tool",
        "stdio",
    ]
    base = _env_de_base()
    base["CLAUDE_CONFIG_DIR"] = str(config)
    # L'enveloppeur et le script `surfaces/claude` trouvent le volume par là.
    base["ATELIER_WORK"] = str(settings.work_dir)
    if avec_wikichat:
        # Une seule identité, fixe, pour toutes les mesures : sans elle, chaque
        # lancement laissait une identité `<projet>-<id6>` dans wikichat (audit
        # §1). Le profil et le projet viennent de la déclaration, comme pour un
        # agent : ce sont eux que le serveur filtre.
        base["WIKICHAT_AGENT"] = NOM_VERIFICATEUR
    else:
        # Pont neutralisé : wikichat n'est pas mesuré (rapporté comme tel).
        base["WIKICHAT_PORT"] = "1"
    # Hooks désactivés, et une adresse de modèle morte : `--settings` l'emporte
    # sur `settings.json` (mesuré, 2.1.281). Aucun modèle n'est appelé.
    reglages: dict[str, Any] = {"disableAllHooks": True, "env": {"ANTHROPIC_BASE_URL": MODELE_MORT}}
    sortie: list[Lancement] = []

    # --- app : ce que ferait le harnais pour une conversation neuve ---------
    effectif = config.parent / f"effectif-{dossier.slug}.json"
    serveurs = {
        nom: resoudre_les_variables(cfg, session=session, agent=f"{dossier.slug}-verif")
        for nom, cfg in configuration_du_profil(settings, profil=dossier.profil, cwd=dossier.chemin).items()
    }
    effectif.write_text(json.dumps({"mcpServers": serveurs}, indent=2), encoding="utf-8")
    harnais = ClaudeHarness.__new__(ClaudeHarness)
    harnais.settings = settings
    impose = harnais._env_impose(None)
    env_app = dict(base)
    if not avec_wikichat:
        env_app["WIKICHAT_PORT"] = "1"
    env_app.update(lire_le_fichier(chemin_du_fichier(settings)))
    env_app.update(variables_du_projet(settings.secrets_dir, dossier.chemin))
    env_app.update(impose)
    env_app["CLAUDE_CODE_EFFORT_LEVEL"] = effort_accepte_partout(settings.effort)
    env_app["ATELIER_SESSION"] = session
    env_app["WIKICHAT_AGENT"] = NOM_VERIFICATEUR
    env_app["PATH"] = str(settings.work_dir / "bin") + _os.pathsep + env_app.get("PATH", "")
    reglages_app = refuser_les_outils_simules({}, settings)
    reglages_app["env"] = {**impose, **reglages["env"]}
    reglages_app["disableAllHooks"] = True
    mode_app, _ = mode_resolu(settings, dossier.chemin, session)
    sortie.append(
        Lancement(
            "app",
            [
                str(binaire),
                *commun,
                "--permission-mode",
                mode_app,
                "--settings",
                json.dumps(reglages_app),
                "--mcp-config",
                str(effectif),
                "--strict-mcp-config",
            ],
            env_app,
            dossier.chemin,
            effort=_effort_des_reglages() or env_app["CLAUDE_CODE_EFFORT_LEVEL"],
        )
    )

    # --- vscode : la ligne de l'extension (2.1.282), par l'enveloppeur -------
    machine = _json(donnees_code_server() / "Machine" / "settings.json")
    utilisateur = _json(donnees_code_server() / "User" / "settings.json")
    env_vscode = dict(base)
    for entree in utilisateur.get("claudeCode.environmentVariables") or []:
        if isinstance(entree, dict) and entree.get("name"):
            env_vscode[str(entree["name"])] = str(entree.get("value") or "")
    env_vscode["CLAUDE_CODE_ENTRYPOINT"] = "claude-vscode"
    ligne_vscode = [str(binaire), *commun, "--setting-sources=user,project,local", "--permission-mode", "default"]
    if machine.get(CLE_BYPASS):
        ligne_vscode.append("--allow-dangerously-skip-permissions")
    ligne_vscode += ["--no-chrome", "--settings", json.dumps(reglages)]
    enveloppeur = enveloppeur_vscode(settings)
    commande_vscode = ([str(enveloppeur)] if enveloppeur.is_file() else []) + ligne_vscode
    sortie.append(Lancement("vscode", commande_vscode, env_vscode, dossier.chemin, effort=_effort_des_reglages()))

    # --- terminal interactif et bash -lc : le vrai chemin du shell ------------
    ligne = " ".join(_shlex.quote(a) for a in ["claude", *commun, "--settings", json.dumps(reglages)])
    for surface, option in (("terminal", "-ic"), ("bash-lc", "-lc")):
        sortie.append(
            Lancement(surface, ["bash", option, ligne], dict(base), dossier.chemin, effort=_effort_des_reglages())
        )
    return sortie


def version_de_l_extension() -> str:
    from mcp_gateway.atelier.claude_home import _version, binaire_claude_le_plus_recent

    binaire = binaire_claude_le_plus_recent()
    if binaire is None:
        return ""
    return ".".join(str(n) for n in _version(binaire.parents[2]))


def verifier_le_hook_de_garde(dossier: Path) -> dict[str, Any]:
    """Lance à blanc, depuis le dossier du projet, le hook `garde_bash` posé dans les réglages.

    Il doit refuser `killall node` par le code 2 (audit G2). Rend `{pose, code}`.
    """
    donnees = _json(Path.home() / ".claude" / "settings.json")
    commandes = [
        h.get("command")
        for g in ((donnees.get("hooks") or {}).get("PreToolUse") or [])
        if isinstance(g, dict)
        for h in (g.get("hooks") or [])
        if isinstance(h, dict) and "garde_bash" in str(h.get("command", ""))
    ]
    if not commandes:
        return {"pose": False, "code": None}
    appel = json.dumps(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "killall node"}}
    )
    env = {k: v for k, v in _os.environ.items() if k != "PYTHONPATH"}
    try:
        fini = _subprocess.run(
            ["sh", "-c", str(commandes[0])],
            input=appel,
            capture_output=True,
            text=True,
            cwd=str(dossier),
            env=env,
            timeout=30,
        )
        code: int | None = fini.returncode
    except (OSError, _subprocess.TimeoutExpired):
        code = None
    return {"pose": True, "code": code}


def hooks_introuvables() -> list[str]:
    """Les hooks de `settings.json` dont le programme n'existe pas (« événement : programme »)."""
    donnees = _json(Path.home() / ".claude" / "settings.json")
    manquants: list[str] = []
    for evenement, groupes in (donnees.get("hooks") or {}).items():
        for g in groupes if isinstance(groupes, list) else []:
            for h in (g.get("hooks") if isinstance(g, dict) else None) or []:
                commande = str(h.get("command") or "") if isinstance(h, dict) else ""
                try:
                    mots = _shlex.split(commande, posix=True)
                except ValueError:
                    continue
                # `VAR=valeur programme …` : le programme suit les affectations.
                mots = [m for m in mots if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", m)]
                if not mots:
                    continue
                programme = _os.path.expanduser(mots[0])
                if not (_shutil.which(programme) or Path(programme).is_file()):
                    manquants.append(f"{evenement} : {Path(programme).name}")
    return manquants


def _outils_comparables(vu: Vu, connectes: set[str]) -> set[str]:
    sortie = set()
    for outil in vu.outils:
        if outil in _OUTILS_CIRCONSTANCIELS:
            continue
        if outil.startswith("mcp__") and outil.split("__")[1] not in connectes:
            continue
        sortie.add(outil)
    return sortie


def notes_du_dossier(vus: dict[str, Vu], *, avec_wikichat: bool = True) -> list[str]:
    """Ce qui n'est pas mesuré, et n'est donc pas un écart."""
    notes: list[str] = []
    if not avec_wikichat:
        notes.append("wikichat non mesuré (pont coupé exprès, --sans-wikichat)")
    for s, v in vus.items():
        attente = sorted(n for n, e in v.serveurs.items() if e == "pending")
        if attente:
            notes.append(f"{s} : encore en attente à l'init {attente} (outils non comparés)")
    return notes


def ecarts_du_dossier(
    settings: AtelierSettings,
    dossier: Dossier,
    vus: dict[str, Vu],
    version_attendue: str,
    *,
    avec_wikichat: bool = True,
) -> list[str]:
    """Les surfaces entre elles, puis au profil du contrat.

    Un écart qui attend le filtrage du serveur `atelier` (équipe A) le dit
    par « (équipe A) ».
    """
    from mcp_gateway.atelier.mcp_sync import configuration_du_profil
    from mcp_gateway.atelier.modes_permission import mode_resolu

    ecarts: list[str] = []
    for surface, vu in vus.items():
        if not vu.ok:
            ecarts.append(f"{surface} : {vu.erreur}")
    lus = {s: v for s, v in vus.items() if v.ok}
    if not lus:
        return ecarts
    # Entre surfaces.
    for champ in ("version", "mode", "modele", "effort"):
        valeurs = {s: getattr(v, champ) for s, v in lus.items()}
        if len(set(valeurs.values())) > 1:
            ecarts.append(f"{champ} différent selon la surface : {valeurs}")
    noms = {s: set(v.serveurs) for s, v in lus.items()}
    if len({frozenset(n) for n in noms.values()}) > 1:
        tous = set().union(*noms.values())
        ecarts.append(
            "serveurs différents : "
            + "; ".join(f"{s} sans {sorted(tous - n)}" for s, n in noms.items() if tous - n)
        )
    for s, v in lus.items():
        echoues = sorted(
            n for n, etat in v.serveurs.items() if etat == "failed" and (avec_wikichat or n != "wikichat")
        )
        if echoues:
            ecarts.append(f"{s} : serveurs en échec {echoues}")
    connectes = set.intersection(*[{n for n, e in v.serveurs.items() if e == "connected"} for v in lus.values()])
    outils = {s: _outils_comparables(v, connectes) for s, v in lus.items()}
    reference_surface, reference = next(iter(outils.items()))
    for s, o in outils.items():
        if o != reference:
            ecarts.append(
                f"outils différents de {reference_surface} ({s}) : en plus {sorted(o - reference)[:8]},"
                f" en moins {sorted(reference - o)[:8]}"
            )
    # Au profil.
    attendu_mode, source = mode_resolu(settings, dossier.chemin, f"verif-{dossier.slug}"[:60])
    attendus = set(configuration_du_profil(settings, profil=dossier.profil, cwd=dossier.chemin))
    for s, v in lus.items():
        if version_attendue and v.version != version_attendue:
            ecarts.append(f"{s} : version {v.version}, l'extension est en {version_attendue}")
        if v.mode != attendu_mode:
            ecarts.append(f"{s} : mode {v.mode}, attendu {attendu_mode} ({source})")
        if set(v.serveurs) != attendus:
            ecarts.append(
                f"{s} : serveurs {sorted(v.serveurs)}, le profil {dossier.profil} en donne {sorted(attendus)}"
            )
        if "WebSearch" in v.outils:
            ecarts.append(f"{s} : WebSearch présent, refusé par le socle")
        if dossier.profil == "code":
            interdits = sorted(
                t
                for t in v.outils
                if t.startswith(OUTILS_INTERDITS_CODE)
                or (t.startswith("mcp__wikichat__") and t.split("__", 2)[2] in WIKICHAT_INTERDITS_CODE)
            )
            if interdits:
                equipe_a = " (équipe A)" if all(t.startswith("mcp__atelier__") for t in interdits) else ""
                ecarts.append(f"{s} : outils hors du profil code {interdits[:8]}{equipe_a}")
        else:
            if v.serveurs.get("atelier") == "connected":
                manquants = [t for t in META_OUTILS if t not in v.outils]
                if manquants:
                    ecarts.append(f"{s} : l'Assistant n'a pas les méta-outils {manquants} (équipe A)")
            # Son `.claude/settings.json` (assistant.py) refuse ce qui écrirait
            # hors de son dossier : un refus retire l'outil de la liste.
            interdits = sorted(t for t in v.outils if t in OUTILS_REFUSES_ASSISTANT)
            if interdits:
                ecarts.append(f"{s} : l'Assistant a {interdits}, que son profil refuse")
    return ecarts


def verifier_reel(
    settings: AtelierSettings,
    *,
    projets: list[str] | None = None,
    rapide: bool = False,
    avec_wikichat: bool = True,
    claude: Path | None = None,
    surfaces: tuple[str, ...] = SURFACES,
    delai: float = 60.0,
) -> dict[str, Any]:
    """Le rapport : par dossier, ce que chaque surface a annoncé, et les écarts."""
    dossiers = echantillon(dossiers_reels(settings), projets, rapide)
    version = version_de_l_extension()
    racine = Path(_tempfile.mkdtemp(prefix="atelier-coherence-"))
    rapport: dict[str, Any] = {"version_extension": version, "dossiers": [], "ecarts": 0}
    try:
        config = _config_temporaire(racine)
        manquants = hooks_introuvables()
        rapport["hooks_introuvables"] = manquants
        rapport["ecarts"] += len(manquants)
        for dossier in dossiers:
            vus: dict[str, Vu] = {}
            for lancement in lancements(settings, dossier, config, avec_wikichat=avec_wikichat, claude=claude):
                if lancement.surface in surfaces:
                    vus[lancement.surface] = lire_init(lancement, delai)
            ecarts = ecarts_du_dossier(settings, dossier, vus, version, avec_wikichat=avec_wikichat)
            garde = verifier_le_hook_de_garde(dossier.chemin)
            if not garde["pose"]:
                ecarts.append("hook garde_bash absent des réglages")
            elif garde["code"] != 2:
                ecarts.append(f"hook garde_bash lancé depuis le projet : code {garde['code']}, attendu 2")
            rapport["dossiers"].append(
                {
                    "slug": dossier.slug,
                    "profil": dossier.profil,
                    "surfaces": {s: v.to_dict() for s, v in vus.items()},
                    "hook_garde": garde,
                    "ecarts": ecarts,
                    "notes": notes_du_dossier(vus, avec_wikichat=avec_wikichat),
                }
            )
            rapport["ecarts"] += len(ecarts)
    finally:
        _shutil.rmtree(racine, ignore_errors=True)
    return rapport


def rapport_en_texte(rapport: dict[str, Any]) -> str:
    lignes = [f"Extension Claude Code : {rapport.get('version_extension') or 'introuvable'}"]
    for manque in rapport.get("hooks_introuvables") or []:
        lignes.append(f"  hook introuvable : {manque}")
    for d in rapport.get("dossiers") or []:
        lignes.append("")
        lignes.append(f"[{d['slug']}] profil {d['profil']}")
        for s, v in d["surfaces"].items():
            if not v["ok"]:
                lignes.append(f"  {s:9} ÉCHEC : {v['erreur']}")
                continue
            serveurs = ", ".join(f"{n}:{e}" for n, e in v["serveurs"].items())
            lignes.append(
                f"  {s:9} {v['version']} mode={v['mode']} modele={v['modele']} effort={v['effort'] or '?'}"
                f" outils={len(v['outils'])} [{serveurs}] ({v['duree_s']} s)"
            )
        garde = d["hook_garde"]
        lignes.append(f"  hook garde_bash : {'code ' + str(garde['code']) if garde['pose'] else 'absent'}")
        for n in d.get("notes") or []:
            lignes.append(f"  note : {n}")
        for e in d["ecarts"]:
            lignes.append(f"  ÉCART : {e}")
    lignes.append("")
    equipe_a = sum(1 for d in rapport.get("dossiers") or [] for e in d["ecarts"] if e.endswith("(équipe A)"))
    lignes.append(f"{rapport.get('ecarts', 0)} écart(s), dont {equipe_a} en attente de l'équipe A.")
    return "\n".join(lignes)
