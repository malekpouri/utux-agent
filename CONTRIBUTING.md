# Contributing to utux Agent

Thank you for your interest. utux Agent is in early development (milestone
M0, see the [README](README.md)), so the most useful contributions now are
bug reports, reviews of the documents, and small fixes.

## Before you start

- Read [`AGENTS.md`](AGENTS.md). It is written for coding agents, but it is
  also the rule book for people: which documents decide what, how a task is
  done, the code conventions, the testing rules and the definition of done.
- The documents in `docs/` rank in this order: accepted decisions in
  `docs/adr/`, then RFC-001, RFC-002, the specification and the plans. Closed
  decisions are not reopened in a pull request. If you think one is wrong,
  open an issue with the argument.
- Work is planned in `docs/plan/`. Before starting a feature, check that it
  belongs to the current milestone, or open an issue first.

## Setting up

You need Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and git.

```bash
git clone https://github.com/malekpouri/utux-agent.git
cd utux-agent
uv sync
```

## The checks

All four must pass before a pull request is merged, and CI runs them on
every pull request:

```bash
uv run pytest                  # unit and integration tests, no network
uv run ruff check .            # lint
uv run ruff format --check .   # format
uv run mypy src                # strict type check
```

## Tests

- Tests are written first, from the acceptance criteria, and shown to fail
  before the change is made. A bug fix comes with a test that fails without
  it.
- Tests never reach the network or call a real model. Use the scripted
  providers in `utux.providers.scripted`.
- A test that needs the network or an API key is marked `live`; it is
  deselected by default and never runs in CI. Only the maintainer runs live
  tests.
- Every schema has valid and invalid fixtures and a round-trip test. Every
  fixture is synthetic, says so, and contains no key, account identifier or
  personal data.
- Do not delete, skip or weaken a test to make a change pass. If a test is
  wrong, say why in the pull request.

## Pull requests

- One task per branch and per pull request.
- Small commits with imperative subjects, referencing the task id, for
  example `Add event log writer (M0-05)`. Refactoring and behaviour changes go
  in separate commits.
- The description states what changed, how it was tested (including the
  failing run before the change), and anything left open.
- Public behaviour is documented: docstrings, and `docs/` or the README when
  it is visible to users.

## Dependencies

Ask in an issue before adding a runtime dependency. State what it is for, its
licence, how many packages it adds, what it does when imported, and any
security incident in the last twelve months. Only permissive licences
(Apache-2.0, MIT, BSD, ISC, PSF-2.0) are accepted in the core. The standard
library is preferred when the difference is small.

## Scientific integrity

The value of utux lies in trust in its outputs, so some changes are never
accepted:

- weakening or special-casing a verification check to make a test, a demo or
  a benchmark pass;
- code in which a model output sets a claim's status directly;
- creating, editing or inferring gold-standard labels, or exposing the gold
  `test` split; labels are made by human annotators only (RFC-002);
- changing evaluation thresholds or metric definitions without a written
  proposal;
- presenting invented data as real.

## Security

Never put an API key in a file, a log, a test or an issue. To report a
vulnerability, follow [SECURITY.md](SECURITY.md), not a public issue.

## Licence

utux Agent is licensed under Apache-2.0. By contributing, you agree that
your contribution is licensed under the same terms.
