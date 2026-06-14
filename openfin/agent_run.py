from __future__ import annotations

import os
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

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
from openfin.codex_adapter import CodexAdapter
from openfin.context import assemble_context_pack
from openfin.daemon import connect_daemon
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
NO_INPUT = object()


class AgentDaemonClient(Protocol):
    def register_session(
        self,
        meta: AgentSessionMeta,
        *,
        pid: int | None = None,
    ) -> None: ...

    def update_status(self, session_id: str, status: str) -> None: ...

    def record_event(self, session_id: str, event: AgentEvent) -> None: ...

    def poll_input(self, session_id: str) -> list[dict[str, str]]: ...

    def unregister_session(self, session_id: str, *, status: str) -> None: ...


class BackgroundInput:
    def __init__(self, input_func: Callable[[str], str]) -> None:
        self._input_func = input_func
        self._queue: queue.Queue[str | BaseException] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self, prompt: str) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._read,
            args=(prompt,),
            daemon=True,
        )
        self._thread.start()

    def poll(self) -> str | BaseException | object:
        try:
            return self._queue.get_nowait()
        except queue.Empty:
            return NO_INPUT

    def _read(self, prompt: str) -> None:
        try:
            self._queue.put(self._input_func(prompt))
        except BaseException as exc:
            self._queue.put(exc)


def parse_run_args(args: list[str]) -> RunArgs:
    if not args:
        raise typer.BadParameter("--run requires an adapter name")
    adapter = args[0]
    if adapter not in {"claude", "codex"}:
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
    agent_store = AgentSessionStore(openfin_store.root)
    daemon_client = connect_daemon(agent_store)
    if daemon_client is None:
        console.print("openfind unavailable; continuing local-only", markup=False)
    run_agent_session(
        adapter=adapter,
        project=project,
        store=agent_store,
        initial_prompt=parsed.initial_prompt,
        model=parsed.model,
        resume_id=parsed.resume_id,
        system_context=system_context,
        input_func=lambda prompt: typer.prompt(prompt, prompt_suffix=""),
        output_func=lambda text: console.print(text, markup=False),
        daemon_client=daemon_client,
    )


def create_adapter(name: str) -> AgentAdapter:
    if name == "claude":
        return ClaudeAdapter()
    if name == "codex":
        return CodexAdapter()
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
    daemon_client: AgentDaemonClient | None = None,
) -> AgentSessionMeta:
    meta = store.create_session(
        AgentSessionMeta.new(
            adapter=adapter.name,
            project=project,
        )
    )
    current_resume_id = resume_id
    daemon_active = daemon_client is not None
    background_input = BackgroundInput(input_func)

    def daemon_call(action: Callable[[AgentDaemonClient], object]) -> object | None:
        nonlocal daemon_active
        if not daemon_active or daemon_client is None:
            return None
        try:
            return action(daemon_client)
        except Exception as exc:  # pragma: no cover - defensive local-only fallback
            daemon_active = False
            output_func(f"openfind unavailable; continuing local-only ({exc})")
            return None

    daemon_call(lambda client: client.register_session(meta, pid=os.getpid()))

    def run_turn(prompt: str, resume: str | None) -> str | None:
        nonlocal meta
        store.update_meta(meta.id, status="busy")
        daemon_call(lambda client: client.update_status(meta.id, "busy"))
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
            daemon_call(lambda client, event=event: client.record_event(meta.id, event))
            if event.session_id:
                last_session_id = event.session_id
                meta = store.update_meta(meta.id, native_session_id=last_session_id)
            if event.kind == "error":
                had_error = True
            rendered = render_agent_event(event)
            if rendered:
                output_func(rendered)
        meta = store.update_meta(meta.id, status="error" if had_error else "idle")
        daemon_call(lambda client: client.update_status(meta.id, meta.status))
        return last_session_id

    def process_daemon_input() -> bool:
        nonlocal current_resume_id
        items = daemon_call(lambda client: client.poll_input(meta.id))
        if not isinstance(items, list):
            return False
        should_stop = False
        for item in items:
            item_type = item.get("type")
            source = item.get("source") or "remote"
            if item_type == "message":
                text = (item.get("text") or "").strip()
                if not text:
                    continue
                output_func(f"{source}> {text}")
                current_resume_id = run_turn(text, current_resume_id)
            elif item_type == "interrupt":
                adapter.interrupt()
                output_func(f"{source}> interrupt")
            elif item_type == "stop":
                output_func(f"{source}> stop")
                should_stop = True
        return should_stop

    def read_user_input() -> tuple[str | None, bool]:
        if not daemon_active:
            return input_func("openfin> "), False
        background_input.start("openfin> ")
        while True:
            result = background_input.poll()
            if result is not NO_INPUT:
                if isinstance(result, BaseException):
                    raise result
                return result, False
            if process_daemon_input():
                return None, True
            time.sleep(0.05)

    if initial_prompt:
        current_resume_id = run_turn(initial_prompt, current_resume_id)

    while True:
        if process_daemon_input():
            break
        try:
            user_input, should_stop = read_user_input()
        except (EOFError, KeyboardInterrupt):
            output_func("exiting")
            break
        if should_stop:
            break
        user_input = (user_input or "").strip()
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
    daemon_call(lambda client: client.unregister_session(meta.id, status=meta.status))
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
