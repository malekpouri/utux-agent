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
| `model` | text or null | The model id, for a model call |
| `prompt_version` | text or null | The prompt version, for a model call |
| `tool_version` | text or null | The tool version, for a tool call |
| `input_hash`, `output_hash` | content hash or null | Hash of what was sent and of what came back. The content itself is not stored |
| `tokens_in`, `tokens_out` | integer, 0 or more, or null | Token counts |
| `cost_usd` | number, 0 or more, or null | Cost. Null means the cost is not known; it is never guessed |
| `duration_ms` | integer, 0 or more, or null | How long it took |
| `status` | `ok` or `error` | Whether it succeeded |
| `retry_reason` | text or null | Why a call was repeated |
| `escalated_from` | `light`, `standard`, `strong` or null | The tier a call was moved up from |
| `artifacts` | list of artifact ids; may be empty | The artifact versions the event produced or concerns |

Event types: `project_created`, `stage_start`, `stage_end`, `model_call`,
`tool_call`, `code_execution`, `verification_result`, `approval_requested`,
`approval_answered`, `budget_warning`, `setting_changed`, `error`. An event
with any other type is rejected.

A `parent_id` must name an earlier event. An event that names itself has code
`self_reference`; one that names a later event has code `parent_not_earlier`.

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
- The timestamp comes from the clock at the time of the call, in UTC with
  millisecond precision.
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
joined to the broken line. utux has no repair command yet; the damaged line
has to be removed by a person, outside utux.
