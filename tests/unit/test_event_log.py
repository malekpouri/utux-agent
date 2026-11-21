"""M0-05: the append-only event log."""

import builtins
import io
import json
import os
import threading
import tracemalloc
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError, EventLogCorruptError, EventLogError, UtuxError
from utux.events.log import EventLog
from utux.schemas.event import Event, EventStatus, EventType, NewEvent

FIXED_TIME = datetime(2026, 11, 15, 10, 42, 7, 250_000, tzinfo=UTC)


def _new(**changes: Any) -> NewEvent:
    fields: dict[str, Any] = {
        "actor": "system:utux",
        "type": EventType.STAGE_START,
        "status": EventStatus.OK,
        "data": {"node": "methodology"},
    }
    return NewEvent(**{**fields, **changes})


def _log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "events.jsonl", clock=lambda: FIXED_TIME)


def _line(number: int, **changes: Any) -> str:
    """Return one stored event as a line, without going through the log."""
    fields: dict[str, Any] = {
        "schema_version": 1,
        "event_id": f"e-{number:06d}",
        "run_id": None,
        "request_id": None,
        "parent_id": None,
        "ts": "2026-11-15T10:42:07Z",
        "actor": "agent:planner",
        "stage": "methodology",
        "type": "model_call",
        "model": "synthetic/model",
        "prompt_version": "planner@3",
        "tool_version": None,
        "input_hash": None,
        "output_hash": None,
        "tokens_in": 5120,
        "tokens_out": 830,
        "cost_usd": 0.012,
        "duration_ms": 8400,
        "status": "ok",
        "status_reason": None,
        "retry_reason": None,
        "escalated_from": None,
        "data": {"provider": "synthetic-provider", "is_external": True},
        "artifacts": [],
    }
    return json.dumps({**fields, **changes}) + "\n"


# append()


def test_append_writes_exactly_one_line_that_ends_with_a_newline(tmp_path: Path) -> None:
    log = _log(tmp_path)
    path = tmp_path / "events.jsonl"
    log.append(_new())
    first = path.read_bytes()
    assert first.endswith(b"\n")
    assert first.count(b"\n") == 1
    log.append(
        _new(
            type=EventType.SETTING_CHANGED,
            data={"key": "note", "old_value": None, "new_value": "text with\na line break"},
        )
    )
    second = path.read_bytes()
    # The file grew by exactly one line, and what was there is untouched.
    assert second.startswith(first)
    added = second[len(first) :]
    assert added.endswith(b"\n")
    assert added.count(b"\n") == 1


def test_append_returns_the_stored_event(tmp_path: Path) -> None:
    log = _log(tmp_path)
    event = log.append(_new(type=EventType.PROJECT_CREATED, data={"utux_version": "0.1.0"}))
    assert isinstance(event, Event)
    assert event.schema_version == 1
    assert event.event_id == "e-000001"
    assert event.ts == "2026-11-15T10:42:07.250Z"
    assert event.type is EventType.PROJECT_CREATED
    stored = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert stored == event.to_json_line()


def test_append_flushes_to_disk_before_it_returns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    synced: list[bytes] = []
    real_fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        # What the file holds at the moment it is forced to disk.
        synced.append(path.read_bytes())
        real_fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    log = _log(tmp_path)
    log.append(_new())
    assert len(synced) == 1
    assert synced[0] == path.read_bytes()
    log.append(_new())
    assert len(synced) == 2
    assert synced[1] == path.read_bytes()


def test_append_creates_the_file_but_not_the_directory(tmp_path: Path) -> None:
    log = _log(tmp_path)
    assert not (tmp_path / "events.jsonl").exists()
    log.append(_new())
    assert (tmp_path / "events.jsonl").is_file()
    missing = EventLog(tmp_path / "no-such-directory" / "events.jsonl")
    with pytest.raises(EventLogError):
        missing.append(_new())
    assert issubclass(EventLogError, UtuxError)


def test_timestamp_is_utc_with_z_from_the_clock(tmp_path: Path) -> None:
    times = iter(
        [
            datetime(2026, 11, 15, 23, 59, 59, 999_999, tzinfo=UTC),
            datetime(2026, 11, 16, 0, 0, 0, 0, tzinfo=UTC),
        ]
    )
    log = EventLog(tmp_path / "events.jsonl", clock=lambda: next(times))
    assert log.append(_new()).ts == "2026-11-15T23:59:59.999Z"
    assert log.append(_new()).ts == "2026-11-16T00:00:00.000Z"


def test_clock_that_is_not_utc_is_refused(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.jsonl", clock=lambda: datetime(2026, 11, 15, 10, 0, 0))
    with pytest.raises(EventLogError):
        log.append(_new())
    # The clock is read after the file is locked, so the file may exist; it holds no event.
    assert list(log) == []


# Event ids


def test_event_ids_are_unique_and_increasing(tmp_path: Path) -> None:
    log = _log(tmp_path)
    ids = [log.append(_new()).event_id for _ in range(25)]
    assert ids == [f"e-{number:06d}" for number in range(1, 26)]


def test_ids_continue_after_the_log_is_opened_again(tmp_path: Path) -> None:
    first = _log(tmp_path)
    first.append(_new())
    first.append(_new())
    second = _log(tmp_path)
    assert second.append(_new()).event_id == "e-000003"
    # The first object sees what the second one wrote.
    assert first.append(_new()).event_id == "e-000004"


def test_ids_continue_from_the_last_line_of_an_existing_log(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line(1) + _line(2) + _line(999_999), encoding="utf-8")
    log = _log(tmp_path)
    assert log.append(_new()).event_id == "e-1000000"
    assert log.append(_new()).event_id == "e-1000001"


def test_ids_are_unique_when_several_threads_append_at_once(tmp_path: Path) -> None:
    threads, per_thread = 8, 25
    path = tmp_path / "events.jsonl"
    start = threading.Barrier(threads)

    def worker() -> list[str]:
        # Each thread has its own log object, as separate parts of a program would.
        log = EventLog(path, clock=lambda: FIXED_TIME)
        start.wait(timeout=10)
        return [log.append(_new()).event_id for _ in range(per_thread)]

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker) for _ in range(threads)]
        returned = [event_id for future in futures for event_id in future.result(timeout=60)]
    total = threads * per_thread
    expected = [f"e-{number:06d}" for number in range(1, total + 1)]
    assert sorted(returned) == expected
    # In the file the ids are in increasing order, one event per line.
    assert [event.event_id for event in EventLog(path)] == expected


def test_parent_of_a_new_event_must_be_an_earlier_event(tmp_path: Path) -> None:
    log = _log(tmp_path)
    first = log.append(_new())
    child = log.append(_new(parent_id=first.event_id))
    assert child.parent_id == "e-000001"
    before = (tmp_path / "events.jsonl").read_bytes()
    with pytest.raises(ContractValidationError) as caught:
        log.append(_new(parent_id="e-000050"))
    assert [(p.field, p.code) for p in caught.value.problems] == [
        ("parent_id", "parent_not_earlier")
    ]
    # Nothing was written for the refused event.
    assert (tmp_path / "events.jsonl").read_bytes() == before


# The log is never truncated


class _OpenSpy:
    """Records how the log file is opened, through `os.open` and `open`."""

    def __init__(self, path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.path = str(path)
        self.flags: list[int] = []
        self.modes: list[str] = []
        real_os_open = os.open
        real_open = builtins.open

        def spy_os_open(target: Any, flags: int, *args: Any, **kwargs: Any) -> int:
            if os.fspath(target) == self.path:
                self.flags.append(flags)
            return real_os_open(target, flags, *args, **kwargs)

        def spy_open(target: Any, mode: str = "r", *args: Any, **kwargs: Any) -> Any:
            if not isinstance(target, int) and os.fspath(target) == self.path:
                self.modes.append(mode)
            return real_open(target, mode, *args, **kwargs)

        monkeypatch.setattr(os, "open", spy_os_open)
        monkeypatch.setattr(builtins, "open", spy_open)
        monkeypatch.setattr(io, "open", spy_open)

    def assert_never_truncating(self) -> None:
        assert self.flags or self.modes, "the log file was never opened"
        for flags in self.flags:
            assert not flags & os.O_TRUNC
            writable = flags & (os.O_WRONLY | os.O_RDWR)
            # A writable handle can only add to the end.
            assert not writable or flags & os.O_APPEND
        for mode in self.modes:
            assert "w" not in mode
            assert "+" not in mode
            assert "x" not in mode


def test_log_is_never_opened_in_a_mode_that_can_truncate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    spy = _OpenSpy(path, monkeypatch)
    log = EventLog(path, clock=lambda: FIXED_TIME)
    for _ in range(3):
        log.append(_new())
    assert len(list(log)) == 3
    again = EventLog(path, clock=lambda: FIXED_TIME)
    again.append(_new())
    assert len(list(again)) == 4
    spy.assert_never_truncating()
    # The spy saw the file being opened for writing, so the check is not empty.
    assert any(flags & (os.O_WRONLY | os.O_RDWR) for flags in spy.flags) or any(
        "a" in mode for mode in spy.modes
    )


def test_log_is_not_truncated_when_reading_a_damaged_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "events.jsonl"
    damaged = (_line(1) + _line(2)[:40]).encode()
    path.write_bytes(damaged)
    spy = _OpenSpy(path, monkeypatch)
    log = EventLog(path, clock=lambda: FIXED_TIME)
    with pytest.raises(EventLogCorruptError):
        list(log)
    with pytest.raises(EventLogCorruptError):
        log.append(_new())
    spy.assert_never_truncating()
    assert path.read_bytes() == damaged


def test_existing_lines_are_never_rewritten(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    # Stored with other spacing and key order than the log itself writes.
    original = _line(1) + json.dumps(json.loads(_line(2)), indent=None, sort_keys=True) + "\n"
    path.write_text(original, encoding="utf-8")
    log = _log(tmp_path)
    log.append(_new())
    list(log)
    assert path.read_text(encoding="utf-8").startswith(original)


def test_event_log_has_no_way_to_remove_or_change_events() -> None:
    public = {name for name in vars(EventLog) if not name.startswith("_")}
    assert public == {"append", "path"}


# Reading


def test_reading_returns_the_events_in_file_order(tmp_path: Path) -> None:
    log = _log(tmp_path)
    written = [log.append(_new(request_id=f"q-{n}")) for n in range(5)]
    assert list(log) == written
    # The log can be read more than once.
    assert list(log) == written


def test_a_missing_log_has_no_events(tmp_path: Path) -> None:
    assert list(_log(tmp_path)) == []


def test_an_empty_log_has_no_events(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_bytes(b"")
    log = _log(tmp_path)
    assert list(log) == []
    assert log.append(_new()).event_id == "e-000001"


def test_partially_written_last_line_is_reported_on_read(tmp_path: Path) -> None:
    """A crash in the middle of a write leaves a last line without its newline."""
    path = tmp_path / "events.jsonl"
    path.write_text(_line(1) + _line(2) + _line(3)[:57], encoding="utf-8")
    events: list[Event] = []
    with pytest.raises(EventLogCorruptError) as caught:
        events.extend(EventLog(path))
    # The complete events were delivered, and the damaged line was reported.
    assert [event.event_id for event in events] == ["e-000001", "e-000002"]
    error = caught.value
    assert error.path == path
    assert error.line == 3
    assert "incomplete" in str(error)
    assert str(path) in str(error)
    assert issubclass(EventLogCorruptError, EventLogError)


def test_last_line_without_newline_is_incomplete_even_if_it_parses(tmp_path: Path) -> None:
    """A write may stop exactly before the newline; the line still cannot be trusted."""
    path = tmp_path / "events.jsonl"
    path.write_text(_line(1) + _line(2).rstrip("\n"), encoding="utf-8")
    with pytest.raises(EventLogCorruptError) as caught:
        list(EventLog(path))
    assert caught.value.line == 2


def test_append_refuses_a_log_whose_last_line_is_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    damaged = _line(1) + _line(2)[:30]
    path.write_text(damaged, encoding="utf-8")
    with pytest.raises(EventLogCorruptError) as caught:
        _log(tmp_path).append(_new())
    assert caught.value.line == 2
    # Appending would have joined the new event to the broken line.
    assert path.read_text(encoding="utf-8") == damaged


def test_line_that_is_not_a_valid_event_is_reported_with_its_line_number(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line(1) + _line(2, type="coffee_break") + _line(3), encoding="utf-8")
    events: list[Event] = []
    with pytest.raises(ContractValidationError) as caught:
        events.extend(EventLog(path))
    assert [event.event_id for event in events] == ["e-000001"]
    assert caught.value.source == f"{path}:2"
    assert [(p.field, p.code) for p in caught.value.problems] == [("type", "enum")]


@pytest.mark.parametrize("bad", ["\n", "not json\n", "[1, 2]\n"])
def test_line_that_is_not_an_event_at_all_is_reported(tmp_path: Path, bad: str) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line(1) + bad + _line(3), encoding="utf-8")
    with pytest.raises(ContractValidationError) as caught:
        list(EventLog(path))
    assert caught.value.source == f"{path}:2"


@pytest.mark.parametrize(
    ("numbers", "line"),
    [([1, 2, 2], 3), ([1, 3, 2], 3), ([5, 4], 2)],
)
def test_ids_that_do_not_increase_are_reported_on_read(
    tmp_path: Path, numbers: list[int], line: int
) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("".join(_line(number) for number in numbers), encoding="utf-8")
    with pytest.raises(EventLogCorruptError) as caught:
        list(EventLog(path))
    assert caught.value.line == line
    assert "increas" in str(caught.value)


def test_gaps_between_ids_are_allowed(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line(1) + _line(5) + _line(40), encoding="utf-8")
    assert [event.event_id for event in EventLog(path)] == ["e-000001", "e-000005", "e-000040"]


# Streaming


def _write_many(path: Path, count: int) -> None:
    with path.open("a", encoding="utf-8") as stream:
        for number in range(1, count + 1):
            stream.write(_line(number))


def test_reading_10000_events_does_not_load_the_file_into_memory(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    _write_many(path, 10_000)
    size = path.stat().st_size
    assert size > 3_000_000

    count = 0
    last = ""
    tracemalloc.start()
    try:
        for event in EventLog(path):
            count += 1
            last = event.event_id
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert count == 10_000
    assert last == "e-010000"
    # Holding the file, or all events, would need several megabytes.
    assert peak < size // 10


def test_reading_is_lazy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first event is available after reading a small part of a large file."""
    path = tmp_path / "events.jsonl"
    _write_many(path, 10_000)
    size = path.stat().st_size
    read_bytes = 0
    real_read = os.read

    def counting_read(fd: int, length: int) -> bytes:
        nonlocal read_bytes
        data = real_read(fd, length)
        read_bytes += len(data)
        return data

    monkeypatch.setattr(os, "read", counting_read)
    events: Iterator[Event] = iter(EventLog(path))
    assert next(events).event_id == "e-000001"
    assert 0 < read_bytes < size // 10
    assert next(events).event_id == "e-000002"


# Timestamps and ids agree


def test_timestamp_is_taken_while_the_log_is_locked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The clock is read after the lock is taken, so a later id never has an earlier time."""
    from utux.events import log as log_module

    steps: list[str] = []
    real_flock = log_module.fcntl.flock

    def recording_flock(fd: int, operation: int) -> None:
        real_flock(fd, operation)
        steps.append("lock")

    def clock() -> datetime:
        steps.append("clock")
        return FIXED_TIME

    monkeypatch.setattr(log_module.fcntl, "flock", recording_flock)
    log = EventLog(tmp_path / "events.jsonl", clock=clock)
    log.append(_new())
    log.append(_new())
    assert steps == ["lock", "clock", "lock", "clock"]


def test_timestamps_do_not_decrease_as_ids_increase_across_threads(tmp_path: Path) -> None:
    threads, per_thread = 8, 25
    path = tmp_path / "events.jsonl"
    tick = threading.Lock()
    current = [FIXED_TIME]

    def clock() -> datetime:
        # Every reading of the clock is one millisecond later than the one before.
        with tick:
            current[0] += timedelta(milliseconds=1)
            return current[0]

    start = threading.Barrier(threads)

    def worker() -> None:
        log = EventLog(path, clock=clock)
        start.wait(timeout=10)
        for _ in range(per_thread):
            log.append(_new())

    with ThreadPoolExecutor(max_workers=threads) as pool:
        for future in [pool.submit(worker) for _ in range(threads)]:
            future.result(timeout=60)
    stamps = [event.ts for event in EventLog(path)]
    assert len(stamps) == threads * per_thread
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)


def test_event_one_million_follows_e_999999(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(_line(999_998) + _line(999_999), encoding="utf-8")
    log = _log(tmp_path)
    million = log.append(_new())
    assert million.event_id == "e-1000000"
    # The seven-digit id is a valid event id, also as a parent.
    assert Event.from_json(million.to_json_line()) == million
    child = log.append(_new(parent_id="e-1000000"))
    assert child.event_id == "e-1000001"
    assert child.parent_id == "e-1000000"
    # Reading compares ids as numbers: as text, "e-1000000" sorts before "e-999999".
    assert [event.event_id for event in log] == [
        "e-999998",
        "e-999999",
        "e-1000000",
        "e-1000001",
    ]


# Events that are refused by the schema are not written


def test_event_that_breaks_a_rule_is_not_written(tmp_path: Path) -> None:
    log = _log(tmp_path)
    log.append(_new())
    before = (tmp_path / "events.jsonl").read_bytes()
    for bad in (
        _new(type=EventType.MODEL_CALL),  # no model
        _new(status=EventStatus.ERROR),  # no reason
        _new(data={"note": "x"}),  # key not defined for the type
    ):
        with pytest.raises(ContractValidationError):
            log.append(bad)
    assert (tmp_path / "events.jsonl").read_bytes() == before
