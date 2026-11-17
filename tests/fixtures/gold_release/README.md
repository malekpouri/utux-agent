# Synthetic gold release

`synthetic_release.jsonl` is synthetic: ten invented items, `G9000` to
`G9009`, one per line, built like the fixtures in `../gold_item` and with the
same caveats. Its labels are not annotation and must never be used as
reference labels.

It exists to test the release check, the group-aware split and the split
report. Its items, worked out by hand:

| Item | Origin | Source groups | Split | Domain | Hard case | Claim status | Pairs: evidence text, flags |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G9000 | natural | sg-synthetic-a | dev | ml | none | verified | full text, none |
| G9001 | perturbed from G9000 | sg-synthetic-b | dev | ml | negation_or_hedge | partially_supported | full text, overgeneralisation |
| G9002 | natural | sg-synthetic-c | test | biomedicine | none | verified | abstract, none |
| G9003 | system_generated | sg-synthetic-c, sg-synthetic-d | test | ml | none | contradicted | full text, direction_mismatch; abstract, direction_mismatch and magnitude_mismatch |
| G9004 | natural | sg-synthetic-d | test | biomedicine | abstract_vs_full_text | insufficient_evidence | abstract, none |
| G9005 | natural | sg-synthetic-e | test | ml | none | verified | full text, none |
| G9006 | perturbed from G9005 | sg-synthetic-e | test | ml | none | contradicted | full text, direction_mismatch |
| G9007 | natural | sg-synthetic-f | dev | biomedicine | none | verified | abstract, none |
| G9008 | natural | sg-synthetic-g | test | ml | none | partially_supported | full text, metric_mismatch |
| G9009 | natural | sg-synthetic-h | test | ml | none | verified | full text, none |

Each item has one claim; G9003's claim has two pairs. In the perturbed
items the two annotators' raw entries differ and are adjudicated; in the
others they agree.

The items that must share a split are {G9000, G9001}, {G9002, G9003,
G9004}, {G9005, G9006}, {G9007}, {G9008} and {G9009}: G9003 shares a group
with G9002 and another with G9004, and a perturbed item stays with its
origin. G9001 is attached to a different paper than its origin, so only the
origin link keeps it with G9000.
