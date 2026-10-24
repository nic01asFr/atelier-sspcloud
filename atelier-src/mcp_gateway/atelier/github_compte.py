"""Le compte GitHub de la personne, vu de l'Atelier : se connecter, voir ses dépôts, en ouvrir un comme projet.

La personne colle **une fois** un jeton « fine-grained » dans Réglages (le plus étroit que GitHub
sache faire : choisir les dépôts, ne donner que le contenu). L'Atelier :

- le **vérifie** auprès de GitHub avant de le garder, et dit ce qui ne va pas en clair ;
- l'écrit en 0600 dans `~/work/.secrets/github_token` — le même fichier que la publication
  (`git_repos`) — et ne le rend **jamais**, ni à l'écran, ni dans une erreur, ni au journal ;
- ne l'écrit jamais dans l'adresse d'un dépôt ni sur une ligne de commande : git va le chercher
  par `GIT_ASKPASS` (`git_repos._askpass`), qui ne porte que le chemin du fichier ;
- n'appelle que `api.github.com` et `github.com` : aucune adresse n'est donnée par l'appelant.

**Ouvrir un dépôt comme projet** : on ne clone que `proprietaire/depot`, nom validé (pas de `..`, pas
d'option git qui se glisserait), après avoir demandé à GitHub si le jeton y accède, et sous une
taille plafonnée. Le dépôt arrive dans `~/work/projects/<slug>`, son `origin` sans aucun secret ;
les fichiers de l'Atelier (`.mcp.json`, `.atelier/…`) vont dans `.git/info/exclude`, pas dans son
`.gitignore`. Ce qu'on a cloné est noté dans `.git/atelier-clone.json` et dans
`~/work/.atelier-etat/depots.json` : c'est **ce dépôt-là** que l'Atelier mettra à jour ou
poussera, pas celui qu'un `git remote` aurait été reconfiguré pour viser.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_gateway.atelier import git_repos
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.fournisseurs_gestion import _ecrire

log = logging.getLogger("atelier.github")

API = git_repos.API_GITHUB
ADRESSE_DES_DEPOTS = "https://github.com/"
DELAI_S = 15.0
CLONE_DELAI_S = 600.0
OCTETS_MAX = 5_000_000
TAILLE_MAX_KO = 500_000  # un dépôt de plus de ~500 Mo ne s'ouvre pas d'ici
CACHE_S = 60.0
PAGES_MAX = 3  # 300 dépôts : au-delà, on le dit

# Jetons GitHub : `github_pat_…` (fine-grained), `ghp_…` (classique), `gho_…`… ASCII sans espace.
_JETON = re.compile(r"^[A-Za-z0-9_]{20,255}$")
_PROPRIETAIRE = r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})"
_DEPOT = r"[A-Za-z0-9_.-]{1,100}"
NOM_DEPOT = re.compile(rf"^({_PROPRIETAIRE})/({_DEPOT})$")

_cache: dict[str, Any] = {"t": 0.0, "cle": "", "liste": []}


class ErreurGithub(Exception):
    """Une erreur que la personne (ou l'agent) peut lire telle quelle : jamais un jeton dedans."""


# ── Où sont les choses ──────────────────────────────────────────────────


def _fichier_compte(settings: AtelierSettings) -> Path:
    return settings.secrets_dir / "github.json"


def _registre(settings: AtelierSettings) -> Path:
    return Path(settings.work_dir) / ".atelier-etat" / "depots.json"


def _lire_json(chemin: Path) -> dict[str, Any]:
    try:
        lu = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return lu if isinstance(lu, dict) else {}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── GitHub ──────────────────────────────────────────────────────────────


def _dire(code: int, entetes: Any) -> str:
    if code == 401:
        return "GitHub refuse ce jeton : il est invalide, expiré ou révoqué."
    if code == 403:
        if str(entetes.get("x-ratelimit-remaining", "")) == "0":
            return "GitHub limite les appels pour l'instant : réessayez dans quelques minutes."
        return "Le jeton n'a pas le droit de faire cela : revoyez ses permissions (Contents, Metadata) sur GitHub."
    if code == 404:
        return "Introuvable, ou le jeton n'y a pas accès (un dépôt privé hors du jeton répond comme s'il n'existait pas)."
    return f"GitHub a répondu {code}."


def _get(jeton: str, route: str) -> Any:
    requete = urllib.request.Request(
        API + route,
        headers={
            "Authorization": f"Bearer {jeton}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "atelier",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
            return json.loads(reponse.read(OCTETS_MAX).decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        raise ErreurGithub(_dire(exc.code, exc.headers)) from None
    except (urllib.error.URLError, OSError, ValueError):
        raise ErreurGithub("GitHub est injoignable depuis le pod : réessayez dans un instant.") from None


def _jeton(settings: AtelierSettings) -> str:
    jeton = git_repos._jeton(settings)  # noqa: SLF001 — un seul endroit lit le fichier
    if not jeton:
        raise ErreurGithub("Aucun compte GitHub connecté : collez un jeton dans Réglages.")
    return jeton


# ── Le compte ───────────────────────────────────────────────────────────


def etat(settings: AtelierSettings) -> dict[str, Any]:
    """Où en est la connexion. Jamais le jeton."""
    connecte = bool(git_repos._jeton(settings))  # noqa: SLF001
    compte = _lire_json(_fichier_compte(settings)) if connecte else {}
    return {
        "connecte": connecte,
        "login": str(compte.get("login") or "") if connecte else "",
        "nom": str(compte.get("nom") or "") if connecte else "",
        "type": str(compte.get("type") or "") if connecte else "",
        "depuis": str(compte.get("connecte_le") or "") if connecte else "",
    }


def connecter(settings: AtelierSettings, jeton: str) -> dict[str, Any]:
    """Vérifie le jeton auprès de GitHub, puis le garde. Refuse sans rien écrire si GitHub le refuse."""
    jeton = (jeton or "").strip()
    if not _JETON.match(jeton):
        raise ErreurGithub(
            "Ce n'est pas un jeton GitHub : il commence par « github_pat_ » (jeton fine-grained), "
            "sans espace ni retour à la ligne."
        )
    profil = _get(jeton, "/user")
    login = str((profil or {}).get("login") or "")
    if not login:
        raise ErreurGithub("GitHub n'a pas dit à qui est ce jeton : il n'a pas accès à votre profil.")
    classique = not jeton.startswith("github_pat_")
    _ecrire(settings.github_token_path, jeton)
    try:
        git_repos.poser_credential_helper(settings)  # git lira ce jeton tout seul : plus rien à passer à la main
    except OSError:
        pass
    _ecrire(
        _fichier_compte(settings),
        json.dumps(
            {
                "login": login,
                "nom": str((profil or {}).get("name") or ""),
                "type": "classique" if classique else "fine-grained",
                "connecte_le": _maintenant(),
            },
            ensure_ascii=False,
        ),
    )
    _cache["t"] = 0.0
    rendu = etat(settings)
    if classique:
        rendu["avertissement"] = (
            "Jeton classique : il ouvre tous vos dépôts. Un jeton « fine-grained » limité aux dépôts "
            "voulus est plus sûr."
        )
    return rendu


def deconnecter(settings: AtelierSettings) -> dict[str, Any]:
    """Retire le jeton. Les projets déjà ouverts restent : ils se relient en recollant un jeton."""
    for chemin in (settings.github_token_path, _fichier_compte(settings)):
        try:
            chemin.unlink()
        except FileNotFoundError:
            pass
    _cache.update(t=0.0, cle="", liste=[])
    return etat(settings)


# ── Les dépôts ──────────────────────────────────────────────────────────


def _resume(depot: dict[str, Any]) -> dict[str, Any]:
    return {
        "nom": str(depot.get("full_name") or ""),
        "prive": bool(depot.get("private")),
        "description": str(depot.get("description") or "")[:200],
        "branche": str(depot.get("default_branch") or "main"),
        "maj": str(depot.get("pushed_at") or ""),
        "archive": bool(depot.get("archived")),
        "ecriture": bool((depot.get("permissions") or {}).get("push")),
        "taille_ko": int(depot.get("size") or 0),
    }


def depots_lies(settings: AtelierSettings) -> dict[str, str]:
    """`proprietaire/depot` → slug du projet qui l'a ouvert."""
    lies = _lire_json(_registre(settings))
    return {str(v.get("depot")): slug for slug, v in lies.items() if isinstance(v, dict) and v.get("depot")}


def depots(settings: AtelierSettings, requete: str = "", *, actualiser: bool = False) -> dict[str, Any]:
    """Les dépôts auxquels le jeton donne accès, publics et privés, le plus récent d'abord."""
    jeton = _jeton(settings)
    cle = hashlib.sha256(jeton.encode("utf-8")).hexdigest()[:12]
    maintenant = time.monotonic()
    if actualiser or _cache["cle"] != cle or maintenant - float(_cache["t"]) > CACHE_S:
        liste: list[dict[str, Any]] = []
        for page in range(1, PAGES_MAX + 1):
            lot = _get(
                jeton,
                f"/user/repos?per_page=100&sort=pushed&affiliation=owner,collaborator,organization_member&page={page}",
            )
            liste += [_resume(d) for d in (lot or []) if isinstance(d, dict) and d.get("full_name")]
            if len(lot or []) < 100:
                break
        _cache.update(t=maintenant, cle=cle, liste=liste)
    q = (requete or "").strip().lower()
    liens = depots_lies(settings)
    sortie = [
        {**d, "projet": liens.get(d["nom"], "")}
        for d in _cache["liste"]
        if not q or q in d["nom"].lower() or q in d["description"].lower()
    ]
    return {"depots": sortie, "total": len(sortie), "tronque": len(_cache["liste"]) >= PAGES_MAX * 100}


# ── Ouvrir un dépôt comme projet ────────────────────────────────────────


def valider_le_nom(nom: str) -> tuple[str, str]:
    """`proprietaire/depot`, ou une erreur. Rien d'autre ne parvient à git."""
    m = NOM_DEPOT.match((nom or "").strip())
    if not m or m.group(2) in (".", "..") or m.group(2).startswith("-") or m.group(2).lower().endswith(".git"):
        raise ErreurGithub("Un dépôt se désigne par « proprietaire/depot » (lettres, chiffres, tirets, points).")
    return m.group(1), m.group(2)


def _slug_libre(settings: AtelierSettings, voulu: str) -> str:
    from mcp_gateway.atelier.commandes import structure

    base = structure.slugifier(voulu) or "depot"
    slug, n = base, 2
    while (settings.projects_dir / slug).exists() or slug == settings.assistant_slug:
        suffixe = f"-{n}"
        slug = base[: 40 - len(suffixe)] + suffixe
        n += 1
    return slug


def cloner(settings: AtelierSettings, nom_complet: str, *, slug: str = "") -> dict[str, Any]:
    """Clone le dépôt dans `projects/<slug>`. Ne crée pas le projet de l'Atelier : l'appelant le fait."""
    proprietaire, nom = valider_le_nom(nom_complet)
    jeton = _jeton(settings)
    info = _get(jeton, f"/repos/{proprietaire}/{nom}")
    if not isinstance(info, dict) or str(info.get("full_name", "")).lower() != f"{proprietaire}/{nom}".lower():
        raise ErreurGithub("GitHub n'a pas rendu ce dépôt.")
    taille = int(info.get("size") or 0)
    if taille > TAILLE_MAX_KO:
        raise ErreurGithub(
            f"Ce dépôt est trop gros pour s'ouvrir d'ici ({taille // 1000} Mo ; au plus {TAILLE_MAX_KO // 1000} Mo)."
        )
    complet = str(info["full_name"])
    slug = _slug_libre(settings, slug or str(info.get("name") or nom))
    destination = settings.projects_dir / slug
    login = git_repos.proprietaire(settings) or "x-access-token"
    env = {
        **os.environ,
        **git_repos.SANS_INVITE,
        "GIT_ASKPASS": str(git_repos._askpass(settings)),  # noqa: SLF001
        "ATELIER_GIT_USER": login,
        "ATELIER_GIT_TOKEN_FILE": str(settings.github_token_path),
    }
    settings.projects_dir.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            ["git", "clone", "--quiet", "--", f"{ADRESSE_DES_DEPOTS}{complet}.git", str(destination)],
            capture_output=True,
            text=True,
            env=env,
            timeout=CLONE_DELAI_S,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ErreurGithub(f"Le clonage n'a pas abouti ({type(exc).__name__}).") from None
    if proc.returncode != 0:
        shutil.rmtree(destination, ignore_errors=True)
        detail = (proc.stderr or "").strip().splitlines()[-1:] or ["raison inconnue"]
        raise ErreurGithub(f"Le clonage a échoué : {detail[0][:200]}")

    marque = destination / ".git" / git_repos.MARQUE_CLONE
    marque.write_text(
        json.dumps({"depot": complet, "branche": str(info.get("default_branch") or "main"), "clone_le": _maintenant()}),
        encoding="utf-8",
    )
    git_repos._identite(settings, destination)  # noqa: SLF001
    git_repos.exclure_localement(destination)
    origine = git_repos._git(destination, "remote", "get-url", "origin", verifier=False)  # noqa: SLF001
    if "@" in origine:  # ne devrait jamais arriver : l'adresse clonée n'a pas d'identifiants
        git_repos._git(destination, "remote", "set-url", "origin", f"{ADRESSE_DES_DEPOTS}{complet}.git", verifier=False)  # noqa: SLF001

    registre = _lire_json(_registre(settings))
    registre[slug] = {
        "depot": complet,
        "branche": str(info.get("default_branch") or "main"),
        "prive": bool(info.get("private")),
        "ecriture": bool((info.get("permissions") or {}).get("push")),
        "clone_le": _maintenant(),
    }
    _ecrire(_registre(settings), json.dumps(registre, ensure_ascii=False, indent=1))
    _cache["t"] = 0.0
    return {"slug": slug, "dossier": str(destination), **registre[slug]}
