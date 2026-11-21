# How a run works

A run takes a project through stages 3 to 5 of the specification:
methodology, implementation, and experiment and analysis. It is the graph in
`utux.core.workflow`, built on LangGraph, which no module outside `utux.core`
imports. `run_workflow(project, services)` starts a run and
`resume_workflow(project, services)` continues one; `utux run` does either
([Running a project from the command line](cli-runs.md)). Both hold the
project lock and record setting changes first ([Creating a project](project.md)).

## Two kinds of run

| Kind | What it is | Its id |
| --- | --- | --- |
| Workflow run | One pass through the nodes, from `run_workflow` to the end, resumed as often as needed | The id of its `run_started` event, for example `e-000004`. It is in the `run_id` field of every event of the run, and it is the thread id of the run's checkpoints |
| Execution run | One step in a container, started by the `experiment` node | `r` and at least three digits, for example `r012`. It names `runs/<id>/`, the run manifest's `run_id` and the result records' `run_id` |

The two forms cannot be confused: an event id starts with `e-`, and a run
manifest refuses one.

## The nodes

| Node | Stage | Reads | Writes |
| --- | --- | --- | --- |
| `methodology` | `methodology` | `inputs/*.md` | `method.md`, from the methodologist's plan |
| `implementation` | `implementation` | `method.md` | `code/main.py`, from the implementer |
| `experiment` | `experiment` | `code/main.py` | `runs/<run>/`: the run in the sandbox, its manifest and its result records ([Result records from a run](results.md)) |
| `analysis` | `experiment` | the run's manifest and records | `results.md`, from the analyst's text and the result records |

Each node writes its outputs with sidecars, between a `stage_start` and a
`stage_end` event that name it in `data.node`.

**A node that stops halfway leaves nothing in place** (specification,
section 7). A node writes its outputs and their sidecars into
`.utux/staging/<node>/`, which mirrors the project's paths and is not in git;
the experiment's container writes its outputs there too. Only when the node
has finished are the files moved into the project, sidecars last, before its
`stage_end` event. A node that runs again after a crash starts from an empty
staging area. If a crash comes after the files were moved, the node runs
again and finds that the current version of each output already has the
same content, inputs and maker; it is that version, and no second one is
made. The model calls are logged
with the run's id.

## The roles

Three roles answer the model calls of the run, each with its prompt and the
tier `models.roles` gives it (default `standard`; there is no escalation in
M1).

| Role | Node | Reads | Answers |
| --- | --- | --- | --- |
| methodologist | `methodology` | the files `inputs/*.md`: the question and the data description | numbered steps, each with a title, a description, a success criterion and the metrics it produces |
| implementer | `implementation` | `method.md` | the code of the step, which writes `metrics.json` into the directory in the environment variable `UTUX_OUTPUT_DIR` |
| analyst | `analysis` | the run's result records: id, metric, dataset, split, model, value and unit | a text that refers to every number by its result id, `[R0001]`, and has no other digit |

**Prompts** are versioned files of the pack, `packs/generic/prompts/<role>@<n>.md`,
whose first line is `# Role: <role>`; the highest version is used, and its
name, such as `methodologist@1`, is the `prompt_version` of every model call.
The prompt is the call's system message; the inputs are its user message.

**Answers are JSON**, validated against the role's schema
(`utux.core.agents`). An answer that is not valid is asked for once more,
with the problems in the request and `retry_reason`
`invalid_structured_output` on the call's event. A second invalid answer
fails the stage with `AgentOutputError`, records an `error` event with that
reason, and writes nothing.

- `method.md` is written by utux from the methodologist's steps, so its
  metric lines always have their exact form.
- `results.md` is written by utux from the analyst's text: each `[R0001]`
  becomes `<value> <unit> [R0001]` from that record. The text is checked
  before (no digit and no number word outside a reference, no unknown
  reference) and `results.md` after: a number without its result record is
  refused. The number words are zero to nineteen, the tens, hundred,
  thousand, million, billion, percent, per cent, half, twice, double and
  triple, as whole words in any case. The check catches digits and these
  words; it is not a proof that no number was written ("a dozen", a number
  in another language). Configuration numbers, such as the number of folds,
  belong in `method.md`, and the analyst's prompt says so.

## Starting a run, and commits

A run first makes the test commit of ADR-0010 in a temporary repository with
the project's git configuration: standard input closed,
`GIT_TERMINAL_PROMPT=0`, and a 10-second timeout. Then it writes a
`run_started` event with `mode`, `commits` and `commit_check_reason`.

- If the check passes, each node ends with a commit `utux: <node> (<run id>)`.
- If it fails in `guided` mode, the run continues without commits, and the
  event says why (`commit_check_failed` or `commit_check_timeout`).
- If it fails in `auto` mode, the run does not start: the `run_started`
  event has status `refused`, and nothing else is written.

The id of the `run_started` event is the run's id, for example `e-000004`.

## Gates and pauses

Two gates of the specification fall in stages 3 to 5:

| Gate | Checked | Approves |
| --- | --- | --- |
| `method` | before `implementation` starts | the current version of `method.md` |
| `experiment_plan` | before `experiment` runs anything | the current version of `code/main.py`, the code the experiment will run; M1 has no separate plan file |

A gate is on as `oversight.gate_enabled` says: every gate in `guided` mode,
and in `auto` mode only those switched on in `utux.yaml`.

**Pausing.** At a gate with no answer, the run writes an `artifact` request
`approvals/<id>.request.json`, records an `approval_requested` event, and
stops with `RunPausedError`, whose message names the request. The lock is
released; the checkpoint of the last finished node stays. Resuming before
an answer pauses again on the same request.

**Answers.** A person writes `approvals/<id>.response.json`, with
`utux approve` ([Running a project from the command line](cli-runs.md)). When the run resumes, the answers are taken first, each
recorded as an `approval_answered` event by the person:

- `approve`: the run continues from the gate.
- `reject`, with the person's feedback: the stage that made the file runs
  again with the feedback in its input (`methodology` for the method,
  `implementation` for the experiment plan), and the gate then asks again.
  This is a route back with the finding `rejected_at_gate`, counted against
  the retry cap of that stage like any other; beyond the cap the run pauses
  with a `retry_limit` request. The feedback is in the response and in the
  `approval_answered` event.
- `edit`: the person has changed the file and names the version they saved.
  It is taken only if the file's hash is the response's
  `edited_content_hash` (otherwise `ApprovalMismatchError`, and nothing is
  recorded). The version gets its sidecar, made by the person from the
  requested version, and every artifact built from the requested version,
  directly or not, is marked `stale`. The run continues with the edited
  version.

**Budget.** When a model call is refused because the budget is exhausted,
the run writes a `budget_exhausted` request with the stage and the
`refused_event_id` of the refused call, and pauses. `approve` lets the run
continue only if a `setting_changed` event for `budget.total_usd` or the
stage's budget was written after the request: raise the budget in
`utux.yaml`, and the next `utux run` records the change and then repeats the
refused call. Before that, the run stays paused. `reject` stops the run.

**What an experiment-plan approval covers.** The request records the
execution it approves in `execution`: the image digest, the command, the
read-only paths and the limits, the timeout included. Before the experiment
runs, utux builds the same record again from `utux.yaml` and the pack's
image. If anything differs, for example a rebuilt image, a changed limit or
another pack, the approval does not cover it and the run asks again before
anything runs.

## The check after the analysis, and routing back

M1 has no reviewer agent. A deterministic check runs after the analysis
instead, as the graph's `check` node; it is not a stage, so it writes no
stage events and makes no commit.

| Finding | When | Routed back to |
| --- | --- | --- |
| `run_failed` | the execution run's exit status is not zero, or a limit stopped it | `implementation` |
| `hardcoded_metric` | the value of a result record, rounded to the decimals its tolerance implies, appears as a numeric literal in `code/main.py` | `implementation` |
| `metric_missing` | a metric that `method.md` names has no result record of the run | `methodology` |

The check for a hard-coded metric parses the code, never runs it, and
compares every int and float literal with each recorded value, both rounded
to the decimals that the record's tolerance implies (a tolerance of 0.005
gives two). It is a heuristic that catches only the plain case of a value
written into the code; a value assembled from parts, or read from a file
the code wrote, passes it. The reviewer (M3) and the negative control of
the benchmark (M4) are the stronger checks. A literal such as `1` can match
a metric whose value is 1.0; the run is then sent back, and the cap still
applies.

`method.md` names each metric on a line of exactly this form:

```text
- metric: <name>
```

The hyphen starts the line, there is one space on each side of `metric:`,
and the name is letters, digits, `_`, `.` and `-`, starting with a letter or
digit, with nothing after it. If `method.md` names no metric, or a line
looks like a metric line but is not of this form (`- Metric: r2`,
`-  metric: r2`, `- metric: r2 and auc`), the run stops before the
implementation with `MethodFormatError`, naming the line; correct
`method.md` and run again.

A route back is a `route_back` event with status `ok`, naming the stages,
the finding, the attempt and the cap; the stage runs again with the finding
as part of its input, and the stages after it run again too. Each loop, one
target stage, has the retry cap `workflow.retry_cap` of `utux.yaml`,
default 2. The route back after the
cap is a `route_back` event with status `refused` and `status_reason`
`retry_limit`, and the run pauses with a `retry_limit` request whose
`refused_event_id` names that event. `approve` allows one more route back
for that loop: the next `route_back` event shows the cap raised by one.
`reject` stops the run.

Attempts and caps are counted from the event log, not kept in the graph
state.

## Checkpoints

After every node the graph state is written to `.utux/checkpoints.sqlite`
(not in git), with `utux.core.checkpoints.StrictCheckpointSerializer`, which
stores plain data only. The state holds only ids, relative paths, hashes and
node names: for each finished node, its inputs and outputs by path and hash
and the artifact versions it made, the id of the experiment's run, and the
ids of its result records. Texts and model output stay in the files.

## Resuming

`resume_workflow` continues the last unfinished workflow run and writes a
`run_resumed` event. After a crash the project lock is left behind;
`utux unlock` removes it once its holder is no longer running.

**Only our own checkpoint.** The checkpoint's run must match a `run_started`
event of the project's log. A checkpoint copied from another project, or
from another copy of this one, is refused with `CheckpointMismatchError`, and
nothing is written.

**The files win.** For each finished node, the hashes of its inputs, as it
recorded them, are compared with the files now. The run restarts at the
earliest node whose inputs changed, and a `run_restarted` event names the
node's stage, the changed path and both hashes. For example:

- an edited `method.md` restarts the run at `implementation`;
- an edited `inputs/question.md` restarts it at `methodology`.

A file that a finished node wrote and that changed outside utux is recorded
as a new version, made by `human:unknown` from the version before it, so
that the chain of artifacts stays whole. `human:unknown` is used for nothing
else: `utux validate` reports a sidecar made by it that is not built from one
earlier version of the same artifact (`edit_actor_misused`).
