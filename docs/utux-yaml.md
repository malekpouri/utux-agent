# `utux.yaml`: project configuration

Every project has one `utux.yaml` in its root directory. The schema is
`utux.schemas.project_config.ProjectConfig`. The fields come from the
specification, sections 5, 7, 9 and 10.

## Smallest valid file

```yaml
schema_version: 1
data_policy: local_only
budget:
  total_usd: 20
```

These three values are required. Everything else has a default.

## Fields

| Field | Type | Default | Meaning |
| --- | --- | --- | --- |
| `schema_version` | integer | none; required | Version of this schema. Currently `1` |
| `data_policy` | `external_allowed` or `local_only` | none; required | What may be sent to external services. There is no default on purpose |
| `budget.total_usd` | number above 0 | none; required | Total budget of the project in US dollars |
| `budget.allow_unknown_cost` | boolean | `false` | Whether calls to an external provider may continue after one of its calls reported no cost. See [Cost and budget](cost.md) |
| `budget.per_stage_usd` | mapping of stage to number above 0 | empty | Budget per stage. Stages: `ideation`, `literature`, `methodology`, `implementation`, `experiment`, `writing`. No stage budget may exceed `budget.total_usd`; their sum may |
| `profile` | name | `default` | The named combination of implementations |
| `local_server.base_url` | `http` or `https` URL with a host, without a user name or password | `http://localhost:11434/v1` | The OpenAI-compatible server of the `local` profile. Whether it is external is derived from the host, so a server on another machine counts as external. Codes `invalid_url` and `credentials_in_url`; the value is not repeated in an error |
| `domain_pack` | name | `generic` | The domain pack |
| `oversight.mode` | `guided` or `auto` | `guided` | Which approval gates are on |
| `oversight.gates.idea` | boolean | follows the mode | Switch for the idea gate |
| `oversight.gates.method` | boolean | follows the mode | Switch for the method gate |
| `oversight.gates.experiment_plan` | boolean | follows the mode | Switch for the experiment-plan gate |
| `oversight.gates.final_manuscript` | `true` | always on | May be stated as `true`. `false` is an error |
| `verification.enabled` | boolean | `true` | The verification toggle |
| `ai_disclosure.draft` | boolean | `true` | Whether an AI-use disclosure statement is drafted |
| `resources.cpus` | number above 0 | not set | CPU limit per run |
| `resources.memory_mb` | integer above 0 | not set | Memory limit per run |
| `resources.gpus` | integer, 0 or more | not set | GPU limit per run |
| `resources.wall_clock_seconds` | integer above 0 | not set | Time limit per run |
| `resources.disk_mb` | integer above 0 | not set | Disk limit per run |
| `resources.max_processes` | integer above 0 | not set | Process-count limit per run |
| `resources.output_mb` | integer above 0 | not set | Size limit of a run's output directory, in MiB; the executor's default is 1024. See [The sandbox](sandbox.md) |
| `models.tiers` | mapping of `light`, `standard`, `strong` to a model id | empty | Model for each tier. What is not set comes from the profile |
| `models.roles` | mapping of role name to tier | empty | Tier for each agent role |
| `workflow.retry_cap` | integer, 0 or more | `2` | How many times a run may be routed back to one stage before it pauses and asks; the same cap for every loop. See [How a run works](run.md) |

Names (`profile`, `domain_pack`, role names) are lower-case letters, digits,
`-` and `_`, starting with a letter.

A change of any setting is recorded as a `setting_changed` event by the
next command that writes to the project ([Creating a project](project.md)).

In `guided` mode every gate is on. In `auto` mode only the final-manuscript
gate is on. A per-gate switch overrides the mode for that gate.

## A complete file

Every field set, including the two added in M1, `local_server.base_url` and
`budget.allow_unknown_cost`:

```yaml
schema_version: 1
profile: local
domain_pack: bio-pilot
data_policy: external_allowed
local_server:
  base_url: http://127.0.0.1:8080/v1
budget:
  total_usd: 50
  allow_unknown_cost: true
  per_stage_usd:
    ideation: 2
    literature: 5
    methodology: 5
    implementation: 10
    experiment: 20
    writing: 8
oversight:
  mode: auto
  gates:
    idea: true
    method: false
    experiment_plan: true
    final_manuscript: true
verification:
  enabled: false
ai_disclosure:
  draft: false
resources:
  cpus: 4
  memory_mb: 8192
  gpus: 0
  wall_clock_seconds: 3600
  disk_mb: 20480
  max_processes: 256
  output_mb: 2048
models:
  tiers:
    light: example/light-model
    standard: example/standard-model
    strong: example/strong-model
  roles:
    planner: strong
    writer: standard
    summariser: light
workflow:
  retry_cap: 3
```

## Errors

An invalid file is rejected with one line per problem, in the form
`file: field: reason`. All problems are listed, not only the first.

```text
utux.yaml: colour: unknown key
utux.yaml: data_policy: required field is missing
utux.yaml: oversight.gates.final_manuscript: the final-manuscript gate is always on and cannot be switched off
```

- Unknown keys are errors, at every level (`unknown_key`).
- A key that appears twice in one mapping is an error (`duplicate_key`).
- A stage budget above `budget.total_usd` is reported on that stage
  (`stage_budget_exceeds_total`).
- `oversight.gates.final_manuscript: false` is an error (`final_gate_off`).
- A file with a newer `schema_version` than this version of utux supports is
  refused, and nothing else in it is judged.
