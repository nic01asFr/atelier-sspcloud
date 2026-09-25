"""La déclaration des contrôles (`gardiens.json`) et leur rythme.

Schéma d'un contrôle (`coherence-croisee.md` §1.2) :
`id, gardien, portee, quand, commande, delai_s, si_constat, geste`, plus
`proposer` (lu, pas encore servi : G5), `params` (réglages propres au contrôle)
et `actif` (couper un contrôle sans le retirer).

`quand` a une seule forme (M6) : `{"toutes_les_min": N}` ou
`{"cron": "m h jdm mois jds", "tz": "Europe/Paris"}`.

`commande` est une liste d'arguments. `["interne", "<nom>"]` désigne une
fonction de ce paquet (`controles.REGISTRE`) ; toute autre liste est un
exécutable qui écrit son résultat JSON sur sa sortie.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

GARDIENS = frozenset({"sante", "securite", "coherence", "entretien"})
SI_CONSTAT = frozenset({"signaler", "geste"})
FICHIER_PAR_DEFAUT = Path(__file__).with_name("gardiens.json")


class DeclarationInvalide(ValueError):
    """Une déclaration qu'on refuse de faire tourner, avec la raison lisible."""


@dataclass(frozen=True)
class Controle:
    id: str
    gardien: str
    portee: str
    quand: dict[str, Any]
    commande: list[str]
    delai_s: float = 30.0
    si_constat: str = "signaler"
    geste: str | None = None
    proposer: dict[str, Any] | None = None
    params: dict[str, Any] = field(default_factory=dict)
    actif: bool = True

    @property
    def interne(self) -> str | None:
        if len(self.commande) == 2 and self.commande[0] == "interne":
            return self.commande[1]
        return None

    def en_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "gardien": self.gardien,
            "portee": self.portee,
            "quand": self.quand,
            "commande": self.commande,
            "delai_s": self.delai_s,
            "si_constat": self.si_constat,
            "geste": self.geste,
            "proposer": self.proposer,
            "actif": self.actif,
        }


@dataclass(frozen=True)
class Declaration:
    controles: list[Controle]
    reglages: dict[str, Any]
    source: str


def _controle(brut: Any, gestes_connus: frozenset[str]) -> Controle:
    if not isinstance(brut, dict):
        raise DeclarationInvalide("un contrôle doit être un objet")
    ident = brut.get("id")
    if not isinstance(ident, str) or not ident:
        raise DeclarationInvalide("contrôle sans `id`")
    gardien = brut.get("gardien")
    if gardien not in GARDIENS:
        raise DeclarationInvalide(f"{ident} : gardien inconnu {gardien!r}")
    commande = brut.get("commande")
    if not isinstance(commande, list) or not commande or not all(isinstance(a, str) for a in commande):
        raise DeclarationInvalide(f"{ident} : `commande` doit être une liste d'arguments")
    quand = brut.get("quand")
    intervalle_ou_cron(quand, ident)
    si_constat = brut.get("si_constat", "signaler")
    if si_constat not in SI_CONSTAT:
        raise DeclarationInvalide(f"{ident} : `si_constat` inconnu {si_constat!r}")
    geste = brut.get("geste")
    if geste is not None and geste not in gestes_connus:
        # Liste fermée : un geste qui n'est pas une fonction nommée de
        # l'exécuteur n'existe pas (gardiens.md §3.3).
        raise DeclarationInvalide(f"{ident} : geste hors de la liste fermée {geste!r}")
    if si_constat == "geste" and not geste:
        raise DeclarationInvalide(f"{ident} : `si_constat` = geste sans `geste`")
    delai = brut.get("delai_s", 30)
    if not isinstance(delai, (int, float)) or delai <= 0 or delai > 600:
        raise DeclarationInvalide(f"{ident} : `delai_s` hors de ]0, 600]")
    params = brut.get("params") or {}
    if not isinstance(params, dict):
        raise DeclarationInvalide(f"{ident} : `params` doit être un objet")
    return Controle(
        id=ident,
        gardien=gardien,
        portee=str(brut.get("portee") or "pod"),
        quand=dict(quand),
        commande=list(commande),
        delai_s=float(delai),
        si_constat=si_constat,
        geste=geste,
        proposer=brut.get("proposer"),
        params=params,
        actif=bool(brut.get("actif", True)),
    )


def lire(chemin: Path | None = None, gestes_connus: frozenset[str] | None = None) -> Declaration:
    """Lit et valide la déclaration. Lève `DeclarationInvalide` au premier défaut."""
    if gestes_connus is None:
        from mcp_gateway.gardiens.gestes import GESTES

        gestes_connus = frozenset(GESTES)
    chemin = chemin or chemin_de_la_declaration()
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeclarationInvalide(f"{chemin} illisible : {exc}") from None
    if not isinstance(brut, dict) or not isinstance(brut.get("controles"), list):
        raise DeclarationInvalide(f"{chemin} : il faut un objet avec `controles`")
    controles = [_controle(c, gestes_connus) for c in brut["controles"]]
    vus: set[str] = set()
    for c in controles:
        if c.id in vus:
            raise DeclarationInvalide(f"`id` en double : {c.id}")
        vus.add(c.id)
    reglages = brut.get("reglages") or {}
    if not isinstance(reglages, dict):
        raise DeclarationInvalide("`reglages` doit être un objet")
    return Declaration(controles=controles, reglages=reglages, source=str(chemin))


def chemin_de_la_declaration() -> Path:
    """`ATELIER_GARDIENS_DECLARATION`, sinon celle du projet système, sinon celle du paquet.

    Le projet `atelier-gardiens` (J-g) portera la déclaration vivante ; tant
    qu'il n'existe pas, celle du paquet fait foi.
    """
    explicite = os.environ.get("ATELIER_GARDIENS_DECLARATION")
    if explicite:
        return Path(explicite)
    work = Path(os.environ.get("ATELIER_WORK") or Path.home() / "work")
    projet = work / "projects" / "atelier-gardiens" / "gardiens.json"
    return projet if projet.is_file() else FICHIER_PAR_DEFAUT


# --- rythme -----------------------------------------------------------------


def intervalle_ou_cron(quand: Any, ident: str = "?") -> tuple[float | None, "Cron | None"]:
    if not isinstance(quand, dict):
        raise DeclarationInvalide(f"{ident} : `quand` doit être un objet")
    if "toutes_les_min" in quand:
        n = quand["toutes_les_min"]
        if not isinstance(n, (int, float)) or n <= 0:
            raise DeclarationInvalide(f"{ident} : `toutes_les_min` doit être positif")
        return float(n) * 60.0, None
    if "cron" in quand:
        try:
            return None, Cron(str(quand["cron"]), quand.get("tz"))
        except ValueError as exc:
            raise DeclarationInvalide(f"{ident} : cron invalide ({exc})") from None
    raise DeclarationInvalide(f"{ident} : `quand` attend `toutes_les_min` ou `cron`")


def prochaine_echeance(quand: dict[str, Any], apres: float) -> float:
    """L'instant (epoch) de la prochaine exécution après `apres`."""
    intervalle, cron = intervalle_ou_cron(quand)
    if intervalle is not None:
        return apres + intervalle
    assert cron is not None
    return cron.suivante(apres)


def periode_attendue(quand: dict[str, Any], a: float) -> float:
    """L'écart normal entre deux exécutions, pour l'homme mort."""
    intervalle, cron = intervalle_ou_cron(quand)
    if intervalle is not None:
        return intervalle
    assert cron is not None
    premiere = cron.suivante(a)
    return cron.suivante(premiere) - premiere


def _plage(texte: str, bas: int, haut: int) -> set[int]:
    valeurs: set[int] = set()
    for morceau in texte.split(","):
        pas = 1
        if "/" in morceau:
            morceau, p = morceau.split("/", 1)
            pas = int(p)
            if pas <= 0:
                raise ValueError("pas nul")
        if morceau == "*":
            debut, fin = bas, haut
        elif "-" in morceau:
            a, b = morceau.split("-", 1)
            debut, fin = int(a), int(b)
        else:
            debut = fin = int(morceau)
            if pas != 1:
                fin = haut
        if debut < bas or fin > haut or debut > fin:
            raise ValueError(f"{texte} hors de [{bas}, {haut}]")
        valeurs.update(range(debut, fin + 1, pas))
    return valeurs


class Cron:
    """Cron à cinq champs (`*`, listes, plages, pas), comme les triggers de wikichat."""

    def __init__(self, expression: str, tz: str | None = None) -> None:
        champs = expression.split()
        if len(champs) != 5:
            raise ValueError("cinq champs attendus")
        self.expression = expression
        self.minutes = _plage(champs[0], 0, 59)
        self.heures = _plage(champs[1], 0, 23)
        self.jours = _plage(champs[2], 1, 31)
        self.mois = _plage(champs[3], 1, 12)
        jds = _plage(champs[4], 0, 7)
        self.jours_semaine = {0 if j == 7 else j for j in jds}
        self.jours_libres = champs[2] == "*"
        self.semaine_libre = champs[4] == "*"
        self.tz = _fuseau(tz)

    def _jour_convient(self, d: datetime) -> bool:
        jds = (d.weekday() + 1) % 7  # cron : 0 = dimanche
        dans_mois = d.day in self.jours
        dans_semaine = jds in self.jours_semaine
        if self.jours_libres and self.semaine_libre:
            return True
        if self.jours_libres:
            return dans_semaine
        if self.semaine_libre:
            return dans_mois
        return dans_mois or dans_semaine  # les deux restreints : l'un OU l'autre

    def suivante(self, apres: float) -> float:
        d = datetime.fromtimestamp(apres, self.tz).replace(second=0, microsecond=0) + timedelta(minutes=1)
        limite = d + timedelta(days=366 * 5)
        while d < limite:
            if d.month not in self.mois:
                an, mois = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
                d = d.replace(year=an, month=mois, day=1, hour=0, minute=0)
                continue
            if not self._jour_convient(d):
                d = (d + timedelta(days=1)).replace(hour=0, minute=0)
                continue
            if d.hour not in self.heures:
                d = (d + timedelta(hours=1)).replace(minute=0)
                continue
            if d.minute not in self.minutes:
                d += timedelta(minutes=1)
                continue
            return d.timestamp()
        raise ValueError(f"aucune échéance pour {self.expression!r}")


def _fuseau(nom: str | None):
    if not nom:
        return timezone.utc
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(nom)
    except Exception:  # noqa: BLE001 — sans base de fuseaux (Windows sans tzdata)
        return timezone.utc
