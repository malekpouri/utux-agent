# ADR-0014: Source text in M2: abstracts and structured full text only

- Status: Proposed
- Date: 2026-11-22

## Context

Citation support is checked against the stored text of each cited source in
`sources/` (RFC-001, S2). A matching quote shows that the words are in the
stored text, not that the stored text is a faithful copy of the paper, so
each source record holds the text hash, the source version, the retrieval
route, the extraction method and an extraction quality rating (RFC-001, S2).
The rating is `clean` for structured text from an API or publisher XML,
`good` for a PDF text layer that passes sanity checks, and `degraded` for OCR
or failed checks; degraded text is treated like abstract-only evidence
(RFC-001, S2). A claim checked against an abstract can be `verified`, with
confidence at most `medium` (RFC-001, section 7).

PDF text extraction is out of scope for M2 (`docs/plan/M2.md`). The literature
APIs of M2 return abstracts (`docs/spec.md`, section 6; `docs/plan/M2.md`,
M2-05), and some open-access sources offer structured full text, such as
PubMed Central XML. Gold items are checked against the text the annotators
read (RFC-002, section 4), and the item-building guide asks for structured
text only (`docs/eval/item-building-guide.md`, section 3).

## Decision

In M2, the stored text of a source is either its abstract, from a literature
API, or its full text where an open-access source gives it in a structured
form, for example PubMed Central XML. No text is extracted from a PDF in
M2. The extraction quality of both is `clean`, as RFC-001 defines it for
structured text from an API or publisher XML, and `checked_text` records
which of the two was used.

A source with neither is stored with metadata only, and its claims are
checked against nothing (`no_text`, RFC-001 S2; `docs/plan/M2.md`, M2-03).

## Alternatives rejected

- **PDF text extraction in M2.** It would bring the `good` and `degraded`
  ratings, a PDF library to assess, and errors in numbers and tables into the
  stored text, at a time when the gold set and the six steps are scored for
  the first time. RFC-001 already defines the ratings, so PDF extraction can
  be added later without changing the protocol.
- **Copying text out of a PDF by hand for gold items.** Errors in the copy
  would become errors in the reference labels
  (`docs/eval/item-building-guide.md`, section 3).
- **Abstracts only.** Simpler, but every verified claim would be capped at
  `medium` confidence, and the gold set could not score the hard case of an
  abstract that supports a claim the full text narrows (RFC-002, section 3).

## Consequences

- Most sources in M2 are abstract-only, so most verified claims have
  confidence at most `medium`, and `verification.md` states the limit
  (`docs/spec.md`, section 8).
- Full-text evidence comes mainly from the open-access biomedical
  literature. In machine learning, where most papers are on arXiv as PDFs,
  full text is rare in M2; the results are reported per evidence text so the
  difference is visible (RFC-002, section 3).
- The extraction method and tool version in each source record name the API
  or XML route, so a later PDF route can be told apart.
- The `good` and `degraded` ratings, and the human-review reason
  `degraded_source_text`, are not produced in M2. They stay in the schemas
  and the decision rules, tested with synthetic sources.

## Sources

- `docs/rfc/RFC-001.md`, section 3 (S2, including the extraction quality
  table) and section 7 (abstract-only evidence).
- `docs/rfc/RFC-002.md`, sections 3 and 4 (strata by evidence text; the text
  the annotators read).
- `docs/spec.md`, section 6 (literature sources) and section 8 (the
  abstract-only limitation in `verification.md`).
- `docs/plan/M2.md`, M2-01, M2-03 and M2-05; `docs/eval/item-building-guide.md`,
  section 3.
