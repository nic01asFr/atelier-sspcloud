"""Ce que les contrôles lisent du monde, derrière des fonctions remplaçables.

Un contrôle ne touche jamais `/proc`, le réseau ou un sous-processus
directement : il passe par le `Contexte`. En service, le contexte lit le pod ;
dans les tests, il rend des fixtures. C'est ce qui permet de tester chaque
contrôle sur un pod imaginaire, y compris sous Windows.

Tout ici est en lecture seule.
"""

from __future__ import annotations

import glob
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class Ecoute:
    adresse: str  # « 0.0.0.0 », « :: », « 127.0.0.1 », « ::1 »…
    port: int
    pid: int | None = None
    commande: str = ""

    @property
    def toutes_interfaces(self) -> bool:
        return self.adresse in ("0.0.0.0", "::")


@dataclass(frozen=True)
class Processus:
    pid: int
    argv: list[str]
    cwd: str = ""
    ppid: int | None = None


@dataclass(frozen=True)
class ReponseHttp:
    statut: int  # 0 = pas de réponse
    corps: str = ""
    erreur: str = ""


def http_get(url: str, entetes: dict[str, str] | None = None, delai: float = 5.0) -> ReponseHttp:
    """GET sans exception. Les en-têtes (clés comprises) ne sortent jamais d'ici."""
    requete = urllib.request.Request(url, headers=entetes or {}, method="GET")
    try:
        with urllib.request.urlopen(requete, timeout=delai) as r:  # noqa: S310 — adresses de la déclaration
            return ReponseHttp(r.status, r.read(1_000_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        try:
            corps = exc.read(100_000).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            corps = ""
        return ReponseHttp(exc.code, corps)
    except Exception as exc:  # noqa: BLE001 — refus, délai, DNS : « pas de réponse »
        return ReponseHttp(0, "", type(exc).__name__ + ": " + str(getattr(exc, "reason", exc))[:200])


def lancer(argv: list[str], delai: float = 20.0, cwd: str | None = None) -> tuple[int, str]:
    """Une commande de lecture (git, gh). Rend (code, sortie) ; 127 si absente."""
    try:
        fini = subprocess.run(  # noqa: S603 — argv fixé par le contrôle, sans shell
            argv, capture_output=True, text=True, timeout=delai, cwd=cwd, stdin=subprocess.DEVNULL
        )
    except FileNotFoundError:
        return 127, ""
    except subprocess.TimeoutExpired:
        return 124, ""
    except OSError as exc:
        return 126, str(exc)
    erreur = (fini.stderr or "") if fini.returncode else ""
    return fini.returncode, (fini.stdout or "") + erreur


# --- /proc ------------------------------------------------------------------


def _adresse_ipv4(hexa: str) -> str:
    octets = bytes.fromhex(hexa)[::-1]
    return ".".join(str(b) for b in octets)


def _adresse_ipv6(hexa: str) -> str:
    if hexa == "0" * 32:
        return "::"
    if hexa == "00000000000000000000000001000000":
        return "::1"
    if hexa.startswith("0000000000000000FFFF0000"):
        return _adresse_ipv4(hexa[24:])
    mots = []
    for i in range(0, 32, 8):
        mot = bytes.fromhex(hexa[i : i + 8])[::-1].hex()
        mots += [mot[:4], mot[4:]]
    return ":".join(m.lstrip("0") or "0" for m in mots)


def ecoutes_du_texte(texte: str, v6: bool) -> list[tuple[str, int, str]]:
    """Les sockets TCP en écoute (état 0A) d'un `/proc/net/tcp{,6}` : (adresse, port, inode)."""
    sortie = []
    for ligne in texte.splitlines()[1:]:
        c = ligne.split()
        if len(c) < 10 or c[3] != "0A":
            continue
        hexa, port = c[1].split(":")
        adresse = _adresse_ipv6(hexa) if v6 else _adresse_ipv4(hexa)
        sortie.append((adresse, int(port, 16), c[9]))
    return sortie


def _cmdline(proc: Path, pid: str) -> list[str]:
    try:
        brut = (proc / pid / "cmdline").read_bytes()
    except OSError:
        return []
    return [a.decode("utf-8", "replace") for a in brut.split(b"\0") if a]


def ecoutes_du_pod(proc: Path = Path("/proc")) -> list[Ecoute]:
    """Qui écoute où, par l'inode de la socket (comme `atelier-relancer`)."""
    trouvees: list[tuple[str, int, str]] = []
    for nom, v6 in (("tcp", False), ("tcp6", True)):
        try:
            trouvees += ecoutes_du_texte((proc / "net" / nom).read_text(), v6)
        except OSError:
            continue
    inodes = {i for _, _, i in trouvees}
    proprietaires: dict[str, str] = {}
    for dossier in glob.glob(str(proc / "[0-9]*")):
        pid = os.path.basename(dossier)
        for fd in glob.glob(dossier + "/fd/*"):
            try:
                m = re.match(r"socket:\[(\d+)\]", os.readlink(fd))
            except OSError:
                continue
            if m and m.group(1) in inodes:
                proprietaires.setdefault(m.group(1), pid)
    sortie = []
    vues: set[tuple[str, int]] = set()
    for adresse, port, inode in trouvees:
        if (adresse, port) in vues:
            continue
        vues.add((adresse, port))
        pid = proprietaires.get(inode)
        commande = " ".join(_cmdline(proc, pid))[:160] if pid else ""
        sortie.append(Ecoute(adresse, port, int(pid) if pid else None, commande))
    return sortie


def processus_du_pod(proc: Path = Path("/proc")) -> list[Processus]:
    sortie = []
    for dossier in glob.glob(str(proc / "[0-9]*")):
        pid = os.path.basename(dossier)
        argv = _cmdline(proc, pid)
        if not argv:
            continue
        try:
            cwd = os.readlink(dossier + "/cwd")
        except OSError:
            cwd = ""
        ppid = None
        try:
            for ligne in (Path(dossier) / "status").read_text().splitlines():
                if ligne.startswith("PPid:"):
                    ppid = int(ligne.split()[1])
                    break
        except (OSError, ValueError):
            pass
        sortie.append(Processus(int(pid), argv, cwd, ppid))
    return sortie


# --- le contexte ------------------------------------------------------------


@dataclass
class Contexte:
    work: Path
    home: Path
    port_atelier: int = 8787
    port_relais: int = 8790
    port_wikichat: int = 3777
    secrets_dir: Path | None = None
    sessions_dir: Path | None = None
    projects_dir: Path | None = None
    wikichat_dir: Path | None = None
    code_server_dir: Path | None = None
    atelier_src: Path | None = None
    reglages: dict[str, Any] = field(default_factory=dict)
    http: Callable[..., ReponseHttp] = http_get
    commande: Callable[..., tuple[int, str]] = lancer
    ecoutes: Callable[[], list[Ecoute]] = ecoutes_du_pod
    processus: Callable[[], list[Processus]] = processus_du_pod
    disque: Callable[[Path], tuple[int, int]] = lambda p: _disque(p)  # (total, libre) en octets
    maintenant: Callable[[], float] = time.time
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))
    # Ce que l'exécuteur sait de ses propres contrôles (G0 les inventorie).
    etat_executeur: Callable[[], list[dict[str, Any]]] = lambda: []

    def __post_init__(self) -> None:
        self.secrets_dir = self.secrets_dir or self.work / ".secrets"
        self.sessions_dir = self.sessions_dir or self.work / "sessions"
        self.projects_dir = self.projects_dir or self.work / "projects"
        self.wikichat_dir = self.wikichat_dir or self.home / ".wikichat"
        self.code_server_dir = self.code_server_dir or self.home / ".local/share/code-server"
        self.atelier_src = self.atelier_src or self.work / "atelier-src"

    def cle_owner(self) -> str:
        """La clé de l'Atelier, pour lire son API. Jamais journalisée ni rendue."""
        try:
            return (self.secrets_dir / "atelier_owner_key").read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @classmethod
    def depuis_reglages(cls, reglages_gardiens: dict[str, Any] | None = None) -> "Contexte":
        from mcp_gateway.atelier.claude_home import donnees_code_server
        from mcp_gateway.atelier.config import get_settings

        s = get_settings()
        return cls(
            work=Path(s.work_dir),
            home=Path.home(),
            port_atelier=s.port,
            port_relais=s.relais_llm_port,
            port_wikichat=int(os.environ.get("WIKICHAT_PORT") or 3777),
            secrets_dir=Path(s.secrets_dir),
            sessions_dir=Path(s.sessions_dir),
            projects_dir=Path(s.projects_dir),
            wikichat_dir=Path(os.environ.get("WIKICHAT_HOME") or Path.home() / ".wikichat"),
            code_server_dir=donnees_code_server(),
            reglages=reglages_gardiens or {},
        )


def _disque(chemin: Path) -> tuple[int, int]:
    import shutil

    u = shutil.disk_usage(chemin)
    return u.total, u.free


def lire_json(chemin: Path) -> Any:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


NIVEAUX = ("ok", "attention", "alerte")


def constat(empreinte: str, objet: str, resume: str, preuve: str = "", niveau: str = "alerte") -> dict[str, str]:
    return {"empreinte": empreinte, "objet": objet, "resume": resume, "preuve": preuve, "niveau": niveau}


def resultat(constats: list[dict[str, str]], **donnees: Any) -> dict[str, Any]:
    """`ok` sans constat ; sinon le niveau le plus grave de ses constats."""
    etat = "ok"
    for c in constats:
        n = c.get("niveau", "alerte")
        if NIVEAUX.index(n if n in NIVEAUX else "alerte") > NIVEAUX.index(etat):
            etat = n if n in NIVEAUX else "alerte"
    sortie: dict[str, Any] = {"etat": etat, "constats": constats}
    if donnees:
        sortie["donnees"] = donnees
    return sortie


def github_api(ctx: Contexte, chemin: str) -> tuple[int, Any, str]:
    """GET sur l'API GitHub : (statut, JSON, moyen). Aucun jeton ne sort d'ici.

    `gh` s'il est là (il tient sa propre authentification) ; sinon l'API
    directe, avec `~/work/.secrets/github_token` s'il existe, anonyme sinon.
    """
    code, sortie = ctx.commande(["gh", "api", chemin], 20.0)
    if code == 0:
        try:
            return 200, json.loads(sortie), "gh"
        except json.JSONDecodeError:
            return 0, None, "gh"
    entetes = {"Accept": "application/vnd.github+json", "User-Agent": "atelier-gardiens"}
    moyen = "api anonyme"
    try:
        jeton = (ctx.secrets_dir / "github_token").read_text(encoding="utf-8").strip()
    except OSError:
        jeton = ""
    if jeton:
        entetes["Authorization"] = f"Bearer {jeton}"
        moyen = "api avec jeton"
    r = ctx.http(f"https://api.github.com/{chemin}", entetes, 15.0)
    try:
        corps = json.loads(r.corps) if r.corps else None
    except json.JSONDecodeError:
        corps = None
    return r.statut, corps, moyen
