# Operations

This guide covers running OpenFin day to day, managing local state, scheduling
digests, and operating the agent daemon safely.

## OpenFin Home

Default:

```text
~/.openfin
```

Override:

```bash
export OPENFIN_HOME="$HOME/path/to/openfin-state"
```

The OpenFin home is the backup boundary. If you copy it, you copy the user
memory, tasks, logs, context profiles, search index, and agent transcripts.

## Version-Controlled History

`f init` creates a local Git repository in `OPENFIN_HOME` by default. OpenFin
then commits managed text changes as commands run, so the project memory has a
durable local history without requiring a separate workflow.

Inspect the history:

```bash
git -C "${OPENFIN_HOME:-$HOME/.openfin}" log --oneline
```

Check for uncommitted local edits:

```bash
git -C "${OPENFIN_HOME:-$HOME/.openfin}" status
```

OpenFin stages only managed files:

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

The `.gitignore` keeps derived and live files out of history:

```text
.openfin/
agents/openfind.sock
```

If `.gitignore` already exists, OpenFin preserves existing entries and appends
the missing OpenFin rules.

Skip Git for one initialization:

```bash
uv run f init --no-git
```

Disable Git automation entirely:

```bash
export OPENFIN_GIT=0
```

Keep the repository but stop automatic commits:

```bash
export OPENFIN_GIT_AUTO_COMMIT=0
```

Git automation is best-effort. If `git` is missing or a local Git command
fails, OpenFin still writes the source file and continues.

## Backups

Recommended backup set:

```text
.git/
charter.md
now.md
tasks.yaml
inbox.md
profiles.yaml
log/
agents/*/meta.json
agents/*/transcript.jsonl
```

The following are derived or live files:

```text
.openfin/index.sqlite3
agents/openfind.sock
```

They can be rebuilt or recreated.

## Rebuilding Search

If indexed search looks stale or broken:

```bash
uv run f index status
uv run f index rebuild
```

The direct search path does not need the index:

```bash
uv run f search "query"
```

## Running openfind

`openfind` owns live agent routing and Telegram polling.

Run manually:

```bash
uv run openfind
```

Use a custom socket path for debugging:

```bash
uv run openfind --socket /tmp/openfind.sock
```

`f --run` calls `connect_daemon()` and attempts to autostart `openfind` when it
cannot connect to the default socket.

## Daemon State

Durable state:

- Session metadata in `agents/<session>/meta.json`.
- Transcripts in `agents/<session>/transcript.jsonl`.
- Final `#agent` pointer in `log/YYYY-MM.md`.

Live daemon-only state:

- Session routing map.
- Per-session inbound queues.
- Telegram polling thread.
- Event sinks.

If the daemon exits, durable transcripts remain. Live queues are lost.

## Telegram Setup

Set:

```bash
export OPENFIN_TELEGRAM_BOT_TOKEN=...
export OPENFIN_TELEGRAM_ALLOWED_USER_ID=123456789
export OPENFIN_TELEGRAM_CHAT_ID=123456789
```

`OPENFIN_TELEGRAM_ALLOWED_USER_ID` is the security gate. Messages from other
Telegram users are ignored.

`OPENFIN_TELEGRAM_CHAT_ID` is where agent event relays are sent. For a private
one-person setup, it is usually the same value as the allowed user id.

Start the daemon:

```bash
uv run openfind
```

Available Telegram commands:

- `/sessions`
- `/status <session>`
- `/s <session> <message>`
- `/interrupt <session>`
- `/stop <session>`

Session tokens can be full ids or unambiguous prefixes.

## Telegram Security

Treat the Telegram bot as remote control of a local machine that may run agents,
execute commands, read files, and spend API money.

Minimum precautions:

- Keep the bot token private.
- Use `OPENFIN_TELEGRAM_ALLOWED_USER_ID`.
- Use a private chat id unless you have a clear reason not to.
- Do not relay secrets through Telegram.
- Be careful with agent permission modes in underlying tools.
- Use two-factor authentication on the Telegram account.
- Stop the daemon when you do not need remote control.

OpenFin silently ignores unauthorized Telegram users. It does not currently
provide multi-user authorization, audit approvals, or fine-grained command
permissions.

## Agent Session Operations

Start a session:

```bash
uv run f --run claude --model sonnet "summarize today's context"
```

Inspect sessions:

```bash
uv run f agents list
uv run f agents status <session-id>
uv run f agents show <session-id> --last 50
```

Use tmux or screen for long-lived terminal sessions:

```bash
tmux new -s openfin-agent
uv run f --run claude "work through the review queue"
```

Current limitation: OpenFin does not yet own detached agent processes. Closing
the terminal that runs `f --run` can still stop that session.

## Scheduled Digests

Preview:

```bash
uv run f schedule show --target auto --send desktop
```

Install:

```bash
uv run f schedule install --target auto --send desktop
```

Uninstall:

```bash
uv run f schedule uninstall --target auto
```

Targets:

- `auto`: `launchd` on macOS, `systemd` on Linux when `systemctl` is available,
  otherwise `cron`.
- `cron`
- `systemd`
- `launchd`

Delivery:

- `desktop`: Linux `notify-send` or macOS `osascript`.
- `telegram`: Telegram Bot API.
- `both`: desktop and Telegram.
- `none`: render only.

Scheduled commands embed `OPENFIN_HOME`, so they keep using the store selected
when the schedule was generated.

## Troubleshooting

### `f --run` says openfind is unavailable

The local agent session continues without daemon routing. To investigate:

```bash
uv run openfind
```

Check whether the socket path exists:

```bash
ls -la "$OPENFIN_HOME/agents"
```

If `OPENFIN_HOME` is unset, use `~/.openfin/agents`.

### Telegram commands do nothing

Check:

- `openfind` is running.
- `OPENFIN_TELEGRAM_BOT_TOKEN` is set in the daemon environment.
- `OPENFIN_TELEGRAM_ALLOWED_USER_ID` matches your Telegram user id.
- `OPENFIN_TELEGRAM_CHAT_ID` is where responses should be sent.
- No other process is long-polling the same bot token.

### Indexed search disagrees with direct search

Rebuild:

```bash
uv run f index rebuild
```

Then compare:

```bash
uv run f search "term"
uv run f search "term" --index
```

### Hand-edited task dates look wrong

Run:

```bash
uv run f today
```

OpenFin reports bad dates instead of crashing in normal task views. Fix invalid
date strings in `tasks.yaml`.
