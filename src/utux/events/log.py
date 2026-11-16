"""The append-only event log, `events.jsonl`.

One event is one line. The log is only ever added to: this module has no
operation that rewrites, reorders or removes a line, and it never opens the
file in a mode that can truncate it.

Event ids are given out by `append()`. It holds an exclusive lock on the file
while it reads the last id and writes the next event, so ids are unique and
increasing also when several threads or processes append to one log. The
lock is `flock`, which is available on POSIX systems only.

A write that was interrupted leaves a last line without its newline. Such a
line is reported, on read and on append, and is never dropped or completed.
"""

import fcntl
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from utux.errors import EventLogCorruptError, EventLogError
from utux.schemas.event import Event, NewEvent, event_number, format_event_id

_NEWLINE = b"\n"
_READ_BYTES = 64 * 1024
_INCOMPLETE = "the last line is incomplete; a write to the log was interrupted"


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
        try:
            # O_APPEND: every write goes to the end of the file. No O_TRUNC.
            fd = os.open(self._path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        except OSError as error:
            raise EventLogError(f"cannot open {self._path}: {error.strerror}") from error
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            # The clock is read while the lock is held, so the time of an
            # event is never earlier than that of an event with a lower id.
            stored = Event.validate_document(
                {
                    "schema_version": Event.SCHEMA_VERSION,
                    "event_id": format_event_id(self._last_number() + 1),
                    "ts": self._timestamp(),
                    **event.model_dump(mode="json"),
                },
                str(self._path),
            )
            _write_all(fd, stored.to_json_line().encode("utf-8"))
            os.fsync(fd)
        except OSError as error:
            raise EventLogError(f"cannot write {self._path}: {error.strerror}") from error
        finally:
            # Closing the file also releases the lock.
            os.close(fd)
        return stored

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

    def _timestamp(self) -> str:
        now = self._clock()
        if now.utcoffset() != timedelta(0):
            raise EventLogError("the clock of the event log must return a time in UTC")
        return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"

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
