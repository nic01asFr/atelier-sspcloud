"""Harness — seul module qui construit une ligne de commande `claude`."""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from mcp_gateway.atelier.claude_home import sync_claude_home
from mcp_gateway.atelier.config import AtelierSettings
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


class Harness(ABC):
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
        agent_name: str = "",
        on_event: Callable[[AtelierEvent], None] | None = None,
    ) -> TurnResult: ...

    @abstractmethod
    def interrupt(self, session_id: str) -> bool: ...


class FakeHarness(Harness):
    """Harness factice — flux fixe, sans appeler claude (test modularité)."""

    def __init__(self) -> None:
        self._memory: dict[str, str] = {}
        self._running: dict[str, bool] = {}

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
        agent_name: str = "",
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


# Les modes que le CLI accepte, et que l'Atelier propose. Éprouvés un par un
# sur le pod, avec trois sondes : éditer dans le projet, y lancer une commande,
# et écrire hors du projet.
#
#   mode                edition   commande   hors projet
#   plan                non       non        —
#   acceptEdits         oui       oui        non
#   auto                oui       oui        non
#   bypassPermissions   oui       oui        oui
#
# Deux modes du CLI sont écartés, pour la même raison mesurée : ils supposent
# quelqu'un à qui demander, et un tour en `-p` n'a personne. `manual` refuse
# alors chaque édition ; `dontAsk` refuse tout, y compris ce qu'on croyait
# anodin — vérifié, il ne crée pas plus un fichier qu'il ne lance une commande.
# Un mode qui refuse tout est pire que pas de mode.
MODES_PERMISSION = ("bypassPermissions", "acceptEdits", "plan", "auto")
MODE_PERMISSION_DEFAUT = "bypassPermissions"
NIVEAUX_EFFORT = ("low", "medium", "high", "xhigh", "max")


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

    def _env(self, agent_name: str = "") -> dict[str, str]:
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
        # Clé de la porte MCP de l'Atelier. Elle passe par l'environnement du
        # processus plutôt que par le `.mcp.json` : le fichier vit dans le
        # dossier du projet, qu'on partage et qu'on versionne.
        try:
            cle = self.settings.owner_key_path.read_text(encoding="utf-8").strip()
        except OSError:
            cle = ""
        if cle:
            env["ATELIER_MCP_KEY"] = cle
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
        return env

    def _resolve_claude_bin(self) -> Path:
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
        ext_root = Path.home() / ".local/share/code-server/extensions"
        for ext in sorted(ext_root.glob("anthropic.claude-code-*"), reverse=True):
            native = ext / "resources/native-binary/claude"
            if native.is_file():
                return native
        raise FileNotFoundError(f"claude binary not found at {claude}")

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
        agent_name: str = "",
        on_event: Callable[[AtelierEvent], None] | None = None,
    ) -> TurnResult:
        claude = self._resolve_claude_bin()
        cli_id = (claude_session_id or session_id).strip()

        cmd: list[str] = [
            str(claude),
            "-p",
            message,
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--permission-mode",
            mode_permission_valide(permission_mode),
        ]
        niveau = effort_valide(effort)
        if niveau:
            cmd.extend(["--effort", niveau])
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
                    effort_valide(effort) or "(defaut)",
                    model or "(defaut)",
                )
                + chr(10)
            )

        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=self._env(agent_name),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._procs[session_id] = proc

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
                    line = proc.stdout.readline()
                    if line:
                        if ligne_a_conserver(line):
                            tf.write(line)
                            tf.flush()
                        for ev in parse_stream_json_line(session_id, line):
                            emettre(ev)
                            if ev.kind == "texte" and ev.text and ev.raw_type not in (
                                "thinking",
                                "thinking_delta",
                            ):
                                texts.append(ev.text)
                        continue
                    if proc.poll() is not None:
                        break
                    time.sleep(0.05)
                err = proc.stderr.read()
                if err:
                    lf.write(err)
                    if "[claude-code:unrecognized_model]" not in err and "Error:" in err:
                        emettre(
                            AtelierEvent(kind="erreur", session_id=session_id, cause=err[-500:])
                        )
            code = proc.wait(timeout=5)
        finally:
            # Un tour abandonné en cours de route — l'appelant qui raccroche,
            # une exception dans la boucle — laissait le `claude` vivre seul,
            # sans personne pour lire sa sortie ni faire jouer l'échéance :
            # elle ne vaut que tant que la boucle tourne. Quinze processus
            # s'étaient ainsi accumulés. On ne sort pas d'ici sans l'avoir
            # refermé.
            if proc.poll() is None:
                proc.send_signal(signal.SIGTERM)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
            self._procs.pop(session_id, None)
            try:
                sync_claude_home(self.settings)
            except OSError:
                pass

        if not any(e.kind == "fin" for e in events) and code == 0:
            emettre(AtelierEvent(kind="fin", session_id=session_id, cause="exit_0"))
        if code not in (0, None) and not any(e.kind == "erreur" for e in events):
            emettre(
                AtelierEvent(kind="erreur", session_id=session_id, cause=f"exit_{code}")
            )

        return TurnResult(
            session_id=session_id,
            exit_code=int(code if code is not None else -1),
            events=events,
            log_path=str(log_path),
            transcript_path=str(transcript_path),
            text="".join(texts),
        )

    def interrupt(self, session_id: str) -> bool:
        proc = self._procs.get(session_id)
        if not proc:
            return False
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        self._procs.pop(session_id, None)
        return True


def new_session_id() -> str:
    return str(uuid.uuid4())
