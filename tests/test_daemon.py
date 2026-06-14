from __future__ import annotations

from collections import Counter, deque
import stat
import threading
import uuid
from pathlib import Path

from typer.testing import CliRunner

from openfin.agent_store import AgentEvent, AgentSessionMeta, AgentSessionStore, Project
from openfin.daemon import (
    DaemonClient,
    OpenFindDaemon,
    connect_daemon,
    create_daemon_server,
    daemon_app,
    drain_deque,
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


def test_daemon_rejects_input_for_exited_session(tmp_path: Path) -> None:
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
    daemon.handle({"type": "unregister_session", "session_id": meta.id})

    response = daemon.handle(
        {
            "type": "send_input",
            "session_id": meta.id,
            "text": "anyone home?",
            "source": "telegram",
        }
    )

    assert response == {"ok": False, "error": "session is exited"}


def test_drain_deque_loses_nothing_under_concurrent_append() -> None:
    inbox: deque[dict[str, str]] = deque()
    collected: list[dict[str, str]] = []
    done = threading.Event()
    total = 20_000

    def produce() -> None:
        for index in range(total):
            inbox.append({"type": "message", "text": str(index), "source": "test"})
        done.set()

    def consume() -> None:
        while not done.is_set() or inbox:
            collected.extend(drain_deque(inbox))

    producer = threading.Thread(target=produce)
    consumer = threading.Thread(target=consume)
    producer.start()
    consumer.start()
    producer.join(timeout=5)
    consumer.join(timeout=5)
    collected.extend(drain_deque(inbox))

    assert len(collected) == total
    assert Counter(item["text"] for item in collected) == Counter(
        str(index) for index in range(total)
    )


def test_daemon_input_queue_survives_concurrent_send_and_poll(tmp_path: Path) -> None:
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
    collected: list[dict[str, str]] = []
    done = threading.Event()
    total = 2_000

    def produce() -> None:
        for index in range(total):
            response = daemon.handle(
                {
                    "type": "send_input",
                    "session_id": meta.id,
                    "text": str(index),
                    "source": "telegram",
                }
            )
            assert response.get("ok") is True
        done.set()

    def consume() -> None:
        while not done.is_set():
            response = daemon.handle({"type": "poll_input", "session_id": meta.id})
            assert response.get("ok") is True
            collected.extend(response["items"])
        response = daemon.handle({"type": "poll_input", "session_id": meta.id})
        collected.extend(response["items"])

    producer = threading.Thread(target=produce)
    consumer = threading.Thread(target=consume)
    producer.start()
    consumer.start()
    producer.join(timeout=5)
    consumer.join(timeout=5)

    assert len(collected) == total
    assert Counter(item["text"] for item in collected) == Counter(
        str(index) for index in range(total)
    )


def test_daemon_summaries_survive_concurrent_session_mutation(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    daemon = OpenFindDaemon(store)
    errors: list[BaseException] = []
    done = threading.Event()

    def mutate() -> None:
        try:
            for index in range(200):
                meta = AgentSessionMeta.new(
                    session_id=f"agent-{index:03d}",
                    adapter="claude",
                    project=Project(name="OpenFin", root=tmp_path),
                )
                daemon.handle({"type": "register_session", "session": meta.to_dict()})
                daemon.handle({"type": "unregister_session", "session_id": meta.id})
        except BaseException as exc:
            errors.append(exc)
        finally:
            done.set()

    def summarize() -> None:
        try:
            while not done.is_set():
                daemon.handle({"type": "list_sessions"})
        except BaseException as exc:
            errors.append(exc)

    mutator = threading.Thread(target=mutate)
    summarizer = threading.Thread(target=summarize)
    mutator.start()
    summarizer.start()
    mutator.join(timeout=5)
    summarizer.join(timeout=5)

    assert errors == []


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


def test_daemon_socket_is_private(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    socket_path = store.socket_path
    server = create_daemon_server(OpenFindDaemon(store), socket_path)

    try:
        parent_mode = stat.S_IMODE(socket_path.parent.stat().st_mode)
        socket_mode = stat.S_IMODE(socket_path.stat().st_mode)
    finally:
        server.server_close()

    assert parent_mode == 0o700
    assert socket_mode == 0o600


def test_daemon_rejects_socket_in_shared_tmp() -> None:
    socket_path = Path("/tmp") / f"openfind-{uuid.uuid4().hex}.sock"

    try:
        prepare_socket_path(socket_path)
    except Exception as exc:
        assert "private directory" in str(exc)
    else:
        raise AssertionError("expected shared /tmp socket path to be rejected")
    finally:
        if socket_path.exists():
            socket_path.unlink()


def test_daemon_client_wraps_session_protocol(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    meta = store.create_session(
        AgentSessionMeta.new(
            session_id="agent-001",
            adapter="claude",
            project=Project(name="OpenFin", root=tmp_path),
        )
    )
    server = create_daemon_server(OpenFindDaemon(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    client = DaemonClient(store.socket_path)

    try:
        client.ping()
        client.register_session(meta, pid=123)
        client.update_status(meta.id, "busy")
        client.send_input(meta.id, "from telegram", source="telegram")
        queued = client.poll_input(meta.id)
        status = client.status(meta.id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert queued == [
        {
            "type": "message",
            "text": "from telegram",
            "source": "telegram",
        }
    ]
    assert status["status"] == "busy"
    assert status["pid"] == 123


def test_connect_daemon_can_autostart_with_injected_starter(tmp_path: Path) -> None:
    store = AgentSessionStore(tmp_path / "openfin")
    servers: list[tuple[object, threading.Thread]] = []

    def fake_starter(agent_store: AgentSessionStore) -> None:
        server = create_daemon_server(OpenFindDaemon(agent_store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        servers.append((server, thread))

    try:
        client = connect_daemon(store, starter=fake_starter)
        response = client.ping() if client else {}
    finally:
        for server, thread in servers:
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
