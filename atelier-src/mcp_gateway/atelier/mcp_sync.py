"""Matérialise le registre intégré vers la config Claude Code."""

from __future__ import annotations

import json
import logging
import re
import shlex
from pathlib import Path
from urllib.parse import quote
from typing import Any, Literal

from mcp_gateway.db import connect
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore
from mcp_gateway.atelier.mcp_secrets import (
    en_references,
    en_references_fournies,
    est_une_reference,
    secrets_en_clair,
)

log = logging.getLogger("atelier.mcp_sync")

WorkspaceKind = Literal["assistant", "code"]

# La passerelle de l'Atelier, telle qu'un projet la désigne.
SERVICE_ATELIER = "atelier"
# Le navigateur de l'Atelier (stdio, un processus par client) et l'en-tête de
# conversation de la passerelle vivent dans `navigateur` ; réexportés ici pour
# les appelants existants.
from mcp_gateway.atelier.navigateur import (  # noqa: E402
    CONVERSATION_HORS_ATELIER,
    ENTETE_CONVERSATION,
    SERVICE_CHROME,
    declaration_chrome,
    est_le_navigateur,
    navigateur_configure,
)
# wikichat : le pont stdio, qui porte la conversation (`wikichat_mcp`).
from mcp_gateway.atelier.wikichat_mcp import (  # noqa: E402
    declaration_wikichat,
    est_wikichat,
    integrer_wikichat,
)


def est_alias_onyxia_deguise(nom: str) -> bool:
    """Onyxia_nic01asfr n'est pas le service Onyxia : c'est Atelier `/mcp`.

    Le vrai connecteur s'appelle `Onyxia`. Les agents Code l'ouvrent en
    natif (`mcp__Onyxia__*`) — pas via `gateway_find_tools`, qui n'existait
    pas encore quand cet accès tenait déjà.
    """
    cle = nom.lower()
    return cle.startswith("onyxia") and cle != "onyxia"


def est_amont_de_la_gateway(nom: str) -> bool:
    """Compat : l'alias déguisé seulement, plus le service Onyxia lui-même."""
    return est_alias_onyxia_deguise(nom)


def sans_amonts_gateway(servers: dict[str, Any]) -> dict[str, Any]:
    """Hors les portes Atelier mal nommées Onyxia_*."""
    return {
        nom: cfg for nom, cfg in servers.items() if not est_alias_onyxia_deguise(nom)
    }


def pour_le_home(servers: dict[str, Any]) -> dict[str, Any]:
    """Les déclarations du pool pour un fichier hors profil (`claude-mcp.json`).

    On écarte l'alias déguisé (`Onyxia_nic01asfr`), qui n'est pas le service
    Onyxia — c'est la porte `/mcp` de l'Atelier — et Onyxia lui-même, que
    personne ne joint plus en direct.

    Le navigateur n'y demande rien de plus : c'est un serveur stdio, dont
    chaque client lance son propre processus — le cloisonnement est là.
    """
    propre = sans_amonts_gateway(servers)
    # Plus personne ne joint Onyxia en direct (contrat de l'équipe O) : il
    # passe par le mandataire de la passerelle, que seul le profil distribue.
    directes = adresses_directes_d_onyxia(propre)
    propre = {nom: cfg for nom, cfg in propre.items() if not _est_onyxia_direct(nom, cfg, directes)}
    sortie: dict[str, Any] = {}
    for nom, cfg in propre.items():
        if isinstance(cfg, dict):
            # Jamais un secret en clair dans ce fichier : les déclarations du
            # pool deviennent leurs références `${ATELIER_MCP_…}`, dont
            # `~/work/.secrets/claude-env.sh` porte les valeurs (env_secrets).
            sortie[nom], _ = en_references(nom, cfg)
        else:
            sortie[nom] = cfg
    return sortie


# --- Profils (docs/vision/profils-acces.md) ---------------------------------
#
# Un profil par type d'acteur, identique sur toutes les surfaces : `code` pour
# les agents d'un projet, `assistant` pour le dossier de l'Assistant. La
# configuration d'un dossier est calculée par une seule fonction,
# `configuration_du_profil`, que lisent le fichier effectif d'un tour de
# l'Atelier, le `.mcp.json` du dossier (VS Code, terminal) et
# `enabledMcpjsonServers`.

Profil = Literal["code", "assistant"]
PROFILS: tuple[str, ...] = ("code", "assistant")
# L'en-tête par lequel le serveur `atelier` sait quel profil servir (contrat a,
# équipe A). Le pont wikichat reçoit le sien par son environnement (contrat b).
ENTETE_PROFIL = "X-Atelier-Profil"
ENV_WIKICHAT_PROFIL = "WIKICHAT_PROFIL"
ENV_WIKICHAT_PROJET = "WIKICHAT_PROJET"
# Le nom sous lequel l'Assistant se présente à wikichat comme projet.
PROJET_ASSISTANT = "assistant"
# Le nom de l'entrée Onyxia dans un fichier de configuration.
SERVICE_ONYXIA = "Onyxia"


def profil_du_type(kind: str) -> Profil:
    """Le profil d'une conversation : `assistant` pour l'Assistant, `code` sinon."""
    return "assistant" if kind == "assistant" else "code"


def est_onyxia(nom: str) -> bool:
    """L'entrée du service Onyxia, quelle que soit sa casse (pas l'alias déguisé)."""
    return nom.lower() == "onyxia"


def _onyxia_bouchon(
    settings: AtelierSettings,
    slug: str,
    profil: str,
    *,
    pool: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """En attendant `onyxia_projet` (équipe O), avec sa signature et ses règles.

    - `code` : rien. L'ancien `assurer_onyxia_natif` imposait Onyxia à tout
      projet dès que le pool l'avait (audit G3) : chaque tour attendait 30 s
      une poignée de main qui ne venait pas. Un agent code n'a plus Onyxia que
      par le déploiement de son projet (bloc `deploiement` de `projet.json`),
      ce que dit le module de l'équipe O ;
    - `assistant` : l'entrée du mandataire de la passerelle, `/mcp/onyxia`.
      Plus personne ne joint Onyxia en direct.

    Rien si le pool n'a pas d'Onyxia.
    """
    del slug
    if profil != "assistant":
        return None
    pool = _pool_enabled(settings) if pool is None else pool
    if not any(est_onyxia(nom) for nom in pool):
        return None
    return {
        "type": "http",
        "url": f"http://127.0.0.1:{settings.port}/mcp/onyxia",
        "headers": {"Authorization": "Bearer ${ATELIER_MCP_KEY}"},
    }


def onyxia_du_profil(
    settings: AtelierSettings,
    slug: str,
    profil: str,
    *,
    pool: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """L'entrée Onyxia que reçoit ce dossier (contrat c), sous le nom `Onyxia`.

    `onyxia_pour_projet(settings, slug, profil, *, pool=None) -> dict | None`,
    du module de l'équipe O, fait foi dès qu'il existe ; sinon, le bouchon.
    """
    try:
        from mcp_gateway.atelier.onyxia_projet import onyxia_pour_projet  # type: ignore[import-not-found]
    except ImportError:
        onyxia_pour_projet = _onyxia_bouchon
    entree = onyxia_pour_projet(settings, slug, profil, pool=pool)
    return entree if isinstance(entree, dict) and entree else None


def adresses_directes_d_onyxia(pool: dict[str, Any]) -> set[str]:
    """Les adresses du service Onyxia lui-même (`passerelle-mcp…`), telles que le pool les déclare."""
    return {
        str(cfg.get("url") or "").rstrip("/")
        for nom, cfg in pool.items()
        if est_onyxia(nom) and isinstance(cfg, dict) and cfg.get("url")
    }


def _est_onyxia_direct(nom: str, cfg: Any, directes: set[str]) -> bool:
    """Une entrée qui joint Onyxia sans passer par le mandataire de l'Atelier."""
    if not isinstance(cfg, dict):
        return est_onyxia(nom)
    url = str(cfg.get("url") or "").rstrip("/")
    if url and url in directes:
        return True
    return est_onyxia(nom) and "/mcp/onyxia" not in url


# --- Connecteurs en échec d'authentification --------------------------------
#
# Mesuré le 25/09 (audit M5) : n8n répond 401 avec le jeton du pool, il est en
# échec sur toutes les surfaces, et il restait écrit dans tous les projets. La
# dernière sonde du pool est notée ici ; un connecteur dont elle a échoué en
# authentification n'est plus distribué, et il est signalé (journal, état des
# connecteurs d'un projet, vérificateur de cohérence).

FICHIER_SONDES = "sondes-authentification.json"
_ECHEC_AUTH = re.compile(r"\b(?:401|403)\b|unauthori[sz]ed|forbidden", re.IGNORECASE)


def _chemin_des_sondes(settings: AtelierSettings) -> Path:
    return settings.mcp_dir / FICHIER_SONDES


def connecteurs_en_echec_d_authentification(settings: AtelierSettings) -> dict[str, dict[str, Any]]:
    """Nom du connecteur → `{code, depuis}` ; vide si aucune sonde n'a échoué ainsi."""
    lu = _load_json_object(_chemin_des_sondes(settings)) or {}
    echecs = lu.get("echecs")
    return {str(k): v for k, v in echecs.items() if isinstance(v, dict)} if isinstance(echecs, dict) else {}


def noter_les_sondes(settings: AtelierSettings, statut: dict[str, Any] | None) -> bool:
    """Retient, de la dernière sonde du pool, les connecteurs refusés en authentification.

    `statut` est celui du pool (`pool.startup()`) : clé `registry:<nom>` ou
    `<nom>`, valeur `connected`, `error: …`, `disabled`… Une sonde réussie
    efface l'échec. Rien du message d'erreur n'est gardé : seulement le code.
    Si l'ensemble change, les projets sont reliés, pour que le connecteur
    disparaisse (ou revienne) partout. Rend vrai si l'ensemble a changé.
    """
    if not isinstance(statut, dict):
        return False
    from datetime import datetime, timezone

    # Le pool ne sonde pas les serveurs stdio (« stdio-local ») : n8n, un pont
    # `mcp-remote` vers une adresse à jeton, restait distribué en 401 (mesuré le
    # 26/09). On sonde ces ponts nous-mêmes, au même moment.
    statut = {**statut, **sonder_les_ponts_distants(settings)}
    avant = connecteurs_en_echec_d_authentification(settings)
    apres = dict(avant)
    for cle, valeur in statut.items():
        nom = str(cle).split(":", 1)[1] if str(cle).startswith("registry:") else str(cle)
        texte = str(valeur or "")
        if texte.startswith("error") and _ECHEC_AUTH.search(texte):
            code = 403 if "403" in texte or "forbidden" in texte.lower() else 401
            if nom not in apres:
                apres[nom] = {"code": code, "depuis": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        elif texte and texte not in ("probing", "stdio-local"):
            apres.pop(nom, None)
    if set(apres) == set(avant):
        return False
    for nom in sorted(set(apres) - set(avant)):
        log.warning(
            "connecteur %s refusé en authentification (%s) : il n'est plus distribué aux agents",
            nom,
            apres[nom]["code"],
        )
    _atomic_write_json(_chemin_des_sondes(settings), {"echecs": apres})
    try:
        lier_tous_les_projets(settings)
    except OSError as exc:
        log.warning("liaison après sonde impossible : %s", exc)
    return True


def _pont_distant(cfg: Any) -> tuple[str, dict[str, str]] | None:
    """L'adresse et les en-têtes d'un pont `mcp-remote <url> --header "K: V"`, ou None."""
    if not isinstance(cfg, dict):
        return None
    args = cfg.get("args")
    if not isinstance(args, list) or not any(isinstance(a, str) and "mcp-remote" in a for a in args):
        return None
    url = next((a for a in args if isinstance(a, str) and a.startswith(("http://", "https://"))), "")
    if not url:
        return None
    entetes: dict[str, str] = {}
    for i, a in enumerate(args[:-1]):
        if a == "--header" and isinstance(args[i + 1], str) and ":" in args[i + 1]:
            nom, _, valeur = args[i + 1].partition(":")
            entetes[nom.strip()] = valeur.strip()
    return url, entetes


def sonder_les_ponts_distants(settings: AtelierSettings, delai: float = 8.0) -> dict[str, str]:
    """Sonde en HTTP l'adresse des ponts `mcp-remote` du pool (`initialize`).

    Rend `{nom: "connected" | "error: 401" | "error: 403"}` ; rien pour une
    réponse ambiguë (injoignable, autre code) : on ne retire un connecteur que
    sur un refus d'authentification avéré. Aucun en-tête ni jeton n'est écrit.
    """
    import httpx

    sortie: dict[str, str] = {}
    try:
        pool = _pool_enabled(settings)
    except Exception:  # noqa: BLE001 — une base illisible ne bloque pas le démarrage
        return sortie
    for nom, cfg in pool.items():
        pont = _pont_distant(cfg)
        if pont is None:
            continue
        url, entetes = pont
        corps = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "atelier-sonde", "version": "1"}},
        }
        try:
            reponse = httpx.post(
                url,
                json=corps,
                headers={**entetes, "Accept": "application/json, text/event-stream"},
                timeout=delai,
            )
        except httpx.HTTPError:
            continue
        if reponse.status_code in (401, 403):
            sortie[nom] = f"error: {reponse.status_code}"
        elif 200 <= reponse.status_code < 300:
            sortie[nom] = "connected"
    return sortie


def _sans_echecs_d_authentification(
    settings: AtelierSettings, servers: dict[str, Any]
) -> dict[str, Any]:
    echecs = connecteurs_en_echec_d_authentification(settings)
    if not echecs:
        return servers
    return {nom: cfg for nom, cfg in servers.items() if nom not in echecs}


def _vise_la_passerelle(cfg: Any, settings: AtelierSettings) -> bool:
    """Vrai pour une entrée qui pointe vers la porte `/mcp` de l'Atelier.

    Sous un autre nom que `atelier`, c'est une porte déguisée : elle donnerait
    à un agent code les méta-outils de la passerelle, sans en-tête de profil.
    """
    if not isinstance(cfg, dict):
        return False
    url = str(cfg.get("url") or "")
    if not url:
        return False
    return _hote_normalise(url) == f"local:{settings.port}"


def _load_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("invalid mcp json %s: %s", path, exc)
        return None
    return loaded if isinstance(loaded, dict) else None


# Un projet qui n'a jamais choisi ses connecteurs hérite du pool entier. Son
# `.mcp.json` est désormais écrit quand même (VS Code et le terminal ne lisent
# que lui) ; cette marque dit qu'il reflète le pool et doit le suivre.
MARQUE_HERITAGE = Path(".atelier") / "connecteurs-herites"


def herite_du_pool(cwd: Path) -> bool:
    """Vrai si le projet n'a pas choisi ses connecteurs lui-même."""
    return (cwd / MARQUE_HERITAGE).is_file() or not (cwd / ".mcp.json").is_file()


# Le choix des connecteurs, gardé hors du `.mcp.json` (audit M3) : ce fichier
# est désormais la *sortie* du profil, au format Claude Code, et un connecteur
# qu'on n'y distribue plus (échec d'authentification, Onyxia) ne doit pas sortir
# du choix de la personne pour autant. Format : celui des anciens « bindings »,
# `{"mcpServers": {nom: {"enabled": bool}}}`.
SELECTION = Path(".atelier") / "connecteurs-choisis.json"


def _est_au_format_interne(donnees: dict[str, Any] | None) -> bool:
    """Un ancien « binding » à drapeaux, pas une déclaration Claude Code.

    Relevé sur le pod (audit M3) : `{"mcpServers": {"filesystem": {"enabled": false}}}`
    dans le dossier de l'Assistant. Claude Code n'y lit aucun serveur.
    """
    serveurs = (donnees or {}).get("mcpServers")
    if not isinstance(serveurs, dict) or not serveurs:
        return False
    for cfg in serveurs.values():
        if not isinstance(cfg, dict):
            return False
        if set(cfg) - {"enabled"}:
            return False
    return True


def _selection_du_dossier(cwd: Path) -> dict[str, Any] | None:
    lue = _load_json_object(cwd / SELECTION)
    return lue if isinstance(lue, dict) and isinstance(lue.get("mcpServers"), dict) else None


def _ecrire_la_selection(cwd: Path, noms_actifs: dict[str, bool]) -> None:
    _atomic_write_json(
        cwd / SELECTION,
        {"mcpServers": {nom: {"enabled": bool(actif)} for nom, actif in sorted(noms_actifs.items())}},
    )


def _binding_du_dossier(cwd: Path) -> dict[str, Any] | None:
    """Le choix du projet, ou None s'il hérite du pool.

    Le choix vient de la sélection (`.atelier/connecteurs-choisis.json`), et
    les déclarations propres au projet de son `.mcp.json`. Sans sélection (un
    dossier d'avant), le `.mcp.json` sert des deux.
    """
    if (cwd / MARQUE_HERITAGE).is_file():
        return None
    fichier = _load_json_object(cwd / ".mcp.json")
    selection = _selection_du_dossier(cwd)
    if selection is None:
        return fichier
    declarations = (fichier or {}).get("mcpServers")
    declarations = declarations if isinstance(declarations, dict) else {}
    binding: dict[str, Any] = {}
    for nom, drapeau in selection["mcpServers"].items():
        actif = bool(drapeau.get("enabled", True)) if isinstance(drapeau, dict) else bool(drapeau)
        propre = declarations.get(nom)
        if actif and isinstance(propre, dict) and set(propre) - {"enabled"}:
            binding[nom] = propre
        else:
            binding[nom] = {"enabled": actif}
    return {"mcpServers": binding}


def _binding_selection(binding: dict[str, Any]) -> dict[str, bool]:
    """Nom serveur → activé dans le binding (défaut true si absent)."""
    servers = binding.get("mcpServers")
    if not isinstance(servers, dict):
        return {}
    out: dict[str, bool] = {}
    for name, raw in servers.items():
        if not isinstance(name, str) or not name.strip():
            continue
        if not isinstance(raw, dict):
            out[name] = True
            continue
        out[name] = bool(raw.get("enabled", True))
    return out


def apply_mcp_overlay(
    merged: dict[str, dict[str, Any]],
    mcp_overlay: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Les désactivations propres à une conversation — jamais celle de l'Atelier.

    Le serveur de l'Atelier est présent sur toutes les surfaces ; une
    conversation qui s'en priverait n'aurait plus ses outils `atelier_*` ici
    et les aurait dans VS Code.
    """
    out = dict(merged)
    if mcp_overlay:
        for name, active in mcp_overlay.items():
            if not isinstance(name, str) or name == SERVICE_ATELIER:
                continue
            if active is False and name in out:
                del out[name]
    return out


def slug_du_dossier(settings: AtelierSettings, cwd: Path, profil: str) -> str:
    """Le projet que wikichat et Onyxia associent à ce dossier.

    `assistant` pour le dossier de l'Assistant ; pour un projet, le nom de son
    dossier sous `projects_dir` (ou celui du dossier lui-même s'il est ailleurs).
    """
    if profil == "assistant":
        return PROJET_ASSISTANT
    try:
        relatif = Path(cwd).resolve().relative_to(settings.projects_dir.resolve())
        if relatif.parts:
            return relatif.parts[0]
    except (ValueError, OSError):
        pass
    return Path(cwd).name


def declaration_wikichat_du_profil(
    settings: AtelierSettings, profil: str, slug: str
) -> dict[str, Any]:
    """Le pont wikichat, avec le profil et le projet dans son environnement (contrat b).

    Le serveur wikichat filtre ses outils sur ces deux valeurs (équipe W) :
    un agent code n'y voit que son projet.
    """
    declaration = declaration_wikichat(settings)
    env = dict(declaration.get("env") or {})
    env[ENV_WIKICHAT_PROFIL] = profil
    env[ENV_WIKICHAT_PROJET] = slug
    return {**declaration, "env": env}


def compute_binding_merged(
    settings: AtelierSettings,
    *,
    kind: WorkspaceKind,
    cwd: Path,
) -> dict[str, dict[str, Any]]:
    """Ce que le profil donne à ce dossier, avant toute écriture (sans overlay de conversation).

    - `code` : le pool, restreint au choix du projet s'il en a fait un ;
    - `assistant` : les seuls connecteurs choisis pour l'Assistant (les autres
      passent par les méta-outils de la passerelle) ;
    - dans les deux cas : jamais un connecteur refusé en authentification à
      la dernière sonde, jamais une porte déguisée vers `/mcp`, Onyxia tel que
      le dit `onyxia_pour_projet`, et le serveur `atelier` avec l'en-tête du
      profil.

    Les valeurs sont celles du pool (secrets compris) : `configuration_du_profil`
    en fait des références.
    """
    profil = profil_du_type(kind)
    slug = slug_du_dossier(settings, cwd, profil)
    pool_entier = _pool_enabled(settings)
    directes = adresses_directes_d_onyxia(pool_entier)
    pool = _sans_echecs_d_authentification(settings, pool_entier)
    if profil == "code":
        merged = merge_session_mcp_servers(pool, _binding_du_dossier(cwd))
    else:
        global_binding = _binding_du_dossier(settings.assistant_root) or {"mcpServers": {}}
        session_binding = (
            None
            if Path(cwd).resolve() == settings.assistant_root.resolve()
            else _binding_du_dossier(cwd)
        )
        merged = merge_assistant_bindings(pool, global_binding, session_binding)
    merged = _sans_echecs_d_authentification(settings, merged)
    merged = {
        nom: cfg
        for nom, cfg in merged.items()
        if not _est_onyxia_direct(nom, cfg, directes)
        and not est_onyxia(nom)
        and not (nom != SERVICE_ATELIER and _vise_la_passerelle(cfg, settings))
    }
    onyxia = onyxia_du_profil(settings, slug, profil, pool=pool_entier)
    if onyxia is not None:
        merged[SERVICE_ONYXIA] = onyxia
    merged = integrer_wikichat(integrer_le_navigateur(merged, settings), settings)
    sortie: dict[str, dict[str, Any]] = {SERVICE_ATELIER: declaration_atelier(settings, profil, slug)}
    for nom, cfg in merged.items():
        if nom == SERVICE_ATELIER:
            continue
        if est_wikichat(nom, cfg, settings):
            sortie[nom] = declaration_wikichat_du_profil(settings, profil, slug)
        else:
            sortie[nom] = cfg
    return sortie


def configuration_du_profil(
    settings: AtelierSettings,
    *,
    profil: str,
    cwd: Path,
) -> dict[str, dict[str, Any]]:
    """LA configuration d'un dossier, la même pour l'app, VS Code et le terminal.

    Ce qu'écrit le `.mcp.json` du dossier (lu par VS Code et le terminal) et ce
    que reprend le fichier effectif d'un tour de l'Atelier, qui n'y ajoute que
    la résolution des variables de la conversation (`${ATELIER_SESSION}`).
    Jamais un secret en clair : chaque valeur du pool devient sa référence
    `${ATELIER_MCP_…}`, qu'on trouve dans `claude-env.sh`.
    """
    kind: WorkspaceKind = "assistant" if profil == "assistant" else "code"
    merged = compute_binding_merged(settings, kind=kind, cwd=cwd)
    pool = _pool_enabled(settings)
    herite = herite_du_pool(cwd) and profil == "code"
    chemin = cwd / ".mcp.json"
    existant = _load_json_object(chemin) or {}
    deja = existant.get("mcpServers")
    deja = deja if isinstance(deja, dict) and not _est_au_format_interne(existant) else {}
    sortie: dict[str, dict[str, Any]] = {}
    for nom, cfg in merged.items():
        if not isinstance(cfg, dict):
            continue
        if nom == SERVICE_ATELIER or est_wikichat(nom, cfg, settings) or (
            est_le_navigateur(nom) and navigateur_configure(settings)
        ):
            sortie[nom] = cfg
        elif not herite and isinstance(deja.get(nom), dict) and set(deja[nom]) - {"enabled"} and not est_onyxia(nom):
            config = dict(deja[nom])
            config.pop("enabled", None)
            sortie[nom] = _migrer_les_secrets(nom, config, pool.get(nom), chemin)
        else:
            sortie[nom], _ = en_references(nom, cfg)
    return sortie


def assurer_l_atelier(servers: dict[str, Any], settings: AtelierSettings) -> dict[str, Any]:
    """Le serveur de l'Atelier (`atelier_*`) est dans tout projet, sur toute surface.

    Il n'était là que si le `.mcp.json` du projet l'avait coché : mesuré le
    25 septembre, aucune des quatre surfaces n'avait les outils de l'Atelier
    pour le Lecteur Grist. Il n'est plus un choix du projet.
    """
    if SERVICE_ATELIER in servers:
        return servers
    return {SERVICE_ATELIER: declaration_atelier(settings), **servers}


def portee_utilisateur(settings: AtelierSettings) -> dict[str, Any]:
    """Ce que `~/.claude.json` déclare pour tous les dossiers : l'Atelier seul.

    Ce qui vaut pour un projet vit dans son `.mcp.json` (liaison du projet) :
    la portée utilisateur ne porte que ce qui est commun à tous, sans quoi
    VS Code et le terminal verraient des connecteurs que le projet n'a pas.
    """
    return {SERVICE_ATELIER: declaration_atelier(settings, "code")}


def merge_assistant_bindings(
    pool_enabled: dict[str, dict[str, Any]],
    global_binding: dict[str, Any] | None,
    session_binding: dict[str, Any] | None,
    *,
    mcp_overlay: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Merge pool ∩ binding global ; session = sélection explicite ou désactivations."""
    merged = merge_session_mcp_servers(pool_enabled, global_binding)
    if session_binding is not None:
        selection = _binding_selection(session_binding)
        positives = {name for name, enabled in selection.items() if enabled}
        negatives = {name for name, enabled in selection.items() if not enabled}
        if positives:
            merged = {name: merged[name] for name in positives if name in merged}
        else:
            for name in negatives:
                merged.pop(name, None)
    if mcp_overlay:
        for name, active in mcp_overlay.items():
            if not isinstance(name, str):
                continue
            if active is False and name in merged:
                del merged[name]
    return sans_amonts_gateway(merged)


def _assistant_binding_paths(settings: AtelierSettings, session_cwd: Path) -> tuple[Path, Path]:
    global_path = settings.assistant_root / ".mcp.json"
    session_path = session_cwd / ".mcp.json"
    return global_path, session_path


def merge_session_mcp_servers(
    pool_enabled: dict[str, dict[str, Any]],
    binding: dict[str, Any] | None,
    *,
    mcp_overlay: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """Intersection pool enabled ∩ binding projet ; overlay = toggles conversation (M5)."""
    if binding is None:
        merged = dict(pool_enabled)
    else:
        merged: dict[str, dict[str, Any]] = {}
        declarations = binding.get("mcpServers")
        declarations = declarations if isinstance(declarations, dict) else {}
        for name, enabled in _binding_selection(binding).items():
            if not enabled:
                continue
            propre = declarations.get(name)
            if isinstance(propre, dict) and set(propre) - {"enabled"}:
                # Le projet a sa propre déclaration : elle prime. Elle porte
                # ce que le pool ignore — l'identité de la session dans
                # l'adresse, un helper d'en-têtes — et le pool, lui, ne sert
                # ici qu'à dire ce qui est autorisé. Les confondre faisait
                # parler toutes les conversations sous un même nom.
                config = dict(declarations[name])
                config.pop("enabled", None)
                merged[name] = config
            elif name in pool_enabled:
                merged[name] = pool_enabled[name]
            elif name == SERVICE_ATELIER and isinstance(declarations.get(name), dict):
                # L'Atelier ne figure pas dans son propre pool : sa
                # déclaration fait foi, sinon il serait filtré comme un
                # serveur inconnu et le projet perdrait ce qu'il a choisi.
                merged[name] = declarations[name]
            else:
                log.debug("binding server %s absent du pool enabled — ignoré", name)

    if mcp_overlay:
        for name, active in mcp_overlay.items():
            if not isinstance(name, str):
                continue
            if active is False and name in merged:
                del merged[name]

    return sans_amonts_gateway(merged)


ENTETE_PROJET = "X-Atelier-Projet"
ENTETE_DOSSIER = "X-Atelier-Dossier"
AIDE_AUX_ENTETES = "atelier-entetes-mcp"
_SOURCE_AIDE = Path(__file__).resolve().parents[2] / "bin" / AIDE_AUX_ENTETES


def aide_aux_entetes(settings: AtelierSettings) -> Path:
    """Le `headersHelper` de l'entrée `atelier`, là où l'init le pose : `~/work/bin`."""
    return settings.work_dir / "bin" / AIDE_AUX_ENTETES


def assurer_l_aide_aux_entetes(settings: AtelierSettings) -> Path | None:
    """Pose (ou met à jour) le script dans `~/work/bin` : un déploiement peut se limiter au code."""
    cible = aide_aux_entetes(settings)
    try:
        if _SOURCE_AIDE.is_file():
            contenu = _SOURCE_AIDE.read_bytes()
            if not cible.is_file() or cible.read_bytes() != contenu:
                cible.parent.mkdir(parents=True, exist_ok=True)
                provisoire = cible.with_name(cible.name + ".nouveau")
                provisoire.write_bytes(contenu)
                provisoire.chmod(0o755)
                provisoire.replace(cible)
    except OSError as exc:
        log.warning("aide aux en-têtes non posée : %s", exc)
    return cible if cible.is_file() else None


def declaration_atelier(
    settings: AtelierSettings, profil: str = "code", slug: str | None = None
) -> dict[str, Any]:
    """Comment un agent joint la passerelle de l'Atelier.

    Elle n'est pas dans le pool : l'y mettre ferait sonder l'Atelier par
    lui-même au démarrage. Elle est proposée directement au binding d'un
    projet, comme un service que la maison fournit.

    La clé passe par l'environnement du processus agent, jamais par ce
    fichier — il vit dans le dossier du projet.

    La conversation aussi, par référence : `X-Atelier-Conversation` dit aux
    outils `atelier_artefact_*` qui les appelle, sans que l'agent ait à le
    répéter en argument. Le fichier effectif d'un tour la résout
    (`resoudre_les_variables`), et un client hors conversation — VS Code, qui
    lit le `.mcp.json` du projet — tombe sur le repli « poste ».

    Hors d'un tour de l'Atelier, `ATELIER_SESSION` manque : le `headersHelper`
    (`bin/atelier-entetes-mcp`) donne alors l'identifiant de la conversation
    du `claude` qui se connecte. La forme `${ATELIER_SESSION:-${…}}` ne
    marche pas : Claude Code développe les en-têtes en un seul passage, et son
    repli ne peut pas contenir `}` (relevé dans le binaire 2.1.282).

    Et le profil (contrat a) : `code` pour un agent de projet, `assistant` pour
    l'Assistant. Le serveur `atelier` déduit le profil de la fiche de la
    conversation ; pour une conversation qu'il ne connaît pas, en `code`, il
    borne ses outils au projet que dit `X-Atelier-Projet`.
    """
    entetes = {
        "Authorization": "Bearer ${ATELIER_MCP_KEY}",
        ENTETE_CONVERSATION: _CONVERSATION_PAR_REFERENCE,
        ENTETE_PROFIL: "assistant" if profil == "assistant" else "code",
    }
    if profil != "assistant" and slug:
        entetes[ENTETE_PROJET] = slug
    if profil == "assistant":
        # Règle de l'équipe A pour une conversation que le serveur ne connaît
        # pas (VS Code, terminal) : `assistant` annoncé, le dossier de
        # l'Assistant, et pas de projet, donnent le profil `assistant`.
        entetes[ENTETE_DOSSIER] = settings.assistant_root.as_posix()
    return {
        "type": "http",
        "url": f"http://127.0.0.1:{settings.port}/mcp",
        "headers": entetes,
        "headersHelper": f"sh {shlex.quote(aide_aux_entetes(settings).as_posix())}",
    }


_CONVERSATION_PAR_REFERENCE = "${ATELIER_SESSION:-" + CONVERSATION_HORS_ATELIER + "}"


def integrer_l_atelier(servers: dict[str, Any]) -> dict[str, Any]:
    """La déclaration de l'Atelier porte l'en-tête de conversation, même ancienne.

    Un `.mcp.json` de projet écrit avant l'en-tête ne le porte pas, et le
    binding y prime sur tout : sans ce complément, ses conversations
    appelleraient les outils d'artefact sans auteur jusqu'à ce qu'on
    réenregistre ses connecteurs. On n'ajoute que l'en-tête manquant ; le
    reste de la déclaration reste tel que le projet l'a écrit.
    """
    cfg = servers.get(SERVICE_ATELIER)
    if not isinstance(cfg, dict):
        return servers
    entetes = cfg.get("headers")
    entetes = dict(entetes) if isinstance(entetes, dict) else {}
    if any(str(k).lower() == ENTETE_CONVERSATION.lower() for k in entetes):
        return servers
    entetes[ENTETE_CONVERSATION] = _CONVERSATION_PAR_REFERENCE
    sortie = dict(servers)
    sortie[SERVICE_ATELIER] = {**cfg, "headers": entetes}
    return sortie


def integrer_le_navigateur(
    servers: dict[str, Any],
    settings: AtelierSettings,
) -> dict[str, Any]:
    """Remplace la déclaration du navigateur de l'Atelier par celle du lanceur.

    Seule l'entrée `SERVICE_CHROME` est touchée, et seulement si le
    navigateur n'est pas éteint : un connecteur tiers qui parle de Chrome
    reste tel que la personne l'a écrit. Une ancienne déclaration HTTP (le
    service distant, son jeton, son en-tête) devient celle du lanceur stdio.
    """
    if not navigateur_configure(settings):
        return dict(servers)
    sortie: dict[str, Any] = {}
    for nom, cfg in servers.items():
        if est_le_navigateur(nom):
            sortie[nom] = declaration_chrome(settings)
        else:
            sortie[nom] = cfg
    return sortie


# Les variables qu'un connecteur peut demander dans son adresse. Le fichier
# effectif est reconstruit à chaque tour, et l'Atelier connaît alors la
# conversation : il peut donc les résoudre, ce que le client ne saurait pas faire.
#
# C'est volontairement une demande, pas un cadeau. Ajouter l'identité de la
# conversation à l'adresse de tous les connecteurs l'enverrait à des services
# tiers qui n'en ont que faire — mcp.data.gouv.fr n'a pas à savoir qui lui parle.
# Un service ne la reçoit que s'il l'a écrite dans son adresse.
#
# La passerelle de l'Atelier en a besoin : c'est par là que ses outils
# `atelier_*` savent quelle conversation les appelle.
VARIABLES_CONNUES = ("ATELIER_SESSION", "ATELIER_AGENT")

_VARIABLE = re.compile(r"\$\{([A-Z_]+)(?::-([^}]*))?\}")


def resoudre_les_variables(config: dict[str, Any], *, session: str, agent: str) -> dict[str, Any]:
    """Remplit dans l'adresse les variables que l'Atelier sait renseigner.

    La syntaxe est celle du shell, `${NOM}` ou `${NOM:-repli}`, parce que c'est
    déjà celle du fichier de projet et qu'un connecteur écrit à la main s'y lit
    sans mode d'emploi.

    Une variable qu'on ne connaît pas est laissée telle quelle plutôt qu'effacée :
    une adresse visiblement fautive se répare, une adresse silencieusement vidée
    de son identité donne un service qui mélange deux conversations sans le dire.
    """
    valeurs = {"ATELIER_SESSION": session, "ATELIER_AGENT": agent}

    def remplaceur(encoder: bool) -> Any:
        def remplacer(m: re.Match[str]) -> str:
            nom, repli = m.group(1), m.group(2)
            if nom in valeurs and valeurs[nom]:
                return quote(valeurs[nom], safe="") if encoder else valeurs[nom]
            # Dans un en-tête, une variable qu'on ne fournit pas (le jeton
            # d'un connecteur, `${ATELIER_MCP_…}`) reste au client, repli
            # compris : c'est lui qui la développe depuis son environnement.
            if not encoder and nom not in VARIABLES_CONNUES:
                return m.group(0)
            if repli is not None:
                return quote(repli, safe="") if encoder else repli
            return m.group(0)

        return remplacer

    sortie = dict(config)
    change = False
    url = str(config.get("url") or "")
    if "${" in url:
        resolue = _VARIABLE.sub(remplaceur(True), url)
        if resolue != url:
            sortie["url"] = resolue
            change = True
    # Les en-têtes aussi : c'est par là que la passerelle de l'Atelier reçoit la
    # conversation. Pas d'encodage d'URL dans un en-tête.
    entetes = config.get("headers")
    if isinstance(entetes, dict) and any("${" in str(v) for v in entetes.values()):
        nouveaux = {
            k: _VARIABLE.sub(remplaceur(False), v) if isinstance(v, str) else v
            for k, v in entetes.items()
        }
        if nouveaux != entetes:
            sortie["headers"] = nouveaux
            change = True
    return sortie if change else config


def _avec_identite(config: dict[str, Any], nom: str, wikichat_url: str) -> dict[str, Any]:
    """Inscrit l'identité de la session dans l'adresse du coordinateur.

    Le fichier de projet porte `?agent=${WIKICHAT_AGENT:-}`, à charge pour le
    client d'y substituer la variable. On ne s'y fie pas : le fichier
    effectif est reconstruit à chaque tour et nous connaissons alors le nom.
    L'écrire résolu enlève une dépendance à un détail d'implémentation, et
    un agent qui se présente sans nom perd sa mémoire et son courrier.
    """
    if not nom:
        return config
    url = str(config.get("url") or "")
    if not url or not _est_le_coordinateur(url, wikichat_url):
        return config
    base, _, requete = url.partition("?")
    garde = [
        p
        for p in requete.split("&")
        if p and not p.startswith("agent=")
    ]
    garde.insert(0, f"agent={quote(nom, safe='')}")
    sortie = dict(config)
    sortie["url"] = base + "?" + "&".join(garde)
    return sortie


# La même machine s'écrit de plusieurs façons. Comparer les adresses sans le
# savoir fait manquer une correspondance pourtant évidente : le binding d'un
# projet dit « localhost », la configuration du service dit « 127.0.0.1 ».
_HOTES_LOCAUX = {"localhost", "127.0.0.1", "[::1]", "::1", "0.0.0.0"}


def _hote_normalise(url: str) -> str:
    autorite = url.split("://", 1)[-1].split("/", 1)[0]
    hote, _, port = autorite.rpartition(":")
    if not hote:
        hote, port = autorite, ""
    if hote.lower() in _HOTES_LOCAUX:
        hote = "local"
    return f"{hote.lower()}:{port}"


def _est_le_coordinateur(url: str, wikichat_url: str) -> bool:
    if not wikichat_url or not url:
        return False
    return _hote_normalise(url) == _hote_normalise(wikichat_url)


def project_binding_state(
    settings: AtelierSettings,
    cwd: Path,
) -> list[dict[str, Any]]:
    """Ce que le pool propose au projet, et ce que le projet en retient.

    Sans choix, un projet hérite du pool entier : c'est l'absence de choix,
    pas un choix vide. Un connecteur refusé en authentification à la dernière
    sonde est signalé (`echec_authentification`) : choisi ou non, il n'est
    pas distribué.
    """
    pool = _pool_enabled(settings)
    binding = _binding_du_dossier(cwd)
    selection = _binding_selection(binding) if binding is not None else {}
    herite = binding is None
    echecs = connecteurs_en_echec_d_authentification(settings)
    from mcp_gateway.atelier.gateway_tools import nature_service

    etat: list[dict[str, Any]] = []
    for name in sorted(pool.keys()):
        nature = nature_service(pool[name], settings.wikichat_url, nom=name)
        ligne: dict[str, Any] = {
            "id": name,
            "name": nature["group"] if nature["system"] else name,
            "id_technique": name,
            "active": True if herite else selection.get(name, False),
            "group": nature["group"],
            "system": nature["system"],
            "scope": nature["scope"],
        }
        if name in echecs:
            ligne["echec_authentification"] = echecs[name].get("code", 401)
            ligne["distribue"] = False
        etat.append(ligne)
    # La passerelle de l'Atelier n'est pas dans le pool. Elle est dans tout
    # projet, sans case à cocher ; ce qu'on affiche est ce que l'agent reçoit
    # — lu au même endroit que le fichier effectif, pas supposé.
    try:
        presente = SERVICE_ATELIER in compute_binding_merged(settings, kind="code", cwd=cwd)
    except OSError:
        presente = False
    etat.insert(
        0,
        {
            "id": SERVICE_ATELIER,
            "name": "Accès aux outils",
            "id_technique": SERVICE_ATELIER,
            "active": presente,
            "fixe": True,
            "group": "Accès aux outils",
            "system": True,
            "scope": [],
        },
    )
    return etat


def write_project_binding(
    settings: AtelierSettings,
    cwd: Path,
    actifs: list[str],
) -> list[dict[str, Any]]:
    """Fixe les connecteurs choisis pour un projet, puis écrit sa configuration.

    Le choix va dans `.atelier/connecteurs-choisis.json` ; le `.mcp.json` en est
    la sortie, calculée par le profil (`lier_le_projet`). Une déclaration
    propre au projet (un helper d'en-têtes, une variable d'environnement) y
    reste : elle prime sur celle du pool, dont elle porte souvent ce qu'il
    ignore. Ses secrets en clair sont migrés en références quand le pool les
    connaît — le fichier vit dans le dossier du projet, qui se commite.
    """
    pool = _pool_enabled(settings)
    chemin = cwd / ".mcp.json"
    existant = _load_json_object(chemin) or {}
    deja = existant.get("mcpServers")
    deja = deja if isinstance(deja, dict) and not _est_au_format_interne(existant) else {}
    choisis = [
        n for n in dict.fromkeys(actifs) if n != SERVICE_ATELIER and not est_alias_onyxia_deguise(n)
    ]
    # Les déclarations propres au projet des connecteurs choisis restent dans
    # `.mcp.json` : c'est là que `configuration_du_profil` les reprend.
    propres: dict[str, Any] = {}
    for nom in choisis:
        cfg = deja.get(nom)
        if not isinstance(cfg, dict) or not set(cfg) - {"enabled"}:
            continue
        if est_wikichat(nom, cfg, settings) or est_le_navigateur(nom):
            continue
        config = dict(cfg)
        config.pop("enabled", None)
        propres[nom] = _migrer_les_secrets(nom, config, pool.get(nom), chemin)
    existant["mcpServers"] = propres
    _atomic_write_json(chemin, existant)
    _ecrire_la_selection(cwd, {nom: True for nom in choisis})
    # Un choix explicite : le projet cesse de suivre le pool.
    (cwd / MARQUE_HERITAGE).unlink(missing_ok=True)
    lier_le_projet(settings, cwd, kind="code")
    return project_binding_state(settings, cwd)


def lier_le_projet(
    settings: AtelierSettings,
    cwd: Path,
    *,
    kind: WorkspaceKind = "code",
) -> list[str]:
    """Écrit dans le `.mcp.json` du dossier ce que l'agent y recevra, partout.

    Le contenu est `configuration_du_profil` : la même chose que le fichier
    effectif d'un tour de l'Atelier. VS Code et le terminal ne lisent que
    `~/.claude.json` et ce `.mcp.json` ; on y écrit donc cet ensemble — en
    références, jamais en clair — et on l'approuve dans `~/.claude.json`
    (`enabledMcpjsonServers`).

    Un ancien « binding » au format interne (drapeaux `enabled`, le dossier
    de l'Assistant) est d'abord rangé comme sélection, puis remplacé par une
    vraie déclaration Claude Code (audit M3).

    Un projet de code qui hérite du pool garde sa marque et suit le pool à
    chaque liaison. Rend les noms des serveurs du dossier.
    """
    cwd.mkdir(parents=True, exist_ok=True)
    profil = profil_du_type(kind)
    chemin = cwd / ".mcp.json"
    existant = _load_json_object(chemin) or {}
    serveurs_lus = existant.get("mcpServers")
    if _selection_du_dossier(cwd) is None and isinstance(serveurs_lus, dict):
        if _est_au_format_interne(existant):
            _ecrire_la_selection(
                cwd,
                {nom: bool(cfg.get("enabled", True)) for nom, cfg in serveurs_lus.items() if isinstance(cfg, dict)},
            )
        elif profil == "code" and not herite_du_pool(cwd):
            # Un projet d'avant la sélection : son choix est ce que son
            # `.mcp.json` déclare. On le range, pour qu'un connecteur retiré
            # de la sortie (échec d'authentification) ne sorte pas du choix.
            _ecrire_la_selection(
                cwd,
                {
                    nom: bool(cfg.get("enabled", True)) if isinstance(cfg, dict) else True
                    for nom, cfg in serveurs_lus.items()
                    if nom != SERVICE_ATELIER
                },
            )
    herite = profil == "code" and herite_du_pool(cwd)
    ecrits = configuration_du_profil(settings, profil=profil, cwd=cwd)
    existant = _load_json_object(chemin) or {}
    if ecrits != existant.get("mcpServers") or _est_au_format_interne(existant):
        existant["mcpServers"] = ecrits
        _atomic_write_json(chemin, existant)
        _proteger_du_depot(cwd)
    if herite:
        marque = cwd / MARQUE_HERITAGE
        marque.parent.mkdir(parents=True, exist_ok=True)
        if not marque.is_file():
            marque.write_text(
                "Ce projet hérite des connecteurs du pool : l'Atelier réécrit .mcp.json"
                " quand le pool change. Choisir ses connecteurs dans l'Atelier retire"
                " cette marque.\n",
                encoding="utf-8",
            )
    approuver_les_serveurs_du_projet(cwd, sorted(ecrits), adresses_directes_d_onyxia(_pool_enabled(settings)))
    approuver_dans_les_reglages_du_dossier(cwd, sorted(ecrits))
    # Le mode aussi, le même sur toutes les surfaces : sans défaut de projet,
    # le CLI partirait en `default` dans VS Code et au terminal.
    from mcp_gateway.atelier.modes_permission import assurer_le_defaut_du_projet

    assurer_le_defaut_du_projet(settings, cwd)
    return sorted(ecrits)


def dossiers_de_l_assistant(settings: AtelierSettings) -> list[Path]:
    """Le dossier de l'Assistant et ceux de ses conversations (audit M3)."""
    dossiers: list[Path] = []
    racine = settings.assistant_root
    if racine.is_dir():
        dossiers.append(racine)
    sessions = settings.assistant_sessions_dir
    if sessions.is_dir():
        dossiers.extend(
            d
            for d in sorted(sessions.iterdir())
            if d.is_dir() and not d.is_symlink() and not d.name.startswith(".")
        )
    return dossiers


def lier_tous_les_projets(settings: AtelierSettings) -> int:
    """Relie chaque dossier de projet, et ceux de l'Assistant (démarrage, pool modifié).

    L'Assistant n'était relié qu'à son tour suivant : ses dossiers gardaient un
    « binding » que Claude Code ne lit pas, et VS Code comme le terminal y
    perdaient wikichat (audit M3). Rend le nombre de dossiers reliés.
    """
    n = 0
    racine = settings.projects_dir
    if racine.is_dir():
        for dossier in sorted(racine.iterdir()):
            if not dossier.is_dir() or dossier.is_symlink() or dossier.name.startswith("."):
                continue
            try:
                lier_le_projet(settings, dossier)
                n += 1
            except OSError as exc:
                log.warning("liaison de %s impossible : %s", dossier.name, exc)
    for dossier in dossiers_de_l_assistant(settings):
        try:
            lier_le_projet(settings, dossier, kind="assistant")
            n += 1
        except OSError as exc:
            log.warning("liaison de l'Assistant (%s) impossible : %s", dossier, exc)
    return n


# Les serveurs d'une époque révolue, que `~/.claude.json` garde dans la portée
# locale d'un projet et que l'Atelier ne gère pas. Mesuré le 25/09 (audit M4) :
# `chrome-devtools` visait l'ancien service `http://127.0.0.1:3000/mcp`, en
# échec dans VS Code et au terminal, à côté du vrai `chrome-devtools-mcp`.
SERVEURS_OBSOLETES = frozenset({"chrome-devtools"})


def retirer_les_serveurs_obsoletes(data: dict[str, Any], directes: set[str] | None = None) -> list[str]:
    """Retire des portées de projet de `~/.claude.json` les serveurs obsolètes.

    Les anciens serveurs (`SERVEURS_OBSOLETES`), et toute entrée qui joint
    Onyxia en direct (`directes` : ses adresses dans le pool) : plus personne
    ne le joint sans le mandataire. Rend `dossier:nom` pour chaque retrait. Le
    reste du fichier n'est pas touché.
    """
    directes = directes or set()
    retires: list[str] = []
    projets = data.get("projects")
    if not isinstance(projets, dict):
        return retires
    for dossier, entree in projets.items():
        if not isinstance(entree, dict):
            continue
        serveurs = entree.get("mcpServers")
        if not isinstance(serveurs, dict):
            continue
        for nom in [
            n for n, c in serveurs.items() if n in SERVEURS_OBSOLETES or _est_onyxia_direct(n, c, directes)
        ]:
            del serveurs[nom]
            retires.append(f"{dossier}:{nom}")
        if not serveurs:
            entree.pop("mcpServers", None)
    return retires


def approuver_les_serveurs_du_projet(dossier: Path, noms: list[str], directes: set[str] | None = None) -> bool:
    """Approuve dans `~/.claude.json` les serveurs du `.mcp.json` du dossier.

    Sans approbation, Claude Code demande à l'ouverture (ou ignore en `-p`)
    les serveurs d'un `.mcp.json`. On retire aussi de `disabledMcpServers` —
    que l'Atelier y figeait à chaque ouverture dans VS Code — les serveurs que
    le projet a choisis : ils doivent être actifs partout. Et les serveurs
    obsolètes de la portée locale du dossier (`SERVEURS_OBSOLETES`).

    Un fichier illisible n'est pas écrasé : il porte l'identité de la machine
    et l'historique des projets. Rend vrai si le fichier a changé.
    """
    chemin = Path.home() / ".claude.json"
    data: dict[str, Any] = {}
    if chemin.is_file():
        try:
            charge = json.loads(chemin.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return False
        if not isinstance(charge, dict):
            return False
        data = charge
    projets = data.setdefault("projects", {})
    if not isinstance(projets, dict):
        return False
    entree = projets.setdefault(str(dossier), {})
    if not isinstance(entree, dict):
        return False
    avant = json.dumps(entree, sort_keys=True)
    entree["enabledMcpjsonServers"] = sorted(set(noms))
    for cle in ("disabledMcpServers", "disabledMcpjsonServers"):
        liste = entree.get(cle)
        if isinstance(liste, list):
            reste = [n for n in liste if n not in noms]
            if reste:
                entree[cle] = reste
            else:
                entree.pop(cle, None)
    retirer_les_serveurs_obsoletes({"projects": {str(dossier): entree}}, directes)
    if json.dumps(entree, sort_keys=True) == avant:
        return False
    _ecrire_claude_json(chemin, data)
    return True


def approuver_dans_les_reglages_du_dossier(dossier: Path, noms: list[str]) -> bool:
    """Écrit la même approbation dans `.claude/settings.local.json` du dossier.

    `enabledMcpjsonServers` y est une clé de réglages que Claude Code réunit
    à celle de `~/.claude.json`. Mesuré sur le pod le 26/09 : une ancienne
    liste y restait (`Onyxia`, `n8n`, des noms absents du `.mcp.json`), et
    l'entrée d'un projet dans `~/.claude.json` peut disparaître quand un
    `claude` en cours réécrit ce fichier avec sa propre copie. Ici, la liste
    est exactement celle du `.mcp.json`, et un nom qu'on y approuve sort de
    `disabledMcpjsonServers`. Le reste du fichier est gardé ; un fichier
    illisible n'est pas touché. Rend vrai si le fichier a changé.
    """
    chemin = dossier / ".claude" / "settings.local.json"
    donnees: dict[str, Any] = {}
    if chemin.is_file():
        lu = _load_json_object(chemin)
        if lu is None:
            return False
        donnees = lu
    avant = json.dumps(donnees, sort_keys=True)
    donnees["enabledMcpjsonServers"] = sorted(set(noms))
    refuses = donnees.get("disabledMcpjsonServers")
    if isinstance(refuses, list):
        reste = [n for n in refuses if n not in noms]
        if reste:
            donnees["disabledMcpjsonServers"] = reste
        else:
            donnees.pop("disabledMcpjsonServers", None)
    if json.dumps(donnees, sort_keys=True) == avant:
        return False
    _atomic_write_json(chemin, donnees)
    return True


def _ecrire_claude_json(chemin: Path, data: dict[str, Any]) -> None:
    tmp = chemin.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(chemin)
    try:
        chemin.chmod(0o600)
    except OSError:
        pass


def _migrer_les_secrets(
    nom: str,
    config: dict[str, Any],
    du_pool: dict[str, Any] | None,
    chemin: Path,
) -> dict[str, Any]:
    """Remplace par leur référence les secrets en clair qu'on sait fournir.

    Un en-tête que le pool déclare pour ce service a sa variable : l'Atelier
    la remplit, la valeur en clair peut partir. Un en-tête que le pool ne
    connaît pas a été écrit par la personne, pour un service que nous ne
    servons pas : l'écraser le casserait, et nous n'aurions rien à mettre
    dans la variable. On le laisse, et on le dit.
    """
    references: dict[str, Any] = {}
    if isinstance(du_pool, dict):
        references, _ = en_references(nom, du_pool)
    sortie = dict(config)
    for champ in ("headers", "env"):
        bloc = config.get(champ)
        if not isinstance(bloc, dict):
            continue
        connus = references.get(champ) if isinstance(references.get(champ), dict) else {}
        # La casse d'un en-tête HTTP ne compte pas : `authorization` écrit à
        # la main désigne bien l'`Authorization` du pool.
        par_nom = {str(k).lower(): v for k, v in connus.items()}
        nouveau = dict(bloc)
        for cle in secrets_en_clair({champ: bloc}):
            nom_cle = cle.split(".", 1)[1]
            reference = par_nom.get(nom_cle.lower())
            if est_une_reference(reference):
                nouveau[nom_cle] = reference
            else:
                log.warning(
                    "secret en clair laissé dans %s : %s.%s (inconnu du pool,"
                    " écrit hors de l'Atelier)",
                    chemin,
                    nom,
                    cle,
                )
        sortie[champ] = nouveau
    # Les arguments (`--header "Authorization: Bearer …"` d'un pont stdio) :
    # un secret dont le pool fournit la même valeur devient sa référence ;
    # un autre reste, et se signale comme un en-tête inconnu.
    args = config.get("args")
    if isinstance(args, list):
        _, valeurs = en_references(nom, du_pool) if isinstance(du_pool, dict) else ({}, {})
        sortie["args"] = en_references_fournies(nom, {"args": args}, valeurs)["args"]
        for cle in secrets_en_clair({"args": sortie["args"]}):
            log.warning(
                "secret en clair laissé dans %s : %s.%s (inconnu du pool,"
                " écrit hors de l'Atelier)",
                chemin,
                nom,
                cle,
            )
    return sortie


def _proteger_du_depot(cwd: Path) -> None:
    """Garde `.mcp.json` hors du dépôt, en plus de n'y rien mettre de secret.

    Le .gitignore est complété, pas réécrit. Un fichier déjà suivi le reste :
    le dé-suivre réécrirait l'histoire de la personne sans qu'elle l'ait
    demandé. On le signale, ici et dans l'état du dépôt.
    """
    if not (cwd / ".git").is_dir():
        return
    from mcp_gateway.atelier import git_repos

    try:
        git_repos.completer_le_gitignore(cwd)
        if git_repos.mcp_json_suivi(cwd):
            log.warning(
                "%s/.mcp.json est suivi par git : le .gitignore ne l'en retire pas."
                " Ses secrets sont désormais des références, mais les versions"
                " déjà commitées peuvent en porter — `git rm --cached .mcp.json`"
                " et une rotation des jetons si elles sont parties.",
                cwd,
            )
    except OSError as exc:
        log.warning("protection de .mcp.json impossible dans %s : %s", cwd, exc)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def _pool_enabled(settings: AtelierSettings) -> dict[str, dict[str, Any]]:
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        return store.enabled_mcp_servers()
    finally:
        conn.close()


def materialize_session_mcp(
    settings: AtelierSettings,
    session_id: str,
    *,
    kind: WorkspaceKind,
    cwd: Path,
    mcp_overlay: dict[str, Any] | None = None,
    agent_name: str = "",
) -> Path:
    """Le fichier effectif d'un tour : `configuration_du_profil`, plus la conversation.

    Même source que le `.mcp.json` du dossier (VS Code, terminal) ; s'y
    ajoutent seulement les désactivations propres à la conversation
    (`mcp_overlay`, jamais celle de l'Atelier) et la résolution des variables
    qu'on connaît ici (`${ATELIER_SESSION}`).
    """
    # Plus de sélection propre à une conversation : VS Code lit un `.mcp.json`
    # par dossier et ne saurait pas la suivre. Le « + » du fil règle le choix
    # du projet (`sessions.patch_mcp_overlay`) ; `mcp_overlay` est ignoré.
    del mcp_overlay
    binding_merged = configuration_du_profil(settings, profil=profil_du_type(kind), cwd=cwd)
    merged = dict(binding_merged)
    if agent_name:
        merged = {
            nom: _avec_identite(cfg, agent_name, settings.wikichat_url)
            for nom, cfg in merged.items()
        }
    # Puis les variables que le connecteur a demandées lui-même. Après l'identité
    # du coordinateur, pour qu'un service qui écrirait les deux obtienne les deux.
    merged = {
        nom: resoudre_les_variables(cfg, session=session_id, agent=agent_name)
        for nom, cfg in merged.items()
    }
    # Le fichier effectif ne porte plus de secret en clair : chaque valeur
    # que l'environnement du tour fournit devient sa référence, que le CLI
    # développe (mesuré sur le pod pour `--mcp-config`). Les valeurs viennent
    # du fichier d'environnement unique, régénéré ici au besoin.
    from mcp_gateway.atelier.env_secrets import ecrire_le_fichier

    valeurs = ecrire_le_fichier(settings)
    merged = {
        nom: en_references_fournies(nom, cfg, valeurs) if isinstance(cfg, dict) else cfg
        for nom, cfg in merged.items()
    }
    cfg_path = settings.mcp_effective_dir / f"{session_id}.json"
    _atomic_write_json(cfg_path, {"mcpServers": merged})
    log.info(
        "session mcp %s kind=%s cwd=%s binding=%s effective=%s",
        session_id,
        kind,
        cwd,
        sorted(binding_merged),
        sorted(merged),
    )
    return cfg_path


def materialize_mcp_config(settings: AtelierSettings) -> Path:
    """Écrit `claude-mcp.json` depuis gateway.db (enabled registry) + sync `.claude`."""
    settings.mcp_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        servers = integrer_wikichat(
            integrer_le_navigateur(sans_amonts_gateway(store.enabled_mcp_servers()), settings),
            settings,
        )
    finally:
        conn.close()

    assurer_l_aide_aux_entetes(settings)
    # Le fichier du pool porte aussi l'entrée `atelier` (profil `code`, sans
    # projet) : c'est celui d'un tour lancé sans fichier effectif.
    payload = {"mcpServers": {SERVICE_ATELIER: declaration_atelier(settings, "code"), **pour_le_home(servers)}}
    cfg_path = settings.mcp_config_path
    _atomic_write_json(cfg_path, payload)

    # La portée utilisateur ne porte que l'Atelier : le reste appartient au
    # `.mcp.json` de chaque projet (liaison), pour que VS Code et le terminal
    # voient les mêmes connecteurs que le tour de l'Atelier.
    commun = portee_utilisateur(settings)
    directes = adresses_directes_d_onyxia(servers)
    _merge_user_claude_json(settings.work_dir / ".claude.json", commun, directes)
    home_claude = Path.home() / ".claude.json"
    try:
        _merge_user_claude_json(home_claude, commun, directes)
    except OSError:
        pass

    # Le pool a pu changer : les valeurs des références aussi, et les
    # projets qui en héritent.
    from mcp_gateway.atelier.env_secrets import ecrire_le_fichier

    ecrire_le_fichier(settings)
    lier_tous_les_projets(settings)

    durable_dir = settings.work_dir / ".claude"
    durable_dir.mkdir(parents=True, exist_ok=True)
    (durable_dir / "mcp-config.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    if settings.mcp_registry_path.is_file():
        log.warning(
            "registry.json legacy encore présent — source canonique = %s",
            settings.gateway_db_path,
        )

    return cfg_path


def _merge_user_claude_json(
    path: Path, servers: dict[str, dict[str, Any]], directes: set[str] | None = None
) -> None:
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except json.JSONDecodeError:
            data = {}
    data["mcpServers"] = pour_le_home(servers)
    # Les serveurs obsolètes des portées de projet (audit M4) partent à chaque
    # matérialisation, pas seulement quand on ouvre le projet.
    for retrait in retirer_les_serveurs_obsoletes(data, directes):
        log.info("serveur obsolète retiré de %s : %s", path, retrait)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)
    # Ce fichier portait les jetons des connecteurs en clair — celui de n8n y
    # était, en 644, affiché par `claude mcp list`. Il n'y a plus que des
    # références (`pour_le_home`) ; le 600 reste, pour les adresses et pour
    # ce que d'autres mains y écriraient.
    try:
        path.chmod(0o600)
    except OSError:
        pass


def sync_summary(settings: AtelierSettings) -> dict[str, Any]:
    path = materialize_mcp_config(settings)
    conn = connect(settings.gateway_db_path)
    try:
        store = IntegratedMcpStore(conn)
        all_servers = store.list_servers(mask=True)
    finally:
        conn.close()
    enabled = [n for n, e in all_servers.items() if e.get("enabled", True)]
    return {
        "mcp_config": str(path),
        "gateway_db": str(settings.gateway_db_path),
        "total": len(all_servers),
        "enabled": enabled,
        "disabled": [n for n in all_servers if n not in enabled],
    }
