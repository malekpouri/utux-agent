# Fixture projects

All files here are synthetic. They were written by hand for the tests of
`utux validate` and do not describe real research. The claims, results,
sources, runs and approvals are invented; no file is a gold-standard label.

- `valid_full/` is a valid project with one file of every contract kind.
  It has no `.git` directory; `utux validate` does not read git.
- `corrupted/<name>/` describes a project that is `valid_full` with one
  fault. The directory holds only the files that differ: each file in it
  replaces or adds the file at the same path, and `remove.txt`, if present,
  lists paths to delete. The tests build each corrupted project in a
  temporary directory.

The expected file, line, field and code of each fault are written out in
`tests/unit/test_validation.py`.
