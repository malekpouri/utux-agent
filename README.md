# utux Agent

utux Agent is an open-source, modular multi-agent framework that takes a
computational research project from idea to reviewed manuscript. Its defining
property is scientific reliability: every claim in an output must be traceable
to checked evidence or to a computed result.

## Status

This is a stub. The project is at the start of milestone M0. Only the
repository scaffold exists: the `utux` command prints its help and version and
does nothing else yet. See `docs/plan/M0.md` for what is being built.

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
