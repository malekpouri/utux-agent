"""M0-11: `utux model ping`.

The provider is the scripted fake, put in place of the profile's provider;
no test reaches the network.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from utux.cli import app
from utux.errors import ModelAuthenticationError
from utux.events.log import EventLog
from utux.interfaces.model_provider import ModelProvider
from utux.providers import profiles
from utux.providers.scripted import ScriptedFailure, ScriptedModelProvider, ScriptedReply
from utux.schemas.event import EventStatus, EventType
from utux.workspace.validation import validate_project

runner = CliRunner(env={"NO_COLOR": "1", "TERM": "dumb"})

# utux init writes every default, so the empty tier mapping is replaced.
EMPTY_TIERS = "  tiers: {}\n"
TIERS = "  tiers:\n    light: synthetic/light-model\n"


@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "synthetic.gitconfig"
    config.write_text(
        "[user]\n\tname = Synthetic Person\n\temail = person@example.org\n", encoding="utf-8"
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


class Use:
    """Puts a scripted provider in place of the profile's provider."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.monkeypatch = monkeypatch
        self.profiles: list[str] = []

    def __call__(self, provider: ModelProvider) -> None:
        def factory(profile: str) -> ModelProvider:
            self.profiles.append(profile)
            return provider

        self.monkeypatch.setattr(profiles, "provider_for_profile", factory)


@pytest.fixture
def use(monkeypatch: pytest.MonkeyPatch) -> Use:
    return Use(monkeypatch)


def _project(tmp_path: Path, policy: str = "external_allowed", tiers: str = TIERS) -> Path:
    project = tmp_path / "p"
    result = runner.invoke(
        app, ["init", str(project), "--budget-usd", "5", "--data-policy", policy]
    )
    assert result.exit_code == 0, result.output
    config = project / "utux.yaml"
    text = config.read_text(encoding="utf-8")
    assert text.count(EMPTY_TIERS) == 1
    config.write_text(text.replace(EMPTY_TIERS, tiers), encoding="utf-8")
    return project


def test_ping_prints_tokens_and_cost_and_logs_the_call(tmp_path: Path, use: Use) -> None:
    provider = ScriptedModelProvider(
        [ScriptedReply(content="pong", tokens_in=14, tokens_out=1, cost_usd=0.0000021)],
        name="synthetic-provider",
    )
    use(provider)
    project = _project(tmp_path)
    result = runner.invoke(app, ["model", "ping", "--tier", "light", str(project)])
    assert result.exit_code == 0, result.output
    assert "synthetic/light-model" in result.output
    assert "14 tokens in, 1 token out" in result.output
    assert "cost 0.0000021 USD" in result.output
    assert use.profiles == ["default"]
    (request,) = provider.requests
    assert request.model == "synthetic/light-model"
    events = list(EventLog(project / "events.jsonl"))
    assert [event.type for event in events] == [EventType.PROJECT_CREATED, EventType.MODEL_CALL]
    call = events[-1]
    assert call.status is EventStatus.OK
    assert (call.tokens_in, call.tokens_out, call.cost_usd) == (14, 1, 0.0000021)
    assert call.actor == "system:utux"
    assert call.prompt_version == "ping@1"
    assert call.data == {"provider": "synthetic-provider", "is_external": True}
    assert validate_project(project).problems == ()


def test_ping_says_when_the_cost_is_unknown(tmp_path: Path, use: Use) -> None:
    use(ScriptedModelProvider([ScriptedReply(cost_usd=None)]))
    result = runner.invoke(app, ["model", "ping", str(_project(tmp_path))])
    assert result.exit_code == 0, result.output
    assert "cost unknown: the provider reported none" in result.output


def test_ping_defaults_to_the_light_tier_and_the_current_directory(
    tmp_path: Path, use: Use, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = ScriptedModelProvider([ScriptedReply()])
    use(provider)
    monkeypatch.chdir(_project(tmp_path))
    result = runner.invoke(app, ["model", "ping"])
    assert result.exit_code == 0, result.output
    assert provider.requests[0].model == "synthetic/light-model"


def test_failed_ping_is_logged_and_exits_1(tmp_path: Path, use: Use) -> None:
    use(ScriptedModelProvider([ScriptedFailure(ModelAuthenticationError("synthetic: no key"))]))
    project = _project(tmp_path)
    result = runner.invoke(app, ["model", "ping", str(project)])
    assert result.exit_code == 1
    assert "synthetic: no key" in result.output
    assert "Traceback" not in result.output
    call = list(EventLog(project / "events.jsonl"))[-1]
    assert (call.status, call.status_reason) == (EventStatus.ERROR, "model_authentication")


def test_refused_ping_is_logged_and_makes_no_call(tmp_path: Path, use: Use) -> None:
    provider = ScriptedModelProvider([ScriptedReply()], is_external=True)
    use(provider)
    project = _project(tmp_path, policy="local_only")
    result = runner.invoke(app, ["model", "ping", str(project)])
    assert result.exit_code == 1
    assert "local_only" in result.output
    assert provider.requests == ()
    call = list(EventLog(project / "events.jsonl"))[-1]
    assert (call.status, call.status_reason) == (EventStatus.REFUSED, "data_policy_local_only")


def test_tier_without_a_model_is_an_error_and_nothing_is_logged(tmp_path: Path, use: Use) -> None:
    provider = ScriptedModelProvider([ScriptedReply()])
    use(provider)
    project = _project(tmp_path, tiers=EMPTY_TIERS)
    before = (project / "events.jsonl").read_bytes()
    result = runner.invoke(app, ["model", "ping", "--tier", "strong", str(project)])
    assert result.exit_code == 1
    assert "no model is configured for the tier strong" in result.output
    assert provider.requests == ()
    assert (project / "events.jsonl").read_bytes() == before


def test_unknown_tier_is_a_usage_error(tmp_path: Path) -> None:
    result = runner.invoke(app, ["model", "ping", "--tier", "huge", str(tmp_path)])
    assert result.exit_code == 2


def test_directory_without_a_project_fails(tmp_path: Path) -> None:
    result = runner.invoke(app, ["model", "ping", str(tmp_path)])
    assert result.exit_code == 1
    assert "utux.yaml" in result.output


def test_model_command_is_listed_in_the_help() -> None:
    assert "model" in runner.invoke(app, ["--help"]).output
