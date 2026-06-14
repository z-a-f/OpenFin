from __future__ import annotations

from pathlib import Path
from tests.helpers import openfin_home, run_cli


def test_index_rebuild_status_and_search(tmp_path: Path) -> None:
    idea = run_cli(tmp_path, ["idea", "meter by tokens processed", "-t", "pricing"])
    assert idea.exit_code == 0, idea.output

    rebuilt = run_cli(tmp_path, ["index", "rebuild"])
    status = run_cli(tmp_path, ["index", "status"])
    found = run_cli(tmp_path, ["index", "search", "tokens", "--tag", "pricing"])

    assert rebuilt.exit_code == 0, rebuilt.output
    assert status.exit_code == 0, status.output
    assert found.exit_code == 0, found.output
    assert "Indexed" in rebuilt.output
    assert "Index current" in status.output
    assert "meter by tokens processed" in found.output
    assert (openfin_home(tmp_path) / ".openfin" / "index.sqlite3").exists()


def test_search_index_auto_rebuilds_stale_index(tmp_path: Path) -> None:
    first = run_cli(tmp_path, ["idea", "first indexed thought", "-t", "postmortem"])
    rebuilt = run_cli(tmp_path, ["index", "rebuild"])
    second = run_cli(tmp_path, ["idea", "second indexed thought", "-t", "post"])
    assert first.exit_code == 0, first.output
    assert rebuilt.exit_code == 0, rebuilt.output
    assert second.exit_code == 0, second.output

    found = run_cli(tmp_path, ["search", "second", "--index", "--tag", "post"])
    missed = run_cli(tmp_path, ["search", "first", "--index", "--tag", "post"])
    status = run_cli(tmp_path, ["index", "status"])

    assert found.exit_code == 0, found.output
    assert missed.exit_code == 0, missed.output
    assert status.exit_code == 0, status.output
    assert "second indexed thought" in found.output
    assert "No matches." in missed.output
    assert "Index current" in status.output
