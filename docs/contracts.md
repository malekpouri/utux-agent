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

One file per source in `sources/`. It says where a source came from, under
which terms it may be used, and what is known about the stored text
(specification, section 14; RFC-001, S2; RFC-002, section 2). The text
itself is not part of the record.

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

When text is stored, `text_hash`, `extraction_method` and
`extraction_quality` must not be null (code `required_with_text`). When no
text is stored, the four text fields must be null (code
`not_allowed_without_text`). A source whose version is `index_abstract` cannot
have stored full text (code `stored_text_exceeds_source_version`, on
`stored_text`).

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
| `container` | `image_digest` (content hash), `locked_packages` (name to version) | The image and the locked package versions |
| `datasets` | list of `name`, `version`, `obtained_from`, `files` (list of `path` and `hash`) | Dataset version, origin and input data hashes |
| `seeds` | object of name to integer | The random seeds |
| `hardware` | `cpu`, `cpu_count`, `memory_mb`, `gpu`, `cuda_version`, `driver_version` | The machine. The last three are null without a GPU |
| `models` | list of `model`, `version` (text or null), `settings` (flat object) | Models the run called, with inference settings |
| `external_services` | list of `name`, `version` | External APIs or services the run depends on |
| `outputs` | list of `path` and `hash`; may be empty | The files the run produced |
| `started_at`, `ended_at` | UTC timestamps | Start and end. The end is not before the start (code `ended_before_started`) |
| `exit_status` | integer | Exit status of the command |

A flat object holds only strings, numbers, booleans and null. Paths are
relative paths inside the project. With a GPU, `cuda_version` and
`driver_version` must be given (code `required_with_gpu`); without one they
must be null (code `not_allowed_without_gpu`).

## Approval request and response

The core writes `approvals/<id>.request.json` and pauses. A person answers,
and the CLI or a later interface writes `approvals/<id>.response.json`
(specification, section 7).

An approval binds to one exact version. The request names the artifact
version and the hash of its content, and the response repeats both. If the
file is edited after the request, its hash changes, and an approval given
for the old content does not carry over.

Request:

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Currently `1` |
| `approval_id` | `a-` and at least six digits | Id of the approval |
| `gate` | `idea`, `method`, `experiment_plan` or `final_manuscript` | The gate that asks |
| `artifact_id` | artifact id | The artifact version to approve |
| `content_hash` | content hash | Hash of the content to approve |
| `path` | path inside the project | The file that holds the content |
| `requested_by` | actor | Who asks |
| `requested_at` | UTC timestamp | When the request was written |

Response:

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Currently `1` |
| `approval_id` | as in the request | The request this answers |
| `artifact_id` | as in the request | The artifact version the person saw |
| `content_hash` | as in the request | The hash of the content the person saw |
| `decision` | `approve`, `reject` or `edit` | What the person decided |
| `answered_by` | `human:<id>` | The person. Only a person answers an approval |
| `answered_at` | UTC timestamp | When the answer was given |
| `feedback` | text or null | Remarks. Required for `reject` (code `feedback_required`) |
| `edited_artifact_id` | artifact id or null | The artifact version the person saved and approves. Given exactly when the decision is `edit` |
| `edited_content_hash` | content hash or null | Hash of the content of that version. Given exactly when the decision is `edit` |

For an edit, the person changes the file itself. The response does not carry
the content; it names the version the person saved. The two `edited_...`
fields are not null for `edit` (code `required_for_edit`) and null for every
other decision (code `not_allowed_unless_edit`).

`check_response_matches_request(request, response, source)` compares the
three shared fields. Each one that differs is reported on its own field with
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
source_record.schema.json
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
