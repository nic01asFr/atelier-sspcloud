"""Les fournisseurs de modèles, vus et réglés depuis l'interface.

`fournisseurs.py` sait lire `~/work/.secrets/fournisseurs.json` et une clé par
fournisseur ; ce module en fait un écran : voir ce qui est configuré, ajouter un
fournisseur à la main, retrouver ses modèles tout seul, le retirer.

- **Découverte** : `GET <adresse>/models` avec la clé. Les modèles de conversation
  sont gardés, plongements, voix et reclassement écartés. Une panne est dite
  (« clé refusée », « adresse injoignable », « pas de liste à cette adresse ») au
  lieu de rendre une liste vide.
- **Jamais de clé à l'écran ni dans `fournisseurs.json`** : elle est écrite dans
  `<id>_api_key`, en 0600, à côté des autres secrets ; on ne rend que sa présence.
- **Une adresse qui mène au pod est refusée** : https seulement, ni identifiants dans
  l'adresse, ni hôte interne, résolution DNS comprise. Sans cela, l'Atelier enverrait
  une clé et une requête où l'on voudrait, depuis l'intérieur du cluster.
- Albert est intégré (adresse et réglages du code) : on n'y change que la clé.
  SSPCloud est celui de l'Atelier : on le montre, on ne le règle pas ici.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import secrets
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from mcp_gateway.atelier import models_catalog
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.fournisseurs import (
    SOURCE_SSPCLOUD,
    declaration_valide,
    declarations,
    _IDENTIFIANT,
)
from mcp_gateway.gardiens.garde_navigation import adresse_interne, est_hote_interne

DELAI_S = 6.0
OCTETS_MAX = 2_000_000
_CLE_VALIDE = re.compile(r"^[\x21-\x7e]{8,512}$")  # ASCII imprimable, sans espace ni retour à la ligne
_NOM_MAX = 60


class ErreurFournisseur(Exception):
    """Une erreur que la personne peut lire telle quelle."""


@dataclass
class Decouverte:
    ok: bool
    modeles: list[str] = field(default_factory=list)
    ecartes: int = 0
    erreur: str = ""
    code: int | None = None


# ── l'adresse ────────────────────────────────────────────────────────────────


def _adresses_de(hote: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(hote, None, type=socket.SOCK_STREAM)
    except OSError:
        return []
    sortie = []
    for info in infos:
        try:
            sortie.append(ipaddress.ip_address(info[4][0]))
        except ValueError:
            continue
    return sortie


def valider_adresse(adresse: str) -> str:
    """L'adresse de base, nettoyée, ou une `ErreurFournisseur` qui dit ce qui ne va pas."""
    brut = (adresse or "").strip().rstrip("/")
    if not brut:
        raise ErreurFournisseur("L'adresse est vide. Exemple : https://albert.api.etalab.gouv.fr/v1")
    if len(brut) > 300:
        raise ErreurFournisseur("L'adresse est trop longue.")
    try:
        coupe = urlsplit(brut)
        hote = coupe.hostname or ""
    except ValueError:
        raise ErreurFournisseur("L'adresse n'est pas lisible.") from None
    if coupe.scheme != "https":
        raise ErreurFournisseur("L'adresse doit commencer par https:// (une clé ne part pas en clair).")
    if coupe.username or coupe.password:
        raise ErreurFournisseur("L'adresse ne doit pas contenir d'identifiants : la clé se donne à part.")
    if coupe.query or coupe.fragment:
        raise ErreurFournisseur("L'adresse de base ne porte ni paramètres ni ancre (elle finit en général par /v1).")
    if not hote or est_hote_interne(hote):
        raise ErreurFournisseur(
            "Cette adresse désigne le pod ou son réseau interne : un fournisseur de modèles doit être joignable "
            "sur Internet (ou par une adresse publique de votre service)."
        )
    for ip in _adresses_de(hote):
        if adresse_interne(ip):
            raise ErreurFournisseur(
                f"Le nom {hote} mène vers le réseau interne : il n'est pas accepté comme fournisseur de modèles."
            )
    return brut


def valider_identifiant(identifiant: str) -> str:
    ident = (identifiant or "").strip().lower()
    if not _IDENTIFIANT.match(ident):
        raise ErreurFournisseur(
            "L'identifiant tient en minuscules, chiffres et tirets, commence par une lettre (32 caractères au plus). "
            "Exemple : mon-vllm."
        )
    if ident == SOURCE_SSPCLOUD:
        raise ErreurFournisseur(f"« {ident} » est réservé à SSPCloud.")
    return ident


def _valider_cle(cle: str) -> str:
    cle = (cle or "").strip()
    if not _CLE_VALIDE.match(cle):
        raise ErreurFournisseur("La clé semble incomplète ou contient des espaces (8 à 512 caractères visibles).")
    return cle


# ── la découverte ────────────────────────────────────────────────────────────


def _lire_json(adresse: str, cle: str) -> Any:
    """`GET <adresse>` avec la clé ; les redirections ne sont pas suivies (la clé ne les suit pas)."""

    class _SansRedirection(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_a: Any, **_k: Any) -> None:  # type: ignore[override]
            return None

    ouvreur = urllib.request.build_opener(_SansRedirection)
    entetes = {"Accept": "application/json", "User-Agent": "atelier/0.3"}
    if cle:
        entetes.update({"Authorization": f"Bearer {cle}", "x-api-key": cle})
    with ouvreur.open(urllib.request.Request(adresse, headers=entetes), timeout=DELAI_S) as reponse:
        return json.loads(reponse.read(OCTETS_MAX).decode("utf-8"))


def decouvrir(base_url: str, cle: str) -> Decouverte:
    """Ce que le fournisseur annonce, ou pourquoi on n'a rien pu lire. Ne lève pas."""
    try:
        donnees = _lire_json(f"{base_url}/models", cle)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return Decouverte(False, erreur=f"La clé est refusée (HTTP {exc.code}).", code=exc.code)
        if exc.code in (301, 302, 303, 307, 308):
            return Decouverte(False, erreur="L'adresse redirige ailleurs : donnez l'adresse finale.", code=exc.code)
        if exc.code == 404:
            return Decouverte(
                False,
                erreur="Pas de liste de modèles à cette adresse (HTTP 404). L'adresse de base finit-elle par /v1 ?",
                code=404,
            )
        return Decouverte(False, erreur=f"Le fournisseur répond une erreur (HTTP {exc.code}).", code=exc.code)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raison = getattr(exc, "reason", exc)
        return Decouverte(False, erreur=f"Adresse injoignable : {str(raison)[:120]}.")
    except (ValueError, UnicodeDecodeError):
        return Decouverte(False, erreur="La réponse n'est pas une liste de modèles lisible (ce n'est pas du JSON).")
    entrees = donnees.get("data") if isinstance(donnees, dict) else donnees
    if not isinstance(entrees, list):
        return Decouverte(False, erreur="La réponse ne contient pas de liste de modèles (champ « data » attendu).")
    gardes: list[str] = []
    ecartes = 0
    for e in entrees:
        if not isinstance(e, dict) or not e.get("id"):
            continue
        if models_catalog.est_un_modele_de_conversation(e):
            gardes.append(str(e["id"]))
        else:
            ecartes += 1
    if not gardes:
        return Decouverte(
            False,
            ecartes=ecartes,
            erreur="Le fournisseur répond, mais aucun modèle de conversation n'y figure"
            + (f" ({ecartes} écartés : plongements, voix…)." if ecartes else "."),
        )
    return Decouverte(True, modeles=sorted(set(gardes)), ecartes=ecartes)


# ── la lecture ───────────────────────────────────────────────────────────────


def _cle_de(settings: AtelierSettings, identifiant: str) -> str:
    try:
        return (settings.secrets_dir / f"{identifiant}_api_key").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _ligne(settings: AtelierSettings, identifiant: str, d: dict, en_direct: bool) -> dict[str, Any]:
    integre = bool(d.get("integre"))
    base = str(d.get("base_url") or "").strip().rstrip("/")
    cle = _cle_de(settings, identifiant)
    natifs = [str(m) for m in d.get("outils_natifs") or []] if isinstance(d.get("outils_natifs"), list) else []
    ligne: dict[str, Any] = {
        "id": identifiant,
        "nom": str(d.get("nom") or identifiant),
        "base_url": base,
        "source": "integre" if integre else "declare",
        "cle_presente": bool(cle),
        "fichier_de_la_cle": f"~/work/.secrets/{identifiant}_api_key",
        "outils_natifs": natifs,
        "modifiable": not integre,
        "retirable": True,
        "adresse_valide": declaration_valide(identifiant, d),
        "modeles": [],
        "etat": "sans_cle",
        "detail": "Aucune clé : ce fournisseur n'est pas utilisé.",
    }
    if not ligne["adresse_valide"]:
        ligne.update(etat="adresse_invalide", detail="L'adresse doit être en https:// : ce fournisseur est ignoré.")
        return ligne
    if not cle:
        return ligne
    if not en_direct:
        connus = models_catalog._lire_modeles(base, cle, en_direct=False)
        ligne["modeles"] = [_modele(identifiant, m, natifs) for m in connus]
        ligne.update(etat="ok" if connus else "inconnu", detail="" if connus else "Pas encore interrogé.")
        return ligne
    d_ = decouvrir(base, cle)
    if d_.ok:
        models_catalog._cache[base] = (time.monotonic(), d_.modeles)
        ligne["modeles"] = [_modele(identifiant, m, natifs) for m in d_.modeles]
        ligne.update(etat="ok", detail=f"{len(d_.modeles)} modèles de conversation" + (f" ({d_.ecartes} écartés)" if d_.ecartes else ""))
    else:
        ligne.update(etat="en_erreur", detail=d_.erreur)
    return ligne


def _modele(identifiant: str, modele: str, natifs: list[str]) -> dict[str, Any]:
    return {"id": modele, "public": f"claude-{identifiant}-{modele}", "outils_natifs": modele in natifs}


def configuration(settings: AtelierSettings, *, en_direct: bool = False) -> dict[str, Any]:
    """Tous les fournisseurs, SSPCloud d'abord, sans jamais une clé."""
    base_ssp = settings.anthropic_base_url.rstrip("/")
    cle_ssp = models_catalog._cle(settings)
    modeles_ssp = models_catalog.modeles_de_l_api(settings, en_direct=en_direct)
    ssp: dict[str, Any] = {
        "id": SOURCE_SSPCLOUD,
        "nom": "SSPCloud (API Anthropic)",
        "base_url": base_ssp,
        "source": "sspcloud",
        "cle_presente": bool(cle_ssp),
        "fichier_de_la_cle": "",
        "outils_natifs": [],
        "modifiable": False,
        "retirable": False,
        "adresse_valide": True,
        "modeles": [{"id": m, "public": f"claude-{SOURCE_SSPCLOUD}-{m}", "outils_natifs": True} for m in modeles_ssp],
        "etat": "ok" if modeles_ssp else ("sans_cle" if not cle_ssp else "inconnu"),
        "detail": f"{len(modeles_ssp)} modèles" if modeles_ssp else "Fournisseur de l'Atelier : sa clé se règle à l'installation.",
    }
    lignes = [ssp] + [_ligne(settings, i, d, en_direct) for i, d in declarations(settings).items()]
    return {"fournisseurs": lignes}


# ── les écritures ────────────────────────────────────────────────────────────


def _ecrire(chemin: Path, texte: str) -> None:
    """Fichier provisoire en 0600, puis renommage : jamais un secret lisible par d'autres, jamais à moitié écrit."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    provisoire = chemin.with_name(f"{chemin.name}.{secrets.token_hex(3)}.tmp")
    descripteur = os.open(provisoire, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descripteur, "w", encoding="utf-8") as f:
            f.write(texte)
        os.replace(provisoire, chemin)
    finally:
        try:
            os.unlink(provisoire)
        except OSError:
            pass


def _lire_declarations(settings: AtelierSettings) -> dict[str, Any]:
    chemin = settings.secrets_dir / "fournisseurs.json"
    if not chemin.exists():
        return {}
    try:
        lu = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise ErreurFournisseur(
            "Le fichier fournisseurs.json existe mais n'est pas lisible : rien n'a été modifié, pour ne pas l'écraser. "
            "Corrigez-le ou renommez-le."
        ) from None
    if not isinstance(lu, dict):
        raise ErreurFournisseur("Le fichier fournisseurs.json n'est pas un objet : rien n'a été modifié.")
    return lu


def _verifier_les_prefixes(identifiant: str, existants: list[str]) -> None:
    """`claude-<id>-<modèle>` : un identifiant préfixe d'un autre rendrait le routage ambigu."""
    for autre in existants:
        if autre != identifiant and (autre.startswith(identifiant + "-") or identifiant.startswith(autre + "-")):
            raise ErreurFournisseur(
                f"L'identifiant « {identifiant} » prête à confusion avec « {autre} » (l'un commence par l'autre, suivi d'un "
                "tiret) : les modèles ne sauraient plus à qui aller. Choisissez un autre identifiant."
            )


def tester(settings: AtelierSettings, *, base_url: str, cle: str = "", identifiant: str = "") -> dict[str, Any]:
    """Interroge un fournisseur sans rien enregistrer. Sans clé donnée, utilise celle de `identifiant`."""
    base = valider_adresse(base_url)
    cle = (cle or "").strip()
    if cle:
        cle = _valider_cle(cle)
    elif identifiant:
        cle = _cle_de(settings, valider_identifiant(identifiant))
    if not cle:
        raise ErreurFournisseur("Il faut une clé pour interroger ce fournisseur.")
    d = decouvrir(base, cle)
    return {
        "ok": d.ok,
        "modeles": d.modeles,
        "ecartes": d.ecartes,
        "detail": (f"{len(d.modeles)} modèles de conversation trouvés" if d.ok else d.erreur),
    }


def enregistrer(
    settings: AtelierSettings,
    identifiant: str,
    *,
    nom: str = "",
    base_url: str = "",
    cle: str = "",
    outils_natifs: list[str] | None = None,
) -> dict[str, Any]:
    """Ajoute ou met à jour un fournisseur, puis le relit en direct. Albert : seule la clé change."""
    ident = valider_identifiant(identifiant)
    toutes = declarations(settings)
    integre = bool(toutes.get(ident, {}).get("integre"))
    cle = (cle or "").strip()
    if cle:
        cle = _valider_cle(cle)
    if integre:
        if not cle:
            raise ErreurFournisseur("Albert est intégré : il n'y a que sa clé à donner.")
        _ecrire(settings.secrets_dir / f"{ident}_api_key", cle + "\n")
    else:
        nom = (nom or "").strip() or ident
        if len(nom) > _NOM_MAX:
            raise ErreurFournisseur(f"Le nom tient en {_NOM_MAX} caractères au plus.")
        base = valider_adresse(base_url)
        _verifier_les_prefixes(ident, list(toutes))
        if not cle and not _cle_de(settings, ident):
            raise ErreurFournisseur("Il faut une clé pour ajouter un fournisseur.")
        lu = _lire_declarations(settings)
        entree = dict(lu.get(ident) if isinstance(lu.get(ident), dict) else {})
        entree.update({"nom": nom, "base_url": base})
        if outils_natifs is not None:
            entree["outils_natifs"] = sorted({str(m).strip() for m in outils_natifs if str(m).strip()})
        lu[ident] = entree
        if cle:
            _ecrire(settings.secrets_dir / f"{ident}_api_key", cle + "\n")
        _ecrire(settings.secrets_dir / "fournisseurs.json", json.dumps(lu, indent=2, ensure_ascii=False) + "\n")
    for d in declarations(settings).values():
        models_catalog._cache.pop(str(d.get("base_url") or "").strip().rstrip("/"), None)
    return _ligne(settings, ident, declarations(settings)[ident], True)


def retirer(settings: AtelierSettings, identifiant: str) -> dict[str, Any]:
    """Retire un fournisseur déclaré (déclaration et clé). Albert : retire sa clé, il reste proposé."""
    ident = valider_identifiant(identifiant)
    toutes = declarations(settings)
    if ident not in toutes:
        raise ErreurFournisseur("Ce fournisseur n'existe pas.")
    base = str(toutes[ident].get("base_url") or "").strip().rstrip("/")
    try:
        (settings.secrets_dir / f"{ident}_api_key").unlink()
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise ErreurFournisseur(f"La clé n'a pas pu être retirée : {exc.strerror or exc}.") from None
    if not toutes[ident].get("integre"):
        lu = _lire_declarations(settings)
        if ident in lu:
            del lu[ident]
            _ecrire(settings.secrets_dir / "fournisseurs.json", json.dumps(lu, indent=2, ensure_ascii=False) + "\n")
    models_catalog._cache.pop(base, None)
    return {"retire": ident, "reste_propose": bool(toutes[ident].get("integre"))}
