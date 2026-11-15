# ADR-0004: Three public and three internal interfaces

- Status: Accepted
- Date: 2026-11-15

## Context

The core knows nothing about any research domain. Everything replaceable sits
behind one of six interfaces, each a Python `Protocol`: `ModelProvider`,
`LiteratureSource`, `ToolProvider`, `Executor`, `Writer` and `Reviewer`.
Every public interface is a contract that must be kept, even before it has
outside users.

## Decision

v1 commits to three public interfaces: `ModelProvider`, `LiteratureSource`
and `ToolProvider`. `Executor`, `Writer` and `Reviewer` are internal in v1.

Internal does not mean loosely designed. The internal interfaces have the same
clean, typed contracts and conformance tests as the public ones, and the core
reaches them only through those contracts.

An internal interface becomes public only when two independent
implementations pass its conformance tests.

## Alternatives rejected

- **Six public interfaces.** Rejected: each public interface is a contract
  that must be kept, so v1 commits to three public APIs, not six. The three
  internal ones each have a single real or stable implementation so far:
  Docker is the only real `Executor`, LaTeX and Markdown are enough for
  `Writer`, and one stable `Reviewer` implementation comes first.

## Consequences

- Every implementation must pass a shared conformance test suite for its
  interface.
- Implementations are separate packages discovered through entry points.
- When a second implementation of an internal interface arrives, it can be
  made public without wide changes to the core.
- Other executors are added later as `Executor` packages without touching the
  core.

## Sources

- `docs/spec.md`, section 5, "Six pluggable interfaces" and "Future-proofing".
- `docs/spec.md`, section 13, "Decisions", closing paragraph: an interface
  becomes public plugin API only after two implementations pass its
  conformance tests (added after the team review on 15 Nov 2026).
