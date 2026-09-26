"""G2, gardien Sécurité : qu'est-ce qui est ouvert, en clair, ou plus permissif que déclaré ?

Aucun de ces contrôles n'écrit une valeur secrète : il compare des valeurs en
mémoire et ne rend que des chemins, des noms de variables et des empreintes
(12 caractères de SHA-256).
"""

from __future__ import annotations

import glob
import os
import stat
from pathlib import Path
from typing import Any, Iterable

from mcp_gateway.gardiens.controles.commun import Contexte, constat, lire_json, resultat
from mcp_gateway.gardiens.journal import LONGUEUR_MIN_SECRET, MOTIFS_DE_JETONS, empreinte_de_valeur

# Les motifs sans ambiguïté (préfixes de service). Le motif générique
# « bearer|token|basic <valeur> » donne des faux positifs dans du code et de
# la documentation : il ne s'applique qu'aux fichiers de configuration.
MOTIFS_FORTS = MOTIFS_DE_JETONS[:5]
NOMS_DES_MOTIFS = ("github", "github_pat", "gitlab", "cle sk-", "slack", "en-tete d'authentification")
TAILLE_MAX = 2_000_000


# --- écoutes ----------------------------------------------------------------


def ecoutes(ctx: Contexte, c: Any) -> dict[str, Any]:
    """Toute écoute sur toutes les interfaces hors de la liste déclarée est un constat."""
    declarees = c.params.get("declarees", ctx.reglages.get("ecoutes_declarees", []))
    ports_declares = {int(d["port"]) for d in declarees if isinstance(d, dict) and "port" in d}
    constats = []
    ouvertes = []
    for e in ctx.ecoutes():
        if not e.toutes_interfaces:
            continue
        ouvertes.append({"adresse": e.adresse, "port": e.port, "pid": e.pid, "declaree": e.port in ports_declares})
        if e.port in ports_declares:
            continue
        constats.append(
            constat(
                f"{c.id}:{e.port}",
                f"{e.adresse}:{e.port}",
                "écoute sur toutes les interfaces, hors de la liste déclarée",
                f"pid {e.pid} : {e.commande}" if e.pid else "processus introuvable",
            )
        )
    return resultat(constats, toutes_interfaces=sorted(ouvertes, key=lambda o: o["port"]))


# --- secrets en clair -------------------------------------------------------


def valeurs_connues(ctx: Contexte) -> dict[str, str]:
    """Nom lisible -> valeur, depuis `claude-env.sh` et les fichiers de `~/work/.secrets/`.

    `claude-env.sh` est régénéré par l'Atelier depuis toutes les sources
    (`env_secrets.variables_secretes`) : le lire suffit, sans ouvrir la base
    du pool.
    """
    from mcp_gateway.atelier.env_secrets import NOM_DU_FICHIER, lire_le_fichier

    valeurs = {nom: v for nom, v in lire_le_fichier(ctx.secrets_dir / NOM_DU_FICHIER).items()}
    for chemin in sorted(ctx.secrets_dir.rglob("*")) if ctx.secrets_dir.is_dir() else []:
        if not chemin.is_file() or chemin.name == NOM_DU_FICHIER or chemin.suffix == ".tmp":
            continue
        try:
            if chemin.stat().st_size > 4096:
                continue
            texte = chemin.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            continue
        if texte and "\n" not in texte:
            valeurs.setdefault(f"fichier {chemin.relative_to(ctx.secrets_dir).as_posix()}", texte)
    return {n: v for n, v in valeurs.items() if len(v) >= LONGUEUR_MIN_SECRET}


def fichiers_de_configuration(ctx: Contexte) -> list[Path]:
    """Ce que lit Claude Code ou git, sur toutes les surfaces (`coherence.fichiers_a_inspecter`, élargi)."""
    candidats = [
        ctx.home / ".claude.json",
        ctx.home / ".claude" / "settings.json",
        ctx.work / ".claude.json",
        ctx.code_server_dir / "User" / "settings.json",
        ctx.code_server_dir / "Machine" / "settings.json",
    ]
    for motif in ("mcp/*.json", "mcp/effective/*.json", "projects/*/.mcp.json", "projects/*/.git/config", "repos/*/.git/config"):
        candidats += [Path(p) for p in sorted(glob.glob(str(ctx.work / motif)))]
    vus: set[str] = set()
    sortie = []
    for p in candidats:
        cle = os.path.realpath(p)
        if cle in vus or not p.is_file():
            continue
        vus.add(cle)
        sortie.append(p)
    return sortie


def depots_suivis(ctx: Contexte, c: Any) -> list[Path]:
    motifs = c.params.get("depots", ["projects/*", "repos/*"])
    sortie = []
    for motif in motifs:
        for p in sorted(glob.glob(str(ctx.work / motif))):
            if (Path(p) / ".git").exists():
                sortie.append(Path(p))
    return sortie


def fichiers_suivis(ctx: Contexte, depot: Path, maximum: int) -> list[Path]:
    code, sortie = ctx.commande(["git", "-C", str(depot), "ls-files", "-z"], 20.0)
    if code != 0:
        return []
    noms = [n for n in sortie.split("\0") if n and not n.endswith(".mcp.json")]
    return [depot / n for n in noms[:maximum]]


def _lire(chemin: Path, taille_max: int) -> str | None:
    try:
        if chemin.stat().st_size > taille_max:
            return None
        brut = chemin.read_bytes()
    except OSError:
        return None
    if b"\0" in brut[:8192]:
        return None
    return brut.decode("utf-8", "replace")


def chercher(
    fichiers: Iterable[Path],
    valeurs: dict[str, str],
    motifs: tuple,
    controle: str,
    taille_max: int = TAILLE_MAX,
) -> list[dict[str, str]]:
    constats = []
    for chemin in fichiers:
        texte = _lire(chemin, taille_max)
        if texte is None:
            continue
        for nom, valeur in valeurs.items():
            if valeur in texte:
                emp = empreinte_de_valeur(valeur)
                constats.append(
                    constat(f"{controle}:{emp}:{chemin}", str(chemin), f"valeur de {nom} en clair", f"empreinte {emp}")
                )
        for motif in motifs:
            nom_motif = NOMS_DES_MOTIFS[MOTIFS_DE_JETONS.index(motif)]
            for m in motif.finditer(texte):
                if any(v in m.group(0) or m.group(0) in v for v in valeurs.values()):
                    continue  # déjà vu comme valeur connue
                emp = empreinte_de_valeur(m.group(0))
                ligne = texte.count("\n", 0, m.start()) + 1
                constats.append(
                    constat(
                        f"{controle}:motif:{emp}:{chemin}",
                        str(chemin),
                        f"motif de jeton ({nom_motif})",
                        f"ligne {ligne}, empreinte {emp}",
                        "attention" if motif is MOTIFS_DE_JETONS[5] else "alerte",
                    )
                )
    return constats


def secrets_en_clair(ctx: Contexte, c: Any) -> dict[str, Any]:
    valeurs = valeurs_connues(ctx)
    config = fichiers_de_configuration(ctx)
    constats = chercher(config, valeurs, MOTIFS_DE_JETONS, c.id)
    suivis = 0
    if c.params.get("depots_suivis", True):
        maximum = int(c.params.get("fichiers_max_par_depot", 3000))
        for depot in depots_suivis(ctx, c):
            fichiers = fichiers_suivis(ctx, depot, maximum)
            suivis += len(fichiers)
            constats += chercher(fichiers, valeurs, MOTIFS_FORTS, c.id, 512_000)
    return resultat(
        constats,
        valeurs_connues=len(valeurs),
        fichiers_de_configuration=len(config),
        fichiers_suivis=suivis,
    )


# --- droits -----------------------------------------------------------------


def droits(ctx: Contexte, c: Any) -> dict[str, Any]:
    """Fichiers de secrets en 0600 (rien pour le groupe ni les autres), dossier en 0700."""
    constats = []
    vus = 0
    dossiers = [ctx.secrets_dir]
    fichiers: list[Path] = []
    if ctx.secrets_dir.is_dir():
        for p in sorted(ctx.secrets_dir.rglob("*")):
            (dossiers if p.is_dir() else fichiers).append(p)
    for motif in c.params.get("autres", []):
        fichiers += [Path(p) for p in sorted(glob.glob(os.path.expanduser(motif)))]
    for d in dossiers:
        try:
            mode = stat.S_IMODE(d.stat().st_mode)
        except OSError:
            continue
        if mode & 0o077:
            constats.append(
                constat(f"{c.id}:{d}", str(d), "dossier de secrets ouvert au groupe ou aux autres", f"mode {mode:o}", "attention")
            )
    for f in fichiers:
        try:
            mode = stat.S_IMODE(f.stat().st_mode)
        except OSError:
            continue
        vus += 1
        if mode & 0o077:
            constats.append(constat(f"{c.id}:{f}", str(f), "fichier de secrets lisible par d'autres", f"mode {mode:o}, attendu 600"))
    return resultat(constats, fichiers=vus)


# --- sessions en bypass -----------------------------------------------------


def _est_claude(argv: list[str]) -> bool:
    return any(os.path.basename(a) == "claude" for a in argv[:2])


def _en_bypass(argv: list[str]) -> bool:
    if "--dangerously-skip-permissions" in argv or "--permission-mode=bypassPermissions" in argv:
        return True
    return any(a == "--permission-mode" and b == "bypassPermissions" for a, b in zip(argv, argv[1:]))


def _session(argv: list[str]) -> str:
    for a, b in zip(argv, argv[1:]):
        if a in ("--resume", "-r", "--session-id"):
            return b
    return ""


def fiches_de_l_atelier(ctx: Contexte) -> dict[str, dict[str, Any]]:
    fiches: dict[str, dict[str, Any]] = {}
    for p in sorted(ctx.sessions_dir.glob("*.json")) if ctx.sessions_dir.is_dir() else []:
        d = lire_json(p)
        if not isinstance(d, dict):
            continue
        for cle in ("session_id", "claude_session_id"):
            if d.get(cle):
                fiches[str(d[cle])] = d
    return fiches


# Du moins au plus permissif : un processus plus permissif que ce que sa
# conversation a choisi est un constat ; moins permissif, non.
ORDRE_DES_MODES = {"plan": 0, "default": 1, "acceptEdits": 2, "bypassPermissions": 3}
_ALIAS_DES_MODES = {"manual": "default", "auto": "default"}


def _mode(texte: Any) -> str:
    valeur = _ALIAS_DES_MODES.get(str(texte or ""), str(texte or ""))
    return valeur if valeur in ORDRE_DES_MODES else ""


def _mode_vivant(argv: list[str]) -> str:
    """Le mode qu'un `claude` a reçu à son lancement, lu sur sa ligne de commande."""
    if "--dangerously-skip-permissions" in argv:
        return "bypassPermissions"
    for a, b in zip(argv, argv[1:]):
        if a == "--permission-mode":
            return _mode(b)
    for a in argv:
        if a.startswith("--permission-mode="):
            return _mode(a.split("=", 1)[1])
    return ""


def fichiers_de_processus(ctx: Contexte) -> dict[int, dict[str, Any]]:
    """`<config>/sessions/<pid>.json`, que Claude Code tient pour chaque processus.

    C'est par là qu'un processus VS Code se rattache à sa conversation : sa
    ligne de commande ne porte pas toujours `--resume <id>`.
    """
    dossiers = []
    if (ctx.env or {}).get("CLAUDE_CONFIG_DIR"):
        dossiers.append(Path(ctx.env["CLAUDE_CONFIG_DIR"]))
    dossiers += [ctx.home / ".claude", ctx.work / ".claude"]
    sortie: dict[int, dict[str, Any]] = {}
    for dossier in dossiers:
        repertoire = dossier / "sessions"
        if not repertoire.is_dir():
            continue
        for f in repertoire.glob("*.json"):
            d = lire_json(f)
            if not isinstance(d, dict):
                continue
            try:
                pid = int(d.get("pid") or f.stem)
            except (TypeError, ValueError):
                continue
            sortie.setdefault(pid, d)
    return sortie


def mode_choisi(ctx: Contexte, identifiant: str, fiche: dict[str, Any], cwd: str) -> str:
    """Le mode que la conversation a choisi : son choix, puis le défaut du projet, puis celui du service.

    La même règle que l'Atelier (`modes_permission.mode_resolu`) : le magasin
    de l'extension VS Code d'abord (sous l'identifiant du CLI), la copie de la
    fiche ensuite, le `defaultMode` du projet, et `acceptEdits`.
    """
    magasin = (
        ctx.code_server_dir / "User" / "globalStorage" / "anthropic.claude-code"
        / "session-permission-modes" / f"{identifiant}.json"
    )
    choix = lire_json(magasin) if identifiant else None
    if isinstance(choix, dict) and _mode(choix.get("mode")):
        return _mode(choix.get("mode"))
    if _mode(fiche.get("permission_mode")):
        return _mode(fiche.get("permission_mode"))
    dossier = str(fiche.get("cwd") or cwd or "")
    if dossier:
        reglages = lire_json(Path(dossier) / ".claude" / "settings.local.json")
        permissions = reglages.get("permissions") if isinstance(reglages, dict) else None
        if isinstance(permissions, dict) and _mode(permissions.get("defaultMode")):
            return _mode(permissions.get("defaultMode"))
    return "acceptEdits"


def bypass(ctx: Contexte, c: Any) -> dict[str, Any]:
    """Deux constats sur les processus `claude` :

    - un processus en bypassPermissions qui n'a **aucune** fiche de l'Atelier.
      Le rapprochement se fait par l'identifiant du CLI (`--resume`,
      `--session-id`, ou `sessions/<pid>.json`) et par `claude_session_id` :
      le 26/09, un processus VS Code dont la fiche existait était signalé ;
    - un processus plus permissif que le mode que sa conversation a choisi
      (le mode a changé après son lancement : il le garde jusqu'à sa fin).
    """
    tous = ctx.processus()
    par_pid = {p.pid: p for p in tous}
    fiches = None
    fichiers = None
    constats = []
    en_bypass = 0
    for p in tous:
        if not _est_claude(p.argv):
            continue
        vivant = _mode_vivant(p.argv)
        if not vivant:
            continue
        if vivant == "bypassPermissions":
            en_bypass += 1
        if fiches is None:
            fiches = fiches_de_l_atelier(ctx)
            fichiers = fichiers_de_processus(ctx)
        sid = _session(p.argv) or str((fichiers or {}).get(p.pid, {}).get("sessionId") or "")
        fiche = fiches.get(sid) if sid else None
        parent = par_pid.get(p.ppid) if p.ppid else None
        preuve = f"cwd {p.cwd or '?'} ; lancé par pid {p.ppid} ({' '.join(parent.argv)[:80] if parent else '?'})"
        if fiche is None:
            if vivant == "bypassPermissions":
                constats.append(
                    constat(f"{c.id}:{sid or p.pid}", f"pid {p.pid}", "session claude en bypassPermissions sans fiche de l'Atelier", preuve)
                )
            continue
        choisi = mode_choisi(ctx, sid, fiche, p.cwd)
        if ORDRE_DES_MODES[vivant] > ORDRE_DES_MODES[choisi]:
            surface = str((fichiers or {}).get(p.pid, {}).get("entrypoint") or "")
            constats.append(
                constat(
                    f"{c.id}:{sid}:mode",
                    f"pid {p.pid}",
                    f"session lancée en {vivant} alors que sa conversation a choisi {choisi} : elle le garde jusqu'à sa fermeture",
                    preuve + (f" ; surface {surface}" if surface else ""),
                    "alerte" if vivant == "bypassPermissions" else "attention",
                )
            )
    return resultat(constats, claude_en_bypass=en_bypass)

