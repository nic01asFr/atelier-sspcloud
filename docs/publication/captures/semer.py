"""Sème une instance locale de l'Atelier avec des données de démonstration.

Tout passe par les vraies routes et commandes du service (projets, créations,
conversations, « À valider », journal) ; seuls les transcrits des tours sont
écrits à la main, au format du CLI, puisque le harnais est factice.
Aucune donnée réelle : projets, parcelles et noms sont inventés.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

import os

ICI = Path(__file__).parent
DEPOT = ICI.parents[2]
# Le dossier de travail de l'instance de démonstration (ATELIER_WORK), jamais le vrai.
WORK = Path(os.environ["DEMO_WORK"])
CLE = (WORK / ".secrets" / "atelier_owner_key").read_text(encoding="utf-8").strip()
cle = httpx.Client(base_url="http://127.0.0.1:8787", headers={"Authorization": "Bearer " + CLE}, timeout=60)
# La personne : une session d'interface, comme le navigateur (cookie + en-tête).
_r = cle.post("/v1/auth/cookie")
_sid = _r.headers["set-cookie"].split(";")[0]
c = httpx.Client(base_url="http://127.0.0.1:8787", timeout=60,
                 headers={"Cookie": _sid, "X-Atelier-Interface": "1", "Origin": "http://127.0.0.1:8787"})
POD = "/home/onyxia/work/projects"


def cmd(_commande: str, _client=None, **arguments):
    r = (_client or c).post(f"/v1/commandes/{_commande}", json={"arguments": arguments})
    if r.status_code >= 400:
        print("ÉCHEC", _commande, r.status_code, r.text[:400], file=sys.stderr)
        return {}
    d = r.json()
    return d.get("resultat", d) if isinstance(d, dict) else d


def neutre(o):
    """Remplace les chemins de la machine par ceux d'un pod."""
    t = json.dumps(o, ensure_ascii=False)
    racine = json.dumps(str(WORK / "projects"), ensure_ascii=False)[1:-1]
    t = t.replace(racine, POD).replace("\\\\", "/")
    return json.loads(t)


def projet(titre, objectif, gabarit):
    for p in c.get("/v1/projects").json().get("projects", []):
        if p.get("title") == titre:
            return p.get("slug")
    r = cmd("atelier_projet_creer", titre=titre, objectif=objectif, gabarit=gabarit)
    return r.get("projet") or r.get("slug")


class Fil:
    def __init__(self, sid: str, heure: str):
        self.sid, self.heure, self.lignes, self.n = sid, heure, [], 0

    def _t(self, m):
        return f"2026-09-26T{self.heure}:{m:02d}.000Z"

    def personne(self, texte, m=0):
        self.lignes.append({"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": texte}]},
                            "session_id": self.sid, "timestamp": self._t(m), "parent_tool_use_id": None})

    def agent(self, texte="", outils=(), m=1, pensee=""):
        contenu = []
        if pensee:
            contenu.append({"type": "thinking", "thinking": pensee})
        if texte:
            contenu.append({"type": "text", "text": texte})
        ids = []
        for nom, entree, _ in outils:
            self.n += 1
            i = f"toolu_{self.sid[:6]}_{self.n:03d}"
            ids.append(i)
            contenu.append({"type": "tool_use", "id": i, "name": nom, "input": entree})
        self.n += 1
        self.lignes.append({"type": "assistant", "message": {"id": f"msg_{self.sid[:6]}_{self.n}", "role": "assistant", "content": contenu},
                            "session_id": self.sid, "timestamp": self._t(m)})
        if outils:
            res = []
            for i, (_, _, sortie) in zip(ids, outils):
                s = sortie if isinstance(sortie, str) else json.dumps(sortie, ensure_ascii=False)
                res.append({"type": "tool_result", "tool_use_id": i, "content": s})
            self.lignes.append({"type": "user", "message": {"role": "user", "content": res}, "session_id": self.sid, "timestamp": self._t(m)})

    def fin(self, texte, m=2):
        self.lignes.append({"type": "result", "subtype": "success", "result": texte, "session_id": self.sid,
                            "timestamp": self._t(m), "duration_ms": 41000, "num_turns": 6})

    def ecrire(self, chemin: Path, tours: int):
        chemin.parent.mkdir(parents=True, exist_ok=True)
        chemin.write_text("".join(json.dumps(l, ensure_ascii=False) + "\n" for l in self.lignes), encoding="utf-8")
        rec_path = WORK / "sessions" / f"{self.sid}.json"
        rec = json.loads(rec_path.read_text(encoding="utf-8"))
        rec.update({"turns": tours, "state": "idle", "title_source": "user"})
        rec_path.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def conversation(slug, titre, kind="code"):
    r = c.post("/v1/sessions", json={"slug": slug, "title": titre, "kind": kind})
    r.raise_for_status()
    d = r.json()
    return d["session_id"], Path(d["transcript_path"])


# ── Projets ────────────────────────────────────────────────────────────────
carte = projet("Carte des parcelles", "Une carte interactive des parcelles de la zone d'étude, servie par une création.", "application")
grist = projet("Lecteur Grist", "Lire et explorer un document .grist dans le navigateur, sans serveur.", "application")
veille = projet("Veille jeux de données", "Repérer chaque semaine les nouveaux jeux de données publics sur les mobilités.", "donnees")
ocs = projet("Rapport OCS GE", "Comparer deux millésimes de l'occupation du sol et en tirer une note.", "document")
print("projets", carte, grist, veille, ocs)

# Données et création de la carte.
racine = WORK / "projects" / carte
(racine / "data").mkdir(exist_ok=True)
(racine / "data" / "parcelles.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": [
    {"type": "Feature", "properties": {"id": i, "usage_2019": a, "usage_2021": b}, "geometry": None}
    for i, a, b in [("P-011", "prairie", "prairie"), ("P-014", "prairie", "artificialise"), ("P-019", "foret", "foret"),
                    ("P-022", "vignoble", "vignoble"), ("P-028", "vignoble", "artificialise"), ("P-033", "prairie", "prairie"),
                    ("P-041", "foret", "artificialise"), ("P-045", "prairie", "prairie")]]}, ensure_ascii=False, indent=1), encoding="utf-8")
creation = neutre(cmd("atelier_artefact_creer", projet=carte, nom="carte", mode="autonome"))
(racine / "artifacts" / "carte").mkdir(parents=True, exist_ok=True)
(racine / "artifacts" / "carte" / "index.html").write_text((ICI / "carte_index.html").read_text(encoding="utf-8"), encoding="utf-8")
verif = neutre(cmd("atelier_artefact_verifier", projet=carte, nom="carte"))

sid, tr = conversation(carte, "Carte des parcelles, 2019 et 2021")
f = Fil(sid, "09:12")
f.personne("Fais-moi une carte des parcelles de la zone d'étude, avec leur usage en 2019 et en 2021, et montre-la moi à côté du fil.")
f.agent("Je regarde d'abord les données du projet.", [
    ("Read", {"file_path": f"{POD}/{carte}/data/parcelles.geojson"}, "8 parcelles, champs id, usage_2019, usage_2021."),
], m=1, pensee="Huit parcelles, deux millésimes : une bascule 2019 / 2021 suffit, et je souligne celles qui changent.")
f.agent("Je crée une page autonome, sans dépendance externe, dans les créations du projet.", [
    ("mcp__atelier__atelier_artefact_creer", {"nom": "carte", "mode": "autonome"}, creation),
    ("Write", {"file_path": f"{POD}/{carte}/artifacts/carte/index.html", "content": "<!DOCTYPE html>…"}, "Fichier écrit (132 lignes)."),
    ("mcp__atelier__atelier_artefact_verifier", {"nom": "carte"}, verif),
], m=3)
f.agent("Je l'ouvre dans mon navigateur pour vérifier le rendu avant de te la montrer.", [
    ("mcp__atelier__atelier_navigateur_ouvrir", {"chemin": "carte/"}, {"adresse": "https://user-idep-atelier-apps.user.lab.sspcloud.fr/_atelier/entree?code=…", "valable_s": 120}),
    ("mcp__chrome-devtools-mcp__navigate_page", {"url": "https://user-idep-atelier-apps.user.lab.sspcloud.fr/carte-des-parcelles/carte/"}, "Successfully navigated."),
    ("mcp__chrome-devtools-mcp__take_snapshot", {}, "heading \"Parcelles de la zone d'étude\"; group \"Millésime\": button \"2019\", button \"2021\" (pressed); img \"Carte des parcelles\""),
    ("mcp__chrome-devtools-mcp__list_console_messages", {}, "Aucun message."),
    ("mcp__atelier__atelier_montrer", {"nom": "carte", "titre": "Carte des parcelles"}, {"montre": True, "onglet": "Carte des parcelles"}),
], m=5)
texte = ("La carte est dans le panneau, à droite.\n\n"
         "- **Bascule 2019 / 2021** en haut à droite ; les parcelles qui changent d'usage sont tracées en pointillé.\n"
         "- **Trois parcelles** passent en artificialisé, pour **1,7 ha** : P-014 (1,2 ha), P-028 (0,4 ha) et P-041 (0,1 ha).\n"
         "- Vérifiée dans mon navigateur : la page se charge, la bascule répond, aucune erreur en console.\n\n"
         "Tu peux l'épingler au projet pour la retrouver dans les autres conversations.")
f.agent(texte, m=6)
f.fin(texte, m=6)
f.ecrire(tr, 1)
SID_CARTE = sid

sid, tr = conversation(carte, "Préparer les données de 2023")
f = Fil(sid, "08:40")
f.personne("Quand le millésime 2023 sortira, qu'est-ce qu'il faudra changer ?")
t = "Deux choses : ajouter une colonne `usage_2023` au fichier des parcelles, et un troisième bouton à la bascule. Le reste de la page lit les colonnes sans les nommer."
f.agent(t, m=1)
f.fin(t, m=1)
f.ecrire(tr, 1)

# Lecteur Grist.
sid, tr = conversation(grist, "Export CSV des tables")
f = Fil(sid, "10:05")
f.personne("Ajoute un bouton pour exporter la table affichée en CSV, et vérifie qu'il marche avec le document d'exemple.")
f.agent("Je lis le code du lecteur.", [
    ("Grep", {"pattern": "function afficherTable", "path": "src"}, "src/lecteur.js:212"),
    ("Read", {"file_path": f"{POD}/{grist}/src/lecteur.js"}, "(1 251 lignes)"),
], m=1)
f.agent("", [
    ("Edit", {"file_path": f"{POD}/{grist}/src/lecteur.js", "old_string": "…", "new_string": "…"}, "Modifié."),
    ("Bash", {"command": "npm test", "description": "Lancer les tests du lecteur"}, "12 tests, 12 réussis"),
], m=3)
t = ("Le bouton « Exporter en CSV » est dans la barre de la table. Il exporte la vue affichée, filtres compris, en UTF-8 avec séparateur `;` pour qu'un tableur français l'ouvre directement.\n\n"
     "Testé sur le document d'exemple : 3 tables, 214 lignes, accents intacts. Un test couvre l'export (`tests/export.test.js`).")
f.agent(t, m=4)
f.fin(t, m=4)
f.ecrire(tr, 3)

# Veille.
sid, tr = conversation(veille, "Nouveaux jeux de données sur les mobilités")
f = Fil(sid, "07:30")
f.personne("Quels jeux de données sur les mobilités ont été publiés cette semaine ?")
f.agent("", [
    ("mcp__datagouv__search_datasets", {"query": "mobilités", "page_size": 20}, "20 résultats"),
], m=1)
t = ("Quatre publications cette semaine méritent un regard :\n\n"
     "| Jeu de données | Producteur | Format |\n|---|---|---|\n"
     "| Comptages vélo permanents | une métropole | CSV, API |\n"
     "| Horaires théoriques des bus | un syndicat de transport | GTFS |\n"
     "| Aménagements cyclables | une région | GeoJSON |\n"
     "| Enquête déplacements 2025 | un observatoire | XLSX |\n\n"
     "J'ai noté les quatre dans `veille/2026-39.md`.")
f.agent(t, m=2)
f.fin(t, m=2)
f.ecrire(tr, 2)

# Rapport OCS GE.
sid, tr = conversation(ocs, "Comparer les millésimes 2019 et 2021")
f = Fil(sid, "11:20")
f.personne("Compare les millésimes 2019 et 2021 sur la zone d'étude : quelles parcelles sont passées en artificialisé ?")
f.agent("", [("Read", {"file_path": f"{POD}/{ocs}/data/ocs_2019_2021.csv"}, "(8 lignes)")], m=1)
t = ("Trois parcelles basculent vers l'artificialisé entre 2019 et 2021, pour **1,7 ha** :\n\n"
     "| Parcelle | 2019 | 2021 | Surface |\n|---|---|---|---|\n"
     "| P-014 | prairie | artificialisé | 1,2 ha |\n| P-028 | vignoble | artificialisé | 0,4 ha |\n| P-041 | forêt | artificialisé | 0,1 ha |\n\n"
     "Le gros du changement est P-014. Les deux autres restent du bruit à cette échelle.")
f.agent(t, m=2)
f.fin(t, m=2)
f.ecrire(tr, 1)

# ── « À valider » et mémoire, par les vraies commandes et la vraie file ──
sys.path.insert(0, str(DEPOT / "atelier-src"))
from mcp_gateway.atelier.commandes.a_valider import FileAValider, dossier_a_valider  # noqa: E402
from mcp_gateway.atelier.commandes.journal import Journal, dossier_du_journal, Evenement  # noqa: E402

journal = Journal(dossier_du_journal(WORK))
file = FileAValider(dossier_a_valider(WORK), journal=journal)
file.deposer("gardien", "Réparer la CI de main", "La CI de main échoue depuis 26 h sur un test de rendu. Un réparateur a proposé un correctif sur une branche.",
             acteur="gardien:sante", projet=grist,
             detail={"constat": "sante.ci-main : échec depuis 26 h", "branche": "gardien/sante/2026-09-26-ci-main", "commits": 1, "ecart": "1 fichier, +4 −1"},
             action={"commande": "atelier_reparation_fusionner", "arguments": {"projet": grist, "branche": "gardien/sante/2026-09-26-ci-main"}})
file.deposer("agent", "Fusionner l'export CSV", "L'agent lancé a terminé l'export CSV sur la branche agent/export-csv : tests verts.",
             acteur="conversation:lancement", projet=grist,
             detail={"branche": "agent/export-csv", "commits": 2, "ecart": "3 fichiers, +86 −4"},
             action={"commande": "atelier_reparation_fusionner", "arguments": {"projet": grist, "branche": "agent/export-csv"}})
cmd("atelier_memoire_proposer", type="preference", texte="Préfère des tableaux de synthèse courts, surfaces en hectares, séparateur décimal français.",
    raison="Demandé dans trois conversations de la semaine.")

# ── Assistant ──────────────────────────────────────────────────────────────
av = neutre(cmd("atelier_a_valider"))
nouveau = neutre(cmd("atelier_projet_creer", titre="Note de synthèse OCS GE", objectif="Rédiger la note de synthèse à partir du rapport de comparaison.", gabarit="document"))
lancer = neutre(cmd("atelier_lancer_agent", _client=cle, projet=grist, message="Relire l'export CSV et ajouter l'export de toutes les tables en une archive.", duree_min=15))
sid, tr = conversation(None, "Où en sont mes projets ?", kind="assistant")
f = Fil(sid, "11:45")
f.personne("Où en sont mes projets, et qu'est-ce qui attend mon accord ?")
f.agent("", [
    ("mcp__atelier__atelier_carte", {"forme": "synthetique"}, "4 projets actifs ; 1 création autonome ; 0 alerte grave ; 3 propositions en attente"),
    ("mcp__atelier__atelier_a_valider", {}, av),
], m=1)
t = ("Quatre projets actifs :\n\n"
     "- **Carte des parcelles** : la carte 2019 / 2021 est faite et vérifiée ; elle est dans le panneau.\n"
     "- **Lecteur Grist** : l'export CSV est prêt sur une branche, tests verts.\n"
     "- **Veille jeux de données** : quatre nouveautés relevées cette semaine.\n"
     "- **Rapport OCS GE** : la comparaison est écrite, la note reste à rédiger.\n\n"
     "**À votre accord**, trois propositions dans « À valider » : fusionner l'export CSV, fusionner la réparation de la CI proposée par le gardien Santé, et retenir une préférence de présentation.")
f.agent(t, m=2)
f.personne("Crée un projet pour la note de synthèse, et confie à un agent l'export de toutes les tables du Lecteur Grist.", m=4)
f.agent("", [
    ("mcp__atelier__atelier_projet_creer", {"titre": "Note de synthèse OCS GE", "gabarit": "document"}, nouveau),
    ("mcp__atelier__atelier_lancer_agent", {"projet": grist, "message": "Relire l'export CSV et ajouter l'export de toutes les tables en une archive.", "duree_min": 15}, lancer),
], m=5)
t = ("Le projet est créé (vous pouvez l'annuler depuis sa carte). Pour l'agent, j'ai préparé le lancement : il travaillera sur une branche, "
     "15 minutes au plus, et sa fin arrivera dans « À valider ». Il part quand vous répondez « Oui ».")
f.agent(t, m=5)
f.fin(t, m=5)
f.ecrire(tr, 2)

print("carte", SID_CARTE)
