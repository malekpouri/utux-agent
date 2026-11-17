# The `ModelProvider` interface

`ModelProvider` is one of the three public interfaces. It gives the core one
way to call a language model, whichever service is behind it. The contract is
decided in [ADR-0007](adr/0007-model-provider-contract.md). The code is in
`utux.interfaces.model_provider`.

## Contract

```python
class ModelProvider(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def is_external(self) -> bool: ...
    def complete(self, request: ModelRequest) -> ModelResponse: ...
```

- `complete()` takes the request and no other parameter. It blocks until it
  returns or raises, and it is safe to call from several threads at once.
- The request carries a model id that the core's router has already chosen.
  A provider knows nothing about agent roles or tiers.
- `name` and `is_external` are read-only. `is_external` says whether content
  sent to the provider leaves the machine. It is set per instance from the
  provider's configuration, and it must be true unless the implementation
  can show that content stays on the machine.

## Request

| Field | Form | Meaning |
| --- | --- | --- |
| `model` | text, not empty | The model id |
| `messages` | one or more messages | The conversation, oldest first. A message has a `role` (`system`, `user` or `assistant`) and `content` |
| `timeout_seconds` | number above 0 | How long the caller waits |
| `temperature` | number, 0 or more; optional | Sampling temperature. Not set means the provider's default |
| `max_output_tokens` | integer above 0; optional | Limit on the answer's length. Not set means the provider's default |

Unknown fields are rejected, so a provider cannot add a parameter of its own.

## Response

| Field | Form | Meaning |
| --- | --- | --- |
| `model` | text, not empty | The id of the model that answered |
| `content` | text | The answer |
| `finish_reason` | `stop`, `length` or `content_filter` | Why the model stopped |
| `usage.tokens_in`, `usage.tokens_out` | integers, 0 or more | Token counts. Always present |
| `cost_usd` | number, 0 or more, or null | Cost reported by the provider. Always a field; null when the provider reported no cost. Never guessed |

## Errors

Every error is a `ModelProviderError` from `utux.errors`. A message never
contains an API key or the content of a message.

| Error | When |
| --- | --- |
| `ModelAuthenticationError` | Credentials are missing or were refused |
| `ModelRateLimitError` | The provider refused the call because of a rate limit. `retry_after_seconds` holds the wait it asked for, if any |
| `ModelTimeoutError` | No answer arrived within `timeout_seconds` |
| `ModelInvalidResponseError` | The answer cannot be turned into a valid response, for example because usage is missing |
| `ModelUnavailableError` | A network failure or an upstream server error. Retryable, and the trigger for falling back to another provider |
| `ModelRequestRejectedError` | The provider refused the request itself, for example an unknown model or an input longer than the model's context. Not retryable |

## Not part of the contract in v1

- **Structured output.** The core asks for JSON as text, validates it against
  a schema and retries once (RFC-001, section 2).
- **Tool calling.** It is not modelled. It will be decided in a new ADR
  before the first agent that selects tools itself.

## Conformance suite

Every implementation must pass `tests/conformance/model_provider_suite.py`.
To run it against a provider, add a test module in `tests/conformance/` with
a subclass of `ModelProviderConformance` whose name starts with `Test`, and
implement its four `make_...` methods. The suite never calls a real model.

It checks that:

- the object is a `ModelProvider`, and `complete()` takes only the request;
- `name` is non-empty text, `is_external` is a boolean that is not a class
  constant, and both are read-only;
- a response has a model id, a finish reason, whole-number token counts and
  the `cost_usd` field, which is null when the provider reports no cost;
- an authentication failure, a rate limit, an invalid answer, an unavailable
  provider and a rejected request each raise their typed error;
- a call gives up with `ModelTimeoutError` near its timeout, and an answer
  within the timeout is returned;
- 40 calls from 8 threads at once all return well-formed responses.

## Scripted provider for tests

`utux.providers.scripted.ScriptedModelProvider` answers from a script written
by the test and never contacts a model. It records the requests it receives.
Tests of code that calls a provider use it in place of a real one.

```python
provider = ScriptedModelProvider(
    [
        ScriptedReply(content="first answer", tokens_in=12, tokens_out=3, cost_usd=0.0004),
        ScriptedFailure(ModelRateLimitError("slow down")),
    ]
)
```

## The OpenAI-compatible client and OpenRouter

`utux.providers.openai_compatible` holds the one implementation in the core:
an OpenAI-compatible chat-completions client written on the Python standard
library only (ADR-0008). It serves OpenRouter, a direct OpenAI key, and local
servers such as Ollama.

```python
from utux.providers.openai_compatible import OpenAICompatibleProvider, openrouter

provider = openrouter()  # key from OPENROUTER_API_KEY
local = OpenAICompatibleProvider(
    name="ollama", base_url="http://localhost:11434/v1", api_key_env=None
)
```

### Configuration

| Argument | Meaning |
| --- | --- |
| `name` | Short name, used in logs and error messages |
| `base_url` | The API's base URL. Requests go to `<base_url>/chat/completions`. It must use https, except for a loopback host. It may not hold a user name, a password, a query or a fragment |
| `api_key_env` | The environment variable that holds the key, or `None` for a server that needs no key. The key is read at each call and never stored |
| `extra_body` | Fields added to every request body. They may not replace `model`, `messages`, `temperature` or `max_tokens` |
| `max_attempts`, `backoff_seconds`, `max_backoff_seconds` | Retries: 3 attempts in all, waiting 0.5 s and then 1 s, at most 8 s, by default |

A configuration that cannot work raises `ModelProviderConfigError` when the
provider is created.

`is_external` follows the host of the base URL: `localhost` and loopback
addresses (`127.0.0.0/8`, `::1`) are local; every other host is external,
including addresses on the local network.

`openrouter()` is the client with `https://openrouter.ai/api/v1`, the key from
`OPENROUTER_API_KEY`, and `{"usage": {"include": true}}` in every request
body, which asks OpenRouter to report the cost of the call.

### Request

The body holds `model`, `messages` (`role` and `content`), and
`temperature` and `max_tokens` only when the request sets them. The headers
are `Content-Type` and `Accept` (`application/json`), `User-Agent`
(`utux/<version>`), and `Authorization: Bearer <key>` when a key is
configured.

### Response

| Field read | Becomes |
| --- | --- |
| `model` | `model` |
| `choices[0].message.content` | `content`. Null is accepted only with the finish reason `content_filter`, and becomes empty text |
| `choices[0].finish_reason` | `stop`, `length` or `content_filter`. Any other value, such as `tool_calls`, is an invalid response |
| `usage.prompt_tokens`, `usage.completion_tokens` | `usage.tokens_in`, `usage.tokens_out` |
| `usage.cost` | `cost_usd`, as reported. Missing or null gives null. A value that is not a number of zero or more is an invalid response |

There is no price table and no estimate: a provider that reports no cost
gives `cost_usd: null`.

### Errors and retries

| Upstream | Error | Retried |
| --- | --- | --- |
| No key, or a key with spaces or control characters | `ModelAuthenticationError`, before anything is sent | No |
| HTTP 401, 403 | `ModelAuthenticationError` | No |
| HTTP 429 | `ModelRateLimitError`, with `retry_after_seconds` from a `Retry-After` header given in seconds | Yes |
| HTTP 408, or no answer in time | `ModelTimeoutError` | No |
| HTTP 5xx, or the host cannot be reached | `ModelUnavailableError` | Yes |
| Any other HTTP 4xx, including 402 | `ModelRequestRejectedError` | No |
| HTTP 200 whose body is not a valid response, or a redirect | `ModelInvalidResponseError` | No |

Retries wait `backoff_seconds`, doubling each time up to
`max_backoff_seconds`, or as long as a `Retry-After` header asks. A retry is
made only when an attempt is left and the wait still fits into the request's
timeout, so a call never takes longer than its timeout.

The message of an error holds the provider's name, the HTTP status and the
provider's reason, cut to 300 characters. If the provider echoes the key,
it is replaced by `[redacted]`. The client logs nothing.

### Transport

`HttpTransport` uses `http.client` and `ssl.create_default_context()`, which
loads the system trust store. Before every blocking read it sets the socket
timeout to the time that is left, so the timeout covers the whole exchange,
not each read alone. Name resolution is bounded by the system resolver, not
by the timeout. Proxy settings from the environment (`HTTPS_PROXY`) are not
used. A response body larger than 16 MiB is refused.

### What the tests are based on

The tests use synthetic, hand-written responses
(`tests/fixtures/openai_compatible`) and a loopback HTTP server inside the
test. No response was recorded from a real service.

One run of the live smoke test (`tests/integration/test_openrouter_live.py`)
passed on 2026-11-17, against `openai/gpt-4o-mini`, with
`{"usage": {"include": true}}` in the request. It shows only what the test
asserts: the response parsed into a valid response, with `usage.prompt_tokens`
and `usage.completion_tokens` above zero, a finish reason of `stop` or
`length`, and a `usage.cost` that is a number of zero or more.

These parts of the real response format were not confirmed:

- **Where OpenRouter reports cost, and in what unit.** The client reads
  `usage.cost` and treats it as US dollars. OpenRouter's documentation, as the
  author remembers it, gives the cost in credits, one credit being one US
  dollar. Whether `usage.cost` also appears without
  `{"usage": {"include": true}}` was not checked.
- **Cost with a key of the user's own (BYOK).** Whether `usage.cost` is then
  zero, and whether the upstream cost appears elsewhere, such as in
  `usage.cost_details.upstream_inference_cost`, was not checked.
- **Error bodies.** The shape `{"error": {"message": ..., "code": ...}}` for
  401, 402, 408, 429 and 5xx responses, and whether a 429 carries a
  `Retry-After` header.
- **An error inside a 200 response.** Whether OpenRouter ever answers 200
  with an `error` object instead of `choices`; the client treats such a body
  as an invalid response.
- **Finish reasons.** Which values occur besides `stop` and `length`;
  `native_finish_reason` is not read.
- **`max_tokens`.** Whether every model behind OpenRouter honours it, rather
  than the newer `max_completion_tokens`.
- **Local servers.** The response of Ollama's OpenAI-compatible endpoint, in
  particular whether it always includes `usage`.
