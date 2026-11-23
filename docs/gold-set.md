# Gold items, releases and the split

`utux.evalkit` holds the tooling around the gold-standard set of RFC-002. It
reads and checks gold items and splits a release into `dev` and `test`. The
tooling for annotators and the adjudicator, from batches to merged gold
items, is in [Annotation tooling](annotation-tooling.md). It
never creates, infers or changes a reference label: those are made by people
only (RFC-002, section 5).

## A gold item

One gold item (`utux.evalkit.gold.GoldItem`) is one text unit with its
reference claims, the claim-source pairs and the reference labels, as in
RFC-002, section 4. Annotation has two phases (RFC-002, section 5): each
annotator first lists the claims of the text unit, and then both label the
same reference claims. Each annotator's own entries are kept at every level.

| Field | Form |
| --- | --- |
| `schema_version` | `1` |
| `item_id` | `G` and at least four digits, for example `G0412` |
| `gold_version` | the release, `major.minor`, for example `1.0` |
| `split` | `dev` or `test`, or null until the release is frozen; `check_release` requires one (`split_not_set`) |
| `domain` | `ml` or `biomedicine` |
| `origin` | `natural`, `perturbed`, `system_generated` or `public` |
| `hard_case` | null, or one of `abstract_vs_full_text`, `number_wrong_context`, `conflict_within_source`, `true_but_not_in_source`, `attributed_prior_work`, `heavy_paraphrase`, `negation_or_hedge` (RFC-002, section 3) |
| `text_unit` | non-empty text |
| `claims` | one or more claims |
| `annotation` | see below; null for an item with `provenance` |
| `hidden` | see below |
| `provenance` | for a public item and a perturbation of one; see below. Absent otherwise |

### Claims and pairs

A claim has `claim_id` (the item id and `-c<n>`; `claim_id_mismatch`),
`text`, `span` (start and end in the text unit, the end greater than the
start and not beyond the text unit; `span_out_of_range`), `kind` (the five claim kinds of RFC-001), `pairs`, `status`,
`expert_would_review`, and:

- `raw`: for each annotator, and only for them, their `status`,
  `expert_would_review` and `note` (text or null), stored unchanged;
- `adjudicated`: whether the adjudicator set the claim's values, and
  `adjudication_reason`: the adjudicator's written reason, text when
  `adjudicated` is true and null otherwise;
- `ambiguous`: the claim remained disputed after joint discussion. It stays
  in the release and is excluded from the primary metrics (M0-13b); the
  other claims of its item are kept.

`status` is one of the four scientific statuses: `verified`,
`partially_supported`, `contradicted`, `insufficient_evidence`. `unverified`
is not a reference label and is rejected (RFC-002, section 3).

A claim has at least one pair, except a claim that cites no source: it has
no pairs, its status is `insufficient_evidence`, and both raw statuses are
`insufficient_evidence` too (`raw_status_without_pairs`).

A pair has `pair_id` (the claim id and `-s<n>`; `pair_id_mismatch`), `source_id`,
`source_group`, `text_hash`, `checked_text`, `extraction_quality`,
`evidence_spans` (each a `passage_id` and increasing `offsets`, possibly
none), `agreement_label` (the four agreement labels or `conflicting`),
`scope_flags` (distinct flags of the seven in RFC-001), and:

- `raw`: for each annotator, their `evidence_spans`, `agreement_label`,
  `scope_flags` and `note` (text or null), stored unchanged;
- `adjudicated` and `adjudication_reason`: as for a claim.

### Annotation

`annotation` has:

- `annotators`: exactly two distinct pseudonymous ids such as `a03`
  (`too_short`, `too_long`, `duplicate_annotator`). A name
  is rejected, so that no personal data enters a release.
- `adjudicator`: the adjudicator's id, who is not one of the annotators
  (`adjudicator_is_annotator`). It is required when anything in the item was
  adjudicated (`adjudicator_required`), and null otherwise
  (`adjudicator_not_allowed`).
- `claim_extraction`: `raw`, each annotator's own list of claims (`span`,
  within the text unit; `text`; `kind`, the annotator's kind of the claim;
  and `citations`, the distinct source ids the
  claim relies on, empty for a claim that cites no source; repeated:
  `duplicate_citation`), `adjudicated` and
  `adjudication_reason`.

### Raw entries and adjudication

At each level that has raw entries (claim extraction, each claim, each
pair):

- there is exactly one raw entry per annotator (`missing`,
  `unknown_annotator`);
- where the two raw entries differ, `adjudicated` is true at that level
  (`adjudication_required`);
- where they agree and nothing was adjudicated at that level, the reference
  value is theirs (`differs_from_raw`, on the field that differs). For claim
  extraction, the reference claims are then the agreed list.

Claim lists, evidence spans and scope flags are compared as sets, so their
order does not matter. Two listed claims are the same when span, text, kind
and citations (as a set) are the same; a reference claim's citations are the
sources of its pairs. Notes are not compared. Every level with `adjudicated`
true has an `adjudication_reason` (`adjudication_reason_required`), and every
other level has none (`adjudication_reason_not_allowed`).

A worked example of one item, from the item builder to the stored JSON, is
in [eval/example-item.md](eval/example-item.md). An adjudicated value may differ from both raw
entries, and `adjudicated` may be true where the raw entries agree.

### The hidden record

- A perturbed item has its construction record: `target_error` and
  `secondary_errors` (codes), `error_class` (`single_error` or
  `multi_error`), `confirmation` (`deterministic`, `model_check` or `audit`),
  `confirmed_by` (an annotator id for `audit`, null otherwise:
  `confirmed_by_required`, `confirmed_by_not_allowed`) and `source_item`, the
  natural or public item it was made from, which is not the item itself.
- A system-generated item has `{"generated_by": <code>}`, the code of the
  system and configuration that produced it, for example
  `utux-0.1.0-default`.
- A natural or public item has no `hidden` key at all; `"hidden": null` is
  rejected (`hidden_not_allowed`). A perturbed or system-generated item without its
  record gives `hidden_required`.

The hidden record is never shown to annotators or to the system.

### Public items and provenance

A `public` item comes from a public dataset with expert labels (RFC-002,
section 2; [gold v0 strategy](eval/gold-v0-strategy.md)). Instead of
annotators, it has a `provenance` block:

- `dataset`: `scifact` or `sciclaimeval`;
- `dataset_split`: `train` or `dev`;
- `original_id`: the dataset's own id;
- `licence`;
- `text_redistributable`: whether a release may carry the source texts;
- `evidence_modified`: whether the dataset's authors altered the evidence;
- `not_scored`: the steps whose metrics leave the item out, `S2` or `S4`.

An item with provenance:
- has `annotation` null (`annotation_not_allowed`);
- has empty `raw` entries (`raw_not_allowed`);
- has nothing adjudicated (`adjudication_not_allowed`);
- may have `kind` and `expert_would_review` null.

A public item without provenance gives `provenance_required`. An item of
another origin with provenance gives `provenance_not_allowed`, except a
perturbation of a public item. An item without provenance needs its
annotation (`annotation_required`), its kinds (`kind_required`) and its
review flags (`review_flag_required`). Agreement measures leave public items
out.

Problems are reported with the field and a code, as for every contract
(`docs/schema-conventions.md`). The JSON Schema of a gold item is exported as
`gold_item.schema.json` by `utux schema export`.

## A release

A release is a JSON Lines file with one item per line. `read_gold_release`
reads it and reports every invalid line, its field prefixed with the line
number, for example `line 3, split`. An empty line is an error
(`empty_line`).

`check_release` checks the rules across items. Each problem's field starts
with the id of the item to change:

| Rule | Code |
| --- | --- |
| Item ids are unique | `duplicate_item_id` |
| Every item has the version of the first item | `gold_version_mismatch` |
| Every item has a split; the split rules below hold among items that have one | `split_not_set` |
| A perturbed item's origin is in the release | `unknown_source_item` |
| The origin is a natural item | `source_item_not_natural` |
| A perturbed item is in the split of its origin | `split_differs_from_origin` |
| A source has one source group throughout | `source_group_mismatch` |
| A source has one text hash throughout | `text_hash_mismatch` |
| No source group is in both splits | `source_group_in_both_splits` |

A source group in both splits is reported once, on the first pair, in
release order, whose item is in another split than the first item of the
group.

### Departures from the guideline

`check_release` returns a `ReleaseCheck` with `problems` and `departures`.
A departure does not make the release invalid: it is reported for the
adjudicator, who may depart from a guideline rule with a written reason.

| Departure | Code |
| --- | --- |
| A `neutral` pair with scope flags (guideline section 5.3) | `flags_on_neutral_pair` |
| A claim status other than the one the guideline's rules give (section 5.4) | `status_differs_from_rules` |

`guideline_status(labels, flags)` applies the rules of guideline section 5.4
to a claim's pairs, in order: no sources, or a `conflicting` pair, or
support together with contradiction give `insufficient_evidence`; every
non-`neutral` pair `entails`, at least one, with no major or critical flag,
gives `verified`; then any support gives `partially_supported`, any
contradiction `contradicted`, and otherwise `insufficient_evidence`. It
checks labels made by people and never sets one.

## The split

`utux.evalkit.splits` splits by `source_group`, never item by item
(RFC-002, section 6).

`split_groups(items)` returns the sets of items that must share a split.
Two items are in one set when they cite a source of the same source group,
or when one is the origin of the other, directly or through a chain of
items. A perturbed item attached to a different paper than its origin is
kept with its origin through the origin link alone.

`assign_splits(items, dev_share=0.3, seed=...)` shuffles these sets with
`random.Random(seed)` and, in that order, puts a set in `dev` if it fits in
what is left of the target, `round(dev_share * number of items)`, and in
`test` otherwise. The same items and seed always give the same split. The
split stored in the items is ignored.

What the split does not do:

- It does not balance the strata of RFC-002, section 3 (status, scope flag,
  domain, evidence text, item source) between the splits.
- `dev` can fall short of the target when no remaining set fits; the result
  should be checked before it is used.

The split reads item ids, source groups and the origin link only. It never
reads or changes a label.

## The split report

`split_report(items)` counts, for each split, every value of each stratum
of RFC-002, section 3, with zero where a value does not occur, so the two
splits can be compared line by line:

| Stratum | Unit |
| --- | --- |
| Gold status | claim |
| Scope flag | pair |
| Domain | item |
| Evidence text (`abstract`, `full_text`) | pair |
| Item source | item |
| Hard case (`none` for null) | item |

It also gives the number of items in each split and the actual dev share.
`to_json()` returns it as one JSON object, and `lines()` as text:

```text
Items: dev 3, test 7. Dev share: 0.300
Gold status (per claim):
  verified: dev 2, test 3
  ...
```

The report reads labels only to count them. It holds no item id, text,
source or source group.

**Choosing a seed.** A seed for `assign_splits` is chosen from this report,
by comparing the strata of the two splits, before any system output has been
scored. The split is then fixed with the release; it is never changed in
response to system results (RFC-002, sections 1 and 6).
