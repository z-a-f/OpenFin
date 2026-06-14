from __future__ import annotations

from pathlib import Path

from openfin.agent_store import (
    AgentEvent,
    AgentSessionMeta,
    AgentSessionStore,
    Project,
    discover_project,
)
from openfin.storage import read_text, write_text_atomic


def test_agent_event_json_round_trip() -> None:
    event = AgentEvent(
        kind="assistant_text",
        text="hello",
        raw={"type": "assistant", "message": {"content": "hello"}},
        ts="2026-06-14T12:00:00Z",
        session_id="native-1",
    )

    loaded = AgentEvent.from_json(event.to_json())

    assert loaded == event


def test_session_store_writes_meta_and_transcript(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    project = Project(name="OpenFin", root=tmp_path, profile="code")
    meta = AgentSessionMeta(
        id="agent-001",
        adapter="claude",
        project_name=project.name,
        project_root=str(project.root),
        status="idle",
        started_at="2026-06-14T12:00:00Z",
        updated_at="2026-06-14T12:00:00Z",
        native_session_id=None,
        transcript_path="",
        telegram_thread_id=None,
    )

    saved = store.create_session(meta)
    store.append_event(
        saved.id,
        AgentEvent(
            kind="assistant_text",
            text="first",
            raw={"n": 1},
            ts="2026-06-14T12:00:01Z",
            session_id="native-1",
        ),
    )
    store.append_event(
        saved.id,
        AgentEvent(
            kind="turn_done",
            text="done",
            raw={"n": 2},
            ts="2026-06-14T12:00:02Z",
            session_id="native-1",
        ),
    )
    store.update_meta(saved.id, status="exited", native_session_id="native-1")

    loaded = store.load_meta(saved.id)
    transcript = store.load_transcript(saved.id)

    assert loaded.status == "exited"
    assert loaded.native_session_id == "native-1"
    assert loaded.transcript_path.endswith("agents/agent-001/transcript.jsonl")
    assert [event.text for event in transcript] == ["first", "done"]
    assert read_text(store.session_dir(saved.id) / "transcript.jsonl").count("\n") == 2


def test_session_store_lists_saved_sessions(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    first = AgentSessionMeta.new(
        session_id="agent-001",
        adapter="claude",
        project=Project(name="One", root=tmp_path / "one"),
    )
    second = AgentSessionMeta.new(
        session_id="agent-002",
        adapter="claude",
        project=Project(name="Two", root=tmp_path / "two"),
    )

    store.create_session(second)
    store.create_session(first)

    assert [meta.id for meta in store.list_sessions()] == ["agent-001", "agent-002"]


def test_discover_project_uses_nearest_openfinrc(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)
    write_text_atomic(
        root / ".openfinrc",
        "name: Shark Lab\nprofile: code\n",
    )

    project = discover_project(nested)

    assert project.name == "Shark Lab"
    assert project.profile == "code"
    assert project.root == root


def test_discover_project_falls_back_to_cwd(tmp_path: Path) -> None:
    project = discover_project(tmp_path)

    assert project.name == tmp_path.name
    assert project.profile == "default"
    assert project.root == tmp_path
