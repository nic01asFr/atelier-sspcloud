"""Un appel de modèle, pour ce que l'Atelier fait lui-même.

Le harnais lance `claude` pour tenir une conversation ; certaines tâches n'en
demandent pas tant. Décrire un connecteur, c'est une question fermée à
laquelle on répond une fois : un tour de modèle suffit, sans session, sans
outils, sans transcript.

Le point d'accès et la clé sont ceux que le harnais donne déjà à ses agents —
on ne configure rien de plus.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("atelier.llm")


class LlmIndisponible(RuntimeError):
    """Le modèle n'a pas pu être joint, ou n'a rien rendu d'exploitable."""


# Estimation des jetons, comme le relais et la carte : caractères / 3,4.
CARACTERES_PAR_JETON = 3.4


def _estimer(caracteres: int) -> int:
    return max(1, int(caracteres / CARACTERES_PAR_JETON)) if caracteres > 0 else 0


def _cle(settings: Any) -> str:
    depuis_env = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if depuis_env:
        return depuis_env
    try:
        return settings.llm_key_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _modele(settings: Any, demande: str = "") -> str:
    if demande.strip():
        return demande.strip()
    from mcp_gateway.atelier.models_catalog import list_available_models

    catalogue = list_available_models(settings)
    return str(catalogue.get("default") or "").strip() or "sonnet"


@dataclass
class Reponse:
    """Ce que rend un appel : le texte, et ce qu'il a coûté."""

    texte: str
    jetons_entree: int
    jetons_sortie: int
    arret: str
    modele: str
    # Vrai quand l'amont n'a pas rendu d'usage et qu'on l'a estimé
    # (caractères / 3,4) ; faux quand il vient du modèle.
    estime: bool = False


def _poster(url: str, charge: dict[str, Any], entetes: dict[str, str], timeout: float) -> dict[str, Any]:
    requete = urllib.request.Request(
        url,
        data=json.dumps(charge, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **entetes},
    )
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            data = json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise LlmIndisponible(f"HTTP {exc.code} — {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise LlmIndisponible(str(exc)) from exc
    if not isinstance(data, dict):
        raise LlmIndisponible("réponse illisible")
    return data


def appeler(
    settings: Any,
    consigne: str,
    message: str,
    *,
    modele: str = "",
    max_tokens: int = 4000,
    timeout: float = 120.0,
    base: str = "",
) -> Reponse:
    """Un tour de modèle, non streamé : le texte et l'usage.

    `base` : l'adresse à appeler (le relais de l'Atelier, par exemple) ; par
    défaut, l'amont des réglages. Non streamé, l'amont rend un usage exact
    (mesuré le 25/09) ; s'il manque, on l'estime et on le dit.
    """
    cle = _cle(settings)
    if not cle:
        raise LlmIndisponible("aucune clé pour le modèle")
    base = str(base or settings.anthropic_base_url or "").rstrip("/")
    if not base:
        raise LlmIndisponible("aucune adresse pour le modèle")
    nom = _modele(settings, modele)
    charge = {
        "model": nom,
        "max_tokens": max_tokens,
        "system": consigne,
        # Le modèle servi ici raisonne à voix haute avant de répondre, et ce
        # préambule consomme le budget : sur une limite trop basse, la
        # réponse s'arrête avant le premier mot utile. On n'en a pas besoin
        # pour une question fermée.
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": message}],
    }
    data = _poster(
        f"{base}/v1/messages",
        charge,
        {"x-api-key": cle, "anthropic-version": "2023-06-01"},
        timeout,
    )
    blocs = [b for b in (data.get("content") or []) if isinstance(b, dict)]
    texte = "".join(b.get("text", "") for b in blocs if b.get("type") == "text").strip()
    if not texte:
        # Distinguer les deux échecs : rien du tout, ou un raisonnement qui a
        # épuisé le budget avant la réponse. Le second se corrige.
        if any(b.get("type") == "thinking" for b in blocs):
            raise LlmIndisponible(
                "le modèle a raisonné sans conclure — budget de "
                f"{max_tokens} jetons trop court ({data.get('stop_reason')})"
            )
        raise LlmIndisponible("réponse vide")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    entree = sum(int(usage.get(k) or 0) for k in (
        "input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"))
    sortie = int(usage.get("output_tokens") or 0)
    estime = False
    if entree <= 0:
        entree = _estimer(len(consigne) + len(message))
        estime = True
    if sortie <= 0:
        sortie = _estimer(len(texte))
        estime = True
    return Reponse(
        texte=texte,
        jetons_entree=entree,
        jetons_sortie=sortie,
        arret=str(data.get("stop_reason") or ""),
        modele=str(data.get("model") or nom),
        estime=estime,
    )


def demander(
    settings: Any,
    consigne: str,
    message: str,
    *,
    modele: str = "",
    max_tokens: int = 4000,
    timeout: float = 120.0,
) -> str:
    """Pose une question au modèle et rend son texte.

    Lève LlmIndisponible plutôt que de rendre une réponse vide : un appelant
    qui écrit un fichier doit savoir qu'il n'a rien à écrire.
    """
    return appeler(settings, consigne, message, modele=modele, max_tokens=max_tokens, timeout=timeout).texte


def demander_json(settings: Any, consigne: str, message: str, **kw: Any) -> Any:
    """Comme `demander`, mais rend l'objet JSON contenu dans la réponse.

    Un modèle encadre volontiers son JSON de commentaires ou d'une clôture
    Markdown : on prend ce qui se trouve entre la première accolade et la
    dernière, plutôt que d'exiger une réponse parfaite.
    """
    texte = demander(settings, consigne, message, **kw)
    debut, fin = texte.find("{"), texte.rfind("}")
    if debut < 0 or fin <= debut:
        raise LlmIndisponible("aucun objet JSON dans la réponse")
    try:
        return json.loads(texte[debut : fin + 1])
    except json.JSONDecodeError as exc:
        raise LlmIndisponible(f"JSON illisible : {exc}") from exc


# ── Embeddings ───────────────────────────────────────────────────────────────

# Le point d'accès SSPCloud est compatible OpenAI pour les embeddings. Le
# chemin n'a pas été vérifié depuis l'Atelier (le sondage avec la clé a été
# refusé par la garde des permissions pendant l'écriture, le 26/09) : on essaie
# `/v1/embeddings` sous la base, puis `/embeddings` sur un 404 ou un 405.
# `ATELIER_EMBEDDINGS_URL` fixe l'adresse complète si aucun des deux ne répond.
CHEMINS_EMBEDDINGS = ("/v1/embeddings", "/embeddings")


def embeddings(
    settings: Any,
    textes: list[str],
    *,
    modele: str = "qwen3-embedding-8b",
    timeout: float = 30.0,
    base: str = "",
) -> tuple[list[list[float]], int]:
    """Les vecteurs de `textes`, dans l'ordre, et les jetons d'entrée comptés.

    Lève LlmIndisponible si le point d'accès ne répond pas ou rend autre
    chose qu'un vecteur par texte.
    """
    if not textes:
        return [], 0
    cle = _cle(settings)
    if not cle:
        raise LlmIndisponible("aucune clé pour le modèle")
    fixe = os.environ.get("ATELIER_EMBEDDINGS_URL", "").strip()
    base = str(base or settings.anthropic_base_url or "").rstrip("/")
    if not fixe and not base:
        raise LlmIndisponible("aucune adresse pour le modèle")
    adresses = [fixe] if fixe else [f"{base}{c}" for c in CHEMINS_EMBEDDINGS]
    charge = {"model": modele, "input": list(textes)}
    entetes = {"Authorization": f"Bearer {cle}"}
    derniere: LlmIndisponible | None = None
    for adresse in adresses:
        try:
            data = _poster(adresse, charge, entetes, timeout)
        except LlmIndisponible as exc:
            derniere = exc
            if str(exc).startswith(("HTTP 404", "HTTP 405")):
                continue
            raise
        lignes = data.get("data")
        if not isinstance(lignes, list) or len(lignes) != len(textes):
            raise LlmIndisponible("réponse d'embeddings illisible")
        vecteurs: list[list[float]] = [[] for _ in textes]
        for rang, ligne in enumerate(lignes):
            if not isinstance(ligne, dict) or not isinstance(ligne.get("embedding"), list):
                raise LlmIndisponible("réponse d'embeddings illisible")
            place = ligne.get("index", rang)
            if not isinstance(place, int) or not 0 <= place < len(textes):
                raise LlmIndisponible("réponse d'embeddings illisible")
            vecteurs[place] = [float(x) for x in ligne["embedding"]]
        if any(not v for v in vecteurs):
            raise LlmIndisponible("réponse d'embeddings incomplète")
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        jetons = int(usage.get("prompt_tokens") or usage.get("total_tokens") or 0)
        if jetons <= 0:
            jetons = _estimer(sum(len(t) for t in textes))
        return vecteurs, jetons
    raise derniere or LlmIndisponible("aucun point d'accès d'embeddings")
