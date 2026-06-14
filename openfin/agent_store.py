from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml

from openfin.storage import read_text, write_text_atomic


AgentStatus = Literal["idle", "busy", "waiting_input", "exited", "error"]


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_session_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"agent-{stamp}-{uuid.uuid4().hex[:8]}"


@dataclass(frozen=True)
class Project:
    name: str
    root: Path
    profile: str = "default"


@dataclass(frozen=True)
class AgentEvent:
    kind: str
    text: str
    raw: dict[str, Any]
    ts: str
    session_id: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentEvent":
        return cls(
            kind=str(data["kind"]),
            text=str(data.get("text") or ""),
            raw=dict(data.get("raw") or {}),
            ts=str(data["ts"]),
            session_id=str(data.get("session_id") or ""),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "AgentEvent":
        return cls.from_dict(json.loads(text))


@dataclass(frozen=True)
class AgentSessionMeta:
    id: str
    adapter: str
    project_name: str
    project_root: str
    status: AgentStatus
    started_at: str
    updated_at: str
    native_session_id: str | None
    transcript_path: str
    telegram_thread_id: int | None

    @classmethod
    def new(
        cls,
        *,
        adapter: str,
        project: Project,
        session_id: str | None = None,
        status: AgentStatus = "idle",
    ) -> "AgentSessionMeta":
        now = utc_now()
        return cls(
            id=session_id or new_session_id(),
            adapter=adapter,
            project_name=project.name,
            project_root=str(project.root),
            status=status,
            started_at=now,
            updated_at=now,
            native_session_id=None,
            transcript_path="",
            telegram_thread_id=None,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentSessionMeta":
        return cls(
            id=str(data["id"]),
            adapter=str(data["adapter"]),
            project_name=str(data["project_name"]),
            project_root=str(data["project_root"]),
            status=str(data.get("status") or "idle"),  # type: ignore[arg-type]
            started_at=str(data["started_at"]),
            updated_at=str(data["updated_at"]),
            native_session_id=data.get("native_session_id"),
            transcript_path=str(data.get("transcript_path") or ""),
            telegram_thread_id=data.get("telegram_thread_id"),
        )


@dataclass(frozen=True)
class AgentSessionStore:
    root: Path

    @property
    def agents_dir(self) -> Path:
        return self.root / "agents"

    @property
    def socket_path(self) -> Path:
        return self.agents_dir / "openfind.sock"

    def session_dir(self, session_id: str) -> Path:
        return self.agents_dir / session_id

    def transcript_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "transcript.jsonl"

    def meta_path(self, session_id: str) -> Path:
        return self.session_dir(session_id) / "meta.json"

    def create_session(self, meta: AgentSessionMeta) -> AgentSessionMeta:
        session_dir = self.session_dir(meta.id)
        session_dir.mkdir(parents=True, exist_ok=True)
        saved = replace(meta, transcript_path=str(self.transcript_path(meta.id)))
        self.save_meta(saved)
        if not self.transcript_path(meta.id).exists():
            write_text_atomic(self.transcript_path(meta.id), "")
        return saved

    def save_meta(self, meta: AgentSessionMeta) -> None:
        text = json.dumps(meta.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        write_text_atomic(self.meta_path(meta.id), f"{text}\n")

    def load_meta(self, session_id: str) -> AgentSessionMeta:
        return AgentSessionMeta.from_dict(
            json.loads(read_text(self.meta_path(session_id)))
        )

    def update_meta(self, session_id: str, **updates: Any) -> AgentSessionMeta:
        meta = self.load_meta(session_id)
        updated = replace(meta, updated_at=utc_now(), **updates)
        self.save_meta(updated)
        return updated

    def append_event(self, session_id: str, event: AgentEvent) -> None:
        path = self.transcript_path(session_id)
        existing = read_text(path) if path.exists() else ""
        line = event.to_json()
        text = f"{existing}{line}\n"
        write_text_atomic(path, text)

    def load_transcript(self, session_id: str) -> list[AgentEvent]:
        path = self.transcript_path(session_id)
        if not path.exists():
            return []
        return [
            AgentEvent.from_json(line)
            for line in read_text(path).splitlines()
            if line.strip()
        ]

    def list_sessions(self) -> list[AgentSessionMeta]:
        if not self.agents_dir.exists():
            return []
        sessions: list[AgentSessionMeta] = []
        for meta_path in sorted(self.agents_dir.glob("*/meta.json")):
            sessions.append(
                AgentSessionMeta.from_dict(json.loads(read_text(meta_path)))
            )
        return sorted(sessions, key=lambda meta: meta.id)


def discover_project(start: Path | None = None) -> Project:
    start_path = (start or Path.cwd()).resolve()
    search_root = start_path if start_path.is_dir() else start_path.parent
    for path in [search_root, *search_root.parents]:
        config_path = path / ".openfinrc"
        if not config_path.exists():
            continue
        loaded = yaml.safe_load(read_text(config_path)) or {}
        if not isinstance(loaded, dict):
            loaded = {}
        return Project(
            name=str(loaded.get("name") or path.name),
            root=path,
            profile=str(loaded.get("profile") or "default"),
        )
    return Project(name=search_root.name, root=search_root, profile="default")
