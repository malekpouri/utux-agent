"""Model calls that are logged to the event log of a project.

Every call through `LoggedModelCaller` writes exactly one `model_call` event,
whether it succeeds, fails or is refused. The event holds hashes of what was
sent and what came back, never the text itself, together with the tokens, the
cost as the provider reported it, the duration, the status and the prompt
version. Its `data` names the provider and whether it is external, so that the
log shows which provider received which content hash.

A call is refused before any request is sent when the data policy does not
allow it; when an earlier successful call to the same external provider
reported no cost and `budget.allow_unknown_cost` is false; or when the known
cost has reached the project budget or the budget of the call's stage. A
refusal for the budget also writes a `budget_warning` event.
"""

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from utux.budget.accounting import exhausted_budget, summarize_costs
from utux.errors import (
    BudgetExhaustedError,
    ModelAuthenticationError,
    ModelCallRefusedError,
    ModelInvalidResponseError,
    ModelProviderConfigError,
    ModelProviderError,
    ModelRateLimitError,
    ModelRequestRejectedError,
    ModelTimeoutError,
    ModelUnavailableError,
    UnknownCostNotAllowedError,
)
from utux.events.log import EventLog
from utux.interfaces.model_provider import (
    Message,
    MessageRole,
    ModelProvider,
    ModelRequest,
    ModelResponse,
)
from utux.providers import profiles
from utux.schemas.common import Stage, Tier
from utux.schemas.event import Event, EventStatus, EventType, NewEvent
from utux.schemas.project_config import Budget, DataPolicy, load_project_config
from utux.workspace.hashing import hash_bytes
from utux.workspace.layout import CONFIG_FILE, EVENT_LOG_FILE
from utux.workspace.writer import writing_command

REFUSED_LOCAL_ONLY = "data_policy_local_only"
REFUSED_BUDGET = "budget_exhausted"
REFUSED_UNKNOWN_COST = "unknown_cost_not_allowed"
UNEXPECTED_ERROR = "unexpected_error"
INTERRUPTED = "interrupted"

# The status reason of each typed error.
STATUS_REASONS: tuple[tuple[type[ModelProviderError], str], ...] = (
    (ModelTimeoutError, "model_timeout"),
    (ModelRateLimitError, "model_rate_limit"),
    (ModelUnavailableError, "model_unavailable"),
    (ModelAuthenticationError, "model_authentication"),
    (ModelRequestRejectedError, "model_request_rejected"),
    (ModelInvalidResponseError, "model_invalid_response"),
)

PING_PROMPT = "Reply with the single word: pong"
PING_PROMPT_VERSION = "ping@1"
SYSTEM_ACTOR = "system:utux"


def input_hash(request: ModelRequest) -> str:
    """Return the content hash of what a request asks for.

    It is the SHA-256 of the request as canonical JSON (sorted keys, no
    spaces, UTF-8): the model, the messages, the temperature and the output
    limit. The timeout is left out, because it does not change the answer.
    """
    canonical = {
        "model": request.model,
        "messages": [
            {"role": message.role.value, "content": message.content} for message in request.messages
        ],
        "temperature": request.temperature,
        "max_output_tokens": request.max_output_tokens,
    }
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hash_bytes(text.encode("utf-8"))


def output_hash(response: ModelResponse) -> str:
    """Return the content hash of an answer: the SHA-256 of its text in UTF-8."""
    return hash_bytes(response.content.encode("utf-8"))


def status_reason(error: Exception) -> str:
    """Return the stable status reason for an error of a model call."""
    for kind, reason in STATUS_REASONS:
        if isinstance(error, kind):
            return reason
    return UNEXPECTED_ERROR


class LoggedModelCaller:
    """Calls a model provider and logs every call as one `model_call` event."""

    def __init__(
        self,
        log: EventLog,
        provider: ModelProvider,
        data_policy: DataPolicy,
        budget: Budget,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Create the caller.

        Args:
            log: The event log of the project.
            provider: The provider to call.
            data_policy: The project's data policy. Under `local_only`, calls
                to an external provider are refused.
            budget: The project's budget. A call is refused once the known
                cost has reached it, or the budget of the call's stage.
            clock: A monotonic clock in seconds, for the duration. Tests pass
                a fake.
        """
        self._log = log
        self._provider = provider
        self._data_policy = data_policy
        self._budget = budget
        self._clock = clock
        # The event of the last successful call, so that a caller can name
        # the call, for example in the file name of a trace of its answer.
        self.last_event: Event | None = None

    def call(
        self,
        request: ModelRequest,
        *,
        actor: str,
        prompt_version: str | None,
        stage: Stage | None = None,
        run_id: str | None = None,
        retry_reason: str | None = None,
    ) -> ModelResponse:
        """Make one model call and log it as exactly one event.

        The answer is returned only after its event is written, so that no
        result is used without a record. `run_id` names the run the call
        belongs to, if any, in the event.

        Raises:
            ModelCallRefusedError: The data policy does not allow the call.
                It is logged with status `refused`; no request is sent.
            UnknownCostNotAllowedError: An earlier successful call to this
                external provider reported no cost, and
                `budget.allow_unknown_cost` is false. Logged with status
                `refused`; no request is sent.
            BudgetExhaustedError: The project budget, or the budget of the
                call's stage, is exhausted. The call is logged with status
                `refused` and a `budget_warning` event follows it; no request
                is sent.
            ModelProviderError: The call failed. It is logged with status
                `error` and the status reason of its type; the same error is
                raised again.
            KeyboardInterrupt: The call was interrupted. It is logged with
                status `error` and the status reason `interrupted`, then
                raised again.
            EventLogError: The event could not be written.
        """

        def event(status: EventStatus, **fields: Any) -> NewEvent:
            return NewEvent(
                actor=actor,
                type=EventType.MODEL_CALL,
                stage=stage,
                run_id=run_id,
                retry_reason=retry_reason,
                prompt_version=prompt_version,
                input_hash=input_hash(request),
                data={"provider": self._provider.name, "is_external": self._provider.is_external},
                status=status,
                **fields,
            )

        if self._data_policy is DataPolicy.LOCAL_ONLY and self._provider.is_external:
            self._log.append(
                event(EventStatus.REFUSED, status_reason=REFUSED_LOCAL_ONLY, model=request.model)
            )
            raise ModelCallRefusedError(
                f"the data policy local_only does not allow calls to the external provider "
                f"{self._provider.name}"
            )
        if (
            self._provider.is_external
            and not self._budget.allow_unknown_cost
            and self._reported_no_cost(self._provider.name)
        ):
            self._log.append(
                event(EventStatus.REFUSED, status_reason=REFUSED_UNKNOWN_COST, model=request.model)
            )
            raise UnknownCostNotAllowedError(
                f"an earlier call to the external provider {self._provider.name} reported "
                "no cost, so its spending cannot be held against the budget; set "
                "budget.allow_unknown_cost to true in utux.yaml to accept that"
            )
        exhausted = exhausted_budget(summarize_costs(self._log), self._budget, stage)
        if exhausted is not None:
            refused = self._log.append(
                event(EventStatus.REFUSED, status_reason=REFUSED_BUDGET, model=request.model)
            )
            self._log.append(
                NewEvent(
                    actor=actor,
                    type=EventType.BUDGET_WARNING,
                    stage=exhausted.stage,
                    parent_id=refused.event_id,
                    status=EventStatus.OK,
                    data={
                        "spent_usd": float(exhausted.spent_usd),
                        "total_usd": float(exhausted.total_usd),
                    },
                )
            )
            scope = "the project" if exhausted.stage is None else f"the stage {exhausted.stage}"
            raise BudgetExhaustedError(
                f"the budget of {scope} is exhausted: {exhausted.spent_usd} USD spent "
                f"of {exhausted.total_usd} USD; no request was sent",
                refused_event_id=refused.event_id,
            )
        started = self._clock()
        try:
            response = self._provider.complete(request)
        except (Exception, KeyboardInterrupt) as error:
            # Logged, then raised again unchanged. An interrupt is logged too,
            # because the request may already have reached the provider.
            reason = INTERRUPTED if isinstance(error, KeyboardInterrupt) else status_reason(error)
            self._log.append(
                event(
                    EventStatus.ERROR,
                    status_reason=reason,
                    model=request.model,
                    duration_ms=self._milliseconds_since(started),
                )
            )
            raise
        self.last_event = self._log.append(
            event(
                EventStatus.OK,
                model=response.model,
                output_hash=output_hash(response),
                tokens_in=response.usage.tokens_in,
                tokens_out=response.usage.tokens_out,
                cost_usd=response.cost_usd,
                duration_ms=self._milliseconds_since(started),
            )
        )
        return response

    def _reported_no_cost(self, provider: str) -> bool:
        """Whether a successful call to this external provider reported no cost.

        Only a successful call counts: a refused call sent nothing, and a
        failed call is accounted for by its own rules.
        """
        return any(
            event.type is EventType.MODEL_CALL
            and event.status is EventStatus.OK
            and event.cost_usd is None
            and event.data.get("provider") == provider
            and event.data.get("is_external") is True
            for event in self._log
        )

    def _milliseconds_since(self, started: float) -> int:
        return max(0, round((self._clock() - started) * 1000))


@dataclass(frozen=True)
class Ping:
    """The result of `ping_model`."""

    provider: str
    response: ModelResponse


def ping_model(project: Path, tier: Tier) -> Ping:
    """Send a fixed short prompt to the model of a tier, logged in the project.

    The model comes from `models.tiers` in `utux.yaml`, and the provider from
    the project's profile. The command holds the project lock and records
    setting changes before it calls (`utux.workspace.writer`).

    Raises:
        ProjectLockedError: Another command holds the project lock.
        ContractValidationError: `utux.yaml` is missing or invalid.
        ModelProviderConfigError: No model is configured for the tier, or the
            profile has no provider. Nothing is logged.
        ModelCallRefusedError: The data policy does not allow the call, or
            the budget is exhausted (`BudgetExhaustedError`).
        ModelProviderError: The call failed.
    """
    with writing_command(project, "model ping"):
        return _ping(project, tier)


def _ping(project: Path, tier: Tier) -> Ping:
    config = load_project_config(project / CONFIG_FILE)
    model = config.models.tiers.get(tier)
    if model is None:
        raise ModelProviderConfigError(
            f"no model is configured for the tier {tier.value} in {CONFIG_FILE} (models.tiers)"
        )
    provider = profiles.provider_for_profile(
        config.profile, local_base_url=config.local_server.base_url
    )
    caller = LoggedModelCaller(
        EventLog(project / EVENT_LOG_FILE), provider, config.data_policy, config.budget
    )
    response = caller.call(
        ModelRequest(
            model=model,
            messages=(Message(role=MessageRole.USER, content=PING_PROMPT),),
            timeout_seconds=60.0,
            temperature=0.0,
            max_output_tokens=8,
        ),
        actor=SYSTEM_ACTOR,
        prompt_version=PING_PROMPT_VERSION,
    )
    return Ping(provider.name, response)
