# Fixtures for claim ledger entries

All files here are synthetic. They were written by hand for the tests of the
claim ledger schema. The claims, sources, quotes and identifiers in them are
invented and do not describe real papers or real results. The hash in them
is the SHA-256 of the text `synthetic fixture content` followed by a newline.

No file here is a gold-standard label. The statuses and labels in these
files only exercise the schema.

Each file holds one ledger entry as a JSON document. In a project, entries
are the lines of `claims.jsonl`.

- `valid/` holds entries that must validate.
- `invalid/` holds entries that must be rejected. Each one is wrong in
  exactly one way, and the file name states it. The expected field and code
  for each file are written out in `tests/unit/test_claim_ledger.py`.
