from __future__ import annotations

import json
import os
import socket
import socketserver
import subprocess
import sys
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from openfin.agent_store import AgentEvent, AgentSessionMeta, AgentSessionStore
from openfin.storage import ENCODING, OpenFinStore
from openfin.ui import console


PROTOCOL_VERSION = 1
daemon_app = typer.Typer(
    help="Run the OpenFin agent daemon.",
    invoke_without_command=True,
)


class DaemonError(RuntimeError):
    """Base error for openfind protocol failures."""


class DaemonAlreadyRunning(DaemonError):
    """Raised when an active daemon already owns the Unix socket."""


@dataclass
class DaemonSession:
    id: str
    adapter: str
    project_name: str
    status: str
    native_session_id: str | None = None
    pid: int | None = None
    last_event_kind: str | None = None
    last_event_text: str = ""

    @classmethod
    def from_meta(
        cls,
        meta: AgentSessionMeta,
        *,
        pid: int | None = None,
    ) -> "DaemonSession":
        return cls(
            id=meta.id,
            adapter=meta.adapter,
            project_name=meta.project_name,
            status=meta.status,
            native_session_id=meta.native_session_id,
            pid=pid,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "adapter": self.adapter,
            "project_name": self.project_name,
            "status": self.status,
            "native_session_id": self.native_session_id,
            "pid": self.pid,
            "last_event_kind": self.last_event_kind,
            "last_event_text": self.last_event_text,
        }


class OpenFindDaemon:
    def __init__(self, store: AgentSessionStore) -> None:
        self.store = store
        self._sessions: dict[str, DaemonSession] = {}
        self._inboxes: dict[str, deque[dict[str, str]]] = {}

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        request_type = str(request.get("type") or "")
        if request_type == "ping":
            return {"ok": True, "version": PROTOCOL_VERSION}
        if request_type == "register_session":
            return self._register_session(request)
        if request_type == "list_sessions":
            return {"ok": True, "sessions": self._session_summaries()}
        if request_type == "status":
            session = self._lookup_session(str(request.get("session_id") or ""))
            if session is None:
                return self._error("unknown session")
            return {"ok": True, "session": session.to_dict()}
        if request_type == "update_status":
            return self._update_status(request)
        if request_type == "session_event":
            return self._record_event(request)
        if request_type == "send_input":
            return self._queue_message(request)
        if request_type == "interrupt":
            return self._queue_control(request, item_type="interrupt")
        if request_type == "stop":
            return self._queue_control(request, item_type="stop")
        if request_type == "poll_input":
            return self._poll_input(request)
        if request_type == "unregister_session":
            return self._unregister_session(request)
        return self._error(f"unknown request type: {request_type or '<missing>'}")

    def _register_session(self, request: dict[str, Any]) -> dict[str, Any]:
        raw_session = request.get("session")
        if not isinstance(raw_session, dict):
            return self._error("register_session requires a session object")
        meta = AgentSessionMeta.from_dict(raw_session)
        pid = request.get("pid")
        session = DaemonSession.from_meta(
            meta,
            pid=int(pid) if isinstance(pid, int) else None,
        )
        self._sessions[meta.id] = session
        self._inboxes.setdefault(meta.id, deque())
        if not self.store.meta_path(meta.id).exists():
            self.store.create_session(meta)
        return {"ok": True, "session_id": meta.id}

    def _update_status(self, request: dict[str, Any]) -> dict[str, Any]:
        session = self._lookup_session(str(request.get("session_id") or ""))
        if session is None:
            return self._error("unknown session")
        status = str(request.get("status") or "")
        if not status:
            return self._error("update_status requires a status")
        session.status = status
        self._save_meta_if_present(session.id, status=status)
        return {"ok": True}

    def _record_event(self, request: dict[str, Any]) -> dict[str, Any]:
        session = self._lookup_session(str(request.get("session_id") or ""))
        if session is None:
            return self._error("unknown session")
        raw_event = request.get("event")
        if not isinstance(raw_event, dict):
            return self._error("session_event requires an event object")
        event = AgentEvent.from_dict(raw_event)
        session.last_event_kind = event.kind
        session.last_event_text = event.text
        if event.session_id:
            session.native_session_id = event.session_id
            self._save_meta_if_present(session.id, native_session_id=event.session_id)
        return {"ok": True}

    def _queue_message(self, request: dict[str, Any]) -> dict[str, Any]:
        session_id = str(request.get("session_id") or "")
        if self._lookup_session(session_id) is None:
            return self._error("unknown session")
        text = str(request.get("text") or "").strip()
        if not text:
            return self._error("send_input requires text")
        source = str(request.get("source") or "local")
        inbox = self._inboxes.setdefault(session_id, deque())
        inbox.append({"type": "message", "text": text, "source": source})
        return {"ok": True, "queued": len(inbox)}

    def _queue_control(
        self,
        request: dict[str, Any],
        *,
        item_type: str,
    ) -> dict[str, Any]:
        session_id = str(request.get("session_id") or "")
        if self._lookup_session(session_id) is None:
            return self._error("unknown session")
        source = str(request.get("source") or "local")
        inbox = self._inboxes.setdefault(session_id, deque())
        inbox.append({"type": item_type, "text": "", "source": source})
        return {"ok": True, "queued": len(inbox)}

    def _poll_input(self, request: dict[str, Any]) -> dict[str, Any]:
        session_id = str(request.get("session_id") or "")
        if self._lookup_session(session_id) is None:
            return self._error("unknown session")
        inbox = self._inboxes.setdefault(session_id, deque())
        items = list(inbox)
        inbox.clear()
        return {"ok": True, "items": items}

    def _unregister_session(self, request: dict[str, Any]) -> dict[str, Any]:
        session_id = str(request.get("session_id") or "")
        session = self._lookup_session(session_id)
        if session is None:
            return self._error("unknown session")
        status = str(request.get("status") or "exited")
        session.status = status
        self._save_meta_if_present(session_id, status=status)
        self._sessions.pop(session_id, None)
        self._inboxes.pop(session_id, None)
        return {"ok": True}

    def _session_summaries(self) -> list[dict[str, Any]]:
        sessions = {
            meta.id: DaemonSession.from_meta(meta).to_dict()
            for meta in self.store.list_sessions()
        }
        sessions.update(
            {
                session_id: session.to_dict()
                for session_id, session in self._sessions.items()
            }
        )
        return [sessions[session_id] for session_id in sorted(sessions)]

    def _lookup_session(self, session_id: str) -> DaemonSession | None:
        if not session_id:
            return None
        live = self._sessions.get(session_id)
        if live is not None:
            return live
        try:
            meta = self.store.load_meta(session_id)
        except FileNotFoundError:
            return None
        session = DaemonSession.from_meta(meta)
        self._sessions[session_id] = session
        self._inboxes.setdefault(session_id, deque())
        return session

    def _save_meta_if_present(self, session_id: str, **updates: Any) -> None:
        try:
            self.store.update_meta(session_id, **updates)
        except FileNotFoundError:
            return

    def _error(self, message: str) -> dict[str, Any]:
        return {"ok": False, "error": message}


class DaemonClient:
    def __init__(self, socket_path: Path, *, timeout: float = 2.0) -> None:
        self.socket_path = socket_path
        self.timeout = timeout

    def request(self, request: dict[str, Any]) -> dict[str, Any]:
        return send_daemon_request(self.socket_path, request, timeout=self.timeout)

    def ping(self) -> dict[str, Any]:
        return self.request({"type": "ping"})

    def register_session(
        self,
        meta: AgentSessionMeta,
        *,
        pid: int | None = None,
    ) -> None:
        request: dict[str, Any] = {
            "type": "register_session",
            "session": meta.to_dict(),
        }
        if pid is not None:
            request["pid"] = pid
        self._expect_ok(self.request(request))

    def status(self, session_id: str) -> dict[str, Any]:
        response = self.request({"type": "status", "session_id": session_id})
        self._expect_ok(response)
        session = response.get("session")
        if not isinstance(session, dict):
            raise DaemonError("openfind returned status without a session object")
        return session

    def list_sessions(self) -> list[dict[str, Any]]:
        response = self.request({"type": "list_sessions"})
        self._expect_ok(response)
        sessions = response.get("sessions")
        if not isinstance(sessions, list):
            raise DaemonError("openfind returned list without sessions")
        return sessions

    def update_status(self, session_id: str, status: str) -> None:
        self._expect_ok(
            self.request(
                {
                    "type": "update_status",
                    "session_id": session_id,
                    "status": status,
                }
            )
        )

    def record_event(self, session_id: str, event: AgentEvent) -> None:
        self._expect_ok(
            self.request(
                {
                    "type": "session_event",
                    "session_id": session_id,
                    "event": event.to_dict(),
                }
            )
        )

    def send_input(
        self,
        session_id: str,
        text: str,
        *,
        source: str = "local",
    ) -> int:
        response = self.request(
            {
                "type": "send_input",
                "session_id": session_id,
                "text": text,
                "source": source,
            }
        )
        self._expect_ok(response)
        return int(response.get("queued") or 0)

    def interrupt(self, session_id: str, *, source: str = "local") -> None:
        self._expect_ok(
            self.request(
                {
                    "type": "interrupt",
                    "session_id": session_id,
                    "source": source,
                }
            )
        )

    def stop(self, session_id: str, *, source: str = "local") -> None:
        self._expect_ok(
            self.request(
                {
                    "type": "stop",
                    "session_id": session_id,
                    "source": source,
                }
            )
        )

    def poll_input(self, session_id: str) -> list[dict[str, str]]:
        response = self.request({"type": "poll_input", "session_id": session_id})
        self._expect_ok(response)
        items = response.get("items")
        if not isinstance(items, list):
            raise DaemonError("openfind returned poll response without items")
        return [item for item in items if isinstance(item, dict)]

    def unregister_session(self, session_id: str, *, status: str = "exited") -> None:
        self._expect_ok(
            self.request(
                {
                    "type": "unregister_session",
                    "session_id": session_id,
                    "status": status,
                }
            )
        )

    def _expect_ok(self, response: dict[str, Any]) -> None:
        if response.get("ok") is True:
            return
        raise DaemonError(str(response.get("error") or "openfind request failed"))


DaemonStarter = Callable[[AgentSessionStore], object]


def connect_daemon(
    store: AgentSessionStore,
    *,
    autostart: bool = True,
    starter: DaemonStarter | None = None,
    timeout: float = 2.0,
) -> DaemonClient | None:
    client = wait_for_daemon_client(store.socket_path, timeout=0.1)
    if client is not None:
        return client
    if not autostart:
        return None
    (starter or start_openfind_process)(store)
    return wait_for_daemon_client(store.socket_path, timeout=timeout)


def wait_for_daemon_client(socket_path: Path, *, timeout: float) -> DaemonClient | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() <= deadline:
        client = DaemonClient(socket_path, timeout=0.2)
        try:
            client.ping()
            return client
        except (OSError, DaemonError, json.JSONDecodeError, TimeoutError):
            time.sleep(0.05)
    return None


def start_openfind_process(store: AgentSessionStore) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    env["OPENFIN_HOME"] = str(store.root)
    return subprocess.Popen(
        [sys.executable, "-m", "openfin.daemon"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class _DaemonUnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: str,
        RequestHandlerClass: type[socketserver.BaseRequestHandler],
        *,
        daemon: OpenFindDaemon,
        socket_path: Path,
    ) -> None:
        self.daemon = daemon
        self.socket_path = socket_path
        super().__init__(server_address, RequestHandlerClass)

    def server_close(self) -> None:
        super().server_close()
        if self.socket_path.exists():
            self.socket_path.unlink()


class _DaemonRequestHandler(socketserver.StreamRequestHandler):
    server: _DaemonUnixServer

    def handle(self) -> None:
        for raw_line in self.rfile:
            try:
                request = json.loads(raw_line.decode(ENCODING))
                if not isinstance(request, dict):
                    response = {"ok": False, "error": "request must be a JSON object"}
                else:
                    response = self.server.daemon.handle(request)
            except Exception as exc:  # pragma: no cover - last-ditch protocol guard
                response = {"ok": False, "error": str(exc)}
            self.wfile.write(_encode_response(response))


def create_daemon_server(
    daemon: OpenFindDaemon,
    socket_path: Path | None = None,
) -> socketserver.BaseServer:
    path = socket_path or daemon.store.socket_path
    prepare_socket_path(path)
    return _DaemonUnixServer(
        str(path),
        _DaemonRequestHandler,
        daemon=daemon,
        socket_path=path,
    )


def prepare_socket_path(socket_path: Path) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if not socket_path.exists():
        return
    if socket_path.is_socket() and socket_is_alive(socket_path):
        raise DaemonAlreadyRunning(f"openfind is already listening at {socket_path}")
    socket_path.unlink()


def socket_is_alive(socket_path: Path, *, timeout: float = 0.2) -> bool:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        try:
            client.connect(str(socket_path))
        except OSError:
            return False
    return True


def send_daemon_request(
    socket_path: Path,
    request: dict[str, Any],
    *,
    timeout: float = 2.0,
) -> dict[str, Any]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout)
        client.connect(str(socket_path))
        client.sendall(_encode_request(request))
        with client.makefile("rb") as response_file:
            line = response_file.readline()
    if not line:
        raise DaemonError("openfind closed the connection without a response")
    response = json.loads(line.decode(ENCODING))
    if not isinstance(response, dict):
        raise DaemonError("openfind returned a non-object response")
    return response


def _encode_request(request: dict[str, Any]) -> bytes:
    return f"{json.dumps(request, ensure_ascii=False, sort_keys=True)}\n".encode(
        ENCODING
    )


def _encode_response(response: dict[str, Any]) -> bytes:
    return f"{json.dumps(response, ensure_ascii=False, sort_keys=True)}\n".encode(
        ENCODING
    )


def serve_daemon(socket_path: Path | None = None) -> None:
    store = AgentSessionStore(OpenFinStore.from_env().root)
    daemon = OpenFindDaemon(store)
    server = create_daemon_server(daemon, socket_path)
    listening_path = socket_path or store.socket_path
    console.print(f"openfind listening on {listening_path}", markup=False)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


@daemon_app.callback(invoke_without_command=True)
def daemon_main(
    socket_path: Path | None = typer.Option(
        None,
        "--socket",
        help="Override the Unix socket path.",
    ),
) -> None:
    serve_daemon(socket_path)


def main() -> None:
    daemon_app()


if __name__ == "__main__":
    main()
