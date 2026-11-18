# Evaluation protocol

Version 0, approved by the maintainer and tagged `eval-protocol-v0` on
commit 92daf82 on 2026-11-18, before any system output was scored (M0-14,
`docs/plan/M0.md`).

This document gathers what the specification (`docs/spec.md`), RFC-001 and
RFC-002 fix about the evaluation, in one place. It introduces nothing new.
Every definition cites the section it comes from. The differences the first
draft found between the sources were decided by the maintainer and the
sources updated (section 7). What the sources still leave open is listed in
section 8.

**Protocol v0 sets the initial criteria of H3 only.** The H3 thresholds are
locked after the v0 pilot with a second tag, `eval-protocol-v0.1`. Protocol
v1 fixes the criteria of H1, H2, H4 and H5, the level of the paired tests and
any correction for multiple comparisons, before the first M4 benchmark run.

Sources, in the order of `AGENTS.md` section 2: RFC-001, RFC-002, then the
specification. Section numbers below are those of each document.

## 1. Hypotheses

The evaluation is designed before the system is built, and each hypothesis
names the experiment that can refute it (spec section 1, "Hypotheses";
section 11).

| # | Hypothesis | Experiment that can refute it | Refuted if | Source |
| --- | --- | --- | --- | --- |
| H1 | Verification reduces unsupported claims, invalid citations and wrong numbers in the final output | The same tasks under "multi-agent without verification or routing" and "multi-agent with verification" (spec section 11, "System configurations") | Error rates on the gold set do not drop | Spec section 1, section 11 |
| H2 | Model routing lowers cost without lowering reliability | Routing against a single strong model on the same tasks: the configurations "single strong model" and "multi-agent with model routing" | Cost does not fall, or error rates rise | Spec section 1, section 11 |
| H3 | The verification checks detect planted errors with useful precision and recall | The gold set with planted errors (perturbed items, RFC-002 section 2) scored by the procedure of RFC-002 section 8 | Any of the five thresholds of section 4.1 is missed | Spec section 1; RFC-002 section 8 |
| H4 | Run manifests make results reproducible within a stated tolerance | `reproduce.sh` on a clean machine | Results fall outside tolerance | Spec section 1; tolerance per result record, spec section 7 ("Run manifest") |
| H5 | The full system is more reliable than Denario at comparable cost | Controlled comparison: "multi-agent with all mechanisms" against "Denario", under the Denario comparison protocol | No difference, or worse, on the reliability metrics | Spec section 1, section 11 ("Denario comparison protocol") |

The Denario comparison protocol (spec section 11): pin and report the
Denario version and workflow; same underlying models and same token or USD
budget; same literature and search access, or utux restricted to matching
tools where access differs; same external checkers and the same blind human
graders; all runs, their variance and failures reported.

A same-model reviewer variant runs as one extra ablation (spec section 11).

## 2. Units of evaluation

Each metric is computed on one stated unit (RFC-002 section 7, "Unit of
evaluation").

| Unit | Identifier | Metrics computed on it |
| --- | --- | --- |
| Text unit | `item_id` | S1 |
| Claim-source pair | `pair_id` | S2, S3, S4, S5 |
| Claim | `claim_id` | S6, the human-review flag, the four headline metrics |
| Source group | `source_group` | Not scored; the cluster for splitting and for interval estimates |

A claim with three sources is three pairs but one claim, and is counted once
in every claim-level metric. Scope flags are scored per pair; the union of
flags per claim is a secondary view (RFC-002 section 7).

Ambiguous claims are excluded from the primary numbers and reported
separately, with their count and characteristics (RFC-002 section 5, step 7;
section 8, step 3).

## 3. Metrics

### 3.1 Label metrics

For a label c, a unit is a true positive (TP) when the system and the
reference both assign c, a false positive (FP) when only the system does,
and a false negative (FN) when only the reference does (RFC-002 section 7,
"Definitions").

| Metric | Formula | Unit | Denominator | Source |
| --- | --- | --- | --- | --- |
| Precision of c | TP / (TP + FP) | as scored | units the system labels c | RFC-002 section 7 |
| Recall of c | TP / (TP + FN) | as scored | units the reference labels c | RFC-002 section 7 |
| F1 of c | 2 × precision × recall / (precision + recall) | as scored | — | RFC-002 section 7 |
| Macro-F1 | unweighted mean of F1 over all labels | as scored | number of labels | RFC-002 section 7 |
| False-positive rate of c | FP / (units whose reference label is not c) | as scored | units whose reference label is not c | RFC-002 section 7 |

### 3.2 Headline metrics

Computed on claim status, the output of S6 (RFC-002 section 7, "Headline
metrics").

| Metric | Unit | Numerator | Denominator | Source |
| --- | --- | --- | --- | --- |
| False-verified rate | claim | claims marked `verified` whose reference status is not `verified` | claims the system marks `verified` | RFC-002 section 7; equal to 1 − precision of `verified` |
| Critical miss rate | claim | claims marked `verified` whose reference status is `contradicted` | claims whose reference status is `contradicted` | RFC-002 section 7 |
| Verified coverage | claim | claims marked `verified` whose reference status is `verified` | claims whose reference status is `verified` | RFC-002 section 7; equal to the recall of `verified` |
| Review load | claim | claims the system sends to human review | all claims | RFC-002 section 7 |
| Failure rate | claim | claims left `unverified`, with the reasons | all claims | RFC-002 section 7, "Operational failures"; RFC-001 section 8 |

A claim left `unverified` is neither right nor wrong; it is reported in the
failure rate and counts against verified coverage (RFC-002 section 7).

The false-verified rate is reported twice: on the stratified test split, and
re-weighted to the status mix observed in system-generated items (RFC-002
section 7, "Dependence on the status mix"). The re-weighting combines the
rate at which the system predicts `verified` for each reference status with
the status mix of the system-generated items (RFC-002 section 7). Both it and the standard
false-positive rate of `verified` are reported (RFC-002 section 7).

### 3.3 Per-step metrics

| Step | Unit | Matching rule | Metrics | Source |
| --- | --- | --- | --- | --- |
| S1 | text unit | a predicted claim matches a reference claim when their spans overlap by at least half and both carry the same citations | precision and recall of claims | RFC-002 section 7; RFC-001 section 8 |
| S2 retrieval | pair | a reference evidence span is found when a retrieved passage contains it | recall at k | RFC-002 section 7; k = 8 for full text, all passages for an abstract (RFC-001 section 8) |
| S2 selection | pair | a selected passage is correct when it overlaps a reference span | precision and recall of passages; share of quotes that pass the string check | RFC-002 section 7 |
| S3 and S5 | pair | exact match on the five source-level labels | per-label precision, recall and F1; macro-F1; confusion table; kappa between S3 and S5 | RFC-002 section 7 |
| S4 | pair | each flag scored as its own yes-or-no label | per-flag precision, recall and F1; micro and macro averages | RFC-002 section 7 |
| S6 | claim | exact status match | per-status precision, recall and F1; macro-F1; the four headline metrics | RFC-002 section 7 |
| Human-review flag | claim | compared with `expert_would_review`, and with whether the automatic status was wrong | share of wrong automatic statuses that were flagged; review load | RFC-002 section 7; RFC-001 section 8 |

Later steps are scored twice: end to end, and with reference inputs from the
earlier steps (RFC-002 section 7).

### 3.4 Other components of the gold set

| Component | Metrics | Source |
| --- | --- | --- |
| Citation existence | precision and recall of detecting invalid references; false-alarm rate on real references | RFC-002 section 7; components in section 3 |
| Numeric traceability | precision and recall of detecting a wrong or misattributed number, by error type; false-alarm rate on correct numbers | RFC-002 section 7 |
| Methodological errors | detection rate and false-alarm rate of the reviewer agents, by error type | RFC-002 section 7; spec section 11, "Agent-level tests" |

The unit and denominator of these are not stated beyond the above (section 8).

### 3.5 System-level metrics

| Metric | How it is measured | Unit and denominator as stated | Source |
| --- | --- | --- | --- |
| Citation validity | share of cited references that resolve to a real record with matching metadata | cited references | Spec section 2 |
| Claim support | share of literature claims in the system's final manuscripts judged supported by the cited source, by independent human graders on a sample; an M4 metric of the system's output, not a gold-set metric | literature claims in the sample | Spec section 2 |
| Numeric traceability | share of numbers in the manuscript that match a value in a results artifact | numbers in the manuscript | Spec section 2 |
| Reproducibility | share of runs whose results are regenerated by `reproduce.sh` within tolerance | runs | Spec section 2 |
| Cost and time | USD and wall-clock time per completed project, against a single-strong-model baseline | completed project | Spec section 2 |
| Human interventions | number per run | run | Spec section 11, "Metrics" |
| Reviewer findings confirmed | share of reviewer findings confirmed by a human expert | reviewer findings | Spec section 11, "Metrics" |
| Cost per claim | published with the results | claim | RFC-002 section 8, step 7 |

Each reliability metric except claim support is computed against the
gold-standard set, not the system's own judgement; claim support is judged
by human graders. Detection metrics are reported as precision, recall, F1 and
false-positive rate (spec section 2, "How the metrics are measured").

Bias checks report source concentration (the share of citations from a few
venues, groups or years), whether contrary evidence was retrieved, and
whether the interpretation of results goes beyond what the numbers support
(spec section 11, "Bias checks").

### 3.6 Annotator agreement

| Label | Measures | Source |
| --- | --- | --- |
| Agreement label, status | raw agreement, the confusion table between annotators, Cohen's kappa, Gwet's AC1 | RFC-002 section 5 |
| Scope flags | raw agreement, Cohen's kappa and Gwet's AC1 per flag | RFC-002 section 5 |
| Evidence spans | token-level overlap F1 and intersection over union between the two annotators' spans | RFC-002 section 5 |
| Atomic claims | share of claims matched between annotators | RFC-002 section 5 |

Agreement is computed before any discussion (RFC-002 section 5, step 5),
reported per label and per domain, and is the practical ceiling for the
system's scores on that label (RFC-002 section 5).

Human graders of system outputs grade blind to the system, follow a written
rubric, and their inter-rater agreement is reported (spec section 11, "Human
evaluation").

## 4. Initial thresholds

### 4.1 Hypothesis H3

Initial targets on the v1 test split (RFC-002 section 8, "Proposed
thresholds for hypothesis H3"):

| Metric | Unit and denominator | Initial target |
| --- | --- | --- |
| False-verified rate | claims the system marks `verified` | at most 5%, with the upper end of the 95% interval at most 10% |
| Critical miss rate | claims whose reference status is `contradicted` | at most 2%, with the upper end of the 95% interval at most 5% |
| Verified coverage | claims whose reference status is `verified` | at least 60% |
| Macro-F1 of status | all non-ambiguous claims, four statuses | at least 0.70 |
| Review load | all claims | at most 25% |

Every interval in a threshold is the two-sided 95% exact binomial interval.
A threshold is met only if the stated interval condition holds, and only if
all three runs of the procedure meet it. Comparisons between configurations
rest on the paired test of the procedure (RFC-002 section 8).

With no misses, the upper end of the interval is 1 − 0.025^(1/n): 2.4% for
150 items. On 150 reference-`contradicted` claims the critical-miss
threshold is met with up to 2 misses (1.3%, upper end 4.7%) and missed with
3 (2.0%, upper end 5.7%) (RFC-002 section 3). If the thresholds are missed, the result is reported as
it is, H3 is not supported, and the thresholds are not moved afterwards
(RFC-002 section 8).

### 4.2 Annotation

A kappa of 0.6 is the initial floor for each label, reported with raw
agreement and Gwet's AC1. A label below it after calibration is revised or
merged with a neighbour before the main round (RFC-002 section 5; section 8,
"Accepted defaults").

### 4.3 Other hypotheses

Protocol v0 sets no criteria for H1, H2, H4 or H5. They are fixed in
protocol v1, before the first M4 benchmark run; until then their refutation
conditions are those of section 1.

## 5. Procedure

From RFC-002 section 8, "Procedure":

1. Fix the system configuration and log it.
2. Run the full test split three times, because model output can vary even
   at temperature 0. Report the mean and the range. A threshold is met only
   if all three runs meet it.
3. Compute every metric of section 3 on its stated unit. Exclude `ambiguous`
   claims from the primary numbers and report them separately, with their
   count and characteristics.
4. Report two 95% intervals for the false-verified rate and the critical miss
   rate: an exact binomial interval, which stays valid when a stratum is
   small or no error is observed, and a cluster bootstrap that resamples by
   `source_group`. The source groups cited by one claim form one cluster,
   for the bootstrap and for the split. Other metrics use the cluster
   bootstrap.
5. Break results down by domain, item source, evidence text (abstract or full
   text), hard-case group and error class.
6. Compare configurations on the same items with a paired test: an exact
   McNemar test for paired binary errors, and a paired bootstrap for cost
   and time.
7. Publish the full confusion tables, the failures, the failure rate and the
   cost per claim, not only the summary numbers.

Evaluation runs on the complete set, never on a sample (RFC-002 section 1,
principle 4; RFC-001 section 8). Zero observed errors never supports a claim
that the error rate is zero (RFC-002 section 3).

Baselines for the protocol itself (RFC-002 section 8): one model and one
prompt; S1 to S3 only; the full protocol with the same model in S3 and S5;
human agreement.

Protection of the test split (RFC-002 section 6): the test split is held by
the adjudicator and is not readable by agents or by developers who tune
prompts; test runs go through a script that returns metrics only; prompts,
models, k and decision rules are fixed before a test run; every test run is
logged with the protocol version, prompt versions, model IDs and the gold
release; test results are computed at the end of M2 on v0 and in M4 on v1.

## 6. Lock procedure

The thresholds for H3 are fixed in three stages (RFC-002 section 8):

1. The v0 pilot is used to calibrate the annotation guideline, measure human
   agreement and estimate the sample sizes needed. Its results may inform the
   thresholds.
2. The final thresholds for H3 are recorded and locked after the v0 pilot and
   before the first run on the v1 test split.
3. After v1 test results have been seen, the thresholds do not change.

This version of the protocol, with the initial thresholds of section 4, is
committed and tagged `eval-protocol-v0` before any system output is scored
(`docs/plan/M0.md`, M0-14; spec section 1 and section 12). It sets the
initial criteria of H3 only.

| Version | Tag | When | What it fixes |
| --- | --- | --- | --- |
| v0 | `eval-protocol-v0` | before any system output is scored (done: commit 92daf82, 2026-11-18) | hypotheses, metrics, initial H3 thresholds, procedure |
| v0.1 | `eval-protocol-v0.1` | after the v0 pilot, before the first run on the v1 test split | the locked H3 thresholds (stage 2) |
| v1 | `eval-protocol-v1` | before the first M4 benchmark run | the criteria of H1, H2, H4 and H5, the level of the paired tests, and any correction for multiple comparisons |

After v1 test results have been seen, the H3 thresholds do not change
(stage 3).

## 7. Differences found in the first draft, and how they were decided

The first draft listed these differences between the sources. The
maintainer decided each on 2026-11-18: where an RFC is more precise, it
governs, and the specification was updated to match.

1. **When thresholds are fixed.** As RFC-002 section 8 locks them; the
   specification now says "before any system output is scored".
2. **What refutes H3.** RFC-002's five thresholds; the specification's H3
   row now says so.
3. **Name of the main risk metric.** "False-verified rate" everywhere,
   including RFC-001's tables; the standard false-positive rate of
   `verified` is reported beside it.
4. **S4 metrics.** As in RFC-002 section 7; RFC-001 section 8 refers to it.
5. **Human-review flag.** As in RFC-002 section 7; RFC-001 section 8 aligned.
6. **Intervals.** Every threshold's interval is two-sided 95%. The
   critical-miss threshold gained an upper end of at most 5%, and RFC-002
   section 3 now states the two-sided bounds for its sizes, checked by a
   test.
7. **Claim support.** An M4 metric of the system's final manuscripts, judged
   by independent human graders on a sample; not a gold-set metric.
8. **Numeric traceability.** RFC-002 section 7 gained a false-alarm rate on
   correct numbers.

## 8. Open in the sources

Decided by the maintainer and recorded in RFC-002 sections 7 and 8: the
paired tests, the three-run rule, the re-weighting, and the clusters. Still
open:

- The criteria of H1, H2, H4 and H5, including what counts as "comparable
  cost" (H5) and "error rates do not drop" (H1) in numbers; the level of the
  paired tests; and any correction for multiple comparisons: all fixed in
  protocol v1, before the first M4 benchmark run.
- How the results of the three runs combine with the intervals of step 4,
  beyond the rule that every run must meet a threshold.
- Units and denominators of the citation existence, numeric traceability and
  methodological error metrics beyond section 3.4.

## 9. Choices made by the toolkit

`utux.evalkit` (M0-13) had to decide some details that the sources do not.
They are listed here for review, not as part of the protocol
(`docs/evaluation-toolkit.md`):

- A ratio with a zero denominator is undefined (None), not 0. F1 of a label
  that neither side used is undefined, and macro-F1 averages the labels whose
  F1 is defined.
- An `unverified` prediction is never a TP or FP for any status and is an FN
  for its reference status.
- A pair the system did not assess counts as an FN for its reference label.
- Claims are matched one to one when they cite the same sources and their
  spans share at least half of the longer span's characters.
- Evidence spans are compared over tokens: a run of word characters, or one
  other non-space character; a span covers every token it touches.
- The bootstrap is a percentile interval over clusters of linked items (the
  groups of the split), with a fixed seed. A cluster joins every source
  group cited by an item, which includes those cited by one claim.
- The exact interval is Clopper-Pearson, two-sided.
