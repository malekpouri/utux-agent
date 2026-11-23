# Synthetic responses of an OpenAI-compatible chat-completions API

Every file here is synthetic. It was written by hand for the tests of the
OpenAI-compatible client and was not recorded from a real service. No API
key was available when these files were written.

The shapes follow the public documentation of the OpenAI chat-completions
API and of OpenRouter, as the author understood it. They were not checked
against a live response. The fields that could not be confirmed are listed in
`docs/model-provider.md`.

Each `.json` file is the body of one HTTP response. The HTTP status that goes
with it is set in the tests. Model names, ids and amounts are invented.

| File | Stands for |
| --- | --- |
| `openrouter_completion_with_cost.json` | A successful OpenRouter response that reports its cost in `usage.cost` |
| `openai_completion_without_cost.json` | A successful response of an OpenAI-compatible server that reports no cost |
| `completion_without_usage.json` | A successful status with a body that has no `usage` |
| `error_unauthorized.json` | The body of a 401 response |
| `error_insufficient_credits.json` | The body of a 402 response |
| `error_bad_request.json` | The body of a 400 response |
| `error_rate_limited.json` | The body of a 429 response |
| `error_unavailable.json` | The body of a 503 response |
| `error_in_ok_response.json` | A 200 response whose body holds an `error` object instead of `choices`. Whether OpenRouter sends such bodies, and in this shape, is not confirmed |

`gemini_completion.json` is a synthetic answer in the shape of the Gemini API's OpenAI-compatible endpoint (M0-15c): token usage and no cost.
