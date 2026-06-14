from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import typer

from openfin.agent_adapter import AgentAdapter
from openfin.agent_store import (
    AgentEvent,
    AgentSessionMeta,
    AgentSessionStore,
    Project,
    discover_project,
)
from openfin.claude_adapter import ClaudeAdapter
from openfin.context import assemble_context_pack
from openfin.storage import OpenFinStore
from openfin.ui import console


@dataclass(frozen=True)
class RunArgs:
    adapter: str
    model: str | None
    resume_id: str | None
    profile: str
    topic: str | None
    initial_prompt: str | None


SAFE_RUN_OPTIONS = {"--model", "--resume", "--profile", "--for"}


def parse_run_args(args: list[str]) -> RunArgs:
    if not args:
        raise typer.BadParameter("--run requires an adapter name")
    adapter = args[0]
    if adapter != "claude":
        raise typer.BadParameter(f"unsupported --run adapter: {adapter}")

    model: str | None = None
    resume_id: str | None = None
    profile = "default"
    topic: str | None = None
    prompt_parts: list[str] = []

    index = 1
    while index < len(args):
        token = args[index]
        if token in SAFE_RUN_OPTIONS:
            if index + 1 >= len(args):
                raise typer.BadParameter(f"{token} requires a value")
            value = args[index + 1]
            if token == "--model":
                model = value
            elif token == "--resume":
                resume_id = value
            elif token == "--profile":
                profile = value
            elif token == "--for":
                topic = value
            index += 2
            continue
        if token.startswith("--"):
            raise typer.BadParameter(f"unsupported --run option: {token}")
        prompt_parts.extend(args[index:])
        break

    prompt = " ".join(prompt_parts).strip() or None
    return RunArgs(
        adapter=adapter,
        model=model,
        resume_id=resume_id,
        profile=profile,
        topic=topic,
        initial_prompt=prompt,
    )


def run_agent_from_cli(args: list[str]) -> None:
    parsed = parse_run_args(args)
    openfin_store = OpenFinStore.from_env()
    project = discover_project(Path.cwd())
    system_context = assemble_context_pack(
        openfin_store,
        profile_name=parsed.profile,
        topic=parsed.topic,
    )
    adapter = create_adapter(parsed.adapter)
    run_agent_session(
        adapter=adapter,
        project=project,
        store=AgentSessionStore(openfin_store.root),
        initial_prompt=parsed.initial_prompt,
        model=parsed.model,
        resume_id=parsed.resume_id,
        system_context=system_context,
        input_func=lambda prompt: typer.prompt(prompt, prompt_suffix=""),
        output_func=lambda text: console.print(text, markup=False),
    )


def create_adapter(name: str) -> AgentAdapter:
    if name == "claude":
        return ClaudeAdapter()
    raise typer.BadParameter(f"unsupported adapter: {name}")


def run_agent_session(
    *,
    adapter: AgentAdapter,
    project: Project,
    store: AgentSessionStore,
    initial_prompt: str | None,
    model: str | None,
    resume_id: str | None,
    system_context: str | None,
    input_func: Callable[[str], str],
    output_func: Callable[[str], None],
) -> AgentSessionMeta:
    meta = store.create_session(
        AgentSessionMeta.new(
            adapter=adapter.name,
            project=project,
        )
    )
    current_resume_id = resume_id

    def run_turn(prompt: str, resume: str | None) -> str | None:
        nonlocal meta
        store.update_meta(meta.id, status="busy")
        last_session_id = resume
        had_error = False
        for event in adapter.run_turn(
            project=project,
            prompt=prompt,
            resume_id=resume,
            model=model,
            system_context=system_context,
        ):
            store.append_event(meta.id, event)
            if event.session_id:
                last_session_id = event.session_id
                meta = store.update_meta(meta.id, native_session_id=last_session_id)
            if event.kind == "error":
                had_error = True
            rendered = render_agent_event(event)
            if rendered:
                output_func(rendered)
        meta = store.update_meta(meta.id, status="error" if had_error else "idle")
        return last_session_id

    if initial_prompt:
        current_resume_id = run_turn(initial_prompt, current_resume_id)

    while True:
        try:
            user_input = input_func("openfin> ").strip()
        except (EOFError, KeyboardInterrupt):
            output_func("exiting")
            break
        if not user_input:
            continue
        if user_input in {"/exit", "/quit"}:
            break
        if user_input == "/status":
            output_func(f"status: {adapter.status()}")
            continue
        if user_input == "/interrupt":
            adapter.interrupt()
            output_func("interrupt sent")
            continue
        current_resume_id = run_turn(user_input, current_resume_id)

    meta = store.update_meta(meta.id, status="exited")
    write_agent_memory_log(store, meta)
    return meta


def render_agent_event(event: AgentEvent) -> str:
    if event.kind == "assistant_text":
        return event.text
    if event.kind == "tool_use":
        return event.text
    if event.kind == "tool_result":
        return event.text
    if event.kind == "needs_input":
        return event.text
    if event.kind == "error":
        return f"error: {event.text}"
    if event.kind == "turn_done":
        return event.text
    if event.kind == "progress":
        return event.text
    return event.text


def write_agent_memory_log(store: AgentSessionStore, meta: AgentSessionMeta) -> None:
    openfin_store = OpenFinStore(store.root)
    transcript_path = meta.transcript_path or str(store.transcript_path(meta.id))
    openfin_store.append_log_entry(
        f"#agent {meta.id} {meta.adapter} ended status {meta.status} transcript {transcript_path}"
    )
