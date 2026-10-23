"""Les connecteurs : le pool de la passerelle, et le choix de chaque projet.

- `atelier_connecteur_ajouter` (engageante) ajoute un connecteur au pool
  (`gateway.db`, le registre que lit `UpstreamPool` et que montre la page
  Connecteurs), régénère les configurations (`mcp_sync.sync_summary`, la même
  que `PUT /v1/mcp/servers/<nom>`) et le sonde. Ouvrir un service à tous les
  agents engage : aperçu, puis « Oui ».
- `atelier_connecteur_retirer` (réversible) le met hors service sans effacer
  sa déclaration : il sort de toutes les configurations, et « Annuler » le
  remet tel qu'il était, secret compris, sans que le secret passe par un
  argument.
- `atelier_connecteur_choisir` (réversible) fixe les connecteurs d'un projet
  par `mcp_sync.write_project_binding`, qui passe par la fonction unique de
  profil (`configuration_du_profil`) ; ou le remet à hériter du pool.
- `atelier_connecteur_accorder` (réservée, jamais exposée aux modèles) donne
  à un connecteur un secret **désigné par son nom** : un fichier du dossier des
  secrets, lu par le serveur. Aucune valeur ne passe jamais par un argument.

Un connecteur ajouté par commande ne porte aucun secret : un en-tête ou une
variable qui s'annonce comme tel, une référence `${…}` ou une adresse qui
porte un jeton sont refusés, avec le chemin à suivre.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from mcp_gateway.atelier import projets_aide
from mcp_gateway.atelier.commandes import structure
from mcp_gateway.atelier.commandes.catalogue import Catalogue
from mcp_gateway.atelier.commandes.creations import booleen, liste_de_noms, services_de, texte
from mcp_gateway.atelier.commandes.journal import maintenant
from mcp_gateway.atelier.commandes.modele import (
    ENGAGEANTE,
    RESERVEE,
    REVERSIBLE,
    Commande,
    Contexte,
    Effet,
    Refus,
)

log = logging.getLogger("atelier.commandes")

AJOUTER = "atelier_connecteur_ajouter"
RETIRER = "atelier_connecteur_retirer"
CHOISIR = "atelier_connecteur_choisir"
ACCORDER = "atelier_connecteur_accorder"
RENOUVELER = "atelier_connecteur_renouveler"
MODIFIER = "atelier_connecteur_modifier"

# Des noms que l'Atelier tient lui-même : ils ne s'ajoutent ni ne se retirent par commande.
NOMS_TENUS = frozenset({"atelier", "wikichat", "Onyxia"})
_MARQUE = "atelier"
_SCHEMAS = ("Bearer", "Token", "Basic")
_CHAMP_SECRET = re.compile(r"^(headers|env)\.([A-Za-z0-9_.-]{1,64})$")


# La clé de l'Atelier dans une entrée du pool : ses vues relayées (`apps/bureaux.py`,
# équipe B). Posée par la personne seule, jamais rendue à un modèle.
CLE_ATELIER = "atelier"


def sans_cle_atelier(cfg: dict[str, Any]) -> dict[str, Any]:
    """La déclaration telle qu'on la rend : sans la clé `atelier`, qui dit seulement combien de vues."""
    sortie = {k: v for k, v in cfg.items() if k != CLE_ATELIER}
    vues = (cfg.get(CLE_ATELIER) or {}).get("vues") if isinstance(cfg.get(CLE_ATELIER), dict) else None
    if isinstance(vues, list):
        sortie["vues_relayees"] = len(vues)
    return sortie


def _secrets_de_l_adresse(url: str) -> list[str]:
    from mcp_gateway.atelier.mcp_secrets import est_un_nom_secret

    parties = urlsplit(url)
    trouves = []
    if parties.username or parties.password:
        trouves.append("url (identifiants)")
    for cle, _ in parse_qsl(parties.query, keep_blank_values=True):
        if est_un_nom_secret(cle):
            trouves.append(f"url ?{cle}=")
    return trouves


def inscrire_les_connecteurs(app: Any, catalogue: Catalogue) -> None:
    settings = app.state.settings

    def ouvrir() -> Any:
        from mcp_gateway.db import connect

        return connect(settings.gateway_db_path)

    def entree(conn: Any, nom: str) -> Any:
        from mcp_gateway.registry import get_registry_server

        return get_registry_server(conn, nom)

    def est_actif(conn: Any, nom: str) -> bool:
        from mcp_gateway.server_enable import is_registry_enabled

        return bool(is_registry_enabled(conn, nom))

    def activer(conn: Any, nom: str, actif: bool) -> None:
        from mcp_gateway.server_enable import SCOPE_REGISTRY, set_enabled

        set_enabled(conn, SCOPE_REGISTRY, nom, actif)

    def marquer(conn: Any, nom: str, marque: dict[str, Any] | None) -> None:
        """Pose (ou retire) la marque de l'Atelier dans `_metadata`, sans toucher au reste."""
        from mcp_gateway.registry import update_registry_server_config

        e = entree(conn, nom)
        if e is None:
            raise Refus(f"connecteur inconnu : {nom}")
        cfg = dict(e.config)
        meta = dict(cfg.get("_metadata") or {})
        atelier = dict(meta.get(_MARQUE) or {})
        if marque is None:
            atelier.pop("retire", None)
        else:
            atelier.update(marque)
        meta[_MARQUE] = atelier
        cfg["_metadata"] = meta
        update_registry_server_config(conn, nom, cfg)

    def synchroniser() -> dict[str, Any]:
        from mcp_gateway.atelier.mcp_sync import sync_summary

        try:
            resume = sync_summary(settings)
        except Exception as exc:  # noqa: BLE001 — le pool est écrit ; la synchro se refera
            log.warning("synchronisation des connecteurs : %s", exc)
            return {"erreur": f"{type(exc).__name__}: {exc}"}
        return {"actifs": len(resume.get("enabled") or []), "total": resume.get("total")}

    async def sonder(nom: str) -> dict[str, Any]:
        sonde = services_de(app).sonder
        if sonde is None:
            return {"sonde": "non faite", "raison": "passerelle absente ici"}
        try:
            return await sonde(nom)
        except Exception as exc:  # noqa: BLE001 — une sonde en échec se dit, elle ne défait rien
            return {"sonde": "echec", "erreur": f"{type(exc).__name__}: {exc}"[:300]}

    def nom_valide(args: dict[str, Any]) -> str:
        from mcp_gateway.atelier.mcp_registry import validate_server_name

        nom = texte(args, "nom", requis=True, maximum=64) or ""
        try:
            validate_server_name(nom)
        except ValueError as exc:
            raise Refus(str(exc)) from None
        if nom in NOMS_TENUS:
            raise Refus(f"{nom} est tenu par l'Atelier lui-même")
        return nom

    def projet_existant(slug: str) -> Path:
        if slug == settings.assistant_slug:
            raise Refus(projets_aide.espace_de_l_assistant(settings))
        chemin = settings.projects_dir / slug
        if structure.slugifier(slug) != slug or not chemin.is_dir():
            raise Refus(projets_aide.projet_inconnu(settings, slug))
        return chemin

    # ── Ajouter ─────────────────────────────────────────────────────────

    def declaration(ctx: Contexte, args: dict[str, Any]) -> dict[str, Any]:
        from mcp_gateway.atelier.mcp_secrets import secrets_en_clair

        url = texte(args, "url", maximum=500)
        commande = texte(args, "commande", maximum=300)
        if bool(url) == bool(commande):
            raise Refus("un connecteur a une adresse (url) ou une commande, exactement")
        cfg: dict[str, Any] = {}
        if url:
            if not url.startswith(("http://", "https://")):
                raise Refus("url : http:// ou https://")
            transport = texte(args, "transport", maximum=10) or ("sse" if url.rstrip("/").endswith("/sse") else "http")
            if transport not in ("http", "sse"):
                raise Refus("transport : http ou sse")
            cfg = {"type": transport, "url": url}
            en_tetes = args.get("en_tetes")
            if en_tetes is not None:
                if not isinstance(en_tetes, dict) or not all(
                    isinstance(k, str) and isinstance(v, str) for k, v in en_tetes.items()
                ):
                    raise Refus("en_tetes : un objet {nom: valeur}")
                cfg["headers"] = dict(en_tetes)
        else:
            arguments = args.get("arguments") or []
            if not isinstance(arguments, list) or not all(isinstance(a, str) for a in arguments):
                raise Refus("arguments : une liste de textes")
            cfg = {"command": commande, "args": list(arguments)}
            env = args.get("env")
            if env is not None:
                if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
                    raise Refus("env : un objet {NOM: valeur}")
                cfg["env"] = dict(env)
        vues = args.get(CLE_ATELIER)
        if vues is not None:
            # Une vue relayée ouvre un service interne dans le navigateur de la
            # personne (bureaux, équipe B) : seule la personne la pose.
            if not ctx.est_la_personne:
                raise Refus(
                    f"la clé {CLE_ATELIER} (vues relayées d'un service interne) ne se pose que par la "
                    "personne : écran des connecteurs, ou une proposition « À valider »"
                )
            if not isinstance(vues, dict):
                raise Refus(f"{CLE_ATELIER} : un objet, par exemple {{vues: [...]}}")
            cfg[CLE_ATELIER] = json.loads(json.dumps(vues))
        trouves = secrets_en_clair(cfg)
        if url:
            trouves += _secrets_de_l_adresse(url)
        brut = json.dumps(cfg, ensure_ascii=False)
        if "${" in brut:
            trouves.append("référence ${…}")
        if trouves:
            raise Refus(
                f"un secret ne passe jamais par un argument ({', '.join(trouves)}). Ajoutez le "
                f"connecteur sans lui ; la personne l'accorde ensuite par son nom ({ACCORDER}, "
                "écran des connecteurs), depuis le dossier des secrets."
            )
        from mcp_gateway.atelier.mcp_sync import _vise_la_passerelle

        if _vise_la_passerelle(cfg, settings):
            raise Refus("ce connecteur viserait la passerelle de l'Atelier elle-même")
        return cfg

    def reprise_possible(nom: str, args: dict[str, Any]) -> None:
        """Une reprise ne rouvre que ce que l'Atelier a retiré, et rien d'autre."""
        autres = set(args) - {"nom", "reprendre"}
        if autres:
            raise Refus(f"reprendre ne se combine pas avec {sorted(autres)}")
        conn = ouvrir()
        try:
            e = entree(conn, nom)
            if e is None:
                raise Refus(f"connecteur inconnu : {nom}")
            if est_actif(conn, nom):
                raise Refus(f"{nom} est déjà en service")
            if not ((e.config.get("_metadata") or {}).get(_MARQUE) or {}).get("retire"):
                raise Refus(
                    f"{nom} n'a pas été retiré par l'Atelier : sa mise en service revient à la "
                    "personne (écran des connecteurs)"
                )
        finally:
            conn.close()

    def apercu_ajouter(ctx: Contexte, args: dict[str, Any]) -> dict[str, Any]:
        nom = nom_valide(args)
        if booleen(args, "reprendre"):
            reprise_possible(nom, args)
            return {"connecteur": nom, "effet": "remis en service tel qu'il était avant son retrait"}
        cfg = declaration(ctx, args)
        projets = liste_de_noms(args, "projets") or []
        for slug in projets:
            projet_existant(slug)
        return {
            "connecteur": nom,
            "declaration": sans_cle_atelier(cfg),
            "effet": (
                "ajouté au pool : tout projet qui hérite du pool le reçoit"
                + (f", et il est choisi pour {', '.join(projets)}" if projets else "")
            ),
            "secrets": "aucun ; s'il en faut un, la personne l'accorde par son nom",
        }

    async def ajouter(ctx: Contexte, args: dict[str, Any]) -> Effet:
        nom = nom_valide(args)
        if booleen(args, "reprendre"):
            return await reprendre(ctx, nom, args)
        cfg = declaration(ctx, args)
        projets = liste_de_noms(args, "projets") or []
        chemins = [projet_existant(slug) for slug in projets]
        conn = ouvrir()
        try:
            if entree(conn, nom) is not None:
                raise Refus(f"{nom} est déjà dans le pool (hors service ? {RETIRER} puis Annuler le remet)")
            from mcp_gateway.atelier.gateway_mcp import IntegratedMcpStore

            IntegratedMcpStore(conn).upsert(
                nom,
                {**cfg, "enabled": True, "_metadata": {"name": nom, _MARQUE: {"ajoute_par": ctx.acteur, "le": maintenant()}}},
            )
        except ValueError as exc:
            raise Refus(f"déclaration refusée : {exc}") from None
        finally:
            conn.close()
        choisis: dict[str, Any] = {}
        for slug, chemin in zip(projets, chemins):
            choisis[slug] = choisir_pour(chemin, ajout=nom)
        synchro = synchroniser()
        sonde = await sonder(nom)
        return Effet(
            charge={"connecteur": nom, "projets": projets, "sonde": sonde},
            objet_id=nom,
            titre="Connecteur ajouté",
            resume=f"{nom} est dans le pool" + (f", choisi pour {', '.join(projets)}" if projets else ""),
            voir="/?vue=connecteurs",
            preuve={"pool": {"present": True, "actif": True}, "sonde": sonde, "synchro": synchro, "projets": choisis},
            avant=None,
            apres={"connecteur": nom, "declaration": sans_cle_atelier(cfg), "projets": projets},
            inverse_arguments={"nom": nom},
        )

    async def reprendre(ctx: Contexte, nom: str, args: dict[str, Any]) -> Effet:
        reprise_possible(nom, args)
        conn = ouvrir()
        try:
            marquer(conn, nom, None)
            activer(conn, nom, True)
        finally:
            conn.close()
        synchro = synchroniser()
        sonde = await sonder(nom)
        return Effet(
            charge={"connecteur": nom, "repris": True, "sonde": sonde},
            objet_id=nom,
            titre="Connecteur remis en service",
            resume=f"{nom} revient dans le pool, tel qu'il était",
            voir="/?vue=connecteurs",
            preuve={"pool": {"present": True, "actif": True}, "sonde": sonde, "synchro": synchro},
            avant={"actif": False},
            apres={"actif": True},
            inverse_arguments={"nom": nom},
        )

    catalogue.ajouter(
        Commande(
            nom=AJOUTER,
            description=(
                "Ajoute un connecteur au pool de la passerelle (adresse http/sse, ou commande locale), "
                "le sonde, et peut le choisir pour des projets. Aucun secret : la personne accorde un "
                "jeton ensuite, par son nom. reprendre=true remet en service un connecteur retiré."
            ),
            objet="connecteur",
            classe=ENGAGEANTE,
            inverse=RETIRER,
            regles=[
                "aucun secret en argument : en-tête ou variable secrète, référence ${…} et adresse à jeton refusés",
                "nom unique dans le pool ; atelier, wikichat et Onyxia sont tenus par l'Atelier",
                "régénère les configurations par mcp_sync (même chemin que la page Connecteurs)",
                "rend la sonde du connecteur",
                "reprendre : seulement un connecteur retiré par l'Atelier (inverse de retirer)",
                "la clé atelier (vues relayées) : la personne seule ; jamais rendue dans une réponse",
            ],
            executer=ajouter,
            apercu=apercu_ajouter,
            arguments_au_journal=sans_cle_atelier,
            schema={
                "type": "object",
                "properties": {
                    "nom": {"type": "string", "description": "Nom du connecteur dans le pool."},
                    "url": {"type": "string", "description": "Adresse du service (http ou sse)."},
                    "transport": {"type": "string", "enum": ["http", "sse"]},
                    "en_tetes": {"type": "object", "description": "En-têtes non secrets."},
                    "commande": {"type": "string", "description": "Commande d'un serveur local (stdio)."},
                    "arguments": {"type": "array", "items": {"type": "string"}},
                    "env": {"type": "object", "description": "Variables non secrètes."},
                    "projets": {"type": "array", "items": {"type": "string"}},
                    "reprendre": {"type": "boolean", "description": "Remet en service un connecteur retiré."},
                    "atelier": {
                        "type": "object",
                        "description": "Vues relayées (bureaux) : la personne seule ; refusé à un modèle.",
                    },
                },
                "required": ["nom"],
            },
        )
    )

    # ── Retirer ─────────────────────────────────────────────────────────

    async def retirer(ctx: Contexte, args: dict[str, Any]) -> Effet:
        nom = nom_valide(args)
        conn = ouvrir()
        try:
            if entree(conn, nom) is None:
                raise Refus(f"connecteur inconnu : {nom}")
            if not est_actif(conn, nom):
                raise Refus(f"{nom} est déjà hors service")
            marquer(conn, nom, {"retire": {"par": ctx.acteur, "le": maintenant()}})
            activer(conn, nom, False)
            present = entree(conn, nom) is not None
            actif = est_actif(conn, nom)
        finally:
            conn.close()
        from mcp_gateway.registry import registry_pool_key

        pool = getattr(app.state, "pool", None)
        if pool is not None:
            try:
                await pool.disconnect_server(registry_pool_key(nom))
            except Exception as exc:  # noqa: BLE001
                log.warning("déconnexion de %s : %s", nom, exc)
        synchro = synchroniser()
        return Effet(
            charge={"connecteur": nom, "retire": True},
            objet_id=nom,
            titre="Connecteur retiré",
            resume=f"{nom} est hors service : il sort de toutes les configurations ; sa déclaration est gardée",
            voir="/?vue=connecteurs",
            preuve={"pool": {"present": present, "actif": actif}, "synchro": synchro},
            avant={"actif": True},
            apres={"actif": False},
            inverse_arguments={"nom": nom, "reprendre": True},
        )

    catalogue.ajouter(
        Commande(
            nom=RETIRER,
            description=(
                "Retire un connecteur du pool : il sort de toutes les configurations. Sa déclaration "
                "(secret compris) est gardée hors service ; Annuler le remet tel qu'il était."
            ),
            objet="connecteur",
            classe=REVERSIBLE,
            inverse=AJOUTER,
            regles=[
                "met hors service, n'efface pas : aucun secret à ressaisir pour annuler",
                "régénère les configurations par mcp_sync",
            ],
            executer=retirer,
            schema={"type": "object", "properties": {"nom": {"type": "string"}}, "required": ["nom"]},
        )
    )

    # ── Choisir ─────────────────────────────────────────────────────────

    def etat_du_choix(chemin: Path) -> dict[str, Any]:
        from mcp_gateway.atelier.mcp_sync import herite_du_pool, project_binding_state

        if herite_du_pool(chemin):
            return {"herite": True, "connecteurs": []}
        lignes = project_binding_state(settings, chemin)
        return {
            "herite": False,
            "connecteurs": sorted(l["id"] for l in lignes if l.get("active") and not l.get("fixe")),
        }

    def servis(chemin: Path) -> list[str]:
        try:
            brut = json.loads((chemin / ".mcp.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        serveurs = brut.get("mcpServers") if isinstance(brut, dict) else None
        return sorted(serveurs or {})

    def choisir_pour(chemin: Path, *, ajout: str) -> dict[str, Any]:
        """Ajoute un connecteur au choix d'un projet qui a fait le sien (sinon il hérite déjà)."""
        from mcp_gateway.atelier.mcp_sync import write_project_binding

        etat = etat_du_choix(chemin)
        if etat["herite"]:
            return {"herite": True}
        try:
            write_project_binding(settings, chemin, sorted(set(etat["connecteurs"]) | {ajout}))
        except Exception as exc:  # noqa: BLE001
            return {"erreur": f"{type(exc).__name__}: {exc}"}
        return {"connecteurs": servis(chemin)}

    def choisir(ctx: Contexte, args: dict[str, Any]) -> Effet:
        from mcp_gateway.atelier.mcp_sync import (
            MARQUE_HERITAGE,
            SELECTION,
            _pool_enabled,
            lier_le_projet,
            write_project_binding,
        )

        slug = texte(args, "projet", requis=True, maximum=60) or ""
        chemin = projet_existant(slug)
        heriter = booleen(args, "heriter")
        noms = liste_de_noms(args, "connecteurs")
        if heriter == (noms is not None):
            raise Refus("connecteurs (la liste choisie) ou heriter=true, exactement")
        avant = etat_du_choix(chemin)
        if heriter:
            if avant["herite"]:
                apres = avant
            else:
                (chemin / SELECTION).unlink(missing_ok=True)
                marque = chemin / MARQUE_HERITAGE
                marque.parent.mkdir(parents=True, exist_ok=True)
                marque.write_text(
                    "Ce projet hérite des connecteurs du pool : l'Atelier réécrit .mcp.json"
                    " quand le pool change. Choisir ses connecteurs dans l'Atelier retire"
                    " cette marque.\n",
                    encoding="utf-8",
                )
                lier_le_projet(settings, chemin)
                apres = etat_du_choix(chemin)
        else:
            try:
                connus = set(_pool_enabled(settings))
            except Exception as exc:  # noqa: BLE001
                raise Refus(f"catalogue des connecteurs illisible : {exc}") from None
            voulus = [n for n in (noms or []) if n != "atelier"]
            inconnus = [n for n in voulus if n not in connus]
            if inconnus:
                raise Refus(
                    f"connecteurs absents du pool : {', '.join(inconnus)}. "
                    f"Disponibles : {', '.join(sorted(connus)) or 'aucun'}"
                )
            if not avant["herite"] and sorted(voulus) == avant["connecteurs"]:
                apres = avant
            else:
                write_project_binding(settings, chemin, voulus)
                apres = etat_du_choix(chemin)
        change = apres != avant
        inverse: dict[str, Any] | None = None
        if change:
            inverse = {"projet": slug, "heriter": True} if avant["herite"] else {"projet": slug, "connecteurs": avant["connecteurs"]}
        return Effet(
            charge={"projet": slug, **apres},
            objet_id=slug,
            titre="Connecteurs du projet choisis" if change else "Connecteurs inchangés",
            resume=(
                "le projet hérite du pool" if apres["herite"] else (", ".join(apres["connecteurs"]) or "aucun connecteur")
            ),
            voir=f"/?slug={slug}",
            preuve={"mcp_json": servis(chemin), "profil": "code", "fonction": "mcp_sync.configuration_du_profil"},
            avant=avant,
            apres=apres,
            inverse_arguments=inverse,
        )

    catalogue.ajouter(
        Commande(
            nom=CHOISIR,
            description=(
                "Choisit les connecteurs d'un projet parmi ceux du pool (liste complète), ou le remet "
                "à hériter du pool (heriter=true). Régénère son .mcp.json par la fonction de profil de "
                "l'Atelier : même configuration dans l'app, VS Code et le terminal."
            ),
            objet="projet",
            classe=REVERSIBLE,
            inverse=CHOISIR,
            regles=[
                "seulement des connecteurs du pool",
                "le .mcp.json est la sortie de mcp_sync.configuration_du_profil, en références",
                "le choix va dans .atelier/connecteurs-choisis.json",
            ],
            executer=choisir,
            schema={
                "type": "object",
                "properties": {
                    "projet": {"type": "string"},
                    "connecteurs": {"type": "array", "items": {"type": "string"}},
                    "heriter": {"type": "boolean"},
                },
                "required": ["projet"],
            },
        )
    )

    # ── Modifier un connecteur distant (la personne seule) ──────────────

    async def modifier(ctx: Contexte, args: dict[str, Any]) -> Effet:
        """Change l'adresse et le transport d'un service distant, sans le retirer : ses secrets accordés, ses en-têtes et son état restent.

        Réservée à la personne : changer l'adresse d'un connecteur qui porte un secret l'enverrait à un autre hôte.
        """
        from mcp_gateway.registry import update_registry_server_config

        nom = nom_valide(args)
        autres = set(args) - {"nom", "url", "transport"}
        if autres:
            raise Refus(f"modifier : seulement l'adresse (url) et le transport ; pas {sorted(autres)}")
        if not texte(args, "url", maximum=500) and not texte(args, "transport", maximum=10):
            raise Refus("modifier : donnez l'adresse (url) ou le transport à changer")
        conn = ouvrir()
        try:
            e = entree(conn, nom)
            if e is None:
                raise Refus(f"connecteur inconnu : {nom}")
            cfg = dict(e.config)
            if "url" not in cfg:
                raise Refus(f"{nom} est un serveur local : on ne modifie ici que l'adresse et le transport d'un service distant")
            actuel = cfg.get("type") if cfg.get("type") in ("http", "sse") else None
            valide = declaration(
                ctx, {"url": texte(args, "url", maximum=500) or cfg["url"], "transport": texte(args, "transport", maximum=10) or actuel}
            )
            avant = {"url": cfg["url"], "transport": cfg.get("type")}
            apres = {"url": valide["url"], "transport": valide["type"]}
            if avant == apres:
                raise Refus(f"{nom} a déjà cette adresse et ce transport : rien à modifier")
            update_registry_server_config(conn, nom, {**cfg, "type": valide["type"], "url": valide["url"]})
            accords = ((cfg.get("_metadata") or {}).get(_MARQUE) or {}).get("accords") or {}
        finally:
            conn.close()
        hote_change = urlsplit(avant["url"]).netloc != urlsplit(apres["url"]).netloc
        avertissement = (
            f"L'hôte change : les secrets accordés à {nom} ({', '.join(sorted(accords))}) seront envoyés à {urlsplit(apres['url']).netloc}."
            if accords and hote_change
            else ""
        )
        synchro = synchroniser()
        sonde = await sonder(nom)
        return Effet(
            charge={"connecteur": nom, "avant": avant, "apres": apres, "sonde": sonde, **({"avertissement": avertissement} if avertissement else {})},
            objet_id=nom,
            titre="Connecteur modifié",
            resume=f"{nom} : {avant['url']} → {apres['url']}" + (f" ({avertissement})" if avertissement else ""),
            voir="/?vue=connecteurs",
            preuve={"sonde": sonde, "synchro": synchro, "hote_change": hote_change},
            avant=avant,
            apres=apres,
        )

    # ── Renouveler les secrets accordés (la personne seule) ─────────────

    def _schema_de(valeur: Any) -> str:
        """Le préfixe (« Bearer »…) que portait la valeur accordée : on le garde au renouvellement."""
        texte = str(valeur or "")
        premier = texte.split(" ", 1)[0]
        return premier if " " in texte and premier in _SCHEMAS else ""

    def renouveler(*, nom: str | None = None, secret: str | None = None) -> list[dict[str, Any]]:
        """Relit les fichiers des secrets déjà accordés et remet leur valeur dans les connecteurs.

        Un accord copie la valeur du fichier au moment où on l'accorde : changer le fichier (un jeton qui expire, une clé qu'on
        change) ne change pas le connecteur. Ici on relit — pour un connecteur (`nom`), pour un secret (`secret`) ou pour tout.
        Le compte rendu ne porte jamais une valeur : des noms et un état (`renouvele`, `inchange`, `illisible`).
        """
        from mcp_gateway.atelier.apps.secrets import SecretIllisible, lire_secret
        from mcp_gateway.registry import list_registry_servers, update_registry_server_config

        rendu: list[dict[str, Any]] = []
        conn = ouvrir()
        try:
            for e in list_registry_servers(conn):
                if nom and e.server_id != nom:
                    continue
                cfg = dict(e.config)
                meta = dict(cfg.get("_metadata") or {})
                atelier = dict(meta.get(_MARQUE) or {})
                accords = dict(atelier.get("accords") or {})
                modifie = False
                for champ, accord in list(accords.items()):
                    reference = (accord or {}).get("secret")
                    m = _CHAMP_SECRET.match(champ)
                    if not reference or not m or (secret and reference != secret):
                        continue
                    ligne = {"connecteur": e.server_id, "champ": champ, "secret": reference}
                    bloc, cle = m.group(1), m.group(2)
                    contenu = dict(cfg.get(bloc) or {})
                    try:
                        valeur = lire_secret(settings.secrets_dir, reference)
                    except SecretIllisible as exc:
                        rendu.append({**ligne, "etat": "illisible", "motif": str(exc)})
                        continue
                    schema = _schema_de(contenu.get(cle))
                    nouveau = f"{schema} {valeur}" if schema else valeur
                    if contenu.get(cle) == nouveau:
                        rendu.append({**ligne, "etat": "inchange"})
                        continue
                    contenu[cle] = nouveau
                    cfg[bloc] = contenu
                    accords[champ] = {**accord, "renouvele_le": maintenant()}
                    rendu.append({**ligne, "etat": "renouvele"})
                    modifie = True
                if modifie:
                    atelier["accords"] = accords
                    meta[_MARQUE] = atelier
                    cfg["_metadata"] = meta
                    update_registry_server_config(conn, e.server_id, cfg)
        finally:
            conn.close()
        if any(r["etat"] == "renouvele" for r in rendu):
            synchroniser()
        return rendu

    app.state.renouveler_les_secrets = renouveler  # appelé aussi quand la personne renouvelle son jeton GitHub (Réglages)

    def renouveler_commande(ctx: Contexte, args: dict[str, Any]) -> Effet:
        nom = texte(args, "nom", maximum=64) or None
        if nom:
            conn = ouvrir()
            try:
                if entree(conn, nom) is None:
                    raise Refus(f"connecteur inconnu : {nom}")
            finally:
                conn.close()
        rendu = renouveler(nom=nom)
        if not rendu:
            raise Refus(f"{nom} n'a reçu aucun secret : rien à renouveler." if nom else "Aucun connecteur n'a reçu de secret : rien à renouveler.")
        faits = sorted({r["connecteur"] for r in rendu if r["etat"] == "renouvele"})
        illisibles = [r for r in rendu if r["etat"] == "illisible"]
        resume = (
            f"{len(faits)} connecteur(s) renouvelé(s) : {', '.join(faits)}" if faits else "Les secrets accordés n'ont pas changé : rien à renouveler"
        )
        if illisibles:
            resume += f" ; {len(illisibles)} secret(s) illisible(s) (voir le détail)"
        return Effet(
            charge={"renouveles": faits, "details": rendu},
            objet_id=nom or "tous",
            titre="Secrets renouvelés",
            resume=resume,
            voir="/?vue=connecteurs",
            preuve={"details": rendu},
            avant=None,
            apres={"renouveles": faits},
        )

    # ── Accorder un secret (la personne seule) ──────────────────────────

    def accorder(ctx: Contexte, args: dict[str, Any]) -> Effet:
        from mcp_gateway.atelier.apps.secrets import SecretIllisible, lire_secret, reference_valide
        from mcp_gateway.registry import update_registry_server_config

        nom = nom_valide(args)
        champ = texte(args, "champ", requis=True, maximum=80) or ""
        m = _CHAMP_SECRET.match(champ)
        if not m:
            raise Refus("champ : headers.<Nom> ou env.<NOM>")
        reference = texte(args, "secret", requis=True, maximum=64) or ""
        if not reference_valide(reference):
            raise Refus("secret : le nom d'un fichier du dossier des secrets, rien d'autre")
        schema = texte(args, "schema", maximum=10) or ""
        if schema and schema not in _SCHEMAS:
            raise Refus(f"schema : {', '.join(_SCHEMAS)}")
        try:
            valeur = lire_secret(settings.secrets_dir, reference)
        except SecretIllisible as exc:
            raise Refus(str(exc)) from None
        bloc, cle = m.group(1), m.group(2)
        conn = ouvrir()
        try:
            e = entree(conn, nom)
            if e is None:
                raise Refus(f"connecteur inconnu : {nom}")
            cfg = dict(e.config)
            if bloc == "headers" and "url" not in cfg:
                raise Refus(f"{nom} est un serveur local : env.<NOM>, pas headers")
            if bloc == "env" and "command" not in cfg:
                raise Refus(f"{nom} est un service distant : headers.<Nom>, pas env")
            contenu = dict(cfg.get(bloc) or {})
            contenu[cle] = f"{schema} {valeur}" if schema else valeur
            cfg[bloc] = contenu
            meta = dict(cfg.get("_metadata") or {})
            atelier = dict(meta.get(_MARQUE) or {})
            accords = dict(atelier.get("accords") or {})
            accords[champ] = {"secret": reference, "par": ctx.acteur, "le": maintenant()}
            atelier["accords"] = accords
            meta[_MARQUE] = atelier
            cfg["_metadata"] = meta
            update_registry_server_config(conn, nom, cfg)
        finally:
            conn.close()
        synchro = synchroniser()
        return Effet(
            charge={"connecteur": nom, "champ": champ, "secret": reference},
            objet_id=nom,
            titre="Secret accordé",
            resume=f"{nom} reçoit le secret « {reference} » dans {champ} ; les projets n'en voient qu'une référence",
            voir="/?vue=connecteurs",
            preuve={"champ": champ, "secret": reference, "synchro": synchro},
            avant=None,
            apres={"champ": champ, "secret": reference},
        )

    catalogue.ajouter(
        Commande(
            nom=ACCORDER,
            description=(
                "Donne à un connecteur un secret désigné par son nom (fichier du dossier des secrets), "
                "dans un en-tête ou une variable. Réservée à la personne ; aucune valeur en argument."
            ),
            objet="connecteur",
            classe=RESERVEE,
            regles=[
                "jamais par un modèle",
                "le secret est un nom de fichier du dossier des secrets, lu par le serveur",
                "la valeur n'apparaît ni dans le journal, ni dans la carte, ni dans un .mcp.json",
            ],
            executer=accorder,
            schema={
                "type": "object",
                "properties": {
                    "nom": {"type": "string"},
                    "champ": {"type": "string", "description": "headers.<Nom> ou env.<NOM>"},
                    "secret": {"type": "string", "description": "Nom du fichier dans le dossier des secrets."},
                    "schema": {"type": "string", "enum": list(_SCHEMAS)},
                },
                "required": ["nom", "champ", "secret"],
            },
            exposee_mcp=False,
        )
    )

    catalogue.ajouter(
        Commande(
            nom=RENOUVELER,
            description=(
                "Relit les fichiers des secrets déjà accordés à un connecteur (ou à tous) et remet leur valeur à jour. "
                "Réservée à la personne ; aucune valeur en argument ni dans le résultat."
            ),
            objet="connecteur",
            classe=RESERVEE,
            regles=[
                "jamais par un modèle",
                "ne relit que des secrets déjà accordés par la personne",
                "la valeur n'apparaît ni dans le journal, ni dans la carte, ni dans un .mcp.json",
            ],
            executer=renouveler_commande,
            schema={"type": "object", "properties": {"nom": {"type": "string", "description": "Le connecteur ; sans lui, tous."}}},
            exposee_mcp=False,
        )
    )

    catalogue.ajouter(
        Commande(
            nom=MODIFIER,
            description=(
                "Change l'adresse et le transport d'un connecteur distant sans le retirer : ses secrets accordés et son état restent. "
                "Réservée à la personne ; aucun secret en argument."
            ),
            objet="connecteur",
            classe=RESERVEE,
            regles=[
                "jamais par un modèle : changer l'adresse d'un connecteur qui porte un secret l'enverrait à un autre hôte",
                "seulement l'adresse et le transport d'un service distant ; les secrets restent à « Accorder un secret »",
                "l'ancienne et la nouvelle adresse sont au journal ; un changement d'hôte avec secret accordé est signalé",
            ],
            executer=modifier,
            schema={
                "type": "object",
                "properties": {
                    "nom": {"type": "string"},
                    "url": {"type": "string", "description": "La nouvelle adresse (http ou https)."},
                    "transport": {"type": "string", "enum": ["http", "sse"]},
                },
                "required": ["nom"],
            },
            exposee_mcp=False,
        )
    )


__all__ = ["ACCORDER", "MODIFIER", "RENOUVELER", "AJOUTER", "CHOISIR", "CLE_ATELIER", "RETIRER", "inscrire_les_connecteurs", "sans_cle_atelier"]
