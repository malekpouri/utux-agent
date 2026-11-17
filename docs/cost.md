# Cost and budget: `utux cost`

utux totals the cost of a project from the `model_call` events of its
`events.jsonl` (`utux.budget.accounting`). Nothing else is read: a cost that
was not logged does not exist for utux, and a cost is never guessed.

## How a call counts

| The call | Counts as |
| --- | --- |
| Reported a cost (zero included) | that cost, in the known cost |
| Local provider (`is_external` false), no cost reported | zero, shown as "local, not billed" |
| Failed with `model_authentication`, `model_request_rejected` or `model_rate_limit` | zero, shown as "failed, not billed" |
| External provider, no cost reported, successful or failed for any other reason (`model_timeout`, `model_unavailable`, `model_invalid_response`, `interrupted`, `unexpected_error`) | unknown cost: counted separately, adds nothing to the known cost |
| Refused by utux (`status` `refused`) | no request was sent; counted as refused, costs nothing |

"Failed, not billed" is an assumption about provider billing, not a confirmed
fact. A rejected key, a rejected request and a rate limit usually mean that
the provider refused the request before doing any work, so no provider is
expected to bill it; utux has not confirmed this with any provider. The other
failures can come after the provider has started work, for example a
timeout, so their cost stays unknown when the provider is external.

Amounts are summed as exact decimals of the logged values, so 0.1 and 0.2
make 0.3.

While a call of unknown cost exists, the budget cannot be fully enforced:
only the known cost is compared with the budget. `utux cost` says so.

## The budget stop

Before each model call, after the data policy check, utux compares the known
cost with the budget:

- The project budget, `budget.total_usd` in `utux.yaml`, is checked first.
- Then, if the call has a stage and that stage has a budget in
  `budget.per_stage_usd`, the known cost of that stage is compared with it.

A budget is exhausted when the known cost is equal to it or more. The call is
then refused before any request is sent, and two events are written:

1. a `model_call` event with status `refused` and `status_reason`
   `budget_exhausted`;
2. a `budget_warning` event whose `parent_id` is that call, whose `stage` is
   the stage whose budget is exhausted (null for the project budget), and
   whose `data` is `{"spent_usd": <known cost>, "total_usd": <budget>}`.

`BudgetExhaustedError` is raised. Every later call is refused the same way
until the budget is raised.

A call can overshoot: the cost of a call is known only after it returns, so
the call that crosses the budget is completed and logged, and the next one is
refused.

## `utux cost`

```bash
uv run utux cost [DIRECTORY] [--json]
```

It prints the known cost of the project against its budget, the number of
calls made and refused, the local, failed-not-billed and unknown-cost calls, and the totals per
stage and per actor. Every stage with a call or a budget is listed, in stage
order, then the calls without a stage:

```text
Known cost: 0.2156021 USD of a budget of 0.25 USD (0.0343979 USD left)
Calls: 13 made, 1 refused
Local, not billed: 2 calls
Failed, not billed: 3 calls (assumed: the provider rejected them)
Unknown cost: 3 calls to an external provider reported no cost
The budget cannot be fully enforced while calls of unknown cost exist: only the known cost is compared with the budget.

Per stage:
  ideation: 0.0156 USD, 4 calls, 1 of unknown cost
  literature: 0 USD, 2 calls, 1 failed, not billed, 1 of unknown cost
  methodology: 0.2 USD of a budget of 0.2 USD, exhausted, 4 calls, 2 local, not billed, 1 of unknown cost
  writing: 0 USD, 1 call, 1 failed, not billed, 1 refused
  no stage: 0.0000021 USD, 2 calls, 1 failed, not billed

Per actor:
  agent:ideator: 0.0156 USD, 4 calls, 1 of unknown cost
  ...
```

This example is the synthetic log of `tests/fixtures/cost`.

With `--json` the same report is printed as one JSON object:

| Key | Value |
| --- | --- |
| `fully_enforceable` | false while a call of unknown cost exists |
| `total` | the totals of the project and its budget |
| `per_stage` | one object per stage, with `stage` (null for calls without a stage) |
| `per_actor` | one object per actor, with `actor`, sorted by actor |

Each totals object has `known_cost_usd`, `calls`, `local_unbilled_calls`,
`unknown_cost_calls`, `failed_unbilled_calls` and `refused_calls`. The project and each stage also have
`budget_usd`, `remaining_usd` (never below zero) and `exhausted`; for a stage
without a budget of its own these are null, null and false.
