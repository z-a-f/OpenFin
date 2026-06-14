from __future__ import annotations

from datetime import date

import typer

from openfin.dates import parse_date_input
from openfin.index import search_index
from openfin.storage import OpenFinStore
from openfin.ui import console


def search(
    query: str,
    tag: str | None = typer.Option(None, "--tag"),
    since: str | None = typer.Option(None, "--since"),
    use_index: bool = typer.Option(
        False, "--index", help="Search the derived SQLite FTS index."
    ),
) -> None:
    """Search across charter, now, tasks, inbox, and log files."""
    store = OpenFinStore.from_env()
    since_date = parse_since_date(since)
    hits = (
        search_index(store, query, tag=tag, since=since_date)
        if use_index
        else store.search(query, tag=tag, since=since_date)
    )
    print_hits(hits)


def parse_since_date(since: str | None) -> date | None:
    return date.fromisoformat(parse_date_input(since)) if since else None


def print_hits(hits) -> None:
    if not hits:
        console.print("No matches.")
        return
    for hit in hits:
        console.print(f"{hit.source}:{hit.line_number}: {hit.line}", markup=False)
