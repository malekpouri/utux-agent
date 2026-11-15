"""A scripted `ModelProvider` for tests.

It answers from a list of steps written by the test and never contacts a
model. Tests of code that calls a provider use it in place of a real one.
"""

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from pydantic import ValidationError

from utux.errors import (
    ModelInvalidResponseError,
    ModelProviderError,
    ModelTimeoutError,
    ScriptExhaustedError,
)
from utux.interfaces.model_provider import FinishReason, ModelRequest, ModelResponse, Usage


@dataclass(frozen=True)
class ScriptedReply:
    """A successful answer.

    Attributes:
        content: The text of the answer.
        tokens_in: Reported input tokens.
        tokens_out: Reported output tokens.
        cost_usd: Reported cost, or None for an answer without a cost.
        finish_reason: Why the model stopped.
        model: The model id to report, or None to report the requested one.
        delay_seconds: How long the answer takes.
    """

    content: str = "synthetic reply"
    tokens_in: int = 1
    tokens_out: int = 1
    cost_usd: float | None = 0.0
    finish_reason: FinishReason = FinishReason.STOP
    model: str | None = None
    delay_seconds: float = 0.0


@dataclass(frozen=True)
class ScriptedRawReply:
    """An answer as an upstream service might send it, before validation.

    A payload that is not a valid `ModelResponse` makes the provider raise
    `ModelInvalidResponseError`, as a real provider must.
    """

    payload: Mapping[str, object]
    delay_seconds: float = 0.0


@dataclass(frozen=True)
class ScriptedFailure:
    """A failed call: the provider raises `error`."""

    error: ModelProviderError
    delay_seconds: float = 0.0


ScriptedStep = ScriptedReply | ScriptedRawReply | ScriptedFailure


class ScriptedModelProvider:
    """A `ModelProvider` that plays back a script, one step per call.

    A step whose delay is longer than the timeout of the request raises
    `ModelTimeoutError` after the timeout, and is used up.
    """

    def __init__(
        self,
        script: Sequence[ScriptedStep],
        *,
        name: str = "scripted",
        is_external: bool = True,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create the provider.

        Args:
            script: The steps, played back in order.
            name: The provider name to report.
            is_external: The locality to report. True by default, as for any
                provider that has not shown that content stays on the machine.
            sleep: Called to wait for a delay. Tests may pass a recorder
                instead of really waiting.
        """
        self._script = list(script)
        self._name = name
        self._is_external = is_external
        self._sleep = sleep
        self._requests: list[ModelRequest] = []
        # Guards the position in the script and the list of requests.
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        """Short name of the provider."""
        return self._name

    @property
    def is_external(self) -> bool:
        """The locality given to the constructor."""
        return self._is_external

    @property
    def requests(self) -> tuple[ModelRequest, ...]:
        """Every request received so far, in the order the calls arrived."""
        with self._lock:
            return tuple(self._requests)

    def complete(self, request: ModelRequest) -> ModelResponse:
        """Play back the next step of the script.

        Raises:
            ScriptExhaustedError: If the script has no step left.
            ModelProviderError: As the step says; see `ModelProvider.complete`.
        """
        with self._lock:
            position = len(self._requests)
            if position >= len(self._script):
                raise ScriptExhaustedError(
                    f"the script has {len(self._script)} steps and was called once more"
                )
            self._requests.append(request)
            step = self._script[position]

        if step.delay_seconds > request.timeout_seconds:
            self._sleep(request.timeout_seconds)
            raise ModelTimeoutError(f"no answer within {request.timeout_seconds} seconds")
        if step.delay_seconds > 0:
            self._sleep(step.delay_seconds)

        if isinstance(step, ScriptedFailure):
            raise step.error
        if isinstance(step, ScriptedRawReply):
            return _validated(step.payload)
        return ModelResponse(
            model=step.model if step.model is not None else request.model,
            content=step.content,
            finish_reason=step.finish_reason,
            usage=Usage(tokens_in=step.tokens_in, tokens_out=step.tokens_out),
            cost_usd=step.cost_usd,
        )


def _validated(payload: Mapping[str, object]) -> ModelResponse:
    try:
        return ModelResponse.model_validate(payload)
    except ValidationError as error:
        # Field names and reasons only; the payload's values stay out of the message.
        details = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors(include_url=False, include_input=False, include_context=False)
        )
        raise ModelInvalidResponseError(f"the answer is not a valid response: {details}") from None
