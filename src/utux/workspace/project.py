"""Creating a project directory.

`init_project` creates the paths that exist before any stage has run, writes
`utux.yaml`, records the `project_created` event and makes the first git
commit. Outputs of stages are created later, by the stage that owns them.
"""

import os
import shutil
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from utux.errors import ProjectInitError
from utux.events.log import EventLog
from utux.schemas.event import EventStatus, EventType, NewEvent
from utux.schemas.project_config import DataPolicy, ProjectConfig
from utux.workspace.atomic import atomic_write_bytes, atomic_write_text
from utux.workspace.layout import (
    CLAIM_LEDGER_FILE,
    CONFIG_FILE,
    EVENT_LOG_FILE,
    GITIGNORE_FILE,
    GITIGNORE_LINES,
    GITKEEP_FILE,
    PROJECT_DIRECTORIES,
    RESULTS_FILE,
)

SYSTEM_ACTOR = "system:utux"
FIRST_COMMIT_MESSAGE = "Create utux project"

_NO_IDENTITY = (
    "git has no user identity, which the first commit of the project needs. Set it with:\n"
    '  git config --global user.name "Your Name"\n'
    '  git config --global user.email "you@example.org"'
)


def init_project(
    directory: Path,
    *,
    budget_usd: float,
    data_policy: DataPolicy,
    clock: Callable[[], datetime] | None = None,
) -> Path:
    """Create a new project in a directory that is empty or does not exist.

    Everything that can be checked is checked before anything is created. If
    a later step fails, what was created is removed again.

    Args:
        directory: Where to create the project.
        budget_usd: The total budget of the project in US dollars.
        data_policy: What may be sent to external services.
        clock: Returns the current time in UTC, for the first event. Tests
            pass a fixed time.

    Returns:
        The project directory.

    Raises:
        ContractValidationError: If the options do not make a valid
            `utux.yaml`, for example a budget of zero.
        ProjectInitError: If the directory is not empty, git is missing or
            has no user identity, or the project cannot be created.
    """
    config = ProjectConfig.validate_document(
        {
            "schema_version": ProjectConfig.SCHEMA_VERSION,
            "data_policy": data_policy.value,
            "budget": {"total_usd": budget_usd},
        },
        CONFIG_FILE,
    )
    _check_target(directory)
    _check_git()

    # The topmost directory this call creates; removed again if a step fails.
    created = _first_missing(directory)
    try:
        _create(directory, config, clock)
    except BaseException:
        _remove_created(directory, created)
        raise
    return directory


def _create(directory: Path, config: ProjectConfig, clock: Callable[[], datetime] | None) -> None:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        for name in PROJECT_DIRECTORIES:
            (directory / name).mkdir(parents=True)
    except OSError as error:
        raise ProjectInitError(f"cannot create {directory}: {error.strerror}") from error
    for name in PROJECT_DIRECTORIES:
        # Git does not track an empty directory.
        atomic_write_bytes(directory / name / GITKEEP_FILE, b"")
    atomic_write_text(directory / CONFIG_FILE, config.to_yaml())
    atomic_write_text(directory / GITIGNORE_FILE, _gitignore_text())
    atomic_write_bytes(directory / CLAIM_LEDGER_FILE, b"")
    atomic_write_bytes(directory / RESULTS_FILE, b"")

    log_path = directory / EVENT_LOG_FILE
    log = EventLog(log_path) if clock is None else EventLog(log_path, clock=clock)
    log.append(NewEvent(actor=SYSTEM_ACTOR, type=EventType.PROJECT_CREATED, status=EventStatus.OK))

    _run_git(directory, "init", "--quiet", "--initial-branch=main")
    _run_git(directory, "add", "--all")
    # A signing setup of the user must not turn project creation into a prompt.
    _run_git(
        directory, "-c", "commit.gpgsign=false", "commit", "--quiet", "-m", FIRST_COMMIT_MESSAGE
    )


def _gitignore_text() -> str:
    lines = ["# Written by utux init.", *GITIGNORE_LINES]
    return "\n".join(lines) + "\n"


def _check_target(directory: Path) -> None:
    if not directory.exists():
        return
    if not directory.is_dir():
        raise ProjectInitError(f"cannot create a project at {directory}: it is not a directory")
    try:
        empty = next(directory.iterdir(), None) is None
    except OSError as error:
        raise ProjectInitError(f"cannot read {directory}: {error.strerror}") from error
    if not empty:
        raise ProjectInitError(
            f"cannot create a project in {directory}: the directory is not empty"
        )


def _check_git() -> None:
    if shutil.which("git") is None:
        raise ProjectInitError("git is not installed; a project is a git repository")
    if _git_setting("user.name") is None or _git_setting("user.email") is None:
        raise ProjectInitError(_NO_IDENTITY)


def _git_setting(name: str) -> str | None:
    """Return a git setting as the new repository will see it, or None.

    GIT_DIR points away from any repository, so the settings of a repository
    that happens to surround the working directory are not read. The new
    project is its own repository and would not see them either.
    """
    result = subprocess.run(
        ["git", "config", "--get", name],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_DIR": os.devnull},
    )
    value = result.stdout.strip()
    return value if result.returncode == 0 and value else None


def _run_git(directory: Path, *arguments: str) -> str:
    """Run git in the project directory. The arguments are fixed by this module."""
    result = subprocess.run(
        ["git", *arguments],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        step = next(argument for argument in arguments if not argument.startswith("-"))
        detail = result.stderr.strip() or f"exit status {result.returncode}"
        raise ProjectInitError(f"git {step} failed: {detail}")
    return result.stdout


def _first_missing(directory: Path) -> Path | None:
    """Return the topmost ancestor of the directory that does not exist yet."""
    missing = None
    current = directory
    while not current.exists():
        missing = current
        if current.parent == current:
            break
        current = current.parent
    return missing


def _remove_created(directory: Path, created: Path | None) -> None:
    """Undo a failed creation. The directory was empty or absent before it."""
    if created is not None:
        shutil.rmtree(created, ignore_errors=True)
        return
    for entry in directory.iterdir():
        if entry.is_dir() and not entry.is_symlink():
            shutil.rmtree(entry, ignore_errors=True)
        else:
            entry.unlink(missing_ok=True)
