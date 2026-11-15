# Fixtures for artifact metadata sidecars

All files here are synthetic. They were written by hand for the tests of the
artifact metadata schema and do not describe real artifacts. The content
hash in them is the SHA-256 of the text `synthetic fixture content` followed
by a newline.

- `valid/` holds documents that must validate.
- `invalid/` holds documents that must be rejected. Each one is wrong in
  exactly one way, and the file name states it. The expected field and code
  for each file are written out in `tests/unit/test_artifact_metadata.py`.
