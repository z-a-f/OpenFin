# OpenFin

OpenFin is a local-first founder helper CLI for keeping project memory, tasks,
captures, and AI context packs in plain text.

Phase 1 follows `founder-cli-spec.md`: Markdown and YAML are canonical,
commands parse files on each run, and the base CLI makes no API calls.

## Development

```bash
uv sync
uv run pytest
uv run f --help
```

Set `OPENFIN_HOME` to choose the storage directory. `FOUNDER_HOME` is still
accepted as a compatibility fallback. If neither is set, OpenFin uses
`~/openfin`.

## First Run

```bash
uv run f init
uv run f in "raw thing to remember"
uv run f add "ship the context command" -p P1 -d tomorrow -t code
uv run f touch t-0001 --note "made progress"
uv run f idea "profiles are the cost-control lever" -t decision
uv run f search "profiles"
uv run f context code --for "profiles"
uv run f today
```

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
