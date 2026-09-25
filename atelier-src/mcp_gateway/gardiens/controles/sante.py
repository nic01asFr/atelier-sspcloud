"""G1, gardien Santé : ce qui doit tourner tourne-t-il, et répond-il ?"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_gateway.gardiens.controles.commun import Contexte, constat, github_api, resultat

# Où chaque service répond quand il va bien (install/atelier-init.sh).
SONDES = {
    "atelier": ("port_atelier", "/v1/health"),
    "relais": ("port_relais", "/_relais/sante"),
    "wikichat": ("port_wikichat", "/api/health"),
}


def adresse_de_sonde(ctx: Contexte, service: str) -> str:
    attribut, chemin = SONDES[service]
    return f"http://127.0.0.1:{getattr(ctx, attribut)}{chemin}"


def service(ctx: Contexte, c: Any) -> dict[str, Any]:
    """Un service répond-il 200 à sa sonde ? `params.service` : atelier | relais | wikichat."""
    nom = c.params.get("service")
    if nom not in SONDES:
        return resultat([constat(f"{c.id}:declaration", c.id, f"service inconnu {nom!r}")])
    url = c.params.get("url") or adresse_de_sonde(ctx, nom)
    r = ctx.http(url, None, float(c.params.get("delai_sonde_s", 5)))
    if r.statut == 200:
        return resultat([], service=nom, statut=200)
    preuve = f"GET {url} : " + (f"HTTP {r.statut}" if r.statut else (r.erreur or "pas de réponse"))
    return resultat(
        [constat(f"{c.id}:ne-repond-pas", nom, f"{nom} ne répond pas", preuve)],
        service=nom,
        statut=r.statut,
    )


def creations(ctx: Contexte, c: Any) -> dict[str, Any]:
    """L'état du superviseur des applications, lu à l'API de l'Atelier (`GET /v1/apps`)."""
    url = f"http://127.0.0.1:{ctx.port_atelier}/v1/apps"
    cle = ctx.cle_owner()
    if not cle:
        return resultat(
            [constat(f"{c.id}:illisible", "superviseur", "état du superviseur illisible : pas de clé de l'Atelier", "", "attention")]
        )
    r = ctx.http(url, {"Authorization": f"Bearer {cle}"}, 10.0)
    if r.statut != 200:
        statut = f"HTTP {r.statut}" if r.statut else (r.erreur or "pas de réponse")
        return resultat(
            [constat(f"{c.id}:illisible", "superviseur", "état du superviseur illisible", f"GET {url} : {statut}", "attention")]
        )
    try:
        fiches = json.loads(r.corps).get("artefacts") or []
    except (json.JSONDecodeError, AttributeError):
        fiches = []
    constats = []
    compte: dict[str, int] = {}
    for f in fiches:
        etat = f.get("etat", "?")
        compte[etat] = compte.get(etat, 0) + 1
        objet = f"{f.get('slug')}/{f.get('nom')}"
        if etat == "en_echec":
            constats.append(
                constat(f"{c.id}:en_echec:{objet}", objet, "création serveur en échec : le superviseur a cessé de la relancer", f"raison : {f.get('raison', '')[:200]}")
            )
        elif etat == "invalide":
            constats.append(
                constat(f"{c.id}:invalide:{objet}", objet, "manifeste invalide", str(f.get("erreur", ""))[:200], "attention")
            )
        elif etat == "redemarrage":
            constats.append(constat(f"{c.id}:redemarrage:{objet}", objet, "création en cours de redémarrage", "", "attention"))
    return resultat(constats, par_etat=compte)


def ci_main(ctx: Contexte, c: Any) -> dict[str, Any]:
    """Le dernier run terminé de `main`, par dépôt (`params.depots`)."""
    branche = c.params.get("branche", "main")
    constats = []
    vus = {}
    for depot in c.params.get("depots") or []:
        statut, corps, moyen = github_api(ctx, f"repos/{depot}/actions/runs?branch={branche}&per_page=20")
        if statut != 200 or not isinstance(corps, dict):
            constats.append(
                constat(
                    f"{c.id}:inaccessible:{depot}",
                    depot,
                    "CI illisible",
                    f"{moyen} : HTTP {statut}" + (" (dépôt privé sans jeton ?)" if statut == 404 else ""),
                    "attention",
                )
            )
            continue
        termines = [r for r in corps.get("workflow_runs") or [] if r.get("status") == "completed"]
        if not termines:
            vus[depot] = None
            continue
        dernier = max(termines, key=lambda r: r.get("created_at") or "")
        vus[depot] = {
            "workflow": dernier.get("name"),
            "commit": (dernier.get("head_sha") or "")[:7],
            "conclusion": dernier.get("conclusion"),
            "quand": dernier.get("created_at"),
        }
        if dernier.get("conclusion") != "success":
            constats.append(
                constat(
                    f"{c.id}:rouge:{depot}",
                    depot,
                    f"CI de {branche} rouge : {dernier.get('name')}",
                    f"run {dernier.get('id')} sur {vus[depot]['commit']} : {dernier.get('conclusion')} ({dernier.get('created_at')})",
                )
            )
    return resultat(constats, derniers=vus)


def commit_deploye(ctx: Contexte, c: Any) -> tuple[str, str]:
    """(commit, d'où il vient) ; ("", raison) si rien ne le dit."""
    if ctx.env.get("ATELIER_COMMIT"):
        return ctx.env["ATELIER_COMMIT"].strip(), "ATELIER_COMMIT"
    # L'image écrit son commit dans /opt/atelier/VERSION (deploy/Dockerfile).
    fichiers = c.params.get("fichiers_version") or ["/opt/atelier/VERSION"]
    for chemin in [*fichiers, str(ctx.atelier_src / "VERSION")]:
        try:
            texte = Path(chemin).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if texte:
            return texte, chemin
    if (ctx.atelier_src / ".git").exists() or (ctx.atelier_src.parent / ".git").exists():
        code, sortie = ctx.commande(["git", "-C", str(ctx.atelier_src), "rev-parse", "HEAD"], 10.0)
        if code == 0 and sortie.strip():
            return sortie.strip().splitlines()[0], "git"
    return "", "ni ATELIER_COMMIT, ni /opt/atelier/VERSION, ni dépôt git dans atelier-src"


def image_main(ctx: Contexte, c: Any) -> dict[str, Any]:
    """Le code en service est-il celui de `main` ?"""
    depot = c.params.get("depot")
    branche = c.params.get("branche", "main")
    deploye, origine = commit_deploye(ctx, c)
    statut, corps, moyen = github_api(ctx, f"repos/{depot}/commits/{branche}")
    sha_main = corps.get("sha", "") if statut == 200 and isinstance(corps, dict) else ""
    constats = []
    if not deploye:
        constats.append(constat(f"{c.id}:inconnu", "code en service", "commit déployé inconnu", origine, "attention"))
    if not sha_main:
        constats.append(
            constat(f"{c.id}:main-illisible", depot or "?", f"commit de {branche} illisible", f"{moyen} : HTTP {statut}", "attention")
        )
    if deploye and sha_main and not (sha_main.startswith(deploye) or deploye.startswith(sha_main)):
        constats.append(
            constat(
                f"{c.id}:ecart",
                "code en service",
                f"le code en service n'est pas {branche}",
                f"en service {deploye[:7]} ({origine}), {branche} {sha_main[:7]}",
                "attention",
            )
        )
    return resultat(constats, deploye=deploye[:12], origine=origine, main=sha_main[:12])


def disque(ctx: Contexte, c: Any) -> dict[str, Any]:
    chemin = Path(c.params.get("chemin") or ctx.work)
    try:
        total, libre = ctx.disque(chemin)
    except OSError as exc:
        return resultat([constat(f"{c.id}:illisible", str(chemin), "disque illisible", str(exc), "attention")])
    pris = 100.0 * (total - libre) / total if total else 0.0
    donnees = {"chemin": str(chemin), "pris_pct": round(pris, 1), "libre_go": round(libre / 1e9, 2)}
    alerte = float(c.params.get("seuil_alerte_pct", 95))
    attention = float(c.params.get("seuil_attention_pct", 85))
    if pris >= alerte:
        return resultat([constat(f"{c.id}:plein", str(chemin), f"disque plein à {pris:.0f} %", "", "alerte")], **donnees)
    if pris >= attention:
        return resultat([constat(f"{c.id}:se-remplit", str(chemin), f"disque plein à {pris:.0f} %", "", "attention")], **donnees)
    return resultat([], **donnees)

