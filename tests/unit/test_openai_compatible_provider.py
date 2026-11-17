"""M0-10: the OpenAI-compatible chat-completions client and the OpenRouter provider.

Every response here is synthetic and hand-written. No test reaches the network.
"""

import contextlib
import json
import logging
import traceback
from typing import Any

import pytest
from provider_fakes import (
    OK_WITH_COST,
    OK_WITHOUT_COST,
    SYNTHETIC_KEY,
    FakeTime,
    ScriptedTransport,
    fixture_json,
    response,
)

from utux.errors import (
    ModelAuthenticationError,
    ModelInvalidResponseError,
    ModelProviderConfigError,
    ModelProviderError,
    ModelRateLimitError,
    ModelRequestRejectedError,
    ModelTimeoutError,
    ModelUnavailableError,
    UtuxError,
)
from utux.interfaces.model_provider import (
    FinishReason,
    Message,
    MessageRole,
    ModelRequest,
)
from utux.providers.openai_compatible import (
    OPENROUTER_BASE_URL,
    HttpResponse,
    OpenAICompatibleProvider,
    openrouter,
)


@pytest.fixture(autouse=True)
def openrouter_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", SYNTHETIC_KEY)


def _request(**changes: Any) -> ModelRequest:
    fields: dict[str, Any] = {
        "model": "synthetic/model",
        "messages": (
            Message(role=MessageRole.SYSTEM, content="Synthetic system text."),
            Message(role=MessageRole.USER, content="Synthetic user text."),
        ),
        "timeout_seconds": 30.0,
    }
    return ModelRequest(**{**fields, **changes})


def _provider(
    script: Any, *, time: FakeTime | None = None, **options: Any
) -> tuple[OpenAICompatibleProvider, ScriptedTransport]:
    transport = ScriptedTransport(script)
    fake = time or FakeTime()
    provider = openrouter(transport=transport, sleep=fake.sleep, clock=fake.clock, **options)
    return provider, transport


def _body(transport: ScriptedTransport, call: int = 0) -> dict[str, Any]:
    document = json.loads(transport.calls[call][0].body)
    assert isinstance(document, dict)
    return document


# The request


def test_request_goes_to_chat_completions_with_the_key_as_bearer_token() -> None:
    provider, transport = _provider(OK_WITH_COST)
    provider.complete(_request())
    ((request, timeout),) = transport.calls
    assert request.url == "https://openrouter.ai/api/v1/chat/completions"
    assert request.headers["Authorization"] == f"Bearer {SYNTHETIC_KEY}"
    assert request.headers["Content-Type"] == "application/json"
    assert timeout == 30.0


def test_request_body_holds_the_model_and_the_messages() -> None:
    provider, transport = _provider(OK_WITH_COST)
    provider.complete(_request())
    assert _body(transport) == {
        "model": "synthetic/model",
        "messages": [
            {"role": "system", "content": "Synthetic system text."},
            {"role": "user", "content": "Synthetic user text."},
        ],
        # OpenRouter reports the cost of a call only when asked to.
        "usage": {"include": True},
    }


def test_temperature_and_output_limit_are_sent_only_when_set() -> None:
    provider, transport = _provider(OK_WITH_COST)
    provider.complete(_request(temperature=0.0, max_output_tokens=64))
    body = _body(transport)
    assert body["temperature"] == 0.0
    assert body["max_tokens"] == 64


def test_generic_client_sends_no_provider_specific_field() -> None:
    transport = ScriptedTransport(OK_WITHOUT_COST)
    provider = OpenAICompatibleProvider(
        name="local", base_url="http://localhost:11434/v1", api_key_env=None, transport=transport
    )
    provider.complete(_request())
    assert set(_body(transport)) == {"model", "messages"}
    assert "Authorization" not in transport.calls[0][0].headers
    assert transport.calls[0][0].url == "http://localhost:11434/v1/chat/completions"


def test_extra_body_may_not_replace_a_standard_field() -> None:
    with pytest.raises(ModelProviderConfigError, match="model"):
        OpenAICompatibleProvider(
            name="x",
            base_url="https://example.org/v1",
            api_key_env=None,
            extra_body={"model": "other"},
        )


# The key


@pytest.mark.parametrize("value", [None, "", "   ", "two\nlines", "tab\there"])
def test_missing_or_unusable_key_fails_before_any_network_call(
    monkeypatch: pytest.MonkeyPatch, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv("OPENROUTER_API_KEY")
    else:
        monkeypatch.setenv("OPENROUTER_API_KEY", value)
    provider, transport = _provider(OK_WITH_COST)
    with pytest.raises(ModelAuthenticationError, match="OPENROUTER_API_KEY"):
        provider.complete(_request())
    assert transport.calls == []


def test_key_is_read_at_each_call_and_never_stored(monkeypatch: pytest.MonkeyPatch) -> None:
    provider, transport = _provider(OK_WITH_COST)
    assert SYNTHETIC_KEY not in repr(vars(provider))
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-second-key-00000000")
    provider.complete(_request())
    assert transport.calls[0][0].headers["Authorization"] == "Bearer synthetic-second-key-00000000"


# The response


def test_response_with_cost() -> None:
    provider, _ = _provider(OK_WITH_COST)
    answer = provider.complete(_request())
    assert answer.model == "synthetic/model"
    assert answer.content == "Synthetic reply."
    assert answer.finish_reason is FinishReason.STOP
    assert (answer.usage.tokens_in, answer.usage.tokens_out) == (12, 3)
    assert answer.cost_usd == 0.0000036


def test_cost_is_null_when_the_response_reports_none() -> None:
    provider, _ = _provider(OK_WITHOUT_COST)
    answer = provider.complete(_request())
    assert answer.cost_usd is None
    assert answer.model == "synthetic-local-model"


def _completion(**usage: Any) -> dict[str, object]:
    document = fixture_json("openrouter_completion_with_cost.json")
    document["usage"] = {**document["usage"], **usage}  # type: ignore[dict-item]
    return document


@pytest.mark.parametrize("cost", [None, 0, 0.0, 1, 2.5e-7])
def test_cost_is_taken_as_reported(cost: float | None) -> None:
    provider, _ = _provider(response(200, _completion(cost=cost)))
    answer = provider.complete(_request())
    assert answer.cost_usd == (None if cost is None else float(cost))


@pytest.mark.parametrize("cost", [-0.01, "0.01", True, [1], {"usd": 1}])
def test_reported_cost_that_is_not_a_number_of_zero_or_more_is_invalid(cost: object) -> None:
    provider, _ = _provider(response(200, _completion(cost=cost)))
    with pytest.raises(ModelInvalidResponseError, match="cost"):
        provider.complete(_request())


def test_nan_cost_is_invalid() -> None:
    provider, _ = _provider(response(200, b'{"model": "m", "choices": [], "usage": {"cost": NaN}}'))
    with pytest.raises(ModelInvalidResponseError):
        provider.complete(_request())


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("stop", FinishReason.STOP),
        ("length", FinishReason.LENGTH),
        ("content_filter", FinishReason.CONTENT_FILTER),
    ],
)
def test_finish_reasons(reason: str, expected: FinishReason) -> None:
    document = fixture_json("openrouter_completion_with_cost.json")
    document["choices"][0]["finish_reason"] = reason  # type: ignore[index]
    provider, _ = _provider(response(200, document))
    assert provider.complete(_request()).finish_reason is expected


@pytest.mark.parametrize("reason", ["tool_calls", "function_call", "error", None, "other"])
def test_other_finish_reasons_are_not_supported(reason: str | None) -> None:
    document = fixture_json("openrouter_completion_with_cost.json")
    document["choices"][0]["finish_reason"] = reason  # type: ignore[index]
    provider, _ = _provider(response(200, document))
    with pytest.raises(ModelInvalidResponseError, match="finish"):
        provider.complete(_request())


def test_filtered_answer_without_content_is_empty_text() -> None:
    document = fixture_json("openrouter_completion_with_cost.json")
    document["choices"][0]["finish_reason"] = "content_filter"  # type: ignore[index]
    document["choices"][0]["message"]["content"] = None  # type: ignore[index]
    provider, _ = _provider(response(200, document))
    assert provider.complete(_request()).content == ""


def _broken(change: str) -> bytes:
    document: Any = fixture_json("openrouter_completion_with_cost.json")
    if change == "no usage":
        del document["usage"]
    elif change == "no prompt tokens":
        del document["usage"]["prompt_tokens"]
    elif change == "negative tokens":
        document["usage"]["completion_tokens"] = -1
    elif change == "tokens as text":
        document["usage"]["prompt_tokens"] = "12"
    elif change == "no choices":
        document["choices"] = []
    elif change == "no message":
        del document["choices"][0]["message"]
    elif change == "content is a list":
        document["choices"][0]["message"]["content"] = [{"type": "text"}]
    elif change == "content null on stop":
        document["choices"][0]["message"]["content"] = None
    elif change == "no model":
        del document["model"]
    elif change == "not an object":
        return b"[1, 2]"
    elif change == "not json":
        return b"<html>synthetic proxy page</html>"
    return json.dumps(document).encode()


@pytest.mark.parametrize(
    "change",
    [
        "no usage",
        "no prompt tokens",
        "negative tokens",
        "tokens as text",
        "no choices",
        "no message",
        "content is a list",
        "content null on stop",
        "no model",
        "not an object",
        "not json",
    ],
)
def test_malformed_success_response_is_invalid_and_not_retried(change: str) -> None:
    provider, transport = _provider(response(200, _broken(change)))
    with pytest.raises(ModelInvalidResponseError):
        provider.complete(_request())
    assert len(transport.calls) == 1


# Errors


@pytest.mark.parametrize(
    ("status", "body", "error"),
    [
        (401, "error_unauthorized.json", ModelAuthenticationError),
        (403, "error_unauthorized.json", ModelAuthenticationError),
        (402, "error_insufficient_credits.json", ModelRequestRejectedError),
        (400, "error_bad_request.json", ModelRequestRejectedError),
        (404, "error_bad_request.json", ModelRequestRejectedError),
        (413, "error_bad_request.json", ModelRequestRejectedError),
        (422, "error_bad_request.json", ModelRequestRejectedError),
        (408, "error_unavailable.json", ModelTimeoutError),
        (429, "error_rate_limited.json", ModelRateLimitError),
        (500, "error_unavailable.json", ModelUnavailableError),
        (502, "error_unavailable.json", ModelUnavailableError),
        (503, "error_unavailable.json", ModelUnavailableError),
        (504, "error_unavailable.json", ModelUnavailableError),
        (301, "error_unavailable.json", ModelInvalidResponseError),
    ],
)
def test_http_status_maps_to_its_typed_error(
    status: int, body: str, error: type[ModelProviderError]
) -> None:
    provider, _ = _provider(response(status, body))
    with pytest.raises(ModelProviderError) as caught:
        provider.complete(_request())
    assert type(caught.value) is error
    assert f"HTTP {status}" in str(caught.value) or error is ModelTimeoutError


def test_error_message_carries_the_upstream_reason() -> None:
    provider, _ = _provider(response(400, "error_bad_request.json"))
    with pytest.raises(ModelRequestRejectedError) as caught:
        provider.complete(_request())
    assert str(caught.value) == (
        "openrouter: HTTP 400: Synthetic: synthetic/unknown is not a valid model ID"
    )


def test_long_upstream_reason_is_cut() -> None:
    provider, _ = _provider(response(400, {"error": {"message": "x" * 5000}}))
    with pytest.raises(ModelRequestRejectedError) as caught:
        provider.complete(_request())
    assert len(str(caught.value)) < 400


def test_timeout_and_connection_failure() -> None:
    provider, _ = _provider(TimeoutError("synthetic"))
    with pytest.raises(ModelTimeoutError, match="30"):
        provider.complete(_request())
    provider, transport = _provider(ConnectionRefusedError(111, "synthetic: refused"))
    with pytest.raises(ModelUnavailableError, match=r"openrouter\.ai"):
        provider.complete(_request())
    assert len(transport.calls) == 3  # retried


def test_rate_limit_error_carries_retry_after() -> None:
    script = [response(429, "error_rate_limited.json", {"retry-after": "7"})] * 3
    time = FakeTime()
    provider, _ = _provider(script, time=time, max_attempts=1)
    with pytest.raises(ModelRateLimitError) as caught:
        provider.complete(_request())
    assert caught.value.retry_after_seconds == 7.0


# Retries


def test_transient_failure_is_retried_with_growing_waits() -> None:
    time = FakeTime()
    unavailable = response(503, "error_unavailable.json")
    provider, transport = _provider([unavailable, unavailable, OK_WITH_COST], time=time)
    assert provider.complete(_request()).content == "Synthetic reply."
    assert len(transport.calls) == 3
    assert time.slept == [0.5, 1.0]
    # Each attempt gets what is left of the request's timeout.
    assert [timeout for _, timeout in transport.calls] == [30.0, 29.5, 28.5]


def test_retries_are_bounded() -> None:
    time = FakeTime()
    provider, transport = _provider(response(503, "error_unavailable.json"), time=time)
    with pytest.raises(ModelUnavailableError):
        provider.complete(_request())
    assert len(transport.calls) == 3
    assert time.slept == [0.5, 1.0]


def test_rate_limit_waits_as_long_as_the_provider_asks() -> None:
    time = FakeTime()
    limited = response(429, "error_rate_limited.json", {"Retry-After": "2"})
    provider, _ = _provider([limited, OK_WITH_COST], time=time)
    provider.complete(_request())
    assert time.slept == [2.0]


def test_retry_after_that_is_not_a_number_of_seconds_is_ignored() -> None:
    time = FakeTime()
    limited = response(
        429, "error_rate_limited.json", {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}
    )
    provider, _ = _provider([limited, OK_WITH_COST], time=time)
    provider.complete(_request())
    assert time.slept == [0.5]


def test_no_retry_when_the_wait_would_pass_the_timeout() -> None:
    time = FakeTime()
    unavailable = response(503, "error_unavailable.json")
    provider, transport = _provider([unavailable] * 3, time=time)
    with pytest.raises(ModelUnavailableError):
        provider.complete(_request(timeout_seconds=1.0))
    # Waiting 0.5 leaves 0.5; waiting 1.0 more would pass the timeout.
    assert len(transport.calls) == 2
    assert time.slept == [0.5]


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (400, "error_bad_request.json"),
        (401, "error_unauthorized.json"),
        (402, "error_insufficient_credits.json"),
        (408, "error_unavailable.json"),
    ],
)
def test_errors_that_will_not_change_are_not_retried(status: int, body: str) -> None:
    provider, transport = _provider(response(status, body))
    with pytest.raises(ModelProviderError):
        provider.complete(_request())
    assert len(transport.calls) == 1


def test_timeout_is_not_retried() -> None:
    provider, transport = _provider(TimeoutError("synthetic"))
    with pytest.raises(ModelTimeoutError):
        provider.complete(_request())
    assert len(transport.calls) == 1


# Locality and configuration


@pytest.mark.parametrize(
    ("base_url", "external"),
    [
        ("https://openrouter.ai/api/v1", True),
        ("https://api.example.org/v1", True),
        ("https://10.0.0.5:8443/v1", True),  # another machine on the network
        ("https://192.168.1.20/v1", True),
        ("http://localhost:11434/v1", False),
        ("http://LOCALHOST:11434/v1", False),
        ("http://127.0.0.1:8000/v1", False),
        ("http://127.20.0.9/v1", False),
        ("http://[::1]:8000/v1", False),
    ],
)
def test_is_external_follows_the_configured_host(base_url: str, external: bool) -> None:
    provider = OpenAICompatibleProvider(name="x", base_url=base_url, api_key_env=None)
    assert provider.is_external is external


@pytest.mark.parametrize(
    "base_url",
    [
        "http://openrouter.ai/api/v1",  # a key would travel in clear text
        "http://10.0.0.5/v1",
        "ftp://example.org/v1",
        "https:///v1",
        "https://example.org/v1?key=x",
        "https://user:secret@example.org/v1",
        "example.org/v1",
    ],
)
def test_unusable_base_url_is_a_configuration_error(base_url: str) -> None:
    with pytest.raises(ModelProviderConfigError) as caught:
        OpenAICompatibleProvider(name="x", base_url=base_url, api_key_env=None)
    assert issubclass(ModelProviderConfigError, UtuxError)
    assert "secret" not in str(caught.value)


def test_openrouter_preset() -> None:
    provider = openrouter()
    assert provider.name == "openrouter"
    assert provider.is_external is True
    assert OPENROUTER_BASE_URL == "https://openrouter.ai/api/v1"


def test_name_must_not_be_empty() -> None:
    with pytest.raises(ModelProviderConfigError):
        OpenAICompatibleProvider(name=" ", base_url="https://example.org/v1", api_key_env=None)


# The key never leaks


def _all_text(error: BaseException) -> str:
    return "".join(traceback.format_exception(error)) + repr(error) + str(error)


@pytest.mark.parametrize(
    "item",
    [
        response(401, {"error": {"message": f"Synthetic: key {SYNTHETIC_KEY} is not valid"}}),
        response(400, f"Synthetic: bad request for {SYNTHETIC_KEY}"),
        response(503, {"error": {"message": f"Bearer {SYNTHETIC_KEY}"}}),
        response(200, f"not json {SYNTHETIC_KEY}"),
        TimeoutError(f"synthetic timeout {SYNTHETIC_KEY}"),
        ConnectionResetError(104, f"synthetic reset {SYNTHETIC_KEY}"),
    ],
)
def test_key_never_appears_in_error_text_even_when_echoed_upstream(item: object) -> None:
    provider, _ = _provider(item)
    with pytest.raises(ModelProviderError) as caught:
        provider.complete(_request())
    assert SYNTHETIC_KEY not in _all_text(caught.value)


def test_nothing_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    for script in (OK_WITH_COST, response(401, "error_unauthorized.json"), TimeoutError("x")):
        provider, _ = _provider(script)
        with contextlib.suppress(ModelProviderError):
            provider.complete(_request())
    assert caplog.records == []
    assert SYNTHETIC_KEY not in caplog.text


def test_unexpected_http_response_type_is_not_assumed() -> None:
    assert HttpResponse(status=200, headers={}, body=b"").status == 200
