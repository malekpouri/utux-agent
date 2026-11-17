"""M0-12: cost totals from the event log.

The fixture log is synthetic; its events are listed in
`tests/fixtures/cost/README.md`. Every expected value below is computed by
hand from that table.
"""

from decimal import Decimal
from pathlib import Path

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
    refused: int = 0,
) -> CostTotals:
    return CostTotals(
        known_cost_usd=Decimal(known),
        calls=calls,
        local_unbilled_calls=local,
        unknown_cost_calls=unknown,
        refused_calls=refused,
    )


def test_project_totals_equal_the_hand_computed_values() -> None:
    summary = summarize_costs(_events())
    # 0.0125 + 0.0031 + 0.2 + 0.0000021 + 0 = 0.2156021
    # Calls made: e2 e3 e4 e5 e6 e7 e9 e11 = 8; e8 was refused.
    assert summary.total == _totals("0.2156021", 8, local=1, unknown=2, refused=1)


def test_totals_per_stage_equal_the_hand_computed_values() -> None:
    summary = summarize_costs(_events())
    assert summary.by_stage == {
        # e2 + e3 + e11 = 0.0125 + 0.0031 + 0 = 0.0156
        Stage.IDEATION: _totals("0.0156", 3),
        # e7 failed without a cost at an external provider.
        Stage.LITERATURE: _totals("0", 1, unknown=1),
        # e4 = 0.2; e5 local without cost; e6 external without cost.
        Stage.METHODOLOGY: _totals("0.2", 3, local=1, unknown=1),
        # e8 was refused; no call was made.
        Stage.WRITING: _totals("0", 0, refused=1),
        # e9 has no stage.
        None: _totals("0.0000021", 1),
    }


def test_totals_per_actor_equal_the_hand_computed_values() -> None:
    summary = summarize_costs(_events())
    assert summary.by_actor == {
        "agent:ideator": _totals("0.0156", 3),
        "agent:planner": _totals("0.2", 2, local=1),
        "agent:reviewer": _totals("0", 1, unknown=1),
        "agent:searcher": _totals("0", 1, unknown=1),
        "agent:writer": _totals("0", 0, refused=1),
        "system:utux": _totals("0.0000021", 1),
    }


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
    # Known cost 0.2156021; the two unknown and one local call add nothing.
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


def test_report_as_json() -> None:
    budget = Budget(total_usd=0.25, per_stage_usd={Stage.METHODOLOGY: 0.2})
    report = CostReport(budget, summarize_costs(_events())).to_json()
    assert report["fully_enforceable"] is False
    assert report["total"] == {
        "known_cost_usd": 0.2156021,
        "calls": 8,
        "local_unbilled_calls": 1,
        "unknown_cost_calls": 2,
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
        "calls": 3,
        "local_unbilled_calls": 1,
        "unknown_cost_calls": 1,
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
        "calls": 3,
        "local_unbilled_calls": 0,
        "unknown_cost_calls": 0,
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
