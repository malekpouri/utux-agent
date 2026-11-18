# ADR-0009: Large files outside git, hashes in manifests

- Status: Accepted
- Date: 2026-11-18

## Context

Each project is one git repository, and each stage completion is a commit
(`docs/spec.md`, section 6). A run manifest records input data hashes and
the outputs of a run (section 7, "Run manifest"), and every artifact version
has a sidecar with its content hash (section 7, "Artifact metadata and
validity").

Data files under `inputs/` and run outputs under `runs/<run_id>/outputs/` can
be large, can be binary, and can be confidential: under the data policy
`local_only`, raw data must not leave the machine (section 10, "Data
confidentiality"). Today `utux init` writes a `.gitignore` that excludes
only caches, the checkpoint database and the atomic writer's temporary files.

The M0 plan left this note for M1: "decide how large files under inputs/ and
runs/ are kept out of git while their hashes stay in the manifests"
(`docs/plan/M0.md`, Notes).

## Decision

Proposed in `docs/plan/M1.md`, M1-01, and accepted by the maintainer on
2026-11-18:

Git holds text artifacts, manifests, sidecars and logs. Files under
`inputs/` other than `*.md`, and everything under `runs/<id>/outputs/`, are
ignored by git. Their content hashes in run manifests and sidecars are the
record. `utux init` writes these ignore lines.

## Alternatives rejected

- **Commit every file.** Simple, but large and binary data bloats the
  repository for good, and confidential data enters the history, where
  deleting it later needs rewriting history.
- **Git LFS.** Keeps large files versioned, but needs the `git-lfs` tool and
  a server that supports it, and still puts confidential data on that
  server.
- **A data versioning tool such as DVC.** Adds a runtime dependency and a
  second storage model for what the hashes in manifests already record.
- **Ignore by file size.** Whether a file is tracked would depend on its
  size at the time, so the same project could be tracked differently on two
  machines.

## Consequences

- The hashes are the record of data and outputs. `reproduce.sh` and
  `utux validate` can tell that a file changed or is missing, but cannot
  restore it; keeping the data is the user's responsibility.
- Confidential input data never enters the git history.
- Text inputs (`*.md` under `inputs/`), such as the research question and
  the data description, stay versioned.
- `utux init` gains ignore lines (task M1-05), and existing projects need
  them added by hand. `utux validate` warns, without failing, when a
  project's `.gitignore` lacks them (task M1-05).
- Result records and manifests stay in git, so every number remains
  traceable to a run even when its output files are not.

## Sources

- `docs/spec.md`, section 6 (one git repository per project), section 7
  (project directory, artifact metadata, run manifest), section 10 (data
  confidentiality).
- `docs/plan/M0.md`, Notes: the M1 note on large files.
- `docs/plan/M1.md`, M1-01: the recommendation.
- `src/utux/workspace/layout.py`, `GITIGNORE_LINES`: the current ignore lines.
