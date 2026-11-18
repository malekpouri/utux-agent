# ADR-0011: Approval kinds for pauses that are not about an artifact

- Status: Proposed
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

Proposed in `docs/plan/M1.md`, M1-01:

An approval request has a `kind`: `artifact`, `budget_exhausted` or
`retry_limit`. The artifact fields are required only for `artifact`. For the
other kinds the response is `approve` (continue) or `reject` (stop).
Continuing after `budget_exhausted` is accepted only if the budget was
raised first, which is a `setting_changed` event.

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
  that raises the budget. No command that changes a setting and writes that
  event exists yet, and the M1 plan names none; the task that implements
  this decides it, or asks.
- The gate of a request that is not about an artifact is to be defined by
  task M1-04: today `gate` names one of the four approval gates.

## Sources

- `docs/spec.md`, section 7 (approvals), section 9 (oversight modes: budget
  and retry caps pause the run in every mode).
- `src/utux/schemas/approval.py`: the current request and response.
- `docs/plan/M0.md`, Notes: the M1 note on pauses.
- `docs/plan/M1.md`, M1-01 and M1-04.
