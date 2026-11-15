# utux Agent

utux Agent is an open-source, modular multi-agent framework that takes a
computational research project from idea to reviewed manuscript. Its defining
property is scientific reliability: every claim in an output must be traceable
to checked evidence or to a computed result.

## Status

This is a stub. The project is at the start of milestone M0. Only the
repository scaffold exists: the `utux` command prints its help and version and
does nothing else yet. See `docs/plan/M0.md` for what is being built.

## Documents

- [Technical Product Specification](docs/spec.md)
- [RFC-001: Claim Support Verification Protocol](docs/rfc/RFC-001.md)
- [RFC-002: Gold Standard Dataset and Evaluation Protocol](docs/rfc/RFC-002.md)
- [Architecture decision records](docs/adr/)
- [`utux.yaml` reference](docs/utux-yaml.md)
- [Schema conventions](docs/schema-conventions.md)
- [Artifact metadata and content hashes](docs/artifact-metadata.md)
- [The `ModelProvider` interface](docs/model-provider.md)

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
