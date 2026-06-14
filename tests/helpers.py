from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from openfin.cli import app
from openfin.storage import read_text


runner = CliRunner()


def openfin_home(tmp_path: Path) -> Path:
    return tmp_path / "openfin"


def run_cli(tmp_path: Path, args: list[str], *, input: str | None = None):
    return runner.invoke(
        app,
        args,
        env={"OPENFIN_HOME": str(openfin_home(tmp_path))},
        input=input,
    )


def load_tasks(tmp_path: Path) -> list[dict]:
    return yaml.safe_load(read_text(openfin_home(tmp_path) / "tasks.yaml"))


def log_text(tmp_path: Path) -> str:
    log_dir = openfin_home(tmp_path) / "log"
    return "\n".join(read_text(path) for path in log_dir.glob("*.md"))
