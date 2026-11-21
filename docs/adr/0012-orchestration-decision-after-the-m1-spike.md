# ADR-0012: LangGraph confirmed as the orchestration engine after the M1 spike

- Status: Proposed
- Date: 2026-11-21

## Context

ADR-0001 chose LangGraph and made the choice depend on a spike in M1: stages
3 to 5 are built on it, and four things are confirmed. These are resume after
a crash from the SQLite checkpoint, pause and resume at an approval gate, a
review finding routed back to an earlier stage, and a run that streams
events to the log. If any of the four needs heavy workarounds, the fallback
is a plain Python state machine with the same file contracts
(`docs/spec.md`, section 6, "Prototype evaluation for LangGraph"). The
decision is the exit criterion of M1 (`docs/spec.md`, section 12).

The spike is built: `utux.core.workflow` runs the nodes `methodology`,
`implementation`, `experiment` and `analysis`, and a `check` node, as a
LangGraph `StateGraph` with a `SqliteSaver` at `.utux/checkpoints.sqlite`
(tasks M1-10 to M1-14, `langgraph` 1.2.22 and `langgraph-checkpoint-sqlite`
3.1.3). The four checks are automated tests:

| Check | Test | How LangGraph is used |
| --- | --- | --- |
| 1. Resume after a crash | `tests/integration/test_workflow_kill_and_resume.py`: the process is killed with SIGKILL after the implementation stage; a new process resumes and ends with the same results as an uninterrupted run | The checkpoint written after each node with `durability="sync"`; `invoke(None, thread)` continues from it |
| 2. Pause and resume at a gate | `tests/integration/test_gates.py` (also across processes) and `tests/integration/test_run_cli.py` (through `utux run` and `utux approve`) | A node raises when its gate has no answer, so its checkpoint is not advanced; the next invocation runs the node again, and the node reads the answer from the files |
| 3. A finding routed back | `tests/integration/test_routing.py`, with the retry cap stopping the loop and pausing with `retry_limit` | A conditional edge from the `check` node to `implementation`, `methodology` or the end |
| 4. Events streamed to the log | `tests/integration/test_workflow.py`, `test_events_are_readable_while_the_run_is_in_progress` | Not LangGraph: every event is appended by utux's own event log as it happens |

Check 4 is met only in part. Stage, model call and approval events are
appended as they happen, but the `experiment` node writes no
`code_execution` event; the execution is recorded in the run manifest and
the result records only. The test reads stage events only.

What needed work around LangGraph, none of it a large amount of code:

- LangSmith tracing is switched off in code before any graph is built, and
  the checkpoint serializer is replaced by one that refuses every object it
  would construct (`utux.core`, `utux.core.checkpoints`; M1-02).
- Pausing does not use LangGraph's `interrupt()`. A paused node raises
  `RunPausedError`, and the answer is a file, not a value passed back into
  the graph, so that the files stay the source of truth.
- "The files win" on resume, a rejection at a gate, and `utux run --from`
  move a run to another node with `update_state(..., as_node=...)` on the
  checkpoint, which takes care: the state of the nodes before that point
  must be kept or dropped by hand.
- `utux run --to` uses `interrupt_after`; whether a run is finished is read
  from the snapshot's `next`.
- A node writes into a staging directory and moves its files into place
  only when it completes, because a node that fails halfway is run again
  from its start, and its files must not be half written.
- The run's id is the LangGraph thread id, and a checkpoint that no
  `run_started` event of the log matches is refused.
- Two `type: ignore[call-overload]` on `add_node`, and the compiled graph is
  typed `Any`, because LangGraph's types do not fit `mypy --strict`.

`utux.core` has 2,561 lines, of which `workflow.py` has 1,739. The code that
names LangGraph is about 150 lines: the graph and checkpoint helpers, the
places that invoke, inspect or move the graph, the serializer (90 lines) and
the tracing switch (14 lines). The rest (nodes, gates, routing, staging,
files win, approvals, status) is utux's own logic, which a plain state
machine would need as well.

## Decision

LangGraph stays as the orchestration engine. The four checks pass as
automated tests, apart from the `code_execution` event of check 4, which
does not depend on the engine. None of the work around LangGraph listed
above is heavy, so the fallback of ADR-0001 is not taken.

Before M1 ends, a follow-up task makes the `experiment` node append a
`code_execution` event for each execution run, while the run is in
progress, and extends the check 4 test to model call, code execution and
approval events.

## Alternatives rejected

- **The plain Python state machine of ADR-0001.** Not taken. It would
  replace about 150 lines that name LangGraph, and the 90-line serializer,
  with a loop and a checkpoint format of our own. It would remove a
  dependency of 36 packages and the type workarounds. But the spike needed
  no heavy workaround, which is the condition ADR-0001 sets for the
  fallback, and the stages, gates and routing would be written again for no
  gain in M1.
- **A pluggable engine.** Rejected in ADR-0001; nothing in the spike
  reopens it.

## Consequences

- LangGraph is used in M2 and later, inside `utux.core` only.
- Pauses stay exceptions with answers in files; LangGraph's `interrupt()`
  is not used.
- A follow-up M1 task writes `code_execution` events and tests check 4 in
  full before M1's exit criteria are ticked.
- The dependency conditions of ADR-0001 (tracing off, strict serializer,
  files win, only our own checkpoint) stay in force.

## Sources

- `docs/spec.md`, section 6, "Prototype evaluation for LangGraph": the four
  checks and the fallback.
- `docs/spec.md`, section 12, row "M1. Execution spike": the exit criterion.
- `docs/spec.md`, section 13, "Decisions", row "Orchestration engine".
- `docs/adr/0001-langgraph-orchestration-engine.md`: the choice, the spike
  and its dependency assessment.
- `docs/plan/M1.md`, tasks M1-10 to M1-15.
