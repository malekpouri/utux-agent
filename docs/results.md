# Result records from a run

A number is never stored bare, and it never comes from model text. The code
a step runs writes its computed values to `metrics.json` in its output
directory; when the run has ended, utux turns each entry into one result
record in `results.jsonl` ([Claim ledger and result records](claim-ledger.md)).

## The metrics file

`runs/<run_id>/outputs/metrics.json` (more exactly, `metrics.json` in the
step's output directory). The schema is `utux.schemas.metrics.MetricsFile`,
exported as `metrics.schema.json` by `utux schema export`.

```json
{
  "schema_version": 1,
  "entries": [
    {"metric": "AUC", "value": 0.95, "unit": "score", "dataset": "dataset_x",
     "model": "model_a", "split": "test", "tolerance": 0.005},
    {"metric": "rows", "value": 1200.0, "unit": "count", "dataset": "dataset_x",
     "model": null, "split": null, "tolerance": 0.0}
  ]
}
```

| Field of an entry | Form | Meaning |
| --- | --- | --- |
| `metric` | text | What was measured |
| `value` | number, not infinite or NaN | The value |
| `unit` | text | The unit of the value |
| `dataset` | text | The dataset |
| `model` | text or null | The model; null for a value that belongs to none |
| `split` | text or null | The split of the dataset |
| `tolerance` | number, 0 or more | How far a number in the manuscript may differ, in the unit of the value |

Every field is required. `entries` may be empty. No two entries have the same
metric, dataset, model and split (`duplicate_entry`, on the later one).

## Recording a run

`utux.workspace.results.record_run(project, step, result, manifest)` runs
once a run has ended; it takes the run's `RunResult`, which exists only then.
The caller holds the project lock. In this order:

1. It checks that the manifest, the step and the result are of one run, that
   the manifest states the run's exit status and `stopped_by` as the result
   does, that the manifest's `outputs` are exactly the files the run wrote (by project
   path and hash, as `manifest_outputs` lists them), that the run has no
   manifest yet, and that `metrics.json`, if the run wrote one, still has the
   hash the run reported. Otherwise it raises `ResultRecordingError` and
   writes nothing.
2. It writes `runs/<run_id>/manifest.json` with the atomic writer.
3. If a limit stopped the run (`stopped_by` is set, with or without an exit
   status), it stops here: no record is made, even if `metrics.json` exists,
   because a file that may be cut off mid-write cannot become a published
   number. The reason is `stopped_by_limit`.
4. If the run wrote a `metrics.json`, it validates it. An invalid file raises
   `ContractValidationError` with the schema's problems, named on the
   metrics file; no record is written. The manifest stays, since the run
   ended.
5. Each entry becomes one record with the next free result id (`R0001`,
   `R0002`, and so on, at least four digits, continuing after the highest id
   in the file), the run's `run_id`, and the metrics file as `source`.
   `results.jsonl` is rewritten with the atomic writer: the existing lines
   unchanged, the new ones after them. If a line of `results.jsonl` is
   invalid, nothing is added to it.

`record_run` returns a `RunRecording`: the new `records`, and
`not_recorded`, the reason there are none, `stopped_by_limit` or
`no_metrics_file`, which are reasons and not errors. A run that wrote no
`metrics.json` has no records; whether a metric that the method asked for is
missing is checked later (task M1-12).
