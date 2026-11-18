# ADR-0010: Stage commits and commit signing

- Status: Proposed
- Date: 2026-11-18

## Context

Each stage completion is a git commit (`docs/spec.md`, section 6). In
`auto` mode a run continues without a person present (section 9,
"Oversight modes").

Commits follow the user's git configuration. `utux init` already makes its
first commit that way, signing included, and fails with the git error if the
commit cannot be made (`src/utux/workspace/project.py`). When the user signs
commits, signing can need a passphrase or a hardware key, which an
unattended run cannot supply; a commit that waits for input would stall the
run, and one that fails would stop it halfway.

The M0 plan left this note for M1: "decide how commits made by utux during
an unattended run behave when the user has commit signing configured"
(`docs/plan/M0.md`, Notes).

## Decision

Proposed in `docs/plan/M1.md`, M1-01:

Commits follow the user's git configuration. Before a run starts, utux makes
a test commit in a temporary repository with the same configuration and no
terminal. If it fails, `auto` mode refuses to start, and `guided` mode warns
and continues without commits, recording that in an event.

## Alternatives rejected

- **Always disable signing for utux's commits** (`commit.gpgsign=false`).
  The run never stalls, but it silently overrides a security setting the
  user chose, and unsigned commits may be rejected by the user's
  repositories.
- **Ask for the passphrase at every commit.** Works in `guided` mode only,
  and turns every stage end into an interruption.
- **Skip commits whenever signing is configured.** Loses the per-stage
  history (section 6) for every user who signs, even when signing would
  have worked.
- **Find out at the first stage commit.** The run would fail or stall after
  model calls have been paid for.

## Consequences

- An unattended run never stops at a commit because of signing: it either
  starts with commits known to work, or does not start.
- In `guided` mode a run without commits still has its event log, sidecars
  and manifests; the event says that commits were off and why. The event
  type and its data keys are defined by the task that writes them (rule 1 of
  `docs/plan/M1.md`).
- "No terminal" means the test commit cannot prompt: git is run with
  standard input closed and `GIT_TERMINAL_PROMPT=0`. A signing program that
  opens its own window could still wait; the test commit then needs a
  timeout, which the implementing task sets.
- The test costs one commit in a temporary repository per run.

## Sources

- `docs/spec.md`, section 6 (one git repository per project, a commit per
  stage), section 9 (oversight modes).
- `src/utux/workspace/project.py`: the first commit follows the user's git
  configuration.
- `docs/plan/M0.md`, Notes: the M1 note on commit signing.
- `docs/plan/M1.md`, M1-01: the recommendation.
