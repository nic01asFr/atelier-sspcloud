"""Les commandes de l'Atelier : catalogue, journal unique, file « À valider ».

`enregistrer(app)` est la seule chose à appeler depuis `api.py` : elle monte le
catalogue sur l'application (`app.state.commandes`), la file
(`app.state.a_valider`), les routes `/v1/commandes`, `/v1/journal`,
`/v1/a-valider`, et note les adresses publiques du service pour
`bin/atelier-relancer`.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.commandes.a_valider import FileAValider, dossier_a_valider
from mcp_gateway.atelier.commandes.catalogue import Catalogue, DeclarationOutil
from mcp_gateway.atelier.commandes.journal import Journal, dossier_du_journal, secrets_du_fichier_d_environnement

log = logging.getLogger("atelier.commandes")

# Les réglages qui font d'un Atelier relancé le même Atelier : ses adresses
# publiques. `atelier-relancer` les relit ici quand le processus en service ne
# peut plus les lui donner.
VARIABLES_D_ADRESSE = {
    "ATELIER_PUBLIC_URL": "public_url",
    "ATELIER_APPS_PUBLIC_URL": "apps_public_url",
    "ATELIER_VSCODE_URL": "vscode_url",
}


def fichier_des_adresses(work_dir: Path) -> Path:
    return Path(work_dir) / ".atelier-etat" / "adresses.env"


def noter_les_adresses(settings: Any) -> Path | None:
    """Écrit `~/work/.atelier-etat/adresses.env` : `NOM='valeur'` par adresse connue.

    Une adresse vide n'écrase pas celle déjà notée : un Atelier relancé sans
    elle ne doit pas effacer la mémoire de la bonne.
    """
    chemin = fichier_des_adresses(settings.work_dir)
    anciennes: dict[str, str] = {}
    if chemin.is_file():
        for ligne in chemin.read_text(encoding="utf-8").splitlines():
            nom, sep, valeur = ligne.partition("=")
            if sep and nom.strip() in VARIABLES_D_ADRESSE:
                anciennes[nom.strip()] = valeur.strip().strip("'")
    valeurs = dict(anciennes)
    for variable, champ in VARIABLES_D_ADRESSE.items():
        actuelle = str(getattr(settings, champ, "") or "").strip()
        if actuelle:
            valeurs[variable] = actuelle
    if not valeurs:
        return None
    lignes = ["# Écrit par l'Atelier au démarrage ; relu par bin/atelier-relancer."]
    for variable in VARIABLES_D_ADRESSE:
        if valeurs.get(variable) and "'" not in valeurs[variable]:
            lignes.append(f"{variable}='{valeurs[variable]}'")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("\n".join(lignes) + "\n", encoding="utf-8")
    return chemin


def _acces_au_pilote(settings: Any) -> tuple[Any, Any]:
    """Lire et trancher les propositions du pilote de wikichat, par son API."""
    from mcp_gateway.atelier.pilote_client import pilote_get, pilote_post

    async def lire() -> Any:
        return await pilote_get(settings, "/pilote/api/data")

    async def decider(agent: str, action: str, decision: str, complete: Any) -> Any:
        corps: dict[str, Any] = {"actionId": action, "decision": decision}
        if complete:
            corps["resolved"] = complete
        return await pilote_post(settings, f"/pilote/api/agent/{agent}/decide", corps)

    return lire, decider


def construire(app: Any) -> Catalogue:
    """Le catalogue et ses dépendances, montés sur `app.state`."""
    from mcp_gateway.atelier.commandes.existants import declarer_les_existants
    from mcp_gateway.atelier.commandes.natives import Services, inscrire_les_natives
    from mcp_gateway.atelier.env_secrets import chemin_du_fichier
    from mcp_gateway.atelier.outils_conversation import OutilsAtelier

    settings = app.state.settings
    journal = Journal(
        dossier_du_journal(settings.work_dir),
        secrets=secrets_du_fichier_d_environnement(chemin_du_fichier(settings)),
    )
    file = FileAValider(dossier_a_valider(settings.work_dir), journal=journal)
    outils = OutilsAtelier(
        store=app.state.store,
        projects=app.state.projects,
        harness=app.state.harness,
        apps=getattr(app.state, "apps", None),
    )
    catalogue = Catalogue(journal=journal, outils=outils)
    declarer_les_existants(catalogue)

    pilote_lire: Any = None
    pilote_decider: Any = None
    if not getattr(app.state, "use_fake", False):
        pilote_lire, pilote_decider = _acces_au_pilote(settings)

    inscrire_les_natives(
        catalogue,
        Services(
            settings=settings,
            projects=app.state.projects,
            sessions=app.state.store,
            file=file,
            pilote_lire=pilote_lire,
            pilote_decider=pilote_decider,
        ),
    )
    app.state.commandes = catalogue
    app.state.a_valider = file
    app.state.journal_unique = journal
    return catalogue


def enregistrer(app: Any) -> Catalogue:
    """La ligne que `api.py` appelle : catalogue, routes, adresses."""
    from mcp_gateway.atelier.commandes.carte import inscrire_la_carte
    from mcp_gateway.atelier.commandes.deploiement import inscrire_le_deploiement
    from mcp_gateway.atelier.commandes.routes import construire_le_routeur

    catalogue = construire(app)
    inscrire_le_deploiement(app, catalogue)
    inscrire_la_carte(app, catalogue)
    app.include_router(construire_le_routeur(app))
    try:
        noter_les_adresses(app.state.settings)
    except OSError as exc:
        log.warning("adresses publiques non notées : %s", exc)
    return catalogue


__all__ = [
    "Catalogue",
    "DeclarationOutil",
    "FileAValider",
    "Journal",
    "construire",
    "enregistrer",
    "fichier_des_adresses",
    "noter_les_adresses",
]
