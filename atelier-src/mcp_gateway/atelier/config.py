"""Configuration Atelier (chemins PVC, timeouts, binaire claude)."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Les niveaux d'effort que TOUS les modèles de la passerelle acceptent.
# Mesuré le 16 septembre 2026, CLI 2.1.273, repli neutralisé, sur chacun des
# trois modèles servis : low, medium et xhigh passent partout ; high est refusé
# par qwen3-8-27b — « Unexpected reasoning effort high. Supported types are
# xhigh, medium, and low ». Or ce modèle est à la fois le dernier repli et celui
# des sous-agents : un effort `high`, défaut du CLI, ne tombe pas au premier
# appel mais au pire moment, quand les deux autres ont déjà échoué, et son
# message masque alors la vraie cause.
EFFORTS_ACCEPTES_PARTOUT = ("low", "medium", "xhigh")
EFFORT_SUR_LA_PASSERELLE = "medium"


def effort_accepte_partout(niveau: str | None) -> str:
    """Le niveau demandé s'il passe partout, sinon le plus proche qui passe.

    `high` et `max` deviennent `xhigh` : on garde l'intention — réfléchir
    davantage — plutôt que de la réduire en silence. Rien, ou un niveau
    inconnu, donne le niveau de la passerelle.
    """
    choix = (niveau or "").strip().lower()
    if choix in EFFORTS_ACCEPTES_PARTOUT:
        return choix
    if choix in ("high", "max"):
        return "xhigh"
    return EFFORT_SUR_LA_PASSERELLE


# La fenêtre réelle de chaque modèle servi par la passerelle, en jetons.
# Mesurée le 25 septembre 2026 (essai de fenêtre, /tmp/compaction-essai) : au-
# delà, litellm répond 400 `ContextWindowExceededError`. Le harnais donne au
# CLI la fenêtre du modèle du tour ; VS Code et le terminal, qui ne savent pas
# d'avance quel modèle servira, reçoivent la plus petite.
FENETRES_DES_MODELES: dict[str, int] = {
    "qwen3-6-35b-moe": 131072,
    "qwen3-8-27b": 131072,
    "gemma4-26b-moe": 131072,
}
FENETRE_PAR_DEFAUT = 131072


def fenetre_du_modele(modele: str | None) -> int:
    """La fenêtre d'un modèle ; celle par défaut s'il est inconnu ou absent."""
    return FENETRES_DES_MODELES.get((modele or "").strip(), FENETRE_PAR_DEFAUT)


def fenetre_minimale() -> int:
    """La fenêtre qui tient quel que soit le modèle : celle des surfaces sans tour."""
    return min([FENETRE_PAR_DEFAUT, *FENETRES_DES_MODELES.values()])


def _default_work() -> Path:
    return Path(os.environ.get("ATELIER_WORK", os.environ.get("HOME", "/home/onyxia") + "/work"))


class AtelierSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATELIER_", extra="ignore")

    work_dir: Path = _default_work()
    host: str = "127.0.0.1"
    port: int = 8787
    # Échéance murale d'un tour, en secondes. Seul plafond opérant côté
    # plateforme, et il ne court que pendant le travail : l'attente d'une
    # décision l'arrête.
    #
    # Dix minutes suffisaient tant qu'un tour n'écrivait que du code. Depuis
    # qu'un agent peut agir sur l'infrastructure — construire une image,
    # attendre qu'un pod démarre —, elles ne suffisent plus : un build kaniko
    # a été tué en plein travail. On donne le temps d'une tâche longue, sans
    # renoncer à un plafond : un tour parti en boucle doit finir par s'arrêter.
    turn_timeout_s: int = 2700
    # Le relais LLM (`relais_llm`) : entre Claude Code et la passerelle de
    # modèles, il rend le décompte de jetons que la passerelle rapporte à zéro
    # en flux, et traduit son erreur de fenêtre dépassée dans les mots que
    # Claude Code reconnaît. Avec lui, la compaction native du CLI fonctionne,
    # sur toutes les surfaces. Faux = on s'en passe, et la compaction de
    # l'Atelier (plus bas) reprend du service.
    relais_llm: bool = True
    relais_llm_port: int = 8790
    # Caractères par jeton, pour estimer ce que la passerelle ne compte pas.
    # Mesuré : 363 000 caractères de conversation valent 99 016 jetons réels
    # (3,67) ; 3,4 surestime un peu, ce qui fait compacter un peu tôt plutôt
    # qu'un peu tard.
    relais_llm_ratio: float = 3.4

    # --- Compaction de l'Atelier : repli quand le relais est absent -------
    #
    # Tout ce qui suit ne joue que si le relais ne répond pas. Avec lui, la
    # compaction native du CLI se déclenche d'elle-même (mesuré : essai B,
    # auto-compaction à ~106 000 jetons) et la compaction de l'Atelier ne
    # ferait que doubler le travail.
    #
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
    # Mesuré depuis : notre compte sous-estime d'environ 2,7 fois ce que le
    # modèle servi facture. Une conversation à 45 000 de nos unités a été
    # refusée à 122 881 jetons réels. Le seuil descend donc d'autant : 25 000
    # chez nous valent environ 68 000 là-bas, ce qui laisse de la place pour
    # le tour qui suit.
    compaction_seuil_jetons: int = 25000

    # Le même mal, mais pendant un tour : l'Atelier ne pouvait agir qu'entre
    # deux, et un seul tour peut ajouter cent mille jetons. Mesuré le
    # 17 septembre : un agent parti pour un lot de travail a enchaîné quatre-
    # vingts appels d'outils, s'est mis à inventer une revue qu'on ne lui
    # avait pas faite vers 38 800 de nos unités, et a fini au-delà de la
    # fenêtre du modèle — conversation perdue. Au-delà de ce poids estimé, le
    # harnais arrête le tour ; l'Atelier compacte et le fait reprendre.
    # 0 désactive.
    contexte_plafond_jetons: int = 32000

    # Combien de fois de suite un tour peut être arrêté, résumé, puis repris.
    # Une seule reprise ne suffit pas : le lot L7-1a a demandé 69 000 unités
    # d'un seul tenant, soit deux plafonds. On s'arrête quand le résumé ne
    # rend plus la main — c'est le signe qu'il n'y a plus rien à gagner.
    contexte_reprises_max: int = 3

    cli_fenetre_compaction: int = 30000
    cli_contexte_max: int = 40000
    # Plafond de sortie donné au CLI. Il compte dans la fenêtre du modèle :
    # à 16 384, une conversation de 114 689 jetons faisait 131 073 sur une
    # fenêtre de 131 072 — un jeton de trop, et la compaction elle-même
    # échouait, ce qui rendait la conversation irrécupérable. Mesuré : à
    # 8 192 elle passe.
    max_output_tokens: int = 8192
    # Comment travaillent les conversations qui ne disent rien de particulier.
    # `bypassPermissions` fut le comportement historique, seul vivable tant
    # qu'une réponse « toujours » ne tenait pas. Depuis qu'elle tient — le CLI
    # applique lui-même ce qu'on a accordé —, `acceptEdits` demande une fois
    # par commande et se tait ensuite : c'est le réglage d'un atelier où
    # quelqu'un regarde. Un tour sans interlocuteur (agent piloté, script)
    # garde `bypassPermissions`, sinon il refuserait tout : voir
    # `MODE_SANS_INTERLOCUTEUR` dans le harnais.
    permission_mode: str = "acceptEdits"
    # Un processus `claude` par conversation, gardé entre les tours. Mesuré le
    # 14 septembre 2026 avec dix connecteurs : 3,8 s de reconnexion MCP à
    # chaque processus neuf, 6,6 s au premier mot contre 2,7 s dans le même
    # processus — et sa file de messages devient la nôtre. Il s'éteint après
    # ce silence, et on n'en garde qu'autant que la mémoire le permet : 238 Mo
    # chacun, mesuré, sur un pod sans zone d'échange.
    cli_processus_vivant: bool = True
    cli_inactivite_s: int = 600
    cli_processus_max: int = 3
    effort: str = ""
    default_model: str = ""  # vide = laisser le CLI / settings décider
    default_slug: str = "default"
    # Repo mémoire user (assistant Wikichat) — slug canonique
    assistant_slug: str = "wikichat-memory"
    anthropic_base_url: str = "https://llm.lab.sspcloud.fr/api"
    wikichat_url: str = "http://127.0.0.1:3777/sse"
    # Navigateur intégré (Chrome DevTools MCP), adresse interne de son `/mcp`
    # (ex. `http://chrome-devtools-mcp:3100/mcp`). Vide = pas de navigateur :
    # l'Atelier ne le déclare pas. Jamais l'ingress public.
    chrome_mcp_url: str = ""
    # Jeton du service (sa `CDM_API_KEY`). Le fichier `chrome_mcp_token` du
    # dossier de secrets prime ; cette variable sert à l'amorçage. Il ne
    # s'écrit jamais dans un `.mcp.json` : seulement sa référence.
    chrome_mcp_token: str = ""
    # Adresse à laquelle ce service répond depuis l'extérieur, celle que sert
    # l'ingress. Vide = on retombe sur celle que voit uvicorn, qui derrière un
    # ingress est interne : un client MCP distant y enverrait son flux OAuth et
    # n'arriverait nulle part. À renseigner dès que le service est exposé.
    public_url: str = ""
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
    # Applications des projets (docs/atelier-applications.md). Elles sont
    # servies sur une seconde origine, jamais sous un chemin de celle-ci :
    # vide = pas de second hôte, et « Ouvrir » reste grisé.
    apps_public_url: str = ""
    # Port de la seconde application ASGI, celle de l'hôte des applications.
    apps_port: int = 8788
    # Plage où l'Atelier attribue les ports des applications, bornes
    # comprises. Le proxy n'atteint que ceux qu'il a attribués.
    apps_ports: str = "19000-19099"
    # Applications lancées en même temps, au plus. Chacune coûte de la
    # mémoire sur un pod sans zone d'échange.
    apps_max: int = 4
    # Arrêt d'une application restée sans requête ni connexion ouverte, quand
    # son manifeste ne dit rien.
    apps_idle_minutes: int = 30

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
    def chrome_mcp_token_path(self) -> Path:
        """Jeton du service navigateur, en 0600. Absent = pas de navigateur."""
        return self.secrets_dir / "chrome_mcp_token"

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
