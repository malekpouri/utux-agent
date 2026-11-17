"""The append-only event log, `events.jsonl`.

One event is one line. The log is only ever added to: this module has no
operation that rewrites, reorders or removes a line, and it never opens the
file in a mode that can truncate it.

Event ids are given out by `append()`. It holds an exclusive lock on the file
while it reads the last id and writes the next event, so ids are unique and
increasing also when several threads or processes append to one log. The
lock is `flock`, which is available on POSIX systems only.

A write that was interrupted leaves a last line without its newline. Such a
line is reported, on read and on append, and is never dropped or completed
automatically. `repair_log`, which runs only when a person asks for it with
`utux log repair`, saves the fragment to a side file, removes it from the log
and records the repair. It never changes a complete line.
"""

import fcntl
import os
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from utux.errors import AtomicWriteError, EventLogCorruptError, EventLogError
from utux.schemas.event import (
    Event,
    EventStatus,
    EventType,
    NewEvent,
    event_number,
    format_event_id,
)
from utux.workspace.atomic import atomic_write_bytes
from utux.workspace.hashing import hash_bytes

_NEWLINE = b"\n"
_READ_BYTES = 64 * 1024
_INCOMPLETE = "the last line is incomplete; a write to the log was interrupted; run utux log repair"
SYSTEM_ACTOR = "system:utux"
FRAGMENT_SUFFIX = ".fragment-"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class EventLog:
    """The event log of one project.

    Iterating over the log yields its events in file order, reading the file
    in pieces. Iteration raises `EventLogCorruptError` at an incomplete last
    line or at an id that does not increase, and `ContractValidationError` at
    a line that is not a valid event. Events before that line are still
    yielded. A log file that does not exist has no events.
    """

    def __init__(self, path: Path, *, clock: Callable[[], datetime] = _utc_now) -> None:
        """Create the log object. Nothing is read or written yet.

        Args:
            path: The log file. Its directory must exist; the file is created
                by the first `append()`.
            clock: Returns the current time in UTC. Tests pass a fixed time.
        """
        self._path = path
        self._clock = clock

    @property
    def path(self) -> Path:
        """The log file."""
        return self._path

    def append(self, event: NewEvent) -> Event:
        """Store an event as one line and return it with its id and time.

        The line is written with a single write and forced to disk before
        the call returns.

        Raises:
            EventLogCorruptError: If the last line of the log is incomplete.
                Nothing is written.
            ContractValidationError: If the event is not valid once it has
                its id, for example because its parent is not an earlier
                event. Nothing is written.
            EventLogError: If the file cannot be opened or written, or the
                clock does not return a UTC time.
        """
        fd = self._open_for_append(create=True)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            # The clock is read while the lock is held, so the time of an
            # event is never earlier than that of an event with a lower id.
            return self._store(fd, event, self._now())
        finally:
            # Closing the file also releases the lock.
            os.close(fd)

    def __iter__(self) -> Iterator[Event]:
        """Yield the events of the log in file order, reading in pieces."""
        previous = 0
        for number, line in enumerate(self._lines(), start=1):
            if not line.endswith(_NEWLINE):
                raise EventLogCorruptError(self._path, number, _INCOMPLETE)
            event = _parse(line, f"{self._path}:{number}")
            current = event_number(event.event_id)
            if current <= previous:
                raise EventLogCorruptError(
                    self._path,
                    number,
                    f"event id {event.event_id} does not increase; "
                    f"the line before has {format_event_id(previous)}",
                )
            previous = current
            yield event

    def _open_for_append(self, *, create: bool) -> int:
        # O_APPEND: every write goes to the end of the file. Never O_TRUNC.
        flags = os.O_WRONLY | os.O_APPEND | (os.O_CREAT if create else 0)
        try:
            return os.open(self._path, flags, 0o644)
        except OSError as error:
            raise EventLogError(f"cannot open {self._path}: {error.strerror}") from error

    def _store(self, fd: int, event: NewEvent, now: datetime) -> Event:
        """Write one event at the end of the log. The caller holds the lock on `fd`."""
        stored = Event.validate_document(
            {
                "schema_version": Event.SCHEMA_VERSION,
                "event_id": format_event_id(self._last_number() + 1),
                "ts": _event_time(now),
                **event.model_dump(mode="json"),
            },
            str(self._path),
        )
        try:
            _write_all(fd, stored.to_json_line().encode("utf-8"))
            os.fsync(fd)
        except OSError as error:
            raise EventLogError(f"cannot write {self._path}: {error.strerror}") from error
        return stored

    def _now(self) -> datetime:
        now = self._clock()
        if now.utcoffset() != timedelta(0):
            raise EventLogError("the clock of the event log must return a time in UTC")
        return now

    def _lines(self) -> Iterator[bytes]:
        """Yield the lines of the file with their newline; the last may lack it."""
        try:
            fd = os.open(self._path, os.O_RDONLY)
        except FileNotFoundError:
            return
        except OSError as error:
            raise EventLogError(f"cannot open {self._path}: {error.strerror}") from error
        try:
            pending = b""
            while chunk := os.read(fd, _READ_BYTES):
                pending += chunk
                *complete, pending = pending.split(_NEWLINE)
                for line in complete:
                    yield line + _NEWLINE
            if pending:
                yield pending
        except OSError as error:
            raise EventLogError(f"cannot read {self._path}: {error.strerror}") from error
        finally:
            os.close(fd)

    def _last_number(self) -> int:
        """Return the number of the last stored event, or 0 for an empty log.

        Only the end of the file is read. The caller holds the lock.
        """
        fd = os.open(self._path, os.O_RDONLY)
        try:
            size = os.fstat(fd).st_size
            if size == 0:
                return 0
            tail = b""
            start = size
            # Read backwards until the tail holds the whole last line.
            while start > 0 and tail.count(_NEWLINE) < 2:
                step = min(_READ_BYTES, start)
                start -= step
                tail = os.pread(fd, step, start) + tail
        finally:
            os.close(fd)
        if not tail.endswith(_NEWLINE):
            raise EventLogCorruptError(self._path, self._line_count(), _INCOMPLETE)
        last_line = tail[:-1].rsplit(_NEWLINE, 1)[-1] + _NEWLINE
        return event_number(_parse(last_line, f"{self._path}:{self._line_count()}").event_id)

    def _line_count(self) -> int:
        """Count the lines of the file. Used only to build an error message."""
        return sum(1 for _ in self._lines())


@dataclass(frozen=True)
class LogRepair:
    """What `repair_log` did.

    Attributes:
        fragment_file: Name of the side file that holds the fragment, in the
            directory of the log.
        fragment_bytes: Length of the fragment in bytes.
        fragment_hash: Content hash of the fragment.
        event: The `log_repaired` event that records the repair.
    """

    fragment_file: str
    fragment_bytes: int
    fragment_hash: str
    event: Event


def repair_log(path: Path, *, clock: Callable[[], datetime] = _utc_now) -> LogRepair | None:
    """Repair a log whose last line was left incomplete by an interrupted write.

    This runs only when a person asks for it, through `utux log repair`. It
    saves the incomplete last fragment byte for byte to
    `events.jsonl.fragment-<time>`, removes the fragment from the log so that
    the log ends with its last complete event, and appends a `log_repaired`
    event with the fragment's file name, hash and byte length. Complete lines
    are never changed. The lock of the log is held throughout.

    Args:
        path: The log file.
        clock: Returns the current time in UTC. Tests pass a fixed time.

    Returns:
        What was done, or None if the last line of the log is complete and
        nothing was changed.

    Raises:
        EventLogError: If the log cannot be opened, the fragment cannot be
            saved, or the side file already exists. The log is then unchanged.
        ContractValidationError: If the last complete line is not a valid
            event. The log is then unchanged.
    """
    log = EventLog(path, clock=clock)
    fd = log._open_for_append(create=False)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        size = os.stat(path).st_size
        keep = _complete_length(path, size)
        if keep == size:
            return None
        fragment = _read_range(path, keep, size)
        if keep > 0:
            # The repair event follows the last complete line, so that line
            # must be an event. Checked before anything is changed.
            _parse(_read_last_line(path, keep), f"{path}:{log._line_count() - 1}")
        now = log._now()
        side = path.with_name(path.name + FRAGMENT_SUFFIX + _file_time(now))
        if side.exists():
            raise EventLogError(f"cannot repair {path}: {side.name} already exists")
        try:
            atomic_write_bytes(side, fragment)
        except AtomicWriteError as error:
            raise EventLogError(f"cannot save the fragment of {path}: {error}") from error
        try:
            os.ftruncate(fd, keep)
            os.fsync(fd)
        except OSError as error:
            raise EventLogError(f"cannot repair {path}: {error.strerror}") from error
        stored = log._store(
            fd,
            NewEvent(
                actor=SYSTEM_ACTOR,
                type=EventType.LOG_REPAIRED,
                status=EventStatus.OK,
                data={
                    "fragment_file": side.name,
                    "fragment_hash": hash_bytes(fragment),
                    "fragment_bytes": len(fragment),
                },
            ),
            now,
        )
        return LogRepair(side.name, len(fragment), hash_bytes(fragment), stored)
    finally:
        os.close(fd)


def _complete_length(path: Path, size: int) -> int:
    """Return the length of the log up to and including its last newline."""
    fd = os.open(path, os.O_RDONLY)
    try:
        end = size
        while end > 0:
            start = max(0, end - _READ_BYTES)
            chunk = os.pread(fd, end - start, start)
            index = chunk.rfind(_NEWLINE)
            if index >= 0:
                return start + index + 1
            end = start
        return 0
    finally:
        os.close(fd)


def _read_range(path: Path, start: int, end: int) -> bytes:
    fd = os.open(path, os.O_RDONLY)
    try:
        return os.pread(fd, end - start, start)
    finally:
        os.close(fd)


def _read_last_line(path: Path, end: int) -> bytes:
    """Return the complete line that ends just before `end`, with its newline."""
    start = _complete_length(path, end - 1)
    return _read_range(path, start, end)


def _event_time(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _file_time(now: datetime) -> str:
    """The time for a file name: no colons, which some file systems refuse."""
    return now.strftime("%Y%m%dT%H%M%S.") + f"{now.microsecond // 1000:03d}Z"


def _parse(line: bytes, source: str) -> Event:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError:
        # Let the JSON reader report it as a line that is not valid JSON.
        text = line.decode("utf-8", errors="replace")
    return Event.from_json(text, source)


def _write_all(fd: int, data: bytes) -> None:
    written = os.write(fd, data)
    if written != len(data):
        # With O_APPEND a short write cannot be completed as one line.
        raise OSError(None, "the event was only partly written")
