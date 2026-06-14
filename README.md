# OpenFin

OpenFin is a local-first founder helper CLI for keeping project memory, tasks,
captures, and AI context packs in plain text.

It also wraps agent CLI sessions through `f --run`, records normalized
transcripts, and can relay session updates through the local `openfind` daemon
and Telegram.

## Documentation

- [Usage](docs/usage.md): day-to-day commands and workflows.
- [Architecture](docs/architecture.md): storage, modules, daemon routing, and
  agent instrumentation.
- [SDK](docs/sdk.md): Python APIs and extension points.
- [Development](docs/development.md): setup, tests, TDD, and contribution
  workflow.
- [Operations](docs/operations.md): daemon, Telegram, schedules, backups, and
  security.

## Install

```bash
uv sync
uv run pytest
uv run f --help
```

Set `OPENFIN_HOME` to choose the storage directory. If it is not set, OpenFin
uses `~/.openfin`.

OpenFin initializes a local Git repository in `OPENFIN_HOME` by default and
commits managed text changes as you work, so the plain-text history is preserved.
Use `uv run f init --no-git` for a one-time skip, or set `OPENFIN_GIT=0` to
disable Git automation.

## Quick Start

```bash
uv run f init
git -C "${OPENFIN_HOME:-$HOME/.openfin}" log --oneline
uv run f in "raw thing to remember"
uv run f add "ship the context command" -p P1 -d tomorrow -t code
uv run f assign t-0001 alex --note "handoff"
uv run f touch t-0001 --note "made progress"
uv run f idea "profiles are the cost-control lever" -t decision
uv run f search "profiles"
uv run f index rebuild
uv run f search "profiles" --index
uv run f context code --for "profiles"
uv run f today
uv run f compact --deep-dedup
```

## Core Concepts

- `charter.md`: durable mission, stack, decisions, and non-goals.
- `now.md`: current priorities and active context.
- `tasks.yaml`: structured tasks with priority, owner, due date, status, tags,
  and recheck state.
- `inbox.md`: raw capture buffer for later triage.
- `log/YYYY-MM.md`: append-only dated log entries.
- `profiles.yaml`: context-pack slicing rules.

## Agent Sessions

OpenFin can wrap an agent CLI so the conversation is logged, resumable by the
agent's native session id, and reachable through the local `openfind` daemon.

```bash
uv run f --run claude --model sonnet "review the open tasks and pick the next one"
uv run f agents list
uv run f agents show agent-20260614-120000-abcd1234 --last 20
```

`f --run claude ...` injects the current OpenFin context pack, stores normalized
events under `OPENFIN_HOME/agents/<session>/transcript.jsonl`, and writes a
`#agent` pointer into the normal log when the session exits. The `openfind`
daemon is started automatically when possible; you can also run it directly:

```bash
uv run openfind
```

Telegram relay is enabled when `openfind` sees these variables:

```bash
export OPENFIN_TELEGRAM_BOT_TOKEN=...
export OPENFIN_TELEGRAM_ALLOWED_USER_ID=123456789
export OPENFIN_TELEGRAM_CHAT_ID=123456789
```

Supported Telegram commands:

- `/sessions`
- `/status <session>`
- `/s <session> <message>`
- `/interrupt <session>`
- `/stop <session>`

Only `OPENFIN_TELEGRAM_ALLOWED_USER_ID` is allowed to control the daemon; other
users are ignored. Treat this bot as remote control of your machine: do not relay
secrets, keep the bot token private, and run long-lived sessions inside
tmux/screen if you plan to close the terminal.

## Scheduled Digests

```bash
uv run f digest morning --send desktop
uv run f digest evening --send telegram
uv run f schedule show --target cron --send both
uv run f schedule install --send desktop
```

Telegram delivery requires `OPENFIN_TELEGRAM_BOT_TOKEN` and
`OPENFIN_TELEGRAM_CHAT_ID`. Desktop delivery uses `notify-send` on Linux and
`osascript` on macOS.

## Development

```bash
uv sync
uv run pytest
uv run pytest --cov
uv run ruff check .
```

See [docs/development.md](docs/development.md) for the contributor workflow.
