from __future__ import annotations

from pathlib import Path
from openfin.storage import read_text
from tests.helpers import load_tasks, log_text, openfin_home, run_cli


def test_capture_idea_and_search(tmp_path: Path) -> None:
    captured = run_cli(tmp_path, ["in", "ping design folks about onboarding"])

    assert captured.exit_code == 0, captured.output
    inbox = read_text(openfin_home(tmp_path) / "inbox.md")
    assert "ping design folks about onboarding" in inbox

    idea = run_cli(tmp_path, ["idea", "meter by tokens processed", "-t", "pricing"])

    assert idea.exit_code == 0, idea.output
    log_text = read_text(next((openfin_home(tmp_path) / "log").glob("*.md")))
    assert "#idea #pricing meter by tokens processed" in log_text

    found = run_cli(tmp_path, ["search", "tokens"])

    assert found.exit_code == 0, found.output
    assert "meter by tokens processed" in found.output
    assert "log/" in found.output


def test_triage_task_idea_drop_branches_and_rewrites_inbox(tmp_path: Path) -> None:
    first = run_cli(tmp_path, ["in", "turn first capture into task"])
    second = run_cli(tmp_path, ["in", "turn second capture into idea"])
    third = run_cli(tmp_path, ["in", "drop this capture"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert third.exit_code == 0, third.output

    triaged = run_cli(tmp_path, ["triage"], input="task\nidea\ndrop\n")

    assert triaged.exit_code == 0, triaged.output
    tasks = load_tasks(tmp_path)
    assert tasks[0]["title"] == "turn first capture into task"

    log_text = "\n".join(
        read_text(path) for path in (openfin_home(tmp_path) / "log").glob("*.md")
    )
    assert "#idea turn second capture into idea" in log_text
    assert read_text(openfin_home(tmp_path) / "inbox.md") == ""


def test_triage_empty_decision_note_and_skip_branches(tmp_path: Path) -> None:
    empty = run_cli(tmp_path, ["triage"])
    assert empty.exit_code == 0, empty.output
    assert "Inbox is empty." in empty.output

    for text in ["capture decision", "capture note", "capture skip"]:
        captured = run_cli(tmp_path, ["in", text])
        assert captured.exit_code == 0, captured.output

    triaged = run_cli(tmp_path, ["triage"], input="decision\nnote\nskip\n")

    assert triaged.exit_code == 0, triaged.output
    text = log_text(tmp_path)
    inbox = read_text(openfin_home(tmp_path) / "inbox.md")
    assert "#decision capture decision" in text
    assert "#note capture note" in text
    assert "capture skip" in inbox
