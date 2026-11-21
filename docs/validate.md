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
| 0 | The project is valid; it may have warnings |
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

A warning does not make the project invalid. It is printed after the
problems, starting with `warning:`, and counted in the last line:

```text
warning: .utux/meta/data-v001.json: path: inputs/data.csv does not exist; it is kept out of git (ADR-0009), so a clone does not have it. Its content hash is kept, so a restored file can be checked
The project is valid (12 contract files checked, 1 warning).
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
  ],
  "warnings": []
}
```

`warnings` has the same form as `problems`. `valid` depends on `problems`
only.

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
| `.utux/meta/<artifact_id>.json` | artifact metadata | The file name matches `artifact_id` (`name_mismatch`). No two sidecars share an `artifact_id` (`duplicate_id`, on the later file in name order). Every `input_artifacts` entry has a sidecar (`unknown_reference`). The current version of each path is checked against the file: see below. Any other file here is `unexpected_file` |
| `sources/*.json` | source record | No two records share a `source_id` (`duplicate_id`, on the later file in name order). Other files in `sources/` hold stored text and are not read |
| `runs/<run_id>/manifest.json` | run manifest | `run_id` matches the directory (`name_mismatch`). A run directory without a manifest is a run that has not ended and is accepted. Other files of a run are not read |
| `approvals/<id>.request.json` | approval request | The file name matches `approval_id` (`name_mismatch`). The fields follow the kind (`required_for_kind`, `not_allowed_for_kind`). A request of kind `budget_exhausted` or `retry_limit` names an event of `events.jsonl` in `refused_event_id` (`unknown_reference`): for `budget_exhausted` a `model_call` refused with `budget_exhausted`, for `retry_limit` a `route_back` refused with `retry_limit` (`wrong_refused_event`) |
| `approvals/<id>.response.json` | approval response | The file name matches `approval_id`. A request with the same id exists (`request_missing`). The response matches its request: same `approval_id`, `kind`, `artifact_id` and `content_hash`, and for an edit a different version (`differs_from_request`, `same_as_request`). `edit` answers kind `artifact` only (`edit_not_allowed_for_kind`). Any other file here is `unexpected_file` |


A missing required file has code `missing_file`. `.gitkeep` files are
ignored. Files that are not contracts, such as `code/`, `paper/` and the
outputs of runs, are not read.

A line or a source record that is itself invalid is reported once. Its id
still counts for the checks of uniqueness and of references, so that what
cites it is not reported again. A run manifest counts as present when the
file exists, whether or not it is valid.

### The current version of each path

A sidecar records the `path` of its artifact. The current version of a path
is the sidecar with the highest version number for it, the number after `-v`
in `artifact_id`. Only the current version is compared with the file, since
older versions describe content that has since been replaced. It is reported
on that sidecar:

| Problem | Field | Code |
| --- | --- | --- |
| The content hash of the file differs from `content_hash` | `content_hash` | `content_hash_mismatch` |
| Nothing exists at `path`, and git tracks it | `path` | `missing_file` |
| Nothing exists at `path`, and it is kept out of git (a warning, not a problem) | `path` | `missing_untracked_file` |
| `path` leads outside the project, through a symbolic link; it is not read | `path` | `path_outside_project` |
| A directory at `path` cannot be hashed, for example because it holds a symbolic link | `path` | `unhashable` |
| A sidecar made by `human:unknown` that is not built from exactly one earlier version of the same artifact; that maker is only for a version edited outside utux | `created_by` | `edit_actor_misused` |
| Two sidecars have the same highest version of one path; the current version is not defined and nothing is compared | `artifact_id` | `duplicate_version`, on the later file |

A file is hashed with `hash_file` and a directory with
`hash_project_directory` ([Artifact metadata](artifact-metadata.md)). A
sidecar that is invalid, or that repeats an `artifact_id`, takes no part in
this check.

### The ignore lines

A `.gitignore` that lacks any of the lines of ADR-0009, or a missing
`.gitignore`, gives the warning `gitignore_missing_lines` on `.gitignore`,
naming the lines to add. Large inputs and run outputs might otherwise be
committed. Projects created by `utux init` have the lines.

### Files kept out of git

Under ADR-0009, files under `inputs/` other than `*.md`, and everything
under `runs/<run_id>/outputs/`, are kept out of git, so a clone of a project
does not have them. When such a file is missing, `utux validate` reports the
warning `missing_untracked_file`, not a problem: a fresh clone without its
data and run outputs is valid. The sidecar and the run manifest keep the
file's content hash, so a restored file is checked against it again. A
missing file at a path that git tracks stays the problem `missing_file`.

Whether a path is kept out of git is decided by `ignored_by_git` in
`utux.workspace.layout`. It applies the lines that `utux init` writes to
`.gitignore` ([Creating a project](project.md)), so the rule and the file
cannot drift apart. A missing path counts as kept out of git when git would
ignore a file or a directory of that name, since what it was is no longer
known. The rule does not read the project's own `.gitignore`.

A command that needs a missing file kept out of git, for example a run that
reads a data file under `inputs/`, fails when it needs the file, and its
message names the file. Nothing is assumed about the content of a file that
is not there.

A `.jsonl` file is split into lines at `"\n"` only. Characters such as
U+2028 and U+0085 may appear inside text and do not end a line. A `"\r"`
before the `"\n"` is accepted.

## Not checked yet

- That the edited version named by an approval response has a sidecar.
