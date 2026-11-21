# How a run works

A run takes a project through stages 3 to 5 of the specification:
methodology, implementation, and experiment and analysis. It is the graph in
`utux.core.workflow`, built on LangGraph, which no module outside `utux.core`
imports. `run_workflow(project, services)` starts a run and
`resume_workflow(project, services)` continues one; the command line for
them is task M1-14. Both hold the project lock and record setting changes
first ([Creating a project](project.md)).

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
| `methodology` | `methodology` | `inputs/*.md` | `method.md`, from a model |
| `implementation` | `implementation` | `method.md` | `code/main.py`, from a model |
| `experiment` | `experiment` | `code/main.py` | `runs/<run>/`: the run in the sandbox, its manifest and its result records ([Result records from a run](results.md)) |
| `analysis` | `experiment` | the run's manifest and records | `results.md`, built from the result records, not by a model |

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
with the run's id. In M1 the prompts are placeholders (`skeleton@1`); real
agents and prompts are task M1-13.

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

## Checkpoints

After every node the graph state is written to `.utux/checkpoints.sqlite`
(not in git), with `utux.core.checkpoints.StrictCheckpointSerializer`, which
stores plain data only. The state holds only ids, relative paths, hashes and
node names: for each finished node, its inputs and outputs by path and hash
and the artifact versions it made, the id of the experiment's run, and the
ids of its result records. Texts and model output stay in the files.

## Resuming

`resume_workflow` continues the last unfinished workflow run and writes a
`run_resumed` event. After a crash the project lock is left behind; remove
`.utux/lock` once you have checked that nothing is still running (task M1-14
adds `utux unlock` for this).

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
