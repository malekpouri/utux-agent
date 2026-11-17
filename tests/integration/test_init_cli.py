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
    for name in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("EMAIL", raising=False)
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


BASE = ["--budget-usd", "20", "--data-policy", "local_only"]


def test_profile_and_domain_pack_are_optional_with_the_schema_defaults(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "p"), *BASE])
    assert result.exit_code == 0, result.output
    config = load_project_config(tmp_path / "p" / "utux.yaml")
    assert (config.profile, config.domain_pack) == ("default", "generic")


def test_profile_and_domain_pack_options(tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["init", str(tmp_path / "p"), *BASE, "--profile", "local", "--domain-pack", "ml"]
    )
    assert result.exit_code == 0, result.output
    config = load_project_config(tmp_path / "p" / "utux.yaml")
    assert (config.profile, config.domain_pack) == ("local", "ml")


def test_invalid_profile_fails_with_the_field(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "p"), *BASE, "--profile", "Not A Name"])
    assert result.exit_code == 1
    assert "profile" in result.output
    assert not (tmp_path / "p").exists()


def test_not_empty_message_says_what_to_do_after_an_interrupted_init(tmp_path: Path) -> None:
    target = tmp_path / "busy"
    target.mkdir()
    (target / "utux.yaml").write_text("left over\n", encoding="utf-8")
    result = runner.invoke(app, ["init", str(target), *BASE])
    assert result.exit_code == 1
    assert "interrupted utux init" in " ".join(result.output.split())
