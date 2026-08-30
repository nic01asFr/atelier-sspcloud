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
from typing import Any

log = logging.getLogger("atelier.llm")


class LlmIndisponible(RuntimeError):
    """Le modèle n'a pas pu être joint, ou n'a rien rendu d'exploitable."""


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
    cle = _cle(settings)
    if not cle:
        raise LlmIndisponible("aucune clé pour le modèle")
    base = str(settings.anthropic_base_url or "").rstrip("/")
    if not base:
        raise LlmIndisponible("aucune adresse pour le modèle")

    charge = {
        "model": _modele(settings, modele),
        "max_tokens": max_tokens,
        "system": consigne,
        # Le modèle servi ici raisonne à voix haute avant de répondre, et ce
        # préambule consomme le budget : sur une limite trop basse, la
        # réponse s'arrête avant le premier mot utile. On n'en a pas besoin
        # pour une question fermée.
        "thinking": {"type": "disabled"},
        "messages": [{"role": "user", "content": message}],
    }
    requete = urllib.request.Request(
        f"{base}/v1/messages",
        data=json.dumps(charge, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "x-api-key": cle,
            "anthropic-version": "2023-06-01",
        },
    )
    try:
        with urllib.request.urlopen(requete, timeout=timeout) as reponse:
            data = json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise LlmIndisponible(f"HTTP {exc.code} — {detail}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise LlmIndisponible(str(exc)) from exc

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
    return texte


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
