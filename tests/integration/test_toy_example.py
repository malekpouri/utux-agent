"""M1-16, the agent part: `examples/toy-classification/`.

The commands of the example's README are followed as written, with scripted
services in place of the real model and sandbox, so that its commands, its
gate ids and the exit statuses it states stay true. The maintainer's run
with a real model is the human part of M1-16.
"""

import importlib
import re
import shlex
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner
from workflow_scripts import CODE, METHOD, services

from utux.cli import app
from utux.workspace.validation import validate_project

REPO = Path(__file__).resolve().parents[2]
EXAMPLE = REPO / "examples" / "toy-classification"
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})
# The module, not the Typer object that utux.cli re-exports under the same name.
cli = importlib.import_module("utux.cli.app")


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _section(text: str, title: str) -> str:
    match = re.search(rf"^## {title}\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    assert match is not None, title
    return match.group(1)


def _blocks(section: str, language: str) -> list[str]:
    return re.findall(rf"^ *```{language}\n(.*?)^ *```", section, re.MULTILINE | re.DOTALL)


def test_the_inputs_are_the_idea_and_the_data_description_of_the_quick_start() -> None:
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    written = dict(re.findall(r"^Write `([^`]+)`:\n\n```markdown\n(.*?)^```", readme, re.M | re.S))
    assert sorted(path.name for path in (EXAMPLE / "inputs").iterdir()) == [
        "data.md",
        "question.md",
    ]
    for name in ("question.md", "data.md"):
        assert (EXAMPLE / "inputs" / name).read_text("utf-8") == written[
            f"my-project/inputs/{name}"
        ]


def test_the_readme_leaves_the_budget_and_the_models_to_the_maintainer() -> None:
    text = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    assert "BUDGET_USD=CHOOSE_A_BUDGET" in text
    assert "standard: REPLACE_WITH_THE_MODEL_ID_FOR_THE_STANDARD_TIER" in text
    # The maintainer checks the recorded image instead of building one.
    assert "docker image inspect $(cat packs/generic/image/digest.txt)" in text
    assert "Skip `utux image build`" in text
    commands = _section(text, "The commands")
    assert "utux image build" not in commands


def test_the_commands_of_the_readme_work_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    text = (EXAMPLE / "README.md").read_text(encoding="utf-8")
    section = _section(text, "The commands")
    before, after = _blocks(section, "yaml")
    lines = [line for block in _blocks(section, "bash") for line in block.splitlines() if line]
    assert lines[0] == "BUDGET_USD=CHOOSE_A_BUDGET"

    monkeypatch.setattr(cli, "services_for_run", lambda project: services(project, (METHOD, CODE)))
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    project = tmp_path / "utux-toy"

    steps: list[str] = []
    for line in lines[1:]:
        stated = re.search(r"# exit status (\d)", line)
        words = shlex.split(line.replace('"$BUDGET_USD"', "2"), comments=True)
        if words[0] == "cp":
            assert words[1:] == ["examples/toy-classification/inputs/*.md", "../utux-toy/inputs/"]
            for source in (EXAMPLE / "inputs").glob("*.md"):
                shutil.copy(source, project / "inputs" / source.name)
            # Step 2 of the README edits utux.yaml after the inputs are in place.
            config = project / "utux.yaml"
            body = config.read_text(encoding="utf-8")
            assert body.count(before) == 1
            config.write_text(
                body.replace(
                    before,
                    after.replace(
                        "REPLACE_WITH_THE_MODEL_ID_FOR_THE_STANDARD_TIER", "scripted/standard-model"
                    ),
                ),
                encoding="utf-8",
            )
            continue
        assert words[:3] == ["uv", "run", "utux"], line
        result = runner.invoke(app, words[3:])
        expected = int(stated.group(1)) if stated else 0
        assert result.exit_code == expected, (line, result.output)
        steps.append(words[3])
        if words[3] == "run" and expected == 3:
            approval = re.search(r"a-\d{6}", line)
            assert approval is not None
            assert approval.group(0) in result.output
    assert steps == [
        "init",
        "validate",
        "run",
        "approve",
        "run",
        "status",
        "approve",
        "run",
        "validate",
        "cost",
    ]
    assert validate_project(project).problems == ()
    assert (project / "results.md").is_file()
