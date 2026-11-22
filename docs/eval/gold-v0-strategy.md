# Gold set v0 from public datasets

- Status: **Proposed**, 2026-11-22 (task M0-15b; [ADR-0018](../adr/0018-gold-v0-from-public-datasets.md))
- Nothing here is in force until the maintainer approves it. RFC-002 is not
  amended yet; section 9 lists the amendments this strategy would need.

Every point the maintainer must decide is a line that starts with
"MAINTAINER APPROVAL REQUIRED:" and an empty checkbox.

## 1. Why

RFC-002 plans gold set v0 as about 150 claims labelled by two independent
annotators and adjudicated by a third (RFC-002, sections 3 and 5; M0-15). No
human annotators are available. This strategy builds v0 instead from:

- **public datasets** whose labels were made by expert annotators;
- **perturbations** of their items, whose labels follow from how they were
  made (built later, not in M0-15b).

No label is made, suggested or changed by utux or by a model. The import
renames each dataset's own label by a fixed table (section 3).

**This conflicts with RFC-002 as accepted.** Section 2 says that public
datasets such as SciFact "serve as a secondary, external check" and that
"their labels are not merged into this set, because their label definitions
differ from RFC-001". That reason still holds and is discussed in section 3.
Section 9 says what would change.

## 2. The datasets and their roles

| | SciFact | SciClaimEval |
| --- | --- | --- |
| What it is | Biomedical claims, each checked against the abstracts its citation cites; sentence-level rationales | Claims from ML, NLP and medical papers, each checked against a table or figure of the same paper |
| Labels | SUPPORT, CONTRADICT; NOINFO for a cited abstract with no rationale | Supported, Refuted |
| How Refuted/CONTRADICT was made | Written by annotators ([paper](https://arxiv.org/abs/2004.14974)) | The **evidence** was modified (cells changed, rows or columns swapped, legends swapped), not the claim ([paper](https://arxiv.org/abs/2602.07621)) |
| Splits with public labels | `train`, `dev` (`test` labels are not public) | `dev` (`test` labels are not public) |
| Used | `train` and `dev` | `dev`, subtask 1 |
| Role in v0 | Biomedicine; abstract-only evidence; multi-source claims; S2 evidence spans from rationales | Mainly ML; full-text evidence (tables); numeric claims; contradictions by construction |
| Files and hashes | [datasets.md](datasets.md) | [datasets.md](datasets.md) |

Neither dataset was opened item by item while building this; the counts in
section 5 come from running the converter.

### Licences, as each official source states them

| Dataset | Statement | Source |
| --- | --- | --- |
| SciFact claims and rationales (`claims_*.jsonl`) | CC BY 4.0 | [LICENSE.md in the SciFact repository](https://github.com/allenai/scifact/blob/master/LICENSE.md) |
| SciFact corpus abstracts (`corpus.jsonl`) | ODC-By 1.0, as part of S2ORC | the same file |
| SciFact, whole dataset | CC BY-NC 2.0 | [Hugging Face card of `allenai/scifact`](https://huggingface.co/datasets/allenai/scifact), which links the same LICENSE.md |
| SciClaimEval, whole dataset | CC BY 4.0 | [Hugging Face card](https://huggingface.co/datasets/alabnii/sciclaimeval-shared-task) |
| SciClaimEval, each sample | its own licence: `license_name` and `license_url` of the sample | the same card ("individual samples may have their own licenses") and the [shared-task README](https://github.com/SciClaimEval/sciclaimeval-shared-task) |

Points the agent does not decide:

- **SciFact's two statements disagree:** CC BY 4.0 in the repository against
  CC BY-NC 2.0 on the Hugging Face card, both from AllenAI.
- **ODC-By covers the database, not each abstract.** Copyright in an abstract
  usually stays with its publisher.
- **SciClaimEval's kept items carry five licences:** 349 CC BY 4.0, 22 CC
  BY-NC-SA 4.0, 8 CC BY-SA 4.0, 6 CC BY-NC 4.0 and 3 public domain. RFC-002
  section 2 allows a public release to carry only identifiers, labels and
  offsets where redistribution is not permitted.

- [ ] MAINTAINER APPROVAL REQUIRED: which licence governs SciFact (CC BY 4.0 or CC BY-NC 2.0), and whether its abstracts may be stored and redistributed in a gold release.
- [ ] MAINTAINER APPROVAL REQUIRED: SciClaimEval's licence, and the per-sample licences of the tables kept.
- [ ] MAINTAINER APPROVAL REQUIRED: whether non-commercial (NC) and share-alike (SA) data may be used in the gold set of an Apache-2.0 project, and if so whether it is stored only on the maintainer's machine or released, and in what form.

## 3. The label mapping

`utux gold import-public` applies this table and nothing else
(`utux.evalkit.public`):

| Dataset label | Pair label | Claim status |
| --- | --- | --- |
| SUPPORT, Supported | `entails` | `verified` |
| CONTRADICT, Refuted | `contradicts` | `contradicted` |
| NOINFO: a cited SciFact abstract with no rationale | `neutral` | `insufficient_evidence` |

**SciFact claims with several cited abstracts.** A claim may cite several
abstracts. Its status is `verified` if some abstract supports it and none
contradicts it, and `contradicted` if some abstract contradicts it and none
supports it. It is `insufficient_evidence` if no abstract has a rationale.
If one abstract supports and another contradicts, the claim is dropped.

**Evidence spans** come from `passages@1` (ADR-0015):

- **SciFact.** The abstract is its sentences joined by single spaces. Each
  rationale sentence becomes one span per passage it overlaps, with the
  sentence's offsets. In 45 rationale sentences the splitter cut differently
  from SciFact, mostly after an initial; they give two spans.
- **SciClaimEval.** The table is rendered as text: caption, header rows and
  rows, one paragraph each, cells joined by ` | `. Its checked text is
  `full_text`. The dataset names the whole table as evidence, not cells, so
  every passage is a span.

Where the mapping is weaker than it looks:

- **No `partial` or `partially_supported`.** Neither dataset has them, so a
  claim that RFC-001 would call partially supported is mapped to `verified`.
  This is the difference in label definitions RFC-002 section 2 names.
- **No scope flags.** S4 cannot be scored on imported items until
  perturbations add the flags.
- **Rationales are not RFC-002 evidence spans.** SciFact's rationales are the
  minimal sentences that support or contradict. RFC-002 asks for every
  passage a careful reader would accept, so S2 recall against rationales
  is not the same measure.
- **Table spans make S2 recall trivial** for SciClaimEval: every passage is
  evidence.
- **SciClaimEval refutations change the evidence, not the claim.** The stored
  "source" of a refuted item is a table the dataset authors altered. It is
  marked `evidence_modified`, which is true for all 187 refuted items.
- **Domains.** SciClaimEval's `nlp` and `ml` map to `ml`, and `peerj`
  (medicine) maps to `biomedicine`.

- [ ] MAINTAINER APPROVAL REQUIRED: the label mapping above, including SUPPORT to `verified` despite the absence of `partially_supported`.
- [ ] MAINTAINER APPROVAL REQUIRED: the evidence-span rules: rationale sentences through `passages@1` for SciFact, and every passage of the rendered table for SciClaimEval.
- [ ] MAINTAINER APPROVAL REQUIRED: the domain mapping (`nlp` to `ml`, `peerj` to `biomedicine`), and rendering tables as text, given that ADR-0014 admits abstracts and structured full text only.

## 4. The drop rules

A record that does not map cleanly is dropped and counted by reason:

| Reason | When |
| --- | --- |
| `malformed_record` | A field is missing or of the wrong type, or a SciClaimEval id is not `val_tab_<n>` or `val_fig_<n>` |
| `unknown_label` | A label outside the table of section 3 |
| `no_cited_source` | A SciFact claim with neither cited abstracts nor evidence |
| `source_not_in_corpus` | A cited SciFact abstract that is not in the corpus |
| `rationale_sentence_missing` | A rationale sentence index outside the abstract |
| `mixed_labels_in_source` | One SciFact abstract with both SUPPORT and CONTRADICT rationales |
| `sources_disagree` | One abstract supports and another contradicts the claim |
| `evidence_figure` | SciClaimEval evidence that is a figure: utux checks text only |
| `unknown_evidence_type` | Evidence that is neither a table nor a figure |
| `needs_full_paper` | SciClaimEval `use_context` "other sources": the claim cannot be understood without the paper |
| `unknown_domain` | A SciClaimEval domain outside `ml`, `nlp`, `peerj` |
| `table_missing` | No JSON table for the sample |
| `table_empty` | A JSON table with no rows; the card names some tables left empty on purpose |

A SciClaimEval claim with `use_context` "yes" is kept. Its context, the
preceding sentences of its paragraph, is put before it in the text unit.

- [ ] MAINTAINER APPROVAL REQUIRED: the drop rules above, including keeping claims that need their short context and dropping those that need the full paper.

## 5. What the converter produced

Run on 2026-11-22 on the files of [datasets.md](datasets.md). Two runs gave
byte-identical outputs:

- SciFact: SHA-256 `ab2989ecababb524c8ada9084695314c8127ecff73c130760cceb18dd3bc5228`;
- SciClaimEval: SHA-256 `ce0a619d52c8b9eafa2802b36b1de0baf6809e5c808f1fdf68b76eb315563092`.

The outputs are outside the repository.

**SciFact:** 1,109 items, none dropped.

| Split | Items | `verified` | `contradicted` | `insufficient_evidence` | Pairs `entails` / `contradicts` / `neutral` |
| --- | --- | --- | --- | --- | --- |
| `train` | 809 | 332 | 173 | 304 | 370 / 194 / 355 |
| `dev` | 300 | 124 | 64 | 112 | 138 / 71 / 130 |

**SciClaimEval (`dev`):** 727 samples, 388 items kept and 339 dropped.

| Kept items | Count |
| --- | --- |
| `verified` (all `entails`) | 201 |
| `contradicted` (all `contradicts`) | 187 |
| Domain `ml` | 318 |
| Domain `biomedicine` | 70 |

| Dropped | Count |
| --- | --- |
| `evidence_figure` | 258 |
| `needs_full_paper` | 77 |
| `table_empty` | 4 |

**What this leaves:**

- no `partially_supported` from either dataset;
- no `insufficient_evidence` from SciClaimEval;
- domains of 79% biomedicine (1,179 items) and 21% ML (318 items), against
  RFC-002's 40% biomedicine and 60% ML.

## 6. Perturbations to build later

They are not built in M0-15b. Each takes an imported item whose label is
`verified` and changes one thing. The new label follows from the change.
Each is checked by a deterministic test where one exists, for example that a
number really changed, and its target error is recorded in the hidden record
(RFC-002, section 2).

| Perturbation | From | Label by construction | Flag | Deterministic check |
| --- | --- | --- | --- | --- |
| Attach the claim to an abstract of the same corpus that it does not cite | SciFact `verified` | `insufficient_evidence`, pair `neutral` | | The abstract is not cited and has no rationale for the claim |
| Change a number in the claim so that it differs from every number of the evidence | SciClaimEval or SciFact `verified` | `contradicted` | `magnitude_mismatch` | The new number appears nowhere in the source text |
| Reverse the direction of the effect | `verified` | `contradicted` | `direction_mismatch` | |
| Turn a correlation into a causal statement | `verified` | | `causal_overreach` | |
| Remove a hedge | `verified` | | `certainty_escalation` | The removed hedge word was in the claim |
| Widen the population, dataset or conditions | `verified` | `partially_supported` | `overgeneralisation` | |
| Swap the metric or outcome | `verified` | | `metric_mismatch` | The new metric is not in the source text |
| Drop the comparator | `verified` | | `missing_comparator` | |
| Real references with altered title, first author or year (citation existence) | SciFact corpus metadata | per ADR-0016 rule | | The altered field differs |

These are the types of RFC-002 section 2. Some labels are not certain by
construction alone: a widened claim may still be fully supported, and an
uncited abstract may still support the claim by chance. RFC-002 asks for a
human confirmation that only the target error is present (`single_error`).
Without annotators, that confirmation is the audit of section 8, or nothing.

- [ ] MAINTAINER APPROVAL REQUIRED: the perturbation types to build, and whether a perturbed item may enter v0 without the human confirmation of RFC-002 section 2.

## 7. Gemini's role

Gemini may be used for exactly two things:

1. **Writing perturbations** of section 6. It rewrites a claim to carry one
   given change. The label is the construction's, never Gemini's. An output
   that fails the deterministic check is discarded, never repaired by hand.
2. **Flagging disagreements.** It reads an imported or perturbed item and
   says whether it disagrees with the item's label. A flag sends the item to
   the maintainer's audit (section 8) or drops it. A flag never changes a
   label, and an item without a flag is not thereby confirmed.

Gemini never:

- sets or proposes a reference label;
- is the model of S3 (semantic agreement) or S5 (claim status) in any utux
  run scored on this set, so that the writer of the items is not their
  judge;
- sees the `test` split's labels in a run that is scored.

Sending dataset items to an external model is a data-policy and licence
question for NC items.

- [ ] MAINTAINER APPROVAL REQUIRED: Gemini's role as above, the Gemini model and version, and whether NC-licensed items may be sent to it.

## 8. The optional audit

The maintainer labels 30 items blind, sampled at random by a fixed seed and
stratified by dataset and status. The existing tooling records the labels
(`utux gold batch`, the annotation page). Agreement with the mapped labels is
computed with `utux gold agreement` before any discussion:

- raw agreement;
- Cohen's kappa;
- Gwet's AC1.

The audit does not change labels. A disagreement is recorded, and a
pattern of disagreement is a reason to revise the mapping or a drop rule.
Thirty items give a wide interval; the audit can show a gross mapping error,
not certify the set.

- [ ] MAINTAINER APPROVAL REQUIRED: whether the audit is done, its 30-item size and strata, and what agreement would lead to revising the mapping (proposed: RFC-002's floor, kappa below 0.6).

## 9. Contamination, splits and sizes

**Contamination.**
- SciFact was published in 2020 and is widely used for training and
  evaluating claim verification. SciClaimEval's `dev` labels have been public
  since 2026. Any model may have seen these items and their labels, so
  scores on imported items can be inflated.
- Perturbed items are new text and less exposed. Results are reported per
  dataset and per origin (imported, perturbed), as RFC-002 section 6 already
  asks for natural against perturbed items.
- A public item cannot be hidden from agents or developers. The protection
  of `test` in RFC-002 section 6 holds only for the perturbations, whose
  outputs can be kept off the repository.

**Splits.**
- SciFact's `train` and `dev` are not utux's `dev` and `test`. The utux
  split is made by source group (RFC-002, section 6): a SciFact cited
  abstract, or a SciClaimEval paper.
- The converter does not yet carry SciClaimEval's `paper_id` as a source
  group; that is a follow-up.

**Proposed sizes for v0:** about 300 claims.
- 150 SciFact items: 50 each of `verified`, `contradicted` and
  `insufficient_evidence`.
- 100 SciClaimEval items: 50 `verified`, 50 `contradicted`, licence
  permitting.
- About 50 perturbations, including the only `partially_supported` items.
- Drawn by a fixed seed, stratified by status and domain.
- RFC-002 plans about 150 claims for v0. More are proposed because the
  imported labels are cheaper and the audit is small.

- [ ] MAINTAINER APPROVAL REQUIRED: the target sizes and strata of v0, and the source groups for the split.
- [ ] MAINTAINER APPROVAL REQUIRED: how contamination is reported, and whether imported items count toward the headline metrics or only perturbed ones.

## 10. How RFC-002 must be amended

Not done in M0-15b. If this strategy is approved:

1. **Section 1:**
   - principle 1 holds: the labels are human, from the datasets' expert
     annotators;
   - principle 2 does not hold in the same form: the datasets' annotators
     were not blind to construction in the way RFC-002 requires.
2. **Section 2:**
   - replace "their labels are not merged into this set" with the rule of
     this strategy, its mapping table and the differences in definitions;
   - add `public` as an item origin beside `natural`, `perturbed` and
     `system_generated`;
   - add perturbations of public items, with a deterministic check per type.
3. **Section 3:**
   - v0 sizes and strata as approved;
   - state that v0 has no `partially_supported` except from perturbations.
4. **Section 4:** the item schema. Imported items have no utux annotators,
   so either:
   - (a) a provenance block replaces `annotation` and the per-annotator `raw`
     entries for `origin: public`, with dataset, split, original id, licence
     and `evidence_modified`; or
   - (b) the item stays the separate `public_item` schema of M0-15b and the
     metrics read both.
5. **Section 5:**
   - "Who annotates" and the agreement measures do not apply to imported
     labels. The datasets' own reported agreement is cited instead, and the
     optional audit of section 8 is described.
6. **Section 6:**
   - the split by source group for public items;
   - the limits of test-set protection for public data;
   - contamination reported per origin.

- [ ] MAINTAINER APPROVAL REQUIRED: the amendments of RFC-002 above, and the choice between (a) and (b) for the item schema.
