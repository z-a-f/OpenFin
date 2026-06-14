from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import yaml
from typer.testing import CliRunner

from openfin.cli import app
from openfin.digest import render_digest
from openfin.scheduler import remove_cron_block
from openfin.storage import OpenFinStore
from openfin.storage import dump_yaml, read_text, write_text_atomic


runner = CliRunner()


def run_cli(tmp_path: Path, args: list[str]):
    home = tmp_path / "openfin"
    return runner.invoke(app, args, env={"OPENFIN_HOME": str(home)})


def openfin_home(tmp_path: Path) -> Path:
    return tmp_path / "openfin"


def load_tasks(tmp_path: Path):
    return yaml.safe_load(read_text(openfin_home(tmp_path) / "tasks.yaml"))


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


def test_archived_task_ids_are_not_reused_and_done_log_is_not_duplicated(
    tmp_path: Path,
) -> None:
    old_day = (date.today() - timedelta(days=15)).isoformat()

    created = run_cli(tmp_path, ["add", "Old finished task"])
    done = run_cli(tmp_path, ["done", "t-0001"])
    assert created.exit_code == 0, created.output
    assert done.exit_code == 0, done.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(read_text(task_path))
    tasks[0]["updated"] = old_day
    write_text_atomic(task_path, dump_yaml(tasks))

    compacted = run_cli(tmp_path, ["compact"])
    added = run_cli(tmp_path, ["add", "Fresh task"])

    assert compacted.exit_code == 0, compacted.output
    assert added.exit_code == 0, added.output
    assert "t-0002" in added.output

    log_text = "\n".join(
        read_text(path) for path in (openfin_home(tmp_path) / "log").glob("*.md")
    )
    assert log_text.count("#done t-0001 Old finished task") == 1


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


def test_schedule_show_renders_cron_without_installing(tmp_path: Path) -> None:
    shown = run_cli(
        tmp_path,
        [
            "schedule",
            "show",
            "--target",
            "cron",
            "--send",
            "both",
            "--morning",
            "08:05",
            "--evening",
            "18:30",
        ],
    )

    assert shown.exit_code == 0, shown.output
    assert "OPENFIN_DIGEST_BEGIN" in shown.output
    assert "5 08 * * *" in shown.output
    assert "30 18 * * *" in shown.output
    assert "digest morning --send both" in shown.output
    assert str(openfin_home(tmp_path)) in shown.output


def test_cron_block_removal_preserves_user_entries() -> None:
    existing = "\n".join(
        [
            "0 7 * * * echo keep",
            "# OPENFIN_DIGEST_BEGIN",
            "0 9 * * * old openfin",
            "# OPENFIN_DIGEST_END",
            "0 22 * * * echo also-keep",
        ]
    )

    cleaned = remove_cron_block(existing)

    assert "echo keep" in cleaned
    assert "echo also-keep" in cleaned
    assert "old openfin" not in cleaned


def test_compact_redundancy_requires_old_or_overdue_shared_tag(tmp_path: Path) -> None:
    first = run_cli(tmp_path, ["add", "Implement parser", "-t", "eng"])
    second = run_cli(tmp_path, ["add", "Write renderer", "-t", "eng"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output

    fresh = run_cli(tmp_path, ["compact"])
    assert fresh.exit_code == 0, fresh.output
    assert "POSSIBLE REDUNDANCY" not in fresh.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(read_text(task_path))
    tasks[0]["created"] = (date.today() - timedelta(days=8)).isoformat()
    write_text_atomic(task_path, dump_yaml(tasks))

    old = run_cli(tmp_path, ["compact"])
    assert old.exit_code == 0, old.output
    assert "POSSIBLE REDUNDANCY" in old.output
    assert "#eng" in old.output


def test_bad_hand_edited_dates_are_flagged_not_crashing_views(tmp_path: Path) -> None:
    created = run_cli(tmp_path, ["add", "Bad date task"])
    assert created.exit_code == 0, created.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(read_text(task_path))
    tasks[0]["due"] = "not-a-date"
    write_text_atomic(task_path, dump_yaml(tasks))

    today = run_cli(tmp_path, ["today"])
    overdue = run_cli(tmp_path, ["overdue"])

    assert today.exit_code == 0, today.output
    assert overdue.exit_code == 0, overdue.output
    assert "BAD DATES" in today.output
    assert "BAD DATES" in overdue.output


def test_task_yaml_preserves_unicode_for_human_readability(tmp_path: Path) -> None:
    title = "Résumé \u2014 investor update 😀 漢字"

    created = run_cli(tmp_path, ["add", title])
    captured = run_cli(tmp_path, ["in", title])
    idea = run_cli(tmp_path, ["idea", title])

    assert created.exit_code == 0, created.output
    assert captured.exit_code == 0, captured.output
    assert idea.exit_code == 0, idea.output
    raw = read_text(openfin_home(tmp_path) / "tasks.yaml")
    raw_bytes = (openfin_home(tmp_path) / "tasks.yaml").read_bytes()
    inbox_bytes = (openfin_home(tmp_path) / "inbox.md").read_bytes()
    log_bytes = b"".join(
        path.read_bytes() for path in (openfin_home(tmp_path) / "log").glob("*.md")
    )
    assert "\\u2014" not in raw
    assert title.encode("utf-8") in raw_bytes
    assert title.encode("utf-8") in inbox_bytes
    assert title.encode("utf-8") in log_bytes


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


def test_triage_task_idea_drop_branches_and_rewrites_inbox(tmp_path: Path) -> None:
    first = run_cli(tmp_path, ["in", "turn first capture into task"])
    second = run_cli(tmp_path, ["in", "turn second capture into idea"])
    third = run_cli(tmp_path, ["in", "drop this capture"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert third.exit_code == 0, third.output

    triaged = runner.invoke(
        app,
        ["triage"],
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input="task\nidea\ndrop\n",
    )

    assert triaged.exit_code == 0, triaged.output
    tasks = load_tasks(tmp_path)
    assert tasks[0]["title"] == "turn first capture into task"

    log_text = "\n".join(
        read_text(path) for path in (openfin_home(tmp_path) / "log").glob("*.md")
    )
    assert "#idea turn second capture into idea" in log_text
    assert read_text(openfin_home(tmp_path) / "inbox.md") == ""
