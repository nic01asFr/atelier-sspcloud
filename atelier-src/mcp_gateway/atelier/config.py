"""Configuration Atelier (chemins PVC, timeouts, binaire claude)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_work() -> Path:
    return Path(os.environ.get("ATELIER_WORK", os.environ.get("HOME", "/home/onyxia") + "/work"))


class AtelierSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATELIER_", extra="ignore")

    work_dir: Path = _default_work()
    host: str = "127.0.0.1"
    port: int = 8787
    # Timeout mural par tour (secondes). Seul plafond opérant côté plateforme.
    turn_timeout_s: int = 600
    # Au-delà de ce poids estimé, l'Atelier fait compacter la conversation
    # avant d'envoyer le tour suivant. Claude Code ne s'en charge pas ici : sa
    # bascule automatique se décide sur les jetons consommés, que la passerelle
    # de modèles rapporte à zéro sur ce chemin. 0 désactive.
    #
    # Le seuil est bas à dessein. L'Atelier ne peut agir qu'entre deux tours,
    # et un seul tour qui enchaîne les outils peut ajouter cent mille jetons —
    # mesuré. Il faut donc laisser derrière soi de quoi encaisser ce tour-là,
    # car une conversation qui a franchi la fenêtre ne se rattrape plus : la
    # compaction, qui passe par le même modèle, ne peut plus la lire non plus.
    compaction_seuil_jetons: int = 40000
    # Plafond de sortie donné au CLI. Il compte dans la fenêtre du modèle :
    # à 16 384, une conversation de 114 689 jetons faisait 131 073 sur une
    # fenêtre de 131 072 — un jeton de trop, et la compaction elle-même
    # échouait, ce qui rendait la conversation irrécupérable. Mesuré : à
    # 8 192 elle passe.
    max_output_tokens: int = 8192
    # Comment travaillent les conversations qui ne disent rien de particulier.
    # `bypassPermissions` est le comportement historique ; le jour où un autre
    # défaut paraîtra plus sage, il se change ici sans toucher aux fiches.
    permission_mode: str = "bypassPermissions"
    effort: str = ""
    default_model: str = ""  # vide = laisser le CLI / settings décider
    default_slug: str = "default"
    # Repo mémoire user (assistant Wikichat) — slug canonique
    assistant_slug: str = "wikichat-memory"
    anthropic_base_url: str = "https://llm.lab.sspcloud.fr/api"
    wikichat_url: str = "http://127.0.0.1:3777/sse"
    # URL publique VS Code / code-server du compte (vide = pas de lien hub)
    vscode_url: str = ""
    # code-server sur le même pod (loopback) — un seul PVC ~/work
    vscode_internal_url: str = "http://127.0.0.1:8080"
    # atelier = proxy protégé owner key ; password = repli si code-server garde son login
    vscode_upstream_auth: str = "atelier"
    # Legacy repli uniquement si upstream_auth=password
    vscode_password: str = ""
    # Identite portee par les commits que l'Atelier fait dans un projet.
    # Locale a chaque depot, jamais globale : le pod porte d'autres depots.
    git_user_name: str = "Atelier"
    git_user_email: str = "atelier@localhost"
    # Compte ou organisation GitHub sous lequel publier un projet. Vide =
    # la publication n'est pas proposee, et le depot reste local.
    github_owner: str = ""

    @property
    def sessions_dir(self) -> Path:
        return self.work_dir / "sessions"

    @property
    def wikichat_dir(self) -> Path:
        return self.work_dir / "wikichat"

    # Combien de temps on garde le processus garé pendant qu'une question
    # attend. Ce n'est pas la durée de vie de la décision — elle, ne périme
    # pas : passé ce délai on relâche le processus et la trace prend le
    # relais. Une heure laisse largement le temps de revenir à l'écran, et
    # un tour garé coûte environ 130 Mo qu'aucun échange ne récupère.
    attente_vive_max_s: int = 3600

    @property
    def decisions_dir(self) -> Path:
        """Les questions qu'un tour attend, écrites dès qu'elles sont posées.

        Sur le disque, parce qu'une décision en attente doit pouvoir le rester
        même si le service redémarre entre la question et la réponse.
        """
        return self.work_dir / "decisions"

    @property
    def transcripts_dir(self) -> Path:
        return self.work_dir / "transcripts"

    @property
    def logs_dir(self) -> Path:
        return self.work_dir / "logs" / "harness"

    @property
    def projects_dir(self) -> Path:
        return self.work_dir / "projects"

    @property
    def assistant_root(self) -> Path:
        return self.work_dir / self.assistant_slug

    @property
    def assistant_sessions_dir(self) -> Path:
        return self.assistant_root / "assistant" / "sessions"

    @property
    def mcp_dir(self) -> Path:
        return self.work_dir / "mcp"

    @property
    def mcp_registry_path(self) -> Path:
        """Legacy JSON — migré vers gateway.db au boot."""
        return self.mcp_dir / "registry.json"

    @property
    def gateway_db_path(self) -> Path:
        return self.mcp_dir / "gateway.db"

    @property
    def gateway_catalog_path(self) -> Path:
        return self.mcp_dir / "catalog.yaml"

    @property
    def mcp_effective_dir(self) -> Path:
        return self.mcp_dir / "effective"

    @property
    def mcp_config_path(self) -> Path:
        """Fichier Claude `--mcp-config` (bridge M1 — enabled registry)."""
        return self.mcp_dir / "claude-mcp.json"

    @property
    def secrets_dir(self) -> Path:
        return self.work_dir / "secrets" if (self.work_dir / "secrets").is_dir() else self.work_dir / ".secrets"

    @property
    def owner_key_path(self) -> Path:
        return self.secrets_dir / "atelier_owner_key"

    @property
    def llm_key_path(self) -> Path:
        return self.secrets_dir / "llm_api_key"

    @property
    def github_token_path(self) -> Path:
        """Jeton GitHub, en 0600. Absent = pas de publication possible."""
        return self.secrets_dir / "github_token"

    @property
    def internal_secret_path(self) -> Path:
        """Secret partagé entre l'Atelier et ce qui s'annonce comme interne.

        L'adresse d'origine ne prouve rien : derrière un ingress, uvicorn voit
        celle du contrôleur, qui est dans une plage privée. Toute requête venue
        d'Internet passerait pour une requête du cluster.
        """
        return self.secrets_dir / "atelier_internal_secret"

    @property
    def claude_bin(self) -> Path:
        return self.work_dir / "bin" / "claude"

    @property
    def claude_env_sh(self) -> Path:
        return self.work_dir / "bin" / "claude-env.sh"

    def ensure_dirs(self) -> None:
        for d in (
            self.sessions_dir,
            self.transcripts_dir,
            self.logs_dir,
            self.projects_dir,
            self.assistant_root,
            self.assistant_sessions_dir,
            self.secrets_dir,
            self.mcp_dir,
            self.mcp_effective_dir,
            self.wikichat_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def get_settings() -> AtelierSettings:
    return AtelierSettings()
