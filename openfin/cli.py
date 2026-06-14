from __future__ import annotations

import sys

import typer

from openfin.agent_commands import agents_app
from openfin.agent_run import run_agent_from_cli
from openfin.compact import compact
from openfin.context import context
from openfin.digest import digest
from openfin.idea import capture, idea, triage
from openfin.index import index_app
from openfin.review import review
from openfin.scheduler import schedule_app
from openfin.search import search
from openfin.system import init
from openfin.task import (
    add,
    assign,
    block,
    done,
    drop,
    edit,
    list_tasks,
    overdue,
    start_task,
    today,
    touch,
)


app = typer.Typer(
    help="OpenFin founder helper CLI.",
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    invoke_without_command=True,
    no_args_is_help=True,
)


def _run_option_callback(ctx: typer.Context, value: str | None) -> str | None:
    if value is None or ctx.resilient_parsing:
        return value
    run_agent_from_cli([value, *ctx.args])
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    run: str | None = typer.Option(
        None,
        "--run",
        help="Run an agent adapter through OpenFin, e.g. `f --run claude ...`.",
        callback=_run_option_callback,
        is_eager=True,
    ),
) -> None:
    del ctx, run


def main_entry(argv: list[str] | None = None) -> None:
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--run"]:
        run_agent_from_cli(args[1:])
        return
    app(args=args)


app.command()(init)
app.command("in")(capture)
app.command()(add)
app.command()(assign)
app.command()(idea)
app.command("ls")(list_tasks)
app.command()(search)
app.command("do")(start_task)
app.command()(done)
app.command()(block)
app.command()(drop)
app.command()(touch)
app.command()(edit)
app.command()(overdue)
app.command()(today)
app.command()(review)
app.command()(context)
app.command()(digest)
app.command()(triage)
app.command()(compact)
app.add_typer(schedule_app, name="schedule")
app.add_typer(index_app, name="index")
app.add_typer(agents_app, name="agents")
