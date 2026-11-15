# ADR-0002: File-based stage contracts with SQLite checkpoints

- Status: Accepted
- Date: 2026-11-15

## Context

One of the problems the project targets is fragmentation: ideation, literature
review, experiments and writing live in separate tools with no shared record.
The design is a small fixed core with pluggable layers, and user interfaces and
the core meet only in the project workspace files. The project state format is
one of the two things that are deliberately not pluggable.

## Decision

Stages exchange files, not in-memory objects. Files are the only interface
between stages, and between the core and any user interface. Every contract
file has a versioned Pydantic schema.

Project state is the project files with one metadata sidecar per artifact
version under `.utux/meta/`, plus SQLite checkpoints in
`.utux/checkpoints.sqlite`. This is a fixed layer.

## Alternatives rejected

- **In-memory objects passed between stages.** Rejected: with files, each
  stage can be run, replaced, inspected or edited by hand.
- **A pluggable state format.** Rejected because making it swappable would
  couple every module to the abstraction.
- **Postgres.** Not part of v1; deferred for server deployments.

## Consequences

- Every stage output has a metadata sidecar that records what it was built
  from, so the chain from manuscript back to inputs can be rebuilt.
- Each schema has a version and a migration function; the core refuses to run
  on an unmigrated project rather than guess.
- Stage outputs are written to a temporary directory and moved into place only
  when the stage completes; an artifact without a completed sidecar is ignored.
- Each artifact has one owning stage; inside a stage, parallel agents return
  proposals and a single writer commits the file.
- A project directory is self-contained, with no global state. A web dashboard
  can be a separate package that reads the files the core writes.

## Sources

- `docs/spec.md`, section 1: stages exchange files, not in-memory objects.
- `docs/spec.md`, section 5, "Fixed core" and "Future-proofing": the state
  format is not pluggable; the project directory is self-contained.
- `docs/spec.md`, section 6, technology stack table, row "State", and
  "Recommendations added to the initial proposal": Pydantic schemas.
- `docs/spec.md`, section 7, opening paragraph, "Project directory" and
  "Artifact metadata and validity".
