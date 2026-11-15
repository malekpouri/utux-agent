# ADR-0003: Apache-2.0 licence and no reuse of Denario code

- Status: Accepted
- Date: 2026-11-15

## Context

utux Agent is an independent framework, complementary to Denario, and Denario
is its reference point for comparison and evaluation. Denario is licensed
under GPLv3.

## Decision

The core and the first-party packs are licensed under Apache-2.0.

No Denario code is reused. The code bases are kept separate to avoid licensing
questions. This is a project choice, not a legal conclusion about what GPLv3
permits.

Any dependency with a copyleft licence lives in its own optional plugin
package, never in the core.

## Alternatives rejected

- **Reusing Denario code.** Rejected: Denario is GPLv3 and utux Agent is
  Apache-2.0, and keeping the code bases separate avoids licensing questions.
- **Copyleft dependencies in the core.** Rejected in favour of isolating them
  in optional plugin packages.

## Consequences

- A licence audit of all dependencies runs before the first public release to
  confirm compatibility.
- Project migration from Denario is out of scope for v1.
- Denario remains a comparison target: the evaluation pins and reports the
  exact Denario version and the workflow that is compared.

## Sources

- `docs/spec.md`, section 1, "Positioning".
- `docs/spec.md`, section 11, "Denario comparison protocol".
- `docs/spec.md`, section 13, "Licensing and community", and "Decisions", row
  "License": accepted on 15 Nov 2026.
