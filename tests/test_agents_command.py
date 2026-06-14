from __future__ import annotations

from pathlib import Path

from openfin.agent_store import (
    AgentEvent,
    AgentSessionMeta,
    AgentSessionStore,
    Project,
    utc_now,
)
from tests.helpers import openfin_home, run_cli


def make_session(tmp_path: Path, session_id: str = "agent-001") -> None:
    store = AgentSessionStore(openfin_home(tmp_path))
    meta = store.create_session(
        AgentSessionMeta.new(
            session_id=session_id,
            adapter="claude",
            project=Project(name="OpenFin", root=tmp_path),
        )
    )
    store.update_meta(meta.id, status="idle", native_session_id="native-1")
    store.append_event(
        meta.id,
        AgentEvent(
            kind="assistant_text",
            text="hello from transcript",
            raw={},
            ts=utc_now(),
            session_id="native-1",
        ),
    )


def test_agents_list_status_and_show(tmp_path: Path) -> None:
    make_session(tmp_path)

    listed = run_cli(tmp_path, ["agents", "list"])
    status = run_cli(tmp_path, ["agents", "status", "agent-001"])
    shown = run_cli(tmp_path, ["agents", "show", "agent-001"])

    assert listed.exit_code == 0, listed.output
    assert status.exit_code == 0, status.output
    assert shown.exit_code == 0, shown.output
    assert "agent-001" in listed.output
    assert "claude" in listed.output
    assert "native-1" in status.output
    assert "hello from transcript" in shown.output


def test_agents_show_reports_unknown_session(tmp_path: Path) -> None:
    shown = run_cli(tmp_path, ["agents", "show", "missing"])

    assert shown.exit_code != 0
    assert "unknown agent session: missing" in shown.output
