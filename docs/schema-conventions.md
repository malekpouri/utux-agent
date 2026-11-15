# Schema conventions

Every file contract in `utux.schemas` follows these conventions. They were
set with the first schema, `utux.yaml` (task M0-03), and later schemas copy
them.

## Models

- A whole contract file is a `ContractDocument` subclass. A nested object is
  a `ContractPart` subclass. Both reject unknown keys and are immutable.
- Enumerations used by more than one schema, such as `Stage` and `Tier`, live
  in `utux.schemas.common`.

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

## `schema_version`

- Each `ContractDocument` subclass sets the class constant `SCHEMA_VERSION`
  and has a required `schema_version` field. A file must state its version;
  it is never assumed. Nested parts do not carry a version.
- The version is checked before anything else. A newer version is refused
  with a message that says so, and nothing else in the file is reported. An
  older version is refused as unsupported until a migration exists.

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
