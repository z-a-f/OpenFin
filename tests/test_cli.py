from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml
from typer.testing import CliRunner

from openfin.cli import app


runner = CliRunner()


def run_cli(tmp_path: Path, args: list[str]):
    home = tmp_path / "openfin"
    return runner.invoke(app, args, env={"OPENFIN_HOME": str(home)})


def founder_home(tmp_path: Path) -> Path:
    return tmp_path / "openfin"


def test_task_lifecycle_and_today_view(tmp_path: Path) -> None:
    due_today = date.today().isoformat()

    result = run_cli(
        tmp_path,
        ["add", "Ship Phase 1", "-p", "P1", "-d", due_today, "-t", "code,admin"],
    )

    assert result.exit_code == 0, result.output
    assert "t-0001" in result.output

    tasks = yaml.safe_load((founder_home(tmp_path) / "tasks.yaml").read_text())
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
    tasks = yaml.safe_load((founder_home(tmp_path) / "tasks.yaml").read_text())
    assert tasks[0]["status"] == "done"
    log_text = next((founder_home(tmp_path) / "log").glob("*.md")).read_text()
    assert "#done t-0001 Ship Phase 1" in log_text


def test_capture_idea_and_search(tmp_path: Path) -> None:
    captured = run_cli(tmp_path, ["in", "ping design folks about onboarding"])

    assert captured.exit_code == 0, captured.output
    inbox = (founder_home(tmp_path) / "inbox.md").read_text()
    assert "ping design folks about onboarding" in inbox

    idea = run_cli(tmp_path, ["idea", "meter by tokens processed", "-t", "pricing"])

    assert idea.exit_code == 0, idea.output
    log_text = next((founder_home(tmp_path) / "log").glob("*.md")).read_text()
    assert "#idea #pricing meter by tokens processed" in log_text

    found = run_cli(tmp_path, ["search", "tokens"])

    assert found.exit_code == 0, found.output
    assert "meter by tokens processed" in found.output
    assert "log/" in found.output


def test_context_profile_filters_sections_tasks_and_topic_hits(tmp_path: Path) -> None:
    init = run_cli(tmp_path, ["init"])
    assert init.exit_code == 0, init.output

    home = founder_home(tmp_path)
    (home / "charter.md").write_text(
        "# OpenFin Charter\n"
        "## Mission\n"
        "Keep founder context current.\n"
        "## Stack\n"
        "- Python Typer CLI\n"
        "## Key decisions\n"
        "- Plain text is canonical.\n"
        "## Non-goals\n"
        "- No API layer in Phase 1.\n"
    )
    (home / "profiles.yaml").write_text(
        "default:\n"
        "  charter_sections: all\n"
        "  task_tags: all\n"
        "  log_tags: all\n"
        "  max_log_lines: 40\n"
        "code:\n"
        "  charter_sections: [Stack, Key decisions, Non-goals]\n"
        "  task_tags: [code, eng, infra]\n"
        "  log_tags: [decision]\n"
        "  max_log_lines: 10\n"
    )

    code_task = run_cli(tmp_path, ["add", "Refactor quant arch", "-t", "code"])
    admin_task = run_cli(tmp_path, ["add", "Email investor update", "-t", "investors"])
    decision = run_cli(tmp_path, ["idea", "quant arch uses plain files", "-t", "decision"])

    assert code_task.exit_code == 0, code_task.output
    assert admin_task.exit_code == 0, admin_task.output
    assert decision.exit_code == 0, decision.output

    context = run_cli(tmp_path, ["context", "code", "--for", "quant"])

    assert context.exit_code == 0, context.output
    assert "## Stack" in context.output
    assert "## Mission" not in context.output
    assert "Refactor quant arch" in context.output
    assert "Email investor update" not in context.output
    assert "quant arch uses plain files" in context.output
    assert "Estimated tokens:" in context.output


def test_overdue_view_flags_old_tasks(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    created = run_cli(tmp_path, ["add", "Follow up on pilot", "-d", yesterday, "-p", "P0"])

    assert created.exit_code == 0, created.output

    overdue = run_cli(tmp_path, ["overdue"])

    assert overdue.exit_code == 0, overdue.output
    assert "OVERDUE" in overdue.output
    assert "Follow up on pilot" in overdue.output
    assert "t-0001" in overdue.output
