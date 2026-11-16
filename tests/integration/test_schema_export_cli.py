"""M0-06b: `utux schema export <dir>`."""

import json
from pathlib import Path

from typer.testing import CliRunner

from utux.cli import app
from utux.schemas.export import CONTRACTS

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


def test_schema_export_writes_one_file_per_contract(tmp_path: Path) -> None:
    target = tmp_path / "schemas"
    result = runner.invoke(app, ["schema", "export", str(target)])
    assert result.exit_code == 0, result.output
    names = sorted(path.name for path in target.iterdir())
    assert names == sorted(f"{name}.schema.json" for name in CONTRACTS)
    for path in target.iterdir():
        assert json.loads(path.read_text(encoding="utf-8"))["type"] == "object"
    # The command says what it wrote.
    for name in names:
        assert name in result.output


def test_schema_export_fails_with_a_message_when_the_target_is_a_file(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    target.write_text("x", encoding="utf-8")
    result = runner.invoke(app, ["schema", "export", str(target)])
    assert result.exit_code == 1
    assert "file.txt" in result.output
    assert "Traceback" not in result.output


def test_schema_export_needs_a_directory_argument() -> None:
    result = runner.invoke(app, ["schema", "export"])
    assert result.exit_code == 2


def test_schema_command_is_listed_in_the_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "schema" in result.output
