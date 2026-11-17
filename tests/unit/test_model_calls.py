"""M0-11: logged model calls.

Every provider here is the scripted fake; no test reaches the network.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from utux.errors import (
    ModelAuthenticationError,
    ModelCallRefusedError,
    ModelInvalidResponseError,
    ModelProviderError,
    ModelRateLimitError,
    ModelRequestRejectedError,
    ModelTimeoutError,
    ModelUnavailableError,
    UtuxError,
)
from utux.events.log import EventLog
from utux.interfaces.model_provider import (
    FinishReason,
    Message,
    MessageRole,
    ModelRequest,
    ModelResponse,
)
from utux.providers.scripted import ScriptedFailure, ScriptedModelProvider, ScriptedReply
from utux.schemas.common import Stage
from utux.schemas.event import Event, EventStatus, EventType
from utux.schemas.project_config import DataPolicy
from utux.workspace.model_calls import (
    LoggedModelCaller,
    input_hash,
    output_hash,
)

SECRET_TEXT = "Synthetic confidential sentence that must never reach the log."
REPLY_TEXT = "Synthetic reply that must never reach the log."
FIXED = datetime(2026, 11, 17, 9, 30, 0, tzinfo=UTC)


def _request(**changes: Any) -> ModelRequest:
    fields: dict[str, Any] = {
        "model": "synthetic/model",
        "messages": (
            Message(role=MessageRole.SYSTEM, content="Synthetic system text."),
            Message(role=MessageRole.USER, content=SECRET_TEXT),
        ),
        "timeout_seconds": 30.0,
        "temperature": 0.0,
        "max_output_tokens": 16,
    }
    return ModelRequest(**{**fields, **changes})


class Ticks:
    """A monotonic clock that moves 0.25 s each time it is read."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        self.now += 0.25
        return self.now


def _caller(
    tmp_path: Path,
    provider: Any,
    policy: DataPolicy = DataPolicy.EXTERNAL_ALLOWED,
) -> tuple[LoggedModelCaller, EventLog]:
    log = EventLog(tmp_path / "events.jsonl", clock=lambda: FIXED)
    return LoggedModelCaller(log, provider, policy, clock=Ticks()), log


def _call(caller: LoggedModelCaller, request: ModelRequest | None = None) -> ModelResponse:
    return caller.call(
        request or _request(),
        actor="agent:planner",
        prompt_version="planner@3",
        stage=Stage.METHODOLOGY,
    )


def _events(log: EventLog) -> list[Event]:
    return list(log)


# Success


def test_successful_call_writes_exactly_one_model_call_event(tmp_path: Path) -> None:
    provider = ScriptedModelProvider(
        [ScriptedReply(content=REPLY_TEXT, tokens_in=120, tokens_out=8, cost_usd=0.00042)],
        name="synthetic-provider",
    )
    caller, log = _caller(tmp_path, provider)
    answer = _call(caller)
    assert answer.content == REPLY_TEXT
    (event,) = _events(log)
    assert event.type is EventType.MODEL_CALL
    assert event.status is EventStatus.OK
    assert event.status_reason is None
    assert event.actor == "agent:planner"
    assert event.stage is Stage.METHODOLOGY
    assert event.model == "synthetic/model"
    assert event.prompt_version == "planner@3"
    assert (event.tokens_in, event.tokens_out) == (120, 8)
    assert event.cost_usd == 0.00042
    # Two readings of the clock, 0.25 s apart.
    assert event.duration_ms == 250
    assert event.input_hash == input_hash(_request())
    assert event.output_hash == output_hash(answer)
    assert event.data == {"provider": "synthetic-provider", "is_external": True}


def test_model_is_the_one_that_answered(tmp_path: Path) -> None:
    provider = ScriptedModelProvider([ScriptedReply(model="synthetic/routed-model")])
    caller, log = _caller(tmp_path, provider)
    _call(caller)
    assert _events(log)[0].model == "synthetic/routed-model"


def test_unknown_cost_is_logged_as_null_and_nothing_else_is_written(tmp_path: Path) -> None:
    provider = ScriptedModelProvider([ScriptedReply(cost_usd=None)])
    caller, log = _caller(tmp_path, provider)
    _call(caller)
    (event,) = _events(log)
    assert event.cost_usd is None
    assert event.status is EventStatus.OK


def test_cost_of_zero_is_kept_as_zero(tmp_path: Path) -> None:
    caller, log = _caller(tmp_path, ScriptedModelProvider([ScriptedReply(cost_usd=0.0)]))
    _call(caller)
    assert _events(log)[0].cost_usd == 0.0


def test_each_call_writes_its_own_event(tmp_path: Path) -> None:
    provider = ScriptedModelProvider([ScriptedReply(), ScriptedReply(), ScriptedReply()])
    caller, log = _caller(tmp_path, provider)
    for _ in range(3):
        _call(caller)
    assert [event.event_id for event in _events(log)] == ["e-000001", "e-000002", "e-000003"]


def test_local_provider_is_marked_local(tmp_path: Path) -> None:
    provider = ScriptedModelProvider([ScriptedReply()], name="ollama", is_external=False)
    caller, log = _caller(tmp_path, provider, DataPolicy.LOCAL_ONLY)
    _call(caller)
    (event,) = _events(log)
    assert event.status is EventStatus.OK
    assert event.data == {"provider": "ollama", "is_external": False}


# Failure


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (ModelTimeoutError("synthetic"), "model_timeout"),
        (ModelRateLimitError("synthetic", retry_after_seconds=3.0), "model_rate_limit"),
        (ModelUnavailableError("synthetic"), "model_unavailable"),
        (ModelAuthenticationError("synthetic"), "model_authentication"),
        (ModelRequestRejectedError("synthetic"), "model_request_rejected"),
        (ModelInvalidResponseError("synthetic"), "model_invalid_response"),
    ],
)
def test_failed_call_writes_one_event_with_its_error_type_and_raises(
    tmp_path: Path, error: ModelProviderError, reason: str
) -> None:
    caller, log = _caller(tmp_path, ScriptedModelProvider([ScriptedFailure(error)]))
    with pytest.raises(ModelProviderError) as caught:
        _call(caller)
    assert caught.value is error
    (event,) = _events(log)
    assert event.type is EventType.MODEL_CALL
    assert event.status is EventStatus.ERROR
    assert event.status_reason == reason
    assert event.model == "synthetic/model"
    assert event.input_hash == input_hash(_request())
    assert event.output_hash is None
    assert (event.tokens_in, event.tokens_out, event.cost_usd) == (None, None, None)
    assert event.duration_ms == 250


def test_unexpected_exception_of_a_provider_is_logged_once_and_raised(tmp_path: Path) -> None:
    class Broken:
        name = "broken"
        is_external = True

        def complete(self, request: ModelRequest) -> ModelResponse:
            raise ValueError("synthetic bug")

    caller, log = _caller(tmp_path, Broken())
    with pytest.raises(ValueError, match="synthetic bug"):
        _call(caller)
    (event,) = _events(log)
    assert event.status is EventStatus.ERROR
    assert event.status_reason == "unexpected_error"


# Refusal under local_only


def test_external_provider_is_refused_under_local_only_without_a_call(tmp_path: Path) -> None:
    provider = ScriptedModelProvider([ScriptedReply()], name="openrouter", is_external=True)
    caller, log = _caller(tmp_path, provider, DataPolicy.LOCAL_ONLY)
    with pytest.raises(ModelCallRefusedError) as caught:
        _call(caller)
    assert "local_only" in str(caught.value)
    assert issubclass(ModelCallRefusedError, UtuxError)
    assert not issubclass(ModelCallRefusedError, ModelProviderError)
    # No network call: the provider was never asked.
    assert provider.requests == ()
    (event,) = _events(log)
    assert event.type is EventType.MODEL_CALL
    assert event.status is EventStatus.REFUSED
    assert event.status_reason == "data_policy_local_only"
    assert event.model == "synthetic/model"
    assert event.input_hash == input_hash(_request())
    assert (event.output_hash, event.tokens_in, event.tokens_out) == (None, None, None)
    assert (event.cost_usd, event.duration_ms) == (None, None)
    assert event.data == {"provider": "openrouter", "is_external": True}


# Nothing of the content is stored


def test_message_content_is_not_stored_only_its_hash(tmp_path: Path) -> None:
    provider = ScriptedModelProvider(
        [ScriptedReply(content=REPLY_TEXT), ScriptedFailure(ModelTimeoutError("synthetic"))]
    )
    caller, _ = _caller(tmp_path, provider)
    _call(caller)
    with pytest.raises(ModelTimeoutError):
        _call(caller)
    refusing, _ = _caller(tmp_path, provider, DataPolicy.LOCAL_ONLY)
    with pytest.raises(ModelCallRefusedError):
        _call(refusing)
    text = (tmp_path / "events.jsonl").read_text(encoding="utf-8")
    assert len(text.splitlines()) == 3
    for content in (SECRET_TEXT, REPLY_TEXT, "Synthetic system text."):
        assert content not in text
        assert content[:20] not in text


# Hashes


def test_input_hash_is_the_sha256_of_the_canonical_request() -> None:
    request = _request()
    canonical = json.dumps(
        {
            "model": "synthetic/model",
            "messages": [
                {"role": "system", "content": "Synthetic system text."},
                {"role": "user", "content": SECRET_TEXT},
            ],
            "temperature": 0.0,
            "max_output_tokens": 16,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    assert input_hash(request) == "sha256:" + hashlib.sha256(canonical).hexdigest()


def test_input_hash_ignores_the_timeout_and_follows_the_content() -> None:
    assert input_hash(_request(timeout_seconds=5.0)) == input_hash(_request(timeout_seconds=60.0))
    assert input_hash(_request(temperature=0.5)) != input_hash(_request())
    assert input_hash(_request(model="synthetic/other")) != input_hash(_request())


def test_output_hash_is_the_sha256_of_the_reply_text() -> None:
    answer = ModelResponse(
        model="synthetic/model",
        content=REPLY_TEXT,
        finish_reason=FinishReason.STOP,
        usage={"tokens_in": 1, "tokens_out": 1},  # type: ignore[arg-type]
        cost_usd=None,
    )
    expected = "sha256:" + hashlib.sha256(REPLY_TEXT.encode("utf-8")).hexdigest()
    assert output_hash(answer) == expected


# The log comes first


def test_response_is_not_returned_when_the_event_cannot_be_written(tmp_path: Path) -> None:
    """A result that is not logged is not used."""
    log_path = tmp_path / "events.jsonl"
    log_path.write_bytes(b'{"schema_version": 1, "ev')  # an interrupted write
    provider = ScriptedModelProvider([ScriptedReply(content=REPLY_TEXT)])
    caller = LoggedModelCaller(EventLog(log_path), provider, DataPolicy.EXTERNAL_ALLOWED)
    with pytest.raises(UtuxError) as caught:
        _call(caller)
    assert "utux log repair" in str(caught.value)
