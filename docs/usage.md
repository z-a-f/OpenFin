# Usage

This guide covers the normal OpenFin command-line workflow.

## Install And Initialize

OpenFin is managed with `uv`.

```bash
uv sync
uv run f --help
uv run f init
git -C "${OPENFIN_HOME:-$HOME/.openfin}" log --oneline
```

OpenFin stores data in `~/.openfin` by default. Set `OPENFIN_HOME` to use a
different directory:

```bash
export OPENFIN_HOME="$HOME/work/openfin-state"
```

`FOUNDER_HOME` is not supported. `OPENFIN_HOME` is the only environment variable
used for the OpenFin data directory.

`f init` initializes a local Git repository in `OPENFIN_HOME` by default and
creates the first commit for the base layout. OpenFin then auto-commits managed
changes to tasks, inbox, logs, and agent transcripts as commands run.

Opt out for one initialization run:

```bash
uv run f init --no-git
```

Disable Git automation for a process or shell:

```bash
export OPENFIN_GIT=0
```

Keep git initialization but disable automatic commits:

```bash
export OPENFIN_GIT_AUTO_COMMIT=0
```

## Storage Files

A freshly initialized store contains:

- `.git/`: local history for the OpenFin home, unless Git automation is disabled.
- `.gitignore`: ignores derived indexes and live sockets.
- `charter.md`: durable project/company context.
- `now.md`: current priorities and in-flight work.
- `tasks.yaml`: structured tasks.
- `inbox.md`: raw captures for later triage.
- `profiles.yaml`: context-pack profile definitions.
- `log/YYYY-MM.md`: append-only dated log entries.

Derived and agent files are also kept under the same root:

- `.openfin/index.sqlite3`: rebuildable SQLite FTS search index.
- `agents/openfind.sock`: daemon Unix socket.
- `agents/<session-id>/meta.json`: agent session metadata.
- `agents/<session-id>/transcript.jsonl`: normalized agent transcript.

## Project Binding

OpenFin discovers a project by walking upward from the current directory and
looking for `.openfinrc`.

```yaml
name: OpenFin
profile: code
```

If no `.openfinrc` exists, the current directory name becomes the project name
and the profile defaults to `default`.

## Capture And Triage

Use `f in` for low-friction capture:

```bash
uv run f in "ask Sam about investor FAQ"
```

Captured lines go to `inbox.md` with a timestamp. Later, triage them:

```bash
uv run f triage
```

Triage choices are:

- `task`: create a structured task.
- `idea`: append a `#idea` log entry.
- `decision`: append a `#decision` log entry.
- `note`: append a `#note` log entry.
- `drop`: discard the inbox item.
- `skip`: leave the line in the inbox.

## Tasks

Create a task:

```bash
uv run f add "ship context profiles" -p P1 -d tomorrow -t code -o me
```

Task fields include:

- `id`: monotonic `t-0001` style id.
- `title`: task text.
- `owner`: defaults to `me`.
- `priority`: `P0`, `P1`, `P2`, or `P3`.
- `status`: `open`, `doing`, `blocked`, `done`, or `dropped`.
- `due`: ISO date or `null`.
- `recheck`: ISO date used by the review loop.
- `tags`: list of tag strings.
- `notes`: free-form notes.

Common commands:

```bash
uv run f ls
uv run f ls --status open --tag code --owner me -p P1
uv run f do t-0001
uv run f touch t-0001 --note "drafted first pass"
uv run f assign t-0001 alex --note "needs design review"
uv run f block t-0001 "waiting on vendor"
uv run f done t-0001
uv run f drop t-0001
```

Edit task fields directly:

```bash
uv run f edit t-0001 --title "ship profile slicing" --priority P0 --due friday
uv run f edit t-0001 --status blocked --notes "Blocked on API answer"
```

If no edit flags are provided, `f edit` opens the task YAML in `$EDITOR`. If
`$EDITOR` is unset, OpenFin prints the YAML and exits without writing.

## Today, Overdue, And Review

Use `today` for the working set:

```bash
uv run f today
```

It shows overdue tasks, due-today tasks, in-flight tasks, blocked tasks, stale
task warnings, and invalid date warnings.

Use `overdue` when you only want overdue active work:

```bash
uv run f overdue
```

Use `review` for the anti-rot loop:

```bash
uv run f review
```

Review decisions:

- `commit`: set a future `recheck` date and quiet the overdue item until then.
- `snooze`: set a new due date.
- `block`: mark the task blocked and record a reason.
- `drop`: mark dropped and log `#dropped`.
- `done`: mark done and log `#done`.
- `skip`: leave it unchanged.

## Ideas And Log Entries

Append an idea directly to the monthly log:

```bash
uv run f idea "profiles are the cost-control lever" -t decision
```

Task state changes also append log entries such as `#done`, `#touch`,
`#assign`, and `#blocked`.

## Search And Index

Plain search scans source files directly:

```bash
uv run f search "profiles"
uv run f search "profiles" --tag decision --since "last week"
```

The rebuildable SQLite FTS index can speed repeated searches:

```bash
uv run f index rebuild
uv run f index status
uv run f search "profiles" --index
uv run f index search "profiles"
```

The index is derived state. It is safe to delete and rebuild.

## Context Packs

Context packs assemble project memory for AI tools:

```bash
uv run f context default
uv run f context code --for "agent routing"
uv run f context admin --budget 6000
uv run f context code --copy
```

Profiles live in `profiles.yaml` and control:

- Charter sections.
- Task tags.
- Log tags.
- Maximum recent log lines.

`--for` adds topic-specific search hits to the context pack. `--budget` prints a
warning when the rough token estimate exceeds the provided number. `--copy`
copies the pack with `pyperclip`.

## Digests And Schedules

Render a digest:

```bash
uv run f digest morning
uv run f digest evening
```

Deliver it:

```bash
uv run f digest morning --send desktop
uv run f digest evening --send telegram
uv run f digest morning --send both
```

Supported delivery targets are `none`, `desktop`, `telegram`, and `both`.

Preview or install scheduled digests:

```bash
uv run f schedule show --target auto --send desktop
uv run f schedule install --target systemd --send desktop --morning 09:00 --evening 17:30
uv run f schedule uninstall --target systemd
```

Targets are `auto`, `cron`, `systemd`, and `launchd`.

## Agent Sessions

Start an agent through OpenFin:

```bash
uv run f --run claude --model sonnet "review the open tasks and pick the next one"
```

Supported `--run` options:

- `--model <name>`: pass a model name to the adapter.
- `--resume <native-session-id>`: resume an adapter-native session.
- `--profile <profile>`: choose the context-pack profile.
- `--for <topic>`: include topic hits in the injected context pack.

Inside the local OpenFin prompt:

- `/status`: show adapter status.
- `/interrupt`: send interrupt to the adapter.
- `/exit` or `/quit`: exit the OpenFin wrapper.

Inspect saved sessions:

```bash
uv run f agents list
uv run f agents status agent-20260614-120000-abcd1234
uv run f agents show agent-20260614-120000-abcd1234 --last 20
```

`f --run` writes normalized events to `transcript.jsonl`, stores metadata in
`meta.json`, and appends a `#agent` pointer to the regular monthly log on exit.

## Telegram Relay

The daemon owns Telegram long polling. `f --run` connects to the daemon; it does
not talk to Telegram directly.

Set:

```bash
export OPENFIN_TELEGRAM_BOT_TOKEN=...
export OPENFIN_TELEGRAM_ALLOWED_USER_ID=123456789
export OPENFIN_TELEGRAM_CHAT_ID=123456789
```

Run the daemon manually, or let `f --run` autostart it:

```bash
uv run openfind
```

Telegram commands:

- `/sessions`
- `/status <session>`
- `/s <session> <message>`
- `/interrupt <session>`
- `/stop <session>`

Only `OPENFIN_TELEGRAM_ALLOWED_USER_ID` can control the daemon. Other users are
ignored.
