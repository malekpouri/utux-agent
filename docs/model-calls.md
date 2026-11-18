# Logged model calls and `utux model ping`

Every model call that utux makes goes through `LoggedModelCaller`
(`utux.workspace.model_calls`), which writes exactly one `model_call` event
to the project's `events.jsonl` for it: on success, on failure and when the
call is refused. The answer of a call is returned only after its event is
written, so no result is used without a record.

## The event

| Field | Success | Failure | Refused |
| --- | --- | --- | --- |
| `status` | `ok` | `error` | `refused` |
| `status_reason` | null | see below | `data_policy_local_only` or `budget_exhausted` |
| `model` | the model that answered | the model asked for | the model asked for |
| `input_hash` | hash of the request | hash of the request | hash of the request |
| `output_hash` | hash of the answer's text | null | null |
| `tokens_in`, `tokens_out` | as reported | null | null |
| `cost_usd` | as reported, or null when the provider reported none | null | null |
| `duration_ms` | time of the call | time until the failure | null |
| `actor`, `stage`, `prompt_version` | given by the caller | given by the caller | given by the caller |
| `data` | `{"provider": <name>, "is_external": <bool>}` | the same | the same |

`data` names the provider and whether it is external, so the log shows which
provider received which content hash.

A call whose response carries no cost has `cost_usd: null`. That event is the
record of the unknown cost; no separate warning event is written.

The status reason of a failed call is a stable code for the error type:

| Error | `status_reason` |
| --- | --- |
| `ModelTimeoutError` | `model_timeout` |
| `ModelRateLimitError` | `model_rate_limit` |
| `ModelUnavailableError` | `model_unavailable` |
| `ModelAuthenticationError` | `model_authentication` |
| `ModelRequestRejectedError` | `model_request_rejected` |
| `ModelInvalidResponseError` | `model_invalid_response` |
| anything else raised by a provider | `unexpected_error` |
| an interrupt (`KeyboardInterrupt`, Ctrl-C) during the call | `interrupted` |

The error is raised again after it is logged. An interrupt is logged
because the request may already have reached the provider and been billed.

### Hashes, never text

No message text and no answer text is stored in the event.

- `input_hash` is the SHA-256 of the request as canonical JSON (sorted keys,
  no spaces, UTF-8) of the model, the messages, the temperature and the
  output limit. The timeout is left out, because it does not change the
  answer.
- `output_hash` is the SHA-256 of the answer's text in UTF-8.

### Refused calls

Under the data policy `local_only`, a call to a provider whose `is_external`
is true is refused before anything is sent: a `model_call` event with status
`refused` and `status_reason` `data_policy_local_only` is written, and
`ModelCallRefusedError` is raised. The provider is never asked.

In M0 this rule is stricter than the specification. Section 10 of the
specification lets external models see schemas and aggregate statistics that
the user has approved, even under `local_only`; utux cannot yet tell such
content apart, so under `local_only` every call to an external provider is
refused. Finer control is left to M3.

When the known cost has reached the project budget, or the budget of the
call's stage, a call is refused the same way with `status_reason`
`budget_exhausted`, a `budget_warning` event follows it, and
`BudgetExhaustedError` (a `ModelCallRefusedError`) is raised. The data policy
is checked first. See [Cost and budget](cost.md).

After a successful call to an external provider returned no cost, every
later call to that provider is refused with `status_reason`
`unknown_cost_not_allowed` and `UnknownCostNotAllowedError` (a
`ModelCallRefusedError`), unless `budget.allow_unknown_cost` is true in
`utux.yaml`. Calls to a local provider and failed calls never trigger this.
It is checked after the data policy and before the budget.

## `utux model ping`

```bash
uv run utux model ping [DIRECTORY] [--tier light|standard|strong]
```

It sends a fixed short prompt ("Reply with the single word: pong") to the
model of the tier, through the provider of the project's profile, logs the
call, and prints the tokens and the cost:

```text
openai/gpt-4o-mini answered through openrouter: 14 tokens in, 1 token out, cost 0.0000021 USD
```

- The tier defaults to `light`, the directory to the current one.
- The model comes from `models.tiers` in `utux.yaml`. If the tier has no
  model, the command fails and nothing is logged; there is no default model.
- The provider comes from the profile: `default` is OpenRouter, with the key
  from `OPENROUTER_API_KEY`; `local` is the OpenAI-compatible server at
  `local_server.base_url` in `utux.yaml`, by default
  `http://localhost:11434/v1` (Ollama's usual address).
- It holds the project lock and records setting changes before the call
  ([Creating a project](project.md)). While another command holds the lock,
  it is refused and nothing is sent.
- A cost the provider did not report is printed as
  `cost unknown: the provider reported none`.
- A failed or refused call is logged and the command exits with 1. The event
  is written with the actor `system:utux` and the prompt version `ping@1`.

`utux model ping` makes a real, paid call when the profile is `default`.
