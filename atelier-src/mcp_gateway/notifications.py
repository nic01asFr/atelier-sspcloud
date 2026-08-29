"""Notifications web — être prévenu qu'une composition attend une réponse.

Le service savait déjà *afficher* qu'une exécution était suspendue : une boîte
de réception, un compteur sur l'onglet. Mais il fallait ouvrir la page et
cliquer pour l'apprendre. Une composition qui demandait une approbation à 14 h
restait ignorée jusqu'à ce qu'on y pense.

Ceci fait passer de « vous regardez » à « on vous dit », y compris application
fermée. Sur iOS, cela ne fonctionne que pour une application ajoutée à l'écran
d'accueil — c'est une raison de plus de l'installer, pas une limite du dispositif.

Le chiffrement (RFC 8291) et la signature VAPID (RFC 8292) ne sont pas écrits
ici : `pywebpush` les met en œuvre, et c'est précisément le genre de code
cryptographique qu'on ne maintient pas soi-même.

Un pod par utilisateur : les abonnements sont ceux de ses appareils, il n'y a
personne d'autre à distinguer.
"""
from __future__ import annotations

import base64
import json
import logging
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

CLE_PRIVEE_META = "vapid_private_key"
CLE_PUBLIQUE_META = "vapid_public_key"

# Le serveur de poussée exige un contact joignable. Il n'est jamais affiché à
# l'utilisateur ; il sert au fournisseur pour signaler un abus.
SUJET_VAPID = "mailto:passerelle@localhost"


def migrer_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            endpoint   TEXT PRIMARY KEY,
            p256dh     TEXT NOT NULL,
            auth       TEXT NOT NULL,
            appareil   TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()


# ── Clés VAPID ────────────────────────────────────────────────────────────


def _meta_get(conn: sqlite3.Connection, cle: str) -> str:
    row = conn.execute("SELECT value FROM gateway_meta WHERE key = ?", (cle,)).fetchone()
    return (row["value"] if row else "") or ""


def _meta_set(conn: sqlite3.Connection, cle: str, valeur: str) -> None:
    conn.execute(
        """INSERT INTO gateway_meta (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (cle, valeur),
    )
    conn.commit()


def cles_vapid(conn: sqlite3.Connection) -> tuple[str, str]:
    """La paire du service, créée au premier besoin et jamais régénérée.

    Régénérer invaliderait tous les abonnements en place, sans que personne ne
    l'apprenne : les appareils cesseraient simplement d'être prévenus. Elles
    vivent donc dans la base, sur le volume qui survit aux redémarrages.
    """
    privee = _meta_get(conn, CLE_PRIVEE_META)
    publique = _meta_get(conn, CLE_PUBLIQUE_META)
    if privee and publique:
        return privee, publique

    from py_vapid import Vapid01

    v = Vapid01()
    v.generate_keys()
    privee = base64.urlsafe_b64encode(
        v.private_key.private_numbers().private_value.to_bytes(32, "big")
    ).decode().rstrip("=")
    publique = _cle_publique_brute(v)
    _meta_set(conn, CLE_PRIVEE_META, privee)
    _meta_set(conn, CLE_PUBLIQUE_META, publique)
    log.info("Paire VAPID créée : les notifications web sont disponibles.")
    return privee, publique


def _cle_publique_brute(v: Any) -> str:
    """La forme que le navigateur attend : point non compressé, base64url."""
    from cryptography.hazmat.primitives import serialization

    brut = v.public_key.public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )
    return base64.urlsafe_b64encode(brut).decode().rstrip("=")


# ── Abonnements ───────────────────────────────────────────────────────────


def enregistrer_abonnement(conn: sqlite3.Connection, abonnement: dict[str, Any], appareil: str = "") -> None:
    cles = abonnement.get("keys") or {}
    conn.execute(
        """INSERT INTO push_subscriptions (endpoint, p256dh, auth, appareil)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(endpoint) DO UPDATE SET
             p256dh = excluded.p256dh, auth = excluded.auth, appareil = excluded.appareil""",
        (abonnement["endpoint"], cles.get("p256dh", ""), cles.get("auth", ""), appareil[:120]),
    )
    conn.commit()


def oublier_abonnement(conn: sqlite3.Connection, endpoint: str) -> bool:
    cur = conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
    conn.commit()
    return cur.rowcount > 0


def abonnements(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT endpoint, p256dh, auth, appareil, created_at FROM push_subscriptions"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Envoi ─────────────────────────────────────────────────────────────────


def prevenir(
    conn: sqlite3.Connection,
    titre: str,
    corps: str,
    url: str = "/",
    tag: str = "passerelle",
    run_id: str = "",
) -> int:
    """Pousse vers tous les appareils enregistrés. Retourne le nombre atteint.

    Ne lève jamais : une notification qui échoue ne doit pas faire échouer
    l'exécution qu'elle annonçait. Un abonnement mort — appareil réinitialisé,
    permission retirée — est oublié plutôt que réessayé indéfiniment.
    """
    cibles = abonnements(conn)
    if not cibles:
        return 0

    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        log.warning("pywebpush absent : notification « %s » non envoyée.", titre)
        return 0

    privee, _ = cles_vapid(conn)
    charge = json.dumps(
        {"titre": titre, "corps": corps, "url": url, "tag": tag, "run_id": run_id},
        ensure_ascii=False,
    )
    atteints = 0
    for a in cibles:
        try:
            webpush(
                subscription_info={
                    "endpoint": a["endpoint"],
                    "keys": {"p256dh": a["p256dh"], "auth": a["auth"]},
                },
                data=charge,
                vapid_private_key=privee,
                vapid_claims={"sub": SUJET_VAPID},
                timeout=10,
            )
            atteints += 1
        except WebPushException as exc:
            code = getattr(exc.response, "status_code", None)
            if code in (404, 410):
                # L'abonnement n'existe plus côté navigateur. Le garder ferait
                # échouer chaque envoi suivant, sans que rien ne le signale.
                oublier_abonnement(conn, a["endpoint"])
                log.info("Abonnement expiré, oublié (%s).", a["appareil"] or "appareil inconnu")
            else:
                log.warning("Notification non remise (%s) : %s", code, exc)
        except Exception as exc:  # noqa: BLE001 — jamais bloquant
            log.warning("Notification non remise : %s", exc)
    return atteints


__all__ = [
    "abonnements",
    "cles_vapid",
    "enregistrer_abonnement",
    "migrer_schema",
    "oublier_abonnement",
    "prevenir",
]
