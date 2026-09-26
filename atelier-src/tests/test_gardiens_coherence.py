"""Le vérificateur de cohérence, contrôle quotidien du gardien Cohérence.

Le vérificateur lui-même (le vrai `claude` sur quatre surfaces) ne tourne que
sur le pod : ici, sa sortie `--json` est une fixture, et l'on vérifie ce que
le contrôle en fait (constats, alertes, plafond), puis que le plafond tue
réellement un groupe de processus.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from mcp_gateway.gardiens.controles import REGISTRE, coherence
from mcp_gateway.gardiens.controles.commun import Contexte, lancer_en_groupe
from mcp_gateway.gardiens.declaration import FICHIER_PAR_DEFAUT, Controle, Declaration, lire, prochaine_echeance
from mcp_gateway.gardiens.executeur import Executeur
from mcp_gateway.gardiens.journal import Journal


def _controle(**params) -> Controle:
    return Controle(id="coherence.surfaces", gardien="coherence", portee="atelier",
                    quand={"cron": "40 5 * * *", "tz": "Europe/Paris"},
                    commande=["interne", "coherence.surfaces"], delai_s=60, params=params)


def _rapport(ecarts_par_dossier: dict[str, list[str]], hooks: list[str] | None = None) -> str:
    dossiers = [
        {"slug": slug, "profil": "assistant" if slug == "assistant" else "code",
         "surfaces": {"app": {}, "vscode": {}, "terminal": {}, "bash-lc": {}}, "ecarts": ecarts}
        for slug, ecarts in ecarts_par_dossier.items()
    ]
    total = sum(len(e) for e in ecarts_par_dossier.values()) + len(hooks or [])
    return json.dumps({"version_extension": "2.1.0", "dossiers": dossiers, "ecarts": total,
                       "hooks_introuvables": hooks or []})


@pytest.fixture()
def ctx(tmp_path: Path) -> Contexte:
    work = tmp_path / "work"
    src = work / "atelier-src"
    (src / "bin").mkdir(parents=True)
    (src / "bin" / "atelier-verifier-coherence").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    return Contexte(work=work, home=tmp_path / "home", env={}, ecoutes=lambda: [], processus=lambda: [])


def _brancher(ctx: Contexte, *reponses: tuple[int, str]) -> list[tuple[list[str], float]]:
    appels: list[tuple[list[str], float]] = []
    file = list(reponses)

    def commande_longue(argv, plafond, cwd=None):
        appels.append((argv, plafond))
        return file.pop(0)

    ctx.commande_longue = commande_longue
    return appels


def test_lance_le_verificateur_rapide_en_json_sous_plafond(ctx: Contexte) -> None:
    appels = _brancher(ctx, (0, _rapport({"carte": [], "assistant": []})))
    res = coherence.surfaces(ctx, _controle(plafond_s=300, delai_par_surface_s=30))
    assert res["etat"] == "ok" and res["constats"] == []
    argv, plafond = appels[0]
    assert argv[0] == sys.executable
    assert argv[1].endswith("atelier-src/bin/atelier-verifier-coherence".replace("/", os.sep))
    assert "--rapide" in argv and "--json" in argv
    assert argv[argv.index("--delai") + 1] == "30.0"
    assert plafond == 300
    assert res["donnees"]["surfaces"] == ["app", "bash-lc", "terminal", "vscode"]


def test_chaque_ecart_est_un_constat_stable(ctx: Contexte) -> None:
    rapport = _rapport(
        {"carte": ["vscode : outils hors du profil code ['WebSearch']", "terminal : mode default, attendu auto (projet)"],
         "assistant": ["app : l'Assistant n'a pas les méta-outils ['gateway_call_tool'] (équipe A)"]},
        hooks=["/home/onyxia/work/bin/absent.sh"],
    )
    _brancher(ctx, (1, rapport), (1, rapport))
    premier = coherence.surfaces(ctx, _controle())
    second = coherence.surfaces(ctx, _controle())
    assert premier["etat"] == "alerte"
    assert len(premier["constats"]) == 4
    assert [c["empreinte"] for c in premier["constats"]] == [c["empreinte"] for c in second["constats"]]
    niveaux = {c["objet"]: c["niveau"] for c in premier["constats"]}
    assert niveaux["projet.assistant"] == "attention", "un écart attendu d'un chantier en cours se surveille"
    assert niveaux["projet.carte"] == "alerte"
    assert any(c["objet"] == "hooks" for c in premier["constats"])


def test_plafond_atteint_ou_rapport_illisible_sont_des_erreurs(ctx: Contexte) -> None:
    _brancher(ctx, (124, ""), (2, "Traceback"), (0, "pas du json"))
    for attendu in ("plafond", "echec", "echec"):
        res = coherence.surfaces(ctx, _controle())
        assert res["erreur"] is True and res["etat"] == "alerte"
        assert res["constats"][0]["empreinte"] == f"coherence.surfaces:{attendu}"


def test_verificateur_absent(tmp_path: Path) -> None:
    ctx = Contexte(work=tmp_path / "w", home=tmp_path / "h", env={})
    res = coherence.surfaces(ctx, _controle())
    assert res["erreur"] is True
    assert res["constats"][0]["empreinte"] == "coherence.surfaces:introuvable"


def test_une_alerte_ouverte_par_ecart_fermee_quand_il_disparait_jamais_par_une_erreur(ctx: Contexte, tmp_path: Path) -> None:
    ecart = _rapport({"carte": ["vscode : outils hors du profil code ['WebSearch']"]})
    _brancher(ctx, (1, ecart), (124, ""), (0, _rapport({"carte": []})))
    c = _controle()
    decl = Declaration(controles=[c], reglages={}, source=str(tmp_path / "gardiens.json"))
    publies: list[dict] = []
    ex = Executeur(decl, ctx, Journal(tmp_path / "etat" / "journal"), tmp_path / "etat",
                   publier=publies.append, permettre_gestes=True)

    ligne = ex.passer(c)
    assert "action" not in ligne, "aucun geste : le contrôle ne répare rien"
    ouvertes = ex.alertes_ouvertes()
    assert len(ouvertes) == 1 and ouvertes[0]["gardien"] == "coherence"
    assert publies[0]["resultat"] == "alerte" and publies[0]["action"]["commande"] == "coherence.surfaces"

    ex.passer(c)  # plafond atteint : ne voit rien, ne ferme rien, et le dit
    empreintes = {a["empreinte"] for a in ex.alertes_ouvertes()}
    assert ouvertes[0]["empreinte"] in empreintes
    assert "coherence.surfaces:plafond" in empreintes

    ex.passer(c)  # plus d'écart : l'alerte se ferme
    assert ex.alertes_ouvertes() == []
    assert publies[-1]["resultat"] == "resolue"


def test_declare_une_fois_par_jour_sans_geste_ni_reparateur() -> None:
    decl = lire(FICHIER_PAR_DEFAUT)
    c = next(x for x in decl.controles if x.id == "coherence.surfaces")
    assert REGISTRE[c.interne] is coherence.surfaces
    assert c.gardien == "coherence" and c.si_constat == "signaler"
    assert c.geste is None and c.proposer is None
    assert c.params["rapide"] is True
    assert c.params["plafond_s"] < c.delai_s, "le plafond du vérificateur tombe avant le délai de l'exécuteur"
    t = 1_790_000_000.0
    assert prochaine_echeance(c.quand, prochaine_echeance(c.quand, t)) - prochaine_echeance(c.quand, t) in (82_800, 86_400, 90_000)


def test_attend_le_service_au_demarrage(ctx: Contexte, tmp_path: Path) -> None:
    c = _controle(attente_au_demarrage_s=600)
    decl = Declaration(controles=[c], reglages={}, source=str(tmp_path / "gardiens.json"))
    t = 1_790_000_000.0
    ex = Executeur(decl, ctx, Journal(tmp_path / "etat" / "journal"), tmp_path / "etat", horloge=lambda: t)
    assert ex.etats[c.id].prochaine == t + 600
    assert ex.echeances() == []


def test_le_plafond_tue_la_commande_et_ses_descendants(tmp_path: Path) -> None:
    marque = tmp_path / "enfant.pid"
    script = tmp_path / "long.py"
    script.write_text(
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(marque)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n",
        encoding="utf-8",
    )
    debut = time.monotonic()
    code, sortie = lancer_en_groupe([sys.executable, str(script)], 3.0)
    assert code == 124 and sortie == ""
    assert time.monotonic() - debut < 20
    if os.name != "nt":
        enfant = int(marque.read_text())
        for _ in range(50):
            try:
                os.kill(enfant, 0)
            except ProcessLookupError:
                break
            try:
                # Un zombie en attente de son parent (init) compte comme mort.
                if Path(f"/proc/{enfant}/stat").read_text().split()[2] == "Z":
                    break
            except OSError:
                break
            time.sleep(0.1)
        else:
            pytest.fail("le petit-enfant a survécu au plafond")


def test_une_commande_courte_rend_sa_sortie(tmp_path: Path) -> None:
    code, sortie = lancer_en_groupe([sys.executable, "-c", "print('{}')"], 20.0)
    assert code == 0 and sortie.strip() == "{}"
    assert lancer_en_groupe([str(tmp_path / "absent")], 5.0)[0] == 127
