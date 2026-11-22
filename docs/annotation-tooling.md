# Annotation tooling

`utux.evalkit.annotation` (task M0-15a) is the tooling for the annotators and
the adjudicator of the gold set ([Gold items, releases and the split](gold-set.md),
RFC-002, section 5). It moves labels between files, checks them, and puts the
two annotators' work side by side. **It never writes, suggests or changes a
label**: every label in its output was given by an annotator or by the
adjudicator. Where the two annotators agree and the adjudicator decided
nothing, the reference value is theirs, as `docs/gold-set.md` requires.

## Keep the files away from the system

The batches, the work files, the adjudication files and the merged items
hold labels, including those of items that will be in the `test` split. Keep
them with the adjudicator, **outside the repository**. The agents and the
developers who tune prompts must not read them (RFC-002, section 6). Nothing
in utux reads them; you pass each file to the tooling yourself.

## The steps

| Step | Who | File | Contract |
| --- | --- | --- | --- |
| 1. Prepare the items | maintainer | `pool.json` | `AnnotationPool` |
| 2. Give each annotator a batch | maintainer | `batch-<batch>-<annotator>.json` | `AnnotationBatch`, from `export_batch` |
| 3. List the claims (phase 1) | annotator, in the page | `work-…-claim_extraction.json` | `ExtractionWork` |
| 4. Merge the claim lists | adjudicator | reference claims, and disagreements | `ReferenceClaims`, from `merge_extraction` |
| 5. Decide the disagreements | adjudicator | `adjudication-…json` | `Adjudication` |
| 6. Give each annotator a phase-2 batch | maintainer | batch with the reference claims | `AnnotationBatch` |
| 7. Label (phase 2) | annotator, in the page | `work-…-labelling.json` | `LabellingWork` |
| 8. Merge the labels | adjudicator | gold items, and disagreements | `GoldItem`, from `merge_labelling` |
| 9. Decide, merge again, split | adjudicator | the release | `with_splits` |

Steps 4 and 5, and 8 and 9, repeat until nothing is left to decide: a merge
with the adjudication file settles what it decides and lists the rest.

### 1. The pool

`pool.json` holds the release version and the items. Each item has the
fields of a gold item that are known before annotation: `item_id`, `domain`,
`origin`, `hard_case`, `text_unit`, its `sources`, and for a perturbed or
system-generated item its `hidden` record. Each source has `source_id`,
`source_group`, `checked_text`, `extraction_quality`, the stored `text`, and
its `passages`.

A **passage** is the unit an annotator marks as evidence: a `passage_id` and
the `offsets` of its characters in the source's text. Passages are distinct,
within the text and do not overlap (`duplicate_passage`, `span_out_of_range`,
`passages_overlap`). Cut them at sentences, or a table cell or caption, as
the guideline asks annotators to mark (section 5.1). An evidence span of a
gold item is a passage's id and offsets, and the pair's `text_hash` is the
hash of the source's text, computed by the tooling.

### 2. Batches

```python
from pathlib import Path
from utux.evalkit.annotation import Phase, export_batch, load_pool, write_annotation_page

pool = load_pool(Path("pool.json"))
for annotator in ("a03", "a07"):
    batch = export_batch(pool, Phase.CLAIM_EXTRACTION, annotator, "b01")
    Path(f"batch-b01-{annotator}.json").write_text(batch.to_json(), encoding="utf-8")
write_annotation_page(Path("."))
```

A batch holds what the annotator may see (guideline section 3): each item's
id, domain and text unit, and each source's text, passages, text type and
extraction quality. It holds **no hidden record, no origin and no hard
case**, which would tell the annotator how an item was made (guideline
section 2, rule 4), and no source group. It holds nothing of the other
annotator's work. A phase-2 batch also holds the reference claims, each with
its id, span, text, kind and citations.

`batch_hash` binds the work to its batch: work made from another batch, or
by another annotator, is refused.

### 3 and 7. The page

`annotation_page.html` is one HTML file that works offline. Open it in a
browser, choose the batch file, work through the items, and press "Export
work" to save the work file. It makes no network request: its content
security policy blocks every one. The work is kept in the browser as a
draft until it is exported, and restored when the same batch is opened
again.

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
broken.

### Reading the work back

```python
from utux.evalkit.annotation import load_batch, read_work

work = read_work(load_batch(Path("batch-b01-a03.json")), Path("work-b01-a03-claim_extraction.json"))
```

`read_work` reports every problem on its field:

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

### 4 and 8. Merging

```python
from utux.evalkit.annotation import disagreements_json, merge_extraction

merged = merge_extraction(pool, work_a, work_b)  # later: ..., adjudication
Path("reference-claims.json").write_text(merged.references.to_json(), encoding="utf-8")
Path("disagreements.json").write_text(disagreements_json(merged.disagreements), encoding="utf-8")
```

**Claim extraction.** An item is settled when neither annotator marked it
broken and their lists are the same: the same span, text, kind and
citations, in any order. Its reference claims are that list, numbered
`<item>-c1`, `-c2`, … in the order of their spans, and both lists are kept
as the raw entries. An item the adjudicator decided takes the adjudicator's
list, with `adjudicated` true and the reason. Every other item is a
disagreement, and no list is chosen.

**Labelling.** `merge_labelling(pool, references, work_a, work_b, splits,
adjudication)` makes a gold item for each item whose every claim and pair is
settled: the reference value is the adjudicator's where there is a decision,
else the annotators' where they agree. Evidence spans and scope flags are
compared as sets. Both annotators' labels are the raw entries, unchanged.
Claims the adjudicator lists as `ambiguous` are marked so. Pairs are
`<claim>-s1`, … in the order of the claim's citations; their source group,
text type, extraction quality and text hash come from the pool. Each made
item is checked as a gold item.

A **disagreement** names the item, the level (`claim_extraction`, `claim`,
`pair`, or `flagged` for an item marked broken), the claim or pair, and each
annotator's value. The annotators' notes are included.

### 5. The adjudication file

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

### 9. The split

A gold item needs its split, but the split is chosen only once the items
exist: `assign_splits` and `split_report` read them
([Gold items, releases and the split](gold-set.md)). So merge with a
provisional split for every item, choose the seed from the report, then set
the chosen split:

```python
from utux.evalkit.annotation import with_splits
from utux.evalkit.gold import GoldSplit
from utux.evalkit.splits import assign_splits

merged = merge_labelling(
    pool,
    references,
    work_a,
    work_b,
    {item.item_id: GoldSplit.DEV for item in pool.items},
    adjudication,
)
release = with_splits(merged.items, assign_splits(merged.items, seed=SEED))
```

## What the tooling does not do yet

- **Agreement before adjudication.** `annotation_agreement` reads gold items,
  which exist only once every level is settled. Agreement over the two work
  files before adjudication is not computed yet.
- **The annotators' kinds are not kept.** The guideline asks each annotator
  for a claim's kind (section 4.4), and the merge compares them, but the gold
  item schema has no place for each annotator's kind: only the reference
  kind is stored.
- **A command line.** The tooling is called from Python, as above.
- **A page for the adjudicator.** Adjudication files are written by hand.

The JSON Schemas of the six files are exported by `utux schema export`.
