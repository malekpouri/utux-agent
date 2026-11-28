# Annotation guideline for the utux gold-standard set

Version 0.1, draft. Save as `docs/eval/annotation-guideline.md`.

This draft is written from RFC-001 (claim support verification) and RFC-002
(gold-standard set). It must be reviewed by the maintainer and the
adjudicator, and revised after the calibration round, before the main round
starts. Every change after version 1.0 is listed in the changelog at the end.

All examples in this guideline are invented. They describe no real paper,
method or result, and must never be used as reference labels.

---

## 1. What you are judging

You are shown a short piece of scientific writing that cites one or more
sources, and the stored text of each cited source. You judge one thing:

**Does the cited source support the claim as it is stated?**

You do **not** judge whether the claim is true, whether the source's result
is correct, or whether the source is a good paper. A claim can be true and
still not be supported by the source it cites. A claim can be supported by a
source whose result later turned out to be wrong.

Your labels become the reference answers that the utux system is scored
against. Consistency between annotators matters as much as being right, so
follow the rules here even where you would have judged differently. When you
disagree with a rule, write that in the note field; do not work around it.

## 2. Rules of independence

These rules keep the reference labels independent of the system and of each
other. Breaking one can make a whole release unusable.

1. Do not use any AI tool while annotating: no chat assistants, no AI
   summaries, no AI translation. A dictionary is fine.
2. Judge each source only from the text you are given. Do not look up the
   paper, other versions of it, or other papers. Use your domain knowledge to
   understand the text, not to fill in what it does not say.
3. Do not discuss items with the other annotator until both of you have
   submitted. Calibration discussions are the exception (section 9).
4. Do not try to work out how an item was made. Some items were edited on
   purpose to contain an error; you are not told which, and guessing does not
   help you label them.
5. Do not look at any output of the utux system.
6. Keep the items confidential. Do not copy them out of the annotation tool
   or share them, during or after the project.

If you break a rule by accident, tell the adjudicator. The item is then
re-assigned; nothing else happens.

## 3. What you see

For each item:

- **The text unit**: one or a few sentences that make claims and cite sources.
- **For each cited source**: its stored text, either the abstract only or the
  full text. The tool shows which.
- **An extraction quality note** for each source: `clean`, `good` or
  `degraded`. Degraded text came from scanning or a broken PDF and may contain
  errors, especially in numbers and tables.

Each item is labelled in two phases, at different times. You finish phase 1
for a batch of items, the claim lists are adjudicated, and then you label the
fixed claims in phase 2.

---

## 4. Phase 1: claim extraction

### 4.1 What a claim is

A claim is one factual assertion that could be supported or contradicted by a
source. List every claim in the text unit.

A good claim is:

- **Atomic.** It asserts one thing. If one part could be true while another
  is false, split it.
- **Self-contained.** It can be understood without the surrounding text.
  Replace pronouns and abbreviations with what they refer to, using only
  information from the text unit.
- **Faithful.** It keeps the qualifiers of the original: "on dataset X",
  "in most settings", "may". Do not strengthen or weaken it.
- **Linked to its citations.** Record which cited sources the claim relies
  on. When a citation sits at the end of a sentence with several claims,
  assign it to every claim in that sentence, unless the wording shows it
  belongs to only one.

### 4.2 Splitting

| Text | Claims |
| --- | --- |
| Method A is faster and more accurate than method B [3]. | (1) Method A is faster than method B. (2) Method A is more accurate than method B. Both cite [3]. |
| A reached 91% accuracy on X, which is 4 points above B [5]. | (1) Method A reached 91% accuracy on dataset X. (2) Method A's accuracy on dataset X is 4 points above method B's. Both cite [5]. |
| Pretraining helps small models [2] but not large ones [7]. | (1) Pretraining helps small models, citing [2]. (2) Pretraining does not help large models, citing [7]. |

Do not split a single comparison into its two sides. "A outperforms B" is one
claim.

### 4.3 What not to list

- Statements about the current paper's own work ("we propose", "in this
  paper we show"), unless they also assert something attributed to a citation.
- Questions, plans, motivations and opinions that make no factual assertion.
- Pure section signposting ("as discussed below").

A factual assertion with no citation is still listed. It has no sources and
gets the status `insufficient_evidence` in phase 2.

### 4.4 Claim kinds

Give each claim one kind.

| Kind | Use for | Example |
| --- | --- | --- |
| `finding` | A result: something was observed, outperformed, improved, failed | Method A outperforms method B on dataset X. |
| `quantitative` | A finding whose point is a number | Method A reaches 91% accuracy on dataset X. |
| `method` | What a method is or how it works | Method A trains the encoder and decoder jointly. |
| `definition` | What a term means | A calibrated model is one whose confidence matches its accuracy. |
| `background` | General context attributed to sources | Transformer models are widely used for text classification. |

When a claim has a number and the number is the point, use `quantitative`.

### 4.5 Spans

Mark the span of the text unit each claim comes from. When a claim draws on
words from two places, mark the shortest span that covers both.

---

## 5. Phase 2: labelling

You now see the fixed list of claims. Label each claim, and each pair of a
claim and one of its sources, in this order:

1. Evidence spans, per pair.
2. Agreement label, per pair.
3. Scope flags, per pair.
4. Status, per claim.
5. Whether an expert would review, per claim.

Work through one pair completely before the next.

### 5.1 Evidence spans

Mark every passage in the source that bears on the claim, whether it supports
or contradicts it.

- Mark whole sentences, or a table cell or caption, not single words.
- Mark the smallest set of passages that a careful reader needs. Do not mark
  the whole abstract.
- Mark contradicting passages as well as supporting ones.
- If the source states the claim only as someone else's finding ("prior work
  has shown"), still mark it; the agreement label handles it (section 5.2).
- If nothing in the source bears on the claim, mark nothing.

### 5.2 Agreement label

One label per pair: how well this source supports the claim **as stated**.

| Label | Meaning |
| --- | --- |
| `entails` | The source states the claim, or the claim follows from it directly, with no step a careful reader would question. |
| `partial` | The source supports part of the claim, or a weaker or narrower version of it. |
| `neutral` | The source is on the topic but does not settle the claim either way. |
| `contradicts` | The source states the opposite, or a result that cannot be true at the same time as the claim. |
| `conflicting` | One passage of the source supports the claim and another contradicts it. |

Examples, all with the claim "Method A outperforms method B on dataset X":

| Source says | Label | Why |
| --- | --- | --- |
| A achieved 88.1 and B 85.4 accuracy on X. | `entails` | The comparison follows directly. |
| A outperformed B on the validation split of X; test results are not reported. | `partial` | Supported for one split only. |
| A outperformed B on X and on Y. | `entails` | The claim is narrower than the source; that is fine. |
| We evaluate A and B on X. | `neutral` | On topic, no result. |
| B outperformed A on X. | `contradicts` | Opposite result. |
| A outperformed B on X in the main experiment, but B was better under the corrected protocol in the appendix. | `conflicting` | Both appear in the same source. |

Borderline rules:

- **Prior work.** If the source reports the claim only as a finding of other
  papers, label `partial`, and note "attributed to prior work". The source
  repeats the claim but is not evidence for it.
- **Hedges.** "Our results suggest A may outperform B" against the claim "A
  outperforms B" is `entails` with the flag `certainty_escalation` (section
  5.3).
- **Negation.** Read negated and conditional sentences slowly. "A did not
  outperform B except on small subsets" does not support "A outperforms B".
- **Arithmetic.** A comparison you can compute from numbers in the source
  counts as following directly. A conclusion that needs assumptions the
  source does not state does not.
- **Rounding.** Numbers that agree after rounding to the precision of the
  claim are the same number: 88.14 in the source supports 88.1 in the claim.

### 5.3 Scope flags

Scope flags record the specific ways the claim goes beyond or differs from
the evidence. Compare these parts of the claim with the same parts of the
evidence: population or dataset, method, comparator, outcome or metric,
direction, magnitude, conditions, certainty wording, and study type.

Give flags on every pair labelled `entails`, `partial`, `contradicts` or
`conflicting`. A `neutral` pair gets no flags. Give every flag that applies.

| Flag | Give it when | Severity |
| --- | --- | --- |
| `direction_mismatch` | The claim and the evidence point in opposite directions: better against worse, increase against decrease. | critical |
| `causal_overreach` | The claim says one thing causes another, and the evidence shows only an association, or comes from an observational study. | critical |
| `magnitude_mismatch` | The claim's number differs from the evidence beyond rounding, or confuses a relative change with an absolute one. | critical |
| `overgeneralisation` | The claim covers a broader population, dataset, task or set of conditions than the evidence. | major |
| `metric_mismatch` | The claim names a different metric or outcome from the evidence, such as accuracy for F1. | major |
| `certainty_escalation` | The evidence is hedged ("suggests", "may", "preliminary") and the claim states it as fact. | minor |
| `missing_comparator` | The evidence compares against a baseline that the claim leaves out, so the claim reads as absolute. | minor |

Examples, each against the evidence "On dataset X, A reduced error from 10%
to 8% compared with B":

| Claim | Flags |
| --- | --- |
| A increases error compared with B on X. | `direction_mismatch` |
| A reduces error by 20% compared with B on X. | none: 10% to 8% is a 20% relative reduction, and the claim says relative |
| A reduces error by 20 percentage points compared with B on X. | `magnitude_mismatch` |
| A reduces error compared with B. | `overgeneralisation`: the dataset is dropped |
| A improves accuracy compared with B on X. | `metric_mismatch`, unless the source also reports accuracy |
| A reduces error on X. | `missing_comparator` |

How flags relate to the label. The label is your overall judgement; the flags
are the reasons. They should fit together:

| Flags present | Usual label |
| --- | --- |
| none, or minor only | `entails` |
| any major flag | `partial` |
| `direction_mismatch` or `magnitude_mismatch` | `contradicts` |
| `causal_overreach` | `partial`: the association is supported, the causal claim is not |

A critical flag on an `entails` or `partial` pair makes the claim's status
`insufficient_evidence` (section 5.4, rule 5).

If you choose a label that does not fit this table, explain why in the note.

### 5.4 Status

The status of a claim follows from the labels of all its pairs, by these
rules, applied in order:

1. The claim has no sources: `insufficient_evidence`.
2. Any pair is `conflicting`: `insufficient_evidence`.
3. At least one pair is `entails` or `partial`, and at least one other pair is
   `contradicts`: `insufficient_evidence`. The sources disagree.
4. Every pair that is not `neutral` is `entails`, and no pair has a major or
   critical flag: `verified`. `neutral` pairs are ignored here; the claim
   needs at least one `entails` pair.
5. At least one pair is `entails` or `partial` and has a critical flag:
   `insufficient_evidence`. RFC-001 (section 4) holds such a claim for a
   human review, and the reference is what a correct system outputs before
   that review.
6. At least one pair is `entails` or `partial`: `partially_supported`.
7. At least one pair is `contradicts`: `contradicted`.
8. Otherwise, every pair is `neutral`: `insufficient_evidence`.

| Status | Meaning |
| --- | --- |
| `verified` | The cited sources support the claim as stated. |
| `partially_supported` | They support part of it, or a narrower or weaker version. |
| `contradicted` | They state the opposite, or an incompatible result. |
| `insufficient_evidence` | They do not settle it, or they disagree with each other. |

Use the status the rules give. If you believe it is wrong for this claim, keep
it and explain in the note; the adjudicator reviews such notes, and repeated
cases lead to a change of the rules in the next guideline version.

`verified` means supported by the cited text you were shown. It does not mean
the claim is true.

### 5.5 Would an expert review this claim?

Answer yes if a careful domain expert, about to rely on this claim in a paper,
would want to read the source personally. Answer yes in particular when:

- your label was a close call between two values;
- the claim is consequential and the evidence is abstract-only;
- the source text is `degraded` and the claim depends on a number or table;
- the sources conflict;
- the claim is supported only as prior work.

Otherwise answer no.

---

## 6. Special situations

**Abstract only.** Label against the abstract as given. Do not assume the full
text says more. If the abstract is too short to settle the claim, the label is
`neutral`.

**Degraded text.** Label what the text says. If a number looks garbled (for
example "8 8.1" or a misplaced decimal point), do not correct it; label
`neutral` for that passage and note "possibly garbled".

**Tables and figures.** Table text counts as evidence when it is in the stored
text. A figure you cannot see does not.

**A claim that is true but not in the source.** Label what the source says,
usually `neutral`. Your knowledge that the claim is true does not count.

**A claim citing several sources.** Label each pair on its own. The status
rules combine them.

**Definitions and background.** These often get `neutral` because papers do
not state them directly. That is a correct label, not a failure.

**When you cannot decide.** There is no "unsure" label. Choose the best label,
answer yes to "would an expert review", and write why in the note. If you
believe the item itself is broken (wrong source attached, unreadable text),
mark it for the adjudicator instead of labelling it.

## 7. Notes

Every claim and pair has a free-text note. Use it for:

- any label that departs from the tables in section 5;
- anything you were unsure about;
- anything that looks wrong with the item.

Write notes in English, in one or two plain sentences. Notes are read by the
adjudicator and analysed to improve the guideline; they are not published
with your name.

## 8. What happens after you submit

1. Your labels are stored unchanged, next to the other annotator's.
2. Agreement between the two of you is computed before anyone discusses it.
3. Where you differ, the adjudicator sets the reference label and writes the
   reason. If the adjudicator cannot decide, the three of you discuss it.
4. A claim that stays disputed after that discussion is marked ambiguous. It
   stays in the set and is reported separately.

Disagreement is not a mark against you. Where experts differ is itself a
result of this work.

## 9. Calibration round

Before the main round, both annotators label the same 30 calibration items.
These items are not part of the released set.

1. Each of you labels them independently.
2. Agreement is computed.
3. The three of you discuss every disagreement.
4. The guideline is revised, and its version number goes up.
5. If agreement on any label is still low, the round is repeated with new
   items.

During calibration, discussing items is expected. After it, rule 3 of
section 2 applies again.

## 10. Practical points

- Record the time you spend on each item. This helps plan the main round; it
  is not used to judge you.
- Label in sessions of reasonable length and take breaks. Accuracy drops when
  you are tired.
- If the tool does something unexpected, stop and report it; do not work
  around it.

## 11. Quick reference

```text
Phase 1, per text unit
  list every factual claim: atomic, self-contained, faithful, with citations
  give each claim a kind and a span

Phase 2, per claim, for each of its sources
  1 mark evidence spans (support and contradiction)
  2 agreement label: entails | partial | neutral | contradicts | conflicting
  3 scope flags (not for neutral)
      critical: direction_mismatch, causal_overreach, magnitude_mismatch
      major:    overgeneralisation, metric_mismatch
      minor:    certainty_escalation, missing_comparator
then per claim
  4 status by the rules of 5.4
  5 would an expert review? yes when unsure, degraded, conflicting, abstract-only and consequential
always
  note anything you departed from or were unsure about
```

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-11-17 | First draft, from RFC-001 and RFC-002. |
| 0.1 | 2026-11-28 | Status rule 5 added: a critical flag on an `entails` or `partial` pair gives `insufficient_evidence`, as RFC-001 section 4 does. The draft gave `partially_supported`, which conflicted with RFC-001 (maintainer). |
