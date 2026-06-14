from __future__ import annotations

from pathlib import Path
import sys

import pytest

from openfin.storage import write_text_atomic
from tests.helpers import openfin_home, run_cli


def test_context_profile_filters_sections_tasks_and_topic_hits(tmp_path: Path) -> None:
    init = run_cli(tmp_path, ["init"])
    assert init.exit_code == 0, init.output

    home = openfin_home(tmp_path)
    write_text_atomic(
        home / "charter.md",
        "# OpenFin Charter\n"
        "## Mission\n"
        "Keep founder context current.\n"
        "## Stack\n"
        "- Python Typer CLI\n"
        "## Key decisions\n"
        "- Plain text is canonical.\n"
        "## Non-goals\n"
        "- No API layer in Phase 1.\n",
    )
    write_text_atomic(
        home / "profiles.yaml",
        "default:\n"
        "  charter_sections: all\n"
        "  task_tags: all\n"
        "  log_tags: all\n"
        "  max_log_lines: 40\n"
        "code:\n"
        "  charter_sections: [Stack, Key decisions, Non-goals]\n"
        "  task_tags: [code, eng, infra]\n"
        "  log_tags: [decision]\n"
        "  max_log_lines: 10\n",
    )

    code_task = run_cli(tmp_path, ["add", "Refactor quant arch", "-t", "code"])
    admin_task = run_cli(tmp_path, ["add", "Email investor update", "-t", "investors"])
    decision = run_cli(
        tmp_path, ["idea", "quant arch uses plain files", "-t", "decision"]
    )

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


def test_context_copy_budget_and_unknown_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    fake_pyperclip = type("FakePyperclip", (), {"copy": staticmethod(copied.append)})

    monkeypatch.setitem(sys.modules, "pyperclip", fake_pyperclip)

    created = run_cli(tmp_path, ["add", "Copy context task", "-t", "code"])
    assert created.exit_code == 0, created.output

    copied_context = run_cli(
        tmp_path, ["context", "default", "--copy", "--budget", "1"]
    )
    unknown = run_cli(tmp_path, ["context", "missing"])

    assert copied_context.exit_code == 0, copied_context.output
    assert copied
    assert "Copy context task" in copied[0]
    assert "Copied context pack to clipboard." in copied_context.output
    assert "Budget warning" in copied_context.output
    assert unknown.exit_code != 0
    assert "unknown profile: missing" in unknown.output
