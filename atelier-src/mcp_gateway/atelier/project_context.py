"""Écrit dans le projet ce qu'une session ne peut pas deviner.

Une conversation ignore le nom sous lequel elle parle au coordinateur et le
projet dont elle relève : ce sont des décisions de l'Atelier, prises au
lancement. Sans les lui dire, elle appelle un outil pour se situer — ou pire,
travaille à côté, en écrivant ses notes dans un projet qu'elle a deviné.

`--append-system-prompt` semblait la voie naturelle. Mesuré sur le pod : le
drapeau est accepté sans erreur, mais la consigne n'atteint pas le modèle
servi par la passerelle LLM. On passe donc par ce que Claude Code lit de
lui-même à l'ouverture d'un dossier, `CLAUDE.md` — mécanisme prévu pour cela,
lisible par un humain, et qui survit à tout changement de harnais.

Le fichier appartient au projet : on n'y tient qu'une section délimitée, et
on ne touche jamais au reste.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("atelier.project_context")

DEBUT = "<!-- atelier:contexte -->"
FIN = "<!-- /atelier:contexte -->"


# Les outils `atelier_*` d'un agent code, lus à la source du filtre (le serveur
# `atelier` en profil `code`) : le contexte ne peut pas annoncer un outil que le
# serveur refuserait.
def _outils_du_profil_code() -> list[str]:
    try:
        from mcp_gateway.atelier.commandes.profils import OUTILS_DU_PROFIL_CODE

        return sorted(OUTILS_DU_PROFIL_CODE)
    except Exception:  # noqa: BLE001 — le contexte s'écrit même si le catalogue manque
        return []


def _deploiement(chemin: Path) -> dict[str, Any]:
    """Le bloc `deploiement` de `.atelier/projet.json`, s'il y en a un."""
    try:
        donnees = json.loads((chemin / ".atelier" / "projet.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    bloc = donnees.get("deploiement") if isinstance(donnees, dict) else None
    return bloc if isinstance(bloc, dict) else {}


def _lignes_onyxia(chemin: Path) -> list[str]:
    bloc = _deploiement(chemin)
    cible = str(bloc.get("pod") or bloc.get("service") or "").strip()
    if not cible:
        return [
            "- Onyxia : aucun outil. Ce projet ne déclare pas de déploiement ;"
            " la personne le déclare dans l'Atelier si le projet doit tourner dans un pod.",
        ]
    return [
        f"- Onyxia : les outils de **{cible}** seulement (exécuter, lire, état, démarrer"
        " et arrêter son service, GPU), parce que ce projet y est déployé. Ni les"
        " autres pods, ni l'exposition publique.",
    ]


def _bloc_assistant(chemin: Path) -> list[str]:
    return [
        DEBUT,
        "## Ce dossier dans l'Atelier",
        "",
        f"Tu es l'Assistant de l'Atelier, dossier `{chemin}`. Ce texte est le même dans"
        " l'Atelier, dans VS Code et au terminal ; l'Atelier le régénère.",
        "",
        "- Ton profil : toutes les commandes `atelier_*` (projets, conversations, carte,"
        " « À valider », journal), les méta-outils `gateway_find_tools` et"
        " `gateway_call_tool` pour tout le reste, wikichat au complet.",
        "- Tes briefing et courrier arrivent par wikichat, au démarrage et à chaque"
        " message : ils ne sont pas répétés ici.",
        "- Pour agir dans un projet, confie le travail à ses agents plutôt que d'y écrire"
        " toi-même.",
        "",
        "_Section tenue par l'Atelier._",
        FIN,
    ]


def bloc_contexte(
    slug: str,
    chemin: Path,
    *,
    branche: str = "",
    assistant: bool = False,
) -> str:
    """Le contexte de l'Atelier pour ce dossier, tel qu'il doit apparaître.

    Une seule fonction, et rien qui dépende de la surface : l'Atelier, VS Code,
    le terminal et un agent lancé lisent le même fichier, écrit par elle. Il
    porte ce que seul l'Atelier sait et qui ne change pas d'un tour à l'autre :
    le profil, les outils du projet, où exposer, comment joindre les autres
    projets. Le briefing et le courrier n'y sont jamais : le hook
    `SessionStart` de wikichat en est l'unique canal (lot B).
    """
    if assistant:
        return "\n".join(_bloc_assistant(chemin))
    outils = ", ".join(f"`{o}`" for o in _outils_du_profil_code()) or "(liste indisponible)"
    lignes = [
        DEBUT,
        "## Ce projet dans l'Atelier",
        "",
        f"Tu travailles sur le projet **{slug}**, dossier `{chemin}`. Ce texte est le même"
        " dans l'Atelier, dans VS Code et au terminal ; l'Atelier le régénère.",
        "",
        "### Ton profil : agent code",
        "",
        "- Claude Code au complet (fichiers, Bash, recherche, sous-agents, WebFetch),"
        " les connecteurs choisis pour ce projet (`/mcp` les montre) et ton propre"
        " navigateur.",
        f"- De l'Atelier, les outils de ton projet seulement : {outils}. Le projet est"
        " celui de la conversation : tu n'as pas à le nommer.",
        "- wikichat, limité à ce projet : son état, ses notes, ta mémoire, la"
        " connaissance, la messagerie.",
        *_lignes_onyxia(chemin),
        "",
        "### Ton identité et le coordinateur",
        "",
        "- Ton identité wikichat est automatique : n'appelle pas `register`. Ton"
        " briefing et ton courrier arrivent par wikichat, au démarrage et à chaque"
        " message ; ils ne sont pas répétés ici.",
        "- Ce que tu retiens avec `remember` n'appartient qu'à toi.",
        f"- Ce que tu écris avec `add_project_note` est partagé par toutes les"
        f" conversations de **{slug}**.",
        "",
        "### Joindre les autres projets",
        "",
        "Tu ne vois que ce projet. Pour qu'un autre projet voie ou fasse quelque chose,"
        " adresse-toi à ses agents : `list_sessions` montre qui est là,"
        " `contact_agent(target=…, message=…)` ou `send_message(channel=\"@<agent>\")`"
        " leur écrit. Tu ne lances pas d'agent et tu ne crées pas de tâche automatique :"
        " demande-le à la personne.",
        "",
        "### Montrer ce que tu produis",
        "",
        "Un port ouvert sur le pod n'est joignable par personne : ne cherche pas"
        " d'URL publique, ne lance pas de serveur à la main pour le montrer. Une"
        " création = un dossier `artifacts/<nom>/` = une adresse sur l'hôte des"
        " applications ; `atelier_artefacts` la donne.",
        "",
        "- **Autonome** (fichiers) : `atelier_artefact_creer(nom)`, puis dépose"
        " tes fichiers dans `artifacts/<nom>/` (`index.html` s'ouvre à la racine,"
        " liens relatifs, tout embarqué : bac à sable sans réseau extérieur).",
        "- **Serveur** (processus) : `atelier_artefact_creer(nom, mode=\"serveur\")`,"
        " complète `artifacts/<nom>/artefact.json` (`commande` en liste avec `{port}`,"
        " `sante`, `protocoles`, `repertoire` relatif au dossier), puis"
        " `atelier_artefact_verifier` et `atelier_artefact_demarrer`.",
        "- `atelier_montrer(nom)` l'ouvre dans le panneau de la personne ;"
        " `atelier_navigateur_ouvrir(nom)` dans ton navigateur. Sans MCP,"
        " `~/work/bin/atelier-app`.",
        "",
        "### Le web",
        "",
        "- WebSearch n'existe pas ici (la passerelle LLM le simulerait) : pour"
        " chercher, ouvre `https://html.duckduckgo.com/html/?q=<mots>` avec ton"
        " navigateur. WebFetch lit une page dont tu as l'adresse.",
        "- Pour lire une longue page, préfère `evaluate_script`"
        " (`() => document.body.innerText.slice(0, 20000)`) à `take_snapshot`.",
    ]
    if branche:
        lignes += [
            "",
            "### Cette copie de travail",
            "",
            f"Tu es dans une copie du projet, sur la branche `{branche}`, ouverte pour ton"
            " travail (réparation d'un gardien ou tâche automatique). Travaille et commite ici seulement. Ne change pas de branche,"
            " ne touche pas à `main`, ne pousse rien : l'Atelier montre ta proposition"
            " à la personne, qui décide de la fusion.",
        ]
    lignes += ["", "_Section tenue par l'Atelier ; le reste du fichier est à vous._", FIN]
    return "\n".join(lignes)


IMPORT_DU_CONTEXTE = "@.atelier/contexte.md"


# Les copies de travail des agents lancés sur une branche (réparations des
# gardiens) : `<projet>/.atelier/reparations/<id>`. Sous `.atelier/`, que le
# gabarit ignore, elles n'apparaissent pas dans l'état du projet.
DOSSIER_DES_COPIES = Path(".atelier") / "reparations"


def dossier_du_contexte(settings: Any, cwd: Path, slug: str) -> Path | None:
    """Le seul dossier où le contexte de `slug` peut s'écrire, ou None.

    Le contexte s'écrivait dans le `cwd` de la conversation, quel qu'il soit.
    Le 24/09, une fiche dont le `cwd` était `/tmp` a produit `/tmp/CLAUDE.md`
    (le bloc de `projet-sans-nom-5`), que chargeait ensuite toute session
    lancée sous `/tmp`. Désormais :

    - un projet : exactement `~/work/projects/<slug>`, et seulement si le `cwd`
      de la conversation est ce dossier ;
    - une copie de travail du projet ouverte par l'Atelier pour un agent lancé
      sur une branche : `~/work/projects/<slug>/.atelier/reparations/<id>` ;
    - l'Assistant : son dossier, ou un sous-dossier de celui-ci ;
    - rien d'autre, jamais.
    """
    if not slug or slug in (".", "..") or "/" in slug or "\\" in slug:
        return None
    try:
        ici = Path(cwd).resolve()
        if slug == settings.assistant_slug:
            racine = Path(settings.assistant_root).resolve()
            ici.relative_to(racine)
            return ici
        attendu = (Path(settings.projects_dir) / slug).resolve()
        if Path(settings.projects_dir).resolve() not in attendu.parents:
            return None
    except (OSError, ValueError):
        return None
    if ici == attendu:
        return attendu
    copies = (attendu / DOSSIER_DES_COPIES).resolve()
    if ici.parent == copies and (ici / ".git").is_file():
        return ici
    return None


def branche_de_la_copie(dossier: Path) -> str:
    """La branche d'une copie de travail (`git worktree`), lue sans lancer git.

    Une copie porte un fichier `.git` (« gitdir: … ») ; son `HEAD` dit la
    branche. Un dossier de projet ordinaire (`.git` est un dossier) n'en a pas :
    le contexte ne dépend alors de rien d'autre que du projet.
    """
    marque = Path(dossier) / ".git"
    if not marque.is_file():
        return ""
    try:
        texte = marque.read_text(encoding="utf-8").strip()
        if not texte.startswith("gitdir:"):
            return ""
        gitdir = Path(texte.partition(":")[2].strip())
        if not gitdir.is_absolute():
            gitdir = (Path(dossier) / gitdir).resolve()
        tete = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    prefixe = "ref: refs/heads/"
    return tete[len(prefixe):] if tete.startswith(prefixe) else ""


def contexte_attendu(settings: Any, cwd: Path, slug: str) -> tuple[Path, str] | None:
    """Où le contexte de ce dossier s'écrit, et ce qu'il doit dire.

    Seule source du contenu, pour toutes les surfaces : l'Atelier avant un tour,
    le démarrage du service, un lancement. Rien ici ne dépend de qui demande.
    """
    dossier = dossier_du_contexte(settings, cwd, slug)
    if dossier is None:
        return None
    assistant = slug == settings.assistant_slug
    bloc = bloc_contexte(
        slug,
        dossier,
        branche="" if assistant else branche_de_la_copie(dossier),
        assistant=assistant,
    )
    return dossier, bloc


def ecrire_contexte(cwd: Path, slug: str, settings: Any = None) -> bool:
    """Pose ou met à jour le contexte du projet.

    Là où le projet l'attend : `.atelier/contexte.md` si son `CLAUDE.md`
    l'importe (structure type), sinon la section délimitée de `CLAUDE.md`.
    Rien n'est écrit hors du dossier du projet (voir `dossier_du_contexte`).

    Retourne True si un fichier a changé. Rien n'est réécrit quand le contenu
    est déjà le bon : le fichier est souvent sous git, une modification sans
    objet salirait l'état du dépôt à chaque tour.
    """
    if settings is None:
        from mcp_gateway.atelier.config import get_settings

        settings = get_settings()
    if slug == settings.assistant_slug:
        # L'Assistant a son propre gabarit, à la racine de son dossier, que
        # toutes ses conversations lisent (`assistant.py`).
        from mcp_gateway.atelier.assistant import preparer_le_tour

        return preparer_le_tour(settings, cwd)
    attendu = contexte_attendu(settings, cwd, slug)
    if attendu is None:
        log.warning("contexte de %s non écrit : %s n'est pas le dossier du projet", slug, cwd)
        return False
    dossier, bloc = attendu
    chemin = dossier / "CLAUDE.md"
    try:
        ancien = chemin.read_text(encoding="utf-8") if chemin.is_file() else ""
    except OSError as exc:
        log.info("CLAUDE.md illisible dans %s : %s", dossier, exc)
        return False

    if ancien.lstrip().startswith(IMPORT_DU_CONTEXTE):
        return _ecrire_si_change(dossier / ".atelier" / "contexte.md", bloc + "\n")

    if DEBUT in ancien and FIN in ancien:
        avant, _, reste = ancien.partition(DEBUT)
        _, _, apres = reste.partition(FIN)
        nouveau = avant + bloc + apres
    elif ancien.strip():
        nouveau = ancien.rstrip() + "\n\n" + bloc + "\n"
    else:
        nouveau = bloc + "\n"
    if nouveau == ancien:
        return False
    return _ecrire_si_change(chemin, nouveau)


def importe_le_contexte(dossier: Path) -> bool:
    """Le `CLAUDE.md` du dossier commence-t-il par l'import du contexte ?"""
    try:
        return (Path(dossier) / "CLAUDE.md").read_text(encoding="utf-8").lstrip().startswith(IMPORT_DU_CONTEXTE)
    except OSError:
        return False


def ecrire_tous_les_contextes(settings: Any) -> int:
    """Régénère `.atelier/contexte.md` de chaque projet à la structure type.

    Au démarrage du service : VS Code et le terminal lisent le fichier sans
    qu'un tour de l'Atelier l'ait écrit avant eux. Seuls les projets qui
    importent le contexte sont touchés — le fichier y est ignoré par git. Un
    projet d'avant la structure garde sa section, réécrite à son prochain tour :
    le faire ici salirait d'un coup tous les `CLAUDE.md` suivis. Rend le nombre
    de fichiers changés.
    """
    racine = Path(settings.projects_dir)
    n = 0
    if not racine.is_dir():
        return 0
    for dossier in sorted(racine.iterdir()):
        if not dossier.is_dir() or dossier.is_symlink() or dossier.name.startswith("."):
            continue
        if not importe_le_contexte(dossier):
            continue
        if ecrire_contexte(dossier, dossier.name, settings):
            n += 1
    return n


def _ecrire_si_change(chemin: Path, contenu: str) -> bool:
    try:
        if chemin.is_file() and chemin.read_text(encoding="utf-8") == contenu:
            return False
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(contenu, encoding="utf-8")
    except OSError as exc:
        log.info("%s non écrit : %s", chemin, exc)
        return False
    return True
