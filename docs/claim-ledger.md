# Claim ledger and result records

The claim ledger, `claims.jsonl`, holds one line per atomic scientific claim
with its verdict and enough to audit it. Result records, `results.jsonl`,
hold every computed value with what gives it meaning. The schemas are
`utux.schemas.claim_ledger.ClaimLedgerEntry` and
`utux.schemas.result_record.ResultRecord`; both follow the
[schema conventions](schema-conventions.md).

These schemas describe what a stored entry may hold. They contain no
verification logic. Which status a claim gets is decided only by the
deterministic rules of RFC-001, which are built in milestone M2.

## How the ledger is stored

`claims.jsonl` holds the current state: one line per claim. When a claim
changes, the file is replaced by an atomic write. It is not an append-only
log. The history of a claim lives in the events (`events.jsonl`), in the
trace files under `verification/` and in git.

## Ledger entry

The fields are those of RFC-001, section 6, for every claim type. Every
field is required; a field that does not apply is `null`.

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of this schema. Currently `1` |
| `id` | `C` and at least three digits, for example `C031` | Id of the claim |
| `type` | `literature`, `result` or `derived` | Where the claim's support comes from |
| `kind` | `finding`, `quantitative`, `method`, `definition` or `background` | The kind of assertion |
| `text` | text | The claim |
| `span` | `file`, `start`, `end` | Where the claim sits: a path inside the project and character offsets, with `end` after `start` |
| `status` | see below | The verdict. Always the final, usable value |
| `confidence` | `high`, `medium` or `low` | Ordinal level. Always the final, usable value |
| `needs_human` | boolean | Whether the claim goes to human review |
| `reasons` | list of reasons; may be empty | Machine-readable causes of the verdict |
| `evidence` | list of evidence entries; may be empty | See below |
| `verified_by` | list | Each item is a check with its version, such as `support_check@1`, or `human:<id>`. Empty only for an `unverified` claim |
| `check_id` | `k-` and at least six digits, or null | The check run that set the verdict. Null only for an `unverified` claim |
| `trace` | path inside the project, or null | The full record of that run |
| `claim_hash` | content hash | Hash of the claim text and its source ids |
| `checked_at` | UTC timestamp or null | When the check ran. Null only for an `unverified` claim |
| `human` | object or null | The human review. See below |

### Human review

`status` and `confidence` are always the final, usable values. Code that
asks whether a claim may be used reads them and nothing else.

A review is pending when `needs_human` is true and `human` is null.

When a person has reviewed the claim, `human` holds:

| Field | Form | Meaning |
| --- | --- | --- |
| `reviewer` | `human:<id>` | The person |
| `decision` | a status | The status the person set |
| `note` | text or null | The person's note |
| `reviewed_at` | UTC timestamp | When the review was made |
| `machine_status` | a status | The status the machine had set before the review |
| `machine_confidence` | a confidence level | The confidence the machine had set |

After a review, `status` equals `human.decision` and the reviewer is listed
in `verified_by`. The machine verdict is kept in `machine_status` and
`machine_confidence`.

### Closed sets

All of these are taken from RFC-001. A value outside a set is rejected.

| Set | Values |
| --- | --- |
| Status | `verified`, `partially_supported`, `contradicted`, `insufficient_evidence`, and `unverified` for a claim not yet checked |
| Confidence | `high`, `medium`, `low` |
| Passage-level agreement label | `entails`, `partial`, `neutral`, `contradicts` |
| Source-level label | the four agreement labels, and `conflicting` |
| Scope flag, with its severity | `direction_mismatch`, `causal_overreach`, `magnitude_mismatch` (critical); `overgeneralisation`, `metric_mismatch` (major); `certainty_escalation`, `missing_comparator` (minor) |
| Reason | the seven scope flags, and `no_source`, `no_text`, `no_evidence_found`, `assessor_disagreement`, `conflict_within_source`, `conflict_across_sources`, `citation_not_supporting`, `second_assessor_unavailable`, `degraded_source_text` |
| Checked text | `abstract`, `full_text` |
| Extraction quality | `clean`, `good`, `degraded` |

`verified` means supported by the evidence that was checked. It does not
mean the claim has been proven true.

### Evidence entries

Each entry has an `evidence_type`.

| `evidence_type` | For claims of type | Fields |
| --- | --- | --- |
| `source` | `literature` | `source_id`, `passage_id`, `offsets` (start and end), `quote`, `checked_text`, `extraction_quality`, `primary_label`, `secondary_label` (a source-level label, or null when the independent assessment did not run), `scope_flags` |
| `result_record` | `result` | `id`, the id of a result record |
| `claim` | `derived` | `id`, the id of a claim it follows from |

A scope flag entry has `flag`, `severity`, `claim_slot` and `evidence_slot`.

For a `source` entry, `quote` is the quote that decides the primary label.
For a `conflicting` source it is the contradicting passage; the trace holds
every passage with its label.

### Rules between fields

Each rule is reported on the field to change.

| Rule | Field | Code |
| --- | --- | --- |
| `high` and `medium` confidence require the status `verified` | `confidence` | `confidence_requires_verified` |
| A claim that is `verified`, `partially_supported` or `contradicted` has at least one evidence entry | `evidence` | `evidence_required` |
| A claim whose status is not `unverified` has a check id and a check time | `check_id`, `checked_at` | `check_required` |
| A claim whose status is not `unverified` lists at least one check or person | `verified_by` | `verified_by_required` |
| After a review, the status is the human decision | `status` | `status_differs_from_human_decision` |
| After a review, the reviewer is listed in `verified_by` | `verified_by` | `human_reviewer_missing` |
| The machine confidence follows the same rule as the confidence | `human.machine_confidence` | `confidence_requires_verified` |
| A claim takes only the evidence type of its claim type | `evidence.<n>.evidence_type` | `evidence_type_mismatch` |
| A derived claim cannot follow from itself | `evidence.<n>.id` | `self_reference` |
| A scope flag has the severity RFC-001 gives it | `evidence.<n>.scope_flags.<m>.severity` | `severity_mismatch` |
| The end offset of a quote is after its start | `evidence.<n>.offsets` | `offsets_not_increasing` |
| The end of the span is after its start | `span.end` | `span_end_not_after_start` |
| `span.file` and `trace` are relative paths inside the project | the field | `not_relative_path` |

Which confidence a verified claim gets, and when a derived claim may be
verified, are rules of the verification logic in M2 and are not checked by
the schema.

## Result record

A number is never stored bare. Every field is required; `model` and `split`
may be null, for a value that belongs to no model or split, such as a
statistic of a dataset.

| Field | Form | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Version of this schema. Currently `1` |
| `id` | `R` and at least three digits, for example `R0042` | Id of the record |
| `metric` | text | What was measured |
| `value` | number | The value |
| `unit` | text | The unit of the value |
| `dataset` | text | The dataset |
| `model` | text or null | The model |
| `split` | text or null | The split of the dataset |
| `run_id` | `r` and at least three digits, for example `r012` | The run that produced the value, as in its run manifest |
| `source` | path inside the project | The file that holds the value |
| `tolerance` | number, 0 or more | How far a number in the manuscript may differ from `value`: an absolute difference, in the unit of the value. Zero means an exact match |
