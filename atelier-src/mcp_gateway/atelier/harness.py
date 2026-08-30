"""Harness — seul module qui construit une ligne de commande `claude`."""

from __future__ import annotations

import os
import signal
import subprocess
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp_gateway.atelier.claude_home import sync_claude_home
from mcp_gateway.atelier.config import AtelierSettings
from mcp_gateway.atelier.events import AtelierEvent, parse_stream_json_line
from mcp_gateway.atelier.mcp_sync import materialize_mcp_config


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
        agent_name: str = "",
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
        agent_name: str = "",
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
        line = (
            '{"type":"assistant","message":{"content":[{"type":"text","text":%s}]}}\n'
            % __import__("json").dumps(text)
        )
        with transcript_path.open("a", encoding="utf-8") as tf:
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
        agent_name: str = "",
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
            "bypassPermissions",
        ]
        if resume:
            cmd.extend(["--resume", cli_id])
        else:
            cmd.extend(["--session-id", cli_id])
        if model:
            cmd.extend(["--model", model])

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
            lf.write("cmd: " + " ".join(cmd[:4]) + " …\n")

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
        texts: list[str] = []
        deadline = time.monotonic() + timeout_s
        assert proc.stdout is not None
        assert proc.stderr is not None

        try:
            with transcript_path.open("a", encoding="utf-8") as tf, log_path.open(
                "a", encoding="utf-8"
            ) as lf:
                while True:
                    if time.monotonic() > deadline:
                        proc.send_signal(signal.SIGTERM)
                        try:
                            proc.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        events.append(
                            AtelierEvent(
                                kind="erreur",
                                session_id=session_id,
                                cause="timeout_mural",
                            )
                        )
                        break
                    line = proc.stdout.readline()
                    if line:
                        tf.write(line)
                        tf.flush()
                        for ev in parse_stream_json_line(session_id, line):
                            events.append(ev)
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
                        events.append(
                            AtelierEvent(kind="erreur", session_id=session_id, cause=err[-500:])
                        )
            code = proc.wait(timeout=5)
        finally:
            self._procs.pop(session_id, None)
            try:
                sync_claude_home(self.settings)
            except OSError:
                pass

        if not any(e.kind == "fin" for e in events) and code == 0:
            events.append(AtelierEvent(kind="fin", session_id=session_id, cause="exit_0"))
        if code not in (0, None) and not any(e.kind == "erreur" for e in events):
            events.append(
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
