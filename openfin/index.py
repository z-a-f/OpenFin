from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import typer

from openfin.storage import (
    OpenFinStore,
    TextHit,
    parse_inbox_line_date,
    parse_log_header_date,
    read_text,
)
from openfin.storage import line_has_tag
from openfin.ui import console


index_app = typer.Typer(help="Manage the rebuildable SQLite search index.")


@dataclass(frozen=True)
class IndexStatus:
    exists: bool
    current: bool
    stored_hash: str | None
    source_hash: str
    path: Path


@index_app.command("rebuild")
def rebuild() -> None:
    """Rebuild the derived SQLite FTS index."""
    store = OpenFinStore.from_env()
    count = rebuild_index(store)
    console.print(f"Indexed {count} line(s) at {index_path(store)}.")


@index_app.command("status")
def status() -> None:
    """Show whether the derived SQLite FTS index is current."""
    store = OpenFinStore.from_env()
    current = index_status(store)
    if not current.exists:
        console.print(f"Index missing: {current.path}")
    elif current.current:
        console.print(f"Index current: {current.path}")
    else:
        console.print(f"Index stale: {current.path}")


@index_app.command("search")
def search_index_command(
    query: str,
    tag: str | None = typer.Option(None, "--tag"),
    since: str | None = typer.Option(None, "--since"),
) -> None:
    """Search the derived SQLite FTS index."""
    from openfin.search import parse_since_date, print_hits

    store = OpenFinStore.from_env()
    hits = search_index(store, query, tag=tag, since=parse_since_date(since))
    print_hits(hits)


def index_path(store: OpenFinStore) -> Path:
    return store.root / ".openfin" / "index.sqlite3"


def source_hash(store: OpenFinStore) -> str:
    store.ensure_layout()
    digest = hashlib.sha256()
    for path, source in store.iter_text_files():
        digest.update(source.encode("utf-8"))
        digest.update(b"\0")
        digest.update(read_text(path).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def connect_index(store: OpenFinStore) -> sqlite3.Connection:
    path = index_path(store)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def rebuild_index(store: OpenFinStore) -> int:
    current_hash = source_hash(store)
    with connect_index(store) as connection:
        initialize_schema(connection)
        connection.execute("DELETE FROM search_fts")
        count = 0
        for hit in iter_indexable_lines(store):
            connection.execute(
                "INSERT INTO search_fts(source, line_number, entry_date, line) VALUES (?, ?, ?, ?)",
                (
                    hit.source,
                    hit.line_number,
                    hit.entry_date.isoformat() if hit.entry_date else None,
                    hit.line,
                ),
            )
            count += 1
        connection.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES ('source_hash', ?)",
            (current_hash,),
        )
    return count


def initialize_schema(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    connection.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5("
        "source UNINDEXED, line_number UNINDEXED, entry_date UNINDEXED, line)"
    )


def iter_indexable_lines(store: OpenFinStore) -> list[TextHit]:
    hits: list[TextHit] = []
    for path, source in store.iter_text_files():
        current_date: date | None = None
        for line_number, raw_line in enumerate(read_text(path).splitlines(), start=1):
            line = raw_line.rstrip()
            header_date = parse_log_header_date(line)
            if header_date:
                current_date = header_date
                continue
            if not line:
                continue
            hits.append(
                TextHit(
                    source=source,
                    line_number=line_number,
                    line=line,
                    entry_date=current_date or parse_inbox_line_date(line),
                )
            )
    return hits


def index_status(store: OpenFinStore) -> IndexStatus:
    path = index_path(store)
    current_hash = source_hash(store)
    if not path.exists():
        return IndexStatus(False, False, None, current_hash, path)

    with connect_index(store) as connection:
        initialize_schema(connection)
        row = connection.execute(
            "SELECT value FROM meta WHERE key = 'source_hash'"
        ).fetchone()
    stored_hash = str(row["value"]) if row else None
    return IndexStatus(
        exists=True,
        current=stored_hash == current_hash,
        stored_hash=stored_hash,
        source_hash=current_hash,
        path=path,
    )


def ensure_current_index(store: OpenFinStore) -> None:
    current = index_status(store)
    if not current.current:
        rebuild_index(store)


def search_index(
    store: OpenFinStore,
    query: str,
    *,
    tag: str | None = None,
    since: date | None = None,
) -> list[TextHit]:
    ensure_current_index(store)
    fts_query = build_fts_query(query)
    tag_marker = tag.lstrip("#") if tag else None

    with connect_index(store) as connection:
        rows = connection.execute(
            "SELECT source, line_number, entry_date, line FROM search_fts "
            "WHERE search_fts MATCH ? ORDER BY rank",
            (fts_query,),
        ).fetchall()

    hits: list[TextHit] = []
    for row in rows:
        entry_date = (
            date.fromisoformat(row["entry_date"]) if row["entry_date"] else None
        )
        line = str(row["line"])
        if since and entry_date and entry_date < since:
            continue
        if since and str(row["source"]).startswith("log/") and entry_date is None:
            continue
        if tag_marker and not line_has_tag(line, tag_marker):
            continue
        hits.append(
            TextHit(
                source=str(row["source"]),
                line_number=int(row["line_number"]),
                entry_date=entry_date,
                line=line,
            )
        )
    return sorted(
        hits,
        key=lambda hit: (hit.entry_date or date.min, hit.source, hit.line_number),
        reverse=True,
    )


def build_fts_query(query: str) -> str:
    tokens = re.findall(r"[\w-]+", query.lower())
    if not tokens:
        return f'"{query.replace('"', '""')}"'
    return " AND ".join(f'"{token.replace('"', '""')}"' for token in tokens)
