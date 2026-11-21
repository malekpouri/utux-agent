# Events and the event log

`events.jsonl` records what happened in a project: one event per line. It is
append-only and is the public interface for dashboards and audit
(specification, section 7). The event schema is `utux.schemas.event.Event`;
it follows the [schema conventions](schema-conventions.md). The log is
`utux.events.log.EventLog`.

## Event

A stored event states every field. A field that does not apply is `null`.

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of this schema. Currently `1` |
| `event_id` | `e-` and at least six digits, for example `e-000913` | Unique and increasing within a project |
| `run_id` | text or null | The run the event belongs to |
| `request_id` | text or null | The request the event belongs to |
| `parent_id` | event id or null | The earlier event that caused this one |
| `ts` | UTC timestamp, ISO 8601, ending in `Z` | When the event was recorded |
| `actor` | `agent:<role>`, `human:<id>` or `system:<component>` | Who acted |
| `stage` | a stage or null | The pipeline stage |
| `type` | see below | What happened |
| `model` | text or null | The model id. Required for a `model_call` (code `model_required`) |
| `prompt_version` | text or null | The prompt version, for a model call |
| `tool_version` | text or null | The tool version, for a tool call |
| `input_hash`, `output_hash` | content hash or null | Hash of what was sent and of what came back. The content itself is not stored |
| `tokens_in`, `tokens_out` | integer, 0 or more, or null | Token counts |
| `cost_usd` | number, 0 or more, or null | Cost. Null means the cost is not known; it is never guessed |
| `duration_ms` | integer, 0 or more, or null | How long it took |
| `status` | `ok`, `error` or `refused` | How it ended. `refused` means utux itself declined the action |
| `status_reason` | code or null | A stable machine code that explains a status other than `ok`. Null exactly when the status is `ok` |
| `retry_reason` | code or null | A machine code for why a call was repeated |
| `escalated_from` | `light`, `standard`, `strong` or null | The tier a call was moved up from |
| `data` | flat object; `{}` when empty | Details specific to the event type. See below |
| `artifacts` | list of artifact ids; may be empty | The artifact versions the event produced or concerns |

Event types: `project_created`, `stage_start`, `stage_end`, `model_call`,
`tool_call`, `code_execution`, `verification_result`, `approval_requested`,
`approval_answered`, `budget_warning`, `setting_changed`, `error`,
`log_repaired`, `run_started`, `run_resumed`, `run_restarted`, `route_back`,
`lock_removed`. An event with any other type is rejected.

A `parent_id` must name an earlier event. An event that names itself has code
`self_reference`; one that names a later event has code `parent_not_earlier`.

### Status and reason

`status` is `ok`, `error` or `refused`. A refused action is one that utux
itself declined, for example a call to an external provider under
`local_only` or a call after the budget is exhausted.

`status_reason` is a stable machine code, such as `model_timeout` or
`budget_exhausted`: lower-case letters, digits, `-` and `_`, starting with a
letter. It is required for `error` and `refused` (code
`status_reason_required`) and must be null for `ok` (code
`status_reason_not_allowed`). Both problems are reported on `status_reason`.

No free-text error message is stored anywhere in an event. `retry_reason` is
a machine code as well.

### `data`

`data` holds the details that are specific to an event type. It is a flat
object: every value is a string, a number, a boolean or null. A nested value
is reported on its own key with code `not_scalar`.

Each event type defines its keys. A missing key is reported as
`data.<key>` with code `missing`, and a key the type does not define as
`data.<key>` with code `unknown_key`.

| Type | Keys of `data` |
| --- | --- |
| `project_created` | `utux_version` (non-empty text): the version of utux that created the project; required |
| `setting_changed` | `key` (non-empty text), the dotted key of the setting, such as `budget.total_usd`; `old_value` and `new_value`, null where the key was absent; all required. Written with the actor `system:utux` by a command that writes to the project, for each change of `utux.yaml` since the last snapshot ([Creating a project](project.md)) |
| `model_call` | `provider` (non-empty text), `is_external` (true or false); both required. See [logged model calls](model-calls.md) |
| `budget_warning` | `spent_usd`, the known cost so far, and `total_usd`, the budget it was compared with (numbers, 0 or more; codes `float_type` and `greater_than_equal`); both required. The event's `stage` names the stage whose budget is exhausted, null for the project budget. See [cost and budget](cost.md) |
| `log_repaired` | `fragment_file` (non-empty text), `fragment_hash` (content hash), `fragment_bytes` (whole number, 0 or more); all required |
| `stage_start`, `stage_end` | `node` (non-empty text): the node of the workflow, `methodology`, `implementation`, `experiment` or `analysis`; required. The event's `stage` is the node's stage, `experiment` for the analysis; `stage_end` lists the artifacts the node made in `artifacts`. See [How a run works](run.md) |
| `run_started` | `mode` (non-empty text, `guided` or `auto`), `commits` (true or false), `commit_check_reason` (a code such as `commit_check_failed` or `commit_check_timeout`, or null); all required. Its `event_id` is the run's id, the `run_id` of every later event of the run (ADR-0010) |
| `approval_requested` | `approval_id` (non-empty text), `kind` (non-empty text: `artifact`, `budget_exhausted` or `retry_limit`), `gate` (a gate, or null for the other kinds); all required. `artifacts` names the version asked about |
| `approval_answered` | `approval_id` and `decision` (`approve`, `reject` or `edit`), both non-empty text, and `feedback`, the person's feedback as text, or null; all required. The actor is the person who answered |
| `route_back` | `from_stage` and `to_stage` (non-empty text, stages), `finding` (a code: `run_failed`, `hardcoded_metric`, `metric_missing` or `rejected_at_gate`), `attempt` and `cap` (whole numbers, 0 or more); all required. Status `ok` for a route back within the cap; `refused` with `status_reason` `retry_limit` beyond it. See [How a run works](run.md) |
| `lock_removed` | `pid` (whole number, 0 or more), `host`, `command` and `started_at` (non-empty text): the holder named by the lock file that `utux unlock` removed; all required. The actor is `system:utux` |
| `code_execution` | `execution_run_id` (`r` and at least three digits), `image_digest` (content hash), `exit_status` (whole number or null) and `stopped_by` (`wall_clock`, `memory`, `processes`, `disk`, `output_size` or null); all required. One event per execution run, written by the `experiment` node when the run ends and before it is recorded; also for a run that could not start. `stage` is `experiment`, `input_hash` the hash of the executed code, `output_hash` the hash of `metrics.json` or null, `duration_ms` the run's duration or null. Status `ok` for exit status 0 with no limit; otherwise `error`, with `status_reason` `nonzero_exit`, `limit_<limit>` (for example `limit_wall_clock`, `limit_memory`, `limit_output_size`), `executor_unavailable` or `image_mismatch`. See [How a run works](run.md) |
| `run_resumed` | none. Written when a run continues from its checkpoint |
| `run_restarted` | `changed_path` (non-empty text), `expected_hash` and `actual_hash` (content hash or null: null when the file is new, or gone); all required. The event's `stage` is the stage of the node the run restarts at |
| every other type | none; `data` must be `{}` until the task that emits the type defines its keys |

Message content and source text never go into `data`. An event records what
was sent and received only through `input_hash` and `output_hash`.

## The log

```python
log = EventLog(project_dir / "events.jsonl")
stored = log.append(
    NewEvent(actor="system:utux", type=EventType.PROJECT_CREATED, status=EventStatus.OK)
)
for event in log:
    ...
```

`NewEvent` has every field of an event except the three the log sets:
`schema_version`, `event_id` and `ts`.

### Appending

- `append()` writes exactly one line, ending in a newline, with a single
  write, and forces it to disk before it returns.
- The log gives out the event ids. `append()` holds an exclusive lock on the
  file while it reads the last id and writes the next event, so ids are
  unique and increasing also when several threads or processes append to one
  log. The lock is `flock`, which exists on POSIX systems only.
- The timestamp is read from the clock after the lock is acquired, in UTC
  with millisecond precision, so `ts` never decreases as `event_id`
  increases.
- An event that breaks a rule of the schema is refused with a
  `ContractValidationError`, and nothing is written.
- Ids keep growing past six digits: `e-999999` is followed by `e-1000000`.
  Ids are compared as numbers.
- The file is created by the first `append()`. Its directory must exist.

### Append-only

The log has no operation that rewrites, reorders or removes a line, and it
never opens the file in a mode that can truncate it: it writes through a
handle opened for appending only, and reads through a read-only handle. The
one exception is `utux log repair`, described below, which removes an
incomplete fragment that is not a line, and only when a person asks for it.

Append-only is enforced by utux, not by the file system, so the log is not
tamper-proof (specification, section 7).

### Reading

Iterating over the log yields the events in file order. The file is read in
pieces, so a long log is not loaded into memory. A log file that does not
exist has no events.

Reading stops with an error at the first line that is not sound. The events
before that line are still delivered.

| Situation | Error |
| --- | --- |
| The last line has no newline: a write was interrupted | `EventLogCorruptError`, with the path and the line number |
| An event id is not greater than the one before | `EventLogCorruptError` |
| A line is not a valid event | `ContractValidationError`, with the source `path:line`, the field and the reason |

### After a crash

A last line without its newline is never dropped, completed or overwritten
automatically. `append()` refuses to write to such a log, because the new
event would be joined to the broken line, and reading and `utux validate`
report it.

A person repairs the log with:

```bash
uv run utux log repair [DIRECTORY]
```

If the project lock was left by a process on this host that is no longer
running, as after a crash, the command first removes it, as `utux unlock`
does; a lock whose holder is running or on another host is refused. The
`lock_removed` event is appended once the log ends with a complete line,
before the `log_repaired` event.

The command, while it holds the lock of the log:

1. checks that the last complete line is a valid event, and refuses with
   nothing changed if it is not;
2. saves the incomplete fragment byte for byte to
   `events.jsonl.fragment-<time>` beside the log, for example
   `events.jsonl.fragment-20261116T110712.125Z`, and refuses with nothing
   changed if that file already exists or cannot be written;
3. removes the fragment from the end of the log, so that the log ends with
   its last complete event;
4. appends a `log_repaired` event with the side file's name, the fragment's
   hash and its length in bytes.

Complete lines are never changed. A log whose last line is complete is left
alone, and the command says that there is nothing to repair. The side file
is kept for audit; utux does not delete it.

If the fragment was the whole log, as when a crash interrupts the very first
event, the repaired log starts with `log_repaired`, and `utux validate`
reports that the first event is not `project_created`.

### An interrupted repair

If the process is stopped between steps 3 and 4, the log is complete but
has no `log_repaired` event, and the side file holds the fragment.
`utux validate` reports the side file as `unrecorded_fragment`. Running
`utux log repair` again completes the repair: on a log whose last line is
complete, every side file that no `log_repaired` event records gets its
missing event, in name order, and the command says that an interrupted
repair was completed. If every side file is recorded, nothing changes.

### Side files and `utux validate`

`utux validate` checks the side files and the `log_repaired` events against
each other, in both directions:

- every `events.jsonl.fragment-*` file is named by a `log_repaired` event
  (`unrecorded_fragment`, on the side file);
- every `log_repaired` event names a side file beside the log
  (`invalid_fragment_file`) that exists (`missing_fragment_file`) and whose
  length and hash match `fragment_bytes` and `fragment_hash`
  (`fragment_mismatch`). These are reported on the event's line.
