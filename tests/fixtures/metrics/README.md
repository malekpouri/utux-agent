# Fixtures for metrics files

All files here are synthetic. They were written by hand for the tests of the
metrics file schema (`outputs/metrics.json`) and do not describe real
results.

- `valid/` holds documents that must validate.
- `invalid/` holds documents that must be rejected. Each one is wrong in
  exactly one way, and the file name states it. The expected field and code
  for each file are written out in `tests/unit/test_metrics_file.py`.
