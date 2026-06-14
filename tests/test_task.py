from __future__ import annotations

from pathlib import Path
import os
from datetime import date, timedelta

from openfin.cli import app
from openfin.storage import read_text, write_text_atomic
from tests.helpers import load_tasks, log_text, openfin_home, run_cli, runner


def test_task_lifecycle_and_today_view(tmp_path: Path) -> None:
    due_today = date.today().isoformat()

    result = run_cli(
        tmp_path,
        ["add", "Ship Phase 1", "-p", "P1", "-d", due_today, "-t", "code,admin"],
    )

    assert result.exit_code == 0, result.output
    assert "t-0001" in result.output

    tasks = load_tasks(tmp_path)
    assert tasks[0]["title"] == "Ship Phase 1"
    assert tasks[0]["priority"] == "P1"
    assert tasks[0]["due"] == due_today
    assert tasks[0]["tags"] == ["code", "admin"]

    today = run_cli(tmp_path, ["today"])

    assert today.exit_code == 0, today.output
    assert "TODAY" in today.output
    assert "Ship Phase 1" in today.output

    done = run_cli(tmp_path, ["done", "t-0001"])

    assert done.exit_code == 0, done.output
    tasks = load_tasks(tmp_path)
    assert tasks[0]["status"] == "done"
    log_text = read_text(next((openfin_home(tmp_path) / "log").glob("*.md")))
    assert "#done t-0001 Ship Phase 1" in log_text


def test_assign_updates_owner_filters_and_logs(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Share investor follow-up"])
    assert created.exit_code == 0, created.output

    assigned = run_cli(
        tmp_path,
        ["assign", "t-0001", "alex", "--note", "take point this week"],
    )
    alex_tasks = run_cli(tmp_path, ["ls", "--owner", "alex"])
    my_tasks = run_cli(tmp_path, ["ls", "--owner", "me"])

    assert assigned.exit_code == 0, assigned.output
    assert alex_tasks.exit_code == 0, alex_tasks.output
    assert my_tasks.exit_code == 0, my_tasks.output

    tasks = load_tasks(tmp_path)
    log_text = "\n".join(
        read_text(path) for path in (openfin_home(tmp_path) / "log").glob("*.md")
    )
    assert tasks[0]["owner"] == "alex"
    assert "take point this week" in tasks[0]["notes"]
    assert "Share investor follow-up" in alex_tasks.output
    assert "Share investor follow-up" not in my_tasks.output
    assert (
        "#assign t-0001 alex Share investor follow-up take point this week" in log_text
    )


def test_overdue_view_flags_old_tasks(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    created = run_cli(
        tmp_path, ["add", "Follow up on pilot", "-d", yesterday, "-p", "P0"]
    )

    assert created.exit_code == 0, created.output

    overdue = run_cli(tmp_path, ["overdue"])

    assert overdue.exit_code == 0, overdue.output
    assert "OVERDUE" in overdue.output
    assert "Follow up on pilot" in overdue.output
    assert "t-0001" in overdue.output


def test_task_edit_filters_block_drop_and_validation(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Edit me", "-t", "ops"])
    assert created.exit_code == 0, created.output

    edited = run_cli(
        tmp_path,
        [
            "edit",
            "t-0001",
            "--title",
            "Edited task",
            "-p",
            "P0",
            "-d",
            "tomorrow",
            "--status",
            "doing",
            "-t",
            "eng,ops",
            "--notes",
            "details",
        ],
    )
    listed = run_cli(tmp_path, ["ls", "--status", "doing", "--tag", "eng", "-p", "P0"])
    blocked = run_cli(tmp_path, ["block", "t-0001", "needs input"])
    dropped = run_cli(tmp_path, ["drop", "t-0001"])
    invalid_priority = run_cli(tmp_path, ["add", "Bad priority", "-p", "P9"])
    invalid_status = run_cli(tmp_path, ["ls", "--status", "sleeping"])
    missing = run_cli(tmp_path, ["done", "t-9999"])

    assert edited.exit_code == 0, edited.output
    assert listed.exit_code == 0, listed.output
    assert "Edited task" in listed.output
    assert blocked.exit_code == 0, blocked.output
    assert dropped.exit_code == 0, dropped.output
    assert invalid_priority.exit_code != 0
    assert invalid_status.exit_code != 0
    assert missing.exit_code != 0

    tasks = load_tasks(tmp_path)
    text = log_text(tmp_path)
    assert tasks[0]["status"] == "dropped"
    assert tasks[0]["tags"] == ["eng", "ops"]
    assert "#blocked t-0001 needs input" in text
    assert "#dropped t-0001 Edited task" in text


def test_edit_without_editor_prints_task_yaml(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Print editable YAML"])
    assert created.exit_code == 0, created.output

    edited = runner.invoke(
        app,
        ["edit", "t-0001"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path)), "EDITOR": ""},
    )

    assert edited.exit_code == 0
    assert "Print editable YAML" in edited.output
    assert "priority: P2" in edited.output


def test_edit_with_editor_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Editor invalid YAML"])
    assert created.exit_code == 0, created.output

    editor = tmp_path / "editor.py"
    write_text_atomic(
        editor,
        "import pathlib, sys\npathlib.Path(sys.argv[1]).write_text('- nope\\n', encoding='utf-8')\n",
    )
    editor.chmod(0o755)

    edited = runner.invoke(
        app,
        ["edit", "t-0001"],
        env={
            "OPENFIN_HOME": str(openfin_home(tmp_path)),
            "EDITOR": f"{os.sys.executable} {editor}",
        },
    )

    assert edited.exit_code != 0
    assert "edited task must be a YAML mapping" in edited.output
