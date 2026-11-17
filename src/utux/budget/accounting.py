"""Cost totals from the event log, and the budget stop.

Totals come from the `model_call` events of `events.jsonl`. Amounts are
summed as exact decimals of the logged values, so that a total equals the
sum a person would write down. A cost is never guessed:

- A call that reported a cost counts with that cost, zero included.
- A call to a local provider (`is_external` false) that reported no cost
  counts as zero and is shown as "local, not billed".
- A call to an external provider that reported no cost, including a call that
  failed, has an unknown cost. It is counted separately and adds nothing to
  the known cost, so the budget cannot be fully enforced while such calls
  exist.
- A refused call made no request and costs nothing; it is counted as refused.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path

from utux.events.log import EventLog
from utux.schemas.common import Stage
from utux.schemas.event import Event, EventStatus, EventType
from utux.schemas.project_config import Budget, load_project_config
from utux.workspace.layout import CONFIG_FILE, EVENT_LOG_FILE

ZERO = Decimal(0)


def usd(amount: float) -> Decimal:
    """Return a logged or configured amount as the exact decimal it was written as."""
    # repr gives the shortest text that reads back as the same float, which is
    # what the JSON or YAML file holds.
    return Decimal(repr(amount))


@dataclass(frozen=True)
class CostTotals:
    """The cost of a group of model calls.

    Attributes:
        known_cost_usd: The sum of the costs that are known.
        calls: Calls that were made, successful or failed. Refused calls are
            not included.
        local_unbilled_calls: Calls to a local provider that reported no cost.
            They count as zero.
        unknown_cost_calls: Calls to an external provider that reported no
            cost.
        refused_calls: Calls that utux refused; no request was sent.
    """

    known_cost_usd: Decimal = ZERO
    calls: int = 0
    local_unbilled_calls: int = 0
    unknown_cost_calls: int = 0
    refused_calls: int = 0

    def add(self, event: Event) -> "CostTotals":
        """Return the totals with one `model_call` event added."""
        if event.status is EventStatus.REFUSED:
            return replace(self, refused_calls=self.refused_calls + 1)
        totals = replace(self, calls=self.calls + 1)
        if event.cost_usd is not None:
            return replace(totals, known_cost_usd=totals.known_cost_usd + usd(event.cost_usd))
        if event.data.get("is_external") is False:
            return replace(totals, local_unbilled_calls=totals.local_unbilled_calls + 1)
        return replace(totals, unknown_cost_calls=totals.unknown_cost_calls + 1)

    def to_json(self) -> dict[str, object]:
        """Return the totals as a JSON object."""
        return {
            "known_cost_usd": float(self.known_cost_usd),
            "calls": self.calls,
            "local_unbilled_calls": self.local_unbilled_calls,
            "unknown_cost_calls": self.unknown_cost_calls,
            "refused_calls": self.refused_calls,
        }


@dataclass(frozen=True)
class CostSummary:
    """The totals of a log: for the project, per stage and per actor.

    `by_stage` has the key None for calls without a stage. A stage or actor
    without any `model_call` event is not a key.
    """

    total: CostTotals = field(default_factory=CostTotals)
    by_stage: Mapping[Stage | None, CostTotals] = field(default_factory=dict)
    by_actor: Mapping[str, CostTotals] = field(default_factory=dict)


def summarize_costs(events: Iterable[Event]) -> CostSummary:
    """Sum the cost of the `model_call` events. Other events are ignored."""
    total = CostTotals()
    by_stage: dict[Stage | None, CostTotals] = {}
    by_actor: dict[str, CostTotals] = {}
    for event in events:
        if event.type is not EventType.MODEL_CALL:
            continue
        total = total.add(event)
        by_stage[event.stage] = by_stage.get(event.stage, CostTotals()).add(event)
        by_actor[event.actor] = by_actor.get(event.actor, CostTotals()).add(event)
    return CostSummary(total, by_stage, by_actor)


@dataclass(frozen=True)
class ExhaustedBudget:
    """A budget whose known cost has reached its limit.

    Attributes:
        stage: The stage whose budget is exhausted, or None for the project
            budget.
        spent_usd: The known cost, of the project or of the stage.
        total_usd: The budget it was compared with.
    """

    stage: Stage | None
    spent_usd: Decimal
    total_usd: Decimal


def exhausted_budget(
    summary: CostSummary, budget: Budget, stage: Stage | None
) -> ExhaustedBudget | None:
    """Return the budget that stops a call of `stage`, or None if none does.

    A budget is exhausted when the known cost is equal to it or more. The
    project budget is checked first, then the budget of the call's stage, if
    the call has a stage and that stage has a budget. Unknown costs are not
    included, because they are not known.
    """
    spent = summary.total.known_cost_usd
    total = usd(budget.total_usd)
    if spent >= total:
        return ExhaustedBudget(None, spent, total)
    if stage is not None and stage in budget.per_stage_usd:
        spent = summary.by_stage.get(stage, CostTotals()).known_cost_usd
        total = usd(budget.per_stage_usd[stage])
        if spent >= total:
            return ExhaustedBudget(stage, spent, total)
    return None


@dataclass(frozen=True)
class CostReport:
    """The cost of a project against its budget."""

    budget: Budget
    summary: CostSummary

    @property
    def fully_enforceable(self) -> bool:
        """False while a call to an external provider has an unknown cost."""
        return self.summary.total.unknown_cost_calls == 0

    def stages(self) -> list[tuple[Stage | None, CostTotals, Decimal | None]]:
        """Return each stage with calls or a budget, in stage order, then None.

        Each item is the stage, its totals and its budget, or None when the
        stage has no budget of its own.
        """
        rows: list[tuple[Stage | None, CostTotals, Decimal | None]] = []
        for stage in Stage:
            limit = self.budget.per_stage_usd.get(stage)
            if stage in self.summary.by_stage or limit is not None:
                rows.append(
                    (
                        stage,
                        self.summary.by_stage.get(stage, CostTotals()),
                        None if limit is None else usd(limit),
                    )
                )
        if None in self.summary.by_stage:
            rows.append((None, self.summary.by_stage[None], None))
        return rows

    def actors(self) -> list[tuple[str, CostTotals]]:
        """Return each actor with its totals, sorted by actor."""
        return sorted(self.summary.by_actor.items())

    def to_json(self) -> dict[str, object]:
        """Return the report as a JSON object."""
        return {
            "fully_enforceable": self.fully_enforceable,
            "total": {
                **self.summary.total.to_json(),
                **_against(self.summary.total, usd(self.budget.total_usd)),
            },
            "per_stage": [
                {"stage": None if stage is None else stage.value, **totals.to_json()}
                | _against(totals, limit)
                for stage, totals, limit in self.stages()
            ],
            "per_actor": [{"actor": actor, **totals.to_json()} for actor, totals in self.actors()],
        }


def remaining(totals: CostTotals, limit: Decimal) -> Decimal:
    """Return what is left of a budget, never less than zero."""
    return max(ZERO, limit - totals.known_cost_usd)


def _against(totals: CostTotals, limit: Decimal | None) -> dict[str, object]:
    if limit is None:
        return {"budget_usd": None, "remaining_usd": None, "exhausted": False}
    return {
        "budget_usd": float(limit),
        "remaining_usd": float(remaining(totals, limit)),
        "exhausted": totals.known_cost_usd >= limit,
    }


def project_cost_report(project: Path) -> CostReport:
    """Read the budget and the event log of a project and total its cost.

    Raises:
        ContractValidationError: `utux.yaml` is missing or invalid.
        EventLogError: The event log cannot be read.
    """
    config = load_project_config(project / CONFIG_FILE)
    return CostReport(config.budget, summarize_costs(EventLog(project / EVENT_LOG_FILE)))
