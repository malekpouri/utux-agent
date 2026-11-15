"""M0-01: the `utux` command prints help and its version."""

from importlib.metadata import version

from typer.testing import CliRunner

import utux
from utux.cli import app

# Rich colours the help text when it detects a CI system, which puts escape
# codes inside option names. Plain output keeps the assertions about text.
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def test_help_exits_zero_and_prints_usage() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Usage" in result.output
    assert "--version" in result.output


def test_version_prints_package_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.output.strip() == f"utux {version('utux')}"


def test_dunder_version_matches_installed_metadata() -> None:
    assert utux.__version__ == version("utux")


def test_no_arguments_prints_help() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == 0
    assert "Usage" in result.output
