# Synthetic gold release

`synthetic_release.jsonl` is synthetic: ten invented items, `G9000` to
`G9009`, one per line, built like the fixtures in `../gold_item` and with the
same caveats. Its labels are not annotation and must never be used as
reference labels.

It exists to test the release check and the group-aware split. Its items are
linked like this, worked out by hand:

| Item | Origin | Source groups | Split | Linked to |
| --- | --- | --- | --- | --- |
| G9000 | natural | sg-synthetic-a | dev | G9001 (its perturbation) |
| G9001 | perturbed from G9000 | sg-synthetic-b | dev | G9000 (its origin) |
| G9002 | natural | sg-synthetic-c | test | G9003 (shares sg-synthetic-c) |
| G9003 | system_generated | sg-synthetic-c, sg-synthetic-d | test | G9002, G9004 |
| G9004 | natural | sg-synthetic-d | test | G9003 (shares sg-synthetic-d) |
| G9005 | natural | sg-synthetic-e | test | G9006 |
| G9006 | perturbed from G9005 | sg-synthetic-e | test | G9005 (origin and group) |
| G9007 | natural | sg-synthetic-f | dev | none |
| G9008 | natural | sg-synthetic-g | test | none |
| G9009 | natural | sg-synthetic-h | test | none |

So the items that must share a split are {G9000, G9001}, {G9002, G9003,
G9004}, {G9005, G9006}, {G9007}, {G9008} and {G9009}. G9001 is attached to a
different paper than its origin, so only the origin link keeps it with
G9000.
