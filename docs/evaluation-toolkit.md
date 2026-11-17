# Agreement, metrics and intervals

`utux.evalkit` scores annotators against each other and the system against
the gold set, following RFC-002, sections 5, 7 and 8. It uses the standard
library only. Nothing in it creates or changes a label, and its results hold
counts and rates only: no item, claim or pair id and no label of an item.

Gold items, releases and the split are described in
[gold-set.md](gold-set.md).

## Agreement between annotators

`utux.evalkit.agreement` works on the raw labels, before adjudication.

| Function | What it computes |
| --- | --- |
| `raw_agreement(pairs)` | The share of units with the same label from both annotators |
| `confusion_table(pairs, labels)` | Counts of each label pair; rows are the first annotator |
| `cohens_kappa(pairs, labels)` | (p_o - p_e) / (1 - p_e), p_e = sum over labels of the product of the two annotators' shares; None when p_e is 1 |
| `gwet_ac1(pairs, labels)` | (p_o - p_e) / (1 - p_e), pi_k = mean of the two shares of label k, p_e = sum pi_k (1 - pi_k) / (Q - 1) over the Q labels |
| `span_overlap(first, second, text)` | Token-level F1 = 2\|A and B\| / (\|A\| + \|B\|) and IoU = \|A and B\| / \|A or B\| |

`match_claims(first, second)` counts the claims of two lists that match one
to one: two claims match when their spans share at least half of the longer
span's characters. Candidate pairs are matched greedily, the largest share
first.

### The token rule for spans

Evidence spans are compared token by token over the stored source text:

- A token is a run of word characters (letters, digits and `_`, as in the
  regular expression `\w+`), or a single character that is neither a word
  character nor white space, such as `%`, `.` or `(`.
- White space is not a token.
- A span covers every token it overlaps by at least one character, so a span
  that cuts a word in half still covers the whole word.

When neither annotator selected a token, F1 and IoU are None; when only one
did, both are 0.

### A release

`annotation_agreement(items, source_texts=None)` applies these to a release:

| Label | Unit | Measures |
| --- | --- | --- |
| Claim extraction | item | first and second list sizes, matched claims, share = 2 matched / (first + second) |
| Status | claim | four statuses: raw agreement, confusion table, kappa, AC1 |
| `expert_would_review` | claim | yes or no: the same |
| Agreement label | pair | five labels: the same |
| Each scope flag | pair | yes or no: the same |
| Evidence spans | pair | mean token F1 and IoU, and the pairs where both are undefined |

The first annotator is the first of `annotation.annotators`. Ambiguous claims
are included, since agreement is measured on everything that was labelled.

Evidence spans are compared only when `source_texts` maps every `source_id`
to its stored text. Each text is checked against the pair's `text_hash`
first, and a missing text or a mismatch is refused (`GoldSetError`), so that
agreement is measured only on the text the annotators read.

## Metrics

`utux.evalkit.metrics.evaluate(items, predictions)` scores the system's
output. `Predictions` holds a `ClaimPrediction` per claim id (status,
`unverified` included; whether it was sent to review; the failure reason
when unverified) and a `PairPrediction` per pair id (agreement label, or None
when the pair was not assessed; scope flags). Every claim and pair needs a
prediction.

For each label c, a unit is a TP when both give c, an FP when only the system
does, and an FN when only the reference does. Precision is TP / (TP + FP),
recall TP / (TP + FN), F1 2TP / (2TP + FP + FN), and the false-positive rate
FP / (units whose reference is not c). A value with a zero denominator is
None. Macro-F1 is the mean F1 over the labels whose F1 is defined; a label
neither side used is left out.

**On claims** (a claim with several sources counts once):

| Metric | Definition |
| --- | --- |
| Status scores | Per status: precision, recall, F1, false-positive rate; macro-F1 |
| False-verified rate | Of the claims marked `verified`, those whose reference is not `verified` |
| Critical miss rate | Of the claims whose reference is `contradicted`, those marked `verified` |
| Verified coverage | Of the claims whose reference is `verified`, those marked `verified` |
| Review load | Of all claims, those sent to review |
| Failure rate | Of all claims, those left `unverified`, with the count of each reason |
| Wrong status flagged | Of the claims given a wrong status, those sent to review |

A claim left `unverified` is neither right nor wrong: it is never a TP or an
FP, it counts as an FN for its reference status, and so against verified
coverage. Rates carry their numerator and denominator, for intervals.

**On pairs**: agreement label scores over the five labels (S3 and S5), and
each scope flag as its own yes-or-no label (S4), with micro averages (pooled
counts) and macro-F1.

**Ambiguous claims** and their pairs are excluded from the primary metrics
and scored separately (`ambiguous_claims`, `ambiguous_pairs`).

**Metrics only.** `metrics_only(items, predictions)` returns the evaluation
as a JSON object of numbers and prints nothing. It is the mode for runs on
the test split.

## Intervals

`utux.evalkit.intervals`:

- `exact_binomial_interval(x, n, alpha=0.05)` is the Clopper-Pearson
  interval. With no events the upper bound is 1 - (alpha/2)^(1/n); with n
  events the lower bound is (alpha/2)^(1/n). Otherwise the bounds solve
  P(X >= x | lower) = alpha/2 and P(X <= x | upper) = alpha/2, found by
  bisection.
- `cluster_bootstrap(clusters, statistic, replicates=..., seed=...)`
  resamples whole clusters with replacement and returns the percentile
  interval: the replicates at indices floor(alpha/2 m) and
  ceil((1 - alpha/2) m) - 1 of the m sorted defined replicates. Replicates
  whose statistic is undefined are counted, not used. The same inputs and
  seed give the same interval.
- `claim_clusters(items)` names the cluster of each claim: the group of
  linked items from the split (shared source groups and perturbation
  origins).

The false-verified rate and the critical miss rate are reported with both
intervals; other metrics with the cluster bootstrap (RFC-002, section 8).
