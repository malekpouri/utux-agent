"""M0-08b: `utux log repair`."""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app

PROJECT = Path(__file__).resolve().parents[1] / "fixtures" / "projects" / "valid_full"

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def _damaged(tmp_path: Path) -> Path:
    project = tmp_path / "p"
    shutil.copytree(PROJECT, project)
    with (project / "events.jsonl").open("ab") as stream:
        stream.write(b'{"schema_version": 1, "event_id": "e-0000')
    return project


def test_repair_then_validate(tmp_path: Path) -> None:
    project = _damaged(tmp_path)
    assert runner.invoke(app, ["validate", str(project)]).exit_code == 1
    result = runner.invoke(app, ["log", "repair", str(project)])
    assert result.exit_code == 0, result.output
    assert "events.jsonl.fragment-" in result.output
    assert "40 bytes" in result.output
    assert "e-000003" in result.output
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
