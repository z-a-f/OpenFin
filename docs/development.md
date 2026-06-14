# Development

This guide is for contributors changing OpenFin.

## Local Setup

Requirements:

- Python 3.12 or newer.
- `uv`.

Install dependencies:

```bash
uv sync
```

Run the CLI from the working tree:

```bash
uv run f --help
uv run openfind --help
```

Use an isolated data directory while developing:

```bash
export OPENFIN_HOME="$(pwd)/.dev-openfin"
uv run f init
```

## Test And Lint

Run all tests:

```bash
uv run pytest
```

Run coverage:

```bash
uv run pytest --cov
```

Run lint:

```bash
uv run ruff check .
```

Run the opt-in Claude binary smoke test when changing the Claude adapter and you
are willing to make a real Claude CLI request:

```bash
OPENFIN_RUN_CLAUDE_SMOKE=1 uv run pytest -q -m smoke tests/test_claude_adapter.py
```

Run the opt-in Codex binary smoke test when changing the Codex adapter and you
are willing to make a real Codex CLI request:

```bash
OPENFIN_RUN_CODEX_SMOKE=1 uv run pytest -q -m smoke tests/test_codex_adapter.py
```

Pre-commit hooks currently run whitespace checks, YAML checks, large-file
checks, Ruff linting, and Ruff formatting.

## Workflow

Prefer TDD for behavior changes:

1. Add or update the smallest failing test.
2. Run the narrow test command and confirm the failure.
3. Implement the smallest fix.
4. Re-run the targeted tests.
5. Run the broader suite and lint.

For docs-only changes, run at least a quick grep/readback and the normal test
suite when docs mention command behavior or public paths.

## Repository Layout

```text
openfin/
  cli.py              Typer app and command registration
  storage.py          OpenFin home, file helpers, search helpers
  task.py             task commands and task model helpers
  idea.py             capture, idea, triage
  context.py          context-pack assembly
  search.py           direct search command
  index.py            SQLite FTS derived index
  review.py           overdue/recheck decision loop
  compact.py          archive and redundancy/staleness checks
  digest.py           digest rendering
  delivery.py         desktop/Telegram digest delivery
  scheduler.py        cron/systemd/launchd schedule generation
  agent_store.py      agent metadata and transcript store
  agent_adapter.py    adapter protocol
  claude_adapter.py   Claude stream-json adapter
  codex_adapter.py    Codex exec JSON adapter
  agent_run.py        f --run loop
  agent_commands.py   f agents commands
  daemon.py           openfind socket daemon and client
  telegram.py         Telegram commands and polling runner
tests/
  test_*.py
docs/
  *.md
```

The project intentionally uses a flat `openfin/` package rather than a `src/`
layout.

## Adding A CLI Command

1. Put command behavior in the module that owns the domain.
2. Add or update tests near the module's existing test file.
3. Register the command in `openfin.cli`.
4. Run the narrow test file.
5. Run `uv run pytest` and `uv run ruff check .`.
6. Update docs if the command is user-facing.

Command guidelines:

- Keep output concise.
- Use `OpenFinStore.from_env()` for storage.
- Keep human-editable files canonical.
- Use `write_text_atomic()` for rewrites.
- Use UTF-8 helpers from `openfin.storage`.
- Use `markup=False` when printing user-authored text.

## Adding A Store File Or Field

When adding canonical state:

- Prefer YAML, Markdown, or JSONL over opaque formats.
- Make it understandable in a text editor.
- Add tests for read/write behavior.
- Preserve UTF-8.
- Avoid migrations until necessary; when necessary, make them explicit.

When adding derived state:

- Put it under a clearly derived path.
- Make rebuild cheap and deterministic.
- Do not make the derived file the source of truth.

## Adding A Task Behavior

Task behavior should respect:

- Active statuses: `open`, `doing`, `blocked`.
- Closed statuses: `done`, `dropped`.
- Priority values: `P0`, `P1`, `P2`, `P3`.
- Recheck semantics: future `recheck` quiets overdue surfacing.

Add regression tests for:

- The command output.
- The task YAML mutation.
- Any log entry added.
- Edge cases around dates and invalid input.

## Adding An Agent Adapter

Adapter work should start with tests for the event normalizer.

Adapter requirements:

- Use a structured API, JSON output, SDK, or local server interface.
- Do not scrape ANSI/TUI output.
- Yield normalized `AgentEvent` values.
- Preserve raw native payloads.
- Capture native resume/session ids.
- Implement `interrupt()` and `status()` honestly.

Then:

1. Implement `openfin/<tool>_adapter.py`.
2. Add tests for command construction and event normalization.
3. Register the adapter in `openfin.agent_run.create_adapter()`.
4. Extend `parse_run_args()` only with safe options.
5. Add run-loop tests with a fake adapter.
6. Update `docs/usage.md`, `docs/architecture.md`, and `docs/sdk.md`.

## Working On openfind

The daemon has two testable layers:

- `OpenFindDaemon.handle()` for pure request/response behavior.
- `create_daemon_server()` and `DaemonClient` for socket behavior.

Prefer pure handler tests for most behavior. Add socket tests for protocol
framing, stale socket handling, and client wrappers.

The daemon should keep only live routing in memory. Durable state belongs in
`AgentSessionStore`.

## Working On Telegram

Telegram behavior should be testable without network access:

- Inject a fake client with `send_message()`.
- Test command parsing through `TelegramBot.handle_update()`.
- Test daemon queue effects with `OpenFindDaemon.handle()`.
- Keep authorization behavior explicit.

The daemon owns the Telegram long-poll consumer. Do not add polling to `f --run`.

## Docs Changes

When changing behavior, update the docs that match the user-facing surface:

- CLI workflow: `docs/usage.md`.
- Module boundaries or data flow: `docs/architecture.md`.
- Python extension points: `docs/sdk.md`.
- Developer workflow: `docs/development.md`.
- Daemon, schedules, security, backups: `docs/operations.md`.
- Short entrypoint summary: `README.md`.

Keep README concise and use `docs/` for detail.
