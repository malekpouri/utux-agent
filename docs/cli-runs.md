# Running a project from the command line

Four commands drive a run: `utux run`, `utux approve`, `utux status` and
`utux unlock` (task M1-14). How a run itself works is in
[How a run works](run.md).

**Each refuses a project that fails `utux validate`**, says so, and changes
nothing; run `utux validate DIR` to see every problem. Warnings do not
count. One problem does not count either: `content_hash_mismatch`, a file
changed since its current version was recorded. That is an edit, which
`utux run` records as a new version (files win) and `utux approve ... edit`
names as the person's version; `utux validate` still reports it.

## utux run

```text
utux run [DIR] [--from STAGE] [--to STAGE]
```

Without `--from`, `utux run` resumes the last run if it is unfinished, and
otherwise starts a new one. The stages of a run are `methodology`,
`implementation` and `experiment`; the analysis and the check after it
belong to `experiment`.

- `--to STAGE` stops the run after that stage. It is not finished, and a
  later `utux run` continues it. A run already past the stage is refused.
  `--to experiment` runs to the end.
- `--from STAGE` starts a new run at that stage, whatever the state of the
  last run; an unfinished one is left as it is, and a later `utux run`
  resumes the new one. The stage works from the current versions of the
  files the earlier stages made: `method.md` for `implementation`, and
  `method.md` and `code/main.py` for `experiment`. A file with no recorded
  version, or a stale one, is refused before anything is written; a file
  changed by hand since its version is first recorded as a new version made
  by `human:unknown`, as on resume.

The command prints how the run ended and the known cost against the budget:

- finished: `Run e-000004 finished, with 1 result record.`
- stopped after `--to`: `Run e-000004 stopped after methodology, as --to asked; utux run DIR continues it.`
- paused at a gate, a budget or the retry cap: the message names the
  request and the command to answer it, `utux approve DIR a-000001
  approve|reject|edit [--feedback TEXT]`.
- a rejected budget or retry pause stops the run for good; the command
  fails and suggests `utux run DIR --from methodology`.

Any other failure prints `error: ...`. The exit status is 0 when the run
completed (finished, or stopped after `--to` as asked), 1 on an error, and 3
when it paused for an approval ([How a run works](run.md#exit-status)).

`utux run` uses the provider of the project's profile, the Docker sandbox,
and the image and prompts of the project's domain pack. In M1 the packs are
the `packs/` directory of the utux source tree, so `utux run` works from a
checkout of the repository installed with `uv sync`. The pack's image must
be built and recorded (`utux image build`), and Docker must be reachable:
it is asked whether it runs rootless before the run starts.

## utux approve

```text
utux approve [DIR] APPROVAL_ID approve|reject|edit [--feedback TEXT] [--by ID]
```

The command writes `approvals/<id>.response.json` under the project lock;
the run takes the answer when it resumes. It does not write an event: the
`approval_answered` event is written by the run when it takes the answer.

- `--by ID` is the person, recorded as `human:<ID>`: lower-case letters,
  digits, `_`, `.` and `-`. The default is the login name. `unknown` is
  refused, since `human:unknown` stands for edits made outside utux. The
  command prints the id it recorded. **This id stays in the project**: it is
  in the response file and in the run's events, and it is shared with
  everyone the project is shared with through git. Set it with `--by` if
  the login name should not be shared.
- `approve` and `reject` are about the version the request names. If the
  file changed since the request, they are refused: answer with `edit` to
  take the file as it is, or undo the change.
- `reject` needs `--feedback`. For a file, the stage that made it runs again
  with the feedback; for a budget or retry pause, the run stops.
- `edit`: save your change to the file first. The response names the saved
  file as the next version of the artifact, for example `method-v002`, with
  its content hash; the run records that version, made by you, when it
  resumes. An unchanged file is refused, and so is `edit` for a budget or
  retry pause, which is not about a file.
- A request is answered once; a second answer is refused.

## utux status

```text
utux status [DIR]
```

Reads the project and writes nothing; it does not take the project lock, so
it can be read while a run holds it. It shows:

- the last run, its mode and whether it commits, and where it is: running
  (a live `run` process holds the lock), paused at a request, paused with
  the request answered, stopped by a rejection, not finished, or finished;
- the stage and node that started last, and whether that node finished;
  for a run whose last event is an error, its reason and, for an answer that
  was not valid, the trace that keeps the answer's raw text;
- every pending request: an answered one is marked, and is taken when the
  run resumes. Beside an experiment-plan request, the execution it
  approves: command, image digest, read-only paths and limits, timeout
  included. The limits are those that apply, the executor's defaults where
  `utux.yaml` sets none; only a request written before this was recorded
  shows `not set`;
- the last execution run, its exit status and the limit Docker reported, if
  any. For exit status 137 with no reported limit, a note says that the
  process was killed and that this is often the memory limit. The note is
  only shown; the run manifest names no limit Docker did not report;
- the known cost against the budget, as in `utux cost`;
- the project lock: not held, held by the run, held by another command,
  left by a process that is no longer running, or held on another host.

```text
Run e-000004 (guided mode, commits on): paused at a-000002, waiting for an answer
Stage: implementation (node implementation, finished)
Pending approvals:
  a-000002: experiment_plan gate, code/main.py (code-v001, sha256:...)
    command: python code/main.py
    image: sha256:...
    read-only paths: code, inputs
    limits: cpus 2, memory 4096 MB, gpus 0, disk 1024 MB, processes 256, output 100 MB, timeout 3600 s
Known cost: 0.0042 USD of a budget of 5 USD (4.9958 USD left)
Lock: not held
```

## utux unlock

```text
utux unlock [DIR]
```

Removes `.utux/lock` only if its holder is a process on this host that is
no longer running. The removal is recorded first, as a `lock_removed` event
that names the holder ([The event log](event-log.md)), and the file is then
removed. It is refused, and the lock left, when there is no lock, when the
lock cannot be read, when its holder is on another host (which cannot be
checked from here), and when its holder is still running.

After a crash the event log can also end with an incomplete line. The
project then fails `utux validate`, so `utux unlock` refuses; run
`utux log repair` instead. It makes the same check as `utux unlock`: if the
lock's holder is a process on this host that is no longer running, it
removes the lock, repairs the log, and appends `lock_removed` and then
`log_repaired`. One `utux log repair` recovers the project. A holder that
is running or on another host is refused, as by every command.
