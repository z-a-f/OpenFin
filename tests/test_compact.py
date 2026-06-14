from __future__ import annotations

from pathlib import Path
from datetime import date, timedelta

import yaml

from openfin.storage import dump_yaml, read_text, write_text_atomic
from tests.helpers import openfin_home, run_cli


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


def test_compact_deep_dedup_is_explicit_and_proposal_only(tmp_path: Path) -> None:
    first = run_cli(tmp_path, ["add", "Write investor update"])
    second = run_cli(tmp_path, ["add", "Draft investor update"])
    unrelated = run_cli(tmp_path, ["add", "Implement parser"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert unrelated.exit_code == 0, unrelated.output

    task_path = openfin_home(tmp_path) / "tasks.yaml"
    tasks = yaml.safe_load(read_text(task_path))
    tasks[0]["created"] = (date.today() - timedelta(days=8)).isoformat()
    before = dump_yaml(tasks)
    write_text_atomic(task_path, before)

    default = run_cli(tmp_path, ["compact"])
    deep = run_cli(tmp_path, ["compact", "--deep-dedup"])
    after = read_text(task_path)

    assert default.exit_code == 0, default.output
    assert deep.exit_code == 0, deep.output
    assert "POSSIBLE DEEP DEDUP" not in default.output
    assert "POSSIBLE DEEP DEDUP" in deep.output
    assert "t-0001 <-> t-0002" in deep.output
    assert "t-0003" not in deep.output
    assert after == before
