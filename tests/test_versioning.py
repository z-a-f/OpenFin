from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from openfin.cli import app
from openfin.agent_store import AgentEvent, AgentSessionMeta, AgentSessionStore, Project
from openfin.versioning import ensure_git_repo
from tests.helpers import openfin_home, run_cli, runner


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not found")


def git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def test_init_creates_git_repo_and_initial_commit(tmp_path: Path) -> None:
    result = run_cli(tmp_path, ["init"])
    home = openfin_home(tmp_path)

    assert result.exit_code == 0, result.output
    assert (home / ".git").exists()
    assert "Initialize OpenFin store" in git_output(home, "log", "--oneline")
    assert git_output(home, "status", "--porcelain") == ""
    assert ".openfin/" in (home / ".gitignore").read_text(encoding="utf-8")


def test_gitignore_rules_are_merged_into_existing_file(tmp_path: Path) -> None:
    home = openfin_home(tmp_path)
    home.mkdir(parents=True)
    (home / ".gitignore").write_text("custom.cache\n", encoding="utf-8")

    assert ensure_git_repo(home)

    gitignore = (home / ".gitignore").read_text(encoding="utf-8")
    assert "custom.cache\n" in gitignore
    assert ".openfin/\n" in gitignore
    assert "agents/openfind.sock\n" in gitignore


def test_store_writes_create_followup_commits(tmp_path: Path) -> None:
    initialized = run_cli(tmp_path, ["init"])
    captured = run_cli(tmp_path, ["in", "remember the investor follow-up"])
    home = openfin_home(tmp_path)

    assert initialized.exit_code == 0, initialized.output
    assert captured.exit_code == 0, captured.output
    log = git_output(home, "log", "--format=%s")
    assert "Capture OpenFin inbox item" in log
    assert "Initialize OpenFin store" in log
    assert git_output(home, "status", "--porcelain") == ""


def test_read_only_commands_do_not_commit_existing_manual_edits(tmp_path: Path) -> None:
    initialized = run_cli(tmp_path, ["init"])
    home = openfin_home(tmp_path)
    (home / "now.md").write_text("# Now\nmanual edit\n", encoding="utf-8")
    before_count = git_output(home, "rev-list", "--count", "HEAD").strip()

    viewed = run_cli(tmp_path, ["today"])

    assert initialized.exit_code == 0, initialized.output
    assert viewed.exit_code == 0, viewed.output
    assert git_output(home, "rev-list", "--count", "HEAD").strip() == before_count
    assert " M now.md" in git_output(home, "status", "--porcelain")


def test_git_initialization_can_be_skipped(tmp_path: Path) -> None:
    home = openfin_home(tmp_path)
    result = runner.invoke(
        app,
        ["init", "--no-git"],
        env={"OPENFIN_HOME": str(home)},
    )

    assert result.exit_code == 0, result.output
    assert not (home / ".git").exists()


def test_git_automation_can_be_disabled_with_env(tmp_path: Path) -> None:
    home = openfin_home(tmp_path)
    result = runner.invoke(
        app,
        ["init"],
        env={"OPENFIN_HOME": str(home), "OPENFIN_GIT": "0"},
    )

    assert result.exit_code == 0, result.output
    assert not (home / ".git").exists()


def test_agent_session_transcripts_are_committed(tmp_path: Path) -> None:
    store = AgentSessionStore(openfin_home(tmp_path))
    meta = store.create_session(
        AgentSessionMeta.new(
            session_id="agent-001",
            adapter="claude",
            project=Project(name="OpenFin", root=tmp_path),
        )
    )
    store.append_event(
        meta.id,
        AgentEvent(
            kind="assistant_text",
            text="hello",
            raw={},
            ts="2026-06-14T12:00:00Z",
            session_id="native-1",
        ),
    )

    log = git_output(openfin_home(tmp_path), "log", "--format=%s")

    assert "Append OpenFin agent transcript agent-001" in log
    assert git_output(openfin_home(tmp_path), "status", "--porcelain") == ""
