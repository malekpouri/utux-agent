# Fixtures for events

All files here are synthetic. They were written by hand for the tests of the
event schema and do not come from a real run. The hashes in them are the
SHA-256 of the text `synthetic fixture content` followed by a newline.

Each file holds one event as a JSON document. In a project, events are the
lines of `events.jsonl`; the tests of the event log build their logs in a
temporary directory.

- `valid/` holds events that must validate.
- `invalid/` holds events that must be rejected. Each one is wrong in exactly
  one way, and the file name states it. The expected field and code for each
  file are written out in `tests/unit/test_event.py`.
