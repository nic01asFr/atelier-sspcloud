"""Messages d'aide pour upstreams hors ligne (API / MCP gateway_status)."""
from __future__ import annotations

from typing import Any


def diagnose_upstream_error(
    error: str | None,
    *,
    auth_hint: str = "",
    server_id: str = "",
    with_prefix: bool = True,
    key_source: str = "",
) -> str | None:
    """Retourne un conseil actionnable, ou None si pas d'erreur.

    `server_id` sert deux usages distincts : préciser le conseil quand le
    service est connu, et préfixer le message. Un écran qui nomme déjà le
    service passe `with_prefix=False` pour garder l'identification sans
    répéter le nom.

    `key_source` (`none` / `stored` / `env` / `not_needed`) tranche ce que le
    code d'erreur seul ne dit pas : un 401 sur un service qui n'a jamais reçu
    de clé n'est pas un refus, c'est une absence. Sans lui, on demandait de
    vérifier une clé que personne n'avait posée.
    """
    if not error:
        return None
    low = error.lower()
    sid = (server_id or "").lower()
    posee = key_source in ("stored", "env")
    tips: list[str] = []
    if "401" in low or "unauthorized" in low or "403" in low:
        if key_source == "env":
            # Une clé fournie par l'environnement est rétablie à chaque
            # démarrage : la corriger ici serait effacé au prochain, et
            # l'utilisateur croirait avoir réparé.
            tips.append(
                "Clé refusée. Elle vient de la configuration du service, pas de "
                "cet écran : elle doit être corrigée là où le service est déployé."
            )
        elif posee:
            tips.append("Clé refusée — vérifiez celle qui est enregistrée pour ce service.")
        else:
            tips.append("Ce service demande une clé d'accès, et aucune n'a encore été renseignée.")
    if "404" in low or "not found" in low:
        # Le conseil nomme le geste, pas l'itinéraire : ces messages s'affichent
        # à côté d'un bouton qui mène déjà au bon endroit, et décrire le chemin
        # à quelqu'un déjà arrivé le fait douter d'être au bon endroit.
        tip = "Adresse introuvable — corrigez l'adresse de ce service."
        # L'exemple ne vaut que pour QGIS : le citer ailleurs égare le lecteur,
        # qui croit lire un conseil sur le service qu'il regarde.
        if "qgis" in sid:
            tip += " Attendu : user-{login}-qgis…/mcp, et non -qgis-mcp-bridge."
        tips.append(tip)
    if "timeout" in low or "timed out" in low or "connect" in low:
        tips.append("Service injoignable — vérifiez qu'il est bien démarré sur SSPCloud.")
    if "stdio" in low or "non supporté" in low:
        tips.append(
            "Ce connecteur ne fonctionne que sur votre poste — la passerelle a "
            "besoin d'une adresse web pour l'atteindre."
        )
    if "421" in low:
        tips.append(
            "La passerelle a joint un autre service que celui attendu — "
            "vérifiez son adresse."
        )
    if not tips and auth_hint:
        tips.append(auth_hint)
    if not tips:
        tips.append(f"Relancez la vérification des connexions. Détail : {error[:160]}")
    prefix = f"{server_id}: " if server_id and with_prefix else ""
    return prefix + " ".join(tips)


def service_state(*, online: bool, enabled: bool, error: str | None, key_source: str) -> str:
    """Qualifie un service en un mot, à la source.

    Le client dérivait cet arbitrage de son côté pendant que le serveur
    composait ses conseils du sien : deux verdicts sur le même service, et un
    écran qui pouvait à la fois dire « configuré mais ne répond plus » et
    « corrigez l'adresse ». La décision revient ici, où sont les faits.

    `attente_cle` est le cas que le code d'erreur seul ne peut pas nommer :
    l'upstream répond 401 aussi bien à une clé fausse qu'à une clé absente.
    """
    if not enabled:
        return "desactive"
    if online:
        return "en_ligne"
    if key_source == "none":
        # Jamais configuré : coller une clé. Distinct d'un service qui tombe.
        return "attente_cle"
    if error:
        return "hors_ligne"
    return "non_teste"


STATE_LABELS = {
    "en_ligne": "En ligne",
    "attente_cle": "Attend sa clé",
    "hors_ligne": "Ne répond plus",
    "desactive": "Désactivé",
    "non_teste": "Non testé",
}


def enrich_upstream_status(
    status: dict[str, Any],
    *,
    auth_hints: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Ajoute un champ hint par upstream en erreur."""
    hints = auth_hints or {}
    out: dict[str, Any] = {}
    for key, info in status.items():
        item = dict(info) if isinstance(info, dict) else {"raw": info}
        err = item.get("error")
        sid = key.split(":", 1)[-1]
        tip = diagnose_upstream_error(err, auth_hint=hints.get(sid, hints.get(key, "")), server_id=key)
        if tip:
            item["hint"] = tip
        out[key] = item
    return out


__all__ = ["diagnose_upstream_error", "enrich_upstream_status"]
