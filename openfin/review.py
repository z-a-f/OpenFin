from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from datetime import timedelta
from typing import Any

import typer

from openfin.dates import parse_date_input, task_due_date, today_date
from openfin.storage import LogEntry, OpenFinStore, line_has_tag
from openfin.task import (
    active_tasks,
    append_task_log,
    format_task_line,
    needs_review,
    sort_tasks,
    update_task_timestamp,
)
from openfin.ui import console


@dataclass(frozen=True)
class CommitRecord:
    task_id: str
    entry: LogEntry
    recheck: date | None
    status: str | None


def review() -> None:
    """Interactive decision loop for overdue and recheck tasks."""
    store = OpenFinStore.from_env()
    tasks = store.load_tasks()
    today = today_date()
    review_items = [task for task in active_tasks(tasks) if needs_review(task, today)]
    if not review_items:
        console.print("No overdue or recheck items.")
        return

    for task in sort_tasks(review_items):
        console.print(format_task_line(task), markup=False)
        message = recheck_progress_message(store, task)
        if message:
            console.print(message)
        choice = (
            typer.prompt(
                "Decision [commit/snooze/block/drop/done/skip]",
                default="skip",
            )
            .strip()
            .lower()
        )
        if choice == "commit":
            days_raw = typer.prompt("Recheck in days", default="1")
            try:
                days = int(days_raw)
            except ValueError as exc:
                raise typer.BadParameter("recheck days must be an integer") from exc
            recheck_date = today + timedelta(days=days)
            task["recheck"] = recheck_date.isoformat()
            update_task_timestamp(task)
            store.append_log_entry(
                f"#commit {task['id']} recheck {recheck_date.isoformat()} status {task.get('status', 'open')}"
            )
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


def recheck_progress_message(store: OpenFinStore, task: dict[str, Any]) -> str | None:
    recheck = task_due_date(task, "recheck")
    today = today_date()
    if recheck is None or recheck > today:
        return None

    commit = latest_commit_for_task(store, str(task.get("id", "")))
    if commit is None:
        return f"Recheck due {recheck.isoformat()}; no matching #commit log found."

    committed = (
        commit.entry.entry_date.isoformat()
        if commit.entry.entry_date
        else "unknown date"
    )
    if has_progress_since_commit(store, task, commit):
        return f"Committed {committed}; progress recorded since then."
    return f"Committed {committed}; nothing moved since then."


def latest_commit_for_task(store: OpenFinStore, task_id: str) -> CommitRecord | None:
    commits: list[CommitRecord] = []
    for entry in store.task_log_entries(task_id, tags=["commit"]):
        parsed = parse_commit_entry(task_id, entry)
        if parsed:
            commits.append(parsed)
    if not commits:
        return None
    return max(
        commits,
        key=lambda commit: (
            commit.entry.entry_date or date.min,
            commit.entry.source,
            commit.entry.line_number,
        ),
    )


def parse_commit_entry(task_id: str, entry: LogEntry) -> CommitRecord | None:
    match = re.search(
        rf"(?<![\w-])#commit\s+{re.escape(task_id)}\s+recheck\s+(\d{{4}}-\d{{2}}-\d{{2}})(?:\s+status\s+(\w+))?",
        entry.line,
    )
    if not match:
        return None
    try:
        recheck = date.fromisoformat(match.group(1))
    except ValueError:
        recheck = None
    return CommitRecord(
        task_id=task_id,
        entry=entry,
        recheck=recheck,
        status=match.group(2),
    )


def has_progress_since_commit(
    store: OpenFinStore, task: dict[str, Any], commit: CommitRecord
) -> bool:
    if commit.status and task.get("status") != commit.status:
        return True

    updated = task_due_date(task, "updated")
    if updated and commit.entry.entry_date and updated > commit.entry.entry_date:
        return True

    progress_tags = ["touch", "done", "blocked", "dropped", "assign"]
    for entry in store.task_log_entries(commit.task_id, tags=progress_tags):
        if entry_is_after(entry, commit.entry) and any(
            line_has_tag(entry.line, tag) for tag in progress_tags
        ):
            return True
    return False


def entry_is_after(candidate: LogEntry, reference: LogEntry) -> bool:
    candidate_date = candidate.entry_date or date.min
    reference_date = reference.entry_date or date.min
    if candidate_date != reference_date:
        return candidate_date > reference_date
    if candidate.source != reference.source:
        return candidate.source > reference.source
    return candidate.line_number > reference.line_number
