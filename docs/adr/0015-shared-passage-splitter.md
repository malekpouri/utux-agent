# ADR-0015: One deterministic passage splitter, shared by the gold tooling and the verifier

- Status: Proposed
- Date: 2026-11-22

## Context

In evidence localisation, the source text is split into passages with stable
ids and character offsets; retrieval returns the top-k passages per source,
and every quote must be an exact substring of its stored passage after
whitespace normalisation (RFC-001, S2). The accepted default of k is 8 for
full text and all passages for an abstract (RFC-001, section 8). The
semantic-agreement step reads each candidate passage with one passage of
context on either side (RFC-001, S3).

The gold set scores S2 by the recall of the reference evidence spans in the
top-k (RFC-001, section 8; RFC-002, section 7). A reference span is a passage
id with its offsets (RFC-002, section 4). If the annotators' passages and the
verifier's passages were cut differently, a reference span could match no
system passage, and S2 could not be scored on equal terms. The gold tooling
of M0-15a already takes passages through its pool (`docs/annotation-tooling.md`).

## Decision

One deterministic function, `split_passages(text, kind)` in `utux.sources`,
splits a stored text into passages. The gold tooling and the verifier both
use it, so reference passages and system passages are the same and share
ids.

- **An abstract** (`kind` `abstract`) is split into sentences.
- **Full text** (`kind` `full_text`) is split into paragraphs at blank
  lines, then each paragraph into sentences. A passage never crosses a
  paragraph.
- **Offsets** are character offsets into the stored text, which is never
  changed: the text of a passage is exactly the slice at its offsets, with
  the whitespace around it left out.
- **A sentence ends** at `.`, `!` or `?` followed by whitespace and a capital
  letter, a digit or an opening bracket, except where the full stop belongs
  to an abbreviation from a fixed list (such as "e.g.", "i.e.", "Fig.",
  "Eq.", "et al."), to a decimal number, or to a citation in brackets.
- **An id** is made from the text hash and the passage's start offset, for
  example `p-3ee9b44b-005321`: the first eight hexadecimal digits of the
  text hash and the start offset. The same text always gives the same ids, on
  every platform, and a changed text gives new ids.
- The rules use no locale and no language model, and the abbreviation list
  is a constant, versioned with the splitter.

## Alternatives rejected

- **Passages cut by hand for gold items.** Reference passages would not be
  the verifier's, so S2 recall would measure the cut as well as the
  retrieval (`docs/eval/item-building-guide.md`, section 3).
- **Fixed-size windows of characters or tokens.** Deterministic and simple,
  but a window cuts sentences, so a quote can span two passages and the
  annotators' "whole sentences" (guideline, section 5.1) are lost.
- **A sentence splitter from an NLP library.** More accurate on hard cases,
  but a runtime dependency whose model or rules can change between versions,
  which would change passage ids under a frozen gold release.
- **Ids by position (`p001`, `p002`, …).** Readable, but the same id would
  name different passages of different texts, and nothing in the id would
  show that a text changed.

## Consequences

- The gold tooling's pool takes its passages from the splitter (M2-02), and
  gold passage ids come from it. Real gold items wait for M2-02
  (`docs/plan/M2.md`, "Order and dependencies").
- A change of the splitter's rules changes passage ids. It is a new splitter
  version, and a frozen gold release names the version its passages came
  from; a release is not re-split.
- Sentences are short. With sentence passages, k = 8 for full text is eight
  sentences, plus one of context on either side in S3. Whether that recall
  is enough is measured on the gold dev split (RFC-001, section 8).
- Offsets count Unicode code points, as Python's strings do. The offline
  annotation page, which runs in a browser that counts UTF-16 code units,
  converts between the two, so that a character outside the Basic
  Multilingual Plane does not shift the offsets.
- The splitter makes mistakes on hard text, such as an abbreviation missing
  from the list. They are deterministic and shared by the reference and the
  system, so they do not bias the scores, and each is fixed in a new
  version.

## Sources

- `docs/rfc/RFC-001.md`, section 3 (S2 and S3) and section 8 (k, and the
  gold annotation S2 needs).
- `docs/rfc/RFC-002.md`, section 4 (evidence spans) and section 7 (S2
  metrics).
- `docs/plan/M2.md`, M2-01 (the recommendation), M2-02 and M2-09;
  `docs/eval/item-building-guide.md`, section 3; `docs/annotation-tooling.md`.
