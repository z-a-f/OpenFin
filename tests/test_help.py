from __future__ import annotations

from typer.testing import CliRunner

from openfin.daemon import daemon_app
from tests.helpers import run_cli


def test_all_cli_help_pages_render(tmp_path) -> None:
    commands = [
        ["--help"],
        ["init", "--help"],
        ["in", "--help"],
        ["add", "--help"],
        ["assign", "--help"],
        ["idea", "--help"],
        ["ls", "--help"],
        ["search", "--help"],
        ["do", "--help"],
        ["done", "--help"],
        ["block", "--help"],
        ["drop", "--help"],
        ["touch", "--help"],
        ["edit", "--help"],
        ["overdue", "--help"],
        ["today", "--help"],
        ["review", "--help"],
        ["context", "--help"],
        ["digest", "--help"],
        ["triage", "--help"],
        ["compact", "--help"],
        ["schedule", "--help"],
        ["schedule", "show", "--help"],
        ["schedule", "install", "--help"],
        ["schedule", "uninstall", "--help"],
        ["index", "--help"],
        ["index", "rebuild", "--help"],
        ["index", "status", "--help"],
        ["index", "search", "--help"],
        ["agents", "--help"],
        ["agents", "list", "--help"],
        ["agents", "status", "--help"],
        ["agents", "show", "--help"],
    ]

    for command in commands:
        result = run_cli(tmp_path, command)

        assert result.exit_code == 0, f"{command}\n{result.output}"
        assert "Show this message and exit" in result.output


def test_main_help_mentions_supported_agent_adapters(tmp_path) -> None:
    result = run_cli(tmp_path, ["--help"])

    assert result.exit_code == 0
    assert "claude" in result.output
    assert "codex" in result.output


def test_task_command_help_explains_core_arguments(tmp_path) -> None:
    add_help = run_cli(tmp_path, ["add", "--help"])
    edit_help = run_cli(tmp_path, ["edit", "--help"])
    block_help = run_cli(tmp_path, ["block", "--help"])

    assert add_help.exit_code == 0
    assert "Task title to add to tasks.yaml" in add_help.output
    assert "Priority bucket: P0 urgent" in add_help.output
    assert "Comma-separated tags" in add_help.output

    assert edit_help.exit_code == 0
    assert "Task id to edit" in edit_help.output
    assert "Set status: open, doing, blocked, done" in edit_help.output
    assert "dropped" in edit_help.output

    assert block_help.exit_code == 0
    assert "Short reason the task is blocked" in block_help.output


def test_context_search_digest_and_agent_help_are_self_describing(tmp_path) -> None:
    context_help = run_cli(tmp_path, ["context", "--help"])
    search_help = run_cli(tmp_path, ["search", "--help"])
    digest_help = run_cli(tmp_path, ["digest", "--help"])
    agent_help = run_cli(tmp_path, ["agents", "show", "--help"])

    assert context_help.exit_code == 0
    assert "Context profile from profiles.yaml" in context_help.output
    assert "Topic to search for" in context_help.output

    assert search_help.exit_code == 0
    assert "Text to search for across OpenFin memory files" in search_help.output
    assert "derived SQLite FTS index" in search_help.output
    assert "files directly" in search_help.output

    assert digest_help.exit_code == 0
    assert "Digest kind to render: morning or evening" in digest_help.output
    assert "Delivery target after rendering" in digest_help.output

    assert agent_help.exit_code == 0
    assert "OpenFin agent session id whose transcript" in agent_help.output
    assert "be shown" in agent_help.output
    assert "Number of most recent transcript events" in agent_help.output


def test_schedule_and_daemon_help_explain_operational_choices(tmp_path) -> None:
    schedule_help = run_cli(tmp_path, ["schedule", "install", "--help"])
    daemon_help = CliRunner().invoke(daemon_app, ["--help"])

    assert schedule_help.exit_code == 0
    assert "Scheduler backend to install" in schedule_help.output
    assert "Delivery target for scheduled digests" in schedule_help.output
    assert "telegram, both, or none" in schedule_help.output
    assert "24-hour HH:MM format" in schedule_help.output

    assert daemon_help.exit_code == 0
    assert "OPENFIN_HOME/agents/openfind.sock" in daemon_help.output
