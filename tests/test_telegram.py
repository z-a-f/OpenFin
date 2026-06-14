from __future__ import annotations

from pathlib import Path

from openfin.agent_store import AgentEvent, AgentSessionMeta, AgentSessionStore, Project
from openfin.daemon import OpenFindDaemon
from openfin.telegram import TelegramBot, TelegramConfig, chunk_text


class FakeTelegramClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


def make_update(text: str, *, user_id: int = 42, chat_id: int = 42) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 10,
            "text": text,
            "from": {"id": user_id},
            "chat": {"id": chat_id},
        },
    }


def make_daemon(tmp_path: Path) -> tuple[OpenFindDaemon, AgentSessionMeta]:
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
    return daemon, meta


def test_telegram_sessions_and_send_command_route_to_daemon(tmp_path: Path) -> None:
    daemon, meta = make_daemon(tmp_path)
    client = FakeTelegramClient()
    bot = TelegramBot(
        daemon=daemon,
        client=client,
        config=TelegramConfig(
            token="token",
            allowed_user_id="42",
            chat_id="42",
        ),
    )

    bot.handle_update(make_update("/sessions"))
    bot.handle_update(make_update("/s agent-001 please continue"))
    queued = daemon.handle({"type": "poll_input", "session_id": meta.id})

    assert client.sent[0] == (
        "42",
        "OpenFin agent sessions:\n- agent-001 claude idle OpenFin",
    )
    assert client.sent[1] == ("42", "queued for agent-001")
    assert queued["items"] == [
        {
            "type": "message",
            "text": "please continue",
            "source": "telegram",
        }
    ]


def test_telegram_status_interrupt_and_stop_commands(tmp_path: Path) -> None:
    daemon, meta = make_daemon(tmp_path)
    client = FakeTelegramClient()
    bot = TelegramBot(
        daemon=daemon,
        client=client,
        config=TelegramConfig(
            token="token",
            allowed_user_id="42",
            chat_id="42",
        ),
    )

    bot.handle_update(make_update("/status agent"))
    bot.handle_update(make_update("/interrupt agent"))
    bot.handle_update(make_update("/stop agent"))
    queued = daemon.handle({"type": "poll_input", "session_id": meta.id})

    assert "agent-001" in client.sent[0][1]
    assert "status: idle" in client.sent[0][1]
    assert client.sent[1] == ("42", "interrupt queued for agent-001")
    assert client.sent[2] == ("42", "stop queued for agent-001")
    assert [item["type"] for item in queued["items"]] == ["interrupt", "stop"]


def test_telegram_ignores_unapproved_users(tmp_path: Path) -> None:
    daemon, _meta = make_daemon(tmp_path)
    client = FakeTelegramClient()
    bot = TelegramBot(
        daemon=daemon,
        client=client,
        config=TelegramConfig(
            token="token",
            allowed_user_id="42",
            chat_id="42",
        ),
    )

    bot.handle_update(make_update("/sessions", user_id=999))

    assert client.sent == []


def test_telegram_relay_agent_events_from_daemon(tmp_path: Path) -> None:
    daemon, meta = make_daemon(tmp_path)
    client = FakeTelegramClient()
    bot = TelegramBot(
        daemon=daemon,
        client=client,
        config=TelegramConfig(
            token="token",
            allowed_user_id="42",
            chat_id="42",
        ),
    )
    daemon.add_event_sink(bot.relay_agent_event)

    daemon.handle(
        {
            "type": "session_event",
            "session_id": meta.id,
            "event": AgentEvent(
                kind="assistant_text",
                text="done from agent",
                raw={},
                ts="2026-06-14T12:00:00Z",
                session_id="native-1",
            ).to_dict(),
        }
    )

    assert client.sent == [("42", "agent-001 assistant_text:\ndone from agent")]


def test_telegram_chunks_long_messages() -> None:
    chunks = chunk_text("abcdef", limit=2)

    assert chunks == ["ab", "cd", "ef"]
