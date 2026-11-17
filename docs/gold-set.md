# Gold items, releases and the split

`utux.evalkit` holds the tooling around the gold-standard set of RFC-002. It
reads and checks gold items and splits a release into `dev` and `test`. It
never creates, infers or changes a reference label: those are made by people
only (RFC-002, section 5).

## A gold item

One gold item (`utux.evalkit.gold.GoldItem`) is one text unit with its
reference claims, the claim-source pairs, the reference labels, both
annotators' raw labels and, for a perturbed item, the hidden construction
record. The fields are those of RFC-002, section 4, plus `schema_version`,
which every file contract of utux carries.

| Field | Form |
| --- | --- |
| `schema_version` | `1` |
| `item_id` | `G` and at least four digits, for example `G0412` |
| `gold_version` | the release, `major.minor`, for example `1.0` |
| `split` | `dev` or `test` |
| `domain` | `ml` or `biomedicine` |
| `origin` | `natural`, `perturbed` or `system_generated` |
| `hard_case` | a code such as `abstract_vs_full_text`, or null |
| `text_unit` | non-empty text |
| `claims` | one or more claims |
| `annotation` | see below |
| `hidden` | the construction record; required for a perturbed item, null otherwise |

A claim has `claim_id` (the item id and `-c<n>`), `text`, `span` (start and
end in the text unit, the end greater than the start and not beyond the
text unit), `kind` (the five claim kinds of RFC-001), one or more `pairs`,
`status` and `expert_would_review` (true or false).

`status` is one of the four scientific statuses: `verified`,
`partially_supported`, `contradicted`, `insufficient_evidence`. `unverified`
is not a reference label and is rejected (RFC-002, section 3).

A pair has `pair_id` (the claim id and `-s<n>`), `source_id`,
`source_group`, `text_hash`, `checked_text`, `extraction_quality`,
`evidence_spans` (each a `passage_id` and increasing `offsets`, possibly
none), `agreement_label` (the four agreement labels or `conflicting`) and
`scope_flags` (distinct flags of the seven in RFC-001).

`annotation` has:

- `annotators`: exactly two distinct pseudonymous ids such as `a03`. A name
  is rejected, so that no personal data enters a release.
- `raw_labels`: for each annotator, and only for them, the
  `agreement_label` and `status` they gave, stored unchanged.
- `adjudicated` and `adjudicator`: an adjudicated item names its
  adjudicator, who is not one of the annotators; an item that was not
  adjudicated has none. When the two raw label sets differ, the item must be
  adjudicated.
- `ambiguous`: true for an item still disputed after joint discussion. It
  stays in the release and is excluded from the primary metrics (M0-13b).

`hidden` has `target_error` and `secondary_errors` (codes),
`error_class` (`single_error` or `multi_error`), `confirmed_by` (an
annotator id) and `source_item`, the natural item the perturbation was made
from, which is not the item itself.

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
| A perturbed item's origin is in the release | `unknown_source_item` |
| The origin is a natural item | `source_item_not_natural` |
| A perturbed item is in the split of its origin | `split_differs_from_origin` |
| A source has one source group throughout | `source_group_mismatch` |
| A source has one text hash throughout | `text_hash_mismatch` |
| No source group is in both splits | `source_group_in_both_splits` |

A source group in both splits is reported once, on the first pair, in
release order, whose item is in another split than the first item of the
group.

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
