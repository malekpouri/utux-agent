# ADR-0011: Approval kinds for pauses that are not about an artifact

- Status: Accepted
- Date: 2026-11-18

## Context

The core writes `approvals/<id>.request.json` and pauses; a response
`approve`, `reject` or `edit` resumes or stops the run (`docs/spec.md`,
section 7, "Approvals"). Today a request is always bound to an artifact: it
has a gate, an artifact id, the content hash and the path of the content to
approve (`src/utux/schemas/approval.py`), and an approval is checked against
that hash.

A budget or retry cap being reached pauses the run and asks the user, in
every mode (section 9, "Oversight modes"). Such a pause concerns no
artifact, so it cannot be expressed by today's request.

The M0 plan left this note for M1: "pauses for budget and retry limits need
an approval request that is not bound to an artifact" (`docs/plan/M0.md`,
Notes).

## Decision

Proposed in `docs/plan/M1.md`, M1-01, and accepted by the maintainer on
2026-11-18 with the additions below:

An approval request has a `kind`: `artifact`, `budget_exhausted` or
`retry_limit`. The artifact fields are required only for `artifact`. For the
other kinds the response is `approve` (continue) or `reject` (stop).
Continuing after `budget_exhausted` is accepted only if the budget was
raised first, which is a `setting_changed` event.

Additions on acceptance:

- A request that is not of kind `artifact` records the stage and the
  `event_id` of the refused call. After `approve`, the run repeats that
  call.
- Continuing after `budget_exhausted` is accepted only if a
  `setting_changed` event for `budget.total_usd` or for the stage's budget
  was written after the request.
- There is no separate budget command. Every command that writes to a
  project compares `utux.yaml` with the last recorded snapshot, kept under
  `.utux/`, before it acts, and writes one `setting_changed` event per
  changed key, with the old and the new value (task M1-05). A hand edit of
  the budget is recorded this way.

### Addition, 2026-11-18: the refused call of `retry_limit`

Decided by the maintainer on 2026-11-18, after task M1-04 asked which event
a `retry_limit` request names. Implemented in task M1-12.

- Task M1-12 defines the event type `route_back`, with data keys
  `from_stage`, `to_stage`, `finding` (a stable code), `attempt` and `cap`.
- A route back within the cap is a `route_back` event with status `ok`. At
  the cap it is a `route_back` event with status `refused` and
  `status_reason` `retry_limit`, and the `retry_limit` request's
  `refused_event_id` names that event.
- `approve` allows one more route back for that loop, raising its cap by
  one, which the event that resumes the run records. `reject` stops the run.
- From task M1-12, `utux validate` checks the type of the referenced event:
  a `budget_exhausted` request names a refused `model_call` with reason
  `budget_exhausted`, and a `retry_limit` request names a refused
  `route_back` with reason `retry_limit`. Until then it checks only that the
  event exists.

## Alternatives rejected

- **A separate file contract for pauses.** A second request and response
  pair, and a second place for a person to look, for what is the same act of
  approving or stopping.
- **Bind a budget or retry pause to a placeholder artifact.** It would fake
  the content hash that makes an artifact approval trustworthy.
- **Resume automatically when the budget is raised.** The specification
  requires asking the user in every mode, and a raised budget alone does not
  say that the person wants to continue.

## Consequences

- The approval request schema changes; under the pre-release rule of
  `AGENTS.md` section 11 no version bump is needed, which the pull request
  says (task M1-04).
- `check_response_matches_request` binds only `artifact` approvals to a
  content hash. An `edit` response is valid only for `artifact`.
- Continuing after `budget_exhausted` depends on a `setting_changed` event
  written after the request. The user raises the budget by editing
  `utux.yaml`; the next writing command, such as `utux approve`, records the
  change before it acts.
- The request schema gains the stage and the refused call's `event_id`
  (task M1-04); repeating the call after `approve` is task M1-11.
- What `gate` holds on a request that is not of kind `artifact` is settled
  in task M1-04: today `gate` names one of the four approval gates.

## Sources

- `docs/spec.md`, section 7 (approvals), section 9 (oversight modes: budget
  and retry caps pause the run in every mode).
- `src/utux/schemas/approval.py`: the current request and response.
- `docs/plan/M0.md`, Notes: the M1 note on pauses.
- `docs/plan/M1.md`, M1-01 and M1-04.
