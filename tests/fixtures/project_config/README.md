# Fixtures for `utux.yaml`

All files here are synthetic. They were written by hand for the tests of the
project configuration schema and do not come from a real project.

- `valid/` holds documents that must validate.
- `invalid/` holds documents that must be rejected. Each one is wrong in
  exactly one way, and the file name states it. The expected field and reason
  for each file are written out in `tests/unit/test_project_config.py`.
