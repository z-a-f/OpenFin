from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from openfin.agent_store import AgentEvent
from openfin.daemon import DaemonSession, OpenFindDaemon


TELEGRAM_CHUNK_LIMIT = 3900
RELAY_EVENT_KINDS = {"assistant_text", "turn_done", "needs_input", "error"}


class TelegramRateLimitError(RuntimeError):
    def __init__(self, *, retry_after: float) -> None:
        super().__init__(f"telegram rate limited; retry after {retry_after:g}s")
        self.retry_after = retry_after


class TelegramClient(Protocol):
    def send_message(self, chat_id: str, text: str) -> None: ...


class TelegramPollingClient(TelegramClient, Protocol):
    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    allowed_user_id: str
    chat_id: str

    @classmethod
    def from_env(cls) -> "TelegramConfig | None":
        token = os.environ.get("OPENFIN_TELEGRAM_BOT_TOKEN")
        allowed_user_id = os.environ.get("OPENFIN_TELEGRAM_ALLOWED_USER_ID")
        chat_id = os.environ.get("OPENFIN_TELEGRAM_CHAT_ID")
        allowed_user_id = allowed_user_id or chat_id
        chat_id = chat_id or allowed_user_id
        if not token or not allowed_user_id or not chat_id:
            return None
        return cls(
            token=token,
            allowed_user_id=str(allowed_user_id),
            chat_id=str(chat_id),
        )


class TelegramApiClient:
    def __init__(self, token: str) -> None:
        self.token = token

    def get_updates(
        self,
        *,
        offset: int | None = None,
        timeout: int = 30,
    ) -> list[dict[str, Any]]:
        data: dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": json.dumps(
                ["message", "edited_message", "callback_query"]
            ),
        }
        if offset is not None:
            data["offset"] = offset
        result = self._api("getUpdates", data)
        return result if isinstance(result, list) else []

    def send_message(self, chat_id: str, text: str) -> None:
        self._api("sendMessage", {"chat_id": chat_id, "text": text})

    def _api(self, method: str, data: dict[str, Any]) -> Any:
        encoded = urllib.parse.urlencode(data).encode("utf-8")
        url = f"https://api.telegram.org/bot{self.token}/{method}"
        request = urllib.request.Request(url, data=encoded, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=35) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            payload = parse_telegram_error(exc)
            retry_after = telegram_retry_after(payload)
            if exc.code == 429 and retry_after is not None:
                raise TelegramRateLimitError(retry_after=retry_after) from exc
            raise RuntimeError("telegram request failed") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"telegram request failed: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("telegram request failed")
        return payload.get("result")


class TelegramBot:
    def __init__(
        self,
        *,
        daemon: OpenFindDaemon,
        client: TelegramClient,
        config: TelegramConfig,
        sleep_func: Any = time.sleep,
    ) -> None:
        self.daemon = daemon
        self.client = client
        self.config = config
        self._sleep = sleep_func

    def handle_update(self, update: dict[str, Any]) -> None:
        if not self._is_authorized_update(update):
            return
        message = self._message_from_update(update)
        if not isinstance(message, dict):
            return
        text = str(message.get("text") or "").strip()
        if not text:
            return
        chat_id = self._chat_id_from_update(update)
        response = self.handle_text(text)
        if response:
            self._send(chat_id, response)

    def handle_text(self, text: str) -> str:
        parts = text.split(maxsplit=2)
        command = parts[0].split("@", maxsplit=1)[0].lower()
        if command == "/sessions":
            return self._format_sessions()
        if command == "/status":
            if len(parts) < 2:
                return "usage: /status <session>"
            return self._format_status(parts[1])
        if command == "/s":
            if len(parts) < 3:
                return "usage: /s <session> <message>"
            return self._send_input(parts[1], parts[2])
        if command == "/interrupt":
            if len(parts) < 2:
                return "usage: /interrupt <session>"
            return self._queue_control("interrupt", parts[1])
        if command == "/stop":
            if len(parts) < 2:
                return "usage: /stop <session>"
            return self._queue_control("stop", parts[1])
        if command == "/help":
            return self._help()
        return self._help()

    def relay_agent_event(self, session: DaemonSession, event: AgentEvent) -> None:
        if event.kind not in RELAY_EVENT_KINDS:
            return
        text = event.text.strip()
        if not text:
            return
        self._send(self.config.chat_id, f"{session.id} {event.kind}:\n{text}")

    def _send_input(self, session_token: str, text: str) -> str:
        session_id = self._resolve_session_id(session_token)
        if session_id is None:
            return f"unknown or ambiguous session: {session_token}"
        response = self.daemon.handle(
            {
                "type": "send_input",
                "session_id": session_id,
                "text": text,
                "source": "telegram",
            }
        )
        if response.get("ok") is not True:
            return str(response.get("error") or "failed to queue input")
        return f"queued for {session_id}"

    def _queue_control(self, command: str, session_token: str) -> str:
        session_id = self._resolve_session_id(session_token)
        if session_id is None:
            return f"unknown or ambiguous session: {session_token}"
        response = self.daemon.handle(
            {
                "type": command,
                "session_id": session_id,
                "source": "telegram",
            }
        )
        if response.get("ok") is not True:
            return str(response.get("error") or f"failed to queue {command}")
        return f"{command} queued for {session_id}"

    def _format_sessions(self) -> str:
        response = self.daemon.handle({"type": "list_sessions"})
        sessions = response.get("sessions") if response.get("ok") is True else []
        if not sessions:
            return "No agent sessions."
        lines = ["OpenFin agent sessions:"]
        for session in sessions:
            lines.append(
                f"- {session['id']} {session['adapter']} {session['status']} {session['project_name']}"
            )
        return "\n".join(lines)

    def _format_status(self, session_token: str) -> str:
        session_id = self._resolve_session_id(session_token)
        if session_id is None:
            return f"unknown or ambiguous session: {session_token}"
        response = self.daemon.handle({"type": "status", "session_id": session_id})
        if response.get("ok") is not True:
            return str(response.get("error") or "status failed")
        session = response["session"]
        lines = [
            str(session["id"]),
            f"adapter: {session['adapter']}",
            f"project: {session['project_name']}",
            f"status: {session['status']}",
        ]
        if session.get("native_session_id"):
            lines.append(f"native: {session['native_session_id']}")
        if session.get("last_event_kind"):
            lines.append(
                f"last: {session['last_event_kind']} {session.get('last_event_text') or ''}".strip()
            )
        return "\n".join(lines)

    def _resolve_session_id(self, token: str) -> str | None:
        response = self.daemon.handle({"type": "list_sessions"})
        sessions = response.get("sessions") if response.get("ok") is True else []
        ids = [str(session["id"]) for session in sessions if isinstance(session, dict)]
        if token in ids:
            return token
        matches = [session_id for session_id in ids if session_id.startswith(token)]
        return matches[0] if len(matches) == 1 else None

    def _is_authorized_update(self, update: dict[str, Any]) -> bool:
        return update_sender_id(update) == self.config.allowed_user_id

    def _message_from_update(self, update: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("message", "edited_message"):
            message = update.get(key)
            if isinstance(message, dict):
                return message
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            data = callback.get("data")
            if isinstance(data, str):
                return {"text": data}
        return None

    def _chat_id_from_update(self, update: dict[str, Any]) -> str:
        chat_id = update_chat_id(update)
        return chat_id or self.config.chat_id

    def _send(self, chat_id: str, text: str) -> None:
        for chunk in chunk_text(text):
            while True:
                try:
                    self.client.send_message(chat_id, chunk)
                    break
                except TelegramRateLimitError as exc:
                    self._sleep(exc.retry_after)

    def _help(self) -> str:
        return "\n".join(
            [
                "OpenFin agent commands:",
                "/sessions",
                "/status <session>",
                "/s <session> <message>",
                "/interrupt <session>",
                "/stop <session>",
            ]
        )


class TelegramBotRunner:
    def __init__(self, bot: TelegramBot, client: TelegramPollingClient) -> None:
        self.bot = bot
        self.client = client
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self.run_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def run_forever(self) -> None:
        offset: int | None = None
        while not self._stop.is_set():
            try:
                updates = self.client.get_updates(offset=offset, timeout=30)
            except Exception:
                time.sleep(5)
                continue
            for update in updates:
                update_id = update.get("update_id")
                if isinstance(update_id, int):
                    offset = update_id + 1
                self.bot.handle_update(update)


def chunk_text(text: str, *, limit: int = TELEGRAM_CHUNK_LIMIT) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def update_sender_id(update: dict[str, Any]) -> str | None:
    for key in ("message", "edited_message"):
        message = update.get(key)
        if isinstance(message, dict):
            sender = message.get("from")
            if isinstance(sender, dict):
                return str(sender.get("id") or "")
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        sender = callback.get("from")
        if isinstance(sender, dict):
            return str(sender.get("id") or "")
    return None


def update_chat_id(update: dict[str, Any]) -> str | None:
    for key in ("message", "edited_message"):
        message = update.get(key)
        if isinstance(message, dict):
            chat = message.get("chat")
            if isinstance(chat, dict):
                return str(chat.get("id") or "")
    callback = update.get("callback_query")
    if isinstance(callback, dict):
        message = callback.get("message")
        if isinstance(message, dict):
            chat = message.get("chat")
            if isinstance(chat, dict):
                return str(chat.get("id") or "")
    return None


def parse_telegram_error(exc: urllib.error.HTTPError) -> dict[str, Any]:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def telegram_retry_after(payload: dict[str, Any]) -> float | None:
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        return None
    retry_after = parameters.get("retry_after")
    if isinstance(retry_after, int | float):
        return float(retry_after)
    return None
