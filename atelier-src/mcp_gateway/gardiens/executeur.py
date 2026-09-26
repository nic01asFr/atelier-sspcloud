"""L'exécuteur des gardiens : ordonnancer, exécuter, dédoublonner, journaliser, surveiller.

Ce qu'il fait, et seulement cela (décision J-a) :

- il fait tourner les contrôles déclarés, chacun à son rythme, chacun borné
  par son `delai_s` (un contrôle bloqué n'arrête pas les autres) ;
- il écrit une ligne au journal par exécution, même « rien à signaler » ;
- il tient **une alerte par empreinte** : le même constat revu cinquante fois
  est une alerte avec un compteur, pas cinquante alertes ; un constat qui
  disparaît ferme son alerte ;
- **homme mort** : un contrôle qui n'a pas tourné à l'heure prévue (exécuteur
  arrêté, contrôle bloqué) est lui-même une alerte ;
- il applique la liste fermée de gestes (`gestes.py`), à ses conditions, et
  journalise chaque geste avec l'avant et l'après ;
- il se laisse piloter à chaud par l'Atelier (`api.py`, `POST /pilotage`) :
  lancer un contrôle tout de suite, le couper, le réactiver. Une coupure
  survit au redémarrage (`coupes.json`) ; la déclaration reste la source, et
  un contrôle qu'elle déclare `"actif": false` ne se réactive pas d'ici.

Il ne consomme aucun jeton : aucun contrôle n'appelle de modèle.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Any

from mcp_gateway.gardiens import gestes as gestes_mod
from mcp_gateway.gardiens import reparations as reparations_mod
from mcp_gateway.gardiens.controles import REGISTRE
from mcp_gateway.gardiens.controles.commun import NIVEAUX, Contexte
from mcp_gateway.gardiens.declaration import Controle, Declaration, periode_attendue, prochaine_echeance
from mcp_gateway.gardiens.journal import Journal, horodatage

log = logging.getLogger("atelier.gardiens")

HOMME_MORT = "gardiens.homme-mort"
RELANCES_PAR_HEURE = 3


@dataclass
class EtatControle:
    derniere: float | None = None
    prochaine: float = 0.0
    etat: str | None = None
    secondes: float | None = None
    echecs_consecutifs: int = 0
    premier_echec: float | None = None
    en_cours: bool = False
    resultat: dict[str, Any] | None = None
    gestes: list[float] = field(default_factory=list)


def gestes_permis(env: dict[str, str] | None = None) -> bool:
    return (env if env is not None else os.environ).get("ATELIER_GARDIENS_GESTES", "1") != "0"


def normaliser(brut: Any, c: Controle) -> dict[str, Any]:
    """Un résultat au contrat `{etat, constats:[{empreinte, objet, resume, preuve}]}`, quoi qu'on ait reçu."""
    if not isinstance(brut, dict):
        return {
            "etat": "alerte",
            "constats": [_constat(f"{c.id}:sortie-invalide", c.id, "le contrôle n'a pas rendu un objet JSON")],
            "erreur": True,
        }
    constats = []
    for i, x in enumerate(brut.get("constats") or []):
        if not isinstance(x, dict):
            continue
        niveau = x.get("niveau") if x.get("niveau") in NIVEAUX[1:] else "alerte"
        constats.append(
            {
                "empreinte": str(x.get("empreinte") or f"{c.id}:{i}")[:300],
                "objet": str(x.get("objet") or "")[:300],
                "resume": str(x.get("resume") or "")[:300],
                "preuve": str(x.get("preuve") or "")[:500],
                "niveau": niveau,
            }
        )
    etat = brut.get("etat") if brut.get("etat") in NIVEAUX else "alerte"
    if constats and etat == "ok":
        etat = max((x["niveau"] for x in constats), key=NIVEAUX.index)
    sortie: dict[str, Any] = {"etat": etat, "constats": constats}
    if isinstance(brut.get("donnees"), dict):
        sortie["donnees"] = brut["donnees"]
    if brut.get("erreur"):
        sortie["erreur"] = True
    return sortie


def _constat(empreinte: str, objet: str, resume: str, preuve: str = "", niveau: str = "alerte") -> dict[str, str]:
    return {"empreinte": empreinte, "objet": objet, "resume": resume, "preuve": preuve, "niveau": niveau}


def _ecrire_json(chemin: Path, donnees: Any) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(chemin.name + ".tmp")
    provisoire.write_text(json.dumps(donnees, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(provisoire, chemin)


def _lire_json(chemin: Path) -> Any:
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


class Executeur:
    def __init__(
        self,
        declaration: Declaration,
        ctx: Contexte,
        journal: Journal,
        dossier_etat: Path | None,
        *,
        permettre_gestes: bool | None = None,
        a_blanc: bool = False,
        horloge=time.time,
        attente_apres_geste_s: float | None = None,
        publier: Callable[[dict[str, Any]], None] | None = None,
        reparations: "reparations_mod.Reparations | None" = None,
    ) -> None:
        self.declaration = declaration
        self.controles = {c.id: c for c in declaration.controles}
        self.ctx = ctx
        self.journal = journal
        self.dossier_etat = None if a_blanc else dossier_etat
        self.permettre_gestes = gestes_permis(ctx.env) if permettre_gestes is None else permettre_gestes
        self.a_blanc = a_blanc
        self.horloge = horloge
        self.attente_apres_geste_s = attente_apres_geste_s
        # Le journal unique de l'Atelier (architecture-transverse §1.7) : ce qu'une
        # personne doit lire. Le journal des gardiens reste le journal technique
        # de chaque exécution ; seuls les ouvertures et fermetures d'alertes et
        # les gestes passent ici.
        self.publier = None if a_blanc else publier
        # G5 : les demandes d'agents réparateurs. Jamais à blanc.
        self.reparations = None if a_blanc else (reparations or self._reparations_par_defaut())
        self.demarre_a = horloge()
        self.etats: dict[str, EtatControle] = {c.id: EtatControle() for c in declaration.controles}
        self.alertes: dict[str, dict[str, Any]] = {}
        # Les contrôles coupés à chaud : {id: {par, quand}}. Un contrôle coupé
        # ne tourne plus, n'a plus d'échéance et ne déclenche plus d'homme mort.
        self.coupes: dict[str, dict[str, Any]] = {}
        self._verrou = threading.RLock()
        self._arret = threading.Event()
        self._fils: list[threading.Thread] = []
        self._occupes: set[str] = set()
        ctx.etat_executeur = self.etat_des_controles
        self._reprendre()

    def _reparations_par_defaut(self) -> "reparations_mod.Reparations":
        ctx = self.ctx

        def cle() -> str:
            try:
                return (Path(ctx.secrets_dir) / "atelier_lanceur_key").read_text(encoding="utf-8").strip()
            except OSError:
                return ""

        return reparations_mod.Reparations(
            dossier_etat=self.dossier_etat,
            cle=cle,
            poster=reparations_mod.poster_par_http(ctx.port_atelier),
            env=ctx.env,
            par_jour=int((ctx.env or {}).get("ATELIER_REPARATIONS_PAR_JOUR") or reparations_mod.PAR_JOUR_DEFAUT),
            nettoyer=self.journal.filtre.nettoyer,
        )

    # --- état durable -------------------------------------------------------

    def _reprendre(self) -> None:
        """Relit l'état d'avant un redémarrage ; un contrôle en retard est un homme mort."""
        maintenant = self.horloge()
        precedent = _lire_json(self.dossier_etat / "etat.json") if self.dossier_etat else None
        alertes = _lire_json(self.dossier_etat / "alertes.json") if self.dossier_etat else None
        if isinstance(alertes, dict):
            self.alertes = {k: v for k, v in alertes.items() if isinstance(v, dict)}
        coupes = _lire_json(self.dossier_etat / "coupes.json") if self.dossier_etat else None
        if isinstance(coupes, dict):
            self.coupes = {k: v for k, v in coupes.items() if k in self.controles and isinstance(v, dict)}
        for rang, c in enumerate(self.declaration.controles):
            st = self.etats[c.id]
            ancien = (precedent or {}).get(c.id) if isinstance(precedent, dict) else None
            if isinstance(ancien, dict):
                st.derniere = ancien.get("derniere")
                st.etat = ancien.get("etat")
                st.echecs_consecutifs = int(ancien.get("echecs_consecutifs") or 0)
                st.premier_echec = ancien.get("premier_echec")
            # Tout part dans la première minute, étalé : on ne sait rien de l'instant.
            st.prochaine = maintenant + min(rang * 2.0, 60.0)
            if self.actif(c) and st.derniere is not None:
                attendu = st.derniere + periode_attendue(c.quand, st.derniere) + self.tolerance(c)
                if maintenant > attendu:
                    self._homme_mort(c, maintenant, f"dernière exécution {horodatage(st.derniere)}, rien depuis")

    def _sauver(self) -> None:
        if not self.dossier_etat:
            return
        with self._verrou:
            etat = {
                cid: {
                    "derniere": st.derniere,
                    "etat": st.etat,
                    "echecs_consecutifs": st.echecs_consecutifs,
                    "premier_echec": st.premier_echec,
                }
                for cid, st in self.etats.items()
            }
            # Sous le verrou : deux gardiens qui finissent ensemble écriraient
            # le même fichier provisoire.
            _ecrire_json(self.dossier_etat / "etat.json", etat)
            _ecrire_json(self.dossier_etat / "alertes.json", self.alertes)
            _ecrire_json(self.dossier_etat / "coupes.json", self.coupes)

    # --- exécution ----------------------------------------------------------

    def actif(self, c: Controle) -> bool:
        """Déclaré actif, et pas coupé à chaud."""
        return c.actif and c.id not in self.coupes

    @staticmethod
    def tolerance(c: Controle) -> float:
        """Le retard admis avant l'homme mort : un contrôle peut attendre son tour
        derrière un autre du même gardien (un seul à la fois par gardien)."""
        return max(300.0, 2 * c.delai_s)

    def executer_controle(self, c: Controle) -> dict[str, Any]:
        nom = c.interne
        if nom is not None:
            fonction = REGISTRE.get(nom)
            if fonction is None:
                return normaliser({"etat": "alerte", "constats": [_constat(f"{c.id}:inconnu", c.id, f"contrôle interne inconnu {nom!r}")], "erreur": True}, c)
            boite: dict[str, Any] = {}

            def corps() -> None:
                try:
                    boite["r"] = fonction(self.ctx, c)
                except Exception as exc:  # noqa: BLE001 — un contrôle cassé est un constat, pas une panne
                    boite["e"] = f"{type(exc).__name__}: {exc}"

            fil = threading.Thread(target=corps, name=f"gardien-{c.id}", daemon=True)
            fil.start()
            fil.join(c.delai_s)
            if fil.is_alive():
                return normaliser({"etat": "alerte", "constats": [_constat(f"{c.id}:delai", c.id, f"délai de {c.delai_s:.0f} s dépassé")], "erreur": True}, c)
            if "e" in boite:
                return normaliser({"etat": "alerte", "constats": [_constat(f"{c.id}:erreur", c.id, "le contrôle a levé une erreur", boite["e"][:300])], "erreur": True}, c)
            return normaliser(boite.get("r"), c)
        cwd = str(Path(self.declaration.source).parent)
        try:
            fini = subprocess.run(  # noqa: S603 — commande de la déclaration, sans shell
                c.commande, capture_output=True, text=True, timeout=c.delai_s, cwd=cwd, stdin=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired:
            return normaliser({"etat": "alerte", "constats": [_constat(f"{c.id}:delai", c.id, f"délai de {c.delai_s:.0f} s dépassé")], "erreur": True}, c)
        except OSError as exc:
            return normaliser({"etat": "alerte", "constats": [_constat(f"{c.id}:lancement", c.id, "commande impossible à lancer", str(exc)[:200])], "erreur": True}, c)
        try:
            brut = json.loads(fini.stdout)
        except json.JSONDecodeError:
            return normaliser({"etat": "alerte", "constats": [_constat(f"{c.id}:sortie-invalide", c.id, "sortie non JSON", f"code {fini.returncode}")], "erreur": True}, c)
        return normaliser(brut, c)

    def passer(self, c: Controle) -> dict[str, Any]:
        """Exécute un contrôle, met à jour alertes et état, applique un geste, journalise."""
        st = self.etats[c.id]
        with self._verrou:
            st.en_cours = True
        debut = time.monotonic()
        try:
            res = self.executer_controle(c)
        finally:
            with self._verrou:
                st.en_cours = False
        secondes = round(time.monotonic() - debut, 2)
        maintenant = self.horloge()
        with self._verrou:
            st.derniere = maintenant
            st.prochaine = prochaine_echeance(c.quand, maintenant)
            st.etat = res["etat"]
            st.secondes = secondes
            st.resultat = res
            if res["etat"] == "alerte":
                st.echecs_consecutifs += 1
                st.premier_echec = st.premier_echec or maintenant
            else:
                st.echecs_consecutifs = 0
                st.premier_echec = None
            nouvelles, resolues = self._alertes(c, res, maintenant)
            self._fermer(f"{HOMME_MORT}:{c.id}", maintenant, resolues)
        action = self._geste(c, res, maintenant)
        reparations = self._proposer(c, maintenant)
        ligne: dict[str, Any] = {
            "gardien": c.gardien,
            "controle": c.id,
            "portee": c.portee,
            "etat": res["etat"],
            "constats": res["constats"],
            "alertes": {"nouvelles": nouvelles, "resolues": resolues},
            "cout": {"jetons": 0, "secondes": secondes},
        }
        donnees = res.get("donnees")
        if donnees is not None:
            texte = json.dumps(donnees, ensure_ascii=False, default=str)
            ligne["donnees"] = donnees if len(texte) <= 2000 else {"taille": len(texte)}
        if action is not None:
            ligne["action"] = action
        if reparations:
            ligne["reparations"] = reparations
        self.journal.ecrire(ligne)
        self._publier_les_evenements(c, nouvelles, resolues, action)
        self._publier_les_reparations(c, reparations)
        self._sauver()
        return ligne

    def _publier_les_evenements(
        self, c: Controle, nouvelles: list[str], resolues: list[str], action: dict[str, Any] | None
    ) -> None:
        if self.publier is None:
            return
        evenements: list[dict[str, Any]] = []
        for emp in nouvelles:
            a = self.alertes.get(emp) or {}
            evenements.append({
                "source": "controle",
                "objet": {"type": c.portee or "atelier", "id": a.get("objet", "")},
                "action": {"commande": c.id, "classe": "lecture", "origine": c.gardien, "avant": None,
                           "apres": {"alerte": "ouverte", "niveau": a.get("niveau"), "resume": a.get("resume")}},
                "resultat": "alerte",
                "empreinte": emp,
            })
        for emp in resolues:
            a = self.alertes.get(emp) or {}
            evenements.append({
                "source": "controle",
                "objet": {"type": c.portee or "atelier", "id": a.get("objet", "")},
                "action": {"commande": c.id, "classe": "lecture", "origine": c.gardien,
                           "avant": {"alerte": "ouverte"}, "apres": {"alerte": "resolue"}},
                "resultat": "resolue",
                "empreinte": emp,
            })
        if action is not None:
            evenements.append({
                "source": "geste",
                "objet": {"type": c.portee or "atelier", "id": action.get("nom", "")},
                "action": {"commande": action.get("nom", ""), "classe": "reversible", "origine": c.gardien,
                           "avant": action.get("avant"), "apres": action.get("apres")},
                "resultat": "refuse" if action.get("refuse") else "fait",
                "empreinte": "",
            })
        for e in evenements:
            try:
                self.publier(e)
            except Exception:  # noqa: BLE001 — le journal unique ne doit jamais arrêter un contrôle
                pass

    def _proposer(self, c: Controle, maintenant: float) -> list[dict[str, Any]]:
        """G5 : un constat qui persiste au-delà du seuil déclaré demande un réparateur."""
        if self.reparations is None or not c.proposer:
            return []
        try:
            return self.reparations.examiner(c, self.alertes, maintenant)
        except Exception as exc:  # noqa: BLE001 — une demande ratée ne casse pas le contrôle
            log.exception("réparation pour %s", c.id)
            return [{"type": "reparation", "controle": c.id, "echec": f"{type(exc).__name__}: {exc}"[:300]}]

    def _publier_les_reparations(self, c: Controle, reparations: list[dict[str, Any]]) -> None:
        if self.publier is None:
            return
        for r in reparations:
            demandee = r.get("demandee") or {}
            try:
                self.publier({
                    "source": "automate",
                    "objet": {"type": "projet", "id": demandee.get("projet") or ""},
                    "action": {"commande": "reparation", "classe": "engageante", "origine": c.gardien,
                               "avant": {"alerte": r.get("empreinte")},
                               "apres": demandee or {"refuse": r.get("refuse") or r.get("echec")}},
                    "resultat": "demandee" if demandee else ("refuse" if r.get("refuse") else "echec"),
                    "empreinte": r.get("empreinte") or "",
                })
            except Exception:  # noqa: BLE001 — le journal unique ne doit jamais arrêter un contrôle
                pass

    def _alertes(self, c: Controle, res: dict[str, Any], maintenant: float) -> tuple[list[str], list[str]]:
        vues = set()
        nouvelles = []
        for x in res["constats"]:
            emp = x["empreinte"]
            vues.add(emp)
            a = self.alertes.get(emp)
            if a and a.get("ouverte"):
                a.update(vu_le=horodatage(maintenant), compte=int(a.get("compte", 1)) + 1, preuve=x["preuve"], niveau=x["niveau"])
                continue
            nouvelles.append(emp)
            self.alertes[emp] = {
                "empreinte": emp,
                "controle": c.id,
                "gardien": c.gardien,
                "portee": c.portee,
                "objet": x["objet"],
                "resume": x["resume"],
                "preuve": x["preuve"],
                "niveau": x["niveau"],
                "depuis": horodatage(maintenant),
                "vu_le": horodatage(maintenant),
                "compte": 1,
                "ouverte": True,
            }
        resolues: list[str] = []
        if not res.get("erreur"):
            # Un contrôle en erreur ne voit rien : il ne ferme rien non plus.
            for emp, a in self.alertes.items():
                if a.get("controle") == c.id and a.get("ouverte") and emp not in vues:
                    a.update(ouverte=False, resolue_le=horodatage(maintenant))
                    resolues.append(emp)
        return nouvelles, resolues

    def _fermer(self, emp: str, maintenant: float, resolues: list[str]) -> None:
        a = self.alertes.get(emp)
        if a and a.get("ouverte"):
            a.update(ouverte=False, resolue_le=horodatage(maintenant))
            resolues.append(emp)

    def _homme_mort(self, c: Controle, maintenant: float, preuve: str) -> None:
        emp = f"{HOMME_MORT}:{c.id}"
        with self._verrou:
            a = self.alertes.get(emp)
            if a and a.get("ouverte"):
                return
            self.alertes[emp] = {
                "empreinte": emp,
                "controle": HOMME_MORT,
                "gardien": c.gardien,
                "portee": c.portee,
                "objet": c.id,
                "resume": "contrôle qui n'a pas tourné à l'heure prévue",
                "preuve": preuve,
                "niveau": "alerte",
                "depuis": horodatage(maintenant),
                "vu_le": horodatage(maintenant),
                "compte": 1,
                "ouverte": True,
            }
        self.journal.ecrire(
            {
                "gardien": c.gardien,
                "controle": HOMME_MORT,
                "portee": c.portee,
                "etat": "alerte",
                "constats": [_constat(emp, c.id, "contrôle qui n'a pas tourné à l'heure prévue", preuve)],
                "alertes": {"nouvelles": [emp], "resolues": []},
                "cout": {"jetons": 0, "secondes": 0},
            }
        )
        self._sauver()

    def verifier_homme_mort(self) -> list[str]:
        maintenant = self.horloge()
        en_retard = []
        for c in self.declaration.controles:
            st = self.etats[c.id]
            # La tolérance couvre le délai du contrôle : un contrôle en cours
            # depuis plus longtemps est bloqué, pas lent.
            if self.actif(c) and maintenant > st.prochaine + self.tolerance(c):
                en_retard.append(c.id)
                self._homme_mort(c, maintenant, f"attendu à {horodatage(st.prochaine)}")
        return en_retard

    # --- gestes -------------------------------------------------------------

    def _geste(self, c: Controle, res: dict[str, Any], maintenant: float) -> dict[str, Any] | None:
        if c.si_constat != "geste" or not c.geste or res["etat"] != "alerte" or res.get("erreur"):
            return None
        g = gestes_mod.GESTES[c.geste]
        st = self.etats[c.id]
        # Les paramètres peuvent durcir les conditions, jamais les assouplir.
        echecs_min = max(g.echecs_avant, int(c.params.get("echecs_avant_geste", 0)))
        silence_min = max(g.silence_min_s, float(c.params.get("silence_min_s", 0)))
        if st.echecs_consecutifs < echecs_min:
            return None
        silence = maintenant - (st.premier_echec or maintenant)
        if silence < silence_min:
            return None
        action: dict[str, Any] = {"type": "geste", "nom": c.geste, "avant": _resume(res)}
        if self.a_blanc:
            return {**action, "refuse": "exécution à blanc"}
        if not self.permettre_gestes:
            return {**action, "refuse": "ATELIER_GARDIENS_GESTES=0"}
        if c.geste == "relancer_atelier" and (self.ctx.env or {}).get("ATELIER_AVANT_PLAN") == "1":
            # En mode image, l'Atelier est le processus principal du conteneur :
            # le relancer arrêterait le pod. La sonde reste, le geste non.
            return {**action, "refuse": "ATELIER_AVANT_PLAN=1 : relancer l'Atelier arrêterait le conteneur"}
        recents = [t for t in st.gestes if maintenant - t < 3600]
        if len(recents) >= RELANCES_PAR_HEURE:
            return {**action, "refuse": f"{RELANCES_PAR_HEURE} relances dans l'heure : on attend la personne"}
        st.gestes = recents + [maintenant]
        action["script"] = gestes_mod.executer(c.geste, self.ctx)
        apres = self._attendre_le_retour(c)
        action["apres"] = _resume(apres)
        if apres["etat"] != "alerte":
            with self._verrou:
                st.echecs_consecutifs = 0
                st.premier_echec = None
        return action

    def _attendre_le_retour(self, c: Controle) -> dict[str, Any]:
        attente = self.attente_apres_geste_s
        if attente is None:
            attente = float(c.params.get("attente_apres_geste_s", 30))
        fin = time.monotonic() + attente
        while True:
            res = self.executer_controle(c)
            if res["etat"] != "alerte" or time.monotonic() >= fin:
                return res
            time.sleep(2.0)

    # --- boucle -------------------------------------------------------------

    def echeances(self) -> list[Controle]:
        maintenant = self.horloge()
        return [
            c
            for c in self.declaration.controles
            if self.actif(c) and not self.etats[c.id].en_cours and self.etats[c.id].prochaine <= maintenant
        ]

    def tour(self) -> list[dict[str, Any]]:
        """Exécute ce qui est dû, en série (tests, exécution à blanc)."""
        return [self.passer(c) for c in self.echeances()]

    def lancer_les_echeances(self) -> None:
        """Un fil par gardien, un contrôle à la fois dans chacun : un contrôle
        lent de la sécurité ne retarde pas les sondes de santé."""
        par_gardien: dict[str, list[Controle]] = {}
        for c in self.echeances():
            par_gardien.setdefault(c.gardien, []).append(c)
        for gardien, liste in par_gardien.items():
            with self._verrou:
                if gardien in self._occupes:
                    continue
                self._occupes.add(gardien)

            def serie(liste: list[Controle] = liste, gardien: str = gardien) -> None:
                try:
                    for c in liste:
                        if self._arret.is_set():
                            return
                        try:
                            self.passer(c)
                        except Exception:  # noqa: BLE001 — la boucle ne meurt pas d'un contrôle
                            log.exception("contrôle %s", c.id)
                finally:
                    with self._verrou:
                        self._occupes.discard(gardien)

            threading.Thread(target=serie, name=f"gardien-{gardien}", daemon=True).start()

    def tout_une_fois(self) -> list[dict[str, Any]]:
        return [self.passer(c) for c in self.declaration.controles if self.actif(c)]

    def demarrer(self, pas_s: float = 5.0, veille_s: float = 30.0) -> None:
        def boucle() -> None:
            while not self._arret.is_set():
                try:
                    self.lancer_les_echeances()
                except Exception:  # noqa: BLE001 — la boucle ne meurt pas d'un contrôle
                    log.exception("tour des gardiens")
                self._arret.wait(pas_s)

        def veilleur() -> None:
            while not self._arret.wait(veille_s):
                try:
                    self.verifier_homme_mort()
                except Exception:  # noqa: BLE001
                    log.exception("homme mort")

        for cible, nom in ((boucle, "gardiens-boucle"), (veilleur, "gardiens-homme-mort")):
            fil = threading.Thread(target=cible, name=nom, daemon=True)
            fil.start()
            self._fils.append(fil)

    def arreter(self) -> None:
        self._arret.set()

    # --- pilotage (l'Atelier, par l'API locale) -----------------------------

    def _cibles(self, gardien: str | None, controle: str | None) -> list[Controle]:
        if controle:
            c = self.controles.get(controle)
            if c is None:
                raise KeyError(f"contrôle inconnu : {controle}")
            return [c]
        if gardien:
            liste = [c for c in self.declaration.controles if c.gardien == gardien]
            if not liste:
                raise KeyError(f"gardien sans contrôle : {gardien}")
            return liste
        raise KeyError("ni gardien ni contrôle")

    def lancer_maintenant(self, gardien: str | None = None, controle: str | None = None) -> list[str]:
        """Avance l'échéance des contrôles visés : la boucle les prend au tour suivant.

        Rien ne tourne dans l'appel lui-même : un contrôle garde son fil, son
        délai et son rang derrière les autres du même gardien. Un contrôle
        coupé ou déjà en cours n'est pas relancé.
        """
        maintenant = self.horloge()
        lances = []
        with self._verrou:
            for c in self._cibles(gardien, controle):
                st = self.etats[c.id]
                if self.actif(c) and not st.en_cours:
                    st.prochaine = maintenant
                    lances.append(c.id)
        return lances

    def couper(self, gardien: str | None = None, controle: str | None = None, par: str = "") -> list[str]:
        maintenant = self.horloge()
        coupes: list[str] = []
        resolues: list[str] = []
        with self._verrou:
            for c in self._cibles(gardien, controle):
                if c.id in self.coupes or not c.actif:
                    continue
                self.coupes[c.id] = {"par": par or "atelier", "quand": horodatage(maintenant)}
                coupes.append(c.id)
                # Un contrôle coupé n'est pas en retard : son homme mort se ferme.
                self._fermer(f"{HOMME_MORT}:{c.id}", maintenant, resolues)
        if coupes:
            self._sauver()
        return coupes

    def reactiver(self, gardien: str | None = None, controle: str | None = None, par: str = "") -> list[str]:
        del par
        maintenant = self.horloge()
        repris: list[str] = []
        with self._verrou:
            for c in self._cibles(gardien, controle):
                if c.id not in self.coupes:
                    continue
                del self.coupes[c.id]
                # Il repart tout de suite : l'échéance d'avant la coupure est passée.
                self.etats[c.id].prochaine = maintenant
                repris.append(c.id)
        if repris:
            self._sauver()
        return repris

    # --- lecture (API) ------------------------------------------------------

    def etat_des_controles(self) -> list[dict[str, Any]]:
        with self._verrou:
            return [
                {
                    **c.en_dict(),
                    "source": self.declaration.source,
                    "derniere": horodatage(self.etats[c.id].derniere) if self.etats[c.id].derniere else None,
                    "actif": self.actif(c),
                    "actif_declare": c.actif,
                    "coupe": self.coupes.get(c.id),
                    "prochaine": horodatage(self.etats[c.id].prochaine) if self.actif(c) else None,
                    "etat": self.etats[c.id].etat,
                    "secondes": self.etats[c.id].secondes,
                    "echecs_consecutifs": self.etats[c.id].echecs_consecutifs,
                    "en_cours": self.etats[c.id].en_cours,
                }
                for c in self.declaration.controles
            ]

    def alertes_ouvertes(self, toutes: bool = False) -> list[dict[str, Any]]:
        with self._verrou:
            liste = [dict(a) for a in self.alertes.values() if toutes or a.get("ouverte")]
        return sorted(liste, key=lambda a: (a.get("niveau") != "alerte", a.get("depuis") or ""))

    def resultat(self, controle: str) -> dict[str, Any] | None:
        st = self.etats.get(controle)
        with self._verrou:
            return dict(st.resultat) if st and st.resultat else None


def _resume(res: dict[str, Any]) -> dict[str, Any]:
    return {"etat": res["etat"], "preuve": "; ".join(x["preuve"] for x in res["constats"])[:300]}
