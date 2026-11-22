# Annotation tooling

`utux.evalkit.annotation` and the `utux gold` commands (task M0-15a) are the
tooling for the item builder, the annotators and the adjudicator of the gold
set ([Gold items, releases and the split](gold-set.md), RFC-002, section 5).
They move labels between files, check them, and put the two annotators' work
side by side. **They never write, suggest or change a label**: every label in
their output was given by an annotator or by the adjudicator. Where the two
annotators agree and the adjudicator decided nothing, the reference value is
theirs, as `docs/gold-set.md` requires.

How the items themselves are built is in
[Building gold items](eval/item-building-guide.md).

## Keep the files away from the system

The batches, the work files, the adjudication files and the merged items
hold labels, including those of items that will be in the `test` split. Keep
them with the adjudicator, **outside the repository**. The agents and the
developers who tune prompts must not read them (RFC-002, section 6). Nothing
in utux reads them on its own; you pass each file to a command yourself.

## The steps

| Step | Who | Command | File |
| --- | --- | --- | --- |
| 1. Prepare the items | item builder | `utux gold pool-check` | `pool.json`, an `AnnotationPool` |
| 2. Give each annotator a batch | adjudicator | `utux gold batch --phase claim_extraction` | `batch-<batch>-<annotator>-claim_extraction.json` and `annotation_page.html` |
| 3. List the claims (phase 1) | annotator, in the page | | `work-…-claim_extraction.json`, an `ExtractionWork` |
| 4. Check each work, measure agreement | adjudicator | `utux gold import`, `utux gold agreement` | |
| 5. Merge the claim lists | adjudicator | `utux gold merge` | reference claims, and disagreements |
| 6. Decide the disagreements, merge again | adjudicator | `utux gold merge --adjudication` | `adjudication.json` |
| 7. Give each annotator a phase-2 batch | adjudicator | `utux gold batch --phase labelling --references` | |
| 8. Label (phase 2) | annotator, in the page | | `work-…-labelling.json`, a `LabellingWork` |
| 9. Check, measure agreement, merge, decide | adjudicator | `import`, `agreement`, `merge` | gold items, one per line |
| 10. Choose the split and freeze | adjudicator | `utux gold split-report`, `utux gold freeze` | the release |

Agreement is measured in steps 4 and 9, **before any adjudication** and
before anyone discusses the items (RFC-002, section 5). Every command prints
`--help`.

### 1. The pool

`pool.json` holds the release version and the items. Each item has the
fields of a gold item that are known before annotation: `item_id`, `domain`,
`origin`, `hard_case`, `text_unit`, its `sources`, and for a perturbed or
system-generated item its `hidden` record. Each source has `source_id`,
`source_group`, `checked_text`, `extraction_quality` and the stored `text`.

A **passage** is the unit an annotator marks as evidence. **Passages are not
given in the pool and not cut by hand**: they come from the shared splitter
([Passages](passages.md), ADR-0015), by the source's `checked_text`, so that
the passage ids of the reference labels are the ids the verifier uses. A
pool that gives passages of its own is refused (`unknown_key`). An evidence
span of a gold item is a passage's id and offsets, in code points, and the
pair's `text_hash` is the hash of the source's text, computed by the tooling.

```bash
uv run utux gold pool-check pool.json
```

### 2 and 7. Batches

```bash
uv run utux gold batch pool.json --phase claim_extraction --annotator a03 --batch-id b01 --out batches/
uv run utux gold batch pool.json --phase claim_extraction --annotator a07 --batch-id b01 --out batches/
```

Each command writes the batch and, beside it, `annotation_page.html`. A
batch holds what the annotator may see (guideline section 3): each item's id,
domain and text unit, and each source's text, passages, text type and
extraction quality. It records the version of the splitter its passages came
from (`splitter`). It holds **no hidden record, no origin and no hard
case**, which would tell the annotator how an item was made (guideline
section 2, rule 4), and no source group. It holds nothing of the other
annotator's work. A phase-2 batch also holds the reference claims, each with
its id, span, text, kind and citations; it is made with
`--references reference-claims.json`.

`batch_hash` binds the work to its batch: work made from another batch, or
by another annotator, is refused.

### 3 and 8. The page

`annotation_page.html` is one HTML file that works offline. Open it in a
browser, choose the batch file, work through the items, and press "Export
work" to save the work file. It makes no network request: its content
security policy blocks every one. The work is kept in the browser as a
draft until it is exported, and restored when the same batch is opened
again. Offsets are code points in every file; the page converts from and to
the browser's UTF-16 units ([Passages](passages.md)).

- **Phase 1**: mark a claim's span in the text unit, write the claim, choose
  its kind and the sources it cites.
- **Phase 2**: for each claim and each cited source, mark the passages that
  bear on the claim, choose the agreement label and the scope flags, then the
  claim's status and whether an expert would review it, in the guideline's
  order. Notes are free text.
- For each item: the minutes spent, and a box to mark the item broken for
  the adjudicator (wrong source, unreadable text) instead of labelling it
  (guideline section 6).

**No label is set when the page opens**: every choice starts empty, and the
page does not export while a label is missing, except for an item marked
broken. There is no page for the adjudicator in v0: adjudication files are
written by hand.

### 4 and 9. Checking a work file

```bash
uv run utux gold import batches/batch-b01-a03-claim_extraction.json work-b01-a03-claim_extraction.json
```

It reports every problem on its field, with its code:

| Problem | Code |
| --- | --- |
| Another phase, batch, batch hash or annotator | `differs_from_batch` |
| An item of the batch without work, one not in the batch, or one twice | `missing_item`, `unknown_item`, `duplicate_item` |
| A claim's span beyond the text unit | `span_out_of_range` |
| A citation that is not a source of the item, or one given twice | `unknown_source`, `duplicate_citation` |
| A reference claim, or a pair of one, without labels | `missing_claim`, `missing_pair` |
| A claim that is not a reference claim; a pair with a source the claim does not cite | `unknown_claim`, `unknown_source` |
| Evidence that is not a passage of the source, or a passage with other offsets | `unknown_passage`, `offsets_differ` |
| A scope flag given twice | `duplicate_flag` |
| A claim citing no source whose status is not `insufficient_evidence` | `raw_status_without_pairs` |

Labels outside the vocabularies of RFC-001 and RFC-002 are refused by the
schema (`enum`).

### 4 and 9. Agreement before adjudication

```bash
uv run utux gold agreement pool.json BATCH_A WORK_A BATCH_B WORK_B
uv run utux gold agreement pool.json BATCH_A WORK_A BATCH_B WORK_B --references reference-claims.json --json
```

It prints counts and measures only, never a label or an item. For claim
extraction: how many claims each annotator listed and how many match, as
`match_claims` defines it (RFC-002, section 7, S1). For labelling, the
measures of RFC-002, section 5: claim extraction again from the two raw
lists of the reference claims; raw agreement, the confusion table, Cohen's
kappa and Gwet's AC1 for status, the review flag, the agreement label and
each scope flag; and the overlap of evidence spans on the pool's texts. An
item either annotator marked broken is left out. In Python:
`extraction_agreement` and `labelling_agreement`.

### 5, 6 and 9. Merging

```bash
uv run utux gold merge pool.json BATCH_A WORK_A BATCH_B WORK_B \
    --out reference-claims.json --disagreements disagreements.json
uv run utux gold merge pool.json BATCH_A WORK_A BATCH_B WORK_B --references reference-claims.json \
    --adjudication adjudication.json --out items.jsonl --disagreements disagreements.json
```

**Claim extraction.** An item is settled when neither annotator marked it
broken and their lists are the same: the same span, text, kind and
citations, in any order. Its reference claims are that list, numbered
`<item>-c1`, `-c2`, … in the order of their spans, and both lists are kept as
the raw entries, each annotator's kind included. An item the adjudicator
decided takes the adjudicator's list, with `adjudicated` true and the
reason. Every other item is a disagreement, and no list is chosen.

**Labelling.** An item becomes a gold item when its every claim and pair is
settled: the reference value is the adjudicator's where there is a decision,
else the annotators' where they agree. Evidence spans and scope flags are
compared as sets. Both annotators' labels are the raw entries, unchanged.
Claims the adjudicator lists as `ambiguous` are marked so. Pairs are
`<claim>-s1`, … in the order of the claim's citations; their source group,
text type, extraction quality and text hash come from the pool. Each item is
checked as a gold item, and has **no split yet** (`split` is null).

A **disagreement** names the item, the level (`claim_extraction`, `claim`,
`pair`, or `flagged` for an item marked broken), the claim or pair, and each
annotator's value, notes included. Merge again with the adjudication file
until none is left.

### The adjudication file

```json
{"schema_version": 1, "phase": "labelling", "adjudicator": "a01",
 "extraction": [],
 "claims": [{"claim_id": "G0001-c1", "status": "partially_supported",
             "expert_would_review": true, "reason": "The source reports one dataset."}],
 "pairs": [{"pair_id": "G0001-c1-s1", "evidence_spans": [{"passage_id": "p2", "offsets": [20, 43]}],
            "agreement_label": "partial", "scope_flags": ["overgeneralisation"],
            "reason": "The source reports one dataset."}],
 "ambiguous": ["G0001-c2"]}
```

In phase 1, `extraction` gives an item's reference claims (`span`, `text`,
`kind`, `citations`) with a reason. Every decision needs a reason. The
adjudicator may decide where the annotators agree, too. An item has one
adjudicator across both phases.

### 10. The split and the freeze

A gold item's split is null until the release is frozen. The split is chosen
from the labelled items, by comparing the strata of the two splits under a
seed, before any system output is scored (RFC-002, sections 1 and 6):

```bash
uv run utux gold split-report items.jsonl --seed 17
uv run utux gold freeze items.jsonl --seed 17 --out gold-v0.1.jsonl
```

`freeze` checks the release rules of `check_release` first, sets every
item's split from the seed (`assign_splits`, dev share 0.3 by default), checks
again, and writes the release once: it never writes over an existing file.
It prints every departure from the guideline, the split sizes and the
release's content hash. Record the version, the hash, the splitter version
of the batches and a changelog with the release, and give the `test` split to the adjudicator to hold outside the
repository (M0-15).

## Importing public datasets (proposed)

Task M0-15b. `utux gold import-public` maps a downloaded public dataset into
`public_item` files by fixed rules. It renames each dataset's own label and
writes, suggests or changes none. It follows [the gold v0
strategy](eval/gold-v0-strategy.md), which is Proposed: its items are not a
gold release.

```bash
uv run utux gold import-public scifact ~/utux-data/gold/scifact --out ~/utux-data/gold/items/scifact.jsonl
uv run utux gold import-public sciclaimeval ~/utux-data/gold/sciclaimeval --out ~/utux-data/gold/items/sciclaimeval.jsonl
```

- **Input.** The directory holds the release as downloaded
  ([datasets.md](eval/datasets.md)).
- **Splits.** Only splits with published labels are read: SciFact's `train`
  and `dev`, and SciClaimEval's `dev`. SciFact's `claims_test.jsonl` is never
  opened.
- **Output.** The output file is refused inside any git work tree, so dataset
  text cannot be committed by accident.
- **What it prints.** The number of items, then counts only: by split, status,
  pair label, drop reason, licence and domain. It never prints a claim or a
  text.

## Schemas

The JSON Schemas of the six files (`annotation_pool`, `annotation_batch`,
`extraction_work`, `labelling_work`, `adjudication`, `reference_claims`) are
exported by `utux schema export`.
