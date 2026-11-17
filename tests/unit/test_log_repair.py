"""M0-08b: repairing an event log whose last line is incomplete."""

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from utux.errors import ContractValidationError, EventLogCorruptError, EventLogError
from utux.events import log as log_module
from utux.events.log import EventLog, repair_log
from utux.schemas.event import EventStatus, EventType, NewEvent
from utux.workspace.hashing import hash_bytes
from utux.workspace.validation import validate_project

PROJECT = Path(__file__).resolve().parents[1] / "fixtures" / "projects" / "valid_full"
FIXED_TIME = datetime(2026, 11, 16, 11, 7, 12, 125_000, tzinfo=UTC)
SIDE_FILE = "events.jsonl.fragment-20261116T110712.125Z"


def _clock() -> datetime:
    return FIXED_TIME


def _damaged(tmp_path: Path, cut: int = 57) -> tuple[Path, bytes, bytes]:
    """A copy of the valid fixture project whose log ends in a cut third line.

    Returns the project, the bytes of the complete lines, and the fragment.
    """
    project = tmp_path / "p"
    shutil.copytree(PROJECT, project)
    log = project / "events.jsonl"
    complete = log.read_bytes()
    third = json.loads(complete.split(b"\n")[1])
    third.update(event_id="e-000003", parent_id=None)
    fragment = (json.dumps(third) + "\n").encode()[:cut]
    log.write_bytes(complete + fragment)
    return project, complete, fragment


def _side_files(project: Path) -> list[str]:
    return sorted(path.name for path in project.glob("events.jsonl.fragment-*"))


# The repair


def test_fragment_is_saved_byte_for_byte_and_the_log_ends_with_its_last_complete_event(
    tmp_path: Path,
) -> None:
    project, _, fragment = _damaged(tmp_path)
    repair = repair_log(project / "events.jsonl", clock=_clock)
    assert repair is not None
    assert _side_files(project) == [SIDE_FILE]
    assert (project / SIDE_FILE).read_bytes() == fragment
    assert repair.fragment_file == SIDE_FILE
    assert repair.fragment_bytes == len(fragment)
    assert repair.fragment_hash == hash_bytes(fragment)


def test_complete_lines_are_never_changed(tmp_path: Path) -> None:
    project, complete, _ = _damaged(tmp_path)
    repair_log(project / "events.jsonl", clock=_clock)
    after = (project / "events.jsonl").read_bytes()
    assert after.startswith(complete)
    # Exactly one line follows: the log_repaired event.
    added = after[len(complete) :]
    assert added.endswith(b"\n")
    assert added.count(b"\n") == 1


def test_repair_is_recorded_as_the_next_event(tmp_path: Path) -> None:
    project, _, fragment = _damaged(tmp_path)
    repair = repair_log(project / "events.jsonl", clock=_clock)
    assert repair is not None
    events = list(EventLog(project / "events.jsonl"))
    assert [event.event_id for event in events] == ["e-000001", "e-000002", "e-000003"]
    last = events[-1]
    assert last == repair.event
    assert last.type is EventType.LOG_REPAIRED
    assert last.actor == "system:utux"
    assert last.status is EventStatus.OK
    assert last.ts == "2026-11-16T11:07:12.125Z"
    assert last.data == {
        "fragment_file": SIDE_FILE,
        "fragment_hash": hash_bytes(fragment),
        "fragment_bytes": len(fragment),
    }


def test_repaired_project_passes_validation(tmp_path: Path) -> None:
    project, _, _ = _damaged(tmp_path)
    assert [p.code for p in validate_project(project).problems] == ["incomplete_line"]
    repair_log(project / "events.jsonl", clock=_clock)
    assert validate_project(project).problems == ()


def test_the_log_can_be_appended_to_after_the_repair(tmp_path: Path) -> None:
    project, _, _ = _damaged(tmp_path)
    log = EventLog(project / "events.jsonl", clock=_clock)
    with pytest.raises(EventLogCorruptError):
        log.append(NewEvent(actor="system:utux", type=EventType.STAGE_START, status=EventStatus.OK))
    repair_log(project / "events.jsonl", clock=_clock)
    stored = log.append(
        NewEvent(actor="system:utux", type=EventType.STAGE_START, status=EventStatus.OK)
    )
    assert stored.event_id == "e-000004"


def test_fragment_that_is_only_a_newline_short_is_still_a_fragment(tmp_path: Path) -> None:
    """A write may stop just before the newline; the line still cannot be trusted."""
    project, complete, _ = _damaged(tmp_path)
    full_third = (project / "events.jsonl").read_bytes()[len(complete) :]
    line = json.loads(complete.split(b"\n")[1])
    line.update(event_id="e-000003")
    whole = json.dumps(line).encode()
    (project / "events.jsonl").write_bytes(complete + whole)
    repair = repair_log(project / "events.jsonl", clock=_clock)
    assert repair is not None
    assert (project / SIDE_FILE).read_bytes() == whole
    assert full_third  # the helper did write a fragment before


def test_log_that_is_only_a_fragment_is_repaired_to_its_repair_event(tmp_path: Path) -> None:
    """A crash while writing the very first event leaves nothing complete."""
    log = tmp_path / "events.jsonl"
    log.write_bytes(b'{"schema_version": 1, "event_')
    repair = repair_log(log, clock=_clock)
    assert repair is not None
    (event,) = list(EventLog(log))
    assert event.event_id == "e-000001"
    assert event.type is EventType.LOG_REPAIRED


# Nothing to repair


@pytest.mark.parametrize("content", [b"", None])
def test_log_with_a_complete_last_line_is_left_alone(tmp_path: Path, content: bytes | None) -> None:
    project = tmp_path / "p"
    shutil.copytree(PROJECT, project)
    log = project / "events.jsonl"
    if content is not None:
        log.write_bytes(content)
    before = log.read_bytes()
    assert repair_log(log, clock=_clock) is None
    assert log.read_bytes() == before
    assert _side_files(project) == []


def test_missing_log_is_a_typed_error_and_nothing_is_created(tmp_path: Path) -> None:
    with pytest.raises(EventLogError):
        repair_log(tmp_path / "events.jsonl", clock=_clock)
    assert list(tmp_path.iterdir()) == []


# Refusals leave the log unchanged


def test_invalid_last_complete_line_is_refused_and_nothing_changes(tmp_path: Path) -> None:
    log = tmp_path / "events.jsonl"
    content = b'{"not": "an event"}\n{"schema_version": 1, "ev'
    log.write_bytes(content)
    with pytest.raises(ContractValidationError) as caught:
        repair_log(log, clock=_clock)
    assert caught.value.source == f"{log}:1"
    assert log.read_bytes() == content
    assert sorted(path.name for path in tmp_path.iterdir()) == ["events.jsonl"]


def test_existing_fragment_file_is_never_overwritten(tmp_path: Path) -> None:
    project, complete, fragment = _damaged(tmp_path)
    (project / SIDE_FILE).write_bytes(b"an earlier fragment\n")
    with pytest.raises(EventLogError, match="already exists"):
        repair_log(project / "events.jsonl", clock=_clock)
    assert (project / SIDE_FILE).read_bytes() == b"an earlier fragment\n"
    assert (project / "events.jsonl").read_bytes() == complete + fragment


def test_failure_to_save_the_fragment_leaves_the_log_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, complete, fragment = _damaged(tmp_path)

    def fail(source: Any, destination: Any) -> None:
        raise OSError(28, "synthetic: no space left on device")

    monkeypatch.setattr(os, "replace", fail)
    with pytest.raises(EventLogError):
        repair_log(project / "events.jsonl", clock=_clock)
    assert (project / "events.jsonl").read_bytes() == complete + fragment
    assert _side_files(project) == []


def test_fragment_is_saved_before_the_log_is_cut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _, fragment = _damaged(tmp_path)
    side = project / SIDE_FILE
    seen: list[bytes] = []
    real = os.ftruncate

    def spy(fd: int, length: int) -> None:
        # When the log is cut, the fragment is already safe on disk.
        seen.append(side.read_bytes())
        real(fd, length)

    monkeypatch.setattr(os, "ftruncate", spy)
    repair_log(project / "events.jsonl", clock=_clock)
    assert seen == [fragment]


def test_repair_holds_the_lock_of_the_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project, _, _ = _damaged(tmp_path)
    steps: list[str] = []
    real_flock, real_ftruncate = log_module.fcntl.flock, os.ftruncate

    def flock(fd: int, operation: int) -> None:
        real_flock(fd, operation)
        steps.append("lock")

    def ftruncate(fd: int, length: int) -> None:
        steps.append("cut")
        real_ftruncate(fd, length)

    monkeypatch.setattr(log_module.fcntl, "flock", flock)
    monkeypatch.setattr(os, "ftruncate", ftruncate)
    repair_log(project / "events.jsonl", clock=_clock)
    # One lock, taken before the cut and held for the repair event too.
    assert steps == ["lock", "cut"]


# Never automatic


def test_reading_and_appending_still_refuse_an_incomplete_line(tmp_path: Path) -> None:
    project, complete, fragment = _damaged(tmp_path)
    log = EventLog(project / "events.jsonl")
    with pytest.raises(EventLogCorruptError) as caught:
        list(log)
    assert "utux log repair" in str(caught.value)
    with pytest.raises(EventLogCorruptError):
        log.append(NewEvent(actor="system:utux", type=EventType.STAGE_START, status=EventStatus.OK))
    validate_project(project)
    assert (project / "events.jsonl").read_bytes() == complete + fragment
    assert _side_files(project) == []


def test_validation_points_to_the_repair_command(tmp_path: Path) -> None:
    project, _, _ = _damaged(tmp_path)
    (problem,) = validate_project(project).problems
    assert "utux log repair" in problem.reason
