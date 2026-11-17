"""M0-11: the README quick start, followed step by step.

The commands and the edit of `utux.yaml` are read from `README.md` itself,
so the test fails when the README and the tool drift apart. The provider is
the scripted fake, put in place of the profile's provider; no test reaches
the network.
"""

import re
import shlex
from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app
from utux.events.log import EventLog
from utux.providers import profiles
from utux.providers.scripted import ScriptedModelProvider, ScriptedReply
from utux.schemas.event import EventStatus, EventType
from utux.workspace.validation import validate_project

README = Path(__file__).resolve().parents[2] / "README.md"
runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _quick_start() -> str:
    text = README.read_text(encoding="utf-8")
    match = re.search(r"^## Quick start\n(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert match is not None, "README.md has no Quick start section"
    return match.group(1)


def _blocks(section: str, language: str) -> list[str]:
    return re.findall(rf"^```{language}\n(.*?)^```", section, re.MULTILINE | re.DOTALL)


def _utux_commands(block: str) -> list[list[str]]:
    commands = []
    for line in block.splitlines():
        words = shlex.split(line, comments=True)
        if words[:3] == ["uv", "run", "utux"]:
            commands.append(words[3:])
    return commands


def test_readme_quick_start_works_as_written(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    section = _quick_start()
    bash = _blocks(section, "bash")
    yaml = _blocks(section, "yaml")
    assert len(bash) == 2, "expected one block before and one after the edit of utux.yaml"
    assert len(yaml) == 2, "expected the line to replace and its replacement"
    before, after = yaml
    assert "tiers: {}" in before
    assert "models:" not in after, "the replacement must not add a second models key"

    provider = ScriptedModelProvider([ScriptedReply(content="pong", cost_usd=0.0000021)])
    monkeypatch.setattr(profiles, "provider_for_profile", lambda profile: provider)
    monkeypatch.chdir(tmp_path)

    setup = _utux_commands(bash[0])
    assert [command[0] for command in setup] == ["init", "validate"]
    for command in setup:
        result = runner.invoke(app, command)
        assert result.exit_code == 0, (command, result.output)
    project = tmp_path / setup[0][1]

    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count(before) == 1, "utux init does not write the line the README edits"
    config.write_text(text.replace(before, after), encoding="utf-8")
    assert validate_project(project).problems == ()

    (ping,) = _utux_commands(bash[1])
    assert ping[:2] == ["model", "ping"]
    result = runner.invoke(app, ping)
    assert result.exit_code == 0, result.output
    assert "cost 0.0000021 USD" in result.output
    call = list(EventLog(project / "events.jsonl"))[-1]
    assert (call.type, call.status) == (EventType.MODEL_CALL, EventStatus.OK)


def test_appending_a_second_models_key_is_rejected_as_the_readme_warns(tmp_path: Path) -> None:
    section = _quick_start()
    assert "duplicate" in section
    project = tmp_path / "p"
    result = runner.invoke(
        app, ["init", str(project), "--budget-usd", "5", "--data-policy", "external_allowed"]
    )
    assert result.exit_code == 0, result.output
    config = project / "utux.yaml"
    with config.open("a", encoding="utf-8") as stream:
        stream.write("models:\n  tiers:\n    light: synthetic/light-model\n")
    problems = validate_project(project).problems
    assert any(problem.code == "duplicate_key" for problem in problems), problems
