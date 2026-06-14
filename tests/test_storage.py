from __future__ import annotations

from pathlib import Path

from openfin.storage import OpenFinStore, read_text
from tests.helpers import openfin_home, run_cli


def test_store_defaults_to_dot_openfin_home(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENFIN_HOME", raising=False)
    monkeypatch.delenv("FOUNDER_HOME", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    store = OpenFinStore.from_env()

    assert store.root == tmp_path / ".openfin"


def test_store_uses_only_openfin_home_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENFIN_HOME", str(tmp_path / "configured"))
    monkeypatch.setenv("FOUNDER_HOME", str(tmp_path / "founder"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    store = OpenFinStore.from_env()

    assert store.root == tmp_path / "configured"


def test_store_ignores_founder_home_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENFIN_HOME", raising=False)
    monkeypatch.setenv("FOUNDER_HOME", str(tmp_path / "founder"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    store = OpenFinStore.from_env()

    assert store.root == tmp_path / ".openfin"


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
