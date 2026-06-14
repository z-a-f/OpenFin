from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import typer
import yaml

from openfin.storage import (
    ACTIVE_STATUSES,
    PRIORITIES,
    TASK_STATUSES,
    OpenFinStore,
    dump_yaml,
    parse_now_updated,
)

app = typer.Typer(help="OpenFin founder helper CLI.")


class PlainConsole:
    def print(self, *objects: Any, **_: Any) -> None:
        typer.echo(" ".join(str(item) for item in objects))


console = PlainConsole()

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def get_store() -> OpenFinStore:
    return OpenFinStore.from_env()


def today_date() -> date:
    return date.today()


def parse_tags(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip().lstrip("#") for item in value.split(",") if item.strip()]


def validate_priority(priority: str) -> str:
    normalized = priority.upper()
    if normalized not in PRIORITIES:
        raise typer.BadParameter(f"priority must be one of {', '.join(sorted(PRIORITIES))}")
    return normalized


def validate_status(status: str) -> str:
    normalized = status.lower()
    if normalized not in TASK_STATUSES:
        raise typer.BadParameter(f"status must be one of {', '.join(sorted(TASK_STATUSES))}")
    return normalized


def parse_date_input(value: str | None) -> str | None:
    if not value:
        return None
    import dateparser

    parsed = dateparser.parse(
        value,
        settings={
            "PREFER_DATES_FROM": "future",
            "RELATIVE_BASE": datetime.now(),
        },
    )
    if parsed is None:
        raise typer.BadParameter(f"could not parse date: {value}")
    return parsed.date().isoformat()


def task_due_date(task: dict[str, Any], field: str = "due") -> date | None:
    value = task.get(field)
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def invalid_task_dates(task: dict[str, Any]) -> list[str]:
    invalid: list[str] = []
    for field in ["due", "recheck", "created", "updated"]:
        value = task.get(field)
        if not value:
            continue
        try:
            date.fromisoformat(str(value))
        except ValueError:
            invalid.append(f"{task.get('id')} {field}={value}")
    return invalid


def is_quiet_until_recheck(task: dict[str, Any], today: date) -> bool:
    recheck = task_due_date(task, "recheck")
    return recheck is not None and recheck > today


def needs_review(task: dict[str, Any], today: date) -> bool:
    recheck = task_due_date(task, "recheck")
    if recheck is not None and recheck > today:
        return False
    due = task_due_date(task)
    overdue = due is not None and due < today
    recheck_due = recheck is not None and recheck <= today
    return overdue or recheck_due


def visible_overdue(task: dict[str, Any], today: date) -> bool:
    if is_quiet_until_recheck(task, today):
        return False
    due = task_due_date(task)
    return due is not None and due < today


def visible_due_today(task: dict[str, Any], today: date) -> bool:
    if is_quiet_until_recheck(task, today):
        return False
    due = task_due_date(task)
    return due is not None and due == today


def active_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [task for task in tasks if task.get("status") in ACTIVE_STATUSES]


def sort_tasks(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        tasks,
        key=lambda task: (
            PRIORITY_RANK.get(str(task.get("priority", "P3")), 99),
            task.get("due") or "9999-12-31",
            task.get("id") or "",
        ),
    )


def find_task(tasks: list[dict[str, Any]], task_id: str) -> dict[str, Any]:
    for task in tasks:
        if task.get("id") == task_id:
            return task
    raise typer.BadParameter(f"unknown task id: {task_id}")


def update_task_timestamp(task: dict[str, Any]) -> None:
    task["updated"] = today_date().isoformat()


def tag_matches(task: dict[str, Any], tag: str | None) -> bool:
    if not tag:
        return True
    wanted = tag.lstrip("#")
    return wanted in [str(item).lstrip("#") for item in task.get("tags") or []]


def task_matches_profile(task: dict[str, Any], tags: list[str] | str) -> bool:
    if tags == "all":
        return True
    task_tags = {str(item).lstrip("#") for item in task.get("tags") or []}
    return bool(task_tags.intersection({tag.lstrip("#") for tag in tags}))


def render_tasks(tasks: list[dict[str, Any]], *, title: str) -> None:
    if not tasks:
        console.print(f"{title}: none")
        return

    from rich.console import Console
    from rich.table import Table

    rich_console = Console(color_system=None, highlight=False)
    table = Table(title=title)
    table.add_column("ID")
    table.add_column("Priority")
    table.add_column("Status")
    table.add_column("Due")
    table.add_column("Tags")
    table.add_column("Title")
    for task in tasks:
        tags = ", ".join(task.get("tags") or [])
        table.add_row(
            str(task.get("id", "")),
            str(task.get("priority", "")),
            str(task.get("status", "")),
            str(task.get("due") or ""),
            tags,
            str(task.get("title", "")),
        )
    rich_console.print(table)


def render_bad_dates(tasks: list[dict[str, Any]]) -> None:
    messages = [message for task in tasks for message in invalid_task_dates(task)]
    if not messages:
        return
    console.print("BAD DATES")
    for message in messages:
        console.print(f"- {message}")


def format_task_line(task: dict[str, Any]) -> str:
    due = f" due {task['due']}" if task.get("due") else ""
    tags = " ".join(f"#{tag}" for tag in task.get("tags") or [])
    tags_text = f" {tags}" if tags else ""
    return (
        f"- [{task.get('priority', 'P2')}] {task.get('id')} "
        f"{task.get('title')} ({task.get('status', 'open')}{due}){tags_text}"
    )


def append_task_log(store: OpenFinStore, marker: str, task: dict[str, Any], suffix: str = "") -> None:
    detail = f" {suffix}" if suffix else ""
    store.append_log_entry(f"#{marker} {task.get('id')} {task.get('title')}{detail}")


@app.command()
def init() -> None:
    """Create the local OpenFin plain-text store."""
    store = get_store()
    store.ensure_layout()
    console.print(f"OpenFin ready at {store.root}")


@app.command("in")
def capture(text: str) -> None:
    """Append a raw line to inbox.md."""
    store = get_store()
    store.append_inbox(text)
    console.print("Captured.")


@app.command()
def add(
    text: str,
    priority: str = typer.Option("P2", "--priority", "-p"),
    due: str | None = typer.Option(None, "--due", "-d"),
    tags: str | None = typer.Option(None, "--tag", "-t"),
    owner: str = typer.Option("me", "--owner", "-o"),
) -> None:
    """Create a structured task."""
    store = get_store()
    tasks = store.load_tasks()
    today = today_date().isoformat()
    task = {
        "id": store.next_task_id(tasks),
        "title": text,
        "owner": owner,
        "priority": validate_priority(priority),
        "status": "open",
        "due": parse_date_input(due),
        "recheck": None,
        "created": today,
        "updated": today,
        "tags": parse_tags(tags),
        "links": [],
        "notes": "",
    }
    tasks.append(task)
    store.save_tasks(tasks)
    console.print(f"Added {task['id']}: {task['title']}")


@app.command()
def idea(
    text: str,
    tags: str | None = typer.Option(None, "--tag", "-t"),
) -> None:
    """Append an idea to the current month's log."""
    store = get_store()
    markers = " ".join(f"#{tag}" for tag in parse_tags(tags))
    body = f"#idea {markers} {text}".replace("  ", " ").strip()
    store.append_log_entry(body)
    console.print("Logged idea.")


@app.command("ls")
def list_tasks(
    status: str | None = typer.Option(None, "--status"),
    tag: str | None = typer.Option(None, "--tag"),
    owner: str | None = typer.Option(None, "--owner"),
    priority: str | None = typer.Option(None, "--priority", "-p"),
) -> None:
    """List tasks with optional filters."""
    store = get_store()
    tasks = store.load_tasks()
    if status:
        status = validate_status(status)
        tasks = [task for task in tasks if task.get("status") == status]
    if tag:
        tasks = [task for task in tasks if tag_matches(task, tag)]
    if owner:
        tasks = [task for task in tasks if task.get("owner") == owner]
    if priority:
        priority = validate_priority(priority)
        tasks = [task for task in tasks if task.get("priority") == priority]
    render_tasks(sort_tasks(tasks), title="TASKS")


@app.command()
def search(
    query: str,
    tag: str | None = typer.Option(None, "--tag"),
    since: str | None = typer.Option(None, "--since"),
) -> None:
    """Search across charter, now, tasks, inbox, and log files."""
    store = get_store()
    since_date = date.fromisoformat(parse_date_input(since)) if since else None
    hits = store.search(query, tag=tag, since=since_date)
    if not hits:
        console.print("No matches.")
        return
    for hit in hits:
        console.print(f"{hit.source}:{hit.line_number}: {hit.line}", markup=False)


@app.command("do")
def start_task(task_id: str) -> None:
    """Mark a task as doing."""
    store = get_store()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    task["status"] = "doing"
    update_task_timestamp(task)
    store.save_tasks(tasks)
    console.print(f"Doing {task_id}: {task['title']}")


@app.command()
def done(task_id: str) -> None:
    """Mark a task done and append a #done log entry."""
    store = get_store()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    task["status"] = "done"
    task["recheck"] = None
    update_task_timestamp(task)
    store.save_tasks(tasks)
    append_task_log(store, "done", task)
    console.print(f"Done {task_id}: {task['title']}")


@app.command()
def block(task_id: str, why: str) -> None:
    """Mark a task blocked with a reason."""
    store = get_store()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    task["status"] = "blocked"
    prior_notes = task.get("notes") or ""
    addition = f"Blocked {today_date().isoformat()}: {why}"
    task["notes"] = f"{prior_notes}\n{addition}".strip()
    update_task_timestamp(task)
    store.save_tasks(tasks)
    store.append_log_entry(f"#blocked {task_id} {why}")
    console.print(f"Blocked {task_id}: {why}")


@app.command()
def drop(task_id: str) -> None:
    """Mark a task dropped and append a #dropped log entry."""
    store = get_store()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    task["status"] = "dropped"
    task["recheck"] = None
    update_task_timestamp(task)
    store.save_tasks(tasks)
    append_task_log(store, "dropped", task)
    console.print(f"Dropped {task_id}: {task['title']}")


@app.command()
def edit(
    task_id: str,
    title: str | None = typer.Option(None, "--title"),
    priority: str | None = typer.Option(None, "--priority", "-p"),
    due: str | None = typer.Option(None, "--due", "-d"),
    status: str | None = typer.Option(None, "--status"),
    tags: str | None = typer.Option(None, "--tag", "-t"),
    notes: str | None = typer.Option(None, "--notes"),
) -> None:
    """Edit task fields with flags, or open the task YAML in $EDITOR."""
    store = get_store()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    if any(value is not None for value in [title, priority, due, status, tags, notes]):
        if title is not None:
            task["title"] = title
        if priority is not None:
            task["priority"] = validate_priority(priority)
        if due is not None:
            task["due"] = parse_date_input(due)
        if status is not None:
            task["status"] = validate_status(status)
        if tags is not None:
            task["tags"] = parse_tags(tags)
        if notes is not None:
            task["notes"] = notes
        update_task_timestamp(task)
        store.save_tasks(tasks)
        console.print(f"Updated {task_id}: {task['title']}")
        return

    edited = edit_task_in_editor(task)
    task.clear()
    task.update(edited)
    update_task_timestamp(task)
    store.save_tasks(tasks)
    console.print(f"Updated {task_id}: {task['title']}")


def edit_task_in_editor(task: dict[str, Any]) -> dict[str, Any]:
    editor = os.environ.get("EDITOR")
    if not editor:
        console.print(dump_yaml(task), markup=False)
        raise typer.Exit()

    with tempfile.NamedTemporaryFile("w+", suffix=".yaml", delete=False) as handle:
        path = Path(handle.name)
        handle.write(dump_yaml(task))
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=True)
        edited = yaml.safe_load(path.read_text())
    finally:
        path.unlink(missing_ok=True)

    if not isinstance(edited, dict):
        raise typer.BadParameter("edited task must be a YAML mapping")
    edited["priority"] = validate_priority(str(edited.get("priority", "P2")))
    edited["status"] = validate_status(str(edited.get("status", "open")))
    return edited


@app.command()
def overdue() -> None:
    """Show overdue active tasks."""
    tasks = get_store().load_tasks()
    today = today_date()
    overdue_tasks = [
        task
        for task in active_tasks(tasks)
        if visible_overdue(task, today)
    ]
    render_tasks(sort_tasks(overdue_tasks), title="OVERDUE")
    render_bad_dates(tasks)


@app.command()
def today() -> None:
    """Show today's working set and stale flags."""
    store = get_store()
    tasks = store.load_tasks()
    today = today_date()
    active = active_tasks(tasks)
    overdue_tasks = [
        task
        for task in active
        if visible_overdue(task, today)
    ]
    due_today = [
        task
        for task in active
        if visible_due_today(task, today)
    ]
    review_tasks = [task for task in active if needs_review(task, today)]
    doing = [task for task in active if task.get("status") == "doing"]
    blocked = [task for task in active if task.get("status") == "blocked"]
    stale = find_stale_tasks(active, today)

    render_tasks(sort_tasks(overdue_tasks), title="OVERDUE")
    render_tasks(sort_tasks(due_today)[:3], title="TODAY")
    render_tasks(sort_tasks(doing), title="IN FLIGHT")
    render_tasks(sort_tasks(blocked), title="WAITING ON")
    if review_tasks:
        console.print("Run `f review` to make a decision on overdue/recheck items.")

    stale_messages = list(stale)
    now_updated = parse_now_updated(store.now_path.read_text())
    if now_updated and now_updated < today - timedelta(days=7):
        stale_messages.append(f"now.md last updated {now_updated.isoformat()}")
    if stale_messages:
        console.print("STALE")
        for message in stale_messages:
            console.print(f"- {message}")
    render_bad_dates(tasks)


def find_stale_tasks(tasks: list[dict[str, Any]], today: date) -> list[str]:
    messages: list[str] = []
    cutoff = today - timedelta(days=7)
    for task in tasks:
        updated = task_due_date(task, "updated")
        if updated and updated < cutoff:
            messages.append(f"{task.get('id')} {task.get('title')} last updated {updated}")
    return messages


@app.command()
def review() -> None:
    """Interactive decision loop for overdue and recheck tasks."""
    store = get_store()
    tasks = store.load_tasks()
    today = today_date()
    review_items = [
        task
        for task in active_tasks(tasks)
        if needs_review(task, today)
    ]
    if not review_items:
        console.print("No overdue or recheck items.")
        return

    for task in sort_tasks(review_items):
        console.print(format_task_line(task), markup=False)
        choice = typer.prompt(
            "Decision [commit/snooze/block/drop/done/skip]",
            default="skip",
        ).strip().lower()
        if choice == "commit":
            days_raw = typer.prompt("Recheck in days", default="1")
            try:
                days = int(days_raw)
            except ValueError as exc:
                raise typer.BadParameter("recheck days must be an integer") from exc
            recheck_date = today + timedelta(days=days)
            task["recheck"] = recheck_date.isoformat()
            update_task_timestamp(task)
            store.append_log_entry(f"#commit {task['id']} recheck {recheck_date.isoformat()}")
        elif choice == "snooze":
            new_due = typer.prompt("New due date")
            task["due"] = parse_date_input(new_due)
            update_task_timestamp(task)
        elif choice == "block":
            why = typer.prompt("Why blocked")
            task["status"] = "blocked"
            prior_notes = task.get("notes") or ""
            task["notes"] = f"{prior_notes}\nBlocked {today.isoformat()}: {why}".strip()
            update_task_timestamp(task)
        elif choice == "drop":
            task["status"] = "dropped"
            task["recheck"] = None
            update_task_timestamp(task)
            append_task_log(store, "dropped", task)
        elif choice == "done":
            task["status"] = "done"
            task["recheck"] = None
            update_task_timestamp(task)
            append_task_log(store, "done", task)
        elif choice == "skip":
            continue
        else:
            console.print(f"Skipped unknown decision: {choice}")
    store.save_tasks(tasks)
    console.print("Review complete.")


@app.command()
def context(
    profile: str = typer.Argument("default"),
    topic: str | None = typer.Option(None, "--for"),
    copy: bool = typer.Option(False, "--copy"),
    budget: int | None = typer.Option(None, "--budget"),
) -> None:
    """Assemble an AI-ready context pack."""
    store = get_store()
    pack = assemble_context_pack(store, profile_name=profile, topic=topic)
    token_estimate = max(1, len(pack) // 4)
    if copy:
        import pyperclip

        pyperclip.copy(pack)
        console.print("Copied context pack to clipboard.")
    else:
        console.print(pack, markup=False)
    console.print(f"\nEstimated tokens: {token_estimate}")
    if budget is not None and token_estimate > budget:
        console.print(f"Budget warning: estimated tokens exceed {budget}.")


def assemble_context_pack(
    store: OpenFinStore,
    *,
    profile_name: str,
    topic: str | None,
) -> str:
    profiles = store.load_profiles()
    if profile_name not in profiles:
        raise typer.BadParameter(f"unknown profile: {profile_name}")

    profile = profiles[profile_name]
    charter = select_charter_sections(
        store.charter_path.read_text(),
        profile.get("charter_sections", "all"),
    )
    now = store.now_path.read_text().strip()
    task_tags = profile.get("task_tags", "all")
    tasks = [
        task
        for task in sort_tasks(active_tasks(store.load_tasks()))
        if task_matches_profile(task, task_tags)
    ]
    log_tags = profile.get("log_tags", "all")
    max_log_lines = int(profile.get("max_log_lines", 40))
    log_entries = store.recent_log_entries(tags=log_tags, limit=max_log_lines)

    parts = [
        "# OpenFin Context Pack",
        f"Profile: {profile_name}",
        "",
        "## Charter",
        charter,
        "",
        "## Now",
        now,
        "",
        "## Open Tasks",
        "\n".join(format_task_line(task) for task in tasks) or "- none",
        "",
        "## Recent Log",
        "\n".join(log_entries) or "- none",
    ]
    if topic:
        hits = store.search(topic)
        parts.extend(
            [
                "",
                f"## Topic Hits: {topic}",
                "\n".join(f"- {hit.source}:{hit.line_number}: {hit.line}" for hit in hits)
                or "- none",
            ]
        )
    return "\n".join(parts).strip()


def select_charter_sections(text: str, sections: list[str] | str) -> str:
    if sections == "all":
        return text.strip()

    wanted = {section.strip() for section in sections}
    output: list[str] = []
    include = False
    for line in text.splitlines():
        if line.startswith("# ") and not output:
            output.append(line)
            continue
        if line.startswith("## "):
            name = line.removeprefix("## ").strip()
            include = name in wanted
        if include:
            output.append(line)
    return "\n".join(output).strip()


@app.command()
def digest(kind: str = typer.Argument("morning")) -> None:
    """Render a morning or evening brief."""
    normalized = kind.lower()
    if normalized not in {"morning", "evening"}:
        raise typer.BadParameter("digest kind must be morning or evening")

    store = get_store()
    tasks = store.load_tasks()
    today = today_date()
    active = active_tasks(tasks)
    overdue_tasks = [
        task
        for task in active
        if visible_overdue(task, today)
    ]

    if normalized == "morning":
        console.print("MORNING DIGEST")
        render_tasks(sort_tasks(overdue_tasks), title="OVERDUE")
        render_tasks(
            sort_tasks(
                [
                    task
                    for task in active
                    if visible_due_today(task, today)
                ]
            )[:3],
            title="TODAY'S TOP 3",
        )
        render_tasks([task for task in active if task.get("status") == "doing"], title="IN FLIGHT")
        render_tasks([task for task in active if task.get("status") == "blocked"], title="WAITING ON")
        return

    console.print("EVENING DIGEST")
    today_log = [
        entry.line
        for entry in store.log_entries(tags=["done"], on_date=today, limit=100)
    ]
    for entry in today_log[:10]:
        console.print(entry, markup=False)
    render_tasks(
        sort_tasks(
            [
                task
                for task in active
                if (due := task_due_date(task)) is not None
                and due == today + timedelta(days=1)
            ]
        )[:3],
        title="TOMORROW'S TOP 3",
    )
    render_tasks(sort_tasks(overdue_tasks), title="SLIPPING")


@app.command()
def triage() -> None:
    """Interactively triage inbox lines into tasks, ideas, decisions, notes, or drops."""
    store = get_store()
    store.ensure_layout()
    lines = [line for line in store.inbox_path.read_text().splitlines() if line.strip()]
    if not lines:
        console.print("Inbox is empty.")
        return

    remaining: list[str] = []
    tasks = store.load_tasks()
    for line in lines:
        text = re.sub(r"^-\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}\s+", "", line).strip()
        console.print(line, markup=False)
        choice = typer.prompt("Triage [task/idea/decision/note/drop/skip]", default="skip").lower()
        if choice == "task":
            today = today_date().isoformat()
            task = {
                "id": store.next_task_id(tasks),
                "title": text,
                "owner": "me",
                "priority": "P2",
                "status": "open",
                "due": None,
                "recheck": None,
                "created": today,
                "updated": today,
                "tags": [],
                "links": [],
                "notes": "",
            }
            tasks.append(task)
            console.print(f"Added {task['id']}.")
        elif choice == "idea":
            store.append_log_entry(f"#idea {text}")
        elif choice == "decision":
            store.append_log_entry(f"#decision {text}")
        elif choice == "note":
            store.append_log_entry(f"#note {text}")
        elif choice == "drop":
            continue
        else:
            remaining.append(line)
    store.save_tasks(tasks)
    store.write_inbox_lines(remaining)
    console.print("Triage complete.")


@app.command()
def compact() -> None:
    """Archive old closed tasks and print stale/redundancy suggestions."""
    store = get_store()
    tasks = store.load_tasks()
    today = today_date()
    archive_cutoff = today - timedelta(days=14)
    stale_cutoff = today - timedelta(days=7)
    kept: list[dict[str, Any]] = []
    archived: list[dict[str, Any]] = []

    for task in tasks:
        updated = task_due_date(task, "updated")
        if task.get("status") in {"done", "dropped"} and updated and updated < archive_cutoff:
            archived.append(task)
            marker = "done" if task.get("status") == "done" else "dropped"
            task_id = str(task.get("id"))
            if not store.has_log_marker(marker, task_id):
                store.append_log_entry(f"#{marker} {task_id} {task.get('title')}")
        else:
            kept.append(task)

    if archived:
        store.save_tasks(kept)
        console.print(f"Archived {len(archived)} closed task(s) into the log.")
    else:
        console.print("No closed tasks old enough to archive.")

    stale = [
        task
        for task in active_tasks(kept)
        if (updated := task_due_date(task, "updated")) and updated < stale_cutoff
    ]
    if stale:
        console.print("STALE - still true?")
        for task in stale:
            console.print(format_task_line(task), markup=False)

    redundant = find_tag_collisions(kept, today=today)
    if redundant:
        console.print("POSSIBLE REDUNDANCY")
        for tag, tasks_for_tag in redundant.items():
            ids = ", ".join(str(task.get("id")) for task in tasks_for_tag)
            console.print(f"#{tag}: {ids}")


def find_tag_collisions(
    tasks: list[dict[str, Any]],
    *,
    today: date,
) -> dict[str, list[dict[str, Any]]]:
    by_tag: dict[str, list[dict[str, Any]]] = {}
    for task in tasks:
        if task.get("status") != "open":
            continue
        for tag in task.get("tags") or []:
            by_tag.setdefault(str(tag), []).append(task)
    return {
        tag: tagged
        for tag, tagged in by_tag.items()
        if len(tagged) >= 2 and any(is_redundancy_candidate(task, today) for task in tagged)
    }


def is_redundancy_candidate(task: dict[str, Any], today: date) -> bool:
    if visible_overdue(task, today):
        return True
    created = task_due_date(task, "created")
    return created is not None and created < today - timedelta(days=7)
