import logging
import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

log = logging.getLogger(__name__)

PREFIXE = "GATEWAY_"
_NAMESPACE_MONTE = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
_PREFIXE_NAMESPACE = "user-"
_utilisateur_deduit: str | None = None


def utilisateur_du_pod() -> str:
    """Le nom d'utilisateur déduit du namespace, quand rien ne l'a fourni.

    Mesuré sur SSPCloud : un pod ne reçoit **pas** de variable ONYXIA_USER —
    c'est le chart qui la pose, donc elle manque à toute installation faite en
    ligne de commande. Le namespace, lui, est toujours monté : « user-jdupont »
    donne « jdupont ».

    Sans cela, les URL du catalogue — bâties sur ${ONYXIA_USER} — se résolvent
    en « https://user--qgis… », une adresse fausse dont l'échec de sondage
    n'apprend rien. C'est la même déduction que fait le chart de QGIS Hub.

    Hors Kubernetes, le fichier n'existe pas et la fonction rend une chaîne
    vide : rien n'est deviné.
    """
    global _utilisateur_deduit
    if _utilisateur_deduit is None:
        _utilisateur_deduit = ""
        try:
            brut = _NAMESPACE_MONTE.read_text(encoding="utf-8").strip()
        except OSError:
            brut = ""
        if brut.startswith(_PREFIXE_NAMESPACE):
            _utilisateur_deduit = brut[len(_PREFIXE_NAMESPACE) :]
    return _utilisateur_deduit


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=PREFIXE, extra="ignore")

    catalog_path: Path = Path("mcp/catalog.yaml")
    db_path: Path = Path("data/gateway.db")
    # Racine du widget. Vide : déduite des sources (dépôt cloné). À renseigner
    # quand le paquet est installé — le widget n'est alors plus à côté du code.
    widget_dir: Path | None = None
    host_url: str = "http://localhost:8080"
    onyxia_user: str = ""
    app_auth_token: str = ""
    # Verrou propriétaire : protège /mcp et /api/v1/* par clé maître ou jeton OAuth.
    # Clé vide + owner_lock actif => clé générée au démarrage et journalisée.
    owner_lock: bool = False
    owner_key: str = ""
    grist_site_url: str = ""
    grist_sync_enabled: bool = False
    # Tokens upstream (optionnels) — ex. GATEWAY_BEARER_COMPUTE=...
    bearer_compute: str = ""
    bearer_qgis: str = ""
    bearer_llm: str = ""
    upstream_probe_on_startup: bool = True
    mcp_default_bundle: str = ""
    gitlab_catalog_url: str = ""
    bearer_ceremadoc: str = ""
    gitlab_catalog_token: str = ""
    catalog_sync_write_local: bool = False

    @property
    def widget_url(self) -> str:
        return f"{self.host_url.rstrip('/')}/widget/"


settings = Settings()
