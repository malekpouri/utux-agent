# utux Agent

utux Agent is an open-source, modular multi-agent framework that takes a
computational research project from idea to reviewed manuscript. Its defining
property is scientific reliability: every claim in an output must be traceable
to checked evidence or to a computed result.

## Status

The project is in milestone M0. What works today:

- `utux init` creates a project: its directory tree, `utux.yaml`, the event
  log with its first event, and a git repository with a first commit.
- `utux schema export <dir>` writes a JSON Schema file for every file
  contract.
- The schemas of all file contracts, the append-only event log and the
  `ModelProvider` interface exist as library code.

What does not exist yet: validating a project, calling a model, cost
accounting, and every pipeline stage. See `docs/plan/M0.md` for what is being
built.

## Quick start

```bash
uv sync
uv run utux init my-project --budget-usd 20 --data-policy local_only
```

`--budget-usd` and `--data-policy` are required and have no default. See
[Creating a project](docs/project.md).

## Documents

- [Technical Product Specification](docs/spec.md)
- [RFC-001: Claim Support Verification Protocol](docs/rfc/RFC-001.md)
- [RFC-002: Gold Standard Dataset and Evaluation Protocol](docs/rfc/RFC-002.md)
- [Architecture decision records](docs/adr/)
- [Creating a project](docs/project.md)
- [`utux.yaml` reference](docs/utux-yaml.md)
- [Schema conventions](docs/schema-conventions.md)
- [Artifact metadata and content hashes](docs/artifact-metadata.md)
- [The `ModelProvider` interface](docs/model-provider.md)
- [Events and the event log](docs/event-log.md)
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
