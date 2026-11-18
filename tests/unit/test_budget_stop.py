"""M0-12: the budget stop of logged model calls.

Every provider here is the scripted fake; no test reaches the network.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from utux.errors import BudgetExhaustedError, ModelCallRefusedError
from utux.events.log import EventLog
from utux.interfaces.model_provider import Message, MessageRole, ModelRequest
from utux.providers.scripted import ScriptedModelProvider, ScriptedReply
from utux.schemas.common import Stage
from utux.schemas.event import Event, EventStatus, EventType
from utux.schemas.project_config import Budget, DataPolicy
from utux.workspace.model_calls import LoggedModelCaller, input_hash

FIXED = datetime(2026, 11, 17, 9, 30, 0, tzinfo=UTC)
REQUEST = ModelRequest(
    model="synthetic/model",
    messages=(Message(role=MessageRole.USER, content="Synthetic question."),),
    timeout_seconds=30.0,
)


def _log(tmp_path: Path) -> EventLog:
    return EventLog(tmp_path / "events.jsonl", clock=lambda: FIXED)


def _spend(
    log: EventLog,
    costs: list[float | None],
    *,
    stage: Stage | None = None,
    is_external: bool = True,
) -> None:
    """Log one successful call per cost, through the caller itself."""
    provider = ScriptedModelProvider(
        [ScriptedReply(cost_usd=cost) for cost in costs], is_external=is_external
    )
    # Unknown costs are allowed while spending, so that every cost is logged as
    # given; otherwise the second unknown cost would be refused (M1-05).
    budget = Budget(total_usd=1000.0, allow_unknown_cost=True)
    caller = LoggedModelCaller(log, provider, DataPolicy.EXTERNAL_ALLOWED, budget)
    for _ in costs:
        caller.call(REQUEST, actor="agent:planner", prompt_version="synthetic@1", stage=stage)


def _call(
    log: EventLog,
    budget: Budget,
    *,
    stage: Stage | None = None,
    policy: DataPolicy = DataPolicy.EXTERNAL_ALLOWED,
) -> ScriptedModelProvider:
    provider = ScriptedModelProvider([ScriptedReply(cost_usd=0.01)], name="synthetic-provider")
    caller = LoggedModelCaller(log, provider, policy, budget)
    caller.call(REQUEST, actor="agent:writer", prompt_version="writer@1", stage=stage)
    return provider


def _refused(log: EventLog, budget: Budget, *, stage: Stage | None = None) -> list[Event]:
    before = len(list(log))
    provider = ScriptedModelProvider([ScriptedReply()], name="synthetic-provider")
    with pytest.raises(BudgetExhaustedError) as caught:
        LoggedModelCaller(log, provider, DataPolicy.EXTERNAL_ALLOWED, budget).call(
            REQUEST, actor="agent:writer", prompt_version="writer@1", stage=stage
        )
    assert provider.requests == ()
    assert "budget" in str(caught.value)
    return list(log)[before:]


def test_call_below_the_budget_is_made(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _spend(log, [0.1, 0.2])
    provider = _call(log, Budget(total_usd=0.31))
    assert len(provider.requests) == 1
    assert list(log)[-1].status is EventStatus.OK


def test_call_after_the_budget_is_exhausted_is_refused_without_a_network_call(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    _spend(log, [0.1, 0.2])
    call, warning = _refused(log, Budget(total_usd=0.3))

    assert call.type is EventType.MODEL_CALL
    assert call.status is EventStatus.REFUSED
    assert call.status_reason == "budget_exhausted"
    assert call.actor == "agent:writer"
    assert call.model == "synthetic/model"
    assert call.input_hash == input_hash(REQUEST)
    assert (call.output_hash, call.tokens_in, call.tokens_out) == (None, None, None)
    assert (call.cost_usd, call.duration_ms) == (None, None)
    assert call.data == {"provider": "synthetic-provider", "is_external": True}

    assert warning.type is EventType.BUDGET_WARNING
    assert warning.parent_id == call.event_id
    assert warning.actor == "agent:writer"
    assert warning.stage is None
    assert warning.data == {"spent_usd": 0.3, "total_usd": 0.3}


def test_budget_error_is_a_refused_call() -> None:
    assert issubclass(BudgetExhaustedError, ModelCallRefusedError)


def test_overspent_budget_refuses_the_next_call(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _spend(log, [0.5])
    refused = _refused(log, Budget(total_usd=0.4))
    assert refused[1].data == {"spent_usd": 0.5, "total_usd": 0.4}


def test_every_call_after_exhaustion_is_refused_and_refusals_cost_nothing(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _spend(log, [0.3])
    _refused(log, Budget(total_usd=0.3))
    second = _refused(log, Budget(total_usd=0.3))
    assert second[1].data == {"spent_usd": 0.3, "total_usd": 0.3}


def test_unknown_and_local_costs_do_not_exhaust_the_budget(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _spend(log, [None, None, None])
    _spend(log, [None], is_external=False)
    provider = _call(log, Budget(total_usd=0.01))
    assert len(provider.requests) == 1


def test_exhausted_stage_budget_refuses_a_call_of_that_stage(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _spend(log, [0.2], stage=Stage.METHODOLOGY)
    budget = Budget(total_usd=10.0, per_stage_usd={Stage.METHODOLOGY: 0.2})
    call, warning = _refused(log, budget, stage=Stage.METHODOLOGY)
    assert (call.status, call.status_reason) == (EventStatus.REFUSED, "budget_exhausted")
    assert call.stage is Stage.METHODOLOGY
    assert warning.stage is Stage.METHODOLOGY
    assert warning.data == {"spent_usd": 0.2, "total_usd": 0.2}


def test_exhausted_stage_budget_does_not_stop_other_stages_or_calls_without_one(
    tmp_path: Path,
) -> None:
    log = _log(tmp_path)
    _spend(log, [0.2], stage=Stage.METHODOLOGY)
    budget = Budget(total_usd=10.0, per_stage_usd={Stage.METHODOLOGY: 0.2})
    assert len(_call(log, budget, stage=Stage.WRITING).requests) == 1
    assert len(_call(log, budget).requests) == 1


def test_data_policy_is_checked_before_the_budget(tmp_path: Path) -> None:
    log = _log(tmp_path)
    _spend(log, [0.5])
    with pytest.raises(ModelCallRefusedError) as caught:
        _call(log, Budget(total_usd=0.1), policy=DataPolicy.LOCAL_ONLY)
    assert not isinstance(caught.value, BudgetExhaustedError)
    events = list(log)
    assert events[-1].status_reason == "data_policy_local_only"
    assert EventType.BUDGET_WARNING not in [event.type for event in events]
