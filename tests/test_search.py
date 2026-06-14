from __future__ import annotations

from pathlib import Path
from tests.helpers import run_cli


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
