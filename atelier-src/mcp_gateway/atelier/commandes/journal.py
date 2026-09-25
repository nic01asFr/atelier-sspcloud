"""Le journal unique de l'Atelier : ce qui a été fait, par qui, avec quel effet.

Transverse §1.7 et `coherence-croisee.md` §2 : un seul journal d'événements,
lisible par la personne, dans `~/work/.atelier-etat/journal/AAAA-MM.jsonl`.
Le « carnet de bord » des délégations et le « journal d'actions » de
l'Assistant en sont des vues filtrées, pas des stockages de plus.

Une ligne par événement, au format commun :

    {"id", "quand", "source", "acteur", "objet", "action": {"avant", "apres", ...},
     "resultat", "cout": {"jetons", "secondes"}, "empreinte"}

Ce module ne dépend d'aucun magasin du service : l'exécuteur des gardiens, qui
vit dans un autre processus, écrit par la même fonction (`ecrire`) avec pour
seul paramètre le dossier du journal.

**Aucune valeur secrète n'y entre.** Deux filtres, appliqués à chaque écriture,
quelle que soit la source :

- une clé dont le nom annonce un secret (`token`, `authorization`, `cle`…) voit
  sa valeur remplacée ;
- une valeur connue du fichier d'environnement (`claude-env.sh`) est remplacée
  partout où elle apparaît, même au milieu d'un texte. C'est le filtre par
  valeur que demande T10 : un nom anodin ne protège pas un jeton recopié.

Le journal existant `atelier/journal.py` fond les registres d'une conversation
(l'Atelier et le CLI) : c'est l'histoire d'un fil, pas un journal d'actions.
Il ne couvre aucune partie de celui-ci et reste tel quel.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets as _secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

# Les sources connues. Une source inconnue est refusée : un journal où chacun
# invente son mot ne se filtre plus.
SOURCES = frozenset(
    {
        "commande",  # une commande du catalogue (§1.8)
        "controle",  # un contrôle des gardiens
        "capacite",  # un accès ouvert ou refusé
        "promotion",
        "vue",
        "automate",  # routine, trigger, entretien
        "geste",  # un geste de la personne dans l'interface
        "validation",  # une entrée de la file « À valider » déposée ou tranchée
    }
)

REMPLACEMENT = "[secret]"
# Au-delà, une valeur texte est coupée : le journal dit ce qui s'est passé, il
# ne recopie pas un message de trois pages ni le contenu d'un fichier. Assez
# pour qu'une description de projet (500 au plus) revienne entière à
# l'annulation.
TEXTE_MAX = 600
# Les valeurs trop courtes ne sont pas filtrées par valeur : « 1 » ou « oui »
# remplacés partout rendraient le journal illisible sans rien protéger.
SECRET_LONGUEUR_MIN = 8

# Cherchés dans le nom entier : assez longs pour ne rien attraper par hasard.
_MOTS_SECRETS = (
    "token",
    "jeton",
    "secret",
    "password",
    "mot_de_passe",
    "passwd",
    "authorization",
    "apikey",
    "cookie",
    "credential",
)
# Cherchés comme mots entiers : « cle » est dans « article », « key » dans
# « keyboard ».
_MOTS_ENTIERS = frozenset({"cle", "key", "mdp", "pat"})
_SEPARATEURS = re.compile(r"[^a-z0-9]+")
# Des clés qui contiennent un mot ci-dessus sans porter de secret.
_NOMS_ANODINS = frozenset({"jetons"})


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def nouvel_identifiant(quand: str = "") -> str:
    """`AAAAMMJJ-xxxxxxxxxx` : le jour dit dans quel fichier chercher."""
    quand = quand or _maintenant()
    return f"{quand[:10].replace('-', '')}-{_secrets.token_hex(5)}"


def maintenant() -> str:
    return _maintenant()


def est_un_nom_secret(nom: str) -> bool:
    cle = str(nom).strip().lower()
    if cle in _NOMS_ANODINS:
        return False
    if any(mot in cle for mot in _MOTS_SECRETS):
        return True
    return any(mot in _MOTS_ENTIERS for mot in _SEPARATEURS.split(cle))


def empreinte(*parties: Any) -> str:
    """Une empreinte stable, sans rien révéler de ce qu'elle résume."""
    brut = json.dumps(parties, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()[:16]


class FiltreDesSecrets:
    """Retire d'une valeur ce qui est un secret, par nom et par valeur.

    `valeurs` rend les secrets connus (le contenu de `claude-env.sh`). Il est
    rappelé à chaque écriture, pour qu'un jeton renouvelé soit filtré aussitôt ;
    à lui de mettre en cache s'il lit un fichier.
    """

    def __init__(self, valeurs: Callable[[], Iterable[str]] | None = None) -> None:
        self._valeurs = valeurs

    def _connues(self) -> list[str]:
        if self._valeurs is None:
            return []
        try:
            vues = [v for v in self._valeurs() if isinstance(v, str)]
        except Exception:  # noqa: BLE001 — un filtre qui échoue ne doit pas bloquer
            return []
        # Les plus longues d'abord : un secret qui en contient un autre doit
        # disparaître entier, pas en laissant un morceau.
        return sorted({v for v in vues if len(v) >= SECRET_LONGUEUR_MIN}, key=len, reverse=True)

    def nettoyer(self, valeur: Any) -> Any:
        return self._nettoyer(valeur, self._connues())

    def _nettoyer(self, valeur: Any, connues: list[str]) -> Any:
        if isinstance(valeur, dict):
            return {
                str(k): (REMPLACEMENT if est_un_nom_secret(k) and v not in (None, "", [], {})
                         else self._nettoyer(v, connues))
                for k, v in valeur.items()
            }
        if isinstance(valeur, (list, tuple)):
            return [self._nettoyer(v, connues) for v in valeur]
        if isinstance(valeur, str):
            texte = valeur
            for secret in connues:
                if secret in texte:
                    texte = texte.replace(secret, REMPLACEMENT)
            if len(texte) > TEXTE_MAX:
                texte = texte[:TEXTE_MAX] + "…"
            return texte
        if valeur is None or isinstance(valeur, (bool, int, float)):
            return valeur
        return self._nettoyer(str(valeur), connues)


@dataclass
class Evenement:
    """Une ligne du journal, avant écriture."""

    source: str
    acteur: str
    objet: dict[str, Any]
    action: dict[str, Any]
    resultat: str
    cout: dict[str, Any] | None = None
    empreinte: str = ""
    id: str = ""
    quand: str = ""

    def en_ligne(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "quand": self.quand,
            "source": self.source,
            "acteur": self.acteur,
            "objet": self.objet,
            "action": self.action,
            "resultat": self.resultat,
            "cout": self.cout or {"jetons": 0, "secondes": 0},
            "empreinte": self.empreinte,
        }


_RE_MOIS = re.compile(r"^\d{4}-\d{2}\.jsonl$")


class Journal:
    """Le journal, dans un dossier. Plusieurs écrivains, un verrou par processus.

    Une ligne s'écrit d'un seul `write` en mode ajout (`O_APPEND`) : chaque
    écriture se place en fin de fichier, même quand un autre processus (les
    gardiens) écrit dans le même mois.
    """

    def __init__(self, dossier: Path, *, secrets: Callable[[], Iterable[str]] | None = None) -> None:
        self.dossier = Path(dossier)
        self.filtre = FiltreDesSecrets(secrets)
        self._verrou = threading.Lock()

    def _fichier(self, quand: str) -> Path:
        return self.dossier / f"{quand[:7]}.jsonl"

    def ecrire(self, evenement: Evenement) -> dict[str, Any]:
        if evenement.source not in SOURCES:
            raise ValueError(f"source inconnue : {evenement.source}")
        evenement.quand = evenement.quand or _maintenant()
        evenement.id = evenement.id or nouvel_identifiant(evenement.quand)
        ligne = self.filtre.nettoyer(evenement.en_ligne())
        texte = json.dumps(ligne, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._verrou:
            self.dossier.mkdir(parents=True, exist_ok=True)
            fichier = self._fichier(evenement.quand)
            neuf = not fichier.exists()
            with open(fichier, "a", encoding="utf-8") as flux:
                flux.write(texte)
            if neuf:
                try:
                    os.chmod(fichier, 0o600)
                except OSError:
                    pass
        return ligne

    def lire(
        self,
        *,
        depuis: str = "",
        source: str = "",
        acteur: str = "",
        objet_type: str = "",
        objet_id: str = "",
        commande: str = "",
        limite: int = 200,
    ) -> list[dict[str, Any]]:
        """Les événements, les plus récents d'abord, filtrés.

        `depuis` est un horodatage ISO : seuls les mois qui peuvent le contenir
        sont ouverts.
        """
        if not self.dossier.is_dir():
            return []
        mois = sorted((f for f in self.dossier.iterdir() if _RE_MOIS.match(f.name)), reverse=True)
        if depuis:
            mois = [f for f in mois if f.name[:7] >= depuis[:7]]
        sortie: list[dict[str, Any]] = []
        for fichier in mois:
            try:
                lignes = fichier.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for brut in reversed(lignes):
                try:
                    e = json.loads(brut)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                if depuis and str(e.get("quand") or "") < depuis:
                    continue
                if source and e.get("source") != source:
                    continue
                if acteur and e.get("acteur") != acteur:
                    continue
                obj = e.get("objet") if isinstance(e.get("objet"), dict) else {}
                if objet_type and obj.get("type") != objet_type:
                    continue
                if objet_id and obj.get("id") != objet_id:
                    continue
                act = e.get("action") if isinstance(e.get("action"), dict) else {}
                if commande and act.get("commande") != commande:
                    continue
                sortie.append(e)
                if len(sortie) >= limite:
                    return sortie
        return sortie

    def trouver(self, identifiant: str) -> dict[str, Any] | None:
        """Un événement par son identifiant (sert à « Annuler »)."""
        if not identifiant or not self.dossier.is_dir():
            return None
        jour = identifiant.split("-", 1)[0]
        mois = f"{jour[:4]}-{jour[4:6]}.jsonl" if len(jour) >= 6 else ""
        candidats = [self.dossier / mois] if mois else sorted(self.dossier.glob("*.jsonl"), reverse=True)
        for fichier in candidats:
            try:
                lignes = fichier.read_text(encoding="utf-8").splitlines()
            except OSError:
                continue
            for brut in reversed(lignes):
                if identifiant not in brut:
                    continue
                try:
                    e = json.loads(brut)
                except json.JSONDecodeError:
                    continue
                if isinstance(e, dict) and e.get("id") == identifiant:
                    return e
        return None


def dossier_du_journal(work_dir: Path) -> Path:
    """`~/work/.atelier-etat/journal/`, le seul endroit du journal."""
    return Path(work_dir) / ".atelier-etat" / "journal"


def secrets_du_fichier_d_environnement(chemin: Path) -> Callable[[], list[str]]:
    """Les valeurs de `claude-env.sh`, relues quand le fichier change.

    Les valeurs ne quittent jamais la mémoire du processus : elles ne servent
    qu'à être retirées de ce qui s'écrit.
    """
    cache: dict[str, Any] = {"cle": None, "valeurs": []}

    def lire() -> list[str]:
        try:
            st = chemin.stat()
        except OSError:
            return []
        cle = (st.st_mtime_ns, st.st_size)
        if cache["cle"] != cle:
            from mcp_gateway.atelier.env_secrets import lire_le_fichier

            try:
                cache["valeurs"] = list(lire_le_fichier(chemin).values())
            except OSError:
                cache["valeurs"] = []
            cache["cle"] = cle
        return cache["valeurs"]

    return lire


__all__ = [
    "Evenement",
    "FiltreDesSecrets",
    "Journal",
    "REMPLACEMENT",
    "SOURCES",
    "dossier_du_journal",
    "empreinte",
    "est_un_nom_secret",
    "maintenant",
    "nouvel_identifiant",
    "secrets_du_fichier_d_environnement",
]
