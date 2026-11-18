"""What every command that writes to a project does first.

Such a command holds the project lock for as long as it runs, so that two
commands never write to one project at the same time, and, before it acts,
records each change of `utux.yaml` since the last recorded snapshot as one
`setting_changed` event. That is how a hand edit of the budget, of
verification or of any other setting enters the log (ADR-0011). Read-only
commands (`utux validate`, `utux cost`, `utux schema export`) do neither.

The lock is the file `.utux/lock`. It names the process that holds it. A
lock whose process is no longer running is reported, never taken over: a
person checks that nothing is writing and removes the file. The snapshot is
`.utux/settings-snapshot.yaml`, a copy of `utux.yaml` as last recorded; it is
tracked by git like `utux.yaml`.
"""

import json
import os
import socket
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from utux.errors import NotAProjectError, ProjectLockedError, StaleProjectLockError
from utux.events.log import EventLog, LogRepair, repair_log
from utux.schemas.common import Scalar
from utux.schemas.event import Event, EventStatus, EventType, NewEvent
from utux.schemas.project_config import ProjectConfig, load_project_config
from utux.schemas.yaml_io import parse_yaml
from utux.workspace.atomic import atomic_write_bytes
from utux.workspace.layout import CONFIG_FILE, EVENT_LOG_FILE

LOCK_FILE = ".utux/lock"
SNAPSHOT_FILE = ".utux/settings-snapshot.yaml"
SYSTEM_ACTOR = "system:utux"


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _timestamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# The lock


def _process_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # The process exists but belongs to someone else.
        return True
    return True


def _refusal(path: Path, raw: bytes) -> ProjectLockedError:
    """Describe the holder of an existing lock, as an error to raise."""
    try:
        holder = json.loads(raw)
        pid = holder["pid"]
        host = holder["host"]
        command = holder["command"]
        started = holder["started_at"]
        if not (isinstance(pid, int) and isinstance(host, str)):
            raise TypeError
    except (ValueError, KeyError, TypeError):
        return ProjectLockedError(
            f"the project lock {LOCK_FILE} exists but cannot be read; if no utux command "
            f"is running on this project, remove {path} and run the command again"
        )
    held_by = f"process {pid} on {host} ({command}, since {started})"
    if host != socket.gethostname():
        return ProjectLockedError(
            f"the project is locked by {held_by}; that host cannot be checked from here, "
            f"so wait for it to finish, or remove {path} if you are sure it has stopped"
        )
    if not _process_running(pid):
        return StaleProjectLockError(
            f"the project lock was left by {held_by}, which is no longer running; it may "
            f"have stopped halfway. Check the project with utux validate, then remove "
            f"{LOCK_FILE} and run the command again"
        )
    return ProjectLockedError(
        f"the project is locked by {held_by}; wait for it to finish and run the command again"
    )


@contextmanager
def project_lock(
    project: Path, command: str, *, clock: Callable[[], datetime] = _utc_now
) -> Iterator[None]:
    """Hold the lock of a project while the body runs.

    Args:
        project: The project directory.
        command: The command that takes the lock, for the message a second
            writer sees, for example `model ping`.
        clock: Returns the current time in UTC. Tests pass a fixed time.

    Raises:
        NotAProjectError: The directory has no `.utux/` directory.
        ProjectLockedError: Another process holds the lock, or the lock file
            cannot be read. Nothing is changed.
        StaleProjectLockError: The lock was left by a process that is no
            longer running. It is not taken over.
    """
    path = project / LOCK_FILE
    if not path.parent.is_dir():
        raise NotAProjectError(
            f"{project} is not a utux project: it has no .utux/ directory beside "
            f"{CONFIG_FILE} and {EVENT_LOG_FILE}; create a project with utux init"
        )
    holder = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "command": command,
        "started_at": _timestamp(clock()),
    }
    content = (json.dumps(holder) + "\n").encode("utf-8")
    try:
        # Created only if absent, so that two processes cannot both hold it.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            raw = b""
        raise _refusal(path, raw) from None
    try:
        os.write(fd, content)
    finally:
        os.close(fd)
    try:
        yield
    finally:
        # Removed only if it is still ours.
        try:
            if path.read_bytes() == content:
                path.unlink()
        except FileNotFoundError:
            pass


# The settings snapshot


@dataclass(frozen=True)
class SettingChanges:
    """What `record_setting_changes` found.

    Attributes:
        events: One `setting_changed` event per changed key, in key order.
        snapshot_created: True if there was no snapshot, so that one was
            taken and nothing could be compared.
    """

    events: tuple[Event, ...]
    snapshot_created: bool


def setting_values(config: ProjectConfig) -> dict[str, Scalar]:
    """Return every setting of a configuration as dotted keys and scalar values.

    Defaults are filled in, so that writing a default out or leaving it away
    is not a change. `schema_version` is not a setting.
    """
    values: dict[str, Scalar] = {}

    def walk(prefix: str, value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                walk(f"{prefix}.{key}" if prefix else str(key), item)
        elif value is None or isinstance(value, str | int | float | bool):
            values[prefix] = value
        else:
            # A list or another structure: compared and recorded as JSON text.
            values[prefix] = json.dumps(value, sort_keys=True)

    dumped = config.model_dump(mode="json")
    dumped.pop("schema_version", None)
    walk("", dumped)
    return values


def record_setting_changes(
    project: Path, *, clock: Callable[[], datetime] | None = None
) -> SettingChanges:
    """Record each change of `utux.yaml` since the snapshot, then update the snapshot.

    A key that is new has `old_value` null, and a key that is gone has
    `new_value` null. If there is no snapshot, the current file becomes the
    snapshot and nothing is recorded.

    Raises:
        ContractValidationError: `utux.yaml` or the snapshot is invalid.
            Nothing is recorded and the snapshot is unchanged.
        EventLogError: An event could not be written.
    """
    config_path = project / CONFIG_FILE
    # Validated first, so that a missing or unreadable file is reported as
    # every contract file is.
    current = load_project_config(config_path)
    raw = config_path.read_bytes()
    snapshot_path = project / SNAPSHOT_FILE
    if not snapshot_path.is_file():
        atomic_write_bytes(snapshot_path, raw)
        return SettingChanges((), snapshot_created=True)
    previous = ProjectConfig.validate_document(
        parse_yaml(snapshot_path.read_text(encoding="utf-8"), SNAPSHOT_FILE), SNAPSHOT_FILE
    )
    old = setting_values(previous)
    new = setting_values(current)
    log_path = project / EVENT_LOG_FILE
    log = EventLog(log_path) if clock is None else EventLog(log_path, clock=clock)
    events = tuple(
        log.append(
            NewEvent(
                actor=SYSTEM_ACTOR,
                type=EventType.SETTING_CHANGED,
                status=EventStatus.OK,
                data={"key": key, "old_value": old.get(key), "new_value": new.get(key)},
            )
        )
        for key in sorted(old.keys() | new.keys())
        if old.get(key) != new.get(key)
    )
    # Written after the events: if it fails, the changes are recorded again
    # next time rather than lost.
    atomic_write_bytes(snapshot_path, raw)
    return SettingChanges(events, snapshot_created=False)


def repair_project_log(
    project: Path, *, clock: Callable[[], datetime] | None = None
) -> tuple[tuple[LogRepair, ...], SettingChanges]:
    """Repair the event log of a project under the project lock (`utux log repair`).

    Setting changes are recorded after the repair, not before: an event
    cannot be appended to a log whose last line is incomplete.

    Raises:
        ProjectLockedError: As `project_lock`; nothing is changed.
        EventLogError: As `repair_log`.
        ContractValidationError: As `repair_log`, or `utux.yaml` is invalid.
            In the second case the repair is already done.
    """
    with project_lock(project, "log repair", **({} if clock is None else {"clock": clock})):
        log_path = project / EVENT_LOG_FILE
        repairs = repair_log(log_path) if clock is None else repair_log(log_path, clock=clock)
        return repairs, record_setting_changes(project, clock=clock)


@contextmanager
def writing_command(
    project: Path, command: str, *, clock: Callable[[], datetime] | None = None
) -> Iterator[SettingChanges]:
    """Hold the project lock and record setting changes, then run the body.

    Raises:
        ProjectLockedError: As `project_lock`; nothing is recorded.
        ContractValidationError: As `record_setting_changes`; the lock is
            released.
    """
    with project_lock(project, command, **({} if clock is None else {"clock": clock})):
        yield record_setting_changes(project, clock=clock)
