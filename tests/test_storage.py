from __future__ import annotations

from pathlib import Path
from openfin.storage import read_text
from tests.helpers import openfin_home, run_cli


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
