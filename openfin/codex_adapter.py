from __future__ import annotations

import json
import signal
import subprocess
import threading
from collections.abc import Callable, Iterator
from typing import Any

from openfin.agent_store import AgentEvent, AgentStatus, Project, utc_now


PopenFactory = Callable[..., Any]


class CodexAdapter:
    name = "codex"

    def __init__(
        self,
        *,
        executable: str = "codex",
        popen: PopenFactory | None = None,
    ) -> None:
        self.executable = executable
        self._popen = popen or subprocess.Popen
        self._process: Any | None = None
        self._status: AgentStatus = "idle"
        self.native_session_id: str | None = None

    def build_command(
        self,
        *,
        project: Project,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
        system_context: str | None = None,
    ) -> list[str]:
        del project
        composed_prompt = compose_codex_prompt(prompt, system_context)
        if resume_id:
            command = [
                self.executable,
                "exec",
                "resume",
                "--json",
                "--skip-git-repo-check",
            ]
            if model:
                command.extend(["--model", model])
            command.extend([resume_id, composed_prompt])
            return command

        command = [
            self.executable,
            "exec",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
        ]
        if model:
            command.extend(["--model", model])
        command.append(composed_prompt)
        return command

    def run_turn(
        self,
        *,
        project: Project,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
        system_context: str | None = None,
    ) -> Iterator[AgentEvent]:
        command = self.build_command(
            project=project,
            prompt=prompt,
            resume_id=resume_id,
            model=model,
            system_context=system_context,
        )
        self._status = "busy"
        had_error = False
        process = self._popen(
            command,
            cwd=str(project.root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._process = process
        stderr_chunks: list[str] = []
        stderr_thread: threading.Thread | None = None
        if process.stderr is not None:
            stderr_thread = threading.Thread(
                target=_drain_stream,
                args=(process.stderr, stderr_chunks),
                daemon=True,
            )
            stderr_thread.start()

        stdout = process.stdout or []
        for raw_line in stdout:
            line = raw_line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                had_error = True
                yield AgentEvent(
                    kind="error",
                    text=f"invalid Codex JSON: {line}",
                    raw={"line": line},
                    ts=utc_now(),
                    session_id=self.native_session_id or "",
                )
                continue
            event = normalize_codex_event(payload)
            if event.session_id:
                self.native_session_id = event.session_id
            yield event

        returncode = process.wait()
        if stderr_thread is not None:
            stderr_thread.join()
        stderr_text = "".join(stderr_chunks).strip()
        self._process = None
        if returncode != 0:
            had_error = True
            yield AgentEvent(
                kind="error",
                text=stderr_text or f"Codex exited with status {returncode}",
                raw={"returncode": returncode, "stderr": stderr_text},
                ts=utc_now(),
                session_id=self.native_session_id or "",
            )
        self._status = "error" if had_error else "idle"

    def interrupt(self) -> None:
        process = self._process
        if process is not None:
            process.send_signal(signal.SIGINT)

    def status(self) -> AgentStatus:
        return self._status


def compose_codex_prompt(prompt: str, system_context: str | None) -> str:
    if not system_context:
        return prompt
    return f"OpenFin context:\n{system_context}\n\nUser request:\n{prompt}"


def normalize_codex_event(payload: dict[str, Any]) -> AgentEvent:
    event_type = str(payload.get("type") or payload.get("event") or "progress")
    item = payload.get("item")
    item_data = item if isinstance(item, dict) else {}
    item_type = str(item_data.get("type") or "")
    role = str(item_data.get("role") or payload.get("role") or "")
    session_id = extract_session_id(payload)

    if item_type == "message" and role == "assistant":
        kind = "assistant_text"
        text = extract_text(item_data) or extract_text(payload)
    elif item_type in {"function_call", "tool_call", "tool_use"}:
        kind = "tool_use"
        name = item_data.get("name") or item_data.get("tool_name") or "tool"
        text = f"Tool use: {name}"
    elif item_type in {"function_call_output", "tool_result", "tool_output"}:
        kind = "tool_result"
        text = extract_text(item_data) or "Tool result"
    elif role == "assistant":
        kind = "assistant_text"
        text = extract_text(item_data) or extract_text(payload)
    elif role == "tool":
        kind = "tool_result"
        text = extract_text(item_data) or extract_text(payload) or "Tool result"
    elif is_error_event(event_type):
        kind = "error"
        text = extract_text(payload) or str(payload.get("error") or "Codex error")
    elif is_turn_done_event(event_type):
        kind = "turn_done"
        text = extract_text(payload) or "done"
    elif is_tool_use_event(event_type):
        kind = "tool_use"
        name = payload.get("name") or payload.get("tool_name") or "tool"
        text = f"Tool use: {name}"
    elif is_tool_result_event(event_type):
        kind = "tool_result"
        text = extract_text(payload) or "Tool result"
    else:
        kind = "progress"
        text = extract_text(payload) or event_type

    return AgentEvent(
        kind=kind,
        text=text,
        raw=payload,
        ts=utc_now(),
        session_id=session_id,
    )


def is_error_event(event_type: str) -> bool:
    return "error" in event_type or "failed" in event_type


def is_turn_done_event(event_type: str) -> bool:
    return event_type in {
        "turn.completed",
        "turn.complete",
        "turn.done",
        "task.completed",
        "task.complete",
        "result",
        "completed",
    }


def is_tool_use_event(event_type: str) -> bool:
    return any(
        token in event_type for token in ("tool_use", "tool_call", "function_call")
    )


def is_tool_result_event(event_type: str) -> bool:
    return any(
        token in event_type
        for token in ("tool_result", "tool_output", "function_call_output")
    )


def extract_session_id(payload: dict[str, Any]) -> str:
    for key in (
        "session_id",
        "sessionId",
        "thread_id",
        "threadId",
        "conversation_id",
        "conversationId",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for key in ("session", "thread", "conversation"):
        value = payload.get(key)
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            return value["id"]
    return ""


def extract_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(
            part for part in (extract_text(item) for item in value) if part
        )
    if not isinstance(value, dict):
        return ""

    for key in (
        "text",
        "output_text",
        "message",
        "last_message",
        "output",
        "result",
        "content",
        "summary",
    ):
        text = extract_text(value.get(key))
        if text:
            return text
    return ""


def _drain_stream(stream: Any, sink: list[str]) -> None:
    try:
        for chunk in iter(lambda: stream.read(8192), ""):
            sink.append(chunk)
    except (OSError, ValueError):
        pass
