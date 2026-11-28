# Gold set v0 from public datasets

- Status: **Accepted**, 2026-11-22: the maintainer's decisions of the review of
  pull request #55 ([ADR-0018](../adr/0018-gold-v0-from-public-datasets.md)).
- RFC-002 is amended to match (sections 1 to 7 and its changelog).
- Task M0-15b. No perturbation has been built and no model has been called.

Each point the maintainer decided is ticked below with the decision.

## 1. Why

RFC-002 planned gold set v0 as about 150 claims labelled by two independent
annotators and adjudicated by a third (M0-15). No human annotators are
available. Gold set v0 is built instead from:

- **public datasets** whose labels were made by expert annotators, as items
  of origin `public`;
- **perturbations** of their items, whose labels follow from how they were
  made. These are built later.

No label is made, suggested or changed by utux or by a model. The import
renames each dataset's own label by a fixed table (section 3).

RFC-002 section 2 used to keep public datasets out of the set because their
label definitions differ from RFC-001. That difference still holds. It is
handled by the rules below, and the amended section 2 states them.

## 2. The datasets and their licences

| | SciFact | SciClaimEval |
| --- | --- | --- |
| What it is | Biomedical claims, each checked against the abstracts its citation cites; sentence-level rationales | Claims from ML, NLP and medical papers, each checked against a table or figure of the same paper |
| Labels | SUPPORT, CONTRADICT; NOINFO for a cited abstract with no rationale | Supported, Refuted |
| How Refuted/CONTRADICT was made | Written by annotators ([paper](https://arxiv.org/abs/2004.14974)) | The **evidence** was modified, not the claim ([paper](https://arxiv.org/abs/2602.07621)) |
| Splits with public labels, used | `train`, `dev` (`test` labels are not public) | `dev` (`test` labels are not public) |
| Role in v0 | Biomedicine; abstract-only evidence; multi-source claims; S2 spans from rationales | Mainly ML; tables; numeric claims; contradictions by construction |
| Files and hashes | [datasets.md](datasets.md) | [datasets.md](datasets.md) |

### Licence statements of the official sources

| Dataset | Statement | Source |
| --- | --- | --- |
| SciFact claims and rationales | CC BY 4.0 | [LICENSE.md](https://github.com/allenai/scifact/blob/master/LICENSE.md) |
| SciFact corpus abstracts | ODC-By 1.0, as part of S2ORC | the same file |
| SciFact, whole dataset | CC BY-NC 2.0 | [Hugging Face card of `allenai/scifact`](https://huggingface.co/datasets/allenai/scifact) |
| SciClaimEval, whole dataset | CC BY 4.0; "individual samples may have their own licenses" | [Hugging Face card](https://huggingface.co/datasets/alabnii/sciclaimeval-shared-task) |

- [x] **SciFact licence.** Treat SciFact as the most restrictive statement, CC BY-NC 2.0, until AllenAI clarifies; the issue text for the SciFact repository is in section 11. Abstracts are never redistributed: a public release carries only ids, labels and offsets (`provenance.text_redistributable` is false).
- [x] **SciClaimEval licences.** Keep only CC BY 4.0 and public-domain samples. NC and SA samples are dropped, counted as `licence_not_allowed`.
- [x] **NC data.** It is stored only on the maintainer's machine and used only for non-commercial research evaluation. This is revisited if utux is ever offered commercially.

## 3. The label mapping and evidence spans

`utux gold import-public` applies this table and nothing else
(`utux.evalkit.public`):

| Dataset label | Pair label | Claim status |
| --- | --- | --- |
| SUPPORT, Supported | `entails` | `verified` |
| CONTRADICT, Refuted | `contradicts` | `contradicted` |
| NOINFO: a cited SciFact abstract with no rationale | `neutral` | `insufficient_evidence` |

**A SciFact claim with several cited abstracts:**
- `verified` if some abstract supports it and none contradicts it;
- `contradicted` if some abstract contradicts it and none supports it;
- `insufficient_evidence` if no abstract has a rationale;
- dropped if one abstract supports it and another contradicts it.

**Evidence spans** come from `passages@1`:
- **SciFact.** Each rationale sentence becomes one span per passage it
  overlaps, with the sentence's offsets.
- **SciClaimEval.** The table is rendered as text: caption, header rows and
  rows, one paragraph each, cells joined by ` | `. Every passage is a span,
  because the dataset names the whole table, not cells.

**Known weaknesses:**
- neither dataset has `partial`, `partially_supported` or scope flags;
- SciFact's rationales are minimal sentences, not every passage a reader
  would accept;
- SciClaimEval's refuted items are paired with an altered table
  (`provenance.evidence_modified`).

- [x] **Label mapping** approved. S4 is not scored on imported items (`provenance.not_scored` holds `S4`). `partially_supported` comes only from perturbations.
- [x] **Evidence spans** approved. SciClaimEval items are excluded from S2 metrics (`not_scored` also holds `S2`).
- [x] **Domain mapping and table rendering** approved, for evaluation only: SciClaimEval's `nlp` and `ml` become `ml`, and `peerj` becomes `biomedicine`. Recorded in ADR-0018.

## 4. The drop rules

| Reason | When |
| --- | --- |
| `malformed_record` | A field is missing or of the wrong type, or a SciClaimEval id is not `val_tab_<n>` or `val_fig_<n>` |
| `unknown_label` | A label outside the table of section 3 |
| `no_cited_source` | A SciFact claim with neither cited abstracts nor evidence |
| `source_not_in_corpus` | A cited SciFact abstract that is not in the corpus |
| `rationale_sentence_missing` | A rationale sentence index outside the abstract |
| `mixed_labels_in_source` | One SciFact abstract with both SUPPORT and CONTRADICT rationales |
| `sources_disagree` | One abstract supports and another contradicts the claim |
| `evidence_figure` | SciClaimEval evidence that is a figure |
| `unknown_evidence_type` | Evidence that is neither a table nor a figure |
| `needs_full_paper` | SciClaimEval `use_context` "other sources" |
| `unknown_domain` | A SciClaimEval domain outside `ml`, `nlp`, `peerj` |
| `licence_not_allowed` | A SciClaimEval sample under a licence other than CC BY 4.0 or public domain |
| `table_missing` | No JSON table for the sample |
| `table_empty` | A JSON table with no rows |

A claim with `use_context` "yes" is kept, with its short context before it
in the text unit.

- [x] **Drop rules** approved, with `licence_not_allowed` added by decision 2.

## 5. What the converter produced

The run of 2026-11-22 is on the files of [datasets.md](datasets.md).

- **Output.** Gold items of origin `public` (RFC-002 section 4, option (a))
  in `items.jsonl`, and their source texts by hash in `sources/`. Both are
  outside the repository.
- **Checks.** `check_release` reports only `split_not_set` for all 1,461
  items; splits are set at the freeze.
- **Reproducibility.** Two runs gave byte-identical output:
  - SciFact `items.jsonl`, SHA-256
    `7ba8fa555d6fd7300e3cee5ad384331aea25a818b3f8295060b096bf967b6d4d`;
  - SciClaimEval `items.jsonl`, SHA-256
    `c5ee19d97d7d9e9e753bd4374cf429f0743988248b6f4828e47085d11d5d7cca`.

**SciFact:** 1,109 items, none dropped.
- 667 source groups and 667 abstracts.
- Licence CC BY-NC 2.0; texts not redistributable.

| Split | Items | `verified` | `contradicted` | `insufficient_evidence` | Pairs `entails` / `contradicts` / `neutral` |
| --- | --- | --- | --- | --- | --- |
| `train` | 809 | 332 | 173 | 304 | 370 / 194 / 355 |
| `dev` | 300 | 124 | 64 | 112 | 138 / 71 / 130 |

For 45 rationale sentences, `passages@1` cut differently from SciFact,
mostly after an initial; each gives one span per passage.

**SciClaimEval (`dev`):** 727 samples, 352 kept and 375 dropped.

| Kept | Count |
| --- | --- |
| `verified` (`entails`) | 181 |
| `contradicted` (`contradicts`), all on modified evidence | 171 |
| Domain `ml` | 288 |
| Domain `biomedicine` | 64 |
| CC BY 4.0 | 349 |
| Public domain | 3 |
| Source groups (papers) | 76 |
| Distinct table texts | 294 |

| Dropped | Count |
| --- | --- |
| `evidence_figure` | 258 |
| `needs_full_paper` | 77 |
| `licence_not_allowed` | 36 |
| `table_empty` | 4 |

## 6. Perturbations to build later

They are not built in M0-15b. Each takes a `verified` item and changes one
thing; the new label follows from the change, and the hidden record holds
the target error and the confirmation.

| Perturbation | Label by construction | Flag | Deterministic check | Confirmation |
| --- | --- | --- | --- | --- |
| Attach the claim to an abstract of the same corpus that it does not cite | `insufficient_evidence`, pair `neutral` | | The abstract is not cited and has no rationale for the claim | `deterministic` |
| Change a number so that it differs from every number of the evidence | `contradicted` | `magnitude_mismatch` | The new number appears nowhere in the source text | `deterministic` |
| Swap the metric or outcome | | `metric_mismatch` | The new metric is not in the source text | `deterministic` |
| Alter the title, first author or year of a real reference (citation existence) | per ADR-0016 | | The altered field differs (see the citation existence items below) | `deterministic` |
| Reverse the direction of the effect | `contradicted` | `direction_mismatch` | none | `model_check`, audited by sample |
| Remove a hedge (model-written, PR #59 review) | `verified` (minor flag) | `certainty_escalation` | A hedge of the fixed list is in the parent claim and absent from the perturbed claim | `model_check`, audited by sample |
| Turn a correlation into a causal statement | **on hold**, see below | `causal_overreach` | none | not built |
| Widen the population, dataset or conditions | `partially_supported` | `overgeneralisation` | none | `model_check`, audited by sample |
| Drop the comparator | | `missing_comparator` | none | `model_check`, audited by sample |

- [x] **Perturbations.**
  - Types with a deterministic check enter v0 directly.
  - Types without one (direction, causal, overgeneralisation, missing comparator) enter only if Gemini's check raises no disagreement, and they are sampled in the audit.
  - Each item records its confirmation: `deterministic`, `model_check` or `audit` (`hidden.confirmation`; `confirmed_by` names the person only for `audit`).

### Third review, 2026-11-28 (pull request #59)

- [x] **Hedge removal** moves to the model-written types, with a deterministic post-check. A hedge of a fixed list must be in the parent claim and absent from the perturbed claim, or the item is dropped and counted (`hedge_not_removed`). The list holds the adverbs (possibly, probably, potentially, perhaps, presumably, apparently, seemingly, conceivably, plausibly, arguably), the modal verbs (may, might, could) and the hedging verbs (suggests, suggest, suggested, appears to, appear to, appeared to, seems to, seem to, seemed to). A parent with no hedge is skipped before any call (`no_hedge`). No rule-made modal rewrites.
- [x] **Citation existence items** use the existing OpenAlex title search, with no new source. A SciFact title is accepted only when exactly one result has the identical normalised title; otherwise it is dropped and counted (`no_identical_title`, `ambiguous_title`, and `missing_author`, `missing_year`, `search_failed`). The command makes network calls and is the maintainer's to run (runbook). Each real reference gives a real item and one altered copy, title, first author and year in turn. The cited family name is the last word of the first author's display name, a construction rule only.
- [x] **The status rule for flag-only perturbations** follows RFC-001's flag severity table (RFC-001, S4) and its adjustment for scope flags (RFC-001, section 4):

  | Flag | RFC-001 severity | RFC-001 effect on an entailed claim | Status given here |
  | --- | --- | --- | --- |
  | `certainty_escalation` | Minor | No change to the status | `verified` |
  | `missing_comparator` | Minor | No change to the status | `verified` |
  | `metric_mismatch` | Major | `verified` is downgraded to `partially_supported` | `partially_supported` |
  | `overgeneralisation` | Major | `verified` is downgraded to `partially_supported` | `partially_supported` |
  | `causal_overreach` | Critical | `insufficient_evidence` until a human has reviewed the claim | **differs**: the guideline's rule gives `partially_supported` |

  These match exactly, except causal overreach. RFC-001 gives a claim with a critical flag `insufficient_evidence` until a human review, while the guideline's rule (section 5.4) gives `partially_supported`. As decided, the difference is reported, not decided: causal overreach is on hold and not built.

  Number change and direction reversal also carry critical flags. Their label, `contradicts` and `contradicted`, is the one the strategy and RFC-002 section 2 give them, not RFC-001's status for a system output, which waits for a human review. This is reported for the record.
- [x] **Thinking and the cap.**
  - Every Gemini request sets `thinking_level` `low` and `max_tokens` 2048. `gemini-3.8-flash` takes a thinking level, `low`, `medium` or `high`, and documents no numeric thinking budget. `max_output_tokens` "applies to the combined total of thinking tokens and output tokens" as "a hard cutoff" ([thinking](https://aistudio.google.com/docs/thinking), read 2026-11-28).
  - Before each call, its worst-case cost at the cap price is reserved against `--max-cost-usd`: the input bounded by its bytes, and 2048 output tokens. The call is refused if the reservation would pass the cap.
  - The runbook starts with a small run (`--per-type 2`).

## 7. Gemini's role

Gemini writes perturbations and flags disagreements:

1. **Writing perturbations.** It rewrites a claim to carry one given change.
   The label is the construction's, never Gemini's. An output that fails its
   deterministic check is discarded, never repaired by hand.
2. **Flagging disagreements.** It reads an item and says whether it disagrees
   with the item's label.
   - For a perturbation type without a deterministic check, a flag keeps the
     item out of v0.
   - Elsewhere, a flag sends the item to the audit or drops it.
   - A flag never changes a label.

Gemini never:
- sets or proposes a reference label;
- is the S3 or S5 model in a utux run scored on this set.

**Model.** `gemini-3.8-flash`, pinned.
- The current [models page](https://aistudio.google.com/docs/models) marks it
  "Stable", and stable codes "usually don't change".
- The Gemini 4 models (`gemini-4-carbon` and others) carry no Stable badge
  there, so they are not used.
- The page shows no "last updated" date. It was read on 2026-11-22, after
  `ai.google.dev/gemini-api/docs/models` redirected to it.

**API tier.** The paid tier of the Gemini API only (Paid Services).
- Under ["How Google Uses Your Data" for Paid Services](https://aistudio.google.com/docs/terms#data-use-paid),
  the Gemini API Additional Terms (effective March 23, 2026) say: "Google
  doesn't use your prompts ... or responses to improve our products". Prompts
  and responses are logged for a limited period, solely for detecting
  violations of the Prohibited Use Policy.
- The unpaid tier, including AI Studio and the free quota, is excluded: there,
  content is used to "improve, and develop Google products", and human
  reviewers may read it.
- Grounding with Google Search is not used: it stores prompts for 30 days on
  either tier.

- [x] **NC data to Gemini** (second review, 2026-11-22).
  - **Allowed:** for non-commercial research evaluation, on the paid tier named above.
  - **Licence:** a perturbation derived from a SciFact item carries its licence, CC BY-NC 2.0, and the same redistribution limit (`provenance.text_redistributable` false).
  - **The uncited-abstract perturbation** is built deterministically, with no model.
  - **Model-written perturbations** prefer ML items from SciClaimEval.

- [x] **Gemini's role** approved. One model version is pinned from Google's current documentation, and only an API tier whose terms say inputs are not used for training is used. Both are named above.

## 8. The audit

The maintainer labels 30 items blind:
- 20 perturbations of types without a deterministic check;
- 10 imported items.

They are sampled at random by a fixed seed. The existing tooling records the
labels (`utux gold batch`, the annotation page), and `utux gold agreement`
computes agreement with the reference labels before any discussion. The
audit does not change labels.

- [x] **Audit** approved: 30 items, 20 from perturbation types without a deterministic check and 10 imported. A Cohen's kappa below 0.6 triggers a review of the mapping.

## 9. Sizes and domain balance

**v0: about 300 claims.**
- About 150 SciFact items: 50 each of `verified`, `contradicted` and
  `insufficient_evidence`.
- About 100 SciClaimEval items, 50 `verified` and 50 `contradicted`, all
  ML (second review).
- About 50 perturbations.
- Drawn by a fixed seed and stratified by status and domain.

**Domain balance against RFC-002's 60% ML:**
- **Available after the import:** 288 of 1,461 items are ML, 19.7%, which is
  40.3 points below.
- **The v0 plan:** 288 ML SciClaimEval items are available, so all 100
  SciClaimEval items can be ML. Imported items are then 100 of 250 ML, 40%,
  20 points below.
- **Perturbations** are made from ML items wherever the type allows (second
  review), targeting about 50% ML:
  - if all 50 are made from ML items, v0 is 150 of 300 ML, 50%, which leaves
    a gap of 10 points from RFC-002's 60%;
  - the uncited-abstract perturbation can only be made from SciFact, which is
    biomedicine. Each one lowers the ML share by a third of a point; with 10
    of them, v0 is 140 of 300 ML, 46.7%, 13.3 points below.

The gap is reported with every result.

- [x] **Domain balance** (second review, 2026-11-22): all 100 SciClaimEval items in v0 are ML, and perturbations are made from ML items where the type allows, targeting about 50% ML. The remaining gap from RFC-002's 60% is at least 10 points, as above.
- [x] **The uncited-abstract perturbation** (third review, 2026-11-22): built from SciFact as planned, capped at 10 items. v0 at about 47% ML (140 of 300) is accepted for v0, and the gap of about 13 points from RFC-002's 60% is reported. Raising the ML share is a goal for v1, not a blocker.

- [x] **Sizes** approved: about 300 as proposed, favouring ML items in the SciClaimEval share; the domain balance and its gap from RFC-002's 60% ML are reported (above).

## 10. Contamination, splits and the item schema

**Contamination.**
- SciFact (2020) and SciClaimEval's `dev` labels are public, so any model may
  have seen them.
- Perturbed items are new text.
- Public items cannot be hidden from agents or developers, so the protection
  of `test` holds only for perturbations.

**Source groups.**
- SciFact: each cited abstract (`scifact-doc-<id>`). Claims that share an
  abstract share a group, and the group-aware split keeps them together.
- SciClaimEval: its paper (`sciclaimeval-paper-<paper_id>`). The converter
  now carries `paper_id`.

- [x] **Contamination.** Headline metrics are computed over all items, with per-origin results mandatory. The H3 thresholds must also hold on the perturbed subset.
- [x] **Item schema:** option (a), one gold item schema with a provenance block (RFC-002 section 4). A `public` item has `provenance`, `annotation` null, empty `raw` entries, no adjudication, and `kind` and `expert_would_review` null. A perturbation of it keeps the provenance.
- [x] **Source groups:** SciFact by cited abstract, SciClaimEval by `paper_id`, carried by the converter.

### Second review, 2026-11-22

- [x] **The locked protocol.** `docs/eval/protocol.md` is not edited. The rule that the H3 thresholds must also hold on the perturbed subset is listed under "Pending for v0.1" in RFC-002's changelog, to be applied at the v0.1 lock after the pilot.
- [x] **The release rule** that a perturbation may be made from a public item (`check_release`) is approved.

## 11. Issue text for the SciFact repository

For the maintainer to post at
[allenai/scifact issues](https://github.com/allenai/scifact/issues):

> **Title:** Which licence applies to the SciFact data: CC BY 4.0 (LICENSE.md) or CC BY-NC 2.0 (Hugging Face card)?
>
> Hello, and thank you for releasing SciFact.
>
> We would like to use SciFact's `claims_train.jsonl` and `claims_dev.jsonl`, with the abstracts of `corpus.jsonl`, as part of an evaluation set for an open-source (Apache-2.0) research tool. We found two licence statements that disagree:
>
> - [LICENSE.md](https://github.com/allenai/scifact/blob/master/LICENSE.md) in this repository says the claims and evidence annotations are under CC BY 4.0, and the corpus abstracts under ODC-By 1.0 as part of S2ORC.
> - The [Hugging Face card of `allenai/scifact`](https://huggingface.co/datasets/allenai/scifact) says the dataset is released under CC BY-NC 2.0.
>
> Could you say which statement applies to the release at `https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz`, and whether either statement should be updated? Until we hear from you, we treat the data as CC BY-NC 2.0, use it only for non-commercial research evaluation, and do not redistribute the abstracts.
>
> Thank you.
