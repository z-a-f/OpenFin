from __future__ import annotations

from pathlib import Path
from datetime import date, timedelta

import pytest

from openfin import digest as digest_module
from openfin.cli import app
from openfin.digest import render_digest
from openfin.storage import OpenFinStore, write_text_atomic
from tests.helpers import openfin_home, run_cli, runner


def test_evening_digest_only_shows_closed_today(tmp_path: Path) -> None:
    init = run_cli(tmp_path, ["init"])
    assert init.exit_code == 0, init.output

    today = date.today()
    yesterday = today - timedelta(days=1)
    log_path = openfin_home(tmp_path) / "log" / f"{today:%Y-%m}.md"
    write_text_atomic(
        log_path,
        f"## {yesterday.isoformat()}\n\n"
        "- 18:00 #done t-0001 Done yesterday\n\n"
        f"## {today.isoformat()}\n\n"
        "- 18:00 #done t-0002 Done today\n",
    )

    digest = run_cli(tmp_path, ["digest", "evening"])

    assert digest.exit_code == 0, digest.output
    assert "Done today" in digest.output
    assert "Done yesterday" not in digest.output


def test_digest_renderer_is_shared_plain_text(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Digest task", "-d", date.today().isoformat()])
    assert created.exit_code == 0, created.output

    store = OpenFinStore(openfin_home(tmp_path))
    rendered = render_digest(store, "morning")
    cli_digest = run_cli(tmp_path, ["digest", "morning"])

    assert cli_digest.exit_code == 0, cli_digest.output
    assert "MORNING DIGEST" in rendered
    assert "Digest task" in rendered
    assert rendered in cli_digest.output


def test_digest_telegram_delivery_requires_credentials(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        ["digest", "morning", "--send", "telegram"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
    )

    assert result.exit_code == 1, result.output
    assert "OPENFIN_TELEGRAM_BOT_TOKEN" in result.output
    assert "OPENFIN_TELEGRAM_CHAT_ID" in result.output


def test_digest_delivery_success_and_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered: list[tuple[str, str]] = []

    monkeypatch.setattr(
        digest_module,
        "deliver_digest",
        lambda *, title, message, target: delivered.append((title, target)) or [target],
    )

    sent = run_cli(tmp_path, ["digest", "morning", "--send", "desktop"])
    bad_kind = run_cli(tmp_path, ["digest", "midday"])
    bad_target = run_cli(tmp_path, ["digest", "morning", "--send", "email"])

    assert sent.exit_code == 0, sent.output
    assert "Sent digest via desktop." in sent.output
    assert delivered == [("OpenFin morning digest", "desktop")]
    assert bad_kind.exit_code != 0
    assert "digest kind must be morning or evening" in bad_kind.output
    assert bad_target.exit_code != 0
    assert (
        "delivery target must be none, desktop, telegram, or both" in bad_target.output
    )
