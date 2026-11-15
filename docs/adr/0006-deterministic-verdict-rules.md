# ADR-0006: Deterministic verdict rules

- Status: Accepted
- Date: 2026-11-15

## Context

A model that judges whether a source supports a claim can itself be wrong, for
example by accepting a claim that the source makes only for one dataset, one
metric or one experimental condition. RFC-001 defines a six-step protocol for
claim support. Five steps use language models to varying degrees, with
deterministic validation where applicable.

## Decision

A model may propose; only rules decide. No model output sets a claim's status
directly.

The final step, S6, is a deterministic function that applies the decision
rules to the outputs of the earlier steps. It alone sets the status, the
confidence level and the human-review flag, and no model is called in it.

Every failure path ends in `unverified` or `insufficient_evidence`, never in
`verified`.

## Alternatives rejected

- **A model output that sets a claim's status directly.** Rejected by the
  first design principle of RFC-001.
- **A model-reported probability as the confidence.** Rejected: confidence is
  an ordinal level set by rule.

## Consequences

- Evidence must be quoted verbatim, and each quote is checked against the
  stored source text by string matching, so a model cannot invent a passage.
- A timeout, an invalid output or an unavailable model leaves the claim
  `unverified` with a reason. Nothing defaults to `verified`.
- `verified` means supported by the evidence that was checked, not proven
  true.
- A deterministic final step does not guarantee a correct verdict. The inputs
  from S3, S4 and S5 are model outputs and can be wrong, which is why these
  steps must be scored against the gold-standard set of RFC-002.

## Sources

- `docs/rfc/RFC-001.md`, section 1, "Design principles" and "What this
  protocol does not establish".
- `docs/rfc/RFC-001.md`, section 2, row S6, and section 3, "S6. Aggregation
  and recording".
- `docs/rfc/RFC-001.md`, section 4, "Decision rules" and "Confidence level".
- `docs/rfc/RFC-001.md`, section 7, "Safeguards".
- `docs/spec.md`, section 8, "Verification checks", item 2.
