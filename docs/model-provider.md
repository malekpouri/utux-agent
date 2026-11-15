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
- an authentication failure, a rate limit and an invalid answer each raise
  their typed error;
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
