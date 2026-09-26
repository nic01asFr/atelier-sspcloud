"""L'API de lecture des gardiens, en boucle locale seulement.

`127.0.0.1:8791` par défaut (`ATELIER_GARDIENS_PORT`). Lecture seule : toute
méthode autre que GET reçoit 405. Rien de ce qu'elle rend ne porte de secret :
tout vient du journal filtré et des résultats des contrôles, qui ne contiennent
que des chemins, des noms et des empreintes.

Contrat (pour la page Gardiens, vague 2), tout en JSON :

- `GET /sante` : `{ok, demarre_a, declaration, controles, interrupteurs}` ;
- `GET /etat` : `{controles: [...], alertes_ouvertes: [...], interrupteurs}` ;
- `GET /resultats?controle=<id>&n=<50>` : les dernières lignes du journal ;
- `GET /resultats/<id>` : le dernier résultat complet d'un contrôle (avec `donnees`) ;
- `GET /echeances` : `[{id, gardien, prochaine, derniere, en_retard}]`, par date ;
- `GET /alertes?toutes=1` : les alertes (ouvertes seulement par défaut) ;
- `GET /automates` : l'inventaire G0 (`{lu_a, automates: [...], par_etat}`).
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp_gateway.gardiens.journal import horodatage

HOTE = "127.0.0.1"
PORT_PAR_DEFAUT = 8791


def interrupteurs(executeur: Any) -> dict[str, Any]:
    return {
        "gardiens": True,  # s'il répond, il n'est pas coupé (ATELIER_GARDIENS=0 l'empêche de démarrer)
        "gestes": executeur.permettre_gestes,
        "a_blanc": executeur.a_blanc,
        "reparations": _reparations_permises(executeur),
    }


def _reparations_permises(executeur: Any) -> bool:
    from mcp_gateway.gardiens.reparations import reparations_permises

    return getattr(executeur, "reparations", None) is not None and reparations_permises(executeur.ctx.env)[0]


def router(executeur: Any, chemin: str, requete: dict[str, list[str]]) -> tuple[int, Any]:
    if chemin == "/sante":
        return 200, {
            "ok": True,
            "demarre_a": horodatage(executeur.demarre_a),
            "declaration": executeur.declaration.source,
            "controles": len(executeur.declaration.controles),
            "interrupteurs": interrupteurs(executeur),
        }
    if chemin == "/etat":
        return 200, {
            "controles": executeur.etat_des_controles(),
            "alertes_ouvertes": executeur.alertes_ouvertes(),
            "interrupteurs": interrupteurs(executeur),
        }
    if chemin == "/resultats":
        n = int((requete.get("n") or ["50"])[0])
        controle = (requete.get("controle") or [None])[0]
        return 200, {"lignes": executeur.journal.recentes(max(1, min(n, 500)), controle)}
    if chemin.startswith("/resultats/"):
        ident = chemin[len("/resultats/") :]
        if ident not in executeur.controles:
            return 404, {"erreur": f"contrôle inconnu : {ident}"}
        return 200, {"controle": ident, "resultat": executeur.resultat(ident)}
    if chemin == "/echeances":
        maintenant = executeur.horloge()
        liste = []
        for c in executeur.declaration.controles:
            if not c.actif:
                continue
            st = executeur.etats[c.id]
            liste.append(
                {
                    "id": c.id,
                    "gardien": c.gardien,
                    "prochaine": horodatage(st.prochaine),
                    "derniere": horodatage(st.derniere) if st.derniere else None,
                    "en_retard": maintenant > st.prochaine + executeur.tolerance(c),
                }
            )
        return 200, {"echeances": sorted(liste, key=lambda e: e["prochaine"])}
    if chemin == "/reparations":
        # Les agents réparateurs demandés (G5) : la vue Agents les montre à côté
        # des autres agents spécifiques. Leur conversation et leur proposition
        # se lisent dans l'Atelier (`/v1/lancements`, « À valider »).
        registre = list(getattr(getattr(executeur, "reparations", None), "registre", []) or [])
        return 200, {"reparations": registre[-100:], "interrupteurs": interrupteurs(executeur)}
    if chemin == "/alertes":
        toutes = (requete.get("toutes") or ["0"])[0] == "1"
        return 200, {"alertes": executeur.alertes_ouvertes(toutes)}
    if chemin == "/automates":
        for c in executeur.declaration.controles:
            if c.interne == "entretien.automates":
                res = executeur.resultat(c.id) or {}
                donnees = res.get("donnees") or {}
                return 200, {
                    "controle": c.id,
                    "lu_a": donnees.get("lu_a"),
                    "automates": donnees.get("automates", []),
                    "par_etat": donnees.get("par_etat", {}),
                }
        return 404, {"erreur": "aucun contrôle d'inventaire déclaré"}
    return 404, {"erreur": "inconnu"}


def serveur(executeur: Any, port: int = PORT_PAR_DEFAUT) -> ThreadingHTTPServer:
    class Gestionnaire(BaseHTTPRequestHandler):
        def _repondre(self, statut: int, corps: Any) -> None:
            donnees = json.dumps(corps, ensure_ascii=False, default=str).encode("utf-8")
            self.send_response(statut)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(donnees)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(donnees)

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            try:
                statut, corps = router(executeur, url.path.rstrip("/") or "/", parse_qs(url.query))
            except Exception as exc:  # noqa: BLE001
                statut, corps = 500, {"erreur": type(exc).__name__}
            self._repondre(statut, corps)

        def _refuser(self) -> None:
            self._repondre(405, {"erreur": "lecture seule"})

        do_POST = do_PUT = do_DELETE = do_PATCH = _refuser  # noqa: N815

        def log_message(self, *args: Any) -> None:  # silence : pas de journal d'accès
            return

    # Boucle locale, sans option pour en sortir (comme le relais LLM).
    return ThreadingHTTPServer((HOTE, port), Gestionnaire)


def servir_en_arriere_plan(executeur: Any, port: int = 0) -> tuple[ThreadingHTTPServer, threading.Thread]:
    srv = serveur(executeur, port)
    fil = threading.Thread(target=srv.serve_forever, name="gardiens-api", daemon=True)
    fil.start()
    return srv, fil
