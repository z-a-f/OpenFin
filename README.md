# OpenFin

OpenFin is a local-first founder helper CLI for keeping project memory, tasks,
captures, and AI context packs in plain text. The name nods to OpenClaw while
keeping a little Shark DNA: `sharkgpt` remains available as a legacy alias, but
`openfin` and `f` are the primary commands.

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
uv run f idea "profiles are the cost-control lever" -t decision
uv run f search "profiles"
uv run f context code --for "profiles"
uv run f today
```
