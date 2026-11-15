# ADR-0007: ModelProvider contract

- Status: Accepted
- Date: 2026-11-15

## Context

`ModelProvider` is one of the three public interfaces (ADR-0004), so its
contract must be kept once it exists. The specification describes it as a
call that takes a request and returns a response with usage and cost, and
gives the choice of model to the core: each agent role maps to a tier, and
each tier maps to a model in the profile.

Several points were open when the interface was first written, in task
M0-09. The first four were the form of the call, how a missing cost is carried, whether the call blocks,
and how the core learns that a provider sends content off the machine. The
last point is needed for the data policy `local_only`, under which raw data
and text derived from it go only to local models.

## Decision

The maintainer decided these points on 2026-11-15.

1. **One typed request.** The interface has one method,
   `complete(request) -> response`. The request carries a model id that the
   core's router has already chosen. A provider knows nothing about agent
   roles or tiers.
2. **Usage and cost.** Token counts are required integers. `cost_usd` is a
   required field of the response; its value is a number of zero or more, or
   null when the provider reports no cost. A cost is never guessed.
3. **Synchronous and thread-safe.** `complete()` blocks until it returns or
   raises. It is safe to call from several threads at once.
4. **Name and locality.** A provider has two read-only attributes: `name` and
   `is_external`. `is_external` is an instance attribute derived from the
   provider's configuration, not a class constant. An implementation must
   return true unless it can show that content stays on the machine.
5. **Structured output.** It is not part of the provider contract in v1. The
   core asks for JSON as text, validates it against a schema and retries
   once (RFC-001, section 2).
6. **Tool calling.** It is not modelled. It is an open item, to be decided in
   a new ADR before the first agent that selects tools itself.
7. **Request options and finish reasons.** The request carries optional
   `temperature` and `max_output_tokens`. Finish reasons are `stop`, `length`
   and `content_filter`.

## Alternatives rejected

- **`complete(role, messages)`.** Rejected: every provider would have to hold
  the mapping from role to model, which belongs to the core's router.
- **A cost that is always a number.** Rejected: a provider that receives no
  cost would have to guess one or fail the call.
- **An asynchronous method.** Rejected in favour of a blocking call that is
  simpler to implement, test and call from the CLI.
- **Only `complete()` in the interface.** Rejected: enforcing the data policy
  would later need a change to a public interface.
- **`is_external` as a class constant.** Rejected: whether content leaves the
  machine depends on how a provider is configured.
- **A response-schema field on the request.** Rejected for v1: the core
  validates the JSON text itself, so every provider behaves the same.
- **Modelling tool calls now.** Rejected: no agent selects tools itself yet,
  and the decision is left to a later ADR.

## Consequences

- The conformance suite checks points 1 to 4, including concurrent calls,
  and every implementation must pass it.
- A call with no reported cost is recorded with a null cost and counted
  separately as unknown cost.
- Callers that need parallel calls use threads.
- The refusal of external providers under `local_only` is built on
  `is_external`, in the core and not in the providers.
- The contract cell of `ModelProvider` in the specification, section 5, was
  updated to the form decided here.

## Sources

- Decision by the maintainer on 2026-11-15, recorded in this ADR.
- `docs/spec.md`, section 5, "Six pluggable interfaces", row `ModelProvider`.
- `docs/spec.md`, section 9, "Model routing": roles map to tiers and tiers to
  models.
- `docs/spec.md`, section 10, "Data confidentiality": the data policy.
- `docs/rfc/RFC-001.md`, section 2: model steps use structured output
  validated against a schema, with one retry.
