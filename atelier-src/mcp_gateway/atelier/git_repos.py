"""Les projets de l'Atelier sont des dépôts git.

Ils ne l'étaient pas. Un projet était un dossier, et le travail d'une session
ne laissait donc aucune trace datée : ni ce qui a changé, ni quand, ni par
rapport à quoi. L'agent de veille, chargé de résumer le travail accompli et
d'en nourrir le savoir commun, n'avait rien à lire — sur treize projets, un
seul portait un `.git`, et c'était un clone amont dont les commits étaient
ceux d'autrui.

Deux niveaux, séparés à dessein :

- **le dépôt local** est créé avec le projet, sans rien demander à personne.
  C'est gratuit, c'est réversible, et c'est ce qui donne sa matière à la
  veille ;
- **la publication sur GitHub** est un geste délibéré, projet par projet.
  Créer un dépôt distant est une action tournée vers l'extérieur : elle ne se
  déclenche pas toute seule parce qu'on a ouvert un projet d'essai.

Le jeton GitHub vit dans `~/work/.secrets/github_token`, en 0600, comme les
autres. Il ne passe ni par l'URL du remote — qu'un `git remote -v` afficherait
à qui la demande, et que tout clone emporterait — ni par la ligne de commande,
où n'importe quel `ps` le lirait. `git` va le chercher lui-même, par un script
`GIT_ASKPASS` qui ne porte que le chemin du coffre.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings

log = logging.getLogger("atelier.git")

# Ce que l'Atelier dépose lui-même dans un projet et qui n'appartient pas à
# l'histoire du travail : état de session, réglages de la machine, réponses
# déjà données. Le reste — CLAUDE.md — dit ce qu'est le projet et se versionne.
#
# `.mcp.json` ne se versionne pas. Il a longtemps été rangé avec CLAUDE.md,
# comme une description du projet ; mais l'Atelier y recopiait les en-têtes
# `Authorization` des connecteurs, et un jeton est parti ainsi sur GitHub. Il
# ne porte plus que des références `${ATELIER_MCP_…}` : l'ignorer est la
# seconde ceinture, pour ce qu'une main y écrirait en clair.
GITIGNORE = """# Écrit par l'Atelier.

# Ce qu'il dépose lui-même : état de session, réglages de la machine.
# Dans .atelier/, seule la déclaration du projet se versionne (projet.json,
# env.json qui ne porte que des références) ; contexte.md se régénère.
.mcp.json
.claude/settings.local.json
.claude/projects/
.atelier/*
!.atelier/projet.json
!.atelier/env.json
.wikichat/
.vscode/

# Ce qui ne doit jamais partir. Un projet du pod porte souvent un .env
# d'amorçage — on en a trouvé un qui disait « ne pas committer » sur sa
# première ligne, et qui l'a été.
.env
.env.*
!.env.example
*.pem
*.key
*_token
*_secret
.secrets/
credentials*

node_modules/
__pycache__/
*.pyc
"""

# Ce qu'un dépôt ne doit pas emporter vers l'extérieur. Le .gitignore protège
# ce qui n'est pas encore suivi ; ceci rattrape ce qui l'était déjà — un
# fichier ajouté avant que la règle existe reste suivi malgré elle.
NOMS_SENSIBLES = (
    ".env",
    ".pem",
    ".key",
    "_token",
    "_secret",
    "credentials",
    "id_rsa",
)


BRANCHE = "main"
API_GITHUB = "https://api.github.com"
# Un push qui attend un mot de passe sur un terminal absent ne rend jamais la
# main. Le harnais tourne sans terminal : on coupe court plutôt que pendre.
SANS_INVITE = {"GIT_TERMINAL_PROMPT": "0", "GIT_PAGER": "cat"}


class ErreurDepot(RuntimeError):
    """Une opération git ou GitHub qui n'a pas abouti, avec de quoi le dire."""


@dataclass
class EtatDepot:
    """Ce qu'on peut dire d'un projet sans rien y modifier."""

    depot: bool = False
    branche: str = ""
    commits: int = 0
    en_attente: int = 0
    distant: str = ""
    # `.mcp.json` suivi malgré le .gitignore : il l'était avant la règle.
    # L'Atelier ne le dé-suit pas lui-même — c'est l'histoire de la personne —
    # mais le dit, pour qu'elle décide.
    mcp_json_suivi: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "repo": self.depot,
            "branch": self.branche,
            "commits": self.commits,
            "pending": self.en_attente,
            "remote": self.distant,
            "mcp_json_tracked": self.mcp_json_suivi,
        }


def _git(
    chemin: Path, *args: str, plus: dict[str, str] | None = None, verifier: bool = True
) -> str:
    """Lance git dans un dossier, et rend sa sortie.

    Rien ne peut demander à l'écran : le harnais tourne sans terminal, et une
    invite y attendrait pour toujours. Ce qui échoue échoue tout de suite.
    """
    env = {**os.environ, **SANS_INVITE, **(plus or {})}
    proc = subprocess.run(
        ["git", "-C", str(chemin), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if verifier and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise ErreurDepot(f"git {' '.join(args[:2])} : {detail[-400:]}")
    return (proc.stdout or "").strip()


def _identite(settings: AtelierSettings, chemin: Path) -> None:
    """Pose l'identité des commits sur ce dépôt, et sur lui seul — si la
    machine n'en a pas.

    Locale et non globale : le pod porte d'autres dépôts, dont un clone amont
    qui traîne déjà une adresse d'emprunt. On ne réécrit pas la machine pour
    configurer un projet.

    Et l'inverse : quand la machine porte une identité, c'est la vraie —
    celle de la personne. Quatorze projets signaient « Atelier
    <atelier@localhost> » parce que notre réglage local recouvrait tout ;
    on ne pose le nôtre que faute de mieux, et on retire celui qu'on avait
    posé dès qu'une identité globale existe.

    Clé par clé : une machine qui ne donne que le courriel n'a pas de nom, et
    git refuse alors de signer (« empty ident name ») là où l'utilisateur n'a
    pas de nom complet dans le système — un conteneur Linux, typiquement. On
    complète donc ce qui manque sans recouvrir ce que la personne a donné.
    """
    for cle, defaut in (
        ("user.name", settings.git_user_name),
        ("user.email", settings.git_user_email),
    ):
        if _git(chemin, "config", "--global", "--get", cle, verifier=False):
            if _git(chemin, "config", "--local", "--get", cle, verifier=False) == defaut:
                _git(chemin, "config", "--local", "--unset", cle, verifier=False)
        else:
            _git(chemin, "config", cle, defaut)


# Les lignes du .gitignore que l'Atelier doit à ses propres dépôts : un
# fichier écrit avant qu'une ligne existe ne la connaît pas, et un agent qui
# « commite tout » emporte alors ce qu'on dépose — `.vscode/` l'a été.
LIGNES_DE_L_ATELIER = (
    ".mcp.json",
    ".claude/settings.local.json",
    ".claude/projects/",
    ".atelier/*",
    "!.atelier/projet.json",
    "!.atelier/env.json",
    ".wikichat/",
    ".vscode/",
)

# Un .gitignore d'avant la structure type ignore `.atelier/` en entier. Git ne
# ré-inclut rien sous un dossier exclu : y ajouter les exceptions ne servirait
# à rien, et doublerait la règle. Ces projets-là se migrent (vague 2).
_EQUIVALENTS_ANCIENS = {
    ".atelier/*": ".atelier/",
    "!.atelier/projet.json": ".atelier/",
    "!.atelier/env.json": ".atelier/",
}


def completer_le_gitignore(chemin: Path) -> list[str]:
    """Ajoute au .gitignore les dépôts de l'Atelier qui y manquent.

    N'écrit rien d'autre : le reste du fichier appartient au projet. Rend
    les lignes ajoutées, pour le dire.
    """
    gitignore = chemin / ".gitignore"
    if not gitignore.is_file():
        gitignore.write_text(GITIGNORE, encoding="utf-8")
        return list(LIGNES_DE_L_ATELIER)
    contenu = gitignore.read_text(encoding="utf-8")
    presentes = {l.strip() for l in contenu.splitlines()}
    manquantes = [
        l
        for l in LIGNES_DE_L_ATELIER
        if l not in presentes and _EQUIVALENTS_ANCIENS.get(l) not in presentes
    ]
    if not manquantes:
        return []
    ajout = "" if contenu.endswith(chr(10)) or not contenu else chr(10)
    ajout += "# Déposé par l'Atelier, à ne pas versionner." + chr(10)
    ajout += chr(10).join(manquantes) + chr(10)
    gitignore.write_text(contenu + ajout, encoding="utf-8")
    return manquantes


def etat(chemin: Path) -> EtatDepot:
    """L'état du dépôt d'un projet — sans jamais échouer sur son absence."""
    if not (chemin / ".git").is_dir():
        return EtatDepot()
    try:
        branche = _git(chemin, "rev-parse", "--abbrev-ref", "HEAD")
        commits = int(_git(chemin, "rev-list", "--count", "HEAD", verifier=False) or 0)
        modifies = _git(chemin, "status", "--porcelain", verifier=False)
        distant = _git(chemin, "remote", "get-url", "origin", verifier=False)
    except (ErreurDepot, ValueError, OSError, subprocess.SubprocessError):
        return EtatDepot(depot=True, mcp_json_suivi=mcp_json_suivi(chemin))
    return EtatDepot(
        depot=True,
        branche=branche,
        commits=commits,
        en_attente=len([l for l in modifies.split("\n") if l.strip()]),
        # L'URL peut porter un jeton si elle a été posée à la main ailleurs :
        # on ne rend que l'adresse, jamais ce qui la précède.
        distant=_url_sans_secret(distant),
        mcp_json_suivi=mcp_json_suivi(chemin),
    )


def mcp_json_suivi(chemin: Path) -> bool:
    """Vrai si le dépôt suit `.mcp.json`, que le .gitignore n'y peut plus rien."""
    if not (chemin / ".git").is_dir():
        return False
    try:
        return bool(_git(chemin, "ls-files", "--", ".mcp.json", verifier=False))
    except (OSError, subprocess.SubprocessError):
        return False


def _url_sans_secret(url: str) -> str:
    if "@" in url and "//" in url:
        schema, reste = url.split("//", 1)
        return schema + "//" + reste.split("@", 1)[1]
    return url


def _sensibles(chemins: list[str]) -> list[str]:
    """Trie une liste de chemins : ne garde que ce qui annonce un secret.

    `.env.example` et consorts sont là pour être lus : ce sont des modèles,
    ils ne portent rien.
    """
    vus: list[str] = []
    for f in chemins:
        f = f.strip()
        if not f or f in vus:
            continue
        if f.endswith((".example", ".sample", ".template", ".dist")):
            continue
        if any(motif in f.lower() for motif in NOMS_SENSIBLES):
            vus.append(f)
    return vus


def fichiers_sensibles_suivis(chemin: Path) -> list[str]:
    """Ce que le dépôt suit aujourd'hui et qui annonce un secret."""
    return _sensibles(_git(chemin, "ls-files", verifier=False).split(chr(10)))


def fichiers_sensibles_dans_l_histoire(chemin: Path) -> list[str]:
    """Ce que le dépôt a suivi un jour, même s'il ne le suit plus.

    Retirer un fichier du suivi ne le retire pas du passé : le commit qui l'a
    introduit le contient toujours, et c'est ce passé que `git push` emporte.
    Un secret retiré la veille part quand même. C'est cette liste-là qui doit
    décider d'une publication, pas l'état du jour.
    """
    trace = _git(
        chemin,
        "log",
        "--all",
        "--pretty=format:",
        "--name-only",
        "--diff-filter=A",
        verifier=False,
    )
    return _sensibles(trace.split(chr(10)))


def initialiser(
    settings: AtelierSettings, chemin: Path, message: str = "Ouvrir le projet"
) -> EtatDepot:
    """Fait du dossier un dépôt, s'il n'en est pas déjà un.

    Idempotent : rappelée sur un projet déjà versionné, elle ne touche à rien
    et rend son état. C'est ce qui permet de l'appeler à chaque création sans
    se demander si le projet existait avant.
    """
    chemin.mkdir(parents=True, exist_ok=True)
    if (chemin / ".git").is_dir():
        return etat(chemin)

    _git(chemin, "init", "-b", BRANCHE)
    _identite(settings, chemin)
    completer_le_gitignore(chemin)

    # Un dépôt sans commit n'a pas de branche : `rev-parse HEAD` échoue, et la
    # veille ne trouve rien à lire. Le premier commit fait exister l'histoire,
    # même si le projet est encore vide.
    _git(chemin, "add", "-A")
    if _git(chemin, "status", "--porcelain", verifier=False):
        _git(chemin, "commit", "-m", message, "--no-verify")
    else:
        _git(chemin, "commit", "--allow-empty", "-m", message, "--no-verify")
    log.info("dépôt initialisé : %s", chemin)
    return etat(chemin)


def enregistrer(settings: AtelierSettings, chemin: Path, message: str) -> EtatDepot:
    """Fige l'état du projet. Sans rien à figer, ne fait rien."""
    if not (chemin / ".git").is_dir():
        initialiser(settings, chemin)
    _identite(settings, chemin)
    completer_le_gitignore(chemin)
    _git(chemin, "add", "-A")
    if not _git(chemin, "status", "--porcelain", verifier=False):
        return etat(chemin)
    _git(chemin, "commit", "-m", message.strip() or "Enregistrer le travail", "--no-verify")
    return etat(chemin)


def enregistrer_fichiers(
    settings: AtelierSettings, chemin: Path, fichiers: list[str], message: str
) -> str:
    """Commite ces fichiers-là, et eux seuls. Rend l'empreinte du commit, ou "".

    Pour les commandes de l'Atelier qui touchent un fichier suivi (`projet.json`) :
    `enregistrer` prend tout (`add -A`) et emporterait le travail en cours d'un
    agent dans un commit qui n'est pas le sien. Ici, le reste de l'arbre n'est
    ni ajouté ni commité.
    """
    if not (chemin / ".git").is_dir() or not fichiers:
        return ""
    _identite(settings, chemin)
    _git(chemin, "add", "--", *fichiers)
    if not _git(chemin, "diff", "--cached", "--name-only", "--", *fichiers, verifier=False):
        return ""
    _git(chemin, "commit", "-m", message, "--no-verify", "--only", "--", *fichiers)
    return _git(chemin, "rev-parse", "HEAD", verifier=False)


def dernier_commit(chemin: Path) -> dict[str, str]:
    """L'empreinte et le message du dernier commit : une preuve lisible."""
    if not (chemin / ".git").is_dir():
        return {}
    brut = _git(chemin, "log", "-1", "--pretty=format:%H%x1f%s", verifier=False)
    separateur = chr(31)
    if separateur not in brut:
        return {}
    empreinte, sujet = brut.split(separateur, 1)
    return {"commit": empreinte, "message": sujet}


# --- GitHub : le geste délibéré ------------------------------------------


def _jeton(settings: AtelierSettings) -> str:
    try:
        return settings.github_token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def publication_possible(settings: AtelierSettings) -> bool:
    """Y a-t-il de quoi publier ? L'interface le demande avant de proposer."""
    return bool(_jeton(settings) and settings.github_owner.strip())


def _appel_github(settings: AtelierSettings, methode: str, route: str, corps: dict | None = None):
    jeton = _jeton(settings)
    if not jeton:
        raise ErreurDepot("aucun jeton GitHub dans ~/work/.secrets/github_token")
    requete = urllib.request.Request(
        API_GITHUB + route,
        method=methode,
        data=json.dumps(corps).encode("utf-8") if corps is not None else None,
        headers={
            "Authorization": f"Bearer {jeton}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
            "User-Agent": "atelier",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=30) as reponse:
            return json.loads(reponse.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise ErreurDepot(f"GitHub {exc.code} : {detail}") from exc
    except OSError as exc:
        raise ErreurDepot(f"GitHub injoignable : {exc}") from exc


def _proprietaire_est_une_organisation(settings: AtelierSettings) -> bool:
    compte = _appel_github(settings, "GET", f"/users/{settings.github_owner.strip()}")
    return str(compte.get("type") or "").lower() == "organization"


def publier(
    settings: AtelierSettings,
    chemin: Path,
    nom: str,
    *,
    description: str = "",
    prive: bool = True,
) -> EtatDepot:
    """Crée le dépôt distant s'il manque, le relie, et pousse la branche.

    Privé par défaut. Un projet ouvert dans l'Atelier n'a pas vocation à
    devenir public parce qu'on a cliqué : ouvrir est un geste de travail,
    publier en est un autre, et c'est celui-là qui ne se rattrape pas.
    """
    proprietaire = settings.github_owner.strip()
    if not proprietaire:
        raise ErreurDepot("aucun propriétaire GitHub configuré (ATELIER_GITHUB_OWNER)")
    if not (chemin / ".git").is_dir():
        initialiser(settings, chemin)

    # Dernière barrière avant l'extérieur. On regarde l'histoire, pas
    # l'état du jour : un secret retiré du suivi hier est toujours dans le
    # commit qui l'a introduit, et c'est l'histoire que `push` emporte. Une
    # fois poussé, il est public même effacé ensuite — les miroirs le
    # gardent.
    sensibles = fichiers_sensibles_dans_l_histoire(chemin)
    if sensibles:
        raise ErreurDepot(
            "publication refusée : ces fichiers annoncent un secret et sont "
            "dans l'histoire du dépôt — " + ", ".join(sensibles[:5])
            + ". Les retirer du suivi ne suffit pas : le commit qui les a "
            "introduits part avec le reste. Il faut réécrire l'histoire avant "
            "de publier."
        )

    route = (
        f"/orgs/{proprietaire}/repos"
        if _proprietaire_est_une_organisation(settings)
        else "/user/repos"
    )
    try:
        _appel_github(
            settings,
            "POST",
            route,
            {"name": nom, "description": description[:350], "private": bool(prive)},
        )
        log.info("dépôt GitHub créé : %s/%s", proprietaire, nom)
    except ErreurDepot as exc:
        # Un dépôt qui existe déjà n'est pas une erreur : c'est le cas d'une
        # seconde publication. Tout le reste en est une.
        if "already exists" not in str(exc) and "name already" not in str(exc):
            raise

    url = f"https://github.com/{proprietaire}/{nom}.git"
    if _git(chemin, "remote", "get-url", "origin", verifier=False):
        _git(chemin, "remote", "set-url", "origin", url)
    else:
        _git(chemin, "remote", "add", "origin", url)

    _pousser(settings, chemin)
    return etat(chemin)



# Le script par lequel git demande de quoi s'authentifier. Il ne porte aucun
# secret : seulement où le lire. Même principe qu'`apiKeyHelper` pour la clé
# du modèle.
ASKPASS = """#!/bin/sh
# Ecrit par l'Atelier. Ne porte aucun secret : seulement ou le lire.
case "$1" in
  *[Uu]sername*) printf '%s' "$ATELIER_GIT_USER" ;;
  *) cat "$ATELIER_GIT_TOKEN_FILE" ;;
esac
"""


def _askpass(settings: AtelierSettings) -> Path:
    """Pose le script d'authentification, et rend son chemin.

    Ni jeton dans l'URL du remote — elle est écrite dans `.git/config`, elle
    ressort au premier `git remote -v`, et tout ce qui clone l'emporte — ni
    jeton sur la ligne de commande, où n'importe quel `ps` le lirait.
    """
    chemin = settings.secrets_dir / "atelier-git-askpass.sh"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    if not chemin.is_file() or chemin.read_text(encoding="utf-8") != ASKPASS:
        chemin.write_text(ASKPASS, encoding="utf-8")
    chemin.chmod(0o700)
    return chemin


def _pousser(settings: AtelierSettings, chemin: Path) -> None:
    """Pousse la branche courante, sans laisser le jeton derrière soi."""
    if not _jeton(settings):
        raise ErreurDepot("aucun jeton GitHub dans ~/work/.secrets/github_token")
    _git(
        chemin,
        "push",
        "-u",
        "origin",
        "HEAD",
        plus={
            "GIT_ASKPASS": str(_askpass(settings)),
            "ATELIER_GIT_USER": settings.github_owner.strip(),
            "ATELIER_GIT_TOKEN_FILE": str(settings.github_token_path),
        },
    )
