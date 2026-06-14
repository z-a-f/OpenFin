from __future__ import annotations

import threading
from pathlib import Path

from typer.testing import CliRunner

from openfin.agent_store import AgentEvent, AgentSessionMeta, AgentSessionStore, Project
from openfin.daemon import (
    OpenFindDaemon,
    create_daemon_server,
    daemon_app,
    prepare_socket_path,
    send_daemon_request,
)


def test_daemon_registers_and_lists_sessions(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    meta = store.create_session(
        AgentSessionMeta.new(
            session_id="agent-001",
            adapter="claude",
            project=Project(name="OpenFin", root=tmp_path),
        )
    )
    daemon = OpenFindDaemon(store)

    registered = daemon.handle(
        {
            "type": "register_session",
            "session": meta.to_dict(),
            "pid": 123,
        }
    )
    listed = daemon.handle({"type": "list_sessions"})

    assert registered == {"ok": True, "session_id": "agent-001"}
    assert listed["ok"] is True
    assert listed["sessions"] == [
        {
            "id": "agent-001",
            "adapter": "claude",
            "project_name": "OpenFin",
            "status": "idle",
            "native_session_id": None,
            "pid": 123,
            "last_event_kind": None,
            "last_event_text": "",
        }
    ]


def test_daemon_events_and_inbound_queue_are_round_trippable(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    meta = store.create_session(
        AgentSessionMeta.new(
            session_id="agent-001",
            adapter="claude",
            project=Project(name="OpenFin", root=tmp_path),
        )
    )
    daemon = OpenFindDaemon(store)
    daemon.handle({"type": "register_session", "session": meta.to_dict()})
    event = AgentEvent(
        kind="turn_done",
        text="ready for next thing",
        raw={},
        ts="2026-06-14T12:00:00Z",
        session_id="native-1",
    )

    event_response = daemon.handle(
        {
            "type": "session_event",
            "session_id": "agent-001",
            "event": event.to_dict(),
        }
    )
    send_response = daemon.handle(
        {
            "type": "send_input",
            "session_id": "agent-001",
            "text": "please continue",
            "source": "telegram",
        }
    )
    first_poll = daemon.handle({"type": "poll_input", "session_id": "agent-001"})
    second_poll = daemon.handle({"type": "poll_input", "session_id": "agent-001"})
    status = daemon.handle({"type": "status", "session_id": "agent-001"})

    assert event_response == {"ok": True}
    assert send_response == {"ok": True, "queued": 1}
    assert first_poll["items"] == [
        {
            "type": "message",
            "text": "please continue",
            "source": "telegram",
        }
    ]
    assert second_poll["items"] == []
    assert status["session"]["native_session_id"] == "native-1"
    assert status["session"]["last_event_kind"] == "turn_done"
    assert status["session"]["last_event_text"] == "ready for next thing"


def test_daemon_unix_socket_request_response(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    socket_path = store.socket_path
    server = create_daemon_server(OpenFindDaemon(store), socket_path)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        response = send_daemon_request(socket_path, {"type": "ping"})
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response == {"ok": True, "version": 1}


def test_prepare_socket_path_removes_stale_socket_file(tmp_path: Path) -> None:
    socket_path = tmp_path / "openfin" / "agents" / "openfind.sock"
    socket_path.parent.mkdir(parents=True)
    socket_path.write_text("stale", encoding="utf-8")

    prepare_socket_path(socket_path)

    assert not socket_path.exists()


def test_openfind_help_is_available() -> None:
    result = CliRunner().invoke(daemon_app, ["--help"])

    assert result.exit_code == 0
    assert "Run the OpenFin agent daemon" in result.output
    assert "--socket" in result.output
