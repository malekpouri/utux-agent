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
| `status_reason` | null | see below | `data_policy_local_only` |
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

The error is raised again after it is logged.

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
  from `OPENROUTER_API_KEY`; `local` is a local OpenAI-compatible server at
  `http://localhost:11434/v1` (Ollama's usual address).
- A cost the provider did not report is printed as
  `cost unknown: the provider reported none`.
- A failed or refused call is logged and the command exits with 1. The event
  is written with the actor `system:utux` and the prompt version `ping@1`.

`utux model ping` makes a real, paid call when the profile is `default`.
