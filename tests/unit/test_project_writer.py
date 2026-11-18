"""M1-05: the project lock and the record of setting changes.

Every command that writes to a project holds the project lock under `.utux/`
and, before it acts, records each change of `utux.yaml` since the last
snapshot as a `setting_changed` event.
"""

import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from utux.errors import ContractValidationError, ProjectLockedError, StaleProjectLockError
from utux.events.log import EventLog
from utux.schemas.event import EventStatus, EventType
from utux.schemas.project_config import DataPolicy
from utux.workspace.project import init_project
from utux.workspace.writer import (
    LOCK_FILE,
    SNAPSHOT_FILE,
    project_lock,
    record_setting_changes,
    writing_command,
)

FIXED = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return init_project(
        tmp_path / "p", budget_usd=20, data_policy=DataPolicy.LOCAL_ONLY, clock=lambda: FIXED
    )


def _dead_pid() -> int:
    child = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getpid())"],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(child.stdout)


def _write_lock(project: Path, **fields: object) -> None:
    holder = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "command": "synthetic",
        "started_at": "2026-11-18T09:00:00Z",
        **fields,
    }
    (project / LOCK_FILE).write_text(json.dumps(holder), encoding="utf-8")


# The lock


def test_the_lock_is_held_while_the_command_runs_and_released_after(project: Path) -> None:
    with project_lock(project, "model ping"):
        holder = json.loads((project / LOCK_FILE).read_text(encoding="utf-8"))
        assert holder["pid"] == os.getpid()
        assert holder["command"] == "model ping"
    assert not (project / LOCK_FILE).exists()


def test_a_second_writer_is_refused_with_the_holders_process_id(project: Path) -> None:
    with (
        project_lock(project, "model ping"),
        pytest.raises(ProjectLockedError) as caught,
        project_lock(project, "log repair"),
    ):
        pass
    message = str(caught.value)
    assert f"process {os.getpid()}" in message
    assert "model ping" in message
    assert not isinstance(caught.value, StaleProjectLockError)


def test_a_lock_left_by_a_dead_process_is_reported_not_taken_over(project: Path) -> None:
    pid = _dead_pid()
    _write_lock(project, pid=pid)
    before = (project / LOCK_FILE).read_bytes()
    with pytest.raises(StaleProjectLockError) as caught, project_lock(project, "model ping"):
        pass
    message = str(caught.value)
    assert f"process {pid}" in message
    assert "no longer running" in message
    assert LOCK_FILE in message
    assert (project / LOCK_FILE).read_bytes() == before


def test_a_lock_of_another_host_is_held_since_it_cannot_be_checked(project: Path) -> None:
    _write_lock(project, host="synthetic-other-host", pid=_dead_pid())
    with pytest.raises(ProjectLockedError) as caught, project_lock(project, "model ping"):
        pass
    assert not isinstance(caught.value, StaleProjectLockError)
    assert "synthetic-other-host" in str(caught.value)


def test_an_unreadable_lock_is_reported(project: Path) -> None:
    (project / LOCK_FILE).write_text("{not json", encoding="utf-8")
    with (
        pytest.raises(ProjectLockedError, match="cannot be read"),
        project_lock(project, "model ping"),
    ):
        pass


def test_the_lock_is_released_when_the_command_fails(project: Path) -> None:
    with pytest.raises(RuntimeError), project_lock(project, "model ping"):
        raise RuntimeError("synthetic failure")
    assert not (project / LOCK_FILE).exists()


def test_a_lock_that_is_no_longer_ours_is_not_removed(project: Path) -> None:
    with project_lock(project, "model ping"):
        _write_lock(project, pid=os.getpid() + 1, command="other")
    assert json.loads((project / LOCK_FILE).read_text(encoding="utf-8"))["command"] == "other"


# The settings snapshot


def _config(project: Path) -> Path:
    return project / "utux.yaml"


def _edit(project: Path, old: str, new: str) -> None:
    text = _config(project).read_text(encoding="utf-8")
    assert text.count(old) == 1, old
    _config(project).write_text(text.replace(old, new), encoding="utf-8")


def _setting_events(project: Path) -> list[tuple[object, ...]]:
    return [
        (e.data["key"], e.data["old_value"], e.data["new_value"])
        for e in EventLog(project / "events.jsonl")
        if e.type is EventType.SETTING_CHANGED
    ]


def test_init_records_the_first_snapshot(project: Path) -> None:
    assert (project / SNAPSHOT_FILE).read_bytes() == _config(project).read_bytes()


def test_no_change_writes_no_event(project: Path) -> None:
    changes = record_setting_changes(project)
    assert changes.events == ()
    assert changes.snapshot_created is False
    assert _setting_events(project) == []


def test_each_changed_key_is_one_event_with_old_and_new_value(project: Path) -> None:
    _edit(project, "total_usd: 20", "total_usd: 30")
    _edit(project, "enabled: true", "enabled: false")
    changes = record_setting_changes(project)
    assert _setting_events(project) == [
        ("budget.total_usd", 20.0, 30.0),
        ("verification.enabled", True, False),
    ]
    for event in changes.events:
        assert event.actor == "system:utux"
        assert event.status is EventStatus.OK
    assert (project / SNAPSHOT_FILE).read_bytes() == _config(project).read_bytes()
    # Recorded once: the snapshot now holds the new values.
    assert record_setting_changes(project).events == ()


def test_a_key_that_appears_or_disappears_has_null_on_the_other_side(project: Path) -> None:
    _edit(project, "  tiers: {}\n", "  tiers:\n    light: synthetic/light-model\n")
    record_setting_changes(project)
    _edit(project, "  tiers:\n    light: synthetic/light-model\n", "  tiers: {}\n")
    record_setting_changes(project)
    assert _setting_events(project) == [
        ("models.tiers.light", None, "synthetic/light-model"),
        ("models.tiers.light", "synthetic/light-model", None),
    ]


def test_writing_a_default_out_or_leaving_it_away_is_no_change(project: Path) -> None:
    _edit(project, "verification:\n  enabled: true\n", "")
    assert record_setting_changes(project).events == ()


def test_a_missing_snapshot_is_taken_without_events(project: Path) -> None:
    (project / SNAPSHOT_FILE).unlink()
    _edit(project, "total_usd: 20", "total_usd: 30")
    changes = record_setting_changes(project)
    assert changes.snapshot_created is True
    assert changes.events == ()
    assert (project / SNAPSHOT_FILE).read_bytes() == _config(project).read_bytes()


def test_an_invalid_configuration_records_nothing(project: Path) -> None:
    before = (project / SNAPSHOT_FILE).read_bytes()
    _edit(project, "total_usd: 20", "total_usd: -1")
    with pytest.raises(ContractValidationError):
        record_setting_changes(project)
    assert (project / SNAPSHOT_FILE).read_bytes() == before
    assert _setting_events(project) == []


def test_a_writing_command_takes_the_lock_and_records_changes_first(project: Path) -> None:
    _edit(project, "total_usd: 20", "total_usd: 25")
    with writing_command(project, "synthetic") as changes:
        assert (project / LOCK_FILE).exists()
        assert [e.data["key"] for e in changes.events] == ["budget.total_usd"]
    assert not (project / LOCK_FILE).exists()


def test_a_refused_writer_records_nothing(project: Path) -> None:
    _edit(project, "total_usd: 20", "total_usd: 25")
    with (
        project_lock(project, "model ping"),
        pytest.raises(ProjectLockedError),
        writing_command(project, "log repair"),
    ):
        pass
    assert _setting_events(project) == []


def test_a_missing_configuration_is_a_contract_error_naming_the_file(project: Path) -> None:
    _config(project).unlink()
    with pytest.raises(ContractValidationError, match=r"utux\.yaml"):
        record_setting_changes(project)
