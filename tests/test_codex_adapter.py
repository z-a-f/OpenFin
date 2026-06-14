from __future__ import annotations

import io
import os
import signal
import shutil
from pathlib import Path

import pytest

from openfin.agent_store import Project
from openfin.codex_adapter import (
    CodexAdapter,
    compose_codex_prompt,
    normalize_codex_event,
)


class FakeProcess:
    def __init__(self, lines: list[str], returncode: int = 0, stderr: str = "") -> None:
        self.stdout = io.StringIO("\n".join(lines) + "\n")
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.signals: list[int] = []

    def wait(self) -> int:
        return self.returncode

    def send_signal(self, sig: int) -> None:
        self.signals.append(sig)


def test_codex_command_uses_exec_json_and_safe_argv(tmp_path: Path) -> None:
    adapter = CodexAdapter(executable="codex")

    command = adapter.build_command(
        project=Project(name="OpenFin", root=tmp_path),
        prompt='$(touch /tmp/openfin-pwned); echo "still data"',
        resume_id=None,
        model="gpt-5",
        system_context="OpenFin context",
    )

    assert command == [
        "codex",
        "exec",
        "--json",
        "--color",
        "never",
        "--skip-git-repo-check",
        "--model",
        "gpt-5",
        compose_codex_prompt(
            '$(touch /tmp/openfin-pwned); echo "still data"',
            "OpenFin context",
        ),
    ]


def test_codex_resume_command_uses_exec_resume(tmp_path: Path) -> None:
    adapter = CodexAdapter(executable="codex")

    command = adapter.build_command(
        project=Project(name="OpenFin", root=tmp_path),
        prompt="continue",
        resume_id="thread-123",
        model=None,
        system_context=None,
    )

    assert command == [
        "codex",
        "exec",
        "resume",
        "--json",
        "--skip-git-repo-check",
        "thread-123",
        "continue",
    ]


def test_codex_prompt_composition_injects_openfin_context() -> None:
    assert compose_codex_prompt("ship it", None) == "ship it"
    assert compose_codex_prompt("ship it", "Context pack") == (
        "OpenFin context:\nContext pack\n\nUser request:\nship it"
    )


def test_codex_event_normalization_handles_messages_tools_and_results() -> None:
    message = normalize_codex_event(
        {
            "type": "item.completed",
            "thread_id": "thread-1",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Hello"}],
            },
        }
    )
    tool = normalize_codex_event(
        {
            "type": "item.completed",
            "item": {
                "type": "function_call",
                "name": "shell",
                "arguments": '{"cmd": "pytest"}',
            },
        }
    )
    result = normalize_codex_event(
        {
            "type": "item.completed",
            "item": {
                "type": "function_call_output",
                "output": "tests passed",
            },
        }
    )
    done = normalize_codex_event(
        {
            "type": "turn.completed",
            "thread_id": "thread-1",
            "last_message": "done",
        }
    )

    assert message.kind == "assistant_text"
    assert message.text == "Hello"
    assert message.session_id == "thread-1"
    assert tool.kind == "tool_use"
    assert tool.text == "Tool use: shell"
    assert result.kind == "tool_result"
    assert result.text == "tests passed"
    assert done.kind == "turn_done"
    assert done.text == "done"
    assert done.session_id == "thread-1"


def test_codex_adapter_streams_events_and_captures_session_id(tmp_path: Path) -> None:
    process = FakeProcess(
        [
            '{"type":"thread.started","thread_id":"thread-abc"}',
            '{"type":"item.completed","item":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"Working"}]}}',
            '{"type":"turn.completed","thread_id":"thread-abc","last_message":"Finished"}',
        ]
    )
    calls: list[tuple[list[str], Path]] = []

    def fake_popen(command, *, cwd, text, stdout, stderr):
        calls.append((command, Path(cwd)))
        return process

    adapter = CodexAdapter(executable="codex", popen=fake_popen)
    project = Project(name="OpenFin", root=tmp_path)

    events = list(adapter.run_turn(project=project, prompt="hello"))

    assert [event.kind for event in events] == [
        "progress",
        "assistant_text",
        "turn_done",
    ]
    assert events[-1].session_id == "thread-abc"
    assert adapter.native_session_id == "thread-abc"
    assert calls[0][1] == tmp_path
    assert adapter.status() == "idle"


def test_codex_adapter_emits_error_on_bad_json_and_failed_exit(tmp_path: Path) -> None:
    process = FakeProcess(["not json"], returncode=2, stderr="boom")
    adapter = CodexAdapter(
        executable="codex",
        popen=lambda command, *, cwd, text, stdout, stderr: process,
    )

    events = list(
        adapter.run_turn(project=Project(name="OpenFin", root=tmp_path), prompt="hi")
    )

    assert events[0].kind == "error"
    assert "invalid Codex JSON" in events[0].text
    assert events[-1].kind == "error"
    assert "boom" in events[-1].text
    assert adapter.status() == "error"


def test_codex_adapter_interrupt_sends_sigint() -> None:
    process = FakeProcess([])
    adapter = CodexAdapter(
        executable="codex",
        popen=lambda command, *, cwd, text, stdout, stderr: process,
    )
    adapter._process = process

    adapter.interrupt()

    assert process.signals == [signal.SIGINT]


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("OPENFIN_RUN_CODEX_SMOKE"),
    reason="set OPENFIN_RUN_CODEX_SMOKE=1 to run the real Codex CLI smoke test",
)
@pytest.mark.skipif(shutil.which("codex") is None, reason="codex not found")
def test_real_codex_exec_json_smoke(tmp_path: Path) -> None:
    adapter = CodexAdapter()

    events = list(
        adapter.run_turn(
            project=Project(name="OpenFin", root=tmp_path),
            prompt="Reply with OK only.",
        )
    )

    kinds = {event.kind for event in events}
    errors = [event.text for event in events if event.kind == "error"]
    assert not errors
    assert "assistant_text" in kinds
    assert "turn_done" in kinds
