"""M0-08: `utux validate`."""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "projects"

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def test_fresh_project_validates_with_exit_code_0(tmp_path: Path) -> None:
    target = tmp_path / "fresh"
    created = runner.invoke(
        app, ["init", str(target), "--budget-usd", "20", "--data-policy", "local_only"]
    )
    assert created.exit_code == 0, created.output
    result = runner.invoke(app, ["validate", str(target)])
    assert result.exit_code == 0, result.output
    assert "valid" in result.output


def test_valid_fixture_project_validates(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(FIXTURES / "valid_full")])
    assert result.exit_code == 0, result.output


def _corrupted(tmp_path: Path) -> Path:
    project = tmp_path / "p"
    shutil.copytree(FIXTURES / "valid_full", project)
    (project / "events.jsonl").unlink()
    with (project / "utux.yaml").open("a", encoding="utf-8") as stream:
        stream.write("colour: blue\n")
    return project


def test_problems_give_exit_code_1_and_one_line_each(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(_corrupted(tmp_path))])
    assert result.exit_code == 1
    assert "events.jsonl: <document>: the file is missing" in result.output
    assert "utux.yaml: colour: unknown key" in result.output
    assert "2 problems" in result.output
    assert "Traceback" not in result.output


def test_json_option_prints_only_the_report(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "--json", str(_corrupted(tmp_path))])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["valid"] is False
    assert {(p["file"], p["code"]) for p in data["problems"]} == {
        ("events.jsonl", "missing_file"),
        ("utux.yaml", "unknown_key"),
    }


def test_newer_schema_version_is_refused_with_a_message_that_says_so(tmp_path: Path) -> None:
    project = tmp_path / "p"
    shutil.copytree(FIXTURES / "valid_full", project)
    config = project / "utux.yaml"
    config.write_text(
        config.read_text(encoding="utf-8").replace("schema_version: 1", "schema_version: 2"),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["validate", str(project)])
    assert result.exit_code == 1
    assert "newer schema version" in result.output
    assert "written by a newer version of utux" in result.output


def test_directory_defaults_to_the_current_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "p"
    shutil.copytree(FIXTURES / "valid_full", project)
    monkeypatch.chdir(project)
    result = runner.invoke(app, ["validate"])
    assert result.exit_code == 0, result.output


def test_validate_is_listed_in_the_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert "validate" in result.output


def _with_missing_untracked_file(tmp_path: Path) -> Path:
    project = tmp_path / "p"
    shutil.copytree(FIXTURES / "valid_full", project)
    sidecar = json.loads(
        (project / ".utux" / "meta" / "idea-v002.json").read_text(encoding="utf-8")
    )
    sidecar.update(artifact_id="data-v001", path="inputs/data.csv")
    (project / ".utux" / "meta" / "data-v001.json").write_text(
        json.dumps(sidecar), encoding="utf-8"
    )
    return project


def test_warnings_are_printed_and_give_exit_code_0(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(_with_missing_untracked_file(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "warning: .utux/meta/data-v001.json: path: inputs/data.csv" in result.output
    assert "1 warning" in result.output


def test_json_report_lists_warnings_apart_from_problems(tmp_path: Path) -> None:
    project = _with_missing_untracked_file(tmp_path)
    result = runner.invoke(app, ["validate", "--json", str(project)])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["valid"] is True
    assert data["problems"] == []
    assert [(w["file"], w["field"], w["code"]) for w in data["warnings"]] == [
        (".utux/meta/data-v001.json", "path", "missing_untracked_file"),
    ]
