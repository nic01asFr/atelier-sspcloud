"""Le travailleur du pod GPU : il appelle le laboratoire (pod CPU), prend un essai, l'entraîne ici, rend les fichiers.

    python -m laboratoire.travailleur_gpu --maitre http://<pod-cpu>:7860 --racine ~/work/projects/<projet>/gpu

- Il ne garde rien d'essentiel : le laboratoire reste maître de la file, des essais et des résultats.
- Le jeu de données est téléchargé une fois et gardé (par identifiant et empreinte) ; l'essai tourne dans le même sous-processus que d'habitude.
- Tant qu'un essai tourne, il donne signe toutes les 15 secondes (avec les métriques), envoie le journal par morceaux, et fait « battre » le GPU
  (voir `battement`). Quand il n'y a rien à faire il ne fait rien : le serveur peut couper le pod, c'est voulu.
- Un réseau qui tombe ne perd pas l'essai : l'entraînement continue, les fichiers restent sur le volume du pod et partent à la reprise du contact.
- Il n'a qu'un jeton, celui d'un « travailleur » : il ne peut rien d'autre que les routes `/api/travail/`.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from laboratoire.distant import extraire_sur
from laboratoire.projet import Racine

log = logging.getLogger("laboratoire.gpu")

INTERVALLE_SIGNE_S = 15.0
INTERVALLE_BATTEMENT_S = 120.0
MORCEAU_JOURNAL = 200_000
A_NE_PAS_RENDRE = ("yolo", "weights", "journal.log")  # dossiers et fichiers qui restent sur le pod (le journal part au fil de l'eau)
ECHEC_TRANSITOIRE = (urllib.error.URLError, ConnectionError, TimeoutError, OSError)


class Maitre:
    """Le laboratoire vu du travailleur. Rien d'autre que des appels HTTP, avec le jeton en en-tête."""

    def __init__(self, url: str, jeton: str, nom: str, delai: float = 60.0) -> None:
        self.url, self.jeton, self.nom, self.delai = url.rstrip("/"), jeton, nom, delai

    def _requete(self, methode: str, chemin: str, *, json_corps: Any = None, donnees: Any = None, taille: int | None = None, delai: float | None = None):
        entetes = {"Authorization": f"Bearer {self.jeton}"}
        corps = donnees
        if json_corps is not None:
            corps = json.dumps(json_corps).encode()
            entetes["Content-Type"] = "application/json"
        if taille is not None:
            entetes["Content-Length"] = str(taille)
            entetes["Content-Type"] = "application/octet-stream"
        elif isinstance(corps, bytes):
            entetes.setdefault("Content-Type", "application/octet-stream")
        requete = urllib.request.Request(self.url + chemin, data=corps, method=methode, headers=entetes)
        return urllib.request.urlopen(requete, timeout=delai or self.delai)  # noqa: S310 - adresse donnée par la personne

    def json(self, methode: str, chemin: str, **kw: Any) -> Any:
        with self._requete(methode, chemin, **kw) as r:
            return json.loads(r.read() or b"null")

    def prendre(self, gpu: dict[str, Any] | None) -> dict[str, Any] | None:
        return self.json("POST", "/api/travail/prendre", json_corps={"travailleur": self.nom, "gpu": gpu})["essai"]

    def signe(self, essai: str, metriques: str | None) -> dict[str, Any]:
        return self.json("POST", f"/api/travail/{essai}/signe", json_corps={"travailleur": self.nom, "metriques": metriques})

    def journal(self, essai: str, debut: int, morceau: bytes) -> int:
        q = urllib.parse.urlencode({"travailleur": self.nom, "debut": debut})
        return int(self.json("POST", f"/api/travail/{essai}/journal?{q}", donnees=morceau)["suivant"])

    def telecharger_variante(self, variante: str, destination: Path) -> str:
        with self._requete("GET", f"/api/travail/variante/{urllib.parse.quote(variante)}", delai=600) as r, open(destination, "wb") as f:
            shutil.copyfileobj(r, f, 1 << 20)
            return r.headers.get("X-Empreinte", "")

    def terminer(self, essai: str, archive: Path | None, code: int | None, arrete: bool) -> dict[str, Any]:
        q = {"travailleur": self.nom, "arrete": "true" if arrete else "false"}
        if code is not None:
            q["code"] = code
        taille = archive.stat().st_size if archive else 0
        with (open(archive, "rb") if archive else open(os.devnull, "rb")) as f:
            return self.json("POST", f"/api/travail/{essai}/terminer?{urllib.parse.urlencode(q)}", donnees=f, taille=taille, delai=900)


def empaqueter(dossier: Path, destination: Path) -> int:
    """Les fichiers de l'essai à rendre (sans les dossiers volumineux et inutiles ailleurs)."""
    n = 0
    with tarfile.open(destination, "w") as t:
        for fichier in sorted(dossier.rglob("*")):
            relatif = fichier.relative_to(dossier)
            if relatif.parts[0] in A_NE_PAS_RENDRE or relatif.parts[0].endswith(".pt") or not fichier.is_file() or fichier.is_symlink():
                continue
            t.add(fichier, arcname=str(relatif), recursive=False)
            n += 1
    return n


class Travailleur:
    def __init__(
        self, maitre: Maitre, racine: Racine, *, python: str = sys.executable, module: str = "laboratoire.sous_processus",
        battement: Callable[[], Any] | None = None, etat_gpu: Callable[[], dict[str, Any] | None] | None = None,
        horloge: Callable[[], float] = time.monotonic, pause: Callable[[float], None] = time.sleep,
    ) -> None:
        self.maitre, self.racine, self.python, self.module = maitre, racine, python, module
        self.battement, self.etat_gpu, self._horloge, self._pause = battement, etat_gpu, horloge, pause
        racine.preparer()

    # -- jeu de données ---------------------------------------------------

    def variante(self, ident: str, empreinte: str) -> Path:
        """Le jeu de données en local, téléchargé seulement s'il manque ou si le laboratoire l'a reconstruit."""
        from laboratoire.distant import empreinte_variante

        dossier = self.racine.dossier_variante(ident)
        if dossier.is_dir() and empreinte_variante(dossier) == empreinte:
            return dossier
        fd, nom = tempfile.mkstemp(prefix="variante-", suffix=".tar", dir=self.racine.chemin)
        os.close(fd)
        try:
            self.maitre.telecharger_variante(ident, Path(nom))
            temporaire = dossier.with_name(dossier.name + ".nouveau")
            shutil.rmtree(temporaire, ignore_errors=True)
            extraire_sur(Path(nom), temporaire)
            shutil.rmtree(dossier, ignore_errors=True)
            temporaire.rename(dossier)
        finally:
            Path(nom).unlink(missing_ok=True)
        return dossier

    # -- un essai ---------------------------------------------------------

    def executer(self, essai: dict[str, Any]) -> None:
        ident = essai["id"]
        dossier = self.racine.dossier_essai(ident)
        shutil.rmtree(dossier, ignore_errors=True)
        dossier.mkdir(parents=True)
        (dossier / "config.json").write_text(json.dumps(essai["config"], ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            variante = self.variante(essai["variante"], essai["empreinte_variante"])
        except Exception as exc:  # noqa: BLE001 - on rend l'échec au laboratoire, il le dira à la personne
            (dossier / "journal.log").write_text(f"jeu de données non récupéré : {exc}\n", encoding="utf-8")
            self._clore(ident, dossier, 2, False)
            return
        journal = open(dossier / "journal.log", "ab")
        try:
            p = subprocess.Popen(  # noqa: S603 - notre propre module
                [self.python, "-m", self.module, str(dossier), str(variante)],
                stdout=journal, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(dossier),
            )
        finally:
            journal.close()
        arret, envoye, dernier_signe, dernier_battement = False, 0, float("-inf"), float("-inf")
        while True:
            fini = p.poll() is not None
            envoye = self._envoyer_journal(ident, dossier / "journal.log", envoye)
            maintenant = self._horloge()
            if fini:
                break
            if self.battement and maintenant - dernier_battement >= INTERVALLE_BATTEMENT_S:
                dernier_battement = maintenant
                try:
                    self.battement()
                except Exception:  # noqa: BLE001 - un battement raté n'arrête pas un essai
                    log.warning("battement raté", exc_info=True)
            if maintenant - dernier_signe >= INTERVALLE_SIGNE_S:
                dernier_signe = maintenant
                try:
                    metriques = dossier / "metriques.csv"
                    reponse = self.maitre.signe(ident, metriques.read_text(encoding="utf-8") if metriques.is_file() else None)
                    if reponse.get("arreter") and not arret:
                        arret = True
                        self._tuer(p)
                except urllib.error.HTTPError as exc:
                    if exc.code == 409:  # l'essai n'est plus à nous (interrompu pendant une coupure) : on s'arrête, rien à rendre
                        log.warning("%s n'est plus confié à ce travailleur : arrêt", ident)
                        self._tuer(p)
                        p.wait()
                        shutil.rmtree(dossier, ignore_errors=True)
                        return
                    log.warning("signe refusé : %s", exc)
                except ECHEC_TRANSITOIRE:
                    log.warning("laboratoire injoignable : l'essai continue")
            self._pause(1.0)
        self._envoyer_journal(ident, dossier / "journal.log", envoye)
        self._clore(ident, dossier, p.returncode, arret)

    @staticmethod
    def _tuer(p: subprocess.Popen[bytes], delai: float = 8.0) -> None:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            return
        fin = time.monotonic() + delai
        while time.monotonic() < fin and p.poll() is None:
            time.sleep(0.1)
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass

    def _envoyer_journal(self, ident: str, chemin: Path, deja: int) -> int:
        """Envoie ce qui n'est pas encore parti. Le laboratoire dit où il en est : un envoi perdu se rattrape au suivant."""
        try:
            taille = chemin.stat().st_size
            while deja < taille:
                with chemin.open("rb") as f:
                    f.seek(deja)
                    morceau = f.read(MORCEAU_JOURNAL)
                deja = min(self.maitre.journal(ident, deja, morceau), taille)  # la position du laboratoire fait foi
        except ECHEC_TRANSITOIRE:
            pass
        except urllib.error.HTTPError as exc:
            log.warning("journal refusé : %s", exc)
        return deja

    # -- rendre -----------------------------------------------------------

    def _clore(self, ident: str, dossier: Path, code: int | None, arrete: bool) -> None:
        """Écrit la fin de l'essai sur le volume, puis tente de la rendre. Si le laboratoire est injoignable, `reprendre()` s'en chargera."""
        (dossier / "fin.json").write_text(json.dumps({"code": code, "arrete": arrete}), encoding="utf-8")
        self._rendre(ident, dossier)

    def _rendre(self, ident: str, dossier: Path) -> bool:
        fin = json.loads((dossier / "fin.json").read_text(encoding="utf-8"))
        fd, nom = tempfile.mkstemp(prefix="rendu-", suffix=".tar", dir=self.racine.chemin)
        os.close(fd)
        try:
            empaqueter(dossier, Path(nom))
            self.maitre.terminer(ident, Path(nom), fin["code"], bool(fin["arrete"]))
        except urllib.error.HTTPError as exc:
            log.error("%s : fichiers refusés (%s) ; ils restent dans %s", ident, exc, dossier)
            (dossier / "fin.json").rename(dossier / "fin.refusee.json")
            return False
        except ECHEC_TRANSITOIRE:
            log.warning("%s : laboratoire injoignable, les fichiers restent dans %s et partiront à la reprise du contact", ident, dossier)
            return False
        finally:
            Path(nom).unlink(missing_ok=True)
        (dossier / "fin.json").rename(dossier / "fin.rendue.json")
        return True

    def reprendre(self) -> None:
        """Rend les essais terminés dont l'envoi n'a pas abouti (réseau coupé, pod relancé)."""
        if not self.racine.essais.is_dir():
            return
        for dossier in sorted(self.racine.essais.iterdir()):
            if (dossier / "fin.json").is_file():
                self._rendre(dossier.name, dossier)

    # -- la boucle --------------------------------------------------------

    def un_pas(self) -> bool:
        """Un tour : rend ce qui reste, puis prend un essai s'il y en a. Rend True si un essai a été traité."""
        self.reprendre()
        essai = self.maitre.prendre(self.etat_gpu() if self.etat_gpu else None)
        if essai is None:
            return False
        log.info("essai %s pris", essai["id"])
        self.executer(essai)
        return True

    def tourner(self, attente_s: float = 5.0) -> None:
        while True:
            try:
                if self.un_pas():
                    continue
            except ECHEC_TRANSITOIRE as exc:
                log.warning("laboratoire injoignable (%s)", exc)
            except urllib.error.HTTPError as exc:
                log.error("laboratoire : %s", exc)
            self._pause(attente_s)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="laboratoire.travailleur_gpu", description=__doc__)
    p.add_argument("--maitre", default=os.environ.get("LABO_MAITRE"), help="adresse du laboratoire (pod CPU), ex. http://10.233.1.2:7860")
    p.add_argument("--racine", default=os.environ.get("LABO_RACINE"), help="dossier de travail de ce pod (jeux gardés, essais en cours)")
    p.add_argument("--nom", default=os.environ.get("LABO_NOM_TRAVAILLEUR", "gpu"))
    p.add_argument("--sans-battement", action="store_true")
    args = p.parse_args(argv)
    jeton = os.environ.get("LABO_JETON_TRAVAILLEUR", "")
    if not (args.maitre and args.racine and jeton):
        print("il faut --maitre (ou LABO_MAITRE), --racine (ou LABO_RACINE) et LABO_JETON_TRAVAILLEUR", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from laboratoire.api import _etat_gpu
    from laboratoire.battement import battre

    # L'adresse du laboratoire peut changer si son pod est relancé : un fichier `maitre.url` dans la racine la remplace sans redémarrer le travailleur.
    racine = Racine(Path(args.racine))
    maitre = Maitre(args.maitre, jeton, args.nom)
    t = Travailleur(maitre, racine, battement=None if args.sans_battement else battre, etat_gpu=_etat_gpu)
    fichier = racine.chemin / "maitre.url"
    pause_reelle = t._pause

    def pause_et_relire(s: float) -> None:
        if fichier.is_file():
            maitre.url = fichier.read_text(encoding="utf-8").strip().rstrip("/") or maitre.url
        pause_reelle(s)

    t._pause = pause_et_relire
    t.tourner()
    return 0


if __name__ == "__main__":
    sys.exit(main())
