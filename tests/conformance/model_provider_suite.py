"""Conformance suite for `ModelProvider` (ADR-0007).

Every implementation must pass this suite. To run it against a provider,
subclass `ModelProviderConformance` in a test module, name the subclass
`Test...`, and implement the four `make_...` methods. The suite never calls a
real model: an implementation supplies providers that answer from a script
or from recorded responses.
"""

import inspect
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import pytest

from utux.errors import (
    ModelAuthenticationError,
    ModelInvalidResponseError,
    ModelProviderError,
    ModelRateLimitError,
    ModelTimeoutError,
    UtuxError,
)
from utux.interfaces.model_provider import (
    FinishReason,
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
    Usage,
)


class Failure(Enum):
    """The upstream failures a provider must turn into typed errors."""

    AUTHENTICATION = "authentication"
    RATE_LIMIT = "rate_limit"
    INVALID_RESPONSE = "invalid_response"


EXPECTED_ERROR: dict[Failure, type[ModelProviderError]] = {
    Failure.AUTHENTICATION: ModelAuthenticationError,
    Failure.RATE_LIMIT: ModelRateLimitError,
    Failure.INVALID_RESPONSE: ModelInvalidResponseError,
}

THREADS = 8
CALLS_PER_THREAD = 5


def make_request(timeout_seconds: float = 5.0) -> ModelRequest:
    """Return a small request with synthetic content."""
    return ModelRequest(
        model="synthetic/model",
        messages=(
            Message(role=MessageRole.SYSTEM, content="Synthetic system text."),
            Message(role=MessageRole.USER, content="Synthetic user text."),
        ),
        timeout_seconds=timeout_seconds,
    )


def assert_well_formed(response: object) -> None:
    """Check everything the contract promises about a response."""
    assert isinstance(response, ModelResponse)
    assert isinstance(response.model, str)
    assert response.model
    assert isinstance(response.content, str)
    assert isinstance(response.finish_reason, FinishReason)
    # Usage is always present, as whole numbers.
    assert isinstance(response.usage, Usage)
    for count in (response.usage.tokens_in, response.usage.tokens_out):
        assert isinstance(count, int)
        assert not isinstance(count, bool)
        assert count >= 0
    # cost_usd is always a field; it is a number of zero or more, or None.
    assert "cost_usd" in type(response).model_fields
    assert response.cost_usd is None or (
        isinstance(response.cost_usd, float) and response.cost_usd >= 0
    )


class ModelProviderConformance(ABC):
    """Tests that every `ModelProvider` implementation must pass."""

    @abstractmethod
    def make_replying(self, replies: int) -> ModelProvider:
        """Return a provider that can answer `replies` calls and reports a cost."""

    @abstractmethod
    def make_without_cost(self) -> ModelProvider:
        """Return a provider whose upstream reports no cost for its answer."""

    @abstractmethod
    def make_failing(self, failure: Failure) -> ModelProvider:
        """Return a provider whose upstream fails in the given way."""

    @abstractmethod
    def make_slow(self, delay_seconds: float) -> ModelProvider:
        """Return a provider whose upstream answers after `delay_seconds`."""

    # Shape of the interface

    def test_is_a_model_provider(self) -> None:
        assert isinstance(self.make_replying(1), ModelProvider)

    def test_complete_takes_the_request_and_nothing_else(self) -> None:
        """An implementation adds no parameter of its own to the call."""
        parameters = inspect.signature(self.make_replying(1).complete).parameters
        assert list(parameters) == ["request"]

    def test_name_is_non_empty_text(self) -> None:
        name = self.make_replying(1).name
        assert isinstance(name, str)
        assert name.strip()

    def test_is_external_is_a_boolean_set_per_instance(self) -> None:
        provider = self.make_replying(1)
        assert isinstance(provider.is_external, bool)
        # Not a class constant: locality comes from the configuration.
        assert not isinstance(inspect.getattr_static(type(provider), "is_external", None), bool)

    @pytest.mark.parametrize("attribute", ["name", "is_external"])
    def test_name_and_is_external_are_read_only(self, attribute: str) -> None:
        provider = self.make_replying(1)
        before = getattr(provider, attribute)
        with pytest.raises(AttributeError):
            setattr(provider, attribute, before)

    # Responses

    def test_response_has_usage_and_cost(self) -> None:
        response = self.make_replying(1).complete(make_request())
        assert_well_formed(response)
        assert response.cost_usd is not None

    def test_cost_is_null_when_the_provider_reports_none(self) -> None:
        response = self.make_without_cost().complete(make_request())
        assert_well_formed(response)
        assert response.cost_usd is None

    # Errors

    @pytest.mark.parametrize("failure", list(Failure), ids=lambda f: f.value)
    def test_failure_maps_to_its_typed_error(self, failure: Failure) -> None:
        provider = self.make_failing(failure)
        with pytest.raises(ModelProviderError) as caught:
            provider.complete(make_request())
        assert type(caught.value) is EXPECTED_ERROR[failure]
        assert isinstance(caught.value, UtuxError)

    # Timeout

    def test_timeout_is_honoured(self) -> None:
        provider = self.make_slow(delay_seconds=30.0)
        started = time.monotonic()
        with pytest.raises(ModelTimeoutError):
            provider.complete(make_request(timeout_seconds=0.05))
        # The call gave up near the timeout, long before the upstream answered.
        assert time.monotonic() - started < 5.0

    def test_answer_within_the_timeout_is_returned(self) -> None:
        provider = self.make_slow(delay_seconds=0.01)
        assert_well_formed(provider.complete(make_request(timeout_seconds=5.0)))

    # Threads

    def test_complete_is_safe_to_call_from_several_threads(self) -> None:
        provider = self.make_replying(THREADS * CALLS_PER_THREAD)
        start = threading.Barrier(THREADS)

        def worker() -> list[ModelResponse]:
            start.wait(timeout=10)
            return [provider.complete(make_request()) for _ in range(CALLS_PER_THREAD)]

        with ThreadPoolExecutor(max_workers=THREADS) as pool:
            futures = [pool.submit(worker) for _ in range(THREADS)]
            responses = [response for future in futures for response in future.result(timeout=30)]
        assert len(responses) == THREADS * CALLS_PER_THREAD
        for response in responses:
            assert_well_formed(response)
