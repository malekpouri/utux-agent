"""M0-12: `utux cost`.

The project's log is the synthetic fixture of `tests/fixtures/cost`; the
expected values are computed by hand in `tests/unit/test_cost_accounting.py`.
"""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cost" / "events.jsonl"
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _project(tmp_path: Path, *, log: Path | None = FIXTURE) -> Path:
    project = tmp_path / "p"
    result = runner.invoke(
        app, ["init", str(project), "--budget-usd", "0.25", "--data-policy", "external_allowed"]
    )
    assert result.exit_code == 0, result.output
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count("  per_stage_usd: {}\n") == 1
    config.write_text(
        text.replace("  per_stage_usd: {}\n", "  per_stage_usd:\n    methodology: 0.2\n"),
        encoding="utf-8",
    )
    if log is not None:
        shutil.copyfile(log, project / "events.jsonl")
    return project


def test_cost_prints_totals_per_stage_and_per_actor(tmp_path: Path) -> None:
    result = runner.invoke(app, ["cost", str(_project(tmp_path))])
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert "Known cost: 0.2156021 USD of a budget of 0.25 USD (0.0343979 USD left)" in lines
    assert "Calls: 8 made, 1 refused" in lines
    assert "Local, not billed: 1 call" in lines
    assert "Unknown cost: 2 calls to an external provider reported no cost" in lines
    assert (
        "The budget cannot be fully enforced while calls of unknown cost exist: "
        "only the known cost is compared with the budget."
    ) in lines
    assert "Per stage:" in lines
    assert "  ideation: 0.0156 USD, 3 calls" in lines
    assert "  literature: 0 USD, 1 call, 1 of unknown cost" in lines
    assert (
        "  methodology: 0.2 USD of a budget of 0.2 USD, exhausted, 3 calls, "
        "1 local, not billed, 1 of unknown cost"
    ) in lines
    assert "  writing: 0 USD, 0 calls, 1 refused" in lines
    assert "  no stage: 0.0000021 USD, 1 call" in lines
    assert "Per actor:" in lines
    assert "  agent:ideator: 0.0156 USD, 3 calls" in lines
    assert "  agent:planner: 0.2 USD, 2 calls, 1 local, not billed" in lines
    assert "  system:utux: 0.0000021 USD, 1 call" in lines
    assert lines.index("Per stage:") < lines.index("Per actor:")


def test_cost_as_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["cost", "--json", str(_project(tmp_path))])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["fully_enforceable"] is False
    assert report["total"]["known_cost_usd"] == 0.2156021
    assert report["total"]["unknown_cost_calls"] == 2
    assert report["total"]["local_unbilled_calls"] == 1
    assert [row["stage"] for row in report["per_stage"]][-1] is None
    assert report["per_stage"][2]["exhausted"] is True
    assert len(report["per_actor"]) == 6


def test_cost_without_unknown_cost_says_nothing_about_enforcement(tmp_path: Path) -> None:
    project = _project(tmp_path, log=None)
    result = runner.invoke(app, ["cost", str(project)])
    assert result.exit_code == 0, result.output
    assert "Known cost: 0 USD of a budget of 0.25 USD (0.25 USD left)" in result.output
    assert "Calls: 0 made, 0 refused" in result.output
    assert "cannot be fully enforced" not in result.output
    assert "Unknown cost" not in result.output
    assert (
        json.loads(runner.invoke(app, ["cost", "--json", str(project)]).output)["fully_enforceable"]
        is True
    )


def test_cost_defaults_to_the_current_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["cost"])
    assert result.exit_code == 0, result.output
    assert "0.2156021 USD" in result.output


def test_cost_of_a_directory_without_a_project_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["cost", str(tmp_path)])
    assert result.exit_code == 1
    assert "utux.yaml" in result.output
    assert "Traceback" not in result.output


def test_cost_command_is_listed_in_the_help() -> None:
    assert "cost" in runner.invoke(app, ["--help"]).output
