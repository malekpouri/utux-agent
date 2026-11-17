# Fixture for cost accounting

`events.jsonl` is synthetic. It was written for the tests of
`utux.budget.accounting` and does not come from a real run; the providers
`synthetic-external` and `synthetic-local` do not exist. The totals it must
give are computed by hand and written out in
`tests/unit/test_cost_accounting.py`.

| Event | Stage | Actor | What it is | Counts as |
| --- | --- | --- | --- | --- |
| e-000001 | none | human:synthetic | project_created | not a model call |
| e-000002 | ideation | agent:ideator | external, ok, 0.0125 USD | known cost |
| e-000003 | ideation | agent:ideator | external, ok, 0.0031 USD | known cost |
| e-000004 | methodology | agent:planner | external, ok, 0.2 USD | known cost |
| e-000005 | methodology | agent:planner | local, ok, no cost | local, not billed |
| e-000006 | methodology | agent:reviewer | external, ok, no cost | unknown cost |
| e-000007 | literature | agent:searcher | external, error, no cost | unknown cost |
| e-000008 | writing | agent:writer | external, refused | refused, no call made |
| e-000009 | none | system:utux | external, ok, 0.0000021 USD | known cost |
| e-000010 | none | human:synthetic | setting_changed | not a model call |
| e-000011 | ideation | agent:ideator | local, ok, 0 USD | known cost of zero |
| e-000012 | literature | agent:searcher | external, error `model_rate_limit` | failed, not billed |
| e-000013 | none | system:utux | external, error `model_authentication` | failed, not billed |
| e-000014 | writing | agent:writer | external, error `model_request_rejected` | failed, not billed |
| e-000015 | ideation | agent:ideator | external, error `interrupted` | unknown cost |
| e-000016 | methodology | agent:planner | local, error `model_unavailable` | local, not billed |
