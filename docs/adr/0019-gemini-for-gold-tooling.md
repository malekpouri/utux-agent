# ADR-0019: Direct Gemini access with an estimated cost, for gold tooling only

- Status: Accepted
- Date: 2026-11-23

## Context

ADR-0008 keeps direct Anthropic and Gemini keys out of the v1 core, where
models are reached through OpenRouter, and sets `cost_usd` to only what the
provider reports: "There is no price table and no estimate."

The gold v0 strategy (ADR-0018) has Gemini write some perturbations and
check them, pinned to `gemini-3.8-flash` on the paid tier of the Gemini API,
whose terms say prompts and responses are not used to improve Google's
products (`docs/eval/gold-v0-strategy.md`, section 7). Task M0-15c asks for
`utux gold perturb` with the key from `GEMINI_API_KEY` and a `--max-cost-usd`
cap (`docs/plan/M0.md`).

Gemini's OpenAI-compatible endpoint,
`https://generativelanguage.googleapis.com/v1beta/openai/`, takes the key as a
bearer token and reports token usage but no cost
([OpenAI compatibility](https://aistudio.google.com/docs/openai), read on
2026-11-23). A cap therefore needs a price table.

## Decision

The maintainer decided on 2026-11-23 on a scoped exception to ADR-0008, for
the gold tooling only (`utux.evalkit`, `utux gold perturb`):

1. **Access.** Gemini is reached directly through the existing
   standard-library OpenAI-compatible client, with the key read only from
   `GEMINI_API_KEY`.
2. **Estimated cost.** A pinned price table gives an estimated cost for each
   call. It is recorded as `estimated_cost_usd` in the `model_call` event's
   data and labelled an estimate in every report. It is never written to
   `cost_usd`, which stays reserved for cost the provider reports.
3. **The cap** always uses the higher of the table's prices, $1.50 per
   million input tokens and $7.50 per million output tokens, thinking
   included, even before 2026-12-31. A wrong or stale table then cannot push
   spending over the cap.

The price table cites the [Gemini API pricing page](https://aistudio.google.com/docs/pricing),
read on 2026-11-23. For `gemini-3.8-flash` on the paid tier, standard, per
million tokens: input $0.75 through 2026-12-31 and $1.50 from 2027-01-01;
output, thinking included, $3.75 through 2026-12-31 and $7.50 from
2027-01-01.

ADR-0008 stays in force for the pipeline: no stage of a project run uses
this access, and no project `cost_usd` comes from a table.

## Alternatives rejected

- **OpenRouter, as ADR-0008 has it.** It reports cost, but requests would go
  under OpenRouter's terms instead of the Gemini API paid tier recorded in
  the strategy.
- **Deferring the model-written perturbations.** v0 would have no
  `partially_supported` items, which only perturbations can give (ADR-0018).
- **Writing the estimate to `cost_usd`.** It would mix an estimate with
  reported costs in the project's cost accounting.

## Consequences

- The `model_call` event gains an optional data key, `estimated_cost_usd`
  (a number of zero or more, or null). It may be absent, as in every event
  written before it existed.
- The gold tooling's own event log lies next to its outputs, outside the
  repository and outside any project.
- The price table is a constant with its source and retrieval date, and has
  to be checked against the pricing page before each run.

## Sources

- `docs/adr/0008-model-access-without-litellm.md` and
  `docs/adr/0018-gold-v0-from-public-datasets.md`.
- `docs/eval/gold-v0-strategy.md`, section 7.
- `docs/plan/M0.md`, M0-15c.
- `docs/spec.md`, section 6 (model access), and `docs/rfc/RFC-002.md`, section 2
  (perturbations and Gemini's role).
