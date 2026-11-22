# Toy task: two classifiers on the breast cancer dataset

The end-to-end run of milestone M1 (task M1-16). It takes one project
through stages 3 to 5 (methodology, implementation, experiment) with a
real model in `guided` mode, with you answering each gate.

**The task.** Compare logistic regression and a decision tree on the
breast cancer dataset that ships with scikit-learn, by accuracy under
5-fold cross-validation. The dataset is bundled in the library, so the
run needs no network inside the sandbox.

**The inputs.** `inputs/question.md` holds the idea, as a question, and
`inputs/data.md` the data description. The methodologist reads every
`inputs/*.md` file of the project; `idea.md` itself is written by stage 1,
which comes in M3.

## Before you start

- Run every command below from the root of the utux repository, after
  `uv sync`. In M1, `utux run` finds the pack's prompts and image in the
  repository's `packs/` directory.
- **Skip `utux image build`.** The recorded image is already on your
  machine. Check that Docker has the image whose id is recorded:

  ```bash
  docker image inspect $(cat packs/generic/image/digest.txt)
  ```

  It prints the image's details. If it prints `No such image` instead, stop
  here and report it: building the image would write another id into
  `digest.txt`.
- Set `OPENROUTER_API_KEY` in your environment. The `default` profile sends
  every model call to OpenRouter. Never write the key into a file of the
  project.
- The model calls are real, paid calls. The budget you choose below is the
  most the run may spend; a run that reaches it pauses and asks you.

## The commands

**1. Create the project and give it the inputs.** The project goes beside
the repository, in `../utux-toy`, so that its own git repository is not
inside the repository's. `CHOOSE_A_BUDGET` is a placeholder: replace it
with the budget you choose, in US dollars, for example `2`.

```bash
BUDGET_USD=CHOOSE_A_BUDGET
uv run utux init ../utux-toy --budget-usd "$BUDGET_USD" --data-policy external_allowed
cp examples/toy-classification/inputs/*.md ../utux-toy/inputs/
```

**2. Give the roles a model.** The three roles (methodologist, implementer,
analyst) use the `standard` tier unless `models.roles` says otherwise. In
`../utux-toy/utux.yaml`, replace this line:

```yaml
  tiers: {}
```

with this, putting an OpenRouter model id, such as `provider/model`, in
place of the placeholder:

```yaml
  tiers:
    standard: REPLACE_WITH_THE_MODEL_ID_FOR_THE_STANDARD_TIER
```

To give a role another tier, add it under `roles`, for example
`methodologist: strong`, and give `strong` a model under `tiers`. Leave
`oversight.mode` at `guided`: then both gates of the run ask you.

**3. Check the project, then run it gate by gate.**

```bash
uv run utux validate ../utux-toy
uv run utux run ../utux-toy                          # exit status 3: paused at the method gate, a-000001
uv run utux approve ../utux-toy a-000001 approve
uv run utux run ../utux-toy                          # exit status 3: paused at the experiment-plan gate, a-000002
uv run utux status ../utux-toy
uv run utux approve ../utux-toy a-000002 approve
uv run utux run ../utux-toy                          # exit status 0: finished
```

**4. Check the result and the cost.**

```bash
uv run utux validate ../utux-toy
uv run utux cost ../utux-toy
```

## Answering each gate

`utux run` prints the id of the request it is waiting for and the command
that answers it. In a new project the first request is `a-000001` and the
second `a-000002`; after a rejection or a route back, the ids go on from
there, so always use the id that `utux run` printed.

- **The method gate** (`a-000001`) asks you to approve `method.md`. Read
  `../utux-toy/method.md`: numbered steps, each with a success criterion and
  its `- metric:` lines. The metrics it names are the ones the run must
  report.
- **The experiment-plan gate** (`a-000002`) asks you to approve the code,
  `../utux-toy/code/main.py`, and the execution it will run in the sandbox.
  `utux status` shows that execution beside the request: command, image
  digest, read-only paths and limits. Check that the code computes the
  metrics, rather than writing numbers into the code.

Each gate takes one of three answers:

```text
uv run utux approve ../utux-toy <id> approve
uv run utux approve ../utux-toy <id> reject --feedback "What to change, in a sentence or two."
uv run utux approve ../utux-toy <id> edit
```

- `approve` continues the run with the file as it is.
- `reject --feedback "..."` runs the stage again with your feedback and
  then asks again, with a new id. Each rejection counts against the retry
  cap, `workflow.retry_cap`, default 2.
- `edit`: save your change to the file first, then answer `edit`. Your
  version becomes the next version of the file, made by you, and the run
  continues with it.

The answer records your login name as `human:<name>`. That id stays in the
project and is shared through git; give another with `--by ID`.

The run can also pause for two reasons that are not gates. `utux status`
shows which:

- **`budget_exhausted`**: the budget is spent. Raise `budget.total_usd` in
  `../utux-toy/utux.yaml`, then approve the request to continue, or reject
  it with feedback to stop.
- **`retry_limit`**: the check after the analysis sent the run back more
  often than the retry cap allows. Approve to allow one more attempt, or
  reject to stop.

## What each exit status means

| Exit status of `utux run` | Meaning | What to do |
| --- | --- | --- |
| 0 | The run completed | Go on to step 4 |
| 3 | The run paused for an approval | Answer the request it names, then run `utux run` again |
| 1 | An error | Read the message, and `utux status ../utux-toy`. After a crash, see "After a crash" in `docs/run.md`. Report it |

The last `utux run` can also exit with 3 instead of 0. This happens when
the check after the analysis sends the run back:

- to implementation, when the run failed, or a recorded value is written
  into the code. The code is rewritten and the experiment-plan gate asks
  again;
- to methodology, when a metric the method names has no result.

Answer the new request the same way. The other commands exit with 0 on
success and 1 on an error.

## What to report

- The output of `uv run utux cost ../utux-toy`.
- Whether `uv run utux validate ../utux-toy` passes.
- Whether every number in `../utux-toy/results.md` stands beside its
  result id, such as `[R0001]`. Check also that each of those records in
  `../utux-toy/results.jsonl` names a run whose manifest exists, as
  `runs/<run_id>/manifest.json`. `utux validate` checks the second.
- Anything that went wrong, with the output of `utux status ../utux-toy`.
  Each is filed as a task for M1 or M2.
