# SDK And Extension Points

OpenFin is primarily a CLI, but its modules are structured so new commands,
adapters, and integrations can reuse the same storage and session primitives.

The current Python API is not promised as a stable third-party package API yet.
Treat this page as the supported internal extension surface for this repository.

## Storage API

Use `OpenFinStore` for canonical project memory.

```python
from openfin.storage import OpenFinStore

store = OpenFinStore.from_env()
store.ensure_layout()
tasks = store.load_tasks()
store.append_log_entry("#note investigated onboarding flow")
```

Important fields:

- `store.root`
- `store.charter_path`
- `store.now_path`
- `store.tasks_path`
- `store.inbox_path`
- `store.profiles_path`
- `store.log_dir`

Important methods:

- `ensure_layout()`
- `load_tasks()`
- `save_tasks(tasks)`
- `load_profiles()`
- `next_task_id(tasks)`
- `append_inbox(text)`
- `write_inbox_lines(lines)`
- `append_log_entry(body)`
- `iter_text_files()`
- `search(query, tag=None, since=None)`
- `log_entries(tags, limit=None, on_date=None)`
- `recent_log_entries(tags, limit)`
- `task_log_entries(task_id, tags="all")`

File helpers:

- `read_text(path)`: UTF-8 read.
- `append_text(path, text)`: UTF-8 append.
- `write_text_atomic(path, text)`: temp-file write plus `os.replace`.
- `dump_yaml(value)`: YAML with unicode preserved.

## Versioning API

Git automation lives in `openfin.versioning`.

```python
from openfin.versioning import auto_commit, ensure_git_repo

store = OpenFinStore.from_env()
store.ensure_layout()
ensure_git_repo(store.root)
auto_commit(store.root, "Update custom OpenFin extension data")
```

Useful helpers:

- `ensure_git_repo(root)`: create or reuse a local Git repository, merge the
  required `.gitignore` rules, and configure a local OpenFin identity if needed.
- `auto_commit(root, message)`: stage OpenFin-managed paths and create a commit
  when there are changes.
- `git_enabled()`: respect `OPENFIN_GIT`.
- `auto_commit_enabled()`: respect `OPENFIN_GIT` and
  `OPENFIN_GIT_AUTO_COMMIT`.

Both `ensure_git_repo()` and `auto_commit()` are best-effort and return `False`
instead of raising when Git is unavailable or a Git command fails. Source-file
writes should complete before calling `auto_commit()` so user data is not
blocked by Git.

## Task API

Task helpers live in `openfin.task`.

```python
from openfin.storage import OpenFinStore
from openfin.task import build_task, sort_tasks, active_tasks

store = OpenFinStore.from_env()
tasks = store.load_tasks()
task = build_task(store, tasks, "follow up with design partner", priority="P1")
tasks.append(task)
store.save_tasks(sort_tasks(tasks))
```

Useful helpers:

- `build_task(store, tasks, text, priority="P2", due=None, tags=None, owner="me")`
- `active_tasks(tasks)`
- `sort_tasks(tasks)`
- `find_task(tasks, task_id)`
- `format_task_line(task)`
- `append_task_log(store, marker, task, suffix="")`
- `needs_review(task, today)`
- `visible_overdue(task, today)`
- `visible_due_today(task, today)`

Validation helpers:

- `validate_priority(priority)`
- `validate_status(status)`

## Date API

Date parsing lives in `openfin.dates`.

Common helpers:

- `today_date()`
- `parse_date_input(value)`
- `task_due_date(task, field="due")`
- `invalid_task_dates(task)`

`parse_date_input()` accepts natural-language-ish strings through `dateparser`
and returns ISO dates. Hand-edited invalid dates should be handled defensively
with `task_due_date()` or `invalid_task_dates()`.

## Context-Pack API

Use `assemble_context_pack()` when another feature needs AI-ready context.

```python
from openfin.context import assemble_context_pack
from openfin.storage import OpenFinStore

pack = assemble_context_pack(
    OpenFinStore.from_env(),
    profile_name="code",
    topic="agent routing",
)
```

The function reads profiles, selected charter sections, now, active tasks,
recent logs, and optional topic hits.

## Search Index API

Direct search is available from `OpenFinStore.search()`.

Indexed search lives in `openfin.index`:

- `rebuild_index(store)`
- `index_status(store)`
- `ensure_current_index(store)`
- `search_index(store, query, tag=None, since=None)`
- `index_path(store)`

The index is derived and can be rebuilt at any time.

## Agent Data Model

Agent primitives live in `openfin.agent_store`.

```python
from openfin.agent_store import AgentEvent, AgentSessionMeta, AgentSessionStore, Project

project = Project(name="OpenFin", root=Path.cwd(), profile="code")
store = AgentSessionStore(OpenFinStore.from_env().root)
meta = store.create_session(
    AgentSessionMeta.new(adapter="claude", project=project)
)
store.append_event(
    meta.id,
    AgentEvent(
        kind="assistant_text",
        text="Hello",
        raw={},
        ts="2026-06-14T12:00:00Z",
        session_id="native-1",
    ),
)
```

Key dataclasses:

- `Project(name, root, profile="default")`
- `AgentEvent(kind, text, raw, ts, session_id)`
- `AgentSessionMeta(...)`
- `AgentSessionStore(root)`

`AgentSessionStore` methods:

- `create_session(meta)`
- `save_meta(meta)`
- `load_meta(session_id)`
- `update_meta(session_id, **updates)`
- `append_event(session_id, event)`
- `load_transcript(session_id)`
- `list_sessions()`

## Agent Adapter Protocol

Adapters implement `openfin.agent_adapter.AgentAdapter`.

```python
class AgentAdapter(Protocol):
    name: str

    def run_turn(
        self,
        *,
        project: Project,
        prompt: str,
        resume_id: str | None = None,
        model: str | None = None,
        system_context: str | None = None,
    ) -> Iterator[AgentEvent]: ...

    def interrupt(self) -> None: ...

    def status(self) -> AgentStatus: ...
```

Rules for adapters:

- Use the tool's structured/headless interface.
- Normalize every output into `AgentEvent`.
- Preserve raw native payloads in `event.raw`.
- Capture native session ids when available.
- Keep interrupt/status semantics honest. If a tool cannot interrupt a turn,
  expose that limitation through behavior and docs.

To add an adapter:

1. Create `openfin/<tool>_adapter.py`.
2. Implement `AgentAdapter`.
3. Add parser/normalizer tests for native events.
4. Register it in `create_adapter()` and `parse_run_args()`.
5. Add CLI/run-loop tests for safe options.
6. Document tool-specific caveats.

## Agent Run Loop API

`openfin.agent_run.run_agent_session()` is the reusable local session runner.
It accepts injected input/output callables and an optional daemon client, which
makes it straightforward to test without spawning real tools.

It handles:

- Session creation.
- Context injection.
- Initial prompt.
- Local prompt commands.
- Transcript writes.
- Native session id updates.
- Daemon registration/events/input polling.
- Final `#agent` log pointer.

## Daemon API

`openfin.daemon.OpenFindDaemon` is the in-process request handler. It is useful
for tests and local integrations that do not need a socket.

```python
daemon = OpenFindDaemon(AgentSessionStore(OpenFinStore.from_env().root))
response = daemon.handle({"type": "list_sessions"})
```

`DaemonClient` is the socket client:

```python
from openfin.daemon import DaemonClient

client = DaemonClient(store.socket_path)
client.ping()
client.send_input(session_id, "continue", source="telegram")
```

Useful client methods:

- `ping()`
- `register_session(meta, pid=None)`
- `list_sessions()`
- `status(session_id)`
- `update_status(session_id, status)`
- `record_event(session_id, event)`
- `send_input(session_id, text, source="local")`
- `interrupt(session_id, source="local")`
- `stop(session_id, source="local")`
- `poll_input(session_id)`
- `unregister_session(session_id, status="exited")`

Use `connect_daemon(store)` to connect to a running daemon or autostart one.

## Telegram API

Telegram integration lives in `openfin.telegram`.

Primary classes:

- `TelegramConfig`
- `TelegramApiClient`
- `TelegramBot`
- `TelegramBotRunner`

`TelegramBot` can be tested with a fake client that implements
`send_message(chat_id, text)`. The runner requires a polling client that also
implements `get_updates(offset=None, timeout=30)`.

The command layer is intentionally thin: Telegram commands translate into
daemon requests. They do not mutate files directly.

## UI API

`openfin.ui.console` is the shared Rich console. Command output should be short,
plain, and useful for terminal and test output.

Use `markup=False` when printing user/project content that might contain Rich
markup characters.

## Stability Notes

The most stable APIs today are:

- Plain file formats in the OpenFin home.
- `OpenFinStore` storage helpers.
- `AgentEvent` normalized event shape.
- `AgentAdapter` protocol.
- `DaemonClient` request methods.

Command internals may still shift as the product story evolves.
