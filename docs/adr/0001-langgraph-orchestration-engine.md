# ADR-0001: LangGraph as the orchestration engine

- Status: Accepted
- Date: 2026-11-15

## Context

The fixed core contains the six-stage workflow graph, checkpoints and approval
gates. The specification names two things that are deliberately not pluggable:
the orchestration engine and the project state format. The orchestration layer
is therefore a single choice with no supported alternative in v1.

## Decision

The orchestration engine is LangGraph. It is a fixed layer: v1 supports no
other engine and defers none.

The choice is validated by a spike in milestone M1. The spike builds stages 3
to 5 and confirms four things: resume after a crash from the SQLite
checkpoint, pause and resume at an approval gate, a review finding routed back
to an earlier stage, and a run that streams events to the log.

## Alternatives rejected

- **A pluggable orchestration engine.** Rejected because making the engine
  swappable would couple every module to the abstraction.
- **A plain Python state machine.** Not chosen. It is kept as the fallback,
  with the same file contracts, only if the M1 spike fails or any of its four
  checks needs heavy workarounds.

## Consequences

- LangGraph is first used in milestone M1, the execution spike.
- The exit criterion of M1 is that the four checks pass and the orchestration
  choice is confirmed.
- Because stages exchange files (ADR-0002), the fallback would keep the same
  file contracts.

## Sources

- `docs/spec.md`, section 5, "Fixed core": the workflow graph is part of the
  core, and the orchestration engine is not pluggable.
- `docs/spec.md`, section 6, technology stack table, row "Orchestration", and
  "Prototype evaluation for LangGraph": the four checks and the fallback.
- `docs/spec.md`, section 12, row "M1. Execution spike": the exit criterion.
- `docs/spec.md`, section 13, "Decisions", row "Orchestration engine":
  accepted on 15 Nov 2026.
