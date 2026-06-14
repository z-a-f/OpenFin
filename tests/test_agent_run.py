from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import typer

from openfin.agent_run import parse_run_args, run_agent_session
from openfin.agent_store import AgentEvent, AgentSessionStore, Project, utc_now
from openfin.cli import main_entry
from tests.helpers import log_text, openfin_home


class FakeAdapter:
    name = "claude"

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.resume_ids: list[str | None] = []
        self.system_contexts: list[str | None] = []
        self.interrupted = False

    def run_turn(
        self,
        *,
        project: Project,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
        system_context: str | None = None,
    ) -> Iterator[AgentEvent]:
        del project, model
        self.prompts.append(prompt)
        self.resume_ids.append(resume_id)
        self.system_contexts.append(system_context)
        yield AgentEvent(
            kind="assistant_text",
            text=f"answer: {prompt}",
            raw={"prompt": prompt},
            ts=utc_now(),
            session_id="native-1",
        )
        yield AgentEvent(
            kind="turn_done",
            text="done",
            raw={},
            ts=utc_now(),
            session_id="native-1",
        )

    def interrupt(self) -> None:
        self.interrupted = True

    def status(self) -> str:
        return "idle"


def test_parse_run_args_accepts_safe_claude_flags() -> None:
    parsed = parse_run_args(
        [
            "claude",
            "--model",
            "sonnet",
            "--resume",
            "native-1",
            "--profile",
            "code",
            "--for",
            "agent routing",
            "ship",
            "it",
        ]
    )

    assert parsed.adapter == "claude"
    assert parsed.model == "sonnet"
    assert parsed.resume_id == "native-1"
    assert parsed.profile == "code"
    assert parsed.topic == "agent routing"
    assert parsed.initial_prompt == "ship it"


def test_parse_run_args_rejects_unknown_flags() -> None:
    with pytest.raises(typer.BadParameter, match="unsupported --run option"):
        parse_run_args(["claude", "--dangerously-skip-permissions", "go"])


def test_run_agent_session_logs_transcript_and_repl_turns(tmp_path: Path) -> None:
    adapter = FakeAdapter()
    outputs: list[str] = []
    inputs = iter(["second turn", "/status", "/interrupt", "/exit"])

    meta = run_agent_session(
        adapter=adapter,
        project=Project(name="OpenFin", root=tmp_path),
        store=AgentSessionStore(openfin_home(tmp_path)),
        initial_prompt="first turn",
        model="sonnet",
        resume_id=None,
        system_context="context pack",
        input_func=lambda prompt: next(inputs),
        output_func=outputs.append,
    )

    store = AgentSessionStore(openfin_home(tmp_path))
    transcript = store.load_transcript(meta.id)
    loaded = store.load_meta(meta.id)

    assert adapter.prompts == ["first turn", "second turn"]
    assert adapter.resume_ids == [None, "native-1"]
    assert adapter.system_contexts == ["context pack", "context pack"]
    assert adapter.interrupted is True
    assert [event.kind for event in transcript] == [
        "assistant_text",
        "turn_done",
        "assistant_text",
        "turn_done",
    ]
    assert loaded.native_session_id == "native-1"
    assert loaded.status == "exited"
    assert f"#agent {meta.id} claude ended" in log_text(tmp_path)
    assert any("status: idle" in output for output in outputs)
    assert any("answer: first turn" in output for output in outputs)


def test_console_entrypoint_run_option_forwards_extra_args(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(args: list[str]) -> None:
        calls.append(args)

    monkeypatch.setattr("openfin.cli.run_agent_from_cli", fake_run)

    main_entry(["--run", "claude", "--model", "sonnet", "hello"])

    assert calls == [["claude", "--model", "sonnet", "hello"]]
