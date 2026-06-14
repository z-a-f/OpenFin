from __future__ import annotations

import typer

from openfin.compact import compact
from openfin.context import context
from openfin.digest import digest
from openfin.idea import capture, idea, triage
from openfin.review import review
from openfin.scheduler import schedule_app
from openfin.search import search
from openfin.system import init
from openfin.task import (
    add,
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


app = typer.Typer(help="OpenFin founder helper CLI.")

app.command()(init)
app.command("in")(capture)
app.command()(add)
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
