"""Le mode de permission : une liste, un défaut par projet, un choix par conversation.

Contrat `docs/vision/profils-acces.md`, « Mode de permission » : l'app, VS Code
et le terminal lisent le même mode, écrit à un seul endroit.

**Les modes.** `default`, `acceptEdits`, `plan`, `bypassPermissions`. Les
anciens noms se lisent encore : `manual` est le nom que l'extension donne à
`default` ; `auto` (classifieur que la passerelle LLM du pod ne sert pas, et
qui demande avant d'écrire là où `acceptEdits` écrit) devient `default`, le
seul des quatre qui n'accorde rien de plus.

**Le défaut du projet** : `permissions.defaultMode` de `.claude/settings.local.json`,
le fichier personnel du dossier. C'est le plus natif : le CLI le résout de
lui-même au terminal, et l'extension VS Code s'en remet au « défaut résolu par
le CLI » quand elle ne passe pas de mode (voir l'enveloppeur).

**Le choix d'une conversation** : le magasin de l'extension VS Code,
`<code-server>/User/globalStorage/anthropic.claude-code/session-permission-modes/<id>.json`,
`{"mode": …, "updatedAt": <ms>}`. Relevé dans l'extension 2.1.282
(`extension.js`, classe du magasin et `getSessionPermissionModes`) :

- l'extension y écrit le mode quand on le change dans une conversation
  (`persist_session_permission_mode`), et le relit pour rouvrir la conversation
  dans ce mode ; une entrée de plus de 30 jours est ignorée ;
- c'est donc déjà l'endroit où VS Code tient le mode *par conversation*.
  L'Atelier y écrit et y lit, sous le même identifiant (celui du CLI) : un
  choix fait dans l'app vaut dans VS Code, et inversement ;
- au terminal, `~/work/bin/atelier-claude-vscode` le lit pour `--resume <id>`.

Ni `bypassPermissions` codé en dur dans un projet, ni réglage machine qui
l'impose : `claudeCode.allowDangerouslySkipPermissions` n'est posé que tant
qu'un projet ou une conversation a choisi `bypassPermissions` (l'extension
rabat sinon ce mode sur `default`), et `claudeCode.initialPermissionMode`, qui
imposait le mode de la dernière ouverture à toutes les conversations neuves,
est retiré.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.claude_home import donnees_code_server
from mcp_gateway.atelier.config import AtelierSettings

log = logging.getLogger("atelier.modes_permission")

MODES = ("default", "acceptEdits", "plan", "bypassPermissions")
BYPASS = "bypassPermissions"
ALIAS = {"manual": "default", "auto": "default"}
# Le défaut du service quand ni la conversation ni le projet n'ont choisi.
MODE_DU_SERVICE = "acceptEdits"
# Ce que l'extension tient pour périmé (30 jours, `XW$` dans extension.js).
DUREE_DE_VIE_MS = 30 * 24 * 3600 * 1000
# Une date trop loin dans le futur est refusée par l'extension (1 jour, `GW$`).
AVANCE_MAX_MS = 24 * 3600 * 1000
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

CLE_MODE_INITIAL = "claudeCode.initialPermissionMode"
CLE_BYPASS = "claudeCode.allowDangerouslySkipPermissions"


def normaliser(mode: str | None) -> str:
    """Un des quatre modes, ou `""` pour un mode inconnu ou vide."""
    texte = (mode or "").strip()
    texte = ALIAS.get(texte, texte)
    return texte if texte in MODES else ""


# --- Choix d'une conversation : le magasin de l'extension -------------------


def dossier_des_conversations() -> Path:
    return (
        donnees_code_server()
        / "User"
        / "globalStorage"
        / "anthropic.claude-code"
        / "session-permission-modes"
    )


def _fichier(identifiant: str) -> Path | None:
    if not identifiant or not _IDENTIFIANT.match(identifiant):
        return None
    return dossier_des_conversations() / f"{identifiant}.json"


def _entree_valide(donnees: Any, maintenant_ms: int) -> str:
    if not isinstance(donnees, dict):
        return ""
    date = donnees.get("updatedAt")
    if not isinstance(date, (int, float)) or date > maintenant_ms + AVANCE_MAX_MS:
        return ""
    if date < maintenant_ms - DUREE_DE_VIE_MS:
        return ""
    mode = donnees.get("mode")
    return mode if mode in MODES else ""


def mode_de_la_conversation(identifiant: str) -> str:
    """Le mode choisi pour la conversation (identifiant du CLI), ou `""`."""
    fichier = _fichier(identifiant)
    if fichier is None or not fichier.is_file():
        return ""
    try:
        donnees = json.loads(fichier.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return _entree_valide(donnees, int(time.time() * 1000))


def ecrire_mode_de_la_conversation(settings: AtelierSettings, identifiant: str, mode: str | None) -> str:
    """Pose (ou retire, avec `""`) le choix de la conversation. Rend le mode retenu.

    Même format que l'extension, écrit par renommage : elle relit le dossier
    à chaque liste des conversations.
    """
    fichier = _fichier(identifiant)
    if fichier is None:
        return ""
    voulu = normaliser(mode)
    if not voulu:
        fichier.unlink(missing_ok=True)
    else:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        provisoire = fichier.with_name(fichier.name + ".atelier-tmp")
        provisoire.write_text(
            json.dumps({"mode": voulu, "updatedAt": int(time.time() * 1000)}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(provisoire, fichier)
    ecrire_les_reglages_machine(settings)
    return voulu


def rafraichir_la_conversation(identifiant: str) -> None:
    """Garde en vie un choix qu'on vient d'appliquer : l'extension l'oublierait après 30 jours."""
    mode = mode_de_la_conversation(identifiant)
    fichier = _fichier(identifiant)
    if not mode or fichier is None:
        return
    try:
        provisoire = fichier.with_name(fichier.name + ".atelier-tmp")
        provisoire.write_text(
            json.dumps({"mode": mode, "updatedAt": int(time.time() * 1000)}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(provisoire, fichier)
    except OSError:
        pass


def _modes_des_conversations() -> dict[str, str]:
    dossier = dossier_des_conversations()
    if not dossier.is_dir():
        return {}
    maintenant = int(time.time() * 1000)
    sortie: dict[str, str] = {}
    for fichier in dossier.glob("*.json"):
        try:
            mode = _entree_valide(json.loads(fichier.read_text(encoding="utf-8")), maintenant)
        except (OSError, ValueError):
            continue
        if mode:
            sortie[fichier.stem] = mode
    return sortie


# --- Défaut du projet : `.claude/settings.local.json` -----------------------


def _reglages_locaux(dossier: Path) -> Path:
    return Path(dossier) / ".claude" / "settings.local.json"


def _lire_json(chemin: Path) -> dict[str, Any] | None:
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        return None
    return donnees if isinstance(donnees, dict) else None


def mode_du_projet_brut(dossier: Path | str) -> str:
    """La valeur écrite telle quelle (`manual`, `auto` compris), ou `""`."""
    donnees = _lire_json(_reglages_locaux(Path(dossier))) or {}
    permissions = donnees.get("permissions")
    return str(permissions.get("defaultMode") or "") if isinstance(permissions, dict) else ""


def mode_du_projet(dossier: Path | str | None) -> str:
    """Le défaut que le projet s'est donné, ou `""`."""
    if not dossier:
        return ""
    return normaliser(mode_du_projet_brut(dossier))


def ecrire_mode_du_projet(settings: AtelierSettings, dossier: Path, mode: str | None) -> str:
    """Pose (ou retire, avec `""`) le défaut du projet. Le reste du fichier est gardé."""
    chemin = _reglages_locaux(dossier)
    donnees = _lire_json(chemin)
    if donnees is None:
        log.warning("%s illisible : défaut du projet non écrit", chemin)
        return mode_du_projet(dossier)
    voulu = normaliser(mode)
    permissions = donnees.get("permissions")
    permissions = dict(permissions) if isinstance(permissions, dict) else {}
    if voulu:
        permissions["defaultMode"] = voulu
    else:
        permissions.pop("defaultMode", None)
    if permissions:
        donnees["permissions"] = permissions
    else:
        donnees.pop("permissions", None)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps(donnees, indent=2) + "\n", encoding="utf-8")
    ecrire_les_reglages_machine(settings)
    return voulu


def assurer_le_defaut_du_projet(settings: AtelierSettings, dossier: Path) -> str:
    """Écrit le défaut du service dans un projet qui n'en a pas. Rend le défaut du projet.

    Sans `defaultMode`, le CLI part en `default` dans VS Code et au terminal,
    quand l'app applique le défaut du service (`acceptEdits`) : deux modes pour
    une même conversation. Le défaut du service est donc posé dans le projet à
    sa liaison, là où toutes les surfaces le lisent. Jamais `bypassPermissions`
    (`mode_du_service`), donc rien à accorder dans les réglages machine.
    """
    existant = mode_du_projet_brut(dossier)
    if existant:
        return normaliser(existant)
    chemin = _reglages_locaux(dossier)
    donnees = _lire_json(chemin)
    if donnees is None:
        return ""
    voulu = mode_du_service(settings)
    permissions = donnees.get("permissions")
    permissions = dict(permissions) if isinstance(permissions, dict) else {}
    permissions["defaultMode"] = voulu
    donnees["permissions"] = permissions
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text(json.dumps(donnees, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("défaut de mode non écrit dans %s : %s", dossier, exc)
        return ""
    return voulu


# --- Résolution ------------------------------------------------------------


def mode_du_service(settings: AtelierSettings) -> str:
    """Le défaut du service, jamais `bypassPermissions` : il ne s'impose pas."""
    mode = normaliser(getattr(settings, "permission_mode", "")) or MODE_DU_SERVICE
    return MODE_DU_SERVICE if mode == BYPASS else mode


def mode_resolu(settings: AtelierSettings, dossier: Path | str | None, identifiant: str) -> tuple[str, str]:
    """Le mode d'un tour et d'où il vient : `conversation`, `projet` ou `service`.

    La même règle que suivent VS Code (magasin, puis défaut du CLI) et le
    terminal (enveloppeur pour une reprise, puis `defaultMode`).
    """
    propre = mode_de_la_conversation(identifiant)
    if propre:
        return propre, "conversation"
    du_projet = mode_du_projet(dossier)
    if du_projet:
        return du_projet, "projet"
    return mode_du_service(settings), "service"


# --- Réglages machine de code-server ---------------------------------------


def dossiers_des_projets(settings: AtelierSettings) -> list[Path]:
    dossiers: list[Path] = []
    for racine in (settings.projects_dir, settings.assistant_sessions_dir):
        if racine.is_dir():
            dossiers.extend(d for d in sorted(racine.iterdir()) if d.is_dir() and not d.name.startswith("."))
    if settings.assistant_root.is_dir():
        dossiers.append(settings.assistant_root)
    return dossiers


def bypass_choisi(settings: AtelierSettings) -> bool:
    """Vrai si une conversation ou un projet a choisi `bypassPermissions`."""
    if BYPASS in _modes_des_conversations().values():
        return True
    return any(mode_du_projet(d) == BYPASS for d in dossiers_des_projets(settings))


def ecrire_les_reglages_machine(settings: AtelierSettings) -> dict[str, Any]:
    """Accorde à l'extension ce que les choix demandent, et rien de plus.

    - `claudeCode.initialPermissionMode` est retiré : de portée machine, il
      imposait à toute conversation neuve le mode de la dernière ouverte ;
    - `claudeCode.allowDangerouslySkipPermissions` n'est vrai que tant qu'un
      choix le demande. Sans lui, l'extension rabat `bypassPermissions` sur
      `default` (« Downgrading launch to default mode ») ; avec lui, elle
      passe `--allow-dangerously-skip-permissions`, qui *permet* le mode sans
      l'imposer. Le reste du fichier n'est pas touché.
    """
    fichier = donnees_code_server() / "Machine" / "settings.json"
    donnees = _lire_json(fichier)
    if donnees is None:
        log.warning("%s illisible : réglages de mode non écrits", fichier)
        return {}
    avant = json.dumps(donnees, sort_keys=True)
    donnees.pop(CLE_MODE_INITIAL, None)
    if bypass_choisi(settings):
        donnees[CLE_BYPASS] = True
    else:
        donnees.pop(CLE_BYPASS, None)
    if json.dumps(donnees, sort_keys=True) != avant:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text(json.dumps(donnees, indent=2) + "\n", encoding="utf-8")
    return {CLE_BYPASS: bool(donnees.get(CLE_BYPASS)), CLE_MODE_INITIAL: None}


# --- Résidus ---------------------------------------------------------------

MARQUE_NETTOYAGE = "modes-permission-v1"


def _modes_des_fiches(settings: AtelierSettings) -> list[tuple[str, str]]:
    """(identifiant du CLI, mode) des fiches de conversation qui en portaient un."""
    sortie: list[tuple[str, str]] = []
    dossier = getattr(settings, "sessions_dir", None)
    if not isinstance(dossier, Path) or not dossier.is_dir():
        return sortie
    for fichier in sorted(dossier.glob("*.json")):
        donnees = _lire_json(fichier) or {}
        mode = str(donnees.get("permission_mode") or "")
        identifiant = str(donnees.get("claude_session_id") or donnees.get("session_id") or "")
        if mode and identifiant:
            sortie.append((identifiant, mode))
    return sortie


def nettoyer_les_residus(settings: AtelierSettings, fiches: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Une fois : range les anciens choix et retire ce qui imposait un mode.

    - le `defaultMode` d'un projet réécrit dans la liste (`manual`, `auto`
      deviennent `default`) ; `bypassPermissions` y est remplacé par le défaut
      du service : il y avait été recopié depuis la conversation ouverte dans
      VS Code par l'ancien `ecrire_mode_du_dossier`, pas choisi pour le projet ;
    - les modes des fiches de conversation (`fiches`, sinon celles du dossier
      des sessions : identifiant du CLI, mode) passent dans le magasin, s'il
      n'y a rien déjà ;
    - les réglages machine sont réécrits.

    Idempotent ; la marque évite de retirer à nouveau un bypass choisi depuis
    pour un projet. Rend ce qui a été fait (noms de dossier, jamais de valeur).
    """
    marque = settings.mcp_dir / f".{MARQUE_NETTOYAGE}"
    fait: dict[str, Any] = {"projets": [], "conversations": 0}
    if not marque.is_file():
        for dossier in dossiers_des_projets(settings):
            brut = mode_du_projet_brut(dossier)
            if not brut:
                continue
            voulu = normaliser(brut)
            if voulu == BYPASS or not voulu:
                # Pas choisi pour le projet : le défaut du service, que lisent
                # toutes les surfaces (`assurer_le_defaut_du_projet`).
                voulu = mode_du_service(settings)
            if voulu != brut:
                ecrire_mode_du_projet(settings, dossier, voulu)
                fait["projets"].append(dossier.name)
        for identifiant, mode in (fiches if fiches is not None else _modes_des_fiches(settings)):
            if normaliser(mode) and not mode_de_la_conversation(identifiant):
                fichier = _fichier(identifiant)
                if fichier is None:
                    continue
                fichier.parent.mkdir(parents=True, exist_ok=True)
                fichier.write_text(
                    json.dumps({"mode": normaliser(mode), "updatedAt": int(time.time() * 1000)}, separators=(",", ":")),
                    encoding="utf-8",
                )
                fait["conversations"] += 1
        marque.parent.mkdir(parents=True, exist_ok=True)
        marque.write_text("fait\n", encoding="utf-8")
        if fait["projets"]:
            log.info("défauts de projet réécrits dans la liste des modes : %s", fait["projets"])
    fait["machine"] = ecrire_les_reglages_machine(settings)
    return fait
