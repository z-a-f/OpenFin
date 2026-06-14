from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import typer
import yaml

from openfin.dates import (
    invalid_task_dates,
    parse_date_input,
    task_due_date,
    today_date,
)
from openfin.storage import (
    ACTIVE_STATUSES,
    ENCODING,
    PRIORITIES,
    TASK_STATUSES,
    OpenFinStore,
    dump_yaml,
    parse_now_updated,
    read_text,
)
from openfin.tags import parse_tags, tag_matches
from openfin.ui import console, render_tasks


PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


def validate_priority(priority: str) -> str:
    normalized = priority.upper()
    if normalized not in PRIORITIES:
        raise typer.BadParameter(
            f"priority must be one of {', '.join(sorted(PRIORITIES))}"
        )
    return normalized


def validate_status(status: str) -> str:
    normalized = status.lower()
    if normalized not in TASK_STATUSES:
        raise typer.BadParameter(
            f"status must be one of {', '.join(sorted(TASK_STATUSES))}"
        )
    return normalized


def build_task(
    store: OpenFinStore,
    tasks: list[dict[str, Any]],
    text: str,
    *,
    priority: str = "P2",
    due: str | None = None,
    tags: str | None = None,
    owner: str = "me",
) -> dict[str, Any]:
    today = today_date().isoformat()
    return {
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


def format_task_line(task: dict[str, Any]) -> str:
    due = f" due {task['due']}" if task.get("due") else ""
    tags = " ".join(f"#{tag}" for tag in task.get("tags") or [])
    tags_text = f" {tags}" if tags else ""
    return (
        f"- [{task.get('priority', 'P2')}] {task.get('id')} "
        f"{task.get('title')} ({task.get('status', 'open')}{due}){tags_text}"
    )


def append_task_log(
    store: OpenFinStore, marker: str, task: dict[str, Any], suffix: str = ""
) -> None:
    detail = f" {suffix}" if suffix else ""
    store.append_log_entry(f"#{marker} {task.get('id')} {task.get('title')}{detail}")


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


def render_bad_dates(tasks: list[dict[str, Any]]) -> None:
    messages = [message for task in tasks for message in invalid_task_dates(task)]
    if not messages:
        return
    console.print("BAD DATES")
    for message in messages:
        console.print(f"- {message}")


def find_stale_tasks(tasks: list[dict[str, Any]], today: date) -> list[str]:
    messages: list[str] = []
    cutoff = today - timedelta(days=7)
    for task in tasks:
        updated = task_due_date(task, "updated")
        if updated and updated < cutoff:
            messages.append(
                f"{task.get('id')} {task.get('title')} last updated {updated}"
            )
    return messages


def add(
    text: str,
    priority: str = typer.Option("P2", "--priority", "-p"),
    due: str | None = typer.Option(None, "--due", "-d"),
    tags: str | None = typer.Option(None, "--tag", "-t"),
    owner: str = typer.Option("me", "--owner", "-o"),
) -> None:
    """Create a structured task."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    task = build_task(
        store, tasks, text, priority=priority, due=due, tags=tags, owner=owner
    )
    tasks.append(task)
    store.save_tasks(tasks)
    console.print(f"Added {task['id']}: {task['title']}")


def list_tasks(
    status: str | None = typer.Option(None, "--status"),
    tag: str | None = typer.Option(None, "--tag"),
    owner: str | None = typer.Option(None, "--owner"),
    priority: str | None = typer.Option(None, "--priority", "-p"),
) -> None:
    """List tasks with optional filters."""
    store = OpenFinStore.from_env()
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


def start_task(task_id: str) -> None:
    """Mark a task as doing."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    task["status"] = "doing"
    update_task_timestamp(task)
    store.save_tasks(tasks)
    console.print(f"Doing {task_id}: {task['title']}")


def done(task_id: str) -> None:
    """Mark a task done and append a #done log entry."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    task["status"] = "done"
    task["recheck"] = None
    update_task_timestamp(task)
    store.save_tasks(tasks)
    append_task_log(store, "done", task)
    console.print(f"Done {task_id}: {task['title']}")


def block(task_id: str, why: str) -> None:
    """Mark a task blocked with a reason."""
    store = OpenFinStore.from_env()
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


def drop(task_id: str) -> None:
    """Mark a task dropped and append a #dropped log entry."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    task["status"] = "dropped"
    task["recheck"] = None
    update_task_timestamp(task)
    store.save_tasks(tasks)
    append_task_log(store, "dropped", task)
    console.print(f"Dropped {task_id}: {task['title']}")


def touch(task_id: str, note: str | None = typer.Option(None, "--note", "-n")) -> None:
    """Record progress on a task without changing its status."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    task = find_task(tasks, task_id)
    if note:
        prior_notes = task.get("notes") or ""
        addition = f"Progress {today_date().isoformat()}: {note}"
        task["notes"] = f"{prior_notes}\n{addition}".strip()
    update_task_timestamp(task)
    store.save_tasks(tasks)
    append_task_log(store, "touch", task, note or "")
    console.print(f"Touched {task_id}: {task['title']}")


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
    store = OpenFinStore.from_env()
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

    with tempfile.NamedTemporaryFile(
        "w+",
        suffix=".yaml",
        delete=False,
        encoding=ENCODING,
    ) as handle:
        path = Path(handle.name)
        handle.write(dump_yaml(task))
    try:
        subprocess.run([*shlex.split(editor), str(path)], check=True)
        edited = yaml.safe_load(read_text(path))
    finally:
        path.unlink(missing_ok=True)

    if not isinstance(edited, dict):
        raise typer.BadParameter("edited task must be a YAML mapping")
    edited["priority"] = validate_priority(str(edited.get("priority", "P2")))
    edited["status"] = validate_status(str(edited.get("status", "open")))
    return edited


def overdue() -> None:
    """Show overdue active tasks."""
    tasks = OpenFinStore.from_env().load_tasks()
    today = today_date()
    overdue_tasks = [
        task for task in active_tasks(tasks) if visible_overdue(task, today)
    ]
    render_tasks(sort_tasks(overdue_tasks), title="OVERDUE")
    render_bad_dates(tasks)


def today() -> None:
    """Show today's working set and stale flags."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    today = today_date()
    active = active_tasks(tasks)
    overdue_tasks = [task for task in active if visible_overdue(task, today)]
    due_today = [task for task in active if visible_due_today(task, today)]
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
    now_updated = parse_now_updated(read_text(store.now_path))
    if now_updated and now_updated < today - timedelta(days=7):
        stale_messages.append(f"now.md last updated {now_updated.isoformat()}")
    if stale_messages:
        console.print("STALE")
        for message in stale_messages:
            console.print(f"- {message}")
    render_bad_dates(tasks)
