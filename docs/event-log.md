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
`log_repaired`. An event with any other type is rejected.

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
| `setting_changed` | `key` (non-empty text), `old_value`, `new_value`; all required |
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
handle opened for appending only, and reads through a read-only handle.

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

A last line without its newline is never dropped, completed or overwritten.
`append()` refuses to write to such a log, because the new event would be
joined to the broken line.

The log is never repaired automatically. `utux log repair` (task M0-08b) will
move the fragment to a side file, restore the log to its last complete
event and record the repair as a `log_repaired` event. Until that task is
done, the damaged line has to be removed by a person, outside utux.
