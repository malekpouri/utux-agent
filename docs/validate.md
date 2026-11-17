# Validating a project

```bash
uv run utux validate [DIRECTORY] [--json]
```

`utux validate` reads every contract file of a project, checks it against
its schema, and checks the rules that span lines and files. It reports every
problem it finds, not only the first, and changes nothing. `DIRECTORY`
defaults to the current directory.

| Exit code | Meaning |
| --- | --- |
| 0 | The project is valid |
| 1 | At least one problem was found |
| 2 | The command was called wrongly |

## Output

One line per problem, naming the file, the field and the reason:

```text
utux.yaml: colour: unknown key
results.jsonl:2: id: R0042 is already used on line 1
claims.jsonl: <document>: the file is missing
3 problems found.
```

A file with one record per line (`.jsonl`) is named with its line number.
`<document>` stands for the whole file. Paths are relative to the project.

If a file was written by a newer version of utux, its problem says
"newer schema version", and the output ends with a line saying that the
project was written by a newer version of utux.

### `--json`

With `--json` the command prints only a JSON report:

```json
{
  "schema_version": 1,
  "valid": false,
  "newer_schema_version": false,
  "files_checked": 9,
  "problems": [
    {"file": "results.jsonl", "line": 2, "field": "id",
     "code": "duplicate_id", "reason": "R0042 is already used on line 1"}
  ]
}
```

`line` is null for a file that is not read line by line. `code` is stable
and meant for programs; `reason` is meant for people. The report holds no
absolute path.

## What is checked

| Files | Schema | Further checks |
| --- | --- | --- |
| `utux.yaml` | project configuration | Required |
| `events.jsonl` | event, per line | Required. A last line without its newline is an interrupted write (`incomplete_line`). Event ids increase from line to line (`event_id_not_increasing`). The first event is `project_created` (`first_event_not_project_created`). Every `parent_id` names an earlier event in the log (`unknown_reference`) |
| `events.jsonl.fragment-*` | none | Side files of `utux log repair`. Each is recorded by a `log_repaired` event, and each such event's file exists with the recorded length and hash. See [the event log](event-log.md#side-files-and-utux-validate) |
| `claims.jsonl` | claim ledger entry, per line | Required; may be empty. Ids are unique (`duplicate_id`). Every `claim` evidence id is a claim in the file, every `result_record` evidence id is a record in `results.jsonl`, and every `source` evidence `source_id` has a source record in `sources/` (`unknown_reference`) |
| `results.jsonl` | result record, per line | Required; may be empty. Ids are unique (`duplicate_id`). Every `run_id` has `runs/<run_id>/manifest.json` (`unknown_reference`) |
| `.utux/meta/<artifact_id>.json` | artifact metadata | The file name matches `artifact_id` (`name_mismatch`). Any other file here is `unexpected_file` |
| `sources/*.json` | source record | No two records share a `source_id` (`duplicate_id`, on the later file in name order). Other files in `sources/` hold stored text and are not read |
| `runs/<run_id>/manifest.json` | run manifest | `run_id` matches the directory (`name_mismatch`). A run directory without a manifest is a run that has not ended and is accepted. Other files of a run are not read |
| `approvals/<id>.request.json` | approval request | The file name matches `approval_id` (`name_mismatch`) |
| `approvals/<id>.response.json` | approval response | The file name matches `approval_id`. A request with the same id exists (`request_missing`). The response matches its request: same `approval_id`, `artifact_id` and `content_hash`, and for an edit a different version (`differs_from_request`, `same_as_request`). Any other file here is `unexpected_file` |


A missing required file has code `missing_file`. `.gitkeep` files are
ignored. Files that are not contracts, such as `code/`, `paper/` and the
outputs of runs, are not read.

A line or a source record that is itself invalid is reported once. Its id
still counts for the checks of uniqueness and of references, so that what
cites it is not reported again. A run manifest counts as present when the
file exists, whether or not it is valid.

A `.jsonl` file is split into lines at `"\n"` only. Characters such as
U+2028 and U+0085 may appear inside text and do not end a line. A `"\r"`
before the `"\n"` is accepted.

## Not checked yet

- That the content hash of a sidecar matches the file it describes, and that
  `input_artifacts` name existing sidecars. The sidecar does not yet record
  the path of its artifact; that is planned for M1.
- That the edited version named by an approval response has a sidecar.
