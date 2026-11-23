# Run manifest, approvals, source record and schema export

This page covers four file contracts and the command that exports all
schemas. The schemas are in `utux.schemas.run_manifest`,
`utux.schemas.approval` and `utux.schemas.source_record`, and follow the
[schema conventions](schema-conventions.md).

The documents give no JSON example for these four contracts, only lists in
prose. The field lists below were proposed in task M0-06b for the
maintainer's review.

In every contract below, every field is required. A field that does not
apply is `null` where the table says it may be.

## Source record

One file per source in `sources/`, named by the stem of its source id
([Stored sources](sources.md)). It says where a source came from, under
which terms it may be used, what is known about the stored text, and the
resolved bibliographic metadata (specification, section 14; RFC-001, S2;
RFC-002, section 2). The text itself is not part of the record; it is stored
beside it.

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Currently `1` |
| `source_id` | text | Identifier, such as `doi:10.0000/example`. Evidence entries in the claim ledger refer to it |
| `url` | http or https URL | The original URL |
| `licence` | text | The licence or access terms |
| `redistribution` | `full_text`, `abstract` or `none` | What the licence permits to be redistributed |
| `source_version` | `publisher`, `preprint` or `index_abstract` | Which version was retrieved |
| `retrieval_route` | code | How it was retrieved, for example `openalex` |
| `retrieved_at` | UTC timestamp | When it was retrieved |
| `stored_text` | `abstract`, `full_text` or null | Which text is stored. Null when none is |
| `text_hash` | content hash or null | Hash of the stored text |
| `extraction_method` | code or null | How the text was extracted |
| `extraction_tool_version` | text or null | The extraction tool and its version |
| `extraction_quality` | `clean`, `good`, `degraded` or null | Quality rating of the stored text |
| `storage_permitted` | boolean | Whether the licence lets utux store the text |
| `title` | text or null | The resolved title |
| `authors` | list of `family` (text or null), `given` (text or null) and `display_name` (text or null); `family` or `display_name` is given | The resolved authors, in order; empty when none were given. A display name is the whole name, never split |
| `year` | integer from 1000 to 2999, or null | The year of publication |
| `venue` | text or null | The journal, conference or repository |

When text is stored, `text_hash`, `extraction_method` and
`extraction_quality` must not be null (code `required_with_text`). When no
text is stored, the four text fields must be null (code
`not_allowed_without_text`). A source whose version is `index_abstract` cannot
have stored full text (code `stored_text_exceeds_source_version`, on
`stored_text`). A source whose `storage_permitted` is false stores no text
(code `text_not_permitted`, on `stored_text`). The bibliographic fields are
added in M2-03 for the citation existence check (ADR-0016); a resolver may
leave any of them unknown.

## Run manifest

`runs/<run_id>/manifest.json` records what is needed to repeat a run
(specification, section 7).

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Currently `1` |
| `run_id` | `r` and at least three digits | Id of the run |
| `command` | list of text, not empty | The command as a list of arguments, not one shell string |
| `parameters` | flat object | The experiment parameters |
| `config_files` | list of `path` and `hash` | The configuration files |
| `git` | `commit` (40 hexadecimal digits), `dirty` (boolean) | The commit, and whether the tree had uncommitted changes |
| `container` | `image_digest` (content hash), `locked_packages` (name to version), `rootless` (boolean) | The image, the locked package versions, and whether Docker ran rootless, which is preferred but not required |
| `datasets` | list of `name`, `version`, `obtained_from`, `files` (list of `path` and `hash`) | Dataset version, origin and input data hashes |
| `seeds` | object of name to integer | The random seeds |
| `hardware` | `cpu`, `cpu_count`, `memory_mb`, `gpu`, `cuda_version`, `driver_version` | The machine. The last three are null without a GPU |
| `models` | list of `model`, `version` (text or null), `settings` (flat object) | Models the run called, with inference settings |
| `external_services` | list of `name`, `version` | External APIs or services the run depends on |
| `outputs` | list of `path` and `hash`; may be empty | The files the run produced |
| `started_at`, `ended_at` | UTC timestamps | Start and end. The end is not before the start (code `ended_before_started`) |
| `exit_status` | integer, or null | Exit status of the command. Null only when `stopped_by` is set (code `exit_status_required`) |
| `stopped_by` | `wall_clock`, `memory`, `processes`, `disk`, `output_size`, or null | The limit that stopped the run. It may come with an exit status, as for `memory`, where Docker killed the container |

A complete manifest:

```json
{
  "schema_version": 1,
  "run_id": "r012",
  "command": [
    "python",
    "code/train.py",
    "--config",
    "code/config.yaml"
  ],
  "parameters": {
    "learning_rate": 0.001,
    "epochs": 20,
    "scheduler": "cosine",
    "augment": true
  },
  "config_files": [
    {
      "path": "code/config.yaml",
      "hash": "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41"
    }
  ],
  "git": {
    "commit": "0123456789abcdef0123456789abcdef01234567",
    "dirty": false
  },
  "container": {
    "image_digest": "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41",
    "locked_packages": {
      "numpy": "2.1.0",
      "scikit-learn": "1.5.2"
    },
    "rootless": false
  },
  "datasets": [
    {
      "name": "dataset_x",
      "version": "1.0",
      "obtained_from": "synthetic public archive",
      "files": [
        {
          "path": "inputs/dataset_x/train.csv",
          "hash": "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41"
        }
      ]
    }
  ],
  "seeds": {
    "python": 0,
    "numpy": 0
  },
  "hardware": {
    "cpu": "synthetic 8-core CPU",
    "cpu_count": 8,
    "memory_mb": 16384,
    "gpu": null,
    "cuda_version": null,
    "driver_version": null
  },
  "models": [],
  "external_services": [],
  "outputs": [
    {
      "path": "runs/r012/metrics.json",
      "hash": "sha256:abababababababababababababababababababababababababababababababab"
    }
  ],
  "started_at": "2026-11-15T10:00:00Z",
  "ended_at": "2026-11-15T10:14:30Z",
  "exit_status": 0,
  "stopped_by": null
}
```

A flat object holds only strings, numbers, booleans and null. Paths are
relative paths inside the project. With a GPU, `cuda_version` and
`driver_version` must be given (code `required_with_gpu`); without one they
must be null (code `not_allowed_without_gpu`).

## Approval request and response

The core writes `approvals/<id>.request.json` and pauses. A person answers,
and the CLI or a later interface writes `approvals/<id>.response.json`
(specification, section 7).

A request has a `kind` (ADR-0011):

| Kind | Asks about | Answers |
| --- | --- | --- |
| `artifact` | One artifact version at a gate | `approve`, `reject` or `edit` |
| `budget_exhausted` | Continuing after the budget was reached | `approve` (continue) or `reject` (stop) |
| `retry_limit` | Continuing after the retry cap was reached | `approve` (continue) or `reject` (stop) |

An approval of kind `artifact` binds to one exact version. The request names
the artifact version and the hash of its content, and the response repeats
both. If the file is edited after the request, its hash changes, and an
approval given for the old content does not carry over.

A request of the other two kinds is about no artifact. It records the stage
that was paused and the event of the refused call; after `approve`, the run
repeats that call. Continuing after `budget_exhausted` also needs the budget
to have been raised after the request, which a `setting_changed` event
records; the run checks that when it resumes (task M1-11).

Request. Every field is required; the ones marked by kind are null for the
other kinds (codes `required_for_kind` and `not_allowed_for_kind`):

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Currently `1` |
| `approval_id` | `a-` and at least six digits | Id of the approval |
| `kind` | `artifact`, `budget_exhausted` or `retry_limit` | What the request is about |
| `gate` | `idea`, `method`, `experiment_plan` or `final_manuscript`; kind `artifact` only | The gate that asks |
| `artifact_id` | artifact id; kind `artifact` only | The artifact version to approve |
| `content_hash` | content hash; kind `artifact` only | Hash of the content to approve |
| `path` | path inside the project; kind `artifact` only | The file that holds the content |
| `stage` | stage; kinds `budget_exhausted` and `retry_limit` only | The stage that was paused |
| `refused_event_id` | event id; kinds `budget_exhausted` and `retry_limit` only | The event of the refused call. `utux validate` checks that it is in `events.jsonl` (`unknown_reference`) |
| `requested_by` | actor | Who asks |
| `requested_at` | UTC timestamp | When the request was written |

A request at the method gate:

```json
{
  "schema_version": 1,
  "approval_id": "a-000007",
  "kind": "artifact",
  "gate": "method",
  "artifact_id": "method-v003",
  "content_hash": "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41",
  "path": "method.md",
  "stage": null,
  "refused_event_id": null,
  "execution": null,
  "requested_by": "agent:methodologist",
  "requested_at": "2026-11-15T10:05:00Z"
}
```

A request at the experiment-plan gate records the execution it approves (`execution`, given exactly for that gate: codes `required_for_gate` and `not_allowed_for_gate`). Before the experiment runs, utux builds the record again; any difference, such as a rebuilt image, other limits or another command, makes the approval no longer valid, and the run asks again:

```json
{
  "schema_version": 1,
  "approval_id": "a-000008",
  "kind": "artifact",
  "gate": "experiment_plan",
  "artifact_id": "code-v001",
  "content_hash": "sha256:3ee9b44b3924f2b73b8a8dddf4500a0982b82c237fc5235036252fe2a641eb41",
  "path": "code/main.py",
  "stage": null,
  "refused_event_id": null,
  "execution": {
    "image_digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "command": ["python", "code/main.py"],
    "read_only_paths": ["code", "inputs"],
    "limits": {"cpus": 2.0, "memory_mb": 4096, "gpus": 0, "disk_mb": 512,
               "max_processes": 256, "output_mb": 1024, "timeout_seconds": 3600.0}
  },
  "requested_by": "system:utux",
  "requested_at": "2026-11-15T10:05:00Z"
}
```

A request after the budget was reached:

```json
{
  "schema_version": 1,
  "approval_id": "a-000009",
  "kind": "budget_exhausted",
  "gate": null,
  "artifact_id": null,
  "content_hash": null,
  "path": null,
  "stage": "implementation",
  "refused_event_id": "e-000042",
  "execution": null,
  "requested_by": "system:utux",
  "requested_at": "2026-11-16T14:00:00Z"
}
```

Response:

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Currently `1` |
| `approval_id` | as in the request | The request this answers |
| `kind` | as in the request | What the request is about |
| `artifact_id` | as in the request; null unless kind `artifact` | The artifact version the person saw |
| `content_hash` | as in the request; null unless kind `artifact` | The hash of the content the person saw |
| `decision` | `approve`, `reject` or `edit`; `edit` for kind `artifact` only (`edit_not_allowed_for_kind`) | What the person decided |
| `answered_by` | `human:<id>` | The person. Only a person answers an approval |
| `answered_at` | UTC timestamp | When the answer was given |
| `feedback` | text or null | Remarks. Required for `reject` (code `feedback_required`) |
| `edited_artifact_id` | artifact id or null | The artifact version the person saved and approves. Given exactly when the decision is `edit` |
| `edited_content_hash` | content hash or null | Hash of the content of that version. Given exactly when the decision is `edit` |

For an edit, the person changes the file itself. The response does not carry
the content; it names the version the person saved. The two `edited_...`
fields are not null for `edit` (code `required_for_edit`) and null for every
other decision (code `not_allowed_unless_edit`).

A response to the request above:

```json
{
  "schema_version": 1,
  "approval_id": "a-000009",
  "kind": "budget_exhausted",
  "artifact_id": null,
  "content_hash": null,
  "decision": "approve",
  "answered_by": "human:alex",
  "answered_at": "2026-11-16T14:30:00Z",
  "feedback": null,
  "edited_artifact_id": null,
  "edited_content_hash": null
}
```

`check_response_matches_request(request, response, source)` compares the
four shared fields: `approval_id`, `kind`, `artifact_id` and `content_hash`.
The last two are null for the kinds that are not about an artifact, so only
an approval of kind `artifact` is bound to a content hash. Each one that differs is reported on its own field with
code `differs_from_request`. For an edit it also checks that the edited
version differs from the requested one, in id and in content hash (code
`same_as_request`).

## Exporting the schemas

```bash
uv run utux schema export schemas/
```

writes one JSON Schema file per contract into the directory, and prints the
paths:

```text
project_config.schema.json      artifact_metadata.schema.json
event.schema.json               claim_ledger_entry.schema.json
result_record.schema.json       run_manifest.schema.json
approval_request.schema.json    approval_response.schema.json
source_record.schema.json       gold_item.schema.json
metrics.schema.json             annotation_pool.schema.json
annotation_batch.schema.json    extraction_work.schema.json
labelling_work.schema.json      adjudication.schema.json
reference_claims.schema.json
```

The directory is created if it does not exist. Existing schema files are
replaced, through the atomic writer; other files are left alone. The output
is the same for the same version of utux.

A JSON Schema states the fields, their types and the closed sets. It does
not state the rules between fields, such as "a verified claim needs
evidence". Those are checked only by utux itself, so a file that passes the
JSON Schema can still be refused by utux. Every exported schema says so in
its description: "utux applies further rules between fields; passing this
schema is necessary but not sufficient."

The tests check each exported file with a JSON Schema validator: the file
is itself a valid schema, and every valid fixture of its contract passes it.
