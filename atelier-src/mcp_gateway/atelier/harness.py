"""Harness — seul module qui construit une ligne de commande `claude`."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import select
import signal
import subprocess
import tempfile
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mcp_gateway.atelier.claude_home import binaire_claude_le_plus_recent, sync_claude_home
from mcp_gateway.atelier.config import (
    EFFORT_SUR_LA_PASSERELLE,
    AtelierSettings,
    effort_accepte_partout,
)
from mcp_gateway.atelier.decisions import (
    Demande,
    RegistreDesDecisions,
    reglages_cli,
    reponse_autorisee,
    reponse_refusee,
)
from mcp_gateway.atelier.events import AtelierEvent, parse_stream_json_line
from mcp_gateway.atelier.mcp_sync import materialize_mcp_config


# Le lecteur de l'interface ne se sert que de ces enregistrements. Le flux
# du CLI en contient bien d'autres — chaque fragment de texte arrive en
# `stream_event` — qui ne servent qu'a l'affichage en direct, deja assure
# par le canal SSE. Les garder gonflait le journal d'un facteur dix, que le
# navigateur retelechargeait et relisait a chaque ouverture.
TYPES_UTILES = frozenset({"assistant", "user", "result"})
_TYPE = re.compile(r'"type"\s*:\s*"([a-z_-]+)"')


def ligne_a_conserver(ligne: str) -> bool:
    trouve = _TYPE.search(ligne)
    return bool(trouve) and trouve.group(1) in TYPES_UTILES


# Les trois façons dont la même phrase nous arrive : en fragments pendant
# qu'elle s'écrit, en bloc quand elle est finie, et une dernière fois dans la
# ligne de résultat.
FRAGMENTS = ("content_block_delta", "text_delta")
REFLEXION = ("thinking", "thinking_delta")


def retenir_le_texte(retenus: list[str], ev: AtelierEvent) -> list[str]:
    """Ce que l'agent a dit, une fois — pas trois.

    Mesuré : « Le fichier a1.txt contient 120 lignes. » revenait trois fois
    dans le résultat d'un tour, parce qu'on additionnait les fragments, puis
    le bloc complet, puis la ligne de résultat. Ce texte-là est ce qu'un agent
    piloté rend à qui l'a lancé : le tripler, c'est tripler la réponse.

    On ne garde donc que les blocs complets. La ligne de résultat ne sert que
    si rien n'est venu avant elle — c'est le cas d'un CLI qui n'émet pas ses
    messages en cours de route.
    """
    if ev.kind != "texte" or not ev.text:
        return retenus
    if ev.raw_type in REFLEXION or ev.raw_type in FRAGMENTS:
        return retenus
    if ev.raw_type == "result_text" and retenus:
        return retenus
    retenus.append(ev.text)
    return retenus


def enregistrement_utilisateur(message: str, session_id: str, horodatage: str) -> str:
    """Ce que quelqu'un vient d'ecrire, tel que le journal doit le garder.

    Le CLI recoit la question en argument et ne la reemet pas dans son flux :
    sans cette ligne, une conversation relue ailleurs n'a plus que les
    reponses, et les messages de la personne restent dans le navigateur qui
    les a tapes.
    """
    return (
        json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": message}],
                },
                "session_id": session_id,
                "timestamp": horodatage,
                "parent_tool_use_id": None,
            },
            ensure_ascii=False,
        )
        + chr(10)
    )


@dataclass
class TurnResult:
    session_id: str
    exit_code: int
    events: list[AtelierEvent] = field(default_factory=list)
    log_path: str = ""
    transcript_path: str = ""
    text: str = ""


class FileDesMessages:
    """Ce qu'on écrira au tour en cours, quand il en aura fini avec le précédent.

    Le CLI tient déjà cette file : un message écrit sur son entrée pendant
    qu'il travaille est gardé, puis traité — mesuré, même processus et même
    session. On pourrait donc y écrire aussitôt.

    On ne le fait pas, pour deux raisons. Un tour qui tombe — échéance,
    interruption, incident — emporterait ce qui attend dans son entrée, sans
    trace. Et un message déjà parti ne se reprend plus, alors qu'on veut
    pouvoir l'annuler tant qu'il n'a pas quitté la file.

    Différer l'écriture règle un troisième problème, sans qu'on l'ait cherché :
    seul le fil du tour écrit dans l'entrée du CLI. Deux fils qui y écriraient
    ensemble pourraient couper une ligne JSON en deux, et il n'existe aucun
    verrou pour l'empêcher.
    """

    def __init__(self) -> None:
        self._verrou = threading.Lock()
        self._files: dict[str, list[dict[str, str]]] = {}

    def deposer(self, session_id: str, texte: str) -> str:
        message = {
            "id": uuid.uuid4().hex[:12],
            "texte": texte,
            "depose_le": datetime.now(timezone.utc).isoformat(),
        }
        with self._verrou:
            self._files.setdefault(session_id, []).append(message)
        return message["id"]

    def retirer(self, session_id: str) -> dict[str, str] | None:
        """Le prochain message à écrire, s'il y en a un."""
        with self._verrou:
            file = self._files.get(session_id) or []
            if not file:
                self._files.pop(session_id, None)
                return None
            return file.pop(0)

    def en_attente(self, session_id: str) -> list[dict[str, str]]:
        with self._verrou:
            return list(self._files.get(session_id) or [])

    def annuler(self, session_id: str, message_id: str) -> bool:
        with self._verrou:
            file = self._files.get(session_id) or []
            for i, m in enumerate(file):
                if m["id"] == message_id:
                    file.pop(i)
                    return True
        return False

    def vider(self, session_id: str) -> int:
        """Le tour s'arrête pour de bon : ce qui attendait n'a plus de porteur."""
        with self._verrou:
            return len(self._files.pop(session_id, []) or [])


class Harness(ABC):
    # Les questions qu'un tour attend. Déclaré sur le contrat parce que
    # les routes s'y adressent sans savoir lequel des deux harnais tourne.
    decisions: RegistreDesDecisions
    # Les messages écrits pendant qu'un tour travaille, en attente de leur départ.
    messages: FileDesMessages

    @abstractmethod
    def run_turn(
        self,
        session_id: str,
        message: str,
        *,
        cwd: Path,
        model: str | None,
        resume: bool,
        transcript_path: Path,
        log_path: Path,
        timeout_s: int,
        claude_session_id: str | None = None,
        mcp_config_path: Path | None = None,
        permission_mode: str = "",
        effort: str = "",
        peut_attendre: bool = False,
        agent_name: str = "",
        poids_initial: int = 0,
        on_event: Callable[[AtelierEvent], None] | None = None,
    ) -> TurnResult: ...

    @abstractmethod
    def interrupt(self, session_id: str) -> bool: ...

    @abstractmethod
    def tour_en_cours(self, session_id: str) -> bool:
        """Un tour tourne-t-il vraiment pour cette conversation ?

        La fiche dit « en cours » ; ce n'est pas la même chose. Un service
        redémarré, un processus tué, et la fiche garde son état alors que plus
        rien ne travaille. Seul le harnais sait, parce que c'est lui qui tient
        les processus.
        """


class FakeHarness(Harness):
    """Harness factice — flux fixe, sans appeler claude (test modularité)."""

    def __init__(self, decisions_dir: Path | None = None) -> None:
        self._memory: dict[str, str] = {}
        self._running: dict[str, bool] = {}
        # Le harnais factice ne pose jamais de question, mais le registre doit
        # exister : les routes s'y adressent sans savoir lequel des deux tourne.
        # Le dossier n'est créé qu'à la première écriture, donc jamais ici.
        self.decisions = RegistreDesDecisions(
            decisions_dir or Path(tempfile.gettempdir()) / "atelier-decisions-fictives"
        )
        self.messages = FileDesMessages()

    def run_turn(
        self,
        session_id: str,
        message: str,
        *,
        cwd: Path,
        model: str | None,
        resume: bool,
        transcript_path: Path,
        log_path: Path,
        timeout_s: int,
        claude_session_id: str | None = None,
        mcp_config_path: Path | None = None,
        permission_mode: str = "",
        effort: str = "",
        peut_attendre: bool = False,
        agent_name: str = "",
        poids_initial: int = 0,
        on_event: Callable[[AtelierEvent], None] | None = None,
    ) -> TurnResult:
        self._running[session_id] = True
        log_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        lower = message.lower()
        if "retiens" in lower or "retenir" in lower:
            import re

            nums = re.findall(r"\d+", message)
            if nums:
                self._memory[session_id] = nums[-1]
            text = "mémorisé."
        elif "quel nombre" in lower or "quel" in lower and "nombre" in lower:
            text = self._memory.get(session_id, "?")
        else:
            text = f"echo:{message}"

        events = [
            AtelierEvent(kind="texte", session_id=session_id, text=text, raw_type="fake"),
            AtelierEvent(kind="fin", session_id=session_id, cause="fake", raw_type="fake"),
        ]
        for ev in events:
            if on_event is not None:
                on_event(ev)
        line = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":%s}]}}\n'
            % __import__("json").dumps(text)
        )
        with transcript_path.open("a", encoding="utf-8") as tf:
            tf.write(
                enregistrement_utilisateur(
                    message, session_id, datetime.now(timezone.utc).isoformat()
                )
            )
            tf.write(line)
            tf.write(
                '{"type":"result","subtype":"success","result":%s}\n'
                % __import__("json").dumps(text)
            )
        log_path.write_text(f"fake turn ok model={model}\n", encoding="utf-8")
        self._running[session_id] = False
        return TurnResult(
            session_id=session_id,
            exit_code=0,
            events=events,
            log_path=str(log_path),
            transcript_path=str(transcript_path),
            text=text,
        )

    def interrupt(self, session_id: str) -> bool:
        self._running[session_id] = False
        return True

    def tour_en_cours(self, session_id: str) -> bool:
        return bool(self._running.get(session_id))


# Les modes que le CLI accepte, et que l'Atelier propose. Éprouvés un par un
# sur le pod, avec trois sondes : éditer dans le projet, y lancer une commande,
# et écrire hors du projet.
#
#   mode                edition   commande   hors projet
#   plan                non       non        —
#   manual              demande   demande    demande
#   acceptEdits         oui       oui        demande
#   auto                oui       oui        demande
#   bypassPermissions   oui       oui        oui
#
# « demande » se lit à la lettre depuis que le harnais tient le canal : le CLI
# ne refuse plus, il pose la question et attend. Les colonnes « non » d'hier
# sont devenues des questions.
#
# Deux modes sont écartés, mais pas pour la même raison.
#
# `dontAsk` refuse tout, y compris ce qu'on croyait anodin — vérifié, il ne crée
# pas plus un fichier qu'il ne lance une commande. Le nom trompe : ne pas
# demander veut dire refuser ce qui aurait demandé. Rien ne le rattrapera.
#
# `manual` est là, désormais. Il demande une approbation à chaque geste, ce qui
# était invivable tant qu'on ne savait pas retenir une réponse : dix-sept
# questions pour un seul tour, mesuré. La mémoire des décisions le rend tenable
# — on accorde une fois, on ne repose plus.
#
# Une réserve tout de même, à dire à l'écran : un tour lancé hors de
# l'interface n'a personne pour répondre, et en `manual` tout passe par la
# porte. Une conversation d'agent réglée ainsi refusera donc tout.
MODES_PERMISSION = ("bypassPermissions", "acceptEdits", "auto", "manual", "plan")
MODE_PERMISSION_DEFAUT = "acceptEdits"
# Un tour que personne ne regarde ne peut pas attendre une autorisation : le
# harnais refuse d'office ce qui demande (voir `SANS_INTERLOCUTEUR`). Sous
# `acceptEdits`, un agent piloté verrait donc chacune de ses commandes
# refusée. Faute de mode choisi pour la conversation, un tel tour garde le
# comportement historique.
MODE_SANS_INTERLOCUTEUR = "bypassPermissions"
NIVEAUX_EFFORT = ("low", "medium", "high", "xhigh", "max")
# Les niveaux acceptés partout, et celui par défaut : voir `config.py`.


# Ce qu'on répond quand la question ne peut atteindre personne. Le motif part
# au modèle : mieux vaut qu'il lise pourquoi on l'a arrêté plutôt que de voir
# un refus muet.
SANS_INTERLOCUTEUR = (
    "Refusé sans être demandé : ce tour ne passe pas par l'interface, "
    "personne ne pouvait répondre. Relancez-le depuis l'Atelier pour décider."
)


@dataclass
class ProcessusVivant:
    """Un `claude` gardé entre deux tours d'une même conversation.

    Sa sortie d'erreur est lue par un fil à part dès sa naissance : lue à la
    fin du tour, comme avant, elle attendrait un processus qui ne finit plus
    — et un tube jamais lu finit par bloquer celui qui y écrit.

    Sa sortie standard aussi, ligne à ligne, dans une file. Surveiller le
    tube avec `select` puis lire par `readline` perdait des lignes de vue :
    `readline` avale tout ce qui est arrivé d'un bloc, en rend une ligne et
    garde le reste dans sa mémoire tampon, que `select` ne voit pas. Quand le
    CLI écrivait sa réponse et son `result` d'un même trait, le `result`
    restait en mémoire et le tour attendait l'échéance, marqué
    `timeout_mural`. Constaté sous Linux, en CI ; Windows y échappait parce
    que `select` n'y écoute pas un tube.
    """

    proc: subprocess.Popen[Any]
    cli_id: str
    empreinte: str
    log_path: Path
    dernier_usage: float = field(default_factory=time.monotonic)
    erreurs: list[str] = field(default_factory=list)
    lecteur: threading.Thread | None = None
    sortie: queue.Queue[str] = field(default_factory=queue.Queue)
    lecteur_sortie: threading.Thread | None = None

    def lire_la_sortie(self) -> None:
        flux = self.proc.stdout
        if flux is None:
            return

        def lire() -> None:
            try:
                for ligne in flux:
                    self.sortie.put(ligne)
            except (OSError, ValueError):
                pass

        self.lecteur_sortie = threading.Thread(target=lire, name="atelier-stdout", daemon=True)
        self.lecteur_sortie.start()

    def sortie_epuisee(self, delai: float = 0.5) -> bool:
        """Vrai quand plus aucune ligne ne viendra : tube fermé, file vide.

        Un processus mort peut laisser des lignes dans le tube que le fil n'a
        pas encore rangées ; on lui laisse `delai` pour finir. Au-delà — un
        petit-enfant qui garde le tube ouvert —, on ne l'attend pas.
        """
        if self.lecteur_sortie is not None:
            self.lecteur_sortie.join(timeout=delai)
        return self.sortie.empty()

    def purger_la_sortie(self) -> None:
        """Jette ce que le processus a pu écrire entre deux tours.

        Rien n'est attendu là — le CLI se tait quand on ne lui parle pas —
        mais une ligne oubliée serait lue comme le début du tour suivant.
        """
        while True:
            try:
                self.sortie.get_nowait()
            except queue.Empty:
                return

    def lire_les_erreurs(self) -> None:
        flux = self.proc.stderr
        if flux is None:
            return

        def lire() -> None:
            try:
                for ligne in flux:
                    self.erreurs.append(ligne)
            except (OSError, ValueError):
                pass

        self.lecteur = threading.Thread(target=lire, name="atelier-stderr", daemon=True)
        self.lecteur.start()

    def attendre_les_erreurs(self, delai: float = 2.0) -> None:
        if self.lecteur is not None:
            self.lecteur.join(timeout=delai)


def ligne_disponible(flux: Any, delai: float) -> str:
    """Lit une ligne, ou rend la main au bout de `delai` secondes.

    `flux` est d'ordinaire la file où un fil range la sortie du CLI (voir
    `ProcessusVivant`) ; un flux ouvert est encore accepté.

    `readline` seul bloque tant que le CLI n'écrit rien. L'échéance du tour se
    trouvait alors hors d'atteinte : elle n'est vérifiée qu'entre deux lignes,
    et un CLI silencieux — le temps d'un appel réseau, ou d'une série de refus
    automatiques — ne produit pas de ligne. Un tour pouvait ainsi dépasser
    largement son échéance sans que rien ne le rappelle. Constaté sur le pod :
    douze minutes pour une échéance de dix.

    Là où `select` ne sait pas écouter un tube — Windows —, on retombe sur la
    lecture bloquante, qui reste correcte : c'est le pod qui fait tourner des
    tours, et il est POSIX.
    """
    if isinstance(flux, queue.Queue):
        try:
            return flux.get(timeout=delai)
        except queue.Empty:
            return ""
    try:
        prets, _, _ = select.select([flux], [], [], delai)
    except (OSError, ValueError, TypeError):
        return flux.readline()
    return flux.readline() if prets else ""


def est_un_resultat(ligne: str) -> bool:
    """La ligne qui clôt un message du CLI.

    Reconnue en la lisant, pas à la lettre : `"type":"result"` collé est la
    forme du vrai CLI, mais un test qui l'écrit avec une espace laissait le
    tour attendre une fin déjà passée.
    """
    if '"result"' not in ligne:
        return False
    try:
        objet = json.loads(ligne)
    except ValueError:
        return False
    return isinstance(objet, dict) and objet.get("type") == "result"


def demande_de_decision(session_id: str, ligne: str) -> Demande | None:
    """Reconnaît, dans le flux, une question posée à l'hôte.

    Le CLI mêle ses `control_request` au reste de sa sortie. Seul le sous-type
    `can_use_tool` nous concerne : c'est la demande d'autorisation, celle qui
    bloque le tour tant qu'on n'a pas répondu.
    """
    if '"control_request"' not in ligne:
        return None
    try:
        objet = json.loads(ligne)
    except ValueError:
        return None
    if not isinstance(objet, dict) or objet.get("type") != "control_request":
        return None
    requete = objet.get("request")
    if not isinstance(requete, dict) or requete.get("subtype") != "can_use_tool":
        return None
    return Demande.depuis_control_request(
        str(objet.get("request_id") or ""), session_id, requete
    )


def mode_permission_valide(mode: str | None) -> str:
    """Le mode demandé s'il est connu, celui par défaut sinon."""
    choix = (mode or "").strip()
    return choix if choix in MODES_PERMISSION else MODE_PERMISSION_DEFAUT


def effort_valide(niveau: str | None) -> str:
    """Le niveau demandé s'il est connu, rien sinon — le CLI décidera."""
    choix = (niveau or "").strip().lower()
    return choix if choix in NIVEAUX_EFFORT else ""


class ClaudeHarness(Harness):
    """Spawn `claude -p` avec stream-json. Seul endroit autorisé à citer claude."""

    def __init__(self, settings: AtelierSettings) -> None:
        self.settings = settings
        self._procs: dict[str, subprocess.Popen[Any]] = {}
        # Les processus gardés entre deux tours, et les conversations dont un
        # tour travaille vraiment. Un processus vivant n'est pas un tour en
        # cours : c'est la seconde qui dit si l'agent travaille.
        self._vivants: dict[str, ProcessusVivant] = {}
        self._en_tour: set[str] = set()
        self._verrou = threading.Lock()
        self._veilleur: threading.Thread | None = None
        # Les questions qu'un tour attend. Portées par le harnais parce que
        # c'est lui qui les pose et se bloque dessus ; la route HTTP y dépose
        # la réponse depuis un autre fil.
        self.decisions = RegistreDesDecisions(settings.decisions_dir)
        self.messages = FileDesMessages()

    def _variables_du_projet(self, cwd: Path | None) -> dict[str, str]:
        """Ce que le projet demande par `.atelier/env.json` (voir `env_projet`)."""
        from mcp_gateway.atelier.env_projet import variables_du_projet

        return variables_du_projet(self.settings.secrets_dir, Path(cwd) if cwd else None)

    def _env(
        self, agent_name: str = "", cwd: Path | None = None, session_id: str = ""
    ) -> dict[str, str]:
        env = os.environ.copy()
        env["ANTHROPIC_BASE_URL"] = self.settings.anthropic_base_url
        key_path = self.settings.llm_key_path
        if key_path.is_file() and not env.get("ANTHROPIC_API_KEY"):
            env["ANTHROPIC_API_KEY"] = key_path.read_text(encoding="utf-8").strip()
        try:
            sync_claude_home(self.settings)
        except OSError:
            pass
        env["PATH"] = str(self.settings.work_dir / "bin") + os.pathsep + env.get("PATH", "")
        # La compaction de nos tours, dite au processus lui-même plutôt que
        # laissée au fichier de réglages global — partagé avec VS Code et
        # avec d'autres mains, où deux valeurs se sont déjà contredites.
        if self.settings.cli_fenetre_compaction > 0:
            env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(self.settings.cli_fenetre_compaction)
        if self.settings.cli_contexte_max > 0:
            env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(self.settings.cli_contexte_max)
        # L'effort par défaut du CLI est `high`, et le modèle de repli de la
        # passerelle — celui du créneau haiku, qui sert aussi les sous-agents —
        # le refuse : « Unexpected reasoning effort high. Supported types are
        # xhigh, medium, and low ». Trois conversations en sont mortes en
        # plein travail, dont un lot entier non commité. On fixe un effort que
        # tous les modèles servis acceptent ; une conversation qui en demande
        # un autre le dit par `--effort`, qui prime.
        env["CLAUDE_CODE_EFFORT_LEVEL"] = effort_accepte_partout(self.settings.effort)
        # Clé de la porte MCP de l'Atelier. Elle passe par l'environnement du
        # processus plutôt que par le `.mcp.json` : le fichier vit dans le
        # dossier du projet, qu'on partage et qu'on versionne.
        try:
            cle = self.settings.owner_key_path.read_text(encoding="utf-8").strip()
        except OSError:
            cle = ""
        if cle:
            env["ATELIER_MCP_KEY"] = cle
        # Les secrets des connecteurs, même raison : le `.mcp.json` d'un
        # projet n'en porte que les références `${ATELIER_MCP_<SERVICE>_…}`,
        # que le CLI développe avec ce qu'il trouve ici. Lus dans le pool à
        # chaque lancement, pour qu'un jeton renouvelé serve au tour suivant.
        from mcp_gateway.atelier.mcp_secrets import variables_du_pool

        env.update(variables_du_pool(self.settings))
        # Les variables que le projet demande, tirées de secrets par
        # référence : un `.mcp.json` qui écrit `${VOICE_TOKEN}` les trouve ici.
        # Résolues à chaque lancement, comme celles du pool.
        env.update(self._variables_du_projet(cwd))
        # Identité de la session auprès du coordinateur. Le `.mcp.json` la
        # relaie dans l'adresse SSE (`?agent=`). Sans elle, la session se
        # présente sans nom : sa mémoire s'écrit dans un sac anonyme et son
        # courrier n'a pas de destinataire.
        #
        # Une identité par conversation, pas par projet : deux fils ouverts
        # sur le même dossier doivent pouvoir se parler et recevoir chacun
        # leur réponse. Ce qu'ils partagent — la mémoire du projet — passe
        # par leur canal-projet commun, que le coordinateur retrouve depuis
        # leur dossier de travail.
        if agent_name:
            env["WIKICHAT_AGENT"] = agent_name
        # La conversation, pour les références `${ATELIER_SESSION}` que le
        # fichier effectif n'a pas résolues lui-même : un `.mcp.json` qu'un
        # outil lancé par l'agent relirait, un sous-processus `claude`. Le
        # processus n'est gardé d'un tour à l'autre que pour la même
        # conversation (`_vivants[session_id]`) : la valeur ne peut pas vieillir.
        # Hérité du poste, `ATELIER_SESSION` serait celui d'une autre : on
        # l'efface plutôt que de le laisser mentir.
        if session_id:
            env["ATELIER_SESSION"] = session_id
        else:
            env.pop("ATELIER_SESSION", None)
        return env

    def _resolve_claude_bin(self) -> Path:
        """Le binaire de nos tours : celui de VS Code d'abord.

        Une même conversation passe d'une surface à l'autre ; elle doit y
        trouver les mêmes outils, les mêmes agents, le même comportement. Le
        lien `~/work/bin/claude` ne vient qu'ensuite, pour un poste sans
        extension.
        """
        recent = binaire_claude_le_plus_recent()
        if recent is not None:
            return recent
        claude = self.settings.claude_bin
        if claude.is_symlink():
            target = claude.resolve()
            if target.is_file():
                return target
        elif claude.is_file():
            return claude
        from shutil import which

        found = which("claude")
        if found:
            return Path(found)
        raise FileNotFoundError(f"claude binary not found at {claude}")

    # Un battement pendant l'attente, pour que le flux vers le navigateur ne
    # s'endorme pas. Sans lui, une question laissée en suspens une heure
    # couperait la connexion, et l'écran n'apprendrait la réponse qu'au
    # rechargement.
    BATTEMENT_ATTENTE = 20.0

    @staticmethod
    def _ecrire_message(proc: subprocess.Popen[Any], texte: str) -> bool:
        """Dépose un message utilisateur sur l'entrée du CLI."""
        if proc.poll() is not None or proc.stdin is None or proc.stdin.closed:
            return False
        try:
            proc.stdin.write(
                json.dumps(
                    {
                        "type": "user",
                        "message": {
                            "role": "user",
                            "content": [{"type": "text", "text": texte}],
                        },
                    },
                    ensure_ascii=False,
                )
                + chr(10)
            )
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    @staticmethod
    def _fermer_entree(proc: subprocess.Popen[Any]) -> None:
        """Dit au CLI qu'il n'y aura plus rien à lire, donc qu'il peut sortir."""
        if proc.stdin is None or proc.stdin.closed:
            return
        try:
            proc.stdin.close()
        except (OSError, ValueError):
            pass

    def _repondre_au_cli(
        self,
        proc: subprocess.Popen[Any],
        request_id: str,
        reponse: dict[str, Any],
    ) -> None:
        """Rend la décision au CLI, qui attend sur son entrée."""
        if proc.poll() is not None or proc.stdin is None or proc.stdin.closed:
            return
        try:
            proc.stdin.write(
                json.dumps(
                    {
                        "type": "control_response",
                        "response": {
                            "subtype": "success",
                            "request_id": request_id,
                            "response": reponse,
                        },
                    },
                    ensure_ascii=False,
                )
                + chr(10)
            )
            proc.stdin.flush()
        except (OSError, ValueError):
            pass

    def _arguments_des_regles(self, session_id: str) -> list[str]:
        """Ce qu'on a accordé dans ce fil, rendu au CLI par `--settings`.

        Un processus par tour : ce que le CLI a retenu pendant un tour meurt
        avec lui. À chaque tour on lui repasse donc les règles du fil, dans sa
        syntaxe, et c'est lui qui les applique — découpage des commandes,
        redirections, liste des commandes sûres : sa sémantique, pas la nôtre.
        Rien quand rien n'a été accordé.
        """
        reglages = reglages_cli(self.decisions.regles(session_id))
        if not reglages:
            return []
        return ["--settings", json.dumps(reglages, ensure_ascii=False)]

    def _attendre_la_decision(
        self,
        demande: Demande,
        proc: subprocess.Popen[Any],
        emettre: Callable[[AtelierEvent], AtelierEvent],
        peut_attendre: bool,
    ) -> float:
        """Pose la question, attend aussi longtemps qu'il faut, rend la réponse.

        Le CLI n'arbitre pas : éprouvé sur ce pod, il attend une demi-heure
        sans broncher, mémoire plate. Rien ici ne vient donc périmer une
        question — c'est l'exigence. Ce qui peut finir, c'est le tour : si le
        processus meurt, ou si l'utilisateur interrompt, on cesse d'attendre.

        Rend le temps passé, que l'appelant ajoute à son échéance.
        """
        # Une décision déjà prise dans ce fil ne se repose pas. C'est ce
        # palier, et lui seul, qui rend `manual` vivable : sans lui, dix-sept
        # questions pour un seul tour. La règle vaut aussi pour un tour
        # automatique — ce que l'utilisateur a accordé, il l'a accordé.
        regle = self.decisions.regle_qui_couvre(demande)
        if regle is not None:
            self._repondre_au_cli(
                proc, demande.request_id, reponse_autorisee(demande.arguments)
            )
            emettre(
                AtelierEvent(
                    kind="decision_rendue",
                    session_id=demande.session_id,
                    tool=demande.outil,
                    tool_id=demande.request_id,
                    cause=f"regle:{regle.portee}",
                )
            )
            return 0.0

        if not peut_attendre:
            # Personne au bout du fil : ce tour ne remonte pas par l'interface.
            # Attendre le figerait pour toujours ; on refuse, ce qui est très
            # exactement ce que le CLI faisait avant que ce canal existe.
            self._repondre_au_cli(
                proc, demande.request_id, reponse_refusee(SANS_INTERLOCUTEUR)
            )
            emettre(
                AtelierEvent(
                    kind="decision_rendue",
                    session_id=demande.session_id,
                    tool=demande.outil,
                    tool_id=demande.request_id,
                    cause="refus_automatique",
                )
            )
            return 0.0

        signal_recu = self.decisions.poser(demande)
        emettre(
            AtelierEvent(
                kind="decision_attendue",
                session_id=demande.session_id,
                text=json.dumps(demande.to_dict(), ensure_ascii=False),
                tool=demande.outil,
                tool_id=demande.request_id,
            )
        )
        debut = time.monotonic()
        limite = max(60, int(self.settings.attente_vive_max_s))
        relachee = False
        while not signal_recu.wait(timeout=self.BATTEMENT_ATTENTE):
            if proc.poll() is not None:
                break
            if time.monotonic() - debut > limite:
                # On rend la mémoire du processus garé, pas la décision : la
                # trace reste sur le disque, et y répondre plus tard la
                # retiendra comme règle. Seul le chemin rapide expire.
                relachee = True
                self.decisions.relacher(demande.request_id)
                break
            emettre(AtelierEvent(kind="heartbeat", session_id=demande.session_id))

        reponse = self.decisions.reponse(demande.request_id)
        if reponse is None:
            # Le tour s'est arrêté, ou l'attente vive a été relâchée. On refuse
            # plutôt que de laisser le CLI attendre quelqu'un qui ne viendra
            # plus.
            reponse = reponse_refusee(
                "Personne n'a répondu à temps ; la question reste posée dans l'Atelier."
                if relachee
                else "Le tour s'est arrêté avant qu'on réponde."
            )
        if not relachee:
            self.decisions.clore(demande.request_id)

        self._repondre_au_cli(proc, demande.request_id, reponse)

        emettre(
            AtelierEvent(
                kind="decision_rendue",
                session_id=demande.session_id,
                tool=demande.outil,
                tool_id=demande.request_id,
                # Pour une question, on renvoie ce qui a été répondu : le
                # navigateur, lui, reconstruit ses blocs depuis ce flux et
                # perdrait ce qu'il avait noté de son côté. Le serveur est le
                # seul à savoir, de source sûre, ce qui est parti au modèle.
                text=(
                    str(reponse.get("message") or "")
                    if demande.genre == "question"
                    else ""
                ),
                cause="relachee" if relachee else str(reponse.get("behavior") or ""),
            )
        )
        return time.monotonic() - debut


    def run_turn(
        self,
        session_id: str,
        message: str,
        *,
        cwd: Path,
        model: str | None,
        resume: bool,
        transcript_path: Path,
        log_path: Path,
        timeout_s: int,
        claude_session_id: str | None = None,
        mcp_config_path: Path | None = None,
        permission_mode: str = "",
        effort: str = "",
        peut_attendre: bool = False,
        agent_name: str = "",
        poids_initial: int = 0,
        on_event: Callable[[AtelierEvent], None] | None = None,
    ) -> TurnResult:
        claude = self._resolve_claude_bin()
        cli_id = (claude_session_id or session_id).strip()

        # Le message ne part plus en argument : il descend par l'entrée
        # standard, qui reste ouverte tout le tour. C'est ce que réclame
        # `--permission-prompt-tool stdio`, par lequel le CLI nous demande
        # l'autorisation au lieu de refuser — et c'est exactement ainsi que
        # l'extension VS Code lance le CLI sur ce pod.
        cmd: list[str] = [
            str(claude),
            "-p",
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-prompt-tool",
            "stdio",
            "--permission-mode",
            mode_permission_valide(permission_mode),
        ]
        # Une conversation qui demande `high` le garde en fiche, mais part avec
        # un niveau que le repli accepte : sinon elle meurt au premier repli.
        niveau = effort_valide(effort)
        if niveau:
            cmd.extend(["--effort", effort_accepte_partout(niveau)])
        cmd.extend(self._arguments_des_regles(session_id))
        if resume:
            cmd.extend(["--resume", cli_id])
        else:
            cmd.extend(["--session-id", cli_id])
        if model:
            cmd.extend(["--model", model])
        # Pas de --append-system-prompt : mesuré sur ce pod, le drapeau est
        # accepté sans erreur mais la consigne n'atteint pas le modèle servi
        # par la passerelle LLM. Le contexte du projet passe par le CLAUDE.md
        # du dossier, que Claude Code lit de lui-même (project_context).

        log_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_path.parent.mkdir(parents=True, exist_ok=True)
        cwd.mkdir(parents=True, exist_ok=True)

        try:
            mcp_cfg = mcp_config_path
            if mcp_cfg is None:
                mcp_cfg = materialize_mcp_config(self.settings)
            cmd.extend(["--mcp-config", str(mcp_cfg), "--strict-mcp-config"])
        except OSError as exc:
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write(f"mcp materialize failed: {exc}\n")

        stamp = datetime.now(timezone.utc).isoformat()
        with log_path.open("a", encoding="utf-8") as lf:
            lf.write(
                f"\n--- turn {stamp} resume={resume} cli_id={cli_id} atelier_id={session_id} "
                f"mcp={mcp_config_path or 'bridge'} ---\n"
            )
            # Quatre mots ne disaient rien de ce qui compte pour comprendre
            # un tour après coup : sous quel mode il a tourné, avec quel
            # effort, quel modèle. On les nomme.
            lf.write(
                "mode: %s | effort: %s | modele: %s" % (
                    mode_permission_valide(permission_mode),
                    effort_accepte_partout(effort_valide(effort)) if effort_valide(effort) else "(defaut)",
                    model or "(defaut)",
                )
                + chr(10)
            )

        # Le même processus sert les tours qui se suivent, tant que rien de ce
        # qui le configure n'a changé : dossier, modèle, mode, effort, agent,
        # connecteurs. Sinon on l'éteint et on repart — un mode de permission
        # se donne à la ligne de commande, il ne se change pas en vol.
        from mcp_gateway.atelier.env_projet import empreinte as empreinte_env

        empreinte = self._empreinte(
            cwd,
            model,
            permission_mode,
            effort,
            agent_name,
            mcp_cfg,
            empreinte_env(self._variables_du_projet(cwd)),
        )
        vivant = self._reprendre(session_id, empreinte)
        if vivant is None:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                env=self._env(agent_name, cwd, session_id),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            vivant = ProcessusVivant(proc=proc, cli_id=cli_id, empreinte=empreinte, log_path=log_path)
            vivant.lire_les_erreurs()
            vivant.lire_la_sortie()
            with self._verrou:
                self._vivants[session_id] = vivant
        else:
            with log_path.open("a", encoding="utf-8") as lf:
                lf.write("processus repris (pid %s)" % vivant.proc.pid + chr(10))
            vivant.purger_la_sortie()
        proc = vivant.proc
        self._procs[session_id] = proc
        with self._verrou:
            self._en_tour.add(session_id)
        depuis = len(vivant.erreurs)
        termine = False
        # L'entrée reste ouverte après l'envoi : c'est par elle que remontent
        # les réponses aux demandes d'autorisation, et que partent les messages
        # écrits pendant que le tour travaille.
        self._ecrire_message(proc, message)

        events: list[AtelierEvent] = []

        def emettre(ev: AtelierEvent) -> AtelierEvent:
            """Retient l'événement, et le donne aussitôt à qui écoute.

            Sans ce rappel, l'appelant ne voyait rien avant la fin du tour :
            la liste ne lui revenait qu'une fois le processus terminé, si bien
            que toute la réponse — texte, appels d'outils, résultats —
            apparaissait d'un bloc après une attente muette.
            """
            events.append(ev)
            if on_event is not None:
                on_event(ev)
            return ev

        texts: list[str] = []
        # Ce que pèse la conversation, mis à jour à mesure qu'elle s'écrit.
        # Même compte que `poids_de_la_conversation` : des caractères divisés
        # par trois. Il ne s'agit pas de facturer, mais de savoir quand
        # s'arrêter.
        poids = poids_initial
        plafond = self.settings.contexte_plafond_jetons
        deadline = time.monotonic() + timeout_s
        assert proc.stdout is not None
        assert proc.stderr is not None

        try:
            with transcript_path.open("a", encoding="utf-8") as tf, log_path.open(
                "a", encoding="utf-8"
            ) as lf:
                tf.write(enregistrement_utilisateur(message, cli_id, stamp))
                tf.flush()
                while True:
                    if time.monotonic() > deadline:
                        proc.send_signal(signal.SIGTERM)
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        emettre(
                            AtelierEvent(
                                kind="erreur",
                                session_id=session_id,
                                cause="timeout_mural",
                            )
                        )
                        break
                    line = ligne_disponible(vivant.sortie, 1.0)
                    if line:
                        demande = demande_de_decision(session_id, line)
                        if demande is not None:
                            # L'horloge du tour s'arrête pendant qu'on attend
                            # quelqu'un : sans cela, `timeout_mural` tuerait un
                            # tour parce qu'un humain déjeune. Deux horloges,
                            # pas une — « l'agent est bloqué » n'est pas « on
                            # attend une réponse ».
                            deadline += self._attendre_la_decision(
                                demande, proc, emettre, peut_attendre
                            )
                            continue
                        if ligne_a_conserver(line):
                            tf.write(line)
                            tf.flush()
                            poids += len(line) // 3
                            if plafond > 0 and poids > plafond:
                                # Le tour a grossi au-delà de ce que le modèle
                                # pourra relire. Le laisser continuer, c'est le
                                # perdre : mesuré, il se met à inventer ce
                                # qu'on ne lui a pas dit, puis la compaction
                                # elle-même ne passe plus. On l'arrête ici ;
                                # l'Atelier compactera et le fera reprendre.
                                self._eteindre(session_id, de_force=True)
                                emettre(
                                    AtelierEvent(
                                        kind="erreur",
                                        session_id=session_id,
                                        cause="contexte_plafond",
                                        text=str(poids),
                                    )
                                )
                                break
                        if est_un_resultat(line):
                            # Un message a fini. S'il en attend un autre, on
                            # l'écrit dans le même tour : le CLI le traitera à
                            # la suite, sans nouveau processus ni `--resume`.
                            # Sinon on ferme l'entrée — tant qu'elle reste
                            # ouverte le CLI attend d'autres messages au lieu
                            # de sortir, et le tour ne s'achevait qu'à
                            # l'échéance murale, marqué `timeout`.
                            suivant = self.messages.retirer(session_id)
                            if suivant is None:
                                # Le tour est fini. Le processus, lui, reste :
                                # ses connecteurs sont branchés, son contexte
                                # est chaud, le prochain message n'aura pas à
                                # repayer tout cela. Sauf si on a demandé
                                # l'ancien comportement, un processus par tour.
                                if self.settings.cli_processus_vivant:
                                    termine = True
                                else:
                                    self._fermer_entree(proc)
                            elif self._ecrire_message(proc, suivant["texte"]):
                                tf.write(
                                    enregistrement_utilisateur(
                                        suivant["texte"],
                                        cli_id,
                                        datetime.now(timezone.utc).isoformat(),
                                    )
                                )
                                tf.flush()
                                # L'échéance repart : ce message n'a pas à
                                # payer le temps qu'a pris le précédent.
                                deadline = time.monotonic() + timeout_s
                                emettre(
                                    AtelierEvent(
                                        kind="systeme",
                                        session_id=session_id,
                                        cause="message_suivant",
                                        text=suivant["texte"],
                                    )
                                )
                            else:
                                self._fermer_entree(proc)
                        for ev in parse_stream_json_line(session_id, line):
                            emettre(ev)
                            retenir_le_texte(texts, ev)
                        if termine:
                            # La ligne de résultat est lue et dite ; le tour
                            # est fini, le processus reste.
                            break
                        continue
                    if proc.poll() is not None and vivant.sortie_epuisee():
                        break
                if termine:
                    code = None
                else:
                    code = proc.wait(timeout=5)
                    vivant.attendre_les_erreurs()
                # La sortie d'erreur est lue par un fil à part : `read()` ici
                # attendrait la fin du processus, qui ne vient plus.
                err = "".join(vivant.erreurs[depuis:])
                if err:
                    lf.write(err)
                    if "[claude-code:unrecognized_model]" not in err and "Error:" in err:
                        emettre(
                            AtelierEvent(kind="erreur", session_id=session_id, cause=err[-500:])
                        )
        finally:
            garder = termine and proc.poll() is None
            with self._verrou:
                self._en_tour.discard(session_id)
            if garder:
                vivant.dernier_usage = time.monotonic()
            else:
                # Un tour abandonné en cours de route — l'appelant qui
                # raccroche, une exception dans la boucle — laissait le
                # `claude` vivre seul, sans personne pour lire sa sortie ni
                # faire jouer l'échéance. Quinze processus s'étaient ainsi
                # accumulés. Ce qui n'est pas un processus gardé à dessein
                # s'éteint ici.
                self._eteindre(session_id, de_force=True)
            # Le tour s'arrête : plus personne n'attend ses questions, ni ne
            # portera les messages restés en file. Les laisser ferait croire
            # qu'ils partiront.
            self.decisions.abandonner(session_id)
            self.messages.vider(session_id)
            try:
                sync_claude_home(self.settings)
            except OSError:
                pass
            self._veiller()

        if not any(e.kind == "fin" for e in events) and code == 0:
            emettre(AtelierEvent(kind="fin", session_id=session_id, cause="exit_0"))
        if code not in (0, None) and not any(e.kind == "erreur" for e in events):
            emettre(
                AtelierEvent(kind="erreur", session_id=session_id, cause=f"exit_{code}")
            )

        return TurnResult(
            session_id=session_id,
            # Un tour fini dans un processus qui vit encore n'a pas de code de
            # sortie ; il s'est bien terminé, c'est ce que l'appelant lit.
            exit_code=0 if termine else int(code if code is not None else -1),
            events=events,
            log_path=str(log_path),
            transcript_path=str(transcript_path),
            text="".join(texts),
        )

    # -- les processus gardés ---------------------------------------------

    @staticmethod
    def _empreinte(
        cwd: Path,
        model: str | None,
        permission_mode: str,
        effort: str,
        agent_name: str,
        mcp_cfg: Path | None,
        env_projet: str = "",
    ) -> str:
        """Ce qui, en changeant, oblige à relancer le processus.

        Les connecteurs comptent par leur contenu, pas par le chemin du
        fichier : celui-ci est le même à chaque tour, seul ce qu'il porte
        change quand on branche ou débranche un connecteur. Les règles
        accordées n'y sont pas : un processus vivant les a reçues avec
        l'autorisation, un neuf les reçoit par `--settings`.
        """
        contenu = b""
        if mcp_cfg is not None:
            try:
                contenu = Path(mcp_cfg).read_bytes()
            except OSError:
                contenu = b""
        clef = "|".join(
            [
                str(cwd),
                model or "",
                mode_permission_valide(permission_mode),
                effort_valide(effort),
                agent_name,
                hashlib.sha256(contenu).hexdigest(),
                # Un secret de `.atelier/env.json` qui change : le processus
                # vivant a l'ancien dans son environnement, on le relance.
                env_projet,
            ]
        )
        return clef

    def _reprendre(self, session_id: str, empreinte: str) -> ProcessusVivant | None:
        """Le processus gardé pour cette conversation, s'il peut encore servir."""
        with self._verrou:
            vivant = self._vivants.get(session_id)
        if vivant is None:
            return None
        if (
            self.settings.cli_processus_vivant
            and vivant.proc.poll() is None
            and vivant.empreinte == empreinte
        ):
            return vivant
        self._eteindre(session_id, de_force=vivant.proc.poll() is None)
        return None

    def _eteindre(self, session_id: str, *, de_force: bool = False) -> None:
        """Referme un processus gardé : l'entrée d'abord, la force ensuite.

        Fermer l'entrée suffit d'ordinaire — le CLI sort quand il n'a plus
        rien à lire. `de_force` est pour ce qui ne doit pas attendre : une
        interruption, un tour abandonné.
        """
        with self._verrou:
            vivant = self._vivants.pop(session_id, None)
        self._procs.pop(session_id, None)
        if vivant is None:
            return
        proc = vivant.proc
        if proc.poll() is None and not de_force:
            self._fermer_entree(proc)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        if proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        vivant.attendre_les_erreurs()

    def _nettoyer_les_processus(self) -> None:
        """Éteint ce qui a trop attendu, ce qui est mort, et ce qui dépasse le plafond.

        Jamais un processus dont un tour travaille. Le plafond retire les moins
        récents d'abord.
        """
        maintenant = time.monotonic()
        with self._verrou:
            garés = [
                (sid, v)
                for sid, v in self._vivants.items()
                if sid not in self._en_tour
            ]
        trop_vieux = [
            sid
            for sid, v in garés
            if maintenant - v.dernier_usage >= self.settings.cli_inactivite_s
            or v.proc.poll() is not None
        ]
        for sid in trop_vieux:
            self._eteindre(sid)
        restants = sorted(
            ((sid, v) for sid, v in garés if sid not in trop_vieux),
            key=lambda item: item[1].dernier_usage,
        )
        with self._verrou:
            total = len(self._vivants)
        excedent = total - max(1, int(self.settings.cli_processus_max))
        for sid, _ in restants[: max(0, excedent)]:
            self._eteindre(sid)

    def _veiller(self) -> None:
        """Nettoie maintenant, et s'assure qu'un fil repassera.

        Appelée à la fin de chaque tour : sans le fil, un dernier processus
        resterait garé tant que personne n'écrit.
        """
        self._nettoyer_les_processus()
        self._assurer_le_veilleur()

    def _assurer_le_veilleur(self) -> None:
        """Un seul fil de veille, jamais deux.

        Le premier essai en lançait un depuis le fil de veille lui-même, à
        chaque passage : sur le pod, 91 139 fils et 2,6 Go en une matinée, et un
        service qui n'écoutait plus. Le fil ne relance donc rien ; il nettoie et
        s'arrête quand il n'y a plus rien à garder, et c'est la fin d'un tour
        qui en repose un au besoin, sous verrou.
        """
        if not self.settings.cli_processus_vivant:
            return

        def boucle() -> None:
            # On dort par tranches d'une seconde plutôt que d'un trait : le
            # dernier processus éteint, le fil doit pouvoir sortir tout de
            # suite au lieu de tenir jusqu'à son prochain réveil.
            pause = max(5, min(30, self.settings.cli_inactivite_s or 30))
            try:
                while True:
                    for _ in range(pause):
                        time.sleep(1)
                        with self._verrou:
                            if not self._vivants:
                                return
                    try:
                        self._nettoyer_les_processus()
                    except Exception:  # noqa: BLE001 — la veille ne doit pas mourir
                        pass
            finally:
                with self._verrou:
                    if self._veilleur is threading.current_thread():
                        self._veilleur = None

        with self._verrou:
            if self._veilleur is not None and self._veilleur.is_alive():
                return
            self._veilleur = threading.Thread(
                target=boucle, name="atelier-veilleur", daemon=True
            )
            fil = self._veilleur
        fil.start()

    def processus_vivants(self) -> list[str]:
        """Les conversations dont un processus est gardé — pour l'état et les tests."""
        with self._verrou:
            return [sid for sid, v in self._vivants.items() if v.proc.poll() is None]

    def tour_en_cours(self, session_id: str) -> bool:
        with self._verrou:
            en_tour = session_id in self._en_tour
        proc = self._procs.get(session_id)
        return en_tour and proc is not None and proc.poll() is None

    def interrupt(self, session_id: str) -> bool:
        # Interrompre, c'est aussi renoncer aux questions du tour : le fil qui
        # attendait va voir le processus mort et cesser d'attendre, mais la
        # trace, elle, resterait sur le disque.
        self.decisions.abandonner(session_id)
        with self._verrou:
            connu = session_id in self._vivants or session_id in self._procs
        if not connu:
            return False
        proc = self._procs.get(session_id)
        self._eteindre(session_id, de_force=True)
        if proc is not None and proc.poll() is None:
            proc.send_signal(signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        return True


def new_session_id() -> str:
    return str(uuid.uuid4())
