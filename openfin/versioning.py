from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


FALSE_VALUES = {"0", "false", "no", "off"}
DEFAULT_GITIGNORE = """.openfin/
agents/openfind.sock
agents/*/transcript.jsonl
"""
IGNORED_TRACKED_PATHS = [
    ":(glob)agents/*/transcript.jsonl",
]
MANAGED_PATHS = [
    ".gitignore",
    "charter.md",
    "now.md",
    "tasks.yaml",
    "inbox.md",
    "profiles.yaml",
    "log",
    "agents",
]


def git_enabled() -> bool:
    return os.environ.get("OPENFIN_GIT", "").strip().lower() not in FALSE_VALUES


def auto_commit_enabled() -> bool:
    return (
        git_enabled()
        and os.environ.get("OPENFIN_GIT_AUTO_COMMIT", "").strip().lower()
        not in FALSE_VALUES
    )


def git_available() -> bool:
    return shutil.which("git") is not None


def ensure_git_repo(root: Path) -> bool:
    if not git_enabled() or not git_available():
        return False
    try:
        root.mkdir(parents=True, exist_ok=True)
        ensure_gitignore(root)
        if not (root / ".git").exists():
            run_git(root, "init")
        ensure_git_identity(root)
    except (OSError, subprocess.SubprocessError):
        return False
    return True


def ensure_gitignore(root: Path) -> None:
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    required = DEFAULT_GITIGNORE.splitlines()
    missing = [line for line in required if line and line not in existing.splitlines()]
    if not path.exists():
        path.write_text(DEFAULT_GITIGNORE, encoding="utf-8")
        return
    if not missing:
        return
    separator = "" if existing.endswith("\n") or not existing else "\n"
    missing_text = "\n".join(missing)
    path.write_text(
        f"{existing}{separator}{missing_text}\n",
        encoding="utf-8",
    )


def auto_commit(root: Path, message: str) -> bool:
    try:
        if not auto_commit_enabled() or not ensure_git_repo(root):
            return False

        pathspecs = [path for path in MANAGED_PATHS if (root / path).exists()]
        if not pathspecs:
            return False

        for pathspec in IGNORED_TRACKED_PATHS:
            run_git(root, "rm", "--cached", "--ignore-unmatch", "--", pathspec)
        run_git(root, "add", "-A", "--", *pathspecs)
        status = run_git(
            root,
            "status",
            "--porcelain",
            "--",
            *pathspecs,
            check=False,
        )
        if not status.stdout.strip():
            return False

        committed = run_git(root, "commit", "-m", message, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return committed.returncode == 0


def ensure_git_identity(root: Path) -> None:
    name = run_git(root, "config", "--get", "user.name", check=False)
    if name.returncode != 0 or not name.stdout.strip():
        run_git(root, "config", "user.name", "OpenFin")

    email = run_git(root, "config", "--get", "user.email", check=False)
    if email.returncode != 0 or not email.stdout.strip():
        run_git(root, "config", "user.email", "openfin@local")


def run_git(
    root: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=check,
    )
