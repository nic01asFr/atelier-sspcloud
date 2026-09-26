"""Ce qu'est une commande de l'Atelier (transverse §1.8).

Chaque commande déclare dans sa définition, et non dans la consigne du modèle :

- `objet` : le type d'objet de la carte qu'elle touche ;
- `classe` : `lecture`, `reversible`, `engageante` ou `reservee`
  (`assistant-role.md` §3.6) ;
- `inverse` : la commande qui l'annule (base du bouton « Annuler ») ;
- `resultat` : une carte d'action (titre, résumé, « Voir », « Annuler »,
  preuve), construite par la commande et non rédigée par le modèle ;
- `regles` : ce qu'elle garantit.

`lecture` s'ajoute aux trois classes du transverse pour les commandes sans
effet (lister, lire) : elles n'ont ni inverse ni carte, et un modèle les
appelle librement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Union

LECTURE = "lecture"
REVERSIBLE = "reversible"
ENGAGEANTE = "engageante"
RESERVEE = "reservee"
CLASSES = (LECTURE, REVERSIBLE, ENGAGEANTE, RESERVEE)
# Du plus léger au plus lourd : une classe effective ne dépasse jamais la
# classe déclarée (voir `Commande.classe_pour`).
_POIDS = {c: i for i, c in enumerate(CLASSES)}

# D'où vient l'appel. `mcp` et `cle` sont des automates ou des modèles : un
# client MCP, ou un porteur de la clé du propriétaire (que lisent aussi les
# agents du pod). `interface` est la personne, par la session de l'interface.
ORIGINE_MCP = "mcp"
ORIGINE_CLE = "cle"
ORIGINE_INTERFACE = "interface"


class Refus(Exception):
    """La commande ne s'exécute pas, et dit pourquoi à qui l'appelle."""


@dataclass
class Contexte:
    """Qui appelle, par où, et avec quel accord."""

    acteur: str
    origine: str
    via: str = ""
    # Accord donné pour cet appel : un jeton de confirmation valide, ou le
    # « Oui » de la personne dans l'interface.
    confirme: bool = False

    @property
    def est_la_personne(self) -> bool:
        return self.origine == ORIGINE_INTERFACE

    @property
    def est_un_modele(self) -> bool:
        """Tout ce qui n'est pas la personne à l'écran peut être un modèle."""
        return self.origine in (ORIGINE_MCP, ORIGINE_CLE)


@dataclass
class Effet:
    """Ce qu'une commande a fait : de quoi rendre, journaliser et annuler."""

    charge: Any
    objet_id: str = ""
    titre: str = ""
    resume: str = ""
    voir: str = ""
    preuve: dict[str, Any] = field(default_factory=dict)
    avant: Any = None
    apres: Any = None
    # Les arguments de l'inverse ; None quand il n'y a rien à annuler (la
    # commande n'a rien changé, ou son inverse n'existe pas).
    inverse_arguments: dict[str, Any] | None = None


Executeur = Callable[["Contexte", dict[str, Any]], Union[Effet, Awaitable[Effet]]]
Apercu = Callable[["Contexte", dict[str, Any]], Union[dict[str, Any], Awaitable[dict[str, Any]]]]


@dataclass
class Commande:
    nom: str
    description: str
    objet: str
    classe: str
    executer: Executeur
    schema: dict[str, Any] = field(default_factory=lambda: {"type": "object", "properties": {}})
    inverse: str | None = None
    regles: list[str] = field(default_factory=list)
    # Une classe plus légère selon les arguments (un refus n'engage rien). Ne
    # peut jamais rendre plus léger que `lecture`, ni plus lourd que `classe`.
    allegement: Callable[[dict[str, Any]], str] | None = None
    # Ce que montre l'aperçu d'une commande engageante, avant « Oui ».
    apercu: Apercu | None = None
    # Faux : absente des outils MCP (l'interface seule la voit).
    exposee_mcp: bool = True
    # Les arguments tels que le journal les garde (le journal se relit par un
    # modèle, `atelier_journal`) : retirer ce qu'il ne doit pas revoir.
    arguments_au_journal: Callable[[dict[str, Any]], dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.classe not in CLASSES:
            raise ValueError(f"{self.nom} : classe inconnue {self.classe}")
        if not self.nom.startswith("atelier_"):
            raise ValueError(f"{self.nom} : une commande de l'Atelier commence par atelier_")

    def classe_pour(self, arguments: dict[str, Any]) -> str:
        if self.allegement is None:
            return self.classe
        try:
            voulue = self.allegement(arguments)
        except Exception:  # noqa: BLE001 — dans le doute, la classe déclarée
            return self.classe
        if voulue not in _POIDS or _POIDS[voulue] > _POIDS[self.classe]:
            return self.classe
        return voulue

    def declaration(self) -> dict[str, Any]:
        """Ce que le catalogue publie : l'API HTTP et les outils MCP le reprennent."""
        return {
            "nom": self.nom,
            "description": self.description,
            "objet": self.objet,
            "classe": self.classe,
            "inverse": self.inverse,
            "regles": list(self.regles),
            "schema": self.schema,
            "exposee_mcp": self.exposee_mcp,
        }


__all__ = [
    "CLASSES",
    "ENGAGEANTE",
    "LECTURE",
    "ORIGINE_CLE",
    "ORIGINE_INTERFACE",
    "ORIGINE_MCP",
    "RESERVEE",
    "REVERSIBLE",
    "Commande",
    "Contexte",
    "Effet",
    "Refus",
]
