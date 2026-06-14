from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import yaml

from openfin.versioning import DEFAULT_GITIGNORE, auto_commit, ensure_git_repo


ENCODING = "utf-8"
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


@dataclass(frozen=True)
class LogEntry:
    source: str
    line_number: int
    line: str
    entry_date: date | None = None


@dataclass
class OpenFinStore:
    root: Path

    @classmethod
    def from_env(cls) -> "OpenFinStore":
        configured = os.environ.get("OPENFIN_HOME")
        root = Path(configured).expanduser() if configured else Path.home() / ".openfin"
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
    def gitignore_path(self) -> Path:
        return self.root / ".gitignore"

    @property
    def log_dir(self) -> Path:
        return self.root / "log"

    def ensure_layout(self, *, version_control: bool = True) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        initialized = any(
            [
                self._write_if_missing(self.charter_path, DEFAULT_CHARTER),
                self._write_if_missing(self.now_path, default_now_text()),
                self._write_if_missing(self.tasks_path, "[]\n"),
                self._write_if_missing(self.inbox_path, ""),
                self._write_if_missing(
                    self.profiles_path,
                    dump_yaml(DEFAULT_PROFILES),
                ),
                self._write_if_missing(self.gitignore_path, DEFAULT_GITIGNORE),
            ]
        )
        had_git = (self.root / ".git").exists()
        if version_control:
            ensure_git_repo(self.root)
            if initialized or not had_git:
                auto_commit(self.root, "Initialize OpenFin store")

    def _write_if_missing(self, path: Path, text: str) -> bool:
        if path.exists():
            return False
        write_text_atomic(path, text)
        return True

    def load_tasks(self) -> list[dict[str, Any]]:
        self.ensure_layout()
        loaded = yaml.safe_load(read_text(self.tasks_path)) or []
        if not isinstance(loaded, list):
            raise ValueError(f"{self.tasks_path} must contain a YAML list")
        return loaded

    def save_tasks(self, tasks: list[dict[str, Any]]) -> None:
        self.ensure_layout()
        write_text_atomic(self.tasks_path, dump_yaml(tasks))
        auto_commit(self.root, "Update OpenFin tasks")

    def load_profiles(self) -> dict[str, dict[str, Any]]:
        self.ensure_layout()
        loaded = yaml.safe_load(read_text(self.profiles_path)) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{self.profiles_path} must contain a YAML mapping")
        return loaded

    def next_task_id(self, tasks: Iterable[dict[str, Any]]) -> str:
        self.ensure_layout()
        highest = 0
        for task in tasks:
            highest = max(highest, max_task_id(str(task.get("id", ""))))
        for path in sorted(self.log_dir.glob("*.md")):
            highest = max(highest, max_task_id(read_text(path)))
        return f"t-{highest + 1:04d}"

    def append_inbox(self, text: str, when: datetime | None = None) -> None:
        self.ensure_layout()
        when = when or datetime.now()
        append_text(self.inbox_path, f"- {when:%Y-%m-%d %H:%M} {text}\n")
        auto_commit(self.root, "Capture OpenFin inbox item")

    def write_inbox_lines(self, lines: list[str]) -> None:
        self.ensure_layout()
        text = ("\n".join(lines) + "\n") if lines else ""
        write_text_atomic(self.inbox_path, text)
        auto_commit(self.root, "Update OpenFin inbox")

    def current_log_path(self, when: datetime | None = None) -> Path:
        when = when or datetime.now()
        return self.log_dir / f"{when:%Y-%m}.md"

    def append_log_entry(self, body: str, when: datetime | None = None) -> None:
        self.ensure_layout()
        when = when or datetime.now()
        path = self.current_log_path(when)
        existing = read_text(path) if path.exists() else ""
        header = f"## {when:%Y-%m-%d}"
        prefix = ""
        if existing and not existing.endswith("\n"):
            prefix += "\n"
        if header not in existing:
            if existing:
                prefix += "\n"
            prefix += f"{header}\n\n"
        append_text(path, f"{prefix}- {when:%H:%M} {body}\n")
        auto_commit(self.root, "Append OpenFin log entry")

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
            for line_number, raw_line in enumerate(
                read_text(path).splitlines(), start=1
            ):
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
                if tag_marker and not line_has_tag(line, tag_marker):
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

    def log_entries(
        self,
        *,
        tags: list[str] | str,
        limit: int | None = None,
        on_date: date | None = None,
    ) -> list[LogEntry]:
        self.ensure_layout()
        want_all = tags == "all"
        tag_markers = [] if want_all else [tag.lstrip("#") for tag in tags]
        entries: list[LogEntry] = []

        for path in sorted(self.log_dir.glob("*.md")):
            current_day: date | None = None
            for line_number, line in enumerate(read_text(path).splitlines(), start=1):
                if line.startswith("## "):
                    current_day = parse_log_header_date(line)
                    continue
                if not line.startswith("- "):
                    continue
                if on_date and current_day != on_date:
                    continue
                if not want_all and not any(
                    line_has_tag(line, marker) for marker in tag_markers
                ):
                    continue
                entries.append(
                    LogEntry(
                        source=f"log/{path.name}",
                        line_number=line_number,
                        line=line,
                        entry_date=current_day,
                    )
                )

        entries.sort(
            key=lambda entry: (
                entry.entry_date or date.min,
                entry.source,
                entry.line_number,
            ),
            reverse=True,
        )
        return entries[:limit] if limit is not None else entries

    def recent_log_entries(
        self,
        *,
        tags: list[str] | str,
        limit: int,
    ) -> list[str]:
        return [entry.line for entry in self.log_entries(tags=tags, limit=limit)]

    def task_log_entries(
        self,
        task_id: str,
        *,
        tags: list[str] | str = "all",
    ) -> list[LogEntry]:
        return [
            entry
            for entry in self.log_entries(tags=tags, limit=None)
            if line_references_task(entry.line, task_id)
        ]

    def has_log_marker(self, marker: str, task_id: str) -> bool:
        needle = re.compile(
            rf"(?<![\w-])#{re.escape(marker)}\s+{re.escape(task_id)}(?![\w-])"
        )
        return any(needle.search(read_text(path)) for path in self.log_dir.glob("*.md"))


def parse_log_header_date(line: str) -> date | None:
    match = re.fullmatch(r"##\s+(\d{4}-\d{2}-\d{2})", line.strip())
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_inbox_line_date(line: str) -> date | None:
    match = re.match(r"-\s+(\d{4}-\d{2}-\d{2})\s+\d{2}:\d{2}\b", line)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def parse_now_updated(text: str) -> date | None:
    match = re.search(r"_updated:\s*(\d{4}-\d{2}-\d{2})_", text)
    if not match:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def dump_yaml(value: Any) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


def read_text(path: Path) -> str:
    return path.read_text(encoding=ENCODING)


def append_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding=ENCODING) as handle:
        handle.write(text)


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            dir=path.parent,
            delete=False,
            encoding=ENCODING,
        ) as handle:
            temp_name = handle.name
            handle.write(text)
        os.replace(temp_name, path)
    finally:
        if temp_name and Path(temp_name).exists():
            Path(temp_name).unlink()


def max_task_id(text: str) -> int:
    highest = 0
    for match in re.finditer(r"\bt-(\d{4,})\b", text):
        highest = max(highest, int(match.group(1)))
    return highest


def line_has_tag(line: str, tag: str) -> bool:
    normalized = tag.lstrip("#")
    return bool(re.search(rf"(?<![\w-])#{re.escape(normalized)}(?![\w-])", line))


def line_references_task(line: str, task_id: str) -> bool:
    return bool(re.search(rf"(?<![\w-]){re.escape(task_id)}(?![\w-])", line))
