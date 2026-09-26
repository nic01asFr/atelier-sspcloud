"""`python -m mcp_gateway.gardiens` : l'exécuteur des gardiens, processus à part.

Lancé par `install/atelier-init.sh`, détaché, journal technique dans
`~/work/logs/gardiens.log` ; le journal des exécutions, lui, est
`~/work/.atelier-etat/gardiens/journal/AAAA-MM.jsonl`.

- `ATELIER_GARDIENS=0` : ne démarre pas (l'interrupteur général) ;
- `ATELIER_GARDIENS_GESTES=0` : tourne, mais ne fait aucun geste ;
- `ATELIER_GARDIENS_HOOKS=0` : ne pose pas le hook du socle ;
- `ATELIER_GARDIENS_PORT` : port de l'API de lecture (défaut 8791, 127.0.0.1).

`--a-blanc` : chaque contrôle une fois, résultat sur la sortie, **rien écrit**
(ni journal, ni état, ni hook) et aucun geste. C'est l'exécution à blanc à
lancer sur un pod en service sans y rien changer.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from mcp_gateway.gardiens.api import PORT_PAR_DEFAUT, creer_le_jeton, serveur
from mcp_gateway.gardiens.controles.commun import Contexte
from mcp_gateway.gardiens.declaration import DeclarationInvalide, lire
from mcp_gateway.gardiens.executeur import Executeur
from mcp_gateway.gardiens.journal import Filtre, Journal

log = logging.getLogger("atelier.gardiens")


def filtre_des_secrets(ctx: Contexte) -> Filtre:
    """Le filtre du journal connaît les valeurs à masquer ; il ne les écrit jamais."""
    try:
        from mcp_gateway.gardiens.controles.securite import valeurs_connues

        return Filtre(valeurs_connues(ctx).values())
    except Exception:  # noqa: BLE001 — sans valeurs connues, restent les motifs de jetons
        return Filtre()


def journal_unique(ctx: Contexte):
    """Écrit au journal unique de l'Atelier (`~/work/.atelier-etat/journal/`)."""
    try:
        from mcp_gateway.atelier.commandes.journal import (
            Evenement,
            Journal as JournalUnique,
            dossier_du_journal,
            secrets_du_fichier_d_environnement,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("journal unique indisponible : %s", exc)
        return None
    unique = JournalUnique(
        dossier_du_journal(ctx.work),
        secrets=secrets_du_fichier_d_environnement(ctx.work / ".secrets" / "claude-env.sh"),
    )

    def publier(e: dict) -> None:
        unique.ecrire(Evenement(acteur="gardiens", **e))

    return publier


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exécuteur des gardiens de l'Atelier")
    parser.add_argument("--declaration", type=Path, default=None)
    parser.add_argument("--port", type=int, default=int(os.environ.get("ATELIER_GARDIENS_PORT") or PORT_PAR_DEFAUT))
    parser.add_argument("--a-blanc", action="store_true", help="une passe, rien écrit, aucun geste")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if os.environ.get("ATELIER_GARDIENS", "1") == "0":
        log.info("gardiens coupés (ATELIER_GARDIENS=0) : rien ne tourne")
        return 0
    try:
        declaration = lire(args.declaration)
    except DeclarationInvalide as exc:
        log.error("déclaration refusée : %s", exc)
        return 2
    ctx = Contexte.depuis_reglages(declaration.reglages)
    filtre = filtre_des_secrets(ctx)

    if args.a_blanc:
        executeur = Executeur(declaration, ctx, Journal(None, filtre), None, a_blanc=True)
        lignes = executeur.tout_une_fois()
        print(json.dumps({"lignes": lignes, "alertes": executeur.alertes_ouvertes()}, ensure_ascii=False, indent=1, default=str))
        return 0

    dossier = ctx.work / ".atelier-etat" / "gardiens"
    journal = Journal(dossier / "journal", filtre)
    if os.environ.get("ATELIER_GARDIENS_HOOKS", "1") != "0":
        from mcp_gateway.gardiens.garde_bash import poser, reglages_par_defaut

        try:
            log.info("hook du socle : %s", poser(reglages_par_defaut()))
        except OSError as exc:
            log.warning("hook du socle non posé : %s", exc)
    executeur = Executeur(declaration, ctx, journal, dossier, publier=journal_unique(ctx))
    try:
        # Le jeton du pilotage : seul l'Atelier le relit, pour lancer, couper
        # ou réactiver un contrôle à chaud (api.py, POST /pilotage).
        jeton = creer_le_jeton(dossier)
    except OSError as exc:
        log.warning("pilotage fermé, jeton non écrit : %s", exc)
        jeton = ""
    try:
        srv = serveur(executeur, args.port, jeton)
    except OSError as exc:
        # Un autre exécuteur tient déjà le port : on ne double pas les contrôles.
        log.error("port %s pris (%s) : un exécuteur tourne déjà ?", args.port, exc)
        return 1
    executeur.demarrer()
    log.info(
        "gardiens en service : %d contrôles (%s), API 127.0.0.1:%d, gestes %s",
        len(declaration.controles),
        declaration.source,
        args.port,
        "permis" if executeur.permettre_gestes else "interdits",
    )
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        executeur.arreter()
        srv.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
