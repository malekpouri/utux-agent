"""M0-12: cost totals from the event log.

The fixture log is synthetic; its events are listed in
`tests/fixtures/cost/README.md`. Every expected value below is computed by
hand from that table.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from utux.budget.accounting import (
    CostReport,
    CostTotals,
    ExhaustedBudget,
    exhausted_budget,
    summarize_costs,
)
from utux.events.log import EventLog
from utux.schemas.common import Stage
from utux.schemas.event import Event
from utux.schemas.project_config import Budget

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "cost" / "events.jsonl"


def _events() -> list[Event]:
    return list(EventLog(FIXTURE))


def _totals(
    known: str,
    calls: int,
    *,
    local: int = 0,
    unknown: int = 0,
    failed: int = 0,
    refused: int = 0,
) -> CostTotals:
    return CostTotals(
        known_cost_usd=Decimal(known),
        calls=calls,
        local_unbilled_calls=local,
        unknown_cost_calls=unknown,
        failed_unbilled_calls=failed,
        refused_calls=refused,
    )


def test_project_totals_equal_the_hand_computed_values() -> None:
    summary = summarize_costs(_events())
    # Known: e2 + e3 + e4 + e9 + e11 = 0.0125 + 0.0031 + 0.2 + 0.0000021 + 0 = 0.2156021
    # Calls made: e2 e3 e4 e5 e6 e7 e9 e11 e12 e13 e14 e15 e16 = 13; e8 was refused.
    # Local, not billed: e5, e16. Unknown: e6, e7, e15. Failed, not billed: e12, e13, e14.
    assert summary.total == _totals("0.2156021", 13, local=2, unknown=3, failed=3, refused=1)


def test_totals_per_stage_equal_the_hand_computed_values() -> None:
    summary = summarize_costs(_events())
    assert summary.by_stage == {
        # e2 + e3 + e11 = 0.0125 + 0.0031 + 0 = 0.0156; e15 interrupted, unknown.
        Stage.IDEATION: _totals("0.0156", 4, unknown=1),
        # e7 timed out (unknown); e12 rate limited (failed, not billed).
        Stage.LITERATURE: _totals("0", 2, unknown=1, failed=1),
        # e4 = 0.2; e5 and e16 local without cost; e6 external without cost.
        Stage.METHODOLOGY: _totals("0.2", 4, local=2, unknown=1),
        # e8 was refused; e14 was rejected (failed, not billed).
        Stage.WRITING: _totals("0", 1, failed=1, refused=1),
        # e9 = 0.0000021; e13 failed authentication (failed, not billed).
        None: _totals("0.0000021", 2, failed=1),
    }


def test_totals_per_actor_equal_the_hand_computed_values() -> None:
    summary = summarize_costs(_events())
    assert summary.by_actor == {
        "agent:ideator": _totals("0.0156", 4, unknown=1),
        "agent:planner": _totals("0.2", 3, local=2),
        "agent:reviewer": _totals("0", 1, unknown=1),
        "agent:searcher": _totals("0", 2, unknown=1, failed=1),
        "agent:writer": _totals("0", 1, failed=1, refused=1),
        "system:utux": _totals("0.0000021", 2, failed=1),
    }


@pytest.mark.parametrize(
    ("reason", "is_external", "kind"),
    [
        ("model_authentication", True, "failed"),
        ("model_request_rejected", True, "failed"),
        ("model_rate_limit", True, "failed"),
        ("model_authentication", False, "failed"),
        ("model_timeout", True, "unknown"),
        ("model_unavailable", True, "unknown"),
        ("model_invalid_response", True, "unknown"),
        ("interrupted", True, "unknown"),
        ("unexpected_error", True, "unknown"),
        ("model_timeout", False, "local"),
        ("interrupted", False, "local"),
    ],
)
def test_failed_calls_are_split_by_their_reason(reason: str, is_external: bool, kind: str) -> None:
    failed = _events()[6]  # e-000007, an external call that failed
    event = failed.model_copy(
        update={
            "status_reason": reason,
            "data": {"provider": "synthetic", "is_external": is_external},
        }
    )
    expected = {
        "failed": _totals("0", 1, failed=1),
        "unknown": _totals("0", 1, unknown=1),
        "local": _totals("0", 1, local=1),
    }[kind]
    assert summarize_costs([event]).total == expected


def test_sums_are_exact_decimals() -> None:
    # 0.1 + 0.2 in binary floating point is 0.30000000000000004.
    summary = summarize_costs(_with_costs([0.1, 0.2]))
    assert summary.total.known_cost_usd == Decimal("0.3")


def test_an_empty_log_costs_nothing() -> None:
    summary = summarize_costs([])
    assert summary.total == _totals("0", 0)
    assert summary.by_stage == {}
    assert summary.by_actor == {}


# Budget stop


def test_budget_is_exhausted_when_the_known_cost_reaches_the_total() -> None:
    summary = summarize_costs(_with_costs([0.1, 0.2]))
    assert exhausted_budget(summary, Budget(total_usd=0.31), None) is None
    assert exhausted_budget(summary, Budget(total_usd=0.3), None) == ExhaustedBudget(
        stage=None, spent_usd=Decimal("0.3"), total_usd=Decimal("0.3")
    )
    assert exhausted_budget(summary, Budget(total_usd=0.25), None) == ExhaustedBudget(
        stage=None, spent_usd=Decimal("0.3"), total_usd=Decimal("0.25")
    )


def test_unknown_and_local_costs_do_not_count_toward_the_budget() -> None:
    summary = summarize_costs(_events())
    # Known cost 0.2156021; the unknown, local and failed calls add nothing.
    assert exhausted_budget(summary, Budget(total_usd=0.2156022), None) is None


def test_stage_budget_is_checked_for_a_call_with_that_stage() -> None:
    summary = summarize_costs(_events())
    budget = Budget(total_usd=10.0, per_stage_usd={Stage.METHODOLOGY: 0.2})
    assert exhausted_budget(summary, budget, Stage.METHODOLOGY) == ExhaustedBudget(
        stage=Stage.METHODOLOGY, spent_usd=Decimal("0.2"), total_usd=Decimal("0.2")
    )
    assert exhausted_budget(summary, budget, Stage.IDEATION) is None
    assert exhausted_budget(summary, budget, None) is None


def test_project_budget_is_reported_before_a_stage_budget() -> None:
    summary = summarize_costs(_events())
    budget = Budget(total_usd=0.2, per_stage_usd={Stage.METHODOLOGY: 0.2})
    assert exhausted_budget(summary, budget, Stage.METHODOLOGY) == ExhaustedBudget(
        stage=None, spent_usd=Decimal("0.2156021"), total_usd=Decimal("0.2")
    )


# The report


def test_report_states_whether_the_budget_can_be_fully_enforced() -> None:
    budget = Budget(total_usd=1.0)
    assert not CostReport(budget, summarize_costs(_events())).fully_enforceable
    assert CostReport(budget, summarize_costs(_with_costs([0.1]))).fully_enforceable
    # A failed call that is assumed not billed does not stop enforcement.
    rejected = _events()[13]  # e-000014, model_request_rejected
    assert CostReport(budget, summarize_costs([rejected])).fully_enforceable


def test_report_as_json() -> None:
    budget = Budget(total_usd=0.25, per_stage_usd={Stage.METHODOLOGY: 0.2})
    report = CostReport(budget, summarize_costs(_events())).to_json()
    assert report["fully_enforceable"] is False
    assert report["total"] == {
        "known_cost_usd": 0.2156021,
        "calls": 13,
        "local_unbilled_calls": 2,
        "unknown_cost_calls": 3,
        "failed_unbilled_calls": 3,
        "refused_calls": 1,
        "budget_usd": 0.25,
        # 0.25 - 0.2156021
        "remaining_usd": 0.0343979,
        "exhausted": False,
    }
    stages = report["per_stage"]
    assert isinstance(stages, list)
    # Stage order, then the calls without a stage.
    assert [row["stage"] for row in stages] == [
        "ideation",
        "literature",
        "methodology",
        "writing",
        None,
    ]
    assert stages[2] == {
        "stage": "methodology",
        "known_cost_usd": 0.2,
        "calls": 4,
        "local_unbilled_calls": 2,
        "unknown_cost_calls": 1,
        "failed_unbilled_calls": 0,
        "refused_calls": 0,
        "budget_usd": 0.2,
        "remaining_usd": 0.0,
        "exhausted": True,
    }
    assert stages[0]["budget_usd"] is None
    assert stages[0]["remaining_usd"] is None
    assert stages[0]["exhausted"] is False
    actors = report["per_actor"]
    assert isinstance(actors, list)
    assert [row["actor"] for row in actors] == [
        "agent:ideator",
        "agent:planner",
        "agent:reviewer",
        "agent:searcher",
        "agent:writer",
        "system:utux",
    ]
    assert actors[0] == {
        "actor": "agent:ideator",
        "known_cost_usd": 0.0156,
        "calls": 4,
        "local_unbilled_calls": 0,
        "unknown_cost_calls": 1,
        "failed_unbilled_calls": 0,
        "refused_calls": 0,
    }


def test_a_stage_with_a_budget_and_no_calls_is_listed() -> None:
    budget = Budget(total_usd=1.0, per_stage_usd={Stage.EXPERIMENT: 0.5})
    report = CostReport(budget, summarize_costs([])).to_json()
    stages = report["per_stage"]
    assert isinstance(stages, list)
    assert stages == [
        {
            "stage": "experiment",
            "known_cost_usd": 0.0,
            "calls": 0,
            "local_unbilled_calls": 0,
            "unknown_cost_calls": 0,
            "failed_unbilled_calls": 0,
            "refused_calls": 0,
            "budget_usd": 0.5,
            "remaining_usd": 0.5,
            "exhausted": False,
        }
    ]


def _with_costs(costs: list[float]) -> list[Event]:
    """Events like e-000002 of the fixture, with other costs."""
    template = _events()[1]
    return [
        template.model_copy(update={"event_id": f"e-{index:06d}", "cost_usd": cost})
        for index, cost in enumerate(costs, start=2)
    ]
