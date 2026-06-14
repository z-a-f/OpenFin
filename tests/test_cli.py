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


def openfin_home(tmp_path: Path) -> Path:
    return tmp_path / "openfin"


def test_task_lifecycle_and_today_view(tmp_path: Path) -> None:
    due_today = date.today().isoformat()

    result = run_cli(
        tmp_path,
        ["add", "Ship Phase 1", "-p", "P1", "-d", due_today, "-t", "code,admin"],
    )

    assert result.exit_code == 0, result.output
    assert "t-0001" in result.output

    tasks = yaml.safe_load((openfin_home(tmp_path) / "tasks.yaml").read_text())
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
    tasks = yaml.safe_load((openfin_home(tmp_path) / "tasks.yaml").read_text())
    assert tasks[0]["status"] == "done"
    log_text = next((openfin_home(tmp_path) / "log").glob("*.md")).read_text()
    assert "#done t-0001 Ship Phase 1" in log_text


def test_capture_idea_and_search(tmp_path: Path) -> None:
    captured = run_cli(tmp_path, ["in", "ping design folks about onboarding"])

    assert captured.exit_code == 0, captured.output
    inbox = (openfin_home(tmp_path) / "inbox.md").read_text()
    assert "ping design folks about onboarding" in inbox

    idea = run_cli(tmp_path, ["idea", "meter by tokens processed", "-t", "pricing"])

    assert idea.exit_code == 0, idea.output
    log_text = next((openfin_home(tmp_path) / "log").glob("*.md")).read_text()
    assert "#idea #pricing meter by tokens processed" in log_text

    found = run_cli(tmp_path, ["search", "tokens"])

    assert found.exit_code == 0, found.output
    assert "meter by tokens processed" in found.output
    assert "log/" in found.output


def test_context_profile_filters_sections_tasks_and_topic_hits(tmp_path: Path) -> None:
    init = run_cli(tmp_path, ["init"])
    assert init.exit_code == 0, init.output

    home = openfin_home(tmp_path)
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


def test_future_recheck_quiets_overdue_review_and_today(tmp_path: Path) -> None:
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    created = run_cli(tmp_path, ["add", "Committed follow-up", "-d", yesterday])
    assert created.exit_code == 0, created.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(task_path.read_text())
    tasks[0]["recheck"] = tomorrow
    task_path.write_text(yaml.safe_dump(tasks, sort_keys=False))

    overdue = run_cli(tmp_path, ["overdue"])
    today = run_cli(tmp_path, ["today"])
    review = run_cli(tmp_path, ["review"])

    assert overdue.exit_code == 0, overdue.output
    assert today.exit_code == 0, today.output
    assert review.exit_code == 0, review.output
    assert "Committed follow-up" not in overdue.output
    assert "Run `f review`" not in today.output
    assert "No overdue or recheck items." in review.output


def test_archived_task_ids_are_not_reused_and_done_log_is_not_duplicated(
    tmp_path: Path,
) -> None:
    old_day = (date.today() - timedelta(days=15)).isoformat()

    created = run_cli(tmp_path, ["add", "Old finished task"])
    done = run_cli(tmp_path, ["done", "t-0001"])
    assert created.exit_code == 0, created.output
    assert done.exit_code == 0, done.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(task_path.read_text())
    tasks[0]["updated"] = old_day
    task_path.write_text(yaml.safe_dump(tasks, sort_keys=False))

    compacted = run_cli(tmp_path, ["compact"])
    added = run_cli(tmp_path, ["add", "Fresh task"])

    assert compacted.exit_code == 0, compacted.output
    assert added.exit_code == 0, added.output
    assert "t-0002" in added.output

    log_text = "\n".join(path.read_text() for path in (openfin_home(tmp_path) / "log").glob("*.md"))
    assert log_text.count("#done t-0001 Old finished task") == 1


def test_evening_digest_only_shows_closed_today(tmp_path: Path) -> None:
    init = run_cli(tmp_path, ["init"])
    assert init.exit_code == 0, init.output

    today = date.today()
    yesterday = today - timedelta(days=1)
    log_path = openfin_home(tmp_path) / "log" / f"{today:%Y-%m}.md"
    log_path.write_text(
        f"## {yesterday.isoformat()}\n\n"
        "- 18:00 #done t-0001 Done yesterday\n\n"
        f"## {today.isoformat()}\n\n"
        "- 18:00 #done t-0002 Done today\n"
    )

    digest = run_cli(tmp_path, ["digest", "evening"])

    assert digest.exit_code == 0, digest.output
    assert "Done today" in digest.output
    assert "Done yesterday" not in digest.output


def test_compact_redundancy_requires_old_or_overdue_shared_tag(tmp_path: Path) -> None:
    first = run_cli(tmp_path, ["add", "Implement parser", "-t", "eng"])
    second = run_cli(tmp_path, ["add", "Write renderer", "-t", "eng"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output

    fresh = run_cli(tmp_path, ["compact"])
    assert fresh.exit_code == 0, fresh.output
    assert "POSSIBLE REDUNDANCY" not in fresh.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(task_path.read_text())
    tasks[0]["created"] = (date.today() - timedelta(days=8)).isoformat()
    task_path.write_text(yaml.safe_dump(tasks, sort_keys=False))

    old = run_cli(tmp_path, ["compact"])
    assert old.exit_code == 0, old.output
    assert "POSSIBLE REDUNDANCY" in old.output
    assert "#eng" in old.output


def test_bad_hand_edited_dates_are_flagged_not_crashing_views(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Bad date task"])
    assert created.exit_code == 0, created.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(task_path.read_text())
    tasks[0]["due"] = "not-a-date"
    task_path.write_text(yaml.safe_dump(tasks, sort_keys=False))

    today = run_cli(tmp_path, ["today"])
    overdue = run_cli(tmp_path, ["overdue"])

    assert today.exit_code == 0, today.output
    assert overdue.exit_code == 0, overdue.output
    assert "BAD DATES" in today.output
    assert "BAD DATES" in overdue.output


def test_task_yaml_preserves_unicode_for_human_readability(tmp_path: Path) -> None:
    title = "Resume \u2014 investor update"

    created = run_cli(tmp_path, ["add", title])

    assert created.exit_code == 0, created.output
    raw = (openfin_home(tmp_path) / "tasks.yaml").read_text()
    assert "\\u2014" not in raw


def test_log_tag_filter_matches_exact_tags(tmp_path: Path) -> None:
    postmortem = run_cli(tmp_path, ["idea", "incident writeup", "-t", "postmortem"])
    post = run_cli(tmp_path, ["idea", "launch draft", "-t", "post"])
    assert postmortem.exit_code == 0, postmortem.output
    assert post.exit_code == 0, post.output

    found = run_cli(tmp_path, ["search", "draft", "--tag", "post"])
    missed = run_cli(tmp_path, ["search", "incident", "--tag", "post"])

    assert found.exit_code == 0, found.output
    assert missed.exit_code == 0, missed.output
    assert "launch draft" in found.output
    assert "No matches." in missed.output
