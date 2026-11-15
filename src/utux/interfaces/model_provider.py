"""The `ModelProvider` interface: one call to a language model.

The contract is recorded in ADR-0007. A provider receives a request whose
model the core's router has already chosen; it knows nothing about agent
roles or tiers. The request and response types hold no provider-specific
field.
"""

from enum import StrEnum
from typing import Annotated, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class _Value(BaseModel):
    """Base of the request and response types: no unknown fields, immutable."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MessageRole(StrEnum):
    """Who a message in a conversation comes from."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class FinishReason(StrEnum):
    """Why the model stopped writing."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"


class Message(_Value):
    """One message of a conversation."""

    role: MessageRole
    content: Annotated[str, Field(strict=True)]


class ModelRequest(_Value):
    """What a provider is asked to do.

    Attributes:
        model: The model id, already chosen by the core's router.
        messages: The conversation, oldest message first. Not empty.
        timeout_seconds: How long the caller waits for the answer.
        temperature: Sampling temperature, or None for the provider's default.
        max_output_tokens: Limit on the answer's length, or None for the
            provider's default.
    """

    model: Annotated[str, Field(min_length=1, strict=True)]
    messages: Annotated[tuple[Message, ...], Field(min_length=1)]
    timeout_seconds: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    temperature: Annotated[float, Field(ge=0, allow_inf_nan=False)] | None = None
    max_output_tokens: Annotated[int, Field(gt=0, strict=True)] | None = None


class Usage(_Value):
    """Token counts of one call. Both are required."""

    tokens_in: Annotated[int, Field(ge=0, strict=True)]
    tokens_out: Annotated[int, Field(ge=0, strict=True)]


class ModelResponse(_Value):
    """What a provider returns.

    Attributes:
        model: The id of the model that answered.
        content: The text of the answer.
        finish_reason: Why the model stopped.
        usage: Token counts. Always present.
        cost_usd: Cost of the call in US dollars as reported by the provider,
            or None when the provider reported no cost. The field is required
            and a cost is never guessed. Zero is a reported cost.
    """

    model: Annotated[str, Field(min_length=1, strict=True)]
    content: Annotated[str, Field(strict=True)]
    finish_reason: FinishReason
    usage: Usage
    cost_usd: Annotated[float, Field(ge=0, allow_inf_nan=False, strict=True)] | None


@runtime_checkable
class ModelProvider(Protocol):
    """Access to language models through one provider.

    An implementation must pass the conformance suite in
    `tests/conformance/model_provider_suite.py`.
    """

    @property
    def name(self) -> str:
        """Short name of the provider, used in logs. Read-only."""
        ...

    @property
    def is_external(self) -> bool:
        """Whether content sent to this provider leaves the machine. Read-only.

        The value is set per instance from the provider's configuration; it
        is not a class constant. An implementation must return True unless it
        can show that content stays on the machine.
        """
        ...

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Send one request and return the model's answer.

        The call blocks until it returns or raises. It is safe to call from
        several threads at once. It takes the request and no other parameter.

        Raises:
            ModelAuthenticationError: Credentials are missing or were refused.
            ModelRateLimitError: The provider refused the call because of a
                rate limit.
            ModelTimeoutError: No answer arrived within
                `request.timeout_seconds`.
            ModelInvalidResponseError: The answer cannot be turned into a
                valid `ModelResponse`, for example because usage is missing.
            ModelUnavailableError: The provider could not be reached or its
                server failed. Retryable; the trigger for provider fallback.
            ModelRequestRejectedError: The provider refused the request
                itself, for example an unknown model or an input longer than
                the model's context. Not retryable.
        """
        ...
