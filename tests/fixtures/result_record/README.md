# Fixtures for result records

All files here are synthetic. They were written by hand for the tests of the
result record schema. The metrics, values, datasets and models in them are
invented and were not computed by any run.

Each file holds one result record as a JSON document. In a project, records
are the lines of `results.jsonl`.

- `valid/` holds records that must validate.
- `invalid/` holds records that must be rejected. Each one is wrong in
  exactly one way, and the file name states it. The expected field and code
  for each file are written out in `tests/unit/test_result_record.py`.
