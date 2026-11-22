# utux Agent

utux Agent is an open-source, modular multi-agent framework that takes a
computational research project from idea to reviewed manuscript. Its defining
property is scientific reliability: every claim in an output must be traceable
to checked evidence or to a computed result.

## What works today

The project is in milestone M1, the execution spike. It runs stages 3 to 5
of the pipeline (methodology, implementation, experiment) with three model
roles and model-written code in a hardened Docker sandbox; the other stages,
claim verification and the reviewers come later. What works:

- `utux init` creates a project: its directory tree, `utux.yaml`, the event
  log with its first event, and a git repository with a first commit.
- `utux validate` checks every contract file of a project and reports every
  problem.
- `utux model ping` sends a short prompt to the model of a tier and prints
  the tokens and the cost. Every model call is logged as a `model_call`
  event, with hashes of what was sent instead of the text.
- `utux cost` prints the known cost of a project against its budget, per
  stage and per actor. A model call is refused once the budget is exhausted,
  and every call to an external provider is refused under the data policy
  `local_only`.
- `utux log repair` saves aside an incomplete last line of the event log,
  left by an interrupted write, and records the repair.
- Commands that write to a project hold a project lock, so two never run at
  once, and record every hand edit of `utux.yaml` as a `setting_changed`
  event before they act.
- `utux schema export <dir>` writes a JSON Schema file for every file
  contract.
- `utux run`, `utux approve`, `utux status` and `utux unlock` drive a run
  through methodology, implementation and experiment, answer its approval
  gates, show where it is, and remove a lock left by a crash
  ([Running a project from the command line](docs/cli-runs.md)).
- As library code: the schemas of all file contracts, the append-only event
  log, the internal `Executor` contract with its conformance suite, the
  `ModelProvider` interface with one OpenAI-compatible client
  (OpenRouter, a direct OpenAI key, or a local server such as Ollama), and
  the evaluation toolkit for the gold-standard set (item schema, group-aware
  split, annotator agreement, metrics and intervals).

## What is planned

Following the roadmap in section 12 of the [specification](docs/spec.md):

- **M0, in progress:** the evaluation protocol and gold set v0, written and
  labelled by people.
- **M1, in progress:** stages 3 to 5 run as described above; what remains is
  the maintainer's end-to-end run of the toy task with a real model. See
  [the M1 plan](docs/plan/M1.md).
- **M2:** claim verification against the literature, scored on the gold set.
- **M3:** the full pipeline from question to reviewed manuscript, with
  approval gates and model routing.
- **M4:** the benchmark against the hypotheses of the specification.
- **M5:** the v1 release.

Nothing on this list beyond what is described above exists yet.

## Requirements

- Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and git 2.28 or
  newer.
- Linux. utux is tested on Linux. macOS should work but is not tested in CI.
  Windows is not supported: the project lock relies on POSIX process checks.

## Quick start

You need the requirements above.

```bash
git clone https://github.com/malekpouri/utux-agent.git
cd utux-agent
uv sync
```

Create a project and check it:

```bash
uv run utux init my-project --budget-usd 20 --data-policy external_allowed
uv run utux validate my-project
```

`--budget-usd` and `--data-policy` are required and have no default. See
[Creating a project](docs/project.md). Under `--data-policy local_only`,
every call to an external provider such as OpenRouter is refused.

`utux model ping` and `utux run` need models under `models.tiers` in
`utux.yaml`: the ping uses the tier it is given, and the roles of a run use
`standard` unless `models.roles` says otherwise.
`utux init` already writes a `models` section with an empty tier mapping, so
edit that section in `my-project/utux.yaml`. Replace this line:

```yaml
  tiers: {}
```

with:

```yaml
  tiers:
    light: openai/gpt-4o-mini
    standard: openai/gpt-4o-mini
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

### Run the toy task

The toy task compares two classifiers on a dataset that ships with
scikit-learn, so the run needs no network inside the sandbox. Describe it in
the project's `inputs/` directory.

Write `my-project/inputs/question.md`:

```markdown
# Question

On the breast cancer dataset that ships with scikit-learn, does logistic
regression classify tumours more accurately than a decision tree, measured
by accuracy under 5-fold cross-validation?
```

Write `my-project/inputs/data.md`:

```markdown
# Data

The Wisconsin breast cancer dataset, loaded in the code with
`sklearn.datasets.load_breast_cancer()`: 569 samples, 30 numeric features,
and a binary label (malignant or benign). It is bundled with scikit-learn;
nothing is downloaded.
```

Build the image of the generic pack once. This needs Docker and the network,
and records the image's id in `packs/generic/image/digest.txt`; a run uses
only that image. Then run the three stages:

```bash
uv run utux image build
uv run utux run my-project                     # exit status 3: paused at the method gate, a-000001
uv run utux status my-project
uv run utux approve my-project a-000001 approve
uv run utux run my-project                     # exit status 3: paused at the experiment-plan gate, a-000002
uv run utux approve my-project a-000002 approve
uv run utux run my-project                     # exit status 0: finished
uv run utux validate my-project
```

`utux run` exits with 0 when the run completed, 1 on an error and 3 when it
paused for an approval; the message names the request and the command that
answers it. Read `my-project/method.md` before you approve `a-000001`, and
`my-project/code/main.py`, with the execution `utux status` shows, before
you approve `a-000002`. To change a file instead, edit it and answer with
`edit`; to ask for another version, answer `reject --feedback "..."`. The
model calls of the run are real, paid calls. The results are in
`my-project/results.md` and `my-project/results.jsonl`. See
[Running a project from the command line](docs/cli-runs.md) and
[How a run works](docs/run.md).

See what the project has spent, as text or as JSON:

```bash
uv run utux cost my-project
uv run utux cost my-project --json
```

See [Cost and budget](docs/cost.md).

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
- [The `Executor` interface](docs/executor.md), [the sandbox](docs/sandbox.md) and [the image of a pack](docs/pack-image.md)
- [Events and the event log](docs/event-log.md)
- [Logged model calls and `utux model ping`](docs/model-calls.md)
- [Cost and budget: `utux cost`](docs/cost.md)
- [Gold items, releases and the split](docs/gold-set.md)
- [Agreement, metrics and intervals](docs/evaluation-toolkit.md)
- [Evaluation protocol, draft](docs/eval/protocol.md)
- [Annotation guideline, draft](docs/eval/annotation-guideline.md)
- [Worked example of a gold item](docs/eval/example-item.md)
- [M0 plan](docs/plan/M0.md) and [M1 plan](docs/plan/M1.md)
- [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md)
- [How a run works](docs/run.md)
- [Claim ledger and result records](docs/claim-ledger.md) and [result records from a run](docs/results.md)
- [Run manifest, approvals, source record and schema export](docs/contracts.md)

## Development

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

```bash
uv sync                      # install dependencies from uv.lock
uv run pytest                # unit and integration tests (no network)
uv run pytest -m docker      # sandbox tests (need Docker and a local image)
uv run ruff check .          # lint
uv run ruff format --check . # format check
uv run mypy src              # type check (strict)
uv run utux --help           # the CLI
```

## Licence

Apache-2.0. See `LICENSE`.
