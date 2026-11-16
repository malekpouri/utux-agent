"""M0-07: `utux init <dir>`."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app
from utux.events.log import EventLog
from utux.schemas.event import EventType
from utux.schemas.project_config import DataPolicy, load_project_config

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    return config


def test_init_creates_a_valid_project(tmp_path: Path) -> None:
    target = tmp_path / "my-project"
    result = runner.invoke(
        app, ["init", str(target), "--budget-usd", "20", "--data-policy", "local_only"]
    )
    assert result.exit_code == 0, result.output
    assert str(target) in result.output
    config = load_project_config(target / "utux.yaml")
    assert config.budget.total_usd == 20.0
    assert config.data_policy is DataPolicy.LOCAL_ONLY
    (event,) = list(EventLog(target / "events.jsonl"))
    assert event.type is EventType.PROJECT_CREATED
    assert (target / ".git").is_dir()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--data-policy", "local_only"],  # no budget
        ["--budget-usd", "20"],  # no data policy
        [],
    ],
)
def test_budget_and_data_policy_are_required_and_have_no_default(
    tmp_path: Path, arguments: list[str]
) -> None:
    target = tmp_path / "p"
    result = runner.invoke(app, ["init", str(target), *arguments])
    assert result.exit_code == 2
    assert not target.exists()


def test_unknown_data_policy_is_refused(tmp_path: Path) -> None:
    target = tmp_path / "p"
    result = runner.invoke(
        app, ["init", str(target), "--budget-usd", "20", "--data-policy", "anything"]
    )
    assert result.exit_code == 2
    assert not target.exists()


def test_invalid_budget_fails_with_the_field_and_reason(tmp_path: Path) -> None:
    target = tmp_path / "p"
    result = runner.invoke(
        app, ["init", str(target), "--budget-usd", "0", "--data-policy", "local_only"]
    )
    assert result.exit_code == 1
    assert "budget.total_usd" in result.output
    assert "Traceback" not in result.output
    assert not target.exists()


def test_non_empty_directory_fails_with_a_clear_message_and_changes_nothing(
    tmp_path: Path,
) -> None:
    target = tmp_path / "busy"
    target.mkdir()
    (target / "notes.txt").write_text("keep me\n", encoding="utf-8")
    result = runner.invoke(
        app, ["init", str(target), "--budget-usd", "20", "--data-policy", "local_only"]
    )
    assert result.exit_code == 1
    assert "not empty" in result.output
    assert "Traceback" not in result.output
    assert [path.name for path in target.iterdir()] == ["notes.txt"]
    assert (target / "notes.txt").read_text(encoding="utf-8") == "keep me\n"


def test_missing_git_identity_prints_the_two_commands_and_creates_nothing(
    tmp_path: Path, git_identity: Path
) -> None:
    git_identity.write_text("", encoding="utf-8")
    target = tmp_path / "p"
    result = runner.invoke(
        app, ["init", str(target), "--budget-usd", "20", "--data-policy", "local_only"]
    )
    assert result.exit_code == 1
    assert 'git config --global user.name "Your Name"' in result.output
    assert 'git config --global user.email "you@example.org"' in result.output
    assert not target.exists()


def test_init_is_listed_in_the_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "init" in result.output
