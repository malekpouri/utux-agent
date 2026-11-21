"""M0-08b: `utux log repair`."""

import os
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app
from utux.events.log import EventLog
from utux.schemas.event import EventType
from utux.workspace.writer import project_lock

PROJECT = Path(__file__).resolve().parents[1] / "fixtures" / "projects" / "valid_full"

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


FRAGMENT = b'{"schema_version": 1, "event_id": "e-0000'


def _damaged(tmp_path: Path) -> Path:
    project = tmp_path / "p"
    shutil.copytree(PROJECT, project)
    with (project / "events.jsonl").open("ab") as stream:
        stream.write(FRAGMENT)
    return project


def test_repair_then_validate(tmp_path: Path) -> None:
    project = _damaged(tmp_path)
    assert runner.invoke(app, ["validate", str(project)]).exit_code == 1
    result = runner.invoke(app, ["log", "repair", str(project)])
    assert result.exit_code == 0, result.output
    assert "events.jsonl.fragment-" in result.output
    assert f"{len(FRAGMENT)} bytes" in result.output
    assert "e-000004" in result.output
    assert runner.invoke(app, ["validate", str(project)]).exit_code == 0


def test_nothing_to_repair(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(PROJECT, project)
    before = (project / "events.jsonl").read_bytes()
    result = runner.invoke(app, ["log", "repair", str(project)])
    assert result.exit_code == 0
    assert "nothing to repair" in result.output
    assert (project / "events.jsonl").read_bytes() == before


def test_project_without_a_log_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["log", "repair", str(tmp_path)])
    assert result.exit_code == 1
    assert "events.jsonl" in result.output
    assert "Traceback" not in result.output


def test_directory_defaults_to_the_current_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = _damaged(tmp_path)
    monkeypatch.chdir(project)
    assert runner.invoke(app, ["log", "repair"]).exit_code == 0


def test_log_command_is_listed_in_the_help() -> None:
    assert "log" in runner.invoke(app, ["--help"]).output


def test_interrupted_repair_is_reported_as_completed(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(PROJECT, project)
    (project / "events.jsonl.fragment-20261116T100000.000Z").write_bytes(FRAGMENT)
    result = runner.invoke(app, ["log", "repair", str(project)])
    assert result.exit_code == 0, result.output
    assert "interrupted repair" in result.output
    assert "events.jsonl.fragment-20261116T100000.000Z" in result.output
    assert runner.invoke(app, ["validate", str(project)]).exit_code == 0


def test_repair_is_refused_while_another_command_holds_the_lock(tmp_path: Path) -> None:
    project = _damaged(tmp_path)
    before = (project / "events.jsonl").read_bytes()
    with project_lock(project, "synthetic holder"):
        result = runner.invoke(app, ["log", "repair", str(project)])
    assert result.exit_code == 1
    assert f"process {os.getpid()}" in result.output
    assert (project / "events.jsonl").read_bytes() == before


def test_repair_records_setting_changes_after_the_repair(tmp_path: Path) -> None:
    project = _damaged(tmp_path)
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count("total_usd: 20") == 1
    config.write_text(text.replace("total_usd: 20", "total_usd: 30"), encoding="utf-8")
    result = runner.invoke(app, ["log", "repair", str(project)])
    assert result.exit_code == 0, result.output
    events = list(EventLog(project / "events.jsonl"))
    assert [e.type for e in events[-2:]] == [EventType.LOG_REPAIRED, EventType.SETTING_CHANGED]
    assert events[-1].data == {"key": "budget.total_usd", "old_value": 20.0, "new_value": 30.0}
    assert runner.invoke(app, ["validate", str(project)]).exit_code == 0
