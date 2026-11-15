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
| `budget.per_stage_usd` | mapping of stage to number above 0 | empty | Budget per stage. Stages: `ideation`, `literature`, `methodology`, `implementation`, `experiment`, `writing`. No stage budget may exceed `budget.total_usd`; their sum may |
| `profile` | name | `default` | The named combination of implementations |
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
| `models.tiers` | mapping of `light`, `standard`, `strong` to a model id | empty | Model for each tier. What is not set comes from the profile |
| `models.roles` | mapping of role name to tier | empty | Tier for each agent role |

Names (`profile`, `domain_pack`, role names) are lower-case letters, digits,
`-` and `_`, starting with a letter.

In `guided` mode every gate is on. In `auto` mode only the final-manuscript
gate is on. A per-gate switch overrides the mode for that gate.

## Errors

An invalid file is rejected with one line per problem, in the form
`file: field: reason`. All problems are listed, not only the first.

```text
utux.yaml: colour: unknown key
utux.yaml: data_policy: required field is missing
utux.yaml: oversight.gates.final_manuscript: the final-manuscript gate is always on and cannot be switched off
```

- Unknown keys are errors, at every level.
- A key that appears twice in one mapping is an error.
- A file with a newer `schema_version` than this version of utux supports is
  refused, and nothing else in it is judged.
