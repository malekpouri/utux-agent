# ADR-0008: Model access without LiteLLM

- Status: Accepted
- Date: 2026-11-16

## Context

The specification named LiteLLM as the way to reach models: OpenRouter as
the default gateway, with direct provider keys and Ollama through the same
library. When LiteLLM was added for task M0-10, it turned out to bring
copyleft packages into the core, which `AGENTS.md` section 10 does not
allow.

The maintainer gave these reasons against LiteLLM in the core:

- Two supply-chain compromises of LiteLLM releases on PyPI in 2026: in
  March, versions 1.82.7 and 1.82.8, and in October, version 1.107.0.
- It adds 61 runtime packages to the core.
- It downloads its model price table from the network when it is imported.
- The costs it reports are computed from that price table, not reported by
  the provider. utux records only a cost that the provider reports
  (ADR-0007).

## Decision

The maintainer decided on 2026-11-16 that LiteLLM does not go into the core.

Models are reached through one small OpenAI-compatible chat-completions
client, written on the Python standard library only (`urllib`, `json`, and
`ssl` with the system trust store). The client is blocking and honours the
request timeout. The OpenRouter provider is that client with OpenRouter's
base URL and the key from `OPENROUTER_API_KEY`. The same client works for any
OpenAI-compatible base URL. `is_external` is derived from the configured
host: a loopback host is local, every other host is external.

`cost_usd` is only what the provider reports in its response. If the
response carries no cost, `cost_usd` is null. There is no price table and no
estimate.

Nothing in utux accesses the network when it is imported.

## Alternatives rejected

- **LiteLLM in the core.** Rejected for the reasons above.
- **LiteLLM in a separate optional package.** Not chosen: it keeps the
  reasons against LiteLLM, only outside the core.
- **Keeping LiteLLM and allowing MPL-2.0 dependencies in the core.** Not
  chosen: it would accept the supply-chain risk, the size and the network
  fetch at import.

## Consequences

- Direct Anthropic and Gemini keys leave the v1 core. Both stay reachable
  through OpenRouter. A separate optional provider package may add them
  later.
- A direct OpenAI key and local OpenAI-compatible servers such as Ollama use
  the same client as OpenRouter.
- A provider that reports no cost gives calls with an unknown cost, which are
  counted separately (ADR-0007).
- The client handles retries, timeouts and error mapping itself, and is
  tested against synthetic responses and a loopback server.
- A test checks that importing any module of utux opens no network
  connection.

## Sources

- Decision by the maintainer on 2026-11-16, recorded in this ADR.
- `docs/spec.md`, section 6, technology stack table, row "Model access", and
  "Recommendations added to the initial proposal", as changed by this
  decision.
- `docs/spec.md`, section 5, "Six pluggable interfaces", row `ModelProvider`.
- `docs/adr/0007-model-provider-contract.md`: cost is never guessed.
- Reports on the LiteLLM incidents, given by the maintainer:
  - https://bleepingcomputer.com/news/security/litellm-release-pipeline-hacked-to-distribute-info-stealer-malware
  - https://letsdatascience.com/news/litellm-breach-exposes-ai-supply-chain-risk-69f3c6f7
