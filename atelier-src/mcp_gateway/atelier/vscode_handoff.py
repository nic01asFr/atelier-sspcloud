"""Handoff VS Code : extension Claude Code + session courante."""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from mcp_gateway.atelier.config import (
    MODELE_PRINCIPAL,
    MODELES_ECARTES,
    OBSOLETES,
    AtelierSettings,
    effort_accepte_partout,
    fenetre_minimale,
)
from mcp_gateway.atelier.claude_home import donnees_code_server
from mcp_gateway.atelier.claude_home import sync_claude_home as sync_claude_home_store

log = logging.getLogger("atelier.vscode_handoff")

CLAUDE_CODE_EXTENSION_ID = "anthropic.claude-code"

# Layout par défaut : Claude Code sidebar, sans Welcome ni Copilot Chat.
WORKBENCH_LAYOUT_SETTINGS: dict[str, object] = {
    "workbench.startupEditor": "none",
    "workbench.secondarySideBar.defaultVisibility": "hidden",
    "chat.disableAIFeatures": True,
    "workbench.welcomePage.walkthroughs.openOnInstall": False,
    "extensions.ignoreRecommendations": True,
    # Le pod expose des services sur des ports que VS Code découvre seul, et
    # il annonce chacun d'eux par une bulle au-dessus de la conversation. Le
    # suivi reste utile ; c'est l'annonce qui gêne, en plein milieu de ce
    # qu'on lisait.
    "remote.otherPortsAttributes": {"onAutoForward": "silent"},
}


def _read_llm_key(settings: AtelierSettings) -> str:
    path = settings.llm_key_path
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def base_url_des_surfaces(settings: AtelierSettings) -> str:
    """L'adresse du modèle pour VS Code, le terminal et wikichat : le relais.

    Ces surfaces lisent un fichier écrit d'avance ; elles ne peuvent pas se
    rabattre sur la passerelle au moment où le relais manquerait. L'Atelier
    le relance au démarrage, l'init du pod aussi. Relais désactivé
    (`ATELIER_RELAIS_LLM=0`) : la passerelle directement, sans compaction
    native.
    """
    if settings.relais_llm:
        from mcp_gateway.atelier.relais_llm import adresse_du_relais

        return adresse_du_relais(settings)
    return settings.anthropic_base_url.strip()


# L'enveloppeur du processus `claude` de l'extension (`bin/atelier-claude-vscode`) :
# il source `~/work/.secrets/claude-env.sh` puis `exec "$@"`. Le réglage est de
# portée machine dans le manifeste de l'extension (relevé en 2.1.280, 2.1.281 et
# 2.1.282) ; l'extension le lance avec, pour arguments, son binaire `claude`
# puis ceux du CLI.
ENVELOPPEUR = "atelier-claude-vscode"
CLE_ENVELOPPEUR = "claudeCode.claudeProcessWrapper"
CLE_ENVIRONNEMENT = "claudeCode.environmentVariables"
_SOURCE_ENVELOPPEUR = Path(__file__).resolve().parents[2] / "bin" / ENVELOPPEUR


def enveloppeur_vscode(settings: AtelierSettings) -> Path:
    """L'enveloppeur, là où `atelier-init.sh` le pose : `~/work/bin/atelier-claude-vscode`."""
    return settings.work_dir / "bin" / ENVELOPPEUR


def assurer_l_enveloppeur(settings: AtelierSettings) -> Path | None:
    """Pose (ou remet à jour) l'enveloppeur dans `~/work/bin`, et le rend.

    L'init le copie aussi ; l'Atelier le fait de son côté parce qu'un
    déploiement peut se limiter à mettre le code à jour et à relancer le
    service. Sans enveloppeur, le réglage désignerait un fichier absent et
    l'extension ne lancerait plus rien : on rend alors None, et le réglage
    n'est pas posé.
    """
    cible = enveloppeur_vscode(settings)
    try:
        if _SOURCE_ENVELOPPEUR.is_file():
            contenu = _SOURCE_ENVELOPPEUR.read_bytes()
            if not cible.is_file() or cible.read_bytes() != contenu:
                cible.parent.mkdir(parents=True, exist_ok=True)
                temporaire = cible.with_name(cible.name + ".nouveau")
                temporaire.write_bytes(contenu)
                temporaire.chmod(0o755)
                temporaire.replace(cible)
    except OSError as exc:
        log.warning("enveloppeur VS Code non posé : %s", exc)
    return cible if cible.is_file() else None


def claude_extension_env(settings: AtelierSettings) -> list[dict[str, str]]:
    """Ce que les réglages de code-server donnent au `claude` de l'extension.

    Aucun secret : les valeurs des références `${ATELIER_MCP_…}` (clé de
    l'Atelier, secrets des connecteurs, variables des projets) viennent du
    fichier d'environnement unique, que l'enveloppeur source au lancement
    (`claudeCode.claudeProcessWrapper`). Elles étaient recopiées ici, donc en
    clair dans les réglages de code-server. La clé du modèle, elle, passe par
    `apiKeyHelper`.
    """
    env: list[dict[str, str]] = [
        {"name": "ANTHROPIC_BASE_URL", "value": base_url_des_surfaces(settings)},
    ]
    model = (settings.default_model or "").strip()
    if model:
        env.append({"name": "ANTHROPIC_MODEL", "value": model})
    return env


def environnement_du_claude_vscode(settings: AtelierSettings) -> dict[str, str]:
    """L'environnement que reçoit réellement le `claude` de l'extension.

    Celui des réglages, puis ce que l'enveloppeur y ajoute en sourçant le
    fichier unique (ses valeurs l'emportent : elles sont chargées après). Sert
    à la comparaison des surfaces (`coherence`).
    """
    from mcp_gateway.atelier.env_secrets import (
        chemin_du_fichier,
        ecrire_le_fichier,
        lire_le_fichier,
    )

    env = {e["name"]: e["value"] for e in claude_extension_env(settings)}
    ecrire_le_fichier(settings)
    env.update(lire_le_fichier(chemin_du_fichier(settings)))
    return env


def _sans_valeurs_secretes(
    entrees: object, settings: AtelierSettings
) -> list[dict[str, str]] | None:
    """Une liste `environmentVariables` d'où sont retirées les variables du fichier unique."""
    if not isinstance(entrees, list):
        return None
    from mcp_gateway.atelier.env_secrets import chemin_du_fichier, lire_le_fichier

    noms = set(lire_le_fichier(chemin_du_fichier(settings)))
    return [
        e
        for e in entrees
        if isinstance(e, dict)
        and not str(e.get("name", "")).startswith("ATELIER_MCP_")
        and e.get("name") not in noms
    ]


def _ecarter_les_modeles_casses(data: dict[str, object], env: dict) -> None:
    """Retire des créneaux et des replis les modèles qui font tomber un tour.

    Un pod installé avant garde `gemma4-26b-moe` au créneau opus et dans
    `fallbackModel` : l'init n'écrase pas un fichier existant. Le créneau
    reprend le modèle principal ; le repli est simplement retiré.
    """
    for cle in (
        "ANTHROPIC_MODEL",
        "ANTHROPIC_DEFAULT_MODEL",
        "ANTHROPIC_DEFAULT_SONNET_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    ):
        if str(env.get(cle) or "").strip() in MODELES_ECARTES:
            env[cle] = MODELE_PRINCIPAL
    if str(data.get("model") or "").strip() in MODELES_ECARTES:
        data["model"] = MODELE_PRINCIPAL
    replis = data.get("fallbackModel")
    if isinstance(replis, list):
        gardes = [m for m in replis if str(m).strip() not in MODELES_ECARTES]
        if gardes:
            data["fallbackModel"] = gardes
        else:
            data.pop("fallbackModel", None)
    elif isinstance(replis, str) and replis.strip() in MODELES_ECARTES:
        data.pop("fallbackModel", None)


def _merge_claude_settings_file(path: Path, settings: AtelierSettings) -> None:
    """Donne au CLI de quoi s'authentifier, sans y écrire le secret.

    Ce fichier portait la clé du modèle en clair. Or n'importe quelle session
    Claude Code peut le lire — c'est même une lecture banale quand on demande
    à un agent d'inspecter sa configuration — et la clé se retrouve alors dans
    son transcript, puis partout où ce transcript est relu. C'est arrivé.

    Le CLI accepte `apiKeyHelper` : une commande dont il lit la sortie. Le
    fichier ne porte donc plus qu'un `cat` du fichier de secrets, resté en
    0600. Le secret ne quitte pas `~/work/.secrets`.
    """
    # On vérifie que le coffre existe, sans en lire le contenu : la valeur
    # ne sert plus à rien ici, et ne pas la charger est le plus sûr moyen
    # qu'elle ne réapparaisse pas dans le fichier.
    if not settings.llm_key_path.is_file():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, object] = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    env = data.setdefault("env", {})
    if not isinstance(env, dict):
        env = {}
        data["env"] = env
    env["ANTHROPIC_BASE_URL"] = base_url_des_surfaces(settings)
    # Les clés déjà écrites en clair sont retirées, pas seulement remplacées :
    # un fichier existant garderait sinon l'ancienne indéfiniment.
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ANTHROPIC_AUTH_TOKEN", None)
    data["apiKeyHelper"] = f"cat {settings.llm_key_path}"
    # Le plafond de sortie compte dans la fenêtre du modèle. Trop haut, il ne
    # laisse pas la place de compacter — et une conversation qui ne peut plus
    # être compactée ne peut plus rien recevoir.
    if settings.max_output_tokens > 0:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(settings.max_output_tokens)
    model = (settings.default_model or "").strip()
    if model:
        env["ANTHROPIC_MODEL"] = model
        env.setdefault("ANTHROPIC_DEFAULT_MODEL", model)
    # La compaction native du CLI, sur la vraie fenêtre du modèle. Le relais
    # LLM lui rend le décompte que la passerelle mettait à zéro : elle se
    # déclenche d'elle-même, dans VS Code et au terminal comme dans nos tours.
    # Ces surfaces ne savent pas d'avance quel modèle servira : elles
    # reçoivent la plus petite fenêtre de la table.
    #
    # Les anciens réglages — fenêtre de compaction à 30 000, plafond à
    # 40 000, levée du contrôle de fenêtre — compensaient un décompte nul.
    # Laissés, ils feraient compacter à contretemps : on les retire.
    data["autoCompactEnabled"] = True
    data.pop("autoCompactWindow", None)
    for ancien in OBSOLETES:
        env.pop(ancien, None)
    env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(fenetre_minimale())
    # L'effort, pour tout ce qui lance `claude` sans passer par nos tours :
    # l'extension VS Code, le terminal, les agents de wikichat. Notre harnais
    # le fixait pour lui seul ; le 16 septembre, les erreurs « Unexpected
    # reasoning effort high » sont tombées dans VS Code, au bout d'une chaîne
    # de replis. Un choix déjà fait est gardé s'il passe partout, relevé à
    # `xhigh` s'il visait plus haut ; sinon, celui du service.
    _ecarter_les_modeles_casses(data, env)
    niveau = effort_accepte_partout(data.get("effortLevel") or settings.effort)
    data["effortLevel"] = niveau
    env["CLAUDE_CODE_EFFORT_LEVEL"] = niveau
    _retirer_l_effort_par_modele(data)
    # WebSearch simule une recherche sur cette passerelle : refusé pour toutes
    # les surfaces qui lisent ce fichier (voir `navigateur`).
    from mcp_gateway.atelier.navigateur import refuser_les_outils_simules

    data = refuser_les_outils_simules(data, settings)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _retirer_l_effort_par_modele(data: dict[str, object]) -> None:
    """Retire `modelSettings.<modèle>.effortLevel` : l'effort n'a qu'une source.

    Mesuré sur le pod le 25/09 (`docs/vision/mesures-vague1.md`) :
    `CLAUDE_CODE_EFFORT_LEVEL` l'emporte sur `modelSettings` et sur `--effort`
    (39 requêtes sur 39 en `medium` malgré un `xhigh` par modèle), et `xhigh`
    n'apporte rien de mieux. Laissé, ce réglage fait croire à un effort qui
    n'est jamais appliqué. Le reste de `modelSettings` n'est pas touché ; une
    entrée vidée disparaît, et la clé avec elle si plus rien n'y reste.
    """
    par_modele = data.get("modelSettings")
    if not isinstance(par_modele, dict):
        return
    for modele in list(par_modele):
        reglages = par_modele[modele]
        if isinstance(reglages, dict) and "effortLevel" in reglages:
            reglages.pop("effortLevel", None)
            if not reglages:
                par_modele.pop(modele, None)
    if not par_modele:
        data.pop("modelSettings", None)


def write_claude_settings_env(settings: AtelierSettings) -> None:
    """~/.claude + PVC durable : source d'auth pour l'extension (évite le login Claude.ai).

    Un seul fichier physique, celui du volume, dont `~/.claude/settings.json`
    est un lien (`claude_home.unifier_les_reglages`, qui y fusionne d'abord un
    vrai fichier trouvé à la place du lien). On y fusionne nos clés ; tout ce
    que l'Atelier ne pose pas lui-même (hooks de wikichat, permissions, choix
    de la personne) reste tel quel. Deux copies fusionnées chacune de son côté,
    puis recopiées l'une sur l'autre, faisaient perdre les hooks que wikichat
    venait de poser.
    """
    from mcp_gateway.atelier.claude_home import unifier_les_reglages

    if not settings.llm_key_path.is_file():
        return
    physique = unifier_les_reglages(settings)
    _merge_claude_settings_file(physique, settings)
    home = Path.home() / ".claude" / "settings.json"
    if not home.is_symlink():
        # Pas de lien possible (Windows sans privilège) : la même chose des deux côtés.
        home.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(physique, home)


def sync_claude_home(settings: AtelierSettings, slug: str) -> None:
    """PVC durable ↔ $HOME/.claude, pour la reprise par le CLI et l'extension.

    Rien du projet n'y passe. Le `.claude/settings.json` d'un projet était
    recopié sur `~/.claude/settings.json` : le réglage global — modèle,
    `apiKeyHelper`, crochets, adresse du relais — devenait celui du dernier
    projet ouvert, pour toutes les surfaces et tous les projets. Claude Code
    lit de lui-même le `.claude/settings.json` du dossier où il tourne ; il
    n'y a rien à copier.
    """
    del slug
    sync_claude_home_store(settings)


def _titre_du_projet(settings: AtelierSettings, slug: str) -> str:
    """Le nom que l'Atelier donne au projet, ou son identifiant a defaut."""
    from mcp_gateway.atelier.projects import ProjectStore

    try:
        for projet in ProjectStore(settings).list_projects(include_archived=True):
            if projet.slug == slug:
                return (projet.title or "").strip() or slug
    except OSError:
        pass
    return slug


# Ce que l'extension VS Code sait des modes : les quatre de l'Atelier, plus
# `manual`, qu'elle tient pour l'autre nom de `default` (relevé dans son
# manifeste, 2.1.282). Gardé pour les appelants d'avant.
MODES_VERS_EXTENSION = {
    "plan": "plan",
    "default": "default",
    "manual": "default",
    "acceptEdits": "acceptEdits",
    "bypassPermissions": "bypassPermissions",
}


def mode_pour_extension(mode: str | None) -> str:
    """Le nom que l'extension comprend pour ce mode, ou rien."""
    return MODES_VERS_EXTENSION.get((mode or "").strip(), "")


def write_vscode_workspace_config(
    settings: AtelierSettings, slug: str, cwd: Path | None = None, mode_permission: str = ""
) -> None:
    del mode_permission  # le mode vit ailleurs : voir `modes_permission`
    vscode_dir = (cwd or settings.projects_dir / slug) / ".vscode"
    vscode_dir.mkdir(parents=True, exist_ok=True)
    cfg = {
        **WORKBENCH_LAYOUT_SETTINGS,
        "claudeCode.disableLoginPrompt": True,
        "claudeCode.preferredLocation": "sidebar",
        "claudeCode.hideOnboarding": True,
        CLE_ENVIRONNEMENT: claude_extension_env(settings),
        "security.workspace.trust.enabled": False,
        "task.allowAutomaticTasks": "on",
        # VS Code nomme la fenetre d'apres le dossier, donc d'apres
        # l'identifiant technique du projet. On lui dicte le nom que l'Atelier
        # affiche : la fenetre, c'est le projet, et plusieurs conversations y
        # tiennent — leur nom se lit sur leur onglet, pas au-dessus.
        "window.title": _titre_du_projet(settings, slug),
    }
    (vscode_dir / "settings.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    (vscode_dir / "extensions.json").write_text(
        json.dumps({"recommendations": [CLAUDE_CODE_EXTENSION_ID]}, indent=2) + "\n",
        encoding="utf-8",
    )


CLE_MODE_EXTENSION = "claudeCode.initialPermissionMode"


def ecrire_mode_machine(settings: AtelierSettings, mode_permission: str = "") -> str:
    """Range les modes au démarrage : plus de mode imposé par un réglage machine.

    Avant, le mode de la dernière conversation ouverte dans VS Code était
    écrit dans `claudeCode.initialPermissionMode`, de portée machine, avec
    `claudeCode.allowDangerouslySkipPermissions` : toutes les conversations
    neuves partaient ainsi, et `--allow-dangerously-skip-permissions` était
    passé à chaque lancement (audit M1). Désormais :

    - le choix d'une conversation vit dans le magasin de l'extension, le
      défaut d'un projet dans son `.claude/settings.local.json`
      (`modes_permission`) ;
    - `initialPermissionMode` est retiré, et `allowDangerouslySkipPermissions`
      n'est posé que tant qu'un choix demande `bypassPermissions` ;
    - les anciens choix sont rangés une fois (`nettoyer_les_residus`).

    Rend `""` : aucun mode n'est plus écrit au niveau machine.
    """
    del mode_permission
    from mcp_gateway.atelier.modes_permission import nettoyer_les_residus

    nettoyer_les_residus(settings)
    return ""


def write_user_code_server_settings(settings: AtelierSettings) -> None:
    """Réglages utilisateur de code-server, et l'enveloppeur du processus `claude`.

    Les valeurs secrètes n'y sont plus : l'enveloppeur les charge au lancement
    depuis `~/work/.secrets/claude-env.sh`, régénéré ici. Le réglage de
    l'enveloppeur est de portée machine : il est écrit dans les réglages
    utilisateur et dans ceux de la machine, où l'on a déjà mesuré qu'un réglage
    de cette portée était lu (`ecrire_mode_machine`).
    """
    from mcp_gateway.atelier.env_secrets import ecrire_le_fichier

    ecrire_le_fichier(settings)
    enveloppeur = assurer_l_enveloppeur(settings)
    user_dir = donnees_code_server() / "User"
    user_dir.mkdir(parents=True, exist_ok=True)
    cfg: dict[str, object] = {
        **WORKBENCH_LAYOUT_SETTINGS,
        "claudeCode.disableLoginPrompt": True,
        "claudeCode.preferredLocation": "sidebar",
        "claudeCode.hideOnboarding": True,
        CLE_ENVIRONNEMENT: claude_extension_env(settings),
        "security.workspace.trust.enabled": False,
        "task.allowAutomaticTasks": "on",
    }
    if enveloppeur is not None:
        cfg[CLE_ENVELOPPEUR] = str(enveloppeur)
    else:
        log.warning(
            "pas d'enveloppeur %s : l'extension VS Code lancera claude sans les"
            " valeurs de claude-env.sh (connecteurs à secret indisponibles)",
            enveloppeur_vscode(settings),
        )
    (user_dir / "settings.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    ecrire_enveloppeur_machine(settings, enveloppeur)


def ecrire_enveloppeur_machine(settings: AtelierSettings, enveloppeur: Path | None) -> None:
    """Pose l'enveloppeur dans les réglages machine, et en retire les secrets.

    Le reste du fichier est gardé ; les réglages de mode sont remis à ce que
    demandent les choix (`modes_permission.ecrire_les_reglages_machine`).
    Une liste `environmentVariables` qui y porterait des valeurs du fichier
    unique en est purgée.
    """
    fichier = donnees_code_server() / "Machine" / "settings.json"
    donnees: dict[str, object] = {}
    if fichier.is_file():
        try:
            lu = json.loads(fichier.read_text(encoding="utf-8"))
            donnees = lu if isinstance(lu, dict) else {}
        except (json.JSONDecodeError, OSError):
            donnees = {}
    avant = json.dumps(donnees, sort_keys=True)
    if enveloppeur is not None:
        donnees[CLE_ENVELOPPEUR] = str(enveloppeur)
    else:
        donnees.pop(CLE_ENVELOPPEUR, None)
    purge = _sans_valeurs_secretes(donnees.get(CLE_ENVIRONNEMENT), settings)
    if purge is not None:
        donnees[CLE_ENVIRONNEMENT] = purge
    if not (fichier.is_file() and json.dumps(donnees, sort_keys=True) == avant):
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(donnees, indent=2) + chr(10), encoding="utf-8")
    # Et les réglages de mode : ni mode initial imposé, ni bypass permis sans
    # qu'un choix le demande (`modes_permission`).
    from mcp_gateway.atelier.modes_permission import ecrire_les_reglages_machine

    ecrire_les_reglages_machine(settings)


PROGRAMMATIQUE = frozenset({"sdk-cli", "sdk-ts", "sdk-py"})
# La marque d'origine, telle que l'extension la lit. Le CLI ecrit sans
# espace, mais elle accepte les deux ecritures : on ne veut pas rater une
# marque pour une virgule d'espacement. Le motif sert au texte comme aux
# octets — on ne l'ecrit qu'une fois.
MOTIF_MARQUE = r'"entrypoint":(\s*)"([^"]*)"'
MARQUE = re.compile(MOTIF_MARQUE.encode("ascii"))
# L'extension lit les 65536 premiers octets du transcript et s'arrete a la
# premiere marque qu'elle y trouve. Une correction en tete vaut donc pour
# toute la suite, quels que soient les tours qu'on ajoute ensuite.
TETE = 65536


def dossier_transcripts_claude(cwd: Path) -> Path:
    """Le dossier ou Claude Code range les transcripts d'un repertoire.

    Meme encodage que le CLI : tout ce qui n'est ni lettre ni chiffre
    devient un tiret.
    """
    return Path.home() / ".claude" / "projects" / re.sub(r"[^a-zA-Z0-9]", "-", str(cwd))


def marque_origine(tete: str) -> str:
    """Ce que la conversation declare de son origine, ou rien.

    Meme lecture que l'extension : la premiere marque rencontree decide,
    et l'espacement autour du deux-points ne compte pas.
    """
    trouve = re.search(MOTIF_MARQUE, tete)
    return trouve.group(2) if trouve else ""


def rendre_visible_a_l_extension(cwd: Path, session_id: str) -> bool:
    """Fait entrer la conversation dans la liste que l'extension propose.

    L'extension Claude Code ecarte de sa liste les sessions marquees
    « sdk-cli », et refuse ensuite de les rouvrir : elle repond
    « restore_declined » et ouvre une conversation neuve a la place, sans rien
    dire. Le marquage vient du CLI, qui pose « sdk-cli » des qu'on l'appelle en
    -p — ce que l'Atelier fait a chaque tour, y compris pour une discussion
    tenue par quelqu'un. Le filtre vise l'automatisation, pas nos
    conversations.

    La correction se fait sur place et a longueur egale : « sdk-cli » devient
    « cli » suivi de quatre espaces, que JSON tolere entre deux jetons. Ni
    troncature ni reecriture, donc rien a perdre si `claude` ecrit dans le
    meme fichier au meme instant — il n'ajoute qu'en fin, et on ne touche que
    la tete.

    Seule la premiere marque compte : l'extension lit les 65536 premiers
    octets et s'arrete a la premiere qu'elle y trouve. Les tours suivants
    reposeront « sdk-cli » en queue, sans consequence.

    Rend vrai si le fichier a ete corrige.
    """
    fichier = dossier_transcripts_claude(cwd) / f"{session_id}.jsonl"
    try:
        with fichier.open("r+b") as f:
            tete = f.read(TETE)
            # La premiere marque, et elle seule : c'est celle que
            # l'extension lira. Corriger les suivantes ne servirait a rien et
            # ferait rouvrir le fichier a chaque passage.
            trouve = MARQUE.search(tete)
            if not trouve or trouve.group(2).decode("ascii", "replace") not in PROGRAMMATIQUE:
                return False
            # Meme longueur, donc meme decoupage du fichier : on complete par
            # des espaces, que JSON tolere entre deux jetons.
            corrige = b'"entrypoint":' + trouve.group(1) + b'"cli"'
            f.seek(trouve.start())
            f.write(corrige.ljust(trouve.end() - trouve.start()))
        return True
    except OSError:
        return False


def nommer_pour_l_extension(cwd: Path, session_id: str, titre: str) -> bool:
    """Donne a la conversation, cote Claude Code, le nom qu'on lui a donne ici.

    Sans cela l'extension continue d'afficher un titre derive du
    transcript — souvent une phrase de passage — et la meme conversation
    porte deux noms selon la fenetre ou on la regarde.

    On emploie le format de l'extension elle-meme : une ligne ajoutee en
    fin de journal, que sa relecture prend pour un renommage. Rien n'est
    reecrit, et la derniere ligne posee l'emporte.
    """
    titre = titre.strip()
    if not titre:
        return False
    fichier = dossier_transcripts_claude(cwd) / f"{session_id}.jsonl"
    if not fichier.is_file():
        return False
    try:
        with fichier.open("rb") as f:
            f.seek(max(0, fichier.stat().st_size - TETE))
            queue = f.read().decode("utf-8", "replace")
    except OSError:
        return False
    # Deja ce nom-la : ne pas rallonger le journal a chaque passage.
    deja = re.findall(r'"customTitle":\s*"([^"]*)"', queue)
    if deja and deja[-1] == titre.replace('"', "'"):
        return False
    # Format compact, celui de l'extension : elle sait relire les deux,
    # mais autant écrire comme elle.
    ligne = json.dumps(
        {"type": "custom-title", "sessionId": session_id, "customTitle": titre},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        with fichier.open("a", encoding="utf-8") as f:
            f.write(ligne + chr(10))
    except OSError:
        return False
    return True


def write_resume_sidecar(
    settings: AtelierSettings, slug: str, session_id: str, cwd: Path | None = None
) -> Path:
    """Désigne au projet la conversation que l'Atelier lui confie.

    Un seul fichier, que la petite extension « atelier-ouvre-claude » lit à
    l'ouverture du dossier pour ouvrir Claude Code dessus. Le Markdown à côté
    ne sert qu'à la lecture humaine.
    """
    dossier = cwd or settings.projects_dir / slug
    root = dossier / ".atelier"
    root.mkdir(parents=True, exist_ok=True)
    (root / "session.json").write_text(
        json.dumps({"session_id": session_id, "slug": slug}, indent=2) + "\n",
        encoding="utf-8",
    )
    path = root / "OPEN_CLAUDE_SESSION.md"
    path.write_text(
        "\n".join(
            [
                "# Session Atelier",
                "",
                f"Session: `{session_id}`",
                "",
                "La conversation s'ouvre d'elle-même dans un onglet.",
                "",
                f"CLI : `claude --resume {session_id}`",
                "",
            ]
        ),
        encoding="utf-8",
    )
    # Une version précédente passait par une tâche « folderOpen » qui appelait
    # un script. Il ne pouvait rien ouvrir — seule une extension peut appeler
    # la commande — et il laissait des onglets vides derrière lui. Les projets
    # déjà visités en gardent une copie : on l'efface plutôt que de la laisser
    # tourner à chaque ouverture.
    ancienne_tache = dossier / ".vscode" / "tasks.json"
    if ancienne_tache.is_file():
        try:
            data = json.loads(ancienne_tache.read_text(encoding="utf-8"))
            taches = data.get("tasks") if isinstance(data, dict) else None
            est_notre = isinstance(taches, list) and all(
                str(t.get("label", "")).startswith("Atelier") for t in taches
            )
        except (json.JSONDecodeError, OSError, AttributeError):
            est_notre = False
        if est_notre:
            ancienne_tache.unlink(missing_ok=True)
    return path


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
            # L'approbation des serveurs du dossier se fait à la liaison
            # (`mcp_sync.approuver_les_serveurs_du_projet`).

    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def prepare_vscode_handoff(
    settings: AtelierSettings,
    slug: str,
    session_id: str,
    cwd: Path | None = None,
    mode_permission: str = "",
    kind: str = "code",
) -> None:
    """Prepare le dossier que VS Code va ouvrir, et lui confie la conversation.

    Le dossier n'est pas toujours celui du projet : une conversation
    « assistant » travaille dans son propre repertoire. Tout ce qu'on depose —
    reglages de la fenetre, consigne d'ouverture — doit atterrir la ou
    code-server ouvrira, sinon l'extension ne trouve rien et n'ouvre rien.
    """
    slug_v = (slug or settings.default_slug).strip() or settings.default_slug
    dossier = cwd or settings.projects_dir / slug_v
    dossier.mkdir(parents=True, exist_ok=True)
    sync_claude_home(settings, slug_v)
    write_claude_settings_env(settings)
    write_vscode_workspace_config(settings, slug_v, dossier)
    # Le mode n'est plus recopié ici : le choix de la conversation est déjà
    # dans le magasin que l'extension lit (`modes_permission`), le défaut du
    # projet dans son `.claude/settings.local.json`. L'ancien
    # `ecrire_mode_du_dossier` recopiait le mode de la conversation ouverte
    # en défaut du projet : d'où les `bypassPermissions` « codés en dur ».
    del mode_permission
    from mcp_gateway.atelier.modes_permission import rafraichir_la_conversation

    rafraichir_la_conversation(session_id)
    # Les connecteurs du dossier : son `.mcp.json`, écrit et approuvé comme
    # avant un tour de l'Atelier. Plus de `disabledMcpServers` : c'était la
    # dernière conversation ouverte qui décidait pour toutes.
    from mcp_gateway.atelier.mcp_sync import lier_le_projet

    lier_le_projet(settings, dossier, kind="assistant" if kind == "assistant" else "code")
    write_user_code_server_settings(settings)
    ensure_claude_onboarding(settings, slug_v)
    write_resume_sidecar(settings, slug_v, session_id, dossier)
    rendre_visible_a_l_extension(dossier, session_id)

