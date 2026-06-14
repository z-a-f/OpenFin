from __future__ import annotations

import typer

from openfin.storage import OpenFinStore
from openfin.ui import console


def init(
    git: bool = typer.Option(
        True,
        "--git/--no-git",
        help="Initialize local Git history for OPENFIN_HOME. Use --no-git to skip it for this run.",
    ),
) -> None:
    """Create the local OpenFin plain-text store."""
    store = OpenFinStore.from_env()
    store.ensure_layout(version_control=git)
    console.print(f"OpenFin ready at {store.root}")
