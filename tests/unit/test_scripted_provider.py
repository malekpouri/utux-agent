"""M0-09: behaviour of the scripted fake provider beyond the conformance suite."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from utux.errors import (
    ModelInvalidResponseError,
    ModelRateLimitError,
    ModelTimeoutError,
    ScriptExhaustedError,
    UtuxError,
)
from utux.interfaces.model_provider import (
    FinishReason,
    Message,
    MessageRole,
    ModelRequest,
)
from utux.providers.scripted import (
    ScriptedFailure,
    ScriptedModelProvider,
    ScriptedRawReply,
    ScriptedReply,
)


def _request(model: str = "synthetic/model", timeout_seconds: float = 5.0) -> ModelRequest:
    return ModelRequest(
        model=model,
        messages=(Message(role=MessageRole.USER, content="Synthetic user text."),),
        timeout_seconds=timeout_seconds,
    )


def test_replies_come_in_script_order_with_their_usage_and_cost() -> None:
    provider = ScriptedModelProvider(
        [
            ScriptedReply(content="first", tokens_in=10, tokens_out=2, cost_usd=0.01),
            ScriptedReply(
                content="second",
                tokens_in=20,
                tokens_out=4,
                cost_usd=None,
                finish_reason=FinishReason.LENGTH,
            ),
        ]
    )
    first = provider.complete(_request())
    second = provider.complete(_request())
    assert (first.content, first.usage.tokens_in, first.usage.tokens_out) == ("first", 10, 2)
    assert first.cost_usd == 0.01
    assert first.finish_reason is FinishReason.STOP
    assert (second.content, second.usage.tokens_in, second.usage.tokens_out) == ("second", 20, 4)
    assert second.cost_usd is None
    assert second.finish_reason is FinishReason.LENGTH


def test_reply_names_the_requested_model_unless_the_script_names_another() -> None:
    provider = ScriptedModelProvider(
        [ScriptedReply(), ScriptedReply(model="synthetic/other-model")]
    )
    assert provider.complete(_request(model="synthetic/asked")).model == "synthetic/asked"
    assert provider.complete(_request(model="synthetic/asked")).model == "synthetic/other-model"


def test_requests_are_recorded_in_order() -> None:
    provider = ScriptedModelProvider([ScriptedReply(), ScriptedReply()])
    first, second = _request(model="synthetic/a"), _request(model="synthetic/b")
    provider.complete(first)
    provider.complete(second)
    assert provider.requests == (first, second)


def test_scripted_failure_is_raised_and_the_request_is_still_recorded() -> None:
    error = ModelRateLimitError("synthetic failure", retry_after_seconds=1.0)
    provider = ScriptedModelProvider([ScriptedFailure(error), ScriptedReply(content="after")])
    with pytest.raises(ModelRateLimitError) as caught:
        provider.complete(_request())
    assert caught.value is error
    assert len(provider.requests) == 1
    # The script moves on after a failure.
    assert provider.complete(_request()).content == "after"


def test_raw_reply_that_is_valid_becomes_a_response() -> None:
    provider = ScriptedModelProvider(
        [
            ScriptedRawReply(
                {
                    "model": "synthetic/model",
                    "content": "raw",
                    "finish_reason": "stop",
                    "usage": {"tokens_in": 1, "tokens_out": 2},
                    "cost_usd": None,
                }
            )
        ]
    )
    response = provider.complete(_request())
    assert response.content == "raw"
    assert response.usage.tokens_out == 2
    assert response.cost_usd is None


def test_raw_reply_that_is_invalid_names_the_fields_but_not_the_content() -> None:
    provider = ScriptedModelProvider(
        [
            ScriptedRawReply(
                {
                    "model": "synthetic/model",
                    "content": "secret synthetic content",
                    "finish_reason": "stop",
                    "usage": {"tokens_in": -5, "tokens_out": 2},
                }
            )
        ]
    )
    with pytest.raises(ModelInvalidResponseError) as caught:
        provider.complete(_request())
    message = str(caught.value)
    assert "usage.tokens_in" in message
    assert "cost_usd" in message
    assert "secret synthetic content" not in message


def test_running_past_the_script_is_a_typed_error() -> None:
    provider = ScriptedModelProvider([ScriptedReply()])
    provider.complete(_request())
    with pytest.raises(ScriptExhaustedError):
        provider.complete(_request())
    assert issubclass(ScriptExhaustedError, UtuxError)


def test_delay_within_the_timeout_waits_for_the_delay() -> None:
    slept: list[float] = []
    provider = ScriptedModelProvider([ScriptedReply(delay_seconds=2.0)], sleep=slept.append)
    provider.complete(_request(timeout_seconds=5.0))
    assert slept == [2.0]


def test_delay_beyond_the_timeout_waits_for_the_timeout_then_raises() -> None:
    slept: list[float] = []
    provider = ScriptedModelProvider(
        [ScriptedReply(delay_seconds=60.0), ScriptedReply(content="next")], sleep=slept.append
    )
    with pytest.raises(ModelTimeoutError):
        provider.complete(_request(timeout_seconds=5.0))
    assert slept == [5.0]
    # The timed-out step is used up.
    assert provider.complete(_request()).content == "next"


def test_a_slow_failure_can_time_out_too() -> None:
    provider = ScriptedModelProvider(
        [ScriptedFailure(ModelRateLimitError("synthetic"), delay_seconds=60.0)],
        sleep=lambda seconds: None,
    )
    with pytest.raises(ModelTimeoutError):
        provider.complete(_request(timeout_seconds=1.0))


def test_name_and_locality_come_from_the_constructor() -> None:
    default = ScriptedModelProvider([])
    assert default.name == "scripted"
    # External unless stated otherwise.
    assert default.is_external is True
    local = ScriptedModelProvider([], name="scripted-local", is_external=False)
    assert local.name == "scripted-local"
    assert local.is_external is False


def test_each_scripted_reply_is_used_exactly_once_across_threads() -> None:
    threads, per_thread = 8, 25
    total = threads * per_thread
    provider = ScriptedModelProvider([ScriptedReply(content=str(n)) for n in range(total)])
    start = threading.Barrier(threads)

    def worker() -> list[str]:
        start.wait(timeout=10)
        return [provider.complete(_request()).content for _ in range(per_thread)]

    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [pool.submit(worker) for _ in range(threads)]
        contents = [content for future in futures for content in future.result(timeout=30)]
    assert sorted(contents, key=int) == [str(n) for n in range(total)]
    assert len(provider.requests) == total
