from __future__ import annotations

from pathlib import Path
import yaml

from openfin.storage import dump_yaml, read_text, write_text_atomic
from tests.helpers import openfin_home, run_cli


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
