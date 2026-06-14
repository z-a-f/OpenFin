from __future__ import annotations

from pathlib import Path
from datetime import date, timedelta

import yaml

from openfin.cli import app
from openfin.storage import dump_yaml, read_text, write_text_atomic
from tests.helpers import load_tasks, log_text, openfin_home, run_cli, runner


def test_future_recheck_quiets_overdue_review_and_today(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    created = run_cli(tmp_path, ["add", "Committed follow-up", "-d", yesterday])
    assert created.exit_code == 0, created.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(read_text(task_path))
    tasks[0]["recheck"] = tomorrow
    write_text_atomic(task_path, dump_yaml(tasks))

    overdue = run_cli(tmp_path, ["overdue"])
    today = run_cli(tmp_path, ["today"])
    review = run_cli(tmp_path, ["review"])

    assert overdue.exit_code == 0, overdue.output
    assert today.exit_code == 0, today.output
    assert review.exit_code == 0, review.output
    assert "Committed follow-up" not in overdue.output
    assert "Run `f review`" not in today.output
    assert "No overdue or recheck items." in review.output


def test_review_commit_writes_recheck_and_quiets_next_run(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    expected_recheck = (date.today() + timedelta(days=3)).isoformat()

    created = run_cli(tmp_path, ["add", "Commit round trip", "-d", yesterday])
    assert created.exit_code == 0, created.output

    reviewed = runner.invoke(
        app,
        ["review"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="commit\n3\n",
    )
    assert reviewed.exit_code == 0, reviewed.output

    tasks = load_tasks(tmp_path)
    assert tasks[0]["recheck"] == expected_recheck
    log_text = "\n".join(
        read_text(path) for path in (openfin_home(tmp_path) / "log").glob("*.md")
    )
    assert f"#commit t-0001 recheck {expected_recheck}" in log_text

    followup_review = run_cli(tmp_path, ["review"])
    today = run_cli(tmp_path, ["today"])
    overdue = run_cli(tmp_path, ["overdue"])

    assert "No overdue or recheck items." in followup_review.output
    assert "Run `f review`" not in today.output
    assert "Commit round trip" not in overdue.output


def test_review_recheck_reports_no_progress_since_commit(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    created = run_cli(tmp_path, ["add", "Check committed task", "-d", yesterday])
    assert created.exit_code == 0, created.output

    committed = runner.invoke(
        app,
        ["review"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="commit\n0\n",
    )
    assert committed.exit_code == 0, committed.output

    recheck = runner.invoke(
        app,
        ["review"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="skip\n",
    )

    assert recheck.exit_code == 0, recheck.output
    assert "nothing moved since then" in recheck.output


def test_touch_records_progress_for_recheck_loop(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    created = run_cli(tmp_path, ["add", "Touched commitment", "-d", yesterday])
    assert created.exit_code == 0, created.output

    committed = runner.invoke(
        app,
        ["review"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="commit\n0\n",
    )
    assert committed.exit_code == 0, committed.output

    touched = run_cli(tmp_path, ["touch", "t-0001", "--note", "drafted the email"])
    assert touched.exit_code == 0, touched.output

    recheck = runner.invoke(
        app,
        ["review"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="skip\n",
    )

    tasks = load_tasks(tmp_path)
    log_text = "\n".join(
        read_text(path) for path in (openfin_home(tmp_path) / "log").glob("*.md")
    )
    assert "drafted the email" in tasks[0]["notes"]
    assert "#touch t-0001 Touched commitment drafted the email" in log_text
    assert "progress recorded since then" in recheck.output


def test_status_advance_counts_as_recheck_progress(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    created = run_cli(tmp_path, ["add", "Advance commitment", "-d", yesterday])
    assert created.exit_code == 0, created.output

    committed = runner.invoke(
        app,
        ["review"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="commit\n0\n",
    )
    assert committed.exit_code == 0, committed.output

    doing = run_cli(tmp_path, ["do", "t-0001"])
    assert doing.exit_code == 0, doing.output

    recheck = runner.invoke(
        app,
        ["review"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="skip\n",
    )

    assert recheck.exit_code == 0, recheck.output
    assert "progress recorded since then" in recheck.output


def test_review_decision_branches_update_tasks_and_log(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    for title in ["Snooze me", "Block me", "Drop me", "Done me", "Unknown me"]:
        created = run_cli(tmp_path, ["add", title, "-d", yesterday])
        assert created.exit_code == 0, created.output

    reviewed = run_cli(
        tmp_path,
        ["review"],
        input=f"snooze\n{tomorrow}\nblock\nwaiting on Alex\ndrop\ndone\nlater\n",
    )

    assert reviewed.exit_code == 0, reviewed.output
    tasks = load_tasks(tmp_path)
    assert tasks[0]["due"] == tomorrow
    assert tasks[1]["status"] == "blocked"
    assert "waiting on Alex" in tasks[1]["notes"]
    assert tasks[2]["status"] == "dropped"
    assert tasks[3]["status"] == "done"
    assert tasks[4]["status"] == "open"
    assert "Skipped unknown decision: later" in reviewed.output
    text = log_text(tmp_path)
    assert "#dropped t-0003 Drop me" in text
    assert "#done t-0004 Done me" in text


def test_review_commit_rejects_non_integer_recheck_days(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    created = run_cli(tmp_path, ["add", "Bad commit days", "-d", yesterday])
    assert created.exit_code == 0, created.output

    reviewed = run_cli(tmp_path, ["review"], input="commit\nlater\n")

    assert reviewed.exit_code != 0
    assert "recheck days must be an integer" in reviewed.output
