from __future__ import annotations

import urllib.error

import pytest

from openfin import delivery


def test_delivery_router_calls_requested_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    monkeypatch.setattr(
        delivery,
        "send_desktop_notification",
        lambda title, message: calls.append(("desktop", title)),
    )
    monkeypatch.setattr(
        delivery,
        "send_telegram_message",
        lambda message: calls.append(("telegram", message)),
    )

    sent = delivery.deliver_digest(title="Digest", message="Hello", target="both")

    assert sent == ["desktop", "telegram"]
    assert calls == [("desktop", "Digest"), ("telegram", "Hello")]
    with pytest.raises(delivery.DeliveryError, match="unknown delivery target"):
        delivery.deliver_digest(title="Digest", message="Hello", target="sms")


def test_desktop_delivery_linux_and_darwin(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[list[str]] = []

    monkeypatch.setattr(delivery.platform, "system", lambda: "Linux")
    monkeypatch.setattr(delivery.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(
        delivery.subprocess,
        "run",
        lambda command, check: calls.append(command),
    )

    delivery.send_desktop_notification("Title", "Body")

    assert calls[-1] == ["/bin/notify-send", "Title", "Body"]

    monkeypatch.setattr(delivery.platform, "system", lambda: "Darwin")
    delivery.send_desktop_notification("Title", 'Body "quoted"')

    assert calls[-1][0:2] == ["/bin/osascript", "-e"]
    assert "display notification" in calls[-1][2]
    assert "quoted" in calls[-1][2]


def test_desktop_delivery_reports_missing_or_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(delivery.platform, "system", lambda: "Linux")
    monkeypatch.setattr(delivery.shutil, "which", lambda name: None)

    with pytest.raises(delivery.DeliveryError, match="notify-send"):
        delivery.send_desktop_notification("Title", "Body")

    monkeypatch.setattr(delivery.platform, "system", lambda: "Windows")

    with pytest.raises(delivery.DeliveryError, match="not supported"):
        delivery.send_desktop_notification("Title", "Body")


class FakeTelegramResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def __enter__(self) -> "FakeTelegramResponse":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


def test_telegram_delivery_success_and_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[str, bytes, str]] = []

    def fake_urlopen(request, timeout):
        opened.append((request.full_url, request.data, request.get_method()))
        return FakeTelegramResponse()

    monkeypatch.setenv("OPENFIN_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("OPENFIN_TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(delivery.urllib.request, "urlopen", fake_urlopen)

    delivery.send_telegram_message("Hello world")

    assert opened[0][0] == "https://api.telegram.org/bottoken/sendMessage"
    assert b"chat_id=chat" in opened[0][1]
    assert b"text=Hello+world" in opened[0][1]
    assert opened[0][2] == "POST"

    monkeypatch.delenv("OPENFIN_TELEGRAM_BOT_TOKEN")
    with pytest.raises(delivery.DeliveryError, match="OPENFIN_TELEGRAM_BOT_TOKEN"):
        delivery.send_telegram_message("Hello")

    monkeypatch.setenv("OPENFIN_TELEGRAM_BOT_TOKEN", "token")

    def failing_urlopen(request, timeout):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(delivery.urllib.request, "urlopen", failing_urlopen)
    with pytest.raises(delivery.DeliveryError, match="offline"):
        delivery.send_telegram_message("Hello")
