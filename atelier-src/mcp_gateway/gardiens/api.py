"""L'API des gardiens, en boucle locale seulement.

`127.0.0.1:8791` par défaut (`ATELIER_GARDIENS_PORT`). Lecture en GET ; une
seule écriture, `POST /pilotage`, pour l'Atelier. Toute autre méthode reçoit
405. Rien de ce qu'elle rend ne porte de secret : tout vient du journal filtré
et des résultats des contrôles, qui ne contiennent que des chemins, des noms
et des empreintes.

Contrat (pour la page Gardiens, vague 2), tout en JSON :

- `GET /sante` : `{ok, demarre_a, declaration, controles, interrupteurs}` ;
- `GET /etat` : `{controles: [...], alertes_ouvertes: [...], interrupteurs}` ;
- `GET /resultats?controle=<id>&n=<50>` : les dernières lignes du journal ;
- `GET /resultats/<id>` : le dernier résultat complet d'un contrôle (avec `donnees`) ;
- `GET /echeances` : `[{id, gardien, prochaine, derniere, en_retard}]`, par date ;
- `GET /alertes?toutes=1` : les alertes (ouvertes seulement par défaut) ;
- `GET /automates` : l'inventaire G0 (`{lu_a, automates: [...], par_etat}`).

**Pilotage** (vague 2, vue Agents) : `POST /pilotage`
`{action: lancer|couper|reactiver, gardien?|controle?, par?}` rend
`{action, controles: [ids touchés], etat: [...]}`. Il n'est pas pour le
navigateur :

- il demande `Authorization: Bearer <jeton>`, le jeton que l'exécuteur écrit à
  son démarrage dans `<état>/pilotage.jeton` (0600) et que seul l'Atelier relit ;
  sans jeton (exécution à blanc), le pilotage est fermé (503) ;
- une requête qui porte `Origin` (un navigateur en envoie toujours un sur un
  POST) est refusée, comme un `Host` qui n'est pas la boucle locale (une page
  qui ferait pointer son nom vers 127.0.0.1) ;
- c'est l'Atelier qui décide qui a le droit (la personne seule coupe un
  gardien) ; ici, on vérifie seulement que c'est lui.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp_gateway.gardiens.journal import horodatage

HOTE = "127.0.0.1"
PORT_PAR_DEFAUT = 8791
FICHIER_DU_JETON = "pilotage.jeton"
ACTIONS = ("lancer", "couper", "reactiver")
HOTES_LOCAUX = ("127.0.0.1", "localhost", "[::1]")


def creer_le_jeton(dossier_etat: Path) -> str:
    """Un jeton neuf à chaque démarrage, lisible du seul propriétaire du fichier."""
    dossier_etat = Path(dossier_etat)
    dossier_etat.mkdir(parents=True, exist_ok=True)
    chemin = dossier_etat / FICHIER_DU_JETON
    jeton = secrets.token_urlsafe(32)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    fd = os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(jeton)
    os.replace(provisoire, chemin)
    try:
        os.chmod(chemin, 0o600)
    except OSError:
        pass
    return jeton


def lire_le_jeton(dossier_etat: Path) -> str:
    try:
        return (Path(dossier_etat) / FICHIER_DU_JETON).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def piloter(executeur: Any, corps: Any) -> tuple[int, Any]:
    if not isinstance(corps, dict):
        return 400, {"erreur": "corps JSON attendu"}
    action = corps.get("action")
    if action not in ACTIONS:
        return 400, {"erreur": f"action : {', '.join(ACTIONS)}"}
    gardien = corps.get("gardien") if isinstance(corps.get("gardien"), str) else None
    controle = corps.get("controle") if isinstance(corps.get("controle"), str) else None
    par = str(corps.get("par") or "atelier")[:120]
    try:
        if action == "lancer":
            touches = executeur.lancer_maintenant(gardien, controle)
        elif action == "couper":
            touches = executeur.couper(gardien, controle, par)
        else:
            touches = executeur.reactiver(gardien, controle, par)
    except KeyError as exc:
        return 404, {"erreur": str(exc.args[0] if exc.args else exc)}
    return 200, {"action": action, "controles": touches, "etat": executeur.etat_des_controles()}


def interrupteurs(executeur: Any) -> dict[str, Any]:
    return {
        "gardiens": True,  # s'il répond, il n'est pas coupé (ATELIER_GARDIENS=0 l'empêche de démarrer)
        "gestes": executeur.permettre_gestes,
        "a_blanc": executeur.a_blanc,
    }


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
            if not executeur.actif(c):
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


def serveur(executeur: Any, port: int = PORT_PAR_DEFAUT, jeton: str = "") -> ThreadingHTTPServer:
    """`jeton` vide : pas de pilotage (exécution à blanc, ou tests de lecture)."""

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

        def do_POST(self) -> None:  # noqa: N802
            # Le corps d'abord, borné : répondre sans l'avoir lu ferme la
            # connexion sous un client qui écrit encore (connexion abandonnée).
            try:
                taille = min(int(self.headers.get("Content-Length") or 0), 10_000)
                brut = self.rfile.read(taille) if taille > 0 else b""
            except (ValueError, OSError):
                return self._repondre(400, {"erreur": "corps illisible"})
            if urlparse(self.path).path.rstrip("/") != "/pilotage":
                return self._refuser()
            if self.headers.get("Origin") is not None:
                return self._repondre(403, {"erreur": "pas depuis un navigateur"})
            hote = (self.headers.get("Host") or "").rsplit(":", 1)[0].lower()
            if hote not in HOTES_LOCAUX:
                return self._repondre(403, {"erreur": "hôte non local"})
            if not jeton:
                return self._repondre(503, {"erreur": "pilotage fermé"})
            porte = self.headers.get("Authorization") or ""
            donne = porte[7:].strip() if porte.lower().startswith("bearer ") else ""
            if not donne or not hmac.compare_digest(donne.encode(), jeton.encode()):
                return self._repondre(401, {"erreur": "jeton de pilotage requis"})
            try:
                corps = json.loads(brut or b"{}")
            except ValueError:
                return self._repondre(400, {"erreur": "corps JSON attendu"})
            try:
                statut, reponse = piloter(executeur, corps)
            except Exception as exc:  # noqa: BLE001
                statut, reponse = 500, {"erreur": type(exc).__name__}
            self._repondre(statut, reponse)

        do_PUT = do_DELETE = do_PATCH = _refuser  # noqa: N815

        def log_message(self, *args: Any) -> None:  # silence : pas de journal d'accès
            return

    # Boucle locale, sans option pour en sortir (comme le relais LLM).
    return ThreadingHTTPServer((HOTE, port), Gestionnaire)


def servir_en_arriere_plan(
    executeur: Any, port: int = 0, jeton: str = ""
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    srv = serveur(executeur, port, jeton)
    fil = threading.Thread(target=srv.serve_forever, name="gardiens-api", daemon=True)
    fil.start()
    return srv, fil
