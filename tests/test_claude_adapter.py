from __future__ import annotations

import io
import os
import signal
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from openfin.agent_store import Project
from openfin.claude_adapter import ClaudeAdapter, normalize_claude_event


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


def test_claude_command_uses_headless_json_and_safe_options(tmp_path: Path) -> None:
    adapter = ClaudeAdapter(executable="claude")
    project = Project(name="OpenFin", root=tmp_path, profile="code")

    command = adapter.build_command(
        project=project,
        prompt="ship it",
        resume_id="native-123",
        model="sonnet",
        system_context="OpenFin context",
    )

    assert command == [
        "claude",
        "-p",
        "--verbose",
        "--output-format",
        "stream-json",
        "--resume",
        "native-123",
        "--model",
        "sonnet",
        "--append-system-prompt",
        "OpenFin context",
        "ship it",
    ]


def test_claude_event_normalization_handles_text_tool_and_result() -> None:
    assistant = normalize_claude_event(
        {
            "type": "assistant",
            "message": {"content": [{"type": "text", "text": "Hello"}]},
            "session_id": "native-1",
        }
    )
    tool = normalize_claude_event(
        {"type": "tool_use", "name": "Read", "input": {"file_path": "README.md"}}
    )
    result = normalize_claude_event(
        {"type": "result", "result": "Done", "session_id": "native-2"}
    )

    assert assistant.kind == "assistant_text"
    assert assistant.text == "Hello"
    assert assistant.session_id == "native-1"
    assert tool.kind == "tool_use"
    assert "Read" in tool.text
    assert result.kind == "turn_done"
    assert result.text == "Done"
    assert result.session_id == "native-2"


def test_claude_event_normalization_handles_nested_tool_messages() -> None:
    tool = normalize_claude_event(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "tool_use",
                        "id": "tool-1",
                        "name": "Read",
                        "input": {"file_path": "README.md"},
                    }
                ]
            },
        }
    )
    result = normalize_claude_event(
        {
            "type": "user",
            "message": {
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "tool-1",
                        "content": "file contents",
                    }
                ]
            },
        }
    )

    assert tool.kind == "tool_use"
    assert tool.text == "Tool use: Read"
    assert result.kind == "tool_result"
    assert result.text == "file contents"


def test_claude_adapter_streams_events_and_captures_session_id(tmp_path: Path) -> None:
    process = FakeProcess(
        [
            '{"type":"assistant","message":{"content":[{"type":"text","text":"Working"}]}}',
            '{"type":"result","result":"Finished","session_id":"native-abc"}',
        ]
    )
    calls: list[tuple[list[str], Path]] = []

    def fake_popen(command, *, cwd, text, stdout, stderr):
        calls.append((command, Path(cwd)))
        return process

    adapter = ClaudeAdapter(executable="claude", popen=fake_popen)
    project = Project(name="OpenFin", root=tmp_path)

    events = list(adapter.run_turn(project=project, prompt="hello"))

    assert [event.kind for event in events] == ["assistant_text", "turn_done"]
    assert events[-1].session_id == "native-abc"
    assert adapter.native_session_id == "native-abc"
    assert calls[0][1] == tmp_path
    assert adapter.status() == "idle"


def test_claude_adapter_emits_error_on_bad_json_and_failed_exit(tmp_path: Path) -> None:
    process = FakeProcess(["not json"], returncode=2, stderr="boom")
    adapter = ClaudeAdapter(
        executable="claude",
        popen=lambda command, *, cwd, text, stdout, stderr: process,
    )

    events = list(
        adapter.run_turn(project=Project(name="OpenFin", root=tmp_path), prompt="hi")
    )

    assert events[0].kind == "error"
    assert "invalid Claude JSON" in events[0].text
    assert events[-1].kind == "error"
    assert "boom" in events[-1].text
    assert adapter.status() == "error"


def test_claude_adapter_does_not_deadlock_on_large_stderr(tmp_path: Path) -> None:
    child = (
        "import sys;"
        "sys.stderr.write('x' * 1_000_000);"
        "sys.stderr.flush();"
        'print(\'{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]},"session_id":"s1"}\', flush=True);'
        'print(\'{"type":"result","result":"done","session_id":"s1"}\', flush=True)'
    )
    processes: list[subprocess.Popen[str]] = []

    def popen(command, *, cwd, text, stdout, stderr):
        del command, cwd, text, stdout, stderr
        process = subprocess.Popen(
            [sys.executable, "-c", child],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        processes.append(process)
        return process

    adapter = ClaudeAdapter(executable="claude", popen=popen)
    events = []
    done = threading.Event()

    def run() -> None:
        events.extend(
            adapter.run_turn(
                project=Project(name="OpenFin", root=tmp_path), prompt="hi"
            )
        )
        done.set()

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    if not done.wait(timeout=15):
        for process in processes:
            process.kill()
        thread.join(timeout=2)
        raise AssertionError("run_turn deadlocked draining stderr")

    assert "assistant_text" in {event.kind for event in events}
    assert "turn_done" in {event.kind for event in events}


def test_claude_adapter_interrupt_sends_sigint(tmp_path: Path) -> None:
    process = FakeProcess([])
    adapter = ClaudeAdapter(
        executable="claude",
        popen=lambda command, *, cwd, text, stdout, stderr: process,
    )
    adapter._process = process

    adapter.interrupt()

    assert process.signals == [signal.SIGINT]


@pytest.mark.smoke
@pytest.mark.skipif(
    not os.environ.get("OPENFIN_RUN_CLAUDE_SMOKE"),
    reason="set OPENFIN_RUN_CLAUDE_SMOKE=1 to run the real Claude CLI smoke test",
)
@pytest.mark.skipif(shutil.which("claude") is None, reason="claude not found")
def test_real_claude_stream_json_smoke(tmp_path: Path) -> None:
    adapter = ClaudeAdapter()

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
