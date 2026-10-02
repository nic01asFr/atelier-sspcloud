"""Les fournisseurs de modèles au format OpenAI, à côté de l'API SSPCloud.

SSPCloud parle le format Anthropic : l'Atelier l'appelle tel quel. Un
fournisseur OpenAI (Albert) passe par le relais, qui traduit. Ses modèles
portent un préfixe, `albert/<modèle>`, par lequel le relais sait où aller.

Déclaration : une clé `~/work/.secrets/albert_api_key` suffit pour Albert ;
`~/work/.secrets/fournisseurs.json` en ajoute d'autres :
`{"id": {"nom": "…", "base_url": "https://…/v1", "outils_natifs": ["modèle"]}}`,
`outils_natifs` listant les modèles dont les appels d'outils fonctionnent tels
quels, la clé étant dans
`<id>_api_key` à côté. Aucune clé n'est jamais dans ce fichier.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from mcp_gateway.atelier.config import AtelierSettings

ALBERT_URL = "https://albert.api.etalab.gouv.fr/v1"
# Mesuré le 2 octobre 2026 : seul gpt-oss-120b rend de vrais appels d'outils
# en mode automatique ; deepseek, gemma, qwen3-coder et mistral répondent vide
# ou écrivent l'appel en texte, mais obéissent à `tool_choice: required`.
ALBERT_OUTILS_NATIFS = ("gpt-oss-120b",)
# Claude Code ne garde, parmi les modèles que la passerelle annonce, que ceux
# dont l'identifiant contient « claude » ou « anthropic » (mesuré sur 2.1.287 :
# « 0 usable models after filter » pour des identifiants nus). Le relais publie
# donc des identifiants `claude-<source>-<modèle>` et retire le préfixe en
# transmettant : `claude-albert-gpt-oss-120b` ↔ `albert/gpt-oss-120b`, et
# `claude-ssp-<modèle>` ↔ le modèle SSPCloud nu.
SOURCE_SSPCLOUD = "ssp"
_IDENTIFIANT = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


@dataclass(frozen=True)
class Fournisseur:
    id: str
    nom: str
    base_url: str
    cle: str
    # Modèles dont le fournisseur analyse bien les appels d'outils. Les autres
    # sont contraints (voir `traduction_openai.OUTIL_REPONDRE`).
    outils_natifs: frozenset[str] = field(default_factory=frozenset)

    def prefixe(self) -> str:
        return f"{self.id}/"

    def identifiant_public(self, modele: str) -> str:
        return f"claude-{self.id}-{modele}"


def _lire_cle(chemin: Path) -> str:
    try:
        return chemin.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def charger_fournisseurs(settings: AtelierSettings) -> list[Fournisseur]:
    """Les fournisseurs OpenAI déclarés qui ont une clé. Jamais d'exception."""
    dossier = settings.secrets_dir
    declares: dict[str, dict] = {
        "albert": {"nom": "Albert API", "base_url": ALBERT_URL, "outils_natifs": list(ALBERT_OUTILS_NATIFS)}
    }
    try:
        lu = json.loads((dossier / "fournisseurs.json").read_text(encoding="utf-8"))
        if isinstance(lu, dict):
            declares.update({k: v for k, v in lu.items() if isinstance(v, dict)})
    except (OSError, json.JSONDecodeError):
        pass
    sortie: list[Fournisseur] = []
    for identifiant, d in declares.items():
        base = str(d.get("base_url") or "").strip().rstrip("/")
        if identifiant == SOURCE_SSPCLOUD or not _IDENTIFIANT.match(identifiant) or not base.startswith("https://"):
            continue
        cle = _lire_cle(dossier / f"{identifiant}_api_key")
        natifs = d.get("outils_natifs")
        natifs = frozenset(str(m) for m in natifs) if isinstance(natifs, list) else frozenset()
        if cle:
            sortie.append(Fournisseur(identifiant, str(d.get("nom") or identifiant), base, cle, natifs))
    return sortie


def identifiant_sspcloud(modele: str) -> str:
    """L'identifiant que le relais publie pour un modèle SSPCloud."""
    return f"claude-{SOURCE_SSPCLOUD}-{modele}"


def modele_sspcloud_nu(modele: str) -> str:
    """Le modèle SSPCloud sous son nom d'amont (inchangé s'il n'a pas le préfixe)."""
    prefixe = f"claude-{SOURCE_SSPCLOUD}-"
    return modele[len(prefixe) :] if modele.startswith(prefixe) and len(modele) > len(prefixe) else modele


def fournisseur_du_modele(fournisseurs: list[Fournisseur], modele: str) -> tuple[Fournisseur, str] | None:
    """(fournisseur, modèle chez lui) pour `albert/x` ; None pour un modèle SSPCloud."""
    for f in fournisseurs:
        for prefixe in (f.prefixe(), f"claude-{f.id}-"):
            if modele.startswith(prefixe) and len(modele) > len(prefixe):
                return f, modele[len(prefixe) :]
    return None
