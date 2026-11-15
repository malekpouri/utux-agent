"""M0-09: the `ModelProvider` Protocol, its request and response types and its errors."""

import inspect
from typing import Any

import pytest
from pydantic import ValidationError

from utux import errors
from utux.interfaces.model_provider import (
    FinishReason,
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    Usage,
)

MESSAGES = (Message(role=MessageRole.USER, content="Synthetic user text."),)


def _request(**changes: Any) -> ModelRequest:
    fields: dict[str, Any] = {
        "model": "synthetic/model",
        "messages": MESSAGES,
        "timeout_seconds": 30.0,
    }
    return ModelRequest(**{**fields, **changes})


def _response(**changes: Any) -> ModelResponse:
    fields: dict[str, Any] = {
        "model": "synthetic/model",
        "content": "Synthetic reply.",
        "finish_reason": FinishReason.STOP,
        "usage": Usage(tokens_in=12, tokens_out=3),
        "cost_usd": 0.0004,
    }
    return ModelResponse(**{**fields, **changes})


def _error_types(error: ValidationError) -> list[tuple[str, str]]:
    return [(".".join(str(part) for part in item["loc"]), item["type"]) for item in error.errors()]


# The Protocol


def test_protocol_has_exactly_the_agreed_members() -> None:
    members = {name for name, _ in inspect.getmembers(ModelProvider) if not name.startswith("_")}
    assert members == {"name", "is_external", "complete"}


def test_complete_takes_one_request_and_no_provider_specific_parameter() -> None:
    parameters = inspect.signature(ModelProvider.complete).parameters
    assert list(parameters) == ["self", "request"]


def test_name_and_is_external_are_read_only_properties() -> None:
    for attribute in ("name", "is_external"):
        declared = inspect.getattr_static(ModelProvider, attribute)
        assert isinstance(declared, property)
        assert declared.fset is None


def test_an_object_without_the_members_is_not_a_provider() -> None:
    class OnlyComplete:
        def complete(self, request: ModelRequest) -> ModelResponse:
            raise NotImplementedError

    assert not isinstance(OnlyComplete(), ModelProvider)


# Request


def test_request_has_only_provider_neutral_fields() -> None:
    assert set(ModelRequest.model_fields) == {
        "model",
        "messages",
        "timeout_seconds",
        "temperature",
        "max_output_tokens",
    }


def test_request_defaults() -> None:
    request = _request()
    assert request.temperature is None
    assert request.max_output_tokens is None


def test_request_rejects_an_unknown_parameter() -> None:
    with pytest.raises(ValidationError) as caught:
        _request(openrouter_route="fallback")
    assert _error_types(caught.value) == [("openrouter_route", "extra_forbidden")]


def test_request_needs_model_messages_and_timeout() -> None:
    with pytest.raises(ValidationError) as caught:
        ModelRequest()  # type: ignore[call-arg]
    assert _error_types(caught.value) == [
        ("model", "missing"),
        ("messages", "missing"),
        ("timeout_seconds", "missing"),
    ]


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"model": ""}, "model"),
        ({"messages": ()}, "messages"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"timeout_seconds": -1.0}, "timeout_seconds"),
        ({"timeout_seconds": float("inf")}, "timeout_seconds"),
        ({"temperature": -0.1}, "temperature"),
        ({"max_output_tokens": 0}, "max_output_tokens"),
    ],
)
def test_request_rejects_values_out_of_range(changes: dict[str, Any], field: str) -> None:
    with pytest.raises(ValidationError) as caught:
        _request(**changes)
    assert [name for name, _ in _error_types(caught.value)] == [field]


def test_message_role_is_a_closed_set() -> None:
    assert {role.value for role in MessageRole} == {"system", "user", "assistant"}
    with pytest.raises(ValidationError):
        Message(role="planner", content="x")  # type: ignore[arg-type]


def test_request_and_response_are_immutable() -> None:
    with pytest.raises(ValidationError, match="frozen"):
        _request().model = "other"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="frozen"):
        _response().cost_usd = 1.0  # type: ignore[misc]


# Response


def test_response_carries_model_content_finish_reason_usage_and_cost() -> None:
    response = _response()
    assert response.model == "synthetic/model"
    assert response.content == "Synthetic reply."
    assert response.finish_reason is FinishReason.STOP
    assert response.usage.tokens_in == 12
    assert response.usage.tokens_out == 3
    assert response.cost_usd == 0.0004


def test_cost_may_be_null_but_the_field_is_required() -> None:
    assert _response(cost_usd=None).cost_usd is None
    assert ModelResponse.model_fields["cost_usd"].is_required()
    with pytest.raises(ValidationError) as caught:
        ModelResponse(
            model="synthetic/model",
            content="x",
            finish_reason=FinishReason.STOP,
            usage=Usage(tokens_in=1, tokens_out=1),
        )  # type: ignore[call-arg]
    assert _error_types(caught.value) == [("cost_usd", "missing")]


def test_cost_of_zero_is_a_reported_cost_not_an_unknown_one() -> None:
    assert _response(cost_usd=0.0).cost_usd == 0.0


@pytest.mark.parametrize("cost", [-0.01, float("nan"), float("inf"), "0.01", True])
def test_cost_must_be_a_real_number_of_zero_or_more(cost: object) -> None:
    with pytest.raises(ValidationError) as caught:
        _response(cost_usd=cost)
    assert {name for name, _ in _error_types(caught.value)} == {"cost_usd"}


def test_usage_is_required() -> None:
    assert ModelResponse.model_fields["usage"].is_required()
    assert Usage.model_fields["tokens_in"].is_required()
    assert Usage.model_fields["tokens_out"].is_required()


@pytest.mark.parametrize("count", [-1, 1.5, "3", True, None])
def test_token_counts_are_whole_numbers_of_zero_or_more(count: object) -> None:
    with pytest.raises(ValidationError):
        Usage(tokens_in=count, tokens_out=0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        Usage(tokens_in=0, tokens_out=count)  # type: ignore[arg-type]


def test_finish_reason_is_a_closed_set() -> None:
    assert {reason.value for reason in FinishReason} == {"stop", "length", "content_filter"}
    with pytest.raises(ValidationError):
        _response(finish_reason="exploded")


def test_response_needs_a_model_id() -> None:
    with pytest.raises(ValidationError):
        _response(model="")


# Errors


@pytest.mark.parametrize(
    "name",
    [
        "ModelAuthenticationError",
        "ModelRateLimitError",
        "ModelTimeoutError",
        "ModelInvalidResponseError",
    ],
)
def test_each_typed_error_is_a_model_provider_error(name: str) -> None:
    error_type = getattr(errors, name)
    assert issubclass(error_type, errors.ModelProviderError)
    assert issubclass(errors.ModelProviderError, errors.UtuxError)


def test_typed_errors_are_distinct() -> None:
    kinds = [
        errors.ModelAuthenticationError,
        errors.ModelRateLimitError,
        errors.ModelTimeoutError,
        errors.ModelInvalidResponseError,
    ]
    for kind in kinds:
        for other in kinds:
            assert kind is other or not issubclass(kind, other)


def test_rate_limit_error_may_say_when_to_retry() -> None:
    assert errors.ModelRateLimitError("slow down").retry_after_seconds is None
    error = errors.ModelRateLimitError("slow down", retry_after_seconds=2.5)
    assert error.retry_after_seconds == 2.5
    assert str(error) == "slow down"
