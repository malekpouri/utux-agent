# Schema conventions

Every file contract in `utux.schemas` follows these conventions. They were
set with the first schema, `utux.yaml` (task M0-03), and later schemas copy
them.

## Models

- A whole contract file is a `ContractDocument` subclass. A nested object is
  a `ContractPart` subclass. Both reject unknown keys and are immutable.
- Enumerations used by more than one schema, such as `Stage` and `Tier`, live
  in `utux.schemas.common`.

## Shared field types

`utux.schemas.common` holds the types that several contracts use. Use them
instead of defining a new pattern.

- `Sha256Hash`: `sha256:` and 64 lower-case hexadecimal digits.
- `UtcTimestamp`: ISO 8601 in UTC with a `Z` suffix, kept as text.
- `ArtifactId`: a name and a version, for example `method-v003`.
- `Actor`: `agent:<role>`, `human:<id>` or `system:<component>`, for example
  `system:utux`.
- `EventId`: `e-` and at least six digits, for example `e-000913`.
- `ClaimId`, `ResultId` and `RunId`: `C`, `R` or `r` and at least three
  digits.
- `RelativePath`: a path inside the project, relative, with `/` as separator
  and without `.` or `..` parts. Every path stored in a contract uses it.
- `FlatObject`: an object whose values are strings, numbers, booleans or
  null. A nested value has code `not_scalar`.
- `NonEmptyText`, `Count` and `NonNegativeUsd` for text, whole numbers of
  zero or more, and amounts of money that may be zero.

## File formats

- `utux.schemas.yaml_io` and `utux.schemas.json_io` read a file into plain
  data. Both refuse a key that appears twice in one mapping.
- A document model offers `from_yaml` or `from_json`, the matching `to_...`
  method, and a module-level `load_...(path)` function. `ContractDocument`
  provides `from_json` and `to_json` for contracts stored as one JSON file.
- A new contract is added to `CONTRACTS` in `utux.schemas.export`. A test
  fails if a `ContractDocument` subclass is missing from it.
- An example from the specification or an RFC is tested by reading it from
  the document itself. Where an example elides a digest as `"sha256:..."`,
  the test replaces only that placeholder with a synthetic digest.

## Field naming

- Keys are `snake_case`. A unit is part of the name: `total_usd`,
  `memory_mb`, `wall_clock_seconds`.
- Related settings are grouped in a nested object, also when the group has
  one field today, so that a later field does not change the shape.
- Closed sets are `StrEnum` classes with lower-case values.
- Booleans, integers and numbers are strict: `"yes"`, `1` or `"20"` are not
  converted.

## Errors

- An invalid file raises one `ContractValidationError`, with `source` (the
  file as the caller named it) and `problems`.
- Each `Problem` has `field` (a dotted path such as
  `oversight.gates.final_manuscript`), `reason` (one line for a person) and
  `code` (stable, for programs and tests).
- The message has one line per problem, `file: field: reason`. Every problem
  is reported, not only the first.
- A problem with the whole file uses the field `<document>`.
- An unknown key is an error at every level. The key is the field, the reason
  is `unknown key` and the code is `unknown_key`.
- A cross-field rule reports one problem per offending value, on the most
  specific field the user must change. Example: a stage budget above the
  total is reported on `budget.per_stage_usd.experiment`, not on `budget`.
  A repeated entry in a list is reported on its position, for example
  `input_artifacts.2`.

### Codes shared by every contract

| Code | Field | When |
| --- | --- | --- |
| `unreadable` | `<document>` | The file cannot be read, or is not UTF-8 text |
| `invalid_json` | `<document>` | The file is not valid JSON |
| `invalid_yaml` | `<document>` | The file is not valid YAML |
| `duplicate_key` | the key | A key appears twice in one mapping |
| `not_a_mapping` | `<document>` | The file does not hold a mapping at the top |
| `schema_version_newer` | `schema_version` | The file was written with a newer schema version |
| `schema_version_unsupported` | `schema_version` | An older schema version, without a migration |
| `unknown_key` | the key | A key the schema does not define |
| `utc_timestamp` | the field | A timestamp that is not ISO 8601 in UTC with `Z`, or a date that does not exist |

Other codes are Pydantic's own (`missing`, `enum`, `string_pattern_mismatch`,
`greater_than_equal` and similar) or are listed with the contract that
raises them.

## `schema_version`

- Each `ContractDocument` subclass sets the class constant `SCHEMA_VERSION`
  and has a required `schema_version` field. A file must state its version;
  it is never assumed. Nested parts do not carry a version.
- The version is checked before anything else. A newer version is refused
  with a message that says so, and nothing else in the file is reported. An
  older version is refused as unsupported until a migration exists.

## Required and nullable fields

- A stored contract states every field. A field that does not apply is
  `null`; it is not left out. `Event` is the example.
- Where code builds a document step by step, a separate input model with
  defaults is used, such as `NewEvent`, and the stored model stays strict.
- A field that explains a failure holds a stable machine code, not a
  message. No free-text error message is stored in a contract file.
- A rule between two fields is reported on the field the user must change:
  a missing reason on `status_reason`, a missing model on `model`.
- A file with one record per line (`.jsonl`) is validated line by line. An
  error names the source as `path:line`.

## Entries of several kinds

- A list whose entries can be of several kinds uses one field that names the
  kind, such as `evidence_type`, and one model per kind.
- A problem inside an entry is reported on its exact path, for example
  `evidence.0.quote`, without the kind in the path.
- A closed set that comes from a document is tested against the text of that
  document, so the code and the document cannot drift apart silently.

## Fixtures and tests

- Fixtures are in `tests/fixtures/<contract>/valid/` and
  `tests/fixtures/<contract>/invalid/`, with a `README.md` that names them as
  synthetic.
- Each invalid file is wrong in exactly one way, and its name says how.
- The test module has one table with the expected `(field, code)` of each
  invalid file. One test checks that the table and the directory list the
  same files, and one that no `(field, code)` pair is repeated.
- Tests assert on `field` and `code`. They assert on the wording of a reason
  only where the wording is itself a requirement.
- Every valid fixture goes through a round-trip test.
