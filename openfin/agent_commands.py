from __future__ import annotations

import typer

from openfin.agent_store import AgentSessionMeta, AgentSessionStore
from openfin.storage import OpenFinStore
from openfin.ui import console


agents_app = typer.Typer(help="Inspect saved agent sessions.")


@agents_app.command("list")
def list_agent_sessions() -> None:
    """List saved agent sessions."""
    store = AgentSessionStore(OpenFinStore.from_env().root)
    sessions = store.list_sessions()
    if not sessions:
        console.print("No agent sessions.")
        return
    for meta in sessions:
        console.print(format_agent_session(meta), markup=False)


@agents_app.command("status")
def agent_status(session_id: str) -> None:
    """Show saved agent session metadata."""
    meta = load_agent_session_or_error(session_id)
    for key, value in meta.to_dict().items():
        console.print(f"{key}: {value}", markup=False)


@agents_app.command("show")
def show_agent_session(
    session_id: str,
    last: int = typer.Option(20, "--last", help="Number of transcript events to show."),
) -> None:
    """Show a saved agent transcript."""
    store = AgentSessionStore(OpenFinStore.from_env().root)
    load_agent_session_or_error(session_id, store=store)
    events = store.load_transcript(session_id)
    for event in events[-last:]:
        console.print(f"{event.kind}: {event.text}", markup=False)


def load_agent_session_or_error(
    session_id: str,
    *,
    store: AgentSessionStore | None = None,
) -> AgentSessionMeta:
    store = store or AgentSessionStore(OpenFinStore.from_env().root)
    try:
        return store.load_meta(session_id)
    except FileNotFoundError as exc:
        raise typer.BadParameter(f"unknown agent session: {session_id}") from exc


def format_agent_session(meta: AgentSessionMeta) -> str:
    native = f" native={meta.native_session_id}" if meta.native_session_id else ""
    return f"{meta.id} {meta.adapter} {meta.status} {meta.project_name}{native}"
