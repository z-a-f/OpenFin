from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml


TASK_STATUSES = {"open", "doing", "blocked", "done", "dropped"}
ACTIVE_STATUSES = {"open", "doing", "blocked"}
PRIORITIES = {"P0", "P1", "P2", "P3"}

DEFAULT_PROFILES: dict[str, dict[str, Any]] = {
    "default": {
        "charter_sections": "all",
        "task_tags": "all",
        "log_tags": "all",
        "max_log_lines": 40,
    },
    "code": {
        "charter_sections": ["Stack", "Key decisions", "Non-goals"],
        "task_tags": ["code", "eng", "infra"],
        "log_tags": ["decision"],
        "max_log_lines": 20,
    },
    "admin": {
        "charter_sections": ["Mission", "Cofounders"],
        "task_tags": ["investors", "ops", "post", "admin"],
        "log_tags": ["decision", "post"],
        "max_log_lines": 20,
    },
}

DEFAULT_CHARTER = """# OpenFin Charter
## Mission
Write the mission here.
## Cofounders
- me
## Stack
- Python
- Typer
- Markdown and YAML
## Key decisions
- Plain text is canonical.
## Non-goals
- No database, daemon, API layer, or web UI in Phase 1.
"""


def default_now_text(today: date | None = None) -> str:
    today = today or date.today()
    return (
        f"# Now - week of {today.isoformat()}\n"
        f"_updated: {today.isoformat()}_\n\n"
        "## Priorities\n"
        "1. \n\n"
        "## In flight\n"
        "- \n\n"
        "## Blocked / waiting on\n"
        "- \n"
    )


@dataclass(frozen=True)
class TextHit:
    source: str
    line_number: int
    line: str
    entry_date: date | None = None


@dataclass
class OpenFinStore:
    root: Path

    @classmethod
    def from_env(cls) -> "OpenFinStore":
        configured = os.environ.get("OPENFIN_HOME") or os.environ.get("FOUNDER_HOME")
        root = Path(configured).expanduser() if configured else Path.home() / "openfin"
        return cls(root=root)

    @property
    def charter_path(self) -> Path:
        return self.root / "charter.md"

    @property
    def now_path(self) -> Path:
        return self.root / "now.md"

    @property
    def tasks_path(self) -> Path:
        return self.root / "tasks.yaml"

    @property
    def inbox_path(self) -> Path:
        return self.root / "inbox.md"

    @property
    def profiles_path(self) -> Path:
        return self.root / "profiles.yaml"

    @property
    def log_dir(self) -> Path:
        return self.root / "log"

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._write_if_missing(self.charter_path, DEFAULT_CHARTER)
        self._write_if_missing(self.now_path, default_now_text())
        self._write_if_missing(self.tasks_path, "[]\n")
        self._write_if_missing(self.inbox_path, "")
        self._write_if_missing(
            self.profiles_path,
            yaml.safe_dump(DEFAULT_PROFILES, sort_keys=False),
        )

    def _write_if_missing(self, path: Path, text: str) -> None:
        if not path.exists():
            path.write_text(text)

    def load_tasks(self) -> list[dict[str, Any]]:
        self.ensure_layout()
        loaded = yaml.safe_load(self.tasks_path.read_text()) or []
        if not isinstance(loaded, list):
            raise ValueError(f"{self.tasks_path} must contain a YAML list")
        return loaded

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self.ensure_layout()
        self.tasks_path.write_text(yaml.safe_dump(tasks, sort_keys=False))

    def load_profiles(self) -> dict[str, dict[str, Any]]:
        self.ensure_layout()
        loaded = yaml.safe_load(self.profiles_path.read_text()) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.profiles_path} must contain a YAML mapping")
        return loaded

    def next_task_id(self, tasks: Iterable[dict[str, Any]]) -> str:
        highest = 0
        for task in tasks:
            match = re.fullmatch(r"t-(\d{4,})", str(task.get("id", "")))
            if match:
                highest = max(highest, int(match.group(1)))
        return f"t-{highest + 1:04d}"

    def append_inbox(self, text: str, when: datetime | None = None) -> None:
        self.ensure_layout()
        when = when or datetime.now()
        with self.inbox_path.open("a") as handle:
            handle.write(f"- {when:%Y-%m-%d %H:%M} {text}\n")

    def current_log_path(self, when: datetime | None = None) -> Path:
        when = when or datetime.now()
        return self.log_dir / f"{when:%Y-%m}.md"

    def append_log_entry(self, body: str, when: datetime | None = None) -> None:
        self.ensure_layout()
        when = when or datetime.now()
        path = self.current_log_path(when)
        existing = path.read_text() if path.exists() else ""
        header = f"## {when:%Y-%m-%d}"
        prefix = ""
        if existing and not existing.endswith("\n"):
            prefix += "\n"
        if header not in existing:
            if existing:
                prefix += "\n"
            prefix += f"{header}\n\n"
        with path.open("a") as handle:
            handle.write(prefix)
            handle.write(f"- {when:%H:%M} {body}\n")

    def iter_text_files(self) -> Iterable[tuple[Path, str]]:
        self.ensure_layout()
        root_files = [
            self.charter_path,
            self.now_path,
            self.tasks_path,
            self.inbox_path,
        ]
        for path in root_files:
            yield path, path.name
        for path in sorted(self.log_dir.glob("*.md")):
            yield path, f"log/{path.name}"

    def search(
        self,
        query: str,
        *,
        tag: str | None = None,
        since: date | None = None,
    ) -> list[TextHit]:
        query_lower = query.lower()
        tag_marker = f"#{tag.lstrip('#')}" if tag else None
        hits: list[TextHit] = []

        for path, source in self.iter_text_files():
            current_date: date | None = None
            for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
                line = raw_line.rstrip()
                header_date = parse_log_header_date(line)
                if header_date:
                    current_date = header_date
                    continue

                entry_date = current_date or parse_inbox_line_date(line)
                if since and entry_date and entry_date < since:
                    continue
                if since and source.startswith("log/") and entry_date is None:
                    continue
                if tag_marker and tag_marker not in line:
                    continue
                if query_lower in line.lower():
                    hits.append(
                        TextHit(
                            source=source,
                            line_number=line_number,
                            line=line,
                            entry_date=entry_date,
                        )
                    )

        return sorted(
            hits,
            key=lambda hit: (hit.entry_date or date.min, hit.source, hit.line_number),
            reverse=True,
        )

    def recent_log_entries(
        self,
        *,
        tags: list[str] | str,
        limit: int,
    ) -> list[str]:
        self.ensure_layout()
        want_all = tags == "all"
        tag_markers = [] if want_all else [f"#{tag.lstrip('#')}" for tag in tags]
        entries: list[tuple[str, str]] = []

        for path in sorted(self.log_dir.glob("*.md")):
            current_day = ""
            for line in path.read_text().splitlines():
                if line.startswith("## "):
                    current_day = line.removeprefix("## ").strip()
                    continue
                if not line.startswith("- "):
                    continue
                if not want_all and not any(marker in line for marker in tag_markers):
                    continue
                entries.append((f"{current_day} {line}", line))

        entries.sort(reverse=True)
        return [entry for _, entry in entries[:limit]]


def parse_log_header_date(line: str) -> date | None:
    match = re.fullmatch(r"##\s+(\d{4}-\d{2}-\d{2})", line.strip())
    if not match:
        return None
    return date.fromisoformat(match.group(1))


def parse_inbox_line_date(line: str) -> date | None:
    match = re.match(r"-\s+(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\b", line)
    if not match:
        return None
    return date.fromisoformat(match.group(1))


def parse_now_updated(text: str) -> date | None:
    match = re.search(r"_updated:\s*(\d{4}-\d{2}-\d{2})_", text)
    if not match:
        return None
    return date.fromisoformat(match.group(1))
