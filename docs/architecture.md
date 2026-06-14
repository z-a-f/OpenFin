# Architecture

OpenFin is designed around a small local-first rule: durable state belongs in
files, and derived or live state must be rebuildable.

## Component Map

Primary CLI entrypoints:

- `f`: user-facing CLI, implemented in `openfin.cli`.
- `openfin`: alias for `f`.
- `openfind`: local agent daemon, implemented in `openfin.daemon`.

Core modules:

- `openfin.storage`: OpenFin home layout, UTF-8 file helpers, task/log search.
- `openfin.versioning`: Git initialization and best-effort auto-commits for
  managed store changes.
- `openfin.task`: structured task commands and task lifecycle helpers.
- `openfin.idea`: inbox capture, idea logging, and inbox triage.
- `openfin.context`: context-pack assembly from charter, now, tasks, logs, and
  topic hits.
- `openfin.search`: direct text search command.
- `openfin.index`: rebuildable SQLite FTS index.
- `openfin.review`: overdue/recheck decision loop.
- `openfin.compact`: archive old closed tasks and detect stale/redundant work.
- `openfin.digest`: morning/evening digest rendering.
- `openfin.delivery`: desktop and Telegram digest delivery.
- `openfin.scheduler`: cron, systemd-user, and launchd schedule generation.
- `openfin.agent_store`: agent session metadata and transcripts.
- `openfin.agent_adapter`: agent adapter protocol.
- `openfin.claude_adapter`: Claude headless stream-json adapter.
- `openfin.agent_run`: `f --run` argument parsing and local agent turn loop.
- `openfin.daemon`: Unix-socket daemon protocol and daemon client.
- `openfin.telegram`: Telegram command and relay layer.

## Storage Layout

`OpenFinStore.from_env()` chooses the root:

1. `OPENFIN_HOME`, if set.
2. `~/.openfin`, otherwise.

The root contains canonical human-editable files:

```text
~/.openfin/
  .git/
  .gitignore
  charter.md
  now.md
  tasks.yaml
  inbox.md
  profiles.yaml
  log/
    2026-06.md
```

Derived or agent-specific files live nearby:

```text
~/.openfin/
  .openfin/
    index.sqlite3
  agents/
    openfind.sock
    agent-YYYYMMDD-HHMMSS-xxxxxxxx/
      meta.json
      transcript.jsonl
```

The project avoids hidden compatibility paths. `FOUNDER_HOME` is intentionally
ignored.

## Version-Controlled History

OpenFin treats `OPENFIN_HOME` as a local Git repository by default. During
layout creation it runs `git init`, writes or merges the required `.gitignore`
rules, configures a local OpenFin commit identity when the repo has none, and
commits the initial files.

Automatic commits are created after managed writes:

- task rewrites in `tasks.yaml`
- inbox appends and rewrites
- monthly log appends
- agent session metadata
- agent transcript appends

The auto-commit path stages only OpenFin-managed paths:

```text
.gitignore
charter.md
now.md
tasks.yaml
inbox.md
profiles.yaml
log/
agents/
```

Derived and live files are ignored:

```text
.openfin/
agents/openfind.sock
```

Git automation is best-effort. If `git` is unavailable or a local git command
fails, OpenFin still completes the file write. Set `OPENFIN_GIT=0` to disable
initialization and commits, or `OPENFIN_GIT_AUTO_COMMIT=0` to keep the repo but
disable automatic commits.

## File Reliability

OpenFin writes source files in UTF-8. Structured rewrites go through
`write_text_atomic()`, which writes a temporary file in the target directory and
then replaces the target with `os.replace()`.

Important consequences:

- A killed process is less likely to leave a truncated YAML/JSON file.
- Non-ASCII text is preserved for human readability.
- Files remain easy to inspect, diff, back up, and edit manually.

Append-only log writes use UTF-8 append mode.

## Command Flow

Most CLI commands follow the same pattern:

1. Resolve the OpenFin home with `OpenFinStore.from_env()`.
2. Ensure the layout exists when reading/writing canonical files.
3. Load plain text or YAML.
4. Make a narrow mutation.
5. Save atomically or append a dated log entry.
6. Auto-commit managed changes when Git automation is enabled.
7. Print a short human-facing result.

Examples:

- `f add` loads `tasks.yaml`, creates a task via `build_task()`, saves the list.
- `f done` updates one task, clears `recheck`, saves tasks, and appends `#done`.
- `f context` reads charter/now/tasks/logs and renders a text pack.
- `f index rebuild` reads source files and rebuilds derived SQLite FTS state.

## Task And Review Model

Tasks are dictionaries in `tasks.yaml`. Active statuses are `open`, `doing`, and
`blocked`; closed statuses are `done` and `dropped`.

The review loop uses two dates:

- `due`: when the task should be complete.
- `recheck`: when a committed overdue task should resurface.

If `recheck` is in the future, overdue surfacing is quieted until that date.
This lets the user make a commitment without being nagged every day.

## Context-Pack Flow

`assemble_context_pack()` combines:

- Selected charter sections from `charter.md`.
- Full `now.md`.
- Active tasks filtered by profile task tags.
- Recent log entries filtered by profile log tags.
- Optional topic hits from direct search.

Profiles live in `profiles.yaml`:

```yaml
code:
  charter_sections:
    - Stack
    - Key decisions
    - Non-goals
  task_tags:
    - code
    - eng
    - infra
  log_tags:
    - decision
  max_log_lines: 20
```

This keeps prompt context explicit and reviewable.

## Search Architecture

OpenFin has two search paths:

- Direct search through `OpenFinStore.search()`.
- Indexed search through `openfin.index`.

The SQLite index is derived from the same text files. `source_hash()` hashes all
source file contents, and `ensure_current_index()` rebuilds stale indexes before
indexed search.

The canonical data remains the plain-text store, not SQLite.

## Agent Architecture

Agent support is split into five layers:

1. `AgentAdapter`: protocol for a tool-specific driver.
2. Adapter implementation: currently `ClaudeAdapter`.
3. `AgentSessionStore`: durable metadata and transcript storage.
4. `run_agent_session()`: local turn loop and transcript writer.
5. `openfind`: daemon for cross-process routing and Telegram ownership.

### Event Vocabulary

Adapters normalize native tool output into `AgentEvent`:

- `assistant_text`
- `tool_use`
- `tool_result`
- `turn_done`
- `needs_input`
- `progress`
- `error`

Every event stores human-facing `text`, original `raw` payload, timestamp `ts`,
and adapter-native `session_id` when available.

### Claude Adapter

The current Claude adapter is the v0 headless one-shot path:

```text
claude -p --output-format stream-json [--resume ID] [--model MODEL] [--append-system-prompt CONTEXT] PROMPT
```

It parses JSONL from stdout, maps each native message into `AgentEvent`, and
captures the native `session_id` for future resume.

## Daemon Architecture

`openfind` is a local Unix-socket daemon. The socket path is:

```text
OPENFIN_HOME/agents/openfind.sock
```

The protocol is JSON-lines over the socket. Each request and response is one
JSON object followed by a newline.

Core request types:

- `ping`
- `register_session`
- `list_sessions`
- `status`
- `update_status`
- `session_event`
- `send_input`
- `interrupt`
- `stop`
- `poll_input`
- `unregister_session`

The daemon keeps live routing and inbound queues in memory. Durable session
state still lives in `meta.json` and `transcript.jsonl`.

## Telegram Ownership

Telegram long polling is owned by the daemon, not by `f --run`. This matters
because a Telegram bot token can only have one long-poll consumer.

Flow:

1. `openfind` starts.
2. If Telegram env vars are present, it starts `TelegramBotRunner`.
3. Telegram commands call `OpenFindDaemon.handle()`.
4. `f --run` polls the daemon queue while the local prompt waits.
5. Agent events are passed through daemon event sinks to Telegram.

Only the configured Telegram user id is allowed to issue commands. Unknown
users are ignored.

## Scheduling Architecture

Scheduled digests are generated for:

- `cron`
- `systemd` user timers
- `launchd`

Generated schedule commands run:

```text
python -m openfin digest morning --send <target>
python -m openfin digest evening --send <target>
```

The schedule embeds `OPENFIN_HOME` so scheduled jobs use the same store as the
interactive CLI.

## Design Principles

- Plain text is canonical.
- Derived state is rebuildable.
- Long-lived network ownership belongs to one daemon.
- Agent tool output must come from structured/headless interfaces, not ANSI/TUI
  scraping.
- Security is part of the feature, because Telegram relay is remote control of
  a machine running agents.
