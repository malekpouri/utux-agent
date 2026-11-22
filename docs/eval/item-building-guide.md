# Building gold items

Version 0.1, draft. Save as `docs/eval/item-building-guide.md`.

This guide is for the **item builder**: the person who chooses the citing
sentences and sources, stores the source text, and writes the perturbed
items of gold set v0. Annotators never read this guide. It follows RFC-002
sections 2 and 3 and is used with the gold tooling of M0-15a.

## 1. Roles and separation

- The item builder does not annotate the items they built. They have seen
  how each item was made, which is exactly what annotators must not know.
- Whoever writes a perturbation does not annotate that item.
- The maintainer, who tunes prompts, does not annotate any item (RFC-002
  section 5). The maintainer may be the item builder.
- Batches, work files, adjudication files and merged files contain labels
  of the future test split. Keep them with the adjudicator, outside the
  repository.

## 2. What v0 contains

The targets below are for v0 (about 150 claims). They are guides, not
quotas to force: a strained item is worse than a missing one.

| Dimension | Target for v0 |
| --- | --- |
| Domain | about 90 claims in machine learning, 60 in biomedicine |
| Origin | about half natural, half perturbed; no system-generated items in v0 |
| Reference status | at least 25 claims of each of the four statuses |
| Hard cases | at least 20 items across the seven hard-case groups |
| Evidence text | both abstract-only and full-text sources, where full text is available |
| Multi-source claims | at least 10 claims citing two sources, a few of them in conflict |

Natural items are mostly supported, so the other statuses come mainly from
perturbations. Plan the perturbations to fill the statuses and flags that
the natural items leave empty.

## 3. Choosing sources

A source is the cited paper whose text the claim is checked against.

- **Licence first.** Use only sources whose licence lets you store the text
  and, if the set is to be published, redistribute it: CC BY or CC0 are the
  safe choices. Many arXiv papers carry only arXiv's distribution licence,
  which does not grant redistribution; check each paper's licence on its
  page and record it. For PubMed Central, prefer papers in the open-access
  subset with a CC BY licence. When the licence permits storing but not
  redistributing, record that, and the public release carries only
  identifiers, labels and offsets.
- **Structured text only.** Take abstracts from the literature APIs and full
  text only where a structured version exists (for example PubMed Central
  XML). Do not copy text out of a PDF by hand: errors in the copy become
  errors in the reference. This is ADR-0014.
- **Record everything** in the source record: identifier (DOI, arXiv id or
  PMID), URL, licence, whether redistribution is allowed, retrieval date,
  the text's hash, and how it was obtained.
- **Variety.** Spread the sources over venues, years and groups. Do not take
  more than about five items from one source, and keep papers of one study
  in one source group (RFC-002 section 6).
- **Split into passages with the tool.** Passages come from the shared
  splitter (ADR-0015), never by hand, so reference passage ids match the
  system's.

## 4. Choosing citing sentences

A natural item is a sentence, or two or three adjacent sentences, from a
paper that cites the source, taken unchanged.

- **The citing paper's licence** matters too, since the sentence is quoted
  in the item. Prefer CC BY citing papers.
- **Finding citing sentences.** Some literature APIs can return the
  sentences in which other papers cite a given paper; check each service's
  current documentation and terms. Otherwise, read the related-work and
  discussion sections of open-access papers.
- **Good candidates** make a checkable claim about the cited source: a
  result, a comparison, a number, a method's property, a definition.
- **Avoid** sentences that cite a source only in passing ("as in [3]"),
  that cite more than three sources at once, or whose claim depends on
  figures or tables that the stored text does not contain.
- **Do not edit** a natural sentence, not even to fix grammar. A changed
  sentence is a perturbation.

## 5. Writing perturbations

A perturbed item is a copy of a natural item with exactly one intended
error. It stays in the same split as its natural item (the tooling enforces
this).

### 5.1 Rules

1. Start from a natural item whose claim the source supports.
2. Change as little as possible: one word, one number, one phrase.
3. Keep the sentence fluent and plausible. An error a reader spots at once
   tests nothing.
4. Record the **target error**, and any **secondary error** you expect the
   change to cause as well (RFC-002 section 2). Changing a number, for
   example, usually causes both `magnitude_mismatch` and a contradiction.
5. Never tell annotators, in any field they see, that an item is perturbed.

After blind annotation, the adjudicator confirms whether only the target
error is present (`single_error`) or more (`multi_error`). You do not set
that yourself.

### 5.2 Perturbation types

The types of RFC-002 section 2, with an invented example of each. Natural
claim for all rows, invented: "Method A reduced error from 10% to 8%
compared with method B on dataset X [1]."

| Type | Edit | Example | Target |
| --- | --- | --- | --- |
| Reverse the direction | the verb or comparison | "Method A increased error compared with method B on dataset X." | `direction_mismatch` |
| Causal overreach | association to cause | (from a claim of correlation) "Feature F causes the improvement." | `causal_overreach` |
| Change the number | one number | "...from 10% to 6%..." | `magnitude_mismatch` |
| Relative for absolute | the unit of change | "...reduced error by 20 percentage points..." | `magnitude_mismatch` |
| Widen the scope | drop or broaden a condition | "Method A reduces error compared with method B." | `overgeneralisation` |
| Swap the metric | the measured quantity | "Method A improved accuracy..." when only error is reported | `metric_mismatch` |
| Remove the hedge | from "suggests" to fact | (from a hedged source) "Method A outperforms method B." | `certainty_escalation` |
| Drop the comparator | the baseline | "Method A reduced error on dataset X." | `missing_comparator` |
| Wrong source | the citation | the same claim citing an unrelated paper on the same topic | `insufficient_evidence` |
| Opposite source | the citation | the same claim citing a paper that reports the opposite | `contradicted` |

The last two change the source, not the sentence: the item keeps the
original sentence and its citation points to another source record.

### 5.3 Hard cases

Hard cases are chosen, not made: they are natural or perturbed items that
fall into one of the seven groups of RFC-002 section 3. Tag the group in the
item's hidden record. Natural examples of "the abstract supports the claim,
the full text narrows it" and "the source states it as prior work" are
especially valuable; look for them while choosing sentences.

## 6. Workflow

1. Choose sources and record them (section 3).
2. Split each source into passages with the tool.
3. Write the natural items (section 4).
4. Plan the perturbations against the targets of section 2, then write them
   (section 5).
5. Build the item pool with the tooling of M0-15a, and check it.
6. Hand the pool to the adjudicator, who makes the annotator batches. From
   here on, the builder stays out of the labelling.

Record the time you spend per item and per perturbation; it helps plan v1.

## 7. Before handing over

- [ ] Every source has a licence, a retrieval date and a text hash.
- [ ] No natural sentence was edited.
- [ ] Every perturbed item has one target error and its expected secondary errors.
- [ ] No field an annotator sees reveals the origin, the hard case or the perturbation.
- [ ] The pool passes the tooling's checks.
- [ ] The targets of section 2 are met, or the gaps are listed.

## Changelog

| Version | Date | Change |
| --- | --- | --- |
| 0.1 | 2026-11-22 | First draft, from RFC-002 sections 2 and 3. |
