# utux Agent

utux Agent is an open-source, modular multi-agent framework that takes a
computational research project from idea to reviewed manuscript. Its defining
property is scientific reliability: every claim in an output must be traceable
to checked evidence or to a computed result.

## Status

The project is in milestone M0. What works today:

- `utux init` creates a project: its directory tree, `utux.yaml`, the event
  log with its first event, and a git repository with a first commit.
- `utux validate` checks every contract file of a project and reports every
  problem.
- `utux log repair` saves aside an incomplete last line of the event log,
  left by an interrupted write, and records the repair.
- `utux model ping` sends a short prompt to the model of a tier and prints
  the tokens and the cost; the call is logged as a `model_call` event.
- `utux schema export <dir>` writes a JSON Schema file for every file
  contract.
- The schemas of all file contracts, the append-only event log and the
  `ModelProvider` interface exist as library code, with one provider: an
  OpenAI-compatible client for OpenRouter, a direct OpenAI key or a local
  server such as Ollama.

What does not exist yet: cost accounting and budgets, and every pipeline
stage. See `docs/plan/M0.md` for what is being
built.

## Quick start

```bash
uv sync
uv run utux init my-project --budget-usd 20 --data-policy external_allowed
uv run utux validate my-project
```

`--budget-usd` and `--data-policy` are required and have no default. See
[Creating a project](docs/project.md). Under `--data-policy local_only`,
every call to an external provider such as OpenRouter is refused.

`utux model ping` needs a model under `models.tiers` in `utux.yaml`.
`utux init` already writes a `models` section with an empty tier mapping, so
edit that section in `my-project/utux.yaml`. Replace this line:

```yaml
  tiers: {}
```

with:

```yaml
  tiers:
    light: openai/gpt-4o-mini
```

Do not append a second `models:` key at the end of the file; a key that
appears twice is rejected as a duplicate. Then send a short prompt to the
model of the `light` tier:

```bash
uv run utux model ping my-project --tier light
```

With the `default` profile this is a real, paid call to OpenRouter and needs
the `OPENROUTER_API_KEY` environment variable. See
[Logged model calls and `utux model ping`](docs/model-calls.md).

## Documents

- [Technical Product Specification](docs/spec.md)
- [RFC-001: Claim Support Verification Protocol](docs/rfc/RFC-001.md)
- [RFC-002: Gold Standard Dataset and Evaluation Protocol](docs/rfc/RFC-002.md)
- [Architecture decision records](docs/adr/)
- [Creating a project](docs/project.md)
- [Validating a project](docs/validate.md)
- [`utux.yaml` reference](docs/utux-yaml.md)
- [Schema conventions](docs/schema-conventions.md)
- [Artifact metadata and content hashes](docs/artifact-metadata.md)
- [The `ModelProvider` interface](docs/model-provider.md)
- [Events and the event log](docs/event-log.md)
- [Logged model calls and `utux model ping`](docs/model-calls.md)
- [Claim ledger and result records](docs/claim-ledger.md)
- [Run manifest, approvals, source record and schema export](docs/contracts.md)

## Development

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync                      # install dependencies from uv.lock
uv run pytest                # unit and integration tests (no network)
uv run ruff check .          # lint
uv run ruff format --check . # format check
uv run mypy src              # type check (strict)
uv run utux --help           # the CLI
```

## Licence

Apache-2.0. See `LICENSE`.
